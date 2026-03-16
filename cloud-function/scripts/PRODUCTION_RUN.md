# 🚀 Running Trading Bot for 2 Weeks (Production Setup)

## Overview
This guide covers multiple approaches to run the trading bot continuously for weeks, with auto-restart on failures and proper monitoring.

---

## 📋 Option 1: Screen/Tmux (Simplest)

### Using Screen (Recommended for Quick Start)

```bash
# 1. Start a named screen session
screen -S trading_bot

# 2. Navigate to project and run bot
cd /Users/kirtanbhatt/code/stockScreener/cloud-function
python3 scripts/trading_bot.py

# 3. Detach from screen (press Ctrl+A, then D)
# Bot continues running in background

# 4. Reattach anytime to check
screen -r trading_bot

# 5. List all screen sessions
screen -ls

# 6. Kill session when done (after 2 weeks)
screen -S trading_bot -X quit
```

**Pros**: 
- ✅ Simple, no installation needed
- ✅ Easy to attach and monitor logs
- ✅ Survives terminal close

**Cons**:
- ❌ Won't survive system reboot
- ❌ No auto-restart on crash

### Using Tmux (Alternative)

```bash
# Install tmux if not present
brew install tmux

# Start session
tmux new -s trading_bot

# Run bot
cd /Users/kirtanbhatt/code/stockScreener/cloud-function
python3 scripts/trading_bot.py

# Detach: Ctrl+B, then D
# Reattach: tmux attach -t trading_bot
```

---

## 📋 Option 2: Nohup (Background Process)

```bash
# Navigate to project
cd /Users/kirtanbhatt/code/stockScreener/cloud-function

# Run with nohup (output to nohup.out)
nohup python3 scripts/trading_bot.py > trading_bot_nohup.log 2>&1 &

# Save process ID
echo $! > /tmp/trading_bot.pid

# Check if running
ps -p $(cat /tmp/trading_bot.pid)

# View logs in real-time
tail -f trading_bot_nohup.log

# Stop bot
kill $(cat /tmp/trading_bot.pid)
```

**Pros**:
- ✅ Runs in background
- ✅ Simple one-liner

**Cons**:
- ❌ No auto-restart on crash
- ❌ Won't survive system reboot

---

## 📋 Option 3: Supervisor (Auto-Restart + Monitoring) ⭐ RECOMMENDED

Supervisor automatically restarts your bot if it crashes and ensures it starts on system boot.

### Installation

```bash
# Install supervisor via pip
pip3 install supervisor

# Or via homebrew
brew install supervisor
```

### Configuration

```bash
# 1. Create supervisor config directory
mkdir -p ~/supervisor

# 2. Create config file
cat > ~/supervisor/trading_bot.conf << 'EOF'
[program:trading_bot]
command=/usr/local/bin/python3 /Users/kirtanbhatt/code/stockScreener/cloud-function/scripts/trading_bot.py
directory=/Users/kirtanbhatt/code/stockScreener/cloud-function
autostart=true
autorestart=true
startretries=10
stderr_logfile=/Users/kirtanbhatt/supervisor/trading_bot.err.log
stdout_logfile=/Users/kirtanbhatt/supervisor/trading_bot.out.log
user=kirtanbhatt
environment=TRADING_ENVIRONMENT="demo"
stopwaitsecs=30

[supervisord]
logfile=/Users/kirtanbhatt/supervisor/supervisord.log
logfile_maxbytes=50MB
logfile_backups=10
loglevel=info
pidfile=/Users/kirtanbhatt/supervisor/supervisord.pid
nodaemon=false
EOF

# 3. Create log directory
mkdir -p ~/supervisor
```

### Running with Supervisor

```bash
# Start supervisord
supervisord -c ~/supervisor/trading_bot.conf

# Check status
supervisorctl -c ~/supervisor/trading_bot.conf status

# View logs
tail -f ~/supervisor/trading_bot.out.log

# Control commands
supervisorctl -c ~/supervisor/trading_bot.conf start trading_bot
supervisorctl -c ~/supervisor/trading_bot.conf stop trading_bot
supervisorctl -c ~/supervisor/trading_bot.conf restart trading_bot

# Stop supervisord completely
supervisorctl -c ~/supervisor/trading_bot.conf shutdown
```

**Pros**:
- ✅ Auto-restart on crash (up to 10 retries)
- ✅ Proper log management with rotation
- ✅ Easy to manage (start/stop/restart)
- ✅ Process monitoring

**Cons**:
- ❌ Requires installation
- ❌ Won't auto-start on Mac reboot (needs LaunchAgent)

---

## 📋 Option 4: macOS LaunchAgent (Survives Reboots) ⭐ PRODUCTION

For production use, create a LaunchAgent that automatically starts on login/reboot.

### Create LaunchAgent

```bash
# 1. Create plist file
cat > ~/Library/LaunchAgents/com.trading.bot.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.trading.bot</string>
    
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>/Users/kirtanbhatt/code/stockScreener/cloud-function/scripts/trading_bot.py</string>
    </array>
    
    <key>WorkingDirectory</key>
    <string>/Users/kirtanbhatt/code/stockScreener/cloud-function</string>
    
    <key>RunAtLoad</key>
    <true/>
    
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
        <key>Crashed</key>
        <true/>
    </dict>
    
    <key>StandardOutPath</key>
    <string>/Users/kirtanbhatt/logs/trading_bot.out.log</string>
    
    <key>StandardErrorPath</key>
    <string>/Users/kirtanbhatt/logs/trading_bot.err.log</string>
    
    <key>EnvironmentVariables</key>
    <dict>
        <key>TRADING_ENVIRONMENT</key>
        <string>demo</string>
    </dict>
</dict>
</plist>
EOF

# 2. Create logs directory
mkdir -p ~/logs

# 3. Load the agent (will auto-start on reboot)
launchctl load ~/Library/LaunchAgents/com.trading.bot.plist

# 4. Start immediately
launchctl start com.trading.bot
```

### Managing LaunchAgent

```bash
# Check if running
launchctl list | grep com.trading.bot

# View logs
tail -f ~/logs/trading_bot.out.log

# Stop
launchctl stop com.trading.bot

# Unload (disable auto-start)
launchctl unload ~/Library/LaunchAgents/com.trading.bot.plist

# Reload after config changes
launchctl unload ~/Library/LaunchAgents/com.trading.bot.plist
launchctl load ~/Library/LaunchAgents/com.trading.bot.plist
```

**Pros**:
- ✅ Auto-starts on Mac reboot
- ✅ Auto-restarts on crash
- ✅ Native macOS integration
- ✅ Runs even when not logged in

**Cons**:
- ❌ More complex setup
- ❌ Harder to debug plist issues

---

## 📋 Option 5: Docker Container

For complete isolation and portability.

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Run bot
CMD ["python3", "scripts/trading_bot.py"]
```

### Run Container

```bash
# Build image
cd /Users/kirtanbhatt/code/stockScreener/cloud-function
docker build -t trading-bot .

# Run with restart policy
docker run -d \
  --name trading_bot \
  --restart unless-stopped \
  -e TRADING_ENVIRONMENT=demo \
  -v $(pwd)/trading_bot.log:/app/trading_bot.log \
  trading-bot

# View logs
docker logs -f trading_bot

# Stop
docker stop trading_bot
```

---

## 🔍 Monitoring & Maintenance

### 1. Log Monitoring Script

Create `scripts/monitor_bot.sh`:

```bash
#!/bin/bash
# Monitor trading bot health

LOG_FILE="/Users/kirtanbhatt/code/stockScreener/cloud-function/trading_bot.log"

echo "📊 Trading Bot Health Check"
echo "============================"
echo ""

# Check if process running (for screen/nohup)
if pgrep -f "trading_bot.py" > /dev/null; then
    echo "✅ Bot Process: RUNNING"
else
    echo "❌ Bot Process: STOPPED"
fi

echo ""
echo "📈 Recent Activity (last 20 lines):"
tail -n 20 "$LOG_FILE"

echo ""
echo "🔔 Recent Signals:"
grep "SIGNAL" "$LOG_FILE" | tail -n 5

echo ""
echo "💼 Recent Orders:"
grep "order" "$LOG_FILE" | tail -n 5

echo ""
echo "⚠️  Recent Errors:"
grep "ERROR" "$LOG_FILE" | tail -n 5
```

Make executable: `chmod +x scripts/monitor_bot.sh`

### 2. Daily Health Check (Cron)

```bash
# Edit crontab
crontab -e

# Add daily health check at 9 AM
0 9 * * * /Users/kirtanbhatt/code/stockScreener/cloud-function/scripts/monitor_bot.sh > /Users/kirtanbhatt/logs/daily_health.log 2>&1
```

### 3. Disk Space Monitor

```bash
# Check log file size
du -h trading_bot.log

# Rotate logs weekly (add to crontab)
0 0 * * 0 mv /Users/kirtanbhatt/code/stockScreener/cloud-function/trading_bot.log /Users/kirtanbhatt/code/stockScreener/cloud-function/trading_bot.log.$(date +\%Y\%m\%d) && touch /Users/kirtanbhatt/code/stockScreener/cloud-function/trading_bot.log
```

---

## ✅ Recommended Setup for 2-Week Test

### Quick Start (Screen)

**Best for**: Immediate testing, you're around to monitor

```bash
screen -S trading_bot
cd /Users/kirtanbhatt/code/stockScreener/cloud-function
python3 scripts/trading_bot.py
# Ctrl+A, D to detach
```

### Production Setup (Supervisor or LaunchAgent)

**Best for**: Unattended 2-week run, want auto-restart

1. **Use Supervisor** if you don't care about system reboots
2. **Use LaunchAgent** if Mac might reboot (updates, etc.)

---

## 🚨 Important Pre-Flight Checks

Before starting 2-week run:

```bash
# 1. Test bot works
python3 scripts/test_trading_bot.py

# 2. Install websockets
pip3 install websockets

# 3. Verify credentials
env | grep apicredentials

# 4. Check disk space (need ~500MB for 2 weeks of logs)
df -h

# 5. Set environment
export TRADING_ENVIRONMENT=demo  # paper trading

# 6. Test 5-minute run first
timeout 300 python3 scripts/trading_bot.py
```

---

## 📊 Expected Resource Usage

- **CPU**: 5-10% (mostly idle, spikes on candle processing)
- **Memory**: 100-200 MB
- **Disk**: ~20 MB/day for logs (400 MB total for 2 weeks)
- **Network**: ~100 KB/hour (WebSocket keepalive + candles)

---

## 🛑 How to Stop After 2 Weeks

### Screen
```bash
screen -r trading_bot
# Press Ctrl+C
```

### Supervisor
```bash
supervisorctl -c ~/supervisor/trading_bot.conf stop trading_bot
supervisorctl -c ~/supervisor/trading_bot.conf shutdown
```

### LaunchAgent
```bash
launchctl stop com.trading.bot
launchctl unload ~/Library/LaunchAgents/com.trading.bot.plist
```

### Docker
```bash
docker stop trading_bot
docker rm trading_bot
```

---

## 🎯 My Recommendation

For your 2-week DEMO paper trading test:

1. **Start with Screen** (simplest)
2. **Upgrade to Supervisor** after confirming it works (2-3 days)
3. **Switch to LaunchAgent** when moving to LIVE (production)

Command sequence:
```bash
cd /Users/kirtanbhatt/code/stockScreener/cloud-function
pip3 install websockets
screen -S trading_bot
python3 scripts/trading_bot.py
# Ctrl+A, D to detach
# Check logs: screen -r trading_bot
```
