#!/usr/bin/env python3
"""Quick parallel vs sequential benchmark (small subset)"""

import time
import sys
sys.path.insert(0, '/Users/kirtanbhatt/code/stockScreener/cloud-function')

from src.runners.run_backtest_from_cache import load_cached_data
from src.optimization.optimize_strategy import StrategyOptimizer

print("Loading data...")
df = load_cached_data('GOLD', 'M5', 3000)
if df is None:
    print("❌ Failed to load data")
    sys.exit(1)
print(f"✅ Loaded {len(df)} bars\n")

# Modify grid to test fewer combinations for speed
class FastOptimizer(StrategyOptimizer):
    def define_quick_grid(self):
        """Smaller grid for testing"""
        return {
            'supertrend_period': [10],
            'supertrend_multiplier': [2.0, 2.5],  # Just 2 values
            'sma_fast': [15],
            'sma_slow': [50],
            'ema_period': [21],
            'bb_period': [20],
            'bb_std': [2.0],
            'tp_sl_strategy': ['fixed'],  # Only fixed, skip ATR
            'sl_pips': [20, 30],  # Just 2 values
            'tp_pips': [40, 50, 60],  # Just 3 values
            'pip_value': [1.0, 1.2],  # Just 2 values
        }

# Calculate expected combinations
# 1 × 2 × 1 × 1 × 1 × 1 × 1 × 2 (base) = 4 base params
# Valid fixed TP/SL: sl=20 with tp=[40,50,60] + sl=30 with tp=[40,50,60] = 6
# Total: 4 × 6 = 24 combinations

print("Testing with ~24 strategy combinations\n")

# Sequential test
print("="*60)
print("SEQUENTIAL (n_jobs=1)")
print("="*60)
opt_seq = FastOptimizer(df, 10000, 'GOLD', 'M5', n_jobs=1)
start = time.time()
res_seq = opt_seq.run_optimization(mode='quick', parallel=False)
time_seq = time.time() - start
print(f"✅ Completed in {time_seq:.2f}s")
print(f"   Strategies: {len(res_seq)}")
print(f"   Best return: {res_seq.iloc[0]['return_pct']:.3f}%\n")

# Parallel test
print("="*60)
print(f"PARALLEL (n_jobs={opt_seq.n_jobs} cores)")
print("="*60)
opt_par = FastOptimizer(df, 10000, 'GOLD', 'M5', n_jobs=-1)
start = time.time()
res_par = opt_par.run_optimization(mode='quick', parallel=True)
time_par = time.time() - start
print(f"✅ Completed in {time_par:.2f}s")
print(f"   Strategies: {len(res_par)}")
print(f"   Best return: {res_par.iloc[0]['return_pct']:.3f}%\n")

# Results
print("="*60)
print("BENCHMARK RESULTS")
print("="*60)
print(f"Sequential:  {time_seq:.2f}s")
print(f"Parallel:    {time_par:.2f}s")
speedup = time_seq / time_par
print(f"Speedup:     {speedup:.2f}x faster 🚀")
print(f"Efficiency:  {speedup/opt_par.n_jobs*100:.1f}% (on {opt_par.n_jobs} cores)")
print()

if speedup > 1:
    print(f"✅ Parallel processing is {speedup:.1f}x faster!")
    print(f"   For 2,340 strategies, expect ~{2340*time_seq/speedup:.0f}s ({2340*time_seq/speedup/60:.1f} min)")
else:
    print("⚠️  No speedup - check if multiprocessing is working")
