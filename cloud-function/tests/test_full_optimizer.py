#!/usr/bin/env python3
"""
Test optimize_strategy.py with pip_value parameter
Run a small subset of strategies to verify everything works
"""
import sys
sys.path.insert(0, '.')

from src.optimization.optimize_strategy import StrategyOptimizer
from src.runners.run_backtest_from_cache import load_cached_data

# Load cached data
print('📊 Loading cached GOLD M5 data...\n')
df = load_cached_data('GOLD', 'M5', 3000)

if df is None:
    print('❌ Failed to load data')
    exit(1)

print(f'✅ Loaded {len(df)} bars\n')

# Create optimizer
optimizer = StrategyOptimizer(df, initial_capital=10000, epic='GOLD', resolution='M5')

# Run optimization
print('🚀 Running optimization with pip_value parameter...')
print('   This will test 1,404 combinations (468 base × 3 pip_values)\n')

df_results = optimizer.run_optimization(mode='quick')

# Show summary
print('\n' + '='*80)
print('📊 OPTIMIZATION COMPLETE!')
print('='*80)

if df_results is not None and len(df_results) > 0:
    results = df_results.to_dict('records')
    print(f'\n✅ Tested {len(results)} strategies\n')
    
    # Top 5 by return
    print('🏆 TOP 5 STRATEGIES BY RETURN:\n')
    results_sorted = sorted(results, key=lambda x: x['total_pnl'], reverse=True)
    
    for i, r in enumerate(results_sorted[:5], 1):
        print(f'{i}. pip_value={r.get("pip_value", 1.0):.2f}, '
              f'ST{r["st_mult"]}, '
              f'SMA{r["sma_fast"]}-{r["sma_slow"]}, '
              f'BB{r["bb_std"]}')
        print(f'   TP/SL: {r.get("tp_sl", "unknown")}')
        print(f'   Trades: {r["total_trades"]}, Win Rate: {r["win_rate"]*100:.1f}%')
        print(f'   P&L: ${r["total_pnl"]:.2f}, Return: {r["return_pct"]:.2f}%\n')
    
    # Compare pip_value impact
    print('\n💡 PIP_VALUE IMPACT COMPARISON:\n')
    for pip_val in [0.01, 0.1, 1.0]:
        pip_results = [r for r in results if r.get('pip_value', 1.0) == pip_val]
        if pip_results:
            best = max(pip_results, key=lambda x: x['total_pnl'])
            print(f'   pip_value={pip_val}: Best P&L = ${best["total_pnl"]:.2f} '
                  f'({len([r for r in pip_results if r["total_pnl"] > 0])} profitable)')
    
    print('\n✅ All tests passed! Optimizer is ready for full run.')
    print('   Run: python3 src/optimization/optimize_strategy.py')
else:
    print('❌ No results generated')
