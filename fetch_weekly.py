#!/usr/bin/env python3
"""
Fetch long weekly history for the friction-screened universe.

A single DAY request returns at most 1000 bars (~3.2 years), and so does WEEK —
which reaches back to 2007. (Paging DAY backwards with `to` reaches the 1970s;
see CLAUDE.md gotcha 61.) That buys the one thing
the daily sample could not provide: the 2008 GFC, 2011, 2015, 2020 and 2022.
A weekly trend horizon is also where the premium is documented to survive
(the 50-day/10-week signal retained Sharpe 0.40 post-2009, vs 0.12 for 5-day).

Writes /tmp/weekly_hist.pkl (wide DataFrame of weekly closes).
"""
import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trading-bot-skills'))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
from clients.capital_api import CapitalAPIClient  # noqa: E402

OUT = '/tmp/weekly_hist.pkl'
SCREEN = '/tmp/universe_screen.json'


def fetch_weekly(client, epic, bars=1000):
    try:
        j = client._request('GET', f'/api/v1/prices/{epic}',
                            params={'resolution': 'WEEK', 'max': bars}).json()
    except Exception:
        return None
    rows = []
    for p in j.get('prices', []):
        ts = (p.get('snapshotTimeUTC') or p.get('snapshotTime') or '')[:19].replace('T', ' ')
        c = p.get('closePrice') or {}
        px = c.get('bid') or c.get('ask')
        if ts and px:
            rows.append((ts, float(px)))
    if len(rows) < 100:
        return None
    s = pd.Series(dict(rows))
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def main():
    min_years = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
    screen = pd.read_json(SCREEN)
    epics = list(screen.epic)
    print(f"fetching WEEK history for {len(epics)} screened epics "
          f"(keeping >= {min_years:g}y)...")

    client = CapitalAPIClient(environment=os.getenv('CAPITAL_ENVIRONMENT', 'demo'))
    client.create_session()

    series, skipped = {}, 0
    for i, e in enumerate(epics, 1):
        s = fetch_weekly(client, e)
        if s is not None and (s.index[-1] - s.index[0]).days / 365.25 >= min_years:
            series[e] = s
        else:
            skipped += 1
        if i % 25 == 0:
            print(f"   {i}/{len(epics)}  kept={len(series)} skipped={skipped}")
        time.sleep(0.08)

    if not series:
        raise SystemExit("nothing met the history requirement")
    px = pd.DataFrame(series).sort_index()
    pd.to_pickle(px, OUT)
    span = (px.index[-1] - px.index[0]).days / 365.25
    print(f"\nkept {len(series)} epics, {len(px)} weekly bars, "
          f"{px.index[0].date()} .. {px.index[-1].date()} ({span:.1f} years)")
    print(f"wrote {OUT}")
    cov = px.notna().sum().sort_values(ascending=False)
    print("\nlongest histories:")
    print(cov.head(20).to_string())


if __name__ == '__main__':
    main()
