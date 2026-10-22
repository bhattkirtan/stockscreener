# Handoff — ready-to-paste prompts for new sessions

Rewritten 2026-10-22 (second session that day). Each prompt below is
self-contained: paste one as the first message of a fresh session. They assume
the agent reads `CLAUDE.md` first.

**Read before starting any of these:**

- `CLAUDE.md` gotchas **22–38** are from 2026-10-21; **40–50** from 2026-10-22.
  Fixed: 22, 29, 31, 40, 41, 42, 49, 50, 51. **Still open hazards: 19, 24, 25,
  26, 36, 48.** 19 now has a built, tested fix (51) that is deliberately
  **switched off** — the backtest says flattening removes the only profitable
  cohort. Prompt 2 is now a decision backed by one more measurement, not a
  build task. Nothing from the last four sessions is deployed either way.
- **Standing constraint:** the three live bots (GOLD, ETHUSD, US100) run on a
  **demo** account in `stockscreener-trading-bot-1`. Do not change live config,
  size, or bot state without explicit instruction. Research and tests are free;
  anything that reaches the broker is not.
- **Nothing in the last three sessions is deployed.** The live bots run baked-in
  image code. See prompt 1 — this is the biggest gap between what the repo says
  and what is actually trading.
- **Git state (updated 2026-10-22): the branch IS PUSHED.** `origin/fix/gate-
  unification-and-live-path-coverage` is at `1145f16`; local is in sync, 0
  unpushed. It is still **31 commits ahead of `origin/main`** because nothing is
  merged — **no PR has been opened.** Open one at
  https://github.com/bhattkirtan/stockscreener/compare/main...fix/gate-unification-and-live-path-coverage
- **The earlier "pushing is confirmed impossible" note was a missing credential,
  not a blocked path — and it is now resolved.** Diagnosed properly: egress from
  this box works (`curl https://github.com` → **200**), there was simply no
  `credential.helper`, no HTTPS credential, and no SSH key GitHub accepts
  (`ssh -T git@github.com` → `Permission denied (publickey)`). The human fixed it
  with `git config credential.helper store` + one interactive push, so **the
  credential is cached on this box and pushes now work from here.**
  **But do not push unasked** — the standing constraint below still applies, and
  a cached credential makes an accidental push easier, not more authorised.
  `gh` is still not installed, so PRs must be opened in the browser.
  **Never go hunting for tokens on disk to work around an auth failure** — that
  stays off-limits regardless of how the push request is phrased.
- `origin/main` is at `ed2357f` and lacks `reverse_signal_exit`, the risk
  breakers, `.coveragerc` and `pytest.ini` entirely, so **the branch is not
  separable** — cherry-picking individual commits onto `main` was tried and
  fails on the first one.
- **`position_size` is settled, don't re-litigate it:** committed as `c0fb630`,
  then deliberately **reverted** by `6a26450`. GOLD therefore still trades 0.5
  contracts against an intended 10. Recover with `git show c0fb630` only when
  the edge justifies it (gotcha 26).
- Test commands (re-measured 2026-10-22, third session):
  `cd trading-bot-skills && python3 -m pytest` → **1152 passing, 0 failing** (~80s)
  `python3 -m pytest --cov` → **74.80%**, floor `fail_under = 72` (~160s)
  Full per-module status: see **Test coverage — status board** below.
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
| nothing force-closes a position | **built, shipped OFF** — mechanism done + tested; the backtest says the weekend-carry trades hold all the profit, so enabling it needs the flatten simulated first (gotcha 51) |
| `backtesting_skill.py` coverage (old prompt 4) | **done** — 59% → **100%**; 6 findings, 2 fixed (the PF divide-by-zero guard reporting 100x gross wins, and a docstring that understated dynamic sizing 10x) (gotcha 53) |

Four bugs the coverage work found in the live loop, all fixed, none deployed:
unconditional position-flag clearing (the real accumulation hole — every reverse
close is booked **twice**), invented `pnl=0.0`, booking a refused close before
checking the broker result, and an error handler that raised inside its own
`except`. Gotcha 49 has the detail.

---

## Test coverage — status board

**Measured 2026-10-22 (fourth session), canonically.** Reproduce with exactly:

```bash
cd trading-bot-skills && python3 -m pytest --cov -o addopts= -q
# -> 1152 passed, TOTAL 74.80%, "Required test coverage of 72.0% reached"
```

**Never `--cov=<dotted.module.path>`** — it reloads numpy and fails ~47 unrelated
tests, *and* under-reports (gotcha 43). Bare `--cov` reads `.coveragerc`, whose
`exclude_lines` drops the `if __name__ == '__main__':` demo blocks several skills
carry. Numbers measured any other way are not comparable to this table.

Status legend: **DONE** = deliberately finished, no further work planned ·
**PARTIAL** = usable cover, known holes, no owner · **OPEN** = an active prompt
below owns it · **LOW** = acknowledged gap, deliberately deprioritised.

| module | cover | miss | status | owned by |
|---|---|---|---|---|
| `core/signal_engine.py` | **100%** | 0 | DONE | — |
| `core/sl_tp_engine.py` | **100%** | 0 | DONE | `test_sl_tp_engine.py` (61) |
| `core/time_exits.py` | **100%** | 0 | DONE | `test_time_exits.py` (72) |
| `orchestrator/trading_orchestrator.py` | **100%** | 0 | DONE | `test_live_orchestrator_loop.py` (83) |
| `skills/backtesting/backtesting_skill.py` | **100%** | 0 | DONE | `test_backtest_engine.py` (**168**), `test_pip_config` (39), `test_backtesting_skill` (13) |
| `clients/capital_websocket.py` | 98% | 2 | DONE | `test_live_execution_and_socket.py` (87) |
| `core/stop_manager.py` | 97% | 3 | DONE | `test_stop_manager.py` (14) |
| `orchestrator/main.py` | 95% | 22 | DONE | `test_live_poll_loop` (66), `test_live_bootstrap` (63), `test_live_tick_exit` (102) |
| `core/operational_monitoring.py` | 95% | 12 | DONE | `test_operational_monitoring.py` (27) |
| `skills/execution/execution_skill.py` | 93% | 11 | DONE | `test_execution_skill` (8) + live suites |
| `core/idempotency.py` | 92% | 9 | DONE | `test_idempotency.py` (17) |
| `skills/base_skill.py` | 92% | 4 | DONE | — |
| `core/circuit_breakers.py` | 89% | 22 | PARTIAL | `test_circuit_breakers.py` (26) |
| `core/indicators.py` | 87% | 15 | PARTIAL | — |
| `skills/analysis/analysis_skill.py` | 85% | 94 | PARTIAL | `test_live_analysis_path` (16), `test_analysis_skill` (5), tick-exit suite |
| `skills/market_data/market_data_skill.py` | 84% | 18 | PARTIAL | `test_market_data_skill` (9), `test_live_signal_path` (35) |
| `skills/risk/risk_skill.py` | 82% | 54 | PARTIAL | `test_risk_skill` (16), `test_execute_pipeline` (31), `test_live_close_and_risk` (62) |
| `core/event_bus.py` | 79% | 40 | PARTIAL | `test_event_bus.py` (19) |
| `core/position_state.py` | 77% | 46 | PARTIAL | `test_position_state.py` (15) |
| `skills/storage/storage_skill.py` | 77% | 35 | PARTIAL | `test_storage_skill` (8), `test_trade_history` (14) |
| `core/cost_calculator.py` | 67% | 11 | PARTIAL | — |
| `clients/telegram_api.py` | 63% | 28 | LOW | — |
| `skills/alerting/alerting_skill.py` | 54% | 55 | LOW | `test_alerting_skill.py` (10) |
| `skills/monitoring/monitoring_skill.py` | 51% | 44 | LOW | `test_monitoring_skill.py` (8) |
| `clients/sqlite_api.py` | 51% | 91 | LOW | — |
| `orchestrator/production_orchestrator.py` | 49% | 119 | **WON'T DO** | not the live path; see note |
| `clients/log_publisher.py` | 30% | 61 | LOW | — |
| **`clients/capital_api.py`** | **19%** | **172** | **OPEN — prompt 5** | `test_activity_parsing.py` (15), partial |
| `clients/firestore_api.py` | 12% | 140 | LOW — prompt 5 tail | — |
| `skills/reporting/reporting_skill.py` | 11% | 209 | LOW (lowest risk) | — |
| **TOTAL** | **74.80%** | 1317 / 5227 | floor `fail_under = 72` | 32 suites, **1152 tests** |

**`production_orchestrator.py` is deliberately not worth covering.** The live bot
never instantiates it (gotcha 19) — it is the only thing that reads `eod_hour`,
and it carries two known defects if anyone reaches for it (`datetime.now()` local
time compared against a UTC config hour, and `hour >= close_hour` true for every
later hour). Covering it would pin behaviour nobody runs. If it is ever revived,
**fix those two defects first**, then cover it.

**One gap now accounts for the largest remaining risky block: `capital_api.py`
at 19% (172 uncovered), the broker boundary.** That is prompt 5 and it is the
whole remaining coverage story; everything else marked LOW is reporting,
alerting and logging. `backtesting_skill.py` — the other half of this note until
2026-10-22 — is **done at 100%** (gotcha 53).

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

## 2. The flatten is BUILT but deliberately OFF — decide whether to enable it

> Read `CLAUDE.md` gotcha **51** first (what was built and the measurement that
> stopped it being switched on), then **19**, **10** and **27**.
>
> **Status 2026-10-22:** `core/time_exits.py` + gate + poll-loop close exist,
> 72 tests, module at 100%. Shipped `enabled: false` on GOLD and US100, absent
> on ETHUSD. So the live bots **still carry positions over the weekend** — by
> choice now, not by oversight.
>
> **Why it is off.** The trades open across a Friday 20:45 hold *all* the
> backtested profit on both instruments:
>
> | | carry trades | their net | all others | their net | total |
> |---|---|---|---|---|---|
> | GOLD | 61 (12.4%) | +$12,234 | 430 | −$9,532 | +$2,702 |
> | US100 | 97 (3.9%) | +$15,780 | 2,388 | −$28,880 | −$13,100 |
>
> Flattening every Friday removes exactly that cohort. That is partly
> survivorship — losers hit a 1:3–1:4 stop fast, so long holds skew to winners
> — and a flatten closes them at the Friday price rather than converting them
> to losses. But the magnitude dwarfs both totals, so it cannot be enabled on
> a guess.
>
> **The one job that settles it: simulate the flatten in the backtester.**
> `run_skills_backtest.py` models SL/TP exits only. Teach it to close a
> position at the configured flatten moment (the entry-gate half already works
> there — `RiskSkill` is shared, so `risk.time_exits` reaches backtest and
> blocks Friday-evening entries using bar time). Then re-run GOLD and US100 2y
> with `--set risk.time_exits.enabled=true` and compare properly. That single
> change turns this from a judgement call into a measurement.
>
> Only after that: flip the YAMLs, rebuild (prompt 1), and watch one Friday —
> the close should land in `trade_history` with a real P&L from
> `get_realised_pnl`, not 0.00, since the flatten books nothing itself.
>
> **Separate and still open: `guaranteedStop` is false on every position.** An
> intraweek gap (a Wednesday news spike) is uncapped and the Friday flatten
> never addressed it. Price the premium against the measured tail.
>
> **Do not** reach for `time_based_exits` / `eod_hour`: still dead, left dead
> on purpose — its base value would close every US100 position from 17:00
> onward. `production_orchestrator.EndOfDayClose` is wrong twice over too:
> local-time `datetime.now()` against a UTC config hour, and `hour >=
> close_hour`, true for every later hour of every day.

---

## 3. The GOLD live/backtest divergence — four hypotheses rejected, two leads left

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
> **Two untested leads remain. Start with A — it is far cheaper, and it is the
> one whose failure mode matches the direction of the error.**
>
> **Lead A — the live MA100 bias was computed over starved bars.** MA100 bias is
> the *only* entry filter on GOLD, and live computes it over whatever the rolling
> buffer actually holds — a buffer that was itself starved for the whole Aug–Oct
> window while gotcha 29 was active (GOLD M5 coverage 6% in Q3/Q4). Sparse bars
> make MA100 a different number over a far longer wall-clock lookback, so the
> gate would admit signals the backtest's dense bars reject — which matches the
> **direction** of the error: live takes **more** trades (93 vs 61), not fewer.
> Rejected hypotheses 1–4 all predict fewer or equal, so this is the first one
> that points the right way.
> **How to check, cheaply:** reconstruct what the 300-bar buffer would have held
> at each of the 93 live entry timestamps given the bars that actually existed
> then, compute MA100 on it, and compare against the dense-bar MA100 the
> backtest used. Entirely a desk exercise against the two existing DBs — no bar
> capture, no container, no broker calls.
>
> **Lead B — WebSocket bars vs REST bars.** The live bot builds candles from the
> tick stream (`_handle_ohlc`, ASK/OFR only) while the DB bars come from the REST
> price endpoint. Bar boundaries — and which bars exist at all — may differ.
> **Count bars per day on each side first**, before comparing OHLC values; a
> bar-count mismatch and an OHLC mismatch have different causes. This one needs
> live bar capture, so only reach for it if Lead A comes back clean.
>
> **Note gotcha 48 before you start:** GOLD's repaired bars are in the HOST
> stray `/data/trading.db` (188,435 as of 2026-10-22), not the live volume
> (163,867). Pin `DB_PATH` deliberately and say which DB every number came from.

---

## 4. `backtesting_skill.py` coverage — every strategy number comes from here

> **STATUS: OPEN, not started. 59%, 111 uncovered.** Read `CLAUDE.md` gotchas
> **31** (the 50x typo that lived in this file's cost model), **40** (the
> cost-scaling contract), **51** (`max_hours` is the only time exit this file
> models) and **43**/**44** (how to measure).
>
> Highest *consequence* gap left: every PF, win rate and P&L figure in gotchas
> 28-35 came out of this file, and a silent arithmetic error here does not crash
> — it produces a confident wrong number. Gotcha 31 is exactly that: one
> character turned -$2,560 into -$134,629 and nothing complained.
>
> ### Implemented today
>
> | suite | tests | what it pins |
> |---|---|---|
> | `test_backtesting_skill.py` | 13 | basic execute/fill happy path |
> | `test_pip_config.py` | 39 | `_propagate_risk_to_sl_tp`, and `TestCostScalingHappensOnce`, which drives `BacktestingSkill.execute()` and asserts the stored cost totals so a double-multiplication fails |
> | `test_time_based_exits.py` | 14 | the `time_based_exits.max_hours` config surface |
>
> So the **cost-scaling contract is already pinned** (gotcha 40) — extend
> `TestCostScalingHappensOnce`, do not duplicate it.
>
> ### Missing — the 111 uncovered statements, by function
>
> | function | lines | uncovered | why it matters |
> |---|---|---|---|
> | `check_exits` | 365-416 | **52** | **the exit engine.** SL/TP detection and the `max_hours` exit at `:398`. Contains the SL-vs-TP-in-the-same-bar precedence question — **if the code has no documented choice, that is a finding, not a test to write around.** |
> | `_close_position` | 444-480 | **37** | the P&L arithmetic and where `spread_cost_usd * current_size` is applied |
> | `close_reverse_positions` | 423-440 | 18 | the reverse-exit path; gotcha 25's `+$185,306` artefact came through here, and the `reverse_signal_exit` guard is at `run_skills_backtest.py:553` |
> | `_compute_position_size` | 267-277 | 11 | **`dynamic_sizing`, which compounds** — how the stale runner produced `+$733,912` on $10k (gotcha 25). Pin it across a winning *and* a losing sequence |
> | `get_results` | 504-512 | 9 | **the PF / WR / P&L aggregation itself.** Every number this project quotes is this function's output and it is entirely untested |
> | `validate_config` | 239-247 | 9 | config rejection paths |
> | `__init__` | 186-235 | 7 | config defaults, incl. `max_hours` |
> | `execute` | 291-333 | 6 | branch tails |
> | `to_dict` | 86 | 1 | trivial |
>
> `get_results` was **not** named in the earlier version of this prompt and
> should be done early — it is only 9 statements and it is the function whose
> output every gotcha in this file quotes.
>
> ### Rules for this work
>
> Assert **exact** values, not inequalities — gotcha 50's lesson: a factor-of-50
> error passes every inequality test. Report the real before/after from a bare
> `--cov` run and raise `fail_under` only to a number the suite actually meets.
> **Expect to find bugs**: the last two coverage pushes into untested live code
> turned up four live-loop bugs (gotcha 49) and an unguarded stop (gotcha 50).

---

## 5. `capital_api.py` coverage — the broker boundary, 19%

> **STATUS: OPEN, barely started. 19%, 172 uncovered — but the priority list in
> the previous version of this prompt pointed at ground that is already
> covered.** Read `CLAUDE.md` gotchas **12**, **15**, **22**, **23**, **30** and
> **38** — each is a fact about this file's endpoints learned the hard way, and
> several contradict each other's earlier versions.
>
> Needs HTTP mocking (`responses` or `requests-mock`). **Nothing here may reach
> the broker.**
>
> ### Implemented today — more than the old prompt implied
>
> `test_activity_parsing.py` (15 tests) subclasses the real client as
> `_RecordingClient` and drives the real `get_activity()`, so these are **already
> pinned** and need no new work:
> - `status==ACCEPTED` is sent, not `EXECUTED` (gotcha 22)
> - the `epic==` clause and `detailed=true` are included (gotcha 23)
> - `details.openPrice` discriminates a close from an open
> - `source` -> `SL_HIT` / `TP_HIT` / `SIGNAL`
> - there is no `details['actions']` array and no `details.profit`
> - `/history/transactions`: `size` IS the realised P&L; `lastPeriod` capped at 86400s
>
> **`get_activity` is down to 3 uncovered lines (341-343, its `except` branch)
> and `get_realised_pnl` to 8.** The old bullet list led with these. The real gap
> is elsewhere.
>
> ### Missing — the 172 uncovered statements, by function
>
> | function | lines | uncovered | why it matters |
> |---|---|---|---|
> | `get_historical_prices` | 536-588 | **53** | `from`+`to` together returns **400** — there is no date-range mode, only backward pagination on `to` + `max`; `to` must be full ISO with `T`; `snapshotTime` is account-local (UTC+2) while `to` is UTC, so pagination must anchor on `snapshotTimeUTC`. Gotchas 30/38. This is the function whose bug starved the bars for two quarters |
> | `create_session` | 75-114 | **40** | session creation; creating sessions in a tight loop returns 400 on `/session` (gotcha 15) — reuse one client |
> | `_request` | 153-186 | **34** | **everything flows through here** — the shared request/retry/error layer. Cover it first; it is the cheapest way to make the rest testable |
> | `place_order` | 218-245 | **28** | **the call that puts money at the broker, at 0% cover.** Not mentioned at all in the old prompt. Highest-risk untested function in the repo |
> | `update_position` | 428-449 | 22 | the stop amend `core/stop_manager.py` drives (gotcha 16); its invariants are tested, this HTTP leg is not |
> | `confirm_order` | 253-269 | 17 | fill confirmation |
> | `close_position` | 396-409 | 14 | the leg the flatten and reverse-exit paths call (gotcha 51) |
> | `__init__` | 42-63 | 22 | env/credential wiring |
> | `get_open_positions` | 278-286 | 9 | drives `_poll_positions` reconcile |
> | `get_account_info` | 458-466 | 9 | — |
> | `find_market` | 478-486 | 9 | — |
>
> ### Suggested order
>
> `_request` (34, unblocks everything) -> `place_order` + `confirm_order` (45,
> highest risk) -> `get_historical_prices` (53, biggest single block and a proven
> bug site) -> `create_session` -> the rest. That is ~155 of the 172.
>
> Keep `get_realised_pnl`'s contract explicit: default look-back is 3600s, it
> returns `None` beyond that, and **`None` must stay `None`, never `0.0`** —
> coercing it is gotcha 22's and 49(a)'s shared root cause.
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
- **Coverage beyond prompts 4 and 5:** see the **Test coverage — status board**
  near the top of this file — it is the single source of truth for every
  module's number, status and owning suite. Do not re-quote figures here; that
  duplication is how the old "`trading_orchestrator` 15%" line survived three
  sessions after it reached 100%.

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
