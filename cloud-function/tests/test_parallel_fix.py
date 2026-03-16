#!/usr/bin/env python3
"""
Test DataFrame ambiguity fix - minimal test
"""
import sys
import os

from src.runners.run_backtest_from_cache import load_cached_data
from src.optimization.optimize_strategy import StrategyOptimizer

def main():
    # Load minimal data
    df = load_cached_data('GOLD', 'M5', 3000)
    if df is None:
        print("❌ Could not load data")
        return
    
    print(f"✅ Loaded {len(df)} bars\n")
    
    # Test with minimal parameters - just 6 combinations
    optimizer = StrategyOptimizer(df, 10000.0, 'GOLD', 'M5', n_jobs=2)
    
    # Override to create minimal grid
    def minimal_grid():
        return {
            'supertrend_period': [10],
            'supertrend_multiplier': [2.0],
            'sma_fast': [15],
            'sma_slow': [50],
            'ema_period': [20],
            'bb_period': [20],
            'bb_std': [2.0],
            'sl_pips': [None],  # ATR-based
            'tp_pips': [None],  # ATR-based
            'atr_period': [14],
            'atr_sl_multiplier': [1.5],
            'atr_tp_multiplier': [3.0],
            'tp_sl_strategy': ['atr'],
            'fastema_period': [30],
            'slowema_period': [50],
            'pip_value': [0.01, 1.0, 1.5]  # 3 values = 3 combinations
        }
    
    optimizer.define_quick_grid = minimal_grid
    
    print("🧪 Testing with 3 strategies (parallel mode, 1 worker)\n")
    results = optimizer.run_optimization(mode='quick', parallel=True)
    
    if len(results) > 0:
        print(f"\n✅ SUCCESS! {len(results)} valid results")
        print(f"   Best return: {results.iloc[0]['return_pct']:.2f}%")
    else:
        print("\n❌ FAILED - No valid results")

if __name__ == '__main__':
    main()
