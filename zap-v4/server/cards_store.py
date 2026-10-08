"""Persistência incremental, com importação transacional do JSON legado."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class CardsStore:
    def __init__(self, path: Path, legacy: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS cards (id TEXT PRIMARY KEY, worker TEXT, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS cards_worker ON cards(worker);
                CREATE TABLE IF NOT EXISTS meta (id TEXT PRIMARY KEY);
            """)
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM meta WHERE id='legacy_imported'").fetchone():
                if legacy.exists():
                    rows = json.loads(legacy.read_text(encoding="utf-8"))
                    if not isinstance(rows, list):
                        raise ValueError("JSON legado deve conter uma lista")
                    for row in rows:
                        key = str(row.get("id_anuncio") or row.get("url") or "").strip()
                        if key:
                            db.execute("INSERT OR REPLACE INTO cards VALUES (?,?,?)",
                                       (key, row.get("worker"), json.dumps(row, ensure_ascii=False)))
                db.execute("INSERT INTO meta VALUES ('legacy_imported')")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=60)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=60000")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def save(self, rows, worker):
        new = 0
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in rows:
                key = str(row.get("id_anuncio") or row.get("url") or "").strip()
                if not key:
                    continue
                old = db.execute("SELECT payload FROM cards WHERE id=?", (key,)).fetchone()
                merged = {**(json.loads(old[0]) if old else {}), **row}
                new += old is None
                db.execute("INSERT OR REPLACE INTO cards VALUES (?,?,?)",
                           (key, merged.get("worker"), json.dumps(merged, ensure_ascii=False)))
            total = db.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
            own = db.execute("SELECT COUNT(*) FROM cards WHERE worker=?", (worker,)).fetchone()[0]
        return new, total, own

    def counts(self, worker):
        with self.connect() as db:
            return (db.execute("SELECT COUNT(*) FROM cards").fetchone()[0],
                    db.execute("SELECT COUNT(*) FROM cards WHERE worker=?", (worker,)).fetchone()[0])

    def all(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM cards ORDER BY rowid")]
