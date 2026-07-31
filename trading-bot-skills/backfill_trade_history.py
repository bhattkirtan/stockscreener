#!/usr/bin/env python3
"""
Backfill the `trade_history` collection from Capital.com.

Why this exists
---------------
Until the StorageSkill fix, no closed trade was ever persisted, so the live
performance report (UI → Performance → Live) had nothing to read. Going
forward the bot writes each trade on close; this script recovers the history
that was lost before that fix landed.

How it works
------------
Two sources are joined on dealId:

  /history/transactions   → realised P&L (authoritative, net of spread/fees)
                            but no entry price, direction, or size
  kv_store/active_positions → entry price, direction, size, opened_at, SL/TP
                            (written by StorageSkill when the position opened)

Rows present in transactions but missing from active_positions are still
written, with P&L only — a partial record beats a missing trade in the totals.

API quirks this works around (all confirmed against the demo account):
  - `size` in a transaction is the realised P&L, NOT the position size.
  - A response is hard-capped at 100 rows; pageSize/pageNumber are ignored.
    Hence the date-window chunking below.
  - `lastPeriod` is capped at 86400s.
  - A `to` in the future returns 400 error.invalid.daterange.

Usage
-----
    cd trading-bot-skills
    python backfill_trade_history.py --days 90
    python backfill_trade_history.py --from 2026-06-01 --to 2026-07-30
    python backfill_trade_history.py --days 30 --dry-run
"""

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Window size for chunking. Each request returns at most 100 rows, so keep
# windows small enough that a busy day cannot silently truncate.
WINDOW_HOURS = 12
MAX_ROWS_PER_RESPONSE = 100

# instrument name (as Capital.com reports it) → bot_id
BOT_ID_BY_INSTRUMENT = {
    'GOLD':   'gold_m5_bot',
    'SILVER': 'silver_m5_bot',
    'EURUSD': 'eurusd_m5_bot',
    'BTCUSD': 'btcusd_m5_bot',
    'ETHUSD': 'ethusd_m5_bot',
    'US100':  'us100_m5_bot',
}


def fetch_transactions(client, start: datetime, end: datetime) -> list:
    """Fetch TRADE transactions across [start, end) in chunked windows."""
    import requests

    headers = {
        'X-SECURITY-TOKEN': client.security_token,
        'CST':              client.cst,
        'X-CAP-API-KEY':    client.api_key,
    }
    url = client.base_url + '/api/v1/history/transactions'

    # A `to` in the future is rejected outright.
    now = datetime.utcnow()
    if end > now:
        end = now

    seen = {}
    truncated_windows = 0
    cursor = start

    while cursor < end:
        window_end = min(cursor + timedelta(hours=WINDOW_HOURS), end)
        params = {
            'from': cursor.strftime('%Y-%m-%dT%H:%M:%S'),
            'to':   window_end.strftime('%Y-%m-%dT%H:%M:%S'),
        }
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code != 200:
                logger.warning(f"  ⚠️  {params['from']} → {params['to']}: "
                               f"HTTP {resp.status_code} {resp.text[:120]}")
                cursor = window_end
                continue
            rows = resp.json().get('transactions', [])
        except Exception as e:
            logger.warning(f"  ⚠️  {params['from']} → {params['to']}: {e}")
            cursor = window_end
            continue

        if len(rows) >= MAX_ROWS_PER_RESPONSE:
            truncated_windows += 1
            logger.warning(
                f"  ⚠️  {params['from']} → {params['to']} returned "
                f"{len(rows)} rows (at the {MAX_ROWS_PER_RESPONSE}-row cap) — "
                f"some trades in this window may be missing. "
                f"Re-run with a smaller WINDOW_HOURS."
            )

        for row in rows:
            if row.get('transactionType') != 'TRADE':
                continue
            deal_id = row.get('dealId')
            if deal_id:
                seen[deal_id] = row

        logger.info(f"  {params['from'][:16]} → {params['to'][:16]}  "
                    f"{len(rows):>3} rows, {len(seen):>4} trades so far")
        cursor = window_end

    if truncated_windows:
        logger.warning(f"\n⚠️  {truncated_windows} window(s) hit the row cap — "
                       f"coverage is incomplete.")
    return list(seen.values())


def load_open_positions(sqlite_client) -> dict:
    """deal_id → position row previously written by StorageSkill."""
    rows = sqlite_client.get_all_positions('active_positions')
    return {r.get('deal_id') or r.get('_id'): r for r in rows}


def build_trade(txn: dict, position: dict, bot_id_override: str = None) -> dict:
    """Merge a transaction (P&L) with its open-position row (entry details)."""
    deal_id = txn['dealId']
    instrument = txn.get('instrumentName', '')

    # Capital.com puts the realised P&L in `size`. Yes, really.
    try:
        pnl = float(txn.get('size') or 0.0)
    except (TypeError, ValueError):
        pnl = 0.0

    position = position or {}
    entry = float(position.get('open_level') or 0.0)
    qty   = float(position.get('size') or 0.0)
    side  = (position.get('direction') or '').upper()
    margin = entry * qty

    exit_price = float(position.get('close_price') or 0.0)
    # close_price was recorded as 0.0 by the old code path. When we know entry,
    # size and P&L, the exit price is recoverable.
    exit_estimated = False
    if not exit_price and entry and qty and side in ('BUY', 'SELL'):
        exit_price = entry + (pnl / qty) * (1.0 if side == 'BUY' else -1.0)
        exit_estimated = True

    return {
        'deal_id':       deal_id,
        'bot_id':        bot_id_override or BOT_ID_BY_INSTRUMENT.get(instrument.upper()),
        'epic':          position.get('epic') or instrument,
        'direction':     side or 'BUY',
        'size':          qty,
        'entry_price':   entry,
        'exit_price':    round(exit_price, 5),
        'entry_time':    position.get('opened_at', ''),
        'exit_time':     txn.get('dateUtc') or txn.get('date') or '',
        'pnl':           round(pnl, 2),
        'pnl_pct':       round(pnl / margin * 100, 4) if margin else 0.0,
        'exit_reason':   position.get('close_reason') or 'UNKNOWN',
        'stop_loss':     position.get('stop_loss'),
        'take_profit':   position.get('take_profit'),
        'currency':      txn.get('currency'),
        'pnl_estimated':  False,          # broker figure — authoritative
        'exit_price_estimated': exit_estimated,
        # opened_at on these rows was rewritten on every ~60s REST reconcile by
        # the pre-fix _save_position, so it is really "last reconcile before
        # close", not the open. Hold time computed from it would read as
        # seconds. Flag it so the UI shows "—" rather than a confident lie.
        'entry_time_estimated': True,
        'backfilled':    True,
        'partial':       not bool(position),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--days', type=int, default=90,
                        help='Look back this many days (default 90)')
    parser.add_argument('--from', dest='from_date',
                        help='Start date YYYY-MM-DD (overrides --days)')
    parser.add_argument('--to', dest='to_date',
                        help='End date YYYY-MM-DD (default: now)')
    parser.add_argument('--environment', default=None,
                        help='demo | live (default: CAPITAL_ENVIRONMENT from .env)')
    parser.add_argument('--instrument', help='Only backfill this instrument (e.g. GOLD)')
    parser.add_argument('--bot-id', dest='bot_id',
                        help='Force this bot_id on every record')
    parser.add_argument('--db', help='Path to trading.db (default: $DB_PATH or /data/trading.db)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be written, write nothing')
    args = parser.parse_args()

    # Load .env from the repo root
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'))

    db_path = args.db or os.environ.get('DB_PATH', '/data/trading.db')
    environment = args.environment or os.environ.get('CAPITAL_ENVIRONMENT', 'demo')

    if args.to_date:
        end = datetime.strptime(args.to_date, '%Y-%m-%d')
    else:
        end = datetime.utcnow()
    if args.from_date:
        start = datetime.strptime(args.from_date, '%Y-%m-%d')
    else:
        start = end - timedelta(days=args.days)

    logger.info(f"📅 Range      : {start:%Y-%m-%d %H:%M} → {end:%Y-%m-%d %H:%M} UTC")
    logger.info(f"🗄️  Database   : {db_path}")
    logger.info(f"🌐 Environment: {environment}")
    if args.dry_run:
        logger.info("🔍 DRY RUN — nothing will be written")
    logger.info("")

    import clients.sqlite_api as sqlite_api
    sqlite_api.DB_PATH = db_path
    from clients.capital_api import CapitalAPIClient
    from clients.sqlite_api import SQLiteAPIClient

    sqlite_client = SQLiteAPIClient(db_path=db_path)
    sqlite_api.DB_PATH = db_path   # constructor resets the global

    logger.info("🔐 Authenticating with Capital.com...")
    capital = CapitalAPIClient(environment=environment)
    capital.create_session()

    logger.info(f"📥 Fetching transactions (windows of {WINDOW_HOURS}h)...")
    transactions = fetch_transactions(capital, start, end)
    logger.info(f"\n✅ {len(transactions)} TRADE transactions\n")

    if args.instrument:
        want = args.instrument.upper()
        transactions = [t for t in transactions
                        if (t.get('instrumentName') or '').upper() == want]
        logger.info(f"🎯 Filtered to {want}: {len(transactions)} transactions\n")

    positions = load_open_positions(sqlite_client)
    logger.info(f"🔗 {len(positions)} position rows available to join against\n")

    trades = [build_trade(t, positions.get(t['dealId']), args.bot_id)
              for t in transactions]

    matched = sum(1 for t in trades if not t['partial'])
    by_bot = defaultdict(lambda: {'n': 0, 'pnl': 0.0})
    for t in trades:
        b = by_bot[t['bot_id'] or 'unknown']
        b['n'] += 1
        b['pnl'] += t['pnl']

    logger.info(f"📊 {len(trades)} trades  ({matched} joined to a position row, "
                f"{len(trades) - matched} P&L-only)\n")
    logger.info(f"   {'bot_id':<20} {'trades':>7} {'total P&L':>12}")
    logger.info(f"   {'-'*20} {'-'*7} {'-'*12}")
    for bot, v in sorted(by_bot.items()):
        logger.info(f"   {bot:<20} {v['n']:>7} {v['pnl']:>+12.2f}")
    logger.info("")

    if args.dry_run:
        logger.info("Sample records:")
        for t in trades[:5]:
            logger.info("  " + json.dumps(t))
        logger.info("\n🔍 Dry run — nothing written.")
        return 0

    written = 0
    for t in trades:
        if sqlite_client.save_trade('trade_history', t['deal_id'], t):
            written += 1

    logger.info(f"✅ Wrote {written}/{len(trades)} records to trade_history")
    logger.info("   UI → Performance → Live should now show history.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
