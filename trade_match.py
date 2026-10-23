#!/usr/bin/env python3
"""
Trade-level live-vs-backtest match (CLAUDE.md gotchas 33, 60).

Pairs each live `trade_history` entry with the nearest unused backtest entry
within --tol minutes, then reports matched / same side / same outcome and
lists every unmatched trade on both sides. A summary-stat match (PF, WR) is
not evidence two runs are the same strategy — this is.

    python3 trade_match.py --bot gold_m5_bot --run results/GOLD/<run_id> \\
        --from 2026-10-23 --to 2026-12-31

--run is relative to the live volume (where container backtests write) unless
it is an absolute path. Live times are the bot's UTC clock; backtest times are
bar labels (next-bar open), which line up because the bot logs a bar at close.
Only meaningful on bid/UTC bars — re-base an instrument first (gotcha 57).
"""
import argparse
import json
import os
import sqlite3

import pandas as pd

VOLUME = '/var/lib/docker/volumes/stockscreener_trading_data/_data'


def load_live(db, bot, start, end):
    con = sqlite3.connect(db)
    rows = [json.loads(d) for (d,) in con.execute(
        "SELECT data FROM kv_store WHERE collection='trade_history'")]
    con.close()
    df = pd.DataFrame([r for r in rows if r.get('bot_id') == bot])
    if df.empty:
        return df
    df['t'] = pd.to_datetime(df.entry_time, format='mixed').dt.tz_localize(None)
    df = df[(df.t >= start) & (df.t < end)].sort_values('t').reset_index(drop=True)
    return df


def pf(pnl):
    loss = -pnl[pnl < 0].sum()
    return pnl[pnl > 0].sum() / loss if loss else float('nan')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--bot', required=True, help='trade_history bot_id, e.g. gold_m5_bot')
    ap.add_argument('--run', required=True, help='backtest results dir holding trades.csv')
    ap.add_argument('--from', dest='start', required=True)
    ap.add_argument('--to', dest='end', required=True, help='exclusive')
    ap.add_argument('--tol', type=float, default=10, help='match tolerance, minutes')
    ap.add_argument('--db', default=os.path.join(VOLUME, 'trading.db'))
    a = ap.parse_args()

    run = a.run if os.path.isabs(a.run) else os.path.join(VOLUME, a.run)
    B = pd.read_csv(os.path.join(run, 'trades.csv'), parse_dates=['entry_time', 'exit_time'])
    Bw = B[(B.entry_time >= a.start) & (B.entry_time < a.end)].reset_index(drop=True)
    L = load_live(a.db, a.bot, a.start, a.end)
    if L.empty:
        print(f'no live trades for {a.bot} in {a.start}..{a.end}')
        return

    tol = pd.Timedelta(minutes=a.tol)
    used, pairs = set(), []
    for i, r in L.iterrows():
        d = (Bw.entry_time - r.t).abs()
        d = d[~d.index.isin(used)]
        j = d.idxmin() if len(d) else None
        if j is not None and d[j] <= tol:
            used.add(j)
            pairs.append((i, j))

    same_side = [(i, j) for i, j in pairs if L.direction[i] == Bw.side[j]]
    same_out = [(i, j) for i, j in same_side if (L.pnl[i] > 0) == (Bw.pnl[j] > 0)]

    print(f'live     n={len(L):4d}  WR={(L.pnl > 0).mean():.2%}  PF={pf(L.pnl):.3f}  (P&L in account ccy)')
    print(f'backtest n={len(Bw):4d}  WR={(Bw.pnl > 0).mean():.2%}  PF={pf(Bw.pnl):.3f}')
    print(f'matched ±{a.tol:g}min {len(pairs)}/{len(L)}  same side {len(same_side)}  '
          f'same outcome {len(same_out)}  backtest-only {len(Bw) - len(used)}')

    matched = {i for i, _ in pairs}
    um = L[~L.index.isin(matched)]
    if len(um):
        print('\nlive-only (bt_open = backtest already held a position):')
        for _, r in um.iterrows():
            held = ((B.entry_time <= r.t) & (B.exit_time > r.t)).any()
            print(f'  {r.t}  {r.direction:4s}  pnl={r.pnl:8.2f}  bt_open={held}')
    bo = Bw[~Bw.index.isin(used)]
    if len(bo):
        print('\nbacktest-only:')
        for _, r in bo.iterrows():
            print(f'  {r.entry_time}  {r.side:4s}  {r.exit_reason:7s}  pnl={r.pnl:8.2f}')


if __name__ == '__main__':
    main()
