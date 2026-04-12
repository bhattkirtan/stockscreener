"""
M1 Exit Backtest (24h)
======================
Entries: M5 Supertrend flip → execute at next M5 bar open
Exits:   First M1 Supertrend flip against position
         OR SL/TP hit (checked on M1 bars)
         OR next M5 reverse signal (whichever comes first)

Settings match GOLD.yaml live config.
"""
import sys
import pandas as pd
import numpy as np

sys.path.insert(0, 'trading-bot-skills')
from dotenv import load_dotenv
load_dotenv('.env')
from clients.sqlite_api import SQLiteAPIClient
from core.indicators import calculate_supertrend, calculate_adx

# ── Config (matches GOLD.yaml) ────────────────────────────────────────────────
ST_PERIOD   = 14
ST_MULT     = 1.5
SL_PIPS     = 20.0
TP_PIPS     = 60.0
SIZE        = 10
SPREAD_USD  = 0.50
SLIP_USD    = 0.10

# ADX filter: set to 0 to disable
ADX_PERIOD    = 14
ADX_THRESHOLD = 25   # only trade when ADX >= this

# ── Load data ─────────────────────────────────────────────────────────────────
db = SQLiteAPIClient()

# Load ALL M5 bars for proper indicator warmup, trim trading window later
m5_rows = db.query_candles('GOLD', 'M5', limit=None)
m5_full = pd.DataFrame(m5_rows)
m5_full['timestamp'] = pd.to_datetime(m5_full['timestamp'])
m5_full = m5_full.sort_values('timestamp').set_index('timestamp')

m1_rows = db.query_candles('GOLD', 'M1', limit=None)
m1 = pd.DataFrame(m1_rows)
m1['timestamp'] = pd.to_datetime(m1['timestamp'])
m1 = m1.sort_values('timestamp').set_index('timestamp')

print(f"M5 full history: {len(m5_full):,}  |  {m5_full.index[0]} → {m5_full.index[-1]}")
print(f"M1 bars:         {len(m1):,}  |  {m1.index[0]} → {m1.index[-1]}")

# ── Compute Supertrend + ADX on FULL history (proper warmup) ──────────────────
_, m5_dir_full, _, _ = calculate_supertrend(m5_full, ST_PERIOD, ST_MULT)
m5_full['st_dir'] = m5_dir_full

adx_vals, _, _ = calculate_adx(m5_full, ADX_PERIOD)
m5_full['adx'] = adx_vals

_, m1_dir, _, _ = calculate_supertrend(m1, ST_PERIOD, ST_MULT)
m1['st_dir'] = m1_dir

# Trim M5 to M1 overlap window for actual trading
trade_start = m1.index[0]
trade_end   = m1.index[-1]
m5 = m5_full.loc[trade_start:trade_end]

print(f"M5 trading window: {len(m5):,}  |  {m5.index[0]} → {m5.index[-1]}")

# ── Backtest ───────────────────────────────────────────────────────────────────

def find_m1_exit(entry_time, side, entry_price, m5_exit_time):
    """
    Scan M1 bars from entry_time to m5_exit_time.
    Returns: (exit_time, exit_price, reason)
    Reasons: 'M1_ST', 'SL', 'TP', 'M5_REVERSE'
    """
    window = m1.loc[entry_time:m5_exit_time] if m5_exit_time else m1.loc[entry_time:]
    if window.empty:
        return m5_exit_time, entry_price, 'M5_REVERSE'

    bars = window.iloc[1:]  # skip entry bar (ST may be stale)
    rev_dir = -1 if side == 'BUY' else 1

    for ts, bar in bars.iterrows():
        # SL check (intrabar)
        if side == 'BUY' and bar['low'] <= entry_price - SL_PIPS:
            return ts, entry_price - SL_PIPS, 'SL'
        if side == 'SELL' and bar['high'] >= entry_price + SL_PIPS:
            return ts, entry_price + SL_PIPS, 'SL'
        # TP check (intrabar)
        if side == 'BUY' and bar['high'] >= entry_price + TP_PIPS:
            return ts, entry_price + TP_PIPS, 'TP'
        if side == 'SELL' and bar['low'] <= entry_price - TP_PIPS:
            return ts, entry_price - TP_PIPS, 'TP'
        # M1 ST reversal
        if bar['st_dir'] == rev_dir:
            return ts, bar['close'], 'M1_ST'

    # No M1 exit found before M5 reverse → exit at M5 bar open
    return m5_exit_time, None, 'M5_REVERSE'

trades = []
m5_arr = m5.reset_index()
n = len(m5_arr)

i = ST_PERIOD  # skip warmup
in_trade = None

while i < n:
    row = m5_arr.iloc[i]
    ts  = row['timestamp']
    sig = None

    if i > 0:
        prev_dir = m5_arr.iloc[i - 1]['st_dir']
        curr_dir = row['st_dir']
        if prev_dir != curr_dir:
            # ADX filter: require trending market at signal bar
            adx_val = row['adx'] if not pd.isna(row['adx']) else 0
            if ADX_THRESHOLD == 0 or adx_val >= ADX_THRESHOLD:
                sig = 'BUY' if curr_dir == 1 else 'SELL'

    # If in a trade, check for reverse signal (M5-level exit boundary)
    if in_trade and sig and sig != in_trade['side']:
        # M5 reverse signal: exit at this bar's open (same as next-bar open logic)
        m5_exit_time = ts
        m5_exit_open = row['open']

        exit_time, exit_price, reason = find_m1_exit(
            in_trade['entry_time'], in_trade['side'],
            in_trade['entry_price'], m5_exit_time
        )
        if exit_price is None:
            exit_price = m5_exit_open

        pts = (exit_price - in_trade['entry_price']) if in_trade['side'] == 'BUY' \
              else (in_trade['entry_price'] - exit_price)
        pnl = round(pts * SIZE - SPREAD_USD - SLIP_USD, 2)
        trades.append({**in_trade, 'exit_time': exit_time, 'exit_price': exit_price,
                       'pnl': pnl, 'reason': reason})
        in_trade = None

    # Enter new trade at next bar's open
    if sig and not in_trade:
        if i + 1 < n:
            next_row  = m5_arr.iloc[i + 1]
            entry_time  = next_row['timestamp']
            entry_price = next_row['open']
            in_trade = {'side': sig, 'entry_time': entry_time, 'entry_price': entry_price}

    i += 1

# Close any open trade at last M1 bar
if in_trade:
    last_m1 = m1.iloc[-1]
    exit_time, exit_price, reason = find_m1_exit(
        in_trade['entry_time'], in_trade['side'],
        in_trade['entry_price'], None
    )
    if exit_price is None:
        exit_price = last_m1['close']
    pts = (exit_price - in_trade['entry_price']) if in_trade['side'] == 'BUY' \
          else (in_trade['entry_price'] - exit_price)
    pnl = round(pts * SIZE - SPREAD_USD - SLIP_USD, 2)
    trades.append({**in_trade, 'exit_time': exit_time, 'exit_price': exit_price,
                   'pnl': pnl, 'reason': reason + '(EOD)'})

# ── Print results ──────────────────────────────────────────────────────────────
print()
print('=' * 110)
print('M1 EXIT BACKTEST — GOLD 24h  |  M5 entries → M1 ST exit (SL/TP safety nets)')
adx_label = f'ADX≥{ADX_THRESHOLD}' if ADX_THRESHOLD > 0 else 'ADX=OFF'
print(f'Settings: ST({ST_PERIOD}×{ST_MULT}), SL={SL_PIPS}, TP={TP_PIPS}, Size={SIZE}, {adx_label}')
print('=' * 110)
print(f"{'#':<3} {'SIDE':<5} {'ENTRY_T':>8} {'ENTRY_P':>9} {'EXIT_T':>8} {'EXIT_P':>9} {'PnL':>9}  REASON")
print('-' * 110)

total_pnl = 0
wins = losses = 0
reason_counts = {}

for n, t in enumerate(trades, 1):
    pnl = t['pnl']
    total_pnl += pnl
    if pnl > 0: wins += 1
    else: losses += 1
    reason_counts[t['reason']] = reason_counts.get(t['reason'], 0) + 1
    print(f"{n:<3} {t['side']:<5} {t['entry_time'].strftime('%H:%M'):>8}"
          f" {t['entry_price']:>9.2f} {t['exit_time'].strftime('%H:%M'):>8}"
          f" {t['exit_price']:>9.2f} {pnl:>+9.2f}  {t['reason']}")

print('-' * 110)
print(f"{'TOT':<3} {'':5} {'':>8} {'':>9} {'':>8} {'':>9} {total_pnl:>+9.2f}")
print()
print('=' * 110)
print('SUMMARY')
print('=' * 110)
total_trades = len(trades)
wr = wins / total_trades * 100 if total_trades else 0
print(f"  Trades: {total_trades}  |  Wins: {wins}  Losses: {losses}  |  Win rate: {wr:.1f}%")
print(f"  Total P&L: {total_pnl:>+.2f}")
print(f"  Exit reasons: {reason_counts}")
