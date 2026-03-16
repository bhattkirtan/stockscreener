#!/usr/bin/env python3
"""
Check if there's a discrepancy between orders CSV and summary trades
"""
import pandas as pd
import json
import os
from pathlib import Path

print("="*80)
print("🔍 ANALYZING ALL TOP 10 STRATEGIES")
print("="*80)
print()

# Use latest optimization run
latest_dir = Path('data/optimization/latest')
if not latest_dir.exists():
    print("❌ No latest/ found")
    exit(1)
base_dir = str(latest_dir)

# Check all rank folders
for rank in range(1, 11):
    # Find folder starting with rank0{rank}
    folders = [f for f in os.listdir(base_dir) if f.startswith(f"rank{rank:02d}_")]
    
    if not folders:
        continue
    
    folder = folders[0]
    folder_path = os.path.join(base_dir, folder)
    
    # Load files
    orders_file = os.path.join(folder_path, "orders.csv")
    summary_file = os.path.join(folder_path, "summary.json")
    
    if not os.path.exists(orders_file) or not os.path.exists(summary_file):
        continue
    
    orders_df = pd.read_csv(orders_file)
    with open(summary_file) as f:
        summary = json.load(f)
    
    orders_count = len(orders_df)
    reported_trades = summary['trades']['total']
    signals = summary['signals']['total']
    
    print(f"📊 Rank {rank:02d}: {folder[:30]}...")
    print(f"   Signals: {signals}")
    print(f"   Orders CSV: {orders_count} rows")
    print(f"   Summary trades: {reported_trades}")
    print(f"   Discrepancy: {orders_count - reported_trades} orders not counted")
    print()

print("="*80)
print("💡 CONCLUSION")
print("="*80)
print()
print("If orders != reported trades, there's a bug in trade counting!")
print()
