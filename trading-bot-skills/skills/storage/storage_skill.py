"""
Storage Skill
Persists data to Firestore.
"""
from typing import Dict, Optional
from datetime import datetime
import sys
import os
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from skills.base_skill import Skill, Context, SkillExecutionError
from clients.firestore_api import FirestoreAPIClient

logger = logging.getLogger(__name__)


class StorageSkill(Skill):
    """
    Storage skill that persists data to Firestore.
    
    Responsibilities:
    - Save/update positions
    - Log signals
    - Update bot status
    - Store trade history
    
    Event Subscriptions:
    - SIGNAL_GENERATED: Log signal
    - ORDER_FILLED: Save position
    - POSITION_CLOSED: Close position
    """
    
    def __init__(self, config: Dict, event_bus: Optional['EventBus'] = None):
        super().__init__(config, event_bus)
        
        self.backend = config.get('backend', 'firestore')
        firestore_config = config.get('firestore', {})
        self.project_id = firestore_config.get('project_id') or config.get('project_id')
        self.collections = firestore_config.get('collections', {}) or config.get('collections', {})
        
        # Collection shortcuts
        self.positions_collection = self.collections.get('positions', 'test_positions')
        self.signals_collection = self.collections.get('signals', 'test_signals')
        self.trades_collection = self.collections.get('trade_history', 'test_trades')
        
        self.mock_mode = config.get('mock_mode', False)
        
        # Initialize Firestore client
        if not self.mock_mode and firestore_config:
            try:
                self.firestore_client = FirestoreAPIClient(
                    project_id=self.project_id,
                    credentials_path=firestore_config.get('credentials_path'),
                    mock_mode=False
                )
                logger.info("✅ Firestore client initialized")
            except Exception as e:
                logger.error(f"❌ Failed to initialize Firestore client: {e}")
                logger.warning("⚠️ Falling back to mock mode")
                self.mock_mode = True
                self.firestore_client = FirestoreAPIClient(mock_mode=True)
        else:
            self.firestore_client = FirestoreAPIClient(mock_mode=True)
            logger.warning("⚠️ Storage Skill running in MOCK MODE")
        
        print(f"💾 Storage Skill initialized: {self.backend}, project={self.project_id}")
    
    async def on_signal_generated(self, event: 'Event') -> None:
        """
        Handle SIGNAL_GENERATED event - log signal to Firestore.
        
        Args:
            event: Event with signal data
        """
        collection = self.signals_collection
        
        signal_doc = {
            'signal': event.payload.get('signal'),
            'timestamp': event.timestamp.isoformat(),
            'entry_price': event.payload.get('entry_price'),
            'stop_loss': event.payload.get('stop_loss'),
            'take_profit': event.payload.get('take_profit'),
            'instrument': event.instrument
        }
        
        logger.info(f"💾 Logging signal: {signal_doc['signal']}")
        
        # Log to Firestore
        success = self.firestore_client.log_signal(
            collection=collection,
            signal_data=signal_doc
        )
        
        if not success:
            logger.error(f"❌ Failed to log signal")
    
    async def on_order_filled(self, event: 'Event') -> None:
        """
        Handle ORDER_FILLED event - save position to Firestore.
        
        Args:
            event: Event with order filled details
        """
        deal_id = event.payload.get('deal_id')
        if not deal_id:
            logger.warning("⚠️ No deal_id in ORDER_FILLED event")
            return
        
        collection = self.positions_collection
        
        document = {
            'deal_id': deal_id,
            'direction': event.payload.get('direction'),
            'size': event.payload.get('size'),
            'entry_price': event.payload.get('entry_price'),
            'stop_loss': event.payload.get('stop_loss'),
            'take_profit': event.payload.get('take_profit'),
            'entry_time': event.timestamp.isoformat(),
            'instrument': event.instrument,
            'status': 'OPEN'
        }
        
        logger.info(f"💾 Saving position to Firestore: {collection}/{deal_id}")
        
        # Save to Firestore
        success = self.firestore_client.save_position(
            collection=collection,
            deal_id=deal_id,
            position_data=document
        )
        
        if success:
            logger.info(f"✅ Position saved: {deal_id}")
        else:
            logger.error(f"❌ Failed to save position: {deal_id}")
    
    async def on_position_closed(self, event: 'Event') -> None:
        """
        Handle POSITION_CLOSED event - update position in Firestore.
        
        Args:
            event: Event with position close details
        """
        deal_id = event.payload.get('deal_id')
        if not deal_id:
            logger.warning("⚠️ No deal_id in POSITION_CLOSED event")
            return
        
        collection = self.positions_collection
        close_price = event.payload.get('close_price')
        close_reason = event.payload.get('close_reason')
        
        close_data = {
            'close_price': close_price,
            'close_reason': close_reason,
            'close_time': event.timestamp.isoformat(),
            'realized_pnl': event.payload.get('realized_pnl', 0),
            'status': 'CLOSED'
        }
        
        logger.info(f"💾 Closing position in Firestore: {collection}/{deal_id} ({close_reason})")
        
        try:
            # CRITICAL: Always close in Firestore (even if API fails)
            success = self.firestore_client.close_position(
                collection=collection,
                deal_id=deal_id,
                close_data=close_data
            )
            
            if success:
                logger.info(f"✅ Firestore position closed: {deal_id}")
            else:
                logger.error(f"❌ Failed to close position in Firestore: {deal_id}")
        
        except Exception as e:
            logger.error(f"⚠️ Firestore close exception: {e}")
            # Don't rethrow - graceful degradation
    
    async def execute(self, context: Context) -> Context:
        """
        Persist data to Firestore based on context state
        
        Args:
            context: Context with position/signal data
            
        Returns:
            Updated context
        """
        # Save position if deal_id present
        if context.deal_id and context.current_position:
            await self._save_position(context.current_position)
        
        # Log signal if present
        if context.signal:
            await self._log_signal(context)
        
        return context
    
    async def _save_position(self, position: Dict):
        """
        Save position to Firestore
        
        Args:
            position: Position dict with deal_id, direction, entry_price, etc.
        """
        deal_id = position.get('deal_id')
        collection = self.collections.get('positions', 'active_positions')
        
        document = {
            'deal_id': deal_id,
            'direction': position.get('direction'),
            'size': position.get('size'),
            'entry_price': position.get('entry_price'),
            'stop_loss': position.get('stop_loss'),
            'take_profit': position.get('take_profit'),
            'entry_time': position.get('entry_time', datetime.now()).isoformat(),
            'status': 'OPEN'
        }
        
        logger.info(f"💾 Saving position to Firestore: {collection}/{deal_id}")
        
        # Save to Firestore
        success = self.firestore_client.save_position(
            collection=collection,
            deal_id=deal_id,
            position_data=document
        )
        
        if success:
            logger.info(f"✅ Position saved: {deal_id}")
        else:
            logger.error(f"❌ Failed to save position: {deal_id}")
    
    async def close_position(self, deal_id: str, close_price: float, close_reason: str):
        """
        Close position in Firestore (ALWAYS called in finally block)
        
        Args:
            deal_id: Position deal ID
            close_price: Close price
            close_reason: 'SL_HIT', 'TP_HIT', or 'SIGNAL'
        """
        collection = self.collections.get('positions', 'active_positions')
        
        close_data = {
            'close_price': close_price,
            'close_reason': close_reason,
            'close_time': datetime.now().isoformat()
        }
        
        logger.info(f"💾 Closing position in Firestore: {collection}/{deal_id} ({close_reason})")
        
        try:
            # CRITICAL: Always close in Firestore (even if API fails)
            success = self.firestore_client.close_position(
                collection=collection,
                deal_id=deal_id,
                close_data=close_data
            )
            
            if success:
                logger.info(f"✅ Firestore position closed: {deal_id}")
            else:
                logger.error(f"❌ Failed to close position in Firestore: {deal_id}")
        
        except Exception as e:
            logger.error(f"⚠️ Firestore close exception: {e}")
            # Don't rethrow - this is in finally block
    
    async def _log_signal(self, context: Context):
        """
        Log signal to Firestore
        
        Args:
            context: Context with signal data
        """
        collection = self.collections.get('signals', 'signals')
        
        signal_doc = {
            'signal': context.signal,
            'timestamp': datetime.now().isoformat(),
            'indicators': context.indicators or {},
            'current_price': context.current_candle.get('close') if context.current_candle else None
        }
        
        logger.info(f"💾 Logging signal: {context.signal}")
        
        # Log to Firestore
        success = self.firestore_client.log_signal(
            collection=collection,
            signal_data=signal_doc
        )
        
        if not success:
            logger.error(f"❌ Failed to log signal")
    
    def validate_config(self) -> bool:
        """Validate storage configuration"""
        if self.backend == 'firestore' and not self.project_id:
            raise SkillExecutionError("Firestore project_id required")
        return True


# Example usage
if __name__ == "__main__":
    import asyncio
    
    config = {
        'backend': 'firestore',
        'firestore': {
            'project_id': 'stockscreener-123',
            'collections': {
                'positions': 'active_positions',
                'signals': 'signals'
            }
        }
    }
    
    skill = StorageSkill(config)
    
    async def test():
        # Mock position
        context = Context(
            deal_id='DEAL123',
            signal='BUY',
            current_position={
                'deal_id': 'DEAL123',
                'direction': 'BUY',
                'size': 0.5,
                'entry_price': 2650.0,
                'stop_loss': 2630.0,
                'take_profit': 2690.0,
                'entry_time': datetime.now()
            },
            current_candle={'close': 2650.0}
        )
        
        context = await skill.execute(context)
        
        # Close position
        await skill.close_position('DEAL123', close_price=2690.0, close_reason='TP_HIT')
    
    asyncio.run(test())
