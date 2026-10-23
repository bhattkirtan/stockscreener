"""IBS overlay on a long index position — see overlay_prereg.md (written before this was run)."""
import math, os, sys
import numpy as np, pandas as pd
S = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, S)
import daily_fam as D
from ev import dsr

N_PRIOR = 54
VARIANTS = {'O1': (1.0, 0.5, False), 'O2': (1.0, 1.0, False), 'O3': (0.8, 0.8, False), 'O4': (1.0, 1.0, True)}
EPICS = ['US100', 'US500', 'DE40']

def legs(x, b, k, trend):
    s = D.sig_ibs(x)
    if trend: s = s * (x.c > x.c.rolling(200).mean()).astype(float)
    w = (b + k * s).shift(1).fillna(b)                       # decided at prev close, held from this open
    bh = x.o.shift(-1) / x.o - 1
    days = (pd.Series(x.index, x.index).shift(-1) - pd.Series(x.index, x.index)).dt.days
    rate = pd.Series(x.index.year.map(lambda y: (D.FF.get(y, 4.0) + 2.5) / 100 / 365), x.index)
    spread = (x.ca - x.c).where(lambda v: v > 0).fillna((x.ca - x.c).median()) * 1.5
    up = w.diff().clip(lower=0).fillna(0)
    r = w * bh - up * spread / x.o - (w - 1).clip(lower=0) * days * rate
    ok = bh.notna()
    return r[ok], bh[ok], (w - b)[ok], days[ok], rate[ok]

def vm_bh(r, bh, days, rate):
    lam = r.std() / bh.std()
    return lam * bh - max(lam - 1, 0) * days * rate, lam

def inc_pf(inc, extra):
    on = extra > 0
    tid = (on & ~on.shift(1, fill_value=False)).cumsum().where(on)
    t = inc.groupby(tid).sum(); w, l = t[t > 0].sum(), -t[t < 0].sum()
    return (round(w / l, 3) if l > 0 else None), len(t)

def evaluate(epic, x, vid):
    b, k, trend = VARIANTS[vid]
    r, bh, extra, days, rate = legs(x, b, k, trend)
    inc = r - b * bh
    mid = r.index[0] + (r.index[-1] - r.index[0]) / 2
    pf, n = inc_pf(inc, extra)
    ipf, _ = inc_pf(inc[r.index < mid], extra[r.index < mid]); opf, _ = inc_pf(inc[r.index >= mid], extra[r.index >= mid])
    vm, lam = vm_bh(r, bh, days, rate)
    p = r.index >= '2010-01-01'
    vm10, lam10 = vm_bh(r[p], bh[p], days[p], rate[p])
    act = r - vm
    return dict(epic=epic, var=vid, n=n, expo=round(float((b + extra).mean()), 3), incPF=pf, IS_PF=ipf, OOS_PF=opf,
                halves=bool((ipf or 0) > 1 and (opf or 0) > 1), lam=round(lam, 3),
                SR=round(D.sr(r), 3), VMBH_SR=round(D.sr(vm), 3), BH_SR=round(D.sr(bh), 3),
                ACT_SR=round(D.sr(act), 3),
                SR10=round(D.sr(r[p]), 3), VMBH_SR10=round(D.sr(vm10), 3),
                CAGR=round(((1 + r).prod() ** (252 / len(r)) - 1) * 100, 2),
                VMBH_CAGR=round(((1 + vm).prod() ** (252 / len(vm)) - 1) * 100, 2),
                MDD=round(float(((1 + r).cumprod() / (1 + r).cumprod().cummax() - 1).min() * 100), 1),
                VMBH_MDD=round(float(((1 + vm).cumprod() / (1 + vm).cumprod().cummax() - 1).min() * 100), 1),
                _act=act, _r=r)

if __name__ == '__main__':
    data = D.load()
    rows = [evaluate(e, data[e], v) for v in VARIANTS for e in EPICS]
    n = N_PRIOR + len(rows)
    srs = [x['SR'] for x in pd.read_pickle(os.path.join(S, 'daily_rows.pkl'))] + [x['ACT_SR'] for x in rows]
    for x in rows:
        x['DSR_act'] = dsr(x['ACT_SR'], x.pop('_act'), n, srs)
        x['DSR_raw'] = dsr(x['SR'], x.pop('_r'), n, srs)
    df = pd.DataFrame(rows)
    pd.set_option('display.width', 250)
    print(f"overlay trials: {len(rows)}  (running total {n})\n")
    print(df.to_string(index=False))
    print("\nverdict (US100 candidate, four tests):")
    for v in VARIANTS:
        g = df[df['var'] == v].set_index('epic')
        u = g.loc['US100']
        t1 = u.halves
        t2 = all(g.loc[e].halves and g.loc[e].SR > g.loc[e].VMBH_SR for e in ['US500', 'DE40'])
        t3 = u.DSR_act >= 0.95
        t4 = u.SR10 > u.VMBH_SR10
        print(f"  {v}: halves={t1}  transfer={t2}  DSR={u.DSR_act}>=0.95:{t3}  2010+ {u.SR10}>{u.VMBH_SR10}:{t4}"
              f"  -> {'PASS' if t1 and t2 and t3 and t4 else 'fail'}")
