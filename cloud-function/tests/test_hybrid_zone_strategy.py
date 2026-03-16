"""Tests for HybridZoneSuperTrendStrategy zone blocking and stop adjustment.

Covers:
  - _should_block_long: blocked when resistance is too close, allowed when clear
  - _should_block_short: blocked when support is too close, allowed when clear
  - _adjust_long_stop_to_zone: stop pulled to zone boundary when zone is nearby
  - _adjust_short_stop_to_zone: stop pulled to zone boundary when zone is nearby
  - no blocking when cached_zones is empty (cold start < 500 bars)
  - enable_zone_filter=False bypasses all zone logic
"""

import unittest
from datetime import datetime
from unittest.mock import patch

from src.zones.zone_engine import Zone, ZoneType, ZoneState, OriginType
from src.strategies.hybrid_zone_supertrend_strategy import HybridZoneSuperTrendStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_zone(
    lower: float,
    upper: float,
    zone_type: ZoneType,
    timeframe: str = "H1",
) -> Zone:
    """Minimal Zone fixture."""
    mid = (lower + upper) / 2
    return Zone(
        id="z1",
        symbol="GOLD",
        timeframe=timeframe,
        type=zone_type,
        lower_bound=lower,
        upper_bound=upper,
        midpoint=mid,
        origin_type=OriginType.SWING,
        created_at=datetime(2024, 1, 1),
        last_tested_at=None,
        touch_count=2,
        freshness_score=1.0,
        strength_score=5.0,
        state=ZoneState.FRESH,
    )


def _make_strategy(**kwargs) -> HybridZoneSuperTrendStrategy:
    """Build a minimal HybridZoneSuperTrendStrategy."""
    defaults = dict(
        supertrend_period=10,
        supertrend_multiplier=2.0,
        sma_fast=20,
        sma_slow=50,
        ema_period=21,
        bb_period=20,
        bb_std=2.0,
        enable_zone_filter=True,
        enable_zone_stops=False,
        zone_block_distance=1.0,
    )
    defaults.update(kwargs)
    return HybridZoneSuperTrendStrategy(**defaults)


# ---------------------------------------------------------------------------
# _should_block_long
# ---------------------------------------------------------------------------

class TestShouldBlockLong(unittest.TestCase):
    """Resistance above price blocks longs when inside zone_block_distance."""

    def setUp(self):
        self.strategy = _make_strategy(zone_block_distance=1.0)
        # Resistance zone 2020-2030 (width=10)
        self.resistance = _make_zone(2020.0, 2030.0, ZoneType.RESISTANCE)
        self.strategy.cached_zones = {"H1": [self.resistance]}

    def test_blocked_when_price_just_below_resistance(self):
        """Distance = 5, zone_width = 10  →  5 < 1.0 * 10  → blocked."""
        blocked, reason = self.strategy._should_block_long(price=2015.0, atr=5.0)
        self.assertTrue(blocked)
        self.assertIn("resistance", reason)

    def test_not_blocked_when_price_far_from_resistance(self):
        """Distance = 15, zone_width = 10  →  15 >= 1.0 * 10  → allowed."""
        blocked, _ = self.strategy._should_block_long(price=2005.0, atr=5.0)
        self.assertFalse(blocked)

    def test_block_respects_zone_block_distance_multiplier(self):
        """With zone_block_distance=0.5, threshold is 5 pips; distance=7 → allowed."""
        self.strategy.zone_block_distance = 0.5
        blocked, _ = self.strategy._should_block_long(price=2013.0, atr=5.0)
        self.assertFalse(blocked)

    def test_no_block_when_no_resistance_above(self):
        """Support zone below price should not trigger a long block."""
        self.strategy.cached_zones = {
            "H1": [_make_zone(1980.0, 1990.0, ZoneType.SUPPORT)]
        }
        blocked, _ = self.strategy._should_block_long(price=2010.0, atr=5.0)
        self.assertFalse(blocked)

    def test_no_block_when_cached_zones_empty(self):
        self.strategy.cached_zones = {}
        blocked, _ = self.strategy._should_block_long(price=2018.0, atr=5.0)
        self.assertFalse(blocked)

    def test_no_block_when_zone_filter_disabled(self):
        self.strategy.enable_zone_filter = False
        blocked, _ = self.strategy._should_block_long(price=2018.0, atr=5.0)
        self.assertFalse(blocked)

    def test_flip_zone_acts_as_resistance(self):
        """FLIP zone above price should also block a long."""
        self.strategy.cached_zones = {
            "H1": [_make_zone(2021.0, 2029.0, ZoneType.FLIP)]
        }
        blocked, _ = self.strategy._should_block_long(price=2015.0, atr=5.0)
        self.assertTrue(blocked)


# ---------------------------------------------------------------------------
# _should_block_short
# ---------------------------------------------------------------------------

class TestShouldBlockShort(unittest.TestCase):
    """Support below price blocks shorts when inside zone_block_distance."""

    def setUp(self):
        self.strategy = _make_strategy(zone_block_distance=1.0)
        # Support zone 1990-2000 (width=10)
        self.support = _make_zone(1990.0, 2000.0, ZoneType.SUPPORT)
        self.strategy.cached_zones = {"H1": [self.support]}

    def test_blocked_when_price_just_above_support(self):
        """Distance = 5, zone_width = 10  →  5 < 1.0 * 10  → blocked."""
        blocked, reason = self.strategy._should_block_short(price=2005.0, atr=5.0)
        self.assertTrue(blocked)
        self.assertIn("support", reason)

    def test_not_blocked_when_price_far_from_support(self):
        """Distance = 15, zone_width = 10  →  15 >= 1.0 * 10  → allowed."""
        blocked, _ = self.strategy._should_block_short(price=2015.0, atr=5.0)
        self.assertFalse(blocked)

    def test_no_block_when_resistance_below_price(self):
        """Resistance below price should not trigger a short block."""
        self.strategy.cached_zones = {
            "H1": [_make_zone(1990.0, 2000.0, ZoneType.RESISTANCE)]
        }
        blocked, _ = self.strategy._should_block_short(price=2010.0, atr=5.0)
        self.assertFalse(blocked)

    def test_no_block_when_cached_zones_empty(self):
        self.strategy.cached_zones = {}
        blocked, _ = self.strategy._should_block_short(price=2005.0, atr=5.0)
        self.assertFalse(blocked)

    def test_no_block_when_zone_filter_disabled(self):
        self.strategy.enable_zone_filter = False
        blocked, _ = self.strategy._should_block_short(price=2005.0, atr=5.0)
        self.assertFalse(blocked)

    def test_flip_zone_acts_as_support(self):
        """FLIP zone below price should also block a short."""
        self.strategy.cached_zones = {
            "H1": [_make_zone(1991.0, 1999.0, ZoneType.FLIP)]
        }
        blocked, _ = self.strategy._should_block_short(price=2005.0, atr=5.0)
        self.assertTrue(blocked)


# ---------------------------------------------------------------------------
# _adjust_long_stop_to_zone
# ---------------------------------------------------------------------------

class TestAdjustLongStopToZone(unittest.TestCase):
    """Stop should be pulled to zone lower boundary when zone is near initial stop."""

    def setUp(self):
        self.strategy = _make_strategy(enable_zone_stops=True)

    def test_stop_adjusted_when_support_zone_near_initial_stop(self):
        """Support zone lower_bound=2000.5 is within 0.5*ATR(5)=2.5 of initial_stop=2000.
        adjusted = 2000.5 - 0.20*5 = 1999.5
        widening check: 1999.5 > 2000 - 0.3*5=1998.5  → passes
        """
        support = _make_zone(2000.5, 2010.5, ZoneType.SUPPORT, timeframe="M15")
        self.strategy.cached_zones = {"M15": [support]}

        entry = 2020.0
        initial_stop = 2000.0
        atr = 5.0

        adjusted, reason = self.strategy._adjust_long_stop_to_zone(entry, initial_stop, atr)
        expected = 2000.5 - 0.20 * 5.0  # 1999.5
        self.assertAlmostEqual(adjusted, expected, places=8)
        self.assertNotEqual(reason, "")

    def test_stop_not_adjusted_when_zone_too_far(self):
        """Zone is 3 ATR away — further than 0.5*ATR threshold, so no adjustment."""
        support = _make_zone(1980.0, 1990.0, ZoneType.SUPPORT, timeframe="M15")
        self.strategy.cached_zones = {"M15": [support]}

        adjusted, reason = self.strategy._adjust_long_stop_to_zone(2020.0, 2000.0, 5.0)
        self.assertEqual(adjusted, 2000.0)
        self.assertEqual(reason, "")

    def test_no_adjustment_when_zone_stops_disabled(self):
        self.strategy.enable_zone_stops = False
        support = _make_zone(1995.0, 2005.0, ZoneType.SUPPORT, timeframe="M15")
        self.strategy.cached_zones = {"M15": [support]}

        adjusted, reason = self.strategy._adjust_long_stop_to_zone(2020.0, 2000.0, 5.0)
        self.assertEqual(adjusted, 2000.0)
        self.assertEqual(reason, "")

    def test_no_adjustment_when_cached_zones_empty(self):
        self.strategy.cached_zones = {}
        adjusted, reason = self.strategy._adjust_long_stop_to_zone(2020.0, 2000.0, 5.0)
        self.assertEqual(adjusted, 2000.0)
        self.assertEqual(reason, "")

    def test_no_adjustment_when_would_widen_stop_too_much(self):
        """If adjusted stop is more than 0.3*ATR below initial, skip it."""
        # Zone lower_bound = 1985, initial_stop = 2000, atr = 5
        # adjusted = 1985 - 1.0 = 1984
        # condition: adjusted(1984) > initial_stop(2000) - 0.3*5(1.5) = 1998.5 → False → no adjust
        support = _make_zone(1985.0, 1995.0, ZoneType.SUPPORT, timeframe="M15")
        self.strategy.cached_zones = {"M15": [support]}

        adjusted, reason = self.strategy._adjust_long_stop_to_zone(2020.0, 2000.0, 5.0)
        self.assertEqual(adjusted, 2000.0)
        self.assertEqual(reason, "")


# ---------------------------------------------------------------------------
# _adjust_short_stop_to_zone
# ---------------------------------------------------------------------------

class TestAdjustShortStopToZone(unittest.TestCase):
    """Stop should be pulled to zone upper boundary when zone is near initial stop."""

    def setUp(self):
        self.strategy = _make_strategy(enable_zone_stops=True)

    def test_stop_adjusted_when_resistance_zone_near_initial_stop(self):
        """Resistance zone upper_bound=2019.5 is within 0.5*ATR(5)=2.5 of initial_stop=2020.
        adjusted = 2019.5 + 0.20*5 = 2020.5
        widening check: 2020.5 < 2020 + 0.3*5=2021.5  → passes
        """
        resistance = _make_zone(2009.5, 2019.5, ZoneType.RESISTANCE, timeframe="M15")
        self.strategy.cached_zones = {"M15": [resistance]}

        entry = 2000.0
        initial_stop = 2020.0
        atr = 5.0

        adjusted, reason = self.strategy._adjust_short_stop_to_zone(entry, initial_stop, atr)
        expected = 2019.5 + 0.20 * 5.0  # 2020.5
        self.assertAlmostEqual(adjusted, expected, places=8)
        self.assertNotEqual(reason, "")

    def test_stop_not_adjusted_when_zone_too_far(self):
        resistance = _make_zone(2040.0, 2050.0, ZoneType.RESISTANCE, timeframe="M15")
        self.strategy.cached_zones = {"M15": [resistance]}

        adjusted, reason = self.strategy._adjust_short_stop_to_zone(2000.0, 2020.0, 5.0)
        self.assertEqual(adjusted, 2020.0)
        self.assertEqual(reason, "")

    def test_no_adjustment_when_zone_stops_disabled(self):
        self.strategy.enable_zone_stops = False
        resistance = _make_zone(2015.0, 2025.0, ZoneType.RESISTANCE, timeframe="M15")
        self.strategy.cached_zones = {"M15": [resistance]}

        adjusted, reason = self.strategy._adjust_short_stop_to_zone(2000.0, 2020.0, 5.0)
        self.assertEqual(adjusted, 2020.0)
        self.assertEqual(reason, "")


if __name__ == "__main__":
    unittest.main()
