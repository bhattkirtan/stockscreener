#!/usr/bin/env python3
"""
Analyze trade holding times from intraday optimization results
"""

import pandas as pd
from pathlib import Path
from datetime import datetime

def analyze_holding_times(orders_file):
    """Analyze holding times from orders CSV"""
    
    # Read orders
    df = pd.read_csv(orders_file)
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    df['exit_time'] = pd.to_datetime(df['exit_time'])
    
    # Calculate holding time in hours
    df['holding_hours'] = (df['exit_time'] - df['entry_time']).dt.total_seconds() / 3600
    
    # Check if closed same day
    df['same_day'] = df['entry_time'].dt.date == df['exit_time'].dt.date
    
    # Calculate metrics
    total_trades = len(df)
    same_day_trades = df['same_day'].sum()
    same_day_pct = (same_day_trades / total_trades) * 100
    
    avg_hold_hours = df['holding_hours'].mean()
    max_hold_hours = df['holding_hours'].max()
    min_hold_hours = df['holding_hours'].min()
    
    # Count overnight trades
    overnight_trades = (~df['same_day']).sum()
    
    # Get some overnight examples
    overnight_examples = df[~df['same_day']].head(5)
    
    return {
        'total_trades': total_trades,
        'same_day_trades': same_day_trades,
        'same_day_pct': same_day_pct,
        'overnight_trades': overnight_trades,
        'avg_hold_hours': avg_hold_hours,
        'max_hold_hours': max_hold_hours,
        'min_hold_hours': min_hold_hours,
        'holding_distribution': df['holding_hours'].describe(),
        'overnight_examples': overnight_examples[['entry_time', 'exit_time', 'holding_hours', 'pnl', 'exit_reason']]
    }

def main():
    # Use latest optimization run - get rank01 folder
    from pathlib import Path
    latest_dir = Path('data/optimization/latest')
    if not latest_dir.exists():
        print("❌ No latest/ found")
        return
    base_dir = latest_dir
    
    # Find rank01 strategy folder
    rank01_folders = list(base_dir.glob('rank01_*'))
    if not rank01_folders:
        print("❌ No rank01 strategy found")
        return
    
    strategies = [rank01_folders[0].name]
    
    print("="*80)
    print("INTRADAY HOLDING TIME ANALYSIS")
    print("="*80)
    print()
    
    for strategy_name in strategies:
        strategy_dir = base_dir / strategy_name
        orders_file = strategy_dir / 'orders.csv'
        
        if not orders_file.exists():
            print(f"⚠️  {strategy_name}: No orders file found")
            continue
        
        print(f"📊 {strategy_name}")
        print("-" * 80)
        
        results = analyze_holding_times(orders_file)
        
        print(f"Total Trades:         {results['total_trades']}")
        print(f"Same-Day Trades:      {results['same_day_trades']} ({results['same_day_pct']:.1f}%)")
        print(f"Overnight Trades:     {results['overnight_trades']} ({100 - results['same_day_pct']:.1f}%)")
        print(f"Avg Holding Time:     {results['avg_hold_hours']:.2f} hours")
        print(f"Max Holding Time:     {results['max_hold_hours']:.2f} hours")
        print(f"Min Holding Time:     {results['min_hold_hours']:.2f} hours")
        print()
        print("Holding Time Distribution:")
        print(results['holding_distribution'])
        print()
        
        if results['overnight_trades'] > 0:
            print("Example Overnight Trades:")
            print(results['overnight_examples'].to_string())
            print()
        
        print()
    
    print("="*80)
    print("CONCLUSION:")
    print("="*80)
    print()
    print("If Same-Day % < 95%: Intraday features were likely DISABLED")
    print("If Avg Hold > 6 hours: Time exit was likely DISABLED")
    print("If Max Hold > 24 hours: EOD close was likely DISABLED")
    print()
    print("This means the optimizer found that BASELINE (no intraday features)")
    print("performs BETTER than using time-based exits!")

if __name__ == '__main__':
    main()
