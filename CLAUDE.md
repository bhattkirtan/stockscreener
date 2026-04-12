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

10. **`deploy_skills_bot.sh` cannot be run inside Claude Code's container — SSH key unavailable:**
    - `~/.ssh/stockscreener_server` does not exist in the Claude Code environment
    - Always run `bash deploy_skills_bot.sh demo GOLD` from your **local machine terminal**
    - The script stops the service, rsyncs all local files, reinstalls the systemd unit, and restarts — no separate restart step needed
    - To pick up a config-only change without full redeploy: `ssh -i ~/.ssh/stockscreener_server root@204.168.191.150 "systemctl restart trading-bot-skills"`

11. **All instrument YAMLs have `execution.environment: demo` as a no-live-trading guard:**
    - Added to GOLD, SILVER, EURUSD, BTCUSD, ETHUSD, US100
    - All instruments now have `execution.epic:` set (ETHUSD was missing this entirely — would have failed to connect)
    - All instruments now have `risk.reverse_signal_exit: false`
    - SL/TP standardised to 1:3 R:R across all instruments: GOLD 15/45, SILVER 1/3, EURUSD 20/60, BTCUSD 400/1200, ETHUSD 25/75, US100 35/105

12. **Capital.com API lookback limits (confirmed):**
    - `/history/activity`: `lastPeriod` only, **hard cap 86400s (24h)**. `from/to` params return 400. Use only for same-day trade reconstruction.
    - `/history/transactions`: supports `from/to` date strings (e.g. `'2026-04-07T00:00:00'`) for multi-day P&L. Use this for historical comparisons.
    - Activity filter syntax: `type==POSITION;status==ACCEPTED` (semicolon-separated). Filter by epic client-side — adding `epic==GOLD` in the filter param causes 400.

---

## Conventions

- **Python version:** 3.12
- **Async:** All skills are async (asyncio). Do not use `time.sleep()` — use `await asyncio.sleep()`.
- **Logging:** Use `logger = logging.getLogger(__name__)` in every module. No print statements.
- **Config:** YAML only — no hardcoded magic numbers. Add new params to `trading_config.yaml` first.
- **Skills:** Each skill inherits from `Skill` (base_skill.py). Must implement `initialize()` and event handler methods. Skills communicate only via EventBus — never import another skill directly.
- **Errors:** Raise specific exceptions. Do not catch bare `Exception` without re-raising or logging at ERROR level.
