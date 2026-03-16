#!/usr/bin/env python3
"""
Download US100 (NASDAQ-100) data for M5 and M15 timeframes (~2 years each)
Direct download from Capital.com API without GCP cache
"""
import sys
from pathlib import Path
import pandas as pd
from datetime import datetime, timedelta
import time

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.api.capital_client import create_client_from_env

def fetch_historical_data(client, epic, resolution, max_bars):
    """
    Fetch historical data in batches (Capital.com API limit: 1000 bars/request)
    
    Args:
        client: Capital com client
        epic: Instrument (e.g., 'US100')
        resolution: 'MINUTE_5' or 'MINUTE_15'
        max_bars: Total bars to fetch
    
    Returns:
        DataFrame with OHLC data
    """
    all_data = []
    bars_fetched = 0
    to_date = None
    
    print(f"   Fetching in batches (API limit: 1,000 bars/request)...")
    print()
    
    while bars_fetched < max_bars:
        # Calculate how many bars to request (max 1000 per request)
        remaining = max_bars - bars_fetched
        batch_size = min(1000, remaining)
        
        # Build request params
        params = {
            'resolution': resolution,
            'max': batch_size
        }
        if to_date:
            params['to'] = to_date
        
        # Fetch batch
        try:
            resp = client.get(f'/api/v1/prices/{epic}', params=params)
            
            if not resp.ok:
                print(f"   ❌ API error: {resp.status_code} - {resp.text}")
                break
            
            data = resp.json()
            prices = data.get('prices', [])
            
            if not prices:
                print(f"   ⚠️  No more data available")
                break
            
            # Convert to dataframe
            df_batch = pd.DataFrame(prices)
            
            # Parse datetime
            if 'snapshotTime' in df_batch.columns:
                df_batch['time'] = pd.to_datetime(df_batch['snapshotTime'])
                df_batch = df_batch.drop(columns=['snapshotTime'])
            elif 'snapshotTimeUTC' in df_batch.columns:
                df_batch['time'] = pd.to_datetime(df_batch['snapshotTimeUTC'])
                df_batch = df_batch.drop(columns=['snapshotTimeUTC'])
            
            # Rename price columns
            column_map = {
                'openPrice': 'open',
                'highPrice': 'high', 
                'lowPrice': 'low',
                'closePrice': 'close',
                'lastTradedVolume': 'volume'
            }
            df_batch = df_batch.rename(columns={k: v for k, v in column_map.items() if k in df_batch.columns})
            
            # Keep only needed columns
            keep_cols = ['time', 'open', 'high', 'low', 'close']
            if 'volume' in df_batch.columns:
                keep_cols.append('volume')
            df_batch = df_batch[keep_cols]
            
            all_data.append(df_batch)
            bars_fetched += len(df_batch)
            
            # Update to_date for next batch (go backwards in time)
            if len(df_batch) > 0:
                earliest_time = df_batch['time'].min()
                to_date = earliest_time.strftime('%Y-%m-%dT%H:%M:%S')
            
            print(f"   ✓ Fetched {len(df_batch):,} bars (total: {bars_fetched:,}/{max_bars:,})")
            
            # Rate limiting (be nice to API)
            time.sleep(0.2)  # 200ms between requests
            
        except Exception as e:
            print(f"   ❌ Error fetching batch: {e}")
            break
    
    if not all_data:
        return None
    
    # Combine all batches
    df_combined = pd.concat(all_data, ignore_index=True)
    
    # Remove duplicates and sort
    df_combined = df_combined.drop_duplicates(subset=['time'])
    df_combined = df_combined.sort_values('time')
    df_combined = df_combined.reset_index(drop=True)
    
    # Set time as index
    df_combined = df_combined.set_index('time')
    
    return df_combined

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
            "max_bars": 150000,
            "output_file": "data/US100_M5_150000bars.csv",
            "description": "M5 (5-minute) ~2 years"
        },
        {
            "epic": "US100",
            "resolution": "MINUTE_15",
            "max_bars": 50000,
            "output_file": "data/US100_M15_50000bars.csv",
            "description": "M15 (15-minute) ~2 years"
        }
    ]
    
    for config in downloads:
        print("─" * 80)
        print(f"📥 Downloading {config['epic']} {config['description']}")
        print(f"   Resolution: {config['resolution']}")
        print(f"   Target bars: {config['max_bars']:,}")
        print()
        
        try:
            # Download data
            df = fetch_historical_data(
                client=client,
                epic=config['epic'],
                resolution=config['resolution'],
                max_bars=config['max_bars']
            )
            
            if df is None or len(df) == 0:
                print(f"   ❌ Failed to download data")
                continue
            
            # Calculate period covered
            start_date = df.index[0]
            end_date = df.index[-1]
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
            output_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(output_path)
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
            import traceback
            traceback.print_exc()
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
