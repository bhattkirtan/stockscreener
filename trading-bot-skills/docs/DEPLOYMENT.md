# Deployment Guide

Complete guide for deploying the skill-based trading bot to production.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Environment Setup](#environment-setup)
3. [Configuration](#configuration)
4. [Testing Process](#testing-process)
5. [Deployment Options](#deployment-options)
6. [Production Checklist](#production-checklist)
7. [Monitoring & Maintenance](#monitoring--maintenance)
8. [Rollback Procedures](#rollback-procedures)

---

## Prerequisites

### Required Accounts & Credentials

- ✅ Capital.com account (Demo & Live)
- ✅ Google Cloud Project with Firestore
- ✅ Telegram Bot token
- ✅ Production server (VPS/Cloud)

### Software Requirements

```bash
# Python 3.8+
python3 --version

# Required packages
pip install -r requirements.txt

# System packages
sudo apt-get update
sudo apt-get install -y python3-pip git tmux
```

---

## Environment Setup

### 1. Server Preparation

```bash
# Connect to server
ssh root@your-server-ip

# Create application directory
mkdir -p /opt/trading-bot-skills
cd /opt/trading-bot-skills

# Clone repository
git clone <your-repo-url> .

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Environment Variables

Create `/opt/trading-bot-skills/.env`:

```bash
# Capital.com API
export CAPITAL_USERNAME="your_email@example.com"
export CAPITAL_PASSWORD="your_password"
export CAPITAL_API_KEY="your_api_key"
export CAPITAL_ENVIRONMENT="demo"  # or 'live'

# Firestore
export FIRESTORE_PROJECT_ID="your-gcp-project-id"
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/serviceaccount.json"

# Telegram
export TELEGRAM_BOT_TOKEN="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
export TELEGRAM_CHAT_ID="123456789"

# Bot Settings
export BOT_MODE="live"  # 'live' or 'paper'
export LOG_LEVEL="INFO"
```

Load environment:
```bash
source .env
```

---

## Configuration

### 1. Create Production Config

Copy example config:
```bash
cp config/trading_config_example.yaml config/trading_config.yaml
```

Edit `config/trading_config.yaml`:

```yaml
# PRODUCTION CONFIGURATION
mode: live
bot_name: SkillBasedTradingBot
version: 1.0.0
timezone: UTC
mock_mode: false  # ⚠️ IMPORTANT: Set to false for production

capital_com:
  username: ${CAPITAL_USERNAME}  # From env var
  password: ${CAPITAL_PASSWORD}
  api_key: ${CAPITAL_API_KEY}
  environment: live  # ⚠️ Use 'demo' first, then 'live'
  epic: GOLD
  position_size: 0.5
  sl_pips: 10
  tp_pips: 30

firestore:
  project_id: ${FIRESTORE_PROJECT_ID}
  credentials_path: ${GOOGLE_APPLICATION_CREDENTIALS}
  collections:
    positions: production_positions
    signals: production_signals
    trade_history: production_trade_history
    bot_status: production_bot_status

telegram:
  enabled: true
  token: ${TELEGRAM_BOT_TOKEN}
  chat_id: ${TELEGRAM_CHAT_ID}
  trade_opened: true
  trade_closed: true
  sl_hit: true
  tp_hit: true
  error: true

risk:
  sl_cooldown:
    enabled: true
    duration_minutes: 15
  tp_cooldown:
    enabled: true
    duration_minutes: 5
  position_sizing:
    max_position_size: 1.0
    default_size: 0.5
  max_daily_loss: 100
  max_drawdown: 200
```

### 2. Service Account Setup

```bash
# Upload Google Cloud service account JSON
scp serviceaccount.json root@your-server:/opt/trading-bot-skills/config/

# Set permissions
chmod 600 /opt/trading-bot-skills/config/serviceaccount.json
```

---

## Testing Process

### Stage 1: Mock Mode Testing (Local)

```bash
# Set mock mode
echo "mock_mode: true" >> config/trading_config.yaml

# Run tests
pytest tests/unit/ -v
pytest tests/integration/ -v

# Test API connections (mock)
python3 test_api_connections.py
# Choose 'n' when prompted
```

### Stage 2: Demo Account Testing (Server)

```bash
# Connect to server
ssh root@your-server

# Set demo environment
export CAPITAL_ENVIRONMENT="demo"

# Update config
sed -i 's/mock_mode: true/mock_mode: false/' config/trading_config.yaml
sed -i 's/environment: live/environment: demo/' config/trading_config.yaml

# Test real APIs (demo account)
python3 test_api_connections.py
# Choose 'y' when prompted

# Run bot in demo mode (1 hour)
timeout 3600 python3 main.py

# Check logs
tail -f logs/bot.log
```

### Stage 3: Live Account Testing (Paper Trading)

```bash
# Run with small position size
# Edit config: position_size: 0.1  (minimum)

# Run for 24 hours
nohup python3 main.py &

# Monitor closely
tail -f logs/bot.log

# Check Telegram alerts
# Verify Firestore positions
```

---

## Deployment Options

### Option 1: Systemd Service (Recommended)

Create `/etc/systemd/system/trading-bot.service`:

```ini
[Unit]
Description=Skill-Based Trading Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/trading-bot-skills
Environment="PATH=/opt/trading-bot-skills/venv/bin"
EnvironmentFile=/opt/trading-bot-skills/.env
ExecStart=/opt/trading-bot-skills/venv/bin/python3 main.py
Restart=always
RestartSec=10
StandardOutput=append:/opt/trading-bot-skills/logs/bot.log
StandardError=append:/opt/trading-bot-skills/logs/bot_error.log

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable trading-bot
sudo systemctl start trading-bot

# Check status
sudo systemctl status trading-bot

# View logs
sudo journalctl -u trading-bot -f
```

### Option 2: Tmux Session

```bash
# Start tmux session
tmux new -s trading-bot

# Activate environment
source venv/bin/activate
source .env

# Run bot
python3 main.py

# Detach: Ctrl+B, then D
# Reattach: tmux attach -t trading-bot
```

### Option 3: Docker Container

Create `Dockerfile`:

```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python3", "main.py"]
```

Build and run:
```bash
docker build -t trading-bot:latest .
docker run -d --name trading-bot \
  --env-file .env \
  -v $(pwd)/config:/app/config \
  -v $(pwd)/logs:/app/logs \
  --restart unless-stopped \
  trading-bot:latest
```

---

## Production Checklist

### Pre-Deployment

- [ ] All unit tests passing (82/82)
- [ ] Integration tests passing
- [ ] Backtest validation within 1% of baseline
- [ ] Demo account tested for 48 hours
- [ ] All API credentials validated
- [ ] Firestore collections created
- [ ] Telegram alerts working
- [ ] Logging configured
- [ ] Monitoring dashboard ready

### Configuration Validation

- [ ] `mock_mode: false`
- [ ] `environment: live` (Capital.com)
- [ ] Correct Firestore collections
- [ ] Cooldown settings: SL=15min, TP=5min
- [ ] Position size appropriate
- [ ] Max daily loss set
- [ ] Max drawdown set
- [ ] Telegram enabled

### Deployment

- [ ] Code pushed to production branch
- [ ] Environment variables set
- [ ] Service configured
- [ ] Bot started successfully
- [ ] First candle processed
- [ ] First signal generated (if conditions met)
- [ ] Position opened successfully
- [ ] Firestore write confirmed
- [ ] Telegram alert received

### Post-Deployment

- [ ] Monitor for 1 hour (no errors)
- [ ] Monitor for 24 hours (normal operation)
- [ ] Check cooldown enforcement
- [ ] Verify SL/TP execution
- [ ] Confirm Firestore persistence
- [ ] Review daily P&L
- [ ] Compare with monolithic bot (if running parallel)

---

## Monitoring & Maintenance

### Real-Time Monitoring

```bash
# Live logs
tail -f logs/bot.log

# Filter errors
grep ERROR logs/bot.log

# Count trades today
grep "Trade opened" logs/bot.log | grep $(date +%Y-%m-%d) | wc -l

# Check process
ps aux | grep python3 | grep main.py
```

### Health Checks

Create `health_check.sh`:

```bash
#!/bin/bash

# Check if bot is running
if ! pgrep -f "python3 main.py" > /dev/null; then
    echo "❌ Bot not running"
    # Send alert
    curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
      -d "chat_id=$TELEGRAM_CHAT_ID" \
      -d "text=⚠️ Trading bot process died on $(hostname)"
    
    # Restart
    systemctl restart trading-bot
fi

# Check last log entry
LAST_LOG=$(tail -1 logs/bot.log | awk '{print $1, $2}')
LAST_LOG_TIME=$(date -d "$LAST_LOG" +%s 2>/dev/null || echo 0)
CURRENT_TIME=$(date +%s)
TIME_DIFF=$((CURRENT_TIME - LAST_LOG_TIME))

if [ $TIME_DIFF -gt 600 ]; then
    echo "⚠️ No logs in 10 minutes"
fi
```

Add to crontab:
```bash
crontab -e
*/5 * * * * /opt/trading-bot-skills/health_check.sh
```

### Daily Maintenance

```bash
# Rotate logs (keep 30 days)
find logs/ -name "*.log" -mtime +30 -delete

# Backup Firestore data
gcloud firestore export gs://your-bucket/backups/$(date +%Y%m%d)

# Check disk space
df -h

# Update dependencies (weekly)
pip install --upgrade -r requirements.txt
```

---

## Rollback Procedures

### Emergency Shutdown

```bash
# Stop bot immediately
sudo systemctl stop trading-bot

# Or kill process
pkill -f "python3 main.py"

# Close all open positions manually via Capital.com dashboard
```

### Rollback to Monolithic Bot

```bash
# Stop skill-based bot
sudo systemctl stop trading-bot

# Switch to monolithic bot directory
cd /opt/trading-bot-monolithic

# Start old bot
sudo systemctl start trading-bot-old

# Verify old bot running
tail -f /opt/trading-bot-monolithic/logs/bot.log
```

### Rollback to Previous Version

```bash
# Stop bot
sudo systemctl stop trading-bot

# Switch git branch
cd /opt/trading-bot-skills
git fetch
git checkout previous-stable-tag  # e.g., v0.9.0

# Restart
sudo systemctl start trading-bot
```

---

## Troubleshooting

### Bot Won't Start

```bash
# Check logs
tail -50 logs/bot_error.log

# Verify environment
source .env
python3 -c "import os; print(os.getenv('CAPITAL_USERNAME'))"

# Test imports
python3 -c "from skills.market_data.market_data_skill import MarketDataSkill"

# Check permissions
ls -la config/serviceaccount.json
```

### Capital.com Connection Failed

```bash
# Test API manually
python3 test_api_connections.py

# Check credentials
python3 -c "from clients.capital_api import CapitalAPIClient; \
  client = CapitalAPIClient(); \
  print(client.create_session())"

# Verify environment (demo vs live)
echo $CAPITAL_ENVIRONMENT
```

### Firestore Write Failed

```bash
# Test Firestore connection
python3 -c "from clients.firestore_api import FirestoreAPIClient; \
  client = FirestoreAPIClient(); \
  print(client.save_position('test', 'TEST123', {}))"

# Check service account permissions
gcloud projects get-iam-policy $FIRESTORE_PROJECT_ID

# Verify credentials path
echo $GOOGLE_APPLICATION_CREDENTIALS
ls -la $GOOGLE_APPLICATION_CREDENTIALS
```

### Telegram Alerts Not Sending

```bash
# Test Telegram API
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getMe"

# Send test message
python3 -c "from clients.telegram_api import TelegramAPIClient; \
  client = TelegramAPIClient(); \
  client.send_message('Test from deployment')"

# Check chat_id
echo $TELEGRAM_CHAT_ID
```

---

## Support & Contact

- **Documentation**: `/docs` directory
- **Logs**: `/logs` directory
- **Config**: `/config` directory
- **Backups**: Daily Firestore exports

---

## Version History

- **v1.0.0** (2026-03-25): Initial production deployment with all APIs wired
- **v0.9.0** (2026-03-24): Skill extraction complete, testing phase
- **v0.8.0** (2026-03-20): Risk skill cooldown fixes deployed

---

**🎉 Deployment Complete!**

The skill-based trading bot is now running in production.
Monitor closely for the first 48 hours and review daily performance.
