#!/usr/bin/env python3
"""
Compare Phase 1/2 (with train/test split) vs Phase 3 (no split)
"""
import pandas as pd

print("=" * 80)
print("🔬 TRAIN/TEST SPLIT COMPARISON")
print("=" * 80)

# Load Phase 2 (March 7) - has train/test split
df_p2 = pd.read_csv('data/optimization/2026-03-07/run_20260307_233341/GOLD_M5_all_strategies_20260307_233341.csv')
print("\n📊 Phase 2 Results (March 7 - WITH train/test split):")
print(f"   Total strategies: {len(df_p2)}")
test_cols_p2 = [c for c in df_p2.columns if 'test' in c.lower()]
print(f"   Test columns: {len(test_cols_p2)} found ✅")

# Find Phase 1 baseline in Phase 2 results
baseline_p2 = df_p2[
    (df_p2['use_rsi_filter']==False) &
    (df_p2['use_session_filter']==False) &
    (df_p2['enable_eod_blackout']==True) &
    (df_p2['use_adx_filter']==False) &
    (df_p2['use_dynamic_tp_sl']==False)
]

if len(baseline_p2) > 0:
    b = baseline_p2.iloc[0]
    print(f"\n✅ Phase 1 Baseline (RSI=False, Session=False, EOD=True):")
    print(f"   Train: {b['return_pct']:.2f}%")
    print(f"   Test: {b['test_return_pct']:.2f}%")
    print(f"   Generalization: {b['test_return_pct'] / b['return_pct']:.2f}x")
    print(f"   Trades (train): {int(b['total_trades'])}")

# Find best RSI=True in Phase 2
best_rsi_p2 = df_p2[
    (df_p2['use_rsi_filter']==True) &
    (df_p2['use_adx_filter']==False) &
    (df_p2['use_dynamic_tp_sl']==False)
].nlargest(1, 'return_pct')

if len(best_rsi_p2) > 0:
    br = best_rsi_p2.iloc[0]
    print(f"\n🏆 Best RSI=True (Phase 2 data, no Phase 2 features):")
    print(f"   Train: {br['return_pct']:.2f}%")
    print(f"   Test: {br['test_return_pct']:.2f}%")
    print(f"   Generalization: {br['test_return_pct'] / br['return_pct']:.2f}x")
    print(f"   Trades (train): {int(br['total_trades'])}")
    print(f"   Config: Session={br['use_session_filter']}, EOD={br['enable_eod_blackout']}")

# Load Phase 3 (March 8) - NO train/test split
df_p3 = pd.read_csv('data/optimization/2026-03-08/run_20260308_123951/GOLD_M5_all_strategies_20260308_123951.csv')
print("\n" + "=" * 80)
print("📊 Phase 3 Results (March 8 - NO train/test split):")
print(f"   Total strategies: {len(df_p3)}")
test_cols_p3 = [c for c in df_p3.columns if 'test' in c.lower()]
print(f"   Test columns: {len(test_cols_p3)} found ⚠️  NONE!")

# Find Phase 1 baseline in Phase 3 results
baseline_p3 = df_p3[
    (df_p3['use_rsi_filter']==False) &
    (df_p3['use_session_filter']==False) &
    (df_p3['enable_eod_blackout']==True) &
    (df_p3['use_mtf_confirmation']==False) &
    (df_p3['use_sr_filter']==False)
]

if len(baseline_p3) > 0:
    b3 = baseline_p3.iloc[0]
    print(f"\n📈 Phase 1 Baseline (same config, all data, no split):")
    print(f"   Return: {b3['return_pct']:.2f}%")
    print(f"   Trades: {int(b3['total_trades'])}")
    if len(baseline_p2) > 0:
        b = baseline_p2.iloc[0]
        print(f"   vs Phase 2 train: {b3['return_pct'] - b['return_pct']:+.2f}%")
        print(f"   vs Phase 2 test: {b3['return_pct'] - b['test_return_pct']:+.2f}%")
        print(f"   Trade count ratio: {b3['total_trades'] / b['total_trades']:.2f}x")

# Find best RSI=True in Phase 3
best_rsi_p3 = df_p3[
    (df_p3['use_rsi_filter']==True) &
    (df_p3['use_mtf_confirmation']==False) &
    (df_p3['use_sr_filter']==False)
].nlargest(1, 'return_pct')

if len(best_rsi_p3) > 0:
    br3 = best_rsi_p3.iloc[0]
    print(f"\n🏆 Best RSI=True (all data, no split):")
    print(f"   Return: {br3['return_pct']:.2f}%")
    print(f"   Trades: {int(br3['total_trades'])}")
    print(f"   Config: Session={br3['use_session_filter']}, EOD={br3['enable_eod_blackout']}")
    
    if len(best_rsi_p2) > 0:
        br = best_rsi_p2.iloc[0]
        print(f"\n   📊 Comparison to Phase 2 (with split):")
        print(f"      Phase 3 (no split): {br3['return_pct']:.2f}%")
        print(f"      Phase 2 train: {br['return_pct']:.2f}%")
        print(f"      Phase 2 test: {br['test_return_pct']:.2f}%")
        print(f"      Difference: {br3['return_pct'] - br['return_pct']:+.2f}% vs train")
        print(f"                  {br3['return_pct'] - br['test_return_pct']:+.2f}% vs test")

print("\n" + "=" * 80)
print("🎯 CONCLUSION")
print("=" * 80)
print("\n⚠️  CRITICAL: Phase 3 results are NOT comparable to Phase 1/2!")
print("   - Phase 1/2: Used 70/30 train/test split")
print("   - Phase 3: Used ALL data for training (no validation)")
print("\n📋 TO GET VALID RESULTS:")
print("   1. Re-run Phase 3 WITH --validation-split 0.3")
print("   2. Compare test performance (not train)")
print(f"   3. Current Phase 3 best ({br3['return_pct']:.2f}%) is likely OVERFITTED")
print("\n" + "=" * 80)
