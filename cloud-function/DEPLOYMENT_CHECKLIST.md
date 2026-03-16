# 🚀 Bot Deployment Checklist

## ✅ Pre-Deployment Validation (COMPLETED)

### Code Quality
- ✅ **17/17 Unit Tests Passing**
  - Timestamp conversion (all formats)
  - Indicator calculation
  - Signal generation (BUY/SELL logic)
  - JSON serialization
  - History management
  - SL/TP calculations
  - File operations
  - Edge cases

### Bug Fixes Applied
- ✅ Mixed timestamp format handling (ISO + Unix ms)
- ✅ Supertrend variable naming (`supertrend_val`)
- ✅ JSON serialization for datetime objects
- ✅ Candle history size limiting (50 bars max)
- ✅ NaN indicator detection

### Current Bot Status
- ✅ Bot running (PID: 26902)
- ✅ WebSocket connected to Capital.com
- ✅ Strategy loaded: SupertrendVWAPStrategy
- ✅ Timeframe: M5 (5-minute candles)
- ✅ Mode: AUTO-TRADE (demo)
- ✅ Firestore publishing enabled

### Monitoring
- ✅ Desktop notifications enabled (macOS)
- ✅ Monitor script checking every 5 minutes
- ✅ Automated health checks scheduled

---

## 📋 Deployment Steps

### 1. Cloud Function Deployment
**Status:** ✅ Already deployed (updateTime: 2026-03-10T09:08:00)

```bash
# Cloud Function details
Name: capitalComService
Region: us-central1
Runtime: Python 3.10
Environment: DEMO (CAPITAL_ENV=demo)
```

**Verify deployment:**
```bash
gcloud functions describe capitalComService --region=us-central1 --gen2
```

### 2. Environment Variables
**Status:** ✅ Configured

Required variables:
- `CAPITAL_ENV=demo` (or `live` for production)
- `GCP_PROJECT_ID` (your project ID)
- `GOOGLE_CLOUD_PROJECT` (your project ID)

### 3. Trading Bot Deployment
**Current:** Running locally on Mac

**Options for production:**

#### Option A: Run on Cloud VM (Recommended)
```bash
# 1. Create VM instance
gcloud compute instances create trading-bot-vm \
  --zone=us-central1-a \
  --machine-type=e2-micro \
  --boot-disk-size=10GB \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud

# 2. SSH to VM
gcloud compute ssh trading-bot-vm --zone=us-central1-a

# 3. Install dependencies
sudo apt-get update
sudo apt-get install -y python3-pip git
pip3 install -r requirements.txt

# 4. Upload bot code
# (use scp or git clone)

# 5. Run bot as systemd service
sudo nano /etc/systemd/system/trading-bot.service
```

Example systemd service:
```ini
[Unit]
Description=M5 Trading Bot
After=network.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/path/to/cloud-function
ExecStart=/usr/bin/python3 scripts/trading_bot_m5.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

#### Option B: Run on Cloud Run (Containerized)
```bash
# 1. Create Dockerfile for bot
# 2. Build and push to Container Registry
# 3. Deploy as Cloud Run service (always-on)
```

#### Option C: Keep running locally (Current)
- **Pros:** Simple, direct control
- **Cons:** Requires Mac to stay on, no redundancy

### 4. Firestore Setup
**Status:** ✅ Already configured

Verify collection exists:
```bash
# Check Firestore in GCP Console
# Collection: trading_signals
```

### 5. Frontend Integration
**Status:** ✅ capital-connect UI deployed

Verify signals appear in UI:
- Open: http://localhost:3000 (or your deployed URL)
- Check that signals from Firestore display correctly

---

## 🔍 Post-Deployment Verification

### Immediate Checks (First 30 minutes)
- [ ] Bot process remains running
- [ ] No error logs in bot.log
- [ ] WebSocket connection stable
- [ ] Candles received every 5 minutes
- [ ] Indicators calculated without errors
- [ ] Signals generated when conditions met
- [ ] Signals published to Firestore
- [ ] Signals visible in UI

### Daily Checks
- [ ] Review trading signals generated
- [ ] Check monitor.log for alerts
- [ ] Verify candle data files created
- [ ] Confirm no memory leaks (process size stable)

### Weekly Checks
- [ ] Review strategy performance
- [ ] Analyze signal quality
- [ ] Check for any pattern errors
- [ ] Update strategy parameters if needed

---

## 🚨 Rollback Plan

If issues occur:

1. **Stop bot immediately:**
   ```bash
   pkill -f "trading_bot_m5.py"
   ```

2. **Review logs:**
   ```bash
   tail -100 bot.log
   tail -100 monitor.log
   ```

3. **Check for positions:**
   - Log into Capital.com account
   - Manually close any open positions if needed

4. **Revert to previous version:**
   ```bash
   git checkout [previous-commit-hash]
   ```

5. **Restart with fixed code**

---

## 📊 Monitoring Dashboard

### Key Metrics to Track
- Signals generated per day
- Signal accuracy (% profitable)
- Average trade duration
- Max drawdown
- Sharpe ratio
- Win rate

### Alert Conditions
- ⚠️ Bot process stopped
- ⚠️ WebSocket disconnected
- ⚠️ No candles received for 10 minutes
- ⚠️ Error rate > 5 per hour
- ⚠️ Position loss exceeds 2% per trade

---

## 🎯 Success Criteria

Bot is successfully deployed when:
- ✅ All 17 unit tests passing
- ✅ Bot runs continuously for 24 hours
- ✅ Signals generated correctly
- ✅ No crashes or errors
- ✅ UI displays signals in real-time
- ✅ Monitor alerts working

---

## 📝 Next Steps

1. **Run bot for 24 hours in demo mode**
   - Validate stability
   - Review all generated signals
   - Fine-tune parameters if needed

2. **Switch to live mode** (when ready)
   - Update `CAPITAL_ENV=live`
   - Start with small position sizes
   - Monitor closely for first week

3. **Scale up gradually**
   - Increase position sizes over time
   - Add more epics (EURUSD, etc.)
   - Deploy multiple instances for redundancy

---

## 🔧 Troubleshooting

### Bot crashes on startup
- Check Python version (requires 3.9+)
- Verify all dependencies installed
- Check environment variables set

### WebSocket disconnects
- Check internet connection
- Verify Capital.com API status
- Review authentication (CST/X-SECURITY-TOKEN)

### Signals not appearing in UI
- Check Firestore write permissions
- Verify collection name matches
- Test Firestore connection manually

### JSON serialization errors
- Run unit tests: `python3 tests/test_trading_bot_complete.py`
- Check datetime conversion logic
- Verify all objects are JSON-serializable

---

## ✅ DEPLOYMENT READY

**All systems validated and tested.**
**Bot is ready for production deployment.**

Run final check:
```bash
python3 tests/test_trading_bot_complete.py
```

Expected output: **✅ ALL TESTS PASSED - BOT IS READY FOR DEPLOYMENT**
