#!/usr/bin/env python3
"""
Fetch M5 historical data from Capital.com API
"""
import sys
sys.path.insert(0, '/Users/kirtanbhatt/code/stockScreener/cloud-function')

from src.api.capital_client import create_client_from_env
from src.data.cache_data import cache_data
import pandas as pd

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Fetch historical M5 data')
    parser.add_argument('--instrument', default='GOLD', help='Instrument to fetch (default: GOLD)')
    parser.add_argument('--bars', type=int, default=25000, help='Number of bars to fetch (default: 25000 = ~4 months)')
    parser.add_argument('--resolution', default='M5', help='Timeframe (default: M5)')
    
    args = parser.parse_args()
    
    # Calculate estimated duration
    trading_hours_per_day = 6.5  # Approximate
    bars_per_day = trading_hours_per_day * 12  # 12 bars per hour for M5
    estimated_days = int(args.bars / bars_per_day)
    estimated_months = round(estimated_days / 22, 1)  # ~22 trading days per month
    
    print(f"🔄 Fetching {args.instrument} {args.resolution} historical data from Capital.com...")
    print(f"   Bars requested: {args.bars:,} (~{estimated_months} months)")
    print()
    
    # Create client
    client = create_client_from_env()
    
    # Define what we want
    instrument = args.instrument
    resolution = args.resolution
    max_bars = args.bars
    
    print(f"📥 Downloading {max_bars:,} bars of {instrument} {resolution}...")
    
    try:
        # Cache the data (downloads and saves to local file)
        df = cache_data(
            client=client,
            epic=instrument,
            resolution=resolution,
            max_bars=max_bars,
            force_refresh=True
        )
        
        output_file = f"data/{instrument}_{resolution}_{max_bars}bars.csv"
        print(f"✅ Downloaded to: {output_file}")
        
        # Verify the download - df is the DataFrame returned
        if isinstance(df, pd.DataFrame):
            if 'timestamp' not in df.columns:
                df = df.reset_index()  # timestamp might be in index
            df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
        else:
            # If it's still a file path, read it
            df = pd.read_csv(output_file)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        print(f"\n📊 Downloaded Data:")
        print(f"   Bars: {len(df):,}")
        print(f"   Start: {df['timestamp'].min()}")
        print(f"   End: {df['timestamp'].max()}")
        print(f"   Duration: {(df['timestamp'].max() - df['timestamp'].min()).days + 1} days")
        
        return output_file
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == '__main__':
    main()
