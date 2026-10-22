#!/usr/bin/env python3
"""
repair_zero_pnl.py — Resolve the zero-P&L trade_history rows left by gotcha 22.

Between 2026-08-01 (when StorageSkill._record_trade landed) and the 2026-10-21
deploy, get_activity() returned [] so every close was detected only by the 60s
REST reconcile, which called _handle_close(deal_id, 0.0, ''). That wrote
pnl = 0.0 and exit_reason = 'SIGNAL' on every row. The live path is fixed and
deployed; history does not self-heal.

Why not just re-run backfill_trade_history.py: that rebuilds EVERY field of
EVERY row in the window from the active_positions row (INSERT OR REPLACE keyed
on deal_id). Measured on 2026-10-22, a blind --days 120 run would rewrite all
2,582 already-correct rows to repair 381, downgrading 10 of them (it hardcodes
entry_time_estimated: True, which the gotcha-13 fix made untrue for rows written
after it). This script instead touches ONLY rows whose pnl is currently 0.0, and
changes only the P&L fields — every other field is preserved byte-for-byte.

exit_reason is deliberately NOT repaired: /history/transactions carries no exit
reason, and /history/activity is hard-capped at 24h (gotcha 12), so the real
SL/TP reason for an August close is no longer obtainable from the broker.

Usage:
    # ALWAYS set DB_PATH explicitly — a bare run on the host silently creates
    # and uses the 35MB stray DB instead of the live volume (gotcha 24).
    DB_PATH=/var/lib/docker/volumes/stockscreener_trading_data/_data/trading.db \
        python3 repair_zero_pnl.py --dry-run
    DB_PATH=/var/lib/.../trading.db python3 repair_zero_pnl.py
    # or from inside a container, where /data IS the volume:
    docker exec stockscreener-trading-bot-1 python3 /app/repair_zero_pnl.py --dry-run
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT.parent / '.env')
load_dotenv(PROJECT_ROOT / '.env')

from clients.capital_api import CapitalAPIClient
from backfill_trade_history import fetch_transactions

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s',
                    datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)


def load_zero_rows(db_path: str) -> list:
    """trade_history rows whose pnl is exactly 0.0 and not flagged unknown."""
    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    rows = con.execute(
        "SELECT doc_id, data FROM kv_store WHERE collection='trade_history'"
    ).fetchall()
    con.close()

    out = []
    for doc_id, raw in rows:
        try:
            trade = json.loads(raw)
        except (ValueError, TypeError):
            logger.warning(f"  skipping unparseable row {doc_id}")
            continue
        # pnl_unknown rows were written deliberately as "we don't know" by the
        # post-fix path; they are not the gotcha-22 zeros and are left alone.
        if trade.get('pnl_unknown'):
            continue
        if trade.get('pnl') in (0, 0.0, '0', '0.0'):
            out.append((doc_id, trade))
    return out


def repair(trade: dict, txn: dict) -> tuple:
    """Return (updated_trade, kind). Only P&L fields are touched."""
    try:
        pnl = round(float(txn.get('size') or 0.0), 2)
    except (TypeError, ValueError):
        return None, 'unparseable-pnl'

    updated = dict(trade)          # preserve every existing field
    updated['pnl'] = pnl
    updated['pnl_estimated'] = False        # broker figure — authoritative
    updated['pnl_repaired'] = True
    updated['pnl_repaired_at'] = datetime.utcnow().isoformat()
    if txn.get('currency'):
        updated['currency'] = txn['currency']

    # pnl_pct needs the entry notional; many of these rows have it, some don't.
    entry = float(trade.get('entry_price') or 0.0)
    size = float(trade.get('size') or 0.0)
    margin = entry * size
    if margin:
        updated['pnl_pct'] = round(pnl / margin * 100, 4)

    # The old path recorded exit_price 0.0 (the `if entry and close_level and
    # size` guard failed on close_level=0.0). With entry, size and a real P&L
    # the exit price is recoverable — same arithmetic backfill_trade_history
    # uses, and flagged the same way.
    side = (trade.get('direction') or '').upper()
    if not float(trade.get('exit_price') or 0.0) and entry and size and side in ('BUY', 'SELL'):
        updated['exit_price'] = round(
            entry + (pnl / size) * (1.0 if side == 'BUY' else -1.0), 5)
        updated['exit_price_estimated'] = True

    return updated, ('confirmed-breakeven' if pnl == 0.0 else 'resolved')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dry-run', action='store_true',
                        help='Report what would change; write nothing.')
    parser.add_argument('--db', default=os.getenv('DB_PATH', '/data/trading.db'),
                        help='SQLite path (default: $DB_PATH or /data/trading.db)')
    parser.add_argument('--env', default='demo', choices=['demo', 'live'])
    parser.add_argument('--pad-days', type=int, default=2,
                        help='Widen the transaction window this many days each side.')
    args = parser.parse_args()

    if not os.path.exists(args.db):
        logger.error(f"❌ No such DB: {args.db}")
        return 1
    logger.info(f"📂 DB: {args.db}")

    zeros = load_zero_rows(args.db)
    if not zeros:
        logger.info("✅ No zero-P&L rows — nothing to repair.")
        return 0

    times = sorted(t.get('exit_time') or t.get('logged_at') or ''
                   for _, t in zeros if (t.get('exit_time') or t.get('logged_at')))
    logger.info(f"🔍 {len(zeros)} zero-P&L rows, {times[0][:10]} → {times[-1][:10]}")

    start = datetime.strptime(times[0][:10], '%Y-%m-%d') - timedelta(days=args.pad_days)
    end = datetime.utcnow()
    logger.info(f"📡 Fetching transactions {start:%Y-%m-%d} → {end:%Y-%m-%d}"
                f" (12h windows)\n")

    client = CapitalAPIClient(environment=args.env)
    client.create_session()
    txns = {t['dealId']: t for t in fetch_transactions(client, start, end) if t.get('dealId')}
    logger.info(f"\n📊 {len(txns)} TRADE transactions available to join against\n")

    updates, kinds, unmatched = [], {}, []
    for doc_id, trade in zeros:
        txn = txns.get(trade.get('deal_id') or doc_id)
        if not txn:
            unmatched.append((doc_id, trade))
            continue
        updated, kind = repair(trade, txn)
        if updated is None:
            unmatched.append((doc_id, trade))
            continue
        updates.append((doc_id, updated))
        kinds[kind] = kinds.get(kind, 0) + 1

    total = sum(u['pnl'] for _, u in updates)
    logger.info(f"✅ matched   : {len(updates)}")
    for k, n in sorted(kinds.items()):
        logger.info(f"     {k:<22} {n}")
    logger.info(f"❔ unmatched : {len(unmatched)}  (no TRADE row — left untouched)")
    logger.info(f"💰 net P&L these rows actually carried: {total:+.2f}\n")

    by_bot = {}
    for _, u in updates:
        b = by_bot.setdefault(u.get('bot_id') or 'unknown', {'n': 0, 'pnl': 0.0})
        b['n'] += 1
        b['pnl'] += u['pnl']
    logger.info(f"   {'bot_id':<20} {'rows':>6} {'P&L':>12}")
    logger.info(f"   {'-'*20} {'-'*6} {'-'*12}")
    for bot, v in sorted(by_bot.items()):
        logger.info(f"   {bot:<20} {v['n']:>6} {v['pnl']:>+12.2f}")
    logger.info("")

    if args.dry_run:
        logger.info("Sample repairs (before → after):")
        for doc_id, u in updates[:5]:
            before = dict(zeros[[d for d, _ in zeros].index(doc_id)][1])
            logger.info(f"  {doc_id[:20]}… {before.get('epic'):<7} "
                        f"pnl {before.get('pnl')} → {u['pnl']:+.2f}   "
                        f"exit {before.get('exit_price')} → {u.get('exit_price')}")
        logger.info("\n🔍 Dry run — nothing written.")
        return 0

    con = sqlite3.connect(args.db, timeout=30)
    written = 0
    try:
        with con:
            for doc_id, updated in updates:
                con.execute(
                    "UPDATE kv_store SET data=?, updated_at=? "
                    "WHERE collection='trade_history' AND doc_id=?",
                    (json.dumps(updated), datetime.utcnow().isoformat(), doc_id))
                written += 1
    finally:
        con.close()

    logger.info(f"✅ Repaired {written}/{len(zeros)} rows in trade_history")
    return 0


if __name__ == '__main__':
    sys.exit(main())
