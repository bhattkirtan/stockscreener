# Trading Bot Deployment Guide

## Server Information
- **Server**: stockscreener-server
- **IP**: 204.168.191.150
- **Location**: Helsinki (EU-Central)
- **Specs**: CX33 (4 vCPU, 8 GB RAM, 80 GB + 10 GB disk)
- **OS**: Ubuntu Linux 6.8.0
- **Python**: 3.12.3

## Prerequisites

✅ SSH key already created: `~/.ssh/stockscreener_server`
✅ Server is accessible via SSH

## Quick Deployment

### 1. Configure API Credentials

Before deploying, you need your Capital.com API credentials:

1. Visit: https://capital.com/trading/platform/
2. Create a demo account (or use existing)
3. Get your API credentials (API Key, Username, Password)

### 2. Deploy the Bot

```bash
cd /Users/kirtanbhatt/code/stockScreener
chmod +x deploy_bot.sh
./deploy_bot.sh
```

### 3. Configure Environment Variables

After deployment completes, connect to the server and set up your credentials:

```bash
ssh -i ~/.ssh/stockscreener_server root@204.168.191.150
cd /opt/trading-bot
nano .env
```

Add your Capital.com API credentials:

```env
TRADING_MODE=DEMO
CAPITAL_API_KEY=your_api_key_here
CAPITAL_USERNAME=your_username_here
CAPITAL_PASSWORD=your_password_here
INSTRUMENT=GOLD
TIMEFRAME=M5
POSITION_SIZE=0.1
```

Save and exit (Ctrl+X, Y, Enter)

### 4. Start the Bot

```bash
systemctl start trading-bot
systemctl status trading-bot
```

### 5. Monitor the Bot

**Real-time logs:**
```bash
journalctl -u trading-bot -f
# or
tail -f /opt/trading-bot/logs/bot-output.log
```

**Check bot status:**
```bash
systemctl status trading-bot
```

**View log files:**
```bash
ls -lh /opt/trading-bot/logs/
cat /opt/trading-bot/trading_bot.log  # Symlink to latest log
```

## Bot Management Commands

```bash
# Start the bot
systemctl start trading-bot

# Stop the bot
systemctl stop trading-bot

# Restart the bot
systemctl restart trading-bot

# Check status
systemctl status trading-bot

# View logs
journalctl -u trading-bot -f              # Live logs
journalctl -u trading-bot --since "1 hour ago"  # Recent logs
tail -f /opt/trading-bot/logs/bot-output.log    # Output logs
```

## Trading Modes

### DEMO Mode (Recommended for Testing)
- Paper trading only
- No real money at risk
- Fully automated (generates signals AND places trades)
- Set `TRADING_MODE=DEMO` in `.env`

### LIVE Mode (Real Trading)
- Real money trading
- **Signal-only mode**: Logs signals but does NOT place trades automatically
- You must manually review and execute trades
- Set `TRADING_MODE=LIVE` in `.env`
- **⚠️ USE WITH EXTREME CAUTION**

## Bot Strategy

**Gold M5 Strategy** (rank01 from optimization 2026-03-17):
- **Instrument**: GOLD (XAU/USD)
- **Timeframe**: M5 (5 minutes)
- **Indicators**:
  - Supertrend: period=7, multiplier=2.0
  - SMA: Fast=25, Slow=30
  - Bollinger Bands: period=20, std=2.0
- **Risk Management**:
  - Stop Loss: 20 pips
  - Take Profit: 40 pips
  - Max Consecutive Losses: 3
- **Event Blocking**: Enabled (15 min before/after high-impact news)
- **Backtest Performance**: 373.7% return, 14.0% max DD, 0.18 Sharpe

## Architecture

```
┌─────────────────┐
│  Trading Bot    │
│  (Python)       │
│  - Strategy     │
│  - Indicators   │
│  - Risk Mgmt    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Capital.com API │
│  - REST API     │
│  - WebSocket    │
│  - Live Prices  │
└─────────────────┘
```

## File Structure on Server

```
/opt/trading-bot/
├── venv/                    # Python virtual environment
├── scripts/
│   ├── trading_bot.py      # Main bot script (M5)
│   ├── trading_bot_m5.py   # M5 variant
│   └── trading_bot_m15.py  # M15 variant
├── src/
│   ├── live_trading/       # Live trading components
│   │   ├── capital_websocket.py
│   │   ├── capital_rest.py
│   │   ├── order_manager.py
│   │   └── config.py
│   ├── core/               # Strategy core
│   │   ├── strategy.py
│   │   └── event_blocker.py
│   └── data/               # Data utilities
├── logs/                   # Log files
│   ├── trading_bot_*.log
│   ├── bot-output.log
│   └── bot-error.log
├── .env                    # Environment variables (YOU MUST CREATE THIS)
└── requirements.txt        # Python dependencies
```

## Troubleshooting

### Bot won't start
```bash
# Check service status
systemctl status trading-bot

# Check logs for errors
journalctl -u trading-bot -n 50

# Verify Python dependencies
cd /opt/trading-bot
source venv/bin/activate
pip list
```

### API connection issues
```bash
# Test Capital.com API credentials
cd /opt/trading-bot
source venv/bin/activate
python3 -c "from src.live_trading.capital_rest import CapitalRestClient; print('Import OK')"
```

### View error logs
```bash
tail -f /opt/trading-bot/logs/bot-error.log
journalctl -u trading-bot -p err
```

### Restart after config changes
```bash
systemctl restart trading-bot
```

## Security Best Practices

1. **Never commit `.env` file** - It contains sensitive API credentials
2. **Use DEMO mode first** - Test thoroughly before using LIVE mode
3. **Monitor regularly** - Check logs daily
4. **Set position limits** - Use small position sizes initially
5. **Use stop losses** - Always have proper risk management
6. **Secure server access** - Keep SSH keys safe
7. **Update regularly** - Keep bot code and dependencies updated

## Performance Monitoring

### Check CPU and Memory Usage
```bash
# Real-time monitoring
top -p $(pgrep -f trading_bot.py)

# System resources
htop
```

### Database queries (if using Firestore/PostgreSQL)
```bash
# Check signal publisher logs
grep "Signal published" /opt/trading-bot/logs/bot-output.log | tail -20
```

## Updating the Bot

To deploy updates:

```bash
# From your local machine
cd /Users/kirtanbhatt/code/stockScreener
./deploy_bot.sh

# On the server, restart the service
ssh -i ~/.ssh/stockscreener_server root@204.168.191.150
systemctl restart trading-bot
```

## Support

For issues or questions:
- Check logs: `/opt/trading-bot/logs/`
- Review Capital.com API docs: https://open-api.capital.com/
- Check trading bot code: `/opt/trading-bot/scripts/trading_bot.py`

---

**⚠️ DISCLAIMER**: Trading involves significant risk. This bot is for educational purposes. Always use DEMO mode first and never trade with money you can't afford to lose.
