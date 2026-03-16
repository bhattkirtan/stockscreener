#!/usr/bin/env python3
"""
Test Signal Generation Logic
Tests the trading bot's signal generation with historical data
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, '/Users/kirtanbhatt/code/stockScreener/cloud-function')

from src.core.strategy import SupertrendVWAPStrategy


def create_test_candles(trend='downtrend', num_candles=25):
    """
    Create test candle data with specific market conditions
    
    Args:
        trend: 'uptrend', 'downtrend', or 'sideways'
        num_candles: Number of candles to generate
    """
    base_price = 5200.0
    timestamps = []
    opens = []
    highs = []
    lows = []
    closes = []
    volumes = []
    
    current_time = datetime.now() - timedelta(minutes=5 * num_candles)
    
    for i in range(num_candles):
        timestamps.append(current_time.isoformat())
        
        if trend == 'downtrend':
            # Bearish trend: prices declining
            drift = -0.5
            open_price = base_price - (i * 2) + np.random.randn() * 2
            close_price = open_price + drift + np.random.randn() * 3
            
        elif trend == 'uptrend':
            # Bullish trend: prices rising
            drift = 0.5
            open_price = base_price + (i * 2) + np.random.randn() * 2
            close_price = open_price + drift + np.random.randn() * 3
            
        else:  # sideways
            # Consolidation: no clear trend
            open_price = base_price + np.random.randn() * 5
            close_price = open_price + np.random.randn() * 3
        
        high_price = max(open_price, close_price) + abs(np.random.randn() * 2)
        low_price = min(open_price, close_price) - abs(np.random.randn() * 2)
        volume = 1000 + np.random.randint(0, 500)
        
        opens.append(open_price)
        highs.append(high_price)
        lows.append(low_price)
        closes.append(close_price)
        volumes.append(volume)
        
        current_time += timedelta(minutes=5)
    
    df = pd.DataFrame({
        'timestamp': timestamps,
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': volumes
    })
    
    return df


def test_signal_generation():
    """Test signal generation with different market conditions"""
    
    print("=" * 80)
    print("🧪 TESTING SIGNAL GENERATION LOGIC")
    print("=" * 80)
    print()
    
    # Initialize strategy with trained parameters
    strategy = SupertrendVWAPStrategy(
        supertrend_period=7,
        multiplier=2.0,
        sma_fast=10,
        sma_slow=21,
        ema=10,
        sl_pips=0.7,
        tp_pips=2.5
    )
    
    # Test 1: Downtrend (should generate SELL signals)
    print("📉 TEST 1: Downtrend Market")
    print("-" * 80)
    df_down = create_test_candles(trend='downtrend', num_candles=25)
    df_with_indicators = strategy.calculate_indicators(df_down)
    
    # Get latest values
    latest = df_with_indicators.iloc[-1]
    prev = df_with_indicators.iloc[-2]
    
    print(f"  Latest Close: {latest['close']:.2f}")
    print(f"  Supertrend: {latest['supertrend']:.2f} ({'UPTREND' if latest['supertrend_direction'] == 1 else 'DOWNTREND'})")
    print(f"  SMA Fast: {latest['sma_fast']:.2f}")
    print(f"  SMA Slow: {latest['sma_slow']:.2f}")
    print(f"  EMA: {latest['ema']:.2f}")
    print(f"  ATR: {latest['atr']:.2f}")
    
    # Check signal conditions
    golden_cross = (latest['sma_fast'] > latest['sma_slow']) and (prev['sma_fast'] <= prev['sma_slow'])
    death_cross = (latest['sma_fast'] < latest['sma_slow']) and (prev['sma_fast'] >= prev['sma_slow'])
    
    print()
    print("  Signal Conditions:")
    print(f"    Supertrend Direction: {'UPTREND' if latest['supertrend_direction'] == 1 else 'DOWNTREND'}")
    print(f"    Price vs EMA: {latest['close']:.2f} {'>' if latest['close'] > latest['ema'] else '<'} {latest['ema']:.2f}")
    print(f"    SMA Fast vs Slow: {latest['sma_fast']:.2f} {'>' if latest['sma_fast'] > latest['sma_slow'] else '<'} {latest['sma_slow']:.2f}")
    print(f"    Golden Cross: {golden_cross}")
    print(f"    Death Cross: {death_cross}")
    print()
    
    # Determine signal
    if (latest['supertrend_direction'] == -1 and 
        latest['close'] < latest['ema'] and 
        (death_cross or latest['sma_fast'] < latest['sma_slow'])):
        
        sl = latest['close'] + (strategy.sl_pips * latest['atr'])
        tp = latest['close'] - (strategy.tp_pips * latest['atr'])
        
        print(f"  ✅ SELL SIGNAL GENERATED")
        print(f"     Entry: {latest['close']:.2f}")
        print(f"     Stop Loss: {sl:.2f} (+{(sl - latest['close']):.2f})")
        print(f"     Take Profit: {tp:.2f} (-{(latest['close'] - tp):.2f})")
        print(f"     Risk/Reward: 1:{(tp - latest['close']) / (sl - latest['close']):.2f}")
    elif (latest['supertrend_direction'] == 1 and 
          latest['close'] > latest['ema'] and 
          (golden_cross or latest['sma_fast'] > latest['sma_slow'])):
        
        sl = latest['close'] - (strategy.sl_pips * latest['atr'])
        tp = latest['close'] + (strategy.tp_pips * latest['atr'])
        
        print(f"  ✅ BUY SIGNAL GENERATED")
        print(f"     Entry: {latest['close']:.2f}")
        print(f"     Stop Loss: {sl:.2f} (-{(latest['close'] - sl):.2f})")
        print(f"     Take Profit: {tp:.2f} (+{(tp - latest['close']):.2f})")
        print(f"     Risk/Reward: 1:{(tp - latest['close']) / (latest['close'] - sl):.2f}")
    else:
        print(f"  ⏸️  NO SIGNAL (conditions not met)")
    
    print()
    print()
    
    # Test 2: Uptrend (should generate BUY signals)
    print("📈 TEST 2: Uptrend Market")
    print("-" * 80)
    df_up = create_test_candles(trend='uptrend', num_candles=25)
    df_with_indicators = strategy.calculate_indicators(df_up)
    
    latest = df_with_indicators.iloc[-1]
    prev = df_with_indicators.iloc[-2]
    
    print(f"  Latest Close: {latest['close']:.2f}")
    print(f"  Supertrend: {latest['supertrend']:.2f} ({'UPTREND' if latest['supertrend_direction'] == 1 else 'DOWNTREND'})")
    print(f"  SMA Fast: {latest['sma_fast']:.2f}")
    print(f"  SMA Slow: {latest['sma_slow']:.2f}")
    print(f"  EMA: {latest['ema']:.2f}")
    print(f"  ATR: {latest['atr']:.2f}")
    
    golden_cross = (latest['sma_fast'] > latest['sma_slow']) and (prev['sma_fast'] <= prev['sma_slow'])
    death_cross = (latest['sma_fast'] < latest['sma_slow']) and (prev['sma_fast'] >= prev['sma_slow'])
    
    print()
    print("  Signal Conditions:")
    print(f"    Supertrend Direction: {'UPTREND' if latest['supertrend_direction'] == 1 else 'DOWNTREND'}")
    print(f"    Price vs EMA: {latest['close']:.2f} {'>' if latest['close'] > latest['ema'] else '<'} {latest['ema']:.2f}")
    print(f"    SMA Fast vs Slow: {latest['sma_fast']:.2f} {'>' if latest['sma_fast'] > latest['sma_slow'] else '<'} {latest['sma_slow']:.2f}")
    print(f"    Golden Cross: {golden_cross}")
    print(f"    Death Cross: {death_cross}")
    print()
    
    if (latest['supertrend_direction'] == 1 and 
        latest['close'] > latest['ema'] and 
        (golden_cross or latest['sma_fast'] > latest['sma_slow'])):
        
        sl = latest['close'] - (strategy.sl_pips * latest['atr'])
        tp = latest['close'] + (strategy.tp_pips * latest['atr'])
        
        print(f"  ✅ BUY SIGNAL GENERATED")
        print(f"     Entry: {latest['close']:.2f}")
        print(f"     Stop Loss: {sl:.2f} (-{(latest['close'] - sl):.2f})")
        print(f"     Take Profit: {tp:.2f} (+{(tp - latest['close']):.2f})")
        print(f"     Risk/Reward: 1:{(tp - latest['close']) / (latest['close'] - sl):.2f}")
    elif (latest['supertrend_direction'] == -1 and 
          latest['close'] < latest['ema'] and 
          (death_cross or latest['sma_fast'] < latest['sma_slow'])):
        
        sl = latest['close'] + (strategy.sl_pips * latest['atr'])
        tp = latest['close'] - (strategy.tp_pips * latest['atr'])
        
        print(f"  ✅ SELL SIGNAL GENERATED")
        print(f"     Entry: {latest['close']:.2f}")
        print(f"     Stop Loss: {sl:.2f} (+{(sl - latest['close']):.2f})")
        print(f"     Take Profit: {tp:.2f} (-{(latest['close'] - tp):.2f})")
        print(f"     Risk/Reward: 1:{(tp - latest['close']) / (sl - latest['close']):.2f}")
    else:
        print(f"  ⏸️  NO SIGNAL (conditions not met)")
    
    print()
    print()
    
    # Test 3: Sideways (should generate fewer signals)
    print("➡️  TEST 3: Sideways Market")
    print("-" * 80)
    df_sideways = create_test_candles(trend='sideways', num_candles=25)
    df_with_indicators = strategy.calculate_indicators(df_sideways)
    
    latest = df_with_indicators.iloc[-1]
    prev = df_with_indicators.iloc[-2]
    
    print(f"  Latest Close: {latest['close']:.2f}")
    print(f"  Supertrend: {latest['supertrend']:.2f} ({'UPTREND' if latest['supertrend_direction'] == 1 else 'DOWNTREND'})")
    print(f"  SMA Fast: {latest['sma_fast']:.2f}")
    print(f"  SMA Slow: {latest['sma_slow']:.2f}")
    print(f"  EMA: {latest['ema']:.2f}")
    print(f"  ATR: {latest['atr']:.2f}")
    print()
    print("  ⏸️  Expected: Fewer or NO signals in sideways market")
    
    print()
    print("=" * 80)
    print("✅ SIGNAL GENERATION TEST COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    test_signal_generation()
