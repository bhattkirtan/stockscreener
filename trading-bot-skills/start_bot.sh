#!/bin/bash
# Start Trading Bot (Skills Architecture)
# Usage: bash start_bot.sh [demo|live]
#        bash start_bot.sh          → defaults to demo
#        bash start_bot.sh live     → REAL MONEY

set -e

MODE="${1:-demo}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_SCRIPT="$SCRIPT_DIR/orchestrator/main.py"
LOG_FILE="$SCRIPT_DIR/trading_bot.log"
PID_FILE="/tmp/trading_bot_skills.pid"

# ── Load .env (skips JSON values and comments) ────────────────────────────────
if [ -f "$SCRIPT_DIR/.env" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "${line// }" ]] && continue
        [[ "$line" =~ =\{ ]] && continue
        [[ "$line" =~ =\[ ]] && continue
        [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] && export "$line"
    done < "$SCRIPT_DIR/.env"
    echo "✅ Loaded .env"
else
    echo "⚠️  No .env found — relying on environment variables"
fi

# ── Validate credentials ──────────────────────────────────────────────────────
if [ -z "$CAPITAL_API_KEY" ] && [ -z "$apicredentials" ]; then
    echo "❌ Missing credentials. Set CAPITAL_API_KEY (or apicredentials) in .env"
    exit 1
fi

# ── Kill existing instance ────────────────────────────────────────────────────
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "Stopping existing bot (PID: $OLD_PID)..."
        kill -15 "$OLD_PID" 2>/dev/null
        sleep 3
        kill -9 "$OLD_PID" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
fi

# Also catch any stray instances
STRAY=$(pgrep -f "orchestrator/main.py" 2>/dev/null || true)
if [ -n "$STRAY" ]; then
    echo "Killing stray instances: $STRAY"
    kill -9 $STRAY 2>/dev/null || true
    sleep 1
fi

# ── Live mode safety prompt ───────────────────────────────────────────────────
if [ "$MODE" = "live" ]; then
    echo ""
    echo "⚠️  WARNING: LIVE MODE — real money will be traded"
    read -r -p "Type 'yes' to confirm: " CONFIRM
    if [ "$CONFIRM" != "yes" ]; then
        echo "Aborted."
        exit 0
    fi
fi

# ── Start bot ─────────────────────────────────────────────────────────────────
echo ""
echo "Starting trading bot in $MODE mode..."
echo "Log: tail -f $LOG_FILE"
echo ""

python3 "$BOT_SCRIPT" \
    --config "$SCRIPT_DIR/config/trading_config.yaml" \
    --mode "$MODE" \
    >> "$LOG_FILE" 2>&1 &

BOT_PID=$!
echo "$BOT_PID" > "$PID_FILE"
disown $BOT_PID

sleep 3

if ps -p "$BOT_PID" > /dev/null 2>&1; then
    echo "✅ Bot running (PID: $BOT_PID)"
else
    echo "❌ Bot failed to start. Last 20 lines of log:"
    tail -20 "$LOG_FILE"
    exit 1
fi

# ── Start monitor ─────────────────────────────────────────────────────────────
MONITOR_SCRIPT="$SCRIPT_DIR/monitor_bot.sh"
if [ -f "$MONITOR_SCRIPT" ]; then
    STRAY_MON=$(pgrep -f "monitor_bot.sh" 2>/dev/null || true)
    [ -n "$STRAY_MON" ] && kill -9 $STRAY_MON 2>/dev/null || true

    bash "$MONITOR_SCRIPT" >> "$SCRIPT_DIR/monitor.log" 2>&1 &
    MON_PID=$!
    disown $MON_PID
    echo "✅ Monitor running (PID: $MON_PID)"
fi

echo ""
echo "Bot PID : $BOT_PID"
echo "Mode    : $MODE"
echo "Log     : tail -f $LOG_FILE"
echo "Stop    : kill $BOT_PID"
