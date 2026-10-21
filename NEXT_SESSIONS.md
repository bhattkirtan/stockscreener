# Handoff — ready-to-paste prompts for new sessions

Written 2026-10-21. Each prompt below is self-contained: paste one as the first
message of a fresh session. They assume the agent reads `CLAUDE.md` first —
every prompt references the gotcha numbers that carry the background, so none
of the investigation has to be re-derived.

**Read before starting any of these:**

- `CLAUDE.md` gotchas **22–38** are all from the 2026-10-21 session. 22, 29, 31
  describe bugs that are now **fixed**; 24, 25, 26, 36 describe hazards that are
  **still open**.
- Commits from that session: `153c557` (live close/P&L/bar-sync fixes),
  `b11ca33` (universe + sizing/validation layer), `22b1fe4` (21y weekly
  validation + leverage/DSR fixes), `c0534f4` (regression tests),
  `5807aa2` (live-POV test suites).
- **Standing constraint:** the three live bots (GOLD, ETHUSD, US100) run on a
  **demo** account in `stockscreener-trading-bot-1`. Do not change live config,
  size, or bot state without explicit instruction. Research and tests are free;
  anything that reaches the broker is not.
- Two uncommitted config changes are **deliberately held back**:
  `GOLD.yaml` / `ETHUSD.yaml` `position_size`. Deploying GOLD's takes risk per
  trade from $7.50 to $150 (20×) on a strategy with no demonstrated edge
  (gotcha 26). Leave them unless told otherwise.
- Test commands:
  `cd trading-bot-skills && python3 -m pytest tests/unit/ -q`  (401 passing)
  `python3 -m pytest tests/ -q`  from repo root (45 passing, research tools)
  The **20 `test_pip_config` failures are pre-existing** and unrelated —
  confirmed by stashing all session changes and re-running. See prompt 4.

---

## 1. Coverage: `orchestrator/main.py` (largest gap, worst track record)

> Read `CLAUDE.md` first, especially gotchas 22, 24 and 38.
>
> `orchestrator/main.py` is at **13% coverage (395 of 456 statements
> uncovered)** and contains the live close-detection path whose previous version
> silently zeroed P&L on 365 trades and disabled three risk breakers for about
> three months. `classify_activity()` and `derive_close_reason()` were already
> extracted and are tested in `tests/unit/test_live_close_and_risk.py`; the
> uncovered mass is the async machinery around them.
>
> Build a fake `CapitalAPIClient` (scripted `get_activity` / `get_open_positions`
> / `get_realised_pnl` / `update_position`) and drive `_poll_positions` directly
> with a cancellable task, asserting on the orchestrator calls it makes. Cover at
> minimum:
> - activity poll detects an open then a close, with the right exit reason
> - the 60s REST reconcile path detects a close the activity poll missed
> - **a close must never be recorded with `pnl=0.0` when P&L is unknown** —
>   `None` means unknown and is flagged `pnl_unknown`; a genuine broker `0.0`
>   is kept. This distinction is the regression; see gotcha 22.
> - the `processed` set prevents double-firing when the lookback window overlaps
> - startup seeding from REST open positions
> - a transient API exception does not kill the loop
> - `stop_manager.forget()` is called on close
>
> Target ≥85% on `main.py`. Run
> `python3 -m pytest tests/unit/ -q --cov=orchestrator.main --cov-report=term-missing`
> and report the before/after number. Do not change live behaviour — if you find
> a bug, report it rather than fixing it silently.

---

## 2. Coverage: `analysis_skill` tick exit and MTF branches

> Read `CLAUDE.md` gotchas 9 and 16 (tick exit has two modes; only the
> profit-trail mode is active) and 36.
>
> `skills/analysis/analysis_skill.py` is at **55% (283 statements uncovered)**.
> `tests/unit/test_live_analysis_path.py` covers warm-up, edge detection, SL/TP
> geometry and the ADX/MA100 filters. The uncovered mass is:
> - **`on_price_tick()` (line ~448) — live-only, never runs in backtest, and
>   currently has no tests at all.** This is the profit-trail exit: it shrinks
>   its check interval as unrealised profit grows (3min → 2min → 1min → every
>   tick). Drive it with a synthetic quote stream and cover each interval tier,
>   the trail-cross exit, and that `reverse_on_loss: false` really does suppress
>   the dangerous reverse-on-loss mode.
> - `on_m1_candle_closed()` — M1 exit validation, disabled in config but live code.
> - the H1 / 4h / daily Bollinger and daily-bias branches
>   (`require_h1_bb`, `require_mtf_bb`, `require_daily_bias`), all currently off
>   in config but all reachable.
>
> Note `on_candle_closed` recomputes indicators over the whole rolling buffer, so
> cost is O(bars × buffer) — keep fixtures small. Warm-up needs only ~35 bars
> with Supertrend-only config, ~120 with MA100 bias. Target ≥85%.

---

## 3. Coverage: `execution_skill`, `capital_websocket`, and a CI gate

> `skills/execution/execution_skill.py` is at **45%**,
> `clients/capital_websocket.py` at **41%**. For execution, build a fake REST
> client and cover order placement, the size resolution path (gotcha 26 —
> `config.get('position_size', 0.5)` at line 51 is why GOLD trades 0.5 contracts
> instead of 10), SL/TP attachment, rejection/failure handling, and the
> idempotency interaction. For the websocket, cover `connect`/`run`/`_keepalive`/
> `_handle_message` dispatch and reconnect behaviour with a fake socket;
> `_handle_ohlc` and `_handle_quote` are already covered in
> `tests/unit/test_live_signal_path.py`.
>
> Then add a coverage floor so this cannot regress: `--cov-fail-under` in a
> `pytest.ini` (the repo has none), set to whatever the suite actually achieves
> minus 2 points. Report the real number; do not set a target you did not meet.

---

## 4. Fix the 20 pre-existing `test_pip_config` failures

> `tests/unit/test_pip_config.py::TestCalculatePnl` has **20 failures that
> predate the 2026-10-21 session** (confirmed by stashing all changes and
> re-running). They cover `calculate_pnl` — per-contract P&L, cost scaling, and
> `pnl_pct` as net return on trade value.
>
> This matters more than "20 red tests": cost and P&L arithmetic is exactly where
> this session's worst errors hid. A 50× slippage typo (gotcha 31) made a US100
> backtest read −$134,629 instead of −$2,560, and cost drag turned out to be the
> whole reason the strategy loses (gotcha 32). Decide per test whether the test
> or the implementation is wrong, and say which — do not just make them green.

---

## 5. Resolve the two live/backtest divergences found by the live-POV tests

> Read `CLAUDE.md` gotcha 36, then `tests/unit/test_live_close_and_risk.py`
> classes `TestGatePathAsymmetry` and `TestStartupFlipSuppression`.
>
> Two divergences are **pinned by passing tests but not resolved**:
>
> 1. **`RiskSkill` has two gate implementations with different rules.**
>    `execute(context)` (used by `TradingOrchestrator`, i.e. live) gates on
>    open-position and startup-flip. `on_signal_generated(event)` (the EventBus
>    path, which `run_skills_backtest.py` drives) does **not**. Anything routed
>    through the event path can stack positions, and the event flow documented in
>    CLAUDE.md describes exactly that path.
> 2. **Startup-flip suppression is live-only** and re-arms on the daily 21:00 UTC
>    restart, so it fires once per bot per day with no backtest equivalent.
>
> Also open: candle dedup compares only against the **last** timestamp, so a
> reconnect replaying 3 bars produces 13 CANDLE_CLOSED events for 10 distinct
> bars and duplicates land in the analysis buffer
> (`test_reconnect_replay_produces_extra_events`).
>
> Decide the intended behaviour for each and make the two paths agree, keeping
> the pinning tests meaningful (update them to assert the new intent rather than
> deleting them). Then re-run the GOLD live-window comparison in gotcha 36 — live
> took 93 trades where the backtest takes 61, win rate 13.98% vs 21.31%, and the
> cause is still unknown. Three hypotheses were already **tested and rejected**:
> broken cooldowns, the 21:00 restart resetting signal state, and Supertrend
> rolling-buffer truncation (100.00% direction agreement, 85 vs 85 flips — do not
> re-test that one). The remaining untested lead is that the live bot builds
> candles from the WebSocket tick stream while the DB bars come from the REST
> price endpoint, so bar boundaries may differ. Compare live candle timestamps
> against DB bars for the same window.

---

## 6. Strategy: expand breadth and re-validate

> Read `CLAUDE.md` gotchas 32, 34, 37 and the commit message of `22b1fe4`.
>
> State of play: `universe.py` discovers 2,956 epics, friction-screens to 126,
> and selects a low-correlation subset. `trend_portfolio.py --weekly` runs a
> volatility-targeted EWMAC portfolio over **1,904 weekly bars (1986–2026,
> 40 years)** with a leverage cap, a buy-and-hold benchmark, deflated Sharpe and
> fractional-Kelly sizing. Current result on 13 epics:
>
> | | Sharpe | Annual | maxDD | IS | OOS |
> |---|---|---|---|---|---|
> | trend net | 0.30 | +2.7% | 42.8% | 0.18 | 0.38 |
> | buy & hold | 0.34 | +4.1% | 65.2% | 0.51 | 0.32 |
>
> Costs are 19.8% of gross (vs >100% on M5). **Deflated Sharpe 0.296 — below
> 0.95, so not significant.** Half-Kelly implies a 15% vol target, not the 20%
> used.
>
> The identified next lever is **breadth**, not tuning: effective breadth is 4.9
> and Grinold gives `IR ≈ IC × √breadth`, so breadth raises both expected IR and
> the statistical power to detect it. Lift it toward 15–20 by relaxing
> `CLASS_CAP` in `universe.py` and deliberately including the bonds and
> interest-rate instruments the screen found (the navigation tree has
> `bonds_group` and `interest_rates_group`). Re-run the weekly validation and
> report Sharpe, DSR, and the benchmark comparison.
>
> **Known limitations to preserve in any write-up, not quietly drop:** the
> universe is screened on *today's* spread snapshot then backtested over 21 years
> (selection bias — the instruments cheap and listed now are not what you would
> have picked in 2005); these are CFD proxies, not futures; spreads are assumed
> constant at today's level; weekly closes only. Do not report a Sharpe without
> its DSR and the buy-and-hold benchmark beside it — every single-number result
> in this project has been wrong so far.

---

## 7. Deferred operational decisions (need a human call)

These are **not** tasks to start unprompted. Raise them, get a decision, then act.

- **Repair Aug–Oct `trade_history`.** 365 rows carry `pnl=0.0 / exit_reason=SIGNAL`
  from the gotcha-22 bug. `backfill_trade_history.py --days 120` rewrites them
  from `/history/transactions`, which is the authoritative source. The live path
  is fixed going forward but historical rows will not self-heal.
- **Rebuild `backtest-runner`.** Its baked code and config are months stale: no
  `reverse_signal_exit` support at all (it closes on reverse signals
  unconditionally), US100 on ST(7, 2.0) instead of ST(14, 1.5), ETHUSD on
  SL 45/TP 170 instead of 25/125. Every UI-triggered backtest therefore tests a
  different strategy than the one deployed — it produced `+$733,912` on $10k
  from a reverse-signal scalper. `docker compose build backtest-runner`. See
  gotcha 25. Note the build context bakes in all uncommitted changes in that
  tree — check `git status` first.
- **Pin `DB_PATH`.** Host scripts default to a stray 35 MB `/data/trading.db`
  that is not the live volume; a host-run US100 backtest silently used 1,500
  bars (~5 days) and reported 18 trades without warning. Gotcha 24.
- **The GOLD/ETHUSD `position_size` changes.** Still uncommitted and
  undeployed, by design. Gotcha 26.
- **Whether to keep running the Supertrend bots at all.** Measured live
  Aug 1–Oct 21: **−€2,004** (−€1,664 of it US100, plus −€184 swap). Every
  instrument sits at or below its breakeven win rate. This was raised and the
  instruction was to improve rather than stop, which is why the research
  streams above exist — but the bots are still running the unchanged strategy
  with only the measurement fixed.
