import csv
import argparse
from pathlib import Path

parser = argparse.ArgumentParser(description="Prepara RJ para avaliação pelo total de anúncios, sem usar população")
parser.add_argument("entrada", type=Path)
args = parser.parse_args()
rows = None
for encoding in ("utf-8-sig", "cp1252"):
    try:
        rows = list(csv.reader(args.entrada.read_text(encoding=encoding).splitlines(), delimiter=";"))
        break
    except UnicodeDecodeError:
        continue
municipios = [{"municipio": r[2].strip(), "uf": "RJ", "estrategia": "total_anuncios"}
              for r in rows if len(r) > 2 and r[0].strip() == "Município"]
if len(municipios) != 92 or len({r["municipio"] for r in municipios}) != 92:
    raise ValueError("Esperados 92 municípios únicos")
saida = Path(__file__).resolve().parents[1] / "config" / "municipios_rj.csv"
with saida.open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["municipio", "uf", "estrategia"], delimiter=";")
    writer.writeheader()
    writer.writerows(municipios)
print(f"{len(municipios)} municípios gravados em {saida}")
