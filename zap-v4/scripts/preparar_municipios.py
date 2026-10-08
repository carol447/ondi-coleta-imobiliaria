from __future__ import annotations

import argparse
import csv
from pathlib import Path


def ler(path: Path) -> tuple[list[dict[str, str]], str]:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            texto = path.read_text(encoding=encoding)
            try:
                delimitador = csv.Sniffer().sniff(texto[:4096], delimiters=";,\t").delimiter
            except csv.Error:
                delimitador = ";"
            return list(csv.DictReader(texto.splitlines(), delimiter=delimitador)), encoding
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"Não foi possível ler {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Normaliza um CSV nacional de municípios para o maestro do ZAP v4.")
    parser.add_argument("entrada", type=Path)
    parser.add_argument("--saida", type=Path, default=Path(__file__).resolve().parents[1] / "config" / "municipios.csv")
    args = parser.parse_args()

    linhas, _ = ler(args.entrada)
    saida: list[dict[str, str]] = []
    vistos: set[tuple[str, str]] = set()
    for linha in linhas:
        municipio = str(linha.get("municipio") or linha.get("cidade") or "").strip()
        uf = str(linha.get("uf") or linha.get("estado") or "").strip().upper()
        if not municipio or len(uf) != 2 or (uf, municipio.casefold()) in vistos:
            continue
        vistos.add((uf, municipio.casefold()))
        saida.append({
            "municipio": municipio,
            "uf": uf,
            "url": str(linha.get("url") or linha.get("url_base") or "").strip(),
            "prioridade": str(linha.get("prioridade") or "0").strip() or "0",
            "populacao": str(linha.get("populacao") or "").strip(),
        })

    args.saida.parent.mkdir(parents=True, exist_ok=True)
    with args.saida.open("w", encoding="utf-8-sig", newline="") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=["municipio", "uf", "url", "prioridade", "populacao"], delimiter=";")
        writer.writeheader()
        writer.writerows(sorted(saida, key=lambda x: (x["uf"], x["municipio"])))
    print(f"{len(saida)} municípios gravados em {args.saida}")


if __name__ == "__main__":
    main()
