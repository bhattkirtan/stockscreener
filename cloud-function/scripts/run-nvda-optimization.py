#!/usr/bin/env python3
"""
NVDA M5 Optimization with Heiken Ashi Candles
Find optimal Supertrend/SMA parameters for NVIDIA stock trading
"""
import sys
import os
from pathlib import Path

# Add cloud-function to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from src.optimization.optimize_strategy import StrategyOptimizer

def define_nvda_ha_grid():
    """
    NVDA M5 Grid: Stock-specific parameters with Heiken Ashi
    
    GOAL: Find best Supertrend + SMA combo for NVDA intraday trading
    
    Stock characteristics vs Forex/Commodities:
    - Market hours: 9:30 AM - 4 PM ET (no 24h trading)
    - Higher volatility: Tech stocks can move 2-5% intraday
    - News-driven: Earnings, analyst reports, sector rotation
    - ATR-based stops: Essential for volatile stocks
    
    Heiken Ashi Benefits:
    - Smooths price action (filters noise)
    - Better trend identification
    - Reduces false signals in choppy markets
    
    TEST FOCUS:
    1. Supertrend Period: 7 (fast), 10 (balanced), 15 (smooth)
    2. Supertrend Multiplier: 2.0 (tight), 2.5, 3.0 (loose)
    3. SMA Fast: 10, 15, 21 (short-term trend)
    4. SMA Slow: 50 (standard), 100 (longer-term for stocks)
    5. EMA: 9, 12, 21 (momentum)
    6. ATR SL: 1.0, 1.5, 2.0 (stock volatility)
    7. ATR TP: 2.0, 3.0, 4.0 (R:R ratios)
    
    Total: 3 ST_period × 3 ST_mult × 3 SMA_fast × 2 SMA_slow × 3 EMA × 3 ATR_SL × 3 ATR_TP
         = 4,374 combinations (~30-40 minutes with 12 workers)
    """
    return {
        # TEST: Supertrend period for stocks (faster may work better for M5)
        'supertrend_period': [7, 10, 15],
        
        # TEST: Supertrend multiplier (stocks may need wider bands)
        'supertrend_multiplier': [2.0, 3.0],
        
        # TEST: SMA configurations for stocks
        'sma_fast': [10, 15, 21],
        'sma_slow': [50, 100],  # Standard stock SMAs
        
        # TEST: EMA for momentum
        'ema_period': [9, 21],
        
        # FIXED: Bollinger Bands (standard config)
        'bb_period': [20],
        'bb_std': [2.0],
        
        # ENABLED: Heiken Ashi for trend smoothing
        'use_heikin_ashi': [True],
        
        # ATR-based TP/SL (essential for volatile stocks)
        'tp_sl_strategy': ['atr'],
        
        # Fixed TP/SL (not used with ATR strategy)
        'sl_pips': [10],
        'tp_pips': [20],
        'pip_value': [1.0],
        
        # TEST: ATR multipliers for stock volatility
        'atr_sl_multiplier': [1.0, 2.0],
        'atr_tp_multiplier': [3.0, 4.0],
        
        # DISABLED: Additional filters (test baseline first)
        'use_rsi_filter': [False],
        'rsi_period': [14],
        'rsi_overbought': [70],
        'rsi_oversold': [30],
        
        'use_atr_volatility_filter': [False],
        'atr_volatility_period': [14],
        'atr_sma_period': [20],
        'atr_min_ratio': [0.7],
        'atr_max_ratio': [1.5],
        
        # ENABLED: Session filter (US market hours 9:30 AM - 4 PM ET)
        'use_session_filter': [True],
        'trading_sessions': ['us_market'],  # Only trade during US market hours
        
        # DISABLED: Time-based exits (let positions run to TP/SL)
        'enable_time_exit': [False],
        'max_holding_hours': [4],
        
        # ENABLED: EOD close (avoid overnight risk for stocks)
        'enable_eod_close': [True],
        'eod_close_hour': [16],  # Close at 4 PM ET
        
        # ENABLED: EOD blackout (no entries in last hour)
        'enable_eod_blackout': [True],
        'no_entry_before_eod_hours': [1],  # No entries after 3 PM ET
        
        # DISABLED: Friday filter (not needed with EOD close)
        'enable_friday_filter': [False],
        'friday_cutoff_hour': [15]
    }

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='NVDA M5 + Heiken Ashi Optimization')
    parser.add_argument('--data-file', default='data/NVDA_M5_150000bars.csv', help='Path to NVDA CSV data')
    parser.add_argument('--validation-split', type=float, default=0.2, help='Train/test split (0.2 = 80/20)')
    parser.add_argument('--max-rows', type=int, default=None, help='Limit data rows (e.g., 50000 for faster testing)')
    parser.add_argument('--n-jobs', type=int, default=12, help='Number of parallel workers')
    
    args = parser.parse_args()
    
    print("\n" + "="*80)
    print("📈 NVDA M5 OPTIMIZATION with HEIKEN ASHI")
    print("="*80 + "\n")
    
    print("🎯 STRATEGY:")
    print("   - Heiken Ashi: ENABLED (trend smoothing)")
    print("   - Market Hours: US only (9:30 AM - 4 PM ET)")
    print("   - EOD Close: ENABLED (no overnight risk)")
    print("   - ATR-based TP/SL: Stock volatility adjusted")
    print()
    
    print("🔬 TESTING:")
    print("   - Supertrend Period: 7, 10, 15")
    print("   - Supertrend Multiplier: 2.0, 2.5, 3.0")
    print("   - SMA Fast: 10, 15, 21")
    print("   - SMA Slow: 50, 100")
    print("   - EMA: 9, 12, 21")
    print("   - ATR SL: 1.0x, 1.5x, 2.0x")
    print("   - ATR TP: 2.0x, 3.0x, 4.0x")
    print("   - Total: 4,374 combinations")
    print()
    print("⏱️  Expected runtime: ~30-40 minutes with 12 workers")
    print()
    
    # Load data
    print(f"📊 Loading NVDA data from {args.data_file}...")
    try:
        df = pd.read_csv(args.data_file)
        
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
        else:
            df.index = pd.to_datetime(df.index)
        
        # Slice data if max_rows specified
        if args.max_rows and len(df) > args.max_rows:
            print(f"⚡ Using first {args.max_rows:,} bars (out of {len(df):,}) for faster testing")
            df = df.head(args.max_rows)
        
        print(f"✅ Loaded {len(df):,} bars")
        print(f"   Range: {df.index[0]} to {df.index[-1]}")
        print(f"   Duration: {(df.index[-1] - df.index[0]).days} days")
        print()
        
    except FileNotFoundError:
        print(f"❌ Data file not found: {args.data_file}")
        print()
        print("💡 To fetch NVDA data, run:")
        print(f"   python3 scripts/fetch-m5-data.py --instrument NVDA --bars 150000 --resolution M5")
        print()
        sys.exit(1)
    except Exception as e:
        print(f"❌ Failed to load data: {e}")
        sys.exit(1)
    
    # Create optimizer with custom grid
    print("🚀 Starting NVDA + Heiken Ashi optimization...")
    optimizer = StrategyOptimizer(
        df=df,
        initial_capital=10000.0,
        epic='NVDA',
        resolution='M5',
        validation_split=args.validation_split,
        n_jobs=args.n_jobs
    )
    
    # Override the intraday grid with NVDA HA grid
    original_grid_func = optimizer.define_intraday_grid
    optimizer.define_intraday_grid = define_nvda_ha_grid
    
    # Run optimization
    results_df = optimizer.run_optimization(
        mode='intraday',
        parallel=True
    )
    
    # Restore original
    optimizer.define_intraday_grid = original_grid_func
    
    # Show summary
    print("\n" + "="*80)
    print("📊 NVDA + HEIKEN ASHI RESULTS")
    print("="*80 + "\n")
    
    optimizer.print_summary(results_df, top_n=10)
    
    # Export results
    output_file = optimizer.export_results(results_df)
    
    if output_file:
        print(f"\n📁 Results exported to: {output_file}")
        
        # Also save top 20 for validation
        top_20 = results_df.head(20)
        top_20_file = output_file.replace('.csv', '_top20.csv')
        top_20.to_csv(top_20_file, index=False)
        print(f"📁 Top 20 saved to: {top_20_file}")
    
    # Show parameter analysis
    print("\n" + "="*80)
    print("📊 PARAMETER IMPACT ANALYSIS")
    print("="*80)
    
    if not results_df.empty:
        # Group by key parameters
        top_50 = results_df.head(50)
        
        print("\n🔧 Best Supertrend Period:")
        for period in sorted(top_50['supertrend_period'].unique()):
            period_results = top_50[top_50['supertrend_period'] == period]
            avg_return = period_results['return_pct'].mean()
            count = len(period_results)
            print(f"   Period {period}: Avg {avg_return:.2f}% ({count} in top 50)")
        
        print("\n🔧 Best Supertrend Multiplier:")
        for mult in sorted(top_50['supertrend_multiplier'].unique()):
            mult_results = top_50[top_50['supertrend_multiplier'] == mult]
            avg_return = mult_results['return_pct'].mean()
            count = len(mult_results)
            print(f"   Mult {mult:.1f}: Avg {avg_return:.2f}% ({count} in top 50)")
        
        print("\n🔧 Best SMA Configuration:")
        sma_combos = top_50.groupby(['sma_fast', 'sma_slow']).agg({
            'return_pct': 'mean',
            'win_rate': 'mean'
        }).sort_values('return_pct', ascending=False).head(5)
        for (fast, slow), row in sma_combos.iterrows():
            print(f"   SMA {fast}/{slow}: {row['return_pct']:.2f}% (WR: {row['win_rate']:.1f}%)")
        
        print("\n🔧 Best ATR TP/SL Ratio:")
        atr_combos = top_50.groupby(['atr_sl_multiplier', 'atr_tp_multiplier']).agg({
            'return_pct': 'mean',
            'win_rate': 'mean',
            'total_trades': 'mean'
        }).sort_values('return_pct', ascending=False).head(5)
        for (sl, tp), row in atr_combos.iterrows():
            rr = tp / sl
            print(f"   SL {sl:.1f}x / TP {tp:.1f}x (R:R 1:{rr:.1f}): {row['return_pct']:.2f}% | Trades: {row['total_trades']:.0f}")
    
    print("\n✅ NVDA + Heiken Ashi optimization complete!\n")
    print("💡 Next steps:")
    print("   1. Review top 10 strategies")
    print("   2. Check parameter patterns (which Supertrend/SMA combos work best?)")
    print("   3. Validate top strategy on test set")
    print("   4. Compare with/without Heiken Ashi (run again with use_heikin_ashi=[False])")
    print()

if __name__ == '__main__':
    main()
