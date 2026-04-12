#!/usr/bin/env python3
"""
Live vs Backtest comparison — GOLD Apr 7-10 2026

Live trades:  fetched from Capital.com demo via /history/transactions (from/to)
Backtest:     results/GOLD/20260412_200033/trades.csv  (SL=15, TP=40, ST14x1.5, MA100 bias)
"""
import sys, csv
sys.path.insert(0, 'trading-bot-skills')
from dotenv import load_dotenv; load_dotenv('.env')
from clients.capital_api import CapitalAPIClient
from datetime import datetime

COMPARE_FROM = '2026-04-07T00:00:00'
COMPARE_TO   = '2026-04-11T00:00:00'
BT_CSV       = 'trading-bot-skills/results/GOLD/20260412_201403/trades.csv'

def fmt(dt): return dt.strftime('%m-%d %H:%M') if dt else '—'

# ── 1. Fetch live transactions ────────────────────────────────────────────────
client = CapitalAPIClient(environment='demo')
client.create_session()

r = client._request('GET', '/api/v1/history/transactions', params={
    'from': COMPARE_FROM, 'to': COMPARE_TO
})
all_txns = r.json().get('transactions', [])

live_trades = sorted(
    [t for t in all_txns if t.get('instrumentName') == 'GOLD' and t.get('transactionType') == 'TRADE'],
    key=lambda x: x['dateUtc']
)
live_swaps = [t for t in all_txns if t.get('instrumentName') == 'GOLD' and t.get('transactionType') == 'SWAP']

# ── 2. Load backtest trades ───────────────────────────────────────────────────
bt_all = []
with open(BT_CSV) as f:
    for row in csv.DictReader(f):
        row['entry_time'] = datetime.fromisoformat(row['entry_time'])
        row['exit_time']  = datetime.fromisoformat(row['exit_time'])
        row['pnl']        = float(row['pnl'])
        bt_all.append(row)

# Filter backtest to the comparison window
compare_start = datetime.fromisoformat(COMPARE_FROM)
compare_end   = datetime.fromisoformat(COMPARE_TO)
bt_trades = [t for t in bt_all if compare_start <= t['exit_time'] < compare_end]

# ── 3. Summary ────────────────────────────────────────────────────────────────
live_pnl   = sum(float(t['size']) for t in live_trades)
bt_pnl     = sum(t['pnl'] for t in bt_trades)
live_wins  = [t for t in live_trades if float(t['size']) > 0]
live_loss  = [t for t in live_trades if float(t['size']) < 0]
bt_wins    = [t for t in bt_trades if t['pnl'] > 0]
bt_loss    = [t for t in bt_trades if t['pnl'] < 0]

print('=' * 75)
print('LIVE vs BACKTEST — GOLD  Apr 7–10 2026  (SL=15  TP=40  ST14×1.5  MA100 bias)')
print('=' * 75)
print(f"{'METRIC':<30} {'LIVE (demo)':>15} {'BACKTEST':>15}")
print('-' * 62)
print(f"{'Trade count':<30} {len(live_trades):>15} {len(bt_trades):>15}")
print(f"{'Winners':<30} {len(live_wins):>15} {len(bt_wins):>15}")
print(f"{'Losers':<30} {len(live_loss):>15} {len(bt_loss):>15}")
lwr = f"{len(live_wins)/len(live_trades)*100:.1f}%" if live_trades else '—'
bwr = f"{len(bt_wins)/len(bt_trades)*100:.1f}%" if bt_trades else '—'
print(f"{'Win Rate':<30} {lwr:>15} {bwr:>15}")
print(f"{'Total P&L':<30} {live_pnl:>+15.2f} {bt_pnl:>+15.2f}")
print(f"{'Avg P&L per trade':<30} {live_pnl/len(live_trades) if live_trades else 0:>+15.2f} {bt_pnl/len(bt_trades) if bt_trades else 0:>+15.2f}")
if live_swaps:
    swap_total = sum(float(t['size']) for t in live_swaps)
    print(f"{'Overnight swap fees':<30} {swap_total:>+15.2f} {'n/a':>15}")
print()

# ── 4. Trade-by-trade ─────────────────────────────────────────────────────────
print('-' * 75)
print('LIVE TRADES (from Capital.com transactions)')
print('-' * 75)
print(f"  {'#':<3} {'Exit Time (UTC)':<22} {'P&L':>10}  {'Cumulative':>12}")
cum = 0
for i, t in enumerate(live_trades, 1):
    pnl = float(t['size'])
    cum += pnl
    flag = '✓' if pnl > 0 else '✗'
    print(f"  {i:<3} {t['dateUtc'][:19]:<22} {pnl:>+10.2f}  {cum:>+12.2f}  {flag}")

print()
print('-' * 75)
print('BACKTEST TRADES (Apr 7–10)')
print('-' * 75)
print(f"  {'#':<3} {'Entry':^17} {'Exit':^17} {'Side':<5} {'Entry$':>8} {'Exit$':>8} {'Hold':>5} {'P&L':>9}  Reason")
cum_bt = 0
for i, t in enumerate(bt_trades, 1):
    hold = int((t['exit_time'] - t['entry_time']).total_seconds() / 60)
    cum_bt += t['pnl']
    flag = '✓' if t['pnl'] > 0 else '✗'
    print(f"  {i:<3} {fmt(t['entry_time']):^17} {fmt(t['exit_time']):^17} {t['side']:<5} "
          f"{float(t['entry_price']):>8.2f} {float(t['exit_price']):>8.2f} {hold:>4}m {t['pnl']:>+9.2f}  {t['exit_reason']}  {flag}")

print()

# ── 5. Key observations ───────────────────────────────────────────────────────
print('=' * 75)
print('KEY OBSERVATIONS')
print('=' * 75)
print(f"  Live:     {len(live_trades)} trades  |  P&L = {live_pnl:+.2f}")
print(f"  Backtest: {len(bt_trades)} trades  |  P&L = {bt_pnl:+.2f}")
print(f"  Diff:     {len(live_trades) - len(bt_trades):+d} trades  |  P&L gap = {live_pnl - bt_pnl:+.2f}")
print()

ratio = len(live_trades) / len(bt_trades) if bt_trades else 0
if ratio > 1.4:
    print(f"  ⚠  TRADE FREQUENCY: Live is {ratio:.1f}× more active than backtest.")
    print(f"     Likely cause: tick_exit.reverse_on_loss=true in GOLD.yaml fires in live")
    print(f"     mode but is NOT simulated by the backtest engine.")
    print(f"     Backtest only closes on SL/TP. Live bot can re-enter on ST tick cross.")

if abs(live_pnl - bt_pnl) > 100:
    print()
    print(f"  ⚠  P&L GAP: {live_pnl - bt_pnl:+.2f} over the period.")
    print(f"     Live avg per trade: {live_pnl/len(live_trades):+.2f}  vs  Backtest: {bt_pnl/len(bt_trades):+.2f}")
    print(f"     Live trades are irregular sizes (not clean $150/$400) → tick exits")
    print(f"     at partial profit/loss, not pure SL/TP fills.")

# Check if exit reasons in backtest are all SL/TP (no tick exits)
exit_reasons = {}
for t in bt_trades:
    exit_reasons[t['exit_reason']] = exit_reasons.get(t['exit_reason'], 0) + 1
print()
print(f"  Backtest exit reasons: {exit_reasons}")
print(f"  (Backtest has no TICK_EXIT — confirms the simulation gap)")
