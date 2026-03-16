#!/usr/bin/env python3
"""
Phase 3 Analysis: MTF Confirmation & S/R Filtering
"""
import pandas as pd
import sys

# Load Phase 3 results - WITH PROPER TRAIN/TEST SPLIT
csv_path = "data/optimization/2026-03-08/run_20260308_155631/GOLD_M5_all_strategies_20260308_155631.csv"
df = pd.read_csv(csv_path)

print("=" * 80)
print("📊 PHASE 3 ANALYSIS: MTF CONFIRMATION & S/R FILTERING")
print("=" * 80)
print(f"\n✅ Loaded {len(df)} strategies")
print(f"   Columns: {list(df.columns)}\n")

# Overall stats
print("\n📈 OVERALL STATISTICS:")
print(f"   Mean Return: {df['return_pct'].mean():.2f}%")
print(f"   Max Return: {df['return_pct'].max():.2f}%")
print(f"   Min Return: {df['return_pct'].min():.2f}%")
print(f"   Median Return: {df['return_pct'].median():.2f}%")
print(f"   Avg Trades: {df['total_trades'].mean():.1f}")

# Phase 1 Baseline Comparison
baseline = 59.23
print(f"\n🎯 BASELINE COMPARISON (Phase 1: {baseline}%):")
better_than_baseline = df[df['return_pct'] > baseline]
print(f"   Strategies beating baseline: {len(better_than_baseline)} / {len(df)} ({len(better_than_baseline)/len(df)*100:.1f}%)")
if len(better_than_baseline) > 0:
    print(f"   Best improvement: +{better_than_baseline['return_pct'].max() - baseline:.2f}%")

# MTF Confirmation Analysis
print("\n" + "=" * 80)
print("🔍 MTF CONFIRMATION ANALYSIS (Multi-Timeframe)")
print("=" * 80)
mtf_analysis = df.groupby('use_mtf_confirmation')['return_pct'].agg(['mean', 'max', 'count'])
print("\nMTF Enabled vs Disabled:")
print(mtf_analysis)
print(f"\nMTF Impact:")
mtf_enabled = df[df['use_mtf_confirmation'] == True]['return_pct'].mean()
mtf_disabled = df[df['use_mtf_confirmation'] == False]['return_pct'].mean()
print(f"   MTF=True:  {mtf_enabled:.2f}% mean")
print(f"   MTF=False: {mtf_disabled:.2f}% mean")
print(f"   Difference: {mtf_enabled - mtf_disabled:+.2f}%")

# MTF Parameter Analysis (when enabled)
if df['use_mtf_confirmation'].any():
    print("\n📊 MTF Parameters (when enabled):")
    mtf_period = df[df['use_mtf_confirmation']==True].groupby('mtf_supertrend_period')['return_pct'].agg(['mean','max','count'])
    print("\nBy MTF Period:")
    print(mtf_period)
    
    mtf_mult = df[df['use_mtf_confirmation']==True].groupby('mtf_supertrend_multiplier')['return_pct'].agg(['mean','max','count'])
    print("\nBy MTF Multiplier:")
    print(mtf_mult)
    
    mtf_combo = df[df['use_mtf_confirmation']==True].groupby(['mtf_supertrend_period','mtf_supertrend_multiplier'])['return_pct'].agg(['mean','max']).sort_values('max', ascending=False)
    print("\nBest MTF Combinations (period, multiplier):")
    print(mtf_combo.head(10))

# S/R Filter Analysis
print("\n" + "=" * 80)
print("🔍 SUPPORT/RESISTANCE FILTER ANALYSIS")
print("=" * 80)
sr_analysis = df.groupby('use_sr_filter')['return_pct'].agg(['mean', 'max', 'count'])
print("\nS/R Enabled vs Disabled:")
print(sr_analysis)
print(f"\nS/R Impact:")
sr_enabled = df[df['use_sr_filter'] == True]['return_pct'].mean()
sr_disabled = df[df['use_sr_filter'] == False]['return_pct'].mean()
print(f"   SR=True:  {sr_enabled:.2f}% mean")
print(f"   SR=False: {sr_disabled:.2f}% mean")
print(f"   Difference: {sr_enabled - sr_disabled:+.2f}%")

# S/R Parameter Analysis (when enabled)
if df['use_sr_filter'].any():
    print("\n📊 S/R Parameters (when enabled):")
    sr_lookback = df[df['use_sr_filter']==True].groupby('sr_lookback')['return_pct'].agg(['mean','max','count'])
    print("\nBy S/R Lookback:")
    print(sr_lookback)
    
    sr_threshold = df[df['use_sr_filter']==True].groupby('sr_threshold_pct')['return_pct'].agg(['mean','max','count'])
    print("\nBy S/R Threshold:")
    print(sr_threshold)
    
    sr_combo = df[df['use_sr_filter']==True].groupby(['sr_lookback','sr_threshold_pct'])['return_pct'].agg(['mean','max']).sort_values('max', ascending=False)
    print("\nBest S/R Combinations (lookback, threshold):")
    print(sr_combo.head(10))

# Combined Phase 3 Analysis
print("\n" + "=" * 80)
print("🔗 COMBINED PHASE 3 FEATURES")
print("=" * 80)
phase3_combo = df.groupby(['use_mtf_confirmation','use_sr_filter'])['return_pct'].agg(['mean','max','count'])
print("\nMTF + S/R Combinations:")
print(phase3_combo)

# Top 10 Strategies
print("\n" + "=" * 80)
print("🏆 TOP 10 PHASE 3 STRATEGIES")
print("=" * 80)
# Top 10 Strategies
print("\n" + "=" * 80)
print("🏆 TOP 10 PHASE 3 STRATEGIES")
print("=" * 80)

# Check which columns are available
test_cols = ['test_return_pct'] if 'test_return_pct' in df.columns else []
cols_to_show = ['return_pct'] + test_cols + [
    'total_trades',
    'use_mtf_confirmation', 'mtf_supertrend_period', 'mtf_supertrend_multiplier',
    'use_sr_filter', 'sr_lookback', 'sr_threshold_pct',
    'use_rsi_filter', 'use_session_filter', 'enable_eod_blackout'
]

top10 = df.nlargest(10, 'return_pct')[cols_to_show]
for idx, (i, row) in enumerate(top10.iterrows(), 1):
    test_str = f", Test: {row['test_return_pct']:.2f}%" if 'test_return_pct' in row else ""
    print(f"\n#{idx} - Return: {row['return_pct']:.2f}%{test_str}, Trades: {int(row['total_trades'])}")
    print(f"   MTF: {row['use_mtf_confirmation']}, Period: {row['mtf_supertrend_period']}, Mult: {row['mtf_supertrend_multiplier']}")
    print(f"   S/R: {row['use_sr_filter']}, Lookback: {row['sr_lookback']}, Threshold: {row['sr_threshold_pct']}")
    print(f"   Phase 1: RSI={row['use_rsi_filter']}, Session={row['use_session_filter']}, EOD={row['enable_eod_blackout']}")

# TEST SET ANALYSIS (if available)
if 'test_return_pct' in df.columns:
    print("\n" + "=" * 80)
    print("📊 TEST SET ANALYSIS (Out-of-Sample Performance)")
    print("=" * 80)
    
    print("\n🔍 FEATURE IMPACT ON TEST SET:")
    
    # RSI Filter Impact on Test
    print("\n1. RSI Filter Impact (Test):")
    rsi_test = df.groupby('use_rsi_filter')['test_return_pct'].agg(['mean', 'max', 'count'])
    print(rsi_test)
    rsi_diff = rsi_test.loc[True, 'mean'] - rsi_test.loc[False, 'mean']
    print(f"   → RSI Impact on Test: {rsi_diff:+.2f}%")
    
    # MTF Impact on Test
    print("\n2. MTF Confirmation Impact (Test):")
    mtf_test = df.groupby('use_mtf_confirmation')['test_return_pct'].agg(['mean', 'max', 'count'])
    print(mtf_test)
    mtf_diff = mtf_test.loc[True, 'mean'] - mtf_test.loc[False, 'mean']
    print(f"   → MTF Impact on Test: {mtf_diff:+.2f}%")
    
    # S/R Impact on Test
    print("\n3. S/R Filter Impact (Test):")
    sr_test = df.groupby('use_sr_filter')['test_return_pct'].agg(['mean', 'max', 'count'])
    print(sr_test)
    sr_diff = sr_test.loc[True, 'mean'] - sr_test.loc[False, 'mean']
    print(f"   → S/R Impact on Test: {sr_diff:+.2f}%")
    
    print("\n" + "=" * 80)
    print("🏆 TOP 10 BY TEST PERFORMANCE")
    print("=" * 80)
    best_test = df.nlargest(10, 'test_return_pct')
    for idx, (i, row) in enumerate(best_test.iterrows(), 1):
        print(f"\n#{idx} - Test: {row['test_return_pct']:.2f}%, Train: {row['return_pct']:.2f}%, Trades: {int(row['total_trades'])}/{int(row['test_total_trades'])}")
        print(f"   MTF={row['use_mtf_confirmation']}, S/R={row['use_sr_filter']}, RSI={row['use_rsi_filter']}")

# Final Verdict
print("\n" + "=" * 80)
print("🎯 PHASE 3 VERDICT")
print("=" * 80)

if 'test_return_pct' in df.columns:
    baseline_test = 136.62  # Phase 1 baseline test performance
    best_phase3_test = df['test_return_pct'].max()
    print(f"\n   Phase 1 Baseline (Test): {baseline_test}%")
    print(f"   Phase 3 Best (Test): {best_phase3_test:.2f}%")
    print(f"   Improvement: {best_phase3_test - baseline_test:+.2f}%")
    
    if best_phase3_test > baseline_test:
        print(f"\n   ✅ Phase 3 IMPROVES baseline by {best_phase3_test - baseline_test:.2f}%")
        best_config = df.loc[df['test_return_pct'].idxmax()]
        print(f"\n   🏆 WINNING CONFIGURATION:")
        print(f"      Train: {best_config['return_pct']:.2f}%, Test: {best_config['test_return_pct']:.2f}%")
        print(f"      MTF: {best_config['use_mtf_confirmation']}, Period: {best_config['mtf_supertrend_period']}, Mult: {best_config['mtf_supertrend_multiplier']}")
        print(f"      S/R: {best_config['use_sr_filter']}, Lookback: {best_config['sr_lookback']}, Threshold: {best_config['sr_threshold_pct']}")
        print(f"      RSI: {best_config['use_rsi_filter']}")
    else:
        print(f"\n   ❌ Phase 3 DOES NOT improve baseline test performance")
        print(f"   📌 Recommendation: Stick with Phase 1 baseline + RSI filter (59.23% train, 136.62% test)")
else:
    best_phase3 = df['return_pct'].max()
    print(f"\n   Phase 1 Baseline: {baseline}%")
    print(f"   Phase 3 Best: {best_phase3:.2f}%")
    print(f"   Improvement: {best_phase3 - baseline:+.2f}%")
    
    if best_phase3 > baseline:
        print(f"\n   ✅ Phase 3 IMPROVES baseline by {best_phase3 - baseline:.2f}%")
        best_config = df.loc[df['return_pct'].idxmax()]
        print(f"\n   🏆 WINNING CONFIGURATION:")
        print(f"      MTF: {best_config['use_mtf_confirmation']}, Period: {best_config['mtf_supertrend_period']}, Mult: {best_config['mtf_supertrend_multiplier']}")
        print(f"      S/R: {best_config['use_sr_filter']}, Lookback: {best_config['sr_lookback']}, Threshold: {best_config['sr_threshold_pct']}")
    else:
        print(f"\n   ❌ Phase 3 DOES NOT improve baseline")
        print(f"   📌 Recommendation: Stick with Phase 1 baseline (59.23%)")

print("\n" + "=" * 80)
