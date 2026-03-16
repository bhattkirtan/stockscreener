#!/usr/bin/env python3
"""Quick test of parallel optimization"""

import time
from src.runners.run_backtest_from_cache import load_cached_data
from src.optimization.optimize_strategy import StrategyOptimizer

print("Loading data...")
df = load_cached_data('GOLD', 'M5', 1000)

print(f"Data loaded: {len(df)} bars\n")

# Test sequential
print("=" * 60)
print("TEST 1: Sequential (n_jobs=1)")
print("=" * 60)
optimizer_seq = StrategyOptimizer(df, 10000, 'GOLD', 'M5', n_jobs=1)

start = time.time()
results_seq = optimizer_seq.run_optimization(mode='quick', parallel=False)
elapsed_seq = time.time() - start

print(f"\n✅ Sequential completed in {elapsed_seq:.2f} seconds")
print(f"   Total strategies: {len(results_seq)}")
print(f"   Best return: {results_seq['return_pct'].max():.4f}%\n")

# Test parallel
print("=" * 60)
print("TEST 2: Parallel (all cores)")
print("=" * 60)
optimizer_par = StrategyOptimizer(df, 10000, 'GOLD', 'M5', n_jobs=-1)

start = time.time()
results_par = optimizer_par.run_optimization(mode='quick', parallel=True)
elapsed_par = time.time() - start

print(f"\n✅ Parallel completed in {elapsed_par:.2f} seconds")
print(f"   Total strategies: {len(results_par)}")
print(f"   Best return: {results_par['return_pct'].max():.4f}%\n")

# Compare
print("=" * 60)
print("COMPARISON")
print("=" * 60)
print(f"Sequential time: {elapsed_seq:.2f}s")
print(f"Parallel time:   {elapsed_par:.2f}s")
print(f"Speedup:         {elapsed_seq/elapsed_par:.2f}x faster")
print(f"Expected:        ~{optimizer_par.n_jobs}x on {optimizer_par.n_jobs} cores")
print()

# Verify results match
if len(results_seq) == len(results_par):
    print("✅ Same number of strategies tested")
    
    # Compare top strategy
    top_seq = results_seq.iloc[0]['strategy_name']
    top_par = results_par.iloc[0]['strategy_name']
    
    if top_seq == top_par:
        print(f"✅ Same top strategy: {top_seq}")
    else:
        print(f"⚠️  Different top strategies:")
        print(f"   Sequential: {top_seq}")
        print(f"   Parallel:   {top_par}")
else:
    print(f"⚠️  Different result counts: {len(results_seq)} vs {len(results_par)}")
