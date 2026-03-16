#!/usr/bin/env python3
"""
Download 2 years of US100 (NASDAQ-100) data for M5 and M15 timeframes

M5 bars: 150,000 bars for ~2 years
M15 bars: 50,000 bars for ~2 years
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from src.api.capital_client import create_client_from_env
from src.data.cache_data import cache_data
import pandas as pd
from datetime import datetime

def download_us100_data():
    """Download 2 years of US100 data for M5 and M15"""
    
    print("\n" + "="*100)
    print("📥 DOWNLOADING 2 YEARS OF US100 (NASDAQ-100) DATA")
    print("="*100)
    print()
    
    try:
        # Create Capital.com API client
        print("🔑 Connecting to Capital.com API...")
        client = create_client_from_env()
        print("✅ Connected\n")
        
        # Download configurations
        downloads = [
            {'epic': 'US100', 'resolution': 'M5', 'max_bars': 150000, 'file': 'US100_M5_150000bars.csv'},
            {'epic': 'US100', 'resolution': 'M15', 'max_bars': 50000, 'file': 'US100_M15_50000bars.csv'}
        ]
        
        for config in downloads:
            print("─" * 100)
            print(f"📥 Downloading {config['epic']} {config['resolution']} ({config['max_bars']:,} bars)")
            print("   (This may take 1-2 minutes due to API rate limits)")
            print()
            
            df = cache_data(
                client=client,
                epic=config['epic'],
                resolution=config['resolution'],
                max_bars=config['max_bars'],
                force_refresh=True
            )
            
            if df is None or len(df) == 0:
                print(f"❌ Failed to download {config['epic']} {config['resolution']}")
                continue
            
            # Analyze what we got
            start_date = df.index[0]
            end_date = df.index[-1]
            days = (end_date - start_date).days
            months = days / 30.44
            years = days / 365.25
            
            print(f"\n✅ Downloaded {len(df):,} bars")
            print(f"   Period: {start_date.strftime('%Y-%m-%d %H:%M')} → {end_date.strftime('%Y-%m-%d %H:%M')}")
            print(f"   Duration: {days} days ({months:.1f} months, {years:.2f} years)")
            
            # Credibility rating
            if months >= 24:
                stars = "⭐⭐⭐⭐⭐ EXCELLENT"
            elif months >= 18:
                stars = "⭐⭐⭐⭐ GOOD"
            elif months >= 12:
                stars = "⭐⭐⭐ DECENT"
            elif months >= 6:
                stars = "⭐⭐ FAIR"
            else:
                stars = "⭐ LIMITED"
            
            print(f"   Credibility: {stars}")
            
            # Save to CSV
            output_file = f"data/{config['file']}"
            df.to_csv(output_file)
            print(f"   💾 Saved to: {output_file}")
            print()
        
        print("=" * 100)
        print("✅ US100 DATA DOWNLOAD COMPLETE")
        print("=" * 100)
        print()
        print("Next steps:")
        print("  1. Run M5 optimization: python3 scripts/run-phase4-optimization.py --data data/US100_M5_150000bars.csv")
        print("  2. Run M15 optimization: python3 scripts/run-phase4-optimization.py --data data/US100_M15_50000bars.csv")
        print()
        return True
        
    except Exception as e:
        print(f"\n❌ Error downloading data: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = download_us100_data()
    sys.exit(0 if success else 1)
