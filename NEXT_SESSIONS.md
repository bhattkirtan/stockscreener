# Handoff — ready-to-paste prompts for new sessions

Rewritten 2026-10-22 (second session that day), kept current through the eighth (2026-10-23, US100 re-base).
Each prompt below is self-contained: paste one as the first message of a fresh
session. They assume the agent reads `CLAUDE.md` first.

**Read before starting any of these:**

- `CLAUDE.md` gotchas **22–38** are from 2026-10-21; **40–59** from 2026-10-22.
  Fixed: 22, 29, 31, 40, 41, 42, 49, 50, 51, 53, 54 — **all DEPLOYED (55)** — plus
  **25 (56)**, **56's GOLD data gap — now fully closed, phantom bars deleted 2026-10-23** and **59** (the zero-P&L rows).
  **Still open hazards: 19, 26, 36, and the NEW 57.**
  - **Read gotcha 57 before trusting any backtest number, on any instrument.**
    Every stored M5 bar, in both DBs, for every instrument, is **mid price at an
    account-local (UTC+2) label** — except GOLD, now re-based to bid/UTC in both
    and, since 2026-10-23, **bit-identical between host and container backtests**
    (493 / PF 1.0555001992825828 / +$3,342 at `--bars 188534`).
    **US100 is also re-based, in the live volume only (2026-10-23)**: container
    `--bars 203260` = 2485 / PF 0.9748576652952666, now gating the true 13–20 UTC session.
    The host stray DB's US100 is still mid/local, so run US100 backtests in the container.
    **Default for every new session: run backtests inside `stockscreener-backtest-runner-1`.**
    The volume is now equal or better than the host DB for every instrument.
    It is invisible in bar counts, OHLC sanity checks and price ranges; it only
    shows against the broker. PF and win rate survive it (a constant offset is a
    no-op for Supertrend) but **everything clock-keyed does not**: `skip_hours`,
    `time_exits`, and every hour-of-day table in these docs.
  - 19 has a built, tested fix (51) that is deliberately **switched off** — the
    backtest says flattening removes the only profitable cohort. Prompt 2 is a
    decision backed by one more measurement, not a build task.
- **Standing constraint:** the three live bots (GOLD, ETHUSD, US100) run on a
  **demo** account in `stockscreener-trading-bot-1`. Do not change live config,
  size, or bot state without explicit instruction. Research and tests are free;
  anything that reaches the broker is not.
- ✅ **DEPLOYED 2026-10-22 16:13 UTC — prompt 1 is CLOSED.** `trading-bot` and
  `bar-updater` are both running the current tree (gotcha **55**).
  **And read gotcha 55's lesson before trusting any deployment claim in these
  docs, this bullet included:** the line that used to sit here said nothing was
  deployed, and it was wrong — the `get_activity`/P&L fix had already been live
  for a day, so the stated justification for prompt 1 ("every close records
  pnl = 0.0") was false when it was acted on. **Measure instead — one command:**
  `python3 trading-bot-skills/check_deployed.py` (add `--quiet` for drift only;
  exits 1 if any container is behind the host tree).
- **Git state: as of the end of the seventh session the branch was 4 commits AHEAD of
  its upstream (`fdd0e7f`, `9bc0ec5`, `5aa7e7c`, plus the commit that wrote this line —
  the human had not yet said push), and
  no PR has been opened.**
  **Do not trust a hash quoted here — measure it.** This bullet has gone stale
  twice, the second time because the commit that updated it moved `HEAD` past
  the hash it had just recorded. So read the state instead of the prose:
  ```bash
  git status -sb                                  # ahead/behind vs upstream
  git log --oneline @{u}..HEAD | wc -l            # unpushed commits (4 at last handoff)
  git log --oneline origin/main..HEAD | wc -l     # ~40 and growing; nothing merged
  ```
  Open the PR in the browser (`gh` is not installed):
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
- Test commands (re-measured 2026-10-22, fifth session):
  `cd trading-bot-skills && python3 -m pytest` → **1319 passing, 0 failing** (~85s)
  `python3 -m pytest --cov` → **78.13%**, floor `fail_under = 75` (~165s)
  **Measure coverage on a clean tree.** Editing a source file mid-run makes
  coverage map recorded line numbers onto a shifted file, so covered statements
  report as missing — it showed `capital_api.py` at 91% when it was 100%
  (gotcha 54). Re-run before chasing a surprising gap.
  Full per-module status: see **Test coverage — status board** below.
  `python3 -m pytest tests/ -q` from repo root (research tools)
  **Never pass `--cov=<dotted.module.path>`** — it reloads numpy and fails ~47
  unrelated tests. Gotcha 43. Use bare `--cov` or `--cov=<package>`.

---

## Where to start — open prompts in priority order (as of the eighth session, 2026-10-23)

| # | prompt | size | why here |
|---|---|---|---|
| **3** | **SOLVED + DEPLOYED 2026-10-23 05:42 UTC** | — | The divergence was the live bot never applying the MA100 slope gate (CLAUDE.md gotcha 60). Its 105-bar buffer was too short for MA100 + a 20-bar slope, and the fallback made the gate allow everything. Live matches the slope-OFF backtest 82/95 (vs 1/95 for slope-on). Fix `eb9de2e` deployed. GOLD/ETHUSD now run the slope-on strategy as a demo **forward test**: ~60 GOLD trades, PF > 1.0 or stop (gotcha 60). |
| **11** | Re-base ETHUSD (then BTCUSD/EURUSD/SILVER) | medium | Mechanical, and the method is proven twice (GOLD, US100). ETHUSD first because it trades live, so the parity check applies. Needs your **"approve delete"** mid-session. Paste-ready prompt at the top of section 11. |
| **2** | Decide the flatten | medium | Needs the flatten simulated in `run_skills_backtest.py` first. **US100's weekend-carry cohort (gotcha 51) was measured on mid/local labels**, so re-measure it on the re-based bars as part of this. |
| **8** | Strategy research direction | large | Three levers measured and failed. Cost-per-unit-of-R is the cheapest untested one. US100 hour-of-day evidence is now correctly labelled (gotcha 57); ETHUSD's is not until prompt 11 does it. |
| **9** | Small open items | small | Includes the US100 `--quantity` fragility (gotcha 55) and the two latent clock bugs from prompt 11 item 3. Fold into any session. |
| **10** | Keep running these bots? | — | Standing question. Prompt 3 is still the prerequisite for answering it with evidence. |

**Closed:** 1 (deploy), 4 and 5 (coverage), 6 (UI backtests + GOLD data), 7 (zero-P&L rows).
Their prompts are retained below as closed markers so the numbering keeps resolving.

---

## What the 2026-10-22 / 10-23 sessions closed

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
| `capital_api.py` coverage (old prompt 5) | **done** — 19% → **100%**; `place_order` was at 0%. 2 live bugs fixed: `create_session`'s 429 branch was dead (`Response.__bool__` is `self.ok`), and `get_historical_prices` returned account-local timestamps, putting the live warm-up buffer 2h off the DB bars — which closes half of prompt 3's remaining lead (gotcha 54) |
| UI backtests lying — stale runner + GOLD data (old prompt 6) | **done** — runner rebuilt (56); GOLD re-based to bid/UTC with a full 199,400-bar re-fetch, volume now matches host on **99.999%** of common bars. The 25%-missing diagnosis was right but **incomplete** — see gotcha **57**. The final `DELETE` ran 2026-10-23 (row below) |
| GOLD phantom bars (prompt 11 item 1, 2026-10-23) | **done** — 7,886 orphans deleted (backup `/data/GOLD_M5_orphans_backup.json`); container run now **bit-identical** to host: 493 / 21.703853955375255% / PF 1.0555001992825828 / +$3,342. Refuted the documented "extra bars at the series start" explanation for the residual — the phantoms were occupying `--bars` window slots (gotcha 56). Also caught a bug in the handoff's own delete snippet that would have removed `bar_updater`'s post-CSV bars |
| US100 re-base (prompt 11 item 2, first half, 2026-10-23) | **done** — 203,260-bar re-fetch, 6,848 orphans deleted (backups `/data/US100_M5_orphans_backup.json` + full rollback `/data/US100_M5_pre_rebase_backup.json`). Baseline 2485 / PF 0.9749: the same summary as before by coincidence of fixed sizing, but only 990 of 2485 entries shared. Session moved 11–18 → 13–20 UTC; live entries matched by the backtest went 149 → **208 / 224** (gotchas 33, 57) |
| Aug–Oct zero-P&L `trade_history` (old prompt 7) | **done** — 381/381 matched, 0 unmatched, **−$1,672.63** recovered from rows the dashboard showed as `$0.00`. New `repair_zero_pnl.py`; **not** `backfill_trade_history.py`, which rewrites every field of every row in the window (gotcha 59) |

Four bugs the coverage work found in the live loop, all fixed and now **deployed**
(gotcha 55):
unconditional position-flag clearing (the real accumulation hole — every reverse
close is booked **twice**), invented `pnl=0.0`, booking a refused close before
checking the broker result, and an error handler that raised inside its own
`except`. Gotcha 49 has the detail.

---

## Test coverage — status board

**Measured 2026-10-22 (fifth session), canonically, on a clean tree.** Reproduce
with exactly:

```bash
cd trading-bot-skills && python3 -m pytest --cov -o addopts= -q
# -> 1319 passed, TOTAL 78.13%, "Required test coverage of 75.0% reached"
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
| **`clients/capital_api.py`** | **100%** | 0 | DONE | `test_capital_api.py` (**167**), `test_activity_parsing.py` (15) |
| `clients/capital_websocket.py` | 98% | 2 | DONE | `test_live_execution_and_socket.py` (87) |
| `core/stop_manager.py` | 97% | 3 | DONE | `test_stop_manager.py` (14) |
| `orchestrator/main.py` | 95% | 22 | DONE | `test_live_poll_loop` (66), `test_live_bootstrap` (63), `test_live_tick_exit` (102) |
| `core/operational_monitoring.py` | 95% | 12 | DONE | `test_operational_monitoring.py` (27) |
| `skills/execution/execution_skill.py` | 93% | 11 | DONE | `test_execution_skill` (8) + live suites |
| `core/idempotency.py` | 94% | 7 | DONE | `test_idempotency.py` (17), `test_capital_api` (1) |
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
| `clients/firestore_api.py` | 12% | 140 | LOW — largest remaining | — |
| `skills/reporting/reporting_skill.py` | 11% | 209 | LOW (lowest risk) | — |
| **TOTAL** | **78.13%** | 1143 / 5227 | floor `fail_under = 75` | 33 suites, **1319 tests** |

**`production_orchestrator.py` is deliberately not worth covering.** The live bot
never instantiates it (gotcha 19) — it is the only thing that reads `eod_hour`,
and it carries two known defects if anyone reaches for it (`datetime.now()` local
time compared against a UTC config hour, and `hour >= close_hour` true for every
later hour). Covering it would pin behaviour nobody runs. If it is ever revived,
**fix those two defects first**, then cover it.

**No risky module is under-covered any more.** `capital_api.py` — the broker
boundary and the last real gap — reached **100%** on 2026-10-22 (gotcha 54),
after `backtesting_skill.py` did the same (gotcha 53). Everything still marked
LOW is reporting, alerting, logging and firestore: nothing that can place an
order, price a trade, or compute a P&L figure.

The largest remaining block by raw count is `reporting_skill.py` (209) and the
largest by risk is `firestore_api.py` (140, the storage boundary), but neither
has an owner and neither is worth a session ahead of **prompt 1 (deploy)**,
which is now the only thing standing between five sessions of fixes and the
bots that are actually trading.

---

## 1. ~~Deploy the fix stack~~ — **DONE 2026-10-22 16:13 UTC**

> **STATUS: CLOSED.** `docker compose build trading-bot bar-updater && docker
> compose up -d trading-bot bar-updater`. Full record: `CLAUDE.md` gotcha **55**.
> Kept as a closed marker — prompt numbers are cross-referenced by number.
>
> **The prompt's own premise turned out to be false, and that is the thing to
> carry forward.** It claimed the live bots ran code where `get_activity()`
> returns `[]`, so "every close records `pnl = 0.0`, cooldowns never fire, both
> breakers are inert". The container already had that fix — `trade_history` rows
> from the two hours before the deploy read `−51.41`, `−6.79`, `+130.98`,
> `−11.16`, `−50.35` with real `SL_HIT`/`TP_HIT`. **Never infer deployment state
> from these docs; measure it** with
> `docker exec stockscreener-trading-bot-1 grep -c '<symbol>' /app/<file>`.
>
> **What it did deliver:** gate unification (41), candle dedup (42), the four
> orchestrator fixes (49), `core/time_exits.py` (51, still **off**), the
> Supertrend stop guard (50), `capital_api`'s UTC warm-up timestamps (54), and
> `bar_updater`'s `_norm_ts` (29) — the last of which was **visibly broken**:
> all six epics were frozen at `02:10` and the first post-deploy cycle inserted
> 1008 candles, bringing every epic to `16:10`.
>
> **Verified after:** three bots restored with quantities None/None/1.0, SL/TP
> 15/60 · 25/125 · 50/150, ETHUSD's `$150` daily cap the only one armed,
> consecutive-loss breaker off everywhere, flatten off everywhere, **zero
> ERROR/Traceback lines in any bot log**. Pre-deploy baseline: **0 open
> positions** (why that window was chosen), rollback image `sha256:6a54ba10a420`.
>
> ✅ **End-to-end close verification — completed 19:19 UTC, it PASSED.** This was
> left open at deploy time because the startup flip gate suppresses entries until
> the trend flips. The first post-deploy close: **US100 SELL, `pnl=132.3`,
> `exit_reason='TP_HIT'`**, entry 29095.4 → exit 28946.9 (148.5 pts against a
> configured TP of 150), `size=1.0`, `pnl_estimated=False`, `pnl_unknown=False`.
> A real number with a real reason — not `0.0`/`SIGNAL` — and the size confirms
> US100's `--quantity 1.0` survived the restart. 3h of running, zero errors.
>
> **`position_size` did not ride along** — verified in the deployed image, not
> assumed: GOLD/ETHUSD have it only under `backtesting:`, so the broker still
> gets 0.5. Gotcha 26 stands.
>
> **New finding worth its own follow-up:** US100's live size comes from
> `bot_state`, not its YAML. `risk.position_size: 1` propagates to nothing; only
> `--quantity` reaches `execution` (`main.py:909`). It survives restarts because
> `on_startup` replays the stored quantity — but **a US100 bot started from the
> UI without an explicit quantity silently trades 0.5.** Folded into prompt 9.
>
> **`backtest-runner` was deliberately NOT rebuilt** — that is prompt 6.

---

## 2. The flatten is BUILT but deliberately OFF — decide whether to enable it

> Read `CLAUDE.md` gotcha **51** first (what was built and the measurement that
> stopped it being switched on), then **19**, **10** and **27**.
>
> **Status 2026-10-22:** `core/time_exits.py` + gate + poll-loop close exist,
> 72 tests, module at 100%, and the code is now **deployed** (gotcha 55) with
> `enabled: false` on GOLD and US100, absent on ETHUSD. So the live bots **still
> carry positions over the weekend** — by choice, and now the switch is actually
> in the running image, so enabling it is a config change rather than a deploy.
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
> Only after that: flip the YAMLs, **rebuild** (config is baked into the image —
> gotcha 10; prompt 1 is closed but a config change still needs a build or a
> `docker cp` + restart), and watch one Friday. The close should land in
> `trade_history` with a real P&L from `get_realised_pnl`, not 0.00, since the
> flatten books nothing itself — and that reporting path is now **deployed and
> confirmed working** (gotcha 55), so the Friday check is a real measurement
> rather than a test of the plumbing.
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

## 3. The GOLD live/backtest divergence — **SOLVED 2026-10-23 (CLAUDE.md gotcha 60)**

> **Answer:** live never applied `bias_slope_bars: 20`. `main.py` sized the M5 buffer at 105 bars
> (MA bias left out of the warm-up `max()`), so `sma_bias_prev` was always NaN, and
> `_extract_indicators` substituted the current MA, which passes both slope directions. Trade-level
> match against live (95 trades, Aug 1–Oct 21): slope-on backtest **1/95**, slope-off backtest
> **82/95 same side, 81 same outcome**, with PF 0.697 vs live 0.685. ETHUSD has the same defect.
> Leads A/B and the ASK-vs-BID lead below were not needed and are retained as history.
>
> **Decided and deployed 2026-10-23 05:42 UTC (`eb9de2e`):** GOLD/ETHUSD now run the slope-on
> strategy as a demo forward test at unchanged size. The bar is ~60 GOLD trades with PF > 1.0, or stop (prompt 10). Re-match
> ETHUSD after prompt 11 re-bases its bars.

### History — the search, as written before it was solved

> **Paste-ready (2026-10-23):** Read CLAUDE.md gotchas 36, 33 and 57, then this
> section. Before testing any lead, run the **trade-level match** on GOLD: take
> live `trade_history` rows (`bot_id='gold_m5_bot'`, 2026-08-01..10-21) and the
> container backtest's `trades.csv` at `--bars 188534` (or the current row count),
> and match each live entry to a backtest entry within ±10 min. Report matched,
> same side and same outcome, then classify the unmatched live trades: the hour,
> whether the backtest was in a position at the time, and whether the backtest
> signalled on the same bar but was gated. US100 matched 208/224 that way (gotcha 33).
> If GOLD matches far fewer, the unmatched set *is* the divergence, and its
> profile says which lead below to test. Container backtests take ~20 min with
> buffered output; wait for `/data/results/GOLD/<run>/report.json`. Don't change
> live config, size or bot state.
>

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
> **NEW LEAD, 2026-10-22 — the live bot and the backtest run on DIFFERENT PRICE
> SIDES, and each half of the code claims to be the consistent one.** See gotcha 57.
> `capital_websocket._handle_ohlc` passes **only the ASK/OFR candle** to `on_candle`
> ("that's the price you pay to BUY"); `fetch_data.parse_candle` stores **bid**
> ("so that Supertrend and signal logic see the same prices the live bot sees").
> Both comments assert consistency with live; they cannot both be right, and
> `parse_candle`'s stated goal is not met by its own choice.
> - **Why it is not obviously the answer:** a *constant* additive offset is a strict
>   no-op for Supertrend, since ATR is built from differences —
>   `Supertrend(series + c) == Supertrend(series) + c`. So a fixed spread changes
>   nothing at all.
> - **Why it is still worth testing:** the spread is **not** constant — it widens at
>   news and at rollover — so the ask series is not the bid series plus a constant,
>   and flip *timing* can differ exactly when volatility is highest. That is a
>   mechanism for extra live flips, which matches the direction of the error
>   (live takes **more** trades, not fewer).
> - **Cheapest test:** re-fetch a GOLD window with `parse_candle` modified to take
>   `ask` instead of `bid`, backtest both, and compare trade counts and flip counts.
>   No deploy, no live risk. If ask-based backtesting moves 61 toward 93, this is it.
>
> **Two older untested leads also remain. Start with A — it is far cheaper, and it is
> the one whose failure mode matches the direction of the error.**
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
> **Narrowed 2026-10-22 — the *timestamp* half of Lead B is resolved, and it was
> a real defect.** `get_historical_prices` labelled candles with `snapshotTime`
> (account-local, UTC+2, DST-varying) while `fetch_data.parse_candle` stores
> `snapshotTimeUTC`, so the live **warm-up** buffer sat two hours off the DB
> bars — from the same endpoint. Fixed (gotcha 54b), with a regression test that
> asserts both functions pick the same field on one identical broker row.
> **This is not the divergence**, and do not spend the session re-deriving it:
> warm-up bars generate no signals (`warming_up = True`), the MTF `.asof()`
> consumers that *are* label-sensitive are gated by `require_h1_bb`, false on
> all three running bots, and it cannot make live take *more* trades. What
> remains of Lead B is the genuine question — **do the WebSocket-built bars and
> the REST bars have the same boundaries, and do the same bars exist on both
> sides** — which still needs live capture.
>
> **⚠️ Superseded 2026-10-23 — the rest of this paragraph is history.** GOLD is
> now broker-exact in **both** DBs and the container reproduces the host bit-for-bit
> (gotcha 56), so run in the container. Original note: GOLD's repaired bars are in the HOST
> `/data/trading.db`, not the live volume. Pin `DB_PATH` deliberately and say
> which DB every number came from. **Exact bar counts drift daily — read gotcha
> 53's closing correction rather than any count quoted here;** as of 2026-10-22
> the host DB is the better one for **both** GOLD and US100 (GOLD 188,466 /
> US100 202,994 vs the volume's 163,894 / 202,774), which inverts the original
> gotcha-24 advice.

---

## 4. ~~`backtesting_skill.py` coverage~~ — **DONE 2026-10-22**

> **STATUS: CLOSED. 59% → 100%, 111 uncovered → 0.** Do not re-run this prompt.
> The full write-up is **`CLAUDE.md` gotcha 53**; the suite is
> `tests/unit/test_backtest_engine.py` (**168 tests**, 31 classes).
>
> The number is kept here only so the cross-references from CLAUDE.md gotchas
> 39/44 and from prompts 5 and 6 still resolve — the prompt numbering is
> referenced by number in both files, so this section is retained rather than
> deleted and renumbered.
>
> **What it closed:** `get_results` (the PF/WR/expectancy aggregation),
> `check_exits` (SL/TP detection, same-bar precedence, the `max_hours` time
> exit), `_close_position` (P&L arithmetic, equity curve, drawdown ratchet),
> `_compute_position_size` (both dynamic-sizing modes, driven end-to-end across
> a winning *and* a losing sequence), `close_reverse_positions`,
> `validate_config`, `__init__`, `execute`, `reset`, `run_backtest`, `to_dict`.
>
> **Two fixes shipped** (both in gotcha 53 with the reasoning):
> 1. `profit_factor` reported **100x the gross win total** on a loss-free run —
>    `max(total_losses, 0.01)` was a divide-by-zero guard used as a *value*, so
>    one $60 win came out as PF 6000.0, and `optimize_params.py:71` ranks on it.
>    Now the 999.0 sentinel `live_report.py:54` already uses. Provably inert for
>    any run with ≥1 cent of losses.
> 2. The `_compute_position_size` docstring claimed 'steps' keys off *profit
>    above initial_capital*; it keys off **total capital from trade 1**, a 10x
>    understatement of starting size on gotcha 25's `+$733,912` mechanism.
>
> **Four more findings pinned as tests rather than changed** — GOLD's
> `dynamic_sizing` is inert (so gotchas 35/41/49's GOLD runs are *not*
> compounding-contaminated); a break-even trade is counted in `losing_trades`
> but not `total_losses`; `if exit_price:` drops a 0.0 TIME_EXIT (fails closed);
> `max_drawdown_pct` divides by peak equity ever reached, which is the origin of
> gotcha 28's "maxDD 1346%".
>
> **Also found:** the pre-existing `test_sl_hit_before_tp` was **vacuous** — it
> never called the skill and asserted `sl_hit or tp_hit`, so it could not fail,
> and it was the only cover for the SL-vs-TP precedence question. The code does
> make a documented choice (SL wins); now pinned for real.
>
> **Regressions re-run after the fix** (`DB_PATH=/data/trading.db`): US100 2y
> `2485 / 25.473% / PF 0.9728` — exact match; GOLD 2y `493 / 21.704% /
> PF 1.0555` — trades and WR exact, PF +0.0054 from the DB gaining bars, with
> the fix shown bit-identical on that run's own `trades.csv`.
>
> Suite **984 → 1152 passing**, TOTAL **72.67% → 74.80%**, floor **69 → 72**.
> Committed as `017327c`.

---

## 5. ~~`capital_api.py` coverage~~ — **DONE 2026-10-22**

> **STATUS: CLOSED. 19% → 100%** (213 statements, 0 missing).
> `tests/unit/test_capital_api.py`, **167 tests in 23 classes**.
> Full detail: `CLAUDE.md` gotcha **54**.
>
> Kept as a closed marker rather than deleted — prompt numbers are
> cross-referenced by number from gotchas 39, 44 and the small-items list below,
> and renumbering would break all of them.
>
> **What closed it.** `place_order` — the only call in the repo that can move
> money — was at **0% cover**. So were `_request` (the shared auth/retry/error
> layer everything flows through), `get_historical_prices`, `create_session`,
> `update_position`, `close_position` and `confirm_order`.
>
> **The harness is the transferable part.** No HTTP-mocking library is
> installed (`responses`, `requests-mock`, `pytest-httpserver` all absent) and
> none was added. The suite patches `requests.request` / `requests.post` and
> returns **real `requests.Response` objects**, because `Response.__bool__`
> returns `self.ok` and `raise_for_status()` must attach a genuine `HTTPError`.
> That is not fussiness: a hand-rolled fake response is *truthy*, and would have
> hidden the `create_session` bug below while making the test assert the wrong
> behaviour. An autouse fixture points `requests.request/post/get` at a raiser,
> so a missed patch fails loudly instead of dialling Capital.com.
>
> **Two live bugs fixed:**
> 1. `create_session`'s rate-limit branch was **dead code** — `if e.response and
>    e.response.status_code == 429`, and an error Response is falsy, so the one
>    status the branch exists to classify was the one it could never see. Impact
>    was cosmetic (the generic message still carries "Too Many Requests", which
>    `idempotency.is_transient_error` matches, and nothing retries session
>    creation) — fixed because the *shape* is the hazard.
> 2. `get_historical_prices` returned **account-local** timestamps
>    (`snapshotTime`, UTC+2, DST-varying) while `fetch_data.parse_candle:145` —
>    the DB/backtest writer reading the *same endpoint* — picks `snapshotTimeUTC`
>    and documents why. Two readers of one endpoint, two hours apart; the live
>    warm-up buffer was the one that was wrong. **This closes half of prompt 3's
>    remaining lead.**
>
> Also corrected: the docstring's own worked example passed `from`+`to`
> together, which this API rejects with a 400 (gotcha 30).
>
> **Six hazards pinned rather than fixed** — the date-range forwarding under
> (c) above, plus gotcha 54's (d)–(h) — each for a stated reason, most
> importantly `confirm_order` returning `{}` on failure (the caller then
> substitutes the dealReference for the dealId, bounded by the 60s REST
> reconcile) and `CAPITAL_ENVIRONMENT` being shadowed by the signature default
> (inert, and it fails towards *demo* — honouring it would newly make it
> possible to go live by editing a dotenv file). Gotcha 54 has all six.
>
> **Regression:** GOLD 2y = 493 / 21.703853955375255% / PF 1.0555001992825828 /
> +$3,342 — **bit-identical** to gotcha 53's documented float. US100 2y = 2488 /
> 25.482% / PF 0.97328 / −$12,880 vs 2485 / 25.473% / 0.9728, the +3 trades
> explained by its DB gaining 113 tail bars. Expected, and the point:
> `get_historical_prices` has three production callers, all the live warm-up in
> `main.py`, and **zero references anywhere in the backtest path** — the
> regression confirms, it is not the argument.
>
> **Still uncovered here: nothing.** `clients/firestore_api.py` (12%, 140) is
> the same shape of work and genuinely lower risk — it has no owner and no
> prompt, and it should not jump the queue ahead of prompt 1.

---

## 6. ~~Make UI backtests stop lying~~ — **DONE 2026-10-22 20:00; final DELETE done 2026-10-23**

> **STATUS 2026-10-22 20:00: items 1, 2 and 3 are all CLOSED.** The GOLD backfill
> turned out to be only half the problem — the bars that were already there were on
> the wrong price side and time base (**new gotcha 57**), which no bar count reveals.
> A 50k top-up made it *worse* (a series spliced across two conventions); the fix was
> a **full 199,400-bar re-fetch**, after which the volume matches the host on
> **99.999%** of common bars. **One step remains and it needs a human:** 7,887 phantom
> bars (hours 21–22, past GOLD's 21:00 UTC close) survive the re-fetch because
> `INSERT OR REPLACE` cannot remove labels with no true counterpart. Removing them is a
> `DELETE` on the live trading DB — see gotcha 56's closing bullet for the exact
> authoritative-set recipe.
>
> **Historical note — item 1 CLOSED, item 3 partly done, item 2 was the last blocker:**
> Read `CLAUDE.md` gotchas **25**, **29**, **48**, **24** and **55**.
>
> ### ✅ 1. Stale runner — FIXED. `docker compose build backtest-runner && docker compose up -d backtest-runner`.
> Verified after: `/app/run_skills_backtest.py` **992 lines == host**, and
> `reverse_signal_exit` present **2×** (was 866 lines / **zero**, calling
> `close_reverse_positions(...)` unconditionally). Configs now match the live
> bot on all three traded instruments — GOLD SL15/TP60 + `require_sma_bias` +
> `tick_exit` (**all three previously absent**), US100 ST(14, 1.5) +
> `require_h1_bb: false` (was **ST(7, 2.0) + true**), ETHUSD SL25/TP125 (was
> **45/170**). `check_deployed.py` reports **no drift on any container**.
>
> ### ⚠️ 2. THE REMAINING WORK — the live volume's GOLD history is still sparse.
> `DB_PATH` turned out to be **already pinned** per-service in
> `docker-compose.yml` to `/data/trading.db`, so containers were never at risk;
> gotcha 24's trap applies only to **host-run** scripts, where `.env` sets
> nothing. But the depth gap is real and it is the gotcha-29 starvation, never
> backfilled:
>
> | | host `/data/trading.db` | live volume (containers) |
> |---|---|---|
> | GOLD, all bars | 188,534 | 164,099 |
> | **GOLD, inside the 2y window** | **141,972** | **106,747 — 25% missing** |
> | US100 | 203,107 | 202,979 (near-identical) |
>
> **The bar-updater fix (gotcha 55) made the volume *current* — all six epics
> track to the minute now — but it does not backfill history.** So a UI-triggered
> GOLD backtest still produces a wrong number: thin data instead of wrong
> config. US100 is fine either way.
>
> **Do this:** backfill GOLD into the volume from inside a container, which is
> where `/data` is the volume, using **bar-count mode** (`--from/--to` is the
> path that was broken; `--bars N` always worked):
> ```bash
> docker exec stockscreener-backtest-runner-1 \
>   python3 fetch_data.py --epic GOLD --timeframe M5 --bars 50000
> ```
> 50,000 M5 bars ≈ 173 days, which spans the starved Q2–Q4 2026 quarters.
> Re-measure, repeat if the gap persists, then re-run the GOLD regression
> in-container (item 3).
>
> **Only AFTER that, consider pinning `DB_PATH` in `.env`.** Doing it now would
> point host-run backtests at the *thinner* GOLD data and make them worse — the
> host DB is currently the better one for GOLD (gotcha 53's correction). The
> ordering matters.
>
> ### ✅ 3. US100 regression — RUN, and it confirms the rebuild.
> | | trades | WR | PF | P&L | Reverse Signal exits |
> |---|---|---|---|---|---|
> | **container, after rebuild** | **2485** | 25.513% | **0.9749** | −$12,100 | **0** |
> | host documented (gotcha 54) | 2488 | 25.482% | 0.9733 | −$12,880 | 0 |
> | **same container, BEFORE rebuild** (gotcha 25) | 16,999 | — | — | **+$185,306** | **6,973** |
>
> The −3 trades are the container having **128 fewer tail bars** than the host —
> the same drift mechanism, with the sign flipped, that gave +3 in gotcha 54.
> Exit mix is **1851 SL / 634 TP**, against gotcha 28's documented 1849/632.
> **The fantasy numbers are gone.**
>
> **GOLD still cannot match** until item 2 is done — on 25% less data it takes
> fewer trades, and that is **data, not code**. Do not read a GOLD mismatch as a
> failed rebuild.
>
> ⚠️ **A 2y backtest inside the container is slow** — ~15% of a core, because it
> competes with the three live bots. The host run took ~4 min; in-container took
> far longer. Python also buffers the output, so the log looks dead while the run
> is fine: check progress with `test -f /data/results/<EPIC>/<run>/report.json`
> rather than by tailing the log. Results land in **`/data/results/`** (the
> volume), not `/app/results/`.

---

## 7. ~~Repair Aug–Oct `trade_history`~~ — **DONE 2026-10-22**

> **CLOSED: 381/381 rows matched a `/history/transactions` row, 0 unmatched.**
> Net P&L the dashboard had been showing as `$0.00`: **−$1,672.63** (us100 −1,481.61 /
> gold −202.41 / ethusd +11.39 / eurusd 0.00). One row is a genuine broker break-even
> and is now flagged as such; it is the only zero left. Done with a new
> **`trading-bot-skills/repair_zero_pnl.py`**, which touches only zero-P&L rows and
> only their P&L fields — **not** `backfill_trade_history.py`, which rewrites every
> field of every row in the window (see the warning now in gotcha 14). `exit_reason`
> is unrepairable by design: transactions carry no reason and activity is capped at 24h.
> Read **gotcha 59**.
>
> **Historical framing below.**

> Read `CLAUDE.md` gotchas **22** (how the zeros happened), **13** (the writer
> and its idempotency) and **14** (the backfill tool), plus **15** and **21**
> for the exact row shapes.
>
> **381 rows measured 2026-10-22** (this prompt said 365; re-count before you
> start, it is a `select` away). They carry `pnl=0.0` / `exit_reason=SIGNAL` because
> `_handle_close(deal_id, 0.0, '')` was the only close path while
> `get_activity()` was broken. The dashboard therefore shows real P&L only
> through 2026-07-31 and **0.00 for everything after** — US100 shows 223 of 231
> trades at zero. The live path is fixed **and deployed** (gotchas 22, 55) —
> confirmed by post-deploy rows carrying real P&L and `SL_HIT`/`TP_HIT` — but
> **historical rows will not self-heal**.
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

- **US100's live position size comes from `bot_state`, not its YAML** (gotcha
  55). `US100.yaml`'s `risk.position_size: 1` propagates to nothing — only
  `--quantity` reaches `execution` (`main.py:909`) — so US100 trades 1.0 only
  because it was launched with `--quantity 1.0`, which `on_startup` replays from
  `kv_store/bot_state`. **Start it from the UI without a quantity and it
  silently trades 0.5, with no hint in the YAML.** Cheapest fix is to propagate
  `risk.position_size` → `execution.position_size` the way the root key already
  does, but note that touches live sizing — read gotcha 26 first.
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
- **Coverage beyond prompts 4 and 5** (both closed — gotchas 53, 54): see the
  **Test coverage — status board**
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

---

## 11. Finish the bar-data repair — item 1 DONE; item 2's US100 half DONE 2026-10-23; ETHUSD/BTCUSD/EURUSD/SILVER remain

> **Paste-ready for the next session (ETHUSD):** Read CLAUDE.md, then this section
> and gotchas 57, 56, 58 and 33. Re-base ETHUSD's M5 bars to bid/UTC the way US100 was
> done on 2026-10-23:
> (0) back up **all** current ETHUSD M5 rows to `/data/ETHUSD_M5_pre_rebase_backup.json`;
> (1) `docker exec stockscreener-backtest-runner-1 sh -c 'cd /app && python3 fetch_data.py --epic ETHUSD --timeframe M5 --bars 300000 --output /data/ETHUSD_M5_full_authoritative.csv'`
> (ETHUSD trades 24/7, so 2 years is ~210k bars; ask for more and let the broker's
> history depth cap it, then check the date range you got);
> (2) find orphans (not in the CSV **and** `<=` its last bar), back them up to
> `/data/ETHUSD_M5_orphans_backup.json`, then STOP and show me the exact DELETE. I'll
> reply "approve delete";
> (3) re-run the ETHUSD baseline in the container with an explicit `--bars N`. Diff
> `trades.csv` against the previous run rather than trusting a summary match;
> (4) run the trade-level parity check against live `ethusd_m5_bot` trades for
> 2026-08-01..10-21 (±10 min, same side, same outcome), before and after;
> (5) update the gotchas that quote ETHUSD numbers (28, 32, 34, 57) and this file, then commit.
> Volume state at handoff: ETHUSD 220,485 M5 rows, 2024-03-08 → now (BTCUSD 220,480, EURUSD 172,214,
> SILVER 163,970). ETHUSD has no weekend gap, so expect **fewer** orphans than GOLD/US100. A 24/7 series has no closure hours for the +2h labels to fall into. If it has
> almost none, say so rather than assuming the method failed. Don't change live
> config, size or bot state. Don't push unless asked.
>
> Read `CLAUDE.md` gotchas **57** (the convention defect), **56** (what the GOLD
> re-fetch did and did not fix), **58** (`--years` is not a calendar window) and
> **24** (which DB is which).
>
> **Item 1 is closed.** Lesson for item 2's orphan cleanup: the auto-mode classifier
> blocks a `DELETE` on the live DB even after a plain "yes"; it passed once the human
> wrote an explicit **"approve delete"**. Stage the backup + exact command first, then
> ask for that wording rather than retrying.
>
> ### 1. ~~Delete GOLD's phantom bars~~ — **DONE 2026-10-23**
> 7,886 rows deleted (backup `/data/GOLD_M5_orphans_backup.json`); container run at
> `--bars 188534` = **493 / 21.703853955375255% / PF 1.0555001992825828 / +$3,342 / 107 winners**,
> bit-identical to the host. The "494 / +$1,686 / 105" expectation below was wrong — see
> CLAUDE.md gotcha 56. The original brief is kept for the record:
>
> #### (original) Delete GOLD's 7,887 phantom bars (cost already measured: 16 trades, −$996)
> The full re-fetch overwrote every *real* label but `INSERT OR REPLACE` cannot
> remove legacy labels that have no true UTC counterpart. What survives sits at
> **hour 21 (4,209 rows) and hour 22 (3,329)** — the +2h tail past GOLD's 21:00
> UTC close, Friday over-represented (2,088) — i.e. **bars during market closure.**
>
> Their cost is not a guess. Joining the post-re-fetch `trades.csv` against the
> authoritative CSV isolates them exactly: **16 trades entered on timestamps that
> do not exist in the broker's series, 2 wins / 14 losses, −$996.** Excluding them
> leaves 494 trades / +$1,686 / 105 winners — the same trade count as the host.
>
> The authoritative set is **`/data/GOLD_M5_full_authoritative.csv`** (199,400 rows,
> written by the re-fetch and still in the volume). Anything in `candles` for
> GOLD/M5 outside it is an orphan. Back up before deleting — it is bar data and
> re-fetchable, but the DB is live:
> ```python
> # inside a container (/data IS the volume), or on the host with DB_PATH set
> import csv, sqlite3, json
> auth = {r['timestamp'] for r in csv.DictReader(open('/data/GOLD_M5_full_authoritative.csv'))}
> con  = sqlite3.connect('/data/trading.db', timeout=30)
> rows = con.execute("SELECT timestamp,open,high,low,close,volume FROM candles "
>                    "WHERE epic='GOLD' AND timeframe='M5'").fetchall()
> # bound by the CSV's last bar: anything later is bar_updater's real data, not an orphan
> # (82 such bars on 2026-10-23 — the unbounded version deletes them too)
> mx   = max(auth)
> orph = [r for r in rows if r[0] not in auth and r[0] <= mx]
> json.dump(orph, open('/data/GOLD_M5_orphans_backup.json','w'))   # back up FIRST
> with con:
>     con.executemany("DELETE FROM candles WHERE epic='GOLD' AND timeframe='M5' "
>                     "AND timestamp=?", [(r[0],) for r in orph])
> ```
> Expect **199,400** GOLD M5 rows afterwards plus `bar_updater`'s post-CSV bars
> (measured 2026-10-23: 207,368 rows, **7,886** true orphans, 82 post-CSV bars kept). Then re-run the container backtest and expect it to land near
> **494 trades / +$1,686 / 105 winners**; the residual against the host's
> 493 / +$3,342 / 107 is the volume's ~10,866 extra bars at the series *start*
> re-phasing the run (gotcha 58), **not** a defect.
>
> ### 2. Decide whether to re-base the other five instruments — a scoping call, not a chore
> **US100 DONE 2026-10-23 (live volume only).** Result and method are in CLAUDE.md gotchas 33 and 57. Three things to carry forward:
> - **Back up the whole series before the re-fetch, not just the orphans.** `INSERT OR REPLACE` overwrites every real bar in place, so the orphan backup alone can't roll you back. US100's full pre-image is `/data/US100_M5_pre_rebase_backup.json`.
> - **Compare trade sets, not summaries.** On a fixed-size instrument (every trade exactly +TP$ or −SL$), two different runs can match to the last digit. US100 did: 2485 / PF 0.9748576652952666 both times, with only 990 shared entries.
> - **Re-check parity at trade level** (match live entries to backtest entries within ±10 min). That is what showed the re-base mattered (149 → 208 of 224); the aggregate WR/PF barely moved.
> Next: **ETHUSD** (live-traded, so the same parity check applies), then BTCUSD/EURUSD/SILVER. Re-fetching the host stray DB's US100 is optional: containers already see the good copy.
>
> US100, ETHUSD, BTCUSD, EURUSD and SILVER are all still mid/local, in **both** DBs.
> Re-fetching them is mechanically identical to what GOLD got:
> ```bash
> docker exec stockscreener-backtest-runner-1 python3 fetch_data.py \
>     --epic US100 --timeframe M5 --bars 210000 --output /data/US100_M5_full_authoritative.csv
> ```
> **But it moves every documented baseline for them** (gotchas 28, 31, 33, 56), and
> not in the way you would guess. The PF should barely move — a constant offset is a
> no-op for Supertrend — while the **session changes**, because `skip_hours` gates on
> the label. US100's intended 13:00–20:59 UTC session is currently gating
> **11:00–18:59**, so re-basing it re-runs the strategy on a *different two hours of
> the day* for the first time.
> - **Do it one instrument at a time, and re-measure its baseline in the same
>   session**, updating the gotcha that quotes it. A re-fetch without a re-measure
>   leaves this file quoting numbers from data that no longer exists.
> - Expect the orphan tail on each one too — same `INSERT OR REPLACE` limitation,
>   same authoritative-CSV cleanup.
>   **Bound the orphan test by the CSV's last timestamp** (`t not in auth and t <= max(auth)`),
>   or you also delete `bar_updater`'s post-CSV bars — item 1's original snippet had exactly
>   that bug. Back up the orphans to `/data/<EPIC>_M5_orphans_backup.json` first.
> - **Orphans contaminate `--bars N` runs in a non-obvious way** (item 1's finding): they
>   occupy window slots and push the start later, so a run looks merely "re-phased"
>   when it is actually on defective data. Measure baselines only *after* the cleanup.
> - Recipe, per instrument: re-fetch → bound+back up+delete orphans (needs the human's
>   explicit "approve delete") → re-run the baseline with an explicit `--bars N` →
>   compare against the old documented baseline (gotchas 31/33/56 for US100) and
>   **report the session change, not just the PF** → update the gotcha that quotes it.
> - **US100 is the one worth doing first**, because it is the only instrument with
>   established backtest↔live parity (gotcha 33), so it is the only place where a
>   session change can be *checked* against live rather than just observed.
>
> ### 3. While you are in here: two latent clock bugs worth one line each
> - `capital_websocket._handle_ohlc` builds its candle time with
>   `datetime.fromtimestamp(t / 1000)` — **naive local time.** The container's TZ is
>   empty so it resolves to UTC today; set a TZ and every live candle silently
>   shifts. Same family as gotcha 54(b) and `production_orchestrator.EndOfDayClose`.
> - `risk_skill.py:221`'s rejection message reads `"🚫 Skip hour: {ts_hour:02d}h UTC"`
>   and asserts UTC on whatever the bar label happens to be. On mid/local data that
>   message is actively misleading — it is what makes gotcha 57 hard to notice from
>   logs alone.
