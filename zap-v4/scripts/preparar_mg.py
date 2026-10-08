import argparse
import csv
import html
from pathlib import Path

parser = argparse.ArgumentParser(description="Prepara Minas Gerais para busca pelo total de anúncios")
parser.add_argument("entrada", type=Path)
args = parser.parse_args()
rows = list(csv.reader(args.entrada.read_text(encoding="utf-8-sig").splitlines()[1:]))
municipios = [{"municipio": html.unescape(r[0]).strip(), "uf": "MG", "estrategia": "total_anuncios"}
              for r in rows if len(r) > 1 and len(r[1].strip()) == 7 and r[1].strip().isdigit() and r[1].strip().startswith("31")]
if len(municipios) != 853 or len({r["municipio"] for r in municipios}) != 853:
    raise ValueError(f"Esperados 853 municípios únicos; encontrados {len(municipios)}")
saida = Path(__file__).resolve().parents[1] / "config" / "municipios_mg.csv"
with saida.open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["municipio", "uf", "estrategia"], delimiter=";")
    writer.writeheader()
    writer.writerows(municipios)
print(f"{len(municipios)} municípios gravados em {saida}")
