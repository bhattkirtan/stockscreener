# 🔗 Bot Monitoring Endpoints - Added to Existing API

**Updates your existing `capitalComService` function with bot monitoring endpoints**

## ✨ What This Does

Adds **3 new endpoint categories** to your existing Cloud Function **without breaking anything**:

### 🆕 New Endpoints

1. **Bot Monitoring** - `/bot/status`, `/bot/positions`, `/bot/signals`
2. **Logs Access** - `/logs/get`, `/logs/dates`

### ✅ Existing Endpoints (Unchanged)

3. **Capital.com Trading** - `/get_positions`, `/create_position`, `/markets`, etc.

**Your frontend will keep working!** Same function name, same URL, just more endpoints.

---

## 🚀 Deploy Update

```bash
cd /Users/kirtanbhatt/code/stockScreener/cloud-function

# Option 1: Using Makefile (recommended)
make deploy-with-bot-monitoring

# Option 2: Using deploy script directly
./scripts/deploy.sh --confirm-overwrite
```

**Function:** `capitalComService` (existing)  
**Region:** `us-central1`  
**Action:** Update (not create new)

---

## 📡 New Endpoints Available After Deploy

Base URL: `https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService`

| Endpoint | Method | Description | Example |
|----------|--------|-------------|---------|
| **🆕 `/bot/status`** | GET | Bot health & heartbeat | `?bot_id=gold_m5_bot` |
| **🆕 `/bot/positions`** | GET | Active positions with P&L | `?status=open&epic=GOLD` |
| **🆕 `/bot/signals`** | GET | Recent bot signals | Already existed, enhanced |
| **🆕 `/bot/logs/live`** | GET | Real-time logs (Firestore, last 24h) | `?bot_id=gold_m5_bot&limit=100` |
| **🆕 `/logs/get`** | GET | Historical logs (GCS archives) | `?date=2026-03-24&file=bot-output.log` |
| **🆕 `/logs/dates`** | GET | List available log dates | - |
| **✅ `/get_positions`** | GET | Capital.com positions | Unchanged |
| **✅ `/create_position`** | POST | Open new position | Unchanged |
| **✅ `/markets`** | GET | Market data | Unchanged |
| **✅ All others** | - | Everything else | Unchanged |

---

## 🧪 Test New Endpoints

```bash
# Show all endpoints
make show-new-endpoints

# Test bot status
make test-bot-status

# Test bot positions  
make test-bot-positions

# Test logs access
make test-bot-logs
```

Or use curl directly:

```bash
BASE_URL="https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService"

# Bot status
curl "$BASE_URL/bot/status"

# Bot positions
curl "$BASE_URL/bot/positions?status=open"

# Live logs (real-time, last 24 hours)
curl "$BASE_URL/bot/logs/live?bot_id=gold_m5_bot&limit=50"

# Historical logs (GCS archives, older than 24h)
curl "$BASE_URL/logs/dates"
curl "$BASE_URL/logs/get?date=2026-03-23&file=bot-output.log"
```

---

## 🔧 What Changed

**Code:** `functions/main.py` now includes:
- `handle_get_bot_status()` - Bot heartbeat checker
- `handle_get_bot_positions()` - Firestore positions reader
- `handle_get_bot_signals()` - Enhanced signals endpoint
- `handle_get_bot_logs()` - GCS log file reader
- `handle_list_log_dates()` - GCS date lister

**Deployment:**
- Added `GCS_LOGS_BUCKET` environment variable
- All other settings unchanged (memory, timeout, secrets, etc.)

**Routes in hello_http():**
```python
# New routes added
if path == '/bot/status' or path == '/status':
    return handle_get_bot_status(req)

if path == '/bot/positions' or path == '/positions':
    return handle_get_bot_positions(req)

if path == '/logs/get' or path == '/logs':
    return handle_get_bot_logs(req)

if path == '/logs/dates':
    return handle_list_log_dates(req)

# Existing routes unchanged
if path == '/get_positions':
    ...existing code...
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│         capitalComService (Cloud Function)              │
│               - SAME function name                       │
│               - SAME base URL                            │
│                                                          │
│  ┌────────────────┐  ┌──────────────┐  ┌────────────┐ │
│  │   Capital.com  │  │ Bot Monitor  │  │    Logs    │ │
│  │    Trading     │  │  (NEW)       │  │   (NEW)    │ │
│  │   (Existing)   │  │  Firestore   │  │    GCS     │ │
│  └────────────────┘  └──────────────┘  └────────────┘ │
│          ↓                   ↓                ↓         │
│  ┌──────────────────────────────────────────────────┐ │
│  │       hello_http() - Single Entry Point          │ │
│  │         (Routes to appropriate handler)          │ │
│  └──────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
                        ↓
              Same URL as before!
```

---

## ✅ Success Criteria

After deployment, verify:
- [ ] `/bot/status` returns status (404 if bot not publishing yet)
- [ ] `/bot/positions` returns empty array (until bot has positions)
- [ ] `/logs/dates` returns available dates
- [ ] `/get_positions` still works (Capital.com existing endpoint)
- [ ] Frontend continues to work without changes

---

## 🎯 Next Steps

1. **Deploy the update:**
   ```bash
   make deploy-with-bot-monitoring
   ```

2. **Test new endpoints** (see above)

3. **Update bot on server:**
   - Deploy bot with publishers (bot_status_publisher.py, position_publisher.py)
   - Restart bot service
   - Verify Firestore collections populated

4. **Update frontend (optional):**
   - Add bot monitoring dashboard
   - Use new `/bot/status`, `/bot/positions` endpoints
   - Log viewer using `/logs/*` endpoints

---

## 💰 Cost Impact

**None!** Same function, same pricing, just more features.

### 🤖 Bot Monitoring

| Endpoint | Method | Description | Example |
|----------|--------|-------------|---------|
| `/bot/status` | GET | Bot health & statistics | `?bot_id=gold_m5_bot` |
| `/bot/positions` | GET | Active positions with P&L | `?status=open&epic=GOLD` |
| `/bot/signals` | GET | Recent bot signals | `?epic=GOLD&limit=20` |

### � Live Logs (NEW!)

**Real-time log streaming from Firestore** - Last 24 hours, auto-refreshing

| Endpoint | Method | Description | Cost |
|----------|--------|-------------|------|
| `/bot/logs/live` | GET | Stream live logs (Firestore) | ~$1/month |

**Parameters:**
- `bot_id` (default: `gold_m5_bot`) - Bot identifier
- `run_id` (optional) - Specific run ID, or "latest" for most recent
- `limit` (default: 200, max: 500) - Number of logs to return
- `level` (optional) - Filter by log level: INFO, WARNING, ERROR

**Examples:**
```bash
BASE_URL="https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService"

# Get latest 50 logs
curl "$BASE_URL/bot/logs/live?limit=50"

# Get ERROR logs only
curl "$BASE_URL/bot/logs/live?level=ERROR&limit=100"

# Get specific bot run
curl "$BASE_URL/bot/logs/live?bot_id=gold_m5_bot&run_id=20260324_121405"
```

**Response:**
```json
{
  "bot_id": "gold_m5_bot",
  "run_id": "20260324_121405",
  "count": 50,
  "source": "firestore_live",
  "logs": [
    {
      "id": "gold_m5_bot_20260324_121405_23",
      "timestamp": "2026-03-24T12:14:08.591250+00:00",
      "sequence": 23,
      "level": "INFO",
      "logger": "src.live_trading.capital_websocket",
      "message": "📩 marketData.subscribe: {'status': 'OK'}",
      "bot_id": "gold_m5_bot",
      "run_id": "20260324_121405",
      "ttl": "Wed, 25 Mar 2026 12:14:06 GMT"
    }
  ]
}
```

**Features:**
- ⚡ **Real-time**: Updates within 5 seconds of log generation
- 🔄 **Auto-refresh**: Poll this endpoint every 5-10 seconds for live tail
- 💾 **24h retention**: Logs older than 24 hours auto-deleted
- 📦 **Batched writes**: Efficient Firestore usage (~$1/month)
- 🎯 **Structured**: JSON format with timestamps, levels, logger names

**Use Cases:**
- Live bot monitoring dashboard
- Real-time error alerting
- Debug current bot session
- WebSocket connection status

### �📊 Capital.com Trading

| Endpoint | Method | Description | Example |
|----------|--------|-------------|---------|
| `/get_positions` | GET | Get all open positions | - |
| `/create_position` | POST | Open new position | JSON body |
| `/updte_position` | POST | Update position SL/TP | JSON body |
| `/close_position/{dealId}` | DELETE | Close position | - |

### 📈 Market Data

| Endpoint | Method | Description | Example |
|----------|--------|-------------|---------|
| `/market/{epic}` | GET | Current market info | `/market/GOLD` |
| `/prices/{epic}` | GET | Historical prices | `?resolution=HOUR` |
| `/markets` | GET | Search markets | `?searchTerm=GOLD` |

### 📝 Logs

| Endpoint | Method | Description | Example |
|----------|--------|-------------|---------|
| `/bot/logs/live` | GET | Real-time logs (Firestore, last 24h) | `?bot_id=gold_m5_bot&limit=100` |
| `/logs/get` | GET | Historical logs (GCS archives) | `?date=2026-03-24&file=bot-output.log` |
| `/logs/dates` | GET | List available dates | - |

**📊 Logs Comparison:**

| Feature | `/bot/logs/live` (NEW) | `/logs/get` (Historical) |
|---------|----------------------|--------------------------|
| **Source** | Firestore | GCS Bucket |
| **Latency** | ~5 seconds (real-time) | 15 minutes (batch upload) |
| **Retention** | 24 hours | Permanent archives |
| **Format** | JSON structured | Plain text files |
| **Use Case** | Live monitoring, debug | Historical analysis, audit trail |
| **Cost** | ~$1/month | ~$0.02/GB/month |

### 📡 Trading Signals

| Endpoint | Method | Description | Example |
|----------|--------|-------------|---------|
| `/signals` | GET | Recent signals | `?epic=GOLD&limit=20` |
| `/signals/latest` | GET | Latest signal | `?epic=GOLD` |

---

## 🧪 Testing

```bash
# Get API info
curl 'https://us-central1-double-venture-442318-k8.cloudfunctions.net/trading-bot-unified-api/'

# Bot status
curl 'https://us-central1-double-venture-442318-k8.cloudfunctions.net/trading-bot-unified-api/bot/status'

# Active positions
curl 'https://us-central1-double-venture-442318-k8.cloudfunctions.net/trading-bot-unified-api/bot/positions?status=open'

# Recent signals
curl 'https://us-central1-double-venture-442318-k8.cloudfunctions.net/trading-bot-unified-api/signals?epic=GOLD&limit=10'

# Live logs (real-time, last 24h)
curl 'https://us-central1-double-venture-442318-k8.cloudfunctions.net/trading-bot-unified-api/bot/logs/live?limit=50'

# Live logs - ERROR level only
curl 'https://us-central1-double-venture-442318-k8.cloudfunctions.net/trading-bot-unified-api/bot/logs/live?level=ERROR&limit=100'

# Available log dates (historical)
curl 'https://us-central1-double-venture-442318-k8.cloudfunctions.net/trading-bot-unified-api/logs/dates'

# Get historical logs
curl 'https://us-central1-double-venture-442318-k8.cloudfunctions.net/trading-bot-unified-api/logs/get?date=2026-03-24'
```

---

## 🔧 Environment Variables

Set in Cloud Function:
- `GOOGLE_CLOUD_PROJECT` - GCP project ID
- `CAPITAL_ENV` - `demo` or `live`
- `ALLOW_LIVE_TRADING` - `true` to enable live trading
- `GCS_LOGS_BUCKET` - Bucket name for logs (default: `{project_id}-trading-logs`)

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│           Unified Trading Bot API (Cloud Function)          │
│                                                              │
│  ┌────────────────┐  ┌──────────────┐  ┌────────────────┐ │
│  │   Capital.com  │  │ Bot Monitor  │  │  Logs Access   │ │
│  │    Trading     │  │   (Status,   │  │  (GCS Bucket)  │ │
│  │   (REST API)   │  │  Positions)  │  │                │ │
│  └────────────────┘  └──────────────┘  └────────────────┘ │
│          ↓                   ↓                  ↓           │
│  ┌────────────────────────────────────────────────────────┐│
│  │            Single HTTP Entry Point (hello_http)        ││
│  │              Routes to appropriate handler             ││
│  └────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
                              ↓
                    Single Public URL
```

---

## 📊 Data Sources

| API Section | Data Source | Update Frequency |
|-------------|-------------|------------------|
| Bot Status | Firestore `bot_status` | 30 seconds (heartbeat) |
| Positions | Firestore `active_positions` | Real-time (on quotes) |
| Signals | Firestore `trading_signals` | On signal generation |
| Logs | GCS Bucket | Every 15 minutes |
| Capital.com | Capital.com REST API | On demand |

---

## 🔐 CORS

**CORS is enabled** for all endpoints:
- `Access-Control-Allow-Origin: *`
- All methods supported
- Can be called from browser/UI

---

## 📝 Next Steps

1. **Deploy the unified API**
   ```bash
   ./deploy/deploy_unified_api.sh
   ```

2. **Test endpoints**
   - Use curl commands above
   - Check bot status works
   - Verify logs accessible

3. **Update UI**
   - Change API URL in React app
   - Use new unified endpoint
   - Remove old API URLs

4. **Update bot**
   - Deploy bot with publishers
   - Restart bot on server
   - Verify Firestore populated

5. **Cleanup (optional)**
   - Can remove old API files:
     - `functions/trading_api.py`
     - `functions/logs_api.py`
   - Can delete old deployment scripts:
     - `deploy/deploy_trading_api.sh`
     - `deploy/deploy_logs_api.sh`

---

## 🎯 Migration Notes

**From separate APIs:**
- Old: `trading-bot-api`, `trading-bot-logs-api-get` (not deployed yet)
- New: `trading-bot-unified-api` (single function)

**URL changes:**
- Base URL changes from separate functions to one
- Path structure stays the same
- No breaking changes to query params

**Code location:**
- All code merged into `functions/main.py`
- Entry point: `hello_http`
- Routing: Path-based dispatch

---

## 💰 Cost Comparison

**Before (3 separate functions):**
- 3 × Cloud Function instances
- 3 × Cold starts
- 3 × Memory allocations

**After (1 unified function):**
- 1 × Cloud Function instance
- 1 × Cold start
- 1 × Memory allocation (512MB)

**Estimated savings:** ~60-70% on Cloud Functions costs

---

## 📚 Related Documentation

- [ARCHITECTURE.md](./ARCHITECTURE.md) - Overall system architecture
- [TRADING_DATA_STREAM_GUIDE.md](./TRADING_DATA_STREAM_GUIDE.md) - React integration
- [deploy/deploy_unified_api.sh](./deploy/deploy_unified_api.sh) - Deployment script

---

## ✅ Success Criteria

After deployment, verify:
- [ ] Base URL returns API info
- [ ] `/bot/status` returns bot health
- [ ] `/bot/positions` returns empty array (until bot has positions)
- [ ] `/signals` returns signals from Firestore
- [ ] `/logs/dates` returns available dates
- [ ] `/get_positions` returns Capital.com positions
- [ ] CORS headers present in all responses
