import sys, os, csv
sys.path.insert(0, 'trading-bot-skills')
from dotenv import load_dotenv
load_dotenv('.env')

from clients.capital_api import CapitalAPIClient
from datetime import datetime, timedelta

client = CapitalAPIClient(environment='demo')
client.create_session()

last_24h = 24 * 60 * 60
resp = client._request('GET', '/api/v1/history/transactions', params={'lastPeriod': last_24h})
data = resp.json()
txns = data.get('transactions', [])
gold_actual = sorted(
    [t for t in txns if t.get('instrumentName') == 'GOLD' and t.get('transactionType') == 'TRADE'],
    key=lambda x: x['dateUtc']
)

# Load backtest trades
bt_trades = []
with open('trading-bot-skills/results/GOLD/20260409_084731_noEMA_noSMA/trades.csv') as f:
    for row in csv.DictReader(f):
        bt_trades.append(row)

# Summary stats
actual_pnl = sum(float(t['size']) for t in gold_actual)
bt_pnl = sum(float(t['pnl']) for t in bt_trades)

print('='*70)
print('BACKTEST vs ACTUAL CAPITAL DEMO — GOLD (Last 24h)')
print('='*70)
print()
print(f"{'METRIC':<30} {'BACKTEST':>15} {'ACTUAL':>15}")
print('-'*60)
print(f"{'Trade count':<30} {len(bt_trades):>15} {len(gold_actual):>15}")

bt_wins = [t for t in bt_trades if float(t['pnl']) > 0]
bt_losses = [t for t in bt_trades if float(t['pnl']) < 0]
actual_wins = [t for t in gold_actual if float(t['size']) > 0]
actual_losses = [t for t in gold_actual if float(t['size']) < 0]

print(f"{'Winners':<30} {len(bt_wins):>15} {len(actual_wins):>15}")
print(f"{'Losers':<30} {len(bt_losses):>15} {len(actual_losses):>15}")
bt_wr = len(bt_wins)/len(bt_trades)*100 if bt_trades else 0
act_wr = len(actual_wins)/len(gold_actual)*100 if gold_actual else 0
print(f"{'Win Rate':<30} {bt_wr:.1f}%{' ':>13} {act_wr:.1f}%")
print(f"{'Total P&L':<30} ${bt_pnl:>+14.2f} ${actual_pnl:>+14.2f}")
print()

print('ACTUAL TRADES (Capital Demo — ordered chronologically):')
print(f"  {'Exit Time (UTC)':<25} {'P&L':>10}  Cumulative")
cum = 0
for t in gold_actual:
    pnl = float(t['size'])
    cum += pnl
    print(f"  {t['dateUtc']:<25} {pnl:>+10.2f}  {cum:>+10.2f}")

print()
print('BACKTEST TRADES:')
print(f"  {'Entry':<20}  {'Exit':<20}  {'Side':<5}  {'P&L':>10}  Exit Reason")
cum_bt = 0
for t in bt_trades:
    pnl = float(t['pnl'])
    cum_bt += pnl
    print(f"  {t['entry_time']:<20}  {t['exit_time']:<20}  {t['side']:<5}  {pnl:>+10.2f}  {t['exit_reason']}")

print()
print('='*70)
print(f"Backtest P&L:  ${bt_pnl:+.2f}")
print(f"Actual P&L:    ${actual_pnl:+.2f}")
diff = actual_pnl - bt_pnl
print(f"Difference:    ${diff:+.2f}")
print('='*70)
