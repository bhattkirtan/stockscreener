#!/usr/bin/env python3
"""Check if the strategy generates SELL signals"""

import pandas as pd
from src.optimization.worker import build_strategy

# Load data
print("Loading data...")
df = pd.read_csv('data/GOLD_M5_150000bars.csv', parse_dates=['timestamp'])
df.set_index('timestamp', inplace=True)
print(f"Loaded {len(df)} bars")

# Build strategy with exact same params as backtest
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
    'pip_value': 1.0
}

print("\nGenerating signals...")
strategy = build_strategy(params)
df_indicators = strategy.calculate_indicators(df.copy())
signals = strategy.generate_signals(df_indicators)

# Count signals
buy_count = (signals['signal'] == 1).sum()
sell_count = (signals['signal'] == -1).sum()
no_signal_count = (signals['signal'] == 0).sum()

print(f"\n{'='*60}")
print(f"SIGNAL GENERATION RESULTS")
print(f"{'='*60}")
print(f"Total bars: {len(signals):,}")
print(f"BUY signals (signal=1): {buy_count:,} ({buy_count/len(signals)*100:.2f}%)")
print(f"SELL signals (signal=-1): {sell_count:,} ({sell_count/len(signals)*100:.2f}%)")
print(f"No signal (signal=0): {no_signal_count:,} ({no_signal_count/len(signals)*100:.2f}%)")
print(f"\n✅ Strategy generates both BUY and SELL signals: {buy_count > 0 and sell_count > 0}")

# Show some example SELL signals
if sell_count > 0:
    print(f"\n{'='*60}")
    print(f"EXAMPLE SELL SIGNALS (first 5):")
    print(f"{'='*60}")
    sell_signals = signals[signals['signal'] == -1].head(5)
    for idx, row in sell_signals.iterrows():
        print(f"\n📅 {idx}")
        print(f"   Signal: SELL (-1)")
        print(f"   Entry Price: ${row['entry_price']:.2f}")
        print(f"   Stop Loss: ${row['stop_loss']:.2f}")
        print(f"   Take Profit: ${row['take_profit']:.2f}")
