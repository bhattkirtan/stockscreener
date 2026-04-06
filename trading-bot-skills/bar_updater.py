#!/usr/bin/env python3
"""
bar_updater.py — Incremental historical-bar sync job.

Finds the newest stored timestamp per epic/timeframe in the SQLite candles
table, then fetches only the missing bars from Capital.com and upserts them.

  - If the DB has NO bars for a pair → skip with a warning (run fetch_data.py
    first for the initial bulk download).
  - If the DB IS populated → fetch from `latest_bar_ts + 1 bar` to now and
    upsert.  Idempotent: duplicate timestamps are silently replaced.

Usage:
    # One-shot: update every instrument defined in config/instruments/
    python3 bar_updater.py

    # One-shot: specific pair
    python3 bar_updater.py --epic GOLD --timeframe M5

    # Daemon loop: update all pairs every 15 minutes
    python3 bar_updater.py --interval 900

    # Daemon loop: only EURUSD M5, every 5 minutes
    python3 bar_updater.py --epic EURUSD --timeframe M5 --interval 300
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Tuple

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT.parent / '.env')
load_dotenv(PROJECT_ROOT / '.env')

import yaml
from clients.capital_api import CapitalAPIClient
from clients.sqlite_api import SQLiteAPIClient
from fetch_data import (
    TIMEFRAME_MAP,
    MINUTES_PER_BAR,
    EPIC_ALIASES,
    fetch_all_bars,
    resolve_epic,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

RATE_LIMIT_SLEEP = 1.5   # seconds between epic updates within one cycle


# ── Instrument discovery ─────────────────────────────────────────────────────

def _load_instruments_config() -> List[Tuple[str, str]]:
    """
    Return list of (epic, timeframe) pairs from config/instruments/*.yaml.
    The 'timeframe' is read from market_data.timeframe (default M5).
    """
    inst_dir = PROJECT_ROOT / 'config' / 'instruments'
    pairs: List[Tuple[str, str]] = []
    for path in sorted(inst_dir.glob('*.yaml')):
        try:
            with open(path) as f:
                cfg = yaml.safe_load(f) or {}
            epic = cfg.get('market_data', {}).get('epic') or path.stem  # e.g. GOLD
            timeframe = str(cfg.get('market_data', {}).get('timeframe', 'M5')).upper()
            pairs.append((epic, timeframe))
        except Exception as exc:
            logger.warning(f"  ⚠️  Could not read {path.name}: {exc}")
    return pairs


# ── Latest-bar query ─────────────────────────────────────────────────────────

def _latest_timestamp(db: SQLiteAPIClient, epic: str, timeframe: str) -> str | None:
    """Return the MAX(timestamp) stored for this epic/timeframe, or None."""
    rows = db.query_candles(epic, timeframe, limit=1)  # returns newest-first inside
    # query_candles returns oldest→newest with limit; use the last element
    if not rows:
        return None
    return rows[-1]['timestamp']


# ── Core update logic ────────────────────────────────────────────────────────

def update_one(
    client: CapitalAPIClient,
    db: SQLiteAPIClient,
    epic: str,
    timeframe: str,
) -> int:
    """
    Fetch and store all bars newer than the latest stored bar for this pair.
    Returns the number of new candles inserted.
    """
    resolution = TIMEFRAME_MAP.get(timeframe.upper())
    if not resolution:
        logger.error(f"  [{epic}/{timeframe}] Unknown timeframe — skipping.")
        return 0

    latest_ts = _latest_timestamp(db, epic, timeframe)

    if latest_ts is None:
        logger.warning(
            f"  [{epic}/{timeframe}] No bars in DB — "
            f"run `python3 fetch_data.py --epic {epic} --timeframe {timeframe} --bars <N>` first."
        )
        return 0

    # Advance the window by one bar-width to avoid refetching the last bar
    bar_minutes = MINUTES_PER_BAR.get(resolution, 5)
    try:
        latest_dt = datetime.fromisoformat(latest_ts.replace(' ', 'T'))
    except ValueError:
        logger.error(f"  [{epic}/{timeframe}] Cannot parse latest_ts='{latest_ts}'")
        return 0

    from_dt = latest_dt + timedelta(minutes=bar_minutes)
    now_dt  = datetime.now(tz=timezone.utc).replace(tzinfo=None)  # naive UTC

    if from_dt >= now_dt:
        logger.info(f"  [{epic}/{timeframe}] Already up-to-date (latest: {latest_ts})")
        return 0

    from_str = from_dt.strftime('%Y-%m-%d %H:%M:%S')
    to_str   = now_dt.strftime('%Y-%m-%d %H:%M:%S')

    logger.info(f"  [{epic}/{timeframe}] Fetching {from_str} → {to_str}")
    resolved = resolve_epic(epic)

    try:
        candles = fetch_all_bars(
            client,
            epic=resolved,
            resolution=resolution,
            total_bars=10_000,   # upper-cap per run; pagination stops at from_date
            from_date=from_str,
            to_date=to_str,
        )
    except Exception as exc:
        logger.error(f"  [{epic}/{timeframe}] Fetch failed: {exc}")
        return 0

    if not candles:
        logger.info(f"  [{epic}/{timeframe}] No new candles returned (market closed or no data).")
        return 0

    count = db.insert_candles(epic, timeframe, candles)
    logger.info(f"  [{epic}/{timeframe}] ✅ Inserted {count} new candles (latest now: {candles[-1]['timestamp']})")
    return count


def run_cycle(
    pairs: List[Tuple[str, str]],
    env: str = 'demo',
) -> None:
    """Run one update cycle across all pairs, sharing one API session."""
    logger.info(f"🔄 Update cycle started — {len(pairs)} pair(s)")

    client = CapitalAPIClient(environment=env)
    if not client.api_key:
        logger.error("CAPITAL_API_KEY not set — cannot update bars.")
        return

    try:
        client.create_session()
    except Exception as exc:
        logger.error(f"  Authentication failed: {exc}")
        return

    db = SQLiteAPIClient()
    total_new = 0

    for i, (epic, timeframe) in enumerate(pairs):
        if i > 0:
            time.sleep(RATE_LIMIT_SLEEP)
        try:
            total_new += update_one(client, db, epic, timeframe)
        except Exception as exc:
            logger.error(f"  [{epic}/{timeframe}] Unexpected error: {exc}")

    logger.info(f"✅ Cycle complete — {total_new} new candles total")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Incremental historical-bar sync for SQLite candles table.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--epic',      default=None, help='Single epic to update (e.g. GOLD)')
    parser.add_argument('--timeframe', default=None, help='Timeframe for --epic (default: M5)')
    parser.add_argument('--interval',  type=int, default=0,
                        help='If >0, run as daemon: sleep <N> seconds between cycles')
    parser.add_argument('--env',       default=None, help='demo|live (overrides CAPITAL_ENVIRONMENT)')
    args = parser.parse_args()

    env = args.env or os.getenv('CAPITAL_ENVIRONMENT', 'demo')

    # Build pair list
    if args.epic:
        timeframe = (args.timeframe or 'M5').upper()
        pairs = [(args.epic.upper(), timeframe)]
    else:
        pairs = _load_instruments_config()
        if args.timeframe:
            # Filter to requested timeframe only
            pairs = [(e, t) for e, t in pairs if t.upper() == args.timeframe.upper()]

    if not pairs:
        logger.error("No instruments to update. Check config/instruments/ or --epic argument.")
        sys.exit(1)

    logger.info(f"📋 Instruments: {', '.join(f'{e}/{t}' for e, t in pairs)}")

    if args.interval > 0:
        logger.info(f"⏱  Daemon mode: updating every {args.interval}s")
        while True:
            try:
                run_cycle(pairs, env=env)
            except Exception as exc:
                logger.error(f"Cycle error: {exc}")
            logger.info(f"💤 Sleeping {args.interval}s …")
            time.sleep(args.interval)
    else:
        run_cycle(pairs, env=env)


if __name__ == '__main__':
    main()
