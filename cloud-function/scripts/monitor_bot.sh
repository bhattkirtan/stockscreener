#!/bin/bash
# 📊 Trading Bot Continuous Monitor - Runs every 5 minutes
# Usage: ./monitor_bot.sh (runs in foreground) or nohup ./monitor_bot.sh &

# Resolve project root relative to this script, regardless of CWD
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Configuration — trading_bot.log is a symlink to the current run's log in logs/
BOT_LOG="$PROJECT_DIR/trading_bot.log"
SCRIPT_NAME="trading_bot.py"
CHECK_INTERVAL=300  # 5 minutes in seconds

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     🔍 Bot Monitor (Checking Every 5 Minutes)     ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════╝${NC}"
echo ""
echo "Press Ctrl+C to stop monitoring"
echo "----------------------------------------"

while true; do
    TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")
    echo ""
    echo -e "${BLUE}[$TIMESTAMP] Health Check${NC}"
    echo "----------------------------------------"
    
    # 1. Check if process is running
    if ps aux | grep -q "[t]rading_bot.py"; then
        BOT_PID=$(ps aux | grep "[t]rading_bot.py" | awk '{print $2}')
        echo -e "${GREEN}✅ Bot is running (PID: $BOT_PID)${NC}"
    else
        echo -e "${RED}❌ WARNING: Bot process not found!${NC}"
        echo -e "${RED}🚨 ALERT: Trading bot is NOT running!${NC}"
        # Send desktop notification
        osascript -e 'display notification "Trading bot process has stopped!" with title "🚨 Bot Alert" sound name "Basso"'
    fi
    
    # 2. Check for errors in recent logs
    if [ -f "$BOT_LOG" ]; then
        ERROR_COUNT=$(tail -50 "$BOT_LOG" | grep -iE "error|exception|failed|traceback" | wc -l | tr -d ' ')
        
        if [ "$ERROR_COUNT" -gt 0 ]; then
            echo -e "${YELLOW}⚠️  Found $ERROR_COUNT error(s) in last 50 log lines:${NC}"
            echo "----------------------------------------"
            tail -50 "$BOT_LOG" | grep -iE "error|exception|failed|traceback|warning"
            echo "----------------------------------------"
            # Send desktop notification for errors
            osascript -e "display notification \"Found $ERROR_COUNT error(s) in bot logs\" with title \"⚠️ Bot Errors Detected\" sound name \"Funk\""
        else
            echo -e "${GREEN}✅ No errors found in recent logs${NC}"
            
            # Show last candle received
            LAST_CANDLE=$(tail -20 "$BOT_LOG" | grep -E "📊|🎯 Signal|✅ Signal published" | tail -1)
            if [ ! -z "$LAST_CANDLE" ]; then
                echo -e "${BLUE}📊 Latest: $LAST_CANDLE${NC}"
            fi
        fi
    else
        echo -e "${RED}❌ WARNING: bot.log file not found!${NC}"
    fi
    
    echo ""
    echo -e "⏰ ${YELLOW}Next check in 5 minutes...${NC}"
    sleep $CHECK_INTERVAL
done
