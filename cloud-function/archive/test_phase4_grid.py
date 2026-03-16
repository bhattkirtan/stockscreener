#!/usr/bin/env python3
"""Test Phase 4 grid generation with Heiken Ashi parameter"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from scripts.run_phase4_optimization import define_phase4_grid
from src.optimization.optimize_strategy import StrategyOptimizer
import pandas as pd

# Create a dummy optimizer to test grid generation
dummy_df = pd.DataFrame({
    'close': [1, 2, 3], 
    'high': [1, 2, 3], 
    'low': [1, 2, 3], 
    'open': [1, 2, 3], 
    'volume': [100, 100, 100]
})
optimizer = StrategyOptimizer(
    df=dummy_df, 
    initial_capital=10000, 
    epic='GOLD', 
    resolution='M5'
)

# Get Phase 4 grid
grid = define_phase4_grid()

# Generate combinations
combos = optimizer.generate_combinations(grid)

print(f'✅ Phase 4 grid generates {len(combos)} combinations')

# Check if use_heikin_ashi is in the combos
has_ha = any('use_heikin_ashi' in combo for combo in combos)
print(f'✅ use_heikin_ashi parameter present: {has_ha}')

# Count HA True vs False
if has_ha:
    ha_true = sum(1 for combo in combos if combo.get('use_heikin_ashi', False) == True)
    ha_false = sum(1 for combo in combos if combo.get('use_heikin_ashi', False) == False)
    print(f'   - With HA: {ha_true} combinations')
    print(f'   - Without HA: {ha_false} combinations')

# Show first combo
print(f'\n📋 Sample combination (first with HA=True):')
for combo in combos:
    if combo.get('use_heikin_ashi', False):
        print(f"   ST period: {combo['supertrend_period']}")
        print(f"   SL: {combo['atr_sl_multiplier']}× ATR")
        print(f"   TP: {combo['atr_tp_multiplier']}× ATR")
        print(f"   Time exit: {combo['enable_time_exit']}")
        print(f"   EOD close: {combo['enable_eod_close']}")
        print(f"   Heiken Ashi: {combo['use_heikin_ashi']}")
        break

print(f'\n📋 Sample combination (first with HA=False):')
for combo in combos:
    if not combo.get('use_heikin_ashi', False):
        print(f"   ST period: {combo['supertrend_period']}")
        print(f"   SL: {combo['atr_sl_multiplier']}× ATR")
        print(f"   TP: {combo['atr_tp_multiplier']}× ATR")
        print(f"   Time exit: {combo['enable_time_exit']}")
        print(f"   EOD close: {combo['enable_eod_close']}")
        print(f"   Heiken Ashi: {combo['use_heikin_ashi']}")
        break

print(f'\n🎯 Expected: 192 combinations (3 SL × 4 TP × 2 ST × 2 time × 2 EOD × 2 HA)')
print(f'   Actual: {len(combos)} combinations')
print(f'   {"✅ PASS" if len(combos) == 192 else "❌ FAIL"}')
