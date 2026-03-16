# 📡 Signal Flow Architecture

## Overview

The trading bot publishes signals to **Firestore** (and optionally **Pub/Sub**) in real-time. Your main application (capital-connect React frontend or cloud-function backend) can consume these signals using multiple methods.

---

## 🏗️ Architecture Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                   Trading Bot (trading_bot.py)               │
│                   • Streams M5 candles from WebSocket        │
│                   • Aggregates M5 → M15                      │
│                   • Generates BUY/SELL signals               │
└─────────────────────────────┬────────────────────────────────┘
                              │
                              │ publish_signal()
                              ▼
┌──────────────────────────────────────────────────────────────┐
│              Signal Publisher (signal_publisher.py)          │
│              • SignalBackend.FIRESTORE (default)             │
│              • SignalBackend.PUBSUB (optional)               │
└────────┬─────────────────────────────────┬───────────────────┘
         │                                 │
         │                                 │
         ▼                                 ▼
┌──────────────────────┐         ┌──────────────────────┐
│   Firestore DB       │         │   Cloud Pub/Sub      │
│   Collection:        │         │   Topic:             │
│   trading_signals    │         │   trading-signals    │
│                      │         │                      │
│   • 50-200ms latency │         │   • 10-50ms latency  │
│   • Persistent       │         │   • Ephemeral        │
│   • Queryable        │         │   • Streaming        │
└─────────┬────────────┘         └────────┬─────────────┘
          │                               │
          │                               │
          ▼                               ▼
┌────────────────────────────────────────────────────────────┐
│                  Your Main App Consumers                    │
│                                                             │
│  1. React Frontend (capital-connect)                       │
│     • Firestore real-time listener                         │
│     • Updates UI instantly                                 │
│     • Shows notifications                                  │
│                                                             │
│  2. Cloud Function Backend                                 │
│     • HTTP API endpoints                                   │
│     • GET /api/signals                                     │
│     • GET /api/signals/latest                              │
│                                                             │
│  3. Mobile App (future)                                    │
│     • Push notifications                                   │
│     • Alert system                                         │
└────────────────────────────────────────────────────────────┘
```

---

## 🚀 Signal Data Structure

Signals published to Firestore have this structure:

```json
{
  "signal_id": "GOLD_20260309_143025_123456",
  "epic": "GOLD",
  "signal": "BUY",
  "direction": "BUY",
  "price": 1950.25,
  "sl": 1935.0,
  "tp": 1980.0,
  "timestamp": "2026-03-09T14:30:25.123456",
  "received_at": "2026-03-09T14:30:25.150000",
  "strategy": "SupertrendVWAP",
  "mode": "AUTO",
  "indicators": {
    "supertrend": 1945.0,
    "supertrend_direction": 1,
    "sma_fast": 1948.0,
    "sma_slow": 1940.0,
    "ema": 1947.5,
    "atr": 15.0,
    "golden_cross": true
  }
}
```

Fields:
- `signal_id`: Unique identifier
- `epic`: Instrument (GOLD, US100, ETHEREUM, etc.)
- `signal`: Direction (BUY or SELL)
- `price`: Entry price
- `sl`: Stop loss level
- `tp`: Take profit level
- `timestamp`: When signal was generated
- `mode`: AUTO (bot places order) or SIGNAL_ONLY (manual execution)
- `indicators`: Technical indicator values at signal time

---

## ⚡ Speed Comparison

| Method | Latency | Pros | Cons | Use Case |
|--------|---------|------|------|----------|
| **Pub/Sub Push** | 10-50ms | Fastest, scalable | Requires setup | HFT, microsecond-sensitive |
| **Firestore Listener** | 50-200ms | Real-time, persistent | Cloud only | Web apps, dashboards |
| **Firestore Polling** | 1-5s | Simple, no setup | Higher latency | Batch processing |
| **HTTP API** | 5-30s | Easy integration | Manual refresh | Reports, analytics |

**Recommendation**: Use **Firestore Real-time Listener** (already set up, good latency, persistent)

---

## 📥 Integration Options

### Option 1: Firestore Real-Time Listener (⭐ RECOMMENDED)

**Best for**: React frontend, real-time dashboards

```python
from scripts.signal_consumer import FirestoreSignalListener

def handle_signal(signal):
    print(f"🔔 Signal: {signal['signal']} {signal['epic']} @ {signal['price']}")
    # Update UI, send notification, etc.

listener = FirestoreSignalListener()
listener.start_listening(handle_signal, epic='GOLD')
```

**JavaScript/React version**:

```javascript
// In your capital-connect React app
import { onSnapshot, collection, query, where, orderBy } from 'firebase/firestore';
import { db } from './firebase';

function useSignals(epic) {
  const [signals, setSignals] = useState([]);
  
  useEffect(() => {
    const q = query(
      collection(db, 'trading_signals'),
      where('epic', '==', epic),
      orderBy('timestamp', 'desc')
    );
    
    const unsubscribe = onSnapshot(q, (snapshot) => {
      snapshot.docChanges().forEach((change) => {
        if (change.type === 'added') {
          const signal = change.doc.data();
          console.log('🔔 New signal:', signal);
          
          // Show notification
          toast.success(`${signal.signal} signal at ${signal.price}`);
          
          // Update state
          setSignals(prev => [signal, ...prev]);
        }
      });
    });
    
    return () => unsubscribe();
  }, [epic]);
  
  return signals;
}
```

### Option 2: Firestore Polling

**Best for**: Simple backend scripts, batch processing

```python
from scripts.signal_consumer import FirestoreSignalPoller
import asyncio

poller = FirestoreSignalPoller()

await poller.poll_forever(
    callback=lambda s: print(f"Signal: {s['signal']}"),
    interval_seconds=2,
    epic='GOLD'
)
```

### Option 3: HTTP API (Add to Cloud Function)

**Best for**: External integrations, mobile apps

Add to your `/cloud-function/functions/main.py`:

```python
from google.cloud import firestore

@app.get('/api/signals')
def get_signals(request):
    """Get recent trading signals
    
    Query params:
        limit: Max signals to return (default: 10)
        epic: Filter by instrument (optional)
    """
    db = firestore.Client()
    limit = int(request.args.get('limit', 10))
    epic = request.args.get('epic')
    
    query = db.collection('trading_signals')
    
    if epic:
        query = query.where('epic', '==', epic)
    
    query = query.order_by('timestamp', direction='DESCENDING')\
                .limit(limit)
    
    docs = query.stream()
    signals = [doc.to_dict() for doc in docs]
    
    return {'signals': signals, 'count': len(signals)}

@app.get('/api/signals/latest')
def get_latest_signal(request):
    """Get latest signal for an epic"""
    db = firestore.Client()
    epic = request.args.get('epic', 'GOLD')
    
    query = db.collection('trading_signals')\
                .where('epic', '==', epic)\
                .order_by('timestamp', direction='DESCENDING')\
                .limit(1)
    
    docs = list(query.stream())
    if docs:
        return docs[0].to_dict()
    return {'error': 'No signals found'}, 404
```

Then fetch from React:

```javascript
// Get latest signal
const response = await fetch('/api/signals/latest?epic=GOLD');
const signal = await response.json();
console.log('Latest signal:', signal);

// Get recent signals
const response = await fetch('/api/signals?limit=20&epic=GOLD');
const data = await response.json();
console.log(`Found ${data.count} signals:`, data.signals);
```

---

## 🛠️ Setup Instructions

### 1. Firestore Setup (Already Done ✅)

Your cloud-function already has Firestore enabled. No extra setup needed!

To verify:
```bash
gcloud firestore databases list
```

### 2. Enable Signal Publishing (Already Done ✅)

The trading bot automatically publishes to Firestore when it starts. Check logs:

```
📡 Signal publishing enabled (Firestore)
```

### 3. Test Signal Publishing

```bash
# Start bot
cd cloud-function
python3 scripts/trading_bot.py

# In another terminal, consume signals
python3 scripts/signal_consumer.py realtime
```

### 4. Optional: Pub/Sub Setup (For Ultra-Low Latency)

If you need <50ms latency:

```bash
# Create Pub/Sub topic
gcloud pubsub topics create trading-signals

# Create subscription
gcloud pubsub subscriptions create trading-signals-sub \
    --topic=trading-signals

# Update bot to publish to Pub/Sub
# In scripts/trading_bot.py, change:
self.signal_publisher = SignalPublisher(
    backends=[SignalBackend.FIRESTORE, SignalBackend.PUBSUB]
)

# Set GCP_PROJECT_ID
export GCP_PROJECT_ID=your-project-id

# Test subscriber
python3 scripts/signal_consumer.py pubsub
```

---

## 🧪 Testing Signal Flow

### End-to-End Test

Terminal 1 (Publisher):
```bash
cd cloud-function
python3 scripts/trading_bot.py
```

Terminal 2 (Consumer):
```bash
cd cloud-function
python3 scripts/signal_consumer.py realtime
```

You should see:
```
📡 NEW SIGNAL RECEIVED
   Epic: GOLD
   Direction: BUY
   Price: 1950.25
   Stop Loss: 1935.00
   Take Profit: 1980.00
```

### Manual Test (Simulate Signal)

```python
from src.live_trading.signal_publisher import SignalPublisher, SignalBackend

publisher = SignalPublisher(backends=[SignalBackend.FIRESTORE])

test_signal = {
    'epic': 'GOLD',
    'signal': 'BUY',
    'price': 1950.25,
    'sl': 1935.0,
    'tp': 1980.0,
    'timestamp': '2026-03-09T14:30:00'
}

publisher.publish_signal(test_signal)
# Check Firestore console: https://console.firebase.google.com/
```

---

## 📊 Monitoring Signals

### Check Firestore Data

```bash
# Via gcloud
gcloud firestore export gs://your-bucket/signals
gcloud firestore import gs://your-bucket/signals

# Via Python
from google.cloud import firestore
db = firestore.Client()
signals = list(db.collection('trading_signals').limit(10).stream())
for signal in signals:
    print(signal.to_dict())
```

### View in Console

Go to: https://console.firebase.google.com/
1. Select your project
2. Click "Firestore Database"
3. Find `trading_signals` collection
4. View all signals in real-time

---

## 🧹 Cleanup Old Signals

Add to your Cloud Function cron job:

```python
from src.live_trading.signal_publisher import SignalPublisher

# Delete signals older than 30 days
publisher = SignalPublisher()
deleted = publisher.delete_old_signals(days_old=30)
print(f"Deleted {deleted} old signals")
```

Schedule via Cloud Scheduler:
```bash
gcloud scheduler jobs create http cleanup-signals \
    --schedule="0 2 * * *" \
    --uri="https://your-function-url/cleanup" \
    --http-method=POST
```

---

## 📱 React Integration Example

Complete React component:

```javascript
// components/SignalFeed.jsx
import { useState, useEffect } from 'react';
import { collection, query, where, orderBy, onSnapshot } from 'firebase/firestore';
import { db } from '../firebase';

export default function SignalFeed({ epic = 'GOLD' }) {
  const [signals, setSignals] = useState([]);
  const [latestSignal, setLatestSignal] = useState(null);
  
  useEffect(() => {
    const q = query(
      collection(db, 'trading_signals'),
      where('epic', '==', epic),
      orderBy('timestamp', 'desc'),
      limit(20)
    );
    
    const unsubscribe = onSnapshot(q, (snapshot) => {
      const newSignals = [];
      
      snapshot.docChanges().forEach((change) => {
        if (change.type === 'added') {
          const signal = change.doc.data();
          newSignals.push(signal);
          
          // Show notification for new signal
          if (change.type === 'added' && signals.length > 0) {
            showNotification(signal);
          }
        }
      });
      
      if (newSignals.length > 0) {
        setLatestSignal(newSignals[0]);
      }
      
      const allSignals = snapshot.docs.map(doc => doc.data());
      setSignals(allSignals);
    });
    
    return () => unsubscribe();
  }, [epic]);
  
  const showNotification = (signal) => {
    const notification = new Notification('New Trading Signal', {
      body: `${signal.signal} ${signal.epic} @ ${signal.price}`,
      icon: '/logo.png'
    });
  };
  
  return (
    <div className="signal-feed">
      <h2>Live Signals - {epic}</h2>
      
      {latestSignal && (
        <div className={`latest-signal ${latestSignal.signal.toLowerCase()}`}>
          <h3>🔥 Latest: {latestSignal.signal}</h3>
          <p>Price: ${latestSignal.price}</p>
          <p>SL: ${latestSignal.sl} | TP: ${latestSignal.tp}</p>
          <p>Time: {new Date(latestSignal.timestamp).toLocaleString()}</p>
        </div>
      )}
      
      <div className="signal-list">
        {signals.map((signal, i) => (
          <div key={i} className="signal-item">
            <span className={signal.signal}>{signal.signal}</span>
            <span>{signal.price}</span>
            <span>{new Date(signal.timestamp).toLocaleTimeString()}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

---

## 🎯 Summary

**Signal Flow**: Bot → SignalPublisher → Firestore → Your App

**Fastest Method**: Firestore Real-Time Listener (50-200ms)

**Setup**: Already done! Firestore enabled, bot publishes automatically

**Next Steps**:
1. Start bot: `python3 scripts/trading_bot.py`
2. Test consumer: `python3 scripts/signal_consumer.py realtime`
3. Integrate React (copy code above)
4. View signals in Firebase Console

All signals are persistent, queryable, and delivered in real-time!
