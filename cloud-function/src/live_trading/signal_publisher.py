"""
📡 Signal Publisher - Multi-backend support

Publishes trading signals to multiple destinations:
1. Firestore (default, already set up) - Real-time database
2. Cloud Pub/Sub (optional) - Fastest messaging queue
3. Local file (fallback) - Works without GCP

Your main app can consume signals via:
- Firestore real-time listeners (recommended)
- Pub/Sub subscriptions (fastest)
- HTTP API polling (simplest)
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, Optional, List
from enum import Enum

logger = logging.getLogger(__name__)


class SignalBackend(Enum):
    """Signal publishing backends"""
    FIRESTORE = "firestore"
    PUBSUB = "pubsub"
    FILE = "file"
    ALL = "all"  # Publish to all backends


class SignalPublisher:
    """
    Publishes trading signals to configured backends.
    
    Usage:
        publisher = SignalPublisher(backends=[SignalBackend.FIRESTORE])
        publisher.publish_signal({
            'epic': 'GOLD',
            'signal': 'BUY',
            'price': 1950.25,
            'sl': 1935.0,
            'tp': 1980.0
        })
    """
    
    def __init__(
        self,
        backends: List[SignalBackend] = None,
        firestore_collection: str = "trading_signals",
        pubsub_topic: str = "trading-signals",
        file_path: str = "signals.json",
        project_id: str = None
    ):
        """
        Initialize signal publisher
        
        Args:
            backends: List of backends to use (default: [FIRESTORE])
            firestore_collection: Firestore collection name
            pubsub_topic: Pub/Sub topic name
            file_path: Local file path for file backend
            project_id: GCP project ID (auto-detected if not provided)
        """
        self.backends = backends or [SignalBackend.FIRESTORE]
        self.firestore_collection = firestore_collection
        self.pubsub_topic = pubsub_topic
        self.file_path = file_path
        self.project_id = project_id or os.getenv('GOOGLE_CLOUD_PROJECT') or os.getenv('GCP_PROJECT_ID')
        
        # Initialize clients
        self.firestore_client = None
        self.pubsub_publisher = None
        
        self._init_backends()
    
    def _init_backends(self):
        """Initialize configured backends"""
        
        # Firestore
        if SignalBackend.FIRESTORE in self.backends or SignalBackend.ALL in self.backends:
            try:
                from google.cloud import firestore
                self.firestore_client = firestore.Client(project=self.project_id)
                logger.info(f"✅ Firestore publisher initialized (project: {self.project_id})")
            except Exception as e:
                logger.warning(f"⚠️ Firestore initialization failed: {e}")
                logger.warning("Signals will not be published to Firestore")
        
        # Pub/Sub
        if SignalBackend.PUBSUB in self.backends or SignalBackend.ALL in self.backends:
            try:
                from google.cloud import pubsub_v1
                self.pubsub_publisher = pubsub_v1.PublisherClient()
                # Get GCP project ID
                project_id = os.getenv('GCP_PROJECT_ID') or os.getenv('GOOGLE_CLOUD_PROJECT')
                if project_id:
                    self.pubsub_topic_path = self.pubsub_publisher.topic_path(
                        project_id, 
                        self.pubsub_topic
                    )
                    logger.info(f"✅ Pub/Sub publisher initialized (topic: {self.pubsub_topic})")
                else:
                    logger.warning("⚠️ GCP_PROJECT_ID not set, Pub/Sub disabled")
                    self.pubsub_publisher = None
            except Exception as e:
                logger.warning(f"⚠️ Pub/Sub initialization failed: {e}")
                logger.warning("Signals will not be published to Pub/Sub")
    
    def publish_signal(
        self,
        signal_data: Dict,
        signal_id: Optional[str] = None
    ) -> Dict[str, bool]:
        """
        Publish signal to all configured backends
        
        Args:
            signal_data: Signal data dictionary
            signal_id: Optional custom signal ID (auto-generated if None)
        
        Returns:
            Dict mapping backend name to success status
            
        Example signal_data:
            {
                'epic': 'GOLD',
                'signal': 'BUY',  # or 'SELL'
                'price': 1950.25,
                'sl': 1935.0,
                'tp': 1980.0,
                'timestamp': '2026-03-09T14:30:00',
                'strategy': 'SupertrendVWAP',
                'indicators': {
                    'supertrend': 1945.0,
                    'supertrend_direction': 1,
                    'sma_fast': 1948.0,
                    'sma_slow': 1940.0,
                    'atr': 15.0
                }
            }
        """
        results = {}
        
        # Generate signal ID if not provided
        if signal_id is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            signal_id = f"{signal_data.get('epic', 'UNKNOWN')}_{timestamp}"
        
        # Add metadata
        enriched_data = {
            'signal_id': signal_id,
            'timestamp': signal_data.get('timestamp', datetime.now().isoformat()),
            'received_at': datetime.now().isoformat(),
            **signal_data
        }
        
        # Publish to Firestore
        if self.firestore_client:
            results['firestore'] = self._publish_to_firestore(signal_id, enriched_data)
        
        # Publish to Pub/Sub
        if self.pubsub_publisher:
            results['pubsub'] = self._publish_to_pubsub(enriched_data)
        
        # Publish to file (local fallback)
        if SignalBackend.FILE in self.backends or SignalBackend.ALL in self.backends:
            results['file'] = self._publish_to_file(enriched_data)
        
        # Log summary
        success_count = sum(1 for v in results.values() if v)
        total_count = len(results)
        logger.info(f"📡 Signal published: {success_count}/{total_count} backends succeeded")
        
        return results
    
    def _publish_to_firestore(self, signal_id: str, data: Dict) -> bool:
        """Publish signal to Firestore"""
        try:
            doc_ref = self.firestore_client.collection(self.firestore_collection).document(signal_id)
            doc_ref.set(data)
            logger.info(f"✅ Firestore: Signal {signal_id} published")
            return True
        except Exception as e:
            logger.error(f"❌ Firestore publish failed: {e}")
            return False
    
    def _publish_to_pubsub(self, data: Dict) -> bool:
        """Publish signal to Pub/Sub"""
        try:
            message_data = json.dumps(data).encode('utf-8')
            future = self.pubsub_publisher.publish(self.pubsub_topic_path, message_data)
            message_id = future.result(timeout=5.0)
            logger.info(f"✅ Pub/Sub: Signal published (message_id: {message_id})")
            return True
        except Exception as e:
            logger.error(f"❌ Pub/Sub publish failed: {e}")
            return False
    
    def _publish_to_file(self, data: Dict) -> bool:
        """Publish signal to local file (append mode)"""
        try:
            # Read existing signals
            signals = []
            if os.path.exists(self.file_path):
                with open(self.file_path, 'r') as f:
                    signals = json.load(f)
            
            # Append new signal
            signals.append(data)
            
            # Keep only last 1000 signals
            if len(signals) > 1000:
                signals = signals[-1000:]
            
            # Write back
            with open(self.file_path, 'w') as f:
                json.dump(signals, f, indent=2)
            
            logger.info(f"✅ File: Signal appended to {self.file_path}")
            return True
        except Exception as e:
            logger.error(f"❌ File publish failed: {e}")
            return False
    
    def get_recent_signals(
        self,
        limit: int = 10,
        epic: Optional[str] = None
    ) -> List[Dict]:
        """
        Get recent signals from Firestore
        
        Args:
            limit: Maximum number of signals to return
            epic: Filter by epic (optional)
        
        Returns:
            List of signal dictionaries, newest first
        """
        if not self.firestore_client:
            logger.warning("Firestore not initialized, cannot fetch signals")
            return []
        
        try:
            query = self.firestore_client.collection(self.firestore_collection)
            
            # Filter by epic if specified
            if epic:
                query = query.where('epic', '==', epic)
            
            # Order by timestamp descending
            query = query.order_by('timestamp', direction=firestore.Query.DESCENDING)
            
            # Limit results
            query = query.limit(limit)
            
            # Execute query
            docs = query.stream()
            
            signals = [doc.to_dict() for doc in docs]
            logger.info(f"📊 Retrieved {len(signals)} recent signals from Firestore")
            return signals
            
        except Exception as e:
            logger.error(f"❌ Failed to fetch signals from Firestore: {e}")
            return []
    
    def delete_old_signals(self, days_old: int = 7) -> int:
        """
        Delete signals older than specified days
        
        Args:
            days_old: Delete signals older than this many days
        
        Returns:
            Number of signals deleted
        """
        if not self.firestore_client:
            logger.warning("Firestore not initialized, cannot delete signals")
            return 0
        
        try:
            from datetime import timedelta
            from google.cloud import firestore
            
            cutoff_date = datetime.now() - timedelta(days=days_old)
            cutoff_iso = cutoff_date.isoformat()
            
            # Query old signals
            query = self.firestore_client.collection(self.firestore_collection)\
                .where('timestamp', '<', cutoff_iso)
            
            # Delete in batches
            deleted_count = 0
            batch = self.firestore_client.batch()
            batch_size = 0
            
            for doc in query.stream():
                batch.delete(doc.reference)
                batch_size += 1
                
                # Commit batch every 500 docs
                if batch_size >= 500:
                    batch.commit()
                    deleted_count += batch_size
                    batch = self.firestore_client.batch()
                    batch_size = 0
            
            # Commit remaining
            if batch_size > 0:
                batch.commit()
                deleted_count += batch_size
            
            logger.info(f"🗑️ Deleted {deleted_count} signals older than {days_old} days")
            return deleted_count
            
        except Exception as e:
            logger.error(f"❌ Failed to delete old signals: {e}")
            return 0


# Convenience function for quick signal publishing
def publish_signal(signal_data: Dict, backends: List[SignalBackend] = None) -> Dict[str, bool]:
    """
    Quick publish signal to configured backends
    
    Usage:
        from src.live_trading.signal_publisher import publish_signal, SignalBackend
        
        publish_signal({
            'epic': 'GOLD',
            'signal': 'BUY',
            'price': 1950.25,
            'sl': 1935.0,
            'tp': 1980.0
        })
    """
    publisher = SignalPublisher(backends=backends)
    return publisher.publish_signal(signal_data)
