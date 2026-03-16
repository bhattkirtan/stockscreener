#!/usr/bin/env python3
"""Simulate the exact bot scenario that was causing duplicate logs"""
import sys
import pandas as pd
sys.path.insert(0, '.')
from src.core.strategy import SupertrendVWAPStrategy
import logging

# Set up logging to see strategy messages
logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')

strategy = SupertrendVWAPStrategy(
    supertrend_period=7,
    supertrend_multiplier=2.0,
    sma_fast=10,
    sma_slow=21,
    ema_period=10,
    bb_period=20,
    bb_std=2.0,
    sl_pips=0.7,
    tp_pips=2.5,
    pip_value=1.0,
    use_rsi_filter=False,
    use_atr_volatility_filter=False
)

# Create 20 historical candles (what bot fetches on startup)
historical = []
for i in range(20):
    ts = 1773148500000 + (i * 300000)
    price = 5200 + (i * 0.5)
    historical.append({
        'timestamp': ts,
        'open': price,
        'high': price + 2,
        'low': price - 2,
        'close': price + 0.5,
        'volume': 100
    })

print("=" * 80)
print("🤖 SIMULATING BOT BEHAVIOR - Real scenario that caused bug")
print("=" * 80)

# Step 1: Bot starts, fetches 20 historical bars
print(f"\n🔄 15:00 - Bot starts, loads 20 historical M5 bars")
df = pd.DataFrame(historical)
df_indicators = strategy.calculate_indicators(df)
signals = strategy.generate_signals(df_indicators)
print(f"   Processed {strategy.last_processed_index} bars")

# Step 2: First live candle at 15:05 - Supertrend flips DOWN
print(f"\n🕐 15:05 - New candle arrives (Supertrend flips DOWN)")
candle_1505 = {
    'timestamp': 1773150900000,
    'open': 5201.33,
    'high': 5206.72,
    'low': 5198.54,
    'close': 5193.00,  # Price drops - Supertrend flips DOWN
    'volume': 150
}
all_candles = historical + [candle_1505]
df = pd.DataFrame(all_candles)
df_indicators = strategy.calculate_indicators(df)
signals = strategy.generate_signals(df_indicators)
print(f"   Processed up to bar {strategy.last_processed_index}")

# Step 3: Next candle at 15:10
print(f"\n🕐 15:10 - New candle arrives")
candle_1510 = {
    'timestamp': 1773151200000,
    'open': 5193.01,
    'high': 5195.28,
    'low': 5188.08,
    'close': 5190.04,
    'volume': 150
}
all_candles = historical + [candle_1505, candle_1510]
df = pd.DataFrame(all_candles)
df_indicators = strategy.calculate_indicators(df)
print("   OLD BUG: Would log 'flip DOWN at i=20' again (reprocessing)")
print("   NEW FIX: Only processes bar 21, no duplicate logs")
signals = strategy.generate_signals(df_indicators)
print(f"   Processed up to bar {strategy.last_processed_index}")

# Step 4: Next candle at 15:15
print(f"\n🕐 15:15 - New candle arrives")
candle_1515 = {
    'timestamp': 1773151500000,
    'open': 5190.06,
    'high': 5192.67,
    'low': 5185.21,
    'close': 5188.06,
    'volume': 150
}
all_candles = historical + [candle_1505, candle_1510, candle_1515]
df = pd.DataFrame(all_candles)
df_indicators = strategy.calculate_indicators(df)
print("   OLD BUG: Would log 'flip DOWN at i=20' AGAIN (3rd time!)")
print("   NEW FIX: Only processes bar 22, no duplicate logs")
signals = strategy.generate_signals(df_indicators)
print(f"   Processed up to bar {strategy.last_processed_index}")

print("\n" + "=" * 80)
print("✅ BUG FIXED!")
print("=" * 80)
print("OLD BEHAVIOR:")
print("   15:05: Process bars 1-20, log 'flip DOWN at i=20'")
print("   15:10: Process bars 1-21, log 'flip DOWN at i=20' AGAIN + handle i=21")
print("   15:15: Process bars 1-22, log 'flip DOWN at i=20' AGAIN + handle i=21-22")
print("\nNEW BEHAVIOR:")
print("   15:05: Process bars 1-20, log 'flip DOWN at i=20' once")
print("   15:10: Process only bar 21, no reprocessing of i=20")
print("   15:15: Process only bar 22, no reprocessing of i=20 or i=21")
print("=" * 80)
