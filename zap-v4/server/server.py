from __future__ import annotations

import csv
import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread
import time
from typing import Any

from flask import Flask, jsonify, request
from flask_cors import CORS

from maestro import MaestroFila
from cards_store import CardsStore

BASE = Path(__file__).resolve().parents[1]
DADOS = Path(os.environ.get("ZAP_DADOS_DIR", BASE / "dados"))
WORKERS = Path(os.environ.get("ZAP_CHECKPOINTS_DIR", BASE / "workers"))
DADOS.mkdir(parents=True, exist_ok=True)
WORKERS.mkdir(parents=True, exist_ok=True)
ARQUIVO_JSON = DADOS / "cards_zap_v4.json"
ARQUIVO_CSV = DADOS / "cards_zap_v4.csv"
INCIDENTES_CSV = DADOS / "incidentes_zap_v4.csv"
EXCEL_FINAL = DADOS / "zap_v4_coleta_nacional.xlsx"
TELEGRAM_CONFIG = Path(__file__).resolve().parent / "telegram_config.json"
CONFIG = BASE / "config"
MUNICIPIOS_CSV = Path(os.environ.get("ZAP_MUNICIPIOS_CSV", CONFIG / "municipios.csv"))
TIPOS_JSON = Path(os.environ.get("ZAP_TIPOS_JSON", CONFIG / "tipos_imovel.json"))
FILA_DB = Path(os.environ.get("ZAP_FILA_DB", DADOS / "fila_maestro.sqlite3"))
LEASE_SEGUNDOS = int(os.environ.get("ZAP_LEASE_SEGUNDOS", "900"))
LOCK = Lock()
MAESTRO = MaestroFila(FILA_DB, lease_segundos=LEASE_SEGUNDOS)
CARDS = CardsStore(DADOS / "cards_zap_v4.sqlite3", ARQUIVO_JSON)
SEQUENCIA = CONFIG / "sequencia_rj_es.json"
SEQUENCIA_ATIVA = MUNICIPIOS_CSV.name == "municipios_rj.csv" and SEQUENCIA.exists()
ES_DADOS = DADOS.parent / "es"
CARDS_ES = CardsStore(ES_DADOS / "cards_zap_v4.sqlite3", ES_DADOS / "cards_zap_v4.json") if SEQUENCIA_ATIVA else None
MG_DADOS = DADOS.parent / "mg"
CARDS_MG = CardsStore(MG_DADOS / "cards_zap_v4.sqlite3", MG_DADOS / "cards_zap_v4.json") if SEQUENCIA_ATIVA else None
CARDS_SUL = {
    uf: CardsStore(DADOS.parent / uf.lower() / "cards_zap_v4.sqlite3", DADOS.parent / uf.lower() / "cards_zap_v4.json")
    for uf in ("PR", "SC", "RS")
} if SEQUENCIA_ATIVA else {}

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("zap-v4")


def agora() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def worker_dir(worker: str) -> Path:
    safe = "".join(c for c in worker if c.isalnum() or c in "-_") or "worker1"
    path = WORKERS / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def checkpoint_path(worker: str) -> Path:
    return worker_dir(worker) / "checkpoint.json"


def ler_json(path: Path, padrao: Any) -> Any:
    if not path.exists():
        return padrao
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return padrao


def escrever_json_atomico(path: Path, dados: Any) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def chave(item: dict[str, Any]) -> str:
    return str(item.get("id_anuncio") or item.get("url") or "").strip()


def serializar_planilha(v: Any) -> Any:
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return v


def telegram_config() -> dict[str, Any]:
    return ler_json(TELEGRAM_CONFIG, {"ativo": False})


def enviar_telegram(mensagem: str) -> dict[str, Any]:
    cfg = telegram_config()
    token = str(cfg.get("bot_token") or "").strip()
    chat_id = str(cfg.get("chat_id") or "").strip()
    if not cfg.get("ativo") or not token or not chat_id or "COLE_AQUI" in token or "COLE_AQUI" in chat_id:
        return {"ok": False, "erro": "Telegram inativo ou sem bot_token/chat_id."}
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": mensagem,
                                   "disable_web_page_preview": "true"}).encode("utf-8")
    try:
        with urllib.request.urlopen(url, data=body, timeout=15) as response:
            resposta = json.loads(response.read().decode("utf-8"))
        return {"ok": bool(resposta.get("ok")), "resposta": resposta}
    except Exception as exc:
        log.exception("Falha no Telegram")
        return {"ok": False, "erro": str(exc)}


def salvar_csv(path: Path, registros: list[dict[str, Any]]) -> None:
    colunas: list[str] = []
    for registro in registros:
        for campo in registro:
            if campo not in colunas:
                colunas.append(campo)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=colunas, extrasaction="ignore")
        writer.writeheader()
        for registro in registros:
            writer.writerow({k: serializar_planilha(v) for k, v in registro.items()})


def carregar_cards() -> list[dict[str, Any]]:
    return CARDS.all()


@app.get("/")
def raiz():
    return jsonify(ok=True, sistema="ZAP v4 coleta simplificada com maestro", max_paginas=50,
                   fila=MAESTRO.status())


@app.post("/maestro/preparar")
def maestro_preparar():
    payload = request.get_json(silent=True) or {}
    municipios = Path(payload.get("municipios_csv") or MUNICIPIOS_CSV)
    tipos = Path(payload.get("tipos_json") or TIPOS_JSON)
    try:
        resultado = MAESTRO.importar(municipios, tipos)
        return jsonify(ok=True, **resultado, fila=MAESTRO.status())
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        return jsonify(ok=False, erro=str(exc),
                       dica="Gere config/municipios.csv com scripts/preparar_municipios.py"), 400


@app.get("/maestro/status")
def maestro_status():
    return jsonify(ok=True, **MAESTRO.status(), banco=str(FILA_DB))


@app.post("/worker/<worker>/proxima-tarefa")
def proxima_tarefa(worker: str):
    if SEQUENCIA_ATIVA:
        cfg = json.loads(SEQUENCIA.read_text(encoding="utf-8"))
        resultado = MAESTRO.proxima(worker)
        for arquivo in cfg.get("proximos", [cfg["proximo_municipios"], cfg["depois_es"]]):
            if not resultado.get("fila_concluida"):
                break
            resultado = MAESTRO.proxima_com_sequencia(worker, CONFIG / arquivo, CONFIG / cfg["tipos"])
        return jsonify(resultado)
    return jsonify(MAESTRO.proxima(worker))


@app.post("/worker/<worker>/tarefa/<int:tarefa_id>/heartbeat")
def heartbeat_tarefa(worker: str, tarefa_id: int):
    payload = request.get_json(silent=True) or {}
    ok = MAESTRO.heartbeat(tarefa_id, worker, int(payload.get("pagina") or 1))
    return jsonify(ok=ok), 200 if ok else 409


@app.post("/worker/<worker>/tarefa/<int:tarefa_id>/avaliar-total")
def avaliar_total(worker: str, tarefa_id: int):
    try:
        resultado = MAESTRO.avaliar_total(tarefa_id, worker, (request.get_json(silent=True) or {}).get("total"), TIPOS_JSON)
        return jsonify(ok=True, **resultado)
    except (ValueError, OSError) as exc:
        return jsonify(ok=False, erro=str(exc)), 400


@app.post("/worker/<worker>/tarefa/<int:tarefa_id>/concluir")
def concluir_tarefa(worker: str, tarefa_id: int):
    payload = request.get_json(silent=True) or {}
    try:
        ok = MAESTRO.concluir(
            tarefa_id, worker, str(payload.get("status") or "CONCLUIDA"),
            int(payload.get("pagina") or 1), str(payload.get("detalhe") or ""),
        )
    except ValueError as exc:
        return jsonify(ok=False, erro=str(exc)), 400
    return jsonify(ok=ok), 200 if ok else 409


@app.post("/worker/<worker>/tarefa/<int:tarefa_id>/falhar")
def falhar_tarefa(worker: str, tarefa_id: int):
    payload = request.get_json(silent=True) or {}
    resultado = MAESTRO.falhar(
        tarefa_id, worker, int(payload.get("pagina") or 1),
        str(payload.get("detalhe") or "erro sem detalhe"),
    )
    return jsonify(resultado), 200 if resultado.get("ok") else 409


@app.post("/worker/<worker>/liberar-tarefa")
def liberar_tarefa(worker: str):
    payload = request.get_json(silent=True) or {}
    tarefa_id = payload.get("tarefa_id")
    total = MAESTRO.liberar(worker, int(tarefa_id) if tarefa_id else None)
    return jsonify(ok=True, liberadas=total)


@app.route("/worker/<worker>/checkpoint", methods=["GET", "POST"])
def checkpoint(worker: str):
    path = checkpoint_path(worker)
    if request.method == "POST":
        estado = request.get_json(silent=True) or {}
        estado["worker"] = worker
        estado["salvo_em_servidor"] = agora()
        with LOCK:
            escrever_json_atomico(path, estado)
    return jsonify(ok=True, checkpoint=ler_json(path, {}))


@app.post("/dados-lista")
def dados_lista():
    payload = request.get_json(silent=True) or {}
    itens = payload.get("itens") or []
    if not isinstance(itens, list):
        return jsonify(ok=False, erro="itens deve ser uma lista"), 400
    worker = str(payload.get("worker") or "worker1")
    tarefa_id = int(payload.get("tarefa_id") or 0)
    pagina = int(payload.get("pagina") or 1)
    if tarefa_id and not MAESTRO.heartbeat(tarefa_id, worker, pagina):
        return jsonify(ok=False, erro="A tarefa não está reservada para este worker."), 409
    validos = []
    for item in itens:
        if not isinstance(item, dict) or not chave(item):
            continue
        item.setdefault("tarefa_id", tarefa_id or None)
        item.setdefault("municipio_tarefa", payload.get("municipio"))
        item.setdefault("uf_tarefa", payload.get("uf"))
        item.setdefault("tipo_id_tarefa", payload.get("tipo_id"))
        item["worker"] = worker
        item["recebido_em_servidor"] = agora()
        validos.append(item)
    uf_real = MAESTRO.uf_tarefa(tarefa_id) if tarefa_id else payload.get("uf")
    destino = CARDS_ES if CARDS_ES is not None and uf_real == "ES" else CARDS
    if CARDS_MG is not None and uf_real == "MG":
        destino = CARDS_MG
    if uf_real in CARDS_SUL:
        destino = CARDS_SUL[uf_real]
    if uf_real and str(payload.get("uf") or "").upper() != uf_real:
        return jsonify(ok=False, erro="UF enviada difere da tarefa reservada"), 400
    novos, total, total_worker = destino.save(validos, worker)
    log.info("%s tarefa=%s %s/%s página %s: %s itens, %s novos", worker, tarefa_id,
             payload.get("municipio"), payload.get("tipo_id"), pagina, len(itens), novos)
    return jsonify(ok=True, recebidos=len(itens), novos=novos, total=total, total_worker=total_worker)


@app.post("/exportar-csv")
def exportar_csv():
    total = atualizar_csv()
    return jsonify(ok=True, total=total, arquivo=str(ARQUIVO_CSV), arquivo_es=str(ES_DADOS / "cards_zap_v4.csv") if CARDS_ES else None,
                   arquivos_sul={uf: str(DADOS.parent / uf.lower() / "cards_zap_v4.csv") for uf in CARDS_SUL})


def atualizar_csv():
    with LOCK:
        cards = carregar_cards()
        temp = ARQUIVO_CSV.with_suffix(".csv.tmp")
        salvar_csv(temp, cards)
        temp.replace(ARQUIVO_CSV)
        if CARDS_ES is not None:
            es_cards = CARDS_ES.all()
            es_csv = ES_DADOS / "cards_zap_v4.csv"
            es_temp = es_csv.with_suffix(".csv.tmp")
            salvar_csv(es_temp, es_cards)
            es_temp.replace(es_csv)
        if CARDS_MG is not None:
            mg_csv = MG_DADOS / "cards_zap_v4.csv"
            mg_temp = mg_csv.with_suffix(".csv.tmp")
            salvar_csv(mg_temp, CARDS_MG.all())
            mg_temp.replace(mg_csv)
        for uf, store in CARDS_SUL.items():
            destino_csv = DADOS.parent / uf.lower() / "cards_zap_v4.csv"
            temp_csv = destino_csv.with_suffix(".csv.tmp")
            salvar_csv(temp_csv, store.all())
            temp_csv.replace(destino_csv)
    return len(cards)


def exportacao_periodica(intervalo):
    while True:
        time.sleep(intervalo)
        try:
            atualizar_csv()
        except Exception:
            log.exception("Falha na atualização periódica do CSV; anúncios preservados no SQLite")


@app.post("/incidente")
def incidente():
    item = request.get_json(silent=True) or {}
    item.setdefault("horario", agora())
    campos = ["horario", "tipo", "worker", "tarefa_id", "municipio", "uf", "tipo_id", "pagina", "url", "detalhe"]
    with LOCK:
        existe = INCIDENTES_CSV.exists()
        with INCIDENTES_CSV.open("a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
            if not existe:
                w.writeheader()
            w.writerow(item)
        log.warning("INCIDENTE %s", item)
    aviso = enviar_telegram(
        "🚨 ZAP v4 registrou um incidente.\n\n"
        f"Tipo: {item.get('tipo', '-')}\nWorker: {item.get('worker', '-')}\n"
        f"Busca: {item.get('busca', '-')}\nPágina: {item.get('pagina', '-')}\n"
        f"Horário: {item.get('horario', '-')}\nURL: {item.get('url', '-')}"
    )
    return jsonify(ok=True, telegram=aviso)


def gerar_excel() -> dict[str, Any]:
    import pandas as pd

    cards = carregar_cards()
    df = pd.DataFrame([{k: serializar_planilha(v) for k, v in x.items()} for x in cards])
    incidentes = pd.read_csv(INCIDENTES_CSV, encoding="utf-8-sig") if INCIDENTES_CSV.exists() else pd.DataFrame()
    checkpoints = []
    for path in sorted(WORKERS.glob("worker*/checkpoint.json")):
        checkpoints.append(ler_json(path, {}))
    resumo = []
    fila = MAESTRO.listar_tarefas()
    if not df.empty:
        for grupo, parte in df.groupby("grupo_tipos", dropna=False):
            resumo.append({"grupo_tipos": grupo, "anuncios_unicos": len(parte),
                           "preco_medio": parte["preco"].dropna().mean() if "preco" in parte else None,
                           "paginas": parte["pagina"].nunique() if "pagina" in parte else None})
    with pd.ExcelWriter(EXCEL_FINAL, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Todos os imóveis", index=False)
        pd.DataFrame(resumo).to_excel(writer, sheet_name="Resumo por busca", index=False)
        pd.DataFrame(checkpoints).to_excel(writer, sheet_name="Checkpoints", index=False)
        pd.DataFrame(fila).to_excel(writer, sheet_name="Fila maestro", index=False)
        incidentes.to_excel(writer, sheet_name="Incidentes", index=False)
        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for column in sheet.columns:
                letter = column[0].column_letter
                width = min(60, max(10, max(len(str(c.value or "")) for c in column) + 2))
                sheet.column_dimensions[letter].width = width
    return {"arquivo_excel_final": str(EXCEL_FINAL), "total": len(cards), "incidentes": len(incidentes)}


@app.route("/exportar-excel", methods=["GET", "POST"])
def exportar_excel():
    try:
        resultado = gerar_excel()
        aviso = enviar_telegram(
            "✅ Excel do ZAP v4 gerado.\n\n"
            f"Imóveis únicos: {resultado['total']}\nIncidentes: {resultado['incidentes']}\n"
            f"Horário: {agora()}\nArquivo: {resultado['arquivo_excel_final']}"
        )
        return jsonify(ok=True, telegram=aviso, **resultado)
    except Exception as exc:
        log.exception("Falha ao gerar Excel")
        return jsonify(ok=False, erro=str(exc)), 500


@app.get("/status")
def status():
    worker = request.args.get("worker", "worker1")
    total, total_worker = CARDS.counts(worker)
    if CARDS_ES is not None:
        es_total, es_worker = CARDS_ES.counts(worker)
        total += es_total
        total_worker += es_worker
    if CARDS_MG is not None:
        mg_total, mg_worker = CARDS_MG.counts(worker)
        total += mg_total
        total_worker += mg_worker
    for store in CARDS_SUL.values():
        sul_total, sul_worker = store.counts(worker)
        total += sul_total
        total_worker += sul_worker
    return jsonify(ok=True, worker=worker, total_cards=total,
                   total_worker=total_worker,
                   checkpoint=ler_json(checkpoint_path(worker), {}),
                   maestro=MAESTRO.status(),
                   arquivo_excel_final=str(EXCEL_FINAL) if EXCEL_FINAL.exists() else None)


@app.post("/telegram/testar")
def testar_telegram():
    resultado = enviar_telegram(
        "✅ Teste do Telegram: alertas do ZAP v4 estão funcionando.\n"
        f"Horário: {agora()}"
    )
    return jsonify(resultado), 200 if resultado.get("ok") else 500


if __name__ == "__main__":
    intervalo_csv = int(os.environ.get("ZAP_CSV_INTERVALO", "0"))
    if intervalo_csv > 0:
        Thread(target=exportacao_periodica, args=(intervalo_csv,), daemon=True).start()
    print(f"ZAP v4 com maestro: http://127.0.0.1:5000 | dados: {DADOS}")
    print(f"Fila: {FILA_DB} | municípios: {MUNICIPIOS_CSV} | tipos: {TIPOS_JSON}")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
