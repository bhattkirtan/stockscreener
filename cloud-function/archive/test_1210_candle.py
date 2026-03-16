#!/usr/bin/env python3
"""Unit test for 12:10 candle signal generation"""
import sys
import pandas as pd
sys.path.insert(0, '.')
from src.core.strategy import SupertrendVWAPStrategy

# Create strategy with same params as bot
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

# Need 21+ candles for indicators - create base candles then add the 12:10 candle
base_candles = []
start_price = 5150
for i in range(14):
    ts = 1773136500000 + (i * 300000)  # 5-min intervals
    price = start_price + (i * 2.5)
    base_candles.append({
        'timestamp': ts,
        'open': price,
        'high': price + 3,
        'low': price - 2,
        'close': price + 1,
        'volume': 100
    })

# Recent candles leading to 12:10 + actual bot candles
test_candles = [
    {'timestamp': 1773138600000, 'open': 5185.0, 'high': 5188.0, 'low': 5182.0, 'close': 5183.5, 'volume': 100},
    {'timestamp': 1773138900000, 'open': 5183.5, 'high': 5186.0, 'low': 5180.0, 'close': 5181.0, 'volume': 100},
    {'timestamp': 1773139200000, 'open': 5181.0, 'high': 5184.0, 'low': 5178.0, 'close': 5179.5, 'volume': 100},
    {'timestamp': 1773139500000, 'open': 5179.5, 'high': 5182.0, 'low': 5176.0, 'close': 5177.0, 'volume': 100},
    {'timestamp': 1773139800000, 'open': 5177.0, 'high': 5180.0, 'low': 5174.0, 'close': 5175.5, 'volume': 100},
    {'timestamp': 1773140100000, 'open': 5175.5, 'high': 5178.0, 'low': 5172.0, 'close': 5173.08, 'volume': 100},
    {'timestamp': 1773140400000, 'open': 5173.08, 'high': 5178.04, 'low': 5172.22, 'close': 5177.04, 'volume': 100},
    # ACTUAL BOT CANDLES from logs (CORRECTED):
    {'timestamp': 1773140700000, 'open': 5181.40, 'high': 5190.37, 'low': 5181.17, 'close': 5190.28, 'volume': 150},  # 12:10
    {'timestamp': 1773141000000, 'open': 5190.25, 'high': 5191.78, 'low': 5186.73, 'close': 5187.07, 'volume': 150},  # 12:15
    {'timestamp': 1773141300000, 'open': 5187.09, 'high': 5187.29, 'low': 5180.58, 'close': 5184.34, 'volume': 150},  # 12:20
    {'timestamp': 1773141600000, 'open': 5184.35, 'high': 5185.71, 'low': 5177.13, 'close': 5179.17, 'volume': 150},  # 12:25
    {'timestamp': 1773141900000, 'open': 5179.19, 'high': 5180.74, 'low': 5171.32, 'close': 5176.85, 'volume': 150},  # 12:30
    {'timestamp': 1773142200000, 'open': 5182.84, 'high': 5183.91, 'low': 5176.52, 'close': 5180.26, 'volume': 150},  # 12:35
    {'timestamp': 1773142500000, 'open': 5180.25, 'high': 5184.85, 'low': 5179.27, 'close': 5180.75, 'volume': 150},  # 12:40 ← Supertrend flip
    {'timestamp': 1773142800000, 'open': 5180.71, 'high': 5181.10, 'low': 5173.60, 'close': 5174.16, 'volume': 150},  # 12:45
    {'timestamp': 1773143100000, 'open': 5174.17, 'high': 5174.54, 'low': 5171.67, 'close': 5172.33, 'volume': 150},  # 12:50
    {'timestamp': 1773143400000, 'open': 5172.34, 'high': 5179.47, 'low': 5172.34, 'close': 5177.49, 'volume': 150},  # 12:55 ← ACTUAL BOT DATA
    {'timestamp': 1773143700000, 'open': 5177.56, 'high': 5178.60, 'low': 5172.32, 'close': 5174.94, 'volume': 150},  # 13:00
    {'timestamp': 1773144000000, 'open': 5175.12, 'high': 5176.45, 'low': 5167.15, 'close': 5167.71, 'volume': 150},  # 13:05
    {'timestamp': 1773144300000, 'open': 5167.72, 'high': 5169.39, 'low': 5162.26, 'close': 5165.46, 'volume': 150},  # 13:10
    {'timestamp': 1773144600000, 'open': 5165.55, 'high': 5171.74, 'low': 5164.96, 'close': 5171.20, 'volume': 150},  # 13:15
    {'timestamp': 1773144900000, 'open': 5171.18, 'high': 5173.21, 'low': 5165.54, 'close': 5172.89, 'volume': 150},  # 13:20
    {'timestamp': 1773145200000, 'open': 5173.00, 'high': 5177.76, 'low': 5171.74, 'close': 5176.58, 'volume': 150},  # 13:25
    {'timestamp': 1773145500000, 'open': 5176.64, 'high': 5180.49, 'low': 5176.06, 'close': 5179.53, 'volume': 150},  # 13:30
    {'timestamp': 1773145800000, 'open': 5179.60, 'high': 5181.58, 'low': 5178.43, 'close': 5180.36, 'volume': 150},  # 13:35
    {'timestamp': 1773146100000, 'open': 5180.35, 'high': 5182.86, 'low': 5178.96, 'close': 5180.49, 'volume': 150},  # 13:40
    {'timestamp': 1773146400000, 'open': 5180.57, 'high': 5185.43, 'low': 5179.98, 'close': 5185.26, 'volume': 150},  # 13:45
    {'timestamp': 1773146700000, 'open': 5185.21, 'high': 5189.30, 'low': 5185.15, 'close': 5186.21, 'volume': 150},  # 13:50
    {'timestamp': 1773147000000, 'open': 5186.34, 'high': 5187.38, 'low': 5180.29, 'close': 5182.16, 'volume': 150},  # 13:55
    {'timestamp': 1773147300000, 'open': 5182.14, 'high': 5187.12, 'low': 5181.86, 'close': 5186.79, 'volume': 150},  # 14:00
    {'timestamp': 1773147600000, 'open': 5186.80, 'high': 5200.56, 'low': 5185.88, 'close': 5195.52, 'volume': 150},  # 14:05 - Big jump!
    {'timestamp': 1773147900000, 'open': 5195.53, 'high': 5201.30, 'low': 5192.69, 'close': 5200.31, 'volume': 150},  # 14:10
    {'timestamp': 1773148200000, 'open': 5200.29, 'high': 5202.47, 'low': 5198.41, 'close': 5200.66, 'volume': 150},  # 14:15
    {'timestamp': 1773148500000, 'open': 5200.67, 'high': 5215.50, 'low': 5198.98, 'close': 5214.32, 'volume': 150},  # 14:20 - Huge rally!
    {'timestamp': 1773148800000, 'open': 5214.33, 'high': 5218.22, 'low': 5209.17, 'close': 5210.67, 'volume': 150},  # 14:25
    {'timestamp': 1773149100000, 'open': 5210.69, 'high': 5212.75, 'low': 5203.97, 'close': 5207.12, 'volume': 150},  # 14:30
    {'timestamp': 1773149400000, 'open': 5207.14, 'high': 5208.81, 'low': 5201.98, 'close': 5203.45, 'volume': 150},  # 14:35
    {'timestamp': 1773149700000, 'open': 5203.46, 'high': 5206.32, 'low': 5199.58, 'close': 5201.78, 'volume': 150},  # 14:40
    {'timestamp': 1773150000000, 'open': 5201.79, 'high': 5205.83, 'low': 5198.42, 'close': 5202.15, 'volume': 150},  # 14:45
    {'timestamp': 1773150300000, 'open': 5202.16, 'high': 5204.71, 'low': 5197.89, 'close': 5199.23, 'volume': 150},  # 14:50
    {'timestamp': 1773150600000, 'open': 5199.24, 'high': 5202.58, 'low': 5196.15, 'close': 5198.77, 'volume': 150},  # 14:55
    {'timestamp': 1773150900000, 'open': 5198.78, 'high': 5203.41, 'low': 5196.83, 'close': 5201.32, 'volume': 150},  # 15:00
    {'timestamp': 1773151200000, 'open': 5201.33, 'high': 5206.72, 'low': 5198.54, 'close': 5201.32, 'volume': 150},  # 15:05 ← FLIP STORED
    {'timestamp': 1773151500000, 'open': 5201.41, 'high': 5205.28, 'low': 5188.08, 'close': 5193.04, 'volume': 150},  # 15:10 ← CANCELLED + RE-STORED
    {'timestamp': 1773151800000, 'open': 5193.06, 'high': 5196.67, 'low': 5185.21, 'close': 5195.06, 'volume': 150},  # 15:15 ← CANCELLED + RE-STORED AGAIN
]

all_candles = base_candles + test_candles
df = pd.DataFrame(all_candles)

# Calculate indicators first, then generate signals
df_with_indicators = strategy.calculate_indicators(df)
signals = strategy.generate_signals(df_with_indicators)

# Display candles - show last N or all if less
num_candles = len(signals)
display_count = min(25, num_candles)
print('=' * 80)
print(f'📊 Signal Generation Test - Last {display_count} candles')
print('=' * 80)
for i in range(num_candles - display_count, num_candles):
    row = signals.iloc[i]
    ts = int(row['timestamp'])
    from datetime import datetime
    time_str = datetime.fromtimestamp(ts/1000).strftime('%H:%M')
    
    print(f'\n🕐 {time_str} (idx {i}): {ts}')
    print(f'  OHLC: O:{row["open"]:.2f} H:{row["high"]:.2f} L:{row["low"]:.2f} C:{row["close"]:.2f}')
    print(f'  Direction: {row["direction"]:2.0f} | Supertrend: {row["supertrend"]:.2f}')
    print(f'  EMA: {row["ema"]:.2f} | SMA Fast: {row["sma_fast"]:.2f} | SMA Slow: {row["sma_slow"]:.2f}')
    print(f'  Signal: {row["signal"]:2.0f}', end='')
    if row['signal'] == 1:
        print(f' ✅ BUY | Entry: {row["entry_price"]:.2f} | SL: {row["stop_loss"]:.2f} | TP: {row["take_profit"]:.2f}')
    elif row['signal'] == -1:
        print(f' ⬇️ SELL | Entry: {row["entry_price"]:.2f} | SL: {row["stop_loss"]:.2f} | TP: {row["take_profit"]:.2f}')
    else:
        print(' ⏸️ NO SIGNAL')

# Trend change analysis for key transitions
print(f'\n📈 Trend Analysis (last {min(24, num_candles-1)} transitions):')
for i in range(max(1, num_candles - 24), num_candles):
    prev_dir = signals.iloc[i-1]['direction']
    curr_dir = signals.iloc[i]['direction']
    ts = int(signals.iloc[i]['timestamp'])
    from datetime import datetime
    time_str = datetime.fromtimestamp(ts/1000).strftime('%H:%M')
    
    print(f'  {time_str}: {prev_dir:.0f} → {curr_dir:.0f}', end='')
    if prev_dir == -1 and curr_dir == 1:
        print(' ✅ DOWNTREND → UPTREND (BUY TRIGGER)')
    elif prev_dir == 1 and curr_dir == -1:
        print(' ⬇️ UPTREND → DOWNTREND (SELL TRIGGER)')
    else:
        print(' (no change)')

# MEMORY SCENARIO ANALYSIS: If we remembered 12:40 conditions
print('\n' + '=' * 80)
print('🧠 MEMORY SCENARIO: Would waiting for SMA have worked?')
print('=' * 80)
print('At 12:40, Supertrend flipped down, but SMA still bullish (Fast > Slow)')
print('Let\'s check each candle after 12:40 for ALL 3 conditions:\n')

# Find the 12:40 candle index
target_ts = 1773142500000  # 12:40
idx_1240 = None
for i in range(len(signals)):
    if signals.iloc[i]['timestamp'] == target_ts:
        idx_1240 = i
        break

if idx_1240 and idx_1240 < len(signals):
    # Check candles after 12:40 (up to 20 candles or end of data)
    max_offset = min(23, len(signals) - idx_1240 - 1)
    for offset in range(0, max_offset):
        idx = idx_1240 + offset
        if idx >= len(signals):
            break
            
        row = signals.iloc[idx]
        ts = int(row['timestamp'])
        from datetime import datetime
        time_str = datetime.fromtimestamp(ts/1000).strftime('%H:%M')
        
        close = row['close']
        ema = row['ema']
        direction = row['direction']
        sma_fast = row['sma_fast']
        sma_slow = row['sma_slow']
        
        # Check conditions for SELL
        cond1 = direction == -1  # Supertrend downtrend
        cond2 = close < ema      # Price below EMA
        cond3 = sma_fast < sma_slow  # SMA trend bearish
        
        status = []
        if cond1: status.append('✓ ST↓')
        else: status.append('✗ ST↑')
        
        if cond2: status.append('✓ P<EMA')
        else: status.append('✗ P>EMA')
        
        if cond3: status.append('✓ SMA↓')
        else: status.append('✗ SMA↑')
        
        all_met = cond1 and cond2 and cond3
        
        print(f'{time_str}: {" ".join(status)} | Fast:{sma_fast:.2f} Slow:{sma_slow:.2f}', end='')
        if all_met:
            print(' 🎯 ALL CONDITIONS MET → TRADE!')
        else:
            print(f' ⏳ Waiting... ({sum([cond1, cond2, cond3])}/3)')

print('=' * 80)
