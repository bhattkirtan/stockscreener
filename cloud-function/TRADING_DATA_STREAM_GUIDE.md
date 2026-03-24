# 🤖 Trading Bot Data Streaming & API Integration

Complete guide for accessing real-time trading bot data: bot status, active positions, trading signals, and logs.

## 📊 Architecture Overview

```
Trading Bot (Server) → Firestore (Cloud) → UI/API (Client)
        ↓                    ↓                  ↓
   - Status            - bot_status         - Real-time updates
   - Positions         - active_positions    - HTTP API
   - Signals           - trading_signals     - React hooks
   - Logs              - GCS bucket          - REST endpoints
```

## 🔥 Firestore Collections

### 1. `bot_status` - Bot Health Monitoring

**Document ID:** `gold_m5_bot`

**Schema:**
```json
{
  "bot_id": "gold_m5_bot",
  "status": "running|starting|stopped|error",
  "epic": "GOLD",
  "mode": "AUTO|SIGNAL_ONLY",
  "last_heartbeat": "2026-03-24T10:30:00",
  "last_updated": "2026-03-24T10:30:00",
  "start_time": "2026-03-24T08:00:00",
  "uptime_seconds": 9000,
  "statistics": {
    "signals_generated": 15,
    "orders_placed": 10,
    "positions_closed": 8,
    "total_pnl": 450.50
  },
  "metadata": {
    "min_history_bars": 20,
    "current_bars": 50
  }
}
```

**Updates:**
- Heartbeat every 30 seconds
- Status changes on bot start/stop/error
- Statistics increment on each event

### 2. `active_positions` - Live Position Tracking

**Document ID:** `{deal_id}`

**Schema:**
```json
{
  "deal_id": "DEAL123456",
  "epic": "GOLD",
  "direction": "BUY|SELL",
  "size": 0.5,
  "entry_price": 2650.25,
  "current_price": 2655.50,
  "pnl": 2.625,
  "stop_loss": 2630.25,
  "take_profit": 2690.25,
  "status": "opening|open|closing|closed",
  "opened_at": "2026-03-24T10:00:00",
  "closed_at": "2026-03-24T11:00:00",
  "close_price": 2670.00,
  "close_reason": "TP_HIT|SL_HIT|MANUAL|SERVER_CLOSED",
  "realized_pnl": 9.875,
  "last_updated": "2026-03-24T10:30:00"
}
```

**Updates:**
- Created when position opens
- P&L updated on every price quote (real-time)
- Status updated to CLOSED when position closes

### 3. `trading_signals` - Signal History

Already implemented! See existing `useSignals` hook.

**Document ID:** `{epic}_{timestamp}_{signal}`

**Schema:**
```json
{
  "signal_id": "GOLD_20260324_103000_BUY",
  "epic": "GOLD",
  "signal": "BUY|SELL",
  "price": 2650.25,
  "sl": 2630.25,
  "tp": 2690.25,
  "timestamp": "2026-03-24T10:30:00",
  "strategy": "SupertrendVWAP",
  "mode": "AUTO|SIGNAL_ONLY",
  "indicators": {
    "supertrend": 2645.0,
    "supertrend_direction": 1,
    "sma_fast": 2648.0,
    "sma_slow": 2640.0,
    "atr": 15.0
  }
}
```

---

## 🌐 HTTP API Endpoints

Base URL: `https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-api`

### GET `/bot/status` - Bot Health

**Query Params:**
- `bot_id` (optional): Bot identifier (default: `gold_m5_bot`)

**Response:**
```json
{
  "bot_id": "gold_m5_bot",
  "status": "running",
  "epic": "GOLD",
  "mode": "AUTO",
  "uptime_seconds": 9000,
  "last_heartbeat": "2026-03-24T10:30:00",
  "is_stale": false,
  "statistics": {
    "signals_generated": 15,
    "orders_placed": 10,
    "positions_closed": 8,
    "total_pnl": 450.50
  }
}
```

**Example:**
```bash
curl 'https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-api/bot/status'
```

### GET `/bot/positions` - Active Positions

**Query Params:**
- `status` (optional): Filter by status (`open`, `closed`, `all`) - default: `open`
- `epic` (optional): Filter by epic (e.g., `GOLD`)

**Response:**
```json
{
  "positions": [
    {
      "deal_id": "DEAL123",
      "epic": "GOLD",
      "direction": "BUY",
      "size": 0.5,
      "entry_price": 2650.25,
      "current_price": 2655.50,
      "pnl": 2.625,
      "stop_loss": 2630.25,
      "take_profit": 2690.25,
      "opened_at": "2026-03-24T10:00:00",
      "status": "open"
    }
  ],
  "count": 1,
  "total_pnl": 2.625
}
```

**Example:**
```bash
curl 'https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-api/bot/positions?status=open'
```

### GET `/bot/signals` - Trading Signals

**Query Params:**
- `epic` (optional): Filter by epic
- `limit` (optional): Max results (default: 20, max: 100)
- `mode` (optional): Filter by mode (`AUTO`, `SIGNAL_ONLY`, `all`)

**Response:**
```json
{
  "signals": [
    {
      "id": "GOLD_20260324_103000",
      "epic": "GOLD",
      "signal": "BUY",
      "price": 2650.25,
      "sl": 2630.25,
      "tp": 2690.25,
      "timestamp": "2026-03-24T10:30:00",
      "strategy": "SupertrendVWAP",
      "mode": "AUTO"
    }
  ],
  "count": 1
}
```

**Example:**
```bash
curl 'https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-api/bot/signals?epic=GOLD&limit=10'
```

---

## ⚛️ React Integration

### New Hooks for UI

#### `useBotStatus` - Bot Health

```typescript
import { useState, useEffect } from 'react';

interface BotStatus {
  bot_id: string;
  status: 'running' | 'starting' | 'stopped' | 'error';
  epic: string;
  mode: 'AUTO' | 'SIGNAL_ONLY';
  uptime_seconds: number;
  last_heartbeat: string;
  is_stale?: boolean;
  statistics: {
    signals_generated: number;
    orders_placed: number;
    positions_closed: number;
    total_pnl: number;
  };
}

export function useBotStatus(botId: string = 'gold_m5_bot') {
  const [status, setStatus] = useState<BotStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const response = await fetch(
          `https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-api/bot/status?bot_id=${botId}`
        );
        
        if (!response.ok) {
          throw new Error('Failed to fetch bot status');
        }
        
        const data = await response.json();
        setStatus(data);
        setError(null);
      } catch (err) {
        setError(err as Error);
      } finally {
        setLoading(false);
      }
    };

    fetchStatus();
    
    // Refresh every 30 seconds
    const interval = setInterval(fetchStatus, 30000);
    
    return () => clearInterval(interval);
  }, [botId]);

  return { status, loading, error };
}
```

#### `useActivePositions` - Live Positions

```typescript
import { useState, useEffect } from 'react';

interface Position {
  deal_id: string;
  epic: string;
  direction: 'BUY' | 'SELL';
  size: number;
  entry_price: number;
  current_price: number;
  pnl: number;
  stop_loss: number;
  take_profit: number;
  opened_at: string;
  status: 'open' | 'closed';
}

export function useActivePositions(epic?: string) {
  const [positions, setPositive] = useState<Position[]>([]);
  const [totalPnl, setTotalPnl] = useState<number>(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    const fetchPositions = async () => {
      try {
        const url = new URL('https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-api/bot/positions');
        url.searchParams.append('status', 'open');
        if (epic) url.searchParams.append('epic', epic);
        
        const response = await fetch(url.toString());
        
        if (!response.ok) {
          throw new Error('Failed to fetch positions');
        }
        
        const data = await response.json();
        setPositive(data.positions);
        setTotalPnl(data.total_pnl);
        setError(null);
      } catch (err) {
        setError(err as Error);
      } finally {
        setLoading(false);
      }
    };

    fetchPositions();
    
    // Refresh every 5 seconds for near real-time P&L
    const interval = setInterval(fetchPositions, 5000);
    
    return () => clearInterval(interval);
  }, [epic]);

  return { positions, totalPnl, loading, error };
}
```

### Firestore Real-Time Streaming (Alternative)

For zero-latency updates, use Firestore listeners directly:

```typescript
import { useEffect, useState } from 'react';
import { doc, onSnapshot } from 'firebase/firestore';
import { db } from '@/lib/firebase';

export function useBotStatusRealtime(botId: string = 'gold_m5_bot') {
  const [status, setStatus] = useState<BotStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const unsubscribe = onSnapshot(
      doc(db, 'bot_status', botId),
      (doc) => {
        if (doc.exists()) {
          setStatus(doc.data() as BotStatus);
        }
        setLoading(false);
      },
      (error) => {
        console.error('Firestore listener error:', error);
        setLoading(false);
      }
    );

    return () => unsubscribe();
  }, [botId]);

  return { status, loading };
}
```

---

## 🚀 Deployment

### 1. Deploy Trading Bot API

```bash
cd cloud-function
chmod +x deploy/deploy_trading_api.sh
./deploy/deploy_trading_api.sh
```

### 2. Redeploy Bot with New Features

The trading bot needs to be updated on the server:

```bash
# Copy new files
scp -i ~/.ssh/stockscreener_server src/live_trading/bot_status_publisher.py root@204.168.191.150:/opt/trading-bot/src/live_trading/
scp -i ~/.ssh/stockscreener_server src/live_trading/position_publisher.py root@204.168.191.150:/opt/trading-bot/src/live_trading/
scp -i ~/.ssh/stockscreener_server scripts/trading_bot_m5.py root@204.168.191.150:/opt/trading-bot/scripts/

# Restart bot
ssh -i ~/.ssh/stockscreener_server root@204.168.191.150 "systemctl restart trading-bot"
```

### 3. Verify Firestore Collections

After bot restart, check Firestore console:
- `bot_status` should have document `gold_m5_bot`
- `active_positions` should populate when positions open
- `trading_signals` should populate when signals generate

---

## 🧪 Testing

### Test Bot Status API

```bash
curl 'https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-api/bot/status'
```

Expected: `200 OK` with bot status JSON

### Test Positions API

```bash
curl 'https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-api/bot/positions'
```

Expected: `200 OK` with positions array (may be empty if no open positions)

### Test Signals API

```bash
curl 'https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-api/bot/signals?limit=5'
```

Expected: `200 OK` with recent signals

---

## 📋 Summary

### What's Tracked

✅ **Bot Status** - health, uptime, statistics (via Firestore + API)  
✅ **Active Positions** - real-time P&L updates (via Firestore + API)  
✅ **Trading Signals** - historical signals (already implemented)  
✅ **Logs** - uploaded to GCS every 15 min (see LOGS_API_GUIDE.md)

### Data Flow

1. **Bot publishes** to Firestore every few seconds
2. **API endpoints** expose data via HTTP (polling)
3. **Firestore listeners** provide real-time streaming (zero latency)
4. **UI consumes** via React hooks (your choice: HTTP or Firestore)

### Next Steps

1. Deploy Trading API: `./deploy/deploy_trading_api.sh`
2. Update bot on server with new publishers
3. Add `useBotStatus` and `useActivePositions` hooks to UI
4. Display bot health indicator and live P&L in dashboard

---

**Questions?** Check Firestore Console → `double-venture-442318-k8` → Collections
