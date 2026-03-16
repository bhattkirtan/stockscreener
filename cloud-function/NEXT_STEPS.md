# 🚀 Next Steps: 2-Week Trading Bot Test

Your bot is ready! Here's your path to production.

---

## ✅ What's Already Built

### Trading Bot
- ✅ Live trading bot with Supertrend + VWAP strategy
- ✅ WebSocket connection to Capital.com
- ✅ Auto-publishes BUY/SELL signals to Firestore
- ✅ Graceful shutdown with signal handlers
- ✅ Paper trading mode (SIGNAL_ONLY)

### Signal Flow System
- ✅ SignalPublisher with multi-backend support
- ✅ Firestore database enabled (double-venture-442318-k8)
- ✅ Real-time signal listener (50-200ms latency)
- ✅ React integration examples
- ✅ Complete documentation

### Production Tools
- ✅ 5 deployment options (Screen → LaunchAgent)
- ✅ Health monitoring (monitor_bot.sh)
- ✅ Quick start script (start_bot.sh)
- ✅ Supervisor template for auto-restart

---

## 🎯 Your 2-Week Test Plan

### Phase 1: Start Bot (Day 1 - Hour 1)

```bash
# 1. Authenticate (one-time setup)
gcloud auth application-default login

# 2. Navigate to bot directory
cd ~/code/stockScreener/cloud-function

# 3. Start bot in Screen (detached terminal)
./scripts/start_bot.sh screen

# 4. Verify running
./scripts/monitor_bot.sh
```

**Expected**: Bot starts, connects to Capital.com, begins collecting M15 candles.

---

### Phase 2: First Signal (Day 1 - Hour 15-20)

After ~60 M15 bars (15 hours), bot will generate first signal.

**Watch for signal**:
```bash
# Monitor in real-time
tail -f logs/trading_bot.log | grep "🔥 SIGNAL"

# Or check recent signals
python3 scripts/signal_consumer.py realtime GOLD
```

**Expected signal format**:
```json
{
  "epic": "GOLD",
  "signal": "BUY",
  "price": 1950.25,
  "sl": 1935.00,
  "tp": 1980.00,
  "timestamp": "2024-01-15T10:30:00",
  "strategy": "SupertrendVWAP",
  "indicators": {
    "supertrend": 1945.50,
    "vwap": 1948.75,
    "atr": 15.25
  }
}
```

**Test Firestore**:
```bash
# Verify signal in Firestore
python3 scripts/test_signal_flow.py
```

---

### Phase 3: React Integration (Day 1-2)

Add signal listener to your capital-connect app:

**File**: `capital-connect/src/hooks/useSignals.ts`

```typescript
import { useEffect, useState } from 'react';
import { collection, query, orderBy, limit, onSnapshot } from 'firebase/firestore';
import { db } from '@/lib/firebase'; // Configure this

interface Signal {
  epic: string;
  signal: 'BUY' | 'SELL';
  price: number;
  sl: number;
  tp: number;
  timestamp: string;
  strategy: string;
}

export function useSignals(epic?: string, maxSignals = 10) {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let q = query(
      collection(db, 'trading_signals'),
      orderBy('timestamp', 'desc'),
      limit(maxSignals)
    );

    // Real-time listener (50-200ms latency)
    const unsubscribe = onSnapshot(
      q,
      (snapshot) => {
        const newSignals = snapshot.docs.map(doc => ({
          id: doc.id,
          ...doc.data()
        })) as Signal[];
        
        setSignals(newSignals);
        setLoading(false);
        
        // Show notification for new signals
        if (snapshot.docChanges().some(change => change.type === 'added')) {
          const latestSignal = newSignals[0];
          new Notification(`${latestSignal.signal} ${latestSignal.epic}`, {
            body: `Entry: ${latestSignal.price} | SL: ${latestSignal.sl} | TP: ${latestSignal.tp}`
          });
        }
      },
      (err) => {
        setError(err);
        setLoading(false);
      }
    );

    return () => unsubscribe();
  }, [epic, maxSignals]);

  return { signals, loading, error };
}
```

**Use in component**:
```tsx
import { useSignals } from '@/hooks/useSignals';

export function SignalFeed() {
  const { signals, loading, error } = useSignals('GOLD', 20);

  if (loading) return <div>Loading signals...</div>;
  if (error) return <div>Error: {error.message}</div>;

  return (
    <div className="space-y-2">
      {signals.map(signal => (
        <div key={signal.id} className={signal.signal === 'BUY' ? 'bg-green-50' : 'bg-red-50'}>
          <div className="font-bold">{signal.signal} {signal.epic}</div>
          <div>Entry: {signal.price} | SL: {signal.sl} | TP: {signal.tp}</div>
          <div className="text-sm text-gray-500">{new Date(signal.timestamp).toLocaleString()}</div>
        </div>
      ))}
    </div>
  );
}
```

**Firebase Config** (get from Firebase Console):
```typescript
// lib/firebase.ts
import { initializeApp } from 'firebase/app';
import { getFirestore } from 'firebase/firestore';

const firebaseConfig = {
  projectId: "double-venture-442318-k8",
  apiKey: "YOUR_API_KEY", // Get from Firebase Console
  authDomain: "double-venture-442318-k8.firebaseapp.com",
  // ... other config
};

const app = initializeApp(firebaseConfig);
export const db = getFirestore(app);
```

Get config: https://console.firebase.google.com/project/double-venture-442318-k8/settings/general

---

### Phase 4: Daily Monitoring (Day 1-14)

**Morning check** (9 AM):
```bash
# Quick health check
./scripts/monitor_bot.sh

# View recent signals
tail -20 logs/trading_bot.log | grep "🔥 SIGNAL"
```

**Expected output**:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   📊 TRADING BOT HEALTH MONITOR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[✅] Process Status
   PID: 12345
   Status: Running
   Uptime: 5 days, 12:34:56
   CPU: 2.5%
   Memory: 125 MB

[✅] Signal Activity
   BUY signals (24h): 3
   SELL signals (24h): 2
   Last signal: 2024-01-15 14:30:00 (2 hours ago)

[✅] Overall Health Score: 95/100
```

**Weekly check** (Day 7):
```bash
# Check signal statistics
python3 -c "
from src.live_trading.signal_publisher import SignalPublisher
pub = SignalPublisher()
signals = pub.get_recent_signals(limit=100)
print(f'Total signals (7 days): {len(signals)}')
print(f'BUY: {sum(1 for s in signals if s[\"signal\"] == \"BUY\")}')
print(f'SELL: {sum(1 for s in signals if s[\"signal\"] == \"SELL\")}')
"

# Check disk space
df -h .

# View log size
ls -lh logs/trading_bot.log
```

---

### Phase 5: Auto-Restart Setup (Optional - Day 2-3)

If you want bot to survive Mac reboots:

**Option A: LaunchAgent** (survives reboots)
```bash
# See PRODUCTION_RUN.md for full setup
cp scripts/supervisor_template.conf ~/Library/LaunchAgents/com.tradingbot.plist

# Edit plist with your paths
# Load agent
launchctl load ~/Library/LaunchAgents/com.tradingbot.plist
```

**Option B: Supervisor** (auto-restart on crash)
```bash
# Install Supervisor
brew install supervisor

# Copy template
sudo cp scripts/supervisor_template.conf /usr/local/etc/supervisor.d/trading_bot.conf

# Edit with your paths
# Start supervisor
brew services start supervisor
supervisorctl start trading_bot
```

---

## 📊 What to Track During 2 Weeks

### Success Metrics

| Metric | Target | How to Check |
|--------|--------|--------------|
| **Uptime** | >99% (14 days) | `./scripts/monitor_bot.sh` |
| **Signal Latency** | 50-200ms | Check React app notification timing |
| **Signal Count** | 20-50 signals | `pub.get_recent_signals(limit=100)` |
| **Firestore Cost** | $0 (free tier) | [Firebase Console](https://console.firebase.google.com/project/double-venture-442318-k8/usage) |
| **Memory Usage** | <500 MB | `ps aux | grep trading_bot` |
| **Log Size** | <100 MB | `ls -lh logs/trading_bot.log` |

### Red Flags

- ⚠️ Bot stopped (no PID)
- ⚠️ No signals for >24 hours
- ⚠️ Memory usage >1 GB
- ⚠️ Log size >500 MB
- ⚠️ Disk space <10 GB
- ⚠️ WebSocket disconnected for >5 minutes

**Fix**:
```bash
# Restart bot
screen -S trading_bot -X quit  # Stop screen session
./scripts/start_bot.sh screen   # Restart

# Clean old logs
find logs/ -name "*.log" -mtime +7 -delete

# Check Firestore quota
gcloud firestore operations list --project=double-venture-442318-k8
```

---

## 🎓 Documentation Reference

All guides in `cloud-function/scripts/`:

| Guide | Purpose |
|-------|---------|
| **AUTH_SETUP.md** | GCP authentication (one-time setup) |
| **PRODUCTION_RUN.md** | 5 deployment options with pros/cons |
| **SIGNAL_FLOW.md** | Complete architecture and React integration |
| **SIGNAL_QUICK_REFERENCE.md** | TL;DR version of signal flow |
| **start_bot.sh** | Quick start script with pre-flight checks |
| **monitor_bot.sh** | Health check and monitoring |

---

## 🚨 Common Issues

### Bot crashes immediately
```bash
# Check logs
tail -50 logs/trading_bot.log

# Common causes:
# - Missing API credentials (capitalService.py)
# - Wrong Python version (need 3.9+)
# - Missing dependencies (websockets)

# Fix:
pip3 install -r requirements.txt
```

### No signals generated
**Why**: Bot needs 60 M15 candles before first signal (~15 hours)

**Check**:
```bash
grep "current candle count" logs/trading_bot.log | tail -1
# Should show: "current candle count: 45/60" (increasing)
```

**If stuck at low count**: Check WebSocket connection
```bash
grep "WebSocket" logs/trading_bot.log | tail -5
```

### Signals not appearing in React app
**Check Firestore**:
```bash
python3 -c "
from src.live_trading.signal_publisher import SignalPublisher
pub = SignalPublisher()
signals = pub.get_recent_signals(limit=5)
print(f'Found {len(signals)} signals')
for sig in signals:
    print(f'{sig[\"timestamp\"]} - {sig[\"signal\"]} {sig[\"epic\"]}')
"
```

**If empty**: Bot might not have generated signals yet (wait for 60 bars)

**If has signals but React app doesn't see**: Check Firebase config in React app

---

## 🎯 After 2 Weeks

### Success Checklist
- [ ] Bot ran continuously for 14 days
- [ ] Generated 30+ signals
- [ ] React app received all signals in <200ms
- [ ] No crashes or manual restarts needed
- [ ] Firestore costs $0 (free tier)

### Next Steps

**If successful**:
1. Add more epics (Ethereum: `ETHEREUM`, Bitcoin: `BITCOIN`)
2. Enable AUTO trading mode (change `auto_trade=True` in tracking_bot.py)
3. Set up LaunchAgent for permanent deployment
4. Add stop-loss/take-profit execution logic
5. Implement position tracking

**If needs improvement**:
1. Tune strategy parameters (supertrend_multiplier, etc.)
2. Add more indicators (RSI, MACD, etc.)
3. Implement risk management (max drawdown, position sizing)
4. Add backtesting validation

---

## 🆘 Emergency Commands

### Stop bot immediately
```bash
# Find PID
ps aux | grep trading_bot.py

# Kill gracefully
kill -SIGINT <PID>

# Or detach from Screen and kill
screen -r trading_bot
# Then Ctrl+C
```

### View live logs
```bash
tail -f logs/trading_bot.log
```

### Check Firestore signals
```bash
# Recent signals
python3 scripts/signal_consumer.py realtime GOLD

# Or test flow
python3 scripts/test_signal_flow.py
```

### Restart everything
```bash
# Stop
screen -S trading_bot -X quit

# Clean
rm logs/trading_bot.log

# Start fresh
./scripts/start_bot.sh screen
```

---

## 📞 Support

- **Signal Flow**: Read `scripts/SIGNAL_FLOW.md`
- **Authentication**: Read `scripts/AUTH_SETUP.md`
- **Production Deploy**: Read `scripts/PRODUCTION_RUN.md`
- **Quick Reference**: Read `scripts/SIGNAL_QUICK_REFERENCE.md`
- **Firestore Console**: https://console.firebase.google.com/project/double-venture-442318-k8/firestore
- **Firebase Config**: https://console.firebase.google.com/project/double-venture-442318-k8/settings/general

---

## ▶️ Quick Start Summary

```bash
# 1. Authenticate (one-time)
gcloud auth application-default login

# 2. Start bot
cd ~/code/stockScreener/cloud-function
./scripts/start_bot.sh screen

# 3. Monitor
./scripts/monitor_bot.sh

# 4. Add React hook (see Phase 3 above)

# That's it! Signals will flow automatically when bot generates them.
```

**Bot is ready for your 2-week test! 🚀**

**First signal expected in ~15 hours (after 60 M15 bars collected)**
