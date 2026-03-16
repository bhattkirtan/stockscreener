# 🚀 Quick Start Guide - Trading Bot

## ✅ What's Ready

1. **Complete Trading Bot** ([trading_bot.py](trading_bot.py))
   - Streams GOLD M5 prices via WebSocket
   - Aggregates M5 → M15 bars automatically
   - Calculates GOLD M15 indicators (Supertrend, SMA, BB, ATR)
   - Generates BUY/SELL signals
   - Places orders automatically (DEMO mode)
   - Signal-only mode (LIVE mode)

2. **Test Script** ([test_trading_bot.py](test_trading_bot.py))
   - Validates authentication
   - Tests WebSocket connection
   - Verifies M5 streaming
   - Tests M5 → M15 aggregation
   - Checks indicator calculations

3. **Documentation** ([README_TRADING_BOT.md](README_TRADING_BOT.md))
   - Complete usage guide
   - Configuration options
   - Testing workflow
   - Monitoring instructions

## 🎯 Quick Start (3 Steps)

### Step 1: Install Dependencies
```bash
cd /Users/kirtanbhatt/code/stockScreener/cloud-function
pip install websockets>=12.0
```

### Step 2: Test Setup
```bash
# Validate everything works
python3 scripts/test_trading_bot.py
```

**Expected output:**
```
✅ PASS: Authentication
✅ PASS: WebSocket Connection
✅ PASS: M5 Streaming
✅ PASS: M5 to M15 Aggregation
✅ PASS: Indicator Calculation
🎉 ALL TESTS PASSED - Ready to run trading bot!
```

### Step 3: Run Paper Trading Bot
```bash
# Set environment (default is 'demo')
export TRADING_ENVIRONMENT=demo

# Run bot
python3 scripts/trading_bot.py
```

**What to expect:**
- Bot connects to Capital.com demo account
- Subscribes to GOLD M5 candles
- Waits for 60+ M15 bars (~15 hours)
- Starts generating signals
- Places orders automatically in demo account

## 📊 Understanding the Output

### Startup
```
🤖 Trading Bot initialized: Epic=GOLD, Mode=AUTO-TRADE
🔐 Authenticating with Capital.com...
✅ Authentication successful
🎯 Subscribed to GOLD M5 candles and live quotes
⚡ Bot running in AUTO-TRADE mode
```

### Building History
```
📊 M5 Candle: 2024-03-09T10:05:00Z O:2055.30 H:2056.10 L:2054.80 C:2055.90
✅ M15 bar created: 2024-03-09 10:15:00 O:2054.50 H:2057.20 L:2053.80 C:2055.90
⏳ Building history: 12/60 bars
```

Wait for: `Building history: 60/60 bars` before signals start

### Signal Generated
```
================================================================================
🟢 BUY SIGNAL DETECTED
   Price: 2055.30
   Supertrend: UPTREND
   SMA Fast: 2050.15
   SMA Slow: 2045.80
   EMA: 2048.90
   ATR: 8.45
   Stop Loss: 2049.39 (0.7× ATR)
   Take Profit: 2076.42 (2.5× ATR)
================================================================================
📤 Placing BUY order: 0.5 contracts @ 2055.30
   SL: 2049.39 | TP: 2076.42
✅ Order placed successfully: ABC123DEF456
```

### Position Management
```
📍 Already in position: BUY 0.5 @ 2055.30
🎯 TAKE PROFIT HIT: 2076.50 >= 2076.42
```

## 🎛️ Bot Modes

### DEMO Mode (Paper Trading - Recommended First)
```bash
export TRADING_ENVIRONMENT=demo
python3 scripts/trading_bot.py
```
- ✅ Fully automated
- ✅ Real-time signals
- ✅ Automatic order placement
- ✅ Uses demo account (fake money)
- ✅ Safe for testing

### LIVE Mode (Signal Only - For Production)
```bash
export TRADING_ENVIRONMENT=live
python3 scripts/trading_bot.py
```
- ✅ Real-time signals
- ❌ NO automatic orders
- ✅ You execute manually
- ✅ Safe (no accidental trades)
- ⚠️ Requires vigilance

## 📈 Expected Performance

Based on 25-month backtest:
- **Return**: 155% total (6.1% per month)
- **Win Rate**: 26.8% (73.2% losers)
- **Profit Factor**: 1.24 (profitable)
- **Trades**: ~24 per month
- **Max Drawdown**: -31.8%

## ⚙️ Configuration Quick Tweaks

### Change Position Size
Edit [trading_bot.py](trading_bot.py), line ~376:
```python
position_size = 0.5  # Change to 1.0, 2.0, 3.0 etc.
```

### Change Instrument
Edit [trading_bot.py](trading_bot.py), line ~28 in main():
```python
bot = TradingBot(config, epic='US100')  # Or 'ETHEREUM', 'EURUSD', etc.
```

### Adjust Stop Loss / Take Profit
Edit [trading_bot.py](trading_bot.py), line ~123-124:
```python
sl_pips=0.7,  # Change to 0.5, 1.0, etc. (× ATR)
tp_pips=2.5,  # Change to 2.0, 3.0, etc. (× ATR)
```

## 📁 File Structure

```
cloud-function/scripts/
├── trading_bot.py              # 🤖 Main bot (600+ lines)
├── test_trading_bot.py         # 🧪 Validation tests
├── README_TRADING_BOT.md       # 📖 Full documentation
└── QUICK_START.md              # ⚡ This file
```

## 🔍 Monitoring

### Real-time Logs
```bash
tail -f trading_bot.log
```

### Search for Signals
```bash
grep "SIGNAL DETECTED" trading_bot.log
```

### Check Orders
```bash
grep "Order placed" trading_bot.log
```

### View Errors
```bash
grep "ERROR\|failed" trading_bot.log -i
```

## ⚠️ Important Reminders

1. **Wait for 60+ bars**: Bot needs history before generating signals (~15 hours)
2. **Monitor first day**: Watch closely during first 5-10 trades
3. **Compare vs backtest**: Check if win rate and trade frequency match
4. **Start small**: 0.5 contracts = $50 margin @ 20× leverage
5. **Test in DEMO first**: Don't go live until validated

## 🚦 Validation Checklist

Before going live:

- [ ] Ran `test_trading_bot.py` successfully
- [ ] Run bot in DEMO mode for 1-2 weeks
- [ ] Collected at least 20-30 trades in demo
- [ ] Win rate close to 26% (±5%)
- [ ] Trade frequency ~24/month (±5)
- [ ] Slippage acceptable (<$1 per trade)
- [ ] No technical issues or crashes
- [ ] Ready for live signal-only mode

## 🎯 Next Steps

1. **Now**: Run `test_trading_bot.py` to validate setup
2. **Today**: Start bot in DEMO mode, let it run
3. **Week 1**: Monitor daily, check ~5-10 trades
4. **Week 2**: Analyze results vs backtest
5. **Week 3**: If good, switch to LIVE signal-only mode
6. **Month 2**: Consider automation in live (requires code change)
7. **Future**: Add Ethereum, US100 to portfolio

## 📞 Troubleshooting

### "Authentication failed"
- Check `.env` file has `apicredentials`
- Verify Capital.com account credentials
- Try logging in via Capital.com website first

### "No candles received"
- May be outside trading hours (GOLD trades 23h/day)
- Wait up to 5 minutes for first candle
- Check if Capital.com demo account is active

### "Not enough history"
- Normal! Bot needs 60 M15 bars = 180 M5 candles
- Wait ~15 hours for full history
- Bot will log progress: "Building history: X/60"

### "Order placement failed"
- Check Capital.com demo account balance
- Verify position size isn't too large
- Check if market is open

## 🎉 You're Ready!

Run this now:
```bash
cd /Users/kirtanbhatt/code/stockScreener/cloud-function
python3 scripts/test_trading_bot.py
```

If all tests pass ✅, start the bot:
```bash
python3 scripts/trading_bot.py
```

Good luck! 🚀📈
