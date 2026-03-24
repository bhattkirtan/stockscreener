# 🚀 Lovable UI Integration Guide

## API Overview

Your backend has **two main API groups** deployed and running:

### 1. Strategy Optimization APIs
- ✅ Strategy indicators (Supertrend, SMA, EMA, Bollinger Bands)
- ✅ TP/SL strategies (Fixed pips vs ATR-based)
- ✅ Pip value optimization (leverage scaling)
- ✅ Advanced filters (min trades, win rate, drawdown)
- ✅ Data selection options (12 instruments across Forex/Commodities/Crypto/Indices)

### 2. Live Trading Bot Monitoring APIs (NEW!)
- ✅ Real-time bot status and health monitoring
- ✅ Active positions with P&L tracking
- ✅ Trading signals and entry/exit notifications
- ✅ Live log streaming (Firestore, 24h retention)
- ✅ Historical log archives (GCS)
- ✅ Capital.com trading operations

## Production Endpoints

### 🤖 Bot Monitoring & Trading API (capitalComService)
- **URL**: `https://capitalcomservice-6ovej2yaoa-uc.a.run.app`
- **Purpose**: Live bot monitoring, trading operations, real-time logs
- **Status**: ✅ Deployed & Healthy

**Key Endpoints:**
- `GET /bot/status` - Bot health, uptime, statistics
- `GET /bot/positions` - Active positions with real-time P&L
- `GET /bot/signals` - Recent trading signals
- `GET /bot/logs/live` - Real-time log streaming (last 24h)
- `GET /logs/get` - Historical logs from GCS
- `GET /logs/dates` - Available log archive dates
- Capital.com API: `/get_positions`, `/create_position`, `/close_position`, etc.

**Health Check:**
```bash
curl https://capitalcomservice-6ovej2yaoa-uc.a.run.app/
```

### 📊 Optimization API
- **URL**: `https://optimize-api-6ovej2yaoa-uc.a.run.app`
- **Endpoint**: `POST /optimize`
- **Status**: ✅ Deployed & Healthy

### 🕐 Scheduler Control API (Data Sync)
- **URL**: `https://scheduler-control-6ovej2yaoa-uc.a.run.app`
- **Endpoints**: 
  - `GET /scheduler/status` - Check if auto-updates are enabled
  - `POST /scheduler/enable` - Enable automatic data updates
  - `POST /scheduler/disable` - Disable automatic data updates
  - `POST /scheduler/trigger` - Manually trigger data update
- **Status**: ✅ Deployed & Healthy

### Health Checks
```bash
# Verify all services are running
curl https://capitalcomservice-6ovej2yaoa-uc.a.run.app/
curl https://optimize-api-6ovej2yaoa-uc.a.run.app/health
curl https://optimizer-worker-6ovej2yaoa-uc.a.run.app/health
curl https://scheduler-control-6ovej2yaoa-uc.a.run.app/scheduler/status
```

## Available Instruments

The system currently supports **12 instruments** across 4 categories:

### Forex (M15 data)
- **EURUSD** - Euro vs US Dollar
- **EURGBP** - Euro vs British Pound
- **GBPUSD** - British Pound vs US Dollar

### Commodities
- **GOLD** - Gold (M5 and M15 data available)
- **SILVER** - Silver (M15 data)

### Crypto
- **BITCOIN** - Bitcoin (M5 and M15 data available)

### Indices (M15 data)
- **US30** - Dow Jones Industrial Average
- **NASDAQ** - NASDAQ 100

**Note**: Data is automatically updated every 30 minutes when the scheduler is enabled. New instruments can be added by updating the backend configuration.

---

## 🤖 Bot Monitoring API Integration (NEW!)

The **capitalComService** provides real-time bot monitoring and trading operations.

### Base URL
```typescript
const BOT_API_BASE = 'https://capitalcomservice-6ovej2yaoa-uc.a.run.app';
```

### 1. Bot Status Dashboard

Display real-time bot health and statistics:

```typescript
// frontend/src/services/botMonitoring.ts
export interface BotStatus {
  bot_id: string;
  status: 'RUNNING' | 'STOPPED' | 'ERROR';
  uptime_seconds: number;
  last_heartbeat: string;
  current_capital: number;
  total_trades: number;
  open_positions_count: number;
  win_rate?: number;
  total_pnl?: number;
}

export async function getBotStatus(bot_id: string = 'gold_m5_bot'): Promise<BotStatus> {
  const response = await fetch(
    `${BOT_API_BASE}/bot/status?bot_id=${bot_id}`
  );
  return response.json();
}

// Usage in React component:
function BotStatusWidget() {
  const [status, setStatus] = useState<BotStatus | null>(null);
  
  useEffect(() => {
    // Poll every 5 seconds
    const fetchStatus = async () => {
      const data = await getBotStatus('gold_m5_bot');
      setStatus(data);
    };
    
    fetchStatus();
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, []);
  
  if (!status) return <div>Loading...</div>;
  
  return (
    <div className="bot-status-card">
      <div className="status-header">
        <h3>{status.bot_id}</h3>
        <span className={`status-badge ${status.status.toLowerCase()}`}>
          {status.status}
        </span>
      </div>
      <div className="stats-grid">
        <div>Uptime: {formatUptime(status.uptime_seconds)}</div>
        <div>Capital: ${status.current_capital.toFixed(2)}</div>
        <div>Trades: {status.total_trades}</div>
        <div>Win Rate: {(status.win_rate * 100).toFixed(1)}%</div>
        <div>P&L: ${status.total_pnl?.toFixed(2)}</div>
      </div>
    </div>
  );
}
```

### 2. Active Positions Viewer

Monitor open positions with real-time P&L:

```typescript
export interface Position {
  position_id: string;
  deal_id: string;
  epic: string;
  direction: 'BUY' | 'SELL';
  size: number;
  open_level: number;
  current_level: number;
  pnl: number;
  pnl_pct: number;
  stop_loss?: number;
  take_profit?: number;
  opened_at: string;
  signal_data?: any;
}

export async function getActivePositions(
  status: 'open' | 'closed' = 'open',
  epic?: string
): Promise<Position[]> {
  let url = `${BOT_API_BASE}/bot/positions?status=${status}`;
  if (epic) url += `&epic=${epic}`;
  
  const response = await fetch(url);
  const data = await response.json();
  return data.positions || [];
}

// Usage:
function PositionsTable() {
  const [positions, setPositions] = useState<Position[]>([]);
  
  useEffect(() => {
    const fetchPositions = async () => {
      const data = await getActivePositions('open');
      setPositions(data);
    };
    
    fetchPositions();
    const interval = setInterval(fetchPositions, 3000); // 3 second refresh
    return () => clearInterval(interval);
  }, []);
  
  return (
    <table className="positions-table">
      <thead>
        <tr>
          <th>Epic</th>
          <th>Direction</th>
          <th>Size</th>
          <th>Entry</th>
          <th>Current</th>
          <th>P&L</th>
          <th>P&L %</th>
        </tr>
      </thead>
      <tbody>
        {positions.map(pos => (
          <tr key={pos.position_id}>
            <td>{pos.epic}</td>
            <td>{pos.direction}</td>
            <td>{pos.size}</td>
            <td>{pos.open_level}</td>
            <td>{pos.current_level}</td>
            <td className={pos.pnl >= 0 ? 'profit' : 'loss'}>
              ${pos.pnl.toFixed(2)}
            </td>
            <td className={pos.pnl_pct >= 0 ? 'profit' : 'loss'}>
              {pos.pnl_pct.toFixed(2)}%
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

### 3. Trading Signals Feed

Display recent bot signals and trade decisions:

```typescript
export interface TradingSignal {
  signal_id: string;
  bot_id: string;
  epic: string;
  timestamp: string;
  signal_type: 'BUY' | 'SELL' | 'CLOSE';
  confidence?: number;
  indicators: {
    supertrend?: string;
    sma_alignment?: boolean;
    rsi?: number;
  };
  action_taken: 'executed' | 'pending' | 'rejected';
  position_id?: string;
}

export async function getTradingSignals(
  epic?: string,
  limit: number = 20
): Promise<TradingSignal[]> {
  let url = `${BOT_API_BASE}/bot/signals?limit=${limit}`;
  if (epic) url += `&epic=${epic}`;
  
  const response = await fetch(url);
  const data = await response.json();
  return data.signals || [];
}

// Usage:
function SignalsFeed() {
  const [signals, setSignals] = useState<TradingSignal[]>([]);
  
  useEffect(() => {
    const fetchSignals = async () => {
      const data = await getTradingSignals('GOLD', 10);
      setSignals(data);
    };
    
    fetchSignals();
    const interval = setInterval(fetchSignals, 10000); // 10 second refresh
    return () => clearInterval(interval);
  }, []);
  
  return (
    <div className="signals-feed">
      <h3>Recent Signals</h3>
      {signals.map(signal => (
        <div key={signal.signal_id} className={`signal-card ${signal.signal_type.toLowerCase()}`}>
          <div className="signal-header">
            <span className="signal-type">{signal.signal_type}</span>
            <span className="epic">{signal.epic}</span>
            <span className="time">{formatRelativeTime(signal.timestamp)}</span>
          </div>
          <div className="signal-details">
            <span className={`action ${signal.action_taken}`}>
              {signal.action_taken}
            </span>
            {signal.confidence && (
              <span className="confidence">
                Confidence: {(signal.confidence * 100).toFixed(0)}%
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
```

### 4. Live Log Streaming (NEW!)

Real-time log monitoring for debugging and monitoring:

```typescript
export interface BotLog {
  id: string;
  timestamp: string;
  level: 'INFO' | 'WARNING' | 'ERROR' | 'DEBUG';
  logger: string;
  message: string;
  bot_id: string;
  run_id: string;
  sequence: number;
  ttl: string; // 24-hour auto-cleanup
}

export async function getLiveLogs(
  bot_id: string = 'gold_m5_bot',
  limit: number = 100,
  level?: string,
  run_id?: string
): Promise<BotLog[]> {
  let url = `${BOT_API_BASE}/bot/logs/live?bot_id=${bot_id}&limit=${limit}`;
  if (level) url += `&level=${level}`;
  if (run_id) url += `&run_id=${run_id}`;
  
  const response = await fetch(url);
  const data = await response.json();
  return data.logs || [];
}

// Usage - Auto-refreshing log viewer:
function LiveLogsViewer() {
  const [logs, setLogs] = useState<BotLog[]>([]);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [filter, setFilter] = useState<string>('');
  
  useEffect(() => {
    if (!autoRefresh) return;
    
    const fetchLogs = async () => {
      const data = await getLiveLogs('gold_m5_bot', 50, filter || undefined);
      setLogs(data);
    };
    
    fetchLogs();
    const interval = setInterval(fetchLogs, 5000); // 5 second refresh
    return () => clearInterval(interval);
  }, [autoRefresh, filter]);
  
  return (
    <div className="live-logs-viewer">
      <div className="logs-controls">
        <select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">All Levels</option>
          <option value="ERROR">Errors Only</option>
          <option value="WARNING">Warnings</option>
          <option value="INFO">Info</option>
        </select>
        <button onClick={() => setAutoRefresh(!autoRefresh)}>
          {autoRefresh ? '⏸ Pause' : '▶ Resume'}
        </button>
      </div>
      
      <div className="logs-container">
        {logs.map(log => (
          <div key={log.id} className={`log-line level-${log.level.toLowerCase()}`}>
            <span className="timestamp">{new Date(log.timestamp).toLocaleTimeString()}</span>
            <span className={`level ${log.level.toLowerCase()}`}>{log.level}</span>
            <span className="logger">{log.logger}</span>
            <span className="message">{log.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// CSS suggestion:
const styles = `
.log-line.level-error { background: #fee; border-left: 4px solid #f00; }
.log-line.level-warning { background: #ffc; border-left: 4px solid #fa0; }
.log-line.level-info { background: #eff; border-left: 4px solid #0af; }
`;
```

### 5. Combined Dashboard Example

Putting it all together:

```typescript
function TradingDashboard() {
  return (
    <div className="trading-dashboard">
      <div className="dashboard-header">
        <h1>Live Trading Bot Monitor</h1>
      </div>
      
      <div className="dashboard-grid">
        {/* Top Row - Status Cards */}
        <div className="status-section">
          <BotStatusWidget />
        </div>
        
        {/* Middle Row - Positions and Signals */}
        <div className="positions-section">
          <h2>Active Positions</h2>
          <PositionsTable />
        </div>
        
        <div className="signals-section">
          <SignalsFeed />
        </div>
        
        {/* Bottom Row - Live Logs */}
        <div className="logs-section full-width">
          <h2>Live Logs</h2>
          <LiveLogsViewer />
        </div>
      </div>
    </div>
  );
}
```

### API Endpoints Summary

| Endpoint | Method | Description | Refresh Rate |
|----------|--------|-------------|--------------|
| `/bot/status` | GET | Bot health and stats | 5 seconds |
| `/bot/positions` | GET | Active positions with P&L | 3 seconds |
| `/bot/signals` | GET | Recent trading signals | 10 seconds |
| `/bot/logs/live` | GET | Real-time logs (24h) | 5 seconds |
| `/logs/get` | GET | Historical logs (GCS) | On demand |
| `/logs/dates` | GET | Available log dates | On demand |

### Query Parameters

**Bot Status:**
- `bot_id` (default: `gold_m5_bot`) - Bot identifier

**Positions:**
- `status` (default: `open`) - Filter: `open` or `closed`
- `epic` (optional) - Filter by instrument: `GOLD`, `EURUSD`, etc.

**Signals:**
- `epic` (optional) - Filter by instrument
- `limit` (default: 20) - Number of signals to return

**Live Logs:**
- `bot_id` (default: `gold_m5_bot`) - Bot identifier
- `run_id` (optional) - Specific bot run, or `latest`
- `limit` (default: 200, max: 500) - Number of logs
- `level` (optional) - Filter: `ERROR`, `WARNING`, `INFO`, `DEBUG`

---

## 📊 Strategy Optimization UI Integration

### 1. Basic UI (Current - Minimal Changes)

Your current UI already works! Just update the API call:

```typescript
// frontend/src/utils/api.ts
export async function startOptimization(params: {
  instrument: string;
  timeframe: string;
  initial_capital: number;
  position_size: number;
  mode: 'quick' | 'medium' | 'full';
}) {
  const response = await fetch('https://optimize-api-6ovej2yaoa-uc.a.run.app/optimize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params)
  });
  return response.json();
}

// Usage (no changes needed)
const result = await startOptimization({
  instrument: 'GOLD',
  timeframe: 'M5',
  initial_capital: 10000,
  position_size: 0.1,
  mode: 'quick'
});
```

**This works immediately** - no UI changes required!

---

### 2. Enhanced UI - Add Advanced Options

Add a collapsible "Advanced" section for power users:

```typescript
// frontend/src/components/OptimizationForm.tsx
import { useState } from 'react';

export function OptimizationForm() {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [params, setParams] = useState({
    // Basic (always visible)
    instrument: 'GOLD',
    timeframe: 'M5',
    initial_capital: 10000,
    position_size: 0.1,
    mode: 'quick',
    
    // Advanced (optional overrides)
    pip_values: null as number[] | null,
    tp_sl_strategy: 'both',
    sl_pips_range: null as number[] | null,
    tp_pips_range: null as number[] | null,
    min_win_rate: 0,
    max_drawdown_pct: null as number | null,
  });
  
  return (
    <div className="optimization-form">
      {/* Basic Fields */}
      <select value={params.instrument} onChange={e => setParams({...params, instrument: e.target.value})}>
        <option value="GOLD">Gold</option>
        <option value="EURUSD">EUR/USD</option>
        <option value="GBPUSD">GBP/USD</option>
      </select>
      
      <select value={params.timeframe} onChange={e => setParams({...params, timeframe: e.target.value})}>
        <option value="M5">5 Minutes</option>
        <option value="M15">15 Minutes</option>
        <option value="H1">1 Hour</option>
      </select>
      
      <input type="number" value={params.initial_capital} 
             onChange={e => setParams({...params, initial_capital: +e.target.value})} />
      
      <input type="number" step="0.01" value={params.position_size}
             onChange={e => setParams({...params, position_size: +e.target.value})} />
      
      <select value={params.mode} onChange={e => setParams({...params, mode: e.target.value as any})}>
        <option value="quick">Fast (~2 min)</option>
        <option value="medium">Medium (~5 min)</option>
        <option value="full">Full (~30 min)</option>
      </select>
      
      {/* Advanced Toggle */}
      <button onClick={() => setShowAdvanced(!showAdvanced)} className="text-sm text-blue-500">
        {showAdvanced ? '▼' : '▶'} Advanced Parameters
      </button>
      
      {/* Advanced Section */}
      {showAdvanced && (
        <div className="advanced-params mt-4 p-4 bg-gray-50 rounded">
          <h3 className="font-semibold mb-3">Advanced Options</h3>
          
          {/* TP/SL Strategy */}
          <label className="block mb-2">
            <span className="text-sm">TP/SL Strategy:</span>
            <select value={params.tp_sl_strategy} 
                    onChange={e => setParams({...params, tp_sl_strategy: e.target.value})}>
              <option value="both">Test Both (Recommended)</option>
              <option value="fixed">Fixed Pips Only</option>
              <option value="atr">ATR-Based Only</option>
            </select>
          </label>
          
          {/* Stop Loss Range */}
          <label className="block mb-2">
            <span className="text-sm">Stop Loss Pips (comma-separated):</span>
            <input type="text" placeholder="15,20,25,30" 
                   onChange={e => {
                     const vals = e.target.value.split(',').map(v => +v.trim()).filter(v => !isNaN(v));
                     setParams({...params, sl_pips_range: vals.length ? vals : null});
                   }} />
          </label>
          
          {/* Take Profit Range */}
          <label className="block mb-2">
            <span className="text-sm">Take Profit Pips (comma-separated):</span>
            <input type="text" placeholder="30,40,50,60,75" 
                   onChange={e => {
                     const vals = e.target.value.split(',').map(v => +v.trim()).filter(v => !isNaN(v));
                     setParams({...params, tp_pips_range: vals.length ? vals : null});
                   }} />
          </label>
          
          {/* Pip Values (Leverage) */}
          <label className="block mb-2">
            <span className="text-sm">Pip Values (Leverage Multiplier):</span>
            <input type="text" placeholder="1.0,2.0,3.0,5.0" 
                   onChange={e => {
                     const vals = e.target.value.split(',').map(v => +v.trim()).filter(v => !isNaN(v));
                     setParams({...params, pip_values: vals.length ? vals : null});
                   }} />
            <span className="text-xs text-gray-500">Higher = more aggressive</span>
          </label>
          
          {/* Filters */}
          <label className="block mb-2">
            <span className="text-sm">Minimum Win Rate (0-1):</span>
            <input type="number" step="0.05" min="0" max="1" value={params.min_win_rate}
                   onChange={e => setParams({...params, min_win_rate: +e.target.value})} />
          </label>
          
          <label className="block mb-2">
            <span className="text-sm">Max Drawdown %:</span>
            <input type="number" step="5" min="0" max="100" placeholder="30"
                   onChange={e => setParams({...params, max_drawdown_pct: e.target.value ? +e.target.value : null})} />
          </label>
        </div>
      )}
      
      <button onClick={() => startOptimization(params)} className="btn-primary mt-4">
        START OPTIMIZATION
      </button>
    </div>
  );
}
```

---

### 3. Progressive Disclosure UI (Best UX)

Show parameters progressively based on expertise level:

```typescript
export function SmartOptimizationForm() {
  const [expertise, setExpertise] = useState<'beginner' | 'intermediate' | 'expert'>('beginner');
  
  return (
    <div>
      {/* Expertise Level Selector */}
      <div className="mb-6">
        <label>Experience Level:</label>
        <div className="flex gap-2">
          <button 
            className={expertise === 'beginner' ? 'active' : ''}
            onClick={() => setExpertise('beginner')}
          >
            🎯 Beginner
          </button>
          <button 
            className={expertise === 'intermediate' ? 'active' : ''}
            onClick={() => setExpertise('intermediate')}
          >
            ⚙️ Intermediate
          </button>
          <button 
            className={expertise === 'expert' ? 'active' : ''}
            onClick={() => setExpertise('expert')}
          >
            🔬 Expert
          </button>
        </div>
      </div>
      
      {/* Beginner: Only basics */}
      {expertise === 'beginner' && <BeginnerForm />}
      
      {/* Intermediate: + TP/SL + Filters */}
      {expertise === 'intermediate' && <IntermediateForm />}
      
      {/* Expert: All parameters */}
      {expertise === 'expert' && <ExpertForm />}
    </div>
  );
}
```

---

### 4. Preset Strategies (User-Friendly)

Offer pre-configured optimization profiles:

```typescript
const PRESETS = {
  conservative: {
    name: "Conservative (High Win Rate)",
    description: "Focus on consistent wins with low drawdown",
    params: {
      mode: 'medium',
      tp_sl_strategy: 'atr',
      atr_sl_multipliers: [2.0, 2.5, 3.0],
      atr_tp_multipliers: [4.0, 5.0, 6.0],
      pip_values: [1.0, 1.5, 2.0],
      min_win_rate: 0.50,
      max_drawdown_pct: 20
    }
  },
  aggressive: {
    name: "Aggressive (Max Profit)",
    description: "High leverage optimization for maximum returns",
    params: {
      mode: 'full',
      tp_sl_strategy: 'both',
      pip_values: [2.0, 3.0, 5.0, 7.5, 10.0],
      min_win_rate: 0.40,
      max_drawdown_pct: 35
    }
  },
  balanced: {
    name: "Balanced",
    description: "Good risk/reward balance",
    params: {
      mode: 'medium',
      tp_sl_strategy: 'both',
      pip_values: [1.5, 2.0, 2.5, 3.0],
      min_win_rate: 0.45,
      max_drawdown_pct: 25
    }
  }
};

export function PresetSelector({ onSelect }: { onSelect: (params: any) => void }) {
  return (
    <div className="grid grid-cols-3 gap-4">
      {Object.entries(PRESETS).map(([key, preset]) => (
        <div key={key} className="preset-card p-4 border rounded cursor-pointer hover:border-blue-500"
             onClick={() => onSelect(preset.params)}>
          <h3 className="font-semibold">{preset.name}</h3>
          <p className="text-sm text-gray-600">{preset.description}</p>
        </div>
      ))}
    </div>
  );
}
```

---

## Quick Wins for Your UI

### 1. Add Mode Selection (5 min)
```typescript
// Just change the radio buttons to show time estimates
<label>
  <input type="radio" value="quick" checked={mode === 'quick'} />
  Fast (~2 min) - 500 combinations
</label>
<label>
  <input type="radio" value="medium" checked={mode === 'medium'} />
  Medium (~5 min) - 2000 combinations  
</label>
<label>
  <input type="radio" value="full" checked={mode === 'full'} />
  Full (~30 min) - 10000 combinations
</label>
```

### 2. Add Pip Value Slider (10 min)
```typescript
<label>
  Leverage Aggressiveness: {pipValue}x
  <input type="range" min="1" max="10" step="0.5" value={pipValue}
         onChange={e => setPipValue(+e.target.value)} />
  <span className="text-xs">
    {pipValue < 2 ? '🟢 Conservative' : pipValue < 5 ? '🟡 Moderate' : '🔴 Aggressive'}
  </span>
</label>
```

### 3. Add TP/SL Strategy Toggle (5 min)
```typescript
<select value={tpSlStrategy}>
  <option value="both">Smart (Test Both)</option>
  <option value="fixed">Fixed Pips</option>
  <option value="atr">Dynamic (ATR-based)</option>
</select>
```

---

## Testing

### 1. Test Basic Request (No Changes)
```bash
curl -X POST https://optimize-api-6ovej2yaoa-uc.a.run.app/optimize \
  -H "Content-Type: application/json" \
  -d '{
    "instrument": "GOLD",
    "timeframe": "M5",
    "initial_capital": 10000,
    "position_size": 0.1,
    "mode": "quick"
  }'
```

### 2. Test Advanced Request
```bash
curl -X POST https://optimize-api-6ovej2yaoa-uc.a.run.app/optimize \
  -H "Content-Type: application/json" \
  -d '{
    "instrument": "GOLD",
    "timeframe": "M5",
    "initial_capital": 10000,
    "position_size": 0.1,
    "mode": "medium",
    "pip_values": [1.5, 2.0, 2.5, 3.0],
    "tp_sl_strategy": "atr",
    "min_win_rate": 0.45
  }'
```

---

## Summary

✅ **Production Ready** - APIs deployed and tested  
✅ **Backward compatible** - Existing UI works without changes  
✅ **Progressive enhancement** - Add features incrementally  
✅ **User-friendly** - Presets + expertise levels  
✅ **Flexible** - From simple to expert control  

**Recommendation**: Start with basic mode selection and pip value slider, add advanced options later based on user feedback.

---

## Quick Reference for Lovable

### 🔗 API Endpoints

| Service | URL | Purpose |
|---------|-----|---------|
| Optimization API | `https://optimize-api-6ovej2yaoa-uc.a.run.app/optimize` | Run strategy backtests |
| Worker Health | `https://optimizer-worker-6ovej2yaoa-uc.a.run.app/health` | Check worker status |
| Scheduler Status | `https://scheduler-control-6ovej2yaoa-uc.a.run.app/scheduler/status` | Check auto-update status |
| Enable Scheduler | `https://scheduler-control-6ovej2yaoa-uc.a.run.app/scheduler/enable` | Enable data sync |
| Disable Scheduler | `https://scheduler-control-6ovej2yaoa-uc.a.run.app/scheduler/disable` | Disable data sync |

### 📊 Supported Instruments

**Forex**: EURUSD, EURGBP, GBPUSD  
**Commodities**: GOLD, SILVER  
**Crypto**: BITCOIN  
**Indices**: US30, NASDAQ

### ⏱️ Timeframes

- **M5** - 5 minutes (available for GOLD, BITCOIN)
- **M15** - 15 minutes (available for all instruments)
- **H1** - 1 hour (coming soon)

### 🎯 Optimization Modes

- `quick` - ~2 minutes, 500 combinations
- `medium` - ~5 minutes, 2000 combinations
- `full` - ~30 minutes, 10000+ combinations

### 🔧 Minimum Request (5 required fields)

```json
{
  "instrument": "GOLD",
  "timeframe": "M5",
  "initial_capital": 10000,
  "position_size": 0.1,
  "mode": "quick"
}
```

### 🚀 Advanced Parameters (20+ optional fields)

See [API_CUSTOMIZATION_GUIDE.md](./API_CUSTOMIZATION_GUIDE.md) for complete parameter documentation.

### 💾 Response Format

```json
{
  "status": "queued",
  "run_id": "uuid-here",
  "status_url": "https://optimize-api-6ovej2yaoa-uc.a.run.app/status/uuid-here",
  "estimated_time": "~2 minutes"
}
```

Poll the `status_url` to get results when optimization completes.

### 🔐 Authentication

**Current**: No authentication required (APIs are public)  
**Future**: Can add API keys or OAuth if needed

### 📚 Additional Documentation

- **[UNIFIED_API_GUIDE.md](../UNIFIED_API_GUIDE.md)** - Complete bot monitoring & trading API reference (capitalComService)
- **[LOGS_API_GUIDE.md](../LOGS_API_GUIDE.md)** - Historical log archives (GCS)
- [API_CUSTOMIZATION_GUIDE.md](./API_CUSTOMIZATION_GUIDE.md) - All 20+ optimization parameters explained
- [UI_CONTROL_API.md](./UI_CONTROL_API.md) - Complete optimization API reference
- [DEPLOYMENT_COMPLETE.md](./DEPLOYMENT_COMPLETE.md) - Full system architecture
- [FOLDER_STRUCTURE.md](../FOLDER_STRUCTURE.md) - Project organization

---

## 💰 Cost & Architecture Notes

### Bot Monitoring API (capitalComService)
- **Hosting**: Google Cloud Run (Gen 2)
- **Cost**: ~$0-5/month (minimal usage)
- **Firestore**: Live logs with 24h TTL = ~$1/month
- **GCS**: Historical log archives = ~$0.02/GB/month
- **Total**: < $10/month for complete monitoring

### Live Logs Architecture
```
Bot Logs → Firestore (live, 24h TTL) → Cloud Function API → UI
     ↓
   Timer (15 min)
     ↓
  GCS Bucket (historical archives)
```

**Benefits:**
- Real-time: 5-second latency via Firestore
- Cost-effective: Batched writes ($1/month vs $22/month direct GCS)
- Auto-cleanup: 24h TTL prevents data bloat
- Historical: Long-term archives in GCS

### Refresh Rate Recommendations
- **Bot Status**: Poll every 5 seconds
- **Positions**: Poll every 3 seconds (active trading)
- **Signals**: Poll every 10 seconds
- **Live Logs**: Poll every 5 seconds (pauseable)
- **Historical Logs**: On-demand only

### CORS Configuration
All APIs support CORS from any origin. For production, restrict to your domain:
```
Access-Control-Allow-Origin: https://your-ui-domain.com
```

---

**Last Updated**: March 24, 2026
**Backend Version**: v3.0 (Bot Monitoring + Live Logs + 12 instruments)
