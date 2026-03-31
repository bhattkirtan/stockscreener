#!/usr/bin/env python3
"""
fetch_data.py — Download historical OHLC data from Capital.com

Usage:
    python3 fetch_data.py --epic EURUSD --timeframe M5 --bars 150000
    python3 fetch_data.py --epic EURUSD --timeframe M15 --bars 50000
    python3 fetch_data.py --epic CS.D.CFDGOLD.CFD.IP --timeframe M5 --bars 150000 --env live
    python3 fetch_data.py --epic EURUSD --timeframe M5 --bars 10000 --output custom_name.csv

Epics (common):
    EURUSD              EUR/USD forex (auto-resolved to CS.D.EURUSD.CFD.IP)
    GOLD                Gold CFD (auto-resolved to CS.D.CFDGOLD.CFD.IP)
    US100               NASDAQ 100 (auto-resolved to CS.D.NASDAQ.CFD.IP)
    Or any raw Capital.com epic (e.g. CS.D.EURUSD.CFD.IP)

Timeframes:
    M1, M5, M15, M30, H1, H4, D1, W1

Env vars required (or use .env in project root):
    CAPITAL_API_KEY
    CAPITAL_IDENTIFIER   (or CAPITAL_USERNAME)
    CAPITAL_PASSWORD
    CAPITAL_ENVIRONMENT  (demo|live, default: demo)
"""

import argparse
import csv
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path so clients/ is importable
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT.parent / '.env')
load_dotenv(PROJECT_ROOT / '.env')

from clients.capital_api import CapitalAPIClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

TIMEFRAME_MAP = {
    'M1':  'MINUTE',
    'M5':  'MINUTE_5',
    'M15': 'MINUTE_15',
    'M30': 'MINUTE_30',
    'H1':  'HOUR',
    'H4':  'HOUR_4',
    'D1':  'DAY',
    'W1':  'WEEK',
}

MINUTES_PER_BAR = {
    'MINUTE':    1,
    'MINUTE_5':  5,
    'MINUTE_15': 15,
    'MINUTE_30': 30,
    'HOUR':      60,
    'HOUR_4':    240,
    'DAY':       1440,
    'WEEK':      10080,
}

# Friendly name → Capital.com epic
EPIC_ALIASES = {
    # Demo account short epics (discovered via /api/v1/markets search)
    'EURUSD': 'EURUSD',
    'GBPUSD': 'GBPUSD',
    'USDJPY': 'USDJPY',
    'GOLD':   'GOLD',
    'SILVER': 'SILVER',
    'US100':  'US100',
    'US500':  'US500',
    'OIL':    'OIL',
    'BTCUSD': 'BTCUSD',
}

BATCH_SIZE = 1000          # Max bars per API call
RATE_LIMIT_SLEEP = 0.5     # Seconds between API calls


# ── Helpers ──────────────────────────────────────────────────────────────────

def resolve_epic(epic: str) -> str:
    """Resolve friendly name to Capital.com epic format."""
    return EPIC_ALIASES.get(epic.upper(), epic)


def derive_output_name(epic: str, timeframe: str, bars: int) -> Path:
    """Build default output path: cloud-function/data/EURUSD_M5_150000bars.csv"""
    # Reverse-lookup alias for clean filename
    instrument = epic.upper()
    for alias, full_epic in EPIC_ALIASES.items():
        if full_epic == epic:
            instrument = alias
            break

    filename = f"{instrument}_{timeframe}_{bars}bars.csv"
    output_dir = PROJECT_ROOT.parent / 'cloud-function' / 'data'
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / filename


def parse_candle(price: dict) -> dict | None:
    """Extract a flat OHLCV row from Capital.com price dict."""
    try:
        snap = price.get('snapshotTime', '')
        # Capital.com snapshotTime formats:
        #   '2026/03/29 10:00:00:000'  → normalise to '2026-03-29 10:00:00'
        #   '2026-03-29T10:00:00'      → already clean
        ts = snap.replace('/', '-')           # fix date separators
        ts = ts.replace('T', ' ')             # use space between date and time
        # Drop milliseconds: 'YYYY-MM-DD HH:MM:SS:mmm' → 'YYYY-MM-DD HH:MM:SS'
        if ts.count(':') > 2:
            ts = ts.rsplit(':', 1)[0]
        ts = ts[:19]

        bid = price.get('openPrice', {})
        ask = price.get('closePrice', {})  # Capital uses openPrice/closePrice as candle OHLC
        # In Capital's prices API: openPrice, highPrice, lowPrice, closePrice are dicts with bid/ask
        o = price.get('openPrice', {}).get('mid') or (
            (price['openPrice'].get('bid', 0) + price['openPrice'].get('ask', 0)) / 2
        )
        h = price.get('highPrice', {}).get('mid') or (
            (price['highPrice'].get('bid', 0) + price['highPrice'].get('ask', 0)) / 2
        )
        l = price.get('lowPrice', {}).get('mid') or (
            (price['lowPrice'].get('bid', 0) + price['lowPrice'].get('ask', 0)) / 2
        )
        c = price.get('closePrice', {}).get('mid') or (
            (price['closePrice'].get('bid', 0) + price['closePrice'].get('ask', 0)) / 2
        )
        v = price.get('lastTradedVolume', 0)

        if not o or not h or not l or not c:
            return None

        return {
            'timestamp': ts,
            'open':      round(float(o), 6),
            'high':      round(float(h), 6),
            'low':       round(float(l), 6),
            'close':     round(float(c), 6),
            'volume':    int(v) if v else 0,
        }
    except (KeyError, TypeError, ValueError):
        return None


# ── Core fetch loop ──────────────────────────────────────────────────────────

def fetch_all_bars(client: CapitalAPIClient, epic: str, resolution: str, total_bars: int) -> list:
    """
    Fetch `total_bars` candles by paginating backwards using the 'to' parameter.
    Capital.com API: omit 'from', set 'to' = oldest timestamp from previous batch.
    Returns list of candle dicts sorted oldest → newest, deduplicated.
    """
    all_candles = {}   # keyed by timestamp for dedup
    to_timestamp = None  # None = start from most recent
    batch_num = 0

    while len(all_candles) < total_bars:
        remaining = total_bars - len(all_candles)
        batch = min(remaining, BATCH_SIZE)

        params = {
            'resolution': resolution,
            'max': batch,
        }
        if to_timestamp:
            params['to'] = to_timestamp

        batch_num += 1
        logger.info(
            f"  Batch {batch_num}: to={to_timestamp or 'now'} "
            f"(requesting {batch} bars, fetched so far: {len(all_candles)}/{total_bars})"
        )

        try:
            response = client._request('GET', f'/api/v1/prices/{epic}', params=params)
            prices = response.json().get('prices', [])
        except Exception as e:
            logger.error(f"  ❌ Batch {batch_num} failed: {e}")
            break

        if not prices:
            logger.warning("  ⚠️  No data returned, stopping.")
            break

        old_count = len(all_candles)
        oldest_snapshot = None

        for price in prices:
            candle = parse_candle(price)
            if candle and candle['timestamp'] not in all_candles:
                all_candles[candle['timestamp']] = candle
            snap = price.get('snapshotTime', '')
            if oldest_snapshot is None or snap < oldest_snapshot:
                oldest_snapshot = snap

        new_candles = len(all_candles) - old_count
        logger.info(f"  ✅ Got {new_candles} new candles (total unique: {len(all_candles)})")

        if new_candles == 0:
            logger.warning("  No new candles — reached end of available history.")
            break

        # Paginate backwards: set 'to' to the oldest snapshot time
        to_timestamp = oldest_snapshot

        time.sleep(RATE_LIMIT_SLEEP)

    # Sort by timestamp oldest → newest
    sorted_candles = sorted(all_candles.values(), key=lambda x: x['timestamp'])
    return sorted_candles


def save_csv(candles: list, output_path: Path) -> None:
    """Write candles list to CSV file."""
    fieldnames = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(candles)
    logger.info(f"💾 Saved {len(candles)} candles → {output_path}")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Fetch historical OHLC data from Capital.com',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('--epic',      required=True,  help='Instrument epic or alias (e.g. EURUSD, GOLD, US100)')
    parser.add_argument('--timeframe', required=True,  help='Timeframe: M1, M5, M15, M30, H1, H4, D1, W1')
    parser.add_argument('--bars',      type=int, default=50000, help='Total bars to fetch (default: 50000)')
    parser.add_argument('--output',    default=None,   help='Output CSV path (default: cloud-function/data/<EPIC>_<TF>_<BARS>bars.csv)')
    parser.add_argument('--env',       default=None,   help='demo or live (overrides CAPITAL_ENVIRONMENT)')
    args = parser.parse_args()

    # Resolve timeframe
    resolution = TIMEFRAME_MAP.get(args.timeframe.upper())
    if not resolution:
        logger.error(f"Unknown timeframe '{args.timeframe}'. Valid: {', '.join(TIMEFRAME_MAP)}")
        sys.exit(1)

    # Resolve epic
    epic = resolve_epic(args.epic)

    # Determine output path
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        output_path = derive_output_name(epic, args.timeframe.upper(), args.bars)

    # Init API client
    env = args.env or os.getenv('CAPITAL_ENVIRONMENT', 'demo')
    client = CapitalAPIClient(environment=env)

    if not client.api_key:
        logger.error("CAPITAL_API_KEY not set. Add it to .env or export it.")
        sys.exit(1)

    logger.info(f"🚀 Fetching {args.bars} × {args.timeframe} bars for {args.epic} ({epic}) [{env}]")
    logger.info(f"   Output → {output_path}")

    # Authenticate
    try:
        client.create_session()
    except Exception as e:
        logger.error(f"Authentication failed: {e}")
        sys.exit(1)

    # Fetch
    start = time.time()
    candles = fetch_all_bars(client, epic, resolution, args.bars)
    elapsed = time.time() - start

    if not candles:
        logger.error("No candles fetched. Check epic, timeframe, or API credentials.")
        sys.exit(1)

    logger.info(
        f"\n📊 Summary:"
        f"\n   Epic:       {epic}"
        f"\n   Timeframe:  {args.timeframe}"
        f"\n   Requested:  {args.bars} bars"
        f"\n   Received:   {len(candles)} bars"
        f"\n   From:       {candles[0]['timestamp']}"
        f"\n   To:         {candles[-1]['timestamp']}"
        f"\n   Elapsed:    {elapsed:.1f}s"
    )

    save_csv(candles, output_path)
    print(f"\n✅ Done: {output_path}")


if __name__ == '__main__':
    main()
