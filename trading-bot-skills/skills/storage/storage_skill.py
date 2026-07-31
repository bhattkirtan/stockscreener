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
from clients.sqlite_api import SQLiteAPIClient as FirestoreAPIClient

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
        # YAML declares this under the key `trades:`; older code looked up
        # `trade_history` and silently fell back to `test_trades`, which is why
        # no closed trade was ever persisted. Accept both spellings.
        self.trades_collection = (
            self.collections.get('trades')
            or self.collections.get('trade_history')
            or 'trade_history'
        )

        # Stamped onto every trade so the live report can filter per bot
        # (gold_m5_bot, ethusd_m5_bot, ...). Injected by register_skills().
        self.bot_id = config.get('bot_id')
        self.epic = config.get('epic')

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
            'epic': event.instrument,
            'signal': event.payload.get('signal'),
            'price': event.payload.get('entry_price'),
            'sl': event.payload.get('stop_loss'),
            'tp': event.payload.get('take_profit'),
            'timestamp': event.timestamp.isoformat(),
            'strategy': event.payload.get('strategy', 'supertrend_vwap'),
            'mode': event.payload.get('mode', 'AUTO'),
            'indicators': event.payload.get('indicators', {}),
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
        
        entry_price = event.payload.get('entry_price', 0)
        size = event.payload.get('size', 0)
        document = {
            # UI-facing names (BotPosition schema)
            'position_id': deal_id,
            'deal_id': deal_id,
            'epic': event.instrument,
            'direction': event.payload.get('direction'),
            'size': size,
            'open_level': entry_price,
            'current_level': entry_price,
            'pnl': 0.0,
            'pnl_pct': 0.0,
            'stop_loss': event.payload.get('stop_loss'),
            'take_profit': event.payload.get('take_profit'),
            'opened_at': event.timestamp.isoformat(),
            'status': 'OPEN',
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

        # Also append to trade history. Keyed by deal_id, so if the orchestrator
        # already recorded this close the write is an idempotent overwrite
        # rather than a second trade.
        self._record_trade(
            deal_id=deal_id,
            close_price=float(close_price or 0.0),
            close_reason=close_reason,
            pnl=float(event.payload.get('realized_pnl') or 0.0),
            direction=event.payload.get('direction'),
            entry_price=float(event.payload.get('entry_price') or 0.0),
            size=float(event.payload.get('size') or 0.0),
        )

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
        
        entry_price = position.get('open_level') or position.get('entry_price', 0)
        size = position.get('size', 0)
        upl = position.get('upl', 0.0) or 0.0
        pnl_pct = (upl / (entry_price * size) * 100) if entry_price and size else 0.0

        # This method is re-run on every REST reconcile (~60 s) to refresh live
        # P&L. Callers rarely know the true open time, so without this the
        # fallback `datetime.now()` would overwrite opened_at on every pass and
        # every trade would look like it was held for seconds.
        existing_opened_at = None
        try:
            existing_row = self.firestore_client.get_position(collection, deal_id)
            if existing_row:
                existing_opened_at = existing_row.get('opened_at')
        except Exception:
            pass

        document = {
            # UI-facing names (BotPosition schema)
            'position_id': deal_id,
            'deal_id': deal_id,
            'epic': position.get('epic') or position.get('instrument', ''),
            'direction': position.get('direction'),
            'size': size,
            'open_level': entry_price,
            'current_level': position.get('current_level') or entry_price,
            'pnl': upl,
            'pnl_pct': round(pnl_pct, 2),
            'stop_loss': position.get('stop_loss'),
            'take_profit': position.get('take_profit'),
            'opened_at': (
                existing_opened_at
                or position.get('opened_at')
                or position.get('entry_time', datetime.now()).isoformat()
            ),
            'status': 'OPEN',
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
    
    async def save_open_position(
        self,
        deal_id: str,
        epic: str,
        direction: str,
        level: float,
        size: float,
        stop_level=None,
        profit_level=None,
        opened_at: str = None,
        upl: float = 0.0,
    ) -> None:
        """
        Upsert an open position from the broker.
        Called from _poll_positions on startup seed and REST reconciliation.
        upl = unrealized P&L from Capital.com (position.upl).
        """
        await self._save_position({
            'deal_id':       deal_id,
            'epic':          epic,
            'direction':     direction,
            'entry_price':   level,
            'size':          size,
            'stop_loss':     stop_level,
            'take_profit':   profit_level,
            'opened_at':     opened_at or datetime.now().isoformat(),
            'upl':           upl,
        })

    def _record_trade(
        self,
        deal_id: str,
        close_price: float,
        close_reason: str,
        pnl: float = 0.0,
        direction: str = None,
        entry_price: float = 0.0,
        size: float = 0.0,
    ) -> None:
        """
        Write a completed trade to the trade_history collection.

        This is what the live performance report reads
        (cloud-function/api/live_report.py). Any field the caller could not
        supply is backfilled from the open position row, which was written by
        `_save_position` when the position was opened.

        Never raises — a persistence failure must not break the close path.
        """
        try:
            open_row = self.firestore_client.get_position(
                self.positions_collection, deal_id
            ) or {}
        except Exception as e:
            logger.warning(f"⚠️ Could not read open position {deal_id} for trade record: {e}")
            open_row = {}

        entry = float(entry_price or open_row.get('open_level') or 0.0)
        qty   = float(size or open_row.get('size') or 0.0)
        side  = (direction or open_row.get('direction') or 'BUY').upper()

        # pnl arrives from Capital.com activity (`details.profit`) and is the
        # authoritative realised figure — it already includes spread/fees.
        # Only fall back to an arithmetic estimate when the broker gave nothing.
        realized = float(pnl or 0.0)
        estimated = False
        if not realized and entry and close_price and qty:
            realized = (close_price - entry) * (1.0 if side == 'BUY' else -1.0) * qty
            estimated = True

        margin = entry * qty
        trade = {
            'deal_id':      deal_id,
            'bot_id':       self.bot_id,
            'epic':         open_row.get('epic') or self.epic or '',
            'direction':    side,
            'size':         qty,
            'entry_price':  entry,
            'exit_price':   float(close_price or 0.0),
            'entry_time':   open_row.get('opened_at', ''),
            'exit_time':    datetime.now().isoformat(),
            'pnl':          round(realized, 2),
            'pnl_pct':      round(realized / margin * 100, 4) if margin else 0.0,
            'exit_reason':  close_reason or 'UNKNOWN',
            'stop_loss':    open_row.get('stop_loss'),
            'take_profit':  open_row.get('take_profit'),
            'pnl_estimated': estimated,
        }

        try:
            self.firestore_client.save_trade(self.trades_collection, deal_id, trade)
            logger.info(
                f"📒 Trade recorded: {deal_id} {side} {qty} @ {entry} → {close_price} "
                f"= ${realized:.2f} ({close_reason})"
            )
        except Exception as e:
            logger.error(f"❌ Failed to record trade {deal_id}: {e}")

    async def close_position(
        self,
        deal_id: str,
        close_price: float,
        close_reason: str,
        pnl: float = 0.0,
        direction: str = None,
        entry_price: float = 0.0,
        size: float = 0.0,
    ):
        """
        Close position in Firestore (ALWAYS called in finally block)

        Args:
            deal_id: Position deal ID
            close_price: Close price
            close_reason: 'SL_HIT', 'TP_HIT', or 'SIGNAL'
            pnl: Realised P&L from the broker (authoritative when non-zero)
            direction: 'BUY' or 'SELL'
            entry_price: Entry price
            size: Position size in contracts
        """
        collection = self.collections.get('positions', 'active_positions')

        close_data = {
            'close_price': close_price,
            'close_reason': close_reason,
            'close_time': datetime.now().isoformat(),
            'realized_pnl': pnl,
        }

        # Append to trade history BEFORE mutating the open row, so the entry
        # fields are still readable if the position update partially fails.
        self._record_trade(
            deal_id=deal_id,
            close_price=close_price,
            close_reason=close_reason,
            pnl=pnl,
            direction=direction,
            entry_price=entry_price,
            size=size,
        )

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
            'epic': context.current_candle.get('instrument', '') if context.current_candle else '',
            'signal': context.signal,
            'price': context.entry_price or (context.current_candle.get('close') if context.current_candle else None),
            'sl': context.stop_loss,
            'tp': context.take_profit,
            'timestamp': datetime.now().isoformat(),
            'strategy': 'supertrend_vwap',
            'mode': 'AUTO',
            'indicators': context.indicators or {},
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
