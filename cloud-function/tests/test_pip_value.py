#!/usr/bin/env python3
"""
Compare pip_value impact: 0.01 vs 1.0
"""
import sys
sys.path.insert(0, '.')

from src.optimization.optimize_strategy import StrategyOptimizer
from src.runners.run_backtest_from_cache import load_cached_data

# Load cached data
print('📊 Loading cached GOLD M5 data...')
df = load_cached_data('GOLD', 'M5', 3000)

if df is not None:
    print(f'✅ Loaded {len(df)} bars\n')
    
    optimizer = StrategyOptimizer(df, initial_capital=10000, epic='GOLD', resolution='M5')
    
    # Test same strategy with different pip_values
    test_params = {
        'supertrend_period': 10,
        'supertrend_multiplier': 2.0,
        'sma_fast': 15,
        'sma_slow': 50,
        'ema_period': 21,
        'bb_period': 20,
        'bb_std': 2.0,
        'tp_sl_strategy': 'fixed',
        'sl_pips': 20,
        'tp_pips': 60,
        'atr_sl_multiplier': None,
        'atr_tp_multiplier': None,
    }
    
    print('🧪 Testing SAME strategy with different pip_values:\n')
    print('='*70)
    
    for pip_val in [0.01, 0.1, 1.0]:
        test_params['pip_value'] = pip_val
        result = optimizer.run_single_backtest(test_params)
        
        if result and result['valid']:
            print(f'\n📊 pip_value = {pip_val}:')
            print(f'   Trades: {result["total_trades"]}')
            print(f'   Win Rate: {result["win_rate"]*100:.1f}%')
            print(f'   P&L: ${result["total_pnl"]:.2f}')
            print(f'   Return: {(result["total_pnl"]/10000)*100:.3f}%')
            
            if 'avg_win' in result:
                print(f'   Avg Win: ${result["avg_win"]:.2f}')
            if 'avg_loss' in result:
                print(f'   Avg Loss: ${result["avg_loss"]:.2f}')
        else:
            print(f'\n❌ pip_value = {pip_val}: {result.get("error", "Failed")}')
    
    print('\n' + '='*70)
    print('\n💡 Expected behavior:')
    print('   • pip_value 0.01 → Small profits (forex-style)')
    print('   • pip_value 0.1  → 10x larger profits')
    print('   • pip_value 1.0  → 100x larger profits (proper GOLD)')
