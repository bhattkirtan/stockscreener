"""
Unit tests — core/sl_tp_engine.py, the SL/TP arithmetic.

This module decides, for every trade, where the money stops. It is pure
functions over floats, which is exactly the shape of code where CLAUDE.md
gotcha 31 hid a 50x slippage typo for months: nothing crashes, every backtest
still prints a number, and the number is wrong. It was at 44% (30 of 54
statements uncovered) — only the `fixed` BUY path and the dispatcher's default
branch were exercised, because `fixed` is all six deployed instruments use.
The other four methods are one config line away from live.

The assertions are deliberately exact prices rather than "SL < entry": a
magnitude error is the failure mode that matters, and an inequality would not
catch a factor of 50. Where a method has no safety guard, the test says so.

Reference figures use GOLD-shaped prices (pip_size 1.0, so $1/pip/contract) and
the deployed GOLD geometry of SL 15 / TP 45.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from core.indicators import FIBONACCI_LEVELS
from core.sl_tp_engine import (
    calculate_atr_sl_tp,
    calculate_fibonacci_sl_tp,
    calculate_fixed_sl_tp,
    calculate_pct_sl_tp,
    calculate_supertrend_sl_tp,
    compute_sl_tp,
)


# ──────────────────────────────────────────────────────────────────────────
# fixed — the only method any deployed instrument uses
# ──────────────────────────────────────────────────────────────────────────

class TestFixedPips:

    def test_buy_puts_sl_below_and_tp_above(self):
        """GOLD live geometry: SL 15 / TP 45 at pip_size 1.0."""
        sl, tp = calculate_fixed_sl_tp('BUY', 4100.0, 15, 45, pip_size=1.0)
        assert (sl, tp) == (4085.0, 4145.0)

    def test_sell_mirrors_buy(self):
        sl, tp = calculate_fixed_sl_tp('SELL', 4100.0, 15, 45, pip_size=1.0)
        assert (sl, tp) == (4115.0, 4055.0)

    def test_forex_pip_size_scales_the_distance(self):
        """
        EURUSD is pip_size 0.0001 and SL 20 / TP 60. Getting pip_size wrong
        here is a 10,000x error in risk — gotcha 8.
        """
        sl, tp = calculate_fixed_sl_tp('BUY', 1.0850, 20, 60, pip_size=0.0001)
        assert sl == pytest.approx(1.0830)
        assert tp == pytest.approx(1.0910)

    def test_the_realised_rr_is_the_configured_rr(self):
        sl, tp = calculate_fixed_sl_tp('BUY', 4100.0, 15, 45, pip_size=1.0)
        assert (tp - 4100.0) / (4100.0 - sl) == pytest.approx(3.0)

    def test_anything_that_is_not_buy_is_treated_as_sell(self):
        """The branch is `if signal == 'BUY' / else`, so there is no third case."""
        assert calculate_fixed_sl_tp('SELL', 4100.0, 15, 45) == \
               calculate_fixed_sl_tp('EXIT', 4100.0, 15, 45)

    def test_zero_distances_collapse_onto_entry(self):
        assert calculate_fixed_sl_tp('BUY', 4100.0, 0, 0) == (4100.0, 4100.0)


# ──────────────────────────────────────────────────────────────────────────
# atr
# ──────────────────────────────────────────────────────────────────────────

class TestAtr:

    def test_buy_scales_both_legs_by_atr(self):
        sl, tp = calculate_atr_sl_tp('BUY', 4100.0, atr=10.0,
                                     sl_multiplier=1.5, tp_multiplier=3.0)
        assert (sl, tp) == (4085.0, 4130.0)

    def test_sell_mirrors_buy(self):
        sl, tp = calculate_atr_sl_tp('SELL', 4100.0, atr=10.0,
                                     sl_multiplier=1.5, tp_multiplier=3.0)
        assert (sl, tp) == (4115.0, 4070.0)

    def test_the_defaults_are_15_and_30(self):
        sl, tp = calculate_atr_sl_tp('BUY', 4100.0, atr=10.0)
        assert (sl, tp) == (4085.0, 4130.0)

    def test_the_rr_is_the_multiplier_ratio_not_the_atr(self):
        """ATR cancels, so R:R is fixed by the multipliers at any volatility."""
        for atr in (1.0, 10.0, 97.3):
            sl, tp = calculate_atr_sl_tp('BUY', 4100.0, atr=atr,
                                         sl_multiplier=1.5, tp_multiplier=3.0)
            assert (tp - 4100.0) / (4100.0 - sl) == pytest.approx(2.0)

    def test_doubling_atr_doubles_the_risk_per_trade(self):
        """The point of ATR mode — and the reason position size must adapt too."""
        narrow = calculate_atr_sl_tp('BUY', 4100.0, atr=5.0)
        wide = calculate_atr_sl_tp('BUY', 4100.0, atr=10.0)
        assert (4100.0 - wide[0]) == pytest.approx(2 * (4100.0 - narrow[0]))


# ──────────────────────────────────────────────────────────────────────────
# pct
# ──────────────────────────────────────────────────────────────────────────

class TestPct:

    def test_buy_uses_a_fraction_of_entry(self):
        """0.5% / 1.0% of 4100 = 20.5 / 41.0."""
        sl, tp = calculate_pct_sl_tp('BUY', 4100.0, sl_pct=0.005, tp_pct=0.01)
        assert sl == pytest.approx(4079.5)
        assert tp == pytest.approx(4141.0)

    def test_sell_mirrors_buy(self):
        sl, tp = calculate_pct_sl_tp('SELL', 4100.0, sl_pct=0.005, tp_pct=0.01)
        assert sl == pytest.approx(4120.5)
        assert tp == pytest.approx(4059.0)

    def test_the_defaults_are_half_a_percent_and_one_percent(self):
        assert calculate_pct_sl_tp('BUY', 1000.0) == pytest.approx((995.0, 1010.0))

    def test_the_pct_is_a_fraction_not_a_percent_number(self):
        """
        `sl_pct: 0.5` means 50%, not 0.5%. Pinned because the field name reads
        the other way and a config author will get it wrong exactly once.
        """
        sl, _ = calculate_pct_sl_tp('BUY', 4100.0, sl_pct=0.5)
        assert sl == pytest.approx(2050.0)

    def test_the_distance_grows_with_price_unlike_fixed_pips(self):
        """Why BTCUSD cannot share GOLD's fixed-pip config."""
        cheap = calculate_pct_sl_tp('BUY', 100.0, sl_pct=0.005)
        rich = calculate_pct_sl_tp('BUY', 100000.0, sl_pct=0.005)
        assert (100.0 - cheap[0]) == pytest.approx(0.5)
        assert (100000.0 - rich[0]) == pytest.approx(500.0)


# ──────────────────────────────────────────────────────────────────────────
# fibonacci
# ──────────────────────────────────────────────────────────────────────────

class TestFibonacci:
    """
    The grid is measured DOWN from the swing high: ratio 0.0 is the high, 1.0
    the low (indicators.py:282). With high 4200 / low 4100 the 0.382 level is
    4161.8 and the 0.618 level is 4138.2.
    """

    HIGH, LOW = 4200.0, 4100.0

    def test_buy_stop_is_the_five_percent_guard_when_fib_sits_above_entry(self):
        """
        Entry 4150, so the 0.382 retracement (4161.8) is ABOVE entry — a stop
        there is instantly hit. The `min(sl_price, entry - 5% of range)` guard
        is what prevents it: 4150 - 5 = 4145.
        """
        sl, tp = calculate_fibonacci_sl_tp('BUY', 4150.0, self.HIGH, self.LOW)
        assert sl == pytest.approx(4145.0)
        assert tp == pytest.approx(4261.8)   # low + 1.618 * 100

    def test_buy_stop_is_the_fib_level_when_it_sits_well_below_entry(self):
        """Entry 4195: min(4161.8, 4190.0) picks the fib level."""
        sl, _ = calculate_fibonacci_sl_tp('BUY', 4195.0, self.HIGH, self.LOW)
        assert sl == pytest.approx(4161.8)

    def test_sell_stop_is_the_fib_level_when_it_sits_above_the_guard(self):
        """Entry 4150: max(4161.8, 4155.0) picks the fib level."""
        sl, tp = calculate_fibonacci_sl_tp('SELL', 4150.0, self.HIGH, self.LOW)
        assert sl == pytest.approx(4161.8)
        assert tp == pytest.approx(4038.2)   # high - 1.618 * 100

    def test_sell_stop_is_the_five_percent_guard_when_fib_sits_below_entry(self):
        """
        Entry 4180, so the 0.382 retracement (4161.8) is BELOW entry and a
        SELL stop there is instantly hit. `max(sl_price, entry + 5% of range)`
        is the mirror guard: 4180 + 5 = 4185.
        """
        sl, _ = calculate_fibonacci_sl_tp('SELL', 4180.0, self.HIGH, self.LOW)
        assert sl == pytest.approx(4185.0)

    def test_the_stop_is_always_on_the_losing_side_of_entry(self):
        """
        The invariant that actually matters: a stop on the winning side of
        entry is a guaranteed instant loss. The 5% guard enforces it for every
        entry inside the swing range.
        """
        for entry in (4100.0, 4125.0, 4150.0, 4175.0, 4200.0):
            buy_sl, _ = calculate_fibonacci_sl_tp('BUY', entry, self.HIGH, self.LOW)
            sell_sl, _ = calculate_fibonacci_sl_tp('SELL', entry, self.HIGH, self.LOW)
            assert buy_sl < entry, f'BUY stop above entry at {entry}'
            assert sell_sl > entry, f'SELL stop below entry at {entry}'

    def test_a_requested_level_is_snapped_to_the_nearest_fibonacci_ratio(self):
        """
        `snap()` quantises to FIBONACCI_LEVELS, so a config asking for a 2.0
        extension silently gets 1.618 — the config value and the executed value
        are not the same number. Gotcha-31 class: wrong, and silent.
        """
        assert 2.0 not in FIBONACCI_LEVELS
        snapped = calculate_fibonacci_sl_tp('BUY', 4150.0, self.HIGH, self.LOW,
                                            tp_fib_level=2.0)
        exact = calculate_fibonacci_sl_tp('BUY', 4150.0, self.HIGH, self.LOW,
                                          tp_fib_level=1.618)
        assert snapped[1] == pytest.approx(exact[1])

    def test_an_out_of_range_level_snaps_to_the_extreme(self):
        sl, tp = calculate_fibonacci_sl_tp('BUY', 4150.0, self.HIGH, self.LOW,
                                           sl_fib_level=-5.0, tp_fib_level=99.0)
        assert tp == pytest.approx(self.LOW + 2.618 * 100)   # snapped to 2.618
        assert sl == pytest.approx(4145.0)                   # 0.0 level -> guard wins

    def test_a_custom_sl_level_moves_the_stop(self):
        sl, _ = calculate_fibonacci_sl_tp('BUY', 4195.0, self.HIGH, self.LOW,
                                          sl_fib_level=0.618)
        assert sl == pytest.approx(4138.2)

    def test_a_degenerate_zero_width_swing_gives_a_zero_width_trade(self):
        """
        swing_high == swing_low makes every level the same price and the 5%
        guard zero-width, so SL and TP collapse onto the swing. There is no
        validation against it; during indicator warm-up it is reachable.
        """
        sl, tp = calculate_fibonacci_sl_tp('BUY', 4100.0, 4100.0, 4100.0)
        assert sl == pytest.approx(4100.0)
        assert tp == pytest.approx(4100.0)

    def test_the_tp_is_projected_from_the_swing_not_from_entry(self):
        """
        TP is `swing_low + range * ratio`, independent of entry — so a late
        entry gets a much worse R:R than an early one on the same swing.
        """
        early = calculate_fibonacci_sl_tp('BUY', 4110.0, self.HIGH, self.LOW)
        late = calculate_fibonacci_sl_tp('BUY', 4190.0, self.HIGH, self.LOW)
        assert early[1] == pytest.approx(late[1])
        assert (early[1] - 4110.0) > (late[1] - 4190.0)


# ──────────────────────────────────────────────────────────────────────────
# supertrend
# ──────────────────────────────────────────────────────────────────────────

class TestSupertrend:

    def test_buy_anchors_the_stop_on_the_band_and_scales_tp_by_rr(self):
        """Band 4085 under entry 4100 -> 15 of risk, 30 of reward at R:R 2."""
        sl, tp = calculate_supertrend_sl_tp('BUY', 4100.0, 4085.0,
                                            risk_reward_ratio=2.0)
        assert (sl, tp) == (4085.0, 4130.0)

    def test_sell_mirrors_buy(self):
        sl, tp = calculate_supertrend_sl_tp('SELL', 4100.0, 4115.0,
                                            risk_reward_ratio=2.0)
        assert (sl, tp) == (4115.0, 4070.0)

    def test_the_default_rr_is_two(self):
        sl, tp = calculate_supertrend_sl_tp('BUY', 4100.0, 4090.0)
        assert (sl, tp) == (4090.0, 4120.0)

    def test_the_realised_rr_is_the_configured_rr(self):
        sl, tp = calculate_supertrend_sl_tp('BUY', 4100.0, 4085.0,
                                            risk_reward_ratio=3.0)
        assert (tp - 4100.0) / (4100.0 - sl) == pytest.approx(3.0)

    def test_a_band_on_the_wrong_side_of_entry_is_mirrored_not_used_raw(self):
        """
        A BUY whose band sits ABOVE entry previously got a stop above entry —
        hit on the next tick, with a TP sized as if the trade were sound. The
        band's DISTANCE is now kept but mirrored to the losing side.
        """
        sl, tp = calculate_supertrend_sl_tp('BUY', 4100.0, 4115.0,
                                            risk_reward_ratio=2.0)
        assert sl == 4085.0, '15 below entry, not 15 above'
        assert tp == 4130.0

    def test_a_band_on_the_wrong_side_is_mirrored_for_sell_too(self):
        sl, tp = calculate_supertrend_sl_tp('SELL', 4100.0, 4085.0,
                                            risk_reward_ratio=2.0)
        assert sl == 4115.0
        assert tp == 4070.0

    def test_the_guard_changes_nothing_when_the_band_is_on_the_correct_side(self):
        """
        The reachable case must be byte-identical: for a BUY the active
        Supertrend line is the lower band, which sits below price, so the stop
        is still exactly the band.
        """
        for band in (4099.9, 4085.0, 4000.0, 3000.0):
            sl, _ = calculate_supertrend_sl_tp('BUY', 4100.0, band)
            assert sl == pytest.approx(band)
        for band in (4100.1, 4115.0, 4200.0):
            sl, _ = calculate_supertrend_sl_tp('SELL', 4100.0, band)
            assert sl == pytest.approx(band)

    def test_the_stop_is_always_on_the_losing_side_of_entry(self):
        """The invariant the fibonacci path has and this one now has too."""
        for band in (3900.0, 4085.0, 4099.0, 4101.0, 4115.0, 4300.0):
            buy_sl, buy_tp = calculate_supertrend_sl_tp('BUY', 4100.0, band)
            sell_sl, sell_tp = calculate_supertrend_sl_tp('SELL', 4100.0, band)
            assert buy_sl < 4100.0 < buy_tp, f'BUY broken at band {band}'
            assert sell_sl > 4100.0 > sell_tp, f'SELL broken at band {band}'

    def test_a_band_exactly_at_entry_gives_a_zero_width_trade(self):
        assert calculate_supertrend_sl_tp('BUY', 4100.0, 4100.0) == (4100.0, 4100.0)

    def test_a_wider_band_widens_risk_and_reward_together(self):
        tight = calculate_supertrend_sl_tp('BUY', 4100.0, 4095.0)
        loose = calculate_supertrend_sl_tp('BUY', 4100.0, 4080.0)
        assert (4100.0 - loose[0]) == 4 * (4100.0 - tight[0])
        assert (loose[1] - 4100.0) == 4 * (tight[1] - 4100.0)


# ──────────────────────────────────────────────────────────────────────────
# the dispatcher
# ──────────────────────────────────────────────────────────────────────────

class TestDispatcherRouting:
    """
    `compute_sl_tp` is what AnalysisSkill calls (analysis_skill.py:1093),
    passing atr / supertrend / swing_high / swing_low straight out of the
    indicator dict — any of which can be None mid-warm-up.
    """

    def test_fixed_is_the_default_when_no_method_is_given(self):
        assert compute_sl_tp('BUY', 4100.0, {}) == (4080.0, 4140.0)

    def test_the_fixed_defaults_are_20_and_40_pips(self):
        """
        Note these differ from every deployed instrument (GOLD is 15/45), so a
        config that loses its `stop_loss_pips` key silently trades 20/40 at
        R:R 2 instead of failing.
        """
        sl, tp = compute_sl_tp('BUY', 4100.0, {'method': 'fixed'})
        assert (4100.0 - sl, tp - 4100.0) == (20.0, 40.0)

    def test_fixed_honours_pip_size_from_the_config(self):
        cfg = {'method': 'fixed', 'stop_loss_pips': 20, 'take_profit_pips': 60,
               'pip_size': 0.0001}
        sl, tp = compute_sl_tp('BUY', 1.0850, cfg)
        assert sl == pytest.approx(1.0830) and tp == pytest.approx(1.0910)

    def test_pct_routes_to_the_pct_calculator(self):
        cfg = {'method': 'pct', 'sl_pct': 0.005, 'tp_pct': 0.01}
        assert compute_sl_tp('BUY', 4100.0, cfg) == \
               pytest.approx(calculate_pct_sl_tp('BUY', 4100.0, 0.005, 0.01))

    def test_pct_does_not_need_any_indicator_values(self):
        assert compute_sl_tp('SELL', 4100.0, {'method': 'pct'},
                             atr=None, supertrend_value=None) == \
               pytest.approx((4120.5, 4059.0))

    def test_atr_routes_when_atr_is_positive(self):
        cfg = {'method': 'atr', 'atr_sl_multiplier': 1.5, 'atr_tp_multiplier': 3.0}
        assert compute_sl_tp('BUY', 4100.0, cfg, atr=10.0) == (4085.0, 4130.0)

    def test_atr_falls_back_to_fixed_when_atr_is_missing(self):
        """
        The warm-up trap: `method: atr` with no ATR yet silently trades fixed
        20/40 pips instead of raising. Reachable on the first bars after a
        restart, when ATR is still None.
        """
        cfg = {'method': 'atr', 'stop_loss_pips': 15, 'take_profit_pips': 45}
        assert compute_sl_tp('BUY', 4100.0, cfg, atr=None) == (4085.0, 4145.0)

    def test_atr_falls_back_to_fixed_when_atr_is_zero_or_negative(self):
        cfg = {'method': 'atr', 'stop_loss_pips': 15, 'take_profit_pips': 45}
        assert compute_sl_tp('BUY', 4100.0, cfg, atr=0.0) == (4085.0, 4145.0)
        assert compute_sl_tp('BUY', 4100.0, cfg, atr=-3.0) == (4085.0, 4145.0)

    def test_atr_falls_back_to_fixed_on_nan(self):
        """Indicator columns are NaN during warm-up, and `nan > 0` is False."""
        cfg = {'method': 'atr', 'stop_loss_pips': 15, 'take_profit_pips': 45}
        assert compute_sl_tp('BUY', 4100.0, cfg, atr=float('nan')) == (4085.0, 4145.0)

    def test_fibonacci_routes_when_both_swings_are_present(self):
        cfg = {'method': 'fibonacci', 'fibonacci_sl_level': 0.382,
               'fibonacci_tp_level': 1.618}
        assert compute_sl_tp('BUY', 4150.0, cfg, swing_high=4200.0, swing_low=4100.0) == \
               pytest.approx(calculate_fibonacci_sl_tp('BUY', 4150.0, 4200.0, 4100.0))

    def test_fibonacci_falls_back_to_fixed_when_a_swing_is_missing(self):
        cfg = {'method': 'fibonacci', 'stop_loss_pips': 15, 'take_profit_pips': 45}
        assert compute_sl_tp('BUY', 4100.0, cfg, swing_high=4200.0, swing_low=None) == \
               (4085.0, 4145.0)
        assert compute_sl_tp('BUY', 4100.0, cfg, swing_high=None, swing_low=4100.0) == \
               (4085.0, 4145.0)

    def test_supertrend_routes_when_a_band_value_is_present(self):
        cfg = {'method': 'supertrend', 'risk_reward_ratio': 3.0}
        assert compute_sl_tp('BUY', 4100.0, cfg, supertrend_value=4085.0) == \
               (4085.0, 4145.0)

    def test_supertrend_falls_back_to_fixed_without_a_band(self):
        cfg = {'method': 'supertrend', 'stop_loss_pips': 15, 'take_profit_pips': 45}
        assert compute_sl_tp('BUY', 4100.0, cfg, supertrend_value=None) == \
               (4085.0, 4145.0)

    def test_an_unknown_method_falls_back_to_fixed_rather_than_raising(self):
        cfg = {'method': 'martingale', 'stop_loss_pips': 15, 'take_profit_pips': 45}
        assert compute_sl_tp('BUY', 4100.0, cfg) == (4085.0, 4145.0)

    def test_a_supertrend_band_is_ignored_while_the_method_is_fixed(self):
        """Indicator values are always passed in; only `method` decides."""
        cfg = {'method': 'fixed', 'stop_loss_pips': 15, 'take_profit_pips': 45}
        assert compute_sl_tp('BUY', 4100.0, cfg, atr=10.0, supertrend_value=4000.0,
                             swing_high=4200.0, swing_low=4100.0) == (4085.0, 4145.0)

    @pytest.mark.parametrize('method,kwargs', [
        ('fixed', {}),
        ('pct', {}),
        ('atr', {'atr': 10.0}),
        ('fibonacci', {'swing_high': 4200.0, 'swing_low': 4100.0}),
        ('supertrend', {'supertrend_value': 4085.0}),
    ])
    def test_every_method_puts_a_buy_stop_below_entry(self, method, kwargs):
        """
        The one invariant that holds across all five routes for a sane input.
        `supertrend` holds here only because the band is below entry — see
        TestSupertrend for the unguarded case.
        """
        sl, tp = compute_sl_tp('BUY', 4150.0, {'method': method}, **kwargs)
        assert sl < 4150.0 < tp

    @pytest.mark.parametrize('method,kwargs', [
        ('fixed', {}),
        ('pct', {}),
        ('atr', {'atr': 10.0}),
        ('fibonacci', {'swing_high': 4200.0, 'swing_low': 4100.0}),
        ('supertrend', {'supertrend_value': 4165.0}),
    ])
    def test_every_method_puts_a_sell_stop_above_entry(self, method, kwargs):
        sl, tp = compute_sl_tp('SELL', 4150.0, {'method': method}, **kwargs)
        assert sl > 4150.0 > tp
