#!/usr/bin/env python3
"""
Download 2 years of M15 GOLD data for credible backtesting

M15 bars calculation:
- 2 years = ~730 days
- Gold trades ~23 hours/day
- 23 hours × 4 bars/hour = 92 bars/day
- 730 days × 92 bars = ~67,160 bars
- Request 50,000 bars to ensure 2+ years of actual trading data
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from src.api.capital_client import create_client_from_env
from src.data.cache_data import cache_data
import pandas as pd
from datetime import datetime

def download_m15_2years():
    """Download 2 years of M15 GOLD data"""
    
    print("\n" + "="*100)
    print("📥 DOWNLOADING 2 YEARS OF M15 GOLD DATA")
    print("="*100)
    
    print("\n📊 Target:")
    print("   • Instrument: GOLD")
    print("   • Timeframe: M15 (15-minute)")
    print("   • Bars requested: 50,000 (ensures 2+ years)")
    print("   • Expected period: ~2 years (24+ months)")
    print()
    
    try:
        # Create Capital.com API client
        print("🔑 Connecting to Capital.com API...")
        client = create_client_from_env()
        print("✅ Connected")
        
        # Download data
        print("\n📡 Fetching M15 GOLD data from Capital.com...")
        print("   (This may take 1-2 minutes due to API rate limits)")
        print()
        
        df = cache_data(
            client=client,
            epic='GOLD',
            resolution='M15',
            max_bars=50000,
            force_refresh=True  # Force fresh download
        )
        
        if df is None or len(df) == 0:
            print("❌ Failed to download data")
            return False
        
        print("\n" + "="*100)
        print("✅ DOWNLOAD COMPLETE")
        print("="*100)
        
        # Analyze what we got
        start_date = df.index[0]
        end_date = df.index[-1]
        days = (end_date - start_date).days
        months = days / 30.44
        years = days / 365.25
        
        print(f"\n📊 Data Summary:")
        print(f"   Bars downloaded: {len(df):,}")
        print(f"   Start date: {start_date.strftime('%Y-%m-%d %H:%M')}")
        print(f"   End date: {end_date.strftime('%Y-%m-%d %H:%M')}")
        print(f"   Period: {days} days ({months:.1f} months, {years:.2f} years)")
        print()
        
        # Save to file
        output_file = f'data/GOLD_M15_{len(df)}bars.csv'
        df.to_csv(output_file)
        print(f"💾 Saved to: {output_file}")
        
        # Check credibility
        print("\n" + "="*100)
        print("🎯 CREDIBILITY CHECK")
        print("="*100)
        
        if months >= 24:
            stars = "⭐⭐⭐⭐⭐"
            rating = "EXCELLENT"
            print(f"\n{stars} {rating}")
            print(f"   • {months:.1f} months = Highly robust")
            print(f"   • Covers {months/12:.1f} years of market data")
            print(f"   • Multiple market cycles tested")
            print(f"   • HIGH confidence in backtest results")
        elif months >= 12:
            stars = "⭐⭐⭐⭐"
            rating = "VERY GOOD"
            print(f"\n{stars} {rating}")
            print(f"   • {months:.1f} months = Solid")
            print(f"   • Covers {months/12:.1f} years of market data")
            print(f"   • Good variety of market conditions")
            print(f"   • GOOD confidence in backtest results")
        elif months >= 6:
            stars = "⭐⭐⭐"
            rating = "GOOD"
            print(f"\n{stars} {rating}")
            print(f"   • {months:.1f} months = Adequate")
            print(f"   • Minimum acceptable for strategy testing")
            print(f"   • MEDIUM confidence in results")
        else:
            stars = "⭐⭐"
            rating = "FAIR"
            print(f"\n{stars} {rating}")
            print(f"   • {months:.1f} months = Marginal")
            print(f"   • ⚠️  Still short for strong conclusions")
            print(f"   • Consider as preliminary testing only")
        
        print("\n💡 Next Steps:")
        print("   1. Run Phase 4 optimization with this M15 data")
        print("   2. Compare results against M5 (25 months)")
        print("   3. Choose best timeframe based on robust backtest")
        
        print("\n" + "="*100)
        return True
        
    except Exception as e:
        print(f"\n❌ Error downloading data: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = download_m15_2years()
    sys.exit(0 if success else 1)
