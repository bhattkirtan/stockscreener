"""
TP/SL price level application functions — independently unit-testable.

Each function takes a signals DataFrame and a price DataFrame, applies the
chosen stop-loss / take-profit strategy, and returns the updated signals.

Supported strategies
--------------------
- fixed   : sl_pips * pip_value and tp_pips * pip_value from entry price
- atr     : sl_multiplier * ATR * pip_value, tp_multiplier * ATR * pip_value
- fibonacci : derived from recent swing high/low via Fibonacci levels

Use ``apply_tp_sl_by_strategy`` as a single dispatch entry point.
"""

import pandas as pd
from typing import Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.strategy import SupertrendVWAPStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_sl_tp(
    signals: pd.DataFrame,
    i: int,
    direction: int,
    close: float,
    sl_distance: float,
    tp_distance: float,
) -> None:
    """In-place update of stop_loss / take_profit at row *i*."""
    sl_col = signals.columns.get_loc('stop_loss')
    tp_col = signals.columns.get_loc('take_profit')

    if direction == 1:   # BUY
        signals.iloc[i, sl_col] = close - sl_distance
        signals.iloc[i, tp_col] = close + tp_distance
    else:                # SELL
        signals.iloc[i, sl_col] = close + sl_distance
        signals.iloc[i, tp_col] = close - tp_distance


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def apply_fixed_tp_sl(
    signals: pd.DataFrame,
    df: pd.DataFrame,
    sl_distance: float,
    tp_distance: float,
) -> pd.DataFrame:
    """
    Override TP/SL on every non-zero signal row with fixed pip-based distances.

    The strategy's ``generate_signals()`` natively uses ATR multipliers; this
    function replaces those levels with the correct fixed-pip values.

    Args:
        signals: Signals DataFrame (modified in-place and returned)
        df: Price DataFrame aligned with *signals* (used for 'close' column)
        sl_distance: Stop-loss distance in price units (sl_pips * pip_value)
        tp_distance: Take-profit distance in price units (tp_pips * pip_value)

    Returns:
        Updated signals DataFrame
    """
    for i in range(len(signals)):
        signal_val = float(signals.iloc[i]['signal'])
        if signal_val == 0:
            continue

        close = float(df.iloc[i]['close'])
        _set_sl_tp(signals, i, int(signal_val), close, sl_distance, tp_distance)

    return signals


def apply_atr_tp_sl(
    signals: pd.DataFrame,
    df: pd.DataFrame,
    sl_multiplier: float,
    tp_multiplier: float,
    pip_value: float = 1.0,
) -> pd.DataFrame:
    """
    Override TP/SL on every non-zero signal row using ATR-based distances.

    Args:
        signals: Signals DataFrame (modified in-place and returned)
        df: Price DataFrame with an 'atr' column
        sl_multiplier: SL = atr * sl_multiplier * pip_value
        tp_multiplier: TP = atr * tp_multiplier * pip_value
        pip_value: Pip value scaling factor

    Returns:
        Updated signals DataFrame
    """
    for i in range(len(signals)):
        signal_val = float(signals.iloc[i]['signal'])
        if signal_val == 0:
            continue

        close = float(df.iloc[i]['close'])
        atr_raw = df.iloc[i].get('atr', 20.0)
        atr = float(atr_raw) if hasattr(atr_raw, '__float__') else atr_raw

        sl_distance = atr * sl_multiplier * pip_value
        tp_distance = atr * tp_multiplier * pip_value
        _set_sl_tp(signals, i, int(signal_val), close, sl_distance, tp_distance)

    return signals


def apply_fibonacci_tp_sl(
    signals: pd.DataFrame,
    df: pd.DataFrame,
    pip_value: float,
) -> pd.DataFrame:
    """
    Override TP/SL on every non-zero signal row using Fibonacci levels.

    Derives swing-based Fibonacci levels from the price history up to each
    signal bar, then uses TP2 (the previous swing extreme) as the target.

    Args:
        signals: Signals DataFrame (modified in-place and returned)
        df: Price DataFrame with indicator columns
        pip_value: Pip value scaling factor

    Returns:
        Updated signals DataFrame
    """
    from src.core.fibonacci import calculate_fibonacci_tp_sl

    for i in range(len(signals)):
        signal_val = float(signals.iloc[i]['signal'])
        if signal_val == 0:
            continue

        hist_df = df.iloc[:i + 1]
        entry_price = float(hist_df.iloc[-1]['close'])
        direction = int(signal_val)

        tp_pips, sl_pips = calculate_fibonacci_tp_sl(
            hist_df, direction, entry_price, pip_value
        )

        if tp_pips is None or sl_pips is None:
            continue  # Not enough history — leave original levels

        sl_distance = sl_pips * pip_value
        tp_distance = tp_pips * pip_value
        _set_sl_tp(signals, i, direction, entry_price, sl_distance, tp_distance)

    return signals


def apply_tp_sl_by_strategy(
    signals: pd.DataFrame,
    df: pd.DataFrame,
    params: Dict,
) -> pd.DataFrame:
    """
    Dispatch TP/SL application based on ``params['tp_sl_strategy']``.

    This is the single entry point used by the optimisation worker for all
    three supported strategies.  The caller does not need to know which
    concrete function to call.

    Supported values of ``params['tp_sl_strategy']``:
        - ``'fixed'``     — fixed pip distances
        - ``'atr'``       — ATR-scaled distances
        - ``'fibonacci'`` — Fibonacci swing levels

    Args:
        signals: Signals DataFrame (modified in-place and returned)
        df: Price DataFrame with indicators
        params: Parameter dict from the optimisation grid

    Returns:
        Updated signals DataFrame
    """
    strategy_type = params.get('tp_sl_strategy', 'fixed')
    pip_value = params.get('pip_value', 1.0)

    if strategy_type == 'fixed':
        sl_distance = params['sl_pips'] * pip_value
        tp_distance = params['tp_pips'] * pip_value
        return apply_fixed_tp_sl(signals, df, sl_distance, tp_distance)

    elif strategy_type == 'atr':
        return apply_atr_tp_sl(
            signals, df,
            sl_multiplier=params['atr_sl_multiplier'],
            tp_multiplier=params['atr_tp_multiplier'],
            pip_value=pip_value,
        )

    elif strategy_type == 'fibonacci':
        return apply_fibonacci_tp_sl(signals, df, pip_value)

    # Unknown strategy — return signals unchanged
    return signals
