#!/usr/bin/env python3
"""
Detailed Phase 3 Analysis - Check for overfitting and compare to baseline
"""
import pandas as pd
import sys

# Load Phase 3 results
csv_path = "data/optimization/2026-03-08/run_20260308_123951/GOLD_M5_all_strategies_20260308_123951.csv"
df = pd.read_csv(csv_path)

print("=" * 80)
print("🔬 DETAILED PHASE 3 INVESTIGATION")
print("=" * 80)

# Check for test/validation columns
print("\n📊 Available Columns:")
test_cols = [c for c in df.columns if 'test' in c.lower() or 'oos' in c.lower() or 'valid' in c.lower()]
if test_cols:
    print(f"   Test/Validation columns found: {test_cols}")
else:
    print("   ⚠️  NO test/validation columns found!")
    print("   ⚠️  Cannot verify generalization - results are TRAIN ONLY")

# Detailed analysis of top strategy
print("\n" + "=" * 80)
print("🏆 TOP STRATEGY DETAILED ANALYSIS")
print("=" * 80)
top = df.nlargest(1, 'return_pct').iloc[0]
print(f"\n📈 Performance Metrics:")
print(f"   Train Return: {top['return_pct']:.2f}%")
print(f"   Total Trades: {int(top['total_trades'])}")
print(f"   Sharpe Ratio: {top['sharpe_ratio']:.3f}")
print(f"   Win Rate: {top['win_rate']*100:.1f}%")
print(f"   Profit Factor: {top['profit_factor']:.2f}")
print(f"   Max Drawdown: {top['max_drawdown_pct']:.2f}%")
print(f"   Avg Win: ${top['avg_win']:.2f}")
print(f"   Avg Loss: ${top['avg_loss']:.2f}")

print(f"\n🎯 Strategy Configuration:")
print(f"   Supertrend: Period={int(top['st_period'])}, Mult={top['st_mult']}")
print(f"   SMA: Fast={int(top['sma_fast'])}, Slow={int(top['sma_slow'])}")
print(f"   TP/SL: {top['tp_sl']}")
print(f"   RSI Filter: {top['use_rsi_filter']}")
print(f"   Session Filter: {top['use_session_filter']}")
print(f"   EOD Blackout: {top['enable_eod_blackout']}")
print(f"   MTF Confirmation: {top['use_mtf_confirmation']}")
print(f"   S/R Filter: {top['use_sr_filter']}")

# Check if top 10 are all identical
print("\n" + "=" * 80)
print("📊 TOP 10 RETURN DISTRIBUTION")
print("=" * 80)
top10 = df.nlargest(10, 'return_pct')
print("\nReturn Statistics:")
print(top10['return_pct'].describe())
unique_returns = top10['return_pct'].nunique()
print(f"\nUnique return values in top 10: {unique_returns}")
if unique_returns == 1:
    print("⚠️  WARNING: All top 10 have IDENTICAL returns - likely same entry/exit points!")
    print("   This suggests parameters varied don't affect these specific trades")

# Phase 1 baseline comparison
print("\n" + "=" * 80)
print("🔍 PHASE 1 BASELINE COMPARISON")
print("=" * 80)

# Get all strategies without Phase 3 features
no_phase3 = df[(df['use_mtf_confirmation']==False) & (df['use_sr_filter']==False)]
print(f"\nStrategies without Phase 3 features: {len(no_phase3)}")
print(f"Best return (no Phase 3): {no_phase3['return_pct'].max():.2f}%")
print(f"Mean return (no Phase 3): {no_phase3['return_pct'].mean():.2f}%")

# Check RSI filter impact
print("\n📊 RSI Filter Impact (Phase 3 disabled):")
rsi_analysis = no_phase3.groupby('use_rsi_filter')['return_pct'].agg(['mean','max','min','count'])
print(rsi_analysis)

rsi_true = no_phase3[no_phase3['use_rsi_filter']==True]['return_pct'].mean()
rsi_false = no_phase3[no_phase3['use_rsi_filter']==False]['return_pct'].mean()
print(f"\nRSI Impact: {rsi_true - rsi_false:+.2f}% ({rsi_true:.2f}% vs {rsi_false:.2f}%)")

# Find Phase 1 baseline equivalent (RSI=False, Session=?, EOD=?)
print("\n📊 Phase 1 Configurations (MTF=False, S/R=False):")
phase1_configs = no_phase3.groupby(['use_rsi_filter','use_session_filter','enable_eod_blackout'])['return_pct'].agg(['mean','max','count'])
phase1_configs_sorted = phase1_configs.sort_values('max', ascending=False)
print(phase1_configs_sorted.head(10))

# Compare to original Phase 1 baseline (59.23%)
baseline_return = 59.23
print(f"\n🎯 Original Phase 1 Baseline: {baseline_return}%")
print(f"   New best (RSI=True): {no_phase3['return_pct'].max():.2f}%")
print(f"   Improvement: {no_phase3['return_pct'].max() - baseline_return:+.2f}%")

# Check if original baseline config exists
baseline_config = no_phase3[
    (no_phase3['use_rsi_filter']==False) &
    (no_phase3['use_session_filter']==False) &
    (no_phase3['enable_eod_blackout']==True)
]
if len(baseline_config) > 0:
    baseline_match = baseline_config['return_pct'].max()
    print(f"\n✅ Phase 1 baseline config found in results: {baseline_match:.2f}%")
    if abs(baseline_match - baseline_return) < 0.1:
        print("   ✅ Matches original baseline closely!")
    else:
        print(f"   ⚠️  Difference from original: {baseline_match - baseline_return:+.2f}%")
else:
    print("\n⚠️  Phase 1 baseline config not found in results")

# Final verdict
print("\n" + "=" * 80)
print("🎯 FINAL VERDICT")
print("=" * 80)

print(f"\n1. Phase 3 Features:")
print(f"   MTF Confirmation: ❌ HURTS (-5.61% mean)")
print(f"   S/R Filter: ❌ CATASTROPHIC (-45.76% mean)")
print(f"   → Recommendation: DISABLE both Phase 3 features")

print(f"\n2. Best Configuration:")
print(f"   Train Return: {top['return_pct']:.2f}%")
print(f"   RSI Filter: ✅ ENABLED (key improvement)")
print(f"   Phase 3: ❌ DISABLED")

if not test_cols:
    print(f"\n⚠️  CRITICAL ISSUE: No test/validation results!")
    print(f"   Cannot verify if 193.50% generalizes to unseen data")
    print(f"   Recommend running with train/test split to check overfitting")
else:
    test_return = top[test_cols[0]] if test_cols else None
    if test_return:
        print(f"\n3. Generalization Check:")
        print(f"   Train: {top['return_pct']:.2f}%")
        print(f"   Test: {test_return:.2f}%")
        degradation = top['return_pct'] - test_return
        if degradation > 50:
            print(f"   ⚠️  SEVERE OVERFITTING: -{degradation:.2f}% degradation")
        elif degradation > 20:
            print(f"   ⚠️  MODERATE OVERFITTING: -{degradation:.2f}% degradation")
        else:
            print(f"   ✅ Good generalization: -{degradation:.2f}% degradation")

print("\n" + "=" * 80)
