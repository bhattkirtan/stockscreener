"""
Unit tests for pip / SL / TP configuration changes.

Covers:
  1. _propagate_risk_to_sl_tp  — single source of truth propagation
  2. SimulatedTrade.calculate_pnl  — per-contract cost scaling
  3. BacktestingSkill pip_size lookup priority
  4. BacktestingSkill.execute() sl_tp_cfg fallback path
"""
import sys
import os
import pytest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from skills.backtesting.backtesting_skill import (
    BacktestingSkill,
    SimulatedTrade,
    OrderSide,
    OrderStatus,
)
from skills.base_skill import Context
from run_skills_backtest import _propagate_risk_to_sl_tp


# ---------------------------------------------------------------------------
# 1. _propagate_risk_to_sl_tp
# ---------------------------------------------------------------------------

class TestPropagateRiskToSlTp:

    def test_copies_all_three_keys(self):
        config = {
            'risk': {'pip_size': 0.01, 'stop_loss_pips': 2000, 'take_profit_pips': 6000},
        }
        _propagate_risk_to_sl_tp(config)
        sl_tp = config['analysis']['sl_tp']
        assert sl_tp['pip_size'] == 0.01
        assert sl_tp['stop_loss_pips'] == 2000
        assert sl_tp['take_profit_pips'] == 6000

    def test_creates_analysis_and_sl_tp_sections_if_missing(self):
        config = {'risk': {'pip_size': 0.0001, 'stop_loss_pips': 20, 'take_profit_pips': 60}}
        assert 'analysis' not in config
        _propagate_risk_to_sl_tp(config)
        assert 'analysis' in config
        assert 'sl_tp' in config['analysis']

    def test_overwrites_existing_analysis_sl_tp_values(self):
        """risk: is authoritative — always wins over stale analysis.sl_tp values."""
        config = {
            'risk': {'pip_size': 0.01, 'stop_loss_pips': 2000, 'take_profit_pips': 6000},
            'analysis': {'sl_tp': {'pip_size': 99.0, 'stop_loss_pips': 1}},
        }
        _propagate_risk_to_sl_tp(config)
        sl_tp = config['analysis']['sl_tp']
        assert sl_tp['pip_size'] == 0.01
        assert sl_tp['stop_loss_pips'] == 2000

    def test_preserves_method_in_existing_sl_tp(self):
        config = {
            'risk': {'pip_size': 0.1, 'stop_loss_pips': 500, 'take_profit_pips': 1500},
            'analysis': {'sl_tp': {'method': 'fixed'}},
        }
        _propagate_risk_to_sl_tp(config)
        assert config['analysis']['sl_tp']['method'] == 'fixed'

    def test_skips_keys_absent_from_risk(self):
        """If risk has no pip_size, analysis.sl_tp should not get one added."""
        config = {'risk': {'stop_loss_pips': 20}}
        _propagate_risk_to_sl_tp(config)
        assert 'pip_size' not in config['analysis']['sl_tp']
        assert config['analysis']['sl_tp']['stop_loss_pips'] == 20

    def test_empty_risk_section_is_safe(self):
        config = {'risk': {}}
        _propagate_risk_to_sl_tp(config)
        assert config['analysis']['sl_tp'] == {}

    def test_no_risk_section_is_safe(self):
        config = {}
        _propagate_risk_to_sl_tp(config)
        assert config['analysis']['sl_tp'] == {}

    def test_eurusd_instrument_values(self):
        """Simulate EURUSD instrument config after deep-merge."""
        config = {
            'risk': {'pip_size': 0.0001, 'stop_loss_pips': 20, 'take_profit_pips': 60},
            'analysis': {'sl_tp': {'method': 'fixed'}},
        }
        _propagate_risk_to_sl_tp(config)
        sl_tp = config['analysis']['sl_tp']
        assert sl_tp['pip_size'] == 0.0001
        assert sl_tp['stop_loss_pips'] == 20
        assert sl_tp['take_profit_pips'] == 60
        assert sl_tp['method'] == 'fixed'  # preserved

    def test_us100_instrument_values(self):
        config = {
            'risk': {'pip_size': 0.1, 'stop_loss_pips': 500, 'take_profit_pips': 1500},
            'analysis': {'sl_tp': {'method': 'fixed'}},
        }
        _propagate_risk_to_sl_tp(config)
        sl_tp = config['analysis']['sl_tp']
        assert sl_tp['pip_size'] == 0.1
        assert sl_tp['stop_loss_pips'] == 500
        assert sl_tp['take_profit_pips'] == 1500


# ---------------------------------------------------------------------------
# 2. SimulatedTrade.calculate_pnl — per-contract cost scaling
# ---------------------------------------------------------------------------

def _trade(side, entry, exit_price, size, spread=0.0, slippage=0.0):
    t = SimulatedTrade(
        entry_time=datetime(2024, 1, 1),
        entry_price=entry,
        side=side,
        size=size,
        exit_price=exit_price,
        spread_cost=spread,
        slippage_cost=slippage,
    )
    t.calculate_pnl()
    return t


class TestCalculatePnl:

    # --- correctness ---

    def test_buy_winner_no_costs(self):
        t = _trade(OrderSide.BUY, entry=2000.0, exit_price=2020.0, size=1)
        assert t.pnl == pytest.approx(20.0)

    def test_sell_winner_no_costs(self):
        t = _trade(OrderSide.SELL, entry=2000.0, exit_price=1980.0, size=1)
        assert t.pnl == pytest.approx(20.0)

    def test_buy_loser_no_costs(self):
        t = _trade(OrderSide.BUY, entry=2000.0, exit_price=1980.0, size=1)
        assert t.pnl == pytest.approx(-20.0)

    def test_sell_loser_no_costs(self):
        t = _trade(OrderSide.SELL, entry=2000.0, exit_price=2020.0, size=1)
        assert t.pnl == pytest.approx(-20.0)

    # --- cost scaling: costs are per-contract, so total_cost = cost × size ---

    def test_costs_scale_with_size(self):
        """With size=10, total costs must be 10× the per-contract cost."""
        size_1  = _trade(OrderSide.BUY, 2000, 2020, size=1,  spread=0.50, slippage=0.05)
        size_10 = _trade(OrderSide.BUY, 2000, 2020, size=10, spread=0.50, slippage=0.05)
        # gross_pnl scales 10× AND costs scale 10×, so net ratio holds
        assert size_10.pnl == pytest.approx(size_1.pnl * 10)

    def test_gold_tp_hit_10_contracts(self):
        """GOLD: entry=2000, TP at +$20, size=10, spread=$0.50/contract."""
        t = _trade(OrderSide.BUY, entry=2000.0, exit_price=2020.0,
                   size=10, spread=0.50, slippage=0.05)
        # gross = 20×10 = 200, costs = 0.55×10 = 5.50
        assert t.pnl == pytest.approx(194.50)

    def test_gold_sl_hit_10_contracts(self):
        """GOLD: entry=2000, SL at -$20, size=10."""
        t = _trade(OrderSide.BUY, entry=2000.0, exit_price=1980.0,
                   size=10, spread=0.50, slippage=0.05)
        # gross = -20×10 = -200, costs = 0.55×10 = 5.50
        assert t.pnl == pytest.approx(-205.50)

    def test_eurusd_tp_hit_10k_units(self):
        """EURUSD: 60-pip win with 10,000 units."""
        entry = 1.08000
        exit_price = 1.08060      # +60 pips
        size = 10_000
        spread = 0.00007          # $0.70 total
        slippage = 0.00001        # $0.10 total
        t = _trade(OrderSide.BUY, entry, exit_price, size, spread, slippage)
        # gross = 0.00060 × 10000 = $6.00, costs = 0.00008 × 10000 = $0.80
        assert t.pnl == pytest.approx(5.20)

    def test_eurusd_costs_stay_small_for_large_lot(self):
        """Per-unit costs × 10k units must be < $2 (sanity check on cost model)."""
        t = _trade(OrderSide.BUY, 1.08, 1.08, size=10_000,
                   spread=0.00007, slippage=0.00001)
        total_cost = abs(t.pnl)   # zero price move → pnl = -total_cost
        assert total_cost < 2.0, f"EURUSD costs too large: ${total_cost:.4f}"

    def test_pnl_pct_is_net_return_on_trade_value(self):
        """pnl_pct = net pnl / (entry × size) × 100, independent of absolute size."""
        t1 = _trade(OrderSide.BUY, 2000, 2020, size=1,  spread=0.50, slippage=0.05)
        t10 = _trade(OrderSide.BUY, 2000, 2020, size=10, spread=0.50, slippage=0.05)
        assert t1.pnl_pct == pytest.approx(t10.pnl_pct, rel=1e-6)

    def test_no_exit_price_leaves_pnl_zero(self):
        t = SimulatedTrade(
            entry_time=datetime(2024, 1, 1),
            entry_price=2000.0,
            side=OrderSide.BUY,
            size=1,
        )
        t.calculate_pnl()
        assert t.pnl == 0.0
        assert t.pnl_pct == 0.0


# ---------------------------------------------------------------------------
# 3. BacktestingSkill pip_size lookup priority
# ---------------------------------------------------------------------------

def _make_skill(config: dict) -> BacktestingSkill:
    return BacktestingSkill(config, event_bus=None)


class TestPipSizeLookup:

    def test_analysis_sl_tp_takes_priority(self):
        """analysis.sl_tp.pip_size beats risk.pip_size."""
        skill = _make_skill({
            'analysis': {'sl_tp': {'pip_size': 0.0001}},
            'risk':     {'pip_size': 1.0},
        })
        assert skill.pip_size == 0.0001

    def test_risk_used_when_no_analysis_sl_tp(self):
        skill = _make_skill({'risk': {'pip_size': 0.01}})
        assert skill.pip_size == 0.01

    def test_top_level_sl_tp_used_as_last_resort(self):
        skill = _make_skill({'sl_tp': {'pip_size': 0.1}})
        assert skill.pip_size == 0.1

    def test_default_when_nothing_configured(self):
        skill = _make_skill({})
        assert skill.pip_size == 1.0

    def test_gold_config(self):
        """GOLD: pip = $1 price move (commodity convention), SL=20 pips=$20."""
        skill = _make_skill({
            'analysis': {'sl_tp': {'pip_size': 1.0, 'stop_loss_pips': 20}},
            'risk':     {'pip_size': 1.0, 'stop_loss_pips': 20, 'take_profit_pips': 60},
        })
        assert skill.pip_size == 1.0
        assert skill.stop_loss_pips == 20

    def test_eurusd_config(self):
        """EURUSD: pip = 0.0001 (universal forex standard), SL=20 pips."""
        skill = _make_skill({
            'analysis': {'sl_tp': {'pip_size': 0.0001, 'stop_loss_pips': 20}},
            'risk':     {'pip_size': 0.0001, 'stop_loss_pips': 20, 'take_profit_pips': 60},
        })
        assert skill.pip_size == 0.0001
        assert skill.stop_loss_pips == 20

    def test_us100_config(self):
        """US100: pip = 1 index point (index convention), SL=50 pips=50 pts."""
        skill = _make_skill({
            'analysis': {'sl_tp': {'pip_size': 1.0, 'stop_loss_pips': 50}},
            'risk':     {'pip_size': 1.0, 'stop_loss_pips': 50, 'take_profit_pips': 150},
        })
        assert skill.pip_size == 1.0
        assert skill.stop_loss_pips == 50


# ---------------------------------------------------------------------------
# 4. BacktestingSkill.execute() — sl_tp fallback uses analysis.sl_tp
# ---------------------------------------------------------------------------

class TestExecuteSlTpFallback:
    """
    When context has no stop_loss/take_profit, BacktestingSkill computes them.
    The sl_tp_cfg must come from analysis.sl_tp (instrument-specific) first.
    """

    def _context(self, signal='BUY', entry_price=None):
        ctx = Context(timestamp=datetime(2024, 1, 1, 10, 0))
        ctx.signal = signal
        ctx.entry_price = entry_price
        ctx.stop_loss = None
        ctx.take_profit = None
        ctx.current_candle = {'close': entry_price or 2000.0, 'high': 0, 'low': 0}
        return ctx

    def test_execute_uses_sl_tp_from_context_when_present(self):
        """If AnalysisSkill already set SL/TP on context, use those directly."""
        skill = _make_skill({
            'analysis': {'sl_tp': {'method': 'fixed', 'pip_size': 0.01,
                                   'stop_loss_pips': 2000, 'take_profit_pips': 6000}},
            'risk':     {'pip_size': 0.01, 'stop_loss_pips': 2000, 'take_profit_pips': 6000},
        })
        ctx = self._context(entry_price=4500.0)
        ctx.stop_loss = 4480.0    # pre-set by AnalysisSkill
        ctx.take_profit = 4560.0

        skill.execute(ctx)
        assert len(skill.open_positions) == 1
        trade = skill.open_positions[0]
        assert trade.stop_loss == 4480.0
        assert trade.take_profit == 4560.0

    def test_execute_falls_back_to_analysis_sl_tp_for_gold(self):
        """GOLD: pip_size=1.0, SL=20 pips = $20 price distance."""
        skill = _make_skill({
            'analysis': {'sl_tp': {'method': 'fixed', 'pip_size': 1.0,
                                   'stop_loss_pips': 20, 'take_profit_pips': 60}},
            'risk':     {'pip_size': 1.0, 'stop_loss_pips': 20, 'take_profit_pips': 60},
        })
        entry = 4500.0
        ctx = self._context(entry_price=entry)

        skill.execute(ctx)
        assert len(skill.open_positions) == 1
        trade = skill.open_positions[0]
        assert trade.stop_loss  == pytest.approx(entry - 20.0)
        assert trade.take_profit == pytest.approx(entry + 60.0)

    def test_execute_falls_back_to_analysis_sl_tp_for_eurusd(self):
        """EURUSD: pip_size=0.0001, SL=20 pips = 0.0020 price distance."""
        skill = _make_skill({
            'analysis': {'sl_tp': {'method': 'fixed', 'pip_size': 0.0001,
                                   'stop_loss_pips': 20, 'take_profit_pips': 60}},
            'risk':     {'pip_size': 0.0001, 'stop_loss_pips': 20, 'take_profit_pips': 60},
        })
        entry = 1.08000
        ctx = self._context(entry_price=entry)

        skill.execute(ctx)
        trade = skill.open_positions[0]
        assert trade.stop_loss  == pytest.approx(entry - 0.0020, abs=1e-6)
        assert trade.take_profit == pytest.approx(entry + 0.0060, abs=1e-6)

    def test_execute_falls_back_to_analysis_sl_tp_for_us100(self):
        """US100: pip_size=1.0, SL=50 pips = 50 index points distance."""
        skill = _make_skill({
            'analysis': {'sl_tp': {'method': 'fixed', 'pip_size': 1.0,
                                   'stop_loss_pips': 50, 'take_profit_pips': 150}},
            'risk':     {'pip_size': 1.0, 'stop_loss_pips': 50, 'take_profit_pips': 150},
        })
        entry = 23000.0
        ctx = self._context(entry_price=entry)

        skill.execute(ctx)
        trade = skill.open_positions[0]
        assert trade.stop_loss  == pytest.approx(entry - 50.0)
        assert trade.take_profit == pytest.approx(entry + 150.0)
