"""
Validate that all "Reverse Signal" exits in backtest are triggered by legitimate
strategy-level signals based on Supertrend + SMA/EMA conditions.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pandas as pd
from datetime import datetime
from src.core.strategy import SupertrendVWAPStrategy

# Load orders from backtest
orders_path = 'data/optimization/2026-03-26/run_20260326_090350/rank01_ST2.0_SMA25-30_BB2.0_PIP1_F20.0-40.0/orders.csv'
orders_df = pd.read_csv(orders_path)
orders_df['entry_time'] = pd.to_datetime(orders_df['entry_time'])
orders_df['exit_time'] = pd.to_datetime(orders_df['exit_time'])

# Filter only reverse signal exits
reverse_signal_trades = orders_df[orders_df['exit_reason'] == 'Reverse Signal'].copy()
print(f"\nFound {len(reverse_signal_trades)} trades that exited on 'Reverse Signal'")
print(f"Out of {len(orders_df)} total trades ({len(reverse_signal_trades)/len(orders_df)*100:.1f}%)")

# Get date range for data loading (only load what we need)
min_date = reverse_signal_trades['entry_time'].min()
max_date = reverse_signal_trades['exit_time'].max()
print(f"\nDate range: {min_date} to {max_date}")

# Load market data (filter to needed range + buffer for indicators)
print("Loading market data...")
df = pd.read_csv('data/GOLD_M5_150000bars.csv')
df['timestamp'] = pd.to_datetime(df['timestamp'])

# Filter to date range with 200-bar buffer before min_date for indicator warmup
df = df[df['timestamp'] >= min_date - pd.Timedelta(days=3)]  # 3 days buffer
df = df[df['timestamp'] <= max_date]
df.set_index('timestamp', inplace=True)
print(f"Loaded {len(df)} bars")

# Initialize strategy with same parameters as backtest
print("Initializing strategy...")
strategy = SupertrendVWAPStrategy(
    supertrend_period=7,
    supertrend_multiplier=2.0,
    sma_fast=25,
    sma_slow=30,
    ema_period=21,
    bb_period=20,
    bb_std=2.0,
    sl_pips=20.0,
    tp_pips=40.0,
    pip_value=1.0,
    use_rsi_filter=False,
    use_atr_volatility_filter=False,
    use_session_filter=False
)

# Calculate indicators and generate signals
print("Calculating indicators...")
df_with_indicators = strategy.calculate_indicators(df)

print("Generating signals...")
df_with_signals = strategy.generate_signals(df_with_indicators, live_mode=False)

print("\n" + "=" * 80)
print("VALIDATING 'REVERSE SIGNAL' EXITS")
print("=" * 80)

# Filter only reverse signal exits
reverse_signal_trades = orders_df[orders_df['exit_reason'] == 'Reverse Signal'].copy()
print(f"\nFound {len(reverse_signal_trades)} trades that exited on 'Reverse Signal'")
print(f"Out of {len(orders_df)} total trades ({len(reverse_signal_trades)/len(orders_df)*100:.1f}%)\n")

# Validate each reverse signal exit
invalid_exits = []
valid_exits = []

for idx, trade in reverse_signal_trades.iterrows():
    entry_time = trade['entry_time']
    exit_time = trade['exit_time']
    side = trade['side']
    
    # Check if exit time exists in data
    if exit_time not in df_with_signals.index:
        invalid_exits.append({
            'trade': trade,
            'reason': f"Exit time {exit_time} not found in market data"
        })
        continue
    
    # Get the signal at exit time
    exit_row = df_with_signals.loc[exit_time]
    exit_signal = exit_row['signal']
    
    # Check strategy conditions at exit time
    supertrend_dir = exit_row['direction']
    close = exit_row['close']
    ema = exit_row['ema']
    sma_fast = exit_row['sma_fast']
    sma_slow = exit_row['sma_slow']
    
    # For a valid reverse signal:
    # - BUY position must be closed by SELL signal (signal == -1)
    # - SELL position must be closed by BUY signal (signal == 1)
    expected_signal = -1 if side == 'BUY' else 1
    
    # Check if signal matches expectation
    if exit_signal != expected_signal:
        invalid_exits.append({
            'trade': trade,
            'reason': f"{side} position exited at {exit_time} but signal={exit_signal} (expected {expected_signal})",
            'st_dir': supertrend_dir,
            'close': close,
            'ema': ema,
            'sma_fast': sma_fast,
            'sma_slow': sma_slow
        })
        continue
    
    # Additional validation: Check if strategy conditions were met
    # BUY signal requires: Supertrend UP (1) + price > EMA + sma_fast > sma_slow (OR golden cross)
    # SELL signal requires: Supertrend DOWN (-1) + price < EMA + sma_fast < sma_slow (OR death cross)
    
    strategy_valid = False
    if expected_signal == 1:  # Expected BUY signal (closing SELL position)
        # Check lookback for Supertrend flip to uptrend
        lookback_idx = max(0, df_with_signals.index.get_loc(exit_time) - 1)
        if lookback_idx >= 0:
            prev_st_dir = df_with_signals.iloc[lookback_idx]['direction']
            trend_changed_to_up = (supertrend_dir == 1 and prev_st_dir == -1)
            
            # BUY conditions
            price_above_ema = close > ema
            sma_bullish = sma_fast > sma_slow
            
            strategy_valid = trend_changed_to_up and price_above_ema and sma_bullish
            
            if not strategy_valid:
                invalid_exits.append({
                    'trade': trade,
                    'reason': f"BUY signal at {exit_time} doesn't meet strategy conditions",
                    'trend_flip': trend_changed_to_up,
                    'price_above_ema': price_above_ema,
                    'sma_bullish': sma_bullish,
                    'st_dir': supertrend_dir,
                    'prev_st_dir': prev_st_dir,
                    'close': close,
                    'ema': ema,
                    'sma_fast': sma_fast,
                    'sma_slow': sma_slow
                })
                continue
                
    else:  # expected_signal == -1, Expected SELL signal (closing BUY position)
        # Check lookback for Supertrend flip to downtrend
        lookback_idx = max(0, df_with_signals.index.get_loc(exit_time) - 1)
        if lookback_idx >= 0:
            prev_st_dir = df_with_signals.iloc[lookback_idx]['direction']
            trend_changed_to_down = (supertrend_dir == -1 and prev_st_dir == 1)
            
            # SELL conditions
            price_below_ema = close < ema
            sma_bearish = sma_fast < sma_slow
            
            strategy_valid = trend_changed_to_down and price_below_ema and sma_bearish
            
            if not strategy_valid:
                invalid_exits.append({
                    'trade': trade,
                    'reason': f"SELL signal at {exit_time} doesn't meet strategy conditions",
                    'trend_flip': trend_changed_to_down,
                    'price_below_ema': price_below_ema,
                    'sma_bearish': sma_bearish,
                    'st_dir': supertrend_dir,
                    'prev_st_dir': prev_st_dir,
                    'close': close,
                    'ema': ema,
                    'sma_fast': sma_fast,
                    'sma_slow': sma_slow
                })
                continue
    
    # If we got here, the reverse signal is valid
    valid_exits.append({
        'time': exit_time,
        'side': side,
        'signal': exit_signal,
        'st_dir': supertrend_dir
    })

# Print results
print("\n" + "=" * 80)
print("VALIDATION RESULTS")
print("=" * 80)
print(f"\n✅ Valid Reverse Signals: {len(valid_exits)}/{len(reverse_signal_trades)} ({len(valid_exits)/len(reverse_signal_trades)*100:.1f}%)")
print(f"❌ Invalid Reverse Signals: {len(invalid_exits)}/{len(reverse_signal_trades)} ({len(invalid_exits)/len(reverse_signal_trades)*100:.1f}%)")

if invalid_exits:
    print("\n" + "=" * 80)
    print("❌ INVALID REVERSE SIGNAL EXITS FOUND:")
    print("=" * 80)
    for i, item in enumerate(invalid_exits[:10], 1):  # Show first 10
        print(f"\n{i}. {item['reason']}")
        if 'st_dir' in item:
            print(f"   ST_dir: {item['st_dir']}, Close: {item['close']:.2f}, EMA: {item['ema']:.2f}")
            print(f"   SMA Fast: {item['sma_fast']:.2f}, SMA Slow: {item['sma_slow']:.2f}")
        if 'trend_flip' in item:
            print(f"   Trend flip: {item['trend_flip']}, Price/EMA aligned: {item.get('price_above_ema', item.get('price_below_ema'))}, SMA aligned: {item.get('sma_bullish', item.get('sma_bearish'))}")
    
    if len(invalid_exits) > 10:
        print(f"\n... and {len(invalid_exits) - 10} more invalid exits")
    
    print("\n" + "=" * 80)
    print("❌ VALIDATION FAILED!")
    print("=" * 80)
    sys.exit(1)
else:
    print("\n" + "=" * 80)
    print("✅ ALL REVERSE SIGNAL EXITS ARE LEGITIMATE!")
    print("=" * 80)
    print("\nEvery 'Reverse Signal' exit was triggered by an actual strategy-level")
    print("signal meeting all required conditions:")
    print("  - Supertrend direction change")
    print("  - Price/EMA alignment")
    print("  - SMA fast/slow alignment or crossover")
    print("\n" + "=" * 80)
    sys.exit(0)
