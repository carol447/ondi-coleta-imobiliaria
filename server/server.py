from __future__ import annotations

import csv
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

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
    resposta.headers["Access-Control-Allow-Origin"] = origem or "*"
    if origem:
        resposta.headers["Vary"] = "Origin"
    resposta.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resposta.headers["Access-Control-Allow-Headers"] = "Content-Type, Access-Control-Request-Private-Network"
    resposta.headers["Access-Control-Allow-Private-Network"] = "true"
    return resposta


def resposta_options():
    return ("", 204)


BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
WORKERS_DIR = ROOT_DIR / "workers"
ESTADOS_DIR = ROOT_DIR / "Estados"
DEFAULT_ESTADO = "SP"
MAX_PAGINAS = 50
WORKER_IDS = ("worker1", "worker2", "worker3")
DEFAULT_TIPOS = (
    "apartamento_residencial,studio_residencial,kitnet_residencial,"
    "casa_residencial,condominio_residencial,casa-vila_residencial,"
    "cobertura_residencial,flat_residencial,loft_residencial,"
    "lote-terreno_residencial,sobrado_residencial"
)

CAMPOS_LISTA = [
    "worker",
    "municipio",
    "estado",
    "pagina",
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
    "worker",
    "municipio",
    "estado",
    "url",
    "tipo_imovel",
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

CAMPOS_SEM_IMOVEIS = ["worker", "municipio", "estado", "data", "hora", "motivo"]
CAMPOS_URL_INVALIDA = ["worker", "municipio", "estado", "data", "hora", "motivo", "url"]

urls_lista_por_worker: dict[str, set[str]] = {}
urls_detalhe_por_worker: dict[str, set[str]] = {}
loggers: dict[str, logging.Logger] = {}


def agora_data_hora() -> tuple[str, str]:
    agora = datetime.now()
    return agora.strftime("%Y-%m-%d"), agora.strftime("%H:%M:%S")


def normalizar_valor(valor: Any) -> str:
    if valor is None:
        return "N/A"
    texto = str(valor).replace("\u00a0", " ").strip()
    return texto if texto else "N/A"


def slugify(texto: str) -> str:
    mapa = str.maketrans(
        "áàãâäéèêëíìîïóòõôöúùûüçñÁÀÃÂÄÉÈÊËÍÌÎÏÓÒÕÔÖÚÙÛÜÇÑ",
        "aaaaaeeeeiiiiooooouuuucnAAAAAEEEEIIIIOOOOOUUUUCN",
    )
    limpo = texto.translate(mapa).lower()
    limpo = re.sub(r"[^a-z0-9]+", "-", limpo).strip("-")
    return limpo or "municipio"


def worker_id_recebido() -> str:
    payload = request.get_json(silent=True) if request.method in {"POST", "PUT", "PATCH"} else None
    candidato = (
        request.args.get("worker")
        or request.headers.get("X-Worker-Id")
        or (payload or {}).get("worker")
        or (payload or {}).get("worker_id")
        or "worker1"
    )
    return validar_worker_id(str(candidato))


def validar_worker_id(worker_id: str) -> str:
    worker_id = worker_id.strip().lower()
    if worker_id not in WORKER_IDS:
        raise ValueError(f"Worker invalido: {worker_id}. Use worker1, worker2 ou worker3.")
    return worker_id


def worker_dir(worker_id: str) -> Path:
    caminho = WORKERS_DIR / worker_id
    caminho.mkdir(parents=True, exist_ok=True)
    return caminho


def worker_csv(worker_id: str) -> Path:
    raiz = ROOT_DIR / f"{worker_id}.csv"
    if raiz.exists():
        return raiz
    return worker_dir(worker_id) / "municipios.csv"


def checkpoint_path(worker_id: str) -> Path:
    return worker_dir(worker_id) / "checkpoint.json"


def logger_worker(worker_id: str) -> logging.Logger:
    if worker_id in loggers:
        return loggers[worker_id]

    logger = logging.getLogger(worker_id)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.FileHandler(worker_dir(worker_id) / f"{worker_id}.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    loggers[worker_id] = logger
    return logger


def preparar_csv(caminho: Path, campos: list[str]) -> None:
    if caminho.exists():
        return
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8-sig", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=campos, delimiter=";")
        escritor.writeheader()


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


def completar_data_hora(registro: dict[str, Any]) -> dict[str, str]:
    data, hora = agora_data_hora()
    registro.setdefault("data_coleta", data)
    registro.setdefault("hora_coleta", hora)
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


def carregar_checkpoint(worker_id: str) -> dict[str, Any]:
    caminho = checkpoint_path(worker_id)
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
            "ultimo_status": "aguardando inicio",
            "reloads": 0,
            "erros": 0,
            "bloqueado": False,
        }
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger_worker(worker_id).exception("Checkpoint corrompido; criando novo estado.")
        return carregar_checkpoint_novo(worker_id)


def carregar_checkpoint_novo(worker_id: str) -> dict[str, Any]:
    caminho = checkpoint_path(worker_id)
    if caminho.exists():
        caminho.rename(caminho.with_suffix(f".corrompido-{int(time.time())}.json"))
    return carregar_checkpoint(worker_id)


def salvar_checkpoint(worker_id: str, estado: dict[str, Any]) -> dict[str, Any]:
    estado["worker"] = worker_id
    estado["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
    checkpoint_path(worker_id).write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
    return estado


def ler_municipios(worker_id: str) -> list[dict[str, str]]:
    caminho = worker_csv(worker_id)
    if not caminho.exists():
        criar_csv_exemplo(caminho)
        return []

    with caminho.open("r", encoding="utf-8-sig", newline="") as arquivo:
        amostra = arquivo.read(4096)
        arquivo.seek(0)
        delimitador = ";" if ";" in amostra else ","
        leitor = csv.DictReader(arquivo, delimiter=delimitador)
        municipios = []
        for linha in leitor:
            municipio = normalizar_valor(
                linha.get("municipio") or linha.get("cidade") or linha.get("nome")
            )
            if municipio == "N/A":
                continue
            estado = normalizar_valor(linha.get("estado") or linha.get("uf") or DEFAULT_ESTADO).upper()
            url = normalizar_valor(linha.get("url") or linha.get("url_zap") or "")
            latitude = normalizar_valor(linha.get("latitude") or linha.get("lat") or "")
            longitude = normalizar_valor(linha.get("longitude") or linha.get("lon") or linha.get("lng") or "")
            municipios.append(
                {
                    "municipio": municipio,
                    "estado": estado,
                    "url": "" if url == "N/A" else url,
                    "latitude": "" if latitude == "N/A" else latitude.replace(",", "."),
                    "longitude": "" if longitude == "N/A" else longitude.replace(",", "."),
                    "slug": slugify(municipio),
                }
            )
        return municipios


def criar_csv_exemplo(caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8-sig", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=["municipio", "estado", "url"], delimiter=";")
        escritor.writeheader()
        escritor.writerow({"municipio": "Presidente Prudente", "estado": "SP", "url": ""})


def gerar_url_municipio(municipio: str, estado: str, latitude: str = "", longitude: str = "") -> str:
    estado_slug = estado.lower()
    cidade_slug = slugify(municipio)
    estado_nome = "S\u00e3o Paulo" if estado.upper() == "SP" else estado
    estado_nome_ascii = "Sao Paulo" if estado.upper() == "SP" else slugify(estado_nome).replace("-", " ").title()
    coordenadas = ""
    if latitude and longitude:
        coordenadas = f"{latitude},{longitude},"
    onde = quote_plus(
        f",{estado_nome},{municipio},,,,,city,BR>{estado_nome_ascii}>NULL>{municipio},{coordenadas}",
        safe="",
    )
    tipos = quote_plus(DEFAULT_TIPOS, safe="")
    return (
        f"https://www.zapimoveis.com.br/venda/apartamentos/{estado_slug}+{cidade_slug}/"
        f"?onde={onde}&tipos={tipos}"
    )


def municipio_atual(worker_id: str) -> tuple[dict[str, Any] | None, dict[str, Any], list[dict[str, str]]]:
    estado = carregar_checkpoint(worker_id)
    municipios = ler_municipios(worker_id)
    concluidos = set(estado.get("municipios_concluidos") or [])

    indice = int(estado.get("municipio_index") or 0)
    while indice < len(municipios) and municipios[indice]["municipio"] in concluidos:
        indice += 1

    estado["municipio_index"] = indice
    salvar_checkpoint(worker_id, estado)
    if indice >= len(municipios):
        return None, estado, municipios

    municipio = dict(municipios[indice])
    municipio["url"] = municipio["url"] or gerar_url_municipio(
        municipio["municipio"],
        municipio["estado"],
        municipio.get("latitude", ""),
        municipio.get("longitude", ""),
    )
    return municipio, estado, municipios


def cidade_dados_dir(municipio: str, estado: str) -> Path:
    return ESTADOS_DIR / estado.upper() / slugify(municipio) / "dados"


def paths_saida(worker_id: str, municipio: str, estado: str) -> dict[str, Path]:
    dados = cidade_dados_dir(municipio, estado)
    bruto = dados / "bruto"
    return {
        "cidade": dados.parent,
        "dados": dados,
        "bruto": bruto,
        "lista": dados / f"urls_zap_{worker_id}.csv",
        "detalhe": dados / f"imoveis_zap_detalhes_{worker_id}.csv",
        "lista_legado": dados / "urls_zap.csv",
        "detalhe_legado": dados / "imoveis_zap_detalhes.csv",
        "excel": dados / f"dados_zap_{slugify(municipio)}_{worker_id}.xlsx",
        "jsonl": bruto / f"dados_{worker_id}.json",
    }


def salvar_jsonl(worker_id: str, tipo: str, payload: Any, municipio: str, estado: str) -> None:
    paths = paths_saida(worker_id, municipio, estado)
    paths["bruto"].mkdir(parents=True, exist_ok=True)
    bruto = {
        "worker": worker_id,
        "municipio": municipio,
        "estado": estado,
        "tipo": tipo,
        "recebido_em": datetime.now().isoformat(timespec="seconds"),
        "payload": payload,
    }
    with paths["jsonl"].open("a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(bruto, ensure_ascii=False) + "\n")


def inicializar_worker(worker_id: str, municipio: str, estado: str) -> dict[str, Path]:
    paths = paths_saida(worker_id, municipio, estado)
    paths["dados"].mkdir(parents=True, exist_ok=True)
    paths["bruto"].mkdir(parents=True, exist_ok=True)
    preparar_csv(paths["lista"], CAMPOS_LISTA)
    preparar_csv(paths["detalhe"], CAMPOS_DETALHE)

    cache_key = f"{worker_id}:{estado.upper()}:{slugify(municipio)}"
    if cache_key not in urls_lista_por_worker:
        urls_lista_por_worker[cache_key] = carregar_urls_existentes(paths["lista"]) | carregar_urls_existentes(paths["lista_legado"])
    if cache_key not in urls_detalhe_por_worker:
        urls_detalhe_por_worker[cache_key] = carregar_urls_existentes(paths["detalhe"]) | carregar_urls_existentes(paths["detalhe_legado"])
    return paths


def cache_key_municipio(worker_id: str, municipio: str, estado: str) -> str:
    return f"{worker_id}:{estado.upper()}:{slugify(municipio)}"


def carregar_urls_detalhe_municipio(worker_id: str, municipio: str, estado: str) -> set[str]:
    paths = inicializar_worker(worker_id, municipio, estado)
    cache_key = cache_key_municipio(worker_id, municipio, estado)
    urls = carregar_urls_existentes(paths["detalhe"]) | carregar_urls_existentes(paths["detalhe_legado"])
    urls_detalhe_por_worker[cache_key] = urls
    return urls


def estatisticas(worker_id: str, estado: dict[str, Any], total_municipios: int) -> dict[str, Any]:
    agora = time.time()
    inicio = estado.get("iniciado_timestamp")
    cidade_inicio = estado.get("cidade_iniciada_timestamp")
    concluidos = len(estado.get("municipios_concluidos") or [])
    restante = max(total_municipios - concluidos, 0)
    tempo_total = int(agora - inicio) if inicio else 0
    tempo_cidade = int(agora - cidade_inicio) if cidade_inicio else 0
    velocidade = round((estado.get("paginas_processadas") or 0) / max(tempo_total / 60, 1), 2)
    media_cidade = tempo_total / concluidos if concluidos else None
    eta = int(media_cidade * restante) if media_cidade else None
    return {
        "worker": worker_id,
        "municipio_atual": estado.get("municipio_atual"),
        "pagina_atual": estado.get("pagina_atual", 1),
        "tempo_cidade_segundos": tempo_cidade,
        "tempo_total_segundos": tempo_total,
        "municipios_concluidos": concluidos,
        "municipios_restantes": restante,
        "velocidade_media_paginas_min": velocidade,
        "estimativa_termino_segundos": eta,
    }


@app.before_request
def validar_options():
    if request.method == "OPTIONS":
        return resposta_options()
    return None


@app.route("/", methods=["GET"])
def home():
    return jsonify(
        ok=True,
        mensagem="Servidor Zap multi-worker rodando.",
        workers=list(WORKER_IDS),
        max_paginas=MAX_PAGINAS,
        endpoints=[
            "/worker/<worker>/proximo-municipio",
            "/worker/<worker>/checkpoint",
            "/worker/<worker>/pagina-processada",
            "/dados-lista",
            "/dados-detalhe",
            "/status",
        ],
    )


@app.route("/worker/<worker_id>/proximo-municipio", methods=["GET", "POST"])
def proximo_municipio(worker_id: str):
    worker_id = validar_worker_id(worker_id)
    municipio, estado, municipios = municipio_atual(worker_id)
    if not estado.get("iniciado_em"):
        estado["iniciado_em"] = datetime.now().isoformat(timespec="seconds")
        estado["iniciado_timestamp"] = time.time()
    estado["rodando"] = True

    if not municipio:
        estado["rodando"] = False
        estado["ultimo_status"] = "todos os municipios concluidos"
        salvar_checkpoint(worker_id, estado)
        logger_worker(worker_id).info("Todos os municipios concluidos.")
        return jsonify(ok=True, finalizado=True, checkpoint=estado, stats=estatisticas(worker_id, estado, len(municipios)))

    if estado.get("municipio_atual") != municipio["municipio"]:
        estado["municipio_atual"] = municipio["municipio"]
        estado["estado_atual"] = municipio["estado"]
        estado["pagina_atual"] = max(int(estado.get("pagina_atual") or 1), 1)
        estado["cidade_iniciada_em"] = datetime.now().isoformat(timespec="seconds")
        estado["cidade_iniciada_timestamp"] = time.time()
        estado["ultimo_status"] = f"iniciando municipio {municipio['municipio']}"
        logger_worker(worker_id).info("Inicio do municipio %s/%s", municipio["municipio"], municipio["estado"])

    salvar_checkpoint(worker_id, estado)
    return jsonify(
        ok=True,
        finalizado=False,
        worker=worker_id,
        municipio=municipio,
        max_paginas=MAX_PAGINAS,
        checkpoint=estado,
        stats=estatisticas(worker_id, estado, len(municipios)),
    )


@app.route("/worker/<worker_id>/checkpoint", methods=["GET", "POST"])
def checkpoint(worker_id: str):
    worker_id = validar_worker_id(worker_id)
    estado = carregar_checkpoint(worker_id)
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        estado.update(payload)
        salvar_checkpoint(worker_id, estado)
    municipios = ler_municipios(worker_id)
    return jsonify(ok=True, checkpoint=estado, stats=estatisticas(worker_id, estado, len(municipios)))


@app.route("/worker/<worker_id>/pagina-processada", methods=["POST"])
def pagina_processada(worker_id: str):
    worker_id = validar_worker_id(worker_id)
    payload = request.get_json(silent=True) or {}
    estado = carregar_checkpoint(worker_id)
    pagina = min(int(payload.get("pagina") or estado.get("pagina_atual") or 1), MAX_PAGINAS)
    estado["pagina_atual"] = pagina
    estado["ultima_url"] = payload.get("url") or estado.get("ultima_url")
    estado["paginas_processadas"] = int(estado.get("paginas_processadas") or 0) + 1
    estado["ultimo_status"] = payload.get("status") or f"pagina {pagina} processada"
    salvar_checkpoint(worker_id, estado)
    logger_worker(worker_id).info("Pagina processada: municipio=%s pagina=%s url=%s", estado.get("municipio_atual"), pagina, estado.get("ultima_url"))
    return jsonify(ok=True, checkpoint=estado)


@app.route("/worker/<worker_id>/municipio-concluido", methods=["POST"])
def municipio_concluido(worker_id: str):
    worker_id = validar_worker_id(worker_id)
    payload = request.get_json(silent=True) or {}
    estado = carregar_checkpoint(worker_id)
    municipio = payload.get("municipio") or estado.get("municipio_atual")
    if municipio:
        concluidos = estado.setdefault("municipios_concluidos", [])
        if municipio not in concluidos:
            concluidos.append(municipio)
    estado["municipio_index"] = int(estado.get("municipio_index") or 0) + 1
    estado["pagina_atual"] = 1
    estado["ultimo_status"] = payload.get("motivo") or f"municipio concluido: {municipio}"
    salvar_checkpoint(worker_id, estado)
    logger_worker(worker_id).info("Termino do municipio %s. Motivo: %s", municipio, estado["ultimo_status"])
    return jsonify(ok=True, checkpoint=estado)


@app.route("/worker/<worker_id>/municipio-sem-imoveis", methods=["POST"])
def municipio_sem_imoveis(worker_id: str):
    worker_id = validar_worker_id(worker_id)
    payload = request.get_json(silent=True) or {}
    estado_atual = carregar_checkpoint(worker_id)
    municipio = payload.get("municipio") or estado_atual.get("municipio_atual")
    uf = payload.get("estado") or estado_atual.get("estado_atual") or DEFAULT_ESTADO
    data, hora = agora_data_hora()
    salvar_csv(
        WORKERS_DIR / "municipios_sem_imoveis.csv",
        CAMPOS_SEM_IMOVEIS,
        {"worker": worker_id, "municipio": municipio, "estado": uf, "data": data, "hora": hora, "motivo": "SEM_IMOVEIS"},
    )
    logger_worker(worker_id).info("Municipio sem imoveis: %s/%s", municipio, uf)
    return municipio_concluido(worker_id)


@app.route("/worker/<worker_id>/municipio-url-invalida", methods=["POST"])
def municipio_url_invalida(worker_id: str):
    worker_id = validar_worker_id(worker_id)
    payload = request.get_json(silent=True) or {}
    estado_atual = carregar_checkpoint(worker_id)
    municipio = payload.get("municipio") or estado_atual.get("municipio_atual")
    uf = payload.get("estado") or estado_atual.get("estado_atual") or DEFAULT_ESTADO
    url = payload.get("url") or estado_atual.get("ultima_url") or ""
    data, hora = agora_data_hora()
    salvar_csv(
        WORKERS_DIR / "municipios_url_invalida.csv",
        CAMPOS_URL_INVALIDA,
        {
            "worker": worker_id,
            "municipio": municipio,
            "estado": uf,
            "data": data,
            "hora": hora,
            "motivo": "URL_INVALIDA",
            "url": url,
        },
    )
    logger_worker(worker_id).warning("Municipio com URL invalida para repescagem: %s/%s url=%s", municipio, uf, url)
    return municipio_concluido(worker_id)


@app.route("/worker/<worker_id>/bloqueio", methods=["POST"])
def bloqueio(worker_id: str):
    worker_id = validar_worker_id(worker_id)
    payload = request.get_json(silent=True) or {}
    estado = carregar_checkpoint(worker_id)
    estado["rodando"] = False
    estado["bloqueado"] = True
    estado["ultimo_status"] = payload.get("mensagem") or "bloqueio detectado"
    salvar_checkpoint(worker_id, estado)
    logger_worker(worker_id).warning("Bloqueio detectado: %s", payload)
    return jsonify(ok=True, checkpoint=estado)


@app.route("/worker/<worker_id>/log", methods=["POST"])
def registrar_log(worker_id: str):
    worker_id = validar_worker_id(worker_id)
    payload = request.get_json(silent=True) or {}
    nivel = str(payload.get("nivel") or "info").lower()
    mensagem = payload.get("mensagem") or payload.get("status") or payload
    logger = logger_worker(worker_id)
    if nivel == "error":
        logger.error("%s", mensagem)
    elif nivel == "warning":
        logger.warning("%s", mensagem)
    else:
        logger.info("%s", mensagem)
    return jsonify(ok=True)


@app.route("/status", methods=["GET"])
def status():
    worker_id = worker_id_recebido()
    municipio, estado, municipios = municipio_atual(worker_id)
    if municipio:
        paths = paths_saida(worker_id, municipio["municipio"], municipio["estado"])
        total_lista = len(carregar_urls_existentes(paths["lista"]) | carregar_urls_existentes(paths["lista_legado"]))
        total_detalhes = len(carregar_urls_existentes(paths["detalhe"]) | carregar_urls_existentes(paths["detalhe_legado"]))
    else:
        paths = {}
        total_lista = 0
        total_detalhes = 0
    return jsonify(
        ok=True,
        worker=worker_id,
        municipio=municipio,
        checkpoint=estado,
        stats=estatisticas(worker_id, estado, len(municipios)),
        total_lista=total_lista,
        total_detalhes=total_detalhes,
        pasta_cidade=str(paths.get("cidade", "")),
        pasta_dados=str(paths.get("dados", "")),
        arquivo_lista=str(paths.get("lista", "")),
        arquivo_detalhes=str(paths.get("detalhe", "")),
        arquivo_excel_final=str(paths.get("excel", "")),
    )


@app.route("/dados-lista", methods=["POST"])
def receber_lista():
    worker_id = worker_id_recebido()
    payload = request.get_json(silent=True) or {}
    municipio = payload.get("municipio") or payload.get("cidade")
    uf = payload.get("estado") or DEFAULT_ESTADO
    if not municipio:
        atual, _, _ = municipio_atual(worker_id)
        municipio = atual["municipio"] if atual else "N/A"
        uf = atual["estado"] if atual else uf
    paths = inicializar_worker(worker_id, municipio, uf)
    itens = payload.get("itens", [])
    if isinstance(itens, dict):
        itens = [itens]
    if not isinstance(itens, list):
        return jsonify(ok=False, erro="Formato invalido. Envie {'itens': [...]}"), 400

    novos = 0
    repetidos = 0
    cache_key = cache_key_municipio(worker_id, municipio, uf)
    urls_lista = urls_lista_por_worker.setdefault(
        cache_key,
        carregar_urls_existentes(paths["lista"]) | carregar_urls_existentes(paths["lista_legado"]),
    )
    for item in itens:
        if not isinstance(item, dict):
            continue
        url = normalizar_valor(item.get("url"))
        if url == "N/A":
            continue
        if url in urls_lista:
            repetidos += 1
            continue
        item.update({"worker": worker_id, "municipio": municipio, "estado": uf, "pagina": payload.get("pagina")})
        salvar_csv(paths["lista"], CAMPOS_LISTA, item)
        urls_lista.add(url)
        novos += 1
    salvar_jsonl(worker_id, "lista", payload, municipio, uf)
    logger_worker(worker_id).info("Lista salva: %s novos, %s repetidos, municipio=%s", novos, repetidos, municipio)
    return jsonify(ok=True, novos=novos, repetidos=repetidos, total_lista=len(urls_lista), pasta_dados=str(paths["dados"]))


@app.route("/dados-detalhe", methods=["POST"])
def receber_detalhe():
    worker_id = worker_id_recebido()
    item = request.get_json(silent=True) or {}
    if not isinstance(item, dict):
        return jsonify(ok=False, erro="Formato invalido."), 400
    municipio = item.get("municipio") or item.get("cidade")
    uf = item.get("estado") or DEFAULT_ESTADO
    if not municipio:
        atual, _, _ = municipio_atual(worker_id)
        municipio = atual["municipio"] if atual else "N/A"
        uf = atual["estado"] if atual else uf
    paths = inicializar_worker(worker_id, municipio, uf)
    url = normalizar_valor(item.get("url"))
    if url == "N/A":
        return jsonify(ok=False, erro="Registro sem URL."), 400
    cache_key = cache_key_municipio(worker_id, municipio, uf)
    urls_detalhe = urls_detalhe_por_worker.setdefault(
        cache_key,
        carregar_urls_existentes(paths["detalhe"]) | carregar_urls_existentes(paths["detalhe_legado"]),
    )
    if url in urls_detalhe:
        return jsonify(ok=True, repetido=True, total_detalhes=len(urls_detalhe), pasta_dados=str(paths["dados"]))
    item.update({"worker": worker_id, "municipio": municipio, "estado": uf})
    salvar_csv(paths["detalhe"], CAMPOS_DETALHE, item)
    salvar_jsonl(worker_id, "detalhe", item, municipio, uf)
    urls_detalhe.add(url)
    logger_worker(worker_id).info("Detalhe salvo (%s): %s", len(urls_detalhe), url)
    return jsonify(ok=True, repetido=False, total_detalhes=len(urls_detalhe), pasta_dados=str(paths["dados"]))


@app.route("/worker/<worker_id>/filtrar-urls-detalhe", methods=["POST"])
def filtrar_urls_detalhe(worker_id: str):
    worker_id = validar_worker_id(worker_id)
    payload = request.get_json(silent=True) or {}
    municipio = payload.get("municipio") or payload.get("cidade")
    uf = payload.get("estado") or DEFAULT_ESTADO
    urls = payload.get("urls") or []

    if not municipio:
        atual, _, _ = municipio_atual(worker_id)
        municipio = atual["municipio"] if atual else "N/A"
        uf = atual["estado"] if atual else uf

    if not isinstance(urls, list):
        return jsonify(ok=False, erro="Envie {'urls': [...]}"), 400

    existentes = carregar_urls_detalhe_municipio(worker_id, municipio, uf)
    novas = []
    repetidas = []
    for url in urls:
        url = normalizar_valor(url)
        if url == "N/A":
            continue
        if url in existentes:
            repetidas.append(url)
        elif url not in novas:
            novas.append(url)

    logger_worker(worker_id).info(
        "Filtro de detalhes: municipio=%s novas=%s repetidas=%s",
        municipio,
        len(novas),
        len(repetidas),
    )
    return jsonify(
        ok=True,
        municipio=municipio,
        estado=uf,
        novas=novas,
        repetidas=repetidas,
        total_existentes=len(existentes),
    )


@app.route("/exportar-excel", methods=["POST", "GET"])
def endpoint_exportar_excel():
    worker_id = worker_id_recebido()
    municipio, _, _ = municipio_atual(worker_id)
    payload = request.get_json(silent=True) or {}
    if payload.get("municipio"):
        municipio = {"municipio": payload["municipio"], "estado": payload.get("estado") or DEFAULT_ESTADO}
    if not municipio:
        return jsonify(ok=False, erro="Nenhum municipio atual para exportar."), 400
    paths = inicializar_worker(worker_id, municipio["municipio"], municipio["estado"])
    try:
        resultado = gerar_excel_final(
            arquivo_lista_csv=paths["lista"],
            arquivo_detalhe_csv=paths["detalhe"],
            arquivo_excel_final=paths["excel"],
            campos_lista=CAMPOS_LISTA,
            campos_detalhe=CAMPOS_DETALHE,
        )
        logger_worker(worker_id).info("Excel final gerado: %s", resultado["arquivo_excel_final"])
        return jsonify(ok=True, **resultado)
    except Exception as erro:
        logger_worker(worker_id).exception("Erro ao gerar Excel")
        return jsonify(ok=False, erro=str(erro)), 500


if __name__ == "__main__":
    WORKERS_DIR.mkdir(parents=True, exist_ok=True)
    print("Servidor Zap multi-worker iniciado")
    print(f"Workers: {', '.join(WORKER_IDS)}")
    print(f"Municipios: worker1.csv, worker2.csv, worker3.csv ou workers/<worker>/municipios.csv")
    app.run(host="127.0.0.1", port=5000, debug=False)
