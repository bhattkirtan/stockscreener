#!/usr/bin/env python3
"""Verify Phase 4 grid generates correct combinations"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

# Import grid definition directly
exec(open('scripts/run-phase4-optimization.py').read().split('def main()')[0])
from src.optimization.optimize_strategy import StrategyOptimizer

grid = define_phase4_grid()

print("="*80)
print("Phase 4 Grid Definition")
print("="*80)

# Show key parameters
key_params = [
    'supertrend_period',
    'supertrend_multiplier',
    'atr_sl_multiplier',
    'atr_tp_multiplier',
    'enable_friday_filter',
    'friday_cutoff_hour'
]

for param in key_params:
    if param in grid:
        values = grid[param]
        if isinstance(values, list):
            print(f"{param:25s}: {values}")

# Generate combinations
optimizer = StrategyOptimizer(None, validation_split=0.0)
combinations = optimizer.generate_combinations(grid)

print(f"\nTotal combinations: {len(combinations)}")

# Show unique values for key params
st_periods = sorted(set(c['supertrend_period'] for c in combinations))
tp_mults = sorted(set(c['atr_tp_multiplier'] for c in combinations))
friday_filters = sorted(set(c['enable_friday_filter'] for c in combinations))

print(f"\nUnique values:")
print(f"  Supertrend periods: {st_periods}")
print(f"  TP multipliers: {tp_mults}")
print(f"  Friday filters: {friday_filters}")
print(f"\nExpected: {len(st_periods)} ST × {len(tp_mults)} TP × {len(friday_filters)} Friday = {len(st_periods) * len(tp_mults) * len(friday_filters)} combinations")

# Show first few combinations
print(f"\n{'='*80}")
print("First 5 combinations:")
print("="*80)
for i, combo in enumerate(combinations[:5], 1):
    print(f"\n{i}. ST period={combo['supertrend_period']}, "
          f"TP mult={combo['atr_tp_multiplier']}, "
          f"Friday filter={combo['enable_friday_filter']}")
