# Items 2 + 3 — pre-registration (written 2026-10-23, before any selection run)

Prompt 8 item 2: **select instruments on measured edge rather than friction**, without the in-sample
fit gotcha 46 warned about. Item 3: **vol target 20% → 15%**. Both run on the weekly EWMAC trend
portfolio (`trend_portfolio.py --weekly`, gotcha 46). Running trial count before this: **66**.

## Rig (unchanged from `trend_portfolio.py`)
- Weekly closes `weekly_cache/weekly_hist.pkl`, spreads `weekly_cache/universe_screen.json`: byte
  copies of the `/tmp` files gotcha 46 used (sha256 in the README). `trend_portfolio.build()` unchanged:
  EWMAC speeds (2,8)(4,16)(8,32)(16,64) weeks, vol target 20%, $10k, leverage cap 3, spread on
  turnover, `ANNUAL_DAYS = 52`.
- The baseline (`--weekly`, 13 friction-selected names) reproduces gotcha 46 exactly: gross SR 0.37,
  net 0.30, halves 0.18 / 0.38, vol-targeted B&H 0.34.

## Item 2 — walk-forward selection
- **Pool:** every screened epic with ≥ 500 weekly closes (the `load_weekly` history rule, with no class
  cap and no correlation cap): 100 names.
- **Folds, split at 2016-01-01:**
  - A: select on everything before 2016-01-01, test on 2016-01-01 → end.
  - B: select on 2016-01-01 → end, test on 2005-05-09 → 2015-12-31 (the baseline's span before the split).
- **Selection statistic:** each name's net weekly Sharpe over the selection window, read from one
  `build()` of the whole pool. Per-instrument vol targeting makes this independent of pool size,
  except where the leverage cap binds.
- **Eligible:** ≥ 104 weeks with a non-zero position inside the selection window, and a price at the
  test-window start.
- **Rules (the only two that will be run):**
  - **S1:** keep names with selection-window net SR > 0.10 (gotcha 46's own "has edge" threshold).
  - **S2:** keep the top 13 by selection-window net SR (the baseline's breadth).
- The selected names get a **fresh `build()`** (risk budget re-split over n), scored on the test window only.
- 2 rules → **2 trials, running total 68.** The second fold is part of each rule's test, not a new trial.

### Pass bar (all four)
1. **Halves:** the test-window PF of the selected book is > 1.0 in **both** folds.
2. **Transfer (cross-sectional):** in **both** folds, the selected book's test-window SR beats the
   book of eligible names the rule *rejected*. That is the direct test of whether "selected on
   measured edge" carries out of sample.
3. **DSR ≥ 0.95** on fold A's test-window weekly net returns, n_trials = 68
   (`trend_portfolio.deflated_sharpe`, per-observation SR, with skew/kurtosis).
4. **Beat B&H:** fold A test-window SR > vol-targeted B&H on the same names over the same window.
   Fold A's test window is 2016+, so this is inside the "2010+ alone" bar.

Reported for context, not pass conditions: the friction-selected baseline-13 book and the
all-eligible book, scored on the same test windows.

## Item 3 — vol target 15%
Baseline 13 names at `--target-vol 0.15` vs `0.20`. This is a sizing change. Sharpe should be
unchanged except where the leverage cap binds, so it is **not counted as a trial** — **unless**
net SR moves by more than 0.02, in which case it counts as one (trial 69) and gets scored like one.
Report: SR, annual return, maxDD %, and the half-Kelly target the run implies.

## Addendum (written after the run — what went wrong with fold B, not a redesign)
Fold B came out **degenerate: 2 eligible names** (USCOCOA, SOYBEANOIL), none rejected. Cause: the
"price at the test-window start" rule. Most of the weekly series come from a 1000-bar WEEK request and
begin 2006–2011 (27 in 2007, 36 in 2011); only 3 of 100 start before 2006, so almost nothing has a
price on 2005-05-09. That is a flaw in this
pre-registration. It is **left as run**: re-designing fold B after seeing fold A would be a new trial
chosen with knowledge of the result. It does not change the verdict, because both rules already fail
tests 1 and 4 on fold A alone.
