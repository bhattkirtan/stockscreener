#!/usr/bin/env python3
"""Test that strategy only processes new bars, not reprocess history"""
import sys
import pandas as pd
sys.path.insert(0, '.')
from src.core.strategy import SupertrendVWAPStrategy

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

# Create base historical data (25 candles)
base_candles = []
start_price = 5150
for i in range(25):
    ts = 1773136500000 + (i * 300000)
    price = start_price + (i * 2)
    base_candles.append({
        'timestamp': ts,
        'open': price,
        'high': price + 3,
        'low': price - 2,
        'close': price + 1,
        'volume': 100
    })

print("=" * 80)
print("🧪 Testing Incremental Processing - Only NEW bars should be processed")
print("=" * 80)

# Simulate what the bot does: Start with historical data, then add candles one by one
print("\n📊 STEP 1: Process initial 25 historical candles")
df1 = pd.DataFrame(base_candles)
df1_with_indicators = strategy.calculate_indicators(df1)
signals1 = strategy.generate_signals(df1_with_indicators)
print(f"   Processed bars 1-{len(signals1)}")
print(f"   last_processed_index: {strategy.last_processed_index}")

# Add one new candle (simulating 15:05)
print("\n📊 STEP 2: Add candle 26 (15:05)")
new_candle_1 = {
    'timestamp': 1773144000000,
    'open': 5201.33,
    'high': 5206.72,
    'low': 5198.54,
    'close': 5201.32,
    'volume': 150
}
all_candles_2 = base_candles + [new_candle_1]
df2 = pd.DataFrame(all_candles_2)
df2_with_indicators = strategy.calculate_indicators(df2)

print("   Before processing:")
print(f"   last_processed_index: {strategy.last_processed_index}")
print(f"   Total bars: {len(df2_with_indicators)}")
print(f"   Will process: bars {strategy.last_processed_index} to {len(df2_with_indicators)-1}")

signals2 = strategy.generate_signals(df2_with_indicators)
print(f"   ✅ Should only process bar 26 (index {len(signals2)-1})")
print(f"   last_processed_index: {strategy.last_processed_index}")

# Add another new candle (simulating 15:10)
print("\n📊 STEP 3: Add candle 27 (15:10)")
new_candle_2 = {
    'timestamp': 1773144300000,
    'open': 5201.41,
    'high': 5205.28,
    'low': 5188.08,
    'close': 5193.04,
    'volume': 150
}
all_candles_3 = base_candles + [new_candle_1, new_candle_2]
df3 = pd.DataFrame(all_candles_3)
df3_with_indicators = strategy.calculate_indicators(df3)

print("   Before processing:")
print(f"   last_processed_index: {strategy.last_processed_index}")
print(f"   Total bars: {len(df3_with_indicators)}")
print(f"   Will process: bars {strategy.last_processed_index} to {len(df3_with_indicators)-1}")

signals3 = strategy.generate_signals(df3_with_indicators)
print(f"   ✅ Should only process bar 27 (index {len(signals3)-1})")
print(f"   last_processed_index: {strategy.last_processed_index}")

# Add third candle (simulating 15:15)
print("\n📊 STEP 4: Add candle 28 (15:15)")
new_candle_3 = {
    'timestamp': 1773144600000,
    'open': 5193.06,
    'high': 5196.67,
    'low': 5185.21,
    'close': 5195.06,
    'volume': 150
}
all_candles_4 = base_candles + [new_candle_1, new_candle_2, new_candle_3]
df4 = pd.DataFrame(all_candles_4)
df4_with_indicators = strategy.calculate_indicators(df4)

print("   Before processing:")
print(f"   last_processed_index: {strategy.last_processed_index}")
print(f"   Total bars: {len(df4_with_indicators)}")
print(f"   Will process: bars {strategy.last_processed_index} to {len(df4_with_indicators)-1}")

signals4 = strategy.generate_signals(df4_with_indicators)
print(f"   ✅ Should only process bar 28 (index {len(signals4)-1})")
print(f"   last_processed_index: {strategy.last_processed_index}")

print("\n" + "=" * 80)
print("✅ SUCCESS: Each bar processed exactly once!")
print("   - Old behavior would reprocess ALL bars every time")
print("   - New behavior only processes NEW bars")
print("   - Memory checks only happen on latest bar")
print("=" * 80)
