#!/usr/bin/env python3
"""
Debug script to trace result_data lookup mismatch
"""
import sys
import json
from pathlib import Path
import pandas as pd

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Use latest optimization run
latest_dir = Path('data/optimization/latest')
if not latest_dir.exists():
    print("❌ No latest/ found")
    exit(1)
opt_dir = latest_dir

# Find the master CSV
csv_files = list(opt_dir.glob('GOLD_M5_all_strategies*.csv'))
if not csv_files:
    print("❌ No master CSV found")
    exit(1)
master_csv = csv_files[0]

df = pd.DataFrame(pd.read_csv(master_csv))

print("="*80)
print("CHECKING RESULTS LOOKUP BUG")
print("="*80)

# The DataFrame is already sorted by return_pct (best first)
# After reset_index(drop=True), rank01 is at index 0, rank02 at index 1, etc.

print("\nTop 3 strategies in sorted DataFrame:")
print("-"*80)
for idx in range(3):
    row = df.iloc[idx]
    print(f"\nDataFrame index {idx} (rank{idx+1:02d}):")
    print(f"  Strategy: {row['strategy_name']}")
    print(f"  Return: {row['return_pct']:.2f}%")
    print(f"  Total trades (reported): {row['total_trades']}")
    print(f"  Total signals: {row['total_signals']}")
    
# Now check orders.csv for these strategies
print("\n" + "="*80)
print("CHECKING ORDERS.CSV FOR THESE STRATEGIES")
print("="*80)

for idx in range(3):
    row = df.iloc[idx]
    strategy_name = row['strategy_name']
    strategy_dir = opt_dir / strategy_name
    
    orders_file = strategy_dir / "orders.csv"
    if orders_file.exists():
        with open(orders_file, 'r') as f:
            order_lines = len(f.readlines()) - 1  # Subtract header
        print(f"\nrank{idx+1:02d} ({strategy_name}):")
        print(f"  Reported in CSV: {int(row['total_trades'])} trades")
        print(f"  Actual in orders.csv: {order_lines} trades")
        print(f"  DISCREPANCY: {order_lines - int(row['total_trades'])} trades missing from reported!")
    else:
        print(f"\nrank{idx+1:02d}: No orders.csv found")

# Now check if there's an index mismatch in results_lookup
print("\n" + "="*80)
print("HYPOTHESIS: results_lookup bug")
print("="*80)
print("""
The bug is in export_results():

Line 857: results_lookup = {i: result for i, result in enumerate(self.results) ...}
  - Creates dict with keys 0, 1, 2, ... based on TEST ORDER
  
Line 863: for idx, row in df_results.iterrows():
  - df_results is sorted by performance (best first)
  - After reset_index(drop=True), idx is 0, 1, 2, ... in PERFORMANCE ORDER
  
Line 871: result_data = results_lookup.get(idx, {})
  - Tries to match idx (performance order) with lookup key (test order)
  - This is correct only if the best strategy happened to be tested first!

The fix should be:
  - Use result['_idx'] as the key in results_lookup
  - OR store _idx in the DataFrame and use that for lookup
""")

print("\nHowever, orders.csv DOES have the correct trades!")
print("This means result_data['trades'] somehow has the right data.")
print("So the bug must be elsewhere...")
