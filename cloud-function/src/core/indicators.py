"""
Pure indicator calculation functions — each is independently unit-testable.

All functions are stateless: they take a DataFrame (or scalar params) and
return a Series / DataFrame. No class state required.
"""

import pandas as pd
import numpy as np
from typing import Tuple, Optional


def calculate_atr(df: pd.DataFrame, period: int) -> pd.Series:
    """
    Average True Range.

    Args:
        df: DataFrame with 'high', 'low', 'close' columns
        period: Rolling window for ATR

    Returns:
        ATR Series
    """
    high = df['high']
    low = df['low']
    close = df['close']

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def calculate_supertrend(
    df: pd.DataFrame,
    period: int,
    multiplier: float,
) -> Tuple[pd.Series, pd.Series]:
    """
    Supertrend indicator.

    Args:
        df: DataFrame with 'high', 'low', 'close'
        period: ATR period
        multiplier: ATR multiplier for bands

    Returns:
        (supertrend, direction) — direction: 1 = uptrend, -1 = downtrend
    """
    atr = calculate_atr(df, period)
    hl2 = (df['high'] + df['low']) / 2

    upper_band = hl2 + (multiplier * atr)
    lower_band = hl2 - (multiplier * atr)

    supertrend = pd.Series(index=df.index, dtype=float)
    direction = pd.Series(index=df.index, dtype=float)

    first_valid_idx = atr.first_valid_index()
    if first_valid_idx is None:
        return supertrend, direction

    first_pos = df.index.get_loc(first_valid_idx)
    supertrend.iloc[first_pos] = upper_band.iloc[first_pos]
    direction.iloc[first_pos] = 1

    for i in range(first_pos + 1, len(df)):
        prev_st = supertrend.iloc[i - 1]
        prev_close = df['close'].iloc[i - 1]

        if prev_close <= prev_st:
            # Was in downtrend
            new_st = upper_band.iloc[i] if (upper_band.iloc[i] < prev_st or prev_close > prev_st) else prev_st
        else:
            # Was in uptrend
            new_st = lower_band.iloc[i] if (lower_band.iloc[i] > prev_st or prev_close < prev_st) else prev_st

        supertrend.iloc[i] = new_st
        direction.iloc[i] = 1 if df['close'].iloc[i] > new_st else -1

    return supertrend, direction


def calculate_heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """
    Heikin-Ashi candles.

    Args:
        df: DataFrame with 'open', 'high', 'low', 'close'

    Returns:
        DataFrame with 'ha_open', 'ha_high', 'ha_low', 'ha_close'
    """
    ha = df.copy()

    ha['ha_close'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    ha['ha_open'] = 0.0
    ha.iloc[0, ha.columns.get_loc('ha_open')] = (df.iloc[0]['open'] + df.iloc[0]['close']) / 2

    for i in range(1, len(ha)):
        ha.iloc[i, ha.columns.get_loc('ha_open')] = (
            ha.iloc[i - 1]['ha_open'] + ha.iloc[i - 1]['ha_close']
        ) / 2

    ha['ha_high'] = ha[['high', 'ha_open', 'ha_close']].max(axis=1)
    ha['ha_low'] = ha[['low', 'ha_open', 'ha_close']].min(axis=1)

    return ha[['ha_open', 'ha_high', 'ha_low', 'ha_close']]


def calculate_bollinger_bands(
    df: pd.DataFrame,
    period: int,
    std_dev: float,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Bollinger Bands.

    Args:
        df: DataFrame with 'close'
        period: Rolling window
        std_dev: Number of standard deviations

    Returns:
        (upper_band, middle_band, lower_band)
    """
    middle = df['close'].rolling(window=period).mean()
    std = df['close'].rolling(window=period).std()
    return middle + (std * std_dev), middle, middle - (std * std_dev)


def calculate_rsi(df: pd.DataFrame, period: int) -> pd.Series:
    """
    Relative Strength Index.

    Args:
        df: DataFrame with 'close'
        period: RSI period

    Returns:
        RSI Series
    """
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    """
    Volume Weighted Average Price.

    Args:
        df: DataFrame with 'high', 'low', 'close', 'volume'

    Returns:
        VWAP Series
    """
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    return (typical_price * df['volume']).cumsum() / df['volume'].cumsum()
