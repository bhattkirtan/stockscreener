"""Second signal family: pre-registered daily long-only rules, literature defaults, no tuning.

Decision at day-k close -> position held open(k+1) -> open(k+2). Costs: bid/ask spread
(+50% slippage) on every entry, overnight funding (fed funds approx + 2.5%/yr) per
calendar day held. Benchmark: buy-and-hold price return (no funding), same window.
"""
import math, os, sys
import numpy as np, pandas as pd
S = os.path.dirname(os.path.abspath(__file__))
FF = {2000: 6.2, 2001: 3.9, 2002: 1.7, 2003: 1.1, 2004: 1.4, 2005: 3.2, 2006: 5.0, 2007: 5.0, 2008: 1.9,
      2009: .15, 2010: .15, 2011: .1, 2012: .15, 2013: .1, 2014: .1, 2015: .15, 2016: .4, 2017: 1.0,
      2018: 1.8, 2019: 2.2, 2020: .4, 2021: .1, 2022: 1.7, 2023: 5.0, 2024: 5.1, 2025: 4.2, 2026: 3.8}
START = {'GOLD': '2008-01-01', 'SILVER': '2018-01-01'}  # earlier history has multi-day gaps

def rsi(c, n):
    d = c.diff(); up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)

def sig_rsi2(x):  # Connors: RSI(2)<10 above SMA200, exit close > SMA5
    r, s200, s5 = rsi(x.c, 2), x.c.rolling(200).mean(), x.c.rolling(5).mean()
    pos = np.zeros(len(x)); on = False
    for i in range(len(x)):
        if not on and r.iat[i] < 10 and x.c.iat[i] > s200.iat[i]: on = True
        elif on and x.c.iat[i] > s5.iat[i]: on = False
        pos[i] = on
    return pd.Series(pos, x.index)

def sig_ibs(x):  # IBS < 0.2 -> hold one day
    rng = (x.h - x.l).replace(0, np.nan)
    return (((x.c - x.l) / rng) < 0.2).astype(float)

def sig_tom(x):  # turn of month: last trading day + first 3 (calendar-known, no lookahead)
    idx = x.index; nxt = pd.Series(idx, idx).shift(-1)
    # decision at close k for the interval open(k+1)->open(k+2): hold if day k+1 is in window
    m = idx.to_period('M'); rank = pd.Series(1, idx).groupby(m).cumsum()
    d1 = pd.Series(idx, idx).shift(-1)
    in_first3 = rank.shift(-1) <= 3
    is_last = (d1.dt.to_period('M') != pd.Series(idx, idx).shift(-2).dt.to_period('M'))
    return (in_first3 | is_last).fillna(False).astype(float)

def sig_sma200(x):  # Faber-style trend reference
    return (x.c > x.c.rolling(200).mean()).astype(float)

FAMS = {'rsi2': sig_rsi2, 'ibs': sig_ibs, 'tom': sig_tom, 'sma200': sig_sma200}

def run(x, sig):
    o = x.o; pos = sig.shift(1).fillna(0)        # decided at prev close, held from this open
    ret_px = o.shift(-1) / o - 1                  # open(k) -> open(k+1)
    days = (pd.Series(x.index, x.index).shift(-1) - pd.Series(x.index, x.index)).dt.days
    spread = (x.ca - x.c).where(lambda s: s > 0).fillna((x.ca - x.c).median()) * 1.5
    entry = (pos.diff().fillna(pos) > 0).astype(float)
    fund = x.index.year.map(lambda y: (FF.get(y, 4.0) + 2.5) / 100 / 365)
    r = pos * ret_px - entry * spread / o - pos * days * np.asarray(fund)
    gross = pos * ret_px
    return r.dropna(), gross.dropna(), pos, entry

def sr(r): return float(r.mean() / r.std() * math.sqrt(252)) if r.std() > 0 else 0.0

def trades_pf(r, pos):
    tid = (pos.diff().fillna(pos) > 0).cumsum().where(pos > 0)
    t = r.groupby(tid).sum()
    w, l = t[t > 0].sum(), -t[t < 0].sum()
    return (round(w / l, 3) if l > 0 else None), len(t)

def evaluate(epic, x, fam):
    r, g, pos, _ = run(x, FAMS[fam](x))
    pos = pos.reindex(r.index)
    mid = r.index[0] + (r.index[-1] - r.index[0]) / 2
    pf, n = trades_pf(r, pos); gpf, _ = trades_pf(g.reindex(r.index), pos)
    ipf, _ = trades_pf(r[r.index < mid], pos[pos.index < mid]); opf, _ = trades_pf(r[r.index >= mid], pos[pos.index >= mid])
    bh = (x.o.shift(-1) / x.o - 1).dropna()
    return dict(epic=epic, fam=fam, yrs=round((r.index[-1] - r.index[0]).days / 365.25, 1), n=n,
                expo=round(pos.mean() * 100, 1), PF=pf, grossPF=gpf, IS_PF=ipf, OOS_PF=opf,
                CAGR=round(((1 + r).prod() ** (252 / len(r)) - 1) * 100, 2),
                SR=round(sr(r), 3), IS_SR=round(sr(r[r.index < mid]), 3), OOS_SR=round(sr(r[r.index >= mid]), 3),
                BH_SR=round(sr(bh), 3), stable=bool((ipf or 0) > 1 and (opf or 0) > 1), _r=r)

def load():
    d = pd.read_pickle(os.path.join(S, 'daily.pkl')); out = {}
    for e, x in d.items():
        x = x[(x.index >= START.get(e, '2000-01-01')) & (x.index.dayofweek < 5)]
        out[e] = x
    return out

if __name__ == '__main__':
    sys.path.insert(0, S); from ev import dsr
    data = load(); rows = [evaluate(e, x, f) for f in FAMS for e, x in data.items()]
    n_prior = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    n = len(rows) + n_prior; srs = [x['SR'] for x in rows]
    for x in rows: x['DSR'] = dsr(x['SR'], x.pop('_r'), n, srs)
    pd.set_option('display.width', 250)
    print(f"daily trials: {len(rows)}  (DSR deflated over {n} total trials)")
    print(pd.DataFrame(rows).to_string(index=False))
    pd.to_pickle(rows, os.path.join(S, 'daily_rows.pkl'))
