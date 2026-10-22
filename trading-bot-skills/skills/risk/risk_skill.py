"""
Risk Management Skill
Validates trading signals against risk rules, cooldown periods, and trading hours.

EVENT-DRIVEN:
- Subscribes to: SIGNAL_GENERATED
- Publishes: RISK_APPROVED or RISK_REJECTED
"""
from typing import Dict, Optional, Tuple, TYPE_CHECKING
from datetime import datetime, timedelta
import logging
import pytz
import pandas as pd
import sys
import os

logger = logging.getLogger(__name__)

# Add parent directory to path to import base_skill
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from base_skill import Skill, SkillExecutionError

if TYPE_CHECKING:
    from core.event_bus import EventBus, Event
    from core.circuit_breakers import CircuitBreaker, TradingSessionFilter, SpreadSlippageFilter, NewsEventKillSwitch


class RiskSkill(Skill):
    """
    Risk management skill that validates signals before execution.
    
    EVENT-DRIVEN HANDLERS:
    - on_signal_generated(event): Validate signal and publish RISK_APPROVED/REJECTED
    
    Responsibilities:
    - Trading hours enforcement (weekends closed, daily break)
    - Cooldown period enforcement (15min SL, 5min TP)
    - Position sizing
    - Circuit breaker checks (daily/weekly loss limits)
    - Session filtering (LONDON/NEW_YORK only)
    - Spread validation
    - News kill switch
    """
    
    def __init__(self, config: Dict, event_bus: Optional['EventBus'] = None,
                 circuit_breaker=None, session_filter=None, spread_filter=None, news_killswitch=None):
        super().__init__(config, event_bus)
        
        # Circuit breakers (from Phase 15)
        self.circuit_breaker = circuit_breaker
        self.session_filter = session_filter
        self.spread_filter = spread_filter
        self.news_killswitch = news_killswitch
        
        # Trading hours configuration
        self.trading_hours_enabled = config.get('trading_hours', {}).get('enabled', True)
        self.timezone = pytz.timezone(config.get('trading_hours', {}).get('timezone', 'UTC'))
        
        # Weekly schedule
        self.monday_enabled = config.get('trading_hours', {}).get('monday_enabled', True)
        self.tuesday_enabled = config.get('trading_hours', {}).get('tuesday_enabled', True)
        self.wednesday_enabled = config.get('trading_hours', {}).get('wednesday_enabled', True)
        self.thursday_enabled = config.get('trading_hours', {}).get('thursday_enabled', True)
        self.friday_enabled = config.get('trading_hours', {}).get('friday_enabled', True)
        self.saturday_enabled = config.get('trading_hours', {}).get('saturday_enabled', False)
        self.sunday_enabled = config.get('trading_hours', {}).get('sunday_enabled', False)
        
        # Daily hours
        self.start_hour = config.get('trading_hours', {}).get('start_hour', 0)
        self.end_hour = config.get('trading_hours', {}).get('end_hour', 23)
        
        # Daily break
        self.daily_break_enabled = config.get('trading_hours', {}).get('daily_break_enabled', True)
        self.break_start_hour = config.get('trading_hours', {}).get('break_start_hour', 21)
        self.break_end_hour = config.get('trading_hours', {}).get('break_end_hour', 22)
        
        # Friday special rules
        self.friday_close_hour = config.get('trading_hours', {}).get('friday_close_hour', 21)
        self.friday_no_new_trades_hour = config.get('trading_hours', {}).get('friday_no_new_trades_hour', 20)
        
        # Cooldown settings
        self.sl_cooldown_minutes = config.get('sl_cooldown_minutes', 15)
        self.tp_cooldown_minutes = config.get('tp_cooldown_minutes', 5)
        self.current_capital = config.get('initial_capital', 10000)  # Track current capital

        # Hour filter — list of UTC hours where new entries are blocked
        self.skip_hours = config.get('skip_hours', [])

        # Consecutive-loss circuit breaker.
        # After `max_consecutive_losses` losing trades in a row, block ALL new
        # entries for `consecutive_loss_cooldown_minutes`, then reset and resume.
        # A winning trade resets the counter immediately. 0 = disabled (default),
        # so existing instruments are unaffected until they opt in.
        self.max_consecutive_losses = config.get('max_consecutive_losses', 0)
        self.consecutive_loss_cooldown_minutes = config.get('consecutive_loss_cooldown_minutes', 120)
        self.consecutive_losses = 0
        self.loss_circuit_until = None  # tz-naive datetime; entries blocked until this time

        # Daily-loss limit. Once realised P&L for the current UTC day reaches
        # -max_daily_loss_usd, block ALL new entries for the rest of that day;
        # the halt clears automatically at the next UTC date. 0 = disabled.
        # Needs real $ P&L at close (passed via on_position_closed(pnl=...)).
        self.max_daily_loss_usd = config.get('max_daily_loss_usd', 0)
        self._daily_realized_pnl = 0.0
        self._daily_pnl_date = None    # UTC date the accumulator belongs to
        self._daily_halt_date = None   # UTC date we are halted for (None = not halted)
        
        # Position sizing
        self.position_size_pct = config.get('position_size_pct', 2.0)
        self.position_size = config.get('position_size', 0.5)
        
        # Position tracking for cooldown
        self.last_closed_position = None
        self.has_open_position = False
        self.open_position_deal_id: Optional[str] = None
        self.open_position_direction: Optional[str] = None

        # Startup flip gate: block entries until the Supertrend direction changes
        # at least once since the bot started. Prevents entering mid-trend on restart.
        # Set _startup_flip_seen = True externally when resuming a live position.
        # `startup_flip_gate: false` disables it entirely. It is applied by BOTH
        # gate paths so live and backtest agree; previously it was live-only,
        # which cost one bar of divergence after every restart.
        self.startup_flip_gate: bool = bool(config.get('startup_flip_gate', True))
        self._startup_signal: Optional[str] = None
        self._startup_flip_seen: bool = False

        # Reverse-signal exit. When enabled an opposite-direction signal arriving
        # while a position is open is an exit-and-reenter, not a stack, so the
        # open-position gate must let it through — the caller closes the old
        # position first (live does so before gating, backtest on the next bar's
        # open). Default False matches the live orchestrator and every deployed
        # instrument YAML; run_skills_backtest.py used to default it to True.
        self.reverse_signal_exit: bool = bool(config.get('reverse_signal_exit', False))
        
    # ------------------------------------------------------------------
    # The single entry-gate chain
    # ------------------------------------------------------------------

    def _check_startup_flip(self, signal: str) -> Tuple[bool, str]:
        """
        Suppress entries until the signal direction has flipped at least once
        since this process started, so a restart mid-trend does not immediately
        enter. Mutates state, so it must be evaluated exactly once per signal.
        """
        if not self.startup_flip_gate or self._startup_flip_seen:
            return True, ''
        if self._startup_signal is None:
            self._startup_signal = signal
            return False, f"⏳ Startup: recorded initial signal={signal}, waiting for trend flip"
        if signal == self._startup_signal:
            return False, f"⏳ Startup: trend hasn't flipped yet (still {signal})"
        self._startup_flip_seen = True
        logger.info(
            f"✅ Startup flip detected: {self._startup_signal} → {signal} — entries now enabled")
        return True, ''

    def _check_open_position(self, signal: str) -> Tuple[bool, str]:
        """
        One position at a time.

        The single exception is a reverse-signal exit: with
        `reverse_signal_exit: true`, an opposite-direction signal is an
        exit-and-reenter and the caller closes the open position before the new
        entry lands. Same-direction signals are always blocked.
        """
        if not self.has_open_position:
            return True, ''
        if (
            self.reverse_signal_exit
            and self.open_position_direction is not None
            and signal != self.open_position_direction
        ):
            return True, ''
        if self.reverse_signal_exit and self.open_position_direction is None:
            # Direction unknown (backtest does not always set it) — defer to the
            # caller's own reverse-close handling rather than silently dropping
            # a legitimate reverse entry.
            return True, ''
        return False, "🚫 Max positions: position already open"

    def _evaluate_entry_gates(self, signal: str, candle_ts=None) -> Tuple[bool, str]:
        """
        The one and only entry-gate chain. Both ``execute(context)`` (the
        sequential orchestrator the live bot runs) and
        ``on_signal_generated(event)`` (the EventBus path that
        run_skills_backtest.py drives) route through this, so the two cannot
        drift apart again.

        They previously were two separate chains with different rules: the event
        path was missing the startup-flip and open-position gates, so anything
        routed that way could stack positions; the context path was missing the
        circuit breaker, session filter and news kill-switch, so the live bot
        silently ignored all three.

        Order matters — the startup gate mutates state and must be first, and
        cooldown stays last. Returns (allowed, reason).
        """
        # 1. Startup flip
        ok, reason = self._check_startup_flip(signal)
        if not ok:
            return False, reason

        # 2. One position at a time
        ok, reason = self._check_open_position(signal)
        if not ok:
            return False, reason

        # 3. Skip-hours filter (cheapest real check)
        if self.skip_hours:
            ts_hour = pd.Timestamp(candle_ts).hour if candle_ts else datetime.now().hour
            if ts_hour in self.skip_hours:
                return False, f"🚫 Skip hour: {ts_hour:02d}h UTC"

        # 4. Consecutive-loss circuit breaker
        ok, reason = self._check_loss_circuit(timestamp=candle_ts)
        if not ok:
            return False, reason

        # 5. Daily-loss limit
        ok, reason = self._check_daily_loss(timestamp=candle_ts)
        if not ok:
            return False, reason

        # 6. Trading hours
        if self.trading_hours_enabled:
            ok, reason = self._check_trading_hours(timestamp=candle_ts)
            if not ok:
                return False, f"🚫 Trading hours: {reason}"

        # 7. Circuit breaker (injected; None = not configured)
        if self.circuit_breaker:
            from core.circuit_breakers import CircuitBreakerStatus
            status, reason = self.circuit_breaker.check_status(self.current_capital)
            if status != CircuitBreakerStatus.CLOSED:
                return False, f"🚫 Circuit breaker: {reason}"

        # 8. Session filter
        if self.session_filter:
            ok, reason = self.session_filter.is_trading_allowed()
            if not ok:
                return False, f"🚫 Session: {reason}"

        # 9. News kill switch
        if self.news_killswitch:
            ok, reason = self.news_killswitch.is_trading_allowed()
            if not ok:
                return False, f"🚫 News: {reason}"

        # 10. Cooldown (last — anchored to the previous close)
        ok, reason = self._check_cooldown(signal, timestamp=candle_ts)
        if not ok:
            return False, reason

        return True, "✅ Risk checks passed"

    async def execute(self, context) -> 'Context':
        """
        Context-pipeline path (sequential orchestrator — this is what the live
        bot runs). Validates signal → sets context.is_allowed / risk_reason.
        """
        if not context.signal or context.signal not in ('BUY', 'SELL'):
            return context

        candle_ts = context.current_candle.get('timestamp') if context.current_candle else None
        allowed, reason = self._evaluate_entry_gates(context.signal, candle_ts)

        context.is_allowed  = allowed
        context.risk_reason = reason
        if allowed:
            context.position_size = self._calculate_position_size()
        return context

    async def on_signal_generated(self, event: 'Event') -> None:
        """
        EventBus path (SIGNAL_GENERATED → RISK_APPROVED / RISK_REJECTED).
        Runs the same gate chain as execute().
        """
        signal = event.payload.get('signal')
        if not signal or signal not in ['BUY', 'SELL']:
            return

        # Entry price from the signal, falling back to the indicator snapshot
        entry_price = event.payload.get('entry_price')
        if not entry_price:
            entry_price = event.payload.get('indicators', {}).get('current_price', 0)

        # Candle timestamp if available (backtest), else wall clock (live)
        candle_ts = (event.payload.get('candle', {}).get('timestamp')
                     or event.payload.get('timestamp'))

        allowed, reason = self._evaluate_entry_gates(signal, candle_ts)
        if not allowed:
            await self._publish_risk_rejected(event, reason)
            return

        position_size = self._calculate_position_size()

        # Pass through SL/TP computed by AnalysisSkill (sl_tp_engine with full
        # indicator context). RiskSkill does NOT recompute them, so the same
        # levels flow through the whole pipeline.
        stop_loss   = event.payload.get('stop_loss')
        take_profit = event.payload.get('take_profit')

        await self._publish_risk_approved(
            event, signal, position_size, entry_price, stop_loss, take_profit)

    def _check_trading_hours(self, timestamp=None) -> Tuple[bool, str]:
        """
        Check if given time (or now for live trading) is within allowed trading hours.

        Args:
            timestamp: candle timestamp for backtesting; None uses wall clock (live)
        Returns:
            (is_allowed, reason) tuple
        """
        if timestamp is not None:
            if hasattr(timestamp, 'tzinfo') and timestamp.tzinfo is not None:
                now = timestamp.astimezone(self.timezone)
            else:
                import pandas as pd
                ts = pd.Timestamp(timestamp)
                now = ts.to_pydatetime().replace(tzinfo=pytz.utc).astimezone(self.timezone)
        else:
            now = datetime.now(self.timezone)
        weekday = now.weekday()  # Monday=0, Sunday=6
        hour = now.hour
        
        # Check weekend trading (Saturday=5, Sunday=6)
        if weekday == 5 and not self.saturday_enabled:
            return False, "🚫 Weekend: Saturday trading disabled"
        if weekday == 6 and not self.sunday_enabled:
            return False, "🚫 Weekend: Sunday trading disabled"
        
        # Check weekday trading
        weekday_enabled = [
            self.monday_enabled,    # 0: Monday
            self.tuesday_enabled,   # 1: Tuesday
            self.wednesday_enabled, # 2: Wednesday
            self.thursday_enabled,  # 3: Thursday
            self.friday_enabled,    # 4: Friday
            self.saturday_enabled,  # 5: Saturday
            self.sunday_enabled     # 6: Sunday
        ]
        
        if not weekday_enabled[weekday]:
            day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            return False, f"🚫 {day_names[weekday]} trading disabled"
        
        # Check Friday special rules
        if weekday == 4:  # Friday
            if hour >= self.friday_no_new_trades_hour:
                return False, f"🚫 Friday: No new trades after {self.friday_no_new_trades_hour}:00 UTC"
        
        # Check daily trading window
        if hour < self.start_hour or hour >= self.end_hour:
            return False, f"🚫 Outside trading hours: {self.start_hour}:00-{self.end_hour}:00 UTC (current: {hour}:00)"
        
        # Check daily break
        if self.daily_break_enabled:
            if self.break_start_hour <= hour < self.break_end_hour:
                return False, f"🚫 Daily break: {self.break_start_hour}:00-{self.break_end_hour}:00 UTC"
        
        # All checks passed
        return True, f"✅ Trading allowed ({now.strftime('%A %H:%M UTC')})"
    
    async def _publish_risk_approved(self, event: 'Event', signal: str, 
                                     position_size: float, entry_price: float,
                                     stop_loss: float, take_profit: float):
        """Publish RISK_APPROVED event"""
        if not self.event_bus:
            return
        
        from core.event_bus import create_risk_approved_event
        await self.event_bus.publish(
            create_risk_approved_event(
                signal=signal,
                position_size=position_size,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                instrument=event.instrument,
                correlation_id=event.correlation_id
            )
        )
        # print only in debug mode — expected to be very noisy during live trading
        #print(f"✅ Risk approved: {signal} @ entry={entry_price} size={position_size} SL={stop_loss} TP={take_profit}")
    
    async def _publish_risk_rejected(self, event: 'Event', reason: str):
        """Publish RISK_REJECTED event"""
        if not self.event_bus:
            return
        
        from core.event_bus import create_risk_rejected_event
        await self.event_bus.publish(
            create_risk_rejected_event(
                reason=reason,
                instrument=event.instrument,
                correlation_id=event.correlation_id
            )
        )
        # Rejection logged at debug level only — expected during weekends/cooldowns
        # print(f"🚫 Risk rejected: {reason}")  # uncomment for debugging
    
    def _calculate_sl_tp(self, current_price: float, signal: str, 
                         sl_pips: int, tp_pips: int) -> Tuple[float, float]:
        """Calculate stop loss and take profit levels"""
        # For GOLD, 1 pip = 0.01
        pip_value = 0.01
        
        if signal == 'BUY':
            stop_loss = current_price - (sl_pips * pip_value)
            take_profit = current_price + (tp_pips * pip_value)
        else:  # SELL
            stop_loss = current_price + (sl_pips * pip_value)
            take_profit = current_price - (tp_pips * pip_value)
        
        return round(stop_loss, 2), round(take_profit, 2)
    
    def _check_cooldown(self, signal: str, timestamp=None) -> Tuple[bool, str]:
        """
        Check if cooldown period has elapsed since last close.
        
        Cooldown rules:
        - 15 minutes after SL hit (same direction)
        - 5 minutes after TP hit (same direction)
        - No cooldown for opposite direction (allow reversals)
        
        Args:
            signal:    Current signal ('BUY' or 'SELL')
            timestamp: Candle timestamp (backtest) or None (live → wall clock)
            
        Returns:
            (is_allowed, reason) tuple
        """
        if not self.last_closed_position:
            return True, "No cooldown active"
        
        last_direction = self.last_closed_position.get('direction')
        last_close_reason = self.last_closed_position.get('close_reason')
        last_close_time = self.last_closed_position.get('close_time')
        
        # Only enforce cooldown for SAME direction
        if signal != last_direction:
            return True, "Different direction - cooldown bypassed"
        
        # Use candle timestamp for backtesting; fall back to wall clock for live
        import pandas as pd
        if timestamp is not None:
            now = pd.Timestamp(timestamp).to_pydatetime().replace(tzinfo=None)
        else:
            now = datetime.now()
        # Ensure last_close_time is also tz-naive for comparison
        if hasattr(last_close_time, 'tzinfo') and last_close_time.tzinfo is not None:
            last_close_time = last_close_time.replace(tzinfo=None)
        time_elapsed = now - last_close_time
        minutes_elapsed = time_elapsed.total_seconds() / 60
        
        # Check SL cooldown (15 minutes)
        if last_close_reason == 'SL_HIT':
            if minutes_elapsed < self.sl_cooldown_minutes:
                return False, f"🚫 SL cooldown: {minutes_elapsed:.1f}m < {self.sl_cooldown_minutes}m"
            else:
                return True, f"✅ SL cooldown passed: {minutes_elapsed:.1f}m"
        
        # Check TP cooldown (5 minutes)
        if last_close_reason == 'TP_HIT':
            if minutes_elapsed < self.tp_cooldown_minutes:
                return False, f"🚫 TP cooldown: {minutes_elapsed:.1f}m < {self.tp_cooldown_minutes}m"
            else:
                return True, f"✅ TP cooldown passed: {minutes_elapsed:.1f}m"
        
        # No specific cooldown (SIGNAL or manual close)
        return True, "No cooldown required"
    
    def _check_loss_circuit(self, timestamp=None) -> Tuple[bool, str]:
        """
        Consecutive-loss circuit breaker gate.

        Blocks all new entries once `max_consecutive_losses` is hit, for
        `consecutive_loss_cooldown_minutes`. When the cooldown elapses the
        counter and trip are cleared and trading resumes.

        Args:
            timestamp: candle timestamp (backtest) or None (live → wall clock)
        Returns:
            (is_allowed, reason) tuple
        """
        if self.loss_circuit_until is None:
            return True, ""

        import pandas as pd
        if timestamp is not None:
            now = pd.Timestamp(timestamp).to_pydatetime().replace(tzinfo=None)
        else:
            now = datetime.now()

        if now >= self.loss_circuit_until:
            # Cooldown elapsed — reset and resume
            logger.info(
                f"✅ Loss circuit breaker reset after cooldown "
                f"({self.consecutive_losses} consecutive losses cleared)"
            )
            self.loss_circuit_until = None
            self.consecutive_losses = 0
            return True, ""

        remaining = (self.loss_circuit_until - now).total_seconds() / 60
        return False, (
            f"🚫 Loss circuit breaker: {self.consecutive_losses} consecutive "
            f"losses — paused {remaining:.0f}m more"
        )

    def _to_naive(self, timestamp):
        """Coerce a candle timestamp (backtest) or None (live → UTC wall clock) to tz-naive datetime."""
        import pandas as pd
        if timestamp is not None:
            return pd.Timestamp(timestamp).to_pydatetime().replace(tzinfo=None)
        return datetime.utcnow()

    def _check_daily_loss(self, timestamp=None) -> Tuple[bool, str]:
        """
        Daily-loss limit gate. Blocks new entries for the rest of the UTC day
        once the day's realised P&L has breached -max_daily_loss_usd. Clears
        automatically once the clock rolls into a new UTC date.
        """
        if not self.max_daily_loss_usd or self.max_daily_loss_usd <= 0:
            return True, ""
        if self._daily_halt_date is None:
            return True, ""
        if self._to_naive(timestamp).date() == self._daily_halt_date:
            return False, (
                f"🚫 Daily loss limit: {self._daily_realized_pnl:+.2f} today "
                f"(cap -{self.max_daily_loss_usd:g}) — halted until UTC rollover"
            )
        return True, ""  # new UTC day — halt no longer applies

    def _register_daily_pnl(self, pnl: float, when) -> None:
        """Accumulate realised P&L per UTC day and trip the daily-loss halt."""
        if not self.max_daily_loss_usd or self.max_daily_loss_usd <= 0 or pnl is None:
            return
        d = when.date()
        if self._daily_pnl_date != d:
            self._daily_pnl_date = d
            self._daily_realized_pnl = 0.0
        self._daily_realized_pnl += pnl
        if self._daily_realized_pnl <= -abs(self.max_daily_loss_usd) and self._daily_halt_date != d:
            self._daily_halt_date = d
            logger.warning(
                f"🛑 Daily loss limit hit: {self._daily_realized_pnl:+.2f} <= "
                f"-{self.max_daily_loss_usd:g} — halting new entries for {d} (UTC)"
            )

    def _register_trade_outcome(self, is_loss: bool, when) -> None:
        """Update the consecutive-loss counter and trip the breaker if needed."""
        if self.max_consecutive_losses <= 0:
            return  # feature disabled
        if is_loss:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.max_consecutive_losses:
                self.loss_circuit_until = when + timedelta(minutes=self.consecutive_loss_cooldown_minutes)
                logger.warning(
                    f"🛑 Loss circuit breaker TRIPPED: {self.consecutive_losses} "
                    f"consecutive losses — blocking new entries until "
                    f"{self.loss_circuit_until:%Y-%m-%d %H:%M} "
                    f"({self.consecutive_loss_cooldown_minutes}m cooldown)"
                )
        else:
            if self.consecutive_losses:
                logger.info(f"↩️  Win — consecutive-loss counter reset (was {self.consecutive_losses})")
            self.consecutive_losses = 0

    def _calculate_position_size(self) -> float:
        return self.position_size
    
    def on_position_closed(
        self,
        direction: str,
        close_reason: str,
        entry_price: float = None,
        close_price: float = None,
        close_time=None,
        pnl: float = None
    ):
        """
        Update last closed position for cooldown tracking.

        Call this method when a position is closed.

        Args:
            direction:   'BUY' or 'SELL'
            close_reason: 'SL_HIT', 'TP_HIT', or 'SIGNAL'
            entry_price: Entry price (optional)
            close_price: Close price (optional)
            close_time:  Candle timestamp (backtest) or None (live → wall clock)
            pnl:         Realised $ P&L for the trade (optional). Required for the
                         daily-loss limit; also used for the consecutive-loss
                         win/loss call when provided (falls back to prices/reason).
        """
        import pandas as pd
        if close_time is not None:
            ts = pd.Timestamp(close_time).to_pydatetime().replace(tzinfo=None)
        else:
            ts = datetime.now()
        self.last_closed_position = {
            'direction': direction,
            'close_time': ts,
            'close_reason': close_reason,
            'entry_price': entry_price,
            'close_price': close_price
        }

        # Feed the risk breakers. Prefer realised $ P&L sign (captures
        # tick/SIGNAL/EOD exits, not just SL/TP); fall back to price distance,
        # then to the close reason.
        is_loss = None
        if pnl is not None:
            is_loss = pnl < 0
        elif entry_price is not None and close_price is not None and direction:
            diff = (close_price - entry_price) if direction == 'BUY' else (entry_price - close_price)
            is_loss = diff < 0
        elif close_reason == 'SL_HIT':
            is_loss = True
        elif close_reason == 'TP_HIT':
            is_loss = False
        if is_loss is not None:
            self._register_trade_outcome(is_loss, ts)

        # Daily-loss limit needs the real $ P&L (price distance is not $-accurate)
        self._register_daily_pnl(pnl, ts)

        # print only in debug mode — expected to be very noisy during live trading
        # print(f"📝 Updated last closed position: {direction} closed at {close_reason}")
    
    def validate_config(self) -> bool:
        """Validate risk skill configuration"""
        required_keys = [
            'sl_cooldown_minutes',
            'tp_cooldown_minutes',
            'position_size_pct'
        ]
        
        for key in required_keys:
            if key not in self.config:
                raise SkillExecutionError(f"Missing required config: {key}")
        
        # Validate ranges
        if self.sl_cooldown_minutes < 0:
            raise SkillExecutionError("sl_cooldown_minutes must be >= 0")
        
        if self.tp_cooldown_minutes < 0:
            raise SkillExecutionError("tp_cooldown_minutes must be >= 0")
        
        if not (0 < self.position_size_pct <= 100):
            raise SkillExecutionError("position_size_pct must be between 0 and 100")
        
        return True


# Example usage
if __name__ == "__main__":
    import asyncio
    
    # Configure risk skill
    config = {
        'sl_cooldown_minutes': 15,
        'tp_cooldown_minutes': 5,
        'position_size_pct': 2.0,
        'max_drawdown_pct': 20.0,
        'max_positions': 1
    }
    
    risk_skill = RiskSkill(config)
    
    # Test 1: Validate BUY signal (no cooldown)
    print("Test 1: BUY signal, no cooldown")
    context = Context(signal='BUY')
    context = asyncio.run(risk_skill.execute(context))
    print(f"  Allowed: {context.is_allowed}, Reason: {context.risk_reason}\n")
    
    # Test 2: Close position with SL_HIT
    print("Test 2: Close position with SL_HIT")
    risk_skill.on_position_closed(direction='BUY', close_reason='SL_HIT')
    
    # Test 3: Try BUY again immediately (should be blocked)
    print("Test 3: BUY signal, within SL cooldown")
    context = Context(signal='BUY')
    context = asyncio.run(risk_skill.execute(context))
    print(f"  Allowed: {context.is_allowed}, Reason: {context.risk_reason}\n")
    
    # Test 4: Try SELL immediately (should be allowed - opposite direction)
    print("Test 4: SELL signal, opposite direction")
    context = Context(signal='SELL')
    context = asyncio.run(risk_skill.execute(context))
    print(f"  Allowed: {context.is_allowed}, Reason: {context.risk_reason}\n")
    
    # Test 5: Simulate 15 minutes passing
    print("Test 5: BUY signal after 15 minutes")
    risk_skill.last_closed_position['close_time'] = datetime.now() - timedelta(minutes=16)
    context = Context(signal='BUY')
    context = asyncio.run(risk_skill.execute(context))
    print(f"  Allowed: {context.is_allowed}, Reason: {context.risk_reason}\n")
