"""
Tests for ZoneBasedIntradayStrategy.calculate_stop_and_target

Logic under test (strategy.md Section 15):

  LONG
    stop  = zone.lower_bound - zone_width * 0.1   (just below zone)
    target = entry + (entry - stop) * min_rr       (min R:R above entry)

  SHORT
    stop  = zone.upper_bound + zone_width * 0.1   (just above zone)
    target = entry - (stop - entry) * min_rr       (min R:R below entry)
"""

import unittest
from datetime import datetime

from src.core.zone_engine import Zone, ZoneType, ZoneState, ZoneOriginType
from src.core.zone_based_strategy import ZoneBasedIntradayStrategy


def _make_zone(lower: float, upper: float, zone_type: ZoneType = ZoneType.SUPPORT) -> Zone:
    """Helper — build a minimal Zone for TP/SL tests."""
    return Zone(
        id="test_zone",
        symbol="XAUUSD",
        timeframe="H1",
        type=zone_type,
        lower_bound=lower,
        upper_bound=upper,
        midpoint=(lower + upper) / 2,
        origin_type=ZoneOriginType.SWING,
        created_at=datetime(2024, 1, 1),
        state=ZoneState.FRESH,
    )


class TestCalculateStopAndTargetLong(unittest.TestCase):
    """Tests for long direction."""

    def setUp(self):
        self.strategy = ZoneBasedIntradayStrategy()
        # support zone 2000–2010  (width = 10)
        self.zone = _make_zone(2000.0, 2010.0, ZoneType.SUPPORT)

    # ── stop placement ─────────────────────────────────────────────────────────

    def test_long_stop_is_below_zone_lower_bound(self):
        stop, _ = self.strategy.calculate_stop_and_target(2010.0, self.zone, "long")
        self.assertLess(stop, self.zone.lower_bound)

    def test_long_stop_equals_lower_minus_10pct_width(self):
        # stop = lower_bound - width * 0.1 = 2000 - 10*0.1 = 1999
        stop, _ = self.strategy.calculate_stop_and_target(2010.0, self.zone, "long")
        expected_stop = 2000.0 - 10.0 * 0.1        # 1999.0
        self.assertAlmostEqual(stop, expected_stop, places=8)

    # ── target placement ───────────────────────────────────────────────────────

    def test_long_target_is_above_entry(self):
        entry = 2010.0
        _, target = self.strategy.calculate_stop_and_target(entry, self.zone, "long")
        self.assertGreater(target, entry)

    def test_long_rr_meets_minimum_default_2(self):
        entry = 2010.0
        stop, target = self.strategy.calculate_stop_and_target(entry, self.zone, "long")
        risk   = entry - stop
        reward = target - entry
        self.assertGreater(risk, 0)
        rr = reward / risk
        self.assertAlmostEqual(rr, 2.0, places=8)

    def test_long_rr_meets_minimum_custom_3(self):
        entry = 2010.0
        stop, target = self.strategy.calculate_stop_and_target(entry, self.zone, "long", min_rr=3.0)
        risk   = entry - stop
        reward = target - entry
        rr = reward / risk
        self.assertAlmostEqual(rr, 3.0, places=8)

    def test_long_entry_below_zone_upper_still_valid(self):
        """Entry inside zone (e.g. at midpoint) — stop and R:R must still be correct."""
        entry = 2005.0   # inside zone
        stop, target = self.strategy.calculate_stop_and_target(entry, self.zone, "long")
        expected_stop = 2000.0 - 10.0 * 0.1   # 1999.0 — stop is zone-derived, not entry-derived
        self.assertAlmostEqual(stop, expected_stop, places=8)
        risk   = entry - stop
        reward = target - entry
        self.assertAlmostEqual(reward / risk, 2.0, places=8)

    def test_long_exact_values_wide_zone(self):
        """Wide zone (width=100): stop = 1900 - 10 = 1890, entry=1960, target=1960 + 70*2 = 2100."""
        zone  = _make_zone(1900.0, 2000.0, ZoneType.SUPPORT)
        entry = 1960.0
        stop, target = self.strategy.calculate_stop_and_target(entry, zone, "long")
        self.assertAlmostEqual(stop,   1900.0 - 100.0 * 0.1, places=8)   # 1890
        expected_target = entry + (entry - stop) * 2.0
        self.assertAlmostEqual(target, expected_target, places=8)


class TestCalculateStopAndTargetShort(unittest.TestCase):
    """Tests for short direction."""

    def setUp(self):
        self.strategy = ZoneBasedIntradayStrategy()
        # resistance zone 2000–2010  (width = 10)
        self.zone = _make_zone(2000.0, 2010.0, ZoneType.RESISTANCE)

    # ── stop placement ─────────────────────────────────────────────────────────

    def test_short_stop_is_above_zone_upper_bound(self):
        stop, _ = self.strategy.calculate_stop_and_target(2000.0, self.zone, "short")
        self.assertGreater(stop, self.zone.upper_bound)

    def test_short_stop_equals_upper_plus_10pct_width(self):
        # stop = upper_bound + width * 0.1 = 2010 + 10*0.1 = 2011
        stop, _ = self.strategy.calculate_stop_and_target(2000.0, self.zone, "short")
        expected_stop = 2010.0 + 10.0 * 0.1   # 2011.0
        self.assertAlmostEqual(stop, expected_stop, places=8)

    # ── target placement ───────────────────────────────────────────────────────

    def test_short_target_is_below_entry(self):
        entry = 2000.0
        _, target = self.strategy.calculate_stop_and_target(entry, self.zone, "short")
        self.assertLess(target, entry)

    def test_short_rr_meets_minimum_default_2(self):
        entry = 2000.0
        stop, target = self.strategy.calculate_stop_and_target(entry, self.zone, "short")
        risk   = stop - entry
        reward = entry - target
        self.assertGreater(risk, 0)
        rr = reward / risk
        self.assertAlmostEqual(rr, 2.0, places=8)

    def test_short_rr_meets_minimum_custom_3(self):
        entry = 2000.0
        stop, target = self.strategy.calculate_stop_and_target(entry, self.zone, "short", min_rr=3.0)
        risk   = stop - entry
        reward = entry - target
        rr = reward / risk
        self.assertAlmostEqual(rr, 3.0, places=8)

    def test_short_entry_above_zone_lower_still_valid(self):
        """Entry inside zone (e.g. at midpoint) — stop and R:R must still be correct."""
        entry = 2005.0   # inside zone
        stop, target = self.strategy.calculate_stop_and_target(entry, self.zone, "short")
        expected_stop = 2010.0 + 10.0 * 0.1   # 2011.0
        self.assertAlmostEqual(stop, expected_stop, places=8)
        risk   = stop - entry
        reward = entry - target
        self.assertAlmostEqual(reward / risk, 2.0, places=8)

    def test_short_exact_values_wide_zone(self):
        """Wide zone (width=100): stop = 2000 + 10 = 2010, entry=1940, target=1940 - 70*2 = 1800."""
        zone  = _make_zone(1900.0, 2000.0, ZoneType.RESISTANCE)
        entry = 1940.0
        stop, target = self.strategy.calculate_stop_and_target(entry, zone, "short")
        self.assertAlmostEqual(stop,   2000.0 + 100.0 * 0.1, places=8)   # 2010
        expected_target = entry - (stop - entry) * 2.0
        self.assertAlmostEqual(target, expected_target, places=8)


class TestCalculateStopAndTargetSymmetry(unittest.TestCase):
    """Long and short should be symmetric given a symmetric zone and entry at midpoint."""

    def test_symmetric_rr_long_and_short(self):
        strategy = ZoneBasedIntradayStrategy()
        zone = _make_zone(1990.0, 2010.0)   # midpoint = 2000, width = 20
        entry = 2000.0

        long_stop,  long_target  = strategy.calculate_stop_and_target(entry, zone, "long")
        short_stop, short_target = strategy.calculate_stop_and_target(entry, zone, "short")

        long_rr  = (long_target  - entry) / (entry - long_stop)
        short_rr = (entry - short_target) / (short_stop - entry)

        self.assertAlmostEqual(long_rr,  2.0, places=8)
        self.assertAlmostEqual(short_rr, 2.0, places=8)

    def test_stop_distance_is_zone_width_plus_buffer(self):
        """The 0.1-width buffer is always added regardless of entry position."""
        strategy = ZoneBasedIntradayStrategy()
        zone = _make_zone(2000.0, 2020.0)   # width = 20

        long_stop,  _ = strategy.calculate_stop_and_target(2020.0, zone, "long")
        short_stop, _ = strategy.calculate_stop_and_target(2000.0, zone, "short")

        # long stop should be 20*0.1 = 2 points below lower bound (2000)
        self.assertAlmostEqual(long_stop,  2000.0 - 2.0, places=8)
        # short stop should be 20*0.1 = 2 points above upper bound (2020)
        self.assertAlmostEqual(short_stop, 2020.0 + 2.0, places=8)


if __name__ == "__main__":
    unittest.main()
