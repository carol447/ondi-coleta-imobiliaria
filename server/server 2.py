from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request
from flask_cors import CORS

from excel_utils import gerar_excel_final

app = Flask(__name__)

CORS(
    app,
    resources={r"/*": {"origins": "*"}},
    methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Access-Control-Request-Private-Network"],
)


@app.after_request
def liberar_cors_private_network(resposta):
    origem = request.headers.get("Origin")

    if origem:
        resposta.headers["Access-Control-Allow-Origin"] = origem
        resposta.headers["Vary"] = "Origin"
    else:
        resposta.headers["Access-Control-Allow-Origin"] = "*"

    resposta.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resposta.headers["Access-Control-Allow-Headers"] = "Content-Type, Access-Control-Request-Private-Network"
    resposta.headers["Access-Control-Allow-Private-Network"] = "true"
    return resposta


def resposta_options():
    return ("", 204)


# =========================
# PASTAS DO PROJETO
# =========================
BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent

# Agora os dados da cidade ficam dentro da pasta da cidade, como no seu padrão por Estado/Município.
CIDADE_DIR = ROOT_DIR / "Estados" / "SP" / "mogi_das_cruzes"
DADOS_DIR = CIDADE_DIR / "dados"
BRUTO_DIR = DADOS_DIR / "bruto"

DADOS_DIR.mkdir(parents=True, exist_ok=True)
BRUTO_DIR.mkdir(parents=True, exist_ok=True)

ARQ_LISTA_CSV = DADOS_DIR / "urls_zap.csv"
ARQ_DETALHE_CSV = DADOS_DIR / "imoveis_zap_detalhes.csv"
ARQ_EXCEL_FINAL = DADOS_DIR / "dados_zap_mogi_das_cruzes.xlsx" 
ARQ_JSONL = BRUTO_DIR / "dados.json"

CAMPOS_LISTA = [
    "url",
    "preco",
    "metragem",
    "quartos",
    "localizacao",
    "descricao",
    "data_coleta",
    "hora_coleta",
]

CAMPOS_DETALHE = [
    "url",
    "preco",
    "metragem",
    "quartos",
    "anunciante",
    "localizacao",
    "descricao",
    "data_anuncio",
    "data_coleta",
    "hora_coleta",
]

urls_lista: set[str] = set()
urls_detalhe: set[str] = set()


def carregar_urls_existentes(caminho: Path) -> set[str]:
    if not caminho.exists():
        return set()

    urls: set[str] = set()
    with caminho.open("r", encoding="utf-8-sig", newline="") as arquivo:
        leitor = csv.DictReader(arquivo, delimiter=";")
        for linha in leitor:
            url = (linha.get("url") or "").strip()
            if url:
                urls.add(url)
    return urls


def preparar_csv(caminho: Path, campos: list[str]) -> None:
    if caminho.exists():
        return

    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8-sig", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=campos, delimiter=";")
        escritor.writeheader()


def normalizar_valor(valor: Any) -> str:
    if valor is None:
        return "N/A"
    texto = str(valor).replace("\u00a0", " ").strip()
    return texto if texto else "N/A"


def completar_data_hora(registro: dict[str, Any]) -> dict[str, str]:
    agora = datetime.now()
    registro.setdefault("data_coleta", agora.strftime("%Y-%m-%d"))
    registro.setdefault("hora_coleta", agora.strftime("%H:%M:%S"))
    return registro


def limpar_registro(registro: dict[str, Any], campos: list[str]) -> dict[str, str]:
    registro = completar_data_hora(dict(registro))
    return {campo: normalizar_valor(registro.get(campo, "N/A")) for campo in campos}


def salvar_csv(caminho: Path, campos: list[str], registro: dict[str, Any]) -> None:
    preparar_csv(caminho, campos)
    linha = limpar_registro(registro, campos)

    with caminho.open("a", encoding="utf-8-sig", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=campos, delimiter=";")
        escritor.writerow(linha)


def salvar_jsonl(tipo: str, payload: Any) -> None:
    bruto = {
        "tipo": tipo,
        "recebido_em": datetime.now().isoformat(timespec="seconds"),
        "payload": payload,
    }
    with ARQ_JSONL.open("a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(bruto, ensure_ascii=False) + "\n")


def exportar_excel() -> dict[str, int | str]:
    return gerar_excel_final(
        arquivo_lista_csv=ARQ_LISTA_CSV,
        arquivo_detalhe_csv=ARQ_DETALHE_CSV,
        arquivo_excel_final=ARQ_EXCEL_FINAL,
        campos_lista=CAMPOS_LISTA,
        campos_detalhe=CAMPOS_DETALHE,
    )


@app.before_request
def inicializar() -> None:
    global urls_lista, urls_detalhe

    preparar_csv(ARQ_LISTA_CSV, CAMPOS_LISTA)
    preparar_csv(ARQ_DETALHE_CSV, CAMPOS_DETALHE)

    if not urls_lista:
        urls_lista = carregar_urls_existentes(ARQ_LISTA_CSV)
    if not urls_detalhe:
        urls_detalhe = carregar_urls_existentes(ARQ_DETALHE_CSV)


@app.route("/", methods=["GET", "OPTIONS"])
def home():
    if request.method == "OPTIONS":
        return resposta_options()

    return jsonify(
        ok=True,
        mensagem="Servidor do zap Scraper rodando.",
        endpoints=["/dados-lista", "/dados-detalhe", "/exportar-excel", "/status"],
        pasta_cidade=str(CIDADE_DIR),
    )


@app.route("/status", methods=["GET", "OPTIONS"])
def status():
    if request.method == "OPTIONS":
        return resposta_options()

    return jsonify(
        ok=True,
        total_lista=len(urls_lista),
        total_detalhes=len(urls_detalhe),
        pasta_cidade=str(CIDADE_DIR),
        pasta_dados=str(DADOS_DIR),
        arquivo_lista=str(ARQ_LISTA_CSV),
        arquivo_detalhes=str(ARQ_DETALHE_CSV),
        arquivo_excel_final=str(ARQ_EXCEL_FINAL),
        arquivo_bruto=str(ARQ_JSONL),
    )


@app.route("/dados-lista", methods=["POST", "OPTIONS"])
def receber_lista():
    if request.method == "OPTIONS":
        return resposta_options()

    payload = request.get_json(silent=True) or {}
    itens = payload.get("itens", [])

    if isinstance(itens, dict):
        itens = [itens]
    if not isinstance(itens, list):
        return jsonify(ok=False, erro="Formato inválido. Envie {'itens': [...]}"), 400

    novos = 0
    repetidos = 0

    for item in itens:
        if not isinstance(item, dict):
            continue

        url = normalizar_valor(item.get("url"))
        if url == "N/A":
            continue

        if url in urls_lista:
            repetidos += 1
            continue

        salvar_csv(ARQ_LISTA_CSV, CAMPOS_LISTA, item)
        urls_lista.add(url)
        novos += 1

    salvar_jsonl("lista", payload)

    print(f"📄 Lista: {novos} novos, {repetidos} repetidos. Total lista: {len(urls_lista)}")
    print(f"📁 Salvando em: {DADOS_DIR}")

    return jsonify(
        ok=True,
        novos=novos,
        repetidos=repetidos,
        total_lista=len(urls_lista),
        pasta_dados=str(DADOS_DIR),
    )


@app.route("/dados-detalhe", methods=["POST", "OPTIONS"])
def receber_detalhe():
    if request.method == "OPTIONS":
        return resposta_options()

    item = request.get_json(silent=True) or {}

    if not isinstance(item, dict):
        return jsonify(ok=False, erro="Formato inválido."), 400

    url = normalizar_valor(item.get("url"))
    if url == "N/A":
        return jsonify(ok=False, erro="Registro sem URL."), 400

    if url in urls_detalhe:
        print(f"♻️ Detalhe repetido ignorado: {url}")
        return jsonify(
            ok=True,
            repetido=True,
            total_detalhes=len(urls_detalhe),
            pasta_dados=str(DADOS_DIR),
        )

    salvar_csv(ARQ_DETALHE_CSV, CAMPOS_DETALHE, item)
    salvar_jsonl("detalhe", item)
    urls_detalhe.add(url)

    print(f"🏠 Detalhe salvo ({len(urls_detalhe)}): {url}")
    print(f"📁 Salvando em: {DADOS_DIR}")

    return jsonify(
        ok=True,
        repetido=False,
        total_detalhes=len(urls_detalhe),
        pasta_dados=str(DADOS_DIR),
    )


@app.route("/exportar-excel", methods=["POST", "GET", "OPTIONS"])
def endpoint_exportar_excel():
    if request.method == "OPTIONS":
        return resposta_options()

    try:
        resultado = exportar_excel()
        print(f"📊 Excel final gerado: {resultado['arquivo_excel_final']}")
        return jsonify(ok=True, **resultado)
    except Exception as erro:
        print("❌ Erro ao gerar Excel:", erro)
        return jsonify(ok=False, erro=str(erro)), 500


if __name__ == "__main__":
    print("🚀 Servidor zap iniciado")
    print(f"📁 Dados da cidade: {DADOS_DIR}")
    print(f"📊 Excel final: {ARQ_EXCEL_FINAL}")
    app.run(host="127.0.0.1", port=5001, debug=False)
