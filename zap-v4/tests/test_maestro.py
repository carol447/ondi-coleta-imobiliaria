from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from maestro import MaestroFila, TIPOS_BUSCA_UNICA  # noqa: E402


class MaestroFilaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fila = MaestroFila(self.root / "fila.sqlite3", lease_segundos=60)
        self.municipios = self.root / "municipios.csv"
        self.tipos = self.root / "tipos.json"
        self.municipios.write_text(
            "municipio;uf;url;prioridade\nPresidente Prudente;SP;;10\nBauru;SP;;0\n",
            encoding="utf-8",
        )
        self.tipos.write_text(
            json.dumps([
                {"id": "apartamento_residencial", "rotulo": "Apartamento"},
                {"id": "casa_residencial", "rotulo": "Casa"},
            ]),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_importacao_idempotente_e_um_tipo_por_tarefa(self) -> None:
        primeira = self.fila.importar(self.municipios, self.tipos)
        segunda = self.fila.importar(self.municipios, self.tipos)
        self.assertEqual(primeira["criadas"], 4)
        self.assertEqual(segunda["criadas"], 0)
        self.assertEqual(self.fila.status()["total"], 4)

        tarefa = self.fila.proxima("worker1")["tarefa"]
        self.assertEqual(tarefa["municipio"], "Presidente Prudente")
        self.assertNotIn(",", tarefa["tipo_id"])

    def test_reserva_exclusiva_e_fim_da_fila(self) -> None:
        self.fila.importar(self.municipios, self.tipos)
        ids = []
        for indice in range(4):
            worker = f"worker{indice + 1}"
            tarefa = self.fila.proxima(worker)["tarefa"]
            ids.append(tarefa["id"])
            self.assertTrue(self.fila.concluir(tarefa["id"], worker, "CONCLUIDA", 1, "ok"))
        self.assertEqual(len(set(ids)), 4)
        self.assertTrue(self.fila.proxima("worker5")["fila_concluida"])

    def test_populacao_limite_e_filtros_da_busca_unica(self) -> None:
        from urllib.parse import urlsplit, parse_qs
        self.municipios.write_text(
            "municipio;uf;populacao\nPequeno;SP;99999\nLimite;SP;100000\nGrande;SP;100001\n",
            encoding="utf-8",
        )
        self.assertEqual(self.fila.importar(self.municipios, self.tipos)["criadas"], 5)
        self.assertEqual(self.fila.importar(self.municipios, self.tipos)["criadas"], 0)
        tarefa = self.fila.proxima("worker1")["tarefa"]
        self.assertEqual(tarefa["municipio"], "Pequeno")
        query = parse_qs(urlsplit(tarefa["url_base"]).query)
        self.assertEqual(query["tipos"], [",".join(TIPOS_BUSCA_UNICA)])
        self.assertIn("/venda/imoveis/sp+pequeno/", tarefa["url_base"])

    def test_workers_nao_reservam_mesma_cidade_ao_mesmo_tempo(self) -> None:
        self.fila.importar(self.municipios, self.tipos)
        primeira = self.fila.proxima("worker1")["tarefa"]
        segunda = self.fila.proxima("worker2")["tarefa"]
        self.assertNotEqual(primeira["municipio"], segunda["municipio"])
        self.assertTrue(self.fila.proxima("worker3")["aguardar"])
        self.assertEqual(self.fila.proxima("worker1")["tarefa"]["id"], primeira["id"])
        self.fila.concluir(primeira["id"], "worker1", "CONCLUIDA", 1)
        terceira = self.fila.proxima("worker3")["tarefa"]
        self.assertEqual(terceira["municipio"], primeira["municipio"])
        self.assertNotEqual(terceira["tipo_id"], primeira["tipo_id"])

    def test_avaliacao_total_limite_e_divisao(self) -> None:
        self.municipios.write_text("municipio;uf;estrategia\nPequeno;RJ;total_anuncios\nGrande;RJ;total_anuncios\n", encoding="utf-8")
        self.assertEqual(self.fila.importar(self.municipios, self.tipos)["criadas"], 2)
        um = self.fila.proxima("worker1")["tarefa"]
        self.assertFalse(self.fila.avaliar_total(um["id"], "worker1", 1500, self.tipos)["dividida"])
        self.assertEqual(self.fila.status()["total"], 2)
        dois = self.fila.proxima("worker2")["tarefa"]
        self.assertTrue(self.fila.avaliar_total(dois["id"], "worker2", 1501, self.tipos)["dividida"])
        self.assertEqual(self.fila.status()["total"], 4)
        self.assertEqual(self.fila.importar(self.municipios, self.tipos)["criadas"], 0)
        nova = self.fila.proxima("worker3")["tarefa"]
        self.assertEqual(nova["municipio"], "Grande")
        self.assertNotIn(",", nova["tipo_id"])
        with self.assertRaises(ValueError):
            self.fila.avaliar_total(nova["id"], "worker1", 100, self.tipos)

    def test_sequencia_so_inicia_es_depois_de_terminar_rj(self) -> None:
        self.municipios.write_text("municipio;uf;estrategia\nRio de Janeiro;RJ;total_anuncios\n", encoding="utf-8")
        es = self.root / "es.csv"
        es.write_text("municipio;uf;estrategia\nVitória;ES;total_anuncios\n", encoding="utf-8")
        self.fila.importar(self.municipios, self.tipos)
        rj = self.fila.proxima_com_sequencia("worker1", es, self.tipos)["tarefa"]
        self.assertEqual(rj["uf"], "RJ")
        self.assertTrue(self.fila.proxima_com_sequencia("worker2", es, self.tipos)["aguardar"])
        self.assertEqual(self.fila.status()["total"], 1)
        self.fila.concluir(rj["id"], "worker1", "CONCLUIDA", 1)
        tarefa_es = self.fila.proxima_com_sequencia("worker2", es, self.tipos)["tarefa"]
        self.assertEqual(tarefa_es["uf"], "ES")
        self.assertEqual(self.fila.uf_tarefa(tarefa_es["id"]), "ES")
        self.fila.concluir(tarefa_es["id"], "worker2", "SEM_ANUNCIOS", 1)
        self.assertTrue(self.fila.proxima_com_sequencia("worker3", es, self.tipos)["fila_concluida"])
        self.assertEqual(self.fila.status()["total"], 2)

    def test_sem_anuncios_e_pagina_inexistente_sao_finais(self) -> None:
        self.fila.importar(self.municipios, self.tipos)
        primeira = self.fila.proxima("worker1")["tarefa"]
        self.assertTrue(self.fila.concluir(primeira["id"], "worker1", "SEM_ANUNCIOS", 1, "sem resultado"))
        segunda = self.fila.proxima("worker1")["tarefa"]
        self.assertTrue(self.fila.concluir(segunda["id"], "worker1", "PAGINA_NAO_ENCONTRADA", 1, "404"))
        status = self.fila.status()["por_status"]
        self.assertEqual(status["SEM_ANUNCIOS"], 1)
        self.assertEqual(status["PAGINA_NAO_ENCONTRADA"], 1)

    def test_falha_tem_limite_e_nao_fica_em_loop_imediato(self) -> None:
        self.fila.importar(self.municipios, self.tipos)
        tarefa = self.fila.proxima("worker1")["tarefa"]
        resultado = self.fila.falhar(tarefa["id"], "worker1", 2, "erro temporário")
        self.assertEqual(resultado["status"], "PENDENTE")
        proxima = self.fila.proxima("worker1")["tarefa"]
        self.assertNotEqual(proxima["id"], tarefa["id"])


if __name__ == "__main__":
    unittest.main()
