# CLAUDE.md — Stock Screener / Trading Bot

Project context file for AI assistants. Read this before exploring the codebase.

> **Living document:** If during a session you search for something not documented here, discover a gotcha, or correct a wrong assumption — add it to this file before ending the response.

---

## What This Project Is

An automated trading system that:
1. Connects to **Capital.com** (broker) via REST + WebSocket
2. Runs strategy backtests on historical OHLCV data
3. Executes live/demo trades based on technical signals (Supertrend, EMA, etc.)
4. Serves a React dashboard for monitoring + triggering backtests
5. Streams structured logs to Firestore / SQLite

---

## Repository Layout

```
/opt/stockscreener/
├── trading-bot-skills/          # Core trading engine (Python)
│   ├── orchestrator/
│   │   ├── main.py              # ENTRY POINT — live/demo bot (python main.py --mode demo)
│   │   ├── trading_orchestrator.py  # Wires skills together, runs event loop
│   │   └── production_orchestrator.py  # Production-grade variant with circuit breakers
│   ├── skills/                  # Pluggable skill modules (each has __init__.py)
│   │   ├── analysis/analysis_skill.py   # Signal generation — EDIT THIS for strategy changes
│   │   ├── market_data/         # WebSocket bar ingestion from Capital.com
│   │   ├── execution/           # Order placement, Capital.com REST
│   │   ├── risk/risk_skill.py   # Cooldowns, hour filters, position sizing
│   │   ├── backtesting/         # BacktestingSkill — simulates fills from CSV
│   │   ├── storage/             # Firestore + SQLite writers
│   │   ├── monitoring/          # PnL tracking, health checks
│   │   ├── alerting/            # Telegram / Email / Slack notifications
│   │   └── reporting/           # PDF / HTML report generation
│   ├── core/
│   │   ├── event_bus.py         # Async pub/sub — all skills communicate via events
│   │   ├── indicators.py        # Supertrend, EMA, SMA, VWAP, RSI, MACD, BB, MTF
│   │   ├── signal_engine.py     # Reads indicator outputs → BUY/SELL/NONE
│   │   ├── sl_tp_engine.py      # SL/TP calculation (fixed/pct/atr/fibonacci/supertrend)
│   │   ├── position_state.py    # PositionStateManager — single source of truth for open positions
│   │   ├── circuit_breakers.py  # SpreadSlippageFilter, NewsEventKillSwitch, TradingSessionFilter
│   │   ├── idempotency.py       # Prevents duplicate orders
│   │   ├── cost_calculator.py   # Spread + slippage cost model
│   │   └── operational_monitoring.py  # Heartbeat, error rate tracking
│   ├── clients/
│   │   ├── capital_api.py       # Capital.com REST client
│   │   ├── capital_websocket.py # Capital.com streaming WebSocket
│   │   ├── firestore_api.py     # Firestore read/write wrapper
│   │   ├── sqlite_api.py        # Local SQLite persistence
│   │   ├── telegram_api.py      # Telegram bot alerts
│   │   └── log_publisher.py     # Structured log streamer
│   ├── config/
│   │   ├── trading_config.yaml  # BASE config — all default parameters
│   │   └── instruments/         # Per-instrument overrides (deep-merged over base)
│   │       ├── GOLD.yaml        # Primary instrument — best-backtested strategy
│   │       ├── SILVER.yaml
│   │       ├── EURUSD.yaml
│   │       ├── BTCUSD.yaml
│   │       ├── ETHUSD.yaml
│   │       └── US100.yaml
│   ├── run_skills_backtest.py   # ENTRY POINT — backtests (python run_skills_backtest.py --instrument GOLD)
│   ├── optimize_params.py       # Grid-search optimizer for SL/TP/indicator params
│   ├── fetch_data.py            # Download historical OHLCV bars from Capital.com
│   ├── bar_updater.py           # Incremental bar sync daemon (runs every 15 min)
│   ├── check_deployed.py        # Reports what is ACTUALLY deployed (gotcha 55) — run before trusting any "deployed" claim
│   ├── backtest_api.py          # FastAPI — :8010, triggered by frontend
│   └── bot_control_api.py       # FastAPI — :8020, start/stop bot from UI
│
├── cloud-function/              # API layer + data pipeline
│   ├── api/
│   │   ├── app.py               # FastAPI main app — :8000 (internal, behind nginx)
│   │   ├── capital_proxy.py     # Proxies Capital.com REST to frontend
│   │   ├── database.py          # SQLite access layer for the API
│   │   ├── external_data.py     # Economic calendar, macro regime, news
│   │   ├── live_report.py       # Real-time P&L endpoint
│   │   └── scheduler_proxy.py   # Proxy to backtest-runner
│   ├── src/
│   │   ├── api_server.py        # Strategy Optimization FastAPI server
│   │   ├── api_functions.py     # Core strategy/backtest logic used by API
│   │   ├── api_functions_enhanced.py  # Extended version with zone strategy
│   │   └── data_updater.py      # Calendar + news + macro refresh worker
│   ├── data/                    # Shared data volume (mounted by Docker)
│   │   ├── GOLD_M5_*.csv        # Historical bar data — source of truth for backtests
│   │   ├── news_headlines.json  # Latest news by instrument
│   │   ├── economic_calendar.json
│   │   └── macro_regime.json
│   └── tests/                   # Test suite — run with python -m pytest cloud-function/tests/
│
├── capital-connect/             # React frontend (TypeScript + Vite)
│   └── src/                     # Dashboard: live P&L, signal feed, backtest trigger
│
├── docker-compose.yml           # Full stack — see Services section below
├── deploy_bot.sh                # SSH deploy to Hetzner server
├── deploy_skills_bot.sh         # Deploy trading-bot-skills specifically
├── secrets/                     # GCP service account key (gitignored, mounted read-only)
└── .env                         # Local secrets — NEVER commit this file
```

---

## Services (Docker Compose)

| Service | Port (internal) | Purpose |
|---------|----------------|---------|
| `nginx` | `:3000` (host) → `:80` | Serves React UI + reverse proxies `/api` |
| `api` | `:8000` | FastAPI: Capital.com proxy, bot status, external data |
| `backtest-runner` | `:8010` | Runs `run_skills_backtest.py` jobs triggered by UI |
| `trading-bot` | `:8020` | Manages live/demo bot process via `bot_control_api.py` |
| `bar-updater` | — | Incremental bar sync every 15 min |
| `data-updater` | `:8001` | Calendar / news / macro refresh |

All services share a `trading_data` Docker volume mounted at `/data` (SQLite DB + results).

**There are TWO nginxes.** The compose `nginx` container binds **`127.0.0.1:3000` only** — it is not
reachable from the internet. Public traffic is served by a **host-level nginx** (Ubuntu package,
`/etc/nginx/sites-enabled/capitalunlimited.de`) which terminates TLS via certbot on `:443` and
reverse-proxies to `127.0.0.1:3000`. So the public URL is **https://capitalunlimited.de**, and the
only ports open to the world are 22, 80 (certbot redirect → 443) and 443. Editing compose's nginx
config does not touch TLS, the domain, or the redirect — those live on the host.

**No PHP, anywhere** (audited 2026-10-22 against the Hetzner CVE-2026-109618/109619 advisory): no
`php`/`php-fpm` binary, no `php*` dpkg package, no `.php` file in either repo, no PHP in any of the
six containers, and every `php`/`fastcgi` hit in `/etc/nginx` is commented-out Ubuntu boilerplate
(`sites-available/default`, `snippets/fastcgi-php.conf`) with no active `fastcgi_pass`. The stack is
Python + static React only. PHP advisories do not apply to this server — re-run the audit rather
than re-reading this line if it matters:
`which php php-fpm; dpkg -l | grep -i php; grep -rn 'fastcgi_pass' /etc/nginx/sites-enabled/`

---

## Instruments & Strategy

**Primary:** GOLD (XAU/USD) on M5 timeframe

**Current GOLD strategy (as deployed in live/demo bot):**
- Entry: M5 Supertrend(14×1.5) flip + MA100 bias + MA100 slope
  ⚠️ **Until 2026-10-23 05:42 UTC the MA100 slope gate NEVER applied in live**: the buffer was too short for it (gotcha 60).
  Fixed and DEPLOYED then. All live GOLD/ETHUSD history before that date is the slope-OFF strategy.
- SL: **15 pips** ($15/contract) | TP: **60 pips** ($60/contract) — R:R 1:4
  (verified in `GOLD.yaml` 2026-10-22: `risk.stop_loss_pips: 15` / `risk.take_profit_pips: 60`.
  This line said TP 40 and the table below said 45; both were stale. 60 is also what gotcha 35's
  "baseline SL15/TP60" measured, so the backtest numbers in this file are the live geometry.)
- EMA and SMA(25/30) filters **disabled** — MA100 bias is the only filter
- Tick exit enabled (Supertrend trail cross closes position in live mode)
- No reverse-signal exit — SL / TP / tick exit only
- **No EOD close — nothing force-closes a live position** (gotcha 19). The old
  "EOD close at 16:00 UTC" line here was never true of the live bot: exits are
  SL / TP / tick-exit only. A flatten mechanism now exists but ships **off** (gotcha 51).

**Config cascade (important):**
```
trading_config.yaml (base defaults)
    ↓ deep-merged with
instruments/GOLD.yaml (instrument overrides)
    ↓ _propagate_risk_to_sl_tp()
analysis.sl_tp values are overwritten by risk pip values
```
**Gotcha:** `risk.stop_loss_pips` / `risk.take_profit_pips` is the single source of truth for
SL/TP pips. `analysis.sl_tp.*` gets overwritten at load time — edit `risk`, not `analysis`.
**`risk.sl_pips` / `risk.tp_pips` do not exist and are read by nothing** (gotcha 52).

---

## Event Flow

```
Capital.com WebSocket
        │
        ▼
MarketDataSkill ──CANDLE_CLOSED──► AnalysisSkill ──SIGNAL_GENERATED──► RiskSkill
                                                                              │
                                                        RISK_APPROVED ◄───────┤
                                                              │
                                                              ▼
                                                       ExecutionSkill ──► Capital.com REST
                                                              │
                                              POSITION_OPENED / ORDER_FILLED
                                                              │
                                                              ▼
                                               StorageSkill + AlertingSkill
```

All communication is via `EventBus` (async pub/sub). Skills never call each other directly.

---

## Key Classes & Where to Find Them

| Class | File | Purpose |
|-------|------|---------|
| `TradingOrchestrator` | `orchestrator/trading_orchestrator.py` | Wires all skills, runs main loop |
| `ProductionOrchestrator` | `orchestrator/production_orchestrator.py` | Production variant with circuit breakers |
| `AnalysisSkill` | `skills/analysis/analysis_skill.py` | **Strategy logic lives here** |
| `RiskSkill` | `skills/risk/risk_skill.py` | Cooldowns, hour/day filters, sizing |
| `SignalEngine` | `core/signal_engine.py` | Combines indicator outputs → direction |
| `EventBus` | `core/event_bus.py` | Async pub/sub backbone |
| `PositionStateManager` | `core/position_state.py` | Open position tracking |
| `CircuitBreaker` | `core/circuit_breakers.py` | Spread/news/session kill-switch |
| `CapitalAPI` | `clients/capital_api.py` | All Capital.com REST calls |

---

## Running Locally

```bash
# Activate environment (venv location varies — check setup_env.sh or create one)
# python -m venv venv && source venv/bin/activate && pip install -r requirements.txt

# Run backtest (GOLD, from instruments/GOLD.yaml)
cd trading-bot-skills
python run_skills_backtest.py --instrument GOLD

# Run backtest with custom SL/TP
python run_skills_backtest.py --instrument GOLD --sl 15 --tp 40

# Run optimizer (grid search)
python optimize_params.py --instrument GOLD

# Start live bot (demo mode)
python orchestrator/main.py --mode demo --config config/trading_config.yaml

# Start full Docker stack
cd /opt/stockscreener
docker compose up -d

# Rebuild React UI
docker compose --profile build run --rm react-builder
```

---

## Configuration Rules

- **Indicators on/off:** Set `enabled: true/false` under `analysis.indicators.<name>`
- **Signal logic:** Set `require_*: true/false` under `analysis.signal_rules`
- **SL/TP:** Edit `risk.stop_loss_pips` / `risk.take_profit_pips` (not `analysis.sl_tp` — it gets
  overwritten at load time). **Not `risk.sl_pips`/`tp_pips`** — those are read by nothing (gotcha 52).
- **Cooldowns:** `risk.sl_cooldown_minutes` / `risk.tp_cooldown_minutes`
- **Session filter:** `risk.skip_hours: [0,1,...]` — list of UTC hours where **new entries** are blocked (open positions still exit normally). Honored by both live (`risk_skill.py:220`, config read at `:87`) and backtest (`--skip-hours` CLI flag, or the YAML value directly). Use to avoid low-liquidity sessions.
- **Consecutive-loss circuit breaker (opt-in, default OFF):** `risk.max_consecutive_losses: N` blocks all new entries after N losing trades in a row for `risk.consecutive_loss_cooldown_minutes` (default 120), then resets; a win resets the counter immediately. `0` = disabled. Backtest with `--set risk.max_consecutive_losses=4 --set risk.consecutive_loss_cooldown_minutes=720`. **Note:** on trend-followers this is a safety rail, not a profit lever — the GOLD/ETH sweep was non-monotonic/path-dependent (pausing can lock you out of the recovery leg), so it's left disabled on both.
- **Daily-loss limit (opt-in):** `risk.max_daily_loss_usd: X` halts new entries once the current UTC day's realised P&L breaches -X; auto-clears at UTC rollover. `0` = disabled. **Requires real $ P&L** at close — `on_position_closed(pnl=...)` now threads it from both live and backtest. Backtest with `--set risk.max_daily_loss_usd=150`. **Instrument-specific:** enabled on ETHUSD ($150 — improves return+DD+Sharpe there) but left OFF on GOLD, where it worsens results (trend lock-out). Same meta-pattern as the consecutive breaker: helps ETH, hurts GOLD.
- **EOD close / flatten:** `time_based_exits.eod_hour` is **DEAD** — read only by
  `production_orchestrator.py`, which the live bot does not run (gotcha 19). The live
  mechanism is `risk.time_exits` (per-instrument, Friday-specific, defaults off) — gotcha 51.
- **Position size:** the size the broker actually receives is `risk.position_size` /
  `execution.position_size`, defaulting to **0.5** at `execution_skill.py:51` — see gotcha 26,
  which is still live on GOLD and ETHUSD. `risk.position_size_pct` is read (`risk_skill.py:119`)
  but does not set the order size; **`risk.max_position_size` is a dead key** — present at
  `trading_config.yaml:173`, read by no production code.
- **Bot mode:** `bot.mode: AUTO` (trades) or `SIGNAL_ONLY` (logs only, no orders)

---

## Environment Variables (`.env`)

```env
# Capital.com credentials
CAPITAL_API_KEY=...
CAPITAL_USERNAME=...          # email or username (matches CAPITAL_USERNAME in main.py)
CAPITAL_PASSWORD=...
CAPITAL_ENVIRONMENT=demo      # demo | live

# GCP / Firestore
GCP_PROJECT_ID=...
GOOGLE_APPLICATION_CREDENTIALS=/secrets/service-account.json

# Telegram alerts (optional)
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

# Docker paths
DB_PATH=/data/trading.db
RESULTS_DIR=/data/results
DATA_DIR=/data
```

**Never paste real credentials into AI chat.** Use `YOUR_API_KEY_HERE` as placeholder.

---

## Data Files

| File | Location | Notes |
|------|----------|-------|
| `GOLD_M5_*.csv` | `cloud-function/data/` | ~2 years M5 bars, primary backtest data (not in git — lives on server or download via fetch_data.py) |
| `GOLD_M1_*.csv` | `cloud-function/data/` | M1 bars for exit validation (not in git) |
| `trading.db` | `/data/` (Docker volume) | SQLite: bars, trades, logs — **primary bar source for backtests** |
| `news_headlines.json` | `cloud-function/data/` | Per-instrument news (GOLD/SILVER/etc.) |
| `economic_calendar.json` | `cloud-function/data/` | High-impact event blocking |

---

## Bar Data: What's in the DB, How to Get More

### What's currently in `/data/trading.db`

> ⚠️ **The block below is from early 2026 and is badly stale — and worse, there are
> THREE different `trading.db` files. Read gotcha 24 (which DB is which) and gotcha 48
> (the GOLD bar repair landed in the host *stray* DB, not the live volume) before
> trusting any bar count or running a backtest.**

```
GOLD  M5   150,261 bars  from 2024-02-26  to 2026-04-10
GOLD  M1     1,395 bars  from 2026-04-08  to 2026-04-09  (short window — collect_m1_candles.py)
US100 M5       500 bars  from 2026-04-03  to 2026-04-07
```

### Check what's in the DB

```python
import sqlite3
conn = sqlite3.connect('/data/trading.db')
cur = conn.cursor()
cur.execute("SELECT epic, timeframe, COUNT(*), MIN(timestamp), MAX(timestamp) FROM candles GROUP BY epic, timeframe")
for r in cur.fetchall():
    print(f"{r[0]} {r[1]}  bars={r[2]:,}  {r[3]} → {r[4]}")
conn.close()
```

Or via bash:
```bash
sqlite3 /data/trading.db "SELECT epic, timeframe, COUNT(*), MIN(timestamp), MAX(timestamp) FROM candles GROUP BY epic, timeframe;"
```

### Fetch / refresh bars from Capital.com

```bash
cd trading-bot-skills

# Download last N bars into SQLite (no CSV needed)
python fetch_data.py --epic GOLD --timeframe M5 --bars 50000

# Download with a date range
python fetch_data.py --epic GOLD --timeframe M5 --from 2026-04-01 --to 2026-04-10

# Export to CSV as well
python fetch_data.py --epic GOLD --timeframe M5 --bars 50000 --output ../cloud-function/data/GOLD_M5_latest.csv

# Fetch M1 bars for exit validation
python fetch_data.py --epic GOLD --timeframe M1 --bars 5000
```

The `bar_updater.py` daemon runs every 15 min inside Docker and keeps the DB current automatically.
The `run_skills_backtest.py` will auto-fetch missing/stale bars before running.

---

## Fetching Live Trades from Capital.com

Trades are fetched via two endpoints:

| Endpoint | Param support | Used For |
|----------|--------------|---------|
| `GET /api/v1/history/activity` | `lastPeriod` only — **max 86400s (24h)**; `from/to` returns 400 | Reconstructing open/close pairs + exit reason (SL/TP/USER) |
| `GET /api/v1/history/transactions` | **supports `from/to` date strings** OR `lastPeriod` (max 86400s) | P&L per trade |

**Critical gotcha:** `activity` does NOT support `from/to` or `lastPeriod > 86400`. For historical trade analysis beyond 24h, use `transactions` with `from/to` for P&L, but you cannot reconstruct entry price / direction for older trades.

### Quick fetch example

```python
import sys
sys.path.insert(0, 'trading-bot-skills')
from dotenv import load_dotenv; load_dotenv('.env')
from clients.capital_api import CapitalAPIClient

client = CapitalAPIClient(environment='demo')
client.create_session()

# Activity: last 24h only (hard cap — anything > 86400s returns 400)
activities = client._request('GET', '/api/v1/history/activity', params={
    'lastPeriod': 24 * 3600,        # max allowed
    'detailed': 'true',
    'filter': 'type==POSITION;status==ACCEPTED'
}).json().get('activities', [])

# Last 7 days of transactions (P&L)
txns = client._request('GET', '/api/v1/history/transactions', params={
    'lastPeriod': 7 * 24 * 3600
}).json().get('transactions', [])
gold_txns = [t for t in txns if t.get('instrumentName') == 'GOLD' and t.get('transactionType') == 'TRADE']
```

### Existing analysis scripts (root of repo)

| Script | What It Does | Notes |
|--------|-------------|-------|
| `trade_analysis.py` | Trade-by-trade comparison using activity events + transactions. Update `FROM_DATE`/`TO_DATE` and `BT_CSV` path at top of file before running. | Activity limited to 24h — only works for very recent trades |
| `compare_live_vs_backtest.py` | P&L-only comparison using transactions `from/to` — works for any historical window. Points to `results/GOLD/<run_id>/trades.csv` | Use this for multi-day comparisons |
| `compare_gold_trades.py` | Quick summary — trade count, win rate, P&L | Older script |
| `bar_timeline.py` | Timeline view of bars | |
| `m1_exit_backtest.py` / `m1_exit_sim.py` | M1-level exit analysis | |
| `exit_timing_sim.py` | Simulate different exit timing strategies | |

---

## Live GOLD Strategy Parameters (as deployed)

> ⚠️ **This table is an Apr-2026 screenshot artefact and FOUR of its "confirmed live" rows were
> wrong as of 2026-10-22.** The rows are corrected below, but prefer reading `GOLD.yaml` directly —
> it is committed and the working tree is clean, so the old "has uncommitted local changes"
> warning that stood here no longer applies.

**Original note (Apr 2026), kept for provenance:** a live trade screenshot showed SL distance
15.75 / TP distance 39.25, read at the time as confirming SL=15/TP=40. The SL still matches; the
TP does not — `risk.take_profit_pips` is now **60**, so that screenshot predates a TP change.

| Parameter | Deployed (confirmed live) | Git HEAD (stale) |
|-----------|--------------------------|-----------------|
| Supertrend ATR period | 14 | 14 |
| Supertrend multiplier | 1.5 | 1.5 |
| EMA filter | disabled | disabled |
| SMA(25/30) filter | disabled | disabled |
| MA100 bias | **enabled** (`require_sma_bias: true`) | not present |
| Stop loss | **15 pips** ($15/contract) | 20 pips |
| Take profit | **60 pips** ($60/contract, 1:4 R:R) — was wrong here as 45 | 60 pips |
| Tick exit | **enabled, `reverse_on_loss: false`** | not present |
| Position size | **0.5** — the `execution_skill.py:51` default (gotcha 26). The `10` is under `backtesting:` only, so it never reached live | 10 (`backtesting:`) |
| EOD close | **none** — `time_based_exits` is dead in the live bot (gotchas 19, 51). This row claimed 16:00 UTC and was never true | dead key |

### Correct backtest command to match live

```bash
cd trading-bot-skills

# --instrument GOLD already has all correct live params (SL=15, TP=60, MA100 bias)
# NOTE: backtest size comes from backtesting.position_size = 10; live trades 0.5 (gotcha 26),
# so backtest P&L magnitudes are ~20x live. PF/WR are unaffected.
# Note: tick exit (profit trail) is not simulated — backtest exits are SL/TP only
python run_skills_backtest.py --instrument GOLD --bars 1500
```

### To deploy the local uncommitted changes

```bash
# Commit then deploy
cd /opt/stockscreener
git add trading-bot-skills/config/instruments/GOLD.yaml
git commit -m "Update GOLD strategy: SL=15/TP=40, MA100 bias, tick exit"
./deploy_skills_bot.sh
```

### Checking what config the live bot is actually running

```bash
# SSH in and grep the deployed GOLD.yaml
ssh -i ~/.ssh/stockscreener_server root@204.168.191.150 \
  "grep -E 'stop_loss|take_profit|tick_exit|require_sma_bias' /opt/trading-bot-skills/config/instruments/GOLD.yaml"

# Or check bot startup logs (shows SL/TP at init time)
ssh -i ~/.ssh/stockscreener_server root@204.168.191.150 \
  "grep -E 'SL:|TP:|tick_exit|sma_bias' /opt/trading-bot-skills/logs/bot-output.log | tail -20"
```

> **Gotcha — deploy uses rsync, not git:** `deploy_skills_bot.sh` rsyncs local files directly to the server. Uncommitted changes to `GOLD.yaml` (or any config) **will be deployed** when you run the script, even if they haven't been committed. Always check `git status` before deploying to know exactly what's going to the server.

---

## Git Repositories — Two Separate Repos

The project has **two independent git repositories**:

| Repo | Root | What's in it |
|------|------|-------------|
| Main repo | `/opt/stockscreener/` | Bot engine, configs, deploy scripts, cloud-function, CLAUDE.md |
| UI repo | `/opt/stockscreener/capital-connect/` | React frontend (TypeScript + Vite) |

| UI repo | `/opt/stockscreener/capital-connect/` | separate remote: `github.com/bhattkirtan/capital-connect.git` |

**Gotcha:** `git status` at `/opt/stockscreener/` will NOT show changes inside `capital-connect/` — it's a nested repo, not a subdirectory tracked by the parent. Always `cd capital-connect` and run git commands separately for UI changes.

**⚠️ The UI repo has unpushed and uncommitted work that the main repo's `git status` hides (2026-10-22).** `capital-connect` is **2 commits ahead of its own `origin/main`** (`cf45988` live trade-history table + per-bot selector, `331efb5` chart the live results) **and carries an uncommitted 176-line change to `src/pages/Performance.tsx`.**
- That uncommitted diff is **the feature gotcha 18 documents as done** — the trade-history row filters (Side / Result / Reason / Instrument, four `FilterChips`) and sortable columns. It is finished, not WIP: `npx tsc --noEmit -p tsconfig.app.json` reports only the pre-existing `MonthlyPnlChart.tsx:85` error (gotcha 17). But it exists in **no commit**, so one `git checkout` deletes a documented feature.
- Per gotcha 17, what nginx serves comes from the `react_dist` volume, so the running dashboard and this working tree can disagree independently of git.

**Push credentials (2026-10-22).** Egress from this box works (`curl https://github.com` → 200); the long-standing "pushing is impossible here" note was only a missing credential. A `credential.helper store` entry is now cached, so **`git push` works from this box for the main repo**. `gh` is still **not** installed — open PRs in the browser. Pushing is still an explicit-request action, not a default, and **never hunt for tokens on disk** to get around an auth failure.

```bash
# Commit UI changes
cd /opt/stockscreener/capital-connect
git add src/...
git commit -m "..."

# Commit bot/config changes
cd /opt/stockscreener
git add trading-bot-skills/...
git commit -m "..."
```

---

## Testing

```bash
# Run all tests
cd cloud-function
python -m pytest tests/ -v

# Run specific test
python -m pytest tests/test_backtester.py -v

# Integration test (requires live Capital.com credentials)
python trading-bot-skills/test_api_connections.py
```

Tests use real logic — no mocked backtester. SQLite-backed tests hit a real DB.

---

## Deployment

- **Server:** Hetzner CX33, Helsinki — `204.168.191.150`
- **SSH key:** `~/.ssh/stockscreener_server`
- **Deploy bot:** `./deploy_skills_bot.sh`
- **Deploy full stack:** `./deploy_bot.sh`
- **Logs on server:** `journalctl -u trading-bot -f` or `tail -f /opt/trading-bot/logs/bot-output.log`

---

## Common Gotchas

> **Two kinds of claim in this file rot silently. Both have now caused a wrong
> decision, so check rather than trust:**
>
> 1. **Line numbers are indicative, not authoritative.** They drift whenever a
>    file grows — several in this file were shifted by edits made in the very
>    session that wrote them. **Grep the symbol instead:**
>    `grep -n '<symbol>' trading-bot-skills/<file>`. A stale line number is
>    harmless; a stale line number you *trusted* sends you to the wrong code.
> 2. **Deployment state cannot be known from prose.** On 2026-10-22 a deploy was
>    carried out on this file's claim that the live bots ran broken code; they
>    had not for a day (gotcha 55). **Run `python3 trading-bot-skills/check_deployed.py`**
>    — it measures the running containers, reports per-fix drift against the host
>    tree, and exits non-zero when a container is behind.
>
> Config *values* (SL/TP, sizes, flags) also drift — prefer the YAML, or the
> script above, over any table here. Gotchas 11, 50 and 52 are all the same
> lesson.

1. **SL/TP config source:** Always edit `risk.stop_loss_pips` / `risk.take_profit_pips` — not `analysis.sl_tp`, which the propagation function overwrites at load time. **The keys are NOT `risk.sl_pips`/`risk.tp_pips`** — this file said that in three places until 2026-10-22 and nothing reads them; see gotcha 52.

2. **Warm-up bars:** `buffer_size` in config is overridden at runtime to `max_indicator_period × WARMUP_MULTIPLIER (3)`. Don't worry about it manually.

3. **Timeframe resampling:** `market_data.resample_to` can resample M5 data to M10/M15/M30 without downloading new data. Useful for testing longer timeframes quickly.

4. **Instrument config merge:** Changes to `trading_config.yaml` base values may be silently overridden by `instruments/GOLD.yaml`. Always check the instrument file if your config change has no effect.

5. **`bot.mode: AUTO` vs `SIGNAL_ONLY`:** In `SIGNAL_ONLY` mode, no orders are placed. Use this to verify signals before going live.

6. **EOD close default — this entry was WRONG and is corrected here.** EOD close is **not** enabled anywhere that matters: `time_based_exits.eod_hour: 16` is read only by `production_orchestrator.py`, which the live bot does not run, and no backtest path reads it either. The backtester **does** implement one time exit — a max-hold from `time_based_exits.max_hours` (`backtesting_skill.py:408`) — but the base config sets `max_hours: 0`, so it is inert. So live and backtest currently "match" by both carrying positions indefinitely. See gotcha 19 for the confirmed −$153 weekend-gap cost and gotcha 51 for the opt-in replacement (`risk.time_exits`).

7. **Docker volume:** The `trading_data` volume persists between restarts. If the DB is corrupt or you want a clean slate: `docker compose down -v` (destroys all data).

8. **Capital.com pip size:** GOLD pip_size = 1.0 (dollar per pip per contract). Forex pairs use 0.0001. Always verify pip_size when adding a new instrument.

9. **Tick exit has two distinct modes — only profit-trail mode is active:**
   - `on_price_tick()` in `analysis_skill.py:448` is only called from the live WebSocket quote stream — never in backtest
   - **Profit-trail mode (GOOD, enabled):** When in profit, trails the Supertrend band; check interval shrinks from 3min → 2min → 1min → every tick as profit grows. Locks in gains before TP if trend reverses.
   - **Reverse-on-loss mode (DANGEROUS, now disabled):** When in a loss and ST trail crosses, closes position and opens a new trade in the opposite direction. Fires every `loss_check_interval_sec` (180s). Confirmed root cause of Apr 7-10 divergence: 18 live trades / -$315 vs 10 backtest / +$219. **Disabled via `reverse_on_loss: false`.**
   - `loss_check_interval_sec` is effectively unused while `reverse_on_loss: false`
   - Backtest exits are always clean SL/TP — tick exit gap still exists, but profit-trail exits are minor and acceptable

10. **Deployment is Docker, not systemd — and Claude may be running ON the server:**
    - The live bot runs in the **`stockscreener-trading-bot-1` Docker container** (compose service `trading-bot`, launched as `uvicorn bot_control_api:app` on :8020). There is NO active `trading-bot-skills` / `trading-bot` systemd unit — those are `not-found/failed`.
    - **Config is baked into the image at build time** (`Dockerfile COPY` → `/app/config`). The container mounts only `trading_data:/data` and `./secrets:/secrets:ro` — it does **not** mount `config/` from the host. So editing host YAML alone does nothing until you rebuild or copy the file in.
    - The two live bots (`gold_m5_bot`, `ethusd_m5_bot`) are child processes spawned by `bot_control_api`. `on_startup` (`bot_control_api.py:394`) **auto-restores whichever bots were running** from `kv_store(collection='bot_state')` in `/data/trading.db` (survives container restart/recreate). Each restored bot re-reads its YAML fresh from `/app/config`.
    - **Config-only hotfix (no image rebuild), works when running on the server:**
      ```bash
      docker cp trading-bot-skills/config/instruments/ETHUSD.yaml stockscreener-trading-bot-1:/app/config/instruments/ETHUSD.yaml
      docker restart stockscreener-trading-bot-1   # on_startup restores bots, re-reads config
      ```
      Persists across `docker restart` but is **lost on image rebuild / `docker compose up` recreate** — the durable fix is committing the YAML and rebuilding.
    - **Durable deploy:** `docker compose build trading-bot && docker compose up -d trading-bot`. ⚠️ Build context is `./trading-bot-skills`, so a rebuild bakes in **all uncommitted changes** in that tree (e.g. WIP edits to `bot_control_api.py` / `main.py`) — check `git status` first.
    - The old rsync/SSH path (`deploy_skills_bot.sh` from a laptop) still exists but the SSH key isn't present in every environment; verify where you are with `docker ps` first.

11. **All instrument YAMLs have `execution.environment: demo` as a no-live-trading guard:**
    - Added to GOLD, SILVER, EURUSD, BTCUSD, ETHUSD, US100
    - All instruments now have `execution.epic:` set (ETHUSD was missing this entirely — would have failed to connect)
    - All instruments now have `risk.reverse_signal_exit: false`
    - ⚠️ **This bullet's SL/TP list was a snapshot of the moment and is now wrong on HALF the instruments — three were retuned afterwards.** It said "standardised to 1:3 R:R across all instruments: GOLD 15/45, SILVER 1/3, EURUSD 20/60, BTCUSD 400/1200, ETHUSD 25/75, US100 35/105". Measured 2026-10-22:
      | instrument | SL | TP | R:R | what changed |
      |---|---|---|---|---|
      | GOLD | 15 | **60** | **4.0** | TP widened (`1597d45`) — the 15/45 here is stale, as is gotcha 50's copy of it |
      | ETHUSD | 25 | **125** | **5.0** | TP widened to the SL/TP-sweep optimum (`1b2b3c2`) |
      | US100 | **50** | 150 | 3.0 | SL widened 35 → 50 (`70dd071`) |
      | SILVER | 1 | 3 | 3.0 | unchanged |
      | EURUSD | 20 | 60 | 3.0 | unchanged |
      | BTCUSD | 400 | 1200 | 3.0 | unchanged |
      So **"1:3 across all instruments" is no longer true of any of the three that trade** — GOLD is 1:4 and ETHUSD 1:5. The rest of this gotcha's claims were re-verified and all still hold: every instrument sets `execution.environment: demo`, every one sets `execution.epic`, and every one sets `risk.reverse_signal_exit: false`.

12. **Capital.com API lookback limits (confirmed):**
    - `/history/activity`: `lastPeriod` only, **hard cap 86400s (24h)**. `from/to` params return 400. Use only for same-day trade reconstruction.
    - `/history/transactions`: supports `from/to` date strings (e.g. `'2026-04-07T00:00:00'`) for multi-day P&L. Use this for historical comparisons.
    - Activity filter syntax: `type==POSITION;status==ACCEPTED` (semicolon-separated). Filter by epic client-side — adding `epic==GOLD` in the filter param causes 400.

13. **`trade_history` — was never written; FIXED 2026-07-31. Read this before touching live P&L:**
    - Path: UI Performance → Live tab → `GET /live/report` → `live_report.py:214` → `db.kv_get_all("trade_history")` (reads **`kv_store`**, not `append_log`).
    - **The original bug (two independent causes):**
      1. Config key mismatch — `trading_config.yaml` declares `trades: "trade_history"` under `storage.firestore.collections`, but `StorageSkill.__init__` looked up `'trade_history'` and silently fell back to `'test_trades'`.
      2. No writer existed at all — `self.trades_collection` was assigned and never referenced. `close_position()` only patched the `active_positions` row to `status: CLOSED`.
    - **Fix:** `StorageSkill._record_trade()` writes a full trade record on every close; `close_position()` / `on_position_closed()` both call it. `sqlite_api.save_trade()` writes to `kv_store` keyed by `deal_id`, so a duplicate close event (activity poll *and* REST reconcile can both fire) is an idempotent overwrite, not double-counted P&L.
    - **P&L precedence:** the `pnl` threaded from `_handle_close` comes from Capital.com activity `details.profit` and is authoritative (net of spread/fees). `_record_trade` only falls back to `(exit-entry)*size` arithmetic when the broker gave nothing, and flags it with `pnl_estimated: true`.
    - **Never use `active_positions` closed rows as a P&L source:** `close_price` is `0.0` on all of them and there is no `realized_pnl`; `pnl` is a stale unrealized snapshot.
    - **`opened_at` clobbering (fixed at the same time):** `_save_position` re-runs on every ~60s REST reconcile. Its `datetime.now()` fallback used to overwrite `opened_at` each pass, so every trade's recorded hold time collapsed to seconds. It now preserves an existing `opened_at`, and `_persist_open_position` passes the broker's `createdDateUTC`.
    - Regression cover: `tests/unit/test_trade_history.py`.

14. **Backfilling historical trades — `backfill_trade_history.py`:**
    - Joins `/history/transactions` (realised P&L + `dealId`) against `kv_store/active_positions` (entry price, direction, size, SL/TP, `opened_at`) on `dealId`. Rows with no matching position are still written, P&L-only, flagged `partial: true`.
    - `cd trading-bot-skills && python3 backfill_trade_history.py --days 120 [--dry-run] [--instrument GOLD] [--db PATH]`
      — the script lives in **`trading-bot-skills/`**, not the repo root as this line used to imply.
    - ⚠️ **It is repeatable but NOT safe to re-run blindly — it rewrites EVERY field of EVERY row in the
      window.** `sqlite_api.save_trade` is `INSERT OR REPLACE` keyed on `deal_id`, and `build_trade`
      reconstructs each row from the `active_positions` row, so a `--days 120` run rewrites all ~2,580
      already-correct rows in order to repair the broken ones. Measured 2026-10-22, the damage is narrow
      (it hardcodes `entry_time_estimated: True`, which the gotcha-13 fix made untrue for rows written
      after it — 10 rows affected; 17 rows with no position row already carry zeros), but there is no
      reason to accept it: **to repair only the zero-P&L rows, use `repair_zero_pnl.py` instead** (gotcha 59).
    - Run against the live DB from the host at `/var/lib/docker/volumes/stockscreener_trading_data/_data/trading.db`, or inside a container at `/data/trading.db`.
    - **2026-07-31 run:** 2573 trades over 120 days, 2556 (99.3%) joined to a position row.

15. **Capital.com `/history/transactions` quirks (confirmed 2026-07-31 — corrects gotcha 12):**
    - **`size` is the realised P&L, not the position size.** There is no `profitAndLoss` field. A TRADE row is: `date`, `dateUtc`, `instrumentName`, `transactionType`, `note`, `reference`, `size` (=P&L string), `currency`, `status`, `dealId`.
    - **`lastPeriod` is capped at 86400s here too** — `lastPeriod=604800` returns 400. Gotcha 12 previously implied transactions had no such cap; it does.
    - **A `to` in the future returns 400 `error.invalid.daterange`.** Clamp `to` to now.
    - **Responses are hard-capped at 100 rows and `pageSize`/`pageNumber` are ignored.** The only way to get full coverage is date-window chunking (`backfill_trade_history.py` uses 12h windows and warns when a window hits the cap).
    - `dealId` in transactions matches the `deal_id` / doc_id in `kv_store/active_positions` — this is the join key for full trade reconstruction.
    - Creating sessions in a tight loop gets you 400s on `/session`. Reuse one client.

16. **Stop management: broker-side vs tick exit — two different mechanisms:**
    - **Broker-side (`core/stop_manager.py`, added 2026-07-31, DEFAULT OFF):** amends the stop order held at Capital.com via `PUT /positions/{dealId}`. Survives a dropped WebSocket, a bot crash, or a container restart. Config under `risk.stop_management` — `breakeven` (move stop to entry±offset once N pips in profit) and `trailing` (stop follows the best price at a fixed distance). Driven from the live quote stream, wired in `main.py`'s `on_quote`; position state synced by `_poll_positions`.
      - Invariants (covered by `tests/unit/test_stop_manager.py`): stops only ever tighten, never widen; trailing measures from the *best price since entry* so a pullback can't loosen it; a candidate stop through the current price is rejected; a failed amend leaves tracked state untouched so it retries; the broker's stop wins on resync.
      - **Not simulated by `run_skills_backtest.py`** — backtest exits remain clean SL/TP. Enabling it makes live diverge from backtest.
    - **Tick exit (`analysis_skill.py:448`):** does NOT touch the broker stop. Publishes `EXIT_SIGNAL` and closes the position at market when price crosses the M5 Supertrend band. Live-only (WebSocket ticks), at most once per M5 bar.
    - `execution.trailing_stop: false` in `trading_config.yaml` is a **dead flag** — no code reads it. Don't confuse it with `risk.stop_management`.
    - Before the stop manager, the only broker-side protection was the fixed entry SL, and `capital_api.update_position()` was called nowhere outside tests.

17. **UI deploys go through the `react_dist` volume, not the host `dist/`:**
    - `docker compose --profile build run --rm react-builder` runs `npm ci && npm run build` in a node:20-alpine container that mounts `./capital-connect` at `/app` and the **`react_dist` volume** at `/app/dist`. nginx mounts that same volume read-only at `/usr/share/nginx/html`. Editing `capital-connect/src` and rebuilding locally (`npm run build` on the host) writes to the host `dist/` and changes **nothing** that nginx serves.
    - `npm run build` is `vite build` only — no `tsc`. Typecheck separately with `npx tsc --noEmit -p tsconfig.app.json`. There is a **pre-existing** error in `MonthlyPnlChart.tsx:85` (recharts `number[]` domain prop); it does not block the build.
    - To confirm what is actually being served: `docker exec stockscreener-nginx-1 ls -la /usr/share/nginx/html/assets` and compare the hash against `curl -s http://localhost:3000/ | grep -o 'index-[A-Za-z0-9_-]*\.js'`.

18. **Diagnosing "the dashboard doesn't work" — read the nginx access log first:**
    - `docker logs stockscreener-nginx-1 --tail 2000 | grep -E "live/report|auth/login"` shows exactly what the browser requested, the status code, and the response size per request. Browser rows are gzipped (~4.5:1) so they look much smaller than the same request made with `curl` — size differences between bots, not against curl, are what tell you the payload actually varied.
    - The bot filter chips on Performance → Live (`Performance.tsx`, `LIVE_BOT_IDS`) are verified working end to end: each chip issues `GET /live/report?bot_id=…` and the backend filters on the trade's `bot_id` field. Trade counts as of 2026-07-31: gold 403, ethusd 981, us100 8, btcusd 998, eurusd 183, all 2573.
    - The trade-history **table** now has its own row filters (side / result / exit reason / instrument) and sortable columns, added in `TradeHistory` in `Performance.tsx`. The instrument filter and column only appear when the rows span more than one epic (i.e. the ALL view).
    - **`_SESSIONS` in `cloud-function/api/app.py:77` is in-memory with a 12h TTL.** Restarting the api container invalidates every token; the next UI request 401s and `apiFetch` (`capital-connect/src/lib/auth.ts`) responds by clearing the token and calling `window.location.reload()` — which looks to the user like a click that silently did nothing and reset the view.
    - To exercise an endpoint by hand: `PW=$(grep -E '^UI_PASSWORD=' .env | cut -d= -f2-)`, POST it to `/api/auth/login`, then send `Authorization: Bearer <token>`. Calling the api container directly on :8000 does **not** bypass auth.

19. **`time_based_exits` (EOD close / max hold) is DEAD in the live bot.** `eod_hour` / `eod_enabled` are read **only** by `orchestrator/production_orchestrator.py:143`. The live bot is `bot_control_api.py` → `python orchestrator/main.py` → `TradingOrchestrator` (`main.py:767`), which never instantiates `EndOfDayClose` or `IntraDayTimeExit`. **Nothing force-closes a live position** — exits are SL / TP / tick-exit only.
    - Consequence: positions are carried across the weekend. Confirmed loss — US100 `dealId 00384627-…-000083765fd6`, SELL 1 @ 28288.7 opened Fri 2026-07-31 20:00:07 UTC, stop at 28320.1, closed Sun 2026-08-02 22:00:10 UTC at **28441.7** on the reopen gap = 121.6 pts *past* the stop, realised -$153 (-€132.37) vs the intended -$50.
    - `guaranteedStop: false` on every position, so a gap is uncapped.
    - `risk.skip_hours` only blocks **new entries**; it does not flatten. For US100 the whole allowed session (13:00–20:59 UTC) sits *after* `eod_hour: 16`, so even a working EOD close would be useless without a per-instrument close hour.
    - **The fix is now DEPLOYED (gotcha 55) but ships `enabled: false` — see gotcha 51.** So everything above still describes the running container's *behaviour*: nothing force-closes a position.

20. **Live SL/TP are anchored to the signal-bar close, not the actual fill.** `AnalysisSkill._calculate_sl_tp` (`analysis_skill.py:527`) computes levels off the candle close and ships them with the order; the broker fills at market some seconds later. The distances the broker records are therefore *not* the configured pips.
    - Worked example (US100, config SL=50 / TP=150): levels SL 28320.1 / TP 28120.1 imply a reference price of 28270.1, but the fill was 28288.7 → **effective SL 31.4 pts, TP 168.6 pts**. Other same-day US100 fills drifted to 60.2 / 63.5 / 55 pts.
    - So real risk-per-trade varies ±40% from the YAML, and backtests (which fill at the close) systematically disagree with live. To diagnose, compare `details.openPrice` vs `stopLevel`/`profitLevel` in `/history/activity` — do **not** trust the YAML pips.

21. **Reading trades out of the live DB — exact shapes:** `kv_store` columns are `(collection, doc_id, data, updated_at)` — there is no `key`/`value` column. `trade_history` rows carry `bot_id` (e.g. `us100_m5_bot`); `active_positions` rows do **not** (`bot_id: None`) but do carry `opened_at` and `status`. `active_positions` has `entry_price: None` on many rows while `trade_history` has it — join on `deal_id` across both to reconstruct a trade.

22. **`get_activity()` WAS broken — it always returned `[]`, silently disabling three risk mechanisms. FIXED 2026-10-21; this entry said "not yet deployed to the container" and that became WRONG the same day — see gotcha 55.** It reached the container in the 2026-10-21 15:50 build and has been recording real P&L since; the whole consequence chain below is historical, not current.
    - `capital_api.py:330` (was `:308` before this file grew) sent `filter=type==POSITION;status==EXECUTED`. **`status==EXECUTED` matches nothing** — verified against the live demo API: `EXECUTED` → `200 n=0`, `ACCEPTED` → `200 n=11`. The correct value is `ACCEPTED`.
    - Second, independent bug: `main.py:303` iterates `details['actions']` to find `POSITION_OPENED`/`POSITION_CLOSED`. **There is no `actions` array in the response.** Even with the filter fixed, nothing would parse.
    - **Real close-event shape** (`detailed=true`, `status==ACCEPTED`): top-level `date`/`dateUTC`/`epic`/`dealId`/`source`/`type`/`status`, and `details` = `dealReference`, `workingOrderId`, `marketName`, `currency`, `size`, `direction`, `level`, `stopLevel`, `guaranteedStop`, `profitLevel`, and — **only on closes** — `openPrice`.
      - A close is identified by **`details.openPrice` being present**; open events lack it.
      - **`source` is the exit reason**: `SL` | `TP` | `USER`. Use it instead of string-matching `description` (which the REST fallback passes as `''`).
      - **`details.direction` on a close is the CLOSING direction — the opposite of the position.** A position opened BUY shows `direction: SELL` on its close row. Don't use it as the position direction.
      - **There is no `details.profit`.** `_handle_close` reads `details.get('profit')` and so always gets `None`. Realised P&L must be joined from `/history/transactions` on `dealId` (where `size` *is* the P&L — see gotcha 15).
    - **Consequence chain:** activity poll returns `[]` → every close is detected only by the 60 s REST reconcile at `main.py:353`, which calls `_handle_close(deal_id, 0.0, '')`. Then:
      1. `close_level=0.0` is falsy, so the `if entry and close_level and size` guard fails → **`pnl = 0.0`** and `exit_price = 0.0` on every `trade_history` row written since the writer landed (2026-08-01). 365 rows at the time of writing; **381 by the 2026-10-21 deploy, and all 381 are now REPAIRED — gotcha 59.**
      2. `description=''` → `close_reason = 'SIGNAL'` → `_check_cooldown` falls through to "No cooldown required". **`sl_cooldown_minutes` / `tp_cooldown_minutes` never apply in live.** GOLD's 30 m SL cooldown has never once fired.
      3. `is_loss = pnl < 0` with `pnl == 0.0` → **every trade is scored as a win.** The consecutive-loss breaker can never trip.
      4. `_register_daily_pnl(0.0)` → **`risk.max_daily_loss_usd` can never trip.** ETHUSD's $150 cap is inert.
    - The dashboard therefore shows real P&L only through 2026-07-31 (from `backfill_trade_history.py`, which uses `/transactions` and is correct) and **0.00 for everything after**. US100 shows 223 of 231 trades at zero.
    - Until this was fixed, **`/history/transactions` was the only trustworthy live P&L source.** The live path is fixed and deployed (gotcha 55) and the historical rows are repaired (gotcha 59), so `trade_history` is now trustworthy throughout — **except `exit_reason` on the 381 repaired rows**, which stays `SIGNAL` because transactions carry no exit reason and activity is capped at 24h. Do not read those rows' exit mix as strategy evidence.

23. **`epic==` in the activity filter DOES work — corrects gotcha 12.** `filter=type==POSITION;status==ACCEPTED;epic==US100` returns `200 n=8`. The 400 previously attributed to `epic==` was almost certainly the `from/to` params, not the epic clause.

24. **Three different `/data/trading.db` files exist. Know which one you are reading.**
    | Where | Path | Contents (2026-10-21) |
    |---|---|---|
    | Live volume (truth) | `/var/lib/docker/volumes/stockscreener_trading_data/_data/trading.db` (1.2 GB) | 6 epics × ~165–220k M5 bars through today; `trade_history` 2945 rows |
    | **Host stray** | `/opt/stockscreener` → `/data/trading.db` (35 MB) | GOLD 154k bars, **US100 only 1,500**, ETHUSD stale at 2026-07-29 |
    | In-container | `/data/trading.db` inside any compose service | the live volume |
    - `sqlite_api.py:30` defaults `DB_PATH` to `/data/trading.db` and `:49` **creates the parent dir** — so running any script on the host silently creates/uses the stray 35 MB DB. `.env` sets no `DB_PATH`.
    - **A host-run `run_skills_backtest.py --instrument US100 --years 2` therefore backtests 1,500 bars (~5 days) and reports 18 trades without warning.** Always either run backtests inside `stockscreener-backtest-runner-1` or set `DB_PATH` to the volume path.
    - `sqlite3` CLI is **not installed** on the host — use `python3 -c "import sqlite3..."`.
    - ⚠️ **The "Host stray" row above is STALE — see gotcha 53's closing correction.** As of 2026-10-22 that DB holds GOLD **188,466** and US100 **202,994** M5 bars, both current to today, so `DB_PATH=/data/trading.db` is now the right choice for **both** instruments' backtests. The warning about *accidentally* creating it by running a script on the host still stands. **⚠️ Superseded for US100 on 2026-10-23:** US100 was re-based to bid/UTC in the **live volume only** (gotcha 57). The host stray DB's US100 is still mid/local, so **run US100 backtests in the container**, or set `DB_PATH` to the volume path.

25. **`stockscreener-backtest-runner-1` had months-stale baked configs AND code — UI-triggered backtests did NOT test the deployed strategy. REBUILT AND FIXED 2026-10-22 19:30 (gotcha 56); everything below is historical, except that GOLD's bar depth in the volume is still thin.** Config is `COPY`d at build time and the service has not been rebuilt since the strategy changed. Diff vs the live bot on 2026-10-21:
    | Instrument | Live bot | backtest-runner (stale) |
    |---|---|---|
    | GOLD | `require_sma_bias: true` (MA100), `tick_exit` block | **both absent** |
    | US100 | ST(14, 1.5), `require_h1_bb: false`, `reverse_signal_exit: false`, `skip_hours` | **ST(7, 2.0), `require_h1_bb: true`, no reverse-exit guard, no skip_hours** |
    | ETHUSD | SL 25 / TP 125, MA100 bias, `reverse_signal_exit: false` | **SL 45 / TP 170, no bias, no reverse-exit guard** |
    - Effect: a 2-year ETHUSD run in that container produced **16,802 of 16,999 exits as `Reverse Signal`** (avg hold 1.3 bars) and `+$733,912` on $10k — a reverse-signal scalper compounding through `dynamic_sizing`, not the live strategy. Treat any such number as an artefact.
    - **The container's *code* is stale too, and that is worse than the configs.** `/app/run_skills_backtest.py` is 866 lines vs the host's 992, contains **zero occurrences of `reverse_signal_exit`**, and at its line 363 calls `backtesting.close_reverse_positions(...)` **unconditionally**. The host version guards it at `run_skills_backtest.py:553`. So `docker cp`-ing the correct YAML in is **not sufficient** — a run with `reverse_signal_exit: false` correctly loaded still produced 6,973 `Reverse Signal` exits and `+$185,306`.
    - Note the default is also inconsistent in the current code: `run_skills_backtest.py:553` defaults `reverse_signal_exit` to **True**, while `trading_orchestrator.py:130` defaults it to **False**. An instrument YAML that omits the key gets reverse-exit ON in backtest and OFF in live.
    - To backtest the real strategy: rebuild the service (`docker compose build backtest-runner`) — copying YAML alone will not fix it.

26. **`execution.position_size` defaults to `0.5` (`execution_skill.py:51`) — GOLD and ETHUSD have been trading at a fraction of intended size.** The deployed YAMLs define `position_size` only under `backtesting:`, not under `risk:`/`execution:`, so the 0.5 default wins.
    | Instrument | Actually traded | Host YAML intends | Risk/trade actual → intended |
    |---|---|---|---|
    | GOLD | **0.5** | 10 | $7.50 → **$150 (20×)** |
    | ETHUSD | **0.5** | 1 *(comment)* / **2** *(value)* | $12.50 → $25 (2×) |
    | US100 | 1.0 | 1 | $50 — **correct, but NOT for the reason this row gave.** It credited `risk.position_size: 1`; that key reaches nothing. US100 gets 1.0 only because its bot was launched with `--quantity 1.0`, the sole writer of `execution.position_size` (`main.py:909`), replayed from `kv_store/bot_state` on every restart. **Start it without a quantity and it silently trades 0.5** — gotcha 55. |
    - The `position_size` additions to `GOLD.yaml`/`ETHUSD.yaml` are the fix — but deploying them **multiplies GOLD risk 20× on a strategy with no measured edge.** Aug–Oct would have been **−€5,386 instead of −€1,820**. Fix the edge before the size.
    - **Status 2026-10-22: committed as `c0fb630`, then REVERTED by `6a26450`.** The defect is therefore still live and deliberately so. To recover the change: `git show c0fb630`, or `git revert 6a26450`. Verified after the revert — effective loaded sizing is GOLD `risk`/`execution` = **None → 0.5 default**, ETHUSD **None → 0.5**, US100 `risk` = **1** (US100 was never part of the commit and is correct).
    - **The `main.py` root-propagation block (`main.py:126-131`) is committed but INERT**, and is not the mechanism gotcha 26 needs. It only fires on a **root-level** `position_size` key; no instrument YAML has one and neither does `trading_config.yaml`, so it propagates nothing. The other writer is `--quantity` (`main.py:840`), which sets `risk`/`execution` directly. So adding `position_size` under `risk:`/`execution:` in the YAML is what actually changes live size — not the root key.
    - Reverting `c0fb630` also restored ETHUSD `backtesting.position_size` to **2** while its comment still reads "1 ETH per trade". That half of the commit was an unrelated comment/value fix and is **backtest-only**; it changes ETHUSD backtest P&L magnitudes (PF is size-invariant except through `dynamic_sizing` compounding). GOLD's `backtesting.position_size` stays **10**, so the GOLD regressions in gotchas 35/41/49 are unaffected.

27. **SL/TP anchoring drift is small in the median — gotcha 20's "±40%" is a tail, not the typical case.** Measured over 362 live positions (Aug–Oct), broker distance vs configured pips: GOLD SL median +1.6% / TP −0.4%; ETHUSD +2.7% / −0.5%; US100 +1.8% / −0.6%. Realised R:R medians 3.92 / 4.84 / 2.93 against configured 4.0 / 5.0 / 3.0. Tails do drift (US100 SL ranged 31.3–79.1 pts), so per-trade risk varies, but **execution is not the reason the system loses money** — win rate is.

28. **Measured strategy verdict (2026-10-21) — the Supertrend entry has no edge; on GOLD it is worse than random.**
    - Live Aug 1 → Oct 21 (EUR, demo), actual WR vs the WR each R:R needs to break even:
      | | n | WR | breakeven WR | gap | PF | P&L |
      |---|---|---|---|---|---|---|
      | US100 | 221 | 21.72% | 26.02% | **−4.30pp** | 0.79 | −€1,664 |
      | GOLD | 93 | 13.98% | 20.11% | **−6.13pp** | 0.65 | −€190 |
      | ETHUSD | 55 | 18.18% | 17.24% | +0.94pp | 1.07 | +€34 |
      Plus **−€184 of SWAP** (overnight financing; US100 −€164 of it) → **−€2,004 total.** Max cumulative drawdown −€2,588.
    - GOLD 2-year backtest (host DB, size 10, SL/TP exits only), `--shuffle-signals` randomises entry direction:
      | run | n | WR | beWR | gap | PF | P&L | maxDD% |
      |---|---|---|---|---|---|---|---|
      | base SL15/TP60 | 359 | 20.3% | 20.8% | −0.4 | **0.973** | −$1,181 | 42.2 |
      | **shuffle seed A** | 337 | 22.3% | 21.0% | +1.3 | **1.080** | +$3,259 | 26.6 |
      | **shuffle seed B** | 349 | 22.1% | 20.9% | +1.1 | **1.068** | +$2,905 | 36.8 |
      | TP30 (1:2) | 446 | 33.0% | 34.6% | −1.7 | 0.928 | −$3,353 | 44.5 |
      | TP45 (1:3) | 383 | 24.5% | 26.0% | −1.4 | 0.927 | −$3,275 | 47.9 |
      | BUY-only | 217 | 31.8% | 21.0% | +10.8 | 1.750 | +$17,312 | 5.6 |
    - **Two independent random-direction seeds both beat the real signal.** Retuning R:R (TP 30/45/60) does not help — every variant sits at or below breakeven WR. The problem is signal direction, not SL/TP geometry.
    - **BUY-only's +$17k is beta, not alpha:** GOLD went 2032 → 4123 (**+103%**) across the window, so "long-only in a bull market" is tautological. SELLs account for −$10,127 of the base run's loss. Note GOLD was **flat-to-down in Q3–Q4 2026** (4699 → ~4100), which is exactly the live losing window — so BUY-only would *not* have rescued Aug–Oct. Do not deploy it as a fix without an out-of-sample test on a non-trending regime.
    - **US100 2-year backtest (host code, reverse-exit guard active, SL50/TP150, size 1) — ruinous, and it matches live:**
      | | n | WR | beWR | gap | PF | P&L | maxDD% |
      |---|---|---|---|---|---|---|---|
      | US100 backtest | 2481 | 25.47% | 30.90% | **−5.43pp** | **0.764** | **−$134,629** | **1346%** |
      | US100 live (Aug–Oct) | 221 | 21.72% | 26.02% | −4.30pp | 0.79 | −€1,664 | — |
      Exits 1849 SL / 632 TP. **Every allowed hour is negative** (13:−21.0k, 14:−23.8k, 15:−16.9k, 16:−17.1k, 17:−16.8k, 18:−9.1k, 19:−12.4k, 20:−18.7k); only hour 21 (n=24, +1.6k) is positive, and `skip_hours` blocks it. Both directions lose (BUY −73.5k / SELL −61.1k), so there is no long/short asymmetry to exploit as on GOLD. maxDD 1346% = the account is wiped ~13× over.
      **The close live/backtest agreement (PF 0.79 vs 0.764, gap −4.3 vs −5.4pp) is the important part: the host backtester is trustworthy, and it predicted this loss.** The fantasy numbers only come from the stale `backtest-runner` (gotcha 25). Re-tuning US100 session hours cannot fix a strategy whose every session hour is negative.
      ⚠️ **Two corrections to this table:** its P&L is inflated ~6× by gotcha 31's cost typo, and its hour labels are UTC+2, so "13–20" was really 11–18 UTC (gotcha 57). On re-based bid/UTC bars with correct costs (2026-10-23), hours are mixed rather than uniformly negative. The current per-hour table is in gotcha 57.
    - Observed live exit mix is nearly all stops: in a 24 h activity sample, **6 of 6 closes were `source: SL`, zero TP.**

29. **Bar data for GOLD / ETHUSD / EURUSD / SILVER WAS starved — `bar_updater` silently no-op'd from ~Q2 2026. ROOT-CAUSED AND FIXED 2026-10-21.** M5 coverage before the repair:
    | | 2025Q4 | 2026Q1 | 2026Q2 | 2026Q3 | 2026Q4 |
    |---|---|---|---|---|---|
    | GOLD | 99% | 96% | **22%** | **6%** | **6%** |
    | ETHUSD | 98% | 96% | **68%** | **12%** | **5%** |
    | US100 | 102% | 99% | 102% | 104% | healthy |
    - Every 15-min cycle logs `[GOLD/M5] Fetching <from> → <now>` then `No new candles — reached end of available history` → `No new candles returned (market closed or no data)`. **It is logged as INFO/WARNING, never as an error**, so the failure is invisible.
    - **The data is NOT missing broker-side.** Direct calls return GOLD bars for September and for today. Only the updater's incremental path fails; `fetch_data.py --epic GOLD --timeframe M5 --bars N` (bar-count mode) works and is the repair.
    - **Consequence:** a GOLD or ETHUSD backtest over the live window produces **6 and 3 trades against 93 and 55 actual live trades**. Any GOLD/ETH backtest conclusion is effectively measured on data ending ~2026Q1. US100 is the only instrument whose backtest can currently be trusted.

30. **`/api/v1/prices/{epic}` — `to` is UTC, `snapshotTime` comes back in account-local time (UTC+2).** This is why the window looks shifted.
    - `max` + `to` returns `max` bars **ending at** `to` (e.g. `max=1000&to=2026-10-20T12:00:00` → `2026-10-14T22:45` .. `2026-10-20T14:00` local). Backward pagination on `to` is correct.
    - **`to` must be full ISO with `T`** — a date-only `to=2026-09-08` returns **400**.
    - **`from` + `to` together returns 400.** There is no date-range mode; walk backwards with `to` + `max` only. `fetch_data.py --from/--to` is therefore broken (it passes date-only strings); use `--bars N`.

31. **`US100.yaml:35` had `slippage_cost_usd: 10` while its own comment said `$0.20/contract` — a 50× typo that invalidated every US100 backtest. FIXED 2026-10-21 (now 0.20).** Costs scale by size (`backtesting_skill.py:345-346`: `spread_cost_usd * current_size`), so US100 was charged `(1.80 + 10) × 5 = $59/trade` instead of `$10`.
    - Effect on the 2-year run: **−$134,629 / PF 0.764 / maxDD 1346% → −$2,560 (size 1) / PF 0.973 / gap −0.52pp** once corrected. The "ruinous" verdict was almost entirely this one character.
    - Re-measured 2026-10-23 on re-based bid/UTC bars (gotcha 57), container `--bars 203260`, size 5: **2485 / WR 25.513% / PF 0.9749 / −$12,100**. The PF is unchanged; the session moved 2h to the intended 13:00–20:59 UTC.
    - It is in the `backtesting:` block only, so **live trading was never affected** — but every backtest-vs-live comparison was.
    - **Live trades independently confirm the correct value:** live implied R:R is 2.84 vs configured 3.00; that ~5% shortfall is 1.8pts on a 50pt stop, matching `spread_cost_usd: 1.80` with slippage ≈0.20.

32. **Cost drag, not signal quality, is what makes this system lose.** From `trades.csv` (`spread_cost` + `slippage_cost` columns):
    | | n | net | costs | gross (pre-cost) | gross PF |
    |---|---|---|---|---|---|
    | GOLD | 359 | −$1,181 | $2,154 | **+$973** | **1.023** |
    | US100 | 2481 | −$134,629 | $146,379 | **+$11,750** | **1.025** |
    | ETHUSD | 576 | −$1,868 | $1,296 | −$572 | 0.953 |
    - GOLD and US100 both have a **mildly positive gross edge (~PF 1.02)** that costs consume entirely. US100's gross edge is **$4.74/trade** against a true cost of ~$10/trade.
    - This also defuses the `--shuffle-signals` result (gotcha 28): shuffle pays the same costs, so "random beats real" was never evidence the signal is anti-predictive. The correct statement is **the edge is too thin to clear its cost hurdle**.
    - Implication: the lever is **R size relative to spread**, or **fewer trades**, not better entry tuning. Spread is 3.6% of R at SL 50; at SL 100 it is 1.8%.
    - ⚠️ **Tested 2026-10-23 and REFUTED as a mechanism (gotcha 61).** Widening R cut cost from 4% to 1% of R as predicted, but gross PF did not hold still (GOLD M5 1.109 → 0.718 at 4× stop). The gross edge is not a fixed quantity you can expose more cheaply.

33. **Backtest-vs-live agreement (the measurement rig actually works).** Cost-corrected US100 restricted to 2026-08-01 .. 2026-10-21 vs live:
    | | n | WR | avgW | avgL | PF |
    |---|---|---|---|---|---|
    | backtest | 241 | 24.48% | $148.0 | −$52.0 | 0.923 |
    | live | 221 | 21.72% | $150.0 | −$52.7 | 0.789 |
    WR differs by 3.8pp ≈ 1.4 standard errors on n=221 — within sampling noise. **Trust the host backtester for US100**; distrust it for GOLD/ETH until gotcha 29 is repaired.
    - ⚠️ **Re-measured 2026-10-23 on re-based bid/UTC bars (gotcha 57) — and the table above was on the wrong session.** It was measured on mid/local bars, so the backtest was trading **11:00–18:59 UTC** while live traded 13:00–20:59. Same window, container `--bars 203260`, live recomputed from `trade_history` (includes gotcha 59's repaired rows, so n=224; live P&L is EUR, so compare PF/WR, not $):
      | | n | WR | PF | live entries matched ±10 min | same side | same outcome |
      |---|---|---|---|---|---|---|
      | backtest, old mid/local bars | 242 | 24.38% | 0.918 | 149 / 224 | 143 | 138 |
      | **backtest, re-based bid/UTC** | **229** | **24.45%** | **0.921** | **208 / 224** | **203** | **196** |
      | live | 224 | 21.88% | 0.805 | — | — | — |
      **The summary numbers barely moved, but trade-level agreement jumped from 66% to 93% of live entries.** The aggregate match in the old table was partly luck: two different sessions with similar statistics. It is now a real trade-for-trade match. The remaining WR gap is 2.6pp ≈ 0.9 SE. The 16 unmatched live entries and the 7 same-side outcome flips are the residual to explain (bar boundaries, ASK vs BID: gotcha 57). **US100 parity is now established at trade level, and only in the live volume:** the host stray DB is still mid/local for US100.

34. **Parameter tuning did not produce a transferable improvement (~20 configs, 3 instruments, 2026-10-21).** Scored with `/opt/stockscreener/sweep_eval.py`, which splits each run's trades at the midpoint and requires **both halves PF > 1.0**.
    - On GOLD, *every* single-parameter variant came out IS_PF > 1 / OOS_PF < 1 (multiplier 2.0–3.5, ATR period 10/20, ADX 20/25/30, no-bias, M15, M30, MTF-BB). Only `multiplier=2.0 + ADX(25)` passed: PF 1.078, IS 1.157 / OOS 1.013, gap +1.27pp.
    - **It does not transfer:** US100 0.973 → **0.948**, ETHUSD 0.858 → **0.829**. Both *worse* than baseline. Treat the GOLD win as fitted — and note it was measured on data that is 94% absent after 2026Q1 (gotcha 29).
    - Other traps the split caught: `tfM15_adx25` PF 1.322 but n=73 with IS 0.997 / OOS 2.457 (a few lucky trades); `--shuffle-signals` PF 1.08 but OOS 0.960.
    - M30 on GOLD yields **25 trades in 2 years** — frequency reduction starves the signal faster than it saves cost.
    - **Use the IS/OOS + cross-instrument transfer bar before believing any future sweep result.** Single-period PF on one instrument has been wrong every time here.

35. **GOLD's baseline REVERSES once the bars are repaired (gotcha 29). Re-run before trusting any pre-2026-10-21 GOLD result.** On repaired data (188,197 bars, 2y, size 10, SL/TP exits only):
    | run | n | WR | gap | PF | IS_PF | OOS_PF | stable |
    |---|---|---|---|---|---|---|---|
    | baseline SL15/TP60 | 491 | 21.59% | **+0.82** | **1.050** | 1.092 | 1.031 | ✅ |
    | SL30/TP120 | 265 | 21.51% | +0.85 | 1.052 | 1.064 | 1.048 | ✅ |
    | SL45/TP135 | 185 | 24.86% | −0.85 | 0.956 | 1.340 | 0.837 | ✗ |
    - The earlier "GOLD PF 0.973, no edge" was measured on data **94% absent after 2026Q1**. Quarterly PF on repaired data: 2026Q2 **1.38**, Q3 0.97, Q4 **2.04** (vs 1.38/0.97 previously unmeasurable).
    - `m20_adx25` is no longer needed to make GOLD stable — the plain baseline is. Prefer the baseline (fewer fitted knobs, 491 vs 290 trades).

36. **✅ SOLVED 2026-10-23 — see gotcha 60: the live bot never applied the MA100 slope gate.** The rest of this entry is the history of the search. **GOLD live takes ~50% more trades than the backtest and wins less — cause was UNKNOWN. Three plausible explanations were tested and all REJECTED (2026-10-21).** Live window 2026-08-01..10-21:
    | | n | WR | PF |
    |---|---|---|---|
    | backtest (repaired data) | 61 | 21.31% | 1.046 |
    | **live actual** | **93** | **13.98%** | **0.646** |
    - **Rejected — broken SL/TP cooldowns (gotcha 22).** `sl_cooldown_minutes=0` / `60` / `30` all produce **exactly 61 trades** with identical PF. The cooldown gate only blocks *same-direction* re-entry, and `edge_detection` means the next signal is usually the opposite direction, so it almost never binds. The cooldown bug is real but costs nothing here.
    - **Rejected — daily 21:00 restart resetting `last_signal_state`.** The 31 excess live trades are spread across hours 8–20 (hour 12 is +11); **hour 21 has 0 live entries**. No restart signature.
    - **Rejected — Supertrend path-dependence on the live rolling buffer.** Live computes ST on a rolling buffer (this said 300 bars; it is actually **105** — gotcha 60); the backtest precomputes over the full series. Measured over 1,100 GOLD M5 bars: **100.00% direction agreement, 85 vs 85 flips.** ST band memory resets at every flip (~1 per 13 bars), so 300 bars is ample. Not a divergence source — and this also retires the general worry about truncated-buffer indicators.
    - **Still open:** the live bot builds candles from the WebSocket tick stream while the DB bars come from the REST price endpoint — bar boundaries/incomplete bars may differ; and the live MA100 bias is computed over whatever the live buffer actually contains (which was itself starved while gotcha 29 was active).
    - ✅ **The "check live candle timestamps against DB bars" half of that lead is now CLOSED — and it was a real defect.** `get_historical_prices` returned **account-local** timestamps (UTC+2) while `fetch_data.parse_candle` stored UTC, so the live warm-up buffer was two hours off the DB bars from the same endpoint. Fixed 2026-10-22 (gotcha 54b). It does **not** explain the excess live trades by itself — warm-up bars generate no signals — so the WebSocket-vs-REST bar-boundary question remains the live lead.
    - **Consequence:** US100 backtest↔live parity is good (gotcha 33) but **GOLD parity is not established.** Do not size up GOLD on backtest evidence alone.

37. **Where this strategy family sits in the published literature (researched 2026-10-21) — the measured numbers match known structural limits.**
    - [Structural Limits of OHLCV-Based Intraday Momentum in MNQ Futures](https://arxiv.org/abs/2605.04004) tested **14 signal families on 947 days of 5-minute Micro-Nasdaq data** (same instrument and bar size as US100). None passed; **11 of 14 had gross edge 0.07–1.50 points against a 2.0-point friction floor.** Our measured US100 gross edge is **0.95 points/contract** against ~2.0 points of cost — inside that published range. Its *positive* controls did clear friction (RTH confluence T=3.11 net +11.82 pts; London session T=4.30 net +4.09 pts), i.e. edge exists in session/confluence structure, not generic OHLCV momentum.
    - [Is Trend Still Your Friend?](https://arxiv.org/html/2607.01550v1) — Sharpe by signal horizon, pre→post 2009: 5-day 0.84→**0.12**, 10-day 0.83→0.22, 20-day 0.79→0.27, 50-day 0.70→**0.40**. Discriminant is **volatility-normalised tick size**; small-tick contracts collapsed, large-tick held. Called structural, not cyclical. Our median holds: **US100 35 min**, GOLD 191 min, ETHUSD 505 min — i.e. ~200× faster than the fastest horizon that study found already dead.
    - [Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) — when N variants are tried and the best kept, the max is inflated even if all are noise. Directly explains `m20_adx25` (gotcha 34): best of ~20 trials in-sample, failed to transfer. **Count trials and deflate before believing a sweep.**
    - Grinold's Fundamental Law: `IR ≈ IC × √breadth`. This system runs **one signal family, 3 instruments, one position at a time → breadth ≈ 1**, while trying to harvest a PF-1.02 edge. Breadth, not a better indicator, is the multiplier.
    - Practical implication for future work here: **slower horizons (daily/H4), many more markets, several uncorrelated signal types, volatility-targeted sizing, trial-count-corrected validation.** Faster + more tuning is the one direction the evidence rules out.

38. **The 2026-10-21 fixes — what changed. (Its "NOT deployed" warnings are now historical: the `get_activity`/P&L half shipped on 2026-10-21 and everything else on 2026-10-22 — gotcha 55.)** All verified against the live demo API; `tests/unit/` went 271 → 288 passing with the same 20 pre-existing `test_pip_config` failures.
    - **`bar_updater` root cause was a string-comparison format mismatch, not a timezone bug.** `parse_candle()` emits `'YYYY-MM-DD HH:MM:SS'` (space) while `bar_updater` passed `strftime('%Y-%m-%dT%H:%M:%S')` ('T'). In `fetch_all_bars`'s date-range filter `if ts < from_date: continue`, `ord(' ')=32 < ord('T')=84`, so **every same-day candle compared as older than `from_date` and was skipped** → 0 rows → `"reached end of available history"`. Bar-count mode (`--bars N`) was unaffected because it does no date filtering, which is why only US100 (already up-to-date, never entering the fetch) escaped.
      - Fix: new `_norm_ts()` normalises every bound to the `parse_candle` form before comparison; date-only bounds are widened (`from`→`00:00:00`, `to`→`23:59:59`) so `--from/--to` no longer 400s; pagination now anchors on `snapshotTimeUTC` instead of local `snapshotTime` (the API's `to` is UTC, so feeding the local value back shifted each window by the offset and re-fetched overlaps).
      - Verified: `--from 2026-09-01 --to 2026-09-03` on SILVER → **828 bars (was 0)**; `bar_updater.py --epic GOLD` → **61 candles inserted (was 0)**.
    - **`get_activity` + close detection:** filter now `status==ACCEPTED`; the non-existent `details['actions']` loop is replaced by `'openPrice' in details` for close detection and `source` → `{SL: SL_HIT, TP: TP_HIT, else SIGNAL}` for the reason. Verified live: `epic=US100` over 24h returns **14 events (was 0)**, parsed as 7 opens + 7 closes, all correctly `SL_HIT`.
    - **New `CapitalAPIClient.get_realised_pnl(deal_id)`** joins `/history/transactions` on `dealId` (where `size` IS the P&L). Activity and transaction dealIds **are the same ID space** (11/21 overlap in 24h — opens have no TRADE row). Verified: 11/11 closes resolved, magnitudes correct (US100 ≈ −45 EUR on a 50 USD stop, GOLD ≈ −6.7 on 7.5). Default look-back is 3600s; pass more for historical lookups or it returns None.
    - **`pnl is None` now means "unknown" everywhere and is never coerced to `0.0`.** `_handle_close` only estimates from prices when it has entry+close+size; `trading_orchestrator` log-formats None safely; `_record_trade` distinguishes a real broker `0.0` (kept) from unknown (recorded with the new **`pnl_unknown: true`** flag + a warning). The old `float(pnl or 0.0)` also discarded a genuine break-even figure in favour of an estimate — also fixed.
    - **Regression cover:** new `tests/unit/test_activity_parsing.py` (filter must say ACCEPTED, `openPrice` discriminates, source→reason mapping, no `actions`/`profit` fields, transactions `size`-as-P&L, `lastPeriod` cap) and 2 new cases in `test_trade_history.py` for the unknown-vs-break-even distinction.
    - ⚠️ **WAS "not deployed" — now DEPLOYED (gotcha 55).** Measure, do not re-read this line: `docker exec stockscreener-trading-bot-1 grep -c 'status==ACCEPTED' /app/clients/capital_api.py`. A rebuild still bakes in every uncommitted change in `./trading-bot-skills` (gotcha 10), so `git status` first regardless.

39. **Open work is captured as ready-to-paste session prompts in [`NEXT_SESSIONS.md`](NEXT_SESSIONS.md) — rewritten 2026-10-22, kept current through the sixth session that day.** **Read its "Where to start" table first** — it carries the live priority order, and this entry is only an index. Eleven streams; **1, 4, 5, 6 and 7 are CLOSED** (their prompts are retained as closed markers so the numbering keeps resolving).
    - **Open, in priority order:** **(11) finish the bar-data repair** — the GOLD phantom-bar `DELETE` is done (2026-10-23, container now bit-identical to the host); US100 is re-based too (2026-10-23, live volume; gotchas 33, 57). Left: ETHUSD, BTCUSD, EURUSD, SILVER (gotchas 57, 56); **(3) the GOLD live/backtest divergence** (gotcha 36 — four hypotheses rejected, now **three** leads left, the newest being live-on-ASK vs backtest-on-BID per gotcha 57); **(2) the time-based flatten is BUILT but deliberately OFF** (gotchas 51, 19 — the backtest says the weekend-carry trades hold all the profit, so enabling it needs the flatten simulated in the backtester first); **(8) strategy research direction** — three levers measured and failed, cost-per-unit-of-R the cheapest untested one (gotcha 32); **(9)** small open items; **(10)** the standing keep-running-these-bots question.
    - **Closed:** (1) deploy the fix stack (gotcha 55); (4) `backtesting_skill.py` coverage, 59% → 100% (gotcha 53); (5) `capital_api.py` coverage, 19% → 100% (gotcha 54); (6) UI backtests — runner rebuilt (56) and GOLD re-based to bid/UTC (57); (7) the zero-P&L `trade_history` rows, 381/381 repaired (gotcha 59).
    - Each prompt names the gotchas carrying its background so nothing has to be re-derived. **Check it before starting new work** — four hypotheses for the GOLD divergence are already tested and rejected there, and the `position_size` question is settled (committed `c0fb630`, reverted `6a26450`).

40. **The "20 pre-existing `test_pip_config` failures" (gotcha 39 / NEXT_SESSIONS prompt 4) were 20 failures across THREE files with three different causes. All fixed 2026-10-22. Suite is now 761 passing, 0 failing.**
    - **8 in `test_alerting_skill.py` — a real production bug, not a stale test.** `AlertingSkill.__init__` set `self.telegram_client = None` whenever `mock_mode` was on, but every `on_*` handler guards only on `telegram_enabled` and then dereferences the client. So `mock_mode: true` + `telegram.enabled: true` — a combination `trading_config_example.yaml` explicitly documents ("Test in mock mode first") — raised `AttributeError` on **every** alert. Fixed by handing out a real `TelegramAPIClient(mock_mode=True)` instead of None.
    - **5 in `test_pip_config.py` — stale tests, correct implementation.** They built a `SimulatedTrade` with PER-CONTRACT costs and expected `calculate_pnl` to multiply by size. It must not: `backtesting_skill.py:345` already stores `spread_cost_usd * current_size`, i.e. the size multiplication lives in exactly ONE place. "Fixing" the implementation to match would have charged size² of cost — the same class of error as gotcha 31's 50× typo. Tests rewritten to the real contract, plus a new `TestCostScalingHappensOnce` that drives `BacktestingSkill.execute()` and asserts the stored totals, so either half of a double-multiplication now fails.
    - **7 in `test_execute_pipeline.py` — two causes.** Six `RiskSkillExecute` tests never armed the startup-flip gate, which is first in the chain and short-circuits everything (fixture now sets `startup_flip_gate: False`, since their subject is cooldowns/skip-hours). The seventh asserted "H1 BB blocks BUY below midline" — the **opposite** of the implemented semantics, and it set an `h1_bb_middle` column the gate never reads. The gate deliberately treats bands as **price walls**: BUY blocked near the UPPER band (resistance overhead), SELL near the LOWER (`analysis_skill.py:928`, thresholds 0.75/0.25). Its companion "allows" test passed only vacuously — a flat series makes `band_width == 0` and the gate short-circuits.

41. **`RiskSkill` had TWO gate chains enforcing different rules. Unified behind `_evaluate_entry_gates()` 2026-10-22 (resolves NEXT_SESSIONS prompt 5 items 1–2).**
    - Before: `execute(context)` (live, via `TradingOrchestrator`) had startup-flip + open-position but **not** the circuit breaker, session filter or news kill-switch — so the live bot silently ignored all three. `on_signal_generated(event)` (the EventBus path `run_skills_backtest.py` drives) had those three but **not** startup-flip or open-position — so anything routed that way could stack positions.
    - Both now call one chain, in this order: startup-flip → open-position → skip_hours → consecutive-loss → daily-loss → trading-hours → circuit breaker → session filter → news kill-switch → cooldown. The startup gate mutates state so it must stay first; cooldown stays last.
    - **The open-position gate is conditional on `reverse_signal_exit`.** With reverse exits ON, an *opposite*-direction signal is an exit-and-reenter, not a stack, and must pass: live closes the old position *before* gating (`trading_orchestrator.py:131`), backtest on the next bar's open (`run_skills_backtest.py:552`). Same-direction-while-open is always blocked. An unconditional gate would have silently killed reverse-signal entries in backtest.
    - **`reverse_signal_exit` default unified to `False`.** It was `True` in `run_skills_backtest.py` and `production_orchestrator.py` but `False` in `trading_orchestrator.py`, so an instrument omitting the key got reverse-exit ON in backtest and OFF in live. All six deployed YAMLs set it explicitly, so no deployed instrument changed.
    - `risk.startup_flip_gate: false` is a new opt-out, applied by both paths. Backtest now also suppresses its first signal — one bar over a 2-year run.
    - **Regression-checked on two instruments, both unchanged.** GOLD 2y on the repaired data: **492 trades / WR 21.54% / PF 1.046** vs gotcha 35's documented 491 / 21.59% / 1.050 (the DB gained 63 bars in between). US100 2y: **2485 / 25.473% / 0.9728** vs gotcha 31's 2481 / 25.47% / 0.973 (DB gained 25 bars). Both run with `DB_PATH=/data/trading.db` — see gotcha 48.
    - **Still open:** the live startup gate re-arms on the daily 21:00 restart, so it fires once per bot per day with no backtest equivalent. Not the cause of gotcha 36's excess live trades — suppression would make live take *fewer*, and live takes **more**.

42. **Candle dedup was last-timestamp-only; fixed 2026-10-22 (resolves NEXT_SESSIONS prompt 5 item 3).** `market_data_skill.py` compared `candle_ts == self.last_candle_timestamp`, which catches only an *immediate* repeat. A reconnect replaying bars 7,8,9 after bar 9 passed all three (7 != 9, 8 != 7, 9 != 8): **13 `CANDLE_CLOSED` events for 10 distinct bars**, with 3 duplicate bars landing in the analysis buffer and skewing every indicator computed over it. Now a bounded seen-set (`_is_duplicate_candle`, capped at `max(buffer_size, 500)`), shared by both paths. Replay is now fully suppressed: 10 events, 10 bars.
    - **`MarketDataSkill.process_candle` has NO production callers.** The live bot goes through `execute(context)` (`trading_orchestrator.py:115`); `process_candle` is reached only from tests. The pre-existing dedup tests all drove `process_candle`, i.e. they were testing a path the bot does not run. New `TestDedupOnTheLivePath` in `test_live_signal_path.py` pins the behaviour on `execute()` and asserts the two paths agree on the same replay.
    - **`dedup_enabled` used to be ignored by `execute()`** — read by `process_candle` only — so setting it `false` had no effect on live. Both paths now honour it.

43. **`--cov=<dotted.module.path>` breaks ~47 unrelated tests. Always use bare `--cov` or `--cov=<package>`.** The dotted form makes coverage re-import the module; numpy loads a second time ("The NumPy module was reloaded"), and the two instances then collide inside pandas as `TypeError: int() argument must be ... not '_NoValueType'` from `DataFrame.set_index`. The failures vanish without `--cov`, so they look like flaky tests. It also *under*-reports: `--cov=skills.analysis.analysis_skill` read 41% where `--cov=skills` read 77% on the same suite.

44. **Coverage state and the CI floor (2026-10-22).** New `pytest.ini` + `.coveragerc` (the repo had neither). CI should run `python3 -m pytest --cov`; coverage is deliberately **not** in `addopts` because it takes the suite from ~40s to ~160s. **Quote numbers from `--cov` (bare), which reads `.coveragerc`** — the "before" column below was measured without it, and `.coveragerc`'s `exclude_lines` drops the large `if __name__ == '__main__':` demo blocks several skills carry, which alone moved `market_data_skill` from a reported 34% to 75% (now 84%). Mixing the two measurements is how you get a wrong conclusion about where the gap is.
    | file | before | after (canonical) |
    |---|---|---|
    | `orchestrator/main.py` | 13% | **95%** |
    | `clients/capital_websocket.py` | 41% | **98%** |
    | `skills/execution/execution_skill.py` | 45% | **93%** |
    | `skills/analysis/analysis_skill.py` | 55% | **85%** |
    | `skills/risk/risk_skill.py` | — | 82% |
    | `skills/market_data/market_data_skill.py` | — | 84% |
    | TOTAL (skills+clients+core+orchestrator) | — | **69.0%** |
    `fail_under = 64` (measured minus ~5, since the before/after measurement forms differ). **768 tests passing, 0 failing.** New suites: `test_live_poll_loop.py` (66), `test_live_bootstrap.py` (63), `test_live_tick_exit.py` (102), `test_live_execution_and_socket.py` (87).
    - ⚠️ **This gotcha's numbers are the 2026-10-22 *morning* snapshot and three of its "remaining gaps" are now CLOSED** — `trading_orchestrator.py` 15% → **100%** (gotcha 49), `core/sl_tp_engine.py` 44% → **100%** (gotcha 50) and `clients/capital_api.py` 19% → **100%** (gotcha 54). Current canonical figures live in **gotcha 54**: **1319 passing, 78.13% total, `fail_under = 75`** (64 → 69 by gotcha 49, → 72 by gotcha 53, → 75 by gotcha 54). **For the per-module breakdown — every module's cover%, uncovered count, DONE/PARTIAL/OPEN status and owning suite — read the "Test coverage — status board" section of [`NEXT_SESSIONS.md`](NEXT_SESSIONS.md), which is the single source of truth. Do not re-quote per-module numbers into this file**; that duplication is exactly how this gotcha's own table went stale.
    - **Gaps that are still real, ranked by uncovered statements on risky paths:** `clients/firestore_api.py` 12% (140), `skills/reporting/reporting_skill.py` 11% (209, low risk), `clients/log_publisher.py` 30% (61), `clients/sqlite_api.py` 51% (91). **Neither `skills/backtesting/backtesting_skill.py` nor `clients/capital_api.py` is on this list any more — both reached 100% (gotchas 53, 54).** Everything left is reporting, alerting, logging and firestore: no module that can place an order or price a trade is now under-covered.
    - **Testing the infinite poll loop:** `_poll_positions`'s `reconcile_every = max(1, 60 // interval)` means a reconcile is 60 real seconds away at any sane interval, and `60 // 0.01` is huge rather than small. Wall-clock-bounded tests are also flaky under coverage overhead. The working pattern is a `fast_clock` fixture that monkeypatches `asyncio.sleep` to an immediate yield and a runner bounded by **yield count, not elapsed time**; `interval=61` makes `60 // 61 == 0`, so `max(1, 0)` reconciles every cycle.

45. **`DataFrame.asof` returns only rows with NO NaN in ANY column — so every MTF gate silently no-ops during indicator warm-up.** `_check_mtf_confluence` looks its row up with `.asof()`, and `h1_bb_middle` is NaN for the first `h1_bb_period` (20) rows. Any lookup landing in the warm-up window returns an all-NaN row and the gate allows rather than blocks. Each timeframe also subtracts its own offset first (H1 −1h, 4h −4h, daily −24h) to avoid reading a forming bar, so a frame must *start* before `lookup − offset` or asof finds nothing. Both bit the previous tests here. Also note `load_h1_history` does **not** resample — it indexes whatever candles it is handed, so 60 M5 candles become 60 "H1" rows.

46. **Breadth expansion FAILS on this universe — and gross Sharpe falls too, so it is not a cost problem (2026-10-22, resolves NEXT_SESSIONS prompt 6).** `--class-cap` and `--max-corr` are now CLI args on `trend_portfolio.py` (`class_cap` was the binding constraint and was not exposed).
    | class_cap / max_n | n | avg corr | eff. breadth | **gross** SR | **net** SR | IS | OOS | cost % gross | B&H SR |
    |---|---|---|---|---|---|---|---|---|---|
    | 4 / 13 (baseline) | 13 | 0.140 | 4.9 | **0.37** | **0.30** | 0.18 | 0.38 | 19.8% | 0.34 |
    | 6 / 20 | 19 | 0.129 | 5.7 | 0.20 | 0.12 | — | — | 40.9% | — |
    | 8 / 20 | 20 | 0.111 | 6.4 | 0.23 | 0.15 | — | — | 33.0% | — |
    | 12 / 30 | 30 | 0.068 | 10.1 | 0.24 | 0.15 | 0.15 | 0.18 | 37.0% | 0.47 |
    | 20 / 40, corr 0.40 | 24 | 0.038 | 12.8 | — | −0.03 | 0.09 | −0.16 | 137% | 0.52 |
    | uncapped (max breadth) | 48 | 0.051 | **14.1** | **−0.05** | **−0.16** | −0.07 | −0.21 | 198% | 0.50 |
    - Effective breadth **does** rise as intended (4.9 → 14.1) and average correlation falls (0.140 → 0.051). Performance falls monotonically anyway.
    - **Why: IC is not uniform, and Grinold's `IR ≈ IC × √breadth` assumes it is.** At 48 names, per-instrument net Sharpe is **>0.10 for only 9 (19%)**, flat for 18, and **negative for 21** (AUDNOK −0.43, EURHUF −0.41, AU200 −0.41 …). The edge is concentrated in ETHUSD +0.38, GOLD +0.33, FEEDERCATTLE +0.22, US100 +0.20, HEATINGOIL +0.17. The candidate pool is **75 of 117 currency crosses**, which contribute ~nothing.
    - The screen is already ranked cheapest-friction-first, so every marginal instrument is strictly more expensive *and* (measurably) edge-free. **The breadth lever was already exhausted at 13 names.**
    - **Buy-and-hold beats the trend overlay at every breadth level, and the gap widens with breadth** (0.34 → 0.52 as the universe widens, because diversified B&H genuinely benefits). Report it alongside any Sharpe.
    - DSR at n_trials=5 never exceeded 0.69; baseline DSR is **0.938 at n_trials=1** and 0.686 at n_trials=4 — still under 0.95. Half-Kelly implies a **15%** vol target, not the 20% configured.

47. **Bonds / interest rates cannot add breadth on this broker — measured, not assumed (closes the other half of NEXT_SESSIONS prompt 6).**
    - `bonds_group` holds exactly **5** epics (US, TY, FV, TU, AUL); `interest_rates_group` holds **2** (FF, SRA). That is the whole universe, not a subset.
    - Only **2 pass the friction screen** (AUL 0.046, US 0.078) — and they are already in it, as the two `itype: UNKNOWN` rows. TY/FV/TU fail on friction (0.24 / 0.13 / 0.33 vs the 0.08 cap): CFD bond daily ranges are 0.06–0.56% of price, so even a 0.02 spread is 10–33% of the range. FF and SRA return **no `high`/`low` at all**, so no range can be computed.
    - Both survivors have only **2.1–2.9 years** of weekly history on Capital.com (AUL 110 bars from 2024-09, US 151 from 2023-12) against GOLD's **1000 bars / 19.1y**, so `fetch_weekly.py`'s ≥10y filter correctly drops them and they can never enter the 40-year weekly validation.

48. **The gotcha-29 bar repair landed in the HOST STRAY DB, not the live volume.** As of 2026-10-22: host `/data/trading.db` has GOLD **188,260** M5 bars through 2026-10-21 15:35, while the live volume (`/var/lib/docker/volumes/stockscreener_trading_data/_data/trading.db`) has only **163,867** through 02:10. Gotcha 35's "repaired data (188,197 bars)" is the **stray** DB. So gotcha 24's advice inverts for GOLD right now: the stray DB is the *good* one for GOLD backtests, and anything run inside a container (including `backtest-runner`) still sees starved GOLD data. Live trading is unaffected — the live bot builds its buffer from the broker, not the DB.

49. **`orchestrator/trading_orchestrator.py` is at 100% (was 15%), and the four bugs covering it surfaced are all FIXED (2026-10-22).** New suite `tests/unit/test_live_orchestrator_loop.py` (83 tests, fake-skill harness, no network). Suite **912 passing / 0 failing / 71.69%**; `.coveragerc` floor raised 64 → 69. **Live-path only — `run_skills_backtest.py` never instantiates `TradingOrchestrator`**, confirmed by a GOLD 2y regression: 493 trades / WR 21.70% / PF 1.0501 vs gotcha 41's 492 / 21.54% / 1.046, the +1 trade explained by the DB growing 188,260 → 188,435 bars. ⚠️ **DEPLOYED 2026-10-22 — see gotcha 55** (this said "NOT deployed").
    - **(a) The reverse-signal close invented `pnl=0.0` / `entry_price=0.0`.** Gotcha 22's regression in miniature: the breakers compute `is_loss = pnl < 0`, so 0.0 scored every reverse exit as a **win** and added nothing to the daily-loss accumulator. Verified against the real `RiskSkill` — four consecutive losing reverse exits left `consecutive_losses` at **0**, the circuit breaker untripped, `_daily_realized_pnl` at **0.0**. **Fixed:** both are now `None` ("unknown"), so the breakers skip rather than mis-score. `entry_price` had to go to None too — with `pnl=None` and `entry_price=0.0` the price-distance fallback computes `(close − 0.0)` and scores a phantom win anyway. The orchestrator genuinely cannot know either figure (no broker client; the risk skill tracks only deal id + direction), and it does not need to: **`_poll_positions` books the same close ~10s later with the real P&L from `get_realised_pnl(deal_id)`.**
    - **(b) The close was booked BEFORE the broker result was checked**, so a refused close still ran `on_position_closed`, which cleared the open-position flags — letting the next bar stack a second position and defeating the abort branch that exists precisely to prevent that. **Fixed:** the result is checked first; a refused close books nothing and aborts.
    - **(c) `on_position_closed` cleared the position flags unconditionally — the real accumulation hole.** A close event for a deal that is no longer the tracked one wiped the *current* position's flags. This is guaranteed by the reverse path: it closes D-OLD, opens D-NEW 1.5s later, and then the activity poll books D-OLD's close again (`processed` is a closure local to `_poll_positions`, so the orchestrator's own close never registers in it — **every reverse close is booked twice**). Demonstrated: booking D-OLD's close with D-NEW tracked left `has_open_position=False` while D-NEW was live at the broker. **Fixed:** flags clear only when `open_position_deal_id` is None (not yet reconciled — must still clear, or the gate wedges) or equals the closing `deal_id`; a mismatch logs a warning and keeps them. The stale close is still booked in full — only the flags are protected.
    - **(d) `on_candle`'s error handler defeated itself.** A skill that forgot to `return context` handed back None; the next attribute access raised, and the handler's own `context.errors.append(...)` then raised `AttributeError` on None, so the exception **escaped `on_candle`** (caught upstream by `CapitalWebSocketClient._handle_message`, so the bot survived with one log line per failed bar). **Fixed:** a new `_run_skill()` wrapper names the offending skill at ERROR level and carries the previous context forward — safe because skills mutate the context **in place**, so `return context` is redundant with the mutation and no gate decision is lost. The handler is also now `getattr`-guarded so no future variant can resurrect it, and logs at ERROR with `exc_info=True` (the traceback was the missing diagnostic; the `print` is kept so anything grepping `bot-output.log` still matches).
    - Also fixed: `stop()` raised `TypeError` if `start()` never ran — a shutdown path that raises masks whatever caused the shutdown; runtime now falls back to 0.0.
    - **Still open, deliberately:** a **blocked** signal `return`s before stage 6, so the monitoring heartbeat does not run on a blocked bar, while a **no-signal** bar does run it. Pinned by a test. Left alone because it is a structural question (restructuring the early returns) with no observed harm, not a correctness bug.
    - The guards that already worked, now covered: `warming_up` suppresses analysis/risk/execution entirely (a leak is ~300 market orders per restart, not one); the 1.5s settle wait sits between close and re-entry; `Context.is_allowed` defaults False so an unregistered risk skill fails closed.

50. **`core/sl_tp_engine.py` is at 100% (was 44%) — `tests/unit/test_sl_tp_engine.py`, 61 tests.** Only `fixed` was covered before, because `method: fixed` is what all six deployed instruments use; the other four methods are one config line from live. Assertions are exact prices, not inequalities — a factor-of-50 error (gotcha 31) passes every inequality test.
    - **Fixed: `calculate_supertrend_sl_tp` had no "stop on the losing side of entry" guard** (the fibonacci path has an equivalent one). `sl_distance` is `abs()`, so a BUY whose band sat above entry got a stop **above** entry — hit on the next tick, with a TP sized as though the trade were sound. The band's distance is now mirrored to the correct side. **Byte-identical whenever the band is already on the correct side**, which is every reachable case today: signal direction derives from `supertrend_direction` and `supertrend_value` is the lower band when up / upper when down, so a flip-derived BUY always has the band below price. Latent robustness, not an active loss.
    - A band exactly **at** entry still yields a zero-width trade (SL == TP == entry). Left as-is — there is no non-arbitrary minimum distance to substitute, and it is unreachable under `method: fixed`.
    - Config traps the tests pin (all still present — these are documentation, not bugs):
      - **`method: atr` silently falls back to fixed 20/40 pips** whenever ATR is None, 0, negative, or NaN — i.e. during indicator warm-up after every restart. No warning. Same silent fallback for `fibonacci` with a missing swing, `supertrend` with no band, and any unrecognised `method` string.
      - **The dispatcher's fixed defaults are 20/40 pips (R:R 2.0)**, matching no deployed instrument (GOLD is 15/**60** — this said 15/45, the same stale TP gotcha 52 caught in three other places). A config that loses its `stop_loss_pips` key trades 20/40 rather than failing.
      - **`fibonacci_tp_level` is snapped to the nearest value in `FIBONACCI_LEVELS`**, so asking for a 2.0 extension silently executes 1.618. The config value and the executed value are not the same number.
      - `sl_pct: 0.5` means **50%**, not 0.5% — the field name reads the other way.
      - Fibonacci TP is projected from the swing (`swing_low + range * ratio`), independent of entry, so a late entry on the same swing gets a much worse R:R than an early one.

51. **Time-based flatten for the live path — built and tested 2026-10-22, shipped DISABLED, and the measurement is why. Addresses NEXT_SESSIONS prompt 2 (gotcha 19).**
    - New `core/time_exits.py` → `TimeBasedFlatten`: pure, clock-injected, UTC-normalising. Wired into **both** halves of the live path, sharing **one object** so they cannot be configured inconsistently: `RiskSkill._evaluate_entry_gates` gate 4 (refuse entries past the flatten moment) and `main.py:_poll_positions` (ask the broker to close). The poll loop pulls it off the risk skill (`getattr(orchestrator.skills.get('risk'), 'time_exits', None)`).
    - **Both halves are required, and the entry block is the non-obvious one.** Flattening alone is cosmetic: the −$153 US100 position was opened at **20:00 Friday, inside its own allowed session**, so a 20:45 flatten with entries still open would simply re-open it and carry it over the weekend anyway.
    - **⚠️ THE MEASUREMENT THAT MATTERS — the weekend-carry cohort holds ALL the backtested profit on both instruments.** Trades open across a Friday 20:45, 2y backtests:
      | | carry trades | their net | all other trades | their net | total |
      |---|---|---|---|---|---|
      | GOLD | 61 (12.4%) | **+$12,234** | 430 | −$9,532 | +$2,702 |
      | US100 | 97 (3.9%) | **+$15,780** | 2,388 | −$28,880 | −$13,100 |
      Flattening every Friday removes exactly that cohort. On the best evidence available it would take GOLD from +$2,702 to roughly −$9,532 and US100 from −$13,100 to −$28,880. **So the configs ship `enabled: false`** — the mechanism is built, tested and ready, and turning it on is a deliberate, measured decision, not a default.
    - **That is partly survivorship and is NOT proof the flatten loses money.** Losers hit their 1:3–1:4 stop fast, so any long-hold cohort skews to winners; GOLD's carry trades have a median hold of **86.8 h** against the strategy's usual ~3 h. A flatten closes them at the Friday price (partway to TP), it does not convert them to full losses. The true cost needs the flatten **simulated in `run_skills_backtest.py`**, which does not model it. The magnitude is simply too large to enable blind.
    - **The entry gate IS active in backtest; the flatten is not.** `run_skills_backtest.py:342` builds the same `RiskSkill`, so `risk.time_exits` reaches the backtest and blocks Friday-evening entries using bar time. Only the *close* half is live-only. Measured with it enabled, GOLD 2y went 493 → **491 trades, PF 1.0501 → 1.0450** (the 2 removed entries are the whole effect; 0 Friday ≥20:45 entries remain). US100 would lose 11 such entries. With the shipped `enabled: false` both are untouched.
    - **It reads `risk.time_exits`, NOT `time_based_exits`.** `time_based_exits` stays dead, deliberately — the base config carries `eod_hour: 16` + `eod_enabled: true`, and honouring that in the live path would flatten every US100 position from 17:00 onward (its whole session is 13:00–20:59). Every switch defaults **off**.
    - **The poll loop books NOTHING on a flatten** — it only calls `execution.close_position()`. The next activity poll detects the close and resolves the real figure via `get_realised_pnl()`. Inventing a P&L here would repeat gotcha 49(a): `0.0` scores as a win and leaves the daily-loss accumulator at zero. A **refused** close is un-flagged and retried next poll rather than recorded as done; `flatten_requested` is intersected with `known` each tick so one close is requested per deal, not one per 10 s; a missing execution skill logs once, not 8,640×/day.
    - **`validate(skip_hours)` catches the trap prompt 2 named**: a flatten time with entry-allowed hours still after it. Reports *truncates the session* when `block_entries_after_flatten` is on, *will churn* when off. It flags the naive `daily_hour: 16` on US100 (hours 17–20) and on GOLD (hours 17–23). GOLD also logs one **expected, benign** warning for its Friday 20:45 (hours 21–23) — XAUUSD is shut 21:00 Fri → 22:00 Sun and the validator has no market-hours calendar; documented in `GOLD.yaml`.
    - ETHUSD deliberately has no `time_exits` block at all: it trades the weekend, so there is no gap to cap.
    - **Found while wiring it:** `US100.yaml` already had `trading_hours.friday_close_hour: 20` under `trading_hours.enabled: false` — the intent existed and nothing read it. And `production_orchestrator.EndOfDayClose` has two defects if anyone reaches for it: `datetime.now()` (**local time**, compared against a UTC config hour) and `hour >= close_hour`, true for every later hour of every day.
    - Cover: `tests/unit/test_time_exits.py` (72 tests — clock, tz/string parsing, the gate, and the poll loop closing/retrying/booking-nothing). Module at 100%; `main.py` and `risk_skill.py` hold at 95% / 82%. Suite **984 passing, 0 failing, 72.67%** (floor 69).
    - ⚠️ **`max_hold_hours` now exists TWICE, on opposite sides — do not enable one alone.** `risk.time_exits.max_hold_hours` (new, this gotcha) is **live-only**; `time_based_exits.max_hours` (`backtesting_skill.py:196`, exit at `:408`) is **backtest-only** and was already there. Both default to `0`, so nothing diverges today, but setting either one by itself silently makes live and backtest disagree on hold time. The EOD/Friday *flatten* has no backtest counterpart at all — `max_hours` is the only time exit the backtester models.
    - **`guaranteedStop` is still false on every position**, so an *intraweek* gap (a Wednesday news spike) remains uncapped. The Friday flatten never addressed that; it is a separate decision.


52. **Config keys this file named wrong, and one dead function carrying a 100x error. Audited 2026-10-22, docs corrected.** The gotcha-6 lesson generalises: the *substance* of an entry can be right while the *key name* is wrong, and that is the hardest kind to catch because the surrounding explanation reads as authoritative.
    - **`risk.sl_pips` / `risk.tp_pips` are read by nothing.** The real keys are **`risk.stop_loss_pips` / `risk.take_profit_pips`** — those are the three keys (with `pip_size`) that both propagation copies move into `analysis.sl_tp`: `orchestrator/main.py:118-122` (live) and `run_skills_backtest.py:71` (backtest). All six deployed instrument YAMLs use `stop_loss_pips`; none has `sl_pips`. This file asserted the wrong name in **three** places — the "Config cascade (important)" block, the "Configuration Rules" list, and gotcha 1 — i.e. in both of the sections someone reads first, the same blast radius as the EOD errors.
      - Why the wrong name was plausible: **`execution_skill.py:49-50` genuinely reads `sl_pips`/`tp_pips`** — but off its own `execution:` section, not `risk:`. The name is real, the section was not. Following the old instruction (`risk.sl_pips: 20`) edits nothing, produces no warning, and leaves you concluding the propagation is broken.
    - **`risk.max_position_size` is a dead key.** `trading_config.yaml:173` sets `max_position_size: 10.0`; no production code reads it (only a test fixture does). `risk.position_size_pct` *is* read (`risk_skill.py:119`) and validated, but it does not set the order size either — the size the broker receives is `execution_skill.py:51`'s `position_size`, default **0.5**. That is gotcha 26, still live.
    - **`RiskSkill._calculate_sl_tp` (`risk_skill.py:426`) is dead code hardcoding `pip_value = 0.01` with the comment "For GOLD, 1 pip = 0.01".** GOLD's actual `pip_size` is **1.0** (`GOLD.yaml:99`, gotcha 8) — a **100x** error. Zero callers today, in production *or* tests, so nothing is wrong live; but anyone wiring it up gets GOLD stops 100x too tight. Left in place rather than deleted (removing it is a code change, not a doc fix), flagged here. Same family as gotcha 31's 50x `slippage_cost_usd` typo and gotcha 50's wrong-side-stop guard: a magnitude error sitting in a path no test exercises.
    - **GOLD's TP was recorded as two different wrong numbers.** "Instruments & Strategy" said 40, the deployed-parameters table said 45; the YAML says **60** (R:R 1:4). Gotcha 35's "baseline SL15/TP60" matches the YAML, so the measured backtests in this file were run on the live geometry and remain valid — only the prose was stale.
    - **The "Live GOLD Strategy Parameters (as deployed)" table had four wrong rows** (TP, position size, EOD close, plus the stale uncommitted-changes warning above it). It is an Apr-2026 screenshot artefact whose "confirmed live" header outranked, in apparent authority, the later gotchas that corrected it. Corrected in place; **prefer reading `GOLD.yaml` over that table.**

53. **`skills/backtesting/backtesting_skill.py` is at 100% (was 59%, 111 uncovered) — `tests/unit/test_backtest_engine.py`, 168 tests. Six findings; two fixed, four pinned as documentation (2026-10-22).** Every PF, win rate and P&L figure this project quotes comes out of this module, and an arithmetic error here does not crash — it produces a confident wrong number, which is exactly what gotcha 31 was. Assertions are **exact values**, never inequalities (gotcha 50's lesson); genuine float divisions use `pytest.approx(..., rel=1e-12)`.
    - **FIXED (a): `profit_factor` reported 100x the gross win total on a loss-free run.** `total_wins / max(total_losses, 0.01)` used a divide-by-zero guard as a *value*, so a single $60 win came out as **PF 6000.0**. `optimize_params.py:71` RANKS the grid on `pf * 0.6 + sharpe * 0.4`, so such a run scored ~3,500 and would outrank everything real. Now reports the **999.0 sentinel** already used for this case by `cloud-function/api/live_report.py:54` — JSON-safe (`backtest_api.py:456` does `json.dumps` on results, so `float('inf')` was not an option) and obviously a sentinel. **Arithmetically identical for any run with ≥1 cent of losses**, i.e. every real run; the regressions below confirm it. What capped the real-world damage: `MIN_TRADES = 30` (`optimize_params.py:148`) drops a thin run before ranking, and `sweep_eval.py` returns `None` rather than scoring a run with no losses.
    - **FIXED (b): `_compute_position_size`'s docstring contradicted its code.** It claimed 'steps' mode adds `size_increment` per `scale_every_usd` of *"profit above initial_capital"*. The code (`:271`) is `int(self.capital / scale_every_usd)` — **total capital, from the first trade, never referencing `initial_capital`.** A $10k account with `scale_every_usd: 1000` is already at **10 steps on trade 1, at zero profit** — the docstring understates the starting size by `initial_capital / scale_every_usd`. Docstring corrected; no behaviour change. This is the compounding mechanism behind gotcha 25's `+$733,912`.
    - **(c) GOLD's `dynamic_sizing` is INERT, and its comments describe behaviour the code cannot produce.** `GOLD.yaml` sets `enabled: true` with `size_increment: 0.1` against base `position_size: 10`, so `max(steps × 0.1, 10)` stays pinned at **10 until capital reaches $100,000** — ten times the account. Its comments claim "+0.2 oz per step" and "$1k→12oz, $2k→14oz, $5k→20oz"; actual size at $11,000 capital is **10**. **The reassuring half: every trade in gotchas 35/41/49's GOLD runs was a flat 10 oz, so those numbers are NOT contaminated by compounding.** `GOLD.yaml` was deliberately **not** edited — it is live bot config and a comment fix is not worth a config touch; the correction lives here.
    - **(d) A break-even trade (`pnl == 0.0`) is counted in `losing_trades` but not in `total_losses`.** `_close_position:457` splits on `pnl > 0`; `get_results:496` sums losses with `pnl < 0`. The trade lands in the loss *count* but not the loss *sum*, so `win_rate` is deflated and `avg_loss` is understated in magnitude (negative sum ÷ inflated count) while `profit_factor` sees no loss at all — **the summary statistics disagree with each other about what the trade was.** Same family as gotchas 22 and 49(a). **Pinned, not fixed:** no two-bucket split preserves every identity at once (counting it as neither breaks `(100-win_rate)/100 == losing/closed`, which `expectancy` relies on), and it is unreachable on all six deployed instruments — every one charges non-zero spread + slippage, so `pnl` is never exactly 0.0.
    - **(e) `if exit_price:` (`:411`) is a truthiness test on a float**, so an exit computed at exactly `0.0` is silently discarded. Only `TIME_EXIT` can produce one (`close_price = candle.get('close', 0)`): a candle with valid high/low but no `close` key sets `exit_reason='TIME_EXIT'` and then has the exit dropped — the trade stays open and re-evaluates forever. **It fails CLOSED, which is the safe direction** (booking a 0.0 exit price would record a ~100% loss), so the guard is accidentally protective and the hazard is the silent retry, not a wrong number. Pinned, not fixed — `trading.db` candles always carry `close`.
    - **(f) `max_drawdown_pct` (`:539`) divides by the highest equity EVER reached, not the peak that drawdown fell from.** It is therefore not the standard max-DD%, and when the account never makes a new high it is simply "drawdown as a percentage of starting capital", which is unbounded. **This is where gotcha 28's "maxDD 1346%" comes from** — the prose reading there ("the account is wiped ~13× over") is the right conclusion, but the number is not a percentage of anything the account ever held. Pinned, not changed: the denominator is baked into every maxDD% quoted in gotchas 28/31/35/46.
    - **The pre-existing `test_backtesting_skill.py::test_sl_hit_before_tp` is VACUOUS and was the only cover for the SL-vs-TP question.** It never calls the skill — it re-implements the two comparisons inline and asserts `sl_hit or tp_hit`, true whenever either level is touched, so it could not fail. The code *does* make a documented choice: SL is the `if`, TP the `elif`, under the comment "Check Take Profit (only if SL not hit)" (`:390`), so **a bar spanning both levels books the STOP.** That is the conservative call and the right default for a bar-level simulator. Now pinned properly, including the consequence: precedence ignores *where* in the bar each level sits, so a bar that opened above TP and only later dipped to SL is still booked a loss — which understates backtest P&L rather than overstating it.
    - **Exit prices are booked at the LEVEL, not at the candle's extreme.** A BUY whose stop is 90 and whose bar gapped to a low of 70 is still filled at exactly 90.0 — the simulator assumes a perfect stop fill with no gap slippage. Pinned. This is the backtest-side counterpart of gotcha 19's uncapped weekend gap: live has no such guarantee (`guaranteedStop: false` on every position).
    - **`time_based_exits.max_hours` had NO cover before this suite.** `tests/unit/test_time_based_exits.py` tests `production_orchestrator`'s `IntraDayTimeExit`/`EndOfDayClose` — same concept, **different classes, and not the live path** (gotcha 19). This module's own exit at `:398` is now covered: boundary (fires at exactly `max_hold`), precedence (SL and TP both beat an overdue time exit), the `except Exception: pass` on an unparseable clock, and the `max_hours: 0` default that makes it inert.
    - **Regression-checked on both instruments after the fix** (`DB_PATH=/data/trading.db` — per the correction below, the host DB is now the good one for *both*):
      | | this run | prior documented | verdict |
      |---|---|---|---|
      | US100 2y | 2485 / 25.473% / PF **0.9728** / −$13,100 | 2485 / 25.473% / 0.9728 (gotcha 41) | **exact match, zero drift** |
      | GOLD 2y | 493 / 21.704% / PF **1.0555** / +$3,342 | 493 / 21.70% / 1.0501 (gotcha 49) | trades + WR exact; **PF +0.0054 is data drift** |
      **The PF fix is provably inert on both runs, and the GOLD delta is not attributable to it.** Each run has thousands of dollars of gross losses (GOLD $60,216; US100 far more), so `max(total_losses, 0.01)` was already just `total_losses` — on GOLD's own `trades.csv` the old and new expressions evaluate **bit-identically** to `1.0555001992825828`, which is also what `get_results` wrote to `report.json`. GOLD drifted because its series genuinely extended (its DB was 3h stale and gained real bars; US100's was 7h stale and the catch-up fetch returned only duplicates), so the tail trades exit at slightly different levels — same 493 trades, same 107 winners, different cents.
      Also measured: **`zero-pnl = 0` on both runs**, which is the empirical confirmation that finding (d) below is unreachable on the deployed instruments.
    - **Suite: 984 → 1152 passing, 0 failing; TOTAL 72.67% → 74.80%** (bare `--cov`). `.coveragerc` floor raised **69 → 72**. Per-module figures live only in the NEXT_SESSIONS status board, per gotcha 44.
    - **Correction to gotcha 24:** its "host stray DB has US100 only 1,500 bars" row is **stale**. As of 2026-10-22 the host `/data/trading.db` holds **GOLD 188,466** and **US100 202,994** M5 bars, both current to today — healthier than the live volume (GOLD 163,894 / US100 202,774). So `DB_PATH=/data/trading.db` is now correct for **both** GOLD and US100 backtests, not just GOLD. **⚠️ Superseded for US100 on 2026-10-23:** US100 was re-based to bid/UTC in the **live volume only** (gotcha 57). The host stray DB's US100 is still mid/local, so **run US100 backtests in the container**, or set `DB_PATH` to the volume path.

54. **`clients/capital_api.py` is at 100% (was 19%, 172 uncovered) — `tests/unit/test_capital_api.py`, 167 tests in 23 classes. Two live bugs fixed, one misleading docstring corrected, six hazards pinned — the date-range forwarding under (c), plus (d)–(h) (2026-10-22). Closes NEXT_SESSIONS prompt 5.** This is the only module in the repo that can move money, and `place_order` was at **0% cover**.
    - **The harness decision is the finding behind the finding.** Every other suite here stubs `_request` and asserts on params — right for "did we send the correct filter", useless for `_request` itself. This suite patches one level lower (`requests.request` / `requests.post`) and returns **real `requests.Response` objects**, because `Response.__bool__` returns `self.ok` and `raise_for_status()` must attach a genuine `HTTPError`. A hand-rolled fake response is *truthy*, as plain objects are, and would have hidden bug (a) below while making the test assert the wrong behaviour. **Pinning a broker boundary with fakes more forgiving than production is how a client passes its tests and still fails live.**
    - **FIXED (a): `create_session`'s rate-limit branch was dead code.** `if e.response and e.response.status_code == 429` — and `Response.__bool__` is `self.ok`, i.e. **False for every 4xx/5xx**. So the one status the branch exists to classify is the one status it could never see; a 429 fell through to the generic `Failed to create session: {e}`. Now `is not None`. **Honest impact: cosmetic today.** The HTTPError text carries "Too Many Requests", which `idempotency.is_transient_error` already matches, and no production caller retries session creation (all five callers are scripts). Fixed because the *shape* is the hazard — a classification guard that silently never fires, same family as gotcha 50's wrong-side stop and gotcha 53(e)'s truthiness test on a float.
    - **FIXED (b): `get_historical_prices` returned ACCOUNT-LOCAL timestamps, disagreeing with the DB writer by the account offset.** It preferred `snapshotTime` (UTC+2, DST-varying) over `snapshotTimeUTC`, while `fetch_data.parse_candle:145` — the DB/backtest writer reading the *same endpoint* — picks the UTC field and documents exactly why ("snapshotTime is local/exchange time and varies with DST"). Two readers of one endpoint, two hours apart. Demonstrated on one identical broker row: client `12:00`, DB `10:00`. Now aligned on `snapshotTimeUTC`.
      - **Scope is provable, not assumed: three production callers, all the live warm-up (`main.py:681`/`:700`/`:710`), and ZERO references to this function anywhere in the backtest path** (`run_skills_backtest.py` does not mention it). So no backtest number can move — confirmed by the regression below being bit-identical.
      - **Why it was harmless on the running bots:** indicators are value-based, not label-based, and the one label-sensitive consumer — `load_h1_history` feeding `_check_mtf_confluence`'s `.asof()` lookups (gotcha 45) — is gated by `require_h1_bb`, which is **false on GOLD, ETHUSD, US100, EURUSD and BTCUSD**. It is **true on SILVER**, which is stopped. A 2h index shift under an `asof` lookup is a silent gate failure, so enabling that gate before this fix would have been the live bug.
      - **This is a concrete answer to gotcha 36's last open lead** ("check live candle timestamps against DB bars before trusting GOLD live/backtest parity"). The live warm-up buffer *was* 2h off the DB bars. It does not explain the excess live trades on its own — warm-up bars generate no signals (`warming_up = True`) — but it is one of the two named leads, now closed.
    - **FIXED (c): the docstring's own worked example was a guaranteed 400.** It passed `from_date` *and* `to_date` together; `from`+`to` is rejected by this API (gotcha 30), which has no date-range mode. Rewritten to the backward-pagination form (`to` + `max`), with the constraint stated in the docstring. Same family as gotcha 53(b) — documentation describing behaviour the code cannot produce.
    - **PINNED (d): `confirm_order` returns `{}` on ANY failure, and the caller then substitutes the dealReference for the dealId.** `execution_skill.py:272` is `deal_id = confirm.get('dealId') or deal_reference`, so a transient error on the confirm leg makes the bot track the position under its **dealReference** — a different ID space, resolving one to the other being this function's entire job. Nothing rejects the trade, and `get_realised_pnl` joins `/history/transactions` on dealId, so that row can never resolve a real P&L. **Bounded, and the bound matters:** the 60s REST reconcile re-keys `known` from `get_open_positions()` by the broker's own dealId and overwrites `risk.open_position_deal_id` (`main.py:465`). Left as-is deliberately — raising, or treating empty as a rejection, would make the bot forget a position that is live at the broker, which is gotcha 49's accumulation hole in a new place.
    - **PINNED (e): `get_activity` returns `[]` on any failure — indistinguishable from a quiet market.** This is the *exact* shape of gotcha 22, which returned `[]` for three months for a different reason and went unnoticed because an empty list is a legitimate answer. Kept swallowing (it is polled every 10s from `_poll_positions`; raising would take the loop down), pinned so the blind spot is documented. Contrast `get_open_positions`, which correctly **raises** — an empty list there would read as "flat at the broker" and book every tracked position as closed.
    - **PINNED (f): `CAPITAL_ENVIRONMENT` is shadowed by the signature default and does nothing.** `(environment or os.getenv('CAPITAL_ENVIRONMENT', 'demo')).lower()` — `environment` defaults to the non-empty string `'demo'`, which short-circuits the `or`. So setting `CAPITAL_ENVIRONMENT=live` in `.env` is inert for every caller that omits the argument, despite this file documenting it as the demo/live switch. **Not fixed, and the direction is the reason:** the shadowing fails towards *demo*, so honouring the env var would newly make it possible to send real orders by editing a dotenv file. That is a deliberate decision, not a coverage-session cleanup. Also pinned: only the exact string `'live'` selects the live endpoint, so a typo (`'liv'`, `'production'`) fails safe to demo.
    - **PINNED (g): `guaranteedStop` defaults to `False` in `place_order` — this is the origin of gotchas 19 and 51.** Every live position carries it, so every weekend and news gap is uncapped. Also pinned: `place_order` is the only write call here that **never** swallows (contrast (d) and (e)) — an order that may or may not have reached the broker must surface; a 200 with no `dealReference` is logged as success and returned, so the absence of that guard is known rather than assumed; and `stop_level=0.0` is sent rather than dropped, because the guard is `is not None` and not truthiness — the opposite of gotcha 53(e).
    - **PINNED (h): a null price block or null bid raises, and that fails CLOSED.** `price.get('openPrice', {})` only defaults when the key is *absent*, so an explicit JSON null reaches `.get` on None. The warm-up catches it (`main.py:687`, "M5 prefetch failed — continuing without warm-up") and the bot starts with cold indicators rather than fabricated prices. Unlike `parse_candle` there is also **no bid→ask fallback**: a row carrying only an ask maps to `0.0`. Deliberately not aligned — substituting an ask for a bid shifts the candle by the spread, the same corruption `parse_candle`'s own comment warns against for mid prices. The two functions fail in opposite directions on the same row and only one of them can be right.
    - **Regression-checked on both instruments** (`DB_PATH=/data/trading.db`):
      | | this run | prior documented | verdict |
      |---|---|---|---|
      | GOLD 2y | 493 / 21.703853955375255% / PF **1.0555001992825828** / +$3,342 | 493 / 21.704% / 1.0555001992825828 (gotcha 53) | **bit-identical, to the last digit** |
      | US100 2y | 2488 / 25.482315% / PF **0.9732802257074101** / −$12,880 | 2485 / 25.473% / 0.9728 / −$13,100 (gotcha 53) | **+3 trades = tail drift**, not the fix |
      Both DBs grew between the runs (GOLD 188,466 → **188,534**, US100 202,994 → **203,107**). GOLD's +68 tail bars produced no new trades, hence an identical float; US100's +113 produced 3, the same drift mechanism gotcha 53 documented for GOLD. **Neither number can be affected by this session's change in any case** — `get_historical_prices` has three production callers, all the live warm-up in `main.py`, and zero references anywhere in the backtest path. The regression is confirmation, not the argument.
    - **Suite: 1152 → 1319 passing, 0 failing; TOTAL 74.80% → 78.13%** (bare `--cov`, clean tree). `.coveragerc` floor raised **72 → 75**. Per-module figures live only in the NEXT_SESSIONS status board, per gotcha 44.
    - ⚠️ **MEASUREMENT TRAP, new and worth more than it sounds: do not edit a source file while a `--cov` run is in flight.** Coverage records line numbers from the module it imported and maps them onto the file as it stands at *report* time, so any edit that shifts lines makes covered statements report as missing. Doing exactly that here produced `capital_api.py` at **91% with 20 "missing" lines that were ordinary covered statements** — a phantom gap that reads identically to real uncovered code. The targeted re-run said 100%. Third entry in this family after gotcha 43 (`--cov=<dotted.path>` reloads numpy) and gotcha 44 (mixing measurement forms); when a coverage number surprises you, **re-measure on a clean tree before chasing it.**

55. **DEPLOYED 2026-10-22 16:13 UTC — and this file was WRONG about what was already live, in the most consequential way. Read the verification recipe below before trusting any "deployed" claim here, including this one.**
    - Command: `docker compose build trading-bot bar-updater && docker compose up -d trading-bot bar-updater`. Both services share build context `./trading-bot-skills` and the same Dockerfile, so **one build serves both** — that is why `bar-updater` could be included at no extra risk.
    - Images: trading-bot `sha256:19ecb886…`, bar-updater `sha256:873ad486…`. **Rollback target (previous trading-bot): `sha256:6a54ba10a420`.**
    - ⚠️ **THE LESSON. Before this deploy, gotchas 22, 38, 49 and all of NEXT_SESSIONS asserted the live container ran broken code where `get_activity()` returns `[]` — so "every close records `pnl = 0.0`, cooldowns never fire, both breakers are inert". That was FALSE.** The container (started 2026-10-21 15:50 UTC) already carried the `status==ACCEPTED` fix and `get_realised_pnl`. Proof, from `trade_history` in the two hours *before* the deploy: `−51.41`, `−6.79`, `+130.98`, `−11.16`, `−50.35`, all with `SL_HIT`/`TP_HIT`. Gotcha 22's whole consequence chain had been fixed live for a day, and the docs never caught up because a deploy happened without a doc update.
    - **So never infer deployment state from prose — measure it.** That is now one command:
      ```bash
      python3 trading-bot-skills/check_deployed.py          # full report
      python3 trading-bot-skills/check_deployed.py --quiet   # only the drift; exit 1 if any container is behind
      ```
      It checks each tracked fix marker in every container against the host tree, lists the running bots with the size the broker *actually* receives, and prints bar freshness. **Add a row to its `MARKERS` list whenever you land a live-path fix** — an unlisted fix is invisible to it. Equivalent by hand:
      ```bash
      docker exec stockscreener-trading-bot-1 grep -c '<symbol>' /app/<file>
      docker inspect stockscreener-trading-bot-1 --format '{{.Image}}'
      ```
      ⚠️ Two traps the script exists to encode, both of which produced wrong answers when done by hand first: `grep -c` **exits 1 on zero matches**, so `test -f f && grep -c s f || echo NOFILE` reports "file missing" for a file that merely lacks the symbol; and a marker must be a string **only the fixed code has** — `snapshotTimeUTC` looked like a fine marker for gotcha 54 but the *pre*-fix line contained it too, so it reported a stale container as up to date.
      Useful probes: `status==ACCEPTED` + `snapshotTimeUTC` (`clients/capital_api.py`), `_evaluate_entry_gates` (`skills/risk/risk_skill.py`), `_is_duplicate_candle` (`skills/market_data/market_data_skill.py`), `TimeBasedFlatten` (`core/time_exits.py`), `_run_skill` (`orchestrator/trading_orchestrator.py`), `_norm_ts` (`fetch_data.py`). **`ps` is not installed in the container** — list bot processes by reading `/proc/*/cmdline` from `python3`, not with `ps`.
    - **What this deploy actually added** (i.e. the real pre-deploy gap, once measured): gate unification (41), candle dedup (42), the four orchestrator fixes (49), `core/time_exits.py` (51, shipped **off**), the Supertrend wrong-side stop guard (50), `capital_api` UTC warm-up timestamps + the 429 guard (54), and `bar_updater`'s `_norm_ts` (29).
    - **`bar_updater`'s fix is visibly working for the first time.** All six epics were frozen at `2026-10-22 02:10` in the live volume — gotcha 29's exact signature, still live in that container. The first post-deploy cycle inserted **1008 candles** and brought every epic to `16:10`. Live *trading* was never affected by this (the bot buffers from the broker, gotcha 48), but container-run backtests and the dashboard were.
    - **`position_size` did NOT ride along — verified in the deployed image, not assumed.** GOLD and ETHUSD carry `position_size` only under `backtesting:` (10 and 2); root/`risk`/`execution` are all `None`, so the broker still receives `execution_skill.py:51`'s **0.5**. Gotcha 26 remains live and deliberate.
    - **NEW FINDING: US100's live size comes from `bot_state`, not from its YAML.** `US100.yaml` sets `risk.position_size: 1`, and **nothing propagates `risk` → `execution`** — only `--quantity` does (`main.py:909`). US100 trades 1.0 purely because it was started with `--quantity 1.0`, which `on_startup` restores from `kv_store/bot_state` (`bot_control_api.py:404` passes `quantity=cfg.get("quantity")`). **So a US100 bot started from the UI without an explicit quantity silently trades 0.5, and its YAML gives no hint.** Verified both ways: with `--quantity 1.0` the broker gets 1.0; without it, `execution.position_size` is `None` → 0.5.
    - Post-deploy verification, all passed: three bots restored (`gold_m5_bot`, `ethusd_m5_bot`, `us100_m5_bot` — `_load_bot_state()` filters on `status='running'`, so the two stopped bots stayed stopped) with quantities None/None/1.0; SL/TP as intended (GOLD 15/60, ETHUSD 25/125, US100 50/150); `max_daily_loss_usd` 150 on ETHUSD only; `max_consecutive_losses` 0 everywhere, so that breaker stays off; `time_exits.enabled` False/absent everywhere, so **the flatten is deployed but still off**; and **zero ERROR/Traceback lines in any bot log since the restart**. Pre-deploy baseline: **0 open positions** at the broker (which is why this window was chosen), `trade_history` 2962 rows / 381 zeros.
    - Entries are suppressed after every restart until the trend flips once ("⏳ Startup: recorded initial signal=…, waiting for trend flip"). That is the normal startup gate, which **pre-existed in the old container** — logs show it firing 10-16 through 10-21. What gotcha 41 added was the `risk.startup_flip_gate` opt-out *key*, not the gate.
    - **`backtest-runner` was deliberately NOT rebuilt** — that is prompt 6, with its own verification. It remains stale (gotcha 25), so UI-triggered backtests still do not test the deployed strategy.

56. **`backtest-runner` rebuilt 2026-10-22 19:30 — gotcha 25 closed, and the proof is the exit mix. One real gap remains: GOLD's history in the live volume.**
    - `docker compose build backtest-runner && docker compose up -d backtest-runner`. `check_deployed.py` now reports **no drift on any container**.
    - **Verified fixed:** `/app/run_skills_backtest.py` **992 lines == host** with `reverse_signal_exit` present **2×** (was 866 lines and **zero**, calling `close_reverse_positions(...)` unconditionally). Configs match the live bot on all three traded instruments: GOLD SL15/TP60 + `require_sma_bias` + `tick_exit` (**all previously absent**), US100 ST(14, 1.5) + `require_h1_bb: false` (was **ST(7, 2.0) + true**), ETHUSD SL25/TP125 (was **45/170**).
    - **The regression is the point, and the exit mix is the sharpest part of it:**
      | | trades | WR | PF | P&L | Reverse Signal exits |
      |---|---|---|---|---|---|
      | container after rebuild | **2485** | 25.513% | **0.9749** | −$12,100 | **0** |
      | host documented (gotcha 54) | 2488 | 25.482% | 0.9733 | −$12,880 | 0 |
      | same container BEFORE | 16,999 | — | — | **+$185,306** | **6,973** |
      −3 trades is the container holding **128 fewer tail bars** (202,979 vs 203,107) — the identical drift mechanism that produced **+3** in gotcha 54, sign flipped. Exits **1851 SL / 634 TP** against gotcha 28's 1849/632.
    - **✅ CLOSED 2026-10-22 — the volume's GOLD history is backfilled AND re-based.** It was reported here as
      "thin data": inside the 2y window, host **141,972** bars vs volume **106,747 (25% missing)** — gotcha 29's
      starvation, never backfilled, because gotcha 55's `bar_updater` fix keeps the volume *current* but never
      reaches backwards. That diagnosis was right but **incomplete**: the bars that WERE present were also on the
      wrong price side and time base (**gotcha 57**), which no bar count can reveal.
      - **A 50,000-bar top-up is NOT the fix, and is actively worse than doing nothing.** It writes bid/UTC bars
        into a mid/local series, leaving GOLD **spliced across two conventions mid-series**. Measured: the spliced
        series gave **494 trades / PF 0.9664** against the host's **493 / PF 1.0555** on the same bar count.
      - **The fix is a FULL re-fetch** (the whole series on one convention), which is what was run:
        ```bash
        docker exec stockscreener-backtest-runner-1 python3 fetch_data.py \
            --epic GOLD --timeframe M5 --bars 210000 --output /data/GOLD_M5_full_authoritative.csv
        ```
        199,400 bars, 2024-01-01 23:05 → now, ~7 min. The volume's GOLD now matches the host on
        **188,533 / 188,534 common bars (99.999%)** with **zero host-only bars**; the single mismatch is the
        host's final bar caught mid-formation, where the volume holds the completed version.
      - **The re-based series restores the sign of GOLD's edge** (container, `--bars 188534`):
        | run | trades | WR | PF | P&L | w/l |
        |---|---|---|---|---|---|
        | host documented (gotcha 54) | 493 | 21.704% | 1.0555 | +$3,342 | 107 / 386 |
        | **spliced** (50k top-up only) | 494 | 20.243% | **0.9664** | **−$2,064** | 100 / 394 |
        | **after full re-fetch** | 510 | 20.980% | **1.0110** | **+$690** | **107** / 403 |
        The winner count lands back on the host's **107 exactly**. The spliced run is the one to
        disbelieve, and note it was the *more plausible-looking* number — a tidy 494 trades.
      - **✅ The phantom bars are DELETED (2026-10-23) — and the container now reproduces the host bit-for-bit.**
        `INSERT OR REPLACE` is keyed on `(epic, timeframe, timestamp)`, so the re-fetch overwrote every *real*
        label but could not remove legacy labels with no true UTC counterpart: **7,886** orphans, mostly the +2h
        tail past GOLD's 21:00 UTC close (**4,209 at hour 21, 3,329 at hour 22**, plus 339 at hours 17–20; Friday
        2,088) — **bars during market closure**. They cost 16 fictional trades (2w/14l, −$996) in the run above.
        Deleted by timestamp against `/data/GOLD_M5_full_authoritative.csv`, **bounded by the CSV's last bar** —
        an unbounded "not in the CSV" test also deletes `bar_updater`'s post-CSV bars (82–89 of them by then).
        Backup of the deleted rows: `/data/GOLD_M5_orphans_backup.json` (volume). Volume afterwards: 199,489 rows,
        0 orphans. Container re-run, `--bars 188534`:
        | run | trades | WR | PF | P&L | w/l |
        |---|---|---|---|---|---|
        | **after orphan delete** | **493** | **21.703853955375255%** | **1.0555001992825828** | **+$3,342** | **107** / 386 |
        | host documented (gotcha 54) | 493 | 21.703853955375255% | 1.0555001992825828 | +$3,342 | 107 / 386 |
        **Bit-identical.** This also **refutes the explanation previously written here** — that the residual
        vs the host was "~10,866 extra bars at the series start re-phasing the run" and "not a data defect". It
        was the phantoms themselves: `--bars N` takes the last N rows, so 7,886 phantom rows occupied window
        slots and pushed the start ~7.9k bars later (gotcha 58's mechanism, caused by the defect). The prediction
        of "~494 / +$1,686 / 105" (simply dropping the 16 trades) was also wrong for the same reason —
        removing bars re-phases the whole path, it does not subtract trades.
      - US100 is unaffected by the *depth* problem (near-identical counts) but **was** affected by gotcha 57. **Re-based in the live volume 2026-10-23**: 6,848 orphans deleted, and the baseline re-measured at 2485 / PF 0.9749, identical in summary but a different trade set. See gotcha 57.
    - **`DB_PATH` was already pinned** per-service in `docker-compose.yml` to `/data/trading.db`, so containers were never exposed to gotcha 24 — that trap is **host-run scripts only**, where `.env` sets nothing. **Do not pin `DB_PATH` in `.env` until the GOLD backfill is done:** it would point host runs at the *thinner* GOLD data and make them worse, since the host DB is currently the better one for GOLD (gotcha 53's correction). Order matters. **Update 2026-10-23: that precondition is now met** — volume GOLD reproduces the host bit-for-bit, and ETHUSD/US100 were already identical between the two DBs (gotcha 57). Pinning `DB_PATH` for host runs to the volume path is now safe; not done yet. Since the 2026-10-23 US100 re-base the volume is strictly better than the host DB for US100, and equal for GOLD.
    - **Operational notes for in-container backtests**, both of which read as failure and are not: a 2y run gets **~15% of a core** because it competes with the three live bots (172s CPU over ~20min wall; the host run took ~4min), and Python **buffers stdout**, so the log looks dead the entire time. Poll for `/data/results/<EPIC>/<run>/report.json` instead of tailing. Results land in **`/data/results/`** (the volume), **not** `/app/results/` — a waiter looking in `/app/results` finds nothing and reports a false failure.

57. **STORED BARS USE A DIFFERENT PRICE SIDE AND TIME BASE THAN THE CODE THAT READS THEM. Measured 2026-10-22 against the live broker; this is the most consequential measurement defect found so far, because it is invisible in every summary statistic.** Every M5 bar in **both** `trading.db` files, for **every instrument**, was written as **mid price at an account-local (UTC+2) timestamp** — except GOLD, whose host copy gotcha 29's repair re-fetched through the corrected path, and whose live-volume copy this session re-fetched (see gotcha 56).
    - **How it was proved, and why summary stats cannot see it.** A fresh `/api/v1/prices/GOLD` fetch parsed through `fetch_data.parse_candle` matches the **host** GOLD series **bit-for-bit**, but disagrees with the **volume** series on 100% of bars. Both series are internally coherent (each bar's close chains to the next bar's open), so nothing looks broken; bar counts, OHLC sanity checks and price ranges all pass. The defect only appears when you compare against the broker.
    - **Both offsets are exact, not approximate** (US100, verified to 6 decimals on consecutive bars):
      | | value |
      |---|---|
      | DB bar labelled `T` | holds the UTC `T − 2h` bar |
      | DB price | `(bid + ask) / 2` — **mid** |
      | `parse_candle` price | `bid` |
      | US100 spread | 1.80 → DB is **+0.90** on every OHLC field = exactly half-spread |
      The raw broker row makes the time half self-evident: `snapshotTime=2025-06-12T13:35:00` vs `snapshotTimeUTC=2025-06-12T11:35:00`.
    - **Scope, measured per instrument** (host vs volume vs fresh broker, June 2025 window): **ETHUSD and US100 are 100% identical between the two DBs and both differ from the broker** — i.e. both DBs are equally mid/local. **GOLD host == broker** (correct). BTCUSD / EURUSD / SILVER exist only in the volume and are mid/local too. So "host is the good DB" is true **only for GOLD**; for every other instrument the two DBs agree with each other and both disagree with the broker.
    - **What this does and does not change.** A uniform additive price offset and a uniform label shift leave the OHLC **sequence** untouched, and Supertrend/ATR/EMA are all computed from differences — `Supertrend(series + c) == Supertrend(series) + c`. **So PF, win rate and trade counts are NOT invalidated by the offsets themselves.** What *is* wrong is everything keyed on the clock:
      - **`skip_hours` gates on the label.** `risk_skill.py:221` is `ts_hour = pd.Timestamp(candle_ts).hour`, and its rejection message reads `"🚫 Skip hour: {ts_hour:02d}h UTC"` — **asserting UTC on a timestamp that is account-local.** US100's `skip_hours: [0..12, 21..23]` is intended as a 13:00–20:59 UTC session; on mid/local bars it actually gates **11:00–18:59 UTC**. The documented US100 PF therefore does not describe the session the config intends, and **gotcha 28's hour-by-hour P&L table is labelled 2h late** (its "hours 13–20 all negative, hour 21 positive" is really UTC 11–18 negative, 19 positive). **US100 is now fixed in the live volume (2026-10-23; see the re-base bullet below):** container backtests gate 13:00–20:59 UTC, the same session as the live bot, whose 224 Aug–Oct entries all fall at hours 13–20 UTC.
      - `risk.time_exits` (Friday 20:45) and `time_based_exits.max_hours` are likewise label-keyed, so gotcha 51's weekend-carry cohort is 2h off **for US100** (its GOLD half was measured on the host, which is correct).
      - Any hour-of-day or session analysis on US100/ETHUSD/BTCUSD/EURUSD/SILVER.
    - **The live bot is on a THIRD convention: ASK.** `capital_websocket._handle_ohlc` is explicit — *"Capital.com sends both BID and ASK/OFR candles for each bar. Only the ASK/OFR candle is passed to on_candle"* — while `parse_candle` stores **bid** and justifies it as *"so that Supertrend and signal logic see the same prices the live bot sees."* **The two comments each claim consistency with the live bot and they cannot both be right:** live runs on ask, backtest on bid. `parse_candle`'s stated goal is not achieved by its own choice. A *constant* spread is a no-op for Supertrend (see above), but spread is **not** constant — it widens at news and rollover — so this is a live-vs-backtest divergence source that **has never been tested**, and a new lead for gotcha 36 alongside the WebSocket-vs-REST bar-boundary question.
    - **Latent, not yet biting:** `_handle_ohlc` builds its candle time with `datetime.fromtimestamp(t / 1000)` — **naive local time**, the same defect gotcha 51 flags in `production_orchestrator.EndOfDayClose`. The container's TZ is empty (UTC), so it currently resolves to UTC; a container with a TZ set would silently shift every live candle. Same family as gotcha 54(b).
    - **Re-base status: GOLD (both DBs) and US100 (live volume only, 2026-10-23) are bid/UTC. ETHUSD, BTCUSD, EURUSD and SILVER are still mid/local**, as is US100 in the host stray DB. **If you re-fetch another instrument, re-measure its baseline in the same session and update the gotcha that quotes it**, and expect the *session* to change, not the PF.
    - **US100 re-base, 2026-10-23: the prediction held exactly.** Recipe as for GOLD (gotcha 56): `fetch_data.py --epic US100 --timeframe M5 --bars 210000 --output /data/US100_M5_full_authoritative.csv` gave 203,260 bars, 2024-01-01 23:00 → 2026-10-23 04:35. All 203,260 matching DB rows then equalled the CSV exactly. It left **6,848 orphans**, same signature as GOLD: 6,579 at hours 21–22 (the +2h tail into the daily break), Friday 2,797, none at the weekend, plus ~270 scattered across trading hours. They were deleted bounded by the CSV's last bar, leaving 203,261 rows (1 newer `bar_updater` bar kept). Backups in the volume: `/data/US100_M5_orphans_backup.json` (the deleted rows) and **`/data/US100_M5_pre_rebase_backup.json` (all 203,088 pre-re-base rows, the full rollback)**.
      Baseline, container `--bars 203260`: **2485 trades / 634 W / 1851 L / WR 25.51307847082495% / PF 0.9748576652952666 / −$12,100**. That is **bit-identical in every summary figure** to the pre-re-base run (gotcha 56), and **it is a coincidence, not a no-op.** At fixed size 5 every US100 trade books exactly +$740 or −$260, so PF/WR/P&L/expectancy are functions of the W/L counts alone, and both runs landed on 634/1851. The trades are different: only **990 of 2485** share a UTC entry time, the `trades.csv` files hash differently, maxDD moved $18,220 → **$31,240** and Sharpe 0 → 0.0064. **Don't use a summary match as evidence that two runs are the same.** Diff `trades.csv`.
      **The session change**, entries by true UTC hour:
      | | entry hours (UTC) | per-hour P&L, size 5 |
      |---|---|---|
      | before (mid/local labels) | **11–18** (+24 at 19) | 11 −0.5k, 12 −8.7k, 13 +0.6k, 14 +4.3k, 15 −1.6k, 16 +2.0k, 17 −2.5k, 18 −8.2k, 19 +2.8k |
      | **after (bid/UTC)** | **13–20** (+17 at 21–23) | 13 −5.5k, 14 +0.5k, 15 −0.4k, 16 −3.5k, 17 +2.7k, 18 −7.7k, 19 −1.4k, 20 +3.6k |
      The 21–23 entries are next-bar opens off a 20:55 signal, which `skip_hours` gates by signal bar. The per-hour P&L is noisy (each hour is ±a few $k on n≈150–600). Neither row supports a session re-tune.
    - Verify any instrument in one step: fetch a window via `parse_candle` and compare against the DB at the same label, then at label −2h. Exact match at −2h with a constant offset == this defect.

58. **`--years N` is NOT a calendar window — it is a 24/7 bar-count approximation, so on anything that does not trade 24/7 it silently means "the whole DB".** `run_skills_backtest.py:885` is `args.bars = int((args.years * 365 * 24 * 60) / minutes_per_bar)`, so `--years 2` on M5 requests **210,240 bars**. GOLD trades ~5 days/week, so two calendar years is only ~142,000 M5 bars — the request exceeds the entire series and the run uses everything available.
    - Consequence: **every "GOLD 2y" figure in this file is really a ~2.65-year run over the full DB**, and two runs of "the same" `--years 2` on DBs of different depth cover different periods. That is not a rounding difference — the trade sequence is path-dependent through position occupancy (an open position blocks new entries), so a different start date re-phases the entire run, not just its edges. Measured here: the same config over 199,865 bars vs 188,534 bars gave **499 vs 493 trades but 102 vs 107 winners** — the outcome mix shifted throughout.
    - So **`--years` is only comparable between runs on identical data.** To compare across DBs, pass an explicit `--bars N`. There is no `--from/--to` on this script.

59. **The 381 zero-P&L `trade_history` rows are REPAIRED — `repair_zero_pnl.py`, 2026-10-22 (closes NEXT_SESSIONS prompt 7).** These are gotcha 22's residue: between the writer landing (2026-08-01) and the 2026-10-21 deploy, `get_activity()` returned `[]`, so every close was detected only by the 60s REST reconcile calling `_handle_close(deal_id, 0.0, '')`.
    - **The signature is unambiguous and worth recognising:** all 381 were `pnl: 0.0` **and** `exit_reason: 'SIGNAL'` (the `description=''` → `'SIGNAL'` fallthrough), and 380 of 381 were live-written rather than backfilled. If you see that pair, it is this bug.
    - **Result: 381/381 matched a `/history/transactions` row, 0 unmatched.** Net P&L the dashboard had been showing as `$0.00`: **−$1,672.63** (us100 −1,481.61 / gold −202.41 / ethusd +11.39 / eurusd 0.00). One row is a **genuine broker break-even** and is reported as `confirmed-breakeven` rather than silently left looking broken — the distinction gotcha 38 introduced. Only 1 zero-P&L row remains, and it is that one.
    - **Why a separate script instead of re-running `backfill_trade_history.py`:** see the warning added to gotcha 14. This one touches **only** rows whose `pnl` is currently `0.0`, and writes **only** the P&L fields (`pnl`, `pnl_pct`, `pnl_estimated`, plus `exit_price` when it was `0.0` and is recoverable from entry+size+pnl). Every other field is preserved, and each repaired row is stamped `pnl_repaired: true` + `pnl_repaired_at` for provenance. It is a per-row `UPDATE`, not an `INSERT OR REPLACE`.
    - **`exit_reason` is deliberately NOT repaired and cannot be.** `/history/transactions` carries no exit reason, and `/history/activity` is hard-capped at 24h (gotcha 12), so the real SL/TP reason for an August close is gone for good. Those rows stay `SIGNAL`. **Do not read the repaired rows' exit mix as strategy evidence** — use the post-deploy rows for that.
    - Usage (**always set `DB_PATH` explicitly** — a bare host run silently uses the 35MB stray DB, gotcha 24):
      ```bash
      cd trading-bot-skills
      DB_PATH=/var/lib/docker/volumes/stockscreener_trading_data/_data/trading.db \
        python3 repair_zero_pnl.py --dry-run      # then drop --dry-run
      ```
      Takes ~6 min: `/history/transactions` is capped at 100 rows per response and rejects `lastPeriod > 86400`, so it reuses `backfill_trade_history.fetch_transactions`'s 12h window chunking (gotcha 15) over the whole span — ~370 windows for the Apr→Oct range.
    - Idempotent: a second run finds only the genuine break-even row (`pnl` is no longer 0.0 on the repaired ones) and changes nothing. A pre-write backup of all `trade_history` rows is cheap and worth taking — one `SELECT` to JSON.

60. **The live bot NEVER applied GOLD's or ETHUSD's MA100 slope gate — this is gotcha 36's divergence, closed at trade level (2026-10-23).**
    - **The defect.** `main.py`'s warm-up sizing is `max(sma_slow, bb, st, macd_slow+signal, rsi, stoch) × 3` and **omitted the MA bias**, so it came to `35 × 3 = 105` bars. It then *assigned* that to `market_data.buffer_size`, **shrinking** it from 300. Every log since April says `M5 warm-up complete — 105 candles buffered`. On a 105-bar buffer MA100 itself is valid (last 6 rows), but `sma_bias_prev = sma_bias.shift(20)` needs row ≥ 119 and is **always NaN**. `_extract_indicators` then fell back to `prev = current`, which makes `ma_rising` and `ma_falling` both True. So `bias_slope_bars: 20` was a no-op in live, while the backtest (full-series precompute) applied it. Silent, like gotchas 22 and 50: a guard fallback that turns a missing input into "allow".
    - **Trade-level proof** (live `trade_history` `gold_m5_bot`, 2026-08-01..10-21, 95 rows; container runs at `--bars 188534`; matched ±10 min, the gotcha-33 method):
      | backtest | trades in window | WR | PF | matched / 95 | same side | same outcome |
      |---|---|---|---|---|---|---|
      | canonical (`results/GOLD/20261023_041717`, slope 20) | 62 | 22.6% | 1.111 | **1** | 1 | 1 |
      | **slope off** (`results/GOLD/noslope_188534`, `--set analysis.indicators.sma.bias_slope_bars=0`) | **97** | **15.5%** | **0.697** | **82** | **82** | **81** |
      | live | 95 | 14.7% | 0.685 | — | — | — |
      No constant clock offset rescues the canonical match: the best shift found 5/95. **Signal-level proof:** regenerating signals from DB bars with the skill's own `_compute_indicators`/`_evaluate_signal` gives the *identical* 484-signal set for "105-bar buffer, slope 20" and "full series, slope off", recalling **480 of the 541** `📊 Signal:` lines in `gold_m5_bot.log`. The full-series slope-20 run recalls 24. The ~57 extra live signals are about one per trading day, consistent with the 21:00 restart resetting `last_signal_state`. It also follows that **Supertrend truncation at 105 bars is harmless**, which extends gotcha 36's rejection #3 from 300 bars down to 105.
    - **The live strategy is therefore the slope-OFF strategy, and that has no edge over 2y:** **773 trades / WR 20.83% / PF 1.0017 / +$162**, against the slope-on 493 / 21.70% / PF 1.0555 / +$3,342. Every GOLD backtest figure in this file describes a strategy that has **never traded live**. The Aug–Oct live loss is what the backtest of the strategy actually running predicts (PF 0.697 vs 0.685).
    - **Tool:** `trade_match.py` (repo root) is the matching script: `python3 trade_match.py --bot gold_m5_bot --run results/GOLD/<run> --from … --to …`. It reproduces 82/95 on `noslope_188534`. NEXT_SESSIONS prompt 12 is the periodic check.
    - **Residual 13/95 unmatched:** 6 fall while the backtest held a position (occupancy cascades), and several are entries a few seconds late (`:01`, `:07`, `:10` past the bar), likely delayed bar delivery. That's the same order as US100's 16/224.
    - **ETHUSD has the identical defect.** It has the same `bias_slope_bars: 20` and its log shows `Warm-up bars — M5: 105`. Not trade-matched: ETHUSD's bars are still mid/local (gotcha 57), so re-base it first. US100 does not use the bias (buffer 150 there).
    - **Fix, committed `eb9de2e` and DEPLOYED 2026-10-23 05:42 UTC:**
      - `main.py` now includes `sma_bias_period + sma_bias_slope_bars` (when enabled) and `2 × adx_period` (when enabled) in `m5_min_bars`, giving GOLD/ETHUSD **360**. It sets `buffer_size = max(buffer_size, m5_warmup)`, so the buffer is never shrunk.
      - `_extract_indicators` now **fails closed** (`return None`) when the slope gate is on and `sma_bias_prev` is NaN.
      - Tests: `TestMaSlopeGate` in `test_live_analysis_path.py` and four new `TestWarmup` cases in `test_live_bootstrap.py`. The slope gate had **zero** tests before. Suite 1319 → 1328 passing.
      - Backtest regression on GOLD `--bars 188534` (host code, volume DB): **493 / 21.703853955375255% / PF 1.0555001992825828 / +$3,342**, bit-identical to gotcha 56. The fail-closed change only affects bars 110–119 of a series, and the backtest path was always applying the gate.
    - **Deploy record.** `docker compose build trading-bot bar-updater backtest-runner && docker compose up -d …`. New trading-bot image `sha256:d9924627…`; **rollback target `sha256:19ecb886…`**. Pre-deploy there were 0 open positions at the broker. Verified: `check_deployed.py` shows no drift on any container, with both gotcha-60 markers present. GOLD and ETHUSD logs show `Warm-up bars — M5: 360`; US100 is unchanged at 150. Sizes are unchanged (GOLD 0.5, ETHUSD 0.5, US100 1.0), and there were zero ERROR/Traceback lines after the restart.
    - **This is now a FORWARD TEST of the slope-on strategy, on demo, at unchanged size.** Success bar, agreed before the results: after ~60 GOLD trades (≈15/month at the backtest rate, so ~4 months), PF > 1.0 after costs, or stop. Do not size up before then. Trade-match live against the container backtest periodically with the gotcha-33 method; a fresh mismatch means a new defect.
    - ⚠️ **It was a strategy change, not a bug-fix rollout.** It switches live GOLD and ETHUSD from the strategy they've actually been trading to the one the backtests describe: fewer trades, and on GOLD the PF-1.0555 variant. That variant's own IS/OOS evidence is thin (gotchas 34, 35). It is also a different strategy from the one that produced the Aug–Oct live record. Decide it deliberately, and run `check_deployed.py` after (add a marker: `sma_bias_slope_bars', 0)` in `orchestrator/main.py`). A rebuild of `./trading-bot-skills` bakes this in whether or not it is committed (gotcha 10).

61. **Prompt 8, first pass (2026-10-23): the cost-per-R lever is refuted, and the one signal with a real net edge (daily IBS on US indices) fails DSR and the modern buy-and-hold bar. 54 trials, none passes all four tests.** Scripts, result tables and the re-run recipe are in [`research/prompt8/`](research/prompt8/README.md).
    - **Rig.** Host code against a frozen snapshot of the volume's GOLD/US100 M5 bars, with fetching turned off (`bt.py`). Host code == container code per `check_deployed.py`. It reproduces the canonical baselines exactly: GOLD `--bars 188534` 493 / PF 1.0555 / +$3,342 and US100 `--bars 203260` 2485 / PF 0.9749 / −$12,100. Runs four at a time in ~5 min, against ~20 min each in the container (gotcha 56).
    - **Cost per unit of R (gotcha 32's lever) does NOT work the way gotcha 32 assumed.** I swept 4 timeframes (M5/M15/M30/H1 via `resample_to`) × 3 stop widths (1×/2×/4×) at fixed R:R. Size was scaled inversely, so $ risk per trade is constant. Cost fell exactly as predicted (4% → 2% → 1% of R), but **gross PF was not stable across stop width**: GOLD M5 gross PF went 1.109 → 1.043 → **0.718**. Widening R changes which trades exist (holds lengthen and occupancy re-phases the run); it does not keep the same gross edge at a lower cost. So gotcha 32's "the lever is R relative to spread" is **wrong as a mechanism**: the ~PF 1.02 gross edge is not a fixed quantity you can expose more cheaply.
      | best variants (stable = IS & OOS PF > 1) | n | PF | IS / OOS | SR | B&H SR | DSR | transfer |
      |---|---|---|---|---|---|---|---|
      | GOLD H1 SL15/TP60 | 63 | 1.644 | 1.995 / 1.324 | 0.90 | 0.95 | 0.41 | ✗ US100 H1 PF 0.84–0.88 |
      | GOLD M30 SL60/TP240 | 55 | 1.313 | 1.216 / 1.358 | 0.45 | 1.04 | 0.13 | ✗ US100 M30 SL200 0.967 |
      | US100 M30 SL100/TP300 | 626 | 1.051 | 1.077 / 1.031 | 0.29 | 0.92 | 0.09 | ✗ GOLD M30 SL30 IS 0.881 |
      | US100 M5 SL200/TP600 | 394 | 1.194 | 0.995 / 1.335 | 0.83 | 0.91 | 0.36 | unstable (IS < 1) |
      Every stable GOLD variant has n = 38–63 over 2.6y, which is too few to separate from luck. None transfers, and none beats buy-and-hold Sharpe (GOLD B&H ≈ 1.0 over this window, US100 ≈ 0.9). Same verdict as gotcha 34, now covering timeframe and stop width too.
    - **Daily bars go back to the 1970s. `fetch_weekly.py`'s docstring ("DAY capped at ~1000 bars (~3.2 years)") is WRONG.** The cap is 1000 rows *per call*. Paging backwards with `to = first snapshotTimeUTC − 1s` keeps going: GOLD from 1979, US100 from 1970, SILVER 1973, US500 1999, DE40 1993. Data caveats: US100 before 1985 predates the index (back-filled), GOLD has multi-day gaps before 2008 and SILVER before 2018, and every instrument has Sunday-evening stub bars (drop `dayofweek >= 5`). This opens a 20+-year daily sample for any H4/daily work. The 2.6y M5 window cannot validate a daily rule.
    - **Second signal family: four pre-registered daily long-only rules** (`daily_fam.py`) with textbook parameters and no tuning: Connors RSI(2), IBS < 0.2 hold 1 day, turn-of-month, and close > SMA200. Run on GOLD/US100/SILVER/US500/DE40, with the decision at close and the fill at the next open. Net of 1.5× the bid/ask spread per entry and overnight funding at (fed funds by year + 2.5%)/365 per calendar day held.
      - **IBS on US indices is the first signal in this project whose net edge survives everything except the last two bars:** US100 26.8y, n = 1123, net PF **1.364** (gross 1.454), IS 1.33 / OOS 1.43, SR **0.57** vs B&H 0.41. US500 is near-identical (PF 1.367, SR 0.61). It is still positive at 3× costs (SR 0.44), stable across thresholds 0.15–0.30 (SR 0.58–0.63), positive in **all six** 5-year blocks on US100, and **uncorrelated with the Supertrend bots** (daily corr 0.006 vs US100, −0.09 vs GOLD).
      - **It fails two bars.** (1) **DSR 0.59 / 0.66 over 54 trials**, against 0.95. (2) **Its Sharpe lead over buy-and-hold is a 2000–09 artefact**, when B&H Sharpe was negative. From 2010 B&H wins most 5-year blocks (US100 2010–14: IBS 0.29 vs B&H 1.05), and over 2024–26 it is 0.50 vs 0.96. Exposure is ~20%, so its CAGR (8%) is well below B&H. Its transfer is also weak: US500 is the same market, DE40 is barely positive (PF 1.09, SR 0.17), and GOLD/SILVER fail.
      - Other families: RSI(2) works on US indices too (PF 1.6, SR 0.33–0.38, below B&H) and fails on metals. Turn-of-month is positive on GOLD (PF 1.38, SR 0.38 vs B&H 0.55). SMA200 trend has the highest PFs (1.7–2.9) but on 37–89 trades, with SR at or below B&H on 4 of 5.
    - **Where this leaves the research.** No standalone signal beats buy-and-hold here. The defensible next experiment is **IBS as an overlay on a long index position** (B&H plus extra exposure on IBS days), scored against B&H at matched volatility. That is a portfolio question, not a new signal, and it would need its own pre-registered trial count. Don't re-tune IBS's threshold: neighbours were checked, and selecting among them is exactly what the DSR penalises.

62. **Prompt 8, second pass (2026-10-23): IBS as an overlay on a long index position fixes the buy-and-hold problem but fails DSR. 12 trials, running total 66, none passes all four tests.** Variants and tests were written in [`research/prompt8/overlay_prereg.md`](research/prompt8/overlay_prereg.md) before any run. Script: `ibs_overlay.py`. Results: `overlay_results.txt`.
    - **Rebuilding `daily.pkl` per the README reproduces `daily_results.txt` byte-for-byte**, so the rig is stable across re-fetches. Today's partial bar drops out via `dropna`.
    - Exposure is `w = b + k·IBS<0.2` from 2000 on. Costs follow `daily_fam.py`: 1.5× spread on every exposure *increase*, plus funding at FF+2.5% on exposure **above 1.0 only**. The 1.0 base is unfunded, as `daily_fam`'s B&H benchmark is, and the vol-matched B&H pays the same funding on `λ − 1`.
      | US100 | b + k | incPF IS/OOS | SR | vol-matched B&H SR | SR 2010+ | VM-B&H 2010+ | active SR | DSR (active) |
      |---|---|---|---|---|---|---|---|---|
      | O1 | 1 + 0.5 | 1.33 / 1.43 | 0.49 | 0.39 | 0.89 | 0.85 | 0.50 | 0.41 |
      | O2 | 1 + 1.0 | 1.33 / 1.43 | 0.53 | 0.37 | 0.88 | 0.82 | 0.48 | 0.37 |
      | O3 | 0.8 + 0.8 | 1.34 / 1.44 | 0.53 | 0.40 | 0.89 | 0.86 | 0.41 | 0.24 |
      | O4 | 1 + 1·(c>SMA200) | 1.09 / 1.38 | 0.47 | 0.40 | 0.89 | 0.85 | 0.32 | 0.13 |
    - **Tests 1 and 4 pass on every variant.** Unlike standalone IBS, the overlay beats vol-matched B&H in 2010–2026, but only by 0.03–0.06 Sharpe. O1–O3 also pass transfer. DE40 transfer is marginal, though: full-sample SR 0.32 vs 0.30, and **DE40 loses to vol-matched B&H after 2010 on all four**. O4 fails transfer (DE40 OOS PF 0.86).
    - **Test 3 fails everywhere: active-return DSR 0.12–0.41, against 0.95.** I used the DSR of the *active* return (overlay − vol-matched B&H), as pre-registered. The raw overlay's DSR (0.36–0.54) mostly certifies equity beta. An active Sharpe of ~0.5 over 26 years is t ≈ 2.6 before deflation, which isn't enough after 66 trials.
    - The incremental leg's PF equals standalone IBS's (1.364 on O1), as it must: PF is scale-invariant. That's a sanity check on the rig, not new evidence.
    - **Don't add overlay variants to chase DSR.** Each one raises the bar. Prompt 8 items 2–3 are the untested levers left.

---

## Conventions

- **Python version:** 3.12
- **Async:** All skills are async (asyncio). Do not use `time.sleep()` — use `await asyncio.sleep()`.
- **Logging:** Use `logger = logging.getLogger(__name__)` in every module. No print statements.
- **Config:** YAML only — no hardcoded magic numbers. Add new params to `trading_config.yaml` first.
- **Skills:** Each skill inherits from `Skill` (base_skill.py). Must implement `initialize()` and event handler methods. Skills communicate only via EventBus — never import another skill directly.
- **Errors:** Raise specific exceptions. Do not catch bare `Exception` without re-raising or logging at ERROR level.
