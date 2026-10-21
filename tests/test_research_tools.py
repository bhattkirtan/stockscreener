"""
Unit tests — research tooling (universe.py, trend_portfolio.py)

These pin the two defects that produced confidently wrong conclusions during
the 2026-10-21 research session, plus the invariants the sizing and validation
layers depend on.

Defect 1 — volatility targeting is NOT a risk control.
  Without a gross-notional cap, a collapsing volatility estimate makes implied
  position size explode. The first weekly run reported a 140% drawdown and
  Sharpe -0.14, which was an artifact of unbounded leverage, not a strategy
  result. After capping: Sharpe +0.30.

Defect 2 — the Deflated Sharpe expected-maximum term must be scaled by the
  estimator's standard error. Without that factor an un-annualised Sharpe is
  compared against a raw z-score and the result pins to 0.000 for any input,
  which silently destroys the trial-count correction. After fixing: 0.296.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from trend_portfolio import (  # noqa: E402
    FORECAST_CAP,
    _norm_cdf,
    _norm_ppf,
    build,
    deflated_sharpe,
    ewmac_forecast,
    kelly_fraction,
    stats,
)
from universe import friction_screen  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────
# Normal distribution helpers (scipy is not installed on this host)
# ──────────────────────────────────────────────────────────────────────────
class TestNormalHelpers:

    @pytest.mark.parametrize('x,expected', [
        (0.0, 0.5),
        (1.96, 0.975),
        (-1.96, 0.025),
        (2.576, 0.995),
    ])
    def test_cdf_known_values(self, x, expected):
        assert _norm_cdf(x) == pytest.approx(expected, abs=1e-3)

    @pytest.mark.parametrize('p', [0.01, 0.1, 0.5, 0.9, 0.975, 0.999])
    def test_ppf_inverts_cdf(self, p):
        assert _norm_cdf(_norm_ppf(p)) == pytest.approx(p, abs=1e-6)

    def test_ppf_rejects_out_of_range(self):
        assert np.isnan(_norm_ppf(0.0))
        assert np.isnan(_norm_ppf(1.0))


# ──────────────────────────────────────────────────────────────────────────
# Defect 2: Deflated Sharpe
# ──────────────────────────────────────────────────────────────────────────
class TestDeflatedSharpe:

    def test_does_not_pin_to_zero_for_a_strong_result(self):
        """
        The regression: omitting the standard-error factor on E[max] made DSR
        0.000 regardless of input. A strong per-bar Sharpe over a long sample
        must come back near 1.
        """
        dsr = deflated_sharpe(0.15, n_trials=10, n_obs=2000)
        assert dsr > 0.95, f"expected a significant result, got {dsr}"

    def test_more_trials_lowers_significance(self):
        """The whole point of the correction: best-of-N is inflated."""
        few = deflated_sharpe(0.05, n_trials=2, n_obs=1000)
        many = deflated_sharpe(0.05, n_trials=500, n_obs=1000)
        assert few > many

    def test_single_trial_has_no_deflation(self):
        """With one trial E[max] is 0, so DSR reduces to the plain t-test."""
        sr, n = 0.05, 1000
        var = 1 - 0.0 * sr + (3.0 - 1) / 4.0 * sr ** 2      # skew=0, kurt=3
        plain = _norm_cdf(sr / np.sqrt(var / (n - 1)))
        assert deflated_sharpe(sr, n_trials=1, n_obs=n) == pytest.approx(plain, abs=1e-6)

    def test_longer_sample_raises_significance(self):
        short = deflated_sharpe(0.05, n_trials=10, n_obs=200)
        long_ = deflated_sharpe(0.05, n_trials=10, n_obs=5000)
        assert long_ > short

    def test_negative_sharpe_is_insignificant(self):
        assert deflated_sharpe(-0.05, n_trials=10, n_obs=1000) < 0.5

    def test_degenerate_inputs_return_nan(self):
        assert np.isnan(deflated_sharpe(0.1, n_trials=10, n_obs=1))
        assert np.isnan(deflated_sharpe(0.1, n_trials=0, n_obs=100))


class TestKellyFraction:

    def test_half_kelly_is_half_the_sharpe(self):
        assert kelly_fraction(0.60, 0.5) == pytest.approx(0.30)

    def test_non_positive_sharpe_allocates_nothing(self):
        """The formal statement of 'this strategy does not justify capital'."""
        assert kelly_fraction(0.0, 0.5) == 0.0
        assert kelly_fraction(-0.4, 0.5) == 0.0

    def test_quarter_kelly_is_more_conservative(self):
        assert kelly_fraction(0.6, 0.25) < kelly_fraction(0.6, 0.5)


# ──────────────────────────────────────────────────────────────────────────
# Forecasts
# ──────────────────────────────────────────────────────────────────────────
def _trend_series(n=400, slope=1.0, start=100.0):
    idx = pd.date_range('2020-01-01', periods=n, freq='D')
    return pd.Series(start + slope * np.arange(n), index=idx)


class TestEwmacForecast:

    def _fc(self, px):
        vol = px.diff().ewm(span=32, min_periods=32).std().clip(lower=px.abs() * 0.001)
        return ewmac_forecast(px, 16, 64, vol)

    def test_never_exceeds_the_cap(self):
        """An uncapped forecast would size a position without bound."""
        f = self._fc(_trend_series(slope=5.0)).dropna()
        assert f.abs().max() <= FORECAST_CAP + 1e-9

    def test_positive_in_an_uptrend_negative_in_a_downtrend(self):
        up = self._fc(_trend_series(slope=1.0)).dropna()
        down = self._fc(_trend_series(slope=-1.0, start=600.0)).dropna()
        assert up.iloc[-1] > 0
        assert down.iloc[-1] < 0

    def test_is_scale_free(self):
        """
        Dividing by volatility is what makes forecasts comparable across
        markets. Scaling the price series must not change the forecast.
        """
        px = _trend_series(slope=1.0)
        a = self._fc(px).dropna()
        b = self._fc(px * 1000.0).dropna()
        common = a.index.intersection(b.index)
        assert np.allclose(a[common], b[common], atol=1e-6)


# ──────────────────────────────────────────────────────────────────────────
# Defect 1: leverage cap, and the no-look-ahead / cost invariants
# ──────────────────────────────────────────────────────────────────────────
def _price_frame(n=400):
    idx = pd.date_range('2020-01-01', periods=n, freq='D')
    rng = np.random.default_rng(7)
    out = {}
    for i, name in enumerate(['A', 'B', 'C']):
        steps = rng.normal(0.4, 2.0, n)
        out[name] = pd.Series(100.0 + (i + 1) * 10 + np.cumsum(steps), index=idx)
    return pd.DataFrame(out)


class TestLeverageCap:

    def _quiet_uptrend(self, n=400):
        """
        The condition that actually breaks naive vol targeting: very low
        volatility AND a persistent trend. The forecast saturates while 1/vol
        is enormous, so implied size explodes. A random walk never triggers it,
        which is why this needs constructing deliberately.
        """
        idx = pd.date_range('2020-01-01', periods=n, freq='D')
        rng = np.random.default_rng(3)
        steps = 0.05 + rng.normal(0.0, 0.002, n)     # strong drift, tiny noise
        return pd.DataFrame({'QUIET': 100.0 + np.cumsum(steps)}, index=idx)

    def test_uncapped_sizing_would_breach_leverage(self):
        """Precondition: without the cap this configuration IS over-levered."""
        px = self._quiet_uptrend()
        capital = 10_000.0
        r = build(['QUIET'], capital, 0.20, [(16, 64)],
                  price_df=px, spreads={'QUIET': 0.0}, max_leverage=1e9)
        notional = (r['pos'].abs() * r['px']).sum(axis=1)
        assert notional.max() > capital * 10, (
            "fixture no longer produces an over-levered book; "
            f"peak notional was {notional.max():.0f}")

    def test_cap_binds_on_a_quiet_trend(self):
        px = self._quiet_uptrend()
        capital, cap = 10_000.0, 3.0
        r = build(['QUIET'], capital, 0.20, [(16, 64)],
                  price_df=px, spreads={'QUIET': 0.0}, max_leverage=cap)
        notional = (r['pos'].abs() * r['px']).sum(axis=1)
        assert notional.max() <= capital * cap * 1.001

    def test_gross_notional_never_exceeds_the_cap(self):
        px = _price_frame()
        cap, capital = 3.0, 10_000.0
        r = build(list(px.columns), capital, 0.20, [(16, 64)],
                  price_df=px, spreads={c: 0.0 for c in px.columns},
                  max_leverage=cap)
        notional = (r['pos'].abs() * r['px']).sum(axis=1)
        assert notional.max() <= capital * cap * 1.001

    def test_a_collapsing_vol_estimate_cannot_explode_position_size(self):
        """
        The 140%-drawdown defect: a near-flat series gives a near-zero vol
        estimate, and `target / vol` then implies unbounded units.
        """
        idx = pd.date_range('2020-01-01', periods=400, freq='D')
        flat = pd.Series(100.0, index=idx)
        flat.iloc[-80:] = 100.0 + np.arange(80) * 0.01   # barely moves
        px = pd.DataFrame({'FLAT': flat, 'NORMAL': _price_frame()['A'].values},
                          index=idx)
        r = build(['FLAT', 'NORMAL'], 10_000.0, 0.20, [(16, 64)],
                  price_df=px, spreads={'FLAT': 0.0, 'NORMAL': 0.0},
                  max_leverage=3.0)
        assert np.isfinite(r['pos'].values).all()
        notional = (r['pos'].abs() * r['px']).sum(axis=1)
        assert notional.max() <= 10_000.0 * 3.0 * 1.001

    def test_tighter_cap_reduces_exposure(self):
        px = _price_frame()
        kw = dict(price_df=px, spreads={c: 0.0 for c in px.columns})
        loose = build(list(px.columns), 10_000.0, 0.20, [(16, 64)],
                      max_leverage=10.0, **kw)
        tight = build(list(px.columns), 10_000.0, 0.20, [(16, 64)],
                      max_leverage=0.5, **kw)
        n_loose = (loose['pos'].abs() * loose['px']).sum(axis=1).max()
        n_tight = (tight['pos'].abs() * tight['px']).sum(axis=1).max()
        assert n_tight < n_loose


class TestNoLookAhead:

    def test_positions_are_lagged(self):
        """
        P&L on bar t must use the position decided at t-1. If positions were
        applied on the same bar the backtest would be trading on information it
        could not have had.
        """
        px = _price_frame()
        r = build(list(px.columns), 10_000.0, 0.20, [(16, 64)],
                  price_df=px, spreads={c: 0.0 for c in px.columns})
        pos, gross = r['pos'], r['gross']
        # Reconstruct: gross[t] == pos[t] * (px[t] - px[t-1])
        expected = (pos * r['px'].diff()).fillna(0.0)
        assert np.allclose(gross.values, expected.values, atol=1e-9)
        # And pos must be a shifted series: the first bar cannot hold a position
        assert (pos.iloc[0] == 0).all()


class TestCosts:

    def test_zero_turnover_costs_nothing(self):
        px = _price_frame()
        r = build(list(px.columns), 10_000.0, 0.20, [(16, 64)],
                  price_df=px, spreads={c: 1.0 for c in px.columns})
        turnover = r['pos'].diff().abs().fillna(0.0)
        zero_rows = turnover.sum(axis=1) == 0
        assert (r['cost'][zero_rows].sum(axis=1) == 0).all()

    def test_cost_is_spread_times_turnover(self):
        px = _price_frame()
        spread = 0.25
        r = build(list(px.columns), 10_000.0, 0.20, [(16, 64)],
                  price_df=px, spreads={c: spread for c in px.columns})
        turnover = r['pos'].diff().abs().fillna(0.0)
        assert np.allclose(r['cost'].values, (turnover * spread).values, atol=1e-9)

    def test_wider_spread_costs_more(self):
        px = _price_frame()
        kw = dict(price_df=px)
        cheap = build(list(px.columns), 10_000.0, 0.20, [(16, 64)],
                      spreads={c: 0.01 for c in px.columns}, **kw)
        dear = build(list(px.columns), 10_000.0, 0.20, [(16, 64)],
                     spreads={c: 1.00 for c in px.columns}, **kw)
        assert dear['cost'].sum().sum() > cheap['cost'].sum().sum()
        assert dear['net'].sum().sum() < cheap['net'].sum().sum()


class TestStats:

    def test_profit_factor_and_drawdown(self):
        s = pd.Series([10.0, -5.0, 10.0, -5.0])
        out = stats(s, 1000.0, 'x')
        assert out['PF'] == pytest.approx(20.0 / 10.0)
        assert out['total'] == 10
        assert out['maxDD'] == -5          # worst peak-to-trough on cumsum

    def test_all_losses_gives_zero_profit_factor(self):
        assert stats(pd.Series([-1.0, -2.0]), 1000.0, 'x')['PF'] == 0.0

    def test_no_losses_leaves_profit_factor_undefined(self):
        assert stats(pd.Series([1.0, 2.0]), 1000.0, 'x')['PF'] is None

    def test_empty_series_is_handled(self):
        assert stats(pd.Series(dtype=float), 1000.0, 'x') == {}


# ──────────────────────────────────────────────────────────────────────────
# universe.py friction screen
# ──────────────────────────────────────────────────────────────────────────
def _market(epic='X', bid=100.0, offer=100.05, high=101.0, low=99.0,
            itype='INDICES', status='TRADEABLE', streaming=True):
    return {'epic': epic, 'instrumentName': epic, 'instrumentType': itype,
            'marketStatus': status, 'streamingPricesAvailable': streaming,
            'bid': bid, 'offer': offer, 'high': high, 'low': low,
            'tickSize': 0.1}


class TestFrictionScreen:

    def test_baseline_market_passes(self):
        """
        Guards the fixture itself: if the default market did not pass, every
        'rejects X' test below would pass vacuously instead of proving that the
        specific rule fired.
        """
        assert friction_screen([_market()]).epic.tolist() == ['X']

    def test_computes_friction_as_spread_over_range(self):
        m = _market(bid=100.0, offer=101.0, high=102.0, low=100.0)   # 1.0 / 2.0
        df = friction_screen([m], max_friction=0.6)
        assert df.iloc[0]['friction'] == pytest.approx(0.5)

    def test_rejects_untradeable_and_non_streaming(self):
        assert friction_screen([_market(status='CLOSED')]).empty
        assert friction_screen([_market(streaming=False)]).empty

    def test_excludes_single_name_equity(self):
        """SHARES is a different premium, and there are hundreds of them."""
        assert friction_screen([_market(itype='SHARES')]).empty

    def test_rejects_expensive_spreads(self):
        wide = _market(bid=100.0, offer=102.0, high=101.0, low=100.0)   # friction 2.0
        assert friction_screen([wide], max_friction=0.08).empty

    def test_upper_volatility_bound_excludes_meme_coins(self):
        """
        The screen defect: a micro-cap with a 25% daily range passes on
        spread/range purely BECAUSE it is wildly volatile. Those instruments
        are illiquid and gap-prone, and their vol estimate is useless for
        position sizing.
        """
        meme = _market(epic='MEWUSD', bid=1.0, offer=1.01, high=1.15, low=0.88,
                       itype='CRYPTOCURRENCIES')
        assert friction_screen([meme], max_range_pct=8.0).empty
        # ...and it WOULD have passed without the bound
        assert not friction_screen([meme], max_range_pct=100.0).empty

    def test_lower_volatility_bound_excludes_dead_markets(self):
        """Nothing to harvest in a market that does not move, however cheap."""
        dead = _market(bid=100.0, offer=100.001, high=100.05, low=100.0)
        assert friction_screen([dead]).empty

    def test_sorted_cheapest_first(self):
        a = _market(epic='A', bid=100.0, offer=100.01, high=102.0, low=100.0)  # 0.005
        b = _market(epic='B', bid=100.0, offer=100.10, high=102.0, low=100.0)  # 0.050
        df = friction_screen([b, a])
        assert list(df.epic) == ['A', 'B']

    def test_missing_fields_are_skipped_not_crashed(self):
        bad = _market()
        del bad['high']
        assert friction_screen([bad, _market(epic='OK')]).epic.tolist() == ['OK']
