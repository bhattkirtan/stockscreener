# Prompt 8 research — 2026-10-23 (CLAUDE.md gotcha 61)

Results are in `intraday_results.txt`, `daily_results.txt` and `ibs_robust.txt`. 54 trials in total.

Second pass (gotcha 62): IBS as an overlay on a long index position. Variants and tests were
written in `overlay_prereg.md` before the run; results in `overlay_results.txt`. 12 trials → **66 total**.

## Re-running

The scripts read `snap.db` and `daily.pkl` from this directory. Both are gitignored, so rebuild them first.

**`snap.db`**: a frozen copy of the GOLD and US100 M5 bars from the live volume. Copy the `candles`
rows `WHERE epic IN ('GOLD','US100') AND timeframe='M5'` from
`/var/lib/docker/volumes/stockscreener_trading_data/_data/trading.db` (open it read-only) into a new
DB that has the same `candles` schema as `clients/sqlite_api.py`.

**`daily.pkl`**: `dict[epic] -> DataFrame(o, h, l, c, ca)` of DAY bid bars, with `ca` = ask close.
Fetch `/api/v1/prices/{epic}?resolution=DAY&max=1000`, then page backwards with
`to = first snapshotTimeUTC - 1s` until a page returns fewer than 1000 rows.

Then:

```bash
cd research/prompt8
cat jobs.txt | xargs -P4 -I{} sh -c 'python3 -I bt.py {}'   # 22 intraday variants
python3 -I bt.py --instrument GOLD  --bars 188534 --results-dir research/prompt8/res --run-id G_base
python3 -I bt.py --instrument US100 --bars 203260 --results-dir research/prompt8/res --run-id U_base
python3 -I ev.py                    # score intraday runs
python3 -I daily_fam.py 34          # daily families; arg = trials from elsewhere, for the DSR
python3 -I ibs_robust.py
python3 -I ibs_overlay.py           # needs daily_rows.pkl from daily_fam.py
```

`bt.py` turns off `_ensure_candles_in_db`, so a run never fetches. A fetch would add tail bars, and
`--bars N` would then shift its window between runs (gotcha 58).
