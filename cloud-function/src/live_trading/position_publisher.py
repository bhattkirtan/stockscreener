"""
📈 Position Publisher - Track active trading positions in Firestore

Publishes position data for real-time monitoring:
- Position details (epic, direction, size, entry price)
- Stop loss and take profit levels
- Current price and unrealized P&L
- Position status (OPEN, CLOSING, CLOSED)
- Timestamps (opened, last update, closed)
"""

import os
import logging
from datetime import datetime
from typing import Dict, Optional, List
from enum import Enum

logger = logging.getLogger(__name__)


class PositionStatus(Enum):
    """Position status states"""
    OPENING = "opening"
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"
    ERROR = "error"


class PositionPublisher:
    """
    Publishes position data to Firestore for real-time tracking.
    
    Usage:
        publisher = PositionPublisher()
        
        # When position opens
        publisher.publish_position({
            'deal_id': 'DEAL123',
            'epic': 'GOLD',
            'direction': 'BUY',
            'size': 0.5,
            'entry_price': 2650.25,
            'stop_loss': 2630.25,
            'take_profit': 2690.25
        })
        
        # Update P&L on price changes
        publisher.update_pnl('DEAL123', current_price=2655.50)
        
        # Close position
        publisher.close_position('DEAL123', close_price=2670.00)
    """
    
    def __init__(
        self,
        collection: str = "active_positions",
        project_id: str = None
    ):
        """
        Initialize position publisher
        
        Args:
            collection: Firestore collection name
            project_id: GCP project ID (auto-detected if not provided)
        """
        self.collection = collection
        self.project_id = project_id or os.getenv('GOOGLE_CLOUD_PROJECT') or os.getenv('GCP_PROJECT_ID')
        
        # Initialize Firestore client
        self.firestore_client = None
        self._init_firestore()
    
    def _init_firestore(self):
        """Initialize Firestore client"""
        try:
            from google.cloud import firestore
            self.firestore_client = firestore.Client(project=self.project_id)
            logger.info(f"✅ Position Publisher initialized (project: {self.project_id}, collection: {self.collection})")
        except Exception as e:
            logger.warning(f"⚠️ Firestore initialization failed: {e}")
            logger.warning("Position data will not be published to Firestore")
    
    def publish_position(
        self,
        position_data: Dict,
        status: PositionStatus = PositionStatus.OPEN
    ) -> bool:
        """
        Publish or update position in Firestore
        
        Args:
            position_data: Position data dictionary with:
                - deal_id (str): Unique position ID
                - epic (str): Trading instrument
                - direction (str): 'BUY' or 'SELL'
                - size (float): Position size
                - entry_price (float): Entry price
                - stop_loss (float): Stop loss level
                - take_profit (float): Take profit level
                - current_price (float, optional): Current market price
                - pnl (float, optional): Unrealized P&L
            status: Position status
        
        Returns:
            True if successful, False otherwise
        """
        if not self.firestore_client:
            return False
        
        deal_id = position_data.get('deal_id')
        if not deal_id:
            logger.error("❌ Position data must include 'deal_id'")
            return False
        
        try:
            # Build position document
            position_doc = {
                'deal_id': deal_id,
                'epic': position_data.get('epic'),
                'direction': position_data.get('direction'),
                'size': position_data.get('size'),
                'entry_price': position_data.get('entry_price'),
                'stop_loss': position_data.get('stop_loss'),
                'take_profit': position_data.get('take_profit'),
                'status': status.value,
                'last_updated': datetime.now().isoformat(),
            }
            
            # Add current price and P&L if provided
            if 'current_price' in position_data:
                position_doc['current_price'] = position_data['current_price']
            if 'pnl' in position_data:
                position_doc['pnl'] = position_data['pnl']
            
            # Check if this is a new position (doesn't exist yet)
            doc_ref = self.firestore_client.collection(self.collection).document(deal_id)
            existing_doc = doc_ref.get()
            
            if not existing_doc.exists:
                # New position - add opened_at timestamp
                position_doc['opened_at'] = datetime.now().isoformat()
                logger.info(f"✅ New position published: {deal_id} ({position_data.get('direction')} {position_data.get('epic')})")
            else:
                logger.debug(f"📝 Position updated: {deal_id}")
            
            # Write to Firestore
            doc_ref.set(position_doc, merge=True)
            return True
            
        except Exception as e:
            logger.error(f"❌ Position publish failed: {e}")
            return False
    
    def update_pnl(
        self,
        deal_id: str,
        current_price: float,
        pnl: Optional[float] = None
    ) -> bool:
        """
        Update position's current price and P&L
        
        Args:
            deal_id: Position ID
            current_price: Current market price
            pnl: Unrealized P&L (calculated if not provided)
        
        Returns:
            True if successful, False otherwise
        """
        if not self.firestore_client:
            return False
        
        try:
            doc_ref = self.firestore_client.collection(self.collection).document(deal_id)
            
            # If P&L not provided, calculate it
            if pnl is None:
                # Get position data to calculate P&L
                doc = doc_ref.get()
                if doc.exists:
                    data = doc.to_dict()
                    entry_price = data.get('entry_price')
                    size = data.get('size')
                    direction = data.get('direction')
                    
                    if entry_price and size and direction:
                        if direction == 'BUY':
                            pnl = (current_price - entry_price) * size
                        else:  # SELL
                            pnl = (entry_price - current_price) * size
            
            # Update Firestore
            update_doc = {
                'current_price': current_price,
                'last_updated': datetime.now().isoformat()
            }
            
            if pnl is not None:
                update_doc['pnl'] = round(pnl, 2)
            
            doc_ref.set(update_doc, merge=True)
            logger.debug(f"📊 P&L updated: {deal_id} (price: {current_price}, pnl: {pnl})")
            return True
            
        except Exception as e:
            logger.error(f"❌ P&L update failed: {e}")
            return False
    
    def close_position(
        self,
        deal_id: str,
        close_price: float,
        realized_pnl: Optional[float] = None,
        close_reason: Optional[str] = None
    ) -> bool:
        """
        Close position and remove from active positions
        
        Args:
            deal_id: Position ID
            close_price: Final closing price
            realized_pnl: Realized P&L
            close_reason: Reason for closing (SL_HIT, TP_HIT, MANUAL, etc.)
        
        Returns:
            True if successful, False otherwise
        """
        if not self.firestore_client:
            return False
        
        try:
            doc_ref = self.firestore_client.collection(self.collection).document(deal_id)
            
            # Get existing position data
            doc = doc_ref.get()
            if not doc.exists:
                logger.warning(f"⚠️ Position {deal_id} not found in active_positions")
                return False
            
            position_data = doc.to_dict()
            
            # Calculate realized P&L if not provided
            if realized_pnl is None:
                entry_price = position_data.get('entry_price')
                size = position_data.get('size')
                direction = position_data.get('direction')
                
                if entry_price and size and direction:
                    if direction == 'BUY':
                        realized_pnl = (close_price - entry_price) * size
                    else:  # SELL
                        realized_pnl = (entry_price - close_price) * size
            
            # Save to position history (optional - for record keeping)
            try:
                history_doc = position_data.copy()
                history_doc.update({
                    'status': PositionStatus.CLOSED.value,
                    'close_price': close_price,
                    'closed_at': datetime.now().isoformat(),
                    'realized_pnl': round(realized_pnl, 2) if realized_pnl is not None else None,
                    'close_reason': close_reason
                })
                self.firestore_client.collection('position_history').document(deal_id).set(history_doc)
                logger.debug(f"📝 Position saved to history: {deal_id}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to save position history: {e}")
            
            # DELETE from active_positions (this is the key fix!)
            doc_ref.delete()
            
            logger.info(f"✅ Position closed and removed: {deal_id} (price: {close_price}, pnl: {realized_pnl})")
            return True
            
        except Exception as e:
            logger.error(f"❌ Position close failed: {e}")
            return False
    
    def get_active_positions(self) -> List[Dict]:
        """
        Get all active (OPEN) positions
        
        Returns:
            List of active position documents
        """
        if not self.firestore_client:
            return []
        
        try:
            # Query for OPEN positions
            query = self.firestore_client.collection(self.collection).where('status', '==', PositionStatus.OPEN.value)
            docs = query.stream()
            
            positions = []
            for doc in docs:
                position_data = doc.to_dict()
                position_data['id'] = doc.id
                positions.append(position_data)
            
            logger.debug(f"📊 Retrieved {len(positions)} active position(s)")
            return positions
            
        except Exception as e:
            logger.error(f"❌ Failed to get active positions: {e}")
            return []
    
    def delete_position(self, deal_id: str) -> bool:
        """
        Delete position from Firestore (use with caution)
        
        Args:
            deal_id: Position ID
        
        Returns:
            True if successful, False otherwise
        """
        if not self.firestore_client:
            return False
        
        try:
            doc_ref = self.firestore_client.collection(self.collection).document(deal_id)
            doc_ref.delete()
            logger.info(f"🗑️ Position deleted: {deal_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Position delete failed: {e}")
            return False
    
    def cleanup_closed_positions(self) -> int:
        """
        Remove all closed positions from active_positions collection
        
        Returns:
            Number of positions removed
        """
        if not self.firestore_client:
            return 0
        
        try:
            # Query for CLOSED positions
            query = self.firestore_client.collection(self.collection).where('status', '==', PositionStatus.CLOSED.value)
            docs = query.stream()
            
            count = 0
            for doc in docs:
                doc.reference.delete()
                count += 1
                logger.info(f"🗑️ Removed closed position: {doc.id}")
            
            if count > 0:
                logger.info(f"✅ Cleaned up {count} closed position(s)")
            else:
                logger.info("✅ No closed positions to clean up")
            
            return count
            
        except Exception as e:
            logger.error(f"❌ Cleanup failed: {e}")
            return 0
