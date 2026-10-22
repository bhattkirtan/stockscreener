#!/usr/bin/env python3
"""
Analyze live Capital.com trades since 4 June 2026, per instrument.
Uses /history/transactions (supports from/to) for P&L.
"""
import sys, collections, statistics
sys.path.insert(0, 'trading-bot-skills')
from dotenv import load_dotenv; load_dotenv('.env')
from clients.capital_api import CapitalAPIClient
from datetime import datetime

FROM = '2026-06-04T00:00:00'
TO   = '2026-07-30T00:00:00'

client = CapitalAPIClient(environment='demo')
client.create_session()

# transactions endpoint supports from/to but has a max window — chunk into ~7-day slices
from datetime import timedelta
def daterange_chunks(start, end, days=7):
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=days), end)
        yield cur, nxt
        cur = nxt

start_dt = datetime.fromisoformat(FROM)
end_dt   = datetime.fromisoformat(TO)
all_txns = []
seen = set()
for a, b in daterange_chunks(start_dt, end_dt, days=7):
    try:
        r = client._request('GET', '/api/v1/history/transactions', params={
            'from': a.strftime('%Y-%m-%dT%H:%M:%S'),
            'to':   b.strftime('%Y-%m-%dT%H:%M:%S'),
        })
        chunk = r.json().get('transactions', [])
    except Exception as e:
        print(f"  chunk {a.date()}..{b.date()} failed: {e}")
        chunk = []
    added = 0
    for t in chunk:
        key = (t.get('dateUtc'), t.get('reference'), t.get('size'), t.get('instrumentName'))
        if key in seen:
            continue
        seen.add(key)
        all_txns.append(t)
        added += 1
    print(f"  {a.date()}..{b.date()}: {len(chunk)} txns ({added} new)")

print(f"Total raw transactions: {len(all_txns)}")

# Inspect transaction types present
types = collections.Counter(t.get('transactionType') for t in all_txns)
print("Transaction types:", dict(types))
insts = collections.Counter(t.get('instrumentName') for t in all_txns)
print("Instruments:", dict(insts))
print()

trades = [t for t in all_txns if t.get('transactionType') == 'TRADE']
swaps  = [t for t in all_txns if t.get('transactionType') == 'SWAP']

# Group by instrument
by_inst = collections.defaultdict(list)
for t in trades:
    by_inst[t.get('instrumentName')].append(t)

def week_of(dt_str):
    d = datetime.fromisoformat(dt_str[:19])
    return d.isocalendar()[1]

print('=' * 90)
print(f"LIVE TRADE ANALYSIS  —  {FROM[:10]} to {TO[:10]}  (demo account)")
print('=' * 90)

grand_pnl = 0
grand_n = 0
summary_rows = []
for inst in sorted(by_inst, key=lambda k: sum(float(x['size']) for x in by_inst[k])):
    ts = sorted(by_inst[inst], key=lambda x: x['dateUtc'])
    pnls = [float(t['size']) for t in ts]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    total = sum(pnls)
    grand_pnl += total
    grand_n += len(pnls)
    wr = len(wins)/len(pnls)*100 if pnls else 0
    avg_w = statistics.mean(wins) if wins else 0
    avg_l = statistics.mean(losses) if losses else 0
    pf = sum(wins)/abs(sum(losses)) if losses else float('inf')
    summary_rows.append((inst, len(pnls), wr, total, avg_w, avg_l, pf, max(pnls), min(pnls)))

print(f"{'INSTR':<10}{'N':>5}{'Win%':>7}{'Total$':>11}{'AvgWin':>9}{'AvgLoss':>9}{'PF':>7}{'Best':>9}{'Worst':>9}")
print('-' * 90)
for inst, n, wr, total, aw, al, pf, best, worst in summary_rows:
    pfs = f"{pf:.2f}" if pf != float('inf') else 'inf'
    print(f"{inst:<10}{n:>5}{wr:>6.0f}%{total:>+11.2f}{aw:>+9.2f}{al:>+9.2f}{pfs:>7}{best:>+9.2f}{worst:>+9.2f}")
print('-' * 90)
print(f"{'TOTAL':<10}{grand_n:>5}{'':>7}{grand_pnl:>+11.2f}")
if swaps:
    swap_total = sum(float(t['size']) for t in swaps)
    print(f"Overnight swap fees: {swap_total:+.2f}")
print()

# Weekly breakdown per instrument
print('=' * 90)
print("WEEKLY P&L (ISO week)")
print('=' * 90)
weeks = sorted(set(week_of(t['dateUtc']) for t in trades))
header = f"{'INSTR':<10}" + "".join(f"W{w:>5}" for w in weeks) + f"{'Total':>9}"
print(header)
print('-' * len(header))
for inst in sorted(by_inst):
    row = f"{inst:<10}"
    tot = 0
    for w in weeks:
        wp = sum(float(t['size']) for t in by_inst[inst] if week_of(t['dateUtc']) == w)
        tot += wp
        row += f"{wp:>+6.0f}"
    row += f"{tot:>+9.0f}"
    print(row)
print()

# Streak / consecutive loss analysis per instrument
print('=' * 90)
print("LOSS STREAKS & DRAWDOWN (chronological)")
print('=' * 90)
for inst in sorted(by_inst):
    ts = sorted(by_inst[inst], key=lambda x: x['dateUtc'])
    pnls = [float(t['size']) for t in ts]
    # max consecutive losses
    max_streak = cur = 0
    for p in pnls:
        if p < 0:
            cur += 1
            max_streak = max(max_streak, cur)
        else:
            cur = 0
    # equity curve max drawdown
    eq = 0; peak = 0; mdd = 0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    print(f"{inst:<10} trades={len(pnls):>3}  max_consec_losses={max_streak:>2}  max_drawdown={mdd:>+8.2f}")
print()

# Dump full per-instrument trade list to CSV for reference
import csv as _csv
with open('trades_since_jun4.csv', 'w', newline='') as f:
    w = _csv.writer(f)
    w.writerow(['instrument', 'dateUtc', 'pnl', 'ref'])
    for t in sorted(trades, key=lambda x: x['dateUtc']):
        w.writerow([t.get('instrumentName'), t['dateUtc'][:19], t['size'], t.get('reference', '')])
print("Wrote trades_since_jun4.csv")
