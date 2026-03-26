#!/usr/bin/env python3
"""
Trace what happens when the first BUY position closes on Reverse Signal.
Why doesn't it open a SELL position?
"""

import pandas as pd
from src.optimization.worker import build_strategy, build_backtest_config
from src.core.backtester import IntraCandleBacktester

# Load data
print("Loading data...")
df = pd.read_csv('data/GOLD_M5_150000bars.csv', parse_dates=['timestamp'])
df.set_index('timestamp', inplace=True)

# Load orders to find first reverse signal
orders = pd.read_csv('data/optimization/2026-03-26/run_20260326_090350/rank01_ST2.0_SMA25-30_BB2.0_PIP1_F20.0-40.0/orders.csv', parse_dates=['entry_time', 'exit_time'])

# Find first reverse signal trade
first_reverse = orders[orders['exit_reason'] == 'Reverse Signal'].iloc[0]
print(f"\n{'='*60}")
print(f"FIRST REVERSE SIGNAL TRADE:")
print(f"{'='*60}")
print(f"Entry: {first_reverse['entry_time']} @ ${first_reverse['entry_price']:.2f} {first_reverse['side']}")
print(f"Exit:  {first_reverse['exit_time']} @ ${first_reverse['exit_price']:.2f} (Reverse Signal)")
print(f"PnL: ${first_reverse['pnl']:.2f}")

# Get a time window around the reverse signal exit
exit_time = first_reverse['exit_time']
window_start = exit_time - pd.Timedelta(hours=2)
window_end = exit_time + pd.Timedelta(hours=2)

# Filter data to this window
df_window = df[(df.index >= window_start) & (df.index <= window_end)]

# Build strategy and generate signals for this window
params = {
    'supertrend_period': 7,
    'supertrend_multiplier': 2.0,
    'sma_fast': 25,
    'sma_slow': 30,
    'ema_period': 21,
    'bb_period': 20,
    'bb_std': 2.0,
    'sl_pips': 20.0,
    'tp_pips': 40.0,
    'pip_value': 1.0,
    'enable_event_blocking': False  # Use actual backtest config
}

print(f"\n{'='*60}")
print(f"SIGNALS AROUND REVERSE SIGNAL EXIT:")
print(f"{'='*60}")
print(f"Time window: {window_start} to {window_end}")

strategy = build_strategy(params)
df_indicators = strategy.calculate_indicators(df_window.copy())
signals = strategy.generate_signals(df_indicators)

# Show signals in window
signals_with_signal = signals[signals['signal'] != 0]
print(f"\nFound {len(signals_with_signal)} signals in window:")
for idx, row in signals_with_signal.iterrows():
    signal_type = "BUY" if row['signal'] == 1 else "SELL"
    print(f"  {idx}: {signal_type} signal @ ${row['entry_price']:.2f}")

# Check what signal appears at exit time
exit_candle = signals.loc[exit_time]
print(f"\n{'='*60}")
print(f"CANDLE AT EXIT TIME ({exit_time}):")
print(f"{'='*60}")
print(f"Signal: {exit_candle['signal']} {'(SELL)' if exit_candle['signal'] == -1 else '(BUY)' if exit_candle['signal'] == 1 else '(NONE)'}")
print(f"Close: ${df_window.loc[exit_time, 'close']:.2f}")

# Now check backtester config
config = build_backtest_config(params, 10000)
print(f"\n{'='*60}")
print(f"BACKTESTER CONFIG:")
print(f"{'='*60}")
print(f"enable_signal_debouncing: {config.enable_signal_debouncing}")
print(f"sl_cooldown_minutes: {config.sl_cooldown_minutes}")
print(f"tp_cooldown_minutes: {config.tp_cooldown_minutes}")
print(f"enable_event_blocking: {config.enable_event_blocking}")
print(f"enable_eod_blackout: {config.enable_eod_blackout}")
print(f"enable_friday_filter: {config.enable_friday_filter}")

# Check what orders were opened after this exit
next_orders = orders[orders['entry_time'] > exit_time].head(3)
print(f"\n{'='*60}")
print(f"NEXT 3 ORDERS AFTER REVERSE SIGNAL EXIT:")
print(f"{'='*60}")
for _, order in next_orders.iterrows():
    time_diff = (order['entry_time'] - exit_time).total_seconds() / 60
    print(f"  {order['entry_time']} ({time_diff:.0f} mins later): {order['side']} @ ${order['entry_price']:.2f}")

print(f"\n{'='*60}")
print(f"ANALYSIS:")
print(f"{'='*60}")
print(f"At {exit_time}:")
print(f"1. BUY position closed due to SELL signal (Reverse Signal)")
print(f"2. Signal value at this candle: {exit_candle['signal']}")
if exit_candle['signal'] == -1:
    print(f"3. ✅ SELL signal exists - should open SELL position")
    print(f"4. ❌ BUT: No SELL order was created!")
    print(f"5. Possible reasons:")
    print(f"   - Cooldown blocking (check if last_side == SELL)")
    print(f"   - EOD blackout blocking")
    print(f"   - Friday filter blocking")
    print(f"   - Event blocking")
    print(f"   - Bug in backtester logic")
else:
    print(f"3. ❌ NO SELL signal at exit time - this explains why no SELL order")
