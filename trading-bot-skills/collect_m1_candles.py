#!/usr/bin/env python3
"""
collect_m1_candles.py — Daily M1 candle collector

Fetches yesterday's M1 candles from Capital.com and appends them to a
rolling CSV file. Run once per day via cron or systemd timer.

Usage:
    python3 collect_m1_candles.py                        # collect yesterday
    python3 collect_m1_candles.py --epic EURUSD          # different instrument
    python3 collect_m1_candles.py --date 2026-03-30      # specific date
    python3 collect_m1_candles.py --backfill-days 7      # last 7 days

Output:
    cloud-function/data/GOLD_M1_rolling.csv   (appended daily)
"""

import argparse
import csv
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT.parent / '.env')
load_dotenv(PROJECT_ROOT / '.env')

from clients.capital_api import CapitalAPIClient
from fetch_data import fetch_all_bars, TIMEFRAME_MAP, EPIC_ALIASES, parse_candle

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

DATA_DIR = PROJECT_ROOT.parent / 'cloud-function' / 'data'
FIELDNAMES = ['timestamp', 'open', 'high', 'low', 'close', 'volume']


def rolling_file(epic: str) -> Path:
    """Path to the rolling M1 CSV for this instrument."""
    instrument = epic.upper()
    for alias, full in EPIC_ALIASES.items():
        if full == epic:
            instrument = alias
            break
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / f'{instrument}_M1_rolling.csv'


def load_existing_timestamps(path: Path) -> set:
    """Read all timestamps already in the CSV to avoid duplicates."""
    if not path.exists():
        return set()
    with open(path, 'r') as f:
        reader = csv.DictReader(f)
        return {row['timestamp'] for row in reader}


def append_candles(path: Path, candles: list, existing: set) -> int:
    """Append new candles to the rolling CSV. Returns count written."""
    new_candles = [c for c in candles if c['timestamp'] not in existing]
    if not new_candles:
        return 0

    write_header = not path.exists()
    with open(path, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerows(new_candles)
    return len(new_candles)


def collect_day(client: CapitalAPIClient, epic: str, date: str) -> list:
    """
    Fetch all M1 candles for a specific UTC date (YYYY-MM-DD).
    Returns list of candle dicts.
    """
    from_dt = f"{date} 00:00:00"
    to_dt   = f"{date} 23:59:00"

    logger.info(f"📥 Fetching M1 candles: {epic}  {from_dt} → {to_dt}")

    candles = fetch_all_bars(
        client=client,
        epic=epic,
        resolution=TIMEFRAME_MAP['M1'],
        total_bars=1440,           # max 1 day = 1440 M1 bars
        from_date=from_dt,
        to_date=to_dt,
    )
    logger.info(f"   Got {len(candles)} candles for {date}")
    return candles


def main():
    parser = argparse.ArgumentParser(description='Daily M1 candle collector')
    parser.add_argument('--epic',          default='GOLD',  help='Instrument (GOLD, EURUSD, US100)')
    parser.add_argument('--date',          default=None,    help='Specific date YYYY-MM-DD (default: yesterday)')
    parser.add_argument('--backfill-days', type=int, default=1,
                        help='Collect last N days (default: 1 = yesterday only)')
    parser.add_argument('--env',           default=None,    help='demo or live')
    args = parser.parse_args()

    epic = EPIC_ALIASES.get(args.epic.upper(), args.epic.upper())
    env  = args.env or os.getenv('CAPITAL_ENVIRONMENT', 'demo')

    # Determine dates to collect
    if args.date:
        dates = [args.date]
    else:
        today = datetime.utcnow().date()
        dates = [
            str(today - timedelta(days=i))
            for i in range(args.backfill_days, 0, -1)
        ]

    logger.info(f"🚀 M1 collector: {args.epic} ({epic}) [{env}]")
    logger.info(f"   Dates to collect: {dates}")

    # Authenticate once
    client = CapitalAPIClient(environment=env)
    if not client.api_key:
        logger.error("CAPITAL_API_KEY not set.")
        sys.exit(1)
    try:
        client.create_session()
        logger.info("✅ Authenticated")
    except Exception as e:
        logger.error(f"Auth failed: {e}")
        sys.exit(1)

    out_path = rolling_file(epic)
    existing = load_existing_timestamps(out_path)
    logger.info(f"📂 Rolling file: {out_path}  ({len(existing):,} existing candles)")

    total_written = 0
    for date in dates:
        try:
            candles = collect_day(client, epic, date)
            written  = append_candles(out_path, candles, existing)
            existing.update(c['timestamp'] for c in candles)
            total_written += written
            logger.info(f"   ✅ {date}: {written} new candles written")
            time.sleep(0.5)  # rate limit between days
        except Exception as e:
            logger.error(f"   ❌ {date} failed: {e}")

    logger.info(f"\n✅ Done — {total_written} new candles appended to {out_path}")
    if out_path.exists():
        import pandas as pd
        df = pd.read_csv(out_path)
        logger.info(f"   Total in file: {len(df):,} rows  ({df['timestamp'].min()} → {df['timestamp'].max()})")


if __name__ == '__main__':
    main()
