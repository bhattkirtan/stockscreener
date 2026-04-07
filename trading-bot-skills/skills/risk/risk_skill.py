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
        self._startup_signal: Optional[str] = None
        self._startup_flip_seen: bool = False
        
    async def execute(self, context) -> 'Context':
        """
        Context-pipeline path (sequential orchestrator).
        Validates signal → sets context.is_allowed / context.risk_reason.
        """
        if not context.signal or context.signal not in ('BUY', 'SELL'):
            return context

        signal    = context.signal
        candle_ts = context.current_candle.get('timestamp') if context.current_candle else None

        # 0a. Startup flip gate — don't enter on the first signal seen after bot
        # start; wait for the trend to flip at least once first.
        # Bypassed if _startup_flip_seen is True (set when resuming a live position).
        if not self._startup_flip_seen:
            if self._startup_signal is None:
                self._startup_signal = signal
                context.is_allowed  = False
                context.risk_reason = f"⏳ Startup: recorded initial signal={signal}, waiting for trend flip"
                return context
            elif signal == self._startup_signal:
                context.is_allowed  = False
                context.risk_reason = f"⏳ Startup: trend hasn't flipped yet (still {signal})"
                return context
            else:
                # Trend has flipped — normal operation from here
                self._startup_flip_seen = True
                logger.info(f"✅ Startup flip detected: {self._startup_signal} → {signal} — entries now enabled")

        # 0b. Max positions — hard stop, no trading if position already open
        if self.has_open_position:
            context.is_allowed  = False
            context.risk_reason = "🚫 Max positions: position already open"
            return context

        # 1. Skip-hours filter
        if self.skip_hours:
            ts_hour = pd.Timestamp(candle_ts).hour if candle_ts else datetime.now().hour
            if ts_hour in self.skip_hours:
                context.is_allowed  = False
                context.risk_reason = f"🚫 Skip hour: {ts_hour:02d}h UTC"
                return context

        # 2. Trading hours
        if self.trading_hours_enabled:
            is_ok, reason = self._check_trading_hours(timestamp=candle_ts)
            if not is_ok:
                context.is_allowed  = False
                context.risk_reason = reason
                return context

        # 3. Cooldown
        is_ok, reason = self._check_cooldown(signal, timestamp=candle_ts)
        if not is_ok:
            context.is_allowed  = False
            context.risk_reason = reason
            return context

        context.is_allowed    = True
        context.risk_reason   = "✅ Risk checks passed"
        context.position_size = self._calculate_position_size()
        return context

    async def on_signal_generated(self, event: 'Event') -> None:
        """
        Handle SIGNAL_GENERATED event - validate signal and publish result.
        
        Args:
            event: Event with signal and indicators
        """
        signal = event.payload.get('signal')
        if not signal or signal not in ['BUY', 'SELL']:
            return
        
        # Extract entry_price from signal (fallback to indicators if missing)
        entry_price = event.payload.get('entry_price')
        if not entry_price:
            entry_price = event.payload.get('indicators', {}).get('current_price', 0)
        
        # 0. Trading hours check (NEW - FIRST VALIDATION)
        # Use candle timestamp if available (backtest), otherwise wall clock (live)
        candle_ts = event.payload.get('candle', {}).get('timestamp') or event.payload.get('timestamp')

        # 0a. Skip-hours filter (before everything else — cheapest check)
        if self.skip_hours:
            import pandas as pd
            ts_hour = pd.Timestamp(candle_ts).hour if candle_ts else datetime.now().hour
            if ts_hour in self.skip_hours:
                await self._publish_risk_rejected(event, f"Skip hour: {ts_hour:02d}h UTC filtered out")
                return

        if self.trading_hours_enabled:
            is_allowed, reason = self._check_trading_hours(timestamp=candle_ts)
            if not is_allowed:
                await self._publish_risk_rejected(event, f"Trading hours: {reason}")
                return
        
        # 1. Circuit breaker check
        if self.circuit_breaker:
            from core.circuit_breakers import CircuitBreakerStatus
            status, reason = self.circuit_breaker.check_status(self.current_capital)
            if status != CircuitBreakerStatus.CLOSED:
                await self._publish_risk_rejected(event, f"Circuit breaker: {reason}")
                return
        
        # 2. Session filter
        if self.session_filter:
            allowed, reason = self.session_filter.is_trading_allowed()
            if not allowed:
                await self._publish_risk_rejected(event, f"Session: {reason}")
                return
        
        # 3. Spread filter (would need current spread from market data)
        # Skipping for now - would need integration with live spread data
        
        # 4. News kill switch
        if self.news_killswitch:
            allowed, reason = self.news_killswitch.is_trading_allowed()
            if not allowed:
                await self._publish_risk_rejected(event, f"News: {reason}")
                return
        
        # 5. Cooldown check (pass candle timestamp so backtest uses data time, not wall clock)
        is_allowed, reason = self._check_cooldown(signal, timestamp=candle_ts)
        if not is_allowed:
            await self._publish_risk_rejected(event, reason)
            return
        
        # 6. Calculate position size
        position_size = self._calculate_position_size()

        # 7. Pass through SL/TP computed by AnalysisSkill (uses sl_tp_engine with full
        #    indicator context — ATR, Supertrend, Fibonacci, or fixed pips as configured).
        #    RiskSkill does NOT recompute SL/TP; ExecutionSkill/BacktestingSkill use what
        #    AnalysisSkill set so the same levels flow through the entire pipeline.
        stop_loss  = event.payload.get('stop_loss')
        take_profit = event.payload.get('take_profit')

        # ALL CHECKS PASSED - Publish RISK_APPROVED
        await self._publish_risk_approved(event, signal, position_size, entry_price, stop_loss, take_profit)
    
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
    
    def _calculate_position_size(self) -> float:
        return self.position_size
    
    def on_position_closed(
        self, 
        direction: str, 
        close_reason: str, 
        entry_price: float = None,
        close_price: float = None,
        close_time=None
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
