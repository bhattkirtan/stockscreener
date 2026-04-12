"""
Trade-by-trade analysis: backtest vs actual Capital demo
Reconstructs actual trades from paired POSITION ACCEPTED activity events.
"""
import sys, csv, json
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, 'trading-bot-skills')
from dotenv import load_dotenv
load_dotenv('.env')
from clients.capital_api import CapitalAPIClient

# ── 1. Fetch raw data ────────────────────────────────────────────────────────

client = CapitalAPIClient(environment='demo')
client.create_session()

# Date range for comparison — last 4 trading days of last week
FROM_DATE = '2026-04-07T00:00:00'
TO_DATE   = '2026-04-11T00:00:00'

# Activity only supports lastPeriod <= 24h. Use 24h for recent pairs only.
resp = client._request('GET', '/api/v1/history/activity', params={
    'lastPeriod': 24 * 3600, 'detailed': 'true', 'filter': 'type==POSITION;status==ACCEPTED'
})
activities = sorted(
    [a for a in resp.json().get('activities', []) if a.get('epic') == 'GOLD'],
    key=lambda x: x['dateUTC']
)

# Transactions support from/to — fetch full Apr 7-10 window
resp2 = client._request('GET', '/api/v1/history/transactions', params={
    'from': FROM_DATE, 'to': TO_DATE
})
txns = sorted(
    [t for t in resp2.json().get('transactions', [])
     if t.get('instrumentName') == 'GOLD' and t.get('transactionType') == 'TRADE'],
    key=lambda x: x['dateUtc']
)

# ── 2. Reconstruct actual trades ─────────────────────────────────────────────
# Pattern: at each trade event, there are TWO "POSITION ACCEPTED" events:
#   First:  dealId = previous open dealId  → CLOSE of that position (level = exit price)
#   Second: new dealId                     → OPEN of new position   (level = entry price)
# The CLOSE event's direction = direction of the NEW trade (not the one closing).
# So we track open_dealId → { entry_time, entry_direction, entry_price }
# and when that dealId appears again as a close event, we complete the trade.

pos_events = [a for a in activities if a['type'] == 'POSITION' and a['status'] == 'ACCEPTED']

# Group by timestamp (minute precision) to find pairs
from itertools import groupby

open_registry = {}   # dealId -> {entry_time, direction, entry_price, size}
actual_trades = []

# Process chronologically. At each timestamp we expect pairs: [close_event, open_event]
# The close event: its dealId was previously opened
# The open event:  its dealId is new (not in open_registry)
for event in pos_events:
    deal   = event['dealId']
    ts     = datetime.fromisoformat(event['dateUTC'].split('.')[0])
    level  = event['details'].get('level', 0)
    size   = event['details'].get('size', 10)
    sl     = event['details'].get('stopLevel', 0)
    tp     = event['details'].get('profitLevel', 0)
    direct = event['details'].get('direction', '?')

    if deal in open_registry:
        # This is a CLOSE event for 'deal'
        opened = open_registry.pop(deal)
        actual_trades.append({
            'entry_time':  opened['entry_time'],
            'exit_time':   ts,
            'side':        opened['direction'],   # original open direction
            'entry_price': opened['entry_price'],
            'exit_price':  level,
            'sl':          opened['sl'],
            'tp':          opened['tp'],
            'size':        size,
            'pnl':         None,   # filled below from transactions
            'hold_min':    round((ts - opened['entry_time']).total_seconds() / 60, 1),
        })
    else:
        # This is an OPEN event
        open_registry[deal] = {
            'entry_time':  ts,
            'direction':   direct,
            'entry_price': level,
            'sl':          sl,
            'tp':          tp,
            'size':        size,
        }

actual_trades.sort(key=lambda x: x['exit_time'])

# Match P&L from transactions by exit time (within 90s)
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
with open('trading-bot-skills/results/GOLD/20260412_200033/trades.csv') as f:
    for row in csv.DictReader(f):
        row['entry_time']  = datetime.fromisoformat(row['entry_time'])
        row['exit_time']   = datetime.fromisoformat(row['exit_time'])
        row['pnl']         = float(row['pnl'])
        row['entry_price'] = float(row['entry_price'])
        row['exit_price']  = float(row['exit_price'])
        bt_trades.append(row)

# ── 4. Align trades by exit time (best match within 20 min) ─────────────────

def fmt(dt): return dt.strftime('%m-%d %H:%M')

matched = []
used_bt = set()
for act in actual_trades:
    best_bt, best_gap = None, timedelta(minutes=21)
    for i, bt in enumerate(bt_trades):
        if i in used_bt:
            continue
        gap = abs(act['exit_time'] - bt['exit_time'])
        if gap < best_gap:
            best_gap, best_bt = gap, (i, bt)
    if best_bt:
        used_bt.add(best_bt[0])
        matched.append((act, best_bt[1], best_gap))
    else:
        matched.append((act, None, None))

unmatched_bt = [bt for i, bt in enumerate(bt_trades) if i not in used_bt]

# ── 5. Print trade-by-trade table ────────────────────────────────────────────

def side_marker(a_side, bt_side):
    if bt_side is None: return '   '
    return '===' if a_side == bt_side else '<!>'

print('='*130)
print('TRADE-BY-TRADE: ACTUAL vs BACKTEST — GOLD 24h')
print('='*130)
hdr = (f"{'#':<3} {'EXIT':>14} {'DIR':<5} {'ENTRY':>8} {'EXIT_P':>8} {'HOLD':>5} {'PnL':>9} "
       f"| {'DIR':<5} {'ENTRY':>8} {'EXIT_P':>8} {'HOLD':>5} {'PnL':>9}  {'DIFF':>8}  {'BT_EXIT':>14}  FLAG")
print(hdr)
print(f"{'':50}ACTUAL{'':20}| BACKTEST")
print('-'*130)

patterns = defaultdict(list)
cum_act = cum_bt = 0

for n, (act, bt, gap) in enumerate(matched, 1):
    act_pnl = act['pnl'] or 0
    bt_pnl  = bt['pnl'] if bt else 0
    diff    = bt_pnl - act_pnl
    cum_act += act_pnl
    cum_bt  += bt_pnl

    # Entry price discrepancy
    entry_diff = abs(act['entry_price'] - bt['entry_price']) if bt else 0
    exit_diff  = abs(act['exit_price']  - bt['exit_price'])  if bt else 0
    hold_act   = act['hold_min']
    hold_bt    = round((bt['exit_time'] - bt['entry_time']).total_seconds() / 60) if bt else 0

    # Pattern tags
    tags = []
    if bt is None:
        tags.append('NO_MATCH')
    else:
        dir_flag = side_marker(act['side'], bt['side'])
        if act['side'] != bt['side']:
            tags.append('DIRECTION_FLIP')
        if entry_diff > 3:
            tags.append(f'ENTRY_GAP_{entry_diff:.0f}pt')
        if exit_diff > 5:
            tags.append(f'EXIT_GAP_{exit_diff:.0f}pt')
        if act_pnl < 0 and bt_pnl > 0:
            tags.append('ACT_LOSS/BT_WIN')
        elif act_pnl > 0 and bt_pnl < 0:
            tags.append('ACT_WIN/BT_LOSS')
        elif act_pnl < 0 and bt_pnl < 0:
            if abs(act_pnl) > abs(bt_pnl) + 20:
                tags.append(f'ACT_DEEPER_LOSS')
            elif abs(bt_pnl) > abs(act_pnl) + 20:
                tags.append(f'BT_DEEPER_LOSS')
            else:
                tags.append('BOTH_LOSS~')
        elif act_pnl > 0 and bt_pnl > 0:
            if bt_pnl > act_pnl + 20:
                tags.append('BT_BIGGER_WIN')
            elif act_pnl > bt_pnl + 20:
                tags.append('ACT_BIGGER_WIN')
            else:
                tags.append('BOTH_WIN~')
        if hold_bt < hold_act * 0.6 and diff > 20:
            tags.append('BT_EXITED_EARLIER')
        if hold_bt > hold_act * 1.5 and diff > 20:
            tags.append('BT_HELD_LONGER')

    tag_str = ' | '.join(tags) if tags else 'MATCH'
    for t in tags:
        base = t.split('_')[0] + '_' + t.split('_')[1] if '_' in t else t
        patterns[t].append({'n': n, 'act': act_pnl, 'bt': bt_pnl, 'diff': diff})

    if bt:
        act_row = f"{fmt(act['exit_time']):>14} {act['side']:<5} {act['entry_price']:>8.2f} {act['exit_price']:>8.2f} {hold_act:>5.0f} {act_pnl:>+9.2f}"
        bt_row  = f"{bt['side']:<5} {bt['entry_price']:>8.2f} {bt['exit_price']:>8.2f} {hold_bt:>5.0f} {bt_pnl:>+9.2f}  {diff:>+8.2f}  {fmt(bt['exit_time']):>14}"
    else:
        act_row = f"{fmt(act['exit_time']):>14} {act['side']:<5} {act['entry_price']:>8.2f} {act['exit_price']:>8.2f} {hold_act:>5.0f} {act_pnl:>+9.2f}"
        bt_row  = f"{'—':<5} {'—':>8} {'—':>8} {'—':>5} {'—':>9}  {'—':>8}  {'—':>14}"

    print(f"{n:<3} {act_row} | {bt_row}  {tag_str}")

print('-'*130)
print(f"{'TOT':<3} {'':>14} {'':5} {'':>8} {'':>8} {'':5} {cum_act:>+9.2f} | {'':5} {'':>8} {'':>8} {'':>5} {cum_bt:>+9.2f}  {cum_bt-cum_act:>+8.2f}")

# ── 6. Unmatched backtest ────────────────────────────────────────────────────

if unmatched_bt:
    print()
    print('BACKTEST TRADES WITH NO ACTUAL MATCH:')
    for bt in unmatched_bt:
        bh = round((bt['exit_time'] - bt['entry_time']).total_seconds() / 60)
        print(f"  {fmt(bt['exit_time'])} {bt['side']:<5} {bt['entry_price']:>8.2f}→{bt['exit_price']:>8.2f} hold={bh}m  pnl={bt['pnl']:>+.2f}  {bt['exit_reason']}")

# ── 7. Pattern summary ───────────────────────────────────────────────────────

print()
print('='*130)
print('PATTERN FREQUENCY & P&L IMPACT')
print('='*130)

# Group similar patterns
groups = {
    'DIRECTION_FLIP':   [],
    'ACT_LOSS/BT_WIN':  [],
    'ACT_WIN/BT_LOSS':  [],
    'ACT_DEEPER_LOSS':  [],
    'BT_DEEPER_LOSS':   [],
    'BOTH_LOSS~':       [],
    'BT_BIGGER_WIN':    [],
    'ACT_BIGGER_WIN':   [],
    'BT_EXITED_EARLIER':[],
    'BT_HELD_LONGER':   [],
}
entry_gap_trades = []
exit_gap_trades  = []

for tag, cases in patterns.items():
    if tag in groups:
        groups[tag].extend(cases)
    elif tag.startswith('ENTRY_GAP'):
        entry_gap_trades.extend([(tag, c) for c in cases])
    elif tag.startswith('EXIT_GAP'):
        exit_gap_trades.extend([(tag, c) for c in cases])

for label, cases in groups.items():
    if not cases: continue
    total_act  = sum(c['act'] for c in cases)
    total_bt   = sum(c['bt']  for c in cases)
    total_diff = sum(c['diff'] for c in cases)
    ns = ', '.join(f"#{c['n']}" for c in cases)
    print(f"  {label:<25} n={len(cases):>2}  act_total={total_act:>+9.2f}  bt_total={total_bt:>+9.2f}  diff={total_diff:>+9.2f}  trades={ns}")

if entry_gap_trades:
    total_diff = sum(c['diff'] for _, c in entry_gap_trades)
    ns = ', '.join(f"#{c['n']}({tag})" for tag, c in entry_gap_trades)
    print(f"  {'ENTRY_GAP>3pt':<25} n={len(entry_gap_trades):>2}  {'':>9}  {'':>9}  diff={total_diff:>+9.2f}  {ns}")
if exit_gap_trades:
    total_diff = sum(c['diff'] for _, c in exit_gap_trades)
    ns = ', '.join(f"#{c['n']}({tag})" for tag, c in exit_gap_trades)
    print(f"  {'EXIT_GAP>5pt':<25} n={len(exit_gap_trades):>2}  {'':>9}  {'':>9}  diff={total_diff:>+9.2f}  {ns}")

# ── 8. Key metrics ───────────────────────────────────────────────────────────

print()
print('KEY METRICS')
print('-'*60)
act_entries = [t['entry_price'] for t in actual_trades if t['pnl'] is not None]
bt_entries  = [float(t['entry_price']) for t in bt_trades]
if actual_trades and bt_trades:
    matched_valid = [(a, b) for a, b, g in matched if b is not None and a['pnl'] is not None]
    entry_diffs = [abs(a['entry_price'] - float(b['entry_price'])) for a, b in matched_valid]
    exit_diffs  = [abs(a['exit_price']  - float(b['exit_price']))  for a, b in matched_valid]
    hold_diffs  = [a['hold_min'] - round((b['exit_time']-b['entry_time']).total_seconds()/60)
                   for a, b in matched_valid]
    print(f"  Avg entry price diff (act vs bt):  {sum(entry_diffs)/len(entry_diffs):.2f} pts")
    print(f"  Avg exit  price diff (act vs bt):  {sum(exit_diffs)/len(exit_diffs):.2f} pts")
    print(f"  Avg hold time diff   (act - bt):   {sum(hold_diffs)/len(hold_diffs):+.1f} min")
    print(f"  Matched trades: {len(matched_valid)} / {len(actual_trades)}")

print()
print('DIRECTION AGREEMENT (matched trades):')
matched_valid = [(a, b) for a, b, g in matched if b is not None]
same_dir  = [(a, b) for a, b in matched_valid if a['side'] == b['side']]
diff_dir  = [(a, b) for a, b in matched_valid if a['side'] != b['side']]
print(f"  Same direction: {len(same_dir)} trades")
print(f"  Diff direction: {len(diff_dir)} trades — {[(fmt(a['exit_time']), a['side'], b['side']) for a,b in diff_dir]}")
