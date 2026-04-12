"""
Bar-level timeline: M5 OHLC + actual Capital trade entries/exits + backtest entries/exits.
Shows exactly which bar each trade opened/closed on and the price discrepancy.
"""
import sys, csv, sqlite3
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, 'trading-bot-skills')
from dotenv import load_dotenv
load_dotenv('.env')
from clients.capital_api import CapitalAPIClient

# ── 1. Load M5 bars from SQLite ──────────────────────────────────────────────

conn = sqlite3.connect('/data/trading.db')
bars_raw = conn.execute(
    "SELECT timestamp, open, high, low, close FROM candles "
    "WHERE epic='GOLD' AND timeframe='M5' ORDER BY timestamp"
).fetchall()
conn.close()

bars = {}
for ts, o, h, l, c in bars_raw:
    bars[datetime.fromisoformat(ts)] = {'open': o, 'high': h, 'low': l, 'close': c}

# ── 2. Fetch actual Capital trades (reconstruct from activity) ───────────────

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
    deal   = event['dealId']
    ts     = datetime.fromisoformat(event['dateUTC'].split('.')[0])
    level  = event['details'].get('level', 0)
    size   = event['details'].get('size', 10)
    sl     = event['details'].get('stopLevel', 0)
    tp     = event['details'].get('profitLevel', 0)
    direct = event['details'].get('direction', '?')

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
            'pnl':         None,
        })
    else:
        open_registry[deal] = {
            'entry_time':  ts,
            'direction':   direct,
            'entry_price': level,
            'sl':          sl,
            'tp':          tp,
        }

actual_trades.sort(key=lambda x: x['entry_time'])

# Match P&L
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
with open('trading-bot-skills/results/GOLD/20260409_084731_noEMA_noSMA/trades.csv') as f:
    for row in csv.DictReader(f):
        row['entry_time']  = datetime.fromisoformat(row['entry_time'])
        row['exit_time']   = datetime.fromisoformat(row['exit_time'])
        row['pnl']         = float(row['pnl'])
        row['entry_price'] = float(row['entry_price'])
        row['exit_price']  = float(row['exit_price'])
        bt_trades.append(row)

# ── 4. Map events onto bars ──────────────────────────────────────────────────
# Round a timestamp down to the nearest M5 bar

def to_bar(ts: datetime) -> datetime:
    return ts.replace(minute=(ts.minute // 5) * 5, second=0, microsecond=0)

# Build per-bar event index
bar_events = defaultdict(lambda: {'act': [], 'bt': []})

for t in actual_trades:
    bar_events[to_bar(t['entry_time'])]['act'].append(
        {'type': 'OPEN', 'trade': t}
    )
    bar_events[to_bar(t['exit_time'])]['act'].append(
        {'type': 'CLOSE', 'trade': t}
    )

for t in bt_trades:
    bar_events[to_bar(t['entry_time'])]['bt'].append(
        {'type': 'OPEN', 'trade': t}
    )
    bar_events[to_bar(t['exit_time'])]['bt'].append(
        {'type': 'CLOSE', 'trade': t}
    )

# ── 5. Print timeline ────────────────────────────────────────────────────────

# Only print bars that have events (+ 1 bar context before/after)
event_bars = set(bar_events.keys())
context_bars = set()
all_bar_times = sorted(bars.keys())
for bt in event_bars:
    idx = all_bar_times.index(bt) if bt in all_bar_times else -1
    if idx >= 0:
        if idx > 0:   context_bars.add(all_bar_times[idx - 1])
        if idx + 1 < len(all_bar_times): context_bars.add(all_bar_times[idx + 1])

print_bars = sorted(event_bars | context_bars)

# Only show bars within our 24h window
start_24h = min(t['entry_time'] for t in actual_trades)
print_bars = [b for b in print_bars if b >= start_24h - timedelta(minutes=5)]

print('='*130)
print('M5 BAR TIMELINE: ACTUAL CAPITAL TRADES vs BACKTEST — GOLD')
print('Legend: [A]=actual  [B]=backtest  OPEN→entry  CLOSE→exit')
print('='*130)
print(f"{'BAR TIME':<17} {'OPEN':>8} {'HIGH':>8} {'LOW':>8} {'CLOSE':>8}  ACTUAL EVENT                              BACKTEST EVENT")
print('-'*130)

prev_bar_time = None
for bar_time in print_bars:
    bar = bars.get(bar_time)
    if bar is None:
        continue

    # Gap separator
    if prev_bar_time and (bar_time - prev_bar_time) > timedelta(minutes=10):
        print(f"  {'···':^17}")
    prev_bar_time = bar_time

    evs = bar_events.get(bar_time, {'act': [], 'bt': []})
    act_evs = evs['act']
    bt_evs  = evs['bt']

    # Format event strings
    def fmt_ev(evs, label):
        parts = []
        for e in evs:
            t = e['trade']
            pnl_str = f" pnl={t['pnl']:+.0f}" if t.get('pnl') is not None else ''
            bt_pnl  = f" pnl={t['pnl']:+.0f}" if isinstance(t.get('pnl'), float) else ''
            if e['type'] == 'OPEN':
                side = t['side']
                price = t['entry_price']
                sl    = t.get('sl', 0) or t.get('stop_loss', 0)
                try:
                    sl_f = float(sl)
                except:
                    sl_f = 0
                parts.append(f"[{label}] OPEN  {side:<5} @{price:.2f} SL={sl_f:.2f}")
            else:
                side  = t['side']
                price = t['exit_price'] if isinstance(t.get('exit_price'), float) else float(t.get('exit_price',0))
                reason = t.get('exit_reason', '')
                pnl_val = t['pnl'] if t.get('pnl') is not None else t.get('pnl', 0)
                if pnl_val is None: pnl_val = 0
                parts.append(f"[{label}] CLOSE {side:<5} @{price:.2f} {reason} pnl={float(pnl_val):+.0f}")
        return '  '.join(parts) if parts else ''

    act_str = fmt_ev(act_evs, 'A')
    bt_str  = fmt_ev(bt_evs,  'B')

    # Highlight direction mismatch
    act_opens = [e for e in act_evs if e['type'] == 'OPEN']
    bt_opens  = [e for e in bt_evs  if e['type'] == 'OPEN']
    mismatch = ''
    if act_opens and bt_opens:
        a_side = act_opens[0]['trade']['side']
        b_side = bt_opens[0]['trade']['side']
        if a_side != b_side:
            mismatch = '  *** DIR MISMATCH ***'

    ohlc = f"{bar['open']:>8.2f} {bar['high']:>8.2f} {bar['low']:>8.2f} {bar['close']:>8.2f}"
    act_col = f"{act_str:<42}" if act_str else f"{'':42}"

    print(f"{bar_time.strftime('%m-%d %H:%M'):>17} {ohlc}  {act_col}  {bt_str}{mismatch}")

# ── 6. Key mismatches summary ────────────────────────────────────────────────

print()
print('='*130)
print('ENTRY/EXIT PRICE COMPARISON (actual vs backtest per matched trade)')
print('='*130)
print(f"{'ACT ENTRY':>17} {'SIDE':<5} {'ACT entry':>10} {'BT entry':>10} {'Δentry':>8}  {'ACT exit':>10} {'BT exit':>10} {'Δexit':>8}  {'ACT PnL':>9} {'BT PnL':>9}  {'DIFF':>8}  {'BAR CONTEXT'}")
print('-'*130)

used_bt = set()
matched_pairs = []
for act in actual_trades:
    best, best_gap = None, timedelta(minutes=16)
    for i, bt in enumerate(bt_trades):
        if i in used_bt: continue
        gap = abs(act['exit_time'] - bt['exit_time'])
        if gap < best_gap:
            best_gap, best = gap, (i, bt)
    if best:
        used_bt.add(best[0])
        matched_pairs.append((act, best[1]))

for act, bt in matched_pairs:
    if act['pnl'] is None: continue
    act_entry = act['entry_price']
    bt_entry  = float(bt['entry_price'])
    act_exit  = act['exit_price']
    bt_exit   = float(bt['exit_price'])
    d_entry   = act_entry - bt_entry
    d_exit    = act_exit  - bt_exit
    act_pnl   = act['pnl']
    bt_pnl    = float(bt['pnl'])

    # Get the bar at entry time for both
    act_bar = to_bar(act['entry_time'])
    bt_bar  = to_bar(bt['entry_time'])
    bar_act = bars.get(act_bar, {})
    bar_bt  = bars.get(bt_bar, {})

    dir_flag = '===' if act['side'] == bt['side'] else '<!>'
    bar_ctx  = f"ActBar={act_bar.strftime('%H:%M')} BtBar={bt_bar.strftime('%H:%M')} {dir_flag}"

    print(f"{act['entry_time'].strftime('%m-%d %H:%M'):>17} {act['side']:<5} "
          f"{act_entry:>10.2f} {bt_entry:>10.2f} {d_entry:>+8.2f}  "
          f"{act_exit:>10.2f} {bt_exit:>10.2f} {d_exit:>+8.2f}  "
          f"{act_pnl:>+9.2f} {bt_pnl:>+9.2f}  {bt_pnl-act_pnl:>+8.2f}  {bar_ctx}")

print()
print('Δentry = actual_entry - bt_entry  (positive = actual entered higher)')
print('Δexit  = actual_exit  - bt_exit   (positive = actual exited at higher price)')
