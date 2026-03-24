"""
Test cases for Silver CFD P&L calculations.

Silver facts (from Capital.com screenshot, 2026-03-19):
  - Price:        ~$71.618 per troy oz
  - Sell / Buy:   71.734 / 71.814
  - Spread:       $0.080 per oz
  - Trade size:   30 troy oz
  - Spread/trade: $0.080 × 30 = $2.40
  - Step:         0.001
  - pip_value:    1.0  (same as Gold — price distance = dollar amount directly)

P&L formula (from Trade.calculate_pnl):
  pnl_points = exit_price - entry_price   (BUY)
  pnl_points = entry_price - exit_price   (SELL)
  pnl_points -= (spread_cost + slippage_cost)   # in price units
  pnl = pnl_points * size

Screenshot verification:
  SL distance 0.193 → loss = 0.193 × 30 = $5.79  (~€5.04 at EUR/USD 0.87) ✓
  TP distance 1.001 → profit = 1.001 × 30 = $30.03 (~€26.18 at EUR/USD 0.87) ✓
"""

import unittest
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.backtester import Trade, BacktestConfig, OrderSide, OrderStatus, TickLevelBacktester

# Silver constants matching Capital.com
SILVER_SIZE             = 30.0    # troy ounces per trade
SILVER_SPREAD_PER_OZ    = 0.08    # $0.08 per oz (spread_cost_usd = price-units, multiplied by size in P&L)
SILVER_SPREAD_PER_TRADE = 2.40    # $0.08 × 30 oz = $2.40 total per trade
SILVER_PRICE            = 71.618  # mid-price at time of screenshot


def silver_config(slippage_usd: float = 0.0) -> BacktestConfig:
    """
    BacktestConfig for Silver — no slippage by default so tests are deterministic.

    spread_cost_usd is stored as *price units per oz* by the backtester.
    The backtester multiplies it by size inside calculate_pnl:
      total_spread_usd = spread_cost_usd × size = 0.08 × 30 = $2.40  ✓
    """
    return BacktestConfig(
        initial_capital=10_000,
        spread_cost_usd=SILVER_SPREAD_PER_OZ,   # 0.08 price units/oz
        slippage_cost_usd=slippage_usd,
        pip_value=1.0,
        default_position_size=SILVER_SIZE,
        verbose=False,
    )


def make_trade(entry: float, exit_price: float, side: OrderSide,
               spread_cost: float = 0.0, slippage_cost: float = 0.0) -> Trade:
    """Build a closed Trade and compute its P&L."""
    trade = Trade(
        entry_time=datetime(2026, 3, 19, 10, 0),
        entry_price=entry,
        side=side,
        size=SILVER_SIZE,
        spread_cost=spread_cost,
        slippage_cost=slippage_cost,
        exit_time=datetime(2026, 3, 19, 10, 5),
        exit_price=exit_price,
        status=OrderStatus.CLOSED,
    )
    trade.calculate_pnl()
    return trade


# ---------------------------------------------------------------------------
# Group 1: Core P&L formula — no costs
# ---------------------------------------------------------------------------

class TestSilverPnLNoCosts(unittest.TestCase):
    """Verify raw price-distance * size formula with zero transaction costs."""

    def test_buy_profit(self):
        """BUY: price rises 1.001 → +$30.03"""
        trade = make_trade(entry=71.618, exit_price=72.619, side=OrderSide.BUY)
        self.assertAlmostEqual(trade.pnl, 1.001 * SILVER_SIZE, places=4)
        self.assertAlmostEqual(trade.pnl, 30.03, places=2)

    def test_buy_loss(self):
        """BUY: price falls 0.193 → -$5.79"""
        trade = make_trade(entry=71.618, exit_price=71.425, side=OrderSide.BUY)
        self.assertAlmostEqual(trade.pnl, -0.193 * SILVER_SIZE, places=4)
        self.assertAlmostEqual(trade.pnl, -5.79, places=2)

    def test_sell_profit(self):
        """SELL: price falls 0.193 → +$5.79"""
        trade = make_trade(entry=71.618, exit_price=71.425, side=OrderSide.SELL)
        self.assertAlmostEqual(trade.pnl, 0.193 * SILVER_SIZE, places=4)
        self.assertAlmostEqual(trade.pnl, 5.79, places=2)

    def test_sell_loss(self):
        """SELL: price rises 1.001 → -$30.03"""
        trade = make_trade(entry=71.618, exit_price=72.619, side=OrderSide.SELL)
        self.assertAlmostEqual(trade.pnl, -1.001 * SILVER_SIZE, places=4)
        self.assertAlmostEqual(trade.pnl, -30.03, places=2)

    def test_breakeven(self):
        """Flat exit = $0 (minus costs, but costs=0 here)"""
        trade = make_trade(entry=71.618, exit_price=71.618, side=OrderSide.BUY)
        self.assertAlmostEqual(trade.pnl, 0.0, places=6)

    def test_large_move_buy(self):
        """BUY: $2 move → +$60 on 30 oz"""
        trade = make_trade(entry=70.0, exit_price=72.0, side=OrderSide.BUY)
        self.assertAlmostEqual(trade.pnl, 2.0 * SILVER_SIZE, places=4)
        self.assertAlmostEqual(trade.pnl, 60.0, places=4)


# ---------------------------------------------------------------------------
# Group 2: Spread cost deducted from P&L
# ---------------------------------------------------------------------------

class TestSilverSpreadCost(unittest.TestCase):
    """Spread of $2.40 per trade reduces P&L by 2.40/size = 0.08 price units."""

    # Trade.calculate_pnl subtracts spread_cost (price units) from pnl_points,
    # then multiplies by size.  So we pass spread_cost = $0.08 per oz directly.

    def _spread_points(self) -> float:
        """Spread in price-unit terms per oz: $0.08/oz"""
        return SILVER_SPREAD_PER_OZ

    def test_buy_profit_after_spread(self):
        """TP hit at +1.001, spread 0.08/oz → net pnl = (1.001 - 0.08) × 30 = $27.63"""
        spread_pts = self._spread_points()  # 0.08
        trade = make_trade(
            entry=71.618, exit_price=72.619,
            side=OrderSide.BUY, spread_cost=spread_pts
        )
        expected = (1.001 - spread_pts) * SILVER_SIZE
        self.assertAlmostEqual(trade.pnl, expected, places=4)
        self.assertAlmostEqual(trade.pnl, 27.63, places=2)

    def test_buy_loss_after_spread(self):
        """SL hit at -0.193, spread 0.08/oz → net pnl = -(0.193 + 0.08) × 30 = -$8.19"""
        spread_pts = self._spread_points()  # 0.08
        trade = make_trade(
            entry=71.618, exit_price=71.425,
            side=OrderSide.BUY, spread_cost=spread_pts
        )
        expected = -(0.193 + spread_pts) * SILVER_SIZE
        self.assertAlmostEqual(trade.pnl, expected, places=4)
        self.assertAlmostEqual(trade.pnl, -8.19, places=2)

    def test_spread_always_negative(self):
        """Spread always reduces profit / increases loss — never positive impact."""
        spread_pts = self._spread_points()
        no_spread  = make_trade(71.618, 72.619, OrderSide.BUY, spread_cost=0.0)
        with_spread = make_trade(71.618, 72.619, OrderSide.BUY, spread_cost=spread_pts)
        self.assertLess(with_spread.pnl, no_spread.pnl)

    def test_spread_larger_than_move_results_in_loss(self):
        """If move is smaller than spread, trade should be a net loss."""
        spread_pts = self._spread_points()   # 0.08
        tiny_move  = spread_pts * 0.5        # 0.04 — smaller than spread
        trade = make_trade(
            entry=71.618, exit_price=71.618 + tiny_move,
            side=OrderSide.BUY, spread_cost=spread_pts
        )
        self.assertLess(trade.pnl, 0.0)


# ---------------------------------------------------------------------------
# Group 3: Screenshot exact values
# ---------------------------------------------------------------------------

class TestSilverScreenshotValues(unittest.TestCase):
    """
    Reproduce screenshot numbers exactly.
    Screenshot: price 71.618, SL dist 0.193 → Loss €5.04, TP dist 1.001 → Profit €26.18
    EUR/USD ~ 0.87 at time of screenshot.
    We test USD values; EUR conversion is Capital.com's display only.
    """
    EUR_USD = 0.87  # approximate at time of screenshot

    def test_sl_loss_usd(self):
        """SL at distance 0.193 → raw loss = $5.79 before spread"""
        trade = make_trade(
            entry=71.618, exit_price=71.618 - 0.193,
            side=OrderSide.BUY
        )
        self.assertAlmostEqual(trade.pnl, -5.79, places=2)

    def test_sl_loss_eur_approximate(self):
        """SL loss in EUR ≈ €5.04 (screenshot value)"""
        trade = make_trade(
            entry=71.618, exit_price=71.618 - 0.193,
            side=OrderSide.BUY
        )
        loss_eur = abs(trade.pnl) * self.EUR_USD
        # Allow ±0.30 tolerance for EUR/USD rate variation
        self.assertAlmostEqual(loss_eur, 5.04, delta=0.30)

    def test_tp_profit_usd(self):
        """TP at distance 1.001 → raw profit = $30.03 before spread"""
        trade = make_trade(
            entry=71.618, exit_price=71.618 + 1.001,
            side=OrderSide.BUY
        )
        self.assertAlmostEqual(trade.pnl, 30.03, places=2)

    def test_tp_profit_eur_approximate(self):
        """TP profit in EUR ≈ €26.18 (screenshot value)"""
        trade = make_trade(
            entry=71.618, exit_price=71.618 + 1.001,
            side=OrderSide.BUY
        )
        profit_eur = trade.pnl * self.EUR_USD
        self.assertAlmostEqual(profit_eur, 26.18, delta=0.30)


# ---------------------------------------------------------------------------
# Group 4: BacktestConfig for Silver
# ---------------------------------------------------------------------------

class TestSilverBacktestConfig(unittest.TestCase):
    """Verify BacktestConfig is set up correctly for Silver."""

    def test_config_fields(self):
        """Config has correct Silver values: spread is per-oz price units."""
        cfg = silver_config()
        self.assertEqual(cfg.spread_cost_usd, SILVER_SPREAD_PER_OZ)   # 0.08 per oz
        self.assertEqual(cfg.default_position_size, SILVER_SIZE)
        self.assertEqual(cfg.pip_value, 1.0)

    def test_backtester_uses_silver_size(self):
        """Backtester opens a position with Silver size."""
        config = silver_config()
        bt = TickLevelBacktester(config)
        trade = bt.open_position(
            timestamp=datetime(2026, 3, 19, 10, 0),
            price=71.618,
            side=OrderSide.BUY,
            stop_loss=71.425,
            take_profit=72.619,
            size=SILVER_SIZE,
        )
        self.assertIsNotNone(trade)
        self.assertEqual(trade.size, SILVER_SIZE)

    def test_spread_deducted_on_close(self):
        """When the backtester closes a trade, spread reduces P&L."""
        config = silver_config()
        bt = TickLevelBacktester(config)

        trade = bt.open_position(
            timestamp=datetime(2026, 3, 19, 10, 0),
            price=71.618,
            side=OrderSide.BUY,
            size=SILVER_SIZE,
        )

        raw_move = 1.001  # TP distance from screenshot
        exit_price = trade.entry_price + raw_move

        bt.close_position(
            trade,
            timestamp=datetime(2026, 3, 19, 10, 5),
            price=exit_price,
            reason='Take Profit',
        )

        # P&L must be less than raw move × size due to spread
        raw_pnl = raw_move * SILVER_SIZE
        self.assertLess(trade.pnl, raw_pnl)
        # But still positive (move > spread)
        self.assertGreater(trade.pnl, 0.0)


# ---------------------------------------------------------------------------
# Group 5: SL/TP symmetry
# ---------------------------------------------------------------------------

class TestSilverSlTpSymmetry(unittest.TestCase):
    """Winning and losing sides should be mirror-symmetric (no costs)."""

    def test_equal_distance_buy_sell_symmetry(self):
        """
        For same distance, BUY profit == SELL profit in absolute terms
        (no directional bias).
        """
        distance = 0.5
        buy_win  = make_trade(71.618, 71.618 + distance, OrderSide.BUY)
        sell_win = make_trade(71.618, 71.618 - distance, OrderSide.SELL)
        self.assertAlmostEqual(buy_win.pnl, sell_win.pnl, places=6)

    def test_2r_ratio_pnl(self):
        """TP at 2× SL distance should produce exactly 2× the loss at SL."""
        sl_dist = 0.193
        tp_dist = sl_dist * 2     # 2R

        loss  = make_trade(71.618, 71.618 - sl_dist, OrderSide.BUY)
        win   = make_trade(71.618, 71.618 + tp_dist, OrderSide.BUY)
        self.assertAlmostEqual(win.pnl, -2.0 * loss.pnl, places=4)

    def test_1001_sl_coverage_count(self):
        """
        Need >1 winning trade (TP=1.001) to recover from 1 losing (SL=0.193)
        at 2R — sanity check on R:R ratio.
        TP/SL > 1 so single win > single loss.
        """
        sl_loss = abs(make_trade(71.618, 71.618 - 0.193, OrderSide.BUY).pnl)
        tp_gain = make_trade(71.618, 71.618 + 1.001, OrderSide.BUY).pnl
        self.assertGreater(tp_gain, sl_loss)


if __name__ == '__main__':
    unittest.main(verbosity=2)
