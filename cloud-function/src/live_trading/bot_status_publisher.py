"""
📊 Bot Status Publisher - Track bot health and status in Firestore

Publishes bot status for monitoring:
- Bot running/stopped status
- Last heartbeat timestamp
- Current epic being traded
- Mode (AUTO/SIGNAL_ONLY)
- Position count
- Statistics (signals generated, orders placed, etc.)
"""

import os
import logging
from datetime import datetime
from typing import Dict, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class BotStatus(Enum):
    """Bot status states"""
    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


class BotStatusPublisher:
    """
    Publishes bot status and heartbeat to Firestore.
    
    Usage:
        publisher = BotStatusPublisher(bot_id='gold_m5_bot')
        publisher.update_status(BotStatus.RUNNING, epic='GOLD', mode='AUTO')
        publisher.heartbeat()  # Call every 30-60 seconds
        publisher.update_statistics({'signals_generated': 5, 'orders_placed': 3})
    """
    
    def __init__(
        self,
        bot_id: str = "gold_m5_bot",
        collection: str = "bot_status",
        project_id: str = None
    ):
        """
        Initialize bot status publisher
        
        Args:
            bot_id: Unique identifier for this bot instance
            collection: Firestore collection name
            project_id: GCP project ID (auto-detected if not provided)
        """
        self.bot_id = bot_id
        self.collection = collection
        self.project_id = project_id or os.getenv('GOOGLE_CLOUD_PROJECT') or os.getenv('GCP_PROJECT_ID')
        
        # Initialize Firestore client
        self.firestore_client = None
        self._init_firestore()
        
        # Internal state tracking
        self.current_status = None
        self.start_time = None
        self.statistics = {
            'signals_generated': 0,
            'orders_placed': 0,
            'positions_closed': 0,
            'total_pnl': 0.0
        }
    
    def _init_firestore(self):
        """Initialize Firestore client"""
        try:
            from google.cloud import firestore
            self.firestore_client = firestore.Client(project=self.project_id)
            logger.info(f"✅ Bot Status Publisher initialized (project: {self.project_id}, collection: {self.collection})")
        except Exception as e:
            logger.warning(f"⚠️ Firestore initialization failed: {e}")
            logger.warning("Bot status will not be published to Firestore")
    
    def update_status(
        self,
        status: BotStatus,
        epic: Optional[str] = None,
        mode: Optional[str] = None,
        error: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        Update bot status in Firestore
        
        Args:
            status: Bot status (STARTING, RUNNING, STOPPED, ERROR)
            epic: Trading instrument (e.g., 'GOLD')
            mode: Trading mode ('AUTO' or 'SIGNAL_ONLY')
            error: Error message if status is ERROR
            metadata: Additional metadata dict
        
        Returns:
            True if successful, False otherwise
        """
        if not self.firestore_client:
            return False
        
        try:
            # Track start time when bot starts
            if status == BotStatus.STARTING or status == BotStatus.RUNNING:
                if self.start_time is None:
                    self.start_time = datetime.now()
            
            self.current_status = status.value
            
            # Build status document
            status_doc = {
                'bot_id': self.bot_id,
                'status': status.value,
                'last_updated': datetime.now().isoformat(),
                'last_heartbeat': datetime.now().isoformat(),
            }
            
            # Add optional fields
            if epic:
                status_doc['epic'] = epic
            if mode:
                status_doc['mode'] = mode
            if error:
                status_doc['error'] = error
            if self.start_time:
                status_doc['start_time'] = self.start_time.isoformat()
                uptime_seconds = (datetime.now() - self.start_time).total_seconds()
                status_doc['uptime_seconds'] = int(uptime_seconds)
            
            # Add statistics
            status_doc['statistics'] = self.statistics.copy()
            
            # Add custom metadata
            if metadata:
                status_doc['metadata'] = metadata
            
            # Write to Firestore
            doc_ref = self.firestore_client.collection(self.collection).document(self.bot_id)
            doc_ref.set(status_doc, merge=True)
            
            logger.info(f"✅ Bot status updated: {status.value}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Bot status update failed: {e}")
            return False
    
    def heartbeat(self) -> bool:
        """
        Send heartbeat to indicate bot is alive
        Should be called periodically (every 30-60 seconds)
        
        Returns:
            True if successful, False otherwise
        """
        if not self.firestore_client:
            return False
        
        try:
            # Build heartbeat update
            heartbeat_doc = {
                'last_heartbeat': datetime.now().isoformat(),
            }
            
            # Add uptime if we have start time
            if self.start_time:
                uptime_seconds = (datetime.now() - self.start_time).total_seconds()
                heartbeat_doc['uptime_seconds'] = int(uptime_seconds)
            
            # Update Firestore (merge to preserve other fields)
            doc_ref = self.firestore_client.collection(self.collection).document(self.bot_id)
            doc_ref.set(heartbeat_doc, merge=True)
            
            logger.debug(f"💓 Heartbeat sent")
            return True
            
        except Exception as e:
            logger.error(f"❌ Heartbeat failed: {e}")
            return False
    
    def update_statistics(self, stats: Dict) -> bool:
        """
        Update bot statistics
        
        Args:
            stats: Dictionary with statistics to update (e.g., {'signals_generated': 5})
        
        Returns:
            True if successful, False otherwise
        """
        if not self.firestore_client:
            return False
        
        try:
            # Update internal statistics
            self.statistics.update(stats)
            
            # Update Firestore
            doc_ref = self.firestore_client.collection(self.collection).document(self.bot_id)
            doc_ref.set({
                'statistics': self.statistics.copy(),
                'last_updated': datetime.now().isoformat()
            }, merge=True)
            
            logger.debug(f"📊 Statistics updated: {stats}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Statistics update failed: {e}")
            return False
    
    def increment_stat(self, stat_name: str, amount: int = 1) -> bool:
        """
        Increment a statistic counter
        
        Args:
            stat_name: Name of the statistic to increment
            amount: Amount to increment by (default: 1)
        
        Returns:
            True if successful, False otherwise
        """
        if stat_name in self.statistics:
            self.statistics[stat_name] += amount
            return self.update_statistics({stat_name: self.statistics[stat_name]})
        else:
            logger.warning(f"⚠️ Unknown statistic: {stat_name}")
            return False
    
    def increment_signal(self) -> bool:
        """Increment signals_generated counter"""
        return self.increment_stat('signals_generated')
    
    def increment_order(self) -> bool:
        """Increment orders_placed counter"""
        return self.increment_stat('orders_placed')
    
    def increment_position_closed(self) -> bool:
        """Increment positions_closed counter"""
        return self.increment_stat('positions_closed')
    
    def get_current_status(self) -> Optional[Dict]:
        """
        Get current bot status from Firestore
        
        Returns:
            Status document dict or None if failed
        """
        if not self.firestore_client:
            return None
        
        try:
            doc_ref = self.firestore_client.collection(self.collection).document(self.bot_id)
            doc = doc_ref.get()
            
            if doc.exists:
                return doc.to_dict()
            else:
                logger.warning(f"⚠️ Bot status document not found: {self.bot_id}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Failed to get bot status: {e}")
            return None
