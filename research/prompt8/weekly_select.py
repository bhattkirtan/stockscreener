"""Prompt 8 items 2+3: walk-forward instrument selection on the weekly trend book — see select_prereg.md."""
import os, sys
import numpy as np, pandas as pd
S = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(S, '..', '..'))
import trend_portfolio as T

T.ANNUAL_DAYS = 52
PAIRS = [(2, 8), (4, 16), (8, 32), (16, 64)]
CAP, VOL, LEV = 10000.0, 0.20, 3.0
SPLIT, B_START = pd.Timestamp('2016-01-01'), pd.Timestamp('2005-05-09')
N_PRIOR = 66
RULES = {'S1': ('thresh', 0.10), 'S2': ('top', 13)}
BASELINE = ['DE40', 'US100', 'HEATINGOIL', 'USDMXN', 'HK50', 'AUDMXN', 'J225', 'AUDJPY',
            'AUDNZD', 'COPPER', 'USCOCOA', 'ETHUSD', 'GOLD']

def load():
    px = pd.read_pickle(os.path.join(S, 'weekly_cache', 'weekly_hist.pkl'))
    scr = pd.read_json(os.path.join(S, 'weekly_cache', 'universe_screen.json')).set_index('epic')
    pool = [e for e in scr.sort_values('friction').index if e in px.columns and px[e].notna().sum() >= 500]
    return px[pool].ffill(), {e: float(scr.loc[e, 'spread']) for e in pool}

def sr(s):
    s = s.dropna()
    return float(s.mean() / s.std() * np.sqrt(52)) if len(s) > 2 and s.std() > 0 else float('nan')

def pf(s):
    l = -s[s < 0].sum()
    return float(s[s > 0].sum() / l) if l > 0 else float('nan')

def book(px, sp, names, vol=VOL):
    return T.build(names, CAP, vol, PAIRS, price_df=px[names], spreads=sp, max_leverage=LEV)

def bh(px, names, vol=VOL):
    """Vol-targeted always-long, same leverage cap, no costs — trend_portfolio's benchmark."""
    p = px[names]
    v = p.diff().ewm(span=32, min_periods=32).std().clip(lower=p.abs() * 0.001)
    u = (CAP * vol / np.sqrt(52) / len(names) / v).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    sc = (CAP * LEV / (u.abs() * p).sum(axis=1).replace(0, np.nan)).clip(upper=1.0).fillna(1.0)
    return (u.mul(sc, axis=0).shift(1) * p.diff()).sum(axis=1)

def win(s, a, b):
    return s[(s.index >= a) & (s.index < b)]

def score(px, sp, names, a, b, label):
    if not names:
        return dict(book=label, n=0, SR=float('nan'), PF=float('nan'))
    bk = book(px, sp, names)
    r = bk['net'].sum(axis=1)
    t, g = win(r, a, b), win(bh(px, names), a, b)
    return dict(book=label, n=len(names), SR=round(sr(t), 3), G_SR=round(sr(win(bk['gross'].sum(axis=1), a, b)), 3),
                PF=round(pf(t), 3),
                ann_ret=round(t.mean() * 52 / CAP * 100, 2), BH_SR=round(sr(g), 3), _r=t)

def main():
    px, sp = load()
    full = book(px, sp, list(px.columns))
    end = px.index[-1] + pd.Timedelta(days=1)
    folds = {'A': ((px.index[0], SPLIT), (SPLIT, end)), 'B': ((SPLIT, end), (B_START, SPLIT))}
    print(f"pool {len(px.columns)} names, {px.index[0].date()} .. {px.index[-1].date()}")
    out, res = [], {}
    for f, ((sa, sb), (ta, tb)) in folds.items():
        net, pos = win(full['net'], sa, sb), win(full['pos'], sa, sb)
        live = px.loc[px.index >= ta].iloc[0].notna()
        elig = [e for e in px.columns if (pos[e] != 0).sum() >= 104 and live[e]]
        isr = pd.Series({e: sr(net[e]) for e in elig}).sort_values(ascending=False)
        print(f"\nfold {f}: select {sa.date()}..{sb.date()}  test {ta.date()}..{tb.date()}  eligible {len(elig)}")
        print(f"  top 15 selection-window SR: " + ', '.join(f"{e} {v:.2f}" for e, v in isr.head(15).items()))
        out += [score(px, sp, elig, ta, tb, f'{f} all-eligible'),
                score(px, sp, [e for e in BASELINE if e in elig], ta, tb, f'{f} baseline-13 (friction)')]
        for rid, (kind, v) in RULES.items():
            sel = list(isr[isr > v].index) if kind == 'thresh' else list(isr.head(v).index)
            rej = [e for e in elig if e not in sel]
            print(f"  {rid} keeps {len(sel)}: {', '.join(sel)}")
            s, j = score(px, sp, sel, ta, tb, f'{f} {rid} selected'), score(px, sp, rej, ta, tb, f'{f} {rid} rejected')
            out += [s, j]; res[(f, rid)] = (s, j)
    n = N_PRIOR + len(RULES)
    df = pd.DataFrame([{k: v for k, v in x.items() if k != '_r'} for x in out])
    pd.set_option('display.width', 250)
    print(f"\ntest-window scores (net; BH_SR = vol-targeted buy&hold on the same names)\n")
    print(df.to_string(index=False))
    print(f"\nverdict (trials this pass {len(RULES)}, running total {n}):")
    for rid in RULES:
        (sa_, ja), (sb_, jb) = res[('A', rid)], res[('B', rid)]
        r = sa_['_r']; spo = r.mean() / r.std()
        d = T.deflated_sharpe(spo, n, len(r), float(r.skew()), float(r.kurtosis() + 3))
        t1 = sa_['PF'] > 1 and sb_['PF'] > 1
        t2 = sa_['SR'] > ja['SR'] and sb_['SR'] > jb['SR']
        t3 = d >= 0.95
        t4 = sa_['SR'] > sa_['BH_SR']
        if jb['n'] == 0:
            print(f"  ({rid}: fold B is degenerate — {sb_['n']} eligible names, none rejected; tests 1-2 cannot pass. See prereg addendum.)")
        print(f"  {rid}: halves PF A {sa_['PF']} / B {sb_['PF']}:{t1}  transfer sel>rej A {sa_['SR']}>{ja['SR']}"
              f" B {sb_['SR']}>{jb['SR']}:{t2}  DSR {d:.3f}:{t3}  B&H A {sa_['SR']}>{sa_['BH_SR']}:{t4}"
              f"  -> {'PASS' if t1 and t2 and t3 and t4 else 'fail'}")

    print("\nitem 3 — baseline 13, vol target 20% vs 15% (full period, net):")
    for v in (0.20, 0.15):
        r = book(px, sp, BASELINE, vol=v)['net'].sum(axis=1)
        r = r[r.index >= r.ne(0).idxmax()]
        eq = r.cumsum()
        print(f"  {v:.0%}: SR {sr(r):.3f}  ann ret {r.mean()*52/CAP*100:.2f}%  maxDD {abs((eq-eq.cummax()).min())/CAP*100:.1f}%"
              f"  half-Kelly {T.kelly_fraction(sr(r)):.0%}")

if __name__ == '__main__':
    main()
