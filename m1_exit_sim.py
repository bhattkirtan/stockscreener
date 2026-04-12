"""
M1 Exit Simulation
==================
For each actual live trade, walks M1 bars from entry to M5 exit and finds
when the M1 Supertrend first flips against the position.

Compares:
  A) Actual exit (M5 reverse signal / SL / TP)
  B) M1 Supertrend reversal exit

Shows which is better per trade and in aggregate.
"""
import sys, sqlite3
from datetime import datetime
import pandas as pd
import numpy as np

sys.path.insert(0, 'trading-bot-skills')
from dotenv import load_dotenv
load_dotenv('.env')
from clients.capital_api import CapitalAPIClient
from clients.sqlite_api import SQLiteAPIClient
from core.indicators import calculate_supertrend

# ── 1. Load M1 bars from SQLite ───────────────────────────────────────────────

db = SQLiteAPIClient()
m1_rows = db.query_candles('GOLD', 'M1', limit=None)
m1_df = pd.DataFrame(m1_rows)
m1_df['timestamp'] = pd.to_datetime(m1_df['timestamp'])
m1_df = m1_df.sort_values('timestamp').set_index('timestamp')
print(f"M1 bars: {len(m1_df):,}  |  {m1_df.index[0]} → {m1_df.index[-1]}")

# Pre-compute M1 Supertrend (ATR14 × 1.5, same as live bot's M5 config)
ST_PERIOD = 14
ST_MULT   = 1.5
st_vals, st_dir, _, _ = calculate_supertrend(m1_df, ST_PERIOD, ST_MULT)
m1_df['st_dir'] = st_dir   # +1 = bullish, -1 = bearish

# ── 2. Reconstruct actual live trades from Capital activity ───────────────────

client = CapitalAPIClient(environment='demo')
client.create_session()

resp = client._request('GET', '/api/v1/history/activity', params={
    'lastPeriod': 24 * 3600, 'detailed': 'true', 'filter': 'epic==GOLD'
})
activities = sorted(resp.json().get('activities', []), key=lambda x: x['dateUTC'])

resp2 = client._request('GET', '/api/v1/history/transactions', params={'lastPeriod': 24 * 3600})
txns = sorted(
    [t for t in resp2.json().get('transactions', [])
     if t.get('instrumentName') == 'GOLD' and t.get('transactionType') == 'TRADE'],
    key=lambda x: x['dateUtc']
)

pos_events = [a for a in activities if a['type'] == 'POSITION' and a['status'] == 'ACCEPTED']
open_registry = {}
actual_trades = []

for event in pos_events:
    deal  = event['dealId']
    ts    = datetime.fromisoformat(event['dateUTC'].split('.')[0])
    level = event['details'].get('level', 0)
    size  = event['details'].get('size', 10)
    direc = event['details'].get('direction', '?')
    sl    = event['details'].get('stopLevel', 0)
    tp    = event['details'].get('profitLevel', 0)

    if deal in open_registry:
        opened = open_registry.pop(deal)
        actual_trades.append({
            'entry_time':  opened['entry_time'],
            'exit_time':   ts,
            'side':        opened['direction'],
            'entry_price': opened['entry_price'],
            'exit_price':  level,
            'sl':          opened['sl'],
            'tp':          opened['tp'],
            'size':        size,
            'pnl':         None,
        })
    else:
        open_registry[deal] = {
            'entry_time':  ts, 'direction': direc,
            'entry_price': level, 'sl': sl, 'tp': tp,
        }

actual_trades.sort(key=lambda x: x['entry_time'])

used_txn = set()
for trade in actual_trades:
    for i, tx in enumerate(txns):
        if i in used_txn: continue
        tx_t = datetime.fromisoformat(tx['dateUtc'].split('.')[0])
        if abs((tx_t - trade['exit_time']).total_seconds()) <= 90:
            trade['pnl'] = float(tx['size'])
            used_txn.add(i)
            break

# ── 3. For each trade, find M1 Supertrend reversal ────────────────────────────

def find_m1_reversal(entry_time, exit_time, side):
    """
    Scan M1 bars between entry and exit.
    Returns (first_reversal_bar, reversal_price) or (None, None).
    Reversal: M1 ST direction flips against the position direction.
    """
    window = m1_df.loc[entry_time:exit_time]
    if window.empty:
        return None, None

    wanted_dir = 1 if side == 'BUY' else -1   # direction that CONFIRMS position
    reversed_dir = -1 if side == 'BUY' else 1  # direction that signals EXIT

    # Skip the entry bar (first M1 bar) — direction may be stale
    bars = window.iloc[1:]
    for ts, row in bars.iterrows():
        if row['st_dir'] == reversed_dir:
            return ts, row['close']
    return None, None

def sim_pnl(side, entry_price, exit_price, size=10):
    pts = (exit_price - entry_price) if side == 'BUY' else (entry_price - exit_price)
    return round(pts * size, 2)

# ── 4. Print comparison ───────────────────────────────────────────────────────

print()
print('=' * 120)
print('M1 EXIT SIMULATION — GOLD 24h')
print('M1 Supertrend(14×1.5) reversal vs actual exit')
print('=' * 120)
print(f"{'#':<3} {'ENTRY':>8} {'SIDE':<5} {'ACT_exit':>10} {'ACT_PnL':>9}"
      f" | {'M1_exit':>10} {'M1_price':>10} {'M1_PnL':>9}"
      f" | {'DIFF':>8}  VERDICT")
print('-' * 120)

total_actual = 0
total_m1     = 0
cases = []

for n, trade in enumerate(actual_trades, 1):
    if trade['pnl'] is None:
        continue

    act_pnl = trade['pnl']
    rev_bar, rev_price = find_m1_reversal(
        trade['entry_time'], trade['exit_time'], trade['side']
    )

    if rev_bar is not None:
        m1_pnl = sim_pnl(trade['side'], trade['entry_price'], rev_price)
        diff   = m1_pnl - act_pnl
        if act_pnl > 0 and m1_pnl > act_pnl:
            verdict = 'M1 BETTER (held longer)'
        elif act_pnl > 0 and m1_pnl < act_pnl:
            verdict = 'ACT BETTER (M1 cut profit)'
        elif act_pnl < 0 and abs(m1_pnl) < abs(act_pnl):
            verdict = 'M1 BETTER (cut loss earlier)'
        elif act_pnl < 0 and abs(m1_pnl) > abs(act_pnl):
            verdict = 'ACT BETTER (M1 exited worse)'
        else:
            verdict = 'SIMILAR'
        m1_exit_str  = rev_bar.strftime('%H:%M')
        m1_price_str = f"{rev_price:.2f}"
        m1_pnl_str   = f"{m1_pnl:>+9.2f}"
        diff_str     = f"{diff:>+8.2f}"
    else:
        m1_pnl   = act_pnl   # no reversal found → same exit
        diff     = 0
        verdict  = 'NO M1 REVERSAL (held to actual exit)'
        m1_exit_str  = trade['exit_time'].strftime('%H:%M')
        m1_price_str = f"{trade['exit_price']:.2f}"
        m1_pnl_str   = f"{act_pnl:>+9.2f}"
        diff_str     = f"{'0':>8}"

    total_actual += act_pnl
    total_m1     += m1_pnl
    cases.append({'act': act_pnl, 'm1': m1_pnl, 'diff': diff, 'verdict': verdict})

    print(f"{n:<3} {trade['entry_time'].strftime('%H:%M'):>8} {trade['side']:<5}"
          f" {trade['exit_time'].strftime('%H:%M'):>10} {act_pnl:>+9.2f}"
          f" | {m1_exit_str:>10} {m1_price_str:>10} {m1_pnl_str}"
          f" | {diff_str}  {verdict}")

print('-' * 120)
print(f"{'TOT':<3} {'':>8} {'':5} {'':>10} {total_actual:>+9.2f}"
      f" | {'':>10} {'':>10} {total_m1:>+9.2f}"
      f" | {total_m1 - total_actual:>+8.2f}")

# ── 5. Summary ────────────────────────────────────────────────────────────────

better_m1  = [c for c in cases if c['diff'] > 5]
better_act = [c for c in cases if c['diff'] < -5]
similar    = [c for c in cases if abs(c['diff']) <= 5]

print()
print('=' * 120)
print('SUMMARY')
print('=' * 120)
print(f"  M1 exit better    : {len(better_m1):>2} trades  PnL gain = {sum(c['diff'] for c in better_m1):>+8.2f}")
print(f"  Actual exit better: {len(better_act):>2} trades  PnL gain = {sum(abs(c['diff']) for c in better_act):>+8.2f} (lost vs M1)")
print(f"  Similar (±$5)     : {len(similar):>2} trades")
print()
print(f"  Total actual P&L  : {total_actual:>+9.2f}")
print(f"  Total M1 exit P&L : {total_m1:>+9.2f}  (Δ = {total_m1 - total_actual:>+.2f})")
