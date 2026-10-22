"""
Unit Tests - Backtesting engine internals

Covers the four functions every quoted strategy number flows through:

    execute()                -> opens the SimulatedTrade (size + costs)
    check_exits()            -> the exit engine (SL / TP / TIME_EXIT)
    _close_position()        -> the P&L arithmetic and the equity curve
    get_results()            -> the PF / WR / expectancy aggregation

CLAUDE.md gotcha 31 is why this file exists: one character in this module's
cost model turned -$2,560 into -$134,629 and nothing complained. An arithmetic
error here does not crash, it produces a confident wrong number.

So every assertion below is an EXACT value, never an inequality (gotcha 50:
a factor-of-50 error passes every inequality test). Where a genuine float
division is involved, `pytest.approx(..., rel=1e-12)` is used — still exact to
within representation error, still fails on any real arithmetic change.

Scope notes:
  - Cost SCALING is pinned by `test_pip_config.py::TestCostScalingHappensOnce`
    (gotcha 40: the size multiplication must happen in exactly one place).
    This file asserts the resulting totals, it does not re-litigate that.
  - `time_based_exits.max_hours` at :398 is the ONLY time exit this module
    models (gotcha 51). `tests/unit/test_time_based_exits.py` covers the
    production_orchestrator classes of the same name, NOT this one.
"""
import pytest
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from skills.backtesting.backtesting_skill import (
    BacktestingSkill,
    SimulatedTrade,
    OrderSide,
    OrderStatus,
)
from skills.base_skill import Context


# --------------------------------------------------------------------------
# Helpers
#
# The canonical scenario, used wherever an exact figure is quoted below:
#
#   position_size      2.0
#   spread_cost_usd    0.50/unit  -> stored spread_cost   = 1.00
#   slippage_cost_usd  0.10/unit  -> stored slippage_cost = 0.20
#                                    total cost per trade = 1.20
#   leverage           20         -> margin = 100.0 * 2 / 20 = 10.00
#
#   BUY 100.00, SL 90.00, TP 130.00
#     TP hit: (130 - 100) * 2 - 1.20 =  +58.80
#     SL hit: ( 90 - 100) * 2 - 1.20 =  -21.20
# --------------------------------------------------------------------------

def make_skill(**sections):
    """Build a BacktestingSkill from the canonical config, overridable per-section."""
    cfg = {
        'backtest': {'leverage': 20},
        'backtesting': {
            'initial_capital': 10000.0,
            'position_size': 2.0,
            'spread_cost_usd': 0.50,
            'slippage_cost_usd': 0.10,
        },
    }
    for name, override in sections.items():
        if isinstance(override, dict) and isinstance(cfg.get(name), dict):
            cfg[name] = {**cfg[name], **override}
        else:
            cfg[name] = override
    return BacktestingSkill(cfg)


def ctx_at(ts, candle=None, **kw):
    c = Context(timestamp=ts)
    c.current_candle = candle
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def enter(skill, ts, signal='BUY', entry=100.0, sl=90.0, tp=130.0):
    """Open one position at an exact price with exact SL/TP (no sl_tp_engine)."""
    c = ctx_at(ts, {'close': entry, 'high': entry, 'low': entry},
               signal=signal, entry_price=entry, stop_loss=sl, take_profit=tp)
    assert skill.execute(c) is True
    return c


def bar(skill, ts, high, low, close):
    """Feed one candle to the exit engine."""
    return skill.check_exits(ctx_at(ts, {'high': high, 'low': low, 'close': close}))


T0 = datetime(2024, 1, 1, 10, 0)
T1 = datetime(2024, 1, 1, 10, 5)
T2 = datetime(2024, 1, 1, 11, 0)
T3 = datetime(2024, 1, 1, 11, 5)


# ==========================================================================
# 1. get_results — the PF / WR / P&L aggregation
# ==========================================================================

class TestGetResultsAggregation:
    """
    Every figure in CLAUDE.md gotchas 28-35 is this function's output.
    One win (+58.80) then one loss (-21.20), both on the canonical scenario.
    """

    @pytest.fixture
    def results(self):
        s = make_skill()
        enter(s, T0)
        bar(s, T1, high=135.0, low=99.0, close=134.0)      # TP -> +58.80
        enter(s, T2)
        bar(s, T3, high=101.0, low=85.0, close=86.0)       # SL -> -21.20
        assert len(s.closed_positions) == 2
        return s, s.get_results()

    def test_total_pnl_is_the_exact_sum_of_net_trade_pnl(self, results):
        _, r = results
        assert r['total_pnl'] == pytest.approx(37.60, rel=1e-12)

    def test_per_trade_pnl_is_exact(self, results):
        s, _ = results
        assert s.closed_positions[0].pnl == pytest.approx(58.80, rel=1e-12)
        assert s.closed_positions[1].pnl == pytest.approx(-21.20, rel=1e-12)

    def test_final_capital_is_initial_plus_total_pnl(self, results):
        _, r = results
        assert r['initial_capital'] == 10000.0
        assert r['final_capital'] == pytest.approx(10037.60, rel=1e-12)

    def test_total_return_pct(self, results):
        _, r = results
        # 37.60 / 10000 * 100
        assert r['total_return_pct'] == pytest.approx(0.376, rel=1e-12)

    def test_trade_counts(self, results):
        _, r = results
        assert r['total_trades'] == 2
        assert r['winning_trades'] == 1
        assert r['losing_trades'] == 1

    def test_win_rate_is_over_CLOSED_trades(self, results):
        _, r = results
        assert r['win_rate'] == 50.0

    def test_avg_win_and_avg_loss(self, results):
        _, r = results
        assert r['avg_win'] == pytest.approx(58.80, rel=1e-12)
        # avg_loss keeps its sign — it is negative, and expectancy ADDS it
        assert r['avg_loss'] == pytest.approx(-21.20, rel=1e-12)

    def test_profit_factor_is_gross_wins_over_gross_losses(self, results):
        _, r = results
        assert r['profit_factor'] == pytest.approx(58.80 / 21.20, rel=1e-12)
        assert r['profit_factor'] == pytest.approx(2.7735849056603774, rel=1e-12)

    def test_expectancy_per_trade(self, results):
        _, r = results
        # 0.5 * 58.80 + 0.5 * (-21.20)
        assert r['expectancy_per_trade'] == pytest.approx(18.80, rel=1e-12)

    def test_expectancy_equals_total_pnl_over_closed_count(self, results):
        _, r = results
        assert r['expectancy_per_trade'] == pytest.approx(37.60 / 2, rel=1e-12)

    def test_max_drawdown_is_absolute_dollars(self, results):
        _, r = results
        # peak equity 10058.80 after the win, then the loss takes it to 10037.60
        assert r['max_drawdown'] == pytest.approx(21.20, rel=1e-12)

    def test_max_drawdown_pct_divides_by_PEAK_equity_not_initial_capital(self, results):
        _, r = results
        assert r['max_drawdown_pct'] == pytest.approx(21.20 / 10058.80 * 100, rel=1e-12)

    def test_margin_and_return_on_margin(self, results):
        _, r = results
        assert r['leverage'] == 20.0
        # entry 100.00 * size 2 / leverage 20
        assert r['avg_margin_per_trade'] == pytest.approx(10.0, rel=1e-12)
        assert r['return_on_margin_pct'] == pytest.approx(376.0, rel=1e-12)

    def test_trades_list_is_serialised_dicts(self, results):
        _, r = results
        assert len(r['trades']) == 2
        first = r['trades'][0]
        assert first['side'] == 'BUY'
        assert first['status'] == 'CLOSED'
        assert first['exit_reason'] == 'TP_HIT'
        assert first['exit_price'] == 130.0
        assert first['size'] == 2.0
        assert first['spread_cost'] == pytest.approx(1.00, rel=1e-12)
        assert first['slippage_cost'] == pytest.approx(0.20, rel=1e-12)
        assert first['margin'] == pytest.approx(10.0, rel=1e-12)

    def test_sharpe_is_zero_when_every_close_lands_on_one_calendar_day(self, results):
        _, r = results
        # the daily resample yields a single row, so there is no return series
        assert r['sharpe_ratio'] == 0


class TestGetResultsOnAnEmptyBacktest:
    """A run that opened nothing must not produce NaN or a ZeroDivisionError."""

    @pytest.fixture
    def results(self):
        return make_skill().get_results()

    def test_all_counters_zero(self, results):
        assert results['total_trades'] == 0
        assert results['winning_trades'] == 0
        assert results['losing_trades'] == 0
        assert results['total_pnl'] == 0.0

    def test_win_rate_and_averages_are_zero_not_nan(self, results):
        assert results['win_rate'] == 0
        assert results['avg_win'] == 0.0
        assert results['avg_loss'] == 0.0
        assert results['expectancy_per_trade'] == 0.0

    def test_capital_untouched(self, results):
        assert results['final_capital'] == 10000.0
        assert results['total_return_pct'] == 0.0

    def test_avg_margin_falls_back_to_initial_capital(self, results):
        # no closed trades -> no margins -> denominator is the account, not 0
        assert results['avg_margin_per_trade'] == 10000.0
        assert results['return_on_margin_pct'] == 0.0

    def test_drawdown_and_sharpe_zero(self, results):
        assert results['max_drawdown'] == 0.0
        assert results['max_drawdown_pct'] == 0.0
        assert results['sharpe_ratio'] == 0

    def test_profit_factor_of_an_empty_run_is_zero(self, results):
        # 0 wins / max(0 losses, 0.01) -> 0.0, not NaN and not 1.0
        assert results['profit_factor'] == 0.0

    def test_trades_list_empty(self, results):
        assert results['trades'] == []


class TestProfitFactorWithNoLosses:
    """
    FIXED 2026-10-22. `profit_factor` was `total_wins / max(total_losses, 0.01)`
    — a divide-by-zero guard being used as a VALUE. With zero losing trades the
    denominator was one cent, so the reported profit factor was literally 100x
    the gross win total: a single $60 win came out as PF 6000.0.

    That is the "confident wrong number" class this file exists to catch, and
    `optimize_params.py:71` RANKS the grid on `pf * 0.6 + sharpe * 0.4`, so such
    a run scored ~3,500 and would dominate everything real. (`MIN_TRADES = 30`
    at `optimize_params.py:148` dropped it first, and `sweep_eval.py` refuses to
    score a run with no losses at all, so the practical reach was small.)

    Now it reports the 999.0 sentinel already used for this case by
    `cloud-function/api/live_report.py:54` — JSON-safe (results are
    `json.dumps`-ed at `backtest_api.py:456`, so `float('inf')` was not an
    option) and obviously a sentinel rather than a plausible-looking number.

    The change is arithmetically identical for any run with at least one cent of
    losses, which is every real run on all six deployed instruments.
    """

    def test_a_loss_free_run_reports_the_999_sentinel(self):
        s = make_skill()
        enter(s, T0)
        bar(s, T1, high=135.0, low=99.0, close=134.0)
        r = s.get_results()
        assert r['losing_trades'] == 0
        assert r['total_pnl'] == pytest.approx(58.80, rel=1e-12)
        assert r['profit_factor'] == 999.0            # was 5880.0

    def test_the_sentinel_does_not_scale_with_position_size(self):
        s = make_skill(backtesting={'position_size': 20.0})
        enter(s, T0)
        bar(s, T1, high=135.0, low=99.0, close=134.0)
        r = s.get_results()
        assert r['total_pnl'] == pytest.approx(588.0, rel=1e-12)
        assert r['profit_factor'] == 999.0            # was 58800.0

    def test_the_sentinel_is_json_serialisable(self):
        import json
        s = make_skill()
        enter(s, T0)
        bar(s, T1, high=135.0, low=99.0, close=134.0)
        pf = s.get_results()['profit_factor']
        # `float('inf')` would emit bare `Infinity`, which is not valid JSON
        assert json.loads(json.dumps({'pf': pf}))['pf'] == 999.0

    def test_no_trades_at_all_is_zero_not_the_sentinel(self):
        assert make_skill().get_results()['profit_factor'] == 0.0

    def test_one_real_loss_gives_the_true_ratio(self):
        s = make_skill()
        enter(s, T0)
        bar(s, T1, high=135.0, low=99.0, close=134.0)
        enter(s, T2)
        bar(s, T3, high=101.0, low=85.0, close=86.0)
        assert s.get_results()['profit_factor'] == pytest.approx(2.7735849056603774, rel=1e-12)

    def test_a_sub_cent_loss_is_no_longer_floored_to_one_cent(self):
        """The old `max(total_losses, 0.01)` also distorted any loss under a
        cent. Unreachable with real costs, but it was the same defect."""
        s = make_skill(backtesting={'position_size': 1.0,
                                    'spread_cost_usd': 0.0, 'slippage_cost_usd': 0.0})
        enter(s, T0, entry=100.0, sl=99.999, tp=130.0)       # -0.001 on size 1
        bar(s, T1, high=101.0, low=99.0, close=99.5)
        enter(s, T2, entry=100.0, sl=90.0, tp=101.0)         # +1.00
        bar(s, T3, high=101.0, low=99.5, close=100.5)
        r = s.get_results()
        assert r['total_pnl'] == pytest.approx(0.999, rel=1e-9)
        # true ratio 1.0 / 0.001 = 1000.0;  old code gave 1.0 / 0.01 = 100.0
        assert r['profit_factor'] == pytest.approx(1000.0, rel=1e-9)


class TestBreakEvenTradeIsScoredALoss:
    """
    FINDING (reported 2026-10-22): a trade closing at exactly pnl == 0.0 is
    counted in `losing_trades` but contributes nothing to `total_losses`.

    `_close_position` splits on `if trade.pnl > 0: winning else: losing`, while
    `get_results` sums losses with `if t.pnl < 0`. So the break-even trade
    lands in the loss COUNT but not the loss SUM:

        - win_rate is deflated (the trade is a non-win)
        - avg_loss is understated in magnitude (negative sum / inflated count)
        - profit_factor is unaffected (it uses the sums)

    i.e. the summary statistics disagree with each other about what the trade
    was. Same family as gotchas 22 and 49(a): a 0.0 that means "nothing
    happened" being scored as a directional outcome.

    Reachable with zero-cost configs, a TIME_EXIT whose close equals entry, or
    a reverse-signal exit at the entry price. Unreachable on the six deployed
    instruments, all of which charge non-zero spread + slippage.
    """

    @pytest.fixture
    def results(self):
        s = make_skill(backtesting={'spread_cost_usd': 0.0, 'slippage_cost_usd': 0.0})
        enter(s, T0)                                      # BUY @ 100.00, no costs
        s.close_reverse_positions('SELL', 100.0, T1)      # exit at entry -> pnl 0.0
        assert s.closed_positions[0].pnl == 0.0
        return s, s.get_results()

    def test_break_even_trade_counts_as_a_losing_trade(self, results):
        _, r = results
        assert r['winning_trades'] == 0
        assert r['losing_trades'] == 1

    def test_win_rate_is_zero_not_undefined(self, results):
        _, r = results
        assert r['win_rate'] == 0.0

    def test_avg_loss_is_zero_because_the_SUM_excludes_it(self, results):
        _, r = results
        # sum(pnl for pnl < 0) == 0.0, divided by losing_trades == 1
        assert r['avg_loss'] == 0.0

    def test_profit_factor_uses_the_sums_so_it_sees_no_loss_at_all(self, results):
        _, r = results
        assert r['profit_factor'] == 0.0

    def test_capital_is_genuinely_unchanged(self, results):
        s, r = results
        assert s.capital == 10000.0
        assert r['total_pnl'] == 0.0

    def test_one_cent_of_cost_flips_it_into_a_real_loss(self):
        s = make_skill(backtesting={'spread_cost_usd': 0.005, 'slippage_cost_usd': 0.0})
        enter(s, T0)
        s.close_reverse_positions('SELL', 100.0, T1)
        # 0.005 * size 2 = 0.01
        assert s.closed_positions[0].pnl == pytest.approx(-0.01, rel=1e-12)
        r = s.get_results()
        assert r['losing_trades'] == 1
        assert r['avg_loss'] == pytest.approx(-0.01, rel=1e-12)


class TestSharpeRatioResampling:
    """Sharpe is resampled to daily returns, not computed per-trade (:499-512)."""

    def _run(self, day_pnls):
        """Close one trade per calendar day, each for an exact P&L."""
        s = make_skill(backtesting={'spread_cost_usd': 0.0, 'slippage_cost_usd': 0.0})
        for i, pnl in enumerate(day_pnls):
            ts = datetime(2024, 1, 1 + i, 10, 0)
            # size 2 -> a move of pnl/2 points yields exactly pnl
            tp = 100.0 + pnl / 2
            enter(s, ts, entry=100.0, sl=1.0, tp=tp)
            bar(s, datetime(2024, 1, 1 + i, 10, 5), high=tp + 1, low=99.0, close=tp)
        return s

    def test_single_close_yields_zero_sharpe(self):
        s = self._run([100.0])
        assert len(s.equity_curve) == 1
        assert s.get_results()['sharpe_ratio'] == 0

    def test_a_constant_daily_gain_has_a_defined_sharpe(self):
        s = self._run([100.0, 100.0, 100.0, 100.0])
        r = s.get_results()
        assert r['total_pnl'] == pytest.approx(400.0, rel=1e-12)
        # equity 10100, 10200, 10300, 10400 -> a fixed dollar gain on a growing
        # base, so the RETURNS shrink slightly each day: std > 0 but tiny, and
        # the annualised ratio is correspondingly enormous. A near-constant
        # return series is exactly how this metric gets inflated.
        assert r['sharpe_ratio'] == pytest.approx(1619.1219876106854, rel=1e-9)

    def test_zero_variance_returns_leave_sharpe_at_zero(self):
        # two closes on the SAME day -> one daily bar -> no return series
        s = make_skill(backtesting={'spread_cost_usd': 0.0, 'slippage_cost_usd': 0.0})
        enter(s, T0, entry=100.0, sl=1.0, tp=150.0)
        bar(s, T1, high=151.0, low=99.0, close=150.0)
        enter(s, T2, entry=100.0, sl=1.0, tp=150.0)
        bar(s, T3, high=151.0, low=99.0, close=150.0)
        assert len(s.equity_curve) == 2
        assert s.get_results()['sharpe_ratio'] == 0


# ==========================================================================
# 2. check_exits — the exit engine
# ==========================================================================

class TestCheckExitsStopLoss:

    def test_buy_sl_hit_when_low_touches_the_stop(self):
        s = make_skill()
        enter(s, T0)
        closed = bar(s, T1, high=101.0, low=90.0, close=95.0)   # low == SL
        assert len(closed) == 1
        assert closed[0].exit_reason == 'SL_HIT'

    def test_buy_sl_books_the_STOP_price_not_the_candle_low(self):
        s = make_skill()
        enter(s, T0)
        bar(s, T1, high=101.0, low=70.0, close=75.0)            # gapped way through
        t = s.closed_positions[0]
        assert t.exit_price == 90.0
        # i.e. the simulation assumes a perfect fill at the stop, no gap slippage
        assert t.pnl == pytest.approx(-21.20, rel=1e-12)

    def test_buy_sl_not_hit_one_tick_above_the_stop(self):
        s = make_skill()
        enter(s, T0)
        assert bar(s, T1, high=101.0, low=90.01, close=95.0) == []
        assert len(s.open_positions) == 1

    def test_sell_sl_hit_when_high_touches_the_stop(self):
        s = make_skill()
        enter(s, T0, signal='SELL', entry=100.0, sl=110.0, tp=70.0)
        closed = bar(s, T1, high=110.0, low=99.0, close=105.0)
        assert len(closed) == 1
        assert closed[0].exit_reason == 'SL_HIT'
        assert closed[0].exit_price == 110.0
        # (100 - 110) * 2 - 1.20
        assert closed[0].pnl == pytest.approx(-21.20, rel=1e-12)

    def test_sell_sl_not_hit_one_tick_below_the_stop(self):
        s = make_skill()
        enter(s, T0, signal='SELL', entry=100.0, sl=110.0, tp=70.0)
        assert bar(s, T1, high=109.99, low=99.0, close=105.0) == []


class TestCheckExitsTakeProfit:

    def test_buy_tp_hit_when_high_touches_the_target(self):
        s = make_skill()
        enter(s, T0)
        closed = bar(s, T1, high=130.0, low=99.0, close=129.0)
        assert len(closed) == 1
        assert closed[0].exit_reason == 'TP_HIT'
        assert closed[0].exit_price == 130.0
        assert closed[0].pnl == pytest.approx(58.80, rel=1e-12)

    def test_buy_tp_books_the_TARGET_not_the_candle_high(self):
        s = make_skill()
        enter(s, T0)
        bar(s, T1, high=200.0, low=99.0, close=195.0)
        assert s.closed_positions[0].exit_price == 130.0
        assert s.closed_positions[0].pnl == pytest.approx(58.80, rel=1e-12)

    def test_buy_tp_not_hit_one_tick_below_the_target(self):
        s = make_skill()
        enter(s, T0)
        assert bar(s, T1, high=129.99, low=99.0, close=129.0) == []

    def test_sell_tp_hit_when_low_touches_the_target(self):
        s = make_skill()
        enter(s, T0, signal='SELL', entry=100.0, sl=110.0, tp=70.0)
        closed = bar(s, T1, high=101.0, low=70.0, close=71.0)
        assert len(closed) == 1
        assert closed[0].exit_reason == 'TP_HIT'
        assert closed[0].exit_price == 70.0
        # (100 - 70) * 2 - 1.20
        assert closed[0].pnl == pytest.approx(58.80, rel=1e-12)

    def test_sell_tp_not_hit_one_tick_above_the_target(self):
        s = make_skill()
        enter(s, T0, signal='SELL', entry=100.0, sl=110.0, tp=70.0)
        assert bar(s, T1, high=101.0, low=70.01, close=71.0) == []


class TestCheckExitsSameBarPrecedence:
    """
    The code DOES make a documented choice: SL is the `if`, TP the `elif`, under
    the comment "Check Take Profit (only if SL not hit)" (:390). So when a
    single bar's range spans both levels, the STOP is booked.

    This is the conservative (pessimistic) assumption and it is the right
    default for a bar-level simulator, which cannot know the intra-bar path.
    It is pinned here because the pre-existing
    `test_backtesting_skill.py::test_sl_hit_before_tp` never calls the skill —
    it re-implements the two comparisons inline and asserts `sl_hit or tp_hit`,
    which is true whenever either level is touched. It could not fail.

    Consequence worth knowing: precedence ignores WHERE in the bar each level
    sits, so a bar that opened above TP and only later dipped to SL is still
    booked as a loss. That understates backtest P&L rather than overstating it.
    """

    def test_a_bar_spanning_both_levels_books_the_STOP(self):
        s = make_skill()
        enter(s, T0)
        closed = bar(s, T1, high=135.0, low=85.0, close=120.0)
        assert len(closed) == 1
        assert closed[0].exit_reason == 'SL_HIT'
        assert closed[0].exit_price == 90.0
        assert closed[0].pnl == pytest.approx(-21.20, rel=1e-12)

    def test_precedence_holds_even_when_the_bar_CLOSED_beyond_TP(self):
        s = make_skill()
        enter(s, T0)
        closed = bar(s, T1, high=140.0, low=85.0, close=139.0)
        assert closed[0].exit_reason == 'SL_HIT'

    def test_same_precedence_for_a_SELL(self):
        s = make_skill()
        enter(s, T0, signal='SELL', entry=100.0, sl=110.0, tp=70.0)
        closed = bar(s, T1, high=115.0, low=65.0, close=80.0)
        assert closed[0].exit_reason == 'SL_HIT'
        assert closed[0].exit_price == 110.0


class TestCheckExitsGuards:

    def test_no_candle_returns_empty_and_leaves_the_position_open(self):
        s = make_skill()
        enter(s, T0)
        assert s.check_exits(ctx_at(T1, None)) == []
        assert len(s.open_positions) == 1

    def test_zero_high_is_rejected_as_a_malformed_candle(self):
        s = make_skill()
        enter(s, T0)
        assert bar(s, T1, high=0, low=85.0, close=86.0) == []
        assert len(s.open_positions) == 1

    def test_zero_low_is_rejected_as_a_malformed_candle(self):
        s = make_skill()
        enter(s, T0)
        assert bar(s, T1, high=135.0, low=0, close=134.0) == []
        assert len(s.open_positions) == 1

    def test_candle_missing_high_and_low_is_rejected(self):
        s = make_skill()
        enter(s, T0)
        assert s.check_exits(ctx_at(T1, {'close': 95.0})) == []
        assert len(s.open_positions) == 1

    def test_no_open_positions_is_a_no_op(self):
        s = make_skill()
        assert bar(s, T1, high=135.0, low=85.0, close=100.0) == []

    def test_an_untriggered_bar_leaves_the_trade_fully_open(self):
        s = make_skill()
        enter(s, T0)
        assert bar(s, T1, high=105.0, low=95.0, close=100.0) == []
        t = s.open_positions[0]
        assert t.status == OrderStatus.OPEN
        assert t.exit_price is None
        assert t.exit_reason is None
        assert t.pnl == 0.0


class TestCheckExitsTimeExit:
    """
    `time_based_exits.max_hours` (:398) is the only time exit this module
    models — gotcha 51. It is inert by default (`max_hours: 0` in the base
    config) and has no live counterpart, so enabling one side alone silently
    makes live and backtest disagree on hold time.
    """

    def test_max_hours_zero_means_disabled(self):
        s = make_skill()
        assert s.max_hold_minutes == 0
        enter(s, T0)
        # a week later, well inside SL/TP, still open
        assert bar(s, datetime(2024, 1, 8, 10, 0), high=105.0, low=95.0, close=100.0) == []
        assert len(s.open_positions) == 1

    def test_max_hours_is_converted_to_minutes(self):
        assert make_skill(time_based_exits={'max_hours': 4}).max_hold_minutes == 240

    def test_exit_fires_at_exactly_max_hold(self):
        s = make_skill(time_based_exits={'max_hours': 1})
        enter(s, T0)
        closed = bar(s, datetime(2024, 1, 1, 11, 0), high=105.0, low=95.0, close=104.0)
        assert len(closed) == 1
        assert closed[0].exit_reason == 'TIME_EXIT'

    def test_exit_books_the_candle_CLOSE_not_a_level(self):
        s = make_skill(time_based_exits={'max_hours': 1})
        enter(s, T0)
        bar(s, datetime(2024, 1, 1, 11, 0), high=105.0, low=95.0, close=104.0)
        t = s.closed_positions[0]
        assert t.exit_price == 104.0
        # (104 - 100) * 2 - 1.20
        assert t.pnl == pytest.approx(6.80, rel=1e-12)

    def test_one_minute_short_of_max_hold_does_not_exit(self):
        s = make_skill(time_based_exits={'max_hours': 1})
        enter(s, T0)
        assert bar(s, datetime(2024, 1, 1, 10, 59), high=105.0, low=95.0, close=104.0) == []
        assert len(s.open_positions) == 1

    def test_a_losing_time_exit_is_booked_as_a_loss(self):
        s = make_skill(time_based_exits={'max_hours': 1})
        enter(s, T0)
        bar(s, datetime(2024, 1, 1, 11, 0), high=101.0, low=95.0, close=96.0)
        t = s.closed_positions[0]
        assert t.exit_reason == 'TIME_EXIT'
        # (96 - 100) * 2 - 1.20
        assert t.pnl == pytest.approx(-9.20, rel=1e-12)
        assert s.get_results()['losing_trades'] == 1

    def test_SL_takes_precedence_over_an_overdue_time_exit(self):
        s = make_skill(time_based_exits={'max_hours': 1})
        enter(s, T0)
        closed = bar(s, datetime(2024, 1, 1, 12, 0), high=101.0, low=85.0, close=86.0)
        assert closed[0].exit_reason == 'SL_HIT'
        assert closed[0].exit_price == 90.0

    def test_TP_takes_precedence_over_an_overdue_time_exit(self):
        s = make_skill(time_based_exits={'max_hours': 1})
        enter(s, T0)
        closed = bar(s, datetime(2024, 1, 1, 12, 0), high=135.0, low=99.0, close=134.0)
        assert closed[0].exit_reason == 'TP_HIT'
        assert closed[0].exit_price == 130.0

    def test_time_exit_applies_to_a_SELL_too(self):
        s = make_skill(time_based_exits={'max_hours': 1})
        enter(s, T0, signal='SELL', entry=100.0, sl=110.0, tp=70.0)
        bar(s, datetime(2024, 1, 1, 11, 0), high=105.0, low=95.0, close=96.0)
        t = s.closed_positions[0]
        assert t.exit_reason == 'TIME_EXIT'
        # (100 - 96) * 2 - 1.20
        assert t.pnl == pytest.approx(6.80, rel=1e-12)

    def test_unparseable_timestamp_is_swallowed_and_the_trade_survives(self):
        s = make_skill(time_based_exits={'max_hours': 1})
        enter(s, T0)
        # the bare `except Exception: pass` at :407 — a bad clock must not
        # abort the whole backtest run
        assert s.check_exits(ctx_at('not-a-timestamp',
                                    {'high': 105.0, 'low': 95.0, 'close': 100.0})) == []
        assert len(s.open_positions) == 1


class TestTimeExitDroppedWhenCloseIsZero:
    """
    FINDING (reported 2026-10-22): `if exit_price:` at :411 is a truthiness test
    on a float, so an exit computed at exactly 0.0 is silently discarded.

    Only the TIME_EXIT branch can produce it: it takes `close_price` from
    `candle.get('close', 0)`, and a candle carrying valid high/low but no
    `close` key therefore yields `exit_reason='TIME_EXIT'` with
    `exit_price=0.0` — which the guard then drops. The trade stays open and
    re-evaluates on every later bar, silently exceeding max_hold forever.

    It fails CLOSED (no exit) rather than booking a $0 exit price, which would
    be far worse — a 0.0 exit books a ~100% loss. So the guard is accidentally
    protective and the hazard is the silent retry, not a wrong number. Pinned
    rather than changed: candles from `trading.db` always carry `close`, so
    this is unreachable on every real run.
    """

    def test_time_exit_on_a_closeless_candle_leaves_the_trade_open(self):
        s = make_skill(time_based_exits={'max_hours': 1})
        enter(s, T0)
        closed = s.check_exits(ctx_at(datetime(2024, 1, 1, 12, 0),
                                      {'high': 105.0, 'low': 95.0}))
        assert closed == []
        assert len(s.open_positions) == 1

    def test_the_dropped_exit_leaves_no_trace_on_the_trade(self):
        s = make_skill(time_based_exits={'max_hours': 1})
        enter(s, T0)
        s.check_exits(ctx_at(datetime(2024, 1, 1, 12, 0), {'high': 105.0, 'low': 95.0}))
        t = s.open_positions[0]
        assert t.status == OrderStatus.OPEN
        assert t.exit_reason is None
        assert t.exit_price is None

    def test_nothing_is_booked_so_the_results_stay_empty(self):
        s = make_skill(time_based_exits={'max_hours': 1})
        enter(s, T0)
        s.check_exits(ctx_at(datetime(2024, 1, 1, 12, 0), {'high': 105.0, 'low': 95.0}))
        r = s.get_results()
        assert r['total_trades'] == 1       # it was opened
        assert r['winning_trades'] == 0     # but never closed
        assert r['losing_trades'] == 0
        assert r['total_pnl'] == 0.0

    def test_a_present_close_of_zero_is_dropped_the_same_way(self):
        s = make_skill(time_based_exits={'max_hours': 1})
        enter(s, T0)
        assert s.check_exits(ctx_at(datetime(2024, 1, 1, 12, 0),
                                    {'high': 105.0, 'low': 95.0, 'close': 0.0})) == []
        assert len(s.open_positions) == 1


class TestCheckExitsMultiplePositions:
    """
    `execute()` refuses a second concurrent position, but `check_exits` iterates
    a list and `close_reverse_positions` can leave more than one behind, so the
    loop must handle several and mutate the list safely while iterating (:378).
    """

    def test_each_position_exits_on_its_own_level(self):
        s = make_skill()
        s.open_positions.append(SimulatedTrade(
            entry_time=T0, entry_price=100.0, side=OrderSide.BUY, size=2.0,
            stop_loss=90.0, take_profit=130.0))
        s.open_positions.append(SimulatedTrade(
            entry_time=T0, entry_price=100.0, side=OrderSide.BUY, size=2.0,
            stop_loss=80.0, take_profit=200.0))
        closed = bar(s, T1, high=101.0, low=85.0, close=86.0)
        assert len(closed) == 1
        assert closed[0].stop_loss == 90.0
        assert len(s.open_positions) == 1
        assert s.open_positions[0].stop_loss == 80.0

    def test_both_can_close_on_one_bar(self):
        s = make_skill()
        for sl in (90.0, 88.0):
            s.open_positions.append(SimulatedTrade(
                entry_time=T0, entry_price=100.0, side=OrderSide.BUY, size=2.0,
                stop_loss=sl, take_profit=130.0))
        closed = bar(s, T1, high=101.0, low=85.0, close=86.0)
        assert len(closed) == 2
        assert s.open_positions == []
        assert [t.exit_price for t in closed] == [90.0, 88.0]

    def test_a_long_and_a_short_exit_in_opposite_directions(self):
        s = make_skill()
        s.open_positions.append(SimulatedTrade(
            entry_time=T0, entry_price=100.0, side=OrderSide.BUY, size=2.0,
            stop_loss=90.0, take_profit=130.0))
        s.open_positions.append(SimulatedTrade(
            entry_time=T0, entry_price=100.0, side=OrderSide.SELL, size=2.0,
            stop_loss=110.0, take_profit=70.0))
        closed = bar(s, T1, high=101.0, low=85.0, close=86.0)
        # BUY stops out at 90; the SELL's stop (110) and target (70) are both untouched
        assert len(closed) == 1
        assert closed[0].side == OrderSide.BUY
        assert len(s.open_positions) == 1
        assert s.open_positions[0].side == OrderSide.SELL


# ==========================================================================
# 3. _close_position — P&L arithmetic, capital, equity curve, drawdown
# ==========================================================================

class TestClosePositionArithmetic:

    def test_costs_are_subtracted_from_gross_exactly_once(self):
        s = make_skill()
        enter(s, T0)
        bar(s, T1, high=135.0, low=99.0, close=134.0)
        t = s.closed_positions[0]
        assert t.spread_cost == pytest.approx(1.00, rel=1e-12)
        assert t.slippage_cost == pytest.approx(0.20, rel=1e-12)
        gross = (130.0 - 100.0) * 2.0
        assert gross == 60.0
        assert t.pnl == pytest.approx(gross - 1.20, rel=1e-12)

    def test_costs_make_a_loss_worse_not_better(self):
        s = make_skill()
        enter(s, T0)
        bar(s, T1, high=101.0, low=85.0, close=86.0)
        t = s.closed_positions[0]
        gross = (90.0 - 100.0) * 2.0
        assert gross == -20.0
        assert t.pnl == pytest.approx(gross - 1.20, rel=1e-12)

    def test_pnl_pct_is_measured_on_MARGIN_not_notional(self):
        s = make_skill()
        enter(s, T0)
        bar(s, T1, high=135.0, low=99.0, close=134.0)
        t = s.closed_positions[0]
        assert t.margin == pytest.approx(10.0, rel=1e-12)   # 100*2/20
        assert t.pnl_pct == pytest.approx(58.80 / 10.0 * 100, rel=1e-12)
        assert t.pnl_pct == pytest.approx(588.0, rel=1e-12)

    def test_exit_fields_and_status_are_all_set(self):
        s = make_skill()
        enter(s, T0)
        bar(s, T1, high=135.0, low=99.0, close=134.0)
        t = s.closed_positions[0]
        assert t.status == OrderStatus.CLOSED
        assert t.exit_time == T1
        assert t.exit_price == 130.0
        assert t.exit_reason == 'TP_HIT'

    def test_closed_trade_moves_from_open_to_closed_exactly_once(self):
        s = make_skill()
        enter(s, T0)
        bar(s, T1, high=135.0, low=99.0, close=134.0)
        assert s.open_positions == []
        assert len(s.closed_positions) == 1

    def test_leverage_one_makes_margin_the_full_notional(self):
        s = make_skill(backtest={'leverage': 1})
        enter(s, T0)
        bar(s, T1, high=135.0, low=99.0, close=134.0)
        t = s.closed_positions[0]
        assert t.margin == pytest.approx(200.0, rel=1e-12)
        assert t.pnl_pct == pytest.approx(58.80 / 200.0 * 100, rel=1e-12)


class TestClosePositionCapitalAndEquity:

    def test_capital_and_total_pnl_move_together(self):
        s = make_skill()
        enter(s, T0)
        bar(s, T1, high=135.0, low=99.0, close=134.0)
        assert s.capital == pytest.approx(10058.80, rel=1e-12)
        assert s.total_pnl == pytest.approx(58.80, rel=1e-12)

    def test_equity_curve_gets_one_row_per_close(self):
        s = make_skill()
        enter(s, T0)
        bar(s, T1, high=135.0, low=99.0, close=134.0)
        enter(s, T2)
        bar(s, T3, high=101.0, low=85.0, close=86.0)
        assert len(s.equity_curve) == 2
        assert s.equity_curve[0] == {
            'timestamp': T1, 'equity': pytest.approx(10058.80, rel=1e-12),
            'pnl': pytest.approx(58.80, rel=1e-12)}
        assert s.equity_curve[1]['equity'] == pytest.approx(10037.60, rel=1e-12)
        assert s.equity_curve[1]['pnl'] == pytest.approx(-21.20, rel=1e-12)

    def test_win_and_loss_counters_split_on_strictly_positive_pnl(self):
        s = make_skill()
        enter(s, T0)
        bar(s, T1, high=135.0, low=99.0, close=134.0)
        assert (s.winning_trades, s.losing_trades) == (1, 0)
        enter(s, T2)
        bar(s, T3, high=101.0, low=85.0, close=86.0)
        assert (s.winning_trades, s.losing_trades) == (1, 1)

    def test_max_equity_only_ratchets_up(self):
        s = make_skill()
        enter(s, T0)
        bar(s, T1, high=135.0, low=99.0, close=134.0)
        assert s.max_equity == pytest.approx(10058.80, rel=1e-12)
        enter(s, T2)
        bar(s, T3, high=101.0, low=85.0, close=86.0)
        assert s.max_equity == pytest.approx(10058.80, rel=1e-12)   # unchanged by the loss

    def test_max_drawdown_is_the_worst_peak_to_trough_in_dollars(self):
        s = make_skill()
        enter(s, T0)
        bar(s, T1, high=135.0, low=99.0, close=134.0)               # +58.80, new peak
        assert s.max_drawdown == 0.0
        enter(s, T2)
        bar(s, T3, high=101.0, low=85.0, close=86.0)                # -21.20
        assert s.max_drawdown == pytest.approx(21.20, rel=1e-12)

    def test_max_drawdown_does_not_shrink_on_recovery(self):
        s = make_skill()
        enter(s, T0)
        bar(s, T1, high=101.0, low=85.0, close=86.0)                # -21.20 from the start
        assert s.max_drawdown == pytest.approx(21.20, rel=1e-12)
        enter(s, T2)
        bar(s, T3, high=135.0, low=99.0, close=134.0)               # +58.80, recovers
        assert s.capital == pytest.approx(10037.60, rel=1e-12)
        assert s.max_drawdown == pytest.approx(21.20, rel=1e-12)    # the low is remembered


class TestMaxDrawdownPctDenominator:
    """
    FINDING (reported 2026-10-22): `max_drawdown_pct` divides the worst absolute
    drawdown by `max_equity` — the highest equity EVER reached — rather than by
    the peak that particular drawdown fell from. It is therefore not the
    standard max-DD%, and when the account never makes a new high it is simply
    "drawdown as a percentage of starting capital", which is unbounded.

    This is where gotcha 28's "maxDD 1346%" comes from. The prose reading there
    ("the account is wiped ~13x over") is the right conclusion, but the number
    is not a percentage of anything the account ever held.
    """

    def test_a_drawdown_larger_than_the_account_reports_over_100_pct(self):
        s = make_skill()
        s.capital = -40000.0
        s.max_equity = 10000.0
        s.max_drawdown = 50000.0
        assert s.get_results()['max_drawdown_pct'] == pytest.approx(500.0, rel=1e-12)

    def test_the_denominator_is_peak_equity_not_initial_capital(self):
        s = make_skill()
        s.max_equity = 20000.0        # the account doubled at some point
        s.max_drawdown = 5000.0
        # 5000 / 20000, not 5000 / 10000
        assert s.get_results()['max_drawdown_pct'] == pytest.approx(25.0, rel=1e-12)

    def test_zero_peak_equity_is_guarded(self):
        s = make_skill()
        s.max_equity = 0.0
        s.max_drawdown = 1000.0
        assert s.get_results()['max_drawdown_pct'] == 0


# ==========================================================================
# 4. _compute_position_size — dynamic sizing, which compounds
# ==========================================================================

class TestComputePositionSizeStatic:

    def test_disabled_returns_the_configured_size(self):
        s = make_skill()
        assert s.dynamic_sizing_enabled is False
        assert s._compute_position_size() == 2.0

    def test_disabled_ignores_capital_entirely(self):
        s = make_skill()
        s.capital = 1_000_000.0
        assert s._compute_position_size() == 2.0
        s.capital = 1.0
        assert s._compute_position_size() == 2.0


class TestComputePositionSizeStepsMode:
    """
    'steps' mode is the gotcha-25 mechanism: the stale `backtest-runner`
    compounded a reverse-signal scalper into `+$733,912` on $10k through here.
    """

    def _skill(self, **dyn):
        d = {'enabled': True, 'method': 'steps',
             'scale_every_usd': 10000.0, 'size_increment': 1.0}
        d.update(dyn)
        return make_skill(backtesting={'position_size': 1.0, 'dynamic_sizing': d})

    def test_one_step_at_starting_capital(self):
        s = self._skill()
        assert s.capital == 10000.0
        assert s._compute_position_size() == 1.0     # int(10000/10000) * 1.0

    def test_steps_are_floored_integers_not_fractions(self):
        s = self._skill()
        s.capital = 19999.99
        assert s._compute_position_size() == 1.0     # int(1.999999) == 1
        s.capital = 20000.0
        assert s._compute_position_size() == 2.0

    def test_size_doubles_as_capital_doubles(self):
        s = self._skill()
        for capital, expected in [(10000.0, 1.0), (20000.0, 2.0),
                                  (50000.0, 5.0), (100000.0, 10.0)]:
            s.capital = capital
            assert s._compute_position_size() == expected

    def test_size_increment_scales_every_step(self):
        s = self._skill(size_increment=2.5)
        s.capital = 40000.0
        assert s._compute_position_size() == 10.0    # 4 steps * 2.5

    def test_never_falls_below_the_base_size_on_a_drawdown(self):
        s = self._skill()
        s.capital = 1.0                              # account almost wiped
        assert s._compute_position_size() == 1.0     # max(0.0, base 1.0)

    def test_a_negative_account_still_returns_the_base_size(self):
        s = self._skill()
        s.capital = -50000.0
        assert s._compute_position_size() == 1.0

    def test_max_size_caps_the_ladder(self):
        s = self._skill(max_size=4)
        s.capital = 100000.0
        assert s._compute_position_size() == 4.0     # min(10.0, 4.0)

    def test_max_size_is_stored_as_a_float(self):
        s = self._skill(max_size=4)
        assert s.dynamic_sizing_max_size == 4.0
        assert isinstance(s.dynamic_sizing_max_size, float)

    def test_no_max_size_leaves_the_cap_unset(self):
        assert self._skill().dynamic_sizing_max_size is None

    def test_steps_is_the_default_method(self):
        s = make_skill(backtesting={'position_size': 1.0,
                                    'dynamic_sizing': {'enabled': True}})
        assert s.dynamic_sizing_method == 'steps'
        assert s.dynamic_sizing_scale_every_usd == 1000.0
        assert s.dynamic_sizing_size_increment == 1.0


class TestStepsModeKeysOffCapitalNotProfit:
    """
    FINDING (reported 2026-10-22): the `_compute_position_size` docstring says
    'steps' adds `size_increment` "for each full scale_every_usd of PROFIT
    ABOVE INITIAL_CAPITAL". The code (:271) computes
    `int(self.capital / scale_every_usd)` — total capital, from the very first
    trade, with no reference to `initial_capital` at all. The inline comment on
    the same line agrees with the code; only the docstring disagrees.

    The gap is not cosmetic. On the documented reading, a $10k account at zero
    profit trades the base size. On the actual code it trades TEN TIMES that.
    Anyone reasoning about gotcha 25's `+$733,912` from the docstring would
    mis-predict the starting size by a factor of `initial_capital /
    scale_every_usd`.
    """

    def test_at_zero_profit_the_size_is_already_ten_steps(self):
        s = make_skill(backtesting={
            'position_size': 1.0, 'initial_capital': 10000.0,
            'dynamic_sizing': {'enabled': True, 'method': 'steps',
                               'scale_every_usd': 1000.0, 'size_increment': 1.0}})
        assert s.capital == s.initial_capital       # zero profit
        # docstring reading: 0 steps -> base 1.0.  Actual:
        assert s._compute_position_size() == 10.0

    def test_the_factor_is_initial_capital_over_scale_every_usd(self):
        s = make_skill(backtesting={
            'position_size': 1.0, 'initial_capital': 50000.0,
            'dynamic_sizing': {'enabled': True, 'method': 'steps',
                               'scale_every_usd': 1000.0, 'size_increment': 1.0}})
        assert s._compute_position_size() == 50.0

    def test_scale_every_usd_above_initial_capital_yields_zero_steps(self):
        # the only configuration in which the docstring and the code agree
        s = make_skill(backtesting={
            'position_size': 1.0, 'initial_capital': 10000.0,
            'dynamic_sizing': {'enabled': True, 'method': 'steps',
                               'scale_every_usd': 20000.0, 'size_increment': 1.0}})
        assert s._compute_position_size() == 1.0    # max(0 steps, base)


class TestDeployedGoldDynamicSizingIsInert:
    """
    GOLD.yaml really does set `dynamic_sizing.enabled: true`, but with
    `size_increment: 0.1` against a base `position_size: 10`, so
    `max(steps * 0.1, 10)` is pinned at the base until capital reaches
    $100,000 — ten times the starting account.

    Two consequences worth recording:
      - GOLD's own inline comments ("+0.2 oz per step", "$1k->12oz, $2k->14oz,
        $5k->20oz") describe behaviour the code does not produce. The real
        ladder needs 10x the capital per the steps-vs-profit finding above,
        AND the increment is 0.1 rather than the 0.2 the comment claims.
      - the GOLD figures in gotchas 35/41/49 are therefore NOT contaminated by
        compounding — every trade in those runs was a flat 10 oz. That is the
        reassuring half of this finding.
    """

    @pytest.fixture
    def gold(self):
        return make_skill(backtesting={
            'position_size': 10, 'initial_capital': 10000.0,
            'dynamic_sizing': {'enabled': True, 'method': 'steps',
                               'scale_every_usd': 1000, 'size_increment': 0.1,
                               'max_size': 50, 'size_per_capital': 1000}})

    def test_enabled_but_pinned_at_the_base_size(self, gold):
        assert gold.dynamic_sizing_enabled is True
        assert gold._compute_position_size() == 10

    def test_still_pinned_after_the_account_quintuples(self, gold):
        for capital in (20000.0, 50000.0, 99000.0):
            gold.capital = capital
            assert gold._compute_position_size() == 10

    def test_the_ladder_only_starts_at_one_hundred_thousand(self, gold):
        gold.capital = 100000.0
        assert gold._compute_position_size() == pytest.approx(10.0, rel=1e-12)
        gold.capital = 110000.0
        assert gold._compute_position_size() == pytest.approx(11.0, rel=1e-12)

    def test_the_max_size_cap_needs_half_a_million(self, gold):
        gold.capital = 500000.0
        assert gold._compute_position_size() == 50.0
        gold.capital = 10_000_000.0
        assert gold._compute_position_size() == 50.0

    def test_the_comment_s_claim_of_12_oz_at_1k_profit_does_not_happen(self, gold):
        gold.capital = 11000.0      # $1,000 of profit
        assert gold._compute_position_size() == 10      # not 12


class TestComputePositionSizePercentMode:

    def _skill(self, **dyn):
        d = {'enabled': True, 'method': 'percent', 'size_per_capital': 10000.0}
        d.update(dyn)
        return make_skill(backtesting={'position_size': 1.0, 'dynamic_sizing': d})

    def test_one_unit_per_size_per_capital(self):
        s = self._skill()
        assert s._compute_position_size() == 1.0        # 10000 / 10000

    def test_size_is_continuous_not_stepped(self):
        s = self._skill()
        s.capital = 15000.0
        assert s._compute_position_size() == 1.5        # steps mode would say 1.0

    def test_scales_linearly_with_capital(self):
        s = self._skill()
        for capital, expected in [(20000.0, 2.0), (33333.0, 3.3333), (100000.0, 10.0)]:
            s.capital = capital
            assert s._compute_position_size() == pytest.approx(expected, rel=1e-9)

    def test_floors_at_the_base_size_on_a_drawdown(self):
        s = self._skill()
        s.capital = 2000.0
        assert s._compute_position_size() == 1.0        # max(0.2, base 1.0)

    def test_max_size_caps_percent_mode_too(self):
        s = self._skill(max_size=3)
        s.capital = 100000.0
        assert s._compute_position_size() == 3.0

    def test_smaller_size_per_capital_means_more_aggression(self):
        s = self._skill(size_per_capital=1000.0)
        assert s._compute_position_size() == 10.0


class TestDynamicSizingCompoundsThroughRealTrades:
    """
    The sizing mechanism is only dangerous because it feeds back: a bigger size
    makes a bigger P&L, which makes a bigger size. Drive it end-to-end through
    `execute()`/`check_exits()` so the compounding is pinned at the trade
    level, not just in the sizing helper, across a WINNING and a LOSING run.
    """

    def _skill(self):
        return make_skill(backtesting={
            'position_size': 1.0, 'initial_capital': 10000.0,
            'spread_cost_usd': 0.0, 'slippage_cost_usd': 0.0,
            'dynamic_sizing': {'enabled': True, 'method': 'percent',
                               'size_per_capital': 10000.0}})

    def test_a_winning_sequence_doubles_the_size_each_time(self):
        s = self._skill()
        # Each trade targets +100% of capital: TP sits capital/size points away,
        # so with no costs the account exactly doubles on every win. Because
        # size tracks capital, that distance is a constant 10,000 points —
        # which is the compounding, stated as a price.
        expected_sizes = [1.0, 2.0, 4.0]
        expected_capital = [20000.0, 40000.0, 80000.0]
        for i, (size, capital) in enumerate(zip(expected_sizes, expected_capital)):
            ts = datetime(2024, 1, 1 + i, 10, 0)
            tp = 100.0 + s.capital / size
            assert tp == pytest.approx(10100.0, rel=1e-12)
            enter(s, ts, entry=100.0, sl=1.0, tp=tp)
            assert s.open_positions[0].size == pytest.approx(size, rel=1e-12)
            bar(s, datetime(2024, 1, 1 + i, 10, 5), high=tp + 1, low=99.0, close=tp)
            assert s.capital == pytest.approx(capital, rel=1e-12)
        assert [t.size for t in s.closed_positions] == pytest.approx([1.0, 2.0, 4.0], rel=1e-12)

    def test_a_losing_sequence_is_floored_at_the_base_size(self):
        s = self._skill()
        # Lose half the account on one stop. Prices stay positive: check_exits
        # rejects any candle with high <= 0 or low <= 0 as malformed.
        enter(s, datetime(2024, 1, 1, 10, 0), entry=10000.0, sl=5000.0, tp=1e9)
        assert s.open_positions[0].size == pytest.approx(1.0, rel=1e-12)
        bar(s, datetime(2024, 1, 1, 10, 5), high=10001.0, low=4000.0, close=4500.0)
        assert s.closed_positions[0].exit_price == 5000.0
        assert s.closed_positions[0].pnl == pytest.approx(-5000.0, rel=1e-12)
        assert s.capital == pytest.approx(5000.0, rel=1e-12)

        # capital 5000 / 10000 = 0.5, floored back up to the base 1.0
        enter(s, datetime(2024, 1, 2, 10, 0), entry=100.0, sl=90.0, tp=1e9)
        assert s.open_positions[0].size == pytest.approx(1.0, rel=1e-12)
        bar(s, datetime(2024, 1, 2, 10, 5), high=101.0, low=85.0, close=86.0)
        assert s.capital == pytest.approx(4990.0, rel=1e-12)

        # still floored — percent mode scales down but never below base
        s.capital = 10.0
        assert s._compute_position_size() == 1.0

    def test_size_is_fixed_at_ENTRY_and_not_revised_while_open(self):
        s = self._skill()
        enter(s, T0, entry=100.0, sl=1.0, tp=10100.0)
        assert s.open_positions[0].size == pytest.approx(1.0, rel=1e-12)
        s.capital = 1_000_000.0                  # a windfall mid-trade
        assert s.open_positions[0].size == pytest.approx(1.0, rel=1e-12)
        bar(s, T1, high=10101.0, low=99.0, close=10100.0)
        assert s.closed_positions[0].size == pytest.approx(1.0, rel=1e-12)

    def test_costs_scale_with_the_dynamic_size_too(self):
        s = make_skill(backtesting={
            'position_size': 1.0, 'initial_capital': 40000.0,
            'spread_cost_usd': 0.50, 'slippage_cost_usd': 0.10,
            'dynamic_sizing': {'enabled': True, 'method': 'percent',
                               'size_per_capital': 10000.0}})
        enter(s, T0)
        t = s.open_positions[0]
        assert t.size == pytest.approx(4.0, rel=1e-12)
        assert t.spread_cost == pytest.approx(2.00, rel=1e-12)      # 0.50 * 4
        assert t.slippage_cost == pytest.approx(0.40, rel=1e-12)    # 0.10 * 4


# ==========================================================================
# 5. close_reverse_positions — the reverse-exit path
# ==========================================================================

class TestCloseReversePositions:
    """
    Gotcha 25's `+$185,306` artefact came through here (16,802 of 16,999 exits
    booked as `Reverse Signal`, avg hold 1.3 bars). The caller's guard is
    `run_skills_backtest.py:557`, which defaults `reverse_signal_exit` to
    False — matching live and every deployed YAML (gotcha 41).
    """

    def test_a_buy_signal_closes_an_open_sell(self):
        s = make_skill()
        enter(s, T0, signal='SELL', entry=100.0, sl=110.0, tp=70.0)
        closed = s.close_reverse_positions('BUY', 95.0, T1)
        assert len(closed) == 1
        assert closed[0].exit_reason == 'Reverse Signal'
        assert closed[0].exit_price == 95.0
        assert s.open_positions == []

    def test_a_sell_signal_closes_an_open_buy(self):
        s = make_skill()
        enter(s, T0)
        closed = s.close_reverse_positions('SELL', 105.0, T1)
        assert len(closed) == 1
        assert closed[0].side == OrderSide.BUY
        assert closed[0].exit_price == 105.0

    def test_a_same_direction_signal_leaves_the_position_alone(self):
        s = make_skill()
        enter(s, T0)
        assert s.close_reverse_positions('BUY', 105.0, T1) == []
        assert len(s.open_positions) == 1
        assert s.closed_positions == []

    def test_pnl_is_the_exact_price_difference_less_costs(self):
        s = make_skill()
        enter(s, T0)                                     # BUY @ 100.00, size 2
        s.close_reverse_positions('SELL', 105.0, T1)
        # (105 - 100) * 2 - 1.20
        assert s.closed_positions[0].pnl == pytest.approx(8.80, rel=1e-12)
        assert s.capital == pytest.approx(10008.80, rel=1e-12)

    def test_a_reverse_exit_at_a_loss_is_booked_as_a_loss(self):
        s = make_skill()
        enter(s, T0)
        s.close_reverse_positions('SELL', 97.0, T1)
        # (97 - 100) * 2 - 1.20
        assert s.closed_positions[0].pnl == pytest.approx(-7.20, rel=1e-12)
        assert s.get_results()['losing_trades'] == 1

    def test_it_feeds_the_equity_curve_and_drawdown_like_any_close(self):
        s = make_skill()
        enter(s, T0)
        s.close_reverse_positions('SELL', 97.0, T1)
        assert len(s.equity_curve) == 1
        assert s.equity_curve[0]['timestamp'] == T1
        assert s.max_drawdown == pytest.approx(7.20, rel=1e-12)

    def test_no_open_positions_is_a_no_op(self):
        s = make_skill()
        assert s.close_reverse_positions('BUY', 100.0, T1) == []

    def test_only_the_opposite_side_closes_when_both_are_open(self):
        s = make_skill()
        s.open_positions.append(SimulatedTrade(
            entry_time=T0, entry_price=100.0, side=OrderSide.BUY, size=2.0,
            stop_loss=90.0, take_profit=130.0))
        s.open_positions.append(SimulatedTrade(
            entry_time=T0, entry_price=100.0, side=OrderSide.SELL, size=2.0,
            stop_loss=110.0, take_profit=70.0))
        closed = s.close_reverse_positions('BUY', 95.0, T1)
        assert len(closed) == 1
        assert closed[0].side == OrderSide.SELL
        assert len(s.open_positions) == 1
        assert s.open_positions[0].side == OrderSide.BUY

    def test_any_non_BUY_signal_string_is_treated_as_a_sell(self):
        # `opposite = SELL if new_signal == 'BUY' else BUY` — there is no
        # validation, so a malformed signal closes LONGS.
        s = make_skill()
        enter(s, T0)
        closed = s.close_reverse_positions('EXIT', 105.0, T1)
        assert len(closed) == 1
        assert closed[0].side == OrderSide.BUY


class TestCloseReversePositionsDisabled:

    def test_disable_reverse_exit_makes_it_a_no_op(self):
        s = make_skill(backtesting_filters={'disable_reverse_exit': True})
        enter(s, T0)
        assert s.close_reverse_positions('SELL', 105.0, T1) == []
        assert len(s.open_positions) == 1
        assert s.closed_positions == []

    def test_the_flag_defaults_to_False(self):
        assert make_skill().disable_reverse_exit is False


class TestCloseReversePositionsMinHold:
    """`backtesting_filters.min_hold_minutes` suppresses churn by letting a
    young trade live through an opposing signal."""

    def test_defaults_to_zero(self):
        assert make_skill().min_hold_minutes == 0

    def test_a_trade_younger_than_min_hold_survives(self):
        s = make_skill(backtesting_filters={'min_hold_minutes': 60})
        enter(s, T0)
        assert s.close_reverse_positions('SELL', 105.0, datetime(2024, 1, 1, 10, 30)) == []
        assert len(s.open_positions) == 1

    def test_a_trade_at_exactly_min_hold_is_closed(self):
        s = make_skill(backtesting_filters={'min_hold_minutes': 60})
        enter(s, T0)
        closed = s.close_reverse_positions('SELL', 105.0, datetime(2024, 1, 1, 11, 0))
        assert len(closed) == 1
        assert closed[0].exit_reason == 'Reverse Signal'

    def test_one_minute_short_of_min_hold_survives(self):
        s = make_skill(backtesting_filters={'min_hold_minutes': 60})
        enter(s, T0)
        assert s.close_reverse_positions('SELL', 105.0, datetime(2024, 1, 1, 10, 59)) == []

    def test_min_hold_zero_closes_an_instant_reversal(self):
        s = make_skill()
        enter(s, T0)
        assert len(s.close_reverse_positions('SELL', 105.0, T0)) == 1

    def test_the_filter_is_per_trade_not_per_call(self):
        s = make_skill(backtesting_filters={'min_hold_minutes': 60})
        s.open_positions.append(SimulatedTrade(                    # old enough
            entry_time=datetime(2024, 1, 1, 8, 0), entry_price=100.0,
            side=OrderSide.BUY, size=2.0, stop_loss=90.0, take_profit=130.0))
        s.open_positions.append(SimulatedTrade(                    # too young
            entry_time=datetime(2024, 1, 1, 10, 30), entry_price=100.0,
            side=OrderSide.BUY, size=2.0, stop_loss=90.0, take_profit=130.0))
        closed = s.close_reverse_positions('SELL', 105.0, datetime(2024, 1, 1, 11, 0))
        assert len(closed) == 1
        assert closed[0].entry_time == datetime(2024, 1, 1, 8, 0)
        assert len(s.open_positions) == 1


# ==========================================================================
# 6. validate_config / __init__ / execute
# ==========================================================================

class TestValidateConfig:

    def test_the_canonical_config_is_valid(self):
        assert make_skill().validate_config() is True

    def test_zero_initial_capital_is_rejected(self):
        assert make_skill(backtesting={'initial_capital': 0}).validate_config() is False

    def test_negative_initial_capital_is_rejected(self):
        assert make_skill(backtesting={'initial_capital': -1.0}).validate_config() is False

    def test_zero_position_size_is_rejected(self):
        assert make_skill(backtesting={'position_size': 0}).validate_config() is False

    def test_negative_position_size_is_rejected(self):
        assert make_skill(backtesting={'position_size': -2.0}).validate_config() is False

    def test_a_tiny_but_positive_size_is_accepted(self):
        assert make_skill(backtesting={'position_size': 0.01}).validate_config() is True

    def test_it_does_not_validate_costs_or_sl_tp(self):
        # documents what is NOT checked: gotcha 31's 50x slippage typo would
        # have sailed through this function
        s = make_skill(backtesting={'slippage_cost_usd': 10.0})
        assert s.validate_config() is True
        assert s.slippage_cost_usd == 10.0


class TestInitDefaults:

    def test_nested_backtesting_section_defaults(self):
        s = BacktestingSkill({})
        assert s.initial_capital == 10000.0
        assert s.position_size == 1.0
        assert s.spread_cost_usd == 0.50
        assert s.slippage_cost_usd == 0.05
        assert s.commission_per_trade == 2.0
        assert s.intra_candle_simulation is True

    def test_leverage_comes_from_the_singular_backtest_section(self):
        # `backtest:` (data_path / report_prefix / leverage) is a DIFFERENT
        # section from `backtesting:` (sizing / costs). Both are real.
        assert BacktestingSkill({'backtest': {'leverage': 30}}).leverage == 30.0
        assert BacktestingSkill({'backtesting': {'leverage': 30}}).leverage == 1.0

    def test_a_flat_config_is_detected_by_start_date(self):
        s = BacktestingSkill({'start_date': '2022-01-01', 'initial_capital': 5000,
                              'position_size': 3.0})
        assert s.initial_capital == 5000
        assert s.position_size == 3.0

    def test_without_start_date_top_level_keys_are_ignored(self):
        s = BacktestingSkill({'initial_capital': 5000})
        assert s.initial_capital == 10000.0

    def test_sl_tp_pips_come_from_the_risk_section(self):
        s = BacktestingSkill({'risk': {'stop_loss_pips': 15, 'take_profit_pips': 60}})
        assert s.stop_loss_pips == 15
        assert s.take_profit_pips == 60

    def test_sl_tp_pip_defaults_are_20_and_40(self):
        s = BacktestingSkill({})
        assert s.stop_loss_pips == 20
        assert s.take_profit_pips == 40

    def test_initial_state_is_clean(self):
        s = make_skill()
        assert s.capital == 10000.0
        assert s.max_equity == 10000.0
        assert s.max_drawdown == 0.0
        assert s.total_pnl == 0.0
        assert s.total_trades == 0
        assert s.winning_trades == 0
        assert s.losing_trades == 0
        assert s.open_positions == []
        assert s.closed_positions == []
        assert s.equity_curve == []


class TestReset:

    def test_reset_clears_every_counter_and_the_trade_lists(self):
        s = make_skill()
        enter(s, T0)
        bar(s, T1, high=135.0, low=99.0, close=134.0)
        enter(s, T2)
        s.reset()
        assert s.capital == 10000.0
        assert s.total_pnl == 0.0
        assert s.total_trades == 0
        assert s.winning_trades == 0
        assert s.losing_trades == 0
        assert s.max_equity == 10000.0
        assert s.max_drawdown == 0.0
        assert s.open_positions == []
        assert s.closed_positions == []
        assert s.equity_curve == []

    def test_results_after_reset_are_the_empty_shape(self):
        s = make_skill()
        enter(s, T0)
        bar(s, T1, high=135.0, low=99.0, close=134.0)
        s.reset()
        r = s.get_results()
        assert r['total_pnl'] == 0.0
        assert r['total_trades'] == 0
        assert r['trades'] == []


class TestExecuteGuards:

    def test_no_signal_opens_nothing(self):
        s = make_skill()
        assert s.execute(ctx_at(T0, {'close': 100.0})) is False
        assert s.total_trades == 0

    def test_an_EXIT_signal_is_not_an_entry(self):
        s = make_skill()
        c = ctx_at(T0, {'close': 100.0}, signal='EXIT', entry_price=100.0,
                   stop_loss=90.0, take_profit=130.0)
        assert s.execute(c) is False

    def test_a_second_concurrent_position_is_refused(self):
        s = make_skill()
        enter(s, T0)
        c = ctx_at(T1, {'close': 100.0}, signal='BUY', entry_price=100.0,
                   stop_loss=90.0, take_profit=130.0)
        assert s.execute(c) is False
        assert len(s.open_positions) == 1
        assert s.total_trades == 1

    def test_entry_price_falls_back_to_the_candle_close(self):
        s = make_skill()
        c = ctx_at(T0, {'close': 123.0}, signal='BUY', stop_loss=90.0, take_profit=130.0)
        assert s.execute(c) is True
        assert s.open_positions[0].entry_price == 123.0

    def test_entry_price_falls_back_to_a_price_key(self):
        s = make_skill()
        c = ctx_at(T0, {'price': 111.0}, signal='BUY', stop_loss=90.0, take_profit=130.0)
        assert s.execute(c) is True
        assert s.open_positions[0].entry_price == 111.0

    def test_no_price_anywhere_is_refused(self):
        s = make_skill()
        c = ctx_at(T0, None, signal='BUY', stop_loss=90.0, take_profit=130.0)
        assert s.execute(c) is False
        assert s.total_trades == 0

    def test_a_negative_entry_price_is_refused(self):
        s = make_skill()
        c = ctx_at(T0, {'close': -5.0}, signal='BUY', stop_loss=90.0, take_profit=130.0)
        assert s.execute(c) is False

    def test_total_trades_counts_entries_not_closes(self):
        s = make_skill()
        enter(s, T0)
        assert s.total_trades == 1
        assert s.get_results()['total_trades'] == 1
        assert s.get_results()['winning_trades'] == 0
        assert s.get_results()['losing_trades'] == 0

    def test_the_trade_records_the_context_timestamp_as_entry_time(self):
        s = make_skill()
        enter(s, T0)
        assert s.open_positions[0].entry_time == T0


class TestExecuteSideMapping:

    def test_buy_maps_to_OrderSide_BUY(self):
        s = make_skill()
        enter(s, T0, signal='BUY')
        assert s.open_positions[0].side == OrderSide.BUY

    def test_sell_maps_to_OrderSide_SELL(self):
        s = make_skill()
        enter(s, T0, signal='SELL', entry=100.0, sl=110.0, tp=70.0)
        assert s.open_positions[0].side == OrderSide.SELL

    def test_context_sl_tp_are_used_verbatim(self):
        s = make_skill()
        enter(s, T0, entry=100.0, sl=87.5, tp=142.5)
        t = s.open_positions[0]
        assert t.stop_loss == 87.5
        assert t.take_profit == 142.5


class TestRunBacktestPlaceholder:
    """`run_backtest` is a stub — it resets and returns empty results. It does
    NOT drive the strategy; `run_skills_backtest.py` does that. Pinned so the
    stub is not mistaken for the real engine."""

    def test_empty_data_returns_None(self):
        import pandas as pd
        assert make_skill().run_backtest(pd.DataFrame()) is None

    def test_none_data_returns_None(self):
        assert make_skill().run_backtest(None) is None

    def test_it_resets_and_reports_zero_trades_despite_real_candles(self):
        import pandas as pd
        s = make_skill()
        enter(s, T0)
        bar(s, T1, high=135.0, low=99.0, close=134.0)
        df = pd.DataFrame([{'timestamp': T0, 'open': 100.0, 'high': 101.0,
                            'low': 99.0, 'close': 100.0, 'volume': 1}])
        r = s.run_backtest(df)
        assert r['total_trades'] == 0        # the earlier trade was reset away
        assert r['total_pnl'] == 0.0
        assert r['equity_curve'] == []


class TestSimulatedTradeToDict:

    def test_an_open_trade_serialises_with_None_exit_fields(self):
        t = SimulatedTrade(entry_time=T0, entry_price=100.0, side=OrderSide.SELL,
                           size=3.0, stop_loss=110.0, take_profit=70.0)
        d = t.to_dict()
        assert d['side'] == 'SELL'
        assert d['status'] == 'OPEN'
        assert d['size'] == 3.0
        assert d['stop_loss'] == 110.0
        assert d['take_profit'] == 70.0
        assert d['exit_time'] is None
        assert d['exit_price'] is None
        assert d['exit_reason'] is None
        assert d['pnl'] == 0.0
        assert d['pnl_pct'] == 0.0
        assert d['margin'] == 0.0

    def test_every_field_the_trades_csv_depends_on_is_present(self):
        # `trades.csv` is what gotchas 31 and 32 were diagnosed from
        d = SimulatedTrade(entry_time=T0, entry_price=100.0, side=OrderSide.BUY,
                           size=1.0).to_dict()
        assert set(d) == {
            'entry_time', 'entry_price', 'side', 'size', 'stop_loss',
            'take_profit', 'exit_time', 'exit_price', 'exit_reason', 'status',
            'pnl', 'pnl_pct', 'margin', 'spread_cost', 'slippage_cost'}


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
