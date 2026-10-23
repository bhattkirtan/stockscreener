# IBS overlay — pre-registration (written 2026-10-23, before any overlay run)

Question: does IBS<0.2 add value as an **overlay on a long index position**, not standalone?
(Follows gotcha 61's closing note. IBS threshold fixed at 0.2 — neighbours 0.15–0.30 were already
checked in `ibs_robust.txt` and are not re-tuned here.)

## Data and mechanics (unchanged from `daily_fam.py`)
- `daily.pkl` DAY bid bars, `daily_fam.load()` (weekdays only, from 2000-01-01 for indices).
- Signal `s_k = IBS_k < 0.2`, decided at close k, held open(k+1) → open(k+2) (`daily_fam.run` timing).
- Price return per bar: `bh = o(k+1)/o(k) − 1`.

## Variants (exposure `w = b + k·s`)
| id | base b | extra k | note |
|---|---|---|---|
| O1 | 1.0 | 0.5 | 1.5× on IBS days |
| O2 | 1.0 | 1.0 | 2× on IBS days |
| O3 | 0.8 | 0.8 | ~exposure-neutral (mean w ≈ 0.96) |
| O4 | 1.0 | 1.0 × (c > SMA200) | extra leg only in an uptrend |

No other variants will be run. Each is run on US100, US500, DE40 → **12 trials. Running total 54 + 12 = 66.**

## Costs (same as `daily_fam.py`)
- Entry: 1.5 × (ask close − bid close) / open, charged on every **increase** in exposure (`max(Δw, 0)`).
- Funding: (fed funds by year + 2.5%)/365 × calendar days held, on **exposure above 1.0** only
  (`max(w − 1, 0)`). The unlevered 1.0 base is treated as `daily_fam` treats its B&H benchmark — no
  funding. Cash below 1.0 earns nothing. The same rules apply to the benchmark.
- Benchmark: vol-matched B&H = `λ·bh`, `λ = std(overlay)/std(bh)` on the evaluation window, with the
  same funding on `max(λ − 1, 0)`.

## Tests (a candidate must pass all four)
1. **Halves PF**: the *incremental* leg (overlay return − b·bh, i.e. the extra exposure net of its own
   costs and funding), grouped into IBS episodes as trades; PF > 1.0 in both halves of the US100
   2000→2026 window.
2. **Transfer**: on **both** US500 and DE40, test 1 passes **and** full-sample overlay SR > vol-matched B&H SR.
3. **DSR ≥ 0.95** on the **active return** (overlay − vol-matched B&H), US100 full sample, deflated over
   66 trials; trial-SR variance from the 20 `daily_fam` rows + the 12 overlay active SRs. (DSR of the raw
   overlay return is reported for information only — it mostly certifies equity beta.)
4. **2010–2026 Sharpe**: overlay SR > vol-matched B&H SR (λ refit on 2010-01-01 → end) on US100.
