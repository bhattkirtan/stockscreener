#!/usr/bin/env python3
"""
Quick test of optimize_strategy.py with pip_value parameter
"""
import sys
sys.path.insert(0, '.')

from src.optimization.optimize_strategy import StrategyOptimizer
from src.runners.run_backtest_from_cache import load_cached_data

# Load cached data
print('📊 Loading cached GOLD M5 data...')
df = load_cached_data('GOLD', 'M5', 3000)

if df is not None:
    print(f'✅ Loaded {len(df)} bars')
    
    # Create optimizer
    print('\n🔧 Creating optimizer with pip_value parameter...')
    optimizer = StrategyOptimizer(df, initial_capital=10000, epic='GOLD', resolution='M5')
    
    # Get parameter grid
    grid = optimizer.define_quick_grid()
    print(f'\n📋 Parameter grid:')
    for key, values in grid.items():
        print(f'  {key}: {values}')
    
    # Calculate total combinations
    combos = optimizer.generate_combinations(grid)
    print(f'\n🎯 Total combinations to test: {len(combos)}')
    print(f'   Previous (without pip_value): ~468')
    print(f'   New (with pip_value): {len(combos)}')
    
    if len(combos) > 0:
        print(f'\n✅ Optimizer setup successful!')
        print(f'\n📝 First 3 combo samples:')
        for i, combo in enumerate(combos[:3], 1):
            print(f'\n  {i}. {combo}')
        
        # Test running ONE backtest to verify it works
        print(f'\n🧪 Testing single backtest with pip_value...')
        result = optimizer.run_single_backtest(combos[0])
        
        if result and result['valid']:
            print(f'✅ Backtest successful!')
            print(f'   Signals: {result["total_signals"]}')
            print(f'   Trades: {result["total_trades"]}')
            print(f'   P&L: ${result["total_pnl"]:.2f}')
            print(f'   Win Rate: {result["win_rate"]:.1%}')
        else:
            print(f'❌ Backtest failed: {result.get("error", "Unknown error")}')
    else:
        print('❌ No combinations generated!')
else:
    print('❌ Failed to load data')
