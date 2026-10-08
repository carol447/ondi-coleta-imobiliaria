#!/usr/bin/env python3
"""Calcula volume e duração das coletas do ZAP v3.

Por padrão, percorre ``Estados/<UF>/<municipio>/dados``. Para não contar o
mesmo anúncio em JSON, CSV e Excel, usa os arquivos JSON brutos como fonte
principal e considera somente registros do tipo ``detalhe``.

O tempo da coleta é a diferença entre o horário do primeiro e do último
anúncio. A prioridade do timestamp é:

1. ``recebido_em`` do envelope gravado pelo servidor;
2. ``payload.data_coleta`` + ``payload.hora_coleta``;
3. ``data_coleta`` + ``hora_coleta`` no próprio registro.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


ID_RE = re.compile(r"(?:^|[-_/])id[-_]?([0-9]+)(?:[/?#]|$)", re.I)
DEFAULT_SPECIAL = Path("Estados/SP/presidente-prudentev2/dados")


@dataclass
class Registro:
    municipio: str
    uf: str
    url: str
    anuncio_id: str
    horario: datetime | None
    arquivo: Path

    @property
    def chave(self) -> str:
        return self.anuncio_id or self.url.rstrip("/").lower()


def parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
        # Remove timezone apenas para permitir comparação uniforme. Os dados da
        # v3 foram registrados no mesmo ambiente/servidor local.
        return parsed.replace(tzinfo=None)
    except ValueError:
        return None


def timestamp_registro(registro: dict[str, Any], payload: dict[str, Any]) -> datetime | None:
    recebido = parse_datetime(registro.get("recebido_em"))
    if recebido:
        return recebido
    for fonte in (payload, registro):
        data = str(fonte.get("data_coleta") or "").strip()
        hora = str(fonte.get("hora_coleta") or "").strip()
        if data:
            parsed = parse_datetime(f"{data}T{hora or '00:00:00'}")
            if parsed:
                return parsed
    return None


def iter_json(path: Path) -> Iterable[dict[str, Any]]:
    """Aceita JSON Lines, lista JSON ou objeto JSON único."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1")
    if not text.strip():
        return
    try:
        value = json.loads(text)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    yield item
        elif isinstance(value, dict):
            yield value
        return
    except json.JSONDecodeError:
        pass
    for numero, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"AVISO: JSON inválido em {path}, linha {numero}: {exc}", file=sys.stderr)
            continue
        if isinstance(item, dict):
            yield item


def identificar_local(dados_dir: Path, estados_root: Path) -> tuple[str, str]:
    try:
        rel = dados_dir.resolve().relative_to(estados_root.resolve())
        return rel.parts[0], rel.parts[1]
    except (ValueError, IndexError):
        return "", dados_dir.parent.name


def ler_dados(dados_dir: Path, estados_root: Path) -> list[Registro]:
    uf, municipio = identificar_local(dados_dir, estados_root)
    arquivos = sorted((dados_dir / "bruto").glob("*.json"))
    if not arquivos:
        arquivos = sorted(dados_dir.glob("*.json"))
    encontrados: list[Registro] = []
    for arquivo in arquivos:
        for item in iter_json(arquivo):
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else item
            tipo = str(item.get("tipo") or "").strip().lower()
            url = str(payload.get("url") or payload.get("link") or "").strip()
            # Envelopes de paginação/checkpoint não são anúncios.
            if tipo and tipo != "detalhe":
                continue
            if not url or "/imovel/" not in url:
                continue
            match = ID_RE.search(url)
            encontrados.append(Registro(
                municipio=municipio,
                uf=uf,
                url=url,
                anuncio_id=match.group(1) if match else str(payload.get("id_anuncio") or "").strip(),
                horario=timestamp_registro(item, payload),
                arquivo=arquivo,
            ))
    return encontrados


def deduplicar(registros: Iterable[Registro]) -> list[Registro]:
    unicos: dict[str, Registro] = {}
    sem_chave = 0
    for r in registros:
        chave = r.chave
        if not chave:
            sem_chave += 1
            chave = f"__sem_chave_{sem_chave}"
        atual = unicos.get(chave)
        # Para a duração, preserva a primeira ocorrência conhecida da URL/ID.
        if atual is None or (r.horario and (atual.horario is None or r.horario < atual.horario)):
            unicos[chave] = r
    return list(unicos.values())


def duracao_texto(delta) -> str:
    segundos = int(delta.total_seconds())
    dias, segundos = divmod(segundos, 86400)
    horas, segundos = divmod(segundos, 3600)
    minutos, segundos = divmod(segundos, 60)
    partes = []
    if dias: partes.append(f"{dias} dia(s)")
    partes.extend([f"{horas:02d}h", f"{minutos:02d}min", f"{segundos:02d}s"])
    return " ".join(partes)


def resumir(registros: list[Registro]) -> dict[str, Any]:
    unicos = deduplicar(registros)
    horarios = sorted(r.horario for r in unicos if r.horario is not None)
    primeiro = horarios[0] if horarios else None
    ultimo = horarios[-1] if horarios else None
    return {
        "anuncios_unicos": len(unicos),
        "registros_lidos": len(registros),
        "com_horario": len(horarios),
        "primeiro": primeiro,
        "ultimo": ultimo,
        "duracao": ultimo - primeiro if primeiro and ultimo else None,
    }


def fmt(dt: datetime | None) -> str:
    return dt.strftime("%d/%m/%Y %H:%M:%S") if dt else "não disponível"


def main() -> int:
    parser = argparse.ArgumentParser(description="Conta anúncios, municípios e duração da coleta ZAP v3.")
    parser.add_argument("--raiz", type=Path, default=Path(__file__).resolve().parents[1], help="Raiz do projeto zap-v3")
    parser.add_argument("--especial", type=Path, default=None, help="Pasta dados para relatório específico")
    parser.add_argument("--csv", type=Path, default=None, help="Grava detalhamento por município em CSV")
    args = parser.parse_args()

    raiz = args.raiz.resolve()
    estados = raiz / "Estados"
    especial = (args.especial or (raiz / DEFAULT_SPECIAL)).resolve()
    if not estados.is_dir():
        parser.error(f"Pasta Estados não encontrada: {estados}")

    por_municipio: list[dict[str, Any]] = []
    todos: list[Registro] = []
    for dados_dir in sorted(estados.glob("*/*/dados")):
        registros = ler_dados(dados_dir, estados)
        resumo = resumir(registros)
        if resumo["anuncios_unicos"] == 0:
            continue
        uf, municipio = identificar_local(dados_dir, estados)
        todos.extend(registros)
        por_municipio.append({"uf": uf, "municipio": municipio, "pasta": dados_dir, **resumo})

    geral = resumir(todos)
    especial_regs = ler_dados(especial, estados) if especial.is_dir() else []
    esp = resumir(especial_regs)

    print("=" * 72)
    print("RELATÓRIO DA COLETA ZAP v3")
    print("=" * 72)
    print(f"Municípios com anúncios: {len(por_municipio)}")
    print(f"Anúncios únicos no conjunto: {geral['anuncios_unicos']}")
    print(f"Registros brutos lidos: {geral['registros_lidos']}")
    print(f"Primeiro anúncio recebido: {fmt(geral['primeiro'])}")
    print(f"Último anúncio recebido:   {fmt(geral['ultimo'])}")
    print(f"Tempo percorrido: {duracao_texto(geral['duracao']) if geral['duracao'] else 'não disponível'}")

    print("\n" + "-" * 72)
    print(f"DETALHE: {especial}")
    print("-" * 72)
    print(f"Anúncios únicos: {esp['anuncios_unicos']}")
    print(f"Registros brutos lidos: {esp['registros_lidos']}")
    print(f"Anúncios com horário: {esp['com_horario']}")
    print(f"Primeiro anúncio: {fmt(esp['primeiro'])}")
    print(f"Último anúncio:   {fmt(esp['ultimo'])}")
    print(f"Tempo da coleta: {duracao_texto(esp['duracao']) if esp['duracao'] else 'não disponível'}")

    if args.csv:
        saida = args.csv if args.csv.is_absolute() else raiz / args.csv
        saida.parent.mkdir(parents=True, exist_ok=True)
        with saida.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["uf", "municipio", "anuncios_unicos", "registros_lidos", "primeiro", "ultimo", "duracao_segundos", "pasta"])
            for item in por_municipio:
                writer.writerow([
                    item["uf"], item["municipio"], item["anuncios_unicos"], item["registros_lidos"],
                    item["primeiro"].isoformat(sep=" ") if item["primeiro"] else "",
                    item["ultimo"].isoformat(sep=" ") if item["ultimo"] else "",
                    int(item["duracao"].total_seconds()) if item["duracao"] else "",
                    item["pasta"],
                ])
        print(f"\nDetalhamento CSV salvo em: {saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
