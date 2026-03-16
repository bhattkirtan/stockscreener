# 🎛️ Complete UI Control API Reference

## Deployment Summary

✅ **All 3 components deployed with full UI control**

### Endpoints

#### 1. **Optimization API** (Enhanced with 20+ parameters)
**URL**: `https://optimize-api-6ovej2yaoa-uc.a.run.app`

**POST /optimize** - Start optimization with full parameter control

```json
{
  // ── Core Settings ──
  "instrument": "GOLD",              // GOLD, EURUSD, BITCOIN, US30, etc
  "timeframe": "M5",                  // M5, M15, H1
  "initial_capital": 10000,
  "position_size": 10.0,
  
  // ── Optimization Mode ──
  "mode": "quick",                    // quick | medium | full
  "parallel": true,
  "n_jobs": -1,                       // CPU cores (-1 = all)
  
  // ── Strategy Indicators (Customize ranges) ──
  "supertrend_periods": [7, 10, 12, 15],
  "supertrend_multipliers": [1.5, 2.0, 2.5, 3.0],
  "sma_fast_periods": [10, 15, 20, 25, 30],
  "sma_slow_periods": [40, 60, 80, 100],
  "ema_periods": [15, 20, 25, 30],
  "bb_periods": [15, 20, 25],
  "bb_stds": [1.5, 2.0, 2.5, 3.0],
  
  // ── Take Profit / Stop Loss ──
  "tp_sl_strategy": "both",          // fixed | atr | both
  "sl_pips_range": [10, 20, 30, 50],
  "tp_pips_range": [20, 40, 60, 100],
  "atr_sl_multipliers": [1.0, 1.5, 2.0, 2.5, 3.0],
  "atr_tp_multipliers": [2.0, 4.0, 6.0, 8.0],
  
  // ── Leverage / Position Sizing ──
  "pip_values": [0.5, 1.0, 2.0, 5.0, 10.0],
  
  // ── Filters ──
  "min_trades": 10,
  "min_win_rate": 0.0,                // 0.0 - 1.0
  "max_drawdown_pct": 50.0,
  
  // ── Custom Parameter Grid File (Advanced) ──
  "param_grid_file": "custom_grid.json"
}
```

**Response**:
```json
{
  "run_id": "a7f3c91b",
  "status": "queued",
  "estimated_combinations": 540,
  "task_name": "projects/.../tasks/...",
  "config": {
    "instrument": "GOLD",
    "timeframe": "M5",
    "mode": "quick"
  }
}
```

---

#### 2. **Scheduler Control API** (Data sync control)
**URL**: `https://scheduler-control-6ovej2yaoa-uc.a.run.app`

##### **GET /scheduler/status** - Check scheduler status
```bash
curl https://scheduler-control-6ovej2yaoa-uc.a.run.app/status
```
Response:
```json
{
  "status": "enabled",
  "timestamp": "2026-03-05T12:00:00",
  "message": "Scheduler is currently enabled"
}
```

##### **POST /scheduler/enable** - Enable automatic data updates
```bash
curl -X POST https://scheduler-control-6ovej2yaoa-uc.a.run.app/enable
```
Response:
```json
{
  "status": "enabled",
  "message": "Scheduler enabled successfully",
  "timestamp": "2026-03-05T12:00:00"
}
```

##### **POST /scheduler/disable** - Disable automatic data updates
```bash
curl -X POST https://scheduler-control-6ovej2yaoa-uc.a.run.app/disable
```
Response:
```json
{
  "status": "disabled",
  "message": "Scheduler disabled successfully",
  "timestamp": "2026-03-05T12:00:00"
}
```

##### **POST /scheduler/trigger** - Manually trigger data update (with optional filters)
```bash
# Trigger all configured instruments
curl -X POST https://scheduler-control-6ovej2yaoa-uc.a.run.app/trigger

# Selective sync - only GOLD instrument
curl -X POST https://scheduler-control-6ovej2yaoa-uc.a.run.app/trigger \
  -H "Content-Type: application/json" \
  -d '{"instruments": ["GOLD"]}'

# Selective sync - only M15 timeframe
curl -X POST https://scheduler-control-6ovej2yaoa-uc.a.run.app/trigger \
  -H "Content-Type: application/json" \
  -d '{"timeframes": ["M15"]}'

# Selective sync - specific instrument and timeframe
curl -X POST https://scheduler-control-6ovej2yaoa-uc.a.run.app/trigger \
  -H "Content-Type: application/json" \
  -d '{"instruments": ["GOLD"], "timeframes": ["M15"], "force": true}'
```

Request Body (all optional):
```json
{
  "instruments": ["GOLD", "EURUSD"],  // Filter by instrument names
  "timeframes": ["M5", "M15"],         // Filter by timeframes
  "force": true                         // Skip time checks, force update
}
```

Response (Success):
```json
{
  "status": "triggered",
  "message": "Data update started successfully",
  "filters": {
    "instruments": ["GOLD"],
    "timeframes": ["M15"],
    "force": false
  },
  "timestamp": "2026-03-05T12:00:00",
  "updater_response": {
    "summary": {
      "total": 1,
      "successful": 1,
      "failed": 0
    },
    "duration_seconds": 1.2,
    "datasets": {
      "GOLD_M15_10000": {
        "success": true,
        "timestamp": "2026-03-05T12:00:00"
      }
    }
  }
}
```

Response (Error - if data updater has no credentials):
```json
{
  "status": "error",
  "message": "Data updater returned error: 500",
  "details": "No credentials found in environment",
  "timestamp": "2026-03-05T12:00:00"
}
```

##### **GET /data** - Get available data status
```bash
curl https://scheduler-control-6ovej2yaoa-uc.a.run.app/data
```
Response:
```json
{
  "total_datasets": 12,
  "datasets": [
    {
      "instrument": "BITCOIN",
      "timeframe": "M15",
      "bars": 10000,
      "filename": "BITCOIN_M15_10000bars.csv",
      "size_bytes": 2458624,
      "size_mb": 2.34,
      "last_updated": "2026-03-05T11:45:00.000Z",
      "gcs_path": "data/BITCOIN_M15_10000bars.csv"
    },
    {
      "instrument": "GOLD",
      "timeframe": "M5",
      "bars": 5000,
      "filename": "GOLD_M5_5000bars.csv",
      "size_bytes": 1234567,
      "size_mb": 1.18,
      "last_updated": "2026-03-05T11:30:00.000Z",
      "gcs_path": "data/GOLD_M5_5000bars.csv"
    }
  ],
  "timestamp": "2026-03-05T12:00:00"
}
```

##### **GET /instruments** - List configured instruments
```bash
curl https://scheduler-control-6ovej2yaoa-uc.a.run.app/instruments
```
Response:
```json
{
  "total": 3,
  "instruments": [
    {
      "epic": "GOLD",
      "timeframe": "M15",
      "bars": 10000
    },
    {
      "epic": "GOLD",
      "timeframe": "M5",
      "bars": 5000
    },
    {
      "epic": "EURUSD",
      "timeframe": "M15",
      "bars": 10000
    }
  ],
  "timestamp": "2026-03-05T12:00:00"
}
```

##### **POST /instruments** - Add new instrument to sync
```bash
curl -X POST https://scheduler-control-6ovej2yaoa-uc.a.run.app/instruments \
  -H "Content-Type: application/json" \
  -d '{
    "epic": "BTCUSD",
    "timeframe": "M15",
    "bars": 5000
  }'
```
Request Body:
```json
{
  "epic": "BTCUSD",        // Instrument name
  "timeframe": "M15",      // M5 or M15
  "bars": 5000             // Number of bars to fetch
}
```
Response:
```json
{
  "status": "added",
  "instrument": {
    "epic": "BTCUSD",
    "timeframe": "M15",
    "bars": 5000
  },
  "total_instruments": 4
}
```

##### **DELETE /instruments** - Remove instrument from sync
```bash
curl -X DELETE https://scheduler-control-6ovej2yaoa-uc.a.run.app/instruments \
  -H "Content-Type: application/json" \
  -d '{
    "epic": "BTCUSD",
    "timeframe": "M15",
    "bars": 5000
  }'
```
Request Body:
```json
{
  "epic": "BTCUSD",
  "timeframe": "M15",
  "bars": 5000
}
```
Response:
```json
{
  "status": "removed",
  "instrument": {
    "epic": "BTCUSD",
    "timeframe": "M15",
    "bars": 5000
  },
  "total_instruments": 3
}
```

---

#### 3. **Check Optimization Status**

**GET /optimize/{run_id}**
```bash
curl https://optimize-api-6ovej2yaoa-uc.a.run.app/optimize/a7f3c91b
```
Response:
```json
{
  "run_id": "a7f3c91b",
  "status": "completed",  // queued | running | completed | failed
  "start_time": "2026-03-05T11:30:00",
  "end_time": "2026-03-05T11:33:45",
  "duration_seconds": 225,
  "results": {
    "best_sharpe": 2.45,
    "best_profit": 5420.50,
    "combinations_tested": 540
  }
}
```

---

#### 4. **List All Optimizations**

**GET /optimize**
```bash
curl https://optimize-api-6ovej2yaoa-uc.a.run.app/optimize
```
Response:
```json
{
  "runs": [
    {
      "run_id": "a7f3c91b",
      "status": "completed",
      "instrument": "GOLD",
      "timeframe": "M5",
      "created": "2026-03-05T11:30:00"
    }
  ]
}
```

---

#### 5. **Delete Optimization**

**DELETE /optimize/{run_id}**
```bash
curl -X DELETE https://optimize-api-6ovej2yaoa-uc.a.run.app/optimize/a7f3c91b
```

---

## Instruments Available (Updated)

### Forex (4)
- `EURUSD` - Euro / US Dollar
- `EURGBP` - Euro / British Pound
- `GBPUSD` - British Pound / US Dollar

### Commodities (2)
- `GOLD` - Gold
- `SILVER` - Silver

### Crypto (1)
- `BITCOIN` - Bitcoin

### Indices (2)
- `US30` - Dow Jones
- `NASDAQ` - NASDAQ 100

**Total: 12 datasets across 7 instruments**

---

## Data Update Schedule

**Intelligent Scheduling** (automatically adjusts based on timeframe):
- **M5 data**: Updates every **30 minutes** (real-time intraday)
- **M15 data**: Updates every **2 hours** (less frequent for swing trading)

**Manual Control**:
- Use `/scheduler/enable` to start automatic updates
- Use `/scheduler/disable` to stop automatic updates
- Use `/scheduler/trigger` to force immediate update

---

## Frontend Integration Examples

### React/TypeScript Example

```typescript
// services/api.ts
const API_BASE = 'https://optimize-api-6ovej2yaoa-uc.a.run.app';
const SCHEDULER_BASE = 'https://scheduler-control-6ovej2yaoa-uc.a.run.app';

// Start optimization with custom parameters
async function startOptimization(config: OptimizationConfig) {
  const response = await fetch(`${API_BASE}/optimize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      instrument: config.instrument,
      timeframe: config.timeframe,
      mode: config.mode,
      supertrend_periods: config.customIndicators.supertrendPeriods,
      tp_sl_strategy: config.tpSlStrategy,
      pip_values: config.leverageMultipliers,
      // ... other parameters
    })
  });
  return await response.json();
}

// Check optimization status
async function checkStatus(runId: string) {
  const response = await fetch(`${API_BASE}/optimize/${runId}`);
  return await response.json();
}

// Scheduler control
async function getSchedulerStatus() {
  const response = await fetch(`${SCHEDULER_BASE}/status`);
  return await response.json();
}

async function toggleScheduler(enable: boolean) {
  const endpoint = enable ? 'enable' : 'disable';
  const response = await fetch(`${SCHEDULER_BASE}/${endpoint}`, {
    method: 'POST'
  });
  return await response.json();
}

// Trigger data update with optional filters
async function triggerDataUpdate(filters?: {
  instruments?: string[];
  timeframes?: string[];
  force?: boolean;
}) {
  const response = await fetch(`${SCHEDULER_BASE}/trigger`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: filters ? JSON.stringify(filters) : '{}'
  });
  return await response.json();
}

// Get available data status
async function getDataStatus() {
  const response = await fetch(`${SCHEDULER_BASE}/data`);
  return await response.json();
}

// Instrument management
async function listInstruments() {
  const response = await fetch(`${SCHEDULER_BASE}/instruments`);
  return await response.json();
}

async function addInstrument(epic: string, timeframe: string, bars: number) {
  const response = await fetch(`${SCHEDULER_BASE}/instruments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ epic, timeframe, bars })
  });
  return await response.json();
}

async function removeInstrument(epic: string, timeframe: string, bars: number) {
  const response = await fetch(`${SCHEDULER_BASE}/instruments`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ epic, timeframe, bars })
  });
  return await response.json();
}
```

### UI Components Needed

#### 1. Optimization Form
```typescript
interface OptimizationForm {
  // Basic
  instrument: Dropdown  // GOLD, EURUSD, BITCOIN, etc
  timeframe: Dropdown   // M5, M15
  mode: RadioGroup      // quick | medium | full
  
  // Advanced (collapsible)
  indicators: {
    supertrend: RangeSliders
    sma: RangeSliders
    ema: RangeSliders
    bb: RangeSliders
  }
  
  tpSl: {
    strategy: RadioGroup  // fixed | atr | both
    fixedPips: RangeSliders
    atrMultipliers: RangeSliders
  }
  
  leverage: MultiSlider   // pip_values
  filters: {
    minTrades: NumberInput
    minWinRate: Slider
    maxDrawdown: Slider
  }
}
```

#### 2. Scheduler Control Panel
```typescript
interface SchedulerControl {
  status: Badge           // "Enabled" (green) | "Disabled" (red)
  toggleButton: Switch    // Enable/Disable
  triggerButton: Button   // "Update Now"
  
  // Selective sync filters
  instrumentFilter: MultiSelect  // Filter by instruments
  timeframeFilter: MultiSelect   // Filter by timeframes
  forceUpdate: Checkbox          // Skip time checks
  
  lastUpdate: Text        // "Last update: 5 min ago"
  nextUpdate: Text        // "Next update: in 25 min"
}
```

#### 2b. Instrument Management
```typescript
interface InstrumentManager {
  instruments: DataGrid   // Table of configured instruments
  columns: [
    'epic',               // GOLD, EURUSD, BTCUSD
    'timeframe',          // M5, M15
    'bars',               // 5000, 10000
    'actions'             // Delete button
  ]
  addButton: Button       // "Add Instrument"
  addDialog: {
    epic: Input
    timeframe: Dropdown   // M5 | M15
    bars: NumberInput     // 2000, 5000, 10000
    saveButton: Button
  }
  totalInstruments: Badge // "3 instruments"
}
```

#### 3. Data Status Display
```typescript
interface DataStatusDisplay {
  datasets: DataGrid      // Table showing all available datasets
  columns: [
    'instrument',         // GOLD, EURUSD, etc.
    'timeframe',          // M5, M15
    'bars',               // 5000, 10000
    'size_mb',            // File size
    'last_updated',       // Time ago
  ]
  totalDatasets: Badge    // "12 datasets"
  refreshButton: Button   // Refresh status
}
```

#### 4. Status Monitor
```typescript
interface StatusMonitor {
  runId: Text
  status: Badge          // queued | running | completed | failed
  progress: ProgressBar  // 45/540 combinations
  eta: Text             // ETA: 2 min remaining
  results: ResultsTable // Best strategies
}
```

---

## Deployment Commands

### Deploy Scheduler Control API
```bash
cd /Users/kirtanbhatt/code/stockScreener/cloud-function

# Deploy scheduler control function
gcloud functions deploy scheduler-control \
  --gen2 \
  --runtime=python311 \
  --region=us-central1 \
  --source=. \
  --entry-point=scheduler_control \
  --trigger-http \
  --allow-unauthenticated \
  --timeout=60s \
  --memory=256MB \
  --set-env-vars="GCS_BUCKET=double-venture-442318-k8-optimization-results" \
  --project=double-venture-442318-k8
```

### Update Data Updater (with new instruments)
```bash
gcloud functions deploy data-updater \
  --gen2 \
  --runtime=python311 \
  --region=us-central1 \
  --source=. \
  --entry-point=update_market_data \
  --trigger-http \
  --no-allow-unauthenticated \
  --timeout=540s \
  --memory=512MB \
  --max-instances=1 \
  --set-env-vars="GCS_BUCKET=double-venture-442318-k8-optimization-results" \
  --set-secrets="apicredentials=capitalService:latest" \
  --service-account=361802071308-compute@developer.gserviceaccount.com \
  --project=double-venture-442318-k8
```

---

## Summary

✅ **Enhanced Optimization API**: 20+ customizable parameters for complete strategy control
✅ **Scheduler Control API**: Start/stop data updates from UI
✅ **Selective Sync**: Filter updates by instrument and timeframe
✅ **Instrument Management**: Add/remove instruments dynamically via API
✅ **12+ Instruments**: Forex, commodities, crypto, indices (expandable)
✅ **Intelligent Scheduling**: M5 every 30min, M15 every 2hr
✅ **Full CORS Support**: Ready for browser-based frontends
✅ **Status Monitoring**: Real-time optimization tracking

**All endpoints are production-ready and CORS-enabled for your UI!** 🚀

---

## Recent Updates (March 2026)

### ✨ New Features

**Selective Data Sync** (POST /scheduler/trigger)
- Filter by instruments: `{"instruments": ["GOLD", "EURUSD"]}`
- Filter by timeframes: `{"timeframes": ["M15"]}`
- Combine filters: `{"instruments": ["GOLD"], "timeframes": ["M15"]}`
- Force updates: `{"force": true}` to skip time checks
- Tested: ✅ GOLD only → 2 datasets, GOLD M15 only → 1 dataset, No filters → 3 datasets

**Dynamic Instrument Management**
- GET /instruments - List configured instruments
- POST /instruments - Add new instrument to sync
- DELETE /instruments - Remove instrument from sync
- Config persists in GCS (instruments_config.json)
- Tested: ✅ Add/remove BTCUSD, config loads correctly

**Enhanced Logging**
- Config loading: Shows instruments loaded from GCS
- Filter application: Shows filtered vs total datasets
- Debug traces: Full visibility into sync process
