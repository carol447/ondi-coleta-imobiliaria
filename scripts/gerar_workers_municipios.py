from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FONTE = ROOT / "codigos_municipios_regioes.csv"
WORKERS_ROOT = ROOT / "workers"
WORKER_IDS = ("worker1", "worker2", "worker3")


def ler_municipios() -> list[dict[str, str]]:
    with FONTE.open("r", encoding="cp1252", newline="") as arquivo:
        leitor = csv.DictReader(arquivo, delimiter=";")
        municipios = []
        for linha in leitor:
            cod_ibge = (linha.get("cod_ibge") or "").strip()
            municipio = (linha.get("municipio") or "").strip()
            if not cod_ibge.isdigit() or len(cod_ibge) != 7:
                continue
            if cod_ibge == "3500000" or not municipio or "Sem especificação" in municipio:
                continue
            municipios.append(linha)
        return sorted(municipios, key=lambda item: ((item.get("ra") or ""), item["municipio"]))


def distribuir(municipios: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    por_ra: dict[str, list[dict[str, str]]] = defaultdict(list)
    for municipio in municipios:
        por_ra[municipio.get("ra") or ""].append(municipio)

    workers = {worker_id: [] for worker_id in WORKER_IDS}
    for ra in sorted(por_ra):
        grupo = sorted(por_ra[ra], key=lambda item: item["municipio"])
        inicio = sum(ord(char) for char in ra) % len(WORKER_IDS)
        for indice, municipio in enumerate(grupo):
            ordem = [WORKER_IDS[(inicio + indice + deslocamento) % len(WORKER_IDS)] for deslocamento in range(len(WORKER_IDS))]
            worker_id = min(ordem, key=lambda candidato: len(workers[candidato]))
            workers[worker_id].append(municipio)
    return workers


def salvar(workers: dict[str, list[dict[str, str]]]) -> None:
    WORKERS_ROOT.mkdir(parents=True, exist_ok=True)
    campos = [
        "municipio",
        "estado",
        "url",
        "latitude",
        "longitude",
        "cod_ibge",
        "regiao_administrativa",
        "regiao_metropolitana",
        "drs",
    ]

    total = 0
    for worker_id in WORKER_IDS:
        worker_dir = WORKERS_ROOT / worker_id
        worker_dir.mkdir(parents=True, exist_ok=True)
        saida = worker_dir / "municipios.csv"
        linhas = []
        for item in sorted(workers[worker_id], key=lambda linha: ((linha.get("ra") or ""), linha["municipio"])):
            linhas.append(
                {
                    "municipio": item["municipio"].strip(),
                    "estado": "SP",
                    "url": "",
                    "latitude": "",
                    "longitude": "",
                    "cod_ibge": item["cod_ibge"].strip(),
                    "regiao_administrativa": (item.get("ra") or "").strip(),
                    "regiao_metropolitana": (item.get("rm") or "").strip(),
                    "drs": (item.get("drs") or "").strip(),
                }
            )

        with saida.open("w", encoding="utf-8-sig", newline="") as arquivo:
            escritor = csv.DictWriter(arquivo, fieldnames=campos, delimiter=";")
            escritor.writeheader()
            escritor.writerows(linhas)

        total += len(linhas)
        print(f"{worker_id}: {len(linhas)} municipios -> {saida}")

    print(f"Total distribuido: {total} municipios")


def main() -> None:
    municipios = ler_municipios()
    salvar(distribuir(municipios))


if __name__ == "__main__":
    main()
