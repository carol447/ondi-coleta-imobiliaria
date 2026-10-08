from __future__ import annotations

import json
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path


TMP = tempfile.TemporaryDirectory()
ROOT = Path(TMP.name)
os.environ["ZAP_FILA_DB"] = str(ROOT / "fila.sqlite3")
os.environ["ZAP_DADOS_DIR"] = str(ROOT / "dados")
os.environ["ZAP_CHECKPOINTS_DIR"] = str(ROOT / "checkpoints")
SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

FLASK_DISPONIVEL = importlib.util.find_spec("flask") is not None
if FLASK_DISPONIVEL:
    import server  # noqa: E402


@unittest.skipUnless(FLASK_DISPONIVEL, "Flask não está instalado no runtime de testes")
class ServerApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.municipios = ROOT / "municipios.csv"
        cls.tipos = ROOT / "tipos.json"
        cls.municipios.write_text("municipio;uf\nPresidente Prudente;SP\nBauru;SP\n", encoding="utf-8")
        cls.tipos.write_text(json.dumps([{"id": "apartamento_residencial", "rotulo": "Apartamento"}]), encoding="utf-8")
        cls.client = server.app.test_client()

    @classmethod
    def tearDownClass(cls) -> None:
        TMP.cleanup()

    def test_fluxo_da_fila_por_http(self) -> None:
        preparar = self.client.post("/maestro/preparar", json={
            "municipios_csv": str(self.municipios), "tipos_json": str(self.tipos)
        })
        self.assertEqual(preparar.status_code, 200)
        self.assertEqual(preparar.json["fila"]["total"], 2)

        um = self.client.post("/worker/worker1/proxima-tarefa").json["tarefa"]
        dois = self.client.post("/worker/worker2/proxima-tarefa").json["tarefa"]
        self.assertNotEqual(um["id"], dois["id"])

        fim_um = self.client.post(f"/worker/worker1/tarefa/{um['id']}/concluir", json={
            "status": "SEM_ANUNCIOS", "pagina": 1, "detalhe": "mensagem oficial"
        })
        fim_dois = self.client.post(f"/worker/worker2/tarefa/{dois['id']}/concluir", json={
            "status": "PAGINA_NAO_ENCONTRADA", "pagina": 1, "detalhe": "404"
        })
        self.assertEqual(fim_um.status_code, 200)
        self.assertEqual(fim_dois.status_code, 200)
        self.assertTrue(self.client.post("/worker/worker3/proxima-tarefa").json["fila_concluida"])


if __name__ == "__main__":
    unittest.main()
