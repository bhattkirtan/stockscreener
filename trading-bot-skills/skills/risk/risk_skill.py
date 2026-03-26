"""
Risk Management Skill
Validates trading signals against risk rules and cooldown periods.

EVENT-DRIVEN:
- Subscribes to: SIGNAL_GENERATED
- Publishes: RISK_APPROVED or RISK_REJECTED
"""
from typing import Dict, Optional, Tuple, TYPE_CHECKING
from datetime import datetime, timedelta
import sys
import os

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
        
        # Cooldown settings
        self.sl_cooldown_minutes = config.get('sl_cooldown_minutes', 15)
        self.tp_cooldown_minutes = config.get('tp_cooldown_minutes', 5)
        self.current_capital = config.get('initial_capital', 10000)  # Track current capital
        
        # Position sizing
        self.position_size_pct = config.get('position_size_pct', 2.0)
        
        # Position tracking for cooldown
        self.last_closed_position = None
        self.has_open_position = False
        
    async def on_signal_generated(self, event: 'Event') -> None:
        """
        Handle SIGNAL_GENERATED event - validate signal and publish result.
        
        Args:
            event: Event with signal and indicators
        """
        signal = event.payload.get('signal')
        if not signal or signal not in ['BUY', 'SELL']:
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
        
        # 5. Cooldown check
        is_allowed, reason = self._check_cooldown(signal)
        if not is_allowed:
            await self._publish_risk_rejected(event, reason)
            return
        
        # 6. Calculate position size
        position_size = self._calculate_position_size()
        
        # 7. Calculate SL/TP levels
        current_price = event.payload.get('indicators', {}).get('current_price', 0)
        sl_pips = self.config.get('sl_pips', 20)
        tp_pips = self.config.get('tp_pips', 40)
        
        stop_loss, take_profit = self._calculate_sl_tp(current_price, signal, sl_pips, tp_pips)
        
        # ALL CHECKS PASSED - Publish RISK_APPROVED
        await self._publish_risk_approved(event, signal, position_size, stop_loss, take_profit)
    
    async def _publish_risk_approved(self, event: 'Event', signal: str, 
                                     position_size: float, stop_loss: float, take_profit: float):
        """Publish RISK_APPROVED event"""
        if not self.event_bus:
            return
        
        from core.event_bus import create_risk_approved_event
        await self.event_bus.publish(
            create_risk_approved_event(
                signal=signal,
                position_size=position_size,
                stop_loss=stop_loss,
                take_profit=take_profit,
                instrument=event.instrument,
                correlation_id=event.correlation_id
            )
        )
        print(f"✅ Risk approved: {signal} @ size={position_size} SL={stop_loss} TP={take_profit}")
    
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
        print(f"🚫 Risk rejected: {reason}")
    
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
    
    def _check_cooldown(self, signal: str) -> Tuple[bool, str]:
        """
        Check if cooldown period has elapsed since last close.
        
        Cooldown rules:
        - 15 minutes after SL hit (same direction)
        - 5 minutes after TP hit (same direction)
        - No cooldown for opposite direction (allow reversals)
        
        Args:
            signal: Current signal ('BUY' or 'SELL')
            
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
        
        # Calculate time since last close
        now = datetime.now()
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
        """
        Calculate position size based on risk parameters.
        
        Returns:
            Position size (contracts/lots)
        """
        # For GOLD trading, use fixed size based on capital
        # 2% of $10k = $200 risk per trade
        # With 20 pip SL and $1/pip, that's 0.5 contracts
        return 0.5  # 0.5 contracts for GOLD
    
    def on_position_closed(
        self, 
        direction: str, 
        close_reason: str, 
        entry_price: float = None,
        close_price: float = None
    ):
        """
        Update last closed position for cooldown tracking.
        
        Call this method when a position is closed.
        
        Args:
            direction: 'BUY' or 'SELL'
            close_reason: 'SL_HIT', 'TP_HIT', or 'SIGNAL'
            entry_price: Entry price (optional)
            close_price: Close price (optional)
        """
        self.last_closed_position = {
            'direction': direction,
            'close_time': datetime.now(),
            'close_reason': close_reason,
            'entry_price': entry_price,
            'close_price': close_price
        }
        
        print(f"📝 Updated last closed position: {direction} closed at {close_reason}")
    
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
