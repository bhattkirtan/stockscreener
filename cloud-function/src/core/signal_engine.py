"""
Shared Signal Engine - Used by both backtester and live bot
Ensures identical signal generation and exit logic across all systems.

FUNCTIONAL DESIGN:
- Pure functions with no side effects
- Immutable data structures
- Stateless signal evaluation
- Composable logic

This module contains the core trading logic:
1. Signal generation (BUY/SELL entry conditions)
2. Reverse signal detection (exit conditions)
3. Signal validation

Author: Trading Bot Team
"""
from typing import Dict, Optional, Tuple, NamedTuple
from enum import Enum
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


class SignalType(Enum):
    """Trading signal types"""
    NONE = 0
    BUY = 1
    SELL = -1


@dataclass(frozen=True)  # Immutable
class MarketState:
    """Immutable snapshot of market indicators at a point in time"""
    close: float
    supertrend_direction: int  # 1=UP, -1=DOWN
    ema: float
    sma_fast: float
    sma_slow: float
    timestamp: Optional[str] = None  # For debugging


@dataclass(frozen=True)  # Immutable
class SignalConditions:
    """Breakdown of signal conditions for transparency"""
    st_is_up: bool
    st_is_down: bool
    price_above_ema: bool
    price_below_ema: bool
    sma_fast_above_slow: bool
    sma_fast_below_slow: bool
    buy_conditions_met: bool
    sell_conditions_met: bool


@dataclass(frozen=True)  # Immutable
class PositionState:
    """Immutable position state for exit checking"""
    side: str  # 'BUY' or 'SELL'
    entry_price: float
    stop_loss: float
    take_profit: float
    entry_time: Optional[str] = None


class ExitReason(Enum):
    """Exit reasons for transparency"""
    NONE = "NO_EXIT"
    STOP_LOSS = "SL_HIT"
    TAKE_PROFIT = "TP_HIT"
    REVERSE_SIGNAL = "Reverse Signal"
    TIME_EXIT = "TIME_EXIT"
    EOD_CLOSE = "EOD_CLOSE"


# ============================================================================
# PURE FUNCTIONS - Core Signal Logic (Stateless)
# ============================================================================

def check_buy_conditions(market: MarketState, golden_cross: bool = False) -> bool:
    """
    Pure function: Check if BUY signal conditions are met.
    
    BUY Logic:
    - Supertrend direction is UP (1)
    - Price is above EMA (momentum)
    - Either golden cross OR Fast SMA is above Slow SMA (trend confirmation)
    
    Args:
        market: Immutable market state
        golden_cross: True if a golden cross just occurred (fast SMA crossed above slow)
        
    Returns:
        bool: True if all BUY conditions met
    """
    return (
        market.supertrend_direction == 1 and
        market.close > market.ema and
        (golden_cross or market.sma_fast > market.sma_slow)
    )


def check_sell_conditions(market: MarketState, death_cross: bool = False) -> bool:
    """
    Pure function: Check if SELL signal conditions are met.
    
    SELL Logic:
    - Supertrend direction is DOWN (-1)
    - Price is below EMA (momentum)
    - Either death cross OR Fast SMA is below Slow SMA (trend confirmation)
    
    Args:
        market: Immutable market state
        death_cross: True if a death cross just occurred (fast SMA crossed below slow)
        
    Returns:
        bool: True if all SELL conditions met
    """
    return (
        market.supertrend_direction == -1 and
        market.close < market.ema and
        (death_cross or market.sma_fast < market.sma_slow)
    )


def evaluate_signal(market: MarketState, golden_cross: bool = False, death_cross: bool = False) -> SignalType:
    """
    Pure function: Evaluate current signal based on market state.
    
    This is stateless - it looks at current conditions only.
    No flip detection, no history tracking.
    
    Args:
        market: Immutable market state
        golden_cross: True if a golden cross just occurred (fast SMA crossed above slow)
        death_cross: True if a death cross just occurred (fast SMA crossed below slow)
        
    Returns:
        SignalType: BUY, SELL, or NONE
    """
    if check_buy_conditions(market, golden_cross):
        return SignalType.BUY
    elif check_sell_conditions(market, death_cross):
        return SignalType.SELL
    else:
        return SignalType.NONE


def check_supertrend_flip(prev_direction: Optional[int], 
                         current_direction: int) -> bool:
    """
    Pure function: Check if Supertrend direction changed.
    
    Args:
        prev_direction: Previous Supertrend direction (None if first candle)
        current_direction: Current Supertrend direction
        
    Returns:
        bool: True if direction changed or first candle
    """
    if prev_direction is None:
        return True  # First candle, treat as flip
    return prev_direction != current_direction


def evaluate_entry_signal(market: MarketState,
                          prev_supertrend_direction: Optional[int] = None,
                          require_flip: bool = True) -> SignalType:
    """
    Pure function: Evaluate entry signal with optional flip detection.
    
    Args:
        market: Immutable market state
        prev_supertrend_direction: Previous ST direction for flip detection
        require_flip: If True, only signal on Supertrend flip
        
    Returns:
        SignalType: BUY, SELL, or NONE
    """
    # Check for flip if required
    if require_flip:
        has_flipped = check_supertrend_flip(
            prev_supertrend_direction, 
            market.supertrend_direction
        )
        if not has_flipped:
            return SignalType.NONE
    
    # Evaluate conditions
    return evaluate_signal(market)


def check_reverse_signal(current_position_side: str,
                        market: MarketState) -> bool:
    """
    Pure function: Check if position should close due to reverse signal.
    
    Uses FULL signal logic (ST + EMA + SMA), not just Supertrend flip.
    A position closes only when a complete opposite signal fires.
    
    Args:
        current_position_side: 'BUY' or 'SELL'
        market: Immutable market state
        
    Returns:
        bool: True if position should be closed
    """
    # Get current signal (stateless evaluation)
    current_signal = evaluate_signal(market)
    
    # Check for opposite signal
    if current_position_side == 'BUY' and current_signal == SignalType.SELL:
        return True
    elif current_position_side == 'SELL' and current_signal == SignalType.BUY:
        return True
    else:
        return False


def check_stop_loss(position: PositionState, current_price: float) -> bool:
    """
    Pure function: Check if stop loss is hit.
    
    Args:
        position: Immutable position state
        current_price: Current market price
        
    Returns:
        bool: True if stop loss hit
    """
    if position.side == 'BUY':
        # LONG: SL below entry
        return current_price <= position.stop_loss
    elif position.side == 'SELL':
        # SHORT: SL above entry
        return current_price >= position.stop_loss
    return False


def check_take_profit(position: PositionState, current_price: float) -> bool:
    """
    Pure function: Check if take profit is hit.
    
    Args:
        position: Immutable position state
        current_price: Current market price
        
    Returns:
        bool: True if take profit hit
    """
    if position.side == 'BUY':
        # LONG: TP above entry
        return current_price >= position.take_profit
    elif position.side == 'SELL':
        # SHORT: TP below entry
        return current_price <= position.take_profit
    return False


def check_exit(position: PositionState, 
              current_price: float,
              market: MarketState) -> Tuple[bool, ExitReason]:
    """
    Pure function: Check all exit conditions in priority order.
    
    Priority:
    1. Stop Loss (highest priority - risk management)
    2. Take Profit (profit taking)
    3. Reverse Signal (trend change)
    
    Args:
        position: Immutable position state
        current_price: Current market price
        market: Immutable market state (for reverse signal check)
        
    Returns:
        Tuple[bool, ExitReason]: (should_exit, exit_reason)
    """
    # 1. Check Stop Loss first (risk management priority)
    if check_stop_loss(position, current_price):
        return (True, ExitReason.STOP_LOSS)
    
    # 2. Check Take Profit
    if check_take_profit(position, current_price):
        return (True, ExitReason.TAKE_PROFIT)
    
    # 3. Check Reverse Signal
    if check_reverse_signal(position.side, market):
        return (True, ExitReason.REVERSE_SIGNAL)
    
    return (False, ExitReason.NONE)


# ============================================================================
# POSITION MANAGEMENT - Pure Functions
# ============================================================================

def calculate_stop_loss(entry_price: float, 
                       side: str, 
                       sl_pips: float, 
                       pip_value: float = 1.0) -> float:
    """
    Pure function: Calculate stop loss price from entry.
    
    Args:
        entry_price: Entry price
        side: 'BUY' or 'SELL'
        sl_pips: Stop loss distance in pips
        pip_value: Value of 1 pip (default 1.0 for GOLD)
        
    Returns:
        float: Stop loss price
    """
    sl_distance = sl_pips * pip_value
    
    if side == 'BUY':
        # LONG: SL below entry
        return entry_price - sl_distance
    elif side == 'SELL':
        # SHORT: SL above entry
        return entry_price + sl_distance
    else:
        raise ValueError(f"Invalid side: {side}. Must be 'BUY' or 'SELL'")


def calculate_take_profit(entry_price: float, 
                         side: str, 
                         tp_pips: float, 
                         pip_value: float = 1.0) -> float:
    """
    Pure function: Calculate take profit price from entry.
    
    Args:
        entry_price: Entry price
        side: 'BUY' or 'SELL'
        tp_pips: Take profit distance in pips
        pip_value: Value of 1 pip (default 1.0 for GOLD)
        
    Returns:
        float: Take profit price
    """
    tp_distance = tp_pips * pip_value
    
    if side == 'BUY':
        # LONG: TP above entry
        return entry_price + tp_distance
    elif side == 'SELL':
        # SHORT: TP below entry
        return entry_price - tp_distance
    else:
        raise ValueError(f"Invalid side: {side}. Must be 'BUY' or 'SELL'")


def check_cooldown(last_exit_time: Optional[str],
                  last_exit_reason: Optional[str],
                  current_signal: SignalType,
                  last_position_side: Optional[str],
                  minutes_since_exit: float,
                  sl_cooldown_minutes: int = 15,
                  tp_cooldown_minutes: int = 5) -> Tuple[bool, str]:
    """
    Pure function: Check if signal is blocked by cooldown period.
    
    Cooldown Rules:
    - After SL hit: Wait sl_cooldown_minutes (15m) before re-entering SAME direction
    - After TP hit: Wait tp_cooldown_minutes (5m) before re-entering SAME direction
    - Reverse signals: NO cooldown (BUY→SELL or SELL→BUY allowed immediately)
    
    Args:
        last_exit_time: When last position closed (for logging)
        last_exit_reason: Why it closed ('SL_HIT', 'TP_HIT', etc)
        current_signal: Current signal attempting to enter (BUY/SELL/NONE)
        last_position_side: Side of last closed position ('BUY' or 'SELL')
        minutes_since_exit: Time elapsed since last exit
        sl_cooldown_minutes: Cooldown after SL hit (default 15 min)
        tp_cooldown_minutes: Cooldown after TP hit (default 5 min)
        
    Returns:
        Tuple[bool, str]: (is_blocked, reason_message)
    """
    # No cooldown if no previous position
    if last_exit_reason is None or last_position_side is None:
        return (False, "")
    
    # No cooldown if current signal is NONE
    if current_signal == SignalType.NONE:
        return (False, "")
    
    # Convert signal to side string
    current_side = 'BUY' if current_signal == SignalType.BUY else 'SELL'
    
    # REVERSE SIGNAL: No cooldown (BUY→SELL or SELL→BUY allowed immediately)
    if current_side != last_position_side:
        return (False, "Reverse signal - no cooldown")
    
    # SAME DIRECTION: Apply cooldown based on exit reason
    if 'SL' in last_exit_reason and minutes_since_exit < sl_cooldown_minutes:
        message = f"Cooldown: {current_side} SL hit {minutes_since_exit:.1f}m ago, need {sl_cooldown_minutes}m"
        return (True, message)
    
    if 'TP' in last_exit_reason and minutes_since_exit < tp_cooldown_minutes:
        message = f"Cooldown: {current_side} TP hit {minutes_since_exit:.1f}m ago, need {tp_cooldown_minutes}m"
        return (True, message)
    
    # Cooldown period passed
    return (False, "")


def get_signal_conditions(market: MarketState) -> SignalConditions:
    """
    Pure function: Get detailed breakdown of signal conditions.
    
    Args:
        market: Immutable market state
        
    Returns:
        SignalConditions: Immutable breakdown of all conditions
    """
    return SignalConditions(
        st_is_up=(market.supertrend_direction == 1),
        st_is_down=(market.supertrend_direction == -1),
        price_above_ema=(market.close > market.ema),
        price_below_ema=(market.close < market.ema),
        sma_fast_above_slow=(market.sma_fast > market.sma_slow),
        sma_fast_below_slow=(market.sma_fast < market.sma_slow),
        buy_conditions_met=check_buy_conditions(market),
        sell_conditions_met=check_sell_conditions(market)
    )


# ============================================================================
# LOGGING HELPERS (Side effects isolated here)
# ============================================================================

def log_signal(signal: SignalType, market: MarketState) -> None:
    """
    Side effect function: Log signal generation.
    Isolated from core logic.
    """
    if signal == SignalType.BUY:
        logger.info(f"✅ BUY SIGNAL: ST=UP, Price {market.close:.2f} > EMA {market.ema:.2f}, "
                   f"SMA_fast {market.sma_fast:.2f} > SMA_slow {market.sma_slow:.2f}")
    elif signal == SignalType.SELL:
        logger.info(f"✅ SELL SIGNAL: ST=DOWN, Price {market.close:.2f} < EMA {market.ema:.2f}, "
                   f"SMA_fast {market.sma_fast:.2f} < SMA_slow {market.sma_slow:.2f}")


def log_reverse_signal(side: str) -> None:
    """Side effect function: Log reverse signal detection"""
    opposite = 'SELL' if side == 'BUY' else 'BUY'
    logger.info(f"🔄 REVERSE SIGNAL: Close {side}, {opposite} signal detected")


def log_conditions_not_met(market: MarketState) -> None:
    """Side effect function: Log when flip occurred but conditions not met"""
    if market.supertrend_direction == 1:
        logger.debug(f"⚠️ ST flipped UP but conditions not met: "
                    f"Price>{market.ema}={market.close>market.ema}, "
                    f"SMA_fast>{market.sma_slow}={market.sma_fast>market.sma_slow}")
    elif market.supertrend_direction == -1:
        logger.debug(f"⚠️ ST flipped DOWN but conditions not met: "
                    f"Price<{market.ema}={market.close<market.ema}, "
                    f"SMA_fast<{market.sma_slow}={market.sma_fast<market.sma_slow}")


# ============================================================================
# CONVENIENCE FUNCTIONS (Wrappers for common patterns)
# ============================================================================

def create_market_state(close: float,
                       supertrend_direction: int,
                       ema: float,
                       sma_fast: float,
                       sma_slow: float,
                       timestamp: Optional[str] = None) -> MarketState:
    """
    Convenience function: Create immutable MarketState from raw values.
    
    Returns:
        MarketState: Immutable market snapshot
    """
    return MarketState(
        close=close,
        supertrend_direction=supertrend_direction,
        ema=ema,
        sma_fast=sma_fast,
        sma_slow=sma_slow,
        timestamp=timestamp
    )
