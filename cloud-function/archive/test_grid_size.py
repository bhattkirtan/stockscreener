#!/usr/bin/env python3
import sys
sys.path.insert(0, '.')
from src.optimization.optimize_strategy import StrategyOptimizer
import pandas as pd

df = pd.DataFrame({'open': [2500]*100, 'high': [2510]*100, 'low': [2490]*100, 'close': [2505]*100, 'volume': [1000]*100})
df.index = pd.date_range('2026-01-01', periods=100, freq='5min')

optimizer = StrategyOptimizer(df, 10000, 'GOLD', 'M5', n_jobs=1)
grid = optimizer.define_intraday_grid()
combos = optimizer.generate_combinations(grid)

print(f'Total combinations: {len(combos):,}')
print(f'Estimated time: {len(combos) / 12 / 60:.1f} hours ({len(combos) / 12 / 60 * 60:.0f} minutes) with 12 workers')
