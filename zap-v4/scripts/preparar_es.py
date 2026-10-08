import argparse
import csv
import html
from pathlib import Path

parser = argparse.ArgumentParser(description="Prepara os municípios de ES sem usar população")
parser.add_argument("entrada", type=Path)
args = parser.parse_args()
texto = args.entrada.read_text(encoding="utf-8-sig")
rows = list(csv.reader(texto.splitlines()[1:], delimiter=","))
municipios = [{"municipio": html.unescape(r[0]).strip(), "uf": "ES", "estrategia": "total_anuncios"}
              for r in rows if len(r) > 1 and r[1].strip().isdigit() and len(r[1].strip()) == 7 and r[1].strip().startswith("32")]
if len(municipios) != 78 or len({r["municipio"] for r in municipios}) != 78:
    raise ValueError(f"Esperados 78 municípios únicos, encontrados {len(municipios)}")
saida = Path(__file__).resolve().parents[1] / "config" / "municipios_es.csv"
with saida.open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["municipio", "uf", "estrategia"], delimiter=";")
    writer.writeheader()
    writer.writerows(municipios)
print(f"{len(municipios)} municípios gravados em {saida}")
