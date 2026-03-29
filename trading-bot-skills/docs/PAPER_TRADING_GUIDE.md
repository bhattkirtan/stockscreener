# Paper Trading Quick Start Guide

## ✅ Phase 1 Features Enabled

Your bot is now configured for **paper trading** with all Phase 1 features:

### Critical Risk Management:
1. ✅ **Reversal Logic** - Automatically close opposite positions when signal flips
2. ✅ **IntraDayTimeExit** - Force close positions after 4 hours
3. ✅ **EndOfDayClose** - Close all positions at 4 PM UTC (16:00)

### Test Coverage:
- **28 tests passing** (14 reversal + 14 time-based exits)
- All features match backtester behavior exactly

---

## 🚀 How to Start Paper Trading

### Option 1: Using the Script (Easiest)

```bash
cd /Users/kirtanbhatt/code/stockScreener/trading-bot-skills
./start_paper_trading.sh
```

### Option 2: Manual Start

```bash
cd /Users/kirtanbhatt/code/stockScreener/trading-bot-skills

# Load environment variables
export $(cat .env | grep -v '#' | xargs)

# Run bot in demo mode
python3 orchestrator/main.py --mode demo --config config/trading_config.yaml
```

---

## 📊 What Will Happen

1. **Bot connects** to Capital.com demo account (paper trading)
2. **Monitors** GOLD M5 candles in real-time
3. **Generates signals** using Supertrend + EMA + SMA
4. **Executes trades** on demo account (no real money)
5. **Time-based exits**:
   - Positions > 4 hours → Auto-close
   - At 16:00 UTC → Close all positions
6. **Reversal handling**:
   - BUY position + SELL signal → Close BUY, can enter SELL
   - SELL position + BUY signal → Close SELL, can enter BUY

---

## 📋 Configuration Details

### Time-Based Exits:
```yaml
time_based_exits:
  max_hours: 4              # IntraDayTimeExit
  intraday_enabled: true
  eod_hour: 16              # EndOfDayClose (4 PM UTC)
  eod_enabled: true
```

### Strategy Parameters:
- **Instrument**: GOLD
- **Timeframe**: M5 (5 minutes)
- **Supertrend**: ATR(7) × 2.0
- **EMA**: 21 periods
- **SMA Fast**: 25 periods
- **SMA Slow**: 30 periods
- **Stop Loss**: 20 pips
- **Take Profit**: 40 pips

### Risk Management:
- **Max Positions**: 1 at a time
- **Position Size**: 2% of capital
- **Cooldowns**:
  - SL hit: 15 minutes (bypassed on reversal)
  - TP hit: 5 minutes (bypassed on reversal)
- **Trading Hours**: Monday-Friday, respects market hours

---

## 📈 Monitoring Your Paper Trading

### Check Bot Status:
```bash
# View real-time logs
tail -f logs/bot.log

# Check Firestore for positions
# Visit: https://console.firebase.google.com/project/double-venture-442318-k8/firestore
```

### What to Watch For:

1. **Signal Generation**:
   - `🔔 BUY signal detected` or `🔔 SELL signal detected`
   
2. **Trade Execution**:
   - `✅ Position opened: DEAL_123`
   
3. **Reversal Detection**:
   - `⚠️ Reverse signal detected: Closing BUY position`
   
4. **Time-Based Exits**:
   - `⏰ Intraday time exit: DEAL_123 open 4.2h`
   - `⏰ EOD close triggered: 16:00 UTC`

5. **Position Closure**:
   - `✅ Position closed: DEAL_123 (+$45.20 profit)`

---

## 🛑 How to Stop Paper Trading

Press `Ctrl+C` in the terminal running the bot. The bot will gracefully shut down:
```
^C
⏸️ Shutting down...
✅ Bot stopped successfully
```

---

## 🔍 Validation Checklist

After 1 week of paper trading, verify:

- [ ] Reversal logic executes correctly (BUY↔SELL)
- [ ] Positions close after 4 hours (IntraDayTimeExit)
- [ ] All positions close at 16:00 UTC (EndOfDayClose)
- [ ] No positions held overnight
- [ ] Cooldown bypassed on reversal signals
- [ ] SL/TP execution works as expected
- [ ] Trading hours respected (no weekend trades)
- [ ] Circuit breakers trigger if needed

---

## ⚠️ Important Notes

### This is Paper Trading:
- ✅ Using demo account (NO real money)
- ✅ Safe to test Phase 1 features
- ✅ Validate bot behavior before live trading

### After 1 Week Validation:
- Review paper trading results
- Compare with historical backtests
- Verify all Phase 1 features work correctly
- Decide: Deploy to live OR implement Phase 2 (trailing stops)

### Capital.com Demo Account:
- Demo balance resets periodically
- Demo prices match live market
- Demo execution is simulated (may differ slightly from live)

---

## 🚨 Troubleshooting

### Bot Won't Start:
```bash
# Check .env file exists
cat /Users/kirtanbhatt/code/stockScreener/trading-bot-skills/.env

# Verify credentials
echo $CAPITAL_API_KEY
echo $CAPITAL_ENVIRONMENT
```

### No Trades Executing:
1. Check trading hours (Monday-Friday)
2. Check if signals being generated (look for logs)
3. Verify Capital.com demo account accessible
4. Check cooldown status

### Connection Errors:
```bash
# Test Capital.com API connection
cd /Users/kirtanbhatt/code/stockScreener/trading-bot-skills
python3 test_api_connections.py
```

---

## 📞 Next Steps

1. **Start paper trading** (this week)
2. **Monitor for 1 week** (March 29 - April 5, 2026)
3. **Review results** (compare vs backtest)
4. **Phase 2 planning** (trailing stops + NoEntryBeforeEOD)

---

**Ready to start?**

```bash
cd /Users/kirtanbhatt/code/stockScreener/trading-bot-skills
./start_paper_trading.sh
```

**Good luck with paper trading!** 🚀
