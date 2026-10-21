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

---

## Instruments & Strategy

**Primary:** GOLD (XAU/USD) on M5 timeframe

**Current GOLD strategy (as deployed in live/demo bot):**
- Entry: M5 Supertrend(14×1.5) flip + MA100 bias + MA100 slope
- SL: **15 pips** ($15/contract) | TP: **40 pips** ($40/contract) — R:R 1:2.67
- EMA and SMA(25/30) filters **disabled** — MA100 bias is the only filter
- Tick exit enabled (Supertrend trail cross closes position in live mode)
- No reverse-signal exit — SL / TP / tick exit only
- EOD close at 16:00 UTC

**Config cascade (important):**
```
trading_config.yaml (base defaults)
    ↓ deep-merged with
instruments/GOLD.yaml (instrument overrides)
    ↓ _propagate_risk_to_sl_tp()
analysis.sl_tp values are overwritten by risk pip values
```
**Gotcha:** `risk.sl_pips` / `risk.tp_pips` is the single source of truth for SL/TP pips.
`analysis.sl_tp.stop_loss_pips` gets overwritten at load time — edit `risk` section, not `analysis`.

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
- **SL/TP:** Edit `risk.sl_pips` / `risk.tp_pips` (not analysis.sl_tp — it gets overwritten)
- **Cooldowns:** `risk.sl_cooldown_minutes` / `risk.tp_cooldown_minutes`
- **Session filter:** `risk.skip_hours: [0,1,...]` — list of UTC hours where **new entries** are blocked (open positions still exit normally). Honored by both live (`risk_skill.py:141`) and backtest (`--skip-hours` CLI flag, or the YAML value directly). Use to avoid low-liquidity sessions.
- **Consecutive-loss circuit breaker (opt-in, default OFF):** `risk.max_consecutive_losses: N` blocks all new entries after N losing trades in a row for `risk.consecutive_loss_cooldown_minutes` (default 120), then resets; a win resets the counter immediately. `0` = disabled. Backtest with `--set risk.max_consecutive_losses=4 --set risk.consecutive_loss_cooldown_minutes=720`. **Note:** on trend-followers this is a safety rail, not a profit lever — the GOLD/ETH sweep was non-monotonic/path-dependent (pausing can lock you out of the recovery leg), so it's left disabled on both.
- **Daily-loss limit (opt-in):** `risk.max_daily_loss_usd: X` halts new entries once the current UTC day's realised P&L breaches -X; auto-clears at UTC rollover. `0` = disabled. **Requires real $ P&L** at close — `on_position_closed(pnl=...)` now threads it from both live and backtest. Backtest with `--set risk.max_daily_loss_usd=150`. **Instrument-specific:** enabled on ETHUSD ($150 — improves return+DD+Sharpe there) but left OFF on GOLD, where it worsens results (trend lock-out). Same meta-pattern as the consecutive breaker: helps ETH, hurts GOLD.
- **EOD close:** `time_based_exits.eod_hour` (UTC)
- **Position size:** `risk.position_size_pct` and `risk.max_position_size`
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

> **Warning:** `GOLD.yaml` has uncommitted local changes. Always verify against `git show HEAD:trading-bot-skills/config/instruments/GOLD.yaml` before running a comparison backtest.

**Verified from live Capital.com trade screenshot (Apr 2026):**
SL distance shown as 15.75, TP distance as 39.25 — confirming SL=15/TP=40 is live (0.75 pip spread adjustment by broker).
The local uncommitted changes were deployed via rsync before being committed to git.

| Parameter | Deployed (confirmed live) | Git HEAD (stale) |
|-----------|--------------------------|-----------------|
| Supertrend ATR period | 14 | 14 |
| Supertrend multiplier | 1.5 | 1.5 |
| EMA filter | disabled | disabled |
| SMA(25/30) filter | disabled | disabled |
| MA100 bias | **enabled** (`require_sma_bias: true`) | not present |
| Stop loss | **15 pips** ($15/contract) | 20 pips |
| Take profit | **45 pips** ($45/contract, 1:3 R:R) | 60 pips |
| Tick exit | **enabled, `reverse_on_loss: false`** | not present |
| Position size | 10 contracts | 10 contracts |
| EOD close | 16:00 UTC | 16:00 UTC |

### Correct backtest command to match live

```bash
cd trading-bot-skills

# --instrument GOLD already has all correct live params (SL=15, TP=45, MA100 bias)
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

**Gotcha:** `git status` at `/opt/stockscreener/` will NOT show changes inside `capital-connect/` — it's a nested repo, not a subdirectory tracked by the parent. Always `cd capital-connect` and run git commands separately for UI changes.

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

1. **SL/TP config source:** Always edit `risk.sl_pips` / `risk.tp_pips` — not `analysis.sl_tp`. The propagation function overwrites analysis values at load time.

2. **Warm-up bars:** `buffer_size` in config is overridden at runtime to `max_indicator_period × WARMUP_MULTIPLIER (3)`. Don't worry about it manually.

3. **Timeframe resampling:** `market_data.resample_to` can resample M5 data to M10/M15/M30 without downloading new data. Useful for testing longer timeframes quickly.

4. **Instrument config merge:** Changes to `trading_config.yaml` base values may be silently overridden by `instruments/GOLD.yaml`. Always check the instrument file if your config change has no effect.

5. **`bot.mode: AUTO` vs `SIGNAL_ONLY`:** In `SIGNAL_ONLY` mode, no orders are placed. Use this to verify signals before going live.

6. **EOD close default:** EOD close is enabled at 16:00 UTC. Backtests should match — if you disable it in one place, disable in both.

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
    - SL/TP standardised to 1:3 R:R across all instruments: GOLD 15/45, SILVER 1/3, EURUSD 20/60, BTCUSD 400/1200, ETHUSD 25/75, US100 35/105

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
    - `python backfill_trade_history.py --days 120 [--dry-run] [--instrument GOLD] [--db PATH]`
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

20. **Live SL/TP are anchored to the signal-bar close, not the actual fill.** `AnalysisSkill._calculate_sl_tp` (`analysis_skill.py:527`) computes levels off the candle close and ships them with the order; the broker fills at market some seconds later. The distances the broker records are therefore *not* the configured pips.
    - Worked example (US100, config SL=50 / TP=150): levels SL 28320.1 / TP 28120.1 imply a reference price of 28270.1, but the fill was 28288.7 → **effective SL 31.4 pts, TP 168.6 pts**. Other same-day US100 fills drifted to 60.2 / 63.5 / 55 pts.
    - So real risk-per-trade varies ±40% from the YAML, and backtests (which fill at the close) systematically disagree with live. To diagnose, compare `details.openPrice` vs `stopLevel`/`profitLevel` in `/history/activity` — do **not** trust the YAML pips.

21. **Reading trades out of the live DB — exact shapes:** `kv_store` columns are `(collection, doc_id, data, updated_at)` — there is no `key`/`value` column. `trade_history` rows carry `bot_id` (e.g. `us100_m5_bot`); `active_positions` rows do **not** (`bot_id: None`) but do carry `opened_at` and `status`. `active_positions` has `entry_price: None` on many rows while `trade_history` has it — join on `deal_id` across both to reconstruct a trade.

22. **`get_activity()` WAS broken — it always returned `[]`, silently disabling three risk mechanisms. FIXED 2026-10-21 (not yet deployed to the container).**
    - `capital_api.py:308` sends `filter=type==POSITION;status==EXECUTED`. **`status==EXECUTED` matches nothing** — verified against the live demo API: `EXECUTED` → `200 n=0`, `ACCEPTED` → `200 n=11`. The correct value is `ACCEPTED`.
    - Second, independent bug: `main.py:303` iterates `details['actions']` to find `POSITION_OPENED`/`POSITION_CLOSED`. **There is no `actions` array in the response.** Even with the filter fixed, nothing would parse.
    - **Real close-event shape** (`detailed=true`, `status==ACCEPTED`): top-level `date`/`dateUTC`/`epic`/`dealId`/`source`/`type`/`status`, and `details` = `dealReference`, `workingOrderId`, `marketName`, `currency`, `size`, `direction`, `level`, `stopLevel`, `guaranteedStop`, `profitLevel`, and — **only on closes** — `openPrice`.
      - A close is identified by **`details.openPrice` being present**; open events lack it.
      - **`source` is the exit reason**: `SL` | `TP` | `USER`. Use it instead of string-matching `description` (which the REST fallback passes as `''`).
      - **`details.direction` on a close is the CLOSING direction — the opposite of the position.** A position opened BUY shows `direction: SELL` on its close row. Don't use it as the position direction.
      - **There is no `details.profit`.** `_handle_close` reads `details.get('profit')` and so always gets `None`. Realised P&L must be joined from `/history/transactions` on `dealId` (where `size` *is* the P&L — see gotcha 15).
    - **Consequence chain:** activity poll returns `[]` → every close is detected only by the 60 s REST reconcile at `main.py:353`, which calls `_handle_close(deal_id, 0.0, '')`. Then:
      1. `close_level=0.0` is falsy, so the `if entry and close_level and size` guard fails → **`pnl = 0.0`** and `exit_price = 0.0` on every `trade_history` row written since the writer landed (2026-08-01). 365 rows, all zeros.
      2. `description=''` → `close_reason = 'SIGNAL'` → `_check_cooldown` falls through to "No cooldown required". **`sl_cooldown_minutes` / `tp_cooldown_minutes` never apply in live.** GOLD's 30 m SL cooldown has never once fired.
      3. `is_loss = pnl < 0` with `pnl == 0.0` → **every trade is scored as a win.** The consecutive-loss breaker can never trip.
      4. `_register_daily_pnl(0.0)` → **`risk.max_daily_loss_usd` can never trip.** ETHUSD's $150 cap is inert.
    - The dashboard therefore shows real P&L only through 2026-07-31 (from `backfill_trade_history.py`, which uses `/transactions` and is correct) and **0.00 for everything after**. US100 shows 223 of 231 trades at zero.
    - Until this is fixed, **`/history/transactions` is the only trustworthy live P&L source.** Re-running `backfill_trade_history.py` repairs history but not the live path.

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

25. **`stockscreener-backtest-runner-1` has months-stale baked configs — UI-triggered backtests do NOT test the deployed strategy.** Config is `COPY`d at build time and the service has not been rebuilt since the strategy changed. Diff vs the live bot on 2026-10-21:
    | Instrument | Live bot | backtest-runner (stale) |
    |---|---|---|
    | GOLD | `require_sma_bias: true` (MA100), `tick_exit` block | **both absent** |
    | US100 | ST(14, 1.5), `require_h1_bb: false`, `reverse_signal_exit: false`, `skip_hours` | **ST(7, 2.0), `require_h1_bb: true`, no reverse-exit guard, no skip_hours** |
    | ETHUSD | SL 25 / TP 125, MA100 bias, `reverse_signal_exit: false` | **SL 45 / TP 170, no bias, no reverse-exit guard** |
    - Effect: a 2-year ETHUSD run in that container produced **16,802 of 16,999 exits as `Reverse Signal`** (avg hold 1.3 bars) and `+$733,912` on $10k — a reverse-signal scalper compounding through `dynamic_sizing`, not the live strategy. Treat any such number as an artefact.
    - **The container's *code* is stale too, and that is worse than the configs.** `/app/run_skills_backtest.py` is 866 lines vs the host's 984, contains **zero occurrences of `reverse_signal_exit`**, and at its line 363 calls `backtesting.close_reverse_positions(...)` **unconditionally**. The host version guards it at `run_skills_backtest.py:553`. So `docker cp`-ing the correct YAML in is **not sufficient** — a run with `reverse_signal_exit: false` correctly loaded still produced 6,973 `Reverse Signal` exits and `+$185,306`.
    - Note the default is also inconsistent in the current code: `run_skills_backtest.py:553` defaults `reverse_signal_exit` to **True**, while `trading_orchestrator.py:130` defaults it to **False**. An instrument YAML that omits the key gets reverse-exit ON in backtest and OFF in live.
    - To backtest the real strategy: rebuild the service (`docker compose build backtest-runner`) — copying YAML alone will not fix it.

26. **`execution.position_size` defaults to `0.5` (`execution_skill.py:51`) — GOLD and ETHUSD have been trading at a fraction of intended size.** The deployed YAMLs define `position_size` only under `backtesting:`, not under `risk:`/`execution:`, so the 0.5 default wins.
    | Instrument | Actually traded | Host YAML intends | Risk/trade actual → intended |
    |---|---|---|---|
    | GOLD | **0.5** | 10 | $7.50 → **$150 (20×)** |
    | ETHUSD | **0.5** | 1 | $12.50 → $25 (2×) |
    | US100 | 1.0 | 1 | $50 (correct — it sets `risk.position_size`) |
    - The uncommitted `position_size` additions to `GOLD.yaml`/`ETHUSD.yaml` + the `main.py` root-propagation block are the fix — but deploying them **multiplies GOLD risk 20×on a strategy with no measured edge.** Aug–Oct would have been **−€5,386 instead of −€1,820**. Fix the edge before the size.

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

33. **Backtest-vs-live agreement (the measurement rig actually works).** Cost-corrected US100 restricted to 2026-08-01 .. 2026-10-21 vs live:
    | | n | WR | avgW | avgL | PF |
    |---|---|---|---|---|---|
    | backtest | 241 | 24.48% | $148.0 | −$52.0 | 0.923 |
    | live | 221 | 21.72% | $150.0 | −$52.7 | 0.789 |
    WR differs by 3.8pp ≈ 1.4 standard errors on n=221 — within sampling noise. **Trust the host backtester for US100**; distrust it for GOLD/ETH until gotcha 29 is repaired.

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

36. **GOLD live takes ~50% more trades than the backtest and wins less — cause still UNKNOWN. Three plausible explanations were tested and all REJECTED (2026-10-21).** Live window 2026-08-01..10-21:
    | | n | WR | PF |
    |---|---|---|---|
    | backtest (repaired data) | 61 | 21.31% | 1.046 |
    | **live actual** | **93** | **13.98%** | **0.646** |
    - **Rejected — broken SL/TP cooldowns (gotcha 22).** `sl_cooldown_minutes=0` / `60` / `30` all produce **exactly 61 trades** with identical PF. The cooldown gate only blocks *same-direction* re-entry, and `edge_detection` means the next signal is usually the opposite direction, so it almost never binds. The cooldown bug is real but costs nothing here.
    - **Rejected — daily 21:00 restart resetting `last_signal_state`.** The 31 excess live trades are spread across hours 8–20 (hour 12 is +11); **hour 21 has 0 live entries**. No restart signature.
    - **Rejected — Supertrend path-dependence on the live rolling buffer.** Live computes ST on a `max_indicator_period × 3 = 300`-bar buffer; the backtest precomputes over the full series. Measured over 1,100 GOLD M5 bars: **100.00% direction agreement, 85 vs 85 flips.** ST band memory resets at every flip (~1 per 13 bars), so 300 bars is ample. Not a divergence source — and this also retires the general worry about truncated-buffer indicators.
    - **Still open:** the live bot builds candles from the WebSocket tick stream while the DB bars come from the REST price endpoint — bar boundaries/incomplete bars may differ; and the live MA100 bias is computed over whatever the live buffer actually contains (which was itself starved while gotcha 29 was active). Check live candle timestamps against DB bars before trusting GOLD live/backtest parity.
    - **Consequence:** US100 backtest↔live parity is good (gotcha 33) but **GOLD parity is not established.** Do not size up GOLD on backtest evidence alone.

37. **Where this strategy family sits in the published literature (researched 2026-10-21) — the measured numbers match known structural limits.**
    - [Structural Limits of OHLCV-Based Intraday Momentum in MNQ Futures](https://arxiv.org/abs/2605.04004) tested **14 signal families on 947 days of 5-minute Micro-Nasdaq data** (same instrument and bar size as US100). None passed; **11 of 14 had gross edge 0.07–1.50 points against a 2.0-point friction floor.** Our measured US100 gross edge is **0.95 points/contract** against ~2.0 points of cost — inside that published range. Its *positive* controls did clear friction (RTH confluence T=3.11 net +11.82 pts; London session T=4.30 net +4.09 pts), i.e. edge exists in session/confluence structure, not generic OHLCV momentum.
    - [Is Trend Still Your Friend?](https://arxiv.org/html/2607.01550v1) — Sharpe by signal horizon, pre→post 2009: 5-day 0.84→**0.12**, 10-day 0.83→0.22, 20-day 0.79→0.27, 50-day 0.70→**0.40**. Discriminant is **volatility-normalised tick size**; small-tick contracts collapsed, large-tick held. Called structural, not cyclical. Our median holds: **US100 35 min**, GOLD 191 min, ETHUSD 505 min — i.e. ~200× faster than the fastest horizon that study found already dead.
    - [Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) — when N variants are tried and the best kept, the max is inflated even if all are noise. Directly explains `m20_adx25` (gotcha 34): best of ~20 trials in-sample, failed to transfer. **Count trials and deflate before believing a sweep.**
    - Grinold's Fundamental Law: `IR ≈ IC × √breadth`. This system runs **one signal family, 3 instruments, one position at a time → breadth ≈ 1**, while trying to harvest a PF-1.02 edge. Breadth, not a better indicator, is the multiplier.
    - Practical implication for future work here: **slower horizons (daily/H4), many more markets, several uncorrelated signal types, volatility-targeted sizing, trial-count-corrected validation.** Faster + more tuning is the one direction the evidence rules out.

38. **The 2026-10-21 fixes — what changed, and what is still NOT deployed.** All verified against the live demo API; `tests/unit/` went 271 → 288 passing with the same 20 pre-existing `test_pip_config` failures.
    - **`bar_updater` root cause was a string-comparison format mismatch, not a timezone bug.** `parse_candle()` emits `'YYYY-MM-DD HH:MM:SS'` (space) while `bar_updater` passed `strftime('%Y-%m-%dT%H:%M:%S')` ('T'). In `fetch_all_bars`'s date-range filter `if ts < from_date: continue`, `ord(' ')=32 < ord('T')=84`, so **every same-day candle compared as older than `from_date` and was skipped** → 0 rows → `"reached end of available history"`. Bar-count mode (`--bars N`) was unaffected because it does no date filtering, which is why only US100 (already up-to-date, never entering the fetch) escaped.
      - Fix: new `_norm_ts()` normalises every bound to the `parse_candle` form before comparison; date-only bounds are widened (`from`→`00:00:00`, `to`→`23:59:59`) so `--from/--to` no longer 400s; pagination now anchors on `snapshotTimeUTC` instead of local `snapshotTime` (the API's `to` is UTC, so feeding the local value back shifted each window by the offset and re-fetched overlaps).
      - Verified: `--from 2026-09-01 --to 2026-09-03` on SILVER → **828 bars (was 0)**; `bar_updater.py --epic GOLD` → **61 candles inserted (was 0)**.
    - **`get_activity` + close detection:** filter now `status==ACCEPTED`; the non-existent `details['actions']` loop is replaced by `'openPrice' in details` for close detection and `source` → `{SL: SL_HIT, TP: TP_HIT, else SIGNAL}` for the reason. Verified live: `epic=US100` over 24h returns **14 events (was 0)**, parsed as 7 opens + 7 closes, all correctly `SL_HIT`.
    - **New `CapitalAPIClient.get_realised_pnl(deal_id)`** joins `/history/transactions` on `dealId` (where `size` IS the P&L). Activity and transaction dealIds **are the same ID space** (11/21 overlap in 24h — opens have no TRADE row). Verified: 11/11 closes resolved, magnitudes correct (US100 ≈ −45 EUR on a 50 USD stop, GOLD ≈ −6.7 on 7.5). Default look-back is 3600s; pass more for historical lookups or it returns None.
    - **`pnl is None` now means "unknown" everywhere and is never coerced to `0.0`.** `_handle_close` only estimates from prices when it has entry+close+size; `trading_orchestrator` log-formats None safely; `_record_trade` distinguishes a real broker `0.0` (kept) from unknown (recorded with the new **`pnl_unknown: true`** flag + a warning). The old `float(pnl or 0.0)` also discarded a genuine break-even figure in favour of an estimate — also fixed.
    - **Regression cover:** new `tests/unit/test_activity_parsing.py` (filter must say ACCEPTED, `openPrice` discriminates, source→reason mapping, no `actions`/`profit` fields, transactions `size`-as-P&L, `lastPeriod` cap) and 2 new cases in `test_trade_history.py` for the unknown-vs-break-even distinction.
    - ⚠️ **NOT deployed.** The live bot runs baked-in code in `stockscreener-trading-bot-1`; these edits are host-side only. Deploying needs `docker compose build trading-bot && docker compose up -d trading-bot` — which per gotcha 10 also bakes in every other uncommitted change in that tree. Check `git status` first.

39. **Open work is captured as ready-to-paste session prompts in [`NEXT_SESSIONS.md`](NEXT_SESSIONS.md).** Seven streams: coverage for `orchestrator/main.py` (13%), `analysis_skill` tick-exit/MTF (55%), `execution_skill`/`capital_websocket` + a CI coverage floor, the 20 pre-existing `test_pip_config` failures, the two unresolved live/backtest divergences from gotcha 36, breadth expansion for the weekly trend portfolio, and the deferred operational decisions (trade_history backfill, `backtest-runner` rebuild, `DB_PATH` pinning, the held-back `position_size` changes). Each prompt names the gotchas carrying its background so nothing has to be re-derived. **Check it before starting new work — three hypotheses for the GOLD divergence are already tested and rejected there.**

---

## Conventions

- **Python version:** 3.12
- **Async:** All skills are async (asyncio). Do not use `time.sleep()` — use `await asyncio.sleep()`.
- **Logging:** Use `logger = logging.getLogger(__name__)` in every module. No print statements.
- **Config:** YAML only — no hardcoded magic numbers. Add new params to `trading_config.yaml` first.
- **Skills:** Each skill inherits from `Skill` (base_skill.py). Must implement `initialize()` and event handler methods. Skills communicate only via EventBus — never import another skill directly.
- **Errors:** Raise specific exceptions. Do not catch bare `Exception` without re-raising or logging at ERROR level.
