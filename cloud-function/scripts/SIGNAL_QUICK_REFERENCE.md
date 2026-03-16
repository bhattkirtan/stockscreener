# 🚀 Signal Flow Quick Reference

## TL;DR

Your trading bot now publishes signals to **Firestore** automatically. Your main app can consume them with **50-200ms latency** using real-time listeners.

---

## 📋 Quick Start

### 1. Start Bot (Publishes Signals)

```bash
cd cloud-function
./scripts/start_bot.sh screen
```

Bot will publish every BUY/SELL signal to Firestore collection: `trading_signals`

### 2. Consume Signals (Python)

Terminal 2:
```bash
python3 scripts/signal_consumer.py realtime
```

Output:
```
📡 NEW SIGNAL RECEIVED
   Epic: GOLD
   Direction: BUY
   Price: 1950.25
   Stop Loss: 1935.00
   Take Profit: 1980.00
```

### 3. Consume Signals (React Frontend)

Add to your capital-connect app:

```javascript
import { collection, query, where, onSnapshot } from 'firebase/firestore';
import { db } from './firebase';

function SignalListener({ epic }) {
  useEffect(() => {
    const q = query(
      collection(db, 'trading_signals'),
      where('epic', '==', epic)
    );
    
    const unsubscribe = onSnapshot(q, (snapshot) => {
      snapshot.docChanges().forEach((change) => {
        if (change.type === 'added') {
          const signal = change.doc.data();
          console.log('🔔 Signal:', signal);
          // Update UI here
        }
      });
    });
    
    return () => unsubscribe();
  }, [epic]);
}
```

---

## ⚡ Speed Comparison

| Method | Latency | Setup |
|--------|---------|-------|
| **Firestore Listener** ⭐ | 50-200ms | Already done ✅ |
| Firestore Polling | 1-5s | Easy |
| HTTP API | 5-30s | Medium |
| Pub/Sub | 10-50ms | Requires setup |

**Recommendation**: Use Firestore Listener (fastest option that's already set up)

---

## 📊 Signal Structure

```json
{
  "epic": "GOLD",
  "signal": "BUY",
  "price": 1950.25,
  "sl": 1935.0,
  "tp": 1980.0,
  "timestamp": "2026-03-09T14:30:25",
  "mode": "AUTO",
  "indicators": {
    "supertrend_direction": 1,
    "sma_fast": 1948.0,
    "sma_slow": 1940.0,
    "atr": 15.0
  }
}
```

---

## 🧪 Test Signal Flow

```bash
# Terminal 1: Start bot
cd cloud-function
python3 scripts/trading_bot.py

# Terminal 2: Listen for signals
python3 scripts/signal_consumer.py realtime

# Wait for signal (may take ~15 hours to build 60 M15 bars)
# Or test with manual signal:
python3 -c "
from src.live_trading.signal_publisher import SignalPublisher, SignalBackend
p = SignalPublisher(backends=[SignalBackend.FIRESTORE])
p.publish_signal({'epic': 'GOLD', 'signal': 'BUY', 'price': 1950.25})
"
```

---

## 📱 Frontend Integration

### Option A: React Hook

```javascript
// hooks/useSignals.js
export function useSignals(epic) {
  const [signals, setSignals] = useState([]);
  
  useEffect(() => {
    const q = query(
      collection(db, 'trading_signals'),
      where('epic', '==', epic),
      orderBy('timestamp', 'desc')
    );
    
    return onSnapshot(q, (snapshot) => {
      const newSignals = snapshot.docs.map(doc => doc.data());
      setSignals(newSignals);
    });
  }, [epic]);
  
  return signals;
}

// Usage in component
function Dashboard() {
  const signals = useSignals('GOLD');
  
  return (
    <div>
      {signals.map((s, i) => (
        <div key={i}>{s.signal} @ {s.price}</div>
      ))}
    </div>
  );
}
```

### Option B: HTTP API

Add to cloud-function/functions/main.py:

```python
@app.get('/api/signals')
def get_signals(request):
    from google.cloud import firestore
    db = firestore.Client()
    
    epic = request.args.get('epic', 'GOLD')
    limit = int(request.args.get('limit', 10))
    
    query = db.collection('trading_signals')\
              .where('epic', '==', epic)\
              .order_by('timestamp', direction='DESCENDING')\
              .limit(limit)
    
    signals = [doc.to_dict() for doc in query.stream()]
    return {'signals': signals}
```

Fetch from React:
```javascript
const response = await fetch('/api/signals?epic=GOLD&limit=20');
const { signals } = await response.json();
```

---

## 🔍 View Signals in Console

Firebase Console: https://console.firebase.google.com/
1. Select project
2. Firestore Database
3. Collection: `trading_signals`
4. See all signals in real-time

---

## 🧹 Cleanup Old Signals

```python
from src.live_trading.signal_publisher import SignalPublisher

publisher = SignalPublisher()
deleted = publisher.delete_old_signals(days_old=30)
print(f"Deleted {deleted} signals")
```

---

## 📊 Monitor

```bash
# Check bot logs
tail -f cloud-function/trading_bot.log | grep "SIGNAL"

# Health check
./scripts/monitor_bot.sh

# View signals
python3 scripts/signal_consumer.py realtime
```

---

## 💡 Modes

**AUTO Mode (DEMO)**:
- Bot detects signal
- Publishes to Firestore ✅
- Places order automatically ✅

**SIGNAL_ONLY Mode (LIVE)**:
- Bot detects signal
- Publishes to Firestore ✅
- NO automatic order ❌ (you execute manually)

---

## ✅ What's Already Set Up

- ✅ Firestore enabled
- ✅ `trading_signals` collection auto-created
- ✅ SignalPublisher integrated in bot
- ✅ Signals published automatically
- ✅ Python consumer examples ready
- ✅ React integration code provided

---

## 🎯 Next Steps

1. **Start bot**: `./scripts/start_bot.sh screen`
2. **Test consumer**: `python3 scripts/signal_consumer.py realtime`
3. **Integrate React**: Copy code from above or see SIGNAL_FLOW.md
4. **Monitor**: `./scripts/monitor_bot.sh`

---

## 📚 Full Documentation

- **Architecture & Speed**: [SIGNAL_FLOW.md](SIGNAL_FLOW.md)
- **Consumer Examples**: [signal_consumer.py](signal_consumer.py)
- **Production Setup**: [PRODUCTION_RUN.md](PRODUCTION_RUN.md)
- **Testing**: [test_trading_bot.py](test_trading_bot.py)

---

## 🚨 Troubleshooting

**No signals appearing?**
- Bot needs 60+ M15 bars (~15 hours) before generating first signal
- Check logs: `tail -f trading_bot.log | grep "bars"`
- Test with manual signal (see Test section above)

**Firestore permission denied?**
- Run: `gcloud auth application-default login`
- Check: `gcloud firestore databases list`

**Consumer not receiving signals?**
- Verify Firestore enabled: Firebase Console
- Check project ID matches
- Look for signals in console (link above)

---

## 📞 Architecture Summary

```
Bot → publish_signal() → Firestore → Real-time Listener → Your App (50-200ms)
```

That's it! Signals flow from bot to your app in real-time with zero additional setup needed.
