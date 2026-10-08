"""Extrai municípios de SP e população 2022 da tabela fornecida pelo usuário."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import openpyxl


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("entrada", type=Path)
    parser.add_argument("--saida", type=Path, default=Path(__file__).resolve().parents[1] / "config" / "municipios.csv")
    args = parser.parse_args()
    workbook = openpyxl.load_workbook(args.entrada, read_only=True, data_only=True)
    try:
        linhas = []
        for row in workbook.active.values:
            codigo, municipio, _, _, populacao = (*row[:5],)
            if isinstance(codigo, (int, float)) and str(int(codigo)).startswith("35") and municipio:
                if not isinstance(populacao, (int, float)) or populacao < 0:
                    raise ValueError(f"População 2022 inválida: {municipio}")
                linhas.append({"municipio": municipio, "uf": "SP", "url": "", "prioridade": 0,
                               "populacao": int(populacao)})
        if len(linhas) != 645 or len({r["municipio"] for r in linhas}) != 645:
            raise ValueError(f"Esperados 645 municípios únicos de SP; encontrados {len(linhas)}")
        args.saida.parent.mkdir(parents=True, exist_ok=True)
        with args.saida.open("w", encoding="utf-8-sig", newline="") as arquivo:
            writer = csv.DictWriter(arquivo, fieldnames=["municipio", "uf", "url", "prioridade", "populacao"], delimiter=";")
            writer.writeheader()
            writer.writerows(sorted(linhas, key=lambda r: r["municipio"]))
        pequenos = sum(r["populacao"] < 100_000 for r in linhas)
        print(f"{len(linhas)} municípios: {pequenos} com busca única; {len(linhas)-pequenos} por tipo. Saída: {args.saida}")
    finally:
        workbook.close()


if __name__ == "__main__":
    main()
