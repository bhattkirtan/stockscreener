"""
SQLite database layer — replaces Firestore for VM deployment.

Schema:
  kv_store     — keyed documents (bot_status, active_positions, trade_history)
  append_log   — append-only rows (trading_signals, bot_logs)
"""

import json
import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

DB_PATH = os.getenv("DB_PATH", "/data/trading.db")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create tables if they don't exist."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS kv_store (
                collection  TEXT NOT NULL,
                doc_id      TEXT NOT NULL,
                data        TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                PRIMARY KEY (collection, doc_id)
            );

            CREATE TABLE IF NOT EXISTS append_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                collection  TEXT NOT NULL,
                doc_id      TEXT,
                data        TEXT NOT NULL,
                created_at  TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_append_collection
                ON append_log (collection, created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_kv_collection
                ON kv_store (collection);
        """)


# ── kv_store helpers ─────────────────────────────────────────────────────────

def kv_set(collection: str, doc_id: str, data: Dict, merge: bool = False):
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        if merge:
            existing = kv_get(collection, doc_id)
            if existing:
                existing.update(data)
                data = existing
        conn.execute(
            "INSERT OR REPLACE INTO kv_store (collection, doc_id, data, updated_at) VALUES (?, ?, ?, ?)",
            (collection, doc_id, json.dumps(data), now),
        )


def kv_get(collection: str, doc_id: str) -> Optional[Dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT data FROM kv_store WHERE collection=? AND doc_id=?",
            (collection, doc_id),
        ).fetchone()
    if row:
        d = json.loads(row["data"])
        d["_id"] = doc_id
        return d
    return None


def kv_get_all(collection: str) -> List[Dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT doc_id, data FROM kv_store WHERE collection=? ORDER BY updated_at DESC",
            (collection,),
        ).fetchall()
    result = []
    for row in rows:
        d = json.loads(row["data"])
        d["_id"] = row["doc_id"]
        result.append(d)
    return result


def kv_update(collection: str, doc_id: str, update: Dict) -> bool:
    existing = kv_get(collection, doc_id)
    if existing is None:
        return False
    existing.update(update)
    existing.pop("_id", None)
    kv_set(collection, doc_id, existing)
    return True


def kv_delete(collection: str, doc_id: str):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM kv_store WHERE collection=? AND doc_id=?",
            (collection, doc_id),
        )


# ── append_log helpers ────────────────────────────────────────────────────────

def log_append(collection: str, data: Dict, doc_id: Optional[str] = None) -> int:
    """Append a row; returns the new row id."""
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO append_log (collection, doc_id, data, created_at) VALUES (?, ?, ?, ?)",
            (collection, doc_id, json.dumps(data), now),
        )
        return cur.lastrowid


def log_query(
    collection: str,
    limit: int = 100,
    filters: Optional[Dict[str, Any]] = None,
) -> List[Dict]:
    """Return rows in descending order; filter by JSON fields via json_extract."""
    sql = "SELECT id, doc_id, data, created_at FROM append_log WHERE collection=?"
    params: list = [collection]

    if filters:
        for key, value in filters.items():
            if key == "bot_id":
                # Support prefix match: 'gold_m5_bot' matches 'gold_m5_bot_something'
                sql += f" AND (json_extract(data, '$.{key}') = ? OR json_extract(data, '$.{key}') LIKE ?)"
                params.append(value)
                params.append(f"{value}%")
            else:
                sql += f" AND json_extract(data, '$.{key}') = ?"
                params.append(value)

    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    result = []
    for row in rows:
        d = json.loads(row["data"])
        d["_id"] = row["id"]
        d["created_at"] = row["created_at"]
        result.append(d)
    return result
