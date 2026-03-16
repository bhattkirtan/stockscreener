#!/usr/bin/env python3
"""
Debug Zone Strategy - Log why trades are rejected
"""

import sys
import os
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

import pandas as pd
from datetime import datetime
from src.strategies.zone_strategy import ZoneStrategy

# Load sample data
print("Loading data...")
df = pd.read_csv('data/GOLD_M5_150000bars.csv')
if 'time' in df.columns:
    df['timestamp'] = pd.to_datetime(df['time'])
else:
    df['timestamp'] = pd.to_datetime(df['timestamp'])

# Resample
df_copy = df.copy()
df_copy.set_index('timestamp', inplace=True)
h4 = df_copy.resample('4h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna().reset_index()
h1 = df_copy.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna().reset_index()
m15 = df_copy.resample('15min').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna().reset_index()

print(f"Loaded: H4={len(h4)}, H1={len(h1)}, M15={len(m15)}, M5={len(df)}")

# Initialize strategy
strategy = ZoneStrategy(symbol='GOLD')
print(f"Strategy initialized. Min score: {strategy.config['min_trade_score']}")

# Test range: middle 1000 bars
start_idx = len(df) // 2
end_idx = start_idx + 1000

rejection_reasons = {
    'spread_check': 0,
    'daily_limits': 0,
    'no_zones': 0,
    'no_trigger': 0,
    'no_support': 0,
    'too_far_from_zone': 0,
    'blocked_by_resistance': 0,
    'no_target': 0,
    'insufficient_rr': 0,
    'score_too_low': 0,
    'position_size_error': 0
}

valid_setups = 0

print(f"\nTesting {end_idx - start_idx} bars...")

for i in range(start_idx, end_idx):
    if i % 100 == 0:
        print(f"  Bar {i-start_idx}/{end_idx-start_idx}... Valid setups: {valid_setups}")
    
    current_bar = df.iloc[i]
    price = current_bar['close']
    time = current_bar['timestamp']
    
    # Build views
    h4_idx = len(h4[h4['timestamp'] <= time])
    h1_idx = len(h1[h1['timestamp'] <= time])
    m15_idx = len(m15[m15['timestamp'] <= time])
    
    if h4_idx < 100 or h1_idx < 200 or m15_idx < 400:
        continue
    
    df_view = {
        'H4': h4.iloc[:h4_idx].copy(),
        'H1': h1.iloc[:h1_idx].copy(),
        'M15': m15.iloc[:m15_idx].copy(),
        'M5': df.iloc[max(0, i-500):i+1].copy()
    }
    
    # Try to evaluate setup
    try:
        # Manual step-by-step to catch where it fails
        
        # 1. Spread check
        if not strategy._check_spread(0.3, df_view['M5']):
            rejection_reasons['spread_check'] += 1
            continue
        
        # 2. Daily limits
        if strategy._check_daily_limits():
            rejection_reasons['daily_limits'] += 1
            continue
        
        # 3. Update zones
        strategy.update_zones(df_view)
        support_zones = strategy.zone_engine.find_nearest_zones(price, 1, ['H4', 'H1', 'M15'])  # 1 = SUPPORT
        resistance_zones = strategy.zone_engine.find_nearest_zones(price, 2, ['H4', 'H1', 'M15'])  # 2 = RESISTANCE
        
        if not support_zones and not resistance_zones:
            rejection_reasons['no_zones'] += 1
            continue
        
        # 4. Check trigger
        m5_df = df_view['M5']
        support_level = support_zones[0][0].midpoint if support_zones else None
        resistance_level = resistance_zones[0][0].midpoint if resistance_zones else None
        
        trigger = strategy.trigger_detector.detect_trigger(m5_df, support_level, resistance_level)
        
        if trigger.value == 'none':
            rejection_reasons['no_trigger'] += 1
            continue
        
        # Found valid trigger!
        valid_setups += 1
        
        # Try full setup evaluation
        setup = strategy.evaluate_setup(
            df_dict=df_view,
            current_price=price,
            spread=0.3,
            equity=10000,
            is_news_blocked=False
        )
        
        if setup:
            print(f"\n✅ VALID SETUP FOUND at bar {i}:")
            print(f"   Direction: {setup.direction}")
            print(f"   Entry: {setup.entry_price:.2f}")
            print(f"   Stop: {setup.stop_loss:.2f}")
            print(f"   Target: {setup.take_profit_1:.2f}")
            print(f"   Score: {setup.score:.1f}")
            print(f"   Trigger: {trigger.value}")
        
    except Exception as e:
        pass  # Silent fail

print(f"\n{'='*60}")
print("REJECTION SUMMARY")
print(f"{'='*60}")

for reason, count in sorted(rejection_reasons.items(), key=lambda x: x[1], reverse=True):
    if count > 0:
        pct = (count / (end_idx - start_idx)) * 100
        print(f"  {reason:25s}: {count:5d} ({pct:.1f}%)")

print(f"\n  Valid triggers found: {valid_setups}")
print(f"\n{'='*60}\n")
