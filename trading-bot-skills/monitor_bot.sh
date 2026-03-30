#!/bin/bash
# Trading Bot Monitor — checks health every 5 minutes
# Usage: bash monitor_bot.sh          (foreground)
#        nohup bash monitor_bot.sh &   (background)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_LOG="$SCRIPT_DIR/trading_bot.log"
CHECK_INTERVAL=300  # 5 minutes

echo "╔════════════════════════════════════════════╗"
echo "║   🔍 Bot Monitor (Every 5 Minutes)        ║"
echo "╚════════════════════════════════════════════╝"
echo "Press Ctrl+C to stop"
echo ""

while true; do
    TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")
    echo ""
    echo "[$TIMESTAMP] Health Check"
    echo "----------------------------------------"

    # 1. Process check
    BOT_PID=$(pgrep -f "orchestrator/main.py" 2>/dev/null || true)
    if [ -n "$BOT_PID" ]; then
        echo "✅ Bot running (PID: $BOT_PID)"
    else
        echo "❌ WARNING: Bot process not found!"
        # Attempt auto-restart
        if [ -f "$SCRIPT_DIR/start_bot.sh" ]; then
            echo "🔄 Auto-restarting bot..."
            bash "$SCRIPT_DIR/start_bot.sh" demo >> "$BOT_LOG" 2>&1
        fi
    fi

    # 2. Recent error check
    if [ -f "$BOT_LOG" ]; then
        ERROR_COUNT=$(tail -50 "$BOT_LOG" | grep -iE "error|exception|traceback" | wc -l | tr -d ' ')
        if [ "$ERROR_COUNT" -gt 0 ]; then
            echo "⚠️  $ERROR_COUNT error(s) in last 50 log lines:"
            tail -50 "$BOT_LOG" | grep -iE "error|exception|traceback" | tail -5
        else
            echo "✅ No errors in recent logs"
            # Show last signal
            LAST=$(tail -30 "$BOT_LOG" | grep -E "Signal|Trade|Candle|🕯️|📊" | tail -1)
            [ -n "$LAST" ] && echo "   Last: $LAST"
        fi
    else
        echo "⚠️  Log file not found: $BOT_LOG"
    fi

    echo ""
    echo "⏰ Next check in 5 minutes..."
    sleep $CHECK_INTERVAL
done
