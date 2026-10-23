"""Score runs: net/gross PF, IS/OOS halves, daily Sharpe, buy-and-hold Sharpe, DSR."""
import sys, os, glob, sqlite3, math
import numpy as np, pandas as pd
from statistics import NormalDist
N01 = NormalDist()
S = os.path.dirname(os.path.abspath(__file__))
CAP = 10000.0

def pf(x):
    w = x[x > 0].sum(); l = -x[x < 0].sum()
    return round(w / l, 3) if l > 0 else None

_bh = {}
def bh_daily(epic, t0, t1):
    if epic not in _bh:
        c = sqlite3.connect(os.path.join(S, 'snap.db'))
        d = pd.read_sql("select timestamp, close from candles where epic=? and timeframe='M5'", c, params=(epic,))
        d['timestamp'] = pd.to_datetime(d.timestamp)
        _bh[epic] = d.set_index('timestamp').close.resample('1D').last().dropna()
    s = _bh[epic]
    return s[(s.index >= t0.normalize()) & (s.index <= t1)].pct_change().dropna()

def sharpe(r):  # annualised on trading days
    return float(r.mean() / r.std() * math.sqrt(252)) if r.std() > 0 else 0.0

def daily_returns(d, t0, t1):
    days = bh_daily(d.epic.iloc[0], t0, t1).index
    p = d.groupby(d.exit_time.dt.normalize()).pnl.sum().reindex(days, fill_value=0.0)
    return p / CAP

def evaluate(path):
    f = os.path.join(path, 'trades.csv')
    d = pd.read_csv(f); d = d[d.status == 'CLOSED'].copy()
    d['epic'] = path.split('/')[-2]
    d['entry_time'] = pd.to_datetime(d.entry_time); d['exit_time'] = pd.to_datetime(d.exit_time)
    d = d.sort_values('entry_time')
    d['gross'] = d.pnl + d.spread_cost + d.slippage_cost
    mid = d.entry_time.min() + (d.entry_time.max() - d.entry_time.min()) / 2
    IS, OOS = d[d.entry_time < mid], d[d.entry_time >= mid]
    t0, t1 = d.entry_time.min(), d.exit_time.max()
    r = daily_returns(d, t0, t1)
    bh = bh_daily(d.epic.iloc[0], t0, t1)
    cost = (d.spread_cost + d.slippage_cost)
    R = (d.entry_price - d.stop_loss).abs() * d['size']
    return dict(run=os.path.basename(path), n=len(d), WR=round((d.pnl > 0).mean() * 100, 2),
                PF=pf(d.pnl), grossPF=pf(d.gross), IS_PF=pf(IS.pnl), OOS_PF=pf(OOS.pnl),
                pnl=round(d.pnl.sum()), cost_pctR=round((cost / R).median() * 100, 2),
                SR=round(sharpe(r), 3), BH_SR=round(sharpe(bh), 3),
                stable=bool((pf(IS.pnl) or 0) > 1 and (pf(OOS.pnl) or 0) > 1),
                _r=r)

def dsr(sr_ann, r, n_trials, sr_trials_ann):
    """Deflated Sharpe (Bailey & Lopez de Prado), on daily units."""
    T = len(r); sr = sr_ann / math.sqrt(252)
    var = np.var(np.array(sr_trials_ann) / math.sqrt(252), ddof=1) if len(sr_trials_ann) > 1 else 0.0
    em = 0.5772156649
    sr0 = math.sqrt(var) * ((1 - em) * N01.inv_cdf(1 - 1 / n_trials) + em * N01.inv_cdf(1 - 1 / (n_trials * math.e))) if n_trials > 1 else 0.0
    g3, g4 = float(r.skew()), float(r.kurt()) + 3
    z = (sr - sr0) * math.sqrt(T - 1) / math.sqrt(1 - g3 * sr + (g4 - 1) / 4 * sr ** 2)
    return round(float(N01.cdf(z)), 3)

if __name__ == '__main__':
    rows = [evaluate(p) for p in sorted(glob.glob(os.path.join(S, 'res', '*', '*'))) if os.path.exists(os.path.join(p, 'trades.csv'))]
    n = len(rows); srs = [x['SR'] for x in rows]
    for x in rows:
        x['DSR'] = dsr(x['SR'], x.pop('_r'), n, srs)
    df = pd.DataFrame(rows)
    pd.set_option('display.width', 250); pd.set_option('display.max_rows', 500)
    print(f"trials scored: {n}")
    print(df.to_string(index=False))
