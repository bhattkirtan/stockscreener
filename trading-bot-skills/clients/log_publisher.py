"""
Firestore Log Publisher

Streams bot logs to Firestore in real-time for live monitoring:
- Batches writes (every 5 seconds or 20 log entries)
- Keeps only the last 200 entries in memory
- TTL: 24 hours (documents auto-expire)

Usage:
    publisher = LogPublisher(bot_id='gold_m5_bot', run_id='20260329_140000')
    handler = FirestoreLogHandler(publisher, level=logging.INFO)
    logging.getLogger().addHandler(handler)
    publisher.start_batch_writer()
    # ... bot runs ...
    publisher.stop_batch_writer()
"""

import logging
import os
from collections import deque
from datetime import datetime, timedelta
from threading import RLock, Timer
from typing import Optional


class LogPublisher:
    """Publishes bot logs to Firestore in batches."""

    COLLECTION = 'bot_logs'
    MAX_LOGS_IN_MEMORY = 200
    BATCH_SIZE = 20         # Flush after 20 entries
    BATCH_INTERVAL = 5.0    # Or every 5 seconds
    TTL_HOURS = 24

    def __init__(
        self,
        bot_id: str,
        run_id: str,
        project_id: Optional[str] = None,
    ):
        self.bot_id = bot_id
        self.run_id = run_id
        self.project_id = project_id or os.getenv('GCP_PROJECT_ID') or os.getenv('FIRESTORE_PROJECT_ID')

        self.log_buffer: deque = deque(maxlen=self.MAX_LOGS_IN_MEMORY)
        self.lock = RLock()
        self.sequence_number = 0
        self._timer: Optional[Timer] = None
        self._running = False

        self.ttl_timestamp = datetime.now() + timedelta(hours=self.TTL_HOURS)

        self.firestore_client = None
        self._init_firestore()

    def _init_firestore(self) -> None:
        try:
            from google.cloud import firestore
            self.firestore_client = firestore.Client(project=self.project_id)
            logging.getLogger(__name__).info(
                f"✅ LogPublisher initialized (project: {self.project_id})"
            )
        except Exception as e:
            logging.getLogger(__name__).warning(
                f"⚠️ LogPublisher Firestore init failed: {e} — logs will not stream to Firestore"
            )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start_batch_writer(self) -> None:
        """Start the background periodic flush timer."""
        if not self._running:
            self._running = True
            self._schedule_flush()
            logging.getLogger(__name__).info(
                f"📝 Log batch writer started (interval: {self.BATCH_INTERVAL}s)"
            )

    def stop_batch_writer(self) -> None:
        """Stop the periodic flush timer and write remaining buffered logs."""
        self._running = False
        if self._timer:
            self._timer.cancel()
            self._timer = None
        self._flush()
        logging.getLogger(__name__).info("📝 Log batch writer stopped")

    # ── Public API ────────────────────────────────────────────────────────────

    def publish_log(self, level: str, message: str, logger_name: str = 'bot') -> None:
        """Buffer a single log entry for batch write to Firestore."""
        with self.lock:
            self.sequence_number += 1
            entry = {
                'bot_id': self.bot_id,
                'run_id': self.run_id,
                'timestamp': datetime.now().isoformat(),
                'sequence': self.sequence_number,
                'level': level,
                'logger': logger_name,
                'message': message,
                'ttl': self.ttl_timestamp.isoformat(),
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
        if not self.firestore_client:
            return

        with self.lock:
            if not self.log_buffer:
                return

            try:
                entries = list(self.log_buffer)
                batch = self.firestore_client.batch()

                for entry in entries:
                    doc_id = f"{self.bot_id}_{self.run_id}_{entry['sequence']}"
                    doc_ref = self.firestore_client.collection(self.COLLECTION).document(doc_id)
                    batch.set(doc_ref, entry)

                batch.commit()
                logging.getLogger(__name__).debug(f"✅ Flushed {len(entries)} logs to Firestore")
                self.log_buffer.clear()

            except Exception as e:
                logging.getLogger(__name__).error(f"❌ Log batch write failed: {e}")


class FirestoreLogHandler(logging.Handler):
    """
    Standard Python logging.Handler that routes records to LogPublisher.

    Attach to any logger to stream logs to Firestore:
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
