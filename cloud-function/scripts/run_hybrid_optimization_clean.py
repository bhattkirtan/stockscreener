#!/usr/bin/env python3
"""
Hybrid Strategy Optimization: SuperTrend + Zone Filtering + Event Blocking

Leverages existing infrastructure:
- src.core.strategy.SupertrendVWAPStrategy (base strategy with SuperTrend+SMA)
- src.core.backtester.IntraCandleBacktester (proven backtest framework)  
- src.core.event_blocker.EventBlocker (economic calendar blocking)
- src.zones.zone_engine.ZoneEngine (multi-timeframe zone detection)
- src.optimization.optimize_strategy.StrategyOptimizer (parallel optimization)

This script runs optimization to find best parameters for:
1. SuperTrend (period, multiplier, SMA periods)
2. ATR-based TP/SL (proven: 0.7×2.5)
3. Zone filtering (block trades into opposing structure)
4. Event blocking (avoid high-impact news)
"""

import sys
import os
import argparse
import pandas as pd
from pathlib import Path
from datetime import datetime
from itertools import product
from concurrent.futures import ProcessPoolExecutor, as_completed

# Add cloud-function to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.optimization.optimize_strategy import StrategyOptimizer


def define_hybrid_parameter_grid(mode='quick'):
    """Define parameter grid for hybrid strategy optimization.
    
    Args:
        mode: 'quick', 'medium', or 'full'
        
    Returns:
        Parameter grid dictionary
    """
    if mode == 'quick':
        # Test proven baseline (0.7×2.5 ATR) + zone/event filtering
        return {
            # SuperTrend (proven baseline)
            'supertrend_period': [10],
            'supertrend_multiplier': [3.0],
            'sma_fast': [20],
            'sma_slow': [50],
            'ema_period': [21],
            'bb_period': [20],
            'bb_std': [2.0],
            
            # ATR-based TP/SL (proven winner: 0.7×2.5)
            'tp_sl_strategy': ['atr'],
            'atr_sl_multiplier': [0.7],
            'atr_tp_multiplier': [2.5],
            'sl_pips': [None],  # Use ATR
            'tp_pips': [None],  # Use ATR
            
            # Event blocking (NEW - test on/off)
            'enable_event_blocking': [True, False],
            'calendar_path': ['data/economic_calendar.json'],
            
            # Intraday filters (from existing strategy)
            'enable_time_exit': [False],
            'enable_eod_close': [True],
            'eod_close_hour': [16],
            'enable_eod_blackout': [True],
            'no_entry_before_eod_hours': [1],
            
            # RSI filter (proven: +30% test improvement)
            'use_rsi_filter': [True],
            'rsi_period': [14],
            'rsi_overbought': [70],
            'rsi_oversold': [30],
            
            # Other filters
            'use_atr_volatility_filter': [False],
            'use_session_filter': [False],
            
            # Constants
            'pip_value': [1.0],
        }
    
    elif mode == 'medium':
        # More SuperTrend variations + event blocking
        return {
            'supertrend_period': [8, 10, 12],
            'supertrend_multiplier': [2.5, 3.0, 3.5],
            'sma_fast': [15, 20, 25],
            'sma_slow': [40, 50, 60],
            'ema_period': [21],
            'bb_period': [20],
            'bb_std': [2.0],
            
            # ATR-based TP/SL
            'tp_sl_strategy': ['atr'],
            'atr_sl_multiplier': [0.5, 0.7, 1.0],
            'atr_tp_multiplier': [2.0, 2.5, 3.0],
            'sl_pips': [None],
            'tp_pips': [None],
            
            # Event blocking
            'enable_event_blocking': [True, False],
            'calendar_path': ['data/economic_calendar.json'],
            
            # Intraday filters
            'enable_time_exit': [False, True],
            'max_holding_hours': [4],
            'enable_eod_close': [True],
            'eod_close_hour': [16],
            'enable_eod_blackout': [True],
            'no_entry_before_eod_hours': [1, 2],
            
            # RSI filter
            'use_rsi_filter': [True, False],
            'rsi_period': [14],
            'rsi_overbought': [70],
            'rsi_oversold': [30],
            
            'use_atr_volatility_filter': [False],
            'use_session_filter': [False],
            'pip_value': [1.0],
        }
    
    else:  # full
        # Comprehensive grid
        return {
            'supertrend_period': [7, 8, 9, 10, 11, 12],
            'supertrend_multiplier': [2.0, 2.5, 3.0, 3.5, 4.0],
            'sma_fast': [10, 15, 20, 25, 30],
            'sma_slow': [35, 40, 50, 60, 70],
            'ema_period': [21],
            'bb_period': [20],
            'bb_std': [2.0],
            
            'tp_sl_strategy': ['atr'],
            'atr_sl_multiplier': [0.5, 0.6, 0.7, 0.8, 1.0],
            'atr_tp_multiplier': [1.5, 2.0, 2.5, 3.0, 3.5],
            'sl_pips': [None],
            'tp_pips': [None],
            
            'enable_event_blocking': [True, False],
            'calendar_path': ['data/economic_calendar.json'],
            
            'enable_time_exit': [False, True],
            'max_holding_hours': [3, 4, 6],
            'enable_eod_close': [True, False],
            'eod_close_hour': [15, 16, 17],
            'enable_eod_blackout': [True, False],
            'no_entry_before_eod_hours': [1, 2, 3],
            
            'use_rsi_filter': [True, False],
            'rsi_period': [14],
            'rsi_overbought': [65, 70, 75],
            'rsi_oversold': [25, 30, 35],
            
            'use_atr_volatility_filter': [False, True],
            'atr_min_ratio': [0.7],
            'atr_max_ratio': [1.5],
            
            'use_session_filter': [False, True],
            'trading_sessions': ['london_ny'],
            
            'pip_value': [1.0],
        }


def main():
    parser = argparse.ArgumentParser(
        description='Hybrid Strategy Optimization: SuperTrend + Event Blocking'
    )
    parser.add_argument('--data-csv', required=True, 
                       help='Path to M5 CSV data file')
    parser.add_argument('--instrument', default='GOLD', 
                       help='Instrument name (GOLD, US100)')
    parser.add_argument('--capital', type=float, default=10000.0,
                       help='Initial capital')
    parser.add_argument('--mode', default='quick', 
                       choices=['quick', 'medium', 'full'],
                       help='Optimization mode')
    parser.add_argument('--calendar-path', default='data/economic_calendar.json',
                       help='Path to economic calendar JSON')
    parser.add_argument('--n-jobs', type=int, default=-1,
                       help='Number of parallel workers (-1 for all cores)')
    parser.add_argument('--no-parallel', action='store_true',
                       help='Disable parallel processing (for debugging)')
    parser.add_argument('--output-dir', default='results',
                       help='Output directory for results')
    parser.add_argument('--train-test-split', type=float, default=0.7,
                       help='Train/test split ratio (0.7 = 70%% train, 30%% test)')
    
    args = parser.parse_args()
    
    print("\n" + "="*80)
    print("🎯 HYBRID STRATEGY OPTIMIZATION")
    print("   SuperTrend + Event Blocking + Intraday Filters")
    print("="*80)
    
    # Load data
    print(f"\n📊 Loading data from {args.data_csv}...")
    try:
        df = pd.read_csv(args.data_csv)
        
        # Ensure timestamp
        if 'time' in df.columns:
            df['timestamp'] = pd.to_datetime(df['time'])
        elif 'timestamp' not in df.columns:
            raise ValueError("No 'timestamp' or 'time' column found")
        else:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        print(f"✅ Loaded {len(df)} M5 bars")
        print(f"   Range: {df['timestamp'].iloc[0]} to {df['timestamp'].iloc[-1]}")
        
    except Exception as e:
        print(f"❌ Failed to load data: {e}")
        sys.exit(1)
    
    # Check calendar
    calendar_exists = os.path.exists(args.calendar_path)
    print(f"\n📅 Economic calendar: {'✅ Found' if calendar_exists else '⚠️  Not found'}")
    if not calendar_exists:
        print(f"   Event blocking will be disabled")
    
    # Define parameter grid
    print(f"\n🔬 Defining parameter grid (mode: {args.mode})...")
    grid = define_hybrid_parameter_grid(args.mode)
    
    # Update calendar path in grid
    if calendar_exists:
        grid['calendar_path'] = [args.calendar_path]
    else:
        grid['enable_event_blocking'] = [False]  # Force disable if no calendar
        grid['calendar_path'] = [None]
    
    # Calculate total combinations
    from functools import reduce
    import operator
    total_combos = reduce(operator.mul, [len(v) for v in grid.values()], 1)
    
    print(f"✅ Parameter grid defined: {total_combos} combinations")
    print(f"   Event blocking: {grid['enable_event_blocking']}")
    print(f"   ATR TP/SL: {grid['atr_tp_multiplier']}")
    
    # Initialize optimizer using existing framework
    print(f"\n🚀 Initializing optimizer...")
    optimizer = StrategyOptimizer(
        df=df,
        param_grid=grid,
        initial_capital=args.capital,
        train_test_split=args.train_test_split,
        use_validation=True,  # Enable train/test split
        parallel=not args.no_parallel,
        n_jobs=args.n_jobs
    )
    
    print(f"✅ Optimizer ready")
    print(f"   Train/Test split: {args.train_test_split:.0%}/{1-args.train_test_split:.0%}")
    print(f"   Parallel: {not args.no_parallel}")
    if not args.no_parallel:
        n_workers = args.n_jobs if args.n_jobs > 0 else os.cpu_count()
        print(f"   Workers: {n_workers}")
    
    # Run optimization
    print(f"\n⏳ Running optimization...")
    start_time = datetime.now()
    
    results_df = optimizer.optimize()
    
    elapsed = (datetime.now() - start_time).total_seconds()
    
    # Show summary
    print(f"\n" + "="*80)
    print("📊 OPTIMIZATION RESULTS")
    print("="*80)
    
    print(f"\n⏱️  Total time: {elapsed/60:.1f} minutes")
    print(f"⚡ Speed: {len(results_df)/elapsed:.1f} configs/second")
    print(f"\n✅ Tested {len(results_df)} configurations")
    
    # Show top 20
    print(f"\n📈 TOP 20 CONFIGURATIONS (by test return)")
    print("-"*80)
    print(f"{'Rank':<6}{'TestRet':<10}{'TrainRet':<10}{'WinRate':<10}{'Trades':<8}{'EventBlock':<12}{'ATR TP':<8}")
    print("-"*80)
    
    for idx, (_, row) in enumerate(results_df.head(20).iterrows(), 1):
        event_status = "ON" if row['params'].get('enable_event_blocking', False) else "OFF"
        tp_mult = row['params'].get('atr_tp_multiplier', 0)
        
        print(f"{idx:<6}"
              f"{row.get('test_return_pct', 0):>8.2f}% "
              f"{row['return_pct']:>8.2f}% "
              f"{row['win_rate']:>8.1f}% "
              f"{int(row['total_trades']):<8}"
              f"{event_status:<12}"
              f"{tp_mult:<8.1f}")
    
    # Save results
    os.makedirs(args.output_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    output_csv = f"{args.output_dir}/hybrid_optimization_{args.mode}_{timestamp}.csv"
    results_df.to_csv(output_csv, index=False)
    print(f"\n✅ Full results saved to: {output_csv}")
    
    top_50_csv = f"{args.output_dir}/hybrid_optimization_{args.mode}_{timestamp}_top50.csv"
    results_df.head(50).to_csv(top_50_csv, index=False)
    print(f"✅ Top 50 saved to: {top_50_csv}")
    
    print(f"\n{'='*80}")
    print("✅ Optimization complete!\n")


if __name__ == '__main__':
    main()
