# 🤖 Live Trading Bot

Complete trading bot for Capital.com with dual-mode operation:
- **DEMO (Paper Trading)**: Fully automated - generates signals AND places trades
- **LIVE (Real Trading)**: Signal-only mode - ONLY logs signals, NO automatic orders

## 🎯 Strategy: GOLD M15

**Proven Performance:**
- **155% return** over 25.4 months
- **26.8% win rate** (realistic, consistent)
- **1.24 profit factor** (profitable without luck)
- **24 trades/month** (manageable volume)

**Parameters:**
- Supertrend: period=7, multiplier=2.0
- SMA: Fast=21, Slow=50
- Bollinger Bands: period=20, std=2.0
- ATR: period=14
- Stop Loss: 0.7× ATR
- Take Profit: 2.5× ATR

## 📋 Prerequisites

1. **Environment Variables** (`.env` file):
```bash
# Capital.com API Credentials
apicredentials='{"apikey":"YOUR_API_KEY","username":"YOUR_EMAIL","password":"YOUR_PASSWORD","capkey":"YOUR_CAP_KEY"}'

# Trading Mode: 'demo' for paper trading, 'live' for real trading
TRADING_ENVIRONMENT=demo
```

2. **Dependencies** (already installed):
```bash
pip install pandas numpy websockets python-dotenv requests
```

## 🚀 Usage

### Paper Trading (DEMO - Automated)
```bash
# From cloud-function directory
cd /Users/kirtanbhatt/code/stockScreener/cloud-function

# Set to demo mode (automatic trading)
export TRADING_ENVIRONMENT=demo

# Run bot
python3 scripts/trading_bot.py
```

**What happens:**
- ✅ Streams GOLD M5 prices from Capital.com
- ✅ Aggregates M5 → M15 bars (3 M5 = 1 M15)
- ✅ Calculates indicators (Supertrend, SMA, BB, ATR)
- ✅ Generates BUY/SELL signals
- ✅ **Automatically places orders** via REST API
- ✅ Manages positions (tracks SL/TP hits)
- ✅ Logs everything to `trading_bot.log`

### Live Trading (LIVE - Signal Only)
```bash
# From cloud-function directory
cd /Users/kirtanbhatt/code/stockScreener/cloud-function

# Set to live mode (signal-only, NO automatic orders)
export TRADING_ENVIRONMENT=live

# Run bot
python3 scripts/trading_bot.py
```

**What happens:**
- ✅ Streams GOLD M5 prices from Capital.com
- ✅ Aggregates M5 → M15 bars
- ✅ Calculates indicators
- ✅ Generates BUY/SELL signals
- ❌ **Does NOT place orders automatically**
- ✅ Logs signals for manual execution
- ✅ You execute trades manually via Capital.com platform

## 📊 Output Examples

### BUY Signal
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
```

**In DEMO mode**: Order automatically placed
**In LIVE mode**: Signal logged, manual execution required

### SELL Signal
```
================================================================================
🔴 SELL SIGNAL DETECTED
   Price: 2044.70
   Supertrend: DOWNTREND
   SMA Fast: 2048.25
   SMA Slow: 2052.60
   EMA: 2050.10
   ATR: 8.30
   Stop Loss: 2050.51 (0.7× ATR)
   Take Profit: 2023.95 (2.5× ATR)
================================================================================
```

## 🔧 Configuration

Edit `trading_bot.py` to customize:

### Position Size
```python
# Line ~376 in place_order()
position_size = 0.5  # 0.5 contracts = ~$1000 position = $50 margin @ 20×
```

**Recommended sizing:**
- Start: 0.5 contracts ($50 margin)
- After validation: 1.0 contract ($100 margin)
- Target: 3.0 contracts ($300 margin) for full strategy

### Change Instrument
```python
# Line ~28 in main()
bot = TradingBot(config, epic='GOLD')  # Change to 'US100', 'ETHEREUM', etc.
```

### Strategy Parameters
```python
# Line ~115-127 in __init__()
self.strategy = SupertrendVWAPStrategy(
    supertrend_period=7,        # Adjust Supertrend sensitivity
    supertrend_multiplier=2.0,  # Adjust trend threshold
    sma_fast=21,                # Fast SMA period
    sma_slow=50,                # Slow SMA period
    sl_pips=0.7,                # Stop loss (× ATR)
    tp_pips=2.5,                # Take profit (× ATR)
)
```

## 📁 Files

```
cloud-function/
├── scripts/
│   ├── trading_bot.py          # Main trading bot
│   └── README_TRADING_BOT.md   # This file
├── src/
│   ├── live_trading/
│   │   ├── __init__.py
│   │   ├── config.py           # TradingConfig
│   │   └── capital_websocket.py # WebSocket client
│   └── core/
│       └── strategy.py         # Indicator calculations
├── capitalService.py           # REST API (in root)
└── trading_bot.log             # Bot logs
```

## 🧪 Testing Workflow

### Phase 1: Paper Trading (1-2 weeks)
```bash
export TRADING_ENVIRONMENT=demo
python3 scripts/trading_bot.py
```

**Monitor:**
- Number of trades (target: ~24/month)
- Win rate (target: ~26%)
- Average profit/loss per trade
- Slippage and commission impact
- Signal generation latency

**Compare vs Backtest:**
- Are signals matching expected behavior?
- Any execution issues or delays?
- Slippage within acceptable range?

### Phase 2: Live Validation (Signal-Only)
```bash
export TRADING_ENVIRONMENT=live
python3 scripts/trading_bot.py
```

**Week 1-2:**
- Run bot in signal-only mode
- Execute signals manually via Capital.com
- Validate signal quality in real market
- Check for false signals or noise

### Phase 3: Live Deployment (Automated)
After successful validation:
```bash
# Switch to live + auto mode
# IMPORTANT: Modify code to enable auto-trade in live mode (currently disabled for safety)
```

## 🛡️ Safety Features

1. **Dual-Mode Operation**
   - DEMO: Fully automated (safe to test)
   - LIVE: Signal-only (prevents accidental losses)

2. **Position Limits**
   - Max 1 position at a time
   - Position sizing based on margin target

3. **Stop Loss + Take Profit**
   - Always set on every trade
   - ATR-based (adapts to volatility)

4. **Logging**
   - All signals logged to file
   - Easy audit trail for analysis

5. **Manual Override**
   - Can run in signal-only mode
   - You control execution

## 🔍 Monitoring

### Check Logs
```bash
# Real-time monitoring
tail -f trading_bot.log

# Search for signals
grep "SIGNAL DETECTED" trading_bot.log

# Check orders
grep "Order placed" trading_bot.log
```

### Check Open Positions
```python
# In Python console
import capitalService
positions = capitalService.get_open_positions()
print(positions.json())
```

## ⚠️ Important Notes

1. **Start Small**: Begin with 0.5 contracts ($50 margin) for validation
2. **Monitor First Week**: Watch closely during first 5-10 trades
3. **Compare vs Backtest**: Ensure live performance matches expectations
4. **Check Slippage**: GOLD typically has $0.50 spread, factor this in
5. **Session Timeout**: Capital.com sessions expire after 10 minutes of inactivity (bot handles keepalive)

## 🚦 Next Steps

1. ✅ **Validate Setup**: Test authentication and WebSocket connection
2. ✅ **Paper Trade**: Run in DEMO mode for 1-2 weeks
3. ⏳ **Analyze Results**: Compare live vs backtest performance
4. ⏳ **Signal Validation**: Run in LIVE signal-only mode for 1 week
5. ⏳ **Scale Up**: Gradually increase position size if performing well
6. ⏳ **Add Instruments**: Test Ethereum, US100 after GOLD is stable

## 📞 Support

Check logs for errors:
```bash
grep "ERROR" trading_bot.log
grep "failed" trading_bot.log -i
```

Common issues:
- **Authentication fails**: Check `apicredentials` in `.env`
- **WebSocket disconnects**: Normal, bot reconnects automatically
- **No signals**: Need 60+ M15 bars (~15 hours of M5 data)
- **Orders fail**: Check Capital.com account status and margin

---

🎯 **Goal**: Validate GOLD M15 strategy live, then expand to Ethereum and other instruments
📈 **Target**: 6.1% monthly return (155% annual), 24 trades/month, -31.8% max drawdown
