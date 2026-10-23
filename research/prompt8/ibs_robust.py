import sys, os, math, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import daily_fam as D
data = D.load()
def ibs_t(t):
    return lambda x: (((x.c - x.l) / (x.h - x.l).replace(0, np.nan)) < t).astype(float)
print("threshold neighbours (net SR / PF):")
for e in ['US100', 'US500', 'DE40', 'GOLD']:
    row = []
    for t in [0.1, 0.15, 0.2, 0.25, 0.3]:
        r, g, pos, _ = D.run(data[e], ibs_t(t)(data[e])); pf, n = D.trades_pf(r, pos.reindex(r.index))
        row.append(f"{t}: {D.sr(r):.2f}/{pf}")
    print(f"  {e:6s}", "  ".join(row))
print("\ncost x3 (spread*4.5, funding x1.5) and 5-year blocks, IBS<0.2:")
for e in ['US100', 'US500', 'DE40']:
    x = data[e]; r, g, pos, ent = D.run(x, D.sig_ibs(x))
    extra = ent.reindex(r.index) * ((x.ca - x.c).reindex(r.index).clip(lower=0) * 3 / x.o.reindex(r.index))
    fund = pd.Series(x.index.year.map(lambda y: (D.FF.get(y, 4) + 2.5) / 100 / 365), x.index).reindex(r.index)
    r3 = r - extra - pos.reindex(r.index) * fund * 0.5
    bh = (x.o.shift(-1) / x.o - 1).dropna()
    blocks = {f"{y}-{y+4}": (round(D.sr(r[(r.index.year >= y) & (r.index.year <= y + 4)]), 2),
                             round(D.sr(bh[(bh.index.year >= y) & (bh.index.year <= y + 4)]), 2)) for y in range(2000, 2026, 5)}
    print(f"  {e}: SR {D.sr(r):.3f}  costx3 SR {D.sr(r3):.3f}   blocks (IBS, B&H): {blocks}")
    print(f"        2024-01..2026-10 SR {D.sr(r['2024':]):.2f} vs B&H {D.sr(bh['2024':]):.2f}")
