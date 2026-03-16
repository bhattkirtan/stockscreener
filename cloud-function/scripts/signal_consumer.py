"""
📥 Signal Consumer Examples

Shows how your main application (capital-connect React app or cloud-function backend) 
can consume trading signals published by the trading bot.

Three options:
1. Firestore Real-time Listener (⚡ Fastest - 50-200ms)
2. Firestore Polling (📊 Simple - 1-5s latency)
3. Pub/Sub Subscriber (🚀 Ultra-fast - 10-50ms, requires setup)
"""

import asyncio
from datetime import datetime, timedelta
from typing import Callable, Dict, Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =============================================================================
# OPTION 1: Firestore Real-Time Listener (RECOMMENDED)
# =============================================================================

class FirestoreSignalListener:
    """
    Real-time listener for trading signals from Firestore.
    Receives signals as soon as they're published (~50-200ms latency).
    
    Perfect for: Web apps, dashboards, real-time notifications
    """
    
    def __init__(self, collection_name: str = 'trading_signals'):
        from google.cloud import firestore
        self.db = firestore.Client()
        self.collection_name = collection_name
        self.unsubscribe = None
    
    def start_listening(self, callback: Callable[[Dict], None], epic: Optional[str] = None):
        """
        Start listening for new signals
        
        Args:
            callback: Function to call when signal received
            epic: Optional filter for specific instrument (e.g., 'GOLD')
        
        Example:
            def handle_signal(signal):
                print(f"New signal: {signal['signal']} {signal['epic']} @ {signal['price']}")
            
            listener = FirestoreSignalListener()
            listener.start_listening(handle_signal, epic='GOLD')
        """
        query = self.db.collection(self.collection_name)
        
        # Filter by epic if specified
        if epic:
            query = query.where('epic', '==', epic)
        
        # Only listen to recent signals (last 1 hour)
        cutoff = datetime.now() - timedelta(hours=1)
        query = query.where('timestamp', '>=', cutoff.isoformat())
        
        # Define callback
        def on_snapshot(doc_snapshot, changes, read_time):
            for change in changes:
                if change.type.name == 'ADDED':
                    signal = change.document.to_dict()
                    logger.info(f"📥 New signal received: {signal['signal']} {signal['epic']}")
                    callback(signal)
        
        # Start watching
        self.unsubscribe = query.on_snapshot(on_snapshot)
        logger.info(f"👂 Listening for signals in Firestore collection: {self.collection_name}")
    
    def stop_listening(self):
        """Stop listening"""
        if self.unsubscribe:
            self.unsubscribe()
            logger.info("🛑 Stopped listening for signals")


# =============================================================================
# OPTION 2: Firestore Polling (Simple)
# =============================================================================

class FirestoreSignalPoller:
    """
    Poll Firestore every N seconds for new signals.
    Simpler than real-time listener, but higher latency (~1-5s).
    
    Perfect for: Batch processing, periodic checks, simple integrations
    """
    
    def __init__(self, collection_name: str = 'trading_signals'):
        from google.cloud import firestore
        self.db = firestore.Client()
        self.collection_name = collection_name
        self.last_check: Optional[datetime] = None
    
    def get_new_signals(self, epic: Optional[str] = None) -> list:
        """
        Get signals since last check
        
        Args:
            epic: Optional filter for specific instrument
        
        Returns:
            List of new signal dictionaries
        """
        query = self.db.collection(self.collection_name)
        
        # Filter by epic
        if epic:
            query = query.where('epic', '==', epic)
        
        # Get signals since last check
        if self.last_check:
            query = query.where('timestamp', '>', self.last_check.isoformat())
        else:
            # First check: get last 10 minutes
            cutoff = datetime.now() - timedelta(minutes=10)
            query = query.where('timestamp', '>=', cutoff.isoformat())
        
        # Order by timestamp
        query = query.order_by('timestamp')
        
        # Execute
        docs = query.stream()
        signals = [doc.to_dict() for doc in docs]
        
        # Update last check time
        self.last_check = datetime.now()
        
        logger.info(f"📊 Found {len(signals)} new signals")
        return signals
    
    async def poll_forever(
        self,
        callback: Callable[[Dict], None],
        interval_seconds: int = 2,
        epic: Optional[str] = None
    ):
        """
        Poll for new signals every N seconds
        
        Args:
            callback: Function to call for each new signal
            interval_seconds: Seconds between polls
            epic: Optional filter for specific instrument
        
        Example:
            poller = FirestoreSignalPoller()
            await poller.poll_forever(
                callback=lambda s: print(f"Signal: {s['signal']} @ {s['price']}"),
                interval_seconds=2,
                epic='GOLD'
            )
        """
        logger.info(f"🔄 Starting poller (interval: {interval_seconds}s)")
        
        while True:
            try:
                signals = self.get_new_signals(epic=epic)
                for signal in signals:
                    callback(signal)
            except Exception as e:
                logger.error(f"❌ Polling error: {e}")
            
            await asyncio.sleep(interval_seconds)


# =============================================================================
# OPTION 3: Pub/Sub Subscriber (Ultra-Fast, requires setup)
# =============================================================================

class PubSubSignalSubscriber:
    """
    Subscribe to signals via Cloud Pub/Sub.
    Lowest latency (~10-50ms) but requires Pub/Sub topic setup.
    
    Perfect for: High-frequency trading, microsecond-sensitive apps
    """
    
    def __init__(
        self,
        project_id: str,
        subscription_name: str = 'trading-signals-sub'
    ):
        from google.cloud import pubsub_v1
        self.subscriber = pubsub_v1.SubscriberClient()
        self.subscription_path = self.subscriber.subscription_path(
            project_id,
            subscription_name
        )
    
    def start_listening(self, callback: Callable[[Dict], None]):
        """
        Start listening for signals via Pub/Sub
        
        Args:
            callback: Function to call when signal received
        
        Example:
            subscriber = PubSubSignalSubscriber(project_id='my-project')
            subscriber.start_listening(
                lambda signal: print(f"Signal: {signal['signal']}")
            )
        """
        def pubsub_callback(message):
            import json
            signal = json.loads(message.data.decode('utf-8'))
            logger.info(f"⚡ Pub/Sub signal: {signal['signal']} {signal['epic']}")
            callback(signal)
            message.ack()
        
        # Start streaming pull
        streaming_pull_future = self.subscriber.subscribe(
            self.subscription_path,
            callback=pubsub_callback
        )
        
        logger.info(f"👂 Listening to Pub/Sub: {self.subscription_path}")
        
        # Keep listening
        try:
            streaming_pull_future.result()
        except KeyboardInterrupt:
            streaming_pull_future.cancel()


# =============================================================================
# USAGE EXAMPLES
# =============================================================================

def example_signal_handler(signal: Dict):
    """Example callback function that handles incoming signals"""
    print("=" * 80)
    print(f"📡 NEW SIGNAL RECEIVED")
    print(f"   Epic: {signal['epic']}")
    print(f"   Direction: {signal['signal']}")
    print(f"   Price: {signal['price']:.2f}")
    print(f"   Stop Loss: {signal['sl']:.2f}")
    print(f"   Take Profit: {signal['tp']:.2f}")
    print(f"   Timestamp: {signal['timestamp']}")
    print(f"   Mode: {signal['mode']}")
    print("=" * 80)
    
    # Your app logic here:
    # - Send push notification
    # - Update UI dashboard
    # - Execute trade
    # - Log to database
    # - Send email/SMS alert


async def example_1_realtime_listener():
    """Example 1: Firestore real-time listener (RECOMMENDED)"""
    listener = FirestoreSignalListener()
    listener.start_listening(example_signal_handler, epic='GOLD')
    
    # Keep running
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        listener.stop_listening()


async def example_2_polling():
    """Example 2: Firestore polling"""
    poller = FirestoreSignalPoller()
    await poller.poll_forever(
        callback=example_signal_handler,
        interval_seconds=2,
        epic='GOLD'
    )


def example_3_pubsub():
    """Example 3: Pub/Sub subscriber (requires setup)"""
    import os
    project_id = os.getenv('GCP_PROJECT_ID')
    
    if not project_id:
        print("❌ Set GCP_PROJECT_ID environment variable")
        return
    
    subscriber = PubSubSignalSubscriber(project_id)
    subscriber.start_listening(example_signal_handler)


# =============================================================================
# FOR YOUR CAPITAL-CONNECT REACT APP
# =============================================================================

class HTTPSignalAPI:
    """
    HTTP API endpoints for your capital-connect frontend.
    Add these to your cloud-function main.py
    """
    
    def __init__(self):
        from google.cloud import firestore
        self.db = firestore.Client()
    
    def get_recent_signals(self, limit: int = 10, epic: Optional[str] = None):
        """
        GET /api/signals?limit=10&epic=GOLD
        
        Returns recent signals for your React dashboard
        """
        query = self.db.collection('trading_signals')
        
        if epic:
            query = query.where('epic', '==', epic)
        
        query = query.order_by('timestamp', direction='DESCENDING')\
                    .limit(limit)
        
        docs = query.stream()
        return [doc.to_dict() for doc in docs]
    
    def get_latest_signal(self, epic: str):
        """
        GET /api/signals/latest?epic=GOLD
        
        Returns just the latest signal for an epic
        """
        query = self.db.collection('trading_signals')\
                    .where('epic', '==', epic)\
                    .order_by('timestamp', direction='DESCENDING')\
                    .limit(1)
        
        docs = list(query.stream())
        if docs:
            return docs[0].to_dict()
        return None


# =============================================================================
# MAIN: Run examples
# =============================================================================

if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python signal_consumer.py realtime    # Real-time Firestore listener")
        print("  python signal_consumer.py poll        # Firestore polling")
        print("  python signal_consumer.py pubsub      # Pub/Sub subscriber")
        sys.exit(1)
    
    mode = sys.argv[1]
    
    if mode == 'realtime':
        asyncio.run(example_1_realtime_listener())
    elif mode == 'poll':
        asyncio.run(example_2_polling())
    elif mode == 'pubsub':
        example_3_pubsub()
    else:
        print(f"Unknown mode: {mode}")
