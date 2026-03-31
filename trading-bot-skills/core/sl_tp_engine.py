"""
SL/TP Engine — Pure Functions for Stop-Loss & Take-Profit Calculation

FUNCTIONAL DESIGN:
- Pure functions, no side effects
- Three methods: fixed pips, ATR-based, Fibonacci-based
- Also supports Supertrend as SL anchor

Methods:
  fixed      — fixed pip distance from entry
  atr        — ATR multiplier (adapts to volatility)
  fibonacci  — SL at swing extreme, TP at Fibonacci extension
  supertrend — SL at Supertrend line, TP proportional to risk

Config example:
  sl_tp:
    method: atr          # fixed | atr | fibonacci | supertrend
    stop_loss_pips: 20   # used by 'fixed'
    take_profit_pips: 40 # used by 'fixed'
    atr_sl_multiplier: 1.5
    atr_tp_multiplier: 3.0
    fibonacci_sl_level: 0.382   # e.g. SL at 38.2% retracement
    fibonacci_tp_level: 1.618   # TP at 161.8% extension
    risk_reward_ratio: 2.0      # used by 'supertrend' and as fallback
"""
from typing import Tuple, Optional
from core.indicators import calculate_fibonacci_levels, FIBONACCI_LEVELS


def calculate_fixed_sl_tp(
    signal: str,
    entry_price: float,
    sl_pips: float,
    tp_pips: float,
    pip_size: float = 1.0,
) -> Tuple[float, float]:
    """
    Fixed pip-distance SL/TP.

    Args:
        signal:      'BUY' or 'SELL'
        entry_price: Trade entry price
        sl_pips:     Stop loss distance in pips
        tp_pips:     Take profit distance in pips
        pip_size:    Price units per pip (1.0 for GOLD/indices, 0.0001 for forex)

    Returns:
        (stop_loss, take_profit)
    """
    sl_distance = sl_pips * pip_size
    tp_distance = tp_pips * pip_size
    if signal == 'BUY':
        return entry_price - sl_distance, entry_price + tp_distance
    else:  # SELL
        return entry_price + sl_distance, entry_price - tp_distance


def calculate_atr_sl_tp(
    signal: str,
    entry_price: float,
    atr: float,
    sl_multiplier: float = 1.5,
    tp_multiplier: float = 3.0,
) -> Tuple[float, float]:
    """
    ATR-based SL/TP — adapts to market volatility.

    Args:
        signal:        'BUY' or 'SELL'
        entry_price:   Trade entry price
        atr:           Current ATR value
        sl_multiplier: SL = entry ± atr * sl_multiplier
        tp_multiplier: TP = entry ± atr * tp_multiplier

    Returns:
        (stop_loss, take_profit)
    """
    sl_distance = atr * sl_multiplier
    tp_distance = atr * tp_multiplier

    if signal == 'BUY':
        return entry_price - sl_distance, entry_price + tp_distance
    else:  # SELL
        return entry_price + sl_distance, entry_price - tp_distance


def calculate_pct_sl_tp(
    signal: str,
    entry_price: float,
    sl_pct: float = 0.005,
    tp_pct: float = 0.01,
) -> Tuple[float, float]:
    """
    Percentage-based SL/TP.

    Args:
        signal:      'BUY' or 'SELL'
        entry_price: Trade entry price
        sl_pct:      Stop loss as fraction of entry (e.g. 0.005 = 0.5%)
        tp_pct:      Take profit as fraction of entry (e.g. 0.01 = 1.0%)

    Returns:
        (stop_loss, take_profit)
    """
    sl_dist = entry_price * sl_pct
    tp_dist = entry_price * tp_pct

    if signal == 'BUY':
        return entry_price - sl_dist, entry_price + tp_dist
    else:  # SELL
        return entry_price + sl_dist, entry_price - tp_dist


def calculate_fibonacci_sl_tp(
    signal: str,
    entry_price: float,
    swing_high: float,
    swing_low: float,
    sl_fib_level: float = 0.382,
    tp_fib_level: float = 1.618,
) -> Tuple[float, float]:
    """
    Fibonacci-based SL/TP.

    SL is placed at a retracement level (e.g. 38.2% pullback).
    TP is placed at an extension level (e.g. 161.8% projection).

    Args:
        signal:       'BUY' or 'SELL'
        entry_price:  Trade entry price
        swing_high:   Recent swing high (lookback high)
        swing_low:    Recent swing low (lookback low)
        sl_fib_level: Fibonacci ratio for SL (e.g. 0.382)
        tp_fib_level: Fibonacci ratio for TP extension (e.g. 1.618)

    Returns:
        (stop_loss, take_profit)
    """
    levels = calculate_fibonacci_levels(swing_high, swing_low)

    # Ensure requested levels exist (snap to nearest available)
    all_levels = sorted(levels.keys())

    def snap(target):
        return min(all_levels, key=lambda l: abs(l - target))

    sl_ratio = snap(sl_fib_level)
    tp_ratio = snap(tp_fib_level)

    sl_price = levels[sl_ratio]
    tp_price = levels[tp_ratio]

    # For BUY: SL below entry, TP above entry
    if signal == 'BUY':
        stop_loss = min(sl_price, entry_price - (swing_high - swing_low) * 0.05)
        take_profit = swing_low + (swing_high - swing_low) * tp_ratio
    else:  # SELL
        stop_loss = max(sl_price, entry_price + (swing_high - swing_low) * 0.05)
        take_profit = swing_high - (swing_high - swing_low) * tp_ratio

    return stop_loss, take_profit


def calculate_supertrend_sl_tp(
    signal: str,
    entry_price: float,
    supertrend_value: float,
    risk_reward_ratio: float = 2.0,
) -> Tuple[float, float]:
    """
    Supertrend-anchored SL/TP.

    SL is placed at the Supertrend line. TP is R:R multiple of the SL distance.

    Args:
        signal:            'BUY' or 'SELL'
        entry_price:       Trade entry price
        supertrend_value:  Current Supertrend line value
        risk_reward_ratio: TP = entry ± sl_distance * rr_ratio

    Returns:
        (stop_loss, take_profit)
    """
    stop_loss = supertrend_value
    sl_distance = abs(entry_price - stop_loss)
    tp_distance = sl_distance * risk_reward_ratio

    if signal == 'BUY':
        take_profit = entry_price + tp_distance
    else:  # SELL
        take_profit = entry_price - tp_distance

    return stop_loss, take_profit


def compute_sl_tp(
    signal: str,
    entry_price: float,
    sl_tp_config: dict,
    atr: Optional[float] = None,
    supertrend_value: Optional[float] = None,
    swing_high: Optional[float] = None,
    swing_low: Optional[float] = None,
) -> Tuple[float, float]:
    """
    Dispatcher — selects SL/TP method from config and delegates to pure function.

    Config keys (all optional, uses defaults):
        method:              'fixed' | 'atr' | 'fibonacci' | 'supertrend'
        stop_loss_pips:      float  (fixed mode)
        take_profit_pips:    float  (fixed mode)
        atr_sl_multiplier:   float  (atr mode)
        atr_tp_multiplier:   float  (atr mode)
        fibonacci_sl_level:  float  (fibonacci mode, e.g. 0.382)
        fibonacci_tp_level:  float  (fibonacci mode, e.g. 1.618)
        risk_reward_ratio:   float  (supertrend mode, also fallback)

    Returns:
        (stop_loss, take_profit)
    """
    method = sl_tp_config.get('method', 'fixed')

    if method == 'pct':
        return calculate_pct_sl_tp(
            signal=signal,
            entry_price=entry_price,
            sl_pct=sl_tp_config.get('sl_pct', 0.005),
            tp_pct=sl_tp_config.get('tp_pct', 0.01),
        )

    elif method == 'atr' and atr is not None and atr > 0:
        return calculate_atr_sl_tp(
            signal=signal,
            entry_price=entry_price,
            atr=atr,
            sl_multiplier=sl_tp_config.get('atr_sl_multiplier', 1.5),
            tp_multiplier=sl_tp_config.get('atr_tp_multiplier', 3.0),
        )

    elif method == 'fibonacci' and swing_high is not None and swing_low is not None:
        return calculate_fibonacci_sl_tp(
            signal=signal,
            entry_price=entry_price,
            swing_high=swing_high,
            swing_low=swing_low,
            sl_fib_level=sl_tp_config.get('fibonacci_sl_level', 0.382),
            tp_fib_level=sl_tp_config.get('fibonacci_tp_level', 1.618),
        )

    elif method == 'supertrend' and supertrend_value is not None:
        return calculate_supertrend_sl_tp(
            signal=signal,
            entry_price=entry_price,
            supertrend_value=supertrend_value,
            risk_reward_ratio=sl_tp_config.get('risk_reward_ratio', 2.0),
        )

    else:
        # Default: fixed pips
        return calculate_fixed_sl_tp(
            signal=signal,
            entry_price=entry_price,
            sl_pips=sl_tp_config.get('stop_loss_pips', 20),
            tp_pips=sl_tp_config.get('take_profit_pips', 40),
            pip_size=sl_tp_config.get('pip_size', 1.0),
        )
