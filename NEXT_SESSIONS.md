# Handoff — ready-to-paste prompts for new sessions

Rewritten 2026-10-22 (second session that day). Each prompt below is
self-contained: paste one as the first message of a fresh session. They assume
the agent reads `CLAUDE.md` first.

**Read before starting any of these:**

- `CLAUDE.md` gotchas **22–38** are from 2026-10-21; **40–50** from 2026-10-22.
  Fixed: 22, 29, 31, 40, 41, 42, 49, 50. **Still open hazards: 19, 24, 25, 26,
  36, 48** — and 19 is the one that is actively losing money.
- **Standing constraint:** the three live bots (GOLD, ETHUSD, US100) run on a
  **demo** account in `stockscreener-trading-bot-1`. Do not change live config,
  size, or bot state without explicit instruction. Research and tests are free;
  anything that reaches the broker is not.
- **Nothing in the last three sessions is deployed.** The live bots run baked-in
  image code. See prompt 1 — this is the biggest gap between what the repo says
  and what is actually trading.
- **Git state:** branch `fix/gate-unification-and-live-path-coverage`, **26
  commits ahead of `origin/main` and NOT pushed** (no GitHub credentials in the
  container environment — the human pushes). `origin/main` is at `ed2357f` and
  lacks `reverse_signal_exit`, the risk breakers, `.coveragerc` and `pytest.ini`
  entirely, so **the branch is not separable** — cherry-picking individual
  commits onto `main` was tried and fails on the first one.
- **`position_size` is settled, don't re-litigate it:** committed as `c0fb630`,
  then deliberately **reverted** by `6a26450`. GOLD therefore still trades 0.5
  contracts against an intended 10. Recover with `git show c0fb630` only when
  the edge justifies it (gotcha 26).
- Test commands:
  `cd trading-bot-skills && python3 -m pytest` → **912 passing, 0 failing** (~80s)
  `python3 -m pytest --cov` → **71.69%**, floor `fail_under = 69` (~155s)
  `python3 -m pytest tests/ -q` from repo root (research tools)
  **Never pass `--cov=<dotted.module.path>`** — it reloads numpy and fails ~47
  unrelated tests. Gotcha 43. Use bare `--cov` or `--cov=<package>`.

---

## What the 2026-10-22 sessions closed

| old prompt | outcome |
|---|---|
| `orchestrator/main.py` coverage | **done** — 13% → 95% (gotcha 44) |
| `trading_orchestrator.py` coverage | **done** — 15% → **100%**; surfaced 4 live-path bugs, **all fixed** (gotcha 49) |
| `sl_tp_engine.py` coverage | **done** — 44% → **100%**; found+fixed the unguarded Supertrend stop (gotcha 50) |
| `analysis_skill` tick-exit / MTF | **done** — 55% → 85% (gotchas 44, 45) |
| `execution_skill` / websocket + CI gate | **done** — 45% → 93%, 41% → 98%; `pytest.ini` + `.coveragerc` |
| the 20 "`test_pip_config`" failures | **done** — 20 across 3 files, 3 causes, one a real production bug (gotcha 40) |
| gate-path divergences + candle dedup | **done** — one gate chain, dedup fixed (gotchas 41, 42) |
| breadth expansion | **done, and it FAILED** — breadth rose 4.9 → 14.1 and *gross* Sharpe fell too (gotchas 46, 47) |

Four bugs the coverage work found in the live loop, all fixed, none deployed:
unconditional position-flag clearing (the real accumulation hole — every reverse
close is booked **twice**), invented `pnl=0.0`, booking a refused close before
checking the broker result, and an error handler that raised inside its own
`except`. Gotcha 49 has the detail.

---

## 1. Deploy the fix stack — three sessions of fixes are not live

> Read `CLAUDE.md` gotchas **10** (deploy topology), **38** and **49** (what is
> undeployed), then **26** (what must NOT ride along).
>
> **The live bots are running known-broken code.** Everything below is fixed in
> the repo and baked-stale in the running image:
> - `get_activity()` returns `[]`, so every close is detected only by the 60s
>   REST reconcile → `pnl` recorded as **0.0** on every row, SL/TP cooldowns
>   **never fire**, the consecutive-loss breaker scores **every trade a win**,
>   and `max_daily_loss_usd` is **pinned at zero** (gotcha 22's consequence
>   chain).
> - `bar_updater` silently no-ops (gotcha 29's string-comparison bug).
> - The `RiskSkill` live gate chain ignores the circuit breaker, session filter
>   and news kill-switch (gotcha 41).
> - Candle dedup is last-timestamp-only, so a reconnect replays bars into the
>   indicator buffer (gotcha 42).
> - The four live-loop bugs in gotcha 49.
>
> **The hazard is the deploy itself.** Per gotcha 10 the build context is
> `./trading-bot-skills`, so `docker compose build trading-bot` bakes in
> **everything in that tree, committed or not**. Run `git status` first and say
> out loud what is going in. The `position_size` change is currently reverted
> (`6a26450`) so it will NOT ride along — verify that before building.
>
> Suggested order, and stop for a decision at each step:
> 1. `git status` + `git log --oneline origin/main..HEAD` — state exactly what
>    will be baked in.
> 2. Confirm effective loaded config per instrument *before* the build
>    (`load_config('config/instruments/GOLD.yaml')` → `risk`/`execution`
>    `position_size` must be `None`).
> 3. Record the pre-deploy baseline: open positions, `bot_state` in
>    `kv_store`, and the last 24h of activity.
> 4. `docker compose build trading-bot && docker compose up -d trading-bot`.
> 5. `on_startup` auto-restores whichever bots were running
>    (`bot_control_api.py:394`) — confirm the same two/three came back, and that
>    each re-read the intended SL/TP from `/app/config`.
> 6. Watch one real close end-to-end and confirm `pnl` is a real number, not
>    `0.0` and not `None`, and that `close_reason` is `SL_HIT`/`TP_HIT` rather
>    than `SIGNAL`.
>
> **Do not** rebuild `backtest-runner` in the same step — that is prompt 6 and
> has its own verification.

---

## 2. Nothing force-closes a live position — this is losing money now

> Read `CLAUDE.md` gotcha **19**, then **20** and **27**.
>
> **Verified still true on 2026-10-22:** `eod_hour` / `eod_enabled` are read
> **only** by `orchestrator/production_orchestrator.py:143`. The live bot is
> `bot_control_api.py` → `orchestrator/main.py` → `TradingOrchestrator`, which
> contains **zero** references to `EndOfDayClose` or `IntraDayTimeExit`. Live
> exits are SL / TP / tick-exit only. `time_based_exits` in the YAML is dead
> config.
>
> **Confirmed cost:** US100 `dealId 00384627-…-000083765fd6`, SELL 1 @ 28288.7
> opened Fri 2026-07-31 20:00:07 UTC with a stop at 28320.1, closed Sun
> 2026-08-02 22:00:10 UTC at **28441.7** on the reopen gap — 121.6 pts *past*
> the stop, realised **−$153** against an intended −$50. `guaranteedStop: false`
> on every position, so weekend gap risk is **uncapped**.
>
> **The naive fix does not work.** A single global `eod_hour: 16` is useless for
> US100, whose entire allowed session is 13:00–20:59 UTC — every position it
> opens is created *after* the close hour. This needs a **per-instrument**
> flatten time, and a Friday-specific one is what actually caps the gap.
>
> Scope it as: wire a time-based flatten into the live path (`TradingOrchestrator`
> or `main.py`'s poll loop, whichever owns the clock), per-instrument config,
> with a distinct Friday flatten hour. Then decide whether `guaranteedStop`
> is worth its premium on the Friday position specifically.
>
> **Cover it with tests before deploying** — `tests/unit/test_live_orchestrator_loop.py`
> has the fake-skill harness and `test_live_poll_loop.py` has the `fast_clock`
> fixture for anything that awaits `asyncio.sleep`. Note that
> `run_skills_backtest.py` does **not** simulate a flatten, so enabling this
> makes live diverge from backtest unless the backtester gets it too — say which
> you did.

---

## 3. The GOLD live/backtest divergence — four hypotheses rejected, one left

> Read `CLAUDE.md` gotcha **36** (the rejected hypotheses), then **41** and **48**.
>
> Live window 2026-08-01..10-21: backtest takes **61** trades at WR 21.31% /
> PF 1.046; live took **93** at WR 13.98% / PF 0.646. Cause still unknown, and
> until it is closed **no GOLD backtest conclusion is trustworthy** — US100
> parity is good (gotcha 33), GOLD parity is not established.
>
> **Already tested and REJECTED — do not re-test:**
> 1. broken SL/TP cooldowns — 0 / 60 / 30 min all give exactly 61 trades,
>    because the gate only blocks *same-direction* re-entry and `edge_detection`
>    means the next signal is usually the opposite one;
> 2. the daily 21:00 restart resetting `last_signal_state` — the 31 excess live
>    trades spread across hours 8–20, and hour 21 has **zero** live entries;
> 3. Supertrend path-dependence on the 300-bar live buffer — **100.00%**
>    direction agreement over 1,100 bars, 85 vs 85 flips;
> 4. startup-flip suppression — it would make live take **fewer** trades, and
>    live takes more.
>
> **The remaining untested lead:** the live bot builds candles from the WebSocket
> tick stream (`_handle_ohlc`, ASK/OFR only) while the DB bars come from the REST
> price endpoint. Bar boundaries — and which bars exist at all — may differ.
> **Count bars per day on each side first**, before comparing OHLC values; a
> bar-count mismatch and an OHLC mismatch have different causes.
>
> Second untested lead, cheaper to check: the live MA100 bias is computed over
> whatever the live buffer actually holds, and that buffer was itself starved
> while gotcha 29 was active. If live MA100 was being computed on sparse bars,
> the bias gate would admit signals the backtest's dense bars reject — which
> matches the direction of the error (live takes **more** trades).
>
> **Note gotcha 48 before you start:** GOLD's repaired bars are in the HOST
> stray `/data/trading.db` (188,435 as of 2026-10-22), not the live volume
> (163,867). Pin `DB_PATH` deliberately and say which DB every number came from.

---

## 4. `backtesting_skill.py` coverage — every strategy number comes from here

> Read `CLAUDE.md` gotchas **31** (the 50× typo that lived in this file's cost
> model), **40** (the cost-scaling contract) and **43**/**44** (how to measure).
>
> `skills/backtesting/backtesting_skill.py` is **59%, 111 uncovered**
> (`365-416, 423-440, 444-480, 504-512` are the big blocks). It is the highest
> *consequence* gap left: every PF, win rate and P&L figure in gotchas 28–35
> came out of this file, and a silent arithmetic error here does not crash — it
> just produces a confident wrong number. Gotcha 31 is exactly that: one
> character turned −$2,560 into −$134,629 and nothing complained.
>
> Priorities inside it:
> - **the cost model** — `spread_cost_usd * current_size` must be applied in
>   exactly ONE place (gotcha 40 explains why; a double-multiplication charges
>   size² of cost). There is a `TestCostScalingHappensOnce` in
>   `test_pip_config.py` to extend, not duplicate.
> - **`dynamic_sizing`** — it compounds, which is how the stale `backtest-runner`
>   produced `+$733,912` on $10k (gotcha 25). Pin what it does to position size
>   across a winning and a losing sequence.
> - **fill logic and exit precedence** — what happens when a bar's range
>   contains BOTH the SL and the TP. Assert the documented choice; if the code
>   has no documented choice, that is a finding, not a test to write around.
> - **`close_reverse_positions`** and the `reverse_signal_exit` guard at
>   `run_skills_backtest.py:553`.
>
> Assert **exact** values, not inequalities — gotcha 50's lesson: a factor-of-50
> error passes every inequality test. Report the real before/after and raise
> `fail_under` only to a number the suite actually meets.

---

## 5. `capital_api.py` coverage — the broker boundary, 19%

> Read `CLAUDE.md` gotchas **12**, **15**, **22**, **23**, **30** and **38** —
> every one of them is a fact about this file's endpoints that was learned the
> hard way, and several contradict each other's earlier versions.
>
> `clients/capital_api.py` is **19%, 172 uncovered**. It needs HTTP mocking
> (`responses` or `requests-mock`); nothing here should reach the broker.
>
> The behaviours worth pinning, because each one has already caused an outage or
> a wrong number:
> - `get_activity` must send `status==ACCEPTED` — `EXECUTED` matches nothing and
>   silently returned `[]` for months (gotcha 22).
> - A close is identified by **`details.openPrice` being present**; there is no
>   `details['actions']` array and no `details.profit`.
> - `details.direction` on a close is the **closing** direction, the opposite of
>   the position's.
> - `/history/transactions`: **`size` IS the realised P&L**, there is no
>   `profitAndLoss` field; responses are hard-capped at **100 rows** with
>   `pageSize`/`pageNumber` ignored; `lastPeriod` is capped at **86400s** on both
>   activity and transactions; a `to` in the future returns 400.
> - `/prices/{epic}`: `from`+`to` together returns **400** — there is no
>   date-range mode, only backward pagination on `to` + `max`; `to` must be full
>   ISO with `T`; `snapshotTime` comes back account-local (UTC+2) while `to` is
>   UTC, so pagination must anchor on `snapshotTimeUTC` (gotcha 30/38).
> - `get_realised_pnl(deal_id)` default look-back is 3600s and returns `None`
>   beyond it — and `None` must stay `None`, never `0.0`.
> - Session reuse: creating sessions in a tight loop returns 400 on `/session`.
>
> `clients/firestore_api.py` (12%, 140 uncovered) is the same shape of work and
> lower risk — do it second if there is time.

---

## 6. Make UI backtests stop lying — stale runner, split DBs

> Read `CLAUDE.md` gotchas **25** (stale runner), **48** (split DBs) and **24**
> (three different `trading.db` files).
>
> Three separate problems that compound into "the dashboard's backtests describe
> a strategy nobody runs":
>
> 1. **`stockscreener-backtest-runner-1` has stale baked CODE, not just config.**
>    `/app/run_skills_backtest.py` is 866 lines vs the host's 992 and contains
>    **zero** occurrences of `reverse_signal_exit`, calling
>    `close_reverse_positions(...)` unconditionally. So `docker cp`-ing correct
>    YAML in is **not sufficient** — a run with `reverse_signal_exit: false`
>    correctly loaded still produced 6,973 `Reverse Signal` exits and
>    `+$185,306`. It needs `docker compose build backtest-runner`.
> 2. **The GOLD bar repair landed in the host stray DB, not the live volume**
>    (188,435 vs 163,867 bars). So anything run inside a container still sees
>    starved GOLD data, and gotcha 24's usual advice *inverts* for GOLD right
>    now. Decide which DB is canonical, sync it, then **pin `DB_PATH`** so a
>    host-run script cannot silently create a third one
>    (`sqlite_api.py:30` defaults it and `:49` creates the parent dir).
> 3. After the rebuild, **re-run the documented regressions** and compare:
>    GOLD 2y should land near **493 trades / WR 21.70% / PF 1.0501** and US100 2y
>    near **2485 / 25.47% / 0.973**. A large divergence means the container is
>    still not running what the host runs.
>
> Treat any backtest number from that container as an artefact until this is
> done. `sqlite3` CLI is **not installed** on the host — use
> `python3 -c "import sqlite3..."`.

---

## 7. Repair Aug–Oct `trade_history` — 365 rows of zeros

> Read `CLAUDE.md` gotchas **22** (how the zeros happened), **13** (the writer
> and its idempotency) and **14** (the backfill tool), plus **15** and **21**
> for the exact row shapes.
>
> 365 `trade_history` rows carry `pnl=0.0` / `exit_reason=SIGNAL` because
> `_handle_close(deal_id, 0.0, '')` was the only close path while
> `get_activity()` was broken. The dashboard therefore shows real P&L only
> through 2026-07-31 and **0.00 for everything after** — US100 shows 223 of 231
> trades at zero. The live path is fixed going forward, but **historical rows
> will not self-heal**.
>
> `python backfill_trade_history.py --days 120 [--dry-run]` rewrites them from
> `/history/transactions`, which is the authoritative source. `save_trade()`
> keys on `deal_id` in `kv_store`, so re-running is an idempotent overwrite, not
> double-counted P&L. Run `--dry-run` first and report how many rows change and
> by how much before writing.
>
> Run it against the live volume
> (`/var/lib/docker/volumes/stockscreener_trading_data/_data/trading.db`) or
> inside a container at `/data/trading.db` — **not** the host stray DB.
>
> Caveat to carry into the write-up: the join recovers P&L for every row but
> cannot recover entry price or direction for rows with no `active_positions`
> match; those stay flagged `partial: true`.

---

## 8. Where to take the strategy research — three levers are now closed off

> Read `CLAUDE.md` gotchas **32**, **34**, **37**, **46** and **47** **before
> proposing anything.** Three levers have been measured and all three failed,
> and the failures are informative:
>
> - **Parameter tuning** (34): ~20 configs, 3 instruments. The one GOLD winner
>   did not transfer — US100 0.973 → 0.948, ETHUSD 0.858 → 0.829.
> - **Breadth in instruments** (46): effective breadth 4.9 → 14.1 as designed,
>   and *gross* Sharpe fell 0.37 → −0.05, so it is not a cost problem.
>   Grinold's `IR ≈ IC × √breadth` assumes uniform IC; measured IC is
>   concentrated in **9 of 48** names with **21 actively negative**.
> - **Bonds / rates** (47): 7 instruments exist in total, 2 pass the friction
>   screen, both have under 3 years of weekly history.
>
> What the evidence points at, in order:
> 1. **Cost per unit of R, not entry tuning.** Gotcha 32 is the most actionable
>    measurement in the file: GOLD and US100 both have a *positive gross* edge
>    (~PF 1.02) that costs consume entirely — US100's gross edge is $4.74/trade
>    against ~$10/trade of cost. Spread is 3.6% of R at SL 50 and 1.8% at SL 100.
>    So **wider R or fewer trades**, not a better indicator. This has not been
>    tested properly yet and is the cheapest remaining experiment.
> 2. **Instrument selection on measured edge rather than friction.** The screen
>    currently takes the cheapest names; the 9 with edge are not the 9 cheapest.
>    Selecting on realised Sharpe is in-sample fitting, so it needs gotcha 34's
>    IS/OOS + cross-instrument transfer bar and a trial-count-corrected DSR.
> 3. **Vol target 20% → 15%.** Half-Kelly implies 15%; this is the one change
>    already justified by the measurements, and it only touches sizing.
> 4. **A second, uncorrelated signal family.** Breadth in *signals* was never
>    tested; breadth in *instruments* is now ruled out. One family at breadth ≈ 1
>    is the structural problem gotcha 37 describes.
>
> **Non-negotiable in any write-up:** no Sharpe without its DSR and the
> buy-and-hold benchmark beside it. Buy-and-hold currently beats the trend
> overlay at **every** breadth level (0.34 → 0.52), and the gap *widens* as the
> universe grows. Preserve the known limitations rather than dropping them: the
> universe is screened on *today's* spread snapshot then backtested over 21–40
> years (selection bias), these are CFD proxies not futures, spreads are assumed
> constant, and the weekly sample is closes only.

---

## 9. Small open items — fine to fold into another session

- **The live startup-flip gate re-arms on the daily 21:00 restart**, so it fires
  once per bot per day with no backtest equivalent (gotcha 41). Not the cause of
  prompt 3's divergence — suppression makes live take *fewer* trades.
- **A blocked signal skips the monitoring heartbeat** while a no-signal bar runs
  it (gotcha 49). Pinned by a test as current behaviour. Structural question, no
  observed harm — decide whether the asymmetry is intended.
- **ETHUSD `backtesting.position_size` is 2 while its comment says "1 ETH per
  trade"** — restored by the `6a26450` revert. Backtest-only, but it changes
  ETHUSD backtest magnitudes. One-line fix if wanted.
- **`execution.trailing_stop: false` in `trading_config.yaml` is a dead flag** —
  no code reads it. Don't confuse it with `risk.stop_management` (gotcha 16).
- **`core/stop_manager.py` is DEFAULT OFF and not simulated by the backtester.**
  Enabling it makes live diverge from backtest (gotcha 16).
- **`MarketDataSkill.process_candle` has no production callers** (gotcha 42) —
  dead path, consider deleting it rather than maintaining two code paths.
- **Coverage after `backtesting_skill` and `capital_api`:** `firestore_api` 12%
  (140), `production_orchestrator` 49% (119 — but it is NOT the live path, and
  is the only thing that reads `eod_hour`; see prompt 2), `sqlite_api` 51% (91),
  `log_publisher` 30% (61), `reporting_skill` 11% (209, lowest risk).

---

## 10. The standing question — keep running these bots?

> Measured live Aug 1 – Oct 21 (demo, EUR): **−€2,004** total (−€1,664 of it
> US100, plus −€184 of swap). Max cumulative drawdown −€2,588. Every instrument
> sits at or below its breakeven win rate: US100 −4.30pp, GOLD −6.13pp, ETHUSD
> +0.94pp. Gotcha 28.
>
> This was raised before and the instruction was to improve rather than stop.
> Since then **three** improvement levers have been measured and all three
> failed (prompt 8), and the one encouraging datapoint — GOLD's PF reversing to
> 1.05 once the bars were repaired (gotcha 35) — is measured on a backtest whose
> **live parity is not established** (prompt 3, gotcha 36).
>
> So the honest state is: the only instrument with trustworthy backtest↔live
> parity (US100) is also the biggest loser, and the instrument that looks
> salvageable on paper (GOLD) is the one whose backtest we cannot yet trust.
> Prompt 3 is the prerequisite for answering this question with evidence rather
> than hope.
