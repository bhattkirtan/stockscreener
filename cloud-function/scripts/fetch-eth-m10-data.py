#!/usr/bin/env python3
"""
Fetch 1 year of ETH/USD M5 data from Capital.com
~105,120 bars (5-min candles, 24/7 crypto market)
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.api.capital_client import create_client_from_env
from src.data.cache_data import cache_data
import pandas as pd

def main():
    INSTRUMENT = 'ETHUSD'
    RESOLUTION = 'M5'
    # 1 year: 12 candles/hr × 24 hrs × 365 days = 105,120 bars (crypto is 24/7)
    BARS = 105120

    print(f"🔄 Fetching {INSTRUMENT} {RESOLUTION} — 1 year of data...")
    print(f"   Bars requested: {BARS:,} (~12 months, crypto 24/7)")
    print()

    client = create_client_from_env()

    # cache_data auto-names: data/{epic}_{resolution}_{max_bars}bars.csv
    df = cache_data(
        client=client,
        epic=INSTRUMENT,
        resolution=RESOLUTION,
        max_bars=BARS,
        force_refresh=True,
    )

    output_file = f"data/{INSTRUMENT}_{RESOLUTION}_{BARS}bars.csv"

    if isinstance(df, pd.DataFrame):
        if 'timestamp' not in df.columns:
            df = df.reset_index()
        df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
        print(f"✅ Downloaded {len(df):,} bars")
        print(f"   Range: {df['timestamp'].min()} → {df['timestamp'].max()}")
        print(f"   Price range: ${df['close'].min():.2f} – ${df['close'].max():.2f}")
        print(f"   Saved: {output_file}")
    else:
        print(f"✅ Data cached: {output_file}")

if __name__ == '__main__':
    main()
        print(f"   Range: {df['timestamp'].min()} → {df['timestamp'].max()}")
        print(f"   Price range: ${df['close'].min():.2f} – ${df['close'].max():.2f}")
        print(f"   Saved: {output_file}")
    else:
        print(f"✅ Data cached: {output_file}")

if __name__ == '__main__':
    main()
