"""
Exit-timing simulation: for each matched trade (same entry bar, same direction)
simulate what P&L would be if:
  A) actual bot had held to the backtest's exit bar
  B) backtest had exited at the actual bot's exit bar
"""
import sys, csv, sqlite3
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, 'trading-bot-skills')
from dotenv import load_dotenv
load_dotenv('.env')
from clients.capital_api import CapitalAPIClient

# ── 1. Load M5 bars (UTC, bid prices) ───────────────────────────────────────

conn = sqlite3.connect('/data/trading.db')
bars_raw = conn.execute(
    "SELECT timestamp, open, high, low, close "
    "FROM candles WHERE epic='GOLD' AND timeframe='M5' ORDER BY timestamp"
).fetchall()
conn.close()

bars = {}
bar_list = []
for ts, o, h, l, c in bars_raw:
    dt = datetime.fromisoformat(ts)
    bars[dt] = {'open': o, 'high': h, 'low': l, 'close': c}
    bar_list.append(dt)

def bar_at(ts: datetime):
    """Snap ts down to nearest M5 bar."""
    return ts.replace(minute=(ts.minute // 5) * 5, second=0, microsecond=0)

def price_at_bar(dt: datetime, side: str) -> float:
    """Get exit price at bar dt for a given position side."""
    b = bars.get(dt)
    if not b:
        return 0.0
    # Approximate: closing a BUY → sell at close (bid); closing a SELL → buy at close (ask = close + 0.5)
    if side == 'BUY':
        return b['close']
    else:
        return b['close'] + 0.50      # ask ≈ bid + spread

# ── 2. Reconstruct actual trades from Capital activity ────────────────────────

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
    sl    = event['details'].get('stopLevel', 0)
    tp    = event['details'].get('profitLevel', 0)
    direc = event['details'].get('direction', '?')

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
            'entry_time':  ts,
            'direction':   direc,
            'entry_price': level,
            'sl':          sl,
            'tp':          tp,
        }

actual_trades.sort(key=lambda x: x['entry_time'])

used_txn = set()
for trade in actual_trades:
    for i, tx in enumerate(txns):
        if i in used_txn:
            continue
        tx_t = datetime.fromisoformat(tx['dateUtc'].split('.')[0])
        if abs((tx_t - trade['exit_time']).total_seconds()) <= 90:
            trade['pnl'] = float(tx['size'])
            used_txn.add(i)
            break

# ── 3. Load backtest trades ──────────────────────────────────────────────────

bt_trades = []
with open('trading-bot-skills/results/GOLD/20260409_092703_noEMA_noSMA/trades.csv') as f:
    for row in csv.DictReader(f):
        row['entry_time']  = datetime.fromisoformat(row['entry_time'])
        row['exit_time']   = datetime.fromisoformat(row['exit_time'])
        row['pnl']         = float(row['pnl'])
        row['entry_price'] = float(row['entry_price'])
        row['exit_price']  = float(row['exit_price'])
        bt_trades.append(row)

# ── 4. Match by entry bar + direction ────────────────────────────────────────

def to_bar(dt): return dt.replace(minute=(dt.minute//5)*5, second=0, microsecond=0)

matched = []
used_bt = set()
for act in actual_trades:
    act_bar = to_bar(act['entry_time'])
    best, best_gap = None, timedelta(minutes=16)
    for i, bt in enumerate(bt_trades):
        if i in used_bt: continue
        bt_bar = to_bar(bt['entry_time'])
        gap = abs(act_bar - bt_bar)
        if gap < best_gap and act['side'] == bt['side']:
            best_gap, best = gap, (i, bt)
    if best:
        used_bt.add(best[0])
        matched.append((act, best[1]))

# ── 5. Simulate cross-exit ────────────────────────────────────────────────────

def sim_pnl(side, entry_price, exit_bar, size=10):
    """Simulate P&L if trade closed at exit_bar's close."""
    ep = price_at_bar(exit_bar, side)
    if not ep:
        return None
    pts = (ep - entry_price) if side == 'BUY' else (entry_price - ep)
    return round(pts * size, 2)

print('=' * 125)
print('EXIT TIMING SIMULATION — GOLD 24h')
print('What if the live bot held to BT exit? What if BT exited at live exit?')
print('=' * 125)
print(f"{'#':<3} {'ENTRY':>8} {'DIR':<5}"
      f" {'ACT_entry':>10} {'ACT_exit':>10} {'ACT_exit_t':>8} {'ACT_PnL':>8}"
      f" | {'BT_entry':>10} {'BT_exit':>10} {'BT_exit_t':>8} {'BT_PnL':>8}"
      f" | {'SIM:act→BT':>10} {'SIM:bt→ACT':>10}  EXIT_GAP")
print('-' * 125)

total_act = total_bt = total_sim_act_to_bt = total_sim_bt_to_act = 0
cases = []

for n, (act, bt) in enumerate(matched, 1):
    if act['pnl'] is None: continue
    act_pnl = act['pnl']
    bt_pnl  = bt['pnl']

    act_exit_bar = to_bar(act['exit_time'])
    bt_exit_bar  = to_bar(bt['exit_time'])
    exit_gap_min = (bt_exit_bar - act_exit_bar).total_seconds() / 60

    # Simulate: actual entry price, exit at BT's exit bar
    sim_act_to_bt = sim_pnl(act['side'], act['entry_price'], bt_exit_bar)
    # Simulate: BT entry price, exit at actual's exit bar
    sim_bt_to_act = sim_pnl(bt['side'], bt['entry_price'], act_exit_bar)

    total_act          += act_pnl
    total_bt           += bt_pnl
    if sim_act_to_bt: total_sim_act_to_bt += sim_act_to_bt
    if sim_bt_to_act: total_sim_bt_to_act += sim_bt_to_act

    cases.append({
        'n': n, 'side': act['side'],
        'act_pnl': act_pnl, 'bt_pnl': bt_pnl,
        'sim_act_to_bt': sim_act_to_bt,
        'sim_bt_to_act': sim_bt_to_act,
        'exit_gap_min': exit_gap_min,
        'act_entry_t': act['entry_time'],
        'bt_exit_bar': bt_exit_bar,
        'act_exit_bar': act_exit_bar,
    })

    gap_str = f"{exit_gap_min:+.0f}m"
    sim1_str = f"{sim_act_to_bt:>+10.2f}" if sim_act_to_bt is not None else f"{'N/A':>10}"
    sim2_str = f"{sim_bt_to_act:>+10.2f}" if sim_bt_to_act is not None else f"{'N/A':>10}"

    print(f"{n:<3} {act['entry_time'].strftime('%H:%M'):>8} {act['side']:<5}"
          f" {act['entry_price']:>10.2f} {act['exit_price']:>10.2f} {act['exit_time'].strftime('%H:%M'):>8} {act_pnl:>+8.2f}"
          f" | {bt['entry_price']:>10.2f} {bt['exit_price']:>10.2f} {bt['exit_time'].strftime('%H:%M'):>8} {bt_pnl:>+8.2f}"
          f" | {sim1_str} {sim2_str}  {gap_str}")

print('-' * 125)
print(f"{'TOT':<3} {'':>8} {'':5}"
      f" {'':>10} {'':>10} {'':>8} {total_act:>+8.2f}"
      f" | {'':>10} {'':>10} {'':>8} {total_bt:>+8.2f}"
      f" | {total_sim_act_to_bt:>+10.2f} {total_sim_bt_to_act:>+10.2f}")

# ── 6. Pattern analysis ───────────────────────────────────────────────────────

print()
print('=' * 125)
print('PATTERN ANALYSIS: EXIT TIMING IMPACT')
print('=' * 125)

# Categorise by who benefits from holding longer
held_longer_helps_bt  = [c for c in cases if c['exit_gap_min'] > 5  and c['bt_pnl'] > c['act_pnl']]
held_shorter_helps_act = [c for c in cases if c['exit_gap_min'] < -5 and c['act_pnl'] > c['bt_pnl']]
similar_exit          = [c for c in cases if abs(c['exit_gap_min']) <= 5]
bt_exits_earlier_wins  = [c for c in cases if c['exit_gap_min'] < -5 and c['bt_pnl'] > c['act_pnl']]

print(f"\n  BT exits LATER  (>5m) and wins more: {len(held_longer_helps_bt):>2} trades"
      f"  | act_sum={sum(c['act_pnl'] for c in held_longer_helps_bt):>+8.2f}"
      f"  | bt_sum={sum(c['bt_pnl'] for c in held_longer_helps_bt):>+8.2f}"
      f"  | if act held to BT exit: {sum(c['sim_act_to_bt'] or 0 for c in held_longer_helps_bt):>+8.2f}")

print(f"  BT exits EARLIER(<5m) and wins more: {len(bt_exits_earlier_wins):>2} trades"
      f"  | act_sum={sum(c['act_pnl'] for c in bt_exits_earlier_wins):>+8.2f}"
      f"  | bt_sum={sum(c['bt_pnl'] for c in bt_exits_earlier_wins):>+8.2f}")

print(f"  ACT exits earlier and wins more:      {len(held_shorter_helps_act):>2} trades"
      f"  | act_sum={sum(c['act_pnl'] for c in held_shorter_helps_act):>+8.2f}"
      f"  | bt_sum={sum(c['bt_pnl'] for c in held_shorter_helps_act):>+8.2f}")

print(f"  Similar exit time (±5m):              {len(similar_exit):>2} trades")

print()
print(f"  SUMMARY:")
print(f"    Actual  P&L with actual exits:        {total_act:>+9.2f}")
print(f"    Actual  P&L if held to BT exits:      {total_sim_act_to_bt:>+9.2f}  (gain: {total_sim_act_to_bt - total_act:>+.2f})")
print(f"    BT      P&L with BT exits:            {total_bt:>+9.2f}")
print(f"    BT      P&L if exited at ACT times:   {total_sim_bt_to_act:>+9.2f}  (gain: {total_sim_bt_to_act - total_bt:>+.2f})")

# ── 7. Per-trade exit bar detail for big divergences ─────────────────────────

print()
print('=' * 125)
print('TRADE DETAIL: exit bar price vs actual exit price (trades with >$30 diff)')
print('=' * 125)
print(f"  {'#':>3} {'Entry':>8} {'Side':<5} {'Actual exit':>12} {'BT exit':>10} {'Gap':>6}  {'ACT_PnL':>8}  {'BT_PnL':>8}  {'→hold_to_BT':>12}  Analysis")
print('-' * 125)

for c in cases:
    diff = abs(c['bt_pnl'] - c['act_pnl'])
    if diff <= 30:
        continue
    abar = bars.get(c['act_exit_bar'], {})
    bbar = bars.get(c['bt_exit_bar'],  {})
    a_close = abar.get('close', 0)
    b_close = bbar.get('close', 0)
    gap_str = f"{c['exit_gap_min']:>+.0f}m"

    if c['bt_pnl'] > c['act_pnl']:
        if c['exit_gap_min'] > 0:
            analysis = f"BT held {c['exit_gap_min']:.0f}m longer, price moved in favour (close {a_close:.2f}→{b_close:.2f})"
        else:
            analysis = f"BT exited {abs(c['exit_gap_min']):.0f}m EARLIER at better price ({b_close:.2f} vs {a_close:.2f})"
    else:
        if c['exit_gap_min'] < 0:
            analysis = f"ACT exited {abs(c['exit_gap_min']):.0f}m earlier at better price ({a_close:.2f} vs {b_close:.2f})"
        else:
            analysis = f"ACT exited {abs(c['exit_gap_min']):.0f}m earlier, price had already reversed"

    sim1 = f"{c['sim_act_to_bt']:>+.2f}" if c['sim_act_to_bt'] else 'N/A'
    print(f"  {c['n']:>3} {c['act_entry_t'].strftime('%H:%M'):>8} {c['side']:<5}"
          f" {c['act_exit_bar'].strftime('%H:%M'):>12} {c['bt_exit_bar'].strftime('%H:%M'):>10} {gap_str:>6}"
          f"  {c['act_pnl']:>+8.2f}  {c['bt_pnl']:>+8.2f}  {sim1:>12}  {analysis}")
