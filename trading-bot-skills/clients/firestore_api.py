"""
Firestore API Client Wrapper

Handles Cloud Firestore operations for position and trade storage.
"""
import logging
from typing import Dict, Optional, List, Any
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    from google.cloud import firestore
    FIRESTORE_AVAILABLE = True
except ImportError:
    FIRESTORE_AVAILABLE = False
    logger.warning("⚠️ google-cloud-firestore not installed - Storage Skill will use mock mode")


class FirestoreAPIClient:
    """
    Firestore client for position and trade persistence
    
    Features:
    - Position CRUD operations
    - Trade history logging
    - Bot status tracking
    - Signal logging
    """
    
    def __init__(
        self,
        project_id: Optional[str] = None,
        credentials_path: Optional[str] = None,
        mock_mode: bool = False
    ):
        """
        Initialize Firestore client
        
        Args:
            project_id: GCP project ID (or set FIRESTORE_PROJECT_ID env var)
            credentials_path: Path to service account JSON (or set GOOGLE_APPLICATION_CREDENTIALS env var)
            mock_mode: Use mock mode for testing (default: False)
        """
        import os
        
        # Use env vars as fallback
        self.project_id = project_id or os.getenv('FIRESTORE_PROJECT_ID')
        credentials_path = credentials_path or os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
        
        self.mock_mode = mock_mode or not FIRESTORE_AVAILABLE
        self.db = None
        
        if not self.mock_mode:
            try:
                if credentials_path:
                    import os
                    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = credentials_path
                
                if project_id:
                    self.db = firestore.Client(project=project_id)
                else:
                    self.db = firestore.Client()
                
                logger.info(f"✅ Firestore client initialized (project: {project_id or 'default'})")
            
            except Exception as e:
                logger.error(f"❌ Failed to initialize Firestore: {e}")
                logger.warning("⚠️ Falling back to mock mode")
                self.mock_mode = True
        
        if self.mock_mode:
            logger.warning("⚠️ FirestoreAPIClient running in MOCK MODE - no data will be persisted")
            self._mock_db = {}  # Simple in-memory mock
    
    # ────────────────────────────────────────────────────────────────────
    #  Position Management
    # ────────────────────────────────────────────────────────────────────
    
    def save_position(
        self,
        collection: str,
        deal_id: str,
        position_data: Dict[str, Any]
    ) -> bool:
        """
        Save or update a position
        
        Args:
            collection: Firestore collection name (e.g., 'active_positions')
            deal_id: Deal ID (used as document ID)
            position_data: Position data dict
            
        Returns:
            bool indicating success
        """
        if self.mock_mode:
            logger.info(f"💾 [MOCK] Saving position: {collection}/{deal_id}")
            if collection not in self._mock_db:
                self._mock_db[collection] = {}
            self._mock_db[collection][deal_id] = {
                **position_data,
                'updated_at': datetime.now().isoformat()
            }
            return True
        
        try:
            # Add timestamp
            position_data['updated_at'] = firestore.SERVER_TIMESTAMP
            
            # Save to Firestore
            doc_ref = self.db.collection(collection).document(deal_id)
            doc_ref.set(position_data, merge=True)
            
            logger.info(f"💾 Position saved: {collection}/{deal_id}")
            return True
        
        except Exception as e:
            logger.error(f"❌ Failed to save position {deal_id}: {e}")
            return False
    
    def get_position(
        self,
        collection: str,
        deal_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve a position by deal_id
        
        Args:
            collection: Firestore collection name
            deal_id: Deal ID
            
        Returns:
            Position data dict or None if not found
        """
        if self.mock_mode:
            logger.info(f"📖 [MOCK] Getting position: {collection}/{deal_id}")
            return self._mock_db.get(collection, {}).get(deal_id)
        
        try:
            doc_ref = self.db.collection(collection).document(deal_id)
            doc = doc_ref.get()
            
            if doc.exists:
                logger.info(f"📖 Position retrieved: {collection}/{deal_id}")
                return doc.to_dict()
            else:
                logger.info(f"📖 Position not found: {collection}/{deal_id}")
                return None
        
        except Exception as e:
            logger.error(f"❌ Failed to get position {deal_id}: {e}")
            return None
    
    def get_all_positions(self, collection: str) -> List[Dict[str, Any]]:
        """
        Get all positions from a collection
        
        Args:
            collection: Firestore collection name
            
        Returns:
            List of position dicts
        """
        if self.mock_mode:
            logger.info(f"📖 [MOCK] Getting all positions from: {collection}")
            return list(self._mock_db.get(collection, {}).values())
        
        try:
            docs = self.db.collection(collection).stream()
            positions = [doc.to_dict() for doc in docs]
            
            logger.info(f"📖 Retrieved {len(positions)} positions from {collection}")
            return positions
        
        except Exception as e:
            logger.error(f"❌ Failed to get positions from {collection}: {e}")
            return []
    
    def close_position(
        self,
        collection: str,
        deal_id: str,
        close_data: Dict[str, Any]
    ) -> bool:
        """
        Mark a position as closed with exit details
        
        Args:
            collection: Firestore collection name
            deal_id: Deal ID
            close_data: Close data (exit_price, exit_time, pnl, etc.)
            
        Returns:
            bool indicating success
        """
        if self.mock_mode:
            logger.info(f"🔒 [MOCK] Closing position: {collection}/{deal_id}")
            if collection in self._mock_db and deal_id in self._mock_db[collection]:
                self._mock_db[collection][deal_id].update({
                    **close_data,
                    'status': 'CLOSED',
                    'closed_at': datetime.now().isoformat()
                })
            return True
        
        try:
            doc_ref = self.db.collection(collection).document(deal_id)
            
            # Update with close data and mark as closed
            update_data = {
                **close_data,
                'status': 'CLOSED',
                'closed_at': firestore.SERVER_TIMESTAMP
            }
            
            doc_ref.update(update_data)
            
            logger.info(f"🔒 Position closed: {collection}/{deal_id}")
            return True
        
        except Exception as e:
            logger.error(f"❌ Failed to close position {deal_id}: {e}")
            return False
    
    def delete_position(self, collection: str, deal_id: str) -> bool:
        """
        Delete a position document
        
        Args:
            collection: Firestore collection name
            deal_id: Deal ID
            
        Returns:
            bool indicating success
        """
        if self.mock_mode:
            logger.info(f"🗑️ [MOCK] Deleting position: {collection}/{deal_id}")
            if collection in self._mock_db and deal_id in self._mock_db[collection]:
                del self._mock_db[collection][deal_id]
            return True
        
        try:
            self.db.collection(collection).document(deal_id).delete()
            logger.info(f"🗑️ Position deleted: {collection}/{deal_id}")
            return True
        
        except Exception as e:
            logger.error(f"❌ Failed to delete position {deal_id}: {e}")
            return False
    
    # ────────────────────────────────────────────────────────────────────
    #  Signal & Trade Logging
    # ────────────────────────────────────────────────────────────────────
    
    def log_signal(
        self,
        collection: str,
        signal_data: Dict[str, Any]
    ) -> bool:
        """
        Log a trading signal
        
        Args:
            collection: Firestore collection name (e.g., 'signals')
            signal_data: Signal data dict
            
        Returns:
            bool indicating success
        """
        if self.mock_mode:
            logger.info(f"📝 [MOCK] Logging signal to: {collection}")
            return True
        
        try:
            # Add timestamp and create document
            signal_data['timestamp'] = firestore.SERVER_TIMESTAMP
            
            # Auto-generate document ID
            self.db.collection(collection).add(signal_data)
            
            logger.info(f"📝 Signal logged to {collection}")
            return True
        
        except Exception as e:
            logger.error(f"❌ Failed to log signal: {e}")
            return False
    
    def log_trade(
        self,
        collection: str,
        trade_data: Dict[str, Any]
    ) -> bool:
        """
        Log a completed trade
        
        Args:
            collection: Firestore collection name (e.g., 'trade_history')
            trade_data: Trade data dict
            
        Returns:
            bool indicating success
        """
        if self.mock_mode:
            logger.info(f"📝 [MOCK] Logging trade to: {collection}")
            return True
        
        try:
            # Add timestamp
            trade_data['logged_at'] = firestore.SERVER_TIMESTAMP
            
            # Use deal_id as document ID if present
            deal_id = trade_data.get('deal_id')
            if deal_id:
                self.db.collection(collection).document(deal_id).set(trade_data)
            else:
                self.db.collection(collection).add(trade_data)
            
            logger.info(f"📝 Trade logged to {collection}")
            return True
        
        except Exception as e:
            logger.error(f"❌ Failed to log trade: {e}")
            return False
    
    # ────────────────────────────────────────────────────────────────────
    #  Bot Status
    # ────────────────────────────────────────────────────────────────────
    
    def update_bot_status(
        self,
        collection: str,
        bot_id: str,
        status_data: Dict[str, Any]
    ) -> bool:
        """
        Update bot status/heartbeat
        
        Args:
            collection: Firestore collection name (e.g., 'bot_status')
            bot_id: Bot identifier
            status_data: Status data dict
            
        Returns:
            bool indicating success
        """
        if self.mock_mode:
            logger.info(f"💓 [MOCK] Updating bot status: {collection}/{bot_id}")
            return True
        
        try:
            status_data['last_heartbeat'] = firestore.SERVER_TIMESTAMP
            
            doc_ref = self.db.collection(collection).document(bot_id)
            doc_ref.set(status_data, merge=True)
            
            logger.info(f"💓 Bot status updated: {collection}/{bot_id}")
            return True
        
        except Exception as e:
            logger.error(f"❌ Failed to update bot status: {e}")
            return False
    
    # ────────────────────────────────────────────────────────────────────
    #  Generic Operations
    # ────────────────────────────────────────────────────────────────────
    
    def set_document(
        self,
        collection: str,
        document_id: str,
        data: Dict[str, Any],
        merge: bool = False
    ) -> bool:
        """
        Generic set document operation
        
        Args:
            collection: Collection name
            document_id: Document ID
            data: Data to set
            merge: If True, merge with existing data
            
        Returns:
            bool indicating success
        """
        if self.mock_mode:
            logger.info(f"📝 [MOCK] Setting document: {collection}/{document_id}")
            if collection not in self._mock_db:
                self._mock_db[collection] = {}
            if merge and document_id in self._mock_db[collection]:
                self._mock_db[collection][document_id].update(data)
            else:
                self._mock_db[collection][document_id] = data
            return True
        
        try:
            self.db.collection(collection).document(document_id).set(data, merge=merge)
            logger.info(f"📝 Document set: {collection}/{document_id}")
            return True
        
        except Exception as e:
            logger.error(f"❌ Failed to set document {document_id}: {e}")
            return False
