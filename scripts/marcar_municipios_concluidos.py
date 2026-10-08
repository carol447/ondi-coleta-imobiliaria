from __future__ import annotations

import csv
import json
import unicodedata
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKERS_ROOT = ROOT / "workers"
WORKER_IDS = ("worker1", "worker2", "worker3")

MUNICIPIOS_JA_COLETADOS = {
    "bauru",
    "campinas",
    "carapicuiba",
    "diadema",
    "guarulhos",
    "jundiai",
    "maua",
    "mogi-das-cruzes",
    "osasco",
    "piracicaba",
    "praia-grande",
    "presidente-prudente",
    "ribeirao-preto",
    "santo-andre",
    "santos",
    "sao-bernardo-do-campo",
    "sao-jose-do-rio-preto",
    "sao-jose-dos-campos",
    "sao-paulo",
    "sorocaba",
}


def slugify(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(char for char in normalizado if not unicodedata.combining(char))
    slug = []
    anterior_hifen = False
    for char in sem_acento.lower():
        if char.isalnum():
            slug.append(char)
            anterior_hifen = False
        elif not anterior_hifen:
            slug.append("-")
            anterior_hifen = True
    return "".join(slug).strip("-")


def carregar_municipios(worker_id: str) -> list[str]:
    caminho = WORKERS_ROOT / worker_id / "municipios.csv"
    with caminho.open("r", encoding="utf-8-sig", newline="") as arquivo:
        leitor = csv.DictReader(arquivo, delimiter=";")
        return [(linha.get("municipio") or "").strip() for linha in leitor if linha.get("municipio")]


def carregar_checkpoint(worker_id: str) -> dict:
    caminho = WORKERS_ROOT / worker_id / "checkpoint.json"
    if not caminho.exists():
        return {
            "worker": worker_id,
            "rodando": False,
            "municipio_index": 0,
            "municipios_concluidos": [],
            "pagina_atual": 1,
            "detalhes_salvos": 0,
            "iniciado_em": None,
            "cidade_iniciada_em": None,
            "ultimo_status": "municipios ja coletados importados",
            "reloads": 0,
            "erros": 0,
            "bloqueado": False,
        }
    return json.loads(caminho.read_text(encoding="utf-8"))


def main() -> None:
    encontrados: dict[str, list[str]] = {}
    faltantes = set(MUNICIPIOS_JA_COLETADOS)

    for worker_id in WORKER_IDS:
        municipios = carregar_municipios(worker_id)
        por_slug = {slugify(municipio): municipio for municipio in municipios}
        concluidos_worker = []

        for slug in sorted(MUNICIPIOS_JA_COLETADOS):
            municipio = por_slug.get(slug)
            if municipio:
                concluidos_worker.append(municipio)
                faltantes.discard(slug)

        checkpoint = carregar_checkpoint(worker_id)
        existentes = checkpoint.setdefault("municipios_concluidos", [])
        for municipio in concluidos_worker:
            if municipio not in existentes:
                existentes.append(municipio)

        checkpoint["rodando"] = False
        checkpoint["pagina_atual"] = 1
        checkpoint["ultimo_status"] = "municipios ja coletados marcados como concluidos"
        checkpoint["atualizado_em"] = datetime.now().isoformat(timespec="seconds")

        saida = WORKERS_ROOT / worker_id / "checkpoint.json"
        saida.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")
        encontrados[worker_id] = concluidos_worker

    for worker_id, municipios in encontrados.items():
        print(f"{worker_id}: {len(municipios)} marcados")
        for municipio in municipios:
            print(f"  - {municipio}")

    if faltantes:
        print("Nao encontrados nos CSVs oficiais:")
        for slug in sorted(faltantes):
            print(f"  - {slug}")


if __name__ == "__main__":
    main()
