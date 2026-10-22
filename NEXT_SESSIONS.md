# Handoff — ready-to-paste prompts for new sessions

Rewritten 2026-10-22, after the session that worked streams 1–6 of the previous
version of this file. Each prompt below is self-contained: paste one as the
first message of a fresh session. They assume the agent reads `CLAUDE.md` first.

**Read before starting any of these:**

- `CLAUDE.md` gotchas **22–38** are from the 2026-10-21 session; **40–48** are
  from 2026-10-22. 22, 29, 31, 40, 41, 42 describe bugs that are now **fixed**;
  24, 25, 26, 36, 48 describe hazards that are **still open**.
- **Standing constraint:** the three live bots (GOLD, ETHUSD, US100) run on a
  **demo** account in `stockscreener-trading-bot-1`. Do not change live config,
  size, or bot state without explicit instruction. Research and tests are free;
  anything that reaches the broker is not.
- Two uncommitted config changes are **deliberately held back**:
  `GOLD.yaml` / `ETHUSD.yaml` `position_size`. Deploying GOLD's takes risk per
  trade from $7.50 to $150 (20×) on a strategy with no demonstrated edge
  (gotcha 26). Leave them unless told otherwise.
- Test commands:
  `cd trading-bot-skills && python3 -m pytest` → **768 passing, 0 failing**
  `python3 -m pytest --cov` → adds the 64% coverage floor (~160s vs ~40s;
  measured 68.8%)
  `python3 -m pytest tests/ -q` from repo root (research tools)
  **Never pass `--cov=<dotted.module.path>`** — it reloads numpy and fails ~47
  unrelated tests. Gotcha 43.

---

## What the 2026-10-22 session closed

Do not redo these; the measurements are in `CLAUDE.md`.

| old prompt | outcome |
|---|---|
| 1. `orchestrator/main.py` coverage | **done** — 13% → 95% (gotcha 44) |
| 1. `trading_orchestrator.py` coverage | **done** — 15% → 100%; surfaced 4 live-path bugs, **all fixed** (gotchas 49, 50). Not deployed |
| 2. `analysis_skill` tick-exit / MTF | **done** — 55% → 85% (gotchas 44, 45) |
| 3. `execution_skill` / websocket + CI gate | **done** — 45% → 93%, 41% → 98%; `pytest.ini` + `.coveragerc`, `fail_under = 64` |
| 4. the 20 "`test_pip_config`" failures | **done** — they were 20 across 3 files, 3 causes, one a real production bug (gotcha 40) |
| 5. the two gate-path divergences + candle dedup | **done** — one gate chain, dedup fixed (gotchas 41, 42); also found `process_candle` has no production callers, so the old dedup tests tested a dead path. The GOLD trade-count divergence itself is **still open** — see prompt 2 below |
| 6. breadth expansion | **done, and it FAILED** — breadth rose 4.9 → 14.1 and both gross and net Sharpe fell; bonds/rates cannot help (gotchas 46, 47) |

---

## 1. `trading_orchestrator.py` coverage — **DONE 2026-10-22**

> 15% → **100%**. New suite `tests/unit/test_live_orchestrator_loop.py` (83
> tests, fake-skill harness, no network). Secondary target also done:
> `core/sl_tp_engine.py` 44% → **100%** (`test_sl_tp_engine.py`, 61 tests).
> Suite 768 → **912 passing, 0 failing**; total 69.02% → **71.69%**;
> `.coveragerc` floor 64 → **69**.
>
> **Four live-path bugs surfaced and all fixed — see gotcha 49.** The one that
> matters most was not the one first reported: `on_position_closed` cleared the
> open-position flags unconditionally, so a close event for a deal that is no
> longer the tracked one wiped the *current* position's flags. The reverse path
> guarantees this, because **every reverse close is booked twice** — once by
> the orchestrator and again ~10s later by `_poll_positions` (its `processed`
> set is a closure local to the poll loop). Also fixed: the invented
> `pnl=0.0`/`entry_price=0.0` (gotcha 22's regression in miniature, verified
> against the real `RiskSkill`), booking a refused close before checking the
> broker result, and the error handler that defeated itself on a None context.
> Plus the unguarded Supertrend stop (gotcha 50).
>
> **Regression-checked:** GOLD 2y = 493 trades / WR 21.70% / PF 1.0501 vs
> gotcha 41's 492 / 21.54% / 1.046; the +1 trade is the DB growing 188,260 →
> 188,435 bars. `run_skills_backtest.py` never instantiates
> `TradingOrchestrator`, so these are live-path-only changes.
>
> ⚠️ **NOT deployed.** Same constraint as gotcha 38: deploying needs
> `docker compose build trading-bot`, which bakes in every uncommitted change
> in that tree.

---

## 2. The GOLD live/backtest trade-count divergence — four hypotheses rejected, one left

> Read `CLAUDE.md` gotcha 36 (the rejected hypotheses) and 41, then 48.
>
> Live window 2026-08-01..10-21: backtest takes **61** trades at WR 21.31% /
> PF 1.046; live took **93** at WR 13.98% / PF 0.646. Cause still unknown.
>
> **Already tested and REJECTED — do not re-test:**
> 1. broken SL/TP cooldowns — `sl_cooldown_minutes` 0 / 60 / 30 all give exactly
>    61 trades, because the gate only blocks *same-direction* re-entry and
>    `edge_detection` means the next signal is usually the opposite one;
> 2. the daily 21:00 restart resetting `last_signal_state` — the 31 excess live
>    trades are spread across hours 8–20, and hour 21 has **zero** live entries;
> 3. Supertrend path-dependence on the 300-bar live buffer — **100.00%**
>    direction agreement over 1,100 bars, 85 vs 85 flips;
> 4. *(new)* startup-flip suppression — it would make live take **fewer** trades,
>    and live takes more. Also now applied by both paths (gotcha 41).
>
> **The remaining untested lead:** the live bot builds candles from the
> WebSocket tick stream (`_handle_ohlc`, ASK/OFR only) while the DB bars come
> from the REST price endpoint. Bar boundaries, and which bars exist at all, may
> differ. Compare live candle timestamps against DB bars for the same window —
> count bars per day on each side first, before comparing OHLC values.
>
> **Note gotcha 48 before you start:** GOLD's repaired bars are in the HOST
> stray `/data/trading.db` (188,260), not the live volume (163,867). Pin
> `DB_PATH` deliberately and say which DB a number came from.

---

## 3. Where to take the strategy research next — breadth is closed off

> Read `CLAUDE.md` gotchas 32, 34, 37, 46 and 47 **before proposing anything**.
> Three different levers have now been measured and failed, and the failures are
> informative:
>
> - **Parameter tuning** (gotcha 34): ~20 configs, 3 instruments. The one GOLD
>   winner did not transfer — US100 0.973 → 0.948, ETHUSD 0.858 → 0.829.
> - **Breadth** (gotcha 46): effective breadth 4.9 → 14.1 as designed, and
>   *gross* Sharpe fell 0.37 → −0.05. Grinold's `IR ≈ IC × √breadth` assumes
>   uniform IC; measured IC is concentrated in **9 of 48** names with **21
>   actively negative**. Adding bets added noise.
> - **Bonds / rates** (gotcha 47): 7 instruments exist in total, 2 pass the
>   friction screen, and both have under 3 years of weekly history.
>
> What the evidence actually points at, in order:
> 1. **Instrument selection on measured edge, not on friction.** The current
>    screen ranks by spread/range and takes the cheapest — but the 9 names with
>    edge are not the 9 cheapest. Selecting on realised per-instrument Sharpe is
>    in-sample fitting, so it needs the IS/OOS + cross-instrument transfer bar
>    from gotcha 34 and a trial-count-corrected DSR.
> 2. **Vol target.** Half-Kelly implies **15%**, the config runs 20% — the one
>    change the measurements already justify, and it only affects sizing.
> 3. **A second, uncorrelated signal family.** Breadth in *signals* was never
>    tested; breadth in *instruments* has now been ruled out. One signal family
>    at breadth ≈ 1 is the structural problem gotcha 37 describes.
>
> **Non-negotiable in any write-up:** no Sharpe without its DSR and the
> buy-and-hold benchmark beside it. Buy-and-hold currently beats the trend
> overlay at **every** breadth level (0.34 → 0.52), and the gap *widens* as the
> universe grows. Preserve the known limitations rather than dropping them: the
> universe is screened on *today's* spread snapshot then backtested over 21–40
> years (selection bias), these are CFD proxies not futures, spreads are assumed
> constant, and the weekly sample is closes only.

---

## 4. Deferred operational decisions (need a human call)

These are **not** tasks to start unprompted. Raise them, get a decision, then act.

- **Deploy the 2026-10-21 live fixes.** The close-detection / realised-P&L /
  bar-sync fixes (gotcha 38) and now the gate unification (41), dedup fix (42)
  and alerting fix (40) are all **host-side only**. The live bot runs baked-in
  code. `docker compose build trading-bot && docker compose up -d trading-bot`
  — which per gotcha 10 also bakes in every other uncommitted change in that
  tree, including the held-back `position_size`. Check `git status` first.
- **Repair Aug–Oct `trade_history`.** 365 rows carry `pnl=0.0 /
  exit_reason=SIGNAL` from the gotcha-22 bug. `backfill_trade_history.py
  --days 120` rewrites them from `/history/transactions`, the authoritative
  source. The live path is fixed going forward; historical rows will not
  self-heal.
- **Rebuild `backtest-runner`.** Baked code and config are months stale: no
  `reverse_signal_exit` support at all, US100 on ST(7, 2.0) instead of
  ST(14, 1.5), ETHUSD on SL 45/TP 170 instead of 25/125. Every UI-triggered
  backtest tests a different strategy than the one deployed — it produced
  `+$733,912` on $10k from a reverse-signal scalper. Gotcha 25.
- **Reconcile the two GOLD bar sets.** Gotcha 48: the host stray DB has 24k more
  GOLD bars than the live volume, so container-run backtests still see starved
  GOLD data. Decide which is canonical, then pin `DB_PATH` (gotcha 24).
- **The GOLD/ETHUSD `position_size` changes.** Still uncommitted and undeployed,
  by design. Gotcha 26.
- **Whether to keep running the Supertrend bots at all.** Measured live
  Aug 1–Oct 21: **−€2,004** (−€1,664 of it US100, plus −€184 swap). Every
  instrument sits at or below its breakeven win rate. This was raised before and
  the instruction was to improve rather than stop. Since then three improvement
  levers have been measured and all three failed (see prompt 3), so the question
  is now better posed than it was.
