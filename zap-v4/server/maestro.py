from __future__ import annotations

import csv
import json
import sqlite3
import unicodedata
import urllib.parse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


STATUS_FINAIS = {
    "CONCLUIDA",
    "SEM_ANUNCIOS",
    "PAGINA_NAO_ENCONTRADA",
    "ERRO_PERMANENTE",
}

TIPOS_BUSCA_UNICA = (
    "apartamento_residencial", "studio_residencial", "casa_residencial",
    "condominio_residencial", "casa-vila_residencial", "cobertura_residencial",
    "flat_residencial", "loft_residencial", "lote-terreno_residencial",
    "sobrado_residencial", "kitnet_residencial",
)


def agora() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def instante_futuro(segundos: int) -> str:
    return (datetime.now(timezone.utc).astimezone() + timedelta(seconds=segundos)).isoformat(timespec="seconds")


def slug(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto or "")
    ascii_texto = normalizado.encode("ascii", "ignore").decode("ascii").lower()
    return "-".join(parte for parte in "".join(c if c.isalnum() else " " for c in ascii_texto).split() if parte)


def url_busca(municipio: str, uf: str, tipo_id: str, url_base: str = "", rota: str = "imoveis") -> str:
    if url_base:
        url = url_base
    else:
        url = f"https://www.zapimoveis.com.br/venda/{slug(rota) or 'imoveis'}/{slug(uf)}+{slug(municipio)}/"
    partes = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(partes.query, keep_blank_values=True)
    query["tipos"] = [tipo_id]
    query.pop("pagina", None)
    return urllib.parse.urlunsplit(
        (partes.scheme or "https", partes.netloc or "www.zapimoveis.com.br", partes.path, urllib.parse.urlencode(query, doseq=True), "")
    )


def ler_csv(path: Path) -> list[dict[str, str]]:
    ultimo_erro: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            texto = path.read_text(encoding=encoding)
            amostra = texto[:4096]
            try:
                delimiter = csv.Sniffer().sniff(amostra, delimiters=";,\t").delimiter
            except csv.Error:
                delimiter = ";"
            return list(csv.DictReader(texto.splitlines(), delimiter=delimiter))
        except (UnicodeDecodeError, OSError) as exc:
            ultimo_erro = exc
    raise RuntimeError(f"Não foi possível ler {path}: {ultimo_erro}")


class MaestroFila:
    def __init__(self, banco: Path, lease_segundos: int = 900):
        self.banco = banco
        self.lease_segundos = lease_segundos
        banco.parent.mkdir(parents=True, exist_ok=True)
        self._criar_schema()

    @contextmanager
    def _conexao(self):
        conexao = sqlite3.connect(self.banco, timeout=30)
        conexao.row_factory = sqlite3.Row
        conexao.execute("PRAGMA journal_mode=WAL")
        conexao.execute("PRAGMA busy_timeout=30000")
        try:
            yield conexao
            conexao.commit()
        except Exception:
            conexao.rollback()
            raise
        finally:
            conexao.close()

    def _criar_schema(self) -> None:
        with self._conexao() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS tarefas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    municipio TEXT NOT NULL,
                    uf TEXT NOT NULL,
                    tipo_id TEXT NOT NULL,
                    tipo_rotulo TEXT NOT NULL,
                    url_base TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDENTE',
                    prioridade INTEGER NOT NULL DEFAULT 0,
                    tentativas INTEGER NOT NULL DEFAULT 0,
                    max_tentativas INTEGER NOT NULL DEFAULT 3,
                    worker TEXT,
                    ultimo_worker TEXT,
                    reservado_em TEXT,
                    lease_ate TEXT,
                    disponivel_em TEXT,
                    pagina_atual INTEGER NOT NULL DEFAULT 1,
                    ultimo_erro TEXT,
                    criado_em TEXT NOT NULL,
                    atualizado_em TEXT NOT NULL,
                    UNIQUE(uf, municipio, tipo_id)
                );
                CREATE INDEX IF NOT EXISTS idx_tarefas_fila
                    ON tarefas(status, disponivel_em, prioridade DESC, id);
                CREATE INDEX IF NOT EXISTS idx_tarefas_worker
                    ON tarefas(worker, status);
                """
            )

    def importar(self, municipios_csv: Path, tipos_json: Path) -> dict[str, int]:
        if not municipios_csv.exists():
            raise FileNotFoundError(f"Arquivo de municípios não encontrado: {municipios_csv}")
        if not tipos_json.exists():
            raise FileNotFoundError(f"Arquivo de tipos não encontrado: {tipos_json}")

        municipios = ler_csv(municipios_csv)
        tipos = json.loads(tipos_json.read_text(encoding="utf-8"))
        if not isinstance(tipos, list) or not tipos:
            raise ValueError("tipos_imovel.json deve conter uma lista não vazia.")

        criadas = 0
        ignoradas = 0
        horario = agora()
        with self._conexao() as db:
            db.execute("BEGIN IMMEDIATE")
            for linha in municipios:
                municipio = str(linha.get("municipio") or linha.get("cidade") or "").strip()
                uf = str(linha.get("uf") or linha.get("estado") or "").strip().upper()
                if not municipio or len(uf) != 2:
                    ignoradas += 1
                    continue
                base = str(linha.get("url") or linha.get("url_base") or "").strip()
                prioridade = int(str(linha.get("prioridade") or "0").strip() or 0)
                populacao_texto = str(linha.get("populacao") or "").strip()
                populacao = int(populacao_texto) if populacao_texto else None
                if populacao is not None and populacao < 0:
                    raise ValueError(f"População inválida para {municipio}: {populacao}")
                tipos_municipio = tipos
                dinamica = linha.get("estrategia") == "total_anuncios"
                if dinamica or (populacao is not None and populacao < 100_000):
                    tipos_municipio = [{
                        "id": ",".join(TIPOS_BUSCA_UNICA),
                        "rotulo": "Avaliar total de anúncios" if dinamica else "Todos os tipos selecionados",
                        "rota": "imoveis",
                    }]
                for tipo in tipos_municipio:
                    tipo_id = str(tipo.get("id") or "").strip()
                    rotulo = str(tipo.get("rotulo") or tipo_id).strip()
                    rota = str(tipo.get("rota") or "imoveis").strip()
                    if not tipo_id:
                        ignoradas += 1
                        continue
                    cursor = db.execute(
                        """
                        INSERT OR IGNORE INTO tarefas
                        (municipio, uf, tipo_id, tipo_rotulo, url_base, prioridade, criado_em, atualizado_em)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (municipio, uf, tipo_id, rotulo, url_busca(municipio, uf, tipo_id, base, rota), prioridade, horario, horario),
                    )
                    criadas += cursor.rowcount
        return {"criadas": criadas, "ignoradas": ignoradas, "municipios_lidos": len(municipios), "tipos": len(tipos)}

    def avaliar_total(self, tarefa_id: int, worker: str, total: int, tipos_json: Path) -> dict:
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise ValueError("Total deve ser um inteiro não negativo")
        tipos = json.loads(tipos_json.read_text(encoding="utf-8"))
        with self._conexao() as db:
            db.execute("BEGIN IMMEDIATE")
            tarefa = db.execute("SELECT * FROM tarefas WHERE id=? AND worker=? AND status='RESERVADA'",
                                (tarefa_id, worker)).fetchone()
            if not tarefa:
                raise ValueError("Reserva inválida")
            if tarefa["tipo_rotulo"] != "Avaliar total de anúncios":
                return {"dividida": tarefa["tipo_rotulo"] == "Avaliação dividida por tipo", "total": total}
            horario = agora()
            if total <= 1500:
                db.execute("UPDATE tarefas SET tipo_rotulo='Busca única por total', ultimo_erro=?, atualizado_em=? WHERE id=?",
                           (f"Total informado pelo site: {total}", horario, tarefa_id))
            else:
                for tipo in tipos:
                    tid = tipo["id"]
                    db.execute("""INSERT OR IGNORE INTO tarefas
                        (municipio,uf,tipo_id,tipo_rotulo,url_base,prioridade,criado_em,atualizado_em)
                        VALUES (?,?,?,?,?,?,?,?)""", (tarefa["municipio"], tarefa["uf"], tid,
                        tipo.get("rotulo", tid), url_busca(tarefa["municipio"], tarefa["uf"], tid, rota=tipo.get("rota", "imoveis")),
                        tarefa["prioridade"], horario, horario))
                db.execute("UPDATE tarefas SET tipo_rotulo='Avaliação dividida por tipo', status='CONCLUIDA', worker=NULL, lease_ate=NULL, reservado_em=NULL, ultimo_erro=?, atualizado_em=? WHERE id=?",
                           (f"Total informado pelo site: {total}; dividido por tipo", horario, tarefa_id))
        return {"dividida": total > 1500, "total": total}

    def _liberar_leases_expirados(self, db: sqlite3.Connection) -> None:
        horario = agora()
        db.execute(
            """
            UPDATE tarefas
               SET status='PENDENTE', ultimo_worker=worker, worker=NULL,
                   reservado_em=NULL, lease_ate=NULL, atualizado_em=?,
                   ultimo_erro=COALESCE(ultimo_erro, 'reserva expirada')
             WHERE status='RESERVADA' AND lease_ate IS NOT NULL AND lease_ate <= ?
            """,
            (horario, horario),
        )

    def proxima(self, worker: str) -> dict[str, Any]:
        horario = agora()
        with self._conexao() as db:
            db.execute("BEGIN IMMEDIATE")
            self._liberar_leases_expirados(db)

            atual = db.execute(
                "SELECT * FROM tarefas WHERE status='RESERVADA' AND worker=? ORDER BY id LIMIT 1",
                (worker,),
            ).fetchone()
            if atual:
                return {"ok": True, "tarefa": dict(atual), "retomada": True}

            tarefa = db.execute(
                """
                SELECT * FROM tarefas AS candidata
                 WHERE status='PENDENTE'
                   AND (disponivel_em IS NULL OR disponivel_em <= ?)
                   AND NOT EXISTS (
                       SELECT 1 FROM tarefas AS ativa
                        WHERE ativa.status='RESERVADA'
                          AND ativa.uf=candidata.uf
                          AND ativa.municipio=candidata.municipio
                   )
                 ORDER BY CASE WHEN ultimo_worker=? THEN 1 ELSE 0 END,
                          prioridade DESC, id
                 LIMIT 1
                """,
                (horario, worker),
            ).fetchone()
            if tarefa:
                lease_ate = instante_futuro(self.lease_segundos)
                db.execute(
                    """
                    UPDATE tarefas
                       SET status='RESERVADA', worker=?, reservado_em=?, lease_ate=?,
                           atualizado_em=?, pagina_atual=MAX(1, pagina_atual)
                     WHERE id=? AND status='PENDENTE'
                    """,
                    (worker, horario, lease_ate, horario, tarefa["id"]),
                )
                reservada = db.execute("SELECT * FROM tarefas WHERE id=?", (tarefa["id"],)).fetchone()
                return {"ok": True, "tarefa": dict(reservada), "retomada": False}

            pendente_futura = db.execute(
                "SELECT MIN(disponivel_em) AS proxima FROM tarefas WHERE status='PENDENTE'"
            ).fetchone()["proxima"]
            ativas = db.execute("SELECT COUNT(*) FROM tarefas WHERE status='RESERVADA'").fetchone()[0]
            pendentes = db.execute("SELECT COUNT(*) FROM tarefas WHERE status='PENDENTE'").fetchone()[0]
            if pendentes or ativas:
                return {"ok": True, "aguardar": True, "proxima_disponivel_em": pendente_futura, "ativas": ativas}
            return {"ok": True, "fila_concluida": True}

    def heartbeat(self, tarefa_id: int, worker: str, pagina: int) -> bool:
        horario = agora()
        with self._conexao() as db:
            cursor = db.execute(
                """
                UPDATE tarefas SET pagina_atual=?, lease_ate=?, atualizado_em=?
                 WHERE id=? AND status='RESERVADA' AND worker=?
                """,
                (max(1, pagina), instante_futuro(self.lease_segundos), horario, tarefa_id, worker),
            )
            return cursor.rowcount == 1

    def concluir(self, tarefa_id: int, worker: str, status: str, pagina: int, detalhe: str = "") -> bool:
        if status not in STATUS_FINAIS:
            raise ValueError(f"Status final inválido: {status}")
        horario = agora()
        with self._conexao() as db:
            cursor = db.execute(
                """
                UPDATE tarefas
                   SET status=?, pagina_atual=?, ultimo_erro=?, ultimo_worker=?, worker=NULL,
                       reservado_em=NULL, lease_ate=NULL, disponivel_em=NULL, atualizado_em=?
                 WHERE id=? AND status='RESERVADA' AND worker=?
                """,
                (status, max(1, pagina), detalhe or None, worker, horario, tarefa_id, worker),
            )
            return cursor.rowcount == 1

    def falhar(self, tarefa_id: int, worker: str, pagina: int, detalhe: str) -> dict[str, Any]:
        horario = agora()
        with self._conexao() as db:
            db.execute("BEGIN IMMEDIATE")
            tarefa = db.execute(
                "SELECT * FROM tarefas WHERE id=? AND status='RESERVADA' AND worker=?",
                (tarefa_id, worker),
            ).fetchone()
            if not tarefa:
                return {"ok": False, "erro": "Tarefa não pertence ao worker ou já foi encerrada."}
            tentativas = int(tarefa["tentativas"]) + 1
            permanente = tentativas >= int(tarefa["max_tentativas"])
            status = "ERRO_PERMANENTE" if permanente else "PENDENTE"
            atraso = min(3600, 60 * (2 ** max(0, tentativas - 1)))
            db.execute(
                """
                UPDATE tarefas
                   SET status=?, tentativas=?, pagina_atual=?, ultimo_erro=?, ultimo_worker=?,
                       worker=NULL, reservado_em=NULL, lease_ate=NULL, disponivel_em=?, atualizado_em=?
                 WHERE id=?
                """,
                (status, tentativas, max(1, pagina), detalhe, worker,
                 None if permanente else instante_futuro(atraso), horario, tarefa_id),
            )
            return {"ok": True, "status": status, "tentativas": tentativas, "repetir_em_segundos": 0 if permanente else atraso}

    def liberar(self, worker: str, tarefa_id: int | None = None) -> int:
        horario = agora()
        with self._conexao() as db:
            if tarefa_id is None:
                cursor = db.execute(
                    """UPDATE tarefas SET status='PENDENTE', ultimo_worker=worker, worker=NULL,
                       reservado_em=NULL, lease_ate=NULL, disponivel_em=?, atualizado_em=?
                       WHERE status='RESERVADA' AND worker=?""",
                    (horario, horario, worker),
                )
            else:
                cursor = db.execute(
                    """UPDATE tarefas SET status='PENDENTE', ultimo_worker=worker, worker=NULL,
                       reservado_em=NULL, lease_ate=NULL, disponivel_em=?, atualizado_em=?
                       WHERE id=? AND status='RESERVADA' AND worker=?""",
                    (horario, horario, tarefa_id, worker),
                )
            return cursor.rowcount

    def status(self) -> dict[str, Any]:
        with self._conexao() as db:
            db.execute("BEGIN IMMEDIATE")
            self._liberar_leases_expirados(db)
            contagens = {row["status"]: row["total"] for row in db.execute(
                "SELECT status, COUNT(*) AS total FROM tarefas GROUP BY status"
            )}
            total = sum(contagens.values())
            return {"total": total, "por_status": contagens, "concluidas": sum(contagens.get(s, 0) for s in STATUS_FINAIS)}

    def listar_tarefas(self) -> list[dict[str, Any]]:
        with self._conexao() as db:
            return [dict(row) for row in db.execute(
                """SELECT id, municipio, uf, tipo_id, tipo_rotulo, status, prioridade,
                          tentativas, max_tentativas, worker, pagina_atual, ultimo_erro,
                          reservado_em, lease_ate, disponivel_em, atualizado_em
                     FROM tarefas ORDER BY uf, municipio, tipo_rotulo"""
            )]

    def uf_tarefa(self, tarefa_id: int) -> str | None:
        with self._conexao() as db:
            row = db.execute("SELECT uf FROM tarefas WHERE id=?", (tarefa_id,)).fetchone()
            return row[0] if row else None

    def proxima_com_sequencia(self, worker: str, municipios: Path, tipos: Path) -> dict[str, Any]:
        resultado = self.proxima(worker)
        if resultado.get("fila_concluida"):
            self.importar(municipios, tipos)
            resultado = self.proxima(worker)
        return resultado
