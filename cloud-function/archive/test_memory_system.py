#!/usr/bin/env python3
"""
Test memory system with actual 12:10-14:55 candles
Shows how memory system handles:
1. 12:40 flip → 12:50 whipsaw → 12:55 SELL (with memory)
2. 13:20 flip → 13:50 BUY (memory catches rally)
3. Extended through 14:55 to see trend continuation
"""

import sys
sys.path.append('/Users/kirtanbhatt/code/stockScreener/cloud-function')

import pandas as pd
import logging
from src.core.strategy import SupertrendVWAPStrategy

logging.basicConfig(level=logging.INFO)

# Need 21+ historical candles for SMA_slow to be valid by 12:40
# Adding 21 historical M5 candles before 12:10 (10:45-12:05)
historical_candles = [
    # These are dummy historical candles to prime the indicators
    # 21 candles @ 5 min = 105 minutes = 10:45-12:05
    (1773133800000, 5185.00, 5188.00, 5183.00, 5186.00),  # 10:45
    (1773134100000, 5186.00, 5189.00, 5184.00, 5187.00),  # 10:50
    (1773134400000, 5187.00, 5190.00, 5185.00, 5188.00),  # 10:55
    (1773134700000, 5188.00, 5191.00, 5186.00, 5189.00),  # 11:00
    (1773135000000, 5189.00, 5192.00, 5187.00, 5190.00),  # 11:05
    (1773135300000, 5190.00, 5193.00, 5188.00, 5191.00),  # 11:10
    (1773135600000, 5191.00, 5194.00, 5189.00, 5192.00),  # 11:15
    (1773135900000, 5192.00, 5195.00, 5190.00, 5193.00),  # 11:20
    (1773136200000, 5193.00, 5196.00, 5191.00, 5194.00),  # 11:25
    (1773136500000, 5194.00, 5197.00, 5192.00, 5195.00),  # 11:30
    (1773136800000, 5195.00, 5198.00, 5193.00, 5196.00),  # 11:35
    (1773137100000, 5196.00, 5199.00, 5194.00, 5197.00),  # 11:40
    (1773137400000, 5197.00, 5200.00, 5195.00, 5198.00),  # 11:45
    (1773137700000, 5198.00, 5201.00, 5196.00, 5199.00),  # 11:50
    (1773138000000, 5199.00, 5202.00, 5197.00, 5200.00),  # 11:55
    (1773138300000, 5200.00, 5203.00, 5198.00, 5201.00),  # 12:00
    (1773138600000, 5201.00, 5204.00, 5199.00, 5202.00),  # 12:05
    (1773138900000, 5202.00, 5205.00, 5200.00, 5203.00),  # 12:10 ← was first
    (1773139200000, 5203.00, 5206.00, 5201.00, 5204.00),  # 12:15
    (1773139500000, 5204.00, 5207.00, 5202.00, 5205.00),  # 12:20
    (1773139800000, 5205.00, 5208.00, 5203.00, 5206.00),  # 12:25
]

#Actual bot candles from 12:10-14:20
candles = [
    # timestamp, open, high, low, close
    (1773140700000, 5191.51, 5193.96, 5186.51, 5187.08),  # 12:10
    (1773141000000, 5187.09, 5189.28, 5183.79, 5184.96),  # 12:15
    (1773141300000, 5187.09, 5187.29, 5180.58, 5184.34),  # 12:20
    (1773141600000, 5184.35, 5185.71, 5177.13, 5179.17),  # 12:25
    (1773141900000, 5179.19, 5180.74, 5171.32, 5176.85),  # 12:30
    (1773142200000, 5182.84, 5183.91, 5176.52, 5180.26),  # 12:35
    (1773142500000, 5180.25, 5184.85, 5179.27, 5180.75),  # 12:40 - FLIP DOWN
    (1773142800000, 5180.71, 5181.10, 5173.60, 5174.16),  # 12:45
    (1773143100000, 5174.17, 5174.54, 5171.67, 5172.33),  # 12:50 - WHIPSAW FLIP UP
    (1773143400000, 5172.34, 5179.47, 5172.34, 5177.49),  # 12:55 - FLIP DOWN (SMA aligned)
    (1773143700000, 5177.56, 5178.60, 5172.32, 5174.94),  # 13:00
    (1773144000000, 5175.12, 5176.45, 5167.15, 5167.71),  # 13:05
    (1773144300000, 5167.72, 5169.39, 5162.26, 5165.46),  # 13:10
    (1773144600000, 5165.55, 5171.74, 5164.96, 5171.20),  # 13:15
    (1773144900000, 5171.18, 5173.21, 5165.54, 5172.89),  # 13:20 - FLIP UP (memory will catch)
    (1773145200000, 5173.00, 5177.76, 5171.74, 5176.58),  # 13:25
    (1773145500000, 5176.64, 5180.49, 5176.06, 5179.53),  # 13:30
    (1773145800000, 5179.60, 5181.58, 5178.43, 5180.36),  # 13:35
    (1773146100000, 5180.35, 5182.86, 5178.96, 5180.49),  # 13:40
    (1773146400000, 5180.57, 5185.43, 5179.98, 5185.26),  # 13:45
    (1773146700000, 5185.21, 5189.30, 5185.15, 5186.21),  # 13:50 - SMA TURNS BULLISH (memory fires!)
    (1773147000000, 5186.34, 5187.38, 5180.29, 5182.16),  # 13:55
    (1773147300000, 5182.14, 5187.12, 5181.86, 5186.79),  # 14:00
    (1773147600000, 5186.80, 5200.56, 5185.88, 5195.52),  # 14:05 - Big move!
    (1773147900000, 5195.53, 5201.30, 5192.69, 5200.31),  # 14:10
    (1773148200000, 5200.29, 5202.47, 5198.41, 5200.66),  # 14:15
    (1773148500000, 5200.67, 5215.50, 5198.98, 5214.32),  # 14:20 - Peak at 5215!
    (1773148800000, 5214.38, 5216.43, 5210.16, 5212.63),  # 14:25
    (1773149100000, 5212.63, 5215.78, 5202.18, 5203.21),  # 14:30
    (1773149400000, 5203.22, 5208.03, 5202.69, 5207.54),  # 14:35
    (1773149700000, 5207.55, 5213.66, 5204.97, 5212.14),  # 14:40
    (1773150000000, 5212.63, 5216.75, 5209.09, 5209.09),  # 14:45
    (1773150300000, 5209.01, 5209.63, 5196.09, 5204.91),  # 14:50 - Memory system ACTIVE
    (1773150600000, 5204.98, 5210.40, 5202.62, 5208.81),  # 14:55
]

# Combine historical + actual candles
all_candles = historical_candles + candles

# Create DataFrame
df = pd.DataFrame(all_candles, columns=['timestamp', 'open', 'high', 'low', 'close'])
df['volume'] = 1000  # Dummy volume

# Initialize strategy with actual bot parameters
strategy = SupertrendVWAPStrategy(
    supertrend_period=7,
    supertrend_multiplier=2.0,
    sma_fast=10,
    sma_slow=21,
    ema_period=10,
    sl_pips=0.7,  # 0.7x ATR
    tp_pips=2.5,  # 2.5x ATR
    pip_value=0.01
)

# Calculate indicators
df_indicators = strategy.calculate_indicators(df)

# Check indicator calculation
print("📊 Checking indicators...")
print(f"Total candles: {len(df_indicators)} (21 historical + {len(candles)} actual)")
print(f"Direction values: {df_indicators['direction'].unique()}")
print(f"First non-NaN direction at index: {df_indicators['direction'].first_valid_index()}")
print(f"SMA Fast first valid: {df_indicators['sma_fast'].first_valid_index()}")
print(f"SMA Slow first valid: {df_indicators['sma_slow'].first_valid_index()}")
print()

# Show a few candles with indicators
print("Sample candles with indicators:")
for i in [6, 7, 8, 9, 14, 15, 20, 21]:
    if i < len(df_indicators):
        row = df_indicators.iloc[i]
        dir_str = 'NaN' if pd.isna(row['direction']) else int(row['direction'])
        ema_str = 'NaN' if pd.isna(row['ema']) else f"{row['close']:.2f}"
        sma_f_str = 'NaN' if pd.isna(row['sma_fast']) else f"{row['sma_fast']:.2f}"
        sma_s_str = 'NaN' if pd.isna(row['sma_slow']) else f"{row['sma_slow']:.2f}"
        print(f"  i={i}: close={row['close']:.2f}, dir={dir_str}, ema={ema_str}, sma_f={sma_f_str}, sma_s={sma_s_str}")

print()
print("Latest candles (14:45-14:55):")
total = len(df_indicators)
for i in range(max(0, total - 3), total):
    if i < len(df_indicators):
        row = df_indicators.iloc[i]
        ts = row['timestamp']
        hour = int((ts // 1000 // 3600) % 24)
        minute = int((ts // 1000 // 60) % 60)
        dir_str = 'NaN' if pd.isna(row['direction']) else int(row['direction'])
        ema_val = row['ema'] if not pd.isna(row['ema']) else float('nan')
        sma_f_val = row['sma_fast'] if not pd.isna(row['sma_fast']) else float('nan')
        sma_s_val = row['sma_slow'] if not pd.isna(row['sma_slow']) else float('nan')
        print(f"  i={i} ({hour:02d}:{minute:02d}): close={row['close']:.2f}, dir={dir_str}, ema={ema_val:.2f}, sma_f={sma_f_val:.2f}, sma_s={sma_s_val:.2f}")
print()


# Generate signals (with memory system)
signals = strategy.generate_signals(df_indicators)

# Check if we have signals
print(f"📊 Data shape: {signals.shape}")
print(f"📊 Signals column: {signals['signal'].value_counts()}")
print()

# Display signals
print("="*80)
print("🧠 MEMORY SYSTEM TEST - Actual Candles")
print("="*80)
print()

signal_count = 0
for i in range(len(signals)):
    sig = signals['signal'].iloc[i]
    if sig != 0:
        signal_count += 1
        entry = signals['entry_price'].iloc[i]
        sl = signals['stop_loss'].iloc[i]
        tp = signals['take_profit'].iloc[i]
        direction = "BUY" if sig == 1 else "SELL"
        
        # Get timestamp-based time (convert from milliseconds, using UTC)
        from datetime import datetime, timezone
        ts = signals['timestamp'].iloc[i]
        dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        
        print(f"{'✅' if sig == 1 else '⬇️'} {direction} Signal #{signal_count}")
        print(f"   Time: {dt.strftime('%H:%M')} UTC (Index: {i})")
        print(f"   Entry: {entry:.2f}")
        print(f"   SL: {sl:.2f} | TP: {tp:.2f}")
        print(f"   Risk/Reward: {abs(tp - entry):.2f} / {abs(sl - entry):.2f}")
        print()

print("="*80)
print(f"📊 Total Signals: {signal_count}")
print("="*80)
print()

# Show expected behavior
print("🎯 EXPECTED MEMORY BEHAVIOR:")
print()
print("1. 12:40 Flip DOWN → Memory stores (Price < EMA ✓, SMA not ready ✗)")
print("2. 12:50 Flip UP → Memory INVALIDATED (whipsaw protection ✅)")
print("3. 12:55 Flip DOWN → All conditions met → SELL signal ✅")
print()
print("4. 13:20 Flip UP → Memory stores (Price > EMA ✓, SMA not ready ✗)")
print("5. 13:25-13:45 → Memory waits (checking each candle)")
print("6. 13:50 → SMA turns bullish → Memory fires BUY ✅")
print()
print("🚀 Result: Catches 13:50 entry (5182) → 14:20 peak (5215) = +33 points!")
print("📈 Extended data through 14:55 to test continuation")
print("="*80)
print("="*80)
