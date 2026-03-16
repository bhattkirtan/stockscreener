#!/usr/bin/env python3
"""
Deep dive analysis: Could time-based features have prevented overnight trades?
"""

import pandas as pd
from pathlib import Path

def analyze_overnight_trades(orders_file):
    """Analyze why trades went overnight and if features could prevent them"""
    
    # Read orders
    df = pd.read_csv(orders_file)
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    df['exit_time'] = pd.to_datetime(df['exit_time'])
    
    # Calculate holding time in hours
    df['holding_hours'] = (df['exit_time'] - df['entry_time']).dt.total_seconds() / 3600
    
    # Check if closed same day
    df['same_day'] = df['entry_time'].dt.date == df['exit_time'].dt.date
    
    # Get overnight trades
    overnight = df[~df['same_day']].copy()
    
    # Extract time components
    overnight['entry_hour'] = overnight['entry_time'].dt.hour
    overnight['entry_day'] = overnight['entry_time'].dt.day_name()
    overnight['exit_day'] = overnight['exit_time'].dt.day_name()
    
    # Check if weekend-crossing
    overnight['crosses_weekend'] = (
        ((overnight['entry_day'] == 'Friday') & (overnight['exit_day'] != 'Friday')) |
        ((overnight['entry_day'] == 'Saturday') | (overnight['entry_day'] == 'Sunday'))
    )
    
    # Categorize by entry time
    overnight['late_entry'] = overnight['entry_hour'] >= 15  # After 3 PM
    overnight['eod_blackout_zone'] = overnight['entry_hour'] >= 15  # 1h before EOD (4 PM)
    
    # Could features have prevented it?
    overnight['prevented_by_blackout'] = overnight['eod_blackout_zone']
    overnight['prevented_by_eod_close'] = ~overnight['crosses_weekend']  # Non-weekend trades could close at EOD
    
    print("="*100)
    print("OVERNIGHT TRADE DEEP DIVE - Could Time-Based Features Help?")
    print("="*100)
    print()
    
    print(f"Total Overnight Trades: {len(overnight)}")
    print()
    
    print("📅 DAY ANALYSIS:")
    print("-" * 100)
    print(f"Weekend-Crossing Trades:    {overnight['crosses_weekend'].sum():3d} ({overnight['crosses_weekend'].sum()/len(overnight)*100:.1f}%)")
    print(f"Weekday Overnight Trades:   {(~overnight['crosses_weekend']).sum():3d} ({(~overnight['crosses_weekend']).sum()/len(overnight)*100:.1f}%)")
    print()
    
    print("⏰ ENTRY TIME ANALYSIS:")
    print("-" * 100)
    print(f"Late Entries (>= 3 PM):     {overnight['late_entry'].sum():3d} ({overnight['late_entry'].sum()/len(overnight)*100:.1f}%)")
    print(f"Early/Mid-Day Entries:      {(~overnight['late_entry']).sum():3d} ({(~overnight['late_entry']).sum()/len(overnight)*100:.1f}%)")
    print()
    
    print("🛡️ PREVENTION POTENTIAL:")
    print("-" * 100)
    print(f"Preventable by EOD Blackout (no entry after 3 PM): {overnight['prevented_by_blackout'].sum():3d}/{len(overnight)} ({overnight['prevented_by_blackout'].sum()/len(overnight)*100:.1f}%)")
    print(f"Preventable by EOD Close (force close at 4 PM):    {overnight['prevented_by_eod_close'].sum():3d}/{len(overnight)} ({overnight['prevented_by_eod_close'].sum()/len(overnight)*100:.1f}%)")
    print()
    
    print("📋 DETAILED BREAKDOWN:")
    print("-" * 100)
    cols = ['entry_time', 'exit_time', 'entry_hour', 'entry_day', 'exit_day', 
            'holding_hours', 'pnl', 'exit_reason', 'crosses_weekend', 'late_entry']
    print(overnight[cols].to_string(index=False))
    print()
    
    print("="*100)
    print("💡 RECOMMENDATIONS:")
    print("="*100)
    print()
    
    if overnight['prevented_by_blackout'].sum() > 0:
        pct = overnight['prevented_by_blackout'].sum() / len(overnight) * 100
        print(f"✓ EOD BLACKOUT:  Block entries after 3 PM → Prevents {overnight['prevented_by_blackout'].sum()} trades ({pct:.1f}%)")
    else:
        print("✗ EOD BLACKOUT:  Would NOT help (no late entries)")
    
    if overnight['prevented_by_eod_close'].sum() > 0:
        pct = overnight['prevented_by_eod_close'].sum() / len(overnight) * 100
        print(f"✓ EOD CLOSE:     Force close at 4 PM → Prevents {overnight['prevented_by_eod_close'].sum()} trades ({pct:.1f}%)")
    else:
        print("✗ EOD CLOSE:     Would NOT help (all are weekend-crossing)")
    
    if overnight['crosses_weekend'].sum() > 0:
        pct = overnight['crosses_weekend'].sum() / len(overnight) * 100
        print(f"⚠️ WEEKEND ISSUE: {overnight['crosses_weekend'].sum()} trades ({pct:.1f}%) cross weekend - CANNOT be prevented without market hours logic")
    
    print()
    print("="*100)
    print("CONCLUSION:")
    print("="*100)
    print(f"Out of {len(overnight)} overnight trades:")
    print(f"  - {overnight['prevented_by_blackout'].sum()} could be prevented by EOD blackout")
    print(f"  - {overnight['prevented_by_eod_close'].sum()} could be prevented by EOD close") 
    print(f"  - {overnight['crosses_weekend'].sum()} are weekend trades (need different solution)")
    print()
    
    if overnight['prevented_by_blackout'].sum() + overnight['prevented_by_eod_close'].sum() > 0:
        print("✅ TIME-BASED FEATURES WOULD HELP!")
    else:
        print("❌ TIME-BASED FEATURES WOULD NOT HELP MUCH")

def main():
    # Use latest optimization run - find rank01 folder
    from pathlib import Path
    latest_dir = Path('data/optimization/latest')
    if not latest_dir.exists():
        print("❌ No latest/ found")
        return
    base_dir = latest_dir
    
    # Find rank01 strategy folder
    rank01_folders = list(base_dir.glob('rank01_*/orders*.csv'))
    if not rank01_folders:
        print("❌ No rank01 strategy orders found")
        return
    orders_file = rank01_folders[0]
    
    if not orders_file.exists():
        print(f"❌ File not found: {orders_file}")
        return
    
    analyze_overnight_trades(orders_file)

if __name__ == '__main__':
    main()
