#!/usr/bin/env python3
"""
Phase 4 Optimization: SCALPING/INTRADAY Strategy
NO overnight holds, tight fixed SL/TP, quick in/out
"""
import sys
import os
from pathlib import Path

# Add cloud-function to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from src.optimization.optimize_strategy import StrategyOptimizer

def define_phase4_grid():
    """
    Phase 4: SCALPING Strategy - Tight ATR stops, NO overnight + HEIKEN ASHI
    
    GOAL: Quick M5 scalping with tight ATR-based stops
    
    TEST:
    1. TIGHT SL: 0.3, 0.5, 0.7 × ATR (~$6-14 stops at Gold M15 ATR~$20)
    2. Quick TP: 1.0, 1.5, 2.0, 2.5 × ATR (~$20-50 targets)
    3. R:R Ratios: 1:2 to 1:7 (tight stop, proportional target)
    4. Time Exit: Test True/False (4h limit vs natural exit)
    5. EOD Close: Test True/False (forced 4 PM close vs overnight)
    6. ST Period: 7 vs 10 (responsiveness for quick entries)
    7. Heiken Ashi: ENABLED (baseline without HA already tested)
    
    Combinations test: scalping (4h+EOD) vs intraday (4h) vs daily (EOD) vs swing (natural)
    
    Total: 3 SL × 4 TP × 2 ST × 2 time × 2 EOD × 1 HA = 96 combinations (~24-28 min)
    """
    return {
        # TEST: Supertrend period (10=balanced, 15=smooth for US100)
        'supertrend_period': [21, 7],  # Add 7 for more responsive scalping entries
        
        # FIXED: Winner multiplier
        'supertrend_multiplier': [2.0,3],
        
        # FIXED: Winner SMA configuration (from GOLD best)
        'sma_fast': [21, 15],
        'sma_slow': [50],
        
        'ema_period': [9, 12],
        
        # FIXED: Winner BB settings
        'bb_period': [20],
        'bb_std': [2.0],
        
        # SCALPING: ATR-based with TIGHT multipliers
        'tp_sl_strategy': ['atr'],
        
        # Fixed TP/SL (not used with ATR)
        'sl_pips': [10],
        'tp_pips': [15],
        
        'pip_value': [1.0],
        
        # TEST: ATR multipliers adjusted for US100 v3
        # Previous test: 19% win rate with TP 1.5-2.5 - too wide!
        # Try MUCH tighter profit targets for scalping
        'atr_sl_multiplier': [1,1.5],  # Medium to wider stops (reduce overtrading)
        'atr_tp_multiplier': [3, 4],  # Quick scalping exits
        
        # DISABLED: Filters (want flexible entries for scalping)
        'use_rsi_filter': [False],
        'rsi_period': [14],
        'rsi_overbought': [70],
        'rsi_oversold': [30],
        
        'use_atr_volatility_filter': [False],
        'atr_volatility_period': [14],
        'atr_sma_period': [20],
        'atr_min_ratio': [0.7],
        'atr_max_ratio': [1.5],
        
        'use_session_filter': [False],
        'trading_sessions': ['24h'],
        
        # PHASE 4: Heiken Ashi DISABLED (no improvement on GOLD)
        'use_heikin_ashi': [False],  # Disabled - no improvement found
        
        # US100: Test different holding periods (may need longer holds)
        'enable_time_exit': [False],  # No time limit for US100
        'max_holding_hours': [4],  # Not used when enable_time_exit=False
        
        'enable_eod_close': [False],  # Allow overnight for US100
        'eod_close_hour': [16],  # Not used when enable_eod_close=False
        
        'enable_eod_blackout': [False],  # Allow entries until 4h before EOD
        'no_entry_before_eod_hours': [1],
        
        # DISABLED: Friday filter (EOD close handles weekend risk)
        'enable_friday_filter': [False],
        'friday_cutoff_hour': [15]
    }

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Phase 4 Optimization: R:R Ratios & ST Period')
    parser.add_argument('--data-file', default='data/GOLD_M15_49995bars.csv', help='Path to CSV data file')
    parser.add_argument('--validation-split', type=float, default=0.0, help='Train/test split (0.0 = full dataset)')
    parser.add_argument('--max-rows', type=int, default=None, help='Limit data rows (e.g., 75000 for 1 year M5)')
    parser.add_argument('--n-jobs', type=int, default=12, help='Number of parallel workers')
    
    args = parser.parse_args()
    
    # Parse max_rows if provided
    max_rows = args.max_rows
    
    print("\n" + "="*80)
    print("🎯 PHASE 4 OPTIMIZATION: SCALPING Strategy (No Overnight Holding)")
    print("="*80 + "\n")
    
    print("📌 FIXED (Keep indicators):")
    print("   - Supertrend multiplier: 2.0")
    print("   - SMA: 15-50")
    print("   - BB std: 2.0")
    print()
    print("🔬 TESTING SCALPING PARAMETERS:")
    print("   - Tight SL: 0.3, 0.5, 0.7 × ATR (~$6-14 stops)")
    print("   - Quick TP: 1.0, 1.5, 2.0, 2.5 × ATR (~$20-50 targets)")
    print("   - R:R Ratios: 1:2 to 1:7 (tight stop, bigger target)")
    print("   - ST Period: 7 (responsive) vs 10 (smooth)")
    print("   - Time Exit: Test True/False (4h limit vs natural)")
    print("   - EOD Close: Test True/False (4 PM close vs overnight)")
    print("   - Heiken Ashi: ENABLED (baseline already tested)")
    print("   - Total: 3 SL × 4 TP × 2 ST × 2 time × 2 EOD = 96 combinations")
    print()
    print("💡 Strategy: Test HA trend smoothing impact on performance")
    print("⏱️  Expected runtime: ~24-28 minutes with 12 workers")
    print()
    
    # Load data
    print(f"📊 Loading data from {args.data_file}...")
    try:
        df = pd.read_csv(args.data_file)
        
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
        else:
            df.index = pd.to_datetime(df.index)
        
        # Slice data if max_rows specified
        if max_rows and len(df) > max_rows:
            print(f"⚡ Using first {max_rows:,} bars (out of {len(df):,}) for faster testing")
            df = df.head(max_rows)
        
        print(f"✅ Loaded {len(df):,} bars")
        print(f"   Range: {df.index[0]} to {df.index[-1]}")
        print()
        
    except Exception as e:
        print(f"❌ Failed to load data: {e}")
        sys.exit(1)
    
    # Create optimizer with custom grid
    print("🚀 Starting Phase 4 optimization...")
    optimizer = StrategyOptimizer(
        df=df,
        initial_capital=10000.0,
        epic='GOLD',
        resolution='M5',
        validation_split=args.validation_split,
        n_jobs=args.n_jobs
    )
    
    # Override the intraday grid with Phase 4 grid
    original_grid_func = optimizer.define_intraday_grid
    optimizer.define_intraday_grid = define_phase4_grid
    
    # Run optimization
    results_df = optimizer.run_optimization(
        mode='intraday',
        parallel=True
    )
    
    # Restore original
    optimizer.define_intraday_grid = original_grid_func
    
    # Show summary
    print("\n" + "="*80)
    print("📊 PHASE 4 RESULTS")
    print("="*80 + "\n")
    
    optimizer.print_summary(results_df, top_n=8)
    
    # Export results
    output_file = optimizer.export_results(results_df)
    
    if output_file:
        print(f"📁 Results exported to: {output_file}")
    
    # Show EOD close comparison
    print("\n" + "="*80)
    print("📊 EOD CLOSE COMPARISON")
    print("="*80)
    
    if not results_df.empty and 'enable_eod_close' in results_df.columns:
        for eod in [True, False]:
            eod_results = results_df[results_df['enable_eod_close'] == eod].sort_values('return_pct', ascending=False)
            if not eod_results.empty:
                best = eod_results.iloc[0]
                eod_label = "WITH EOD Close (forced exit 4 PM)" if eod else "WITHOUT EOD Close (overnight allowed)"
                print(f"\n{eod_label}:")
                print(f"  Best Return: {best['return_pct']:.2f}%")
                print(f"  Config: SL {best['atr_sl_multiplier']:.1f}× / TP {best['atr_tp_multiplier']:.1f}× ATR")
                print(f"  Trades: {best['total_trades']:.0f}")
                print(f"  Win Rate: {best['win_rate']:.1f}%")
                print(f"  Sharpe: {best['sharpe_ratio']:.3f}")
    
    # Show scalping analysis
    print("\n" + "="*80)
    print("📊 SCALPING STOP LOSS COMPARISON")
    print("="*80)
    
    if not results_df.empty:
        # Group by SL multiplier
        for sl_mult in [0.3, 0.5, 0.7]:
            sl_results = results_df[results_df['atr_sl_multiplier'] == sl_mult].sort_values('return_pct', ascending=False)
            if not sl_results.empty:
                best = sl_results.iloc[0]
                print(f"\nSL {sl_mult}× ATR (tight stop ~${sl_mult*20:.1f}):")
                print(f"  Best Return: {best['return_pct']:.2f}%")
                print(f"  Best Config: TP {best['atr_tp_multiplier']:.1f}× ATR (R:R 1:{best['atr_tp_multiplier']/sl_mult:.1f})")
                print(f"  Trades: {best['total_trades']:.0f}")
                print(f"  Win Rate: {best['win_rate']:.1f}%")
                print(f"  Sharpe: {best['sharpe_ratio']:.3f}")
    
    # Show R:R comparison for scalping
    print("\n" + "="*80)
    print("📊 R:R RATIO COMPARISON (Scalping)")
    print("="*80)
    
    if not results_df.empty:
        # Find best R:R by looking at SL/TP combos
        unique_combos = results_df[['atr_sl_multiplier', 'atr_tp_multiplier']].drop_duplicates()
        for _, combo in unique_combos.iterrows():
            sl = combo['atr_sl_multiplier']
            tp = combo['atr_tp_multiplier']
            rr = tp / sl
            
            combo_results = results_df[
                (results_df['atr_sl_multiplier'] == sl) & 
                (results_df['atr_tp_multiplier'] == tp)
            ].sort_values('return_pct', ascending=False)
            
            if not combo_results.empty:
                best = combo_results.iloc[0]
                print(f"\nSL {sl}× / TP {tp}× = R:R 1:{rr:.1f}:")
                print(f"  Return: {best['return_pct']:.2f}% | Trades: {best['total_trades']:.0f} | Win Rate: {best['win_rate']:.1f}%")
    
    print("\n✅ Phase 4 scalping optimization complete!\n")
    print("💡 Key Questions:")
    print("   - EOD close impact: Better with forced exit or let positions run?")
    print("   - Heiken Ashi impact: Does trend smoothing improve win rate?")
    print("   - Best SL size: Tighter (0.3×) vs Wider (0.7×)?")
    print("   - Optimal R:R for scalping: 1:3, 1:4, or higher?")
    print("   - Trade frequency: More trades with tight stops?")
    print("   - ST period impact: 7 vs 10 for M5 scalping?")
    print("\n📈 Trade-off: EOD close = NO swap fees | No EOD = bigger moves?")
    print()

if __name__ == '__main__':
    main()