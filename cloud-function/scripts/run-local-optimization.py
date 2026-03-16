#!/usr/bin/env python3
"""
Run optimization using local data files (bypass GCS)
"""
import sys
import os
import pandas as pd
from pathlib import Path

# Add cloud-function to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.optimization.optimize_strategy import StrategyOptimizer

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Local Strategy Optimization')
    parser.add_argument('--data-file', required=True, help='Path to CSV data file')
    parser.add_argument('--instrument', default='GOLD', help='Instrument name')
    parser.add_argument('--timeframe', default='M5', help='Timeframe')
    parser.add_argument('--capital', type=float, default=10000.0, help='Initial capital')
    parser.add_argument('--mode', default='quick', choices=['short', 'quick', 'medium', 'full', 'intraday', 'zone'], help='Optimization mode: short=~2k combos, quick=intraday, medium, full=186k, zone=~1.1k zone-vs-baseline')
    parser.add_argument('--validation-split', type=float, default=0.0, help='Train/test split ratio (e.g., 0.3 for 70/30 split)')
    parser.add_argument('--n-jobs', type=int, default=12, help='Number of parallel workers (default: 12, use -1 for all cores)')
    parser.add_argument('--no-parallel', action='store_true', help='Disable parallel processing')
    parser.add_argument('--enable-event-blocking', action='store_true', help='Enable event blocking (requires --calendar-path)')
    parser.add_argument('--calendar-path', default='data/economic_calendar.json', help='Path to economic calendar JSON file')
    parser.add_argument('--sample', type=int, default=0, help='Randomly sample N combinations instead of testing all (e.g. --sample 3000). 0 = test all.')
    
    args = parser.parse_args()
    
    print("\n" + "="*70)
    print("🎯 Local Strategy Parameter Optimization")
    print("="*70 + "\n")
    
    # Load data from local CSV
    print(f"📊 Loading data from {args.data_file}...")
    try:
        df = pd.read_csv(args.data_file)
        
        # Set timestamp as index
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
        else:
            df.index = pd.to_datetime(df.index)
        
        print(f"✅ Loaded {len(df)} bars")
        print(f"   Range: {df.index[0]} to {df.index[-1]}")
        print(f"   Columns: {list(df.columns)}\n")
        
    except Exception as e:
        print(f"❌ Failed to load data: {e}")
        sys.exit(1)
    
    # Run optimization
    print(f"🚀 Starting optimization...")
    print(f"   Mode: {args.mode}")
    print(f"   Capital: ${args.capital:,.2f}")
    if args.validation_split > 0:
        print(f"   Validation Split: {args.validation_split:.1%} (Train: {(1-args.validation_split):.1%}, Test: {args.validation_split:.1%})")
    n_workers = args.n_jobs if args.n_jobs > 0 else os.cpu_count()
    print(f"   Parallel: {'Yes' if not args.no_parallel else 'No'} ({n_workers} workers)")
    print(f"   Concurrency: {n_workers}x")
    if args.sample > 0:
        print(f"   🎲 Random sample: {args.sample:,} combinations (from full grid)")
    if args.enable_event_blocking:
        print(f"   🚫 Event Blocking: ENABLED")
        print(f"   📅 Calendar: {args.calendar_path}")
    print()
    
    optimizer = StrategyOptimizer(
        df=df,
        initial_capital=args.capital,
        epic=args.instrument,
        resolution=args.timeframe,
        validation_split=args.validation_split,
        n_jobs=args.n_jobs
    )
    
    # If event blocking is enabled, inject into parameter grid
    if args.enable_event_blocking:
        # Temporarily modify the grid method to include event blocking
        original_quick_grid = optimizer.define_quick_grid
        original_medium_grid = optimizer.define_medium_grid
        original_intraday_grid = optimizer.define_intraday_grid
        original_full_grid = optimizer.define_parameter_grid
        
        def add_event_blocking(grid):
            grid['enable_event_blocking'] = [True]
            grid['calendar_path'] = [args.calendar_path]
            return grid
        
        optimizer.define_quick_grid = lambda: add_event_blocking(original_quick_grid())
        optimizer.define_medium_grid = lambda: add_event_blocking(original_medium_grid())
        optimizer.define_intraday_grid = lambda: add_event_blocking(original_intraday_grid())
        optimizer.define_parameter_grid = lambda: add_event_blocking(original_full_grid())
    
    results_df = optimizer.run_optimization(
        mode=args.mode,
        parallel=not args.no_parallel,
        max_combos=args.sample if args.sample > 0 else None
    )
    
    # Show summary
    print("\n" + "="*70)
    print("📊 OPTIMIZATION RESULTS")
    print("="*70 + "\n")
    
    optimizer.print_summary(results_df, top_n=20)
    
    # Export results
    output_file = optimizer.export_results(results_df)
    
    if output_file:
        print(f"\n✅ Results saved to: {output_file}")
        
        # Also save top strategies for validation
        top_50 = results_df.head(50)
        top_50_file = output_file.replace('.csv', '_top50.csv')
        top_50.to_csv(top_50_file, index=False)
        print(f"✅ Top 50 saved to: {top_50_file}")
    
    print("\n✅ Optimization complete!\n")


if __name__ == '__main__':
    main()
