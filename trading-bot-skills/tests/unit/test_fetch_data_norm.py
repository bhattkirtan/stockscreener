"""
Unit tests — fetch_data timestamp normalisation

Regression cover for the bug that made `bar_updater` fetch NOTHING for
GOLD/ETHUSD/EURUSD/SILVER from ~Q2 2026 (coverage fell to 6-12%) while logging
"market closed or no data":

    parse_candle() emits 'YYYY-MM-DD HH:MM:SS'   (SPACE separator)
    bar_updater   passes '%Y-%m-%dT%H:%M:%S'     ('T' separator)

and fetch_all_bars compares them as STRINGS. ord(' ')==32 < ord('T')==84, so
every same-day candle compared as older than from_date and was silently
skipped. Bar-count mode (--bars N) was unaffected because it does no date
filtering, which is why only US100 — already up to date, never entering the
incremental path — escaped.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from fetch_data import _norm_ts, parse_candle


class TestNormTs:

    @pytest.mark.parametrize('raw,expected', [
        ('2026-10-21T02:20:00',      '2026-10-21 02:20:00'),   # ISO with T
        ('2026-10-21 02:20:00',      '2026-10-21 02:20:00'),   # already space
        ('2026/03/29 10:00:00',      '2026-03-29 10:00:00'),   # slash date
        ('2026-03-29T10:00:00:000',  '2026-03-29 10:00:00'),   # trailing millis
        ('2026-10-21T02:20:00.123',  '2026-10-21 02:20:00'),   # fractional secs
    ])
    def test_normalises_to_one_form(self, raw, expected):
        assert _norm_ts(raw) == expected

    def test_none_passes_through(self):
        """A missing bound must stay None so the filter is skipped entirely."""
        assert _norm_ts(None) is None
        assert _norm_ts('') is None

    def test_idempotent(self):
        once = _norm_ts('2026-10-21T02:20:00')
        assert _norm_ts(once) == once


class TestTheActualBug:
    """The comparison that silently dropped six months of bars."""

    def test_unnormalised_bound_misorders_same_day_candles(self):
        candle_ts = '2026-10-21 12:15:00'      # what parse_candle produces
        from_raw  = '2026-10-21T02:20:00'      # what bar_updater passed
        # The bug: a candle 10 hours NEWER than from_date compares as older.
        assert candle_ts < from_raw, "precondition: this is the bug being fixed"

    def test_normalised_bound_orders_correctly(self):
        candle_ts = '2026-10-21 12:15:00'
        from_date = _norm_ts('2026-10-21T02:20:00')
        assert candle_ts > from_date
        # ...and the candle is therefore kept rather than skipped
        assert not (from_date and candle_ts < from_date)

    def test_candle_before_window_is_still_excluded(self):
        """Normalising must not break the filter it was meant to fix."""
        from_date = _norm_ts('2026-10-21T02:20:00')
        assert '2026-10-20 23:55:00' < from_date

    def test_candle_after_window_is_excluded(self):
        to_date = _norm_ts('2026-10-21T10:00:00')
        assert '2026-10-21 12:15:00' > to_date


class TestParseCandleContract:
    """
    _norm_ts only works as a comparison bound if parse_candle keeps emitting
    the space-separated form, and keeps preferring the UTC field.
    """

    def _price(self, **kw):
        base = {
            'snapshotTimeUTC': '2026-10-21T10:15:00',
            'snapshotTime':    '2026-10-21T12:15:00',   # exchange-local (UTC+2)
            'openPrice':  {'bid': 4100.0, 'ask': 4100.5},
            'highPrice':  {'bid': 4110.0, 'ask': 4110.5},
            'lowPrice':   {'bid': 4090.0, 'ask': 4090.5},
            'closePrice': {'bid': 4105.0, 'ask': 4105.5},
            'lastTradedVolume': 100,
        }
        base.update(kw)
        return base

    def test_emits_space_separated_timestamp(self):
        c = parse_candle(self._price())
        assert c['timestamp'] == '2026-10-21 10:15:00'
        assert 'T' not in c['timestamp']

    def test_prefers_utc_over_local(self):
        """
        snapshotTime is exchange-local and shifts with DST; snapshotTimeUTC is
        the only safe key. Using the local one also broke pagination, since the
        API's `to` parameter is interpreted as UTC.
        """
        c = parse_candle(self._price())
        assert c['timestamp'].endswith('10:15:00')   # not 12:15:00

    def test_falls_back_to_local_when_utc_absent(self):
        p = self._price()
        del p['snapshotTimeUTC']
        c = parse_candle(p)
        assert c['timestamp'] == '2026-10-21 12:15:00'

    def test_uses_bid_prices(self):
        """The live bot's Supertrend runs on bid candles — mid would shift all
        prices by half a spread and change the indicator state."""
        c = parse_candle(self._price())
        assert c['close'] == 4105.0
        assert c['open'] == 4100.0
