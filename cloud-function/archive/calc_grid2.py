#!/usr/bin/env python3
"""Calculate FULLY expanded Phase 2 grid size with ST 2.5 AND 3.0"""

# Base parameters
st_mult = 2  # 2.5 and 3.0 (from top 10 analysis)

# Phase 1 variations
tp_sl = 2  # 3x and 4x
rsi = 2  # True/False
session = 3  # False, True+london_only, True+london_ny  
eod = 2  # True/False
phase1 = st_mult * tp_sl * rsi * session * eod

# Phase 2
adx = 3  # Off, On+20, On+25
bb = 2  # Off/On
dyn = 2  # Off/On
phase2 = adx * bb * dyn

total = phase1 * phase2

print("=" * 60)
print("FULLY EXPANDED PHASE 2 GRID - Top 10 Coverage")
print("=" * 60)

print(f"\nBase parameters:")
print(f"  ST multiplier: 2 options (2.5, 3.0) ← EXPANDED from top 10 analysis")
print(f"    - 6 of top 10 use ST 2.5 (ranks 1-5, 7)")
print(f"    - 4 of top 10 use ST 3.0 (ranks 6, 8-10)")

print(f"\nPhase 1 variations: {phase1} (ST×TP×RSI×Session×EOD)")
print(f"  - ST: 2 (2.5, 3.0)")
print(f"  - TP/SL: 2 (ATR 2x3, ATR 2x4)")
print(f"  - RSI filter: 2 (True, False)")
print(f"  - Session: 3 (False, True+london_only, True+london_ny)")
print(f"  - EOD blackout: 2 (True, False)")

print(f"\nPhase 2 features: {phase2} (ADX×BB×Dynamic)")
print(f"  - ADX filter: 3 (Off, On+threshold20, On+threshold25)")
print(f"  - BB position sizing: 2 (Off, On)")
print(f"  - Dynamic TP/SL: 2 (Off, On)")

print(f"\n{'=' * 60}")
print(f"TOTAL COMBINATIONS: {total}")
print(f"Estimated runtime: ~{total*12/60/60:.1f} hours @ 12s/backtest, 12 workers")
print(f"{'=' * 60}")

print(f"\nComparison:")
print(f"  Previous (ST 2.5 only): 288 combos (~1.0 hour)")
print(f"  Current (ST 2.5 + 3.0): {total} combos (~{total*12/60/60:.1f} hours)")
print(f"  Gain: Testing {st_mult}x more base configurations from top 10")
