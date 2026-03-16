#!/usr/bin/env python3
"""
Download US100 (NASDAQ-100) data for M5 and M15 timeframes (~2 years each)
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.cache_data import cache_data
from src.api.capital_client import create_client_from_env

def download_us100_data():
    """Download US100 data for both M5 and M15 timeframes"""
    
    print("=" * 80)
    print("US100 (NASDAQ-100) DATA DOWNLOAD")
    print("=" * 80)
    print()
    
    # Connect to Capital.com API
    print("📡 Connecting to Capital.com API...")
    client = create_client_from_env()
    print(f"✅ Connected to Capital.com API")
    print()
    
    # Download configurations
    downloads = [
        {
            "epic": "US100",
            "resolution": "MINUTE_5",
            "num_bars": 150000,
            "output_file": "data/US100_M5_150000bars.csv",
            "description": "M5 (5-minute) ~2 years"
        },
        {
            "epic": "US100",
            "resolution": "MINUTE_15",
            "num_bars": 50000,
            "output_file": "data/US100_M15_50000bars.csv",
            "description": "M15 (15-minute) ~2 years"
        }
    ]
    
    for config in downloads:
        print("─" * 80)
        print(f"📥 Downloading {config['epic']} {config['description']}")
        print(f"   Resolution: {config['resolution']}")
        print(f"   Target bars: {config['num_bars']:,}")
        print()
        
        try:
            # Download data
            df = cache_data(
                client=client,
                epic=config['epic'],
                resolution=config['resolution'],
                max_bars=config['num_bars'],
                force_refresh=True
            )
            
            # Calculate period covered
            start_date = df['time'].min()
            end_date = df['time'].max()
            days = (end_date - start_date).days
            months = round(days / 30.4, 1)
            years = round(days / 365.25, 2)
            
            print()
            print(f"✅ Downloaded {len(df):,} bars")
            print(f"   Period: {start_date} → {end_date}")
            print(f"   Duration: {days} days ({months} months, {years} years)")
            print()
            
            # Save to file
            output_path = Path(config['output_file'])
            df.to_csv(output_path, index=False)
            print(f"💾 Saved to: {output_path}")
            print()
            
            # Credibility rating (based on months of data)
            if months >= 24:
                credibility = "⭐⭐⭐⭐⭐ EXCELLENT (2+ years)"
            elif months >= 18:
                credibility = "⭐⭐⭐⭐ GOOD (1.5-2 years)"
            elif months >= 12:
                credibility = "⭐⭐⭐ DECENT (1-1.5 years)"
            elif months >= 6:
                credibility = "⭐⭐ FAIR (6-12 months)"
            else:
                credibility = "⭐ LIMITED (< 6 months)"
            
            print(f"📊 Credibility: {credibility}")
            print(f"   Confidence: {'HIGH - robust backtest results' if months >= 18 else 'MEDIUM - limited sample' if months >= 12 else 'LOW - insufficient data'}")
            print()
            
        except Exception as e:
            print(f"❌ Error downloading {config['epic']} {config['description']}: {e}")
            print()
            continue
    
    print("=" * 80)
    print("✅ US100 DATA DOWNLOAD COMPLETE")
    print("=" * 80)
    print()
    print("Next steps:")
    print("  1. Run M5 optimization: python3 scripts/run-phase4-optimization.py --data data/US100_M5_150000bars.csv")
    print("  2. Run M15 optimization: python3 scripts/run-phase4-optimization.py --data data/US100_M15_50000bars.csv")
    print()

if __name__ == "__main__":
    download_us100_data()
