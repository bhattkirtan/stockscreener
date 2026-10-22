"""
Trading Orchestrator
Central controller that coordinates all skills.
"""
import asyncio
import logging
from typing import Dict, List
from datetime import datetime
import sys
import os

logger = logging.getLogger(__name__)

# Add skills directory to path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from skills.base_skill import Skill, Context


class TradingOrchestrator:
    """
    Orchestrator coordinates skill execution and manages bot lifecycle.
    
    Responsibilities:
    - Initialize all skills with configuration
    - Route data between skills
    - Handle event loop (WebSocket ticks, timers)
    - Error handling and recovery
    - Logging and monitoring
    """
    
    def __init__(self, config: Dict):
        """
        Initialize orchestrator with configuration.
        
        Args:
            config: Full bot configuration with skill settings
        """
        self.config = config
        self.skills: Dict[str, Skill] = {}
        self.running = False
        self.warming_up = False  # True during historical replay — skips risk/execution

        # Initialize metrics
        self.total_signals = 0
        self.total_trades = 0
        self.start_time = None
        
    def register_skill(self, name: str, skill: Skill):
        """
        Register a skill with the orchestrator.
        
        Args:
            name: Skill name (e.g., 'market_data', 'analysis')
            skill: Skill instance
        """
        if not skill.validate_config():
            raise ValueError(f"Invalid configuration for skill: {name}")
        
        self.skills[name] = skill
        print(f"✅ Registered skill: {name}")
    
    def get_skill(self, name: str) -> Skill:
        """Get skill by name"""
        return self.skills.get(name)

    async def _run_skill(self, name: str, context: Context) -> Context:
        """
        Run one skill and enforce the contract that `execute()` returns the
        context.

        A skill that forgets to `return context` used to hand back None, which
        rebound the pipeline's `context` to None; the next attribute access
        raised, and then `on_candle`'s own error handler raised AttributeError
        on None — so the handler defeated itself and the exception escaped. The
        offending skill is now named at ERROR level and the previous context is
        carried forward, so one misbehaving skill degrades the bar instead of
        breaking the loop.
        """
        result = await self.skills[name].execute(context)
        if result is None:
            logger.error(
                f"❌ Skill '{name}' returned None from execute() instead of the "
                f"context — carrying the previous context forward. This is a bug "
                f"in {type(self.skills[name]).__name__}."
            )
            return context
        return result
    
    async def start(self):
        """Start the orchestrator and all skills"""
        self.running = True
        self.start_time = datetime.now()
        print(f"🚀 Orchestrator started at {self.start_time}")
        print(f"📋 Registered skills: {list(self.skills.keys())}")
        
        # TODO: Start WebSocket connection
        # TODO: Start event loop
        
    async def stop(self):
        """Stop the orchestrator and cleanup"""
        self.running = False
        print("🛑 Orchestrator stopped")
        
        # Print stats. start_time is None if stop() is reached without a
        # successful start() — a shutdown path must not raise, or it masks
        # whatever caused the shutdown.
        runtime = ((datetime.now() - self.start_time).total_seconds() / 60
                   if self.start_time is not None else 0.0)
        print(f"\n📊 Session Stats:")
        print(f"  Runtime: {runtime:.1f} minutes")
        print(f"  Total signals: {self.total_signals}")
        print(f"  Total trades: {self.total_trades}")
    
    async def on_candle(self, candle: Dict):
        """
        Handle new candle event.
        
        This is the main trading loop:
        1. Market Data → Update context with new candle
        2. Analysis → Generate signal from indicators
        3. Risk → Validate signal
        4. Execution → Place order if allowed
        5. Storage → Save position to Firestore
        6. Monitoring → Update P&L metrics
        7. Alerting → Send notifications
        
        Args:
            candle: OHLC candle dict with {open, high, low, close, timestamp}
        """
        # Create new context for this candle
        context = Context(
            current_candle=candle,
            timestamp=datetime.now()
        )
        
        try:
            # Execute skills in sequence

            # 1. Market Data Skill — always runs (builds the indicator buffer)
            if 'market_data' in self.skills:
                context = await self._run_skill('market_data', context)

            # During warm-up we only buffer candles — no signals, no orders
            if self.warming_up:
                return

            # 2. Analysis Skill (calculate indicators, generate signal)
            if 'analysis' in self.skills:
                context = await self._run_skill('analysis', context)
                if context.signal:
                    self.total_signals += 1
                    logger.info(f"📊 Signal: {context.signal} at {candle['close']}")

            # 3a. Reverse-signal close: if an opposite position is open, close it first
            # Only fires when risk.reverse_signal_exit is true (defaults to false).
            _reverse_exit_enabled = self.config.get('risk', {}).get('reverse_signal_exit', False)
            if context.signal and 'risk' in self.skills and _reverse_exit_enabled:
                risk_skill = self.skills['risk']
                if (
                    risk_skill.has_open_position
                    and risk_skill.open_position_direction
                    and context.signal != risk_skill.open_position_direction
                ):
                    deal_to_close = risk_skill.open_position_deal_id
                    closed_direction = risk_skill.open_position_direction
                    logger.info(f"🔄 Reverse signal {context.signal} — closing {closed_direction} position {deal_to_close}")
                    close_succeeded = True
                    if 'execution' in self.skills and deal_to_close:
                        close_succeeded = await self.skills['execution'].close_position(deal_to_close)

                    if not close_succeeded:
                        # Broker rejected the close — the old position may still
                        # be live. Book NOTHING: on_position_closed would clear
                        # the open-position flags and let the next bar stack a
                        # second position, defeating this very guard. And abort
                        # the new entry.
                        logger.warning(
                            f"⚠️ Reverse close failed for {deal_to_close} — skipping new entry to prevent position accumulation"
                        )
                        return

                    # P&L and entry price are deliberately NOT invented here.
                    # This orchestrator does not know either: it has no broker
                    # client and the risk skill tracks only deal id + direction.
                    # The old code passed pnl=0.0 / entry_price=0.0, which the
                    # risk breakers read as a BREAK-EVEN trade — scoring every
                    # reverse exit as a win for the consecutive-loss breaker and
                    # contributing nothing to the daily-loss accumulator. That is
                    # the regression described in CLAUDE.md gotcha 22.
                    #
                    # None means "unknown" and makes the breakers SKIP the trade.
                    # The real figures arrive moments later: main.py's
                    # `_poll_positions` sees this same close in the activity feed,
                    # resolves the realised P&L via `get_realised_pnl(deal_id)`
                    # and books it properly. entry_price must be None too, or the
                    # price-distance fallback computes (close - 0.0) and scores a
                    # phantom win instead.
                    await self.on_position_closed(
                        deal_id=deal_to_close or 'unknown',
                        direction=closed_direction,
                        close_reason='Reverse Signal',
                        pnl=None,
                        entry_price=None,
                        close_price=candle.get('close', 0.0),
                    )

                    # Wait briefly after close before opening the new position.
                    # Capital.com needs a moment to settle the closed position before
                    # accepting a new order on the same instrument — without this delay
                    # the new order arrives while the close is still processing and gets DELETED.
                    await asyncio.sleep(1.5)

            # 3b. Risk Skill (validate signal, check cooldown)
            if 'risk' in self.skills and context.signal:
                context = await self._run_skill('risk', context)
                if not context.is_allowed:
                    logger.info(f"⚠️ Signal blocked: {context.risk_reason}")
                    return

            # 4. Execution Skill (place order)
            if 'execution' in self.skills and context.is_allowed:
                context = await self._run_skill('execution', context)
                if context.deal_id:
                    self.total_trades += 1
                    logger.info(f"✅ Trade opened: {context.signal} @ {candle['close']}, deal={context.deal_id}")
                    if 'risk' in self.skills:
                        risk = self.skills['risk']
                        risk.has_open_position = True
                        risk.open_position_deal_id = context.deal_id
                        risk.open_position_direction = context.signal
                else:
                    logger.warning(
                        f"⚠️ Order rejected by broker — {context.signal} entry NOT opened. "
                        f"Position flat, waiting for next signal."
                    )

            # 5. Storage Skill (save to Firestore)
            if 'storage' in self.skills and context.deal_id:
                context = await self._run_skill('storage', context)

            # 6. Monitoring Skill (update metrics)
            if 'monitoring' in self.skills:
                context = await self._run_skill('monitoring', context)

            # 7. Alerting Skill (send notifications)
            if 'alerting' in self.skills and context.deal_id:
                context = await self._run_skill('alerting', context)
        
        except Exception as e:
            # Log FIRST and at ERROR level with a traceback: this is the only
            # durable record of a failed bar. The context below is local and
            # discarded when this method returns, so appending to it is for
            # whatever inspects the context mid-pipeline, not accounting.
            logger.error(f"❌ Error in orchestrator.on_candle: {e}", exc_info=True)
            print(f"❌ Error in orchestrator: {e}")
            # Never let the handler raise. It used to assume `context` was a
            # Context; a skill returning None made `context.errors` an
            # AttributeError *inside the except block*, so the exception escaped
            # on_candle entirely. _run_skill now prevents the None case, and
            # this guard means no future variant of it can resurrect the bug.
            errors = getattr(context, 'errors', None)
            if isinstance(errors, list):
                errors.append({
                    'location': 'orchestrator.on_candle',
                    'error': str(e),
                    'timestamp': datetime.now()
                })
    
    async def on_position_closed(
        self, 
        deal_id: str, 
        direction: str, 
        close_reason: str,
        pnl: float,
        entry_price: float = 0.0,
        close_price: float = 0.0,
        size: float = 0.0
    ):
        """
        Handle position closed event.

        Args:
            deal_id: Position deal ID
            direction: 'BUY' or 'SELL'
            close_reason: 'SL_HIT', 'TP_HIT', or 'SIGNAL'
            pnl: Profit/loss for the trade
            entry_price: Entry price
            close_price: Close price
            size: Position size in contracts (used for the trade history record)
        """
        # pnl may be None — "broker figure unavailable". Must not be coerced to
        # 0.0 here: the risk breakers distinguish None (skip) from 0.0 (a flat
        # trade, which scores as a win and keeps the daily-loss accumulator at 0).
        _pnl_txt = f"${pnl:.2f}" if pnl is not None else "unknown"
        print(f"🔴 Position closed: {deal_id}, {close_reason}, P&L: {_pnl_txt}")
        
        # Update risk skill: clear open-position flag, set cooldown
        if 'risk' in self.skills:
            risk_skill = self.skills['risk']
            # Only clear the tracked position if THIS is the deal that closed.
            # A close event can arrive for a deal that is no longer the tracked
            # one — the reverse-signal path closes a position and opens another
            # 1.5s later, and main.py's `_poll_positions` then books that same
            # close from the activity feed ~10s afterwards. Clearing
            # unconditionally wiped the NEW position's flags, so the
            # open-position gate saw a flat account and the next signal stacked
            # a second position. An unknown tracked id (None) still clears, so
            # a close detected before the open was ever recorded is not stuck.
            tracked = risk_skill.open_position_deal_id
            if tracked is None or tracked == deal_id:
                risk_skill.has_open_position = False
                risk_skill.open_position_deal_id = None
                risk_skill.open_position_direction = None
            else:
                logger.warning(
                    f"⚠️ Close for {deal_id} but the tracked position is {tracked} "
                    f"— keeping the open-position flags so the gate still blocks"
                )
            risk_skill.on_position_closed(
                direction=direction,
                close_reason=close_reason,
                entry_price=entry_price,
                close_price=close_price,
                pnl=pnl
            )
        
        # Update storage (close position in Firestore) - ALWAYS in finally block
        if 'storage' in self.skills:
            try:
                storage_skill = self.skills['storage']
                await storage_skill.close_position(
                    deal_id, close_price, close_reason,
                    pnl=pnl,
                    direction=direction,
                    entry_price=entry_price,
                    size=size,
                )
            except Exception as e:
                print(f"⚠️ Storage close failed: {e}")
        
        # Update monitoring (track P&L)
        if 'monitoring' in self.skills:
            monitoring_skill = self.skills['monitoring']
            # Build a minimal event-like payload the monitoring skill expects
            class _PositionClosedEvent:
                payload = {
                    'deal_id': deal_id,
                    'realized_pnl': pnl,
                    'close_reason': close_reason,
                }
            import asyncio
            if asyncio.iscoroutinefunction(monitoring_skill.on_position_closed):
                await monitoring_skill.on_position_closed(_PositionClosedEvent())
            else:
                monitoring_skill.on_position_closed(_PositionClosedEvent())
        
        # Send alert
        if 'alerting' in self.skills:
            alerting_skill = self.skills['alerting']
            await alerting_skill.send_trade_closed_alert(
                direction=direction,
                entry_price=entry_price,
                close_price=close_price,
                close_reason=close_reason,
                pnl=pnl
            )


# Example usage
if __name__ == "__main__":
    from skills.risk.risk_skill import RiskSkill
    
    async def main():
        # Configuration
        config = {
            'risk': {
                'sl_cooldown_minutes': 15,
                'tp_cooldown_minutes': 5,
                'position_size_pct': 2.0,
                'max_drawdown_pct': 20.0,
                'max_positions': 1
            }
        }
        
        # Create orchestrator
        orchestrator = TradingOrchestrator(config)
        
        # Register skills (for demo, only risk skill)
        risk_skill = RiskSkill(config['risk'])
        orchestrator.register_skill('risk', risk_skill)
        
        # Start orchestrator
        await orchestrator.start()
        
        # Simulate candle with BUY signal
        print("\n--- Candle 1: BUY Signal ---")
        candle1 = {
            'open': 2650.0,
            'high': 2652.0,
            'low': 2649.0,
            'close': 2651.0,
            'timestamp': datetime.now()
        }
        
        # Mock context with signal
        context = Context(signal='BUY', timestamp=datetime.now())
        context = await risk_skill.execute(context)
        print(f"Signal allowed: {context.is_allowed}, Reason: {context.risk_reason}")
        
        # Simulate position close with SL
        print("\n--- Position Closed: SL_HIT ---")
        await orchestrator.on_position_closed(
            deal_id='DEAL123',
            direction='BUY',
            close_reason='SL_HIT',
            pnl=-20.0
        )
        
        # Try same signal immediately (should be blocked)
        print("\n--- Candle 2: BUY Signal (immediate) ---")
        context = Context(signal='BUY', timestamp=datetime.now())
        context = await risk_skill.execute(context)
        print(f"Signal allowed: {context.is_allowed}, Reason: {context.risk_reason}")
        
        # Try opposite signal (should be allowed)
        print("\n--- Candle 3: SELL Signal (opposite) ---")
        context = Context(signal='SELL', timestamp=datetime.now())
        context = await risk_skill.execute(context)
        print(f"Signal allowed: {context.is_allowed}, Reason: {context.risk_reason}")
        
        # Stop orchestrator
        await orchestrator.stop()
    
    # Run example
    asyncio.run(main())
