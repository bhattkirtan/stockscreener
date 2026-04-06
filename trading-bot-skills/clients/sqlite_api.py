"""
SQLite API Client — drop-in replacement for FirestoreAPIClient.

Implements exactly the same public interface so storage_skill.py and other
callers need zero changes beyond swapping the import:

    # old
    from clients.firestore_api import FirestoreAPIClient
    client = FirestoreAPIClient(project_id=...)

    # new
    from clients.sqlite_api import SQLiteAPIClient as FirestoreAPIClient
    client = FirestoreAPIClient()          # project_id arg is ignored

The SQLite file location is read from the DB_PATH env var
(default: /data/trading.db — same path used by the FastAPI service).
"""

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/data/trading.db")


@contextmanager
def _conn():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _ensure_schema():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with _conn() as con:
        con.executescript("""
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
            CREATE TABLE IF NOT EXISTS candles (
                epic       TEXT NOT NULL,
                timeframe  TEXT NOT NULL,
                timestamp  TEXT NOT NULL,
                open       REAL NOT NULL,
                high       REAL NOT NULL,
                low        REAL NOT NULL,
                close      REAL NOT NULL,
                volume     INTEGER DEFAULT 0,
                PRIMARY KEY (epic, timeframe, timestamp)
            );
            CREATE INDEX IF NOT EXISTS idx_candles_lookup
                ON candles (epic, timeframe, timestamp DESC);
        """)


class SQLiteAPIClient:
    """
    SQLite-backed persistence that mirrors FirestoreAPIClient's interface.

    Args:
        project_id: Ignored (kept for signature compatibility)
        credentials_path: Ignored
        mock_mode: Ignored (always uses real SQLite)
        db_path: Override the DB file path (default: DB_PATH env var)
    """

    def __init__(
        self,
        project_id: Optional[str] = None,
        credentials_path: Optional[str] = None,
        mock_mode: bool = False,
        db_path: Optional[str] = None,
    ):
        global DB_PATH
        if db_path:
            DB_PATH = db_path
        _ensure_schema()
        logger.info(f"SQLiteAPIClient ready → {DB_PATH}")

    # ── kv helpers ────────────────────────────────────────────────────────────

    def _kv_set(self, collection: str, doc_id: str, data: Dict, merge: bool = False):
        now = datetime.utcnow().isoformat()
        if merge:
            existing = self._kv_get(collection, doc_id)
            if existing:
                existing.pop("_id", None)
                existing.update(data)
                data = existing
        with _conn() as con:
            con.execute(
                "INSERT OR REPLACE INTO kv_store (collection, doc_id, data, updated_at) VALUES (?,?,?,?)",
                (collection, doc_id, json.dumps(data), now),
            )

    def _kv_get(self, collection: str, doc_id: str) -> Optional[Dict]:
        with _conn() as con:
            row = con.execute(
                "SELECT data FROM kv_store WHERE collection=? AND doc_id=?",
                (collection, doc_id),
            ).fetchone()
        if row:
            d = json.loads(row["data"])
            d["_id"] = doc_id
            return d
        return None

    def _kv_delete(self, collection: str, doc_id: str):
        with _conn() as con:
            con.execute(
                "DELETE FROM kv_store WHERE collection=? AND doc_id=?",
                (collection, doc_id),
            )

    def _log_append(self, collection: str, data: Dict, doc_id: Optional[str] = None):
        now = datetime.utcnow().isoformat()
        with _conn() as con:
            if doc_id:
                con.execute(
                    "INSERT OR REPLACE INTO append_log (collection, doc_id, data, created_at) VALUES (?,?,?,?)",
                    (collection, doc_id, json.dumps(data), now),
                )
            else:
                con.execute(
                    "INSERT INTO append_log (collection, doc_id, data, created_at) VALUES (?,?,?,?)",
                    (collection, None, json.dumps(data), now),
                )

    # ── Position Management ───────────────────────────────────────────────────

    def save_position(self, collection: str, deal_id: str, position_data: Dict) -> bool:
        try:
            position_data["updated_at"] = datetime.utcnow().isoformat()
            self._kv_set(collection, deal_id, position_data, merge=True)
            logger.info(f"Position saved: {collection}/{deal_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to save position {deal_id}: {e}")
            return False

    def get_position(self, collection: str, deal_id: str) -> Optional[Dict]:
        try:
            data = self._kv_get(collection, deal_id)
            if data:
                logger.debug(f"Position retrieved: {collection}/{deal_id}")
            return data
        except Exception as e:
            logger.error(f"Failed to get position {deal_id}: {e}")
            return None

    def get_all_positions(self, collection: str) -> List[Dict]:
        try:
            with _conn() as con:
                rows = con.execute(
                    "SELECT doc_id, data FROM kv_store WHERE collection=? ORDER BY updated_at DESC",
                    (collection,),
                ).fetchall()
            result = []
            for row in rows:
                d = json.loads(row["data"])
                d["_id"] = row["doc_id"]
                result.append(d)
            logger.info(f"Retrieved {len(result)} positions from {collection}")
            return result
        except Exception as e:
            logger.error(f"Failed to get positions from {collection}: {e}")
            return []

    def close_position(self, collection: str, deal_id: str, close_data: Dict) -> bool:
        try:
            update = {
                **close_data,
                "status": "CLOSED",
                "closed_at": datetime.utcnow().isoformat(),
            }
            existing = self._kv_get(collection, deal_id) or {}
            existing.pop("_id", None)
            existing.update(update)
            self._kv_set(collection, deal_id, existing)
            logger.info(f"Position closed: {collection}/{deal_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to close position {deal_id}: {e}")
            return False

    def delete_position(self, collection: str, deal_id: str) -> bool:
        try:
            self._kv_delete(collection, deal_id)
            logger.info(f"Position deleted: {collection}/{deal_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete position {deal_id}: {e}")
            return False

    # ── Signal & Trade Logging ────────────────────────────────────────────────

    def log_signal(self, collection: str, signal_data: Dict) -> bool:
        try:
            signal_data.setdefault("timestamp", datetime.utcnow().isoformat())
            self._log_append(collection, signal_data)
            logger.info(f"Signal logged to {collection}")
            return True
        except Exception as e:
            logger.error(f"Failed to log signal: {e}")
            return False

    def log_trade(self, collection: str, trade_data: Dict) -> bool:
        try:
            trade_data["logged_at"] = datetime.utcnow().isoformat()
            deal_id = trade_data.get("deal_id")
            self._log_append(collection, trade_data, doc_id=deal_id)
            logger.info(f"Trade logged to {collection}")
            return True
        except Exception as e:
            logger.error(f"Failed to log trade: {e}")
            return False

    # ── Bot Status ────────────────────────────────────────────────────────────

    def update_bot_status(self, collection: str, bot_id: str, status_data: Dict) -> bool:
        try:
            status_data["last_heartbeat"] = datetime.utcnow().isoformat()
            self._kv_set(collection, bot_id, status_data, merge=True)
            logger.debug(f"Bot status updated: {collection}/{bot_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to update bot status: {e}")
            return False

    # ── Generic ───────────────────────────────────────────────────────────────

    # ── Historical Candles ────────────────────────────────────────────────────

    def insert_candles(self, epic: str, timeframe: str, candles: List[Dict]) -> int:
        """Upsert OHLCV candles. Returns number of rows written."""
        if not candles:
            return 0
        rows = [
            (epic, timeframe, c['timestamp'],
             float(c['open']), float(c['high']), float(c['low']), float(c['close']),
             int(c.get('volume', 0)))
            for c in candles
        ]
        with _conn() as con:
            con.executemany(
                "INSERT OR REPLACE INTO candles "
                "(epic, timeframe, timestamp, open, high, low, close, volume) "
                "VALUES (?,?,?,?,?,?,?,?)",
                rows,
            )
        return len(rows)

    def count_candles(self, epic: str, timeframe: str) -> int:
        """Return total stored bars for this epic/timeframe."""
        with _conn() as con:
            row = con.execute(
                "SELECT COUNT(*) FROM candles WHERE epic=? AND timeframe=?",
                (epic, timeframe),
            ).fetchone()
        return row[0] if row else 0

    def query_candles(
        self,
        epic: str,
        timeframe: str,
        limit: int = None,
        from_ts: str = None,
        to_ts: str = None,
    ) -> List[Dict]:
        """
        Return candles sorted oldest→newest.

        limit  — if set, return the most recent `limit` bars (useful for backtests
                 that say "give me the last 215 000 bars").
        from_ts / to_ts — ISO timestamp strings for date-range filtering.
        """
        filters = "WHERE epic=? AND timeframe=?"
        params: list = [epic, timeframe]
        if from_ts:
            filters += " AND timestamp >= ?"
            params.append(from_ts)
        if to_ts:
            filters += " AND timestamp <= ?"
            params.append(to_ts)

        if limit:
            # Grab the most recent `limit` rows, then re-sort ascending
            inner = f"SELECT timestamp,open,high,low,close,volume FROM candles {filters} ORDER BY timestamp DESC LIMIT ?"
            q = f"SELECT * FROM ({inner}) ORDER BY timestamp"
            params.append(limit)
        else:
            q = f"SELECT timestamp,open,high,low,close,volume FROM candles {filters} ORDER BY timestamp"

        with _conn() as con:
            rows = con.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    def set_document(
        self,
        collection: str,
        document_id: str,
        data: Dict,
        merge: bool = False,
    ) -> bool:
        try:
            self._kv_set(collection, document_id, data, merge=merge)
            logger.debug(f"Document set: {collection}/{document_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to set document {document_id}: {e}")
            return False
