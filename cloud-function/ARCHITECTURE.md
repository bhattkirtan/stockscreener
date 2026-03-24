# 🏗️ Trading Bot System Architecture

Complete architecture for M5 Gold Trading Bot with monitoring, data streaming, and API access.

---

## 📊 System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        HETZNER SERVER (Helsinki)                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    Trading Bot M5 (Python)                        │  │
│  │                   trading_bot_m5.py running                       │  │
│  │                                                                   │  │
│  │  Features:                                                        │  │
│  │  • 5-minute candles (M5 timeframe)                              │  │
│  │  • Capital.com WebSocket streaming                              │  │
│  │  • Supertrend + SMA strategy                                    │  │
│  │  • AUTO-TRADE mode (demo) or SIGNAL-ONLY (live)                │  │
│  │  • Auto-restart (systemd service)                               │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                              ↓ ↓ ↓                                      │
│  ┌─────────────────────┐  ┌─────────────────────┐                      │
│  │   Log Uploader      │  │  Local Data Files   │                      │
│  │  (every 15 min)     │  │  /opt/trading-bot/  │                      │
│  │  upload_logs.py     │  │  - logs/            │                      │
│  │  systemd timer      │  │  - data/signals/    │                      │
│  └─────────────────────┘  │  - data/candles/    │                      │
│           ↓                └─────────────────────┘                      │
└───────────┼──────────────────────────────────────────────────────────────┘
            ↓
```

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    GOOGLE CLOUD PLATFORM (GCP)                           │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                         FIRESTORE                                 │  │
│  │                    (Real-time Database)                           │  │
│  │                                                                   │  │
│  │  Collections:                                                     │  │
│  │  ┌────────────────────────────────────────────────────────────┐ │  │
│  │  │ bot_status/gold_m5_bot                                      │ │  │
│  │  │  • status: running/stopped/error                            │ │  │
│  │  │  • last_heartbeat: every 30 seconds                         │ │  │
│  │  │  • statistics: signals, orders, P&L                         │ │  │
│  │  │  • uptime_seconds                                           │ │  │
│  │  └────────────────────────────────────────────────────────────┘ │  │
│  │  ┌────────────────────────────────────────────────────────────┐ │  │
│  │  │ active_positions/{deal_id}                                  │ │  │
│  │  │  • current_price: updated on every quote                    │ │  │
│  │  │  • pnl: real-time unrealized P&L                           │ │  │
│  │  │  • stop_loss, take_profit                                  │ │  │
│  │  │  • status: open/closed                                     │ │  │
│  │  └────────────────────────────────────────────────────────────┘ │  │
│  │  ┌────────────────────────────────────────────────────────────┐ │  │
│  │  │ trading_signals/{signal_id}                                 │ │  │
│  │  │  • epic, signal (BUY/SELL), price                          │ │  │
│  │  │  • sl, tp, timestamp                                       │ │  │
│  │  │  • strategy, indicators                                    │ │  │
│  │  └────────────────────────────────────────────────────────────┘ │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              ↓                                           │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    CLOUD STORAGE (GCS)                            │  │
│  │         double-venture-442318-k8-trading-logs                     │  │
│  │                                                                   │  │
│  │  Structure:                                                       │  │
│  │  logs/                                                           │  │
│  │    └── YYYY-MM-DD/                                              │  │
│  │        ├── bot-output.log     (stdout)                          │  │
│  │        ├── bot-error.log      (stderr)                          │  │
│  │        └── trading_bot_*.log  (app logs)                        │  │
│  │                                                                   │  │
│  │  Uploaded: Every 15 minutes (systemd timer)                      │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              ↓                                           │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                   CLOUD FUNCTIONS (APIs)                          │  │
│  │                                                                   │  │
│  │  ┌────────────────────────────────────────────────────────────┐ │  │
│  │  │ trading-bot-api (Trading Data API)                          │ │  │
│  │  │  • GET /bot/status        → Bot health                      │ │  │
│  │  │  • GET /bot/positions     → Active positions + P&L          │ │  │
│  │  │  • GET /bot/signals       → Recent signals                  │ │  │
│  │  │  Source: Firestore                                          │ │  │
│  │  └────────────────────────────────────────────────────────────┘ │  │
│  │  ┌────────────────────────────────────────────────────────────┐ │  │
│  │  │ trading-bot-logs-api-get (Logs API)                         │ │  │
│  │  │  • GET /get_logs?date=YYYY-MM-DD&file=bot-output.log       │ │  │
│  │  │  • GET /list_dates                                          │ │  │
│  │  │  Source: GCS Bucket                                         │ │  │
│  │  └────────────────────────────────────────────────────────────┘ │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                              ↓ ↓ ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                          UI / CLIENT APPS                                │
│                                                                          │
│  Access Methods:                                                         │
│  ┌────────────────────────────────────────────────────────────────────┐│
│  │ 1. HTTP API Polling (Simple)                                        ││
│  │    • useBotStatus() hook        → Refresh every 30s                 ││
│  │    • useActivePositions() hook  → Refresh every 5s (near real-time) ││
│  │    • useLogs() hook             → Fetch from GCS via API            ││
│  └────────────────────────────────────────────────────────────────────┘│
│  ┌────────────────────────────────────────────────────────────────────┐│
│  │ 2. Firestore Real-time Streaming (Zero Latency)                    ││
│  │    • onSnapshot(bot_status)     → Instant updates                   ││
│  │    • onSnapshot(active_positions) → Live P&L streaming              ││
│  │    • onSnapshot(trading_signals)  → Already implemented!            ││
│  └────────────────────────────────────────────────────────────────────┘│
│  ┌────────────────────────────────────────────────────────────────────┐│
│  │ 3. Direct API Calls (curl, Postman, etc.)                          ││
│  │    • Test endpoints                                                 ││
│  │    • External integrations                                          ││
│  └────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 🤖 Bot Details

### Current Bot: **M5 Gold Trading Bot**

**Location:** `/opt/trading-bot/scripts/trading_bot_m5.py`  
**Service:** `trading-bot.service` (systemd)  
**Status:** Can be checked via API or Firestore

**Strategy:**
- **Timeframe:** M5 (5-minute candles)
- **Epic:** GOLD
- **Indicators:** Supertrend (7, 2.0), SMA (10/21), EMA (10), BB (20, 2.0)
- **Risk:** SL = 0.7× ATR, TP = 2.5× ATR
- **Mode:** AUTO-TRADE (demo) or SIGNAL-ONLY (live)

**Capabilities:**
- WebSocket streaming from Capital.com
- Real-time signal generation
- Automated order placement (demo mode)
- Trailing stop loss (breakeven, progressive, ATR-based)
- Position sync every 30s
- Heartbeat to Firestore every 30s

---

## 📡 Data Streams

### Stream 1: Trading Data (Real-time)

**Path:** Bot → Firestore → API / UI

| Data Type | Collection | Update Frequency | Access Method |
|-----------|-----------|------------------|---------------|
| Bot Status | `bot_status/gold_m5_bot` | Every 30s (heartbeat) | API or Firestore listener |
| Active Positions | `active_positions/{deal_id}` | Every quote (~1s) | API or Firestore listener |
| Signals | `trading_signals/{signal_id}` | On signal generation | API or Firestore listener (already working) |

**Publishers:**
- `bot_status_publisher.py` - Bot health tracking
- `position_publisher.py` - Position tracking with live P&L
- `signal_publisher.py` - Signal publishing (already existed)

**API Endpoint:** `https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-api`

**React Integration:**
```typescript
// HTTP API (polling)
const { status } = useBotStatus('gold_m5_bot');
const { positions, totalPnl } = useActivePositions('GOLD');

// Firestore (real-time streaming)
const { status } = useBotStatusRealtime('gold_m5_bot');
const { signals } = useSignals({ epic: 'GOLD', realtime: true }); // Already works!
```

### Stream 2: Logs (Batch Upload)

**Path:** Bot → GCS → Logs API → UI

| Log Type | File | Update Frequency | Access Method |
|----------|------|------------------|---------------|
| Stdout | `bot-output.log` | Every 15 min | Logs API webhook |
| Stderr | `bot-error.log` | Every 15 min | Logs API webhook |
| App Logs | `trading_bot_*.log` | Every 15 min | Logs API webhook |

**Uploader:** `upload_logs.py` (systemd timer)  
**Storage:** GCS bucket `double-venture-442318-k8-trading-logs`  
**API Endpoint:** `https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-logs-api-get`

**React Integration:**
```typescript
const { logs } = useLogs({ date: '2026-03-24', file: 'bot-output.log' });
```

---

## 🔧 System Management

### Server Access
```bash
ssh -i ~/.ssh/stockscreener_server root@204.168.191.150
```

### Bot Control
```bash
# Status
systemctl status trading-bot

# Restart
systemctl restart trading-bot

# Logs (live tail)
journalctl -u trading-bot -f

# Logs (recent errors)
tail -f /opt/trading-bot/logs/bot-error.log
```

### Verify Data Flow

**1. Check Firestore (Bot Status)**
```bash
# Via API
curl 'https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-api/bot/status'

# Via Firestore Console
# → Firebase Console → Firestore → bot_status → gold_m5_bot
```

**2. Check Positions**
```bash
curl 'https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-api/bot/positions'
```

**3. Check Signals**
```bash
curl 'https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-api/bot/signals?limit=5'
```

**4. Check Logs**
```bash
# List available dates
curl 'https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-logs-api-list'

# Get today's logs
curl 'https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-logs-api-get?date=2026-03-24&file=bot-output.log&lines=100'
```

---

## 📦 Deployment Status

### ✅ Deployed
- Trading Bot M5 (on Hetzner server)
- Signal Publisher (Firestore)
- Log Uploader (systemd timer)

### ⏳ Pending Deployment
1. **Trading API** - Deploy with `./deploy/deploy_trading_api.sh`
2. **Logs API** - Deploy with `./deploy/deploy_logs_api.sh`
3. **Bot Updates** - Deploy new publishers:
   ```bash
   # Full redeploy (recommended)
   ./deploy_bot.sh
   
   # Or update only new files
   scp -i ~/.ssh/stockscreener_server src/live_trading/bot_status_publisher.py root@204.168.191.150:/opt/trading-bot/src/live_trading/
   scp -i ~/.ssh/stockscreener_server src/live_trading/position_publisher.py root@204.168.191.150:/opt/trading-bot/src/live_trading/
   scp -i ~/.ssh/stockscreener_server scripts/trading_bot_m5.py root@204.168.191.150:/opt/trading-bot/scripts/
   ssh -i ~/.ssh/stockscreener_server root@204.168.191.150 "systemctl restart trading-bot"
   ```

---

## 🎯 What You Can Monitor

| Metric | Source | Update Frequency | UI Display |
|--------|--------|------------------|------------|
| Bot Running? | Firestore `bot_status` | 30s | Status indicator |
| Bot Uptime | Firestore `bot_status` | 30s | Uptime counter |
| Open Positions | Firestore `active_positions` | Real-time | Position cards |
| Live P&L | Firestore `active_positions` | Real-time (quotes) | Live P&L chart |
| Recent Signals | Firestore `trading_signals` | On generation | Signal feed (already works!) |
| Statistics | Firestore `bot_status` | On event | Stats dashboard |
| Bot Logs | GCS → Logs API | 15 min | Log viewer |

---

## 🚀 Deployment Checklist

### Phase 1: Deploy APIs
```bash
cd cloud-function

# 1. Deploy Trading API (status, positions, signals)
chmod +x deploy/deploy_trading_api.sh
./deploy/deploy_trading_api.sh

# 2. Deploy Logs API (log fetching)
chmod +x deploy/deploy_logs_api.sh
./deploy/deploy_logs_api.sh
```

### Phase 2: Update Bot
```bash
# Option A: Full redeploy (safest)
./deploy_bot.sh

# Option B: Selective update + restart
scp -i ~/.ssh/stockscreener_server src/live_trading/{bot_status_publisher.py,position_publisher.py} root@204.168.191.150:/opt/trading-bot/src/live_trading/
scp -i ~/.ssh/stockscreener_server scripts/trading_bot_m5.py root@204.168.191.150:/opt/trading-bot/scripts/
ssh -i ~/.ssh/stockscreener_server root@204.168.191.150 "systemctl restart trading-bot"
```

### Phase 3: Verify
```bash
# 1. Check bot started
ssh -i ~/.ssh/stockscreener_server root@204.168.191.150 "systemctl status trading-bot"

# 2. Check Firestore has data (wait 30s for heartbeat)
curl 'https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-api/bot/status'

# 3. Check logs uploading (wait 15 min for first upload)
curl 'https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-logs-api-list'
```

### Phase 4: UI Integration
Add React hooks to your dashboard:
- `useBotStatus()` - Bot health indicator
- `useActivePositions()` - Live P&L display
- `useLogs()` - Log viewer
- `useSignals()` - Already implemented!

---

## 📚 Related Documentation

- [TRADING_DATA_STREAM_GUIDE.md](TRADING_DATA_STREAM_GUIDE.md) - Detailed Firestore schemas, React hooks
- [LOGS_API_GUIDE.md](LOGS_API_GUIDE.md) - Logs API endpoints, integration guide
- [deploy_bot.sh](deploy_bot.sh) - Bot deployment script
- [deploy_trading_api.sh](deploy/deploy_trading_api.sh) - Trading API deployment
- [deploy_logs_api.sh](deploy/deploy_logs_api.sh) - Logs API deployment

---

## ❓ FAQ

**Q: Which bot am I running?**  
A: M5 Gold Trading Bot (`trading_bot_m5.py`) - 5-minute candles

**Q: How do I access bot logs?**  
A: Two ways:
1. Live: SSH + `journalctl -u trading-bot -f`
2. API: Logs API endpoint (uploaded every 15 min to GCS)

**Q: How do I see if bot is running?**  
A: Three ways:
1. Firestore: Check `bot_status/gold_m5_bot` collection
2. API: `GET /bot/status`
3. SSH: `systemctl status trading-bot`

**Q: How do I see live P&L?**  
A: Query Firestore `active_positions` or use Trading API `/bot/positions`

**Q: Are signals already working?**  
A: Yes! Signals are published to Firestore and your UI already has `useSignals()` hook

**Q: What's the difference between Trading API and Logs API?**  
A: Trading API → Real-time trading data (status, positions, signals)  
   Logs API → Historical logs (stdout, stderr, app logs)

---

## 🎨 Architecture Principles

1. **Separation of Concerns**
   - Trading data → Firestore (real-time)
   - Logs → GCS (batch upload)
   - APIs expose both

2. **Data Freshness**
   - Bot status: 30s (heartbeat)
   - Positions: Real-time (on quotes)
   - Signals: Real-time (on generation)
   - Logs: 15 min (batch)

3. **Access Patterns**
   - Real-time monitoring → Firestore listeners
   - Periodic polling → HTTP APIs
   - Historical logs → GCS + Logs API

4. **Resilience**
   - Bot auto-restart (systemd)
   - Local file backups (signals, candles)
   - Firestore persistence
   - GCS log retention

---

**Last Updated:** 24 March 2026  
**Bot Version:** M5 Gold Trading Bot v1.0  
**Project:** double-venture-442318-k8
