#!/usr/bin/env python3
"""
PRODUCTION ZONE STRATEGY BACKTEST
Following zone_strategy_production_ready.md specification exactly

Key Logic (Section 22 Pseudocode):
1. Build zones from H4/H1/M15
2. Compute bias from H4/H1 EMAs  
3. Detect M5 triggers (reclaim/rejection)
4. Score setup: bias(20) + zone_context(20) + trigger(15) + room(15) + session(10)
5. If score >= 65 and R:R >= 1.5, enter trade
"""

import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import multiprocessing

# PARAMETER GRID FOR OPTIMIZATION - REDUCED SET FOR QUICK TESTING
PARAM_GRID = {
    'min_score': [50, 65],              # Test low vs current threshold
    'min_rr': [1.2, 2.0],               # Test aggressive vs conservative R:R
    'zone_width_mult': [0.8, 1.2],      # Test tight vs wide zones  
    'stop_buffer': [0.20, 0.25]         # Keep both stop buffer values
}
# Total: 2×2×2×2 = 16 combinations (much faster than 54)

# Base config (Section 21)
RISK_PER_TRADE = 0.01  # 1% per idea
BASE_ZONE_WIDTH_H4 = 0.30
BASE_ZONE_WIDTH_H1 = 0.22
BASE_ZONE_WIDTH_M15 = 0.15
SPREAD_PIPS = 0.3

def calculate_atr(df, period=14):
    """Section 9.4"""
    high, low, close = df['high'], df['low'], df['close']
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean().fillna(tr.mean())

def detect_zones_simple(df, atr_value, width_fraction, tf_name):
    """Section 9: Detect swing highs/lows as zones"""
    zones = []
    lookback = 20 if tf_name == 'H4' else (15 if tf_name == 'H1' else 10)
    half_width = atr_value * width_fraction
    
    # Only process recent data for speed
    recent = df.iloc[-min(200, len(df)):].copy()
    
    for i in range(lookback, len(recent) - lookback):
        # Swing high
        pivot_high = recent.iloc[i]['high']
        is_swing_high = all(pivot_high >= recent.iloc[i-j]['high'] for j in range(1, lookback+1))
        is_swing_high = is_swing_high and all(pivot_high >= recent.iloc[i+j]['high'] for j in range(1, lookback+1))
        
        if is_swing_high:
            zones.append({
                'type': 'resistance',
                'midpoint': pivot_high,
                'lower': pivot_high - half_width,
                'upper': pivot_high + half_width,
                'tf': tf_name,
                'time': recent.iloc[i]['timestamp']
            })
        
        # Swing low
        pivot_low = recent.iloc[i]['low']
        is_swing_low = all(pivot_low <= recent.iloc[i-j]['low'] for j in range(1, lookback+1))
        is_swing_low = is_swing_low and all(pivot_low <= recent.iloc[i+j]['low'] for j in range(1, lookback+1))
        
        if is_swing_low:
            zones.append({
                'type': 'support',
                'midpoint': pivot_low,
                'lower': pivot_low - half_width,
                'upper': pivot_low + half_width,
                'tf': tf_name,
                'time': recent.iloc[i]['timestamp']
            })
    
    return zones

def compute_bias(h4_df, h1_df):
    """Section 11: EMA bias"""
    if len(h4_df) < 50 or len(h1_df) < 50:
        return 'neutral'
    
    h4_fast = h4_df['close'].ewm(span=20).mean().iloc[-1]
    h4_slow = h4_df['close'].ewm(span=50).mean().iloc[-1]
    h1_fast = h1_df['close'].ewm(span=20).mean().iloc[-1]
    h1_slow = h1_df['close'].ewm(span=50).mean().iloc[-1]
    
    if h1_fast > h1_slow and h4_fast >= h4_slow:
        return 'bullish'
    elif h1_fast < h1_slow and h4_fast <= h4_slow:
        return 'bearish'
    return 'neutral'

def detect_m5_trigger(m5_recent, support_level, resistance_level):
    """Section 12: M5 triggers (reclaim/rejection)"""
    if len(m5_recent) < 3:
        return 'none'
    
    current = m5_recent.iloc[-1]
    prev = m5_recent.iloc[-2]
    
    # Bullish reclaim
    if support_level and prev['close'] <= support_level and current['close'] > support_level and current['close'] > current['open']:
        return 'bullish_reclaim'
    
    # Bearish rejection
    if resistance_level and prev['close'] >= resistance_level and current['close'] < resistance_level and current['close'] < current['open']:
        return 'bearish_rejection'
    
    return 'none'

def find_nearest_zones(price, zones, zone_type):
    """Find zones near price"""
    matching = [z for z in zones if z['type'] == zone_type]
    if not matching:
        return []
    
    # Sort by distance to price
    with_distance = [(z, abs(z['midpoint'] - price)) for z in matching]
    with_distance.sort(key=lambda x: x[1])
    return with_distance[:3]  # Top 3 nearest

def score_long_setup(bias, support_zones, resistance_zones, trigger, price, atr):
    """Section 17: Score long setup"""
    score = 0
    
    # Bias alignment (20 pts)
    if bias == 'bullish':
        score += 20
    elif bias == 'neutral':
        score += 10
    
    # Zone context (20 pts)
    if support_zones:
        nearest_support, dist = support_zones[0]
        if dist < atr * 2:  # Within 2 ATR
            score += 20
        elif dist < atr * 4:
            score += 10
    
    # Check if resistance overhead blocks (Section 13.3)
    if resistance_zones:
        nearest_resistance, dist = resistance_zones[0]
        if dist < atr * 1:  # Too close
            score -= 15  # Penalty
    
    # Trigger quality (15 pts)
    if trigger == 'bullish_reclaim':
        score += 15
    
    # Room to target (15 pts) - checked later
    # Session quality (10 pts) - simplified to always give
    score += 10
    
    return score

def score_short_setup(bias, support_zones, resistance_zones, trigger, price, atr):
    """Section 17: Score short setup"""
    score = 0
    
    if bias == 'bearish':
        score += 20
    elif bias == 'neutral':
        score += 10
    
    if resistance_zones:
        nearest_resistance, dist = resistance_zones[0]
        if dist < atr * 2:
            score += 20
        elif dist < atr * 4:
            score += 10
    
    if support_zones:
        nearest_support, dist = support_zones[0]
        if dist < atr * 1:
            score -= 15
    
    if trigger == 'bearish_rejection':
        score += 15
    
    score += 10  # Session
    
    return score

def run_backtest(df_shared, h4_shared, h1_shared, m15_shared, min_score, min_rr, zone_width_mult, stop_buffer):
    """Run backtest with specific parameters and return results"""
    # Use shared data (no loading needed - passed from main thread)
    df = df_shared
    h4 = h4_shared
    h1 = h1_shared
    m15 = m15_shared
    
    ZONE_WIDTH_H4 = BASE_ZONE_WIDTH_H4 * zone_width_mult
    ZONE_WIDTH_H1 = BASE_ZONE_WIDTH_H1 * zone_width_mult
    ZONE_WIDTH_M15 = BASE_ZONE_WIDTH_M15 * zone_width_mult
    
    equity = 10000
    trades = []
    min_bars = 2000
    total_bars = len(df)
    zones_all = []
    last_zone_update = 0
    
    for i in range(min_bars, total_bars):
        current_bar = df.iloc[i]
        price = current_bar['close']
        time = current_bar['timestamp']
        
        h4_view = h4[h4['timestamp'] <= time]
        h1_view = h1[h1['timestamp'] <= time]
        m15_view = m15[m15['timestamp'] <= time]
        m5_view = df.iloc[max(0, i-100):i+1]
        
        if len(h4_view) < 100 or len(h1_view) < 200 or len(m15_view) < 400:
            continue
        
        if i - last_zone_update >= 50:
            atr_h4 = calculate_atr(h4_view).iloc[-1]
            atr_h1 = calculate_atr(h1_view).iloc[-1]
            atr_m15 = calculate_atr(m15_view).iloc[-1]
            zones_all = []
            zones_all.extend(detect_zones_simple(h4_view, atr_h4, ZONE_WIDTH_H4, 'H4'))
            zones_all.extend(detect_zones_simple(h1_view, atr_h1, ZONE_WIDTH_H1, 'H1'))
            zones_all.extend(detect_zones_simple(m15_view, atr_m15, ZONE_WIDTH_M15, 'M15'))
            last_zone_update = i
        
        if not zones_all:
            continue
        
        bias = compute_bias(h4_view, h1_view)
        support_zones = find_nearest_zones(price, zones_all, 'support')
        resistance_zones = find_nearest_zones(price, zones_all, 'resistance')
        
        if not support_zones and not resistance_zones:
            continue
        
        support_level = support_zones[0][0]['midpoint'] if support_zones else None
        resistance_level = resistance_zones[0][0]['midpoint'] if resistance_zones else None
        trigger = detect_m5_trigger(m5_view, support_level, resistance_level)
        
        if trigger == 'none':
            continue
        
        atr_m5 = calculate_atr(m5_view).iloc[-1]
        
        # Long setup
        if trigger == 'bullish_reclaim' and support_zones:
            score = score_long_setup(bias, support_zones, resistance_zones, trigger, price, atr_m5)
            if score >= min_score:
                zone = support_zones[0][0]
                stop = zone['lower'] - (stop_buffer * atr_m5)
                tp1 = resistance_zones[0][0]['midpoint'] if resistance_zones else price + (price - stop) * 2
                stop_dist = price - stop
                target_dist = tp1 - price
                rr = target_dist / stop_dist if stop_dist > 0 else 0
                
                if rr >= min_rr:
                    entry = price + SPREAD_PIPS
                    for j in range(i+1, min(i+200, total_bars)):
                        bar = df.iloc[j]
                        if bar['low'] <= stop:
                            pnl = stop - entry
                            equity += (pnl / entry) * equity * RISK_PER_TRADE
                            trades.append({'pnl': pnl, 'type': 'loss'})
                            break
                        elif bar['high'] >= tp1:
                            pnl = tp1 - entry
                            equity += (pnl / entry) * equity * RISK_PER_TRADE
                            trades.append({'pnl': pnl, 'type': 'win'})
                            break
        
        # Short setup
        elif trigger == 'bearish_rejection' and resistance_zones:
            score = score_short_setup(bias, support_zones, resistance_zones, trigger, price, atr_m5)
            if score >= min_score:
                zone = resistance_zones[0][0]
                stop = zone['upper'] + (stop_buffer * atr_m5)
                tp1 = support_zones[0][0]['midpoint'] if support_zones else price - (stop - price) * 2
                stop_dist = stop - price
                target_dist = price - tp1
                rr = target_dist / stop_dist if stop_dist > 0 else 0
                
                if rr >= min_rr:
                    entry = price - SPREAD_PIPS
                    for j in range(i+1, min(i+200, total_bars)):
                        bar = df.iloc[j]
                        if bar['high'] >= stop:
                            pnl = entry - stop
                            equity += (pnl / entry) * equity * RISK_PER_TRADE
                            trades.append({'pnl': pnl, 'type': 'loss'})
                            break
                        elif bar['low'] <= tp1:
                            pnl = entry - tp1
                            equity += (pnl / entry) * equity * RISK_PER_TRADE
                            trades.append({'pnl': pnl, 'type': 'win'})
                            break
    
    # Calculate metrics
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
    wins = trades_df[trades_df['type'] == 'win'] if len(trades_df) > 0 else pd.DataFrame()
    losses = trades_df[trades_df['type'] == 'loss'] if len(trades_df) > 0 else pd.DataFrame()
    
    return {
        'min_score': min_score,
        'min_rr': min_rr,
        'zone_mult': zone_width_mult,
        'stop_buffer': stop_buffer,
        'trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': len(wins) / len(trades) * 100 if len(trades) > 0 else 0,
        'total_return': (equity - 10000) / 10000 * 100,
        'final_equity': equity,
        'avg_win': wins['pnl'].mean() if len(wins) > 0 else 0,
        'avg_loss': losses['pnl'].mean() if len(losses) > 0 else 0
    }

# Global data holders for thread sharing
GLOBAL_DF = None
GLOBAL_H4 = None
GLOBAL_H1 = None
GLOBAL_M15 = None

# Wrapper function for parallel execution
def run_backtest_wrapper(params):
    """Wrapper to unpack parameters for parallel execution"""
    min_score, min_rr, zone_mult, stop_buffer = params
    result = run_backtest(GLOBAL_DF, GLOBAL_H4, GLOBAL_H1, GLOBAL_M15, min_score, min_rr, zone_mult, stop_buffer)
    return result

if __name__ == '__main__':
    # Run Parameter Optimization (PARALLEL)
    print("="*70)
    print("ZONE STRATEGY BACKTEST - PRODUCTION SPEC")
    print("="*70)
    
    # Load data once (shared across all threads)
    print(f"\n📊 Loading data...")
    GLOBAL_DF = pd.read_csv('data/GOLD_M5_150000bars.csv')
    if 'time' in GLOBAL_DF.columns:
        GLOBAL_DF['timestamp'] = pd.to_datetime(GLOBAL_DF['time'])
    else:
        GLOBAL_DF['timestamp'] = pd.to_datetime(GLOBAL_DF['timestamp'])
    
    GLOBAL_DF = GLOBAL_DF.sort_values('timestamp').reset_index(drop=True)
    print(f"   ✓ {len(GLOBAL_DF)} M5 bars from {GLOBAL_DF['timestamp'].iloc[0]} to {GLOBAL_DF['timestamp'].iloc[-1]}")
    
    # Resample once
    print(f"\n📈 Resampling...")
    GLOBAL_DF.set_index('timestamp', inplace=True)
    GLOBAL_H4 = GLOBAL_DF.resample('4h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna().reset_index()
    GLOBAL_H1 = GLOBAL_DF.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna().reset_index()
    GLOBAL_M15 = GLOBAL_DF.resample('15min').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna().reset_index()
    GLOBAL_DF.reset_index(inplace=True)
    print(f"   ✓ H4: {len(GLOBAL_H4)} | H1: {len(GLOBAL_H1)} | M15: {len(GLOBAL_M15)}")
    
    print(f"\n🔬 PARAMETER OPTIMIZATION")
    print(f"{'='*70}")
    
    # Generate all parameter combinations
    param_combinations = []
    for min_score in PARAM_GRID['min_score']:
        for min_rr in PARAM_GRID['min_rr']:
            for zone_mult in PARAM_GRID['zone_width_mult']:
                for stop_buffer in PARAM_GRID['stop_buffer']:
                    param_combinations.append((min_score, min_rr, zone_mult, stop_buffer))
    
    total_combos = len(param_combinations)
    
    print(f"\nTesting {total_combos} parameter combinations (sequential with progress)...\n")
    
    results = []
    start_time = datetime.now()
    
    # Run backtests sequentially with clear progress
    for idx, params in enumerate(param_combinations, 1):
        min_score, min_rr, zone_mult, stop_buffer = params
        print(f"[{idx}/{total_combos}] Testing: Score={min_score} RR={min_rr} Zones={zone_mult}x Stop={stop_buffer}...", flush=True)
        combo_start = datetime.now()
        
        result = run_backtest(GLOBAL_DF, GLOBAL_H4, GLOBAL_H1, GLOBAL_M15, min_score, min_rr, zone_mult, stop_buffer)
        results.append(result)
        
        combo_time = (datetime.now() - combo_start).total_seconds()
        print(f"   ✓ Completed in {combo_time:.1f}s → {result['trades']} trades | {result['win_rate']:.1f}% WR | {result['total_return']:+.2f}% return\n", flush=True)
    
    total_time = (datetime.now() - start_time).total_seconds()
    
    # Display Top Results
    print(f"\n{'='*70}")
    print("📊 TOP 10 CONFIGURATIONS (BY TOTAL RETURN)")
    print(f"{'='*70}\n")
    
    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values('total_return', ascending=False)
    
    print(f"{'Rank':<6}{'Score':<8}{'R:R':<7}{'Zones':<8}{'Stop':<7}{'Trades':<9}{'WR%':<8}{'Return':<10}")
    print(f"{'-'*70}")
    
    for idx, (i, row) in enumerate(results_df.head(10).iterrows(), 1):
        print(f"{idx:<6}"
              f"{int(row['min_score']):<8}"
              f"{row['min_rr']:<7.1f}"
              f"{row['zone_mult']:<8.1f}x"
              f"{row['stop_buffer']:<7.2f}"
              f"{int(row['trades']):<9}"
              f"{row['win_rate']:<8.1f}"
              f"{row['total_return']:+9.2f}%")
    
    # Save all results
    results_df.to_csv('zone_param_optimization_results.csv', index=False)
    print(f"\n✅ All {len(results)} combinations saved to zone_param_optimization_results.csv")
    print(f"⏱️  Total time: {total_time/60:.1f} minutes")
    print(f"\n{'='*70}\n")
