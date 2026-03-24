#!/bin/bash
# Start Trading Bot — ensures single clean instance
# Usage: bash scripts/start_bot.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Load environment variables (skips JSON values and comments)
if [ -f "$PROJECT_DIR/.env" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        [[ "$line" =~ ^[[:space:]]*# ]] && continue   # skip comments
        [[ -z "${line// }" ]] && continue              # skip blank lines
        [[ "$line" =~ =\{ ]] && continue               # skip JSON values
        [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] && export "$line"
    done < "$PROJECT_DIR/.env"
fi

# Kill any existing bot instances
EXISTING=$(ps aux | grep "[t]rading_bot.py" | awk '{print $2}')
if [ -n "$EXISTING" ]; then
    echo "Stopping existing bot (PID: $EXISTING)..."
    kill -9 $EXISTING 2>/dev/null
    sleep 1
fi

# Start bot — new timestamped log file per run
echo "Starting trading bot..."
python3 "$SCRIPT_DIR/trading_bot.py" >> "$PROJECT_DIR/trading_bot.log" 2>&1 &
BOT_PID=$!
disown $BOT_PID

sleep 2

# Confirm bot is up
if ps -p $BOT_PID > /dev/null 2>&1; then
    echo "Bot running (PID: $BOT_PID)"
else
    echo "ERROR: Bot failed to start. Check trading_bot.log"
    tail -20 "$PROJECT_DIR/trading_bot.log"
    exit 1
fi

# Kill any existing monitor and start a fresh one
EXISTING_MON=$(ps aux | grep "[m]onitor_bot.sh" | awk '{print $2}')
if [ -n "$EXISTING_MON" ]; then
    echo "Stopping existing monitor (PID: $EXISTING_MON)..."
    kill -9 $EXISTING_MON 2>/dev/null
    sleep 1
fi

echo "Starting monitor..."
bash "$SCRIPT_DIR/monitor_bot.sh" &
MON_PID=$!
disown $MON_PID

echo ""
echo "Bot PID:     $BOT_PID"
echo "Monitor PID: $MON_PID"
echo "Log:         tail -f $PROJECT_DIR/trading_bot.log"
echo "Stop all:    kill $BOT_PID $MON_PID"
