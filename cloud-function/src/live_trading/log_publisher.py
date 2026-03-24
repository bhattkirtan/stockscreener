"""
📝 Log Publisher - Stream Bot Logs to Firestore

Publishes recent bot logs to Firestore for real-time UI streaming.
- Batches log writes (every 5 seconds or 20 lines)
- Keeps only last 200 log entries (auto-cleanup)
- TTL: Logs older than 24 hours are auto-deleted
"""

import os
import logging
from datetime import datetime, timedelta
from collections import deque
from threading import RLock, Timer
from typing import Optional


class LogPublisher:
    """Publishes bot logs to Firestore in batches"""
    
    COLLECTION = "bot_logs"
    MAX_LOGS_IN_MEMORY = 200  # Keep last 200 log entries
    BATCH_SIZE = 20  # Write after 20 log entries
    BATCH_INTERVAL = 5.0  # Or write every 5 seconds
    TTL_HOURS = 24  # Auto-delete logs older than 24 hours
    
    def __init__(self, bot_id: str, run_id: str, project_id: Optional[str] = None):
        """
        Initialize log publisher
        
        Args:
            bot_id: Bot identifier (e.g., 'gold_m5_bot')
            run_id: Current run ID (timestamp-based)
            project_id: GCP project ID (optional, defaults to env var)
        """
        self.bot_id = bot_id
        self.run_id = run_id
        self.project_id = project_id or os.getenv('GCP_PROJECT_ID', 'double-venture-442318-k8')
        self.collection = self.COLLECTION
        
        self.log_buffer = deque(maxlen=self.BATCH_SIZE)
        self.lock = RLock()  # Reentrant lock to prevent deadlock when flush called from publish_log
        self.last_write = datetime.now()
        self.sequence_number = 0
        self._timer: Optional[Timer] = None
        self._running = False
        
        # Calculate TTL timestamp
        self.ttl_timestamp = datetime.now() + timedelta(hours=self.TTL_HOURS)
        
        # Initialize Firestore
        self.firestore_client = None
        self._init_firestore()
    
    def _init_firestore(self):
        """Initialize Firestore client"""
        try:
            from google.cloud import firestore
            self.firestore_client = firestore.Client(project=self.project_id)
            logging.info(f"✅ Log Publisher initialized (project: {self.project_id}, collection: {self.collection})")
        except Exception as e:
            logging.warning(f"⚠️ Firestore initialization failed: {e}")
            logging.warning("Logs will not be published to Firestore")
    
    def start_batch_writer(self):
        """Start background timer for periodic batch writes"""
        if not self._running:
            self._running = True
            self._schedule_flush()
            logging.info(f"📝 Log batch writer started (interval: {self.BATCH_INTERVAL}s)")
    
    def stop_batch_writer(self):
        """Stop background batch writer and flush remaining logs"""
        self._running = False
        if self._timer:
            self._timer.cancel()
            self._timer = None
        self._flush()
        logging.info("📝 Log batch writer stopped")
    
    def _schedule_flush(self):
        """Schedule next periodic flush"""
        if self._running:
            self._timer = Timer(self.BATCH_INTERVAL, self._periodic_flush)
            self._timer.daemon = True
            self._timer.start()
    
    def _periodic_flush(self):
        """Periodic flush callback"""
        try:
            if len(self.log_buffer) > 0:
                self._flush()
        finally:
            # Schedule next flush
            self._schedule_flush()
    
    def publish_log(self, level: str, message: str, logger_name: str = "bot"):
        """
        Publish a single log entry (buffered for batch write)
        
        Args:
            level: Log level (INFO, WARNING, ERROR, etc.)
            message: Log message
            logger_name: Logger name (default: 'bot')
        """
        with self.lock:
            timestamp = datetime.now()
            self.sequence_number += 1
            
            log_entry = {
                "bot_id": self.bot_id,
                "run_id": self.run_id,
                "timestamp": timestamp,
                "sequence": self.sequence_number,
                "level": level,
                "logger": logger_name,
                "message": message,
                "ttl": self.ttl_timestamp  # For Firestore TTL policy
            }
            
            self.log_buffer.append(log_entry)
            
            # Flush if buffer is full
            if len(self.log_buffer) >= self.BATCH_SIZE:
                self._flush()
    
    def _flush(self):
        """Write all buffered logs to Firestore"""
        if not self.firestore_client:
            return
        
        with self.lock:
            if not self.log_buffer:
                return
            
            try:
                count = len(self.log_buffer)
                batch = self.firestore_client.batch()
                
                # Write all buffered logs
                for log_entry in self.log_buffer:
                    # Document ID: {bot_id}_{run_id}_{sequence}
                    doc_id = f"{self.bot_id}_{self.run_id}_{log_entry['sequence']}"
                    doc_ref = self.firestore_client.collection(self.COLLECTION).document(doc_id)
                    batch.set(doc_ref, log_entry)
                
                # Commit batch
                batch.commit()
                logging.debug(f"✅ Flushed {count} logs to Firestore")
                
                self.log_buffer.clear()
                self.last_write = datetime.now()
                
            except Exception as e:
                logging.error(f"❌ Failed to write log batch to Firestore: {e}")
    
    def cleanup_old_logs(self, keep_runs: int = 5):
        """
        Clean up logs from old bot runs (keeps only recent N runs)
        
        Args:
            keep_runs: Number of recent runs to keep (default: 5)
        """
        try:
            # Query logs for this bot, grouped by run_id
            logs_ref = self.db.db.collection(self.COLLECTION)
            query = logs_ref.where("bot_id", "==", self.bot_id).order_by("run_id", direction="DESCENDING")
            
            # Get unique run_ids
            run_ids = set()
            for doc in query.stream():
                run_ids.add(doc.get("run_id"))
                if len(run_ids) > keep_runs:
                    # Found old run, delete its logs
                    old_run_id = doc.get("run_id")
                    self._delete_run_logs(old_run_id)
                    break
        
        except Exception as e:
            logging.error(f"❌ Failed to cleanup old logs: {e}")
    
    def _delete_run_logs(self, run_id: str):
        """Delete all logs for a specific run_id"""
        if not self.firestore_client:
            return
        
        try:
            logs_ref = self.firestore_client.collection(self.COLLECTION)
            query = logs_ref.where("bot_id", "==", self.bot_id).where("run_id", "==", run_id)
            
            batch = self.db.db.batch()
            count = 0
            
            for doc in query.stream():
                batch.delete(doc.reference)
                count += 1
                
                # Firestore batch limit is 500 operations
                if count >= 500:
                    batch.commit()
                    batch = self.db.db.batch()
                    count = 0
            
            if count > 0:
                batch.commit()
            
            logging.info(f"🗑️  Deleted {count} logs for run {run_id}")
        
        except Exception as e:
            logging.error(f"❌ Failed to delete logs for run {run_id}: {e}")


class FirestoreLogHandler(logging.Handler):
    """Custom logging handler that publishes to Firestore via LogPublisher"""
    
    def __init__(self, log_publisher: LogPublisher, level=logging.INFO):
        """
        Initialize Firestore log handler
        
        Args:
            log_publisher: LogPublisher instance
            level: Minimum log level to publish
        """
        super().__init__(level)
        self.log_publisher = log_publisher
    
    def emit(self, record: logging.LogRecord):
        """Emit a log record to Firestore"""
        try:
            # Format the message
            message = self.format(record)
            
            # Publish to Firestore (buffered)
            self.log_publisher.publish_log(
                level=record.levelname,
                message=message,
                logger_name=record.name
            )
        
        except Exception:
            self.handleError(record)
