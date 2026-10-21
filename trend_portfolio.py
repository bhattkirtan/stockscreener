#!/usr/bin/env python3
"""
Daily-bar, multi-market, volatility-targeted trend portfolio.

This is the structure managed-futures funds actually run (Carver, "Systematic
Trading"; AQR "A Century of Evidence on Trend-Following"), rather than a
discrete entry/exit indicator:

  1. EWMAC forecasts — exponentially weighted MA crossover at several speeds,
     each divided by instrument volatility so the signal is comparable across
     markets, then capped. Position size is CONTINUOUS in the forecast: a weak
     trend gets a small position, not a coin-flip entry.
  2. Volatility targeting — each instrument is sized so its expected risk
     contribution is equal. Low-vol markets get bigger positions.
  3. Diversification — the edge per market is thin; breadth is the multiplier
     (Grinold: IR ~ IC * sqrt(breadth)).
  4. No stops. Exits happen because the forecast decays toward zero and the
     position is scaled down. Stops convert a continuous signal into a
     discrete bet and add turnover, which is what costs killed on M5.

Costs are charged on position CHANGES (spread per unit traded) using the same
per-instrument spread assumptions as the live configs.

Validation: reports in-sample / out-of-sample halves, per-instrument
contribution, and a buy-and-hold benchmark. Run with --help for options.
"""
import argparse
import math
import sqlite3
import sys

import numpy as np
import pandas as pd

DB = '/var/lib/docker/volumes/stockscreener_trading_data/_data/trading.db'

# Spread cost per unit (one way), from config/instruments/*.yaml.
# Charged on |position change| so a full round trip pays twice.
SPREAD = {
    'GOLD':   0.50,
    'SILVER': 0.10,
    'EURUSD': 0.00007,
    'US100':  1.80,
    'ETHUSD': 1.75,
    'BTCUSD': 50.0,
}

# EWMAC speed pairs (fast, slow) in days. Slower pairs survived the post-2009
# break; the 2-8 day pair is included only to show it is the one that fails.
EWMAC_PAIRS = [(8, 32), (16, 64), (32, 128), (64, 256)]

FORECAST_CAP = 20.0        # Carver convention
FORECAST_TARGET = 10.0     # average absolute forecast, used to rescale
ANNUAL_DAYS = 256


def load_daily(epic: str) -> pd.DataFrame:
    con = sqlite3.connect(DB)
    df = pd.read_sql(
        "SELECT timestamp, open, high, low, close FROM candles "
        "WHERE epic=? AND timeframe='M5' ORDER BY timestamp",
        con, params=(epic,),
    )
    con.close()
    if df.empty:
        return df
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    daily = df.set_index('timestamp').resample('1D').agg(
        {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}
    ).dropna()
    return daily


def ewmac_forecast(price: pd.Series, fast: int, slow: int, vol: pd.Series) -> pd.Series:
    """Raw crossover divided by price volatility -> scale-free, then capped."""
    raw = price.ewm(span=fast, min_periods=fast).mean() - price.ewm(span=slow, min_periods=slow).mean()
    # vol is daily price stdev; the crossover of an N-day EWMA scales with it
    scaled = raw / vol.replace(0, np.nan)
    # Normalise so the average |forecast| is ~FORECAST_TARGET, then cap.
    norm = scaled.abs().expanding(min_periods=slow).mean()
    f = scaled * (FORECAST_TARGET / norm.replace(0, np.nan))
    return f.clip(-FORECAST_CAP, FORECAST_CAP)


def load_universe(path='universe.json'):
    """
    Load a dynamically selected universe (see universe.py): the chosen epics,
    their cached daily closes, and their MEASURED spreads from the live
    snapshot — so costs come from the broker rather than hand-written guesses.
    """
    import json
    epics = json.load(open(path))['epics']
    px = pd.read_pickle('/tmp/universe_hist.pkl')
    screen = pd.read_json('/tmp/universe_screen.json').set_index('epic')
    spreads = {e: float(screen.loc[e, 'spread']) for e in epics if e in screen.index}
    cols = [e for e in epics if e in px.columns]
    return px[cols].ffill(), spreads


def build(epics, capital, target_vol, pairs, start=None,
          price_df=None, spreads=None):
    prices, fx_vol, forecasts = {}, {}, {}
    for e in epics:
        if price_df is not None:
            if e not in price_df.columns:
                continue
            px = price_df[e].dropna()
        else:
            d = load_daily(e)
            if d.empty or len(d) < 300:
                print(f"  skip {e}: only {len(d)} daily bars", file=sys.stderr)
                continue
            px = d['close']
        if len(px) < 300:
            print(f"  skip {e}: only {len(px)} daily bars", file=sys.stderr)
            continue
        if start:
            px = px[px.index >= start]
        ret = px.diff()
        # Daily price volatility (EWMA, 32-day span), floored to avoid blowups
        vol = ret.ewm(span=32, min_periods=32).std()
        vol = vol.clip(lower=px.abs() * 1e-5)
        prices[e] = px
        fx_vol[e] = vol
        fcs = [ewmac_forecast(px, f, s, vol) for f, s in pairs]
        # Equal-weight the speeds, then rescale to the forecast target
        combined = pd.concat(fcs, axis=1).mean(axis=1)
        cnorm = combined.abs().expanding(min_periods=260).mean()
        combined = (combined * (FORECAST_TARGET / cnorm.replace(0, np.nan))).clip(
            -FORECAST_CAP, FORECAST_CAP)
        forecasts[e] = combined
    if not prices:
        raise SystemExit("no instruments loaded")

    px = pd.DataFrame(prices).ffill()
    vol = pd.DataFrame(fx_vol).reindex(px.index).ffill()
    fc = pd.DataFrame(forecasts).reindex(px.index).ffill()

    n = fc.shape[1]
    # Per-instrument daily cash-vol target: split the portfolio risk budget
    # equally. sqrt(n) credits diversification (assumes modest correlation).
    daily_target = capital * target_vol / np.sqrt(ANNUAL_DAYS)
    per_instrument = daily_target / np.sqrt(n) * np.sqrt(n) / n  # = daily_target/n
    # units such that forecast=10 gives the full per-instrument risk budget
    units = (fc / FORECAST_TARGET) * (per_instrument / vol)
    units = units.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    # Trade at next day's open-equivalent: shift positions by 1 day
    pos = units.shift(1).fillna(0.0)
    pnl_gross = (pos * px.diff()).fillna(0.0)
    turnover = pos.diff().abs().fillna(0.0)
    sp = spreads if spreads is not None else SPREAD
    missing = [e for e in pos.columns if e not in sp]
    if missing:
        print(f"  ! no spread for {missing} — costs understated", file=sys.stderr)
    cost = pd.DataFrame(
        {e: turnover[e] * sp.get(e, 0.0) for e in pos.columns}, index=pos.index)
    pnl_net = pnl_gross - cost
    return dict(px=px, fc=fc, pos=pos, gross=pnl_gross, cost=cost, net=pnl_net)


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via erf — avoids a scipy dependency."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """
    Inverse standard normal CDF (Acklam's rational approximation,
    |error| < 1.15e-9). Used for the expected-maximum-Sharpe term.
    """
    if not 0.0 < p < 1.0:
        return float('nan')
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def deflated_sharpe(observed_sr: float, n_trials: int, n_obs: int,
                    skew: float = 0.0, kurt: float = 3.0) -> float:
    """
    Deflated Sharpe Ratio (Bailey & Lopez de Prado).

    When N variants are tried and the best is kept, the maximum Sharpe is
    inflated even if every candidate is pure noise.  This returns the
    probability that the observed Sharpe is genuinely > 0 after correcting for
    the number of trials, the sample length, and non-normality.

    Interpretation: < 0.95 means the result is NOT distinguishable from the
    best-of-N fluke at conventional confidence.
    """
    if n_trials < 1 or n_obs < 2:
        return float('nan')
    # Expected maximum Sharpe of n_trials independent noise strategies
    e = 0.5772156649  # Euler-Mascheroni
    if n_trials > 1:
        sr0 = ((1 - e) * _norm_ppf(1 - 1.0 / n_trials)
               + e * _norm_ppf(1 - 1.0 / (n_trials * np.e)))
    else:
        sr0 = 0.0
    # Standard error of the Sharpe estimate, adjusted for skew/kurtosis
    se = np.sqrt((1 - skew * observed_sr
                  + (kurt - 1) / 4.0 * observed_sr ** 2) / (n_obs - 1))
    if se <= 0:
        return float('nan')
    return float(_norm_cdf((observed_sr - sr0) / se))


def kelly_fraction(sharpe_annual: float, fraction: float = 0.5) -> float:
    """
    Fractional-Kelly volatility target.

    Kelly leverage for a continuous strategy is Sharpe/vol, so targeting a
    volatility equal to `fraction * Sharpe` holds the position at that fraction
    of full Kelly.  Professionals use half-Kelly or less: half Kelly keeps ~75%
    of the growth for half the volatility, and cuts the probability of ever
    halving capital to roughly 12.5% (vs ~0.8% at quarter Kelly).

    A non-positive Sharpe gives a non-positive target — the formal statement of
    "this strategy does not justify any capital".
    """
    return max(0.0, fraction * sharpe_annual)


def stats(series: pd.Series, capital: float, label: str) -> dict:
    s = series.dropna()
    if s.empty:
        return {}
    ann = s.mean() * ANNUAL_DAYS
    vol = s.std() * np.sqrt(ANNUAL_DAYS)
    eq = s.cumsum()
    dd = (eq - eq.cummax()).min()
    wins = s[s > 0]
    losses = s[s < 0]
    return dict(
        run=label,
        ann_pnl=round(ann),
        ann_ret_pct=round(ann / capital * 100, 1),
        sharpe=round(ann / vol, 2) if vol else None,
        maxDD=round(dd),
        maxDD_pct=round(abs(dd) / capital * 100, 1),
        PF=round(wins.sum() / -losses.sum(), 3) if len(losses) else None,
        pct_days_up=round(len(wins) / len(s) * 100, 1),
        total=round(s.sum()),
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--capital', type=float, default=10000.0)
    ap.add_argument('--target-vol', type=float, default=0.20,
                    help='annualised portfolio volatility target (0.20 = 20%%)')
    ap.add_argument('--epics', default='GOLD,SILVER,EURUSD,US100,ETHUSD,BTCUSD')
    ap.add_argument('--universe', default=None,
                    help='path to universe.json from universe.py (uses its cached '
                         'daily history and MEASURED spreads instead of the local DB)')
    ap.add_argument('--trials', type=int, default=1, help='number of configurations tried, for the Deflated Sharpe correction')
    ap.add_argument('--fast-only', action='store_true',
                    help='use only the 8/32 pair (the speed the research says is dead)')
    args = ap.parse_args()

    epics = [e.strip().upper() for e in args.epics.split(',') if e.strip()]
    pairs = [(8, 32)] if args.fast_only else EWMAC_PAIRS

    price_df = spreads = None
    if args.universe:
        price_df, spreads = load_universe(args.universe)
        epics = list(price_df.columns)
        print(f"universe: {len(epics)} epics from {args.universe}")
    r = build(epics, args.capital, args.target_vol, pairs,
              price_df=price_df, spreads=spreads)
    net, gross, cost = r['net'], r['gross'], r['cost']
    port = net.sum(axis=1)
    pd.set_option('display.width', 250)

    print(f"\nDaily EWMAC trend portfolio — {', '.join(net.columns)}")
    print(f"speeds={pairs}  capital=${args.capital:,.0f}  vol target={args.target_vol:.0%}")
    print(f"period {port.index.min().date()} .. {port.index.max().date()}  ({len(port)} days)\n")

    rows = [stats(port, args.capital, 'PORTFOLIO net')]
    rows.append(stats(gross.sum(axis=1), args.capital, 'PORTFOLIO gross (pre-cost)'))
    mid = port.index[len(port) // 2]
    rows.append(stats(port[port.index < mid], args.capital, '  in-sample (1st half)'))
    rows.append(stats(port[port.index >= mid], args.capital, '  out-of-sample (2nd half)'))
    print(pd.DataFrame([x for x in rows if x]).to_string(index=False))

    print("\nPer-instrument (net):")
    per = pd.DataFrame([stats(net[c], args.capital, c) for c in net.columns])
    print(per.to_string(index=False))

    # ── Benchmark: always-long, same vol targeting, NO costs ────────────────
    # Without this the trend result is uninterpretable. If a timing overlay
    # cannot beat simply holding the same risk, the overlay is destroying value.
    px_b, vol_b = r['px'], None
    bh = None
    for e in net.columns:
        ret = px_b[e].diff()
        v = ret.ewm(span=32, min_periods=32).std().clip(lower=px_b[e].abs() * 1e-5)
        per = args.capital * args.target_vol / np.sqrt(ANNUAL_DAYS) / len(net.columns)
        s = (per / v).shift(1) * ret
        bh = s if bh is None else bh.add(s, fill_value=0)
    bh = bh.dropna()
    brows = [stats(bh, args.capital, 'BENCHMARK buy&hold (vol-targeted)')]
    bmid = bh.index[len(bh) // 2]
    brows.append(stats(bh[bh.index < bmid], args.capital, '  in-sample (1st half)'))
    brows.append(stats(bh[bh.index >= bmid], args.capital, '  out-of-sample (2nd half)'))
    print("\n" + pd.DataFrame([x for x in brows if x]).to_string(index=False))

    tc, tg = cost.sum().sum(), gross.sum().sum()
    print(f"\ncosts ${tc:,.0f} vs gross ${tg:,.0f}"
          f"  -> cost is {abs(tc/tg)*100:.1f}% of gross" if tg else "")
    ann_turn = r['pos'].diff().abs().sum().sum() / (len(port) / ANNUAL_DAYS)
    print(f"annual turnover {ann_turn:,.0f} units  "
          f"(daily rebalance, no stops)")

    # ── Trial-corrected significance + Kelly sizing ─────────────────────────
    sr = (port.mean() * ANNUAL_DAYS) / (port.std() * np.sqrt(ANNUAL_DAYS))
    dsr = deflated_sharpe(sr, n_trials=args.trials, n_obs=len(port),
                          skew=float(port.skew()), kurt=float(port.kurtosis() + 3.0))
    print(f"\nSharpe {sr:.2f} over {len(port)} days; "
          f"Deflated Sharpe (n_trials={args.trials}) = {dsr:.3f}")
    print("  DSR < 0.95 => not distinguishable from the best-of-N fluke."
          if not (dsr >= 0.95) else "  DSR >= 0.95 => survives the trial-count correction.")
    half = kelly_fraction(sr, 0.5)
    print(f"half-Kelly vol target implied by this Sharpe: {half:.0%}"
          f"  (you ran {args.target_vol:.0%})")
    if half <= 0:
        print("  -> non-positive Sharpe: Kelly says allocate nothing.")
    elif args.target_vol > half:
        print(f"  -> {args.target_vol:.0%} is ABOVE half-Kelly; over-levered for this edge.")


if __name__ == '__main__':
    main()
