"""
Unit tests for src/core/indicators.py

Each indicator function is stateless; tests feed a plain DataFrame and assert
outputs — no mocking required.
"""
import unittest
import sys
import os

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.core.indicators import calculate_supertrend, calculate_atr, calculate_heikin_ashi


def _make_ohlc(n: int, base_price: float = 2000.0, step: float = 1.0) -> pd.DataFrame:
    """Return a simple rising OHLC DataFrame with a DatetimeIndex."""
    timestamps = pd.date_range('2026-01-01', periods=n, freq='5min')
    close = base_price + np.arange(n) * step
    return pd.DataFrame({
        'open':  close - 0.5,
        'high':  close + 1.0,
        'low':   close - 1.0,
        'close': close,
    }, index=timestamps)


class TestCalculateSupertrend(unittest.TestCase):

    def test_normal_output_shape(self):
        """supertrend and direction have same length as input."""
        df = _make_ohlc(50)
        st, direction = calculate_supertrend(df, period=7, multiplier=2.0)
        self.assertEqual(len(st), len(df))
        self.assertEqual(len(direction), len(df))

    def test_direction_values_are_1_or_minus1(self):
        """All non-NaN direction values must be +1 or -1."""
        df = _make_ohlc(50)
        _, direction = calculate_supertrend(df, period=7, multiplier=2.0)
        valid = direction.dropna()
        self.assertTrue(((valid == 1) | (valid == -1)).all(),
                        f"Unexpected direction values: {valid.unique()}")

    def test_rising_market_ends_in_uptrend(self):
        """A steadily rising price series should finish in an uptrend (direction = 1)."""
        df = _make_ohlc(100, step=2.0)
        _, direction = calculate_supertrend(df, period=7, multiplier=2.0)
        self.assertEqual(direction.iloc[-1], 1.0)

    def test_falling_market_ends_in_downtrend(self):
        """A steadily falling price series should finish in a downtrend (direction = -1)."""
        df = _make_ohlc(100, step=-2.0)
        _, direction = calculate_supertrend(df, period=7, multiplier=2.0)
        self.assertEqual(direction.iloc[-1], -1.0)

    def test_too_few_bars_returns_empty(self):
        """If the DataFrame is shorter than the ATR period, return all-NaN series."""
        df = _make_ohlc(3)  # period=7 needs at least 7 bars
        st, direction = calculate_supertrend(df, period=7, multiplier=2.0)
        self.assertTrue(st.isna().all())
        self.assertTrue(direction.isna().all())

    # -----------------------------------------------------------------------
    # THE BUG that caused 5 days of missed trades (Mar 20–25 2026):
    # WebSocket can deliver two candles with the same timestamp.
    # pandas get_loc() returns a slice (not an int) for duplicate index labels,
    # and the old code did  slice + int  which raises TypeError.
    # -----------------------------------------------------------------------
    def test_duplicate_timestamps_do_not_raise(self):
        """
        Regression test: duplicate candle timestamps (as fed by the WebSocket)
        must not raise 'unsupported operand type(s) for +: slice and int'.
        """
        df = _make_ohlc(50)
        # Duplicate the 8th row's timestamp (index position 7) — this is what
        # the Capital.com WebSocket sometimes sends.
        duplicate_ts = df.index[7]
        extra_row = df.iloc[[7]].copy()
        extra_row.index = [duplicate_ts]
        df_with_dup = pd.concat([df.iloc[:8], extra_row, df.iloc[8:]])

        # Must not raise
        try:
            st, direction = calculate_supertrend(df_with_dup, period=7, multiplier=2.0)
        except TypeError as e:
            self.fail(f"calculate_supertrend raised TypeError with duplicate timestamps: {e}")

        # Output should have same length as input (including the duplicate row)
        self.assertEqual(len(st), len(df_with_dup))

    def test_duplicate_timestamps_direction_still_valid(self):
        """After deduplication the direction values should still be +1 or -1."""
        df = _make_ohlc(50)
        duplicate_ts = df.index[7]
        extra_row = df.iloc[[7]].copy()
        extra_row.index = [duplicate_ts]
        df_with_dup = pd.concat([df.iloc[:8], extra_row, df.iloc[8:]])

        _, direction = calculate_supertrend(df_with_dup, period=7, multiplier=2.0)
        valid = direction.dropna()
        self.assertTrue(((valid == 1) | (valid == -1)).all())

    def test_boolean_array_index_does_not_raise(self):
        """
        get_loc can also return a boolean ndarray for non-monotonic indexes.
        Ensure that path is also handled without error.
        """
        df = _make_ohlc(50)
        # Shuffle the index to make it non-monotonic, which can trigger the
        # boolean-array path in some pandas versions.
        shuffled_index = list(df.index)
        shuffled_index[3], shuffled_index[4] = shuffled_index[4], shuffled_index[3]
        df_shuffled = df.copy()
        df_shuffled.index = shuffled_index
        try:
            calculate_supertrend(df_shuffled, period=7, multiplier=2.0)
        except Exception as e:
            self.fail(f"calculate_supertrend raised {type(e).__name__} on non-monotonic index: {e}")


class TestCalculateATR(unittest.TestCase):

    def test_output_length(self):
        df = _make_ohlc(50)
        atr = calculate_atr(df, period=14)
        self.assertEqual(len(atr), len(df))

    def test_first_n_values_are_nan(self):
        """First (period-1) values must be NaN as the rolling window fills."""
        df = _make_ohlc(50)
        atr = calculate_atr(df, period=14)
        self.assertTrue(atr.iloc[:13].isna().all())

    def test_atr_is_positive(self):
        df = _make_ohlc(50)
        atr = calculate_atr(df, period=14)
        self.assertTrue((atr.dropna() > 0).all())


class TestCalculateHeikinAshi(unittest.TestCase):

    def test_output_columns(self):
        df = _make_ohlc(20)
        ha = calculate_heikin_ashi(df)
        for col in ('ha_open', 'ha_high', 'ha_low', 'ha_close'):
            self.assertIn(col, ha.columns)

    def test_ha_high_is_max(self):
        """HA high = max(high, open, close) — must be >= both open and close."""
        df = _make_ohlc(20)
        ha = calculate_heikin_ashi(df)
        self.assertTrue((ha['ha_high'] >= ha['ha_open']).all())
        self.assertTrue((ha['ha_high'] >= ha['ha_close']).all())

    def test_ha_low_is_min(self):
        """HA low = min(low, open, close) — must be <= both open and close."""
        df = _make_ohlc(20)
        ha = calculate_heikin_ashi(df)
        self.assertTrue((ha['ha_low'] <= ha['ha_open']).all())
        self.assertTrue((ha['ha_low'] <= ha['ha_close']).all())


if __name__ == '__main__':
    unittest.main(verbosity=2)
