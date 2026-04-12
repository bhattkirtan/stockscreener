"""
Pure Technical Indicator Functions

FUNCTIONAL DESIGN:
- All functions are pure (no side effects, no global state)
- Each function accepts a pd.DataFrame or pd.Series and returns computed values
- Composable — call in any order from any skill or backtest
- Used by AnalysisSkill, BacktestingSkill, and backtests

Indicators implemented:
  Trend:     Supertrend, SMA, EMA, VWAP, MACD
  Momentum:  RSI, Stochastic
  Volatility: Bollinger Bands, ATR
  Volume:    Volume SMA, Volume Ratio
"""
from typing import Tuple
import pandas as pd
import numpy as np


# ──────────────────────────────────────────────
# TREND
# ──────────────────────────────────────────────

def calculate_sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(period, min_periods=period).mean()


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def calculate_supertrend(
    df: pd.DataFrame, period: int, multiplier: float
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    Supertrend indicator.
    Returns:
        supertrend_value (pd.Series): Active Supertrend line (lower band when up, upper when down)
        direction        (pd.Series): +1 = uptrend, -1 = downtrend
        final_upper      (pd.Series): Upper band (resistance / bearish line)
        final_lower      (pd.Series): Lower band (support / bullish line)
    """
    atr = calculate_atr(df, period)
    hl_avg = (df['high'] + df['low']) / 2

    basic_upper = hl_avg + multiplier * atr
    basic_lower = hl_avg - multiplier * atr

    final_upper = basic_upper.copy()
    final_lower = basic_lower.copy()
    supertrend = pd.Series(np.nan, index=df.index)
    direction = pd.Series(1, index=df.index)

    for i in range(1, len(df)):
        # Upper band: carry forward if close was below previous upper band
        if df['close'].iloc[i - 1] <= final_upper.iloc[i - 1]:
            final_upper.iloc[i] = min(basic_upper.iloc[i], final_upper.iloc[i - 1])
        else:
            final_upper.iloc[i] = basic_upper.iloc[i]

        # Lower band: carry forward if close was above previous lower band
        if df['close'].iloc[i - 1] >= final_lower.iloc[i - 1]:
            final_lower.iloc[i] = max(basic_lower.iloc[i], final_lower.iloc[i - 1])
        else:
            final_lower.iloc[i] = basic_lower.iloc[i]

        # Direction
        if df['close'].iloc[i] > final_upper.iloc[i - 1]:
            direction.iloc[i] = 1
        elif df['close'].iloc[i] < final_lower.iloc[i - 1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]

        supertrend.iloc[i] = final_lower.iloc[i] if direction.iloc[i] == 1 else final_upper.iloc[i]

    return supertrend, direction, final_upper, final_lower


def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    """
    Volume Weighted Average Price (VWAP).
    Resets daily (groups by date).
    Requires columns: high, low, close, volume.
    """
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    cumulative_tp_vol = (typical_price * df['volume']).cumsum()
    cumulative_vol = df['volume'].cumsum()
    return cumulative_tp_vol / cumulative_vol.replace(0, np.nan)


def calculate_vwap_daily(df: pd.DataFrame) -> pd.Series:
    """
    VWAP that resets each calendar day.
    Requires a DatetimeIndex.
    """
    vwap = pd.Series(np.nan, index=df.index)
    typical_price = (df['high'] + df['low'] + df['close']) / 3

    if hasattr(df.index, 'date'):
        for date, group_idx in df.groupby(df.index.date).groups.items():
            tp = typical_price.loc[group_idx]
            vol = df['volume'].loc[group_idx]
            cum_vol = vol.cumsum()
            cum_tp_vol = (tp * vol).cumsum()
            vwap.loc[group_idx] = cum_tp_vol / cum_vol.replace(0, np.nan)
    else:
        vwap = calculate_vwap(df)

    return vwap


def calculate_macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    MACD (Moving Average Convergence Divergence).
    Returns: (macd_line, signal_line, histogram)
    """
    ema_fast = calculate_ema(series, fast)
    ema_slow = calculate_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, signal_period)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


# ──────────────────────────────────────────────
# MOMENTUM
# ──────────────────────────────────────────────

def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Relative Strength Index (RSI).
    Returns values in [0, 100].
    """
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calculate_stochastic(
    df: pd.DataFrame, k_period: int = 14, d_period: int = 3
) -> Tuple[pd.Series, pd.Series]:
    """
    Stochastic Oscillator (%K, %D).
    Returns: (stoch_k, stoch_d) both in [0, 100].
    """
    low_min = df['low'].rolling(k_period).min()
    high_max = df['high'].rolling(k_period).max()
    stoch_k = 100 * (df['close'] - low_min) / (high_max - low_min).replace(0, np.nan)
    stoch_d = stoch_k.rolling(d_period).mean()
    return stoch_k, stoch_d


# ──────────────────────────────────────────────
# VOLATILITY
# ──────────────────────────────────────────────

def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range."""
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift(1)).abs(),
        (df['low'] - df['close'].shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def calculate_adx(df: pd.DataFrame, period: int = 14) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Average Directional Index (ADX) with +DI and -DI.

    Returns: (adx, di_plus, di_minus)
      adx      — trend strength 0-100 (>25 = trending, <20 = ranging)
      di_plus  — bullish directional indicator
      di_minus — bearish directional indicator
    """
    high  = df['high']
    low   = df['low']
    close = df['close']

    # True Range
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs(),
    ], axis=1).max(axis=1)

    # Directional Movement
    up_move   = high - high.shift(1)
    down_move = low.shift(1) - low

    dm_plus  = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    dm_minus = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    # Wilder smoothing (EWM with alpha=1/period)
    alpha = 1.0 / period
    atr_s    = tr.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    dmp_s    = dm_plus.ewm(alpha=alpha,  min_periods=period, adjust=False).mean()
    dmm_s    = dm_minus.ewm(alpha=alpha, min_periods=period, adjust=False).mean()

    di_plus  = 100 * dmp_s / atr_s.replace(0, float('nan'))
    di_minus = 100 * dmm_s / atr_s.replace(0, float('nan'))

    dx = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, float('nan'))
    adx = dx.ewm(alpha=alpha, min_periods=period, adjust=False).mean()

    return adx, di_plus, di_minus


def calculate_bollinger_bands(
    series: pd.Series, period: int = 20, std_dev: float = 2.0
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Bollinger Bands.
    Returns: (upper, middle, lower)
    """
    middle = series.rolling(period, min_periods=period).mean()
    std = series.rolling(period, min_periods=period).std()
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return upper, middle, lower


def bb_percent_b(close: pd.Series, upper: pd.Series, lower: pd.Series) -> pd.Series:
    """Bollinger Bands %B — position of close within the bands (0=lower, 1=upper)."""
    band_width = (upper - lower).replace(0, np.nan)
    return (close - lower) / band_width


def bb_bandwidth(upper: pd.Series, middle: pd.Series, lower: pd.Series) -> pd.Series:
    """Bollinger Bands Width — normalized bandwidth."""
    return (upper - lower) / middle.replace(0, np.nan)


# ──────────────────────────────────────────────
# VOLUME
# ──────────────────────────────────────────────

def calculate_volume_sma(volume: pd.Series, period: int = 20) -> pd.Series:
    """Volume Simple Moving Average."""
    return volume.rolling(period, min_periods=1).mean()


def calculate_volume_ratio(volume: pd.Series, volume_sma: pd.Series) -> pd.Series:
    """Volume ratio: current volume / average volume. >1 = above average."""
    return volume / volume_sma.replace(0, np.nan)


def calculate_obv(df: pd.DataFrame) -> pd.Series:
    """On Balance Volume."""
    direction = np.sign(df['close'].diff()).fillna(0)
    return (direction * df['volume']).cumsum()


# ──────────────────────────────────────────────
# FIBONACCI
# ──────────────────────────────────────────────

FIBONACCI_LEVELS = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272, 1.618, 2.618]


def calculate_fibonacci_levels(swing_high: float, swing_low: float) -> dict:
    """
    Calculate Fibonacci retracement and extension levels.
    Returns a dict mapping ratio -> price level.
    """
    diff = swing_high - swing_low
    return {level: swing_high - level * diff for level in FIBONACCI_LEVELS}


def nearest_fibonacci_level(
    price: float, swing_high: float, swing_low: float
) -> Tuple[float, float]:
    """Return (nearest_fib_ratio, nearest_fib_price) to the given price."""
    levels = calculate_fibonacci_levels(swing_high, swing_low)
    closest = min(levels.items(), key=lambda kv: abs(kv[1] - price))
    return closest  # (ratio, price)
