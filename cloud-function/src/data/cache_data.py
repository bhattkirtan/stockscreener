#!/usr/bin/env python3
"""
Incremental data caching - fetches delta from Capital.com
Tracks last fetch time with metadata and only fetches new bars
"""

import os
import sys
import pandas as pd
import json
from datetime import datetime, timedelta
import logging

from src.api.capital_client import create_client_from_env
from .gcs_cache import ensure_csv_from_gcs

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

METADATA_FILE = 'data/.fetch_metadata.json'


RESOLUTIONS = {
    'M1': 'MINUTE',
    'M5': 'MINUTE_5',
    'M15': 'MINUTE_15',
    'M30': 'MINUTE_30',
    'H1': 'HOUR',
    'H4': 'HOUR_4',
    'D1': 'DAY',
}


def load_metadata():
    """Load fetch metadata to track last fetch times"""
    if os.path.exists(METADATA_FILE):
        with open(METADATA_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_metadata(metadata):
    """Save fetch metadata"""
    os.makedirs('data', exist_ok=True)
    with open(METADATA_FILE, 'w') as f:
        json.dump(metadata, f, indent=2)

def fetch_incremental(client, epic, resolution, from_timestamp):
    """Fetch only new bars since last timestamp"""
    try:
        resp = client.get(f'/api/v1/prices/{epic}', params={
            'resolution': RESOLUTIONS[resolution],
            'from': from_timestamp.isoformat(),
            'max': 1000
        })
        if not resp.ok:
            logger.error(f"Failed incremental fetch: {resp.status_code}")
            return None
        
        prices = resp.json().get('prices', [])
        if not prices:
            return None
        
        df = pd.DataFrame([{
            'timestamp': p['snapshotTime'],
            'open': float(p['openPrice']['bid']),
            'high': float(p['highPrice']['bid']),
            'low': float(p['lowPrice']['bid']),
            'close': float(p['closePrice']['bid']),
            'volume': int(p.get('lastTradedVolume', 0))
        } for p in prices])
        
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
        df.sort_index(inplace=True)
        return df
    except Exception as e:
        logger.error(f"Error fetching incremental: {e}")
        return None


def cache_data(client, epic, resolution='M15', max_bars=10000, force_refresh=False):
    """Fetch and cache data with incremental updates
    
    Args:
        force_refresh: Force full re-download
    """
    os.makedirs('data', exist_ok=True)
    
    # Try to get from GCS first
    try:
        cache_file = str(ensure_csv_from_gcs(epic, resolution, max_bars))
    except:
        # Fall back to local path if GCS fails
        cache_file = f"data/{epic}_{resolution}_{max_bars}bars.csv"
    
    metadata = load_metadata()
    key = f"{epic}_{resolution}_{max_bars}"
    
    # Try incremental update
    if not force_refresh and os.path.exists(cache_file) and key in metadata:
        last_fetch = datetime.fromisoformat(metadata[key]['last_fetch'])
        hours_old = (datetime.now() - last_fetch).seconds / 3600
        
        if hours_old < 1:
            logger.info(f"✅ Recent: {cache_file} ({int(hours_old*60)}m ago)")
            return pd.read_csv(cache_file, index_col=0, parse_dates=True)
        
        logger.info(f"📡 Incremental: {epic} {resolution} (last: {int(hours_old)}h ago)")
        existing = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        new_data = fetch_incremental(client, epic, resolution, existing.index[-1])
        
        if new_data is not None and len(new_data) > 0:
            combined = pd.concat([existing, new_data]).drop_duplicates().sort_index()
            if len(combined) > max_bars:
                combined = combined.iloc[-max_bars:]
            combined.to_csv(cache_file)
            
            metadata[key] = {
                'last_fetch': datetime.now().isoformat(),
                'bars': len(combined),
                'last_bar': combined.index[-1].isoformat()
            }
            save_metadata(metadata)
            
            logger.info(f"💾 Updated: +{len(new_data)} new bars (total: {len(combined)})")
            logger.info(f"   Range: {combined.index[0]} to {combined.index[-1]}")
            return combined
        else:
            logger.info(f"✅ No new data available")
            return existing
    
    # Full fetch
    logger.info(f"📡 Full fetch: {epic} {resolution} ({max_bars} bars)")
    
    all_prices = []
    remaining = max_bars
    to_timestamp = None  # Start from most recent, paginate backwards
    
    while remaining > 0:
        batch_size = min(remaining, 1000)  # API limit per request
        
        params = {
            'resolution': RESOLUTIONS[resolution],
            'max': batch_size
        }
        
        # Add 'to' parameter for pagination (fetch older bars)
        if to_timestamp:
            params['to'] = to_timestamp
        
        resp = client.get(f'/api/v1/prices/{epic}', params=params)
        
        if not resp.ok:
            logger.error(f"API error: {resp.status_code}")
            break
        
        prices = resp.json().get('prices', [])
        if not prices:
            logger.info(f"   No more historical data available")
            break
        
        # Check if we got new unique data
        old_count = len(all_prices)
        all_prices.extend(prices)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_prices = []
        for p in all_prices:
            snapshot = p['snapshotTime']
            if snapshot not in seen:
                seen.add(snapshot)
                unique_prices.append(p)
        all_prices = unique_prices
        
        new_bars = len(all_prices) - old_count
        
        if new_bars == 0:
            logger.info(f"   No new bars fetched, stopping pagination")
            break
        
        remaining -= new_bars
        logger.info(f"   Fetched {len(all_prices)} bars...")
        
        # Set 'to' timestamp to oldest bar for next batch (paginate backwards)
        if prices:
            oldest_timestamp = min(p['snapshotTime'] for p in prices)
            to_timestamp = oldest_timestamp
    
    # Convert to DataFrame
    df = pd.DataFrame([{
        'timestamp': p['snapshotTime'],
        'open': float(p['openPrice']['bid']),
        'high': float(p['highPrice']['bid']),
        'low': float(p['lowPrice']['bid']),
        'close': float(p['closePrice']['bid']),
        'volume': int(p.get('lastTradedVolume', 0))
    } for p in all_prices])
    
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df.set_index('timestamp', inplace=True)
    df.sort_index(inplace=True)
    df = df[~df.index.duplicated(keep='first')]
    
    # Save with metadata
    df.to_csv(cache_file)
    
    metadata[key] = {
        'last_fetch': datetime.now().isoformat(),
        'bars': len(df),
        'last_bar': df.index[-1].isoformat()
    }
    save_metadata(metadata)
    
    logger.info(f"💾 Saved {len(df)} bars to {cache_file}")
    logger.info(f"   Range: {df.index[0]} to {df.index[-1]}")
    
    return df


if __name__ == '__main__':
    print("\n" + "="*70)
    print("📊 Data Caching - Fetch from Capital.com")
    print("="*70 + "\n")
    
    try:
        # Check for force refresh flag
        force_refresh = '--force' in sys.argv or '-f' in sys.argv
        if force_refresh:
            print("🔄 Force refresh mode - re-downloading all data\n")
        
        client = create_client_from_env()
        
        # Fetch multiple datasets with larger history
        datasets = [
            ('GOLD', 'M15', 10000),  # ~70 days
            ('GOLD',  'M5', 5000),   # ~17 days
            ('EURUSD', 'M15', 10000), # ~70 days
        ]
        
        # Check for missing files
        if not force_refresh:
            missing = []
            for epic, res, bars in datasets:
                if not os.path.exists(f"data/{epic}_{res}_{bars}bars.csv"):
                    missing.append(f"{epic} {res}")
            
            if missing:
                print(f"📥 Found {len(missing)} missing datasets:")
                for m in missing:
                    print(f"   - {m}")
                print()
        
        for epic, res, bars in datasets:
            cache_data(client, epic, res, bars, force_refresh=force_refresh)
            print()
        
        print("="*70)
        print("✅ All data cached successfully!")
        print("="*70)
        print(f"\n📁 Location: {os.path.abspath('data/')}/")
        print(f"📄 Files: {len(datasets)} CSV files")
        print("\n💡 Next: python3 src/run_backtest_from_cache.py\n")
        
    except Exception as e:
        print(f"\n❌ Error: {e}\n")
        print("💡 Run: python3 setup_local_env.py")
        sys.exit(1)
