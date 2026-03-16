#!/usr/bin/env python3
"""
Test parameter capture for intraday features
Verifies that True/False and all parameters are properly saved to results
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from optimization.optimize_strategy import StrategyOptimizer
import pandas as pd

def test_parameter_capture():
    """Test that parameters are captured correctly in results"""
    
    print("="*80)
    print("🧪 TESTING PARAMETER CAPTURE")
    print("="*80 + "\n")
    
    # Load small dataset for quick test
    data_file = 'data/GOLD_M5_3000bars.csv'
    
    print(f"📂 Loading test data: {data_file}")
    df = pd.read_csv(data_file)
    print(f"   Loaded {len(df)} bars\n")
    
    # Initialize optimizer with intraday mode
    print("🔧 Initializing optimizer...")
    optimizer = StrategyOptimizer(
        df=df,
        initial_capital=10000,
        epic='GOLD',
        resolution='M5',
        n_jobs=2  # Just 2 workers for quick test
    )
    
    # Get grid and combinations
    print("📊 Generating INTRADAY combinations...")
    grid = optimizer.define_intraday_grid()
    combinations = optimizer.generate_combinations(grid)
    
    print(f"   Total combinations: {len(combinations)}")
    
    # Test first 4 combinations to verify variety
    print("\n" + "="*80)
    print("🔍 TESTING FIRST 4 COMBINATIONS")
    print("="*80)
    
    test_combos = combinations[:4]
    
    for i, combo in enumerate(test_combos, 1):
        print(f"\n{i}. Testing combination:")
        print(f"   enable_time_exit:     {combo.get('enable_time_exit', 'MISSING')}")
        print(f"   max_holding_hours:    {combo.get('max_holding_hours', 'MISSING')}")
        print(f"   enable_eod_close:     {combo.get('enable_eod_close', 'MISSING')}")
        print(f"   enable_eod_blackout:  {combo.get('enable_eod_blackout', 'MISSING')}")
        print(f"   enable_partial_exit:  {combo.get('enable_partial_exit', 'MISSING')}")
    
    # Run quick optimization on first 8 strategies
    print("\n" + "="*80)
    print("⚡ RUNNING QUICK TEST (8 strategies)")
    print("="*80 + "\n")
    
    optimizer.combinations = test_combos[:8]
    results = optimizer._run_parallel(optimizer.combinations)
    
    # Format results
    print("\n📋 Formatting results...")
    df_results = optimizer._format_results(results)
    
    if df_results.empty:
        print("❌ ERROR: Results DataFrame is empty!")
        return False
    
    # Verify all columns exist
    print("\n" + "="*80)
    print("✅ VERIFICATION: Checking Required Columns")
    print("="*80)
    
    required_cols = [
        'return_pct', 'sharpe_ratio', 'win_rate', 'profit_factor',
        'enable_time_exit', 'max_holding_hours',
        'enable_eod_close', 'eod_close_hour',
        'enable_eod_blackout', 'no_entry_before_eod_hours',
        'enable_partial_exit', 'partial_exit_tp1_pips', 'partial_exit_tp2_pips'
    ]
    
    all_present = True
    for col in required_cols:
        if col in df_results.columns:
            print(f"   ✅ {col:<30s} [PRESENT]")
        else:
            print(f"   ❌ {col:<30s} [MISSING]")
            all_present = False
    
    # Check boolean values are actually bool type
    print("\n" + "="*80)
    print("🔍 CHECKING DATA TYPES")
    print("="*80)
    
    bool_cols = ['enable_time_exit', 'enable_eod_close', 'enable_eod_blackout', 'enable_partial_exit']
    for col in bool_cols:
        if col in df_results.columns:
            dtype = df_results[col].dtype
            sample_val = df_results[col].iloc[0]
            print(f"   {col:<30s} dtype={dtype}, sample={sample_val}")
    
    # Show sample result rows
    print("\n" + "="*80)
    print("📊 SAMPLE RESULTS (Top 3)")
    print("="*80)
    
    cols_to_show = ['return_pct', 'enable_time_exit', 'enable_eod_close', 
                    'enable_eod_blackout', 'enable_partial_exit', 'max_holding_hours']
    
    for idx, row in df_results.head(3).iterrows():
        print(f"\n{idx+1}. Return: {row['return_pct']:.2f}%")
        print(f"   Time Exit:    {row['enable_time_exit']} (max {row['max_holding_hours']}h)")
        print(f"   EOD Close:    {row['enable_eod_close']}")
        print(f"   EOD Blackout: {row['enable_eod_blackout']}")
        print(f"   Partial Exit: {row['enable_partial_exit']}")
    
    # Final verdict
    print("\n" + "="*80)
    if all_present:
        print("✅ TEST PASSED: All parameters captured correctly!")
        print("   → Ready to run full optimization")
    else:
        print("❌ TEST FAILED: Some parameters missing!")
        print("   → Do NOT run full optimization yet")
    print("="*80 + "\n")
    
    return all_present


if __name__ == '__main__':
    success = test_parameter_capture()
    sys.exit(0 if success else 1)
