"""
Fibonacci retracement / extension calculations — independently unit-testable.

All functions are pure (stateless): they accept price DataFrames or scalars
and return levels or pip distances.
"""

import pandas as pd
from typing import Dict, Optional, Tuple


def find_swing_points(df: pd.DataFrame, lookback: int = 5) -> Tuple[pd.Series, pd.Series]:
    """
    Identify swing highs and swing lows.

    A swing high is a bar whose 'high' exceeds all bars within *lookback* on
    either side.  Swing lows are the mirror image using 'low'.

    Args:
        df: DataFrame with 'high' and 'low' columns
        lookback: Bars to check on each side

    Returns:
        (swing_highs, swing_lows) — boolean Series aligned to df.index
    """
    swing_highs = pd.Series(False, index=df.index)
    swing_lows = pd.Series(False, index=df.index)

    for i in range(lookback, len(df) - lookback):
        window_highs = [df['high'].iloc[i - j] for j in range(1, lookback + 1)] + \
                       [df['high'].iloc[i + j] for j in range(1, lookback + 1)]
        swing_highs.iloc[i] = df['high'].iloc[i] > max(window_highs)

        window_lows = [df['low'].iloc[i - j] for j in range(1, lookback + 1)] + \
                      [df['low'].iloc[i + j] for j in range(1, lookback + 1)]
        swing_lows.iloc[i] = df['low'].iloc[i] < min(window_lows)

    return swing_highs, swing_lows


def get_recent_swing_points(
    df: pd.DataFrame,
    lookback_bars: int = 50,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Return the most recent swing high and swing low prices.

    Args:
        df: DataFrame with 'high' and 'low'
        lookback_bars: How many trailing bars to consider

    Returns:
        (swing_high_price, swing_low_price) — None if not found
    """
    recent = df.iloc[-lookback_bars:] if len(df) > lookback_bars else df
    swing_highs, swing_lows = find_swing_points(recent)

    high_idx = swing_highs[swing_highs].index
    low_idx = swing_lows[swing_lows].index

    swing_high = recent.loc[high_idx[-1], 'high'] if len(high_idx) > 0 else None
    swing_low = recent.loc[low_idx[-1], 'low'] if len(low_idx) > 0 else None

    return swing_high, swing_low


def calculate_fibonacci_levels(
    swing_high: float,
    swing_low: float,
    direction: int,
) -> Dict[str, float]:
    """
    Fibonacci retracement and extension price levels.

    Args:
        swing_high: Recent swing high price
        swing_low: Recent swing low price
        direction: 1 = long (buy), -1 = short (sell)

    Returns:
        Dict with keys: 'sl', 'tp1', 'tp2', 'tp3', 'tp4'
    """
    diff = swing_high - swing_low

    if direction == 1:  # Long
        return {
            'sl':  swing_low  - (0.236 * diff),
            'tp1': swing_low  + (0.618 * diff),
            'tp2': swing_high,
            'tp3': swing_high + (0.618 * diff),
            'tp4': swing_high + (1.0   * diff),
        }
    else:  # Short
        return {
            'sl':  swing_high + (0.236 * diff),
            'tp1': swing_high - (0.618 * diff),
            'tp2': swing_low,
            'tp3': swing_low  - (0.618 * diff),
            'tp4': swing_low  - (1.0   * diff),
        }


def calculate_fibonacci_tp_sl(
    df: pd.DataFrame,
    direction: int,
    entry_price: float,
    pip_value: float,
    lookback_bars: int = 50,
    swing_lookback: int = 5,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Derive TP and SL pip distances from Fibonacci levels.

    Uses the most recent swing high/low to build Fibonacci levels, then
    selects TP2 (previous swing extreme) and the corresponding SL.

    Args:
        df: Recent price DataFrame with 'high' and 'low'
        direction: 1 = long, -1 = short
        entry_price: Trade entry price
        pip_value: Price distance per pip (e.g. 0.5 for Gold)
        lookback_bars: How many bars back to look for swings
        swing_lookback: Bars on each side to qualify a swing point

    Returns:
        (tp_pips, sl_pips) or (None, None) if swing points not found
    """
    recent = df.iloc[-lookback_bars:] if len(df) > lookback_bars else df
    swing_highs, swing_lows = find_swing_points(recent, lookback=swing_lookback)

    high_idx = swing_highs[swing_highs].index
    low_idx = swing_lows[swing_lows].index

    if len(high_idx) == 0 or len(low_idx) == 0:
        return None, None

    swing_high = recent.loc[high_idx[-1], 'high']
    swing_low = recent.loc[low_idx[-1], 'low']

    levels = calculate_fibonacci_levels(swing_high, swing_low, direction)

    tp_price = levels['tp2']
    sl_price = levels['sl']

    tp_pips = abs(tp_price - entry_price) / pip_value
    sl_pips = abs(entry_price - sl_price) / pip_value

    return tp_pips, sl_pips
