#!/usr/bin/env python3
"""Calculate expanded Phase 2 grid size"""

# Phase 1 from top 3
tp_sl = 2  # 3x and 4x
rsi = 2  # True/False
session = 3  # False, True+london_only, True+london_ny  
eod = 2  # True/False
phase1 = tp_sl * rsi * session * eod

# Phase 2
adx = 3  # Off, On+20, On+25
bb = 2  # Off/On
dyn = 2  # Off/On
phase2 = adx * bb * dyn

total = phase1 * phase2

print("=" * 60)
print("EXPANDED PHASE 2 GRID - Testing Top 3 Variations")
print("=" * 60)
print(f"\nPhase 1 variations: {phase1} (TP×RSI×Session×EOD)")
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

print(f"\nGrid covers all top 3 Phase 1 configurations:")
print(f"  ✓ Rank 1 (59.23%): TP 4x, RSI=T, Session=F, EOD=T")
print(f"  ✓ Rank 2 (51.22%): TP 3x, RSI=T, Session=T(london_only), EOD=F")
print(f"  ✓ Rank 3 (46.45%): TP 4x, RSI=F, Session=T(london_ny), EOD=T")
print(f"  ✓ Each tested with {phase2} Phase 2 feature combinations")
