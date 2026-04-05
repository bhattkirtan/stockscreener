"""
SQLite Log Publisher

Streams bot logs to SQLite in real-time for live monitoring:
- Batches writes (every 5 seconds or 20 log entries)
- Keeps only the last 200 entries in memory buffer

Usage:
    publisher = LogPublisher(bot_id='gold_m5_bot', run_id='20260329_140000')
    handler = FirestoreLogHandler(publisher, level=logging.INFO)
    logging.getLogger().addHandler(handler)
    publisher.start_batch_writer()
    # ... bot runs ...
    publisher.stop_batch_writer()
"""

import json
import logging
import os
import sqlite3
from collections import deque
from datetime import datetime
from threading import RLock, Timer
from typing import Optional

DB_PATH = os.getenv("DB_PATH", "/data/trading.db")
COLLECTION = "bot_logs"

logger = logging.getLogger(__name__)


def _ensure_schema() -> None:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("""
        CREATE TABLE IF NOT EXISTS append_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            collection  TEXT NOT NULL,
            doc_id      TEXT,
            data        TEXT NOT NULL,
            created_at  TEXT NOT NULL
        )
    """)
    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_append_collection
            ON append_log (collection, created_at DESC)
    """)
    con.commit()
    con.close()


class LogPublisher:
    """Publishes bot logs to SQLite in batches."""

    MAX_LOGS_IN_MEMORY = 200
    BATCH_SIZE = 20
    BATCH_INTERVAL = 5.0

    def __init__(
        self,
        bot_id: str,
        run_id: str,
        project_id: Optional[str] = None,   # kept for signature compat, ignored
    ):
        self.bot_id = bot_id
        self.run_id = run_id
        self.log_buffer: deque = deque(maxlen=self.MAX_LOGS_IN_MEMORY)
        self.lock = RLock()
        self.sequence_number = 0
        self._timer: Optional[Timer] = None
        self._running = False
        _ensure_schema()
        logger.info(f"LogPublisher ready → {DB_PATH}")

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start_batch_writer(self) -> None:
        if not self._running:
            self._running = True
            self._schedule_flush()
            logger.info(f"Log batch writer started (interval: {self.BATCH_INTERVAL}s)")

    def stop_batch_writer(self) -> None:
        self._running = False
        if self._timer:
            self._timer.cancel()
            self._timer = None
        self._flush()
        logger.info("Log batch writer stopped")

    # ── Public API ────────────────────────────────────────────────────────────

    def publish_log(self, level: str, message: str, logger_name: str = 'bot') -> None:
        with self.lock:
            self.sequence_number += 1
            entry = {
                'bot_id': self.bot_id,
                'run_id': self.run_id,
                'timestamp': datetime.utcnow().isoformat(),
                'sequence': self.sequence_number,
                'level': level,
                'logger': logger_name,
                'message': message,
            }
            self.log_buffer.append(entry)
            if len(self.log_buffer) >= self.BATCH_SIZE:
                self._flush()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _schedule_flush(self) -> None:
        if self._running:
            self._timer = Timer(self.BATCH_INTERVAL, self._periodic_flush)
            self._timer.daemon = True
            self._timer.start()

    def _periodic_flush(self) -> None:
        try:
            if self.log_buffer:
                self._flush()
        finally:
            self._schedule_flush()

    def _flush(self) -> None:
        with self.lock:
            if not self.log_buffer:
                return
            entries = list(self.log_buffer)
            self.log_buffer.clear()

        doc_id_prefix = f"{self.bot_id}_{self.run_id}"
        try:
            con = sqlite3.connect(DB_PATH, check_same_thread=False)
            con.execute("PRAGMA journal_mode=WAL")
            with con:
                con.executemany(
                    "INSERT INTO append_log (collection, doc_id, data, created_at) VALUES (?,?,?,?)",
                    [
                        (
                            COLLECTION,
                            f"{doc_id_prefix}_{e['sequence']}",
                            json.dumps(e),
                            e['timestamp'],
                        )
                        for e in entries
                    ],
                )
            con.close()
            logger.debug(f"Flushed {len(entries)} log entries to SQLite")
        except Exception as ex:
            logger.error(f"Log batch write failed: {ex}")


class FirestoreLogHandler(logging.Handler):
    """
    Standard logging.Handler that routes records to LogPublisher.

    Attach to any logger to stream logs to SQLite:
        handler = FirestoreLogHandler(publisher, level=logging.INFO)
        handler.setFormatter(logging.Formatter('%(asctime)s %(name)s %(message)s'))
        logging.getLogger().addHandler(handler)
    """

    def __init__(self, log_publisher: LogPublisher, level: int = logging.INFO):
        super().__init__(level)
        self.log_publisher = log_publisher

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            self.log_publisher.publish_log(
                level=record.levelname,
                message=message,
                logger_name=record.name,
            )
        except Exception:
            self.handleError(record)
