#!/usr/bin/env python3
"""
Dynamic universe selection for a systematic portfolio.

Breadth is the multiplier on a thin edge (Grinold: IR ~ IC * sqrt(breadth)), but
breadth only counts if the bets are (a) cheap enough to clear the friction floor
and (b) genuinely independent. This picks the universe on exactly those two
criteria instead of hardcoding a list.

Stage 1 - discover: recursively walk /marketnavigation to enumerate every
          tradeable epic the account can see.
Stage 2 - friction screen: spread / daily-range from the live snapshot. This is
          the cost hurdle that killed the M5 strategy, applied up front. An
          instrument whose spread is a large fraction of its daily range cannot
          support a timing strategy at any horizon.
Stage 3 - diversify: pull daily history for the survivors and greedily select a
          low-correlation subset, capped per asset class so the result isn't six
          flavours of the same bet.

Output is a JSON universe file consumable by trend_portfolio.py.

  python3 universe.py --discover            # stage 1+2, writes /tmp/universe_screen.json
  python3 universe.py --select --max 15     # stage 3, writes universe.json
"""
import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trading-bot-skills'))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
from clients.capital_api import CapitalAPIClient  # noqa: E402

SCREEN_FILE = '/tmp/universe_screen.json'
HIST_FILE = '/tmp/universe_hist.pkl'

# Single-name equity is a different premium (and there are hundreds) — exclude.
EXCLUDE_TYPES = {'SHARES'}

# Max instruments to keep per asset class, so the universe stays diversified
# rather than filling up with 20 correlated crypto pairs.
CLASS_CAP = 3


def discover(client, max_depth=4):
    """Recursively walk the market navigation tree."""
    seen_nodes, markets = set(), {}

    def walk(node_id, path, depth):
        if depth > max_depth or node_id in seen_nodes:
            return
        seen_nodes.add(node_id)
        url = '/api/v1/marketnavigation' + (f'/{node_id}' if node_id else '')
        try:
            j = client._request('GET', url).json()
        except Exception as e:
            print(f"   ! {node_id}: {str(e)[:60]}", file=sys.stderr)
            return
        for m in (j.get('markets') or []):
            epic = m.get('epic')
            if epic and epic not in markets:
                m['_path'] = path
                markets[epic] = m
        for n in (j.get('nodes') or []):
            walk(n.get('id'), path + [n.get('name') or n.get('id')], depth + 1)
        time.sleep(0.05)   # be gentle with the API

    walk('', [], 0)
    return list(markets.values())


def friction_screen(markets, max_friction=0.08, max_range_pct=8.0):
    """
    Keep instruments whose spread is small relative to their daily range.

    friction = spread / (high - low).  A 2.0pt spread on a 460pt daily range is
    0.4%; a 2.0pt spread on a 20pt range is 10% and hopeless at any horizon.
    """
    rows = []
    for m in markets:
        if m.get('marketStatus') != 'TRADEABLE':
            continue
        if m.get('instrumentType') in EXCLUDE_TYPES:
            continue
        if not m.get('streamingPricesAvailable'):
            continue
        bid, offer = m.get('bid'), m.get('offer')
        hi, lo = m.get('high'), m.get('low')
        if not all(isinstance(v, (int, float)) for v in (bid, offer, hi, lo)):
            continue
        spread = offer - bid
        rng = hi - lo
        mid = (offer + bid) / 2
        if spread <= 0 or rng <= 0 or mid <= 0:
            continue
        rows.append(dict(
            epic=m['epic'],
            name=(m.get('instrumentName') or '')[:38],
            itype=m.get('instrumentType') or '?',
            mid=round(mid, 6),
            spread=round(spread, 6),
            daily_range=round(rng, 6),
            friction=round(spread / rng, 4),
            range_pct=round(rng / mid * 100, 3),
            tick=m.get('tickSize'),
        ))
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Need real movement as well as a tight spread: a market that barely moves
    # has nothing to harvest no matter how cheap it is.
    #
    # The upper range_pct bound matters as much as the lower one. Without it the
    # screen admits micro-cap crypto with 25%+ daily ranges, which pass on
    # spread/range purely because they are wildly volatile — they are illiquid,
    # gap-prone, and their vol estimate is useless for position sizing.
    df = df[(df.friction <= max_friction)
            & (df.range_pct >= 0.25)
            & (df.range_pct <= max_range_pct)]
    return df.sort_values('friction').reset_index(drop=True)


def fetch_daily(client, epic, bars=500):
    """Daily closes via the price endpoint (resolution=DAY)."""
    try:
        j = client._request('GET', f'/api/v1/prices/{epic}',
                            params={'resolution': 'DAY', 'max': bars}).json()
    except Exception:
        return None
    rows = []
    for p in j.get('prices', []):
        ts = (p.get('snapshotTimeUTC') or p.get('snapshotTime') or '')[:19].replace('T', ' ')
        c = p.get('closePrice') or {}
        px = c.get('bid') or c.get('ask')
        if ts and px:
            rows.append((ts, float(px)))
    if len(rows) < 120:
        return None
    s = pd.Series(dict(rows))
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def select(screen_df, client, max_n=15, max_corr=0.70, min_hist=250):
    """Greedy low-correlation selection, capped per asset class."""
    cached = {}
    if os.path.exists(HIST_FILE):
        cached = {c: s for c, s in pd.read_pickle(HIST_FILE).items()}
        print(f"reusing cached daily history for {len(cached)} instruments")
    print(f"fetching daily history for {len(screen_df)} candidates...")
    series = {}
    for i, row in screen_df.iterrows():
        s = cached.get(row.epic)
        if s is None:
            s = fetch_daily(client, row.epic)
        if s is not None and len(s) >= min_hist:
            series[row.epic] = s
        if (i + 1) % 20 == 0:
            print(f"   {i+1}/{len(screen_df)} ({len(series)} usable)")
        if row.epic not in cached:
            time.sleep(0.08)
    if not series:
        raise SystemExit("no instrument had enough daily history")
    px = pd.DataFrame(series).ffill()
    rets = px.pct_change(fill_method=None)
    corr = rets.corr()
    pd.to_pickle(px, HIST_FILE)
    print(f"usable: {len(series)} instruments, {len(px)} daily bars\n")

    meta = screen_df.set_index('epic')
    # Rank by friction (cheapest first) among those with history
    order = [e for e in screen_df.epic if e in series]
    chosen, class_count = [], {}
    for e in order:
        itype = meta.loc[e, 'itype']
        if class_count.get(itype, 0) >= CLASS_CAP:
            continue
        if any(abs(corr.loc[e, c]) > max_corr for c in chosen):
            continue
        chosen.append(e)
        class_count[itype] = class_count.get(itype, 0) + 1
        if len(chosen) >= max_n:
            break

    sub = corr.loc[chosen, chosen]
    avg_corr = (sub.values[np.triu_indices(len(chosen), 1)]).mean() if len(chosen) > 1 else 0.0
    # Effective breadth: how many independent bets this really is
    eff = len(chosen) / (1 + (len(chosen) - 1) * max(avg_corr, 0))
    return chosen, corr, avg_corr, eff, meta


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--discover', action='store_true')
    ap.add_argument('--select', action='store_true')
    ap.add_argument('--max', type=int, default=15)
    ap.add_argument('--max-friction', type=float, default=0.08)
    ap.add_argument('--max-range-pct', type=float, default=8.0,
                    help='exclude instruments whose daily range exceeds this %% of price')
    ap.add_argument('--max-corr', type=float, default=0.70)
    ap.add_argument('--out', default='universe.json')
    args = ap.parse_args()

    client = CapitalAPIClient(environment=os.getenv('CAPITAL_ENVIRONMENT', 'demo'))
    client.create_session()

    if args.discover or not os.path.exists(SCREEN_FILE):
        print("discovering markets...")
        markets = discover(client)
        print(f"found {len(markets)} unique epics")
        df = friction_screen(markets, args.max_friction, args.max_range_pct)
        df.to_json(SCREEN_FILE, orient='records')
        print(f"\n{len(df)} passed the friction screen (spread/range <= {args.max_friction})")
        pd.set_option('display.width', 220)
        print("\ncheapest 25 by friction:")
        print(df.head(25).to_string(index=False))
        print("\nby instrument type:")
        print(df.groupby('itype').agg(n=('epic', 'size'),
                                      median_friction=('friction', 'median')).to_string())

    if args.select:
        df = pd.read_json(SCREEN_FILE)
        chosen, corr, avg_corr, eff, meta = select(
            df, client, args.max, args.max_corr)
        pd.set_option('display.width', 220)
        print("SELECTED UNIVERSE:")
        print(meta.loc[chosen, ['name', 'itype', 'friction', 'range_pct']].to_string())
        print(f"\naverage pairwise correlation: {avg_corr:.3f}")
        print(f"effective breadth: {eff:.1f} independent bets from {len(chosen)} instruments")
        json.dump({'epics': chosen,
                   'avg_corr': round(float(avg_corr), 4),
                   'effective_breadth': round(float(eff), 2)},
                  open(args.out, 'w'), indent=1)
        print(f"\nwrote {args.out}")


if __name__ == '__main__':
    main()
