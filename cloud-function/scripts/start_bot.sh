#!/bin/bash
# 🚀 Trading Bot Quick Start Script
# ./start_bot.sh [screen|nohup|direct]

set -e

MODE="${1:-screen}"
PROJECT_DIR="/Users/kirtanbhatt/code/stockScreener/cloud-function"
SCRIPT_NAME="trading_bot.py"
LOG_FILE="trading_bot.log"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║         🤖 Trading Bot Quick Starter             ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════╝${NC}"
echo ""

# Check if already running
if pgrep -f "$SCRIPT_NAME" > /dev/null; then
    PID=$(pgrep -f "$SCRIPT_NAME")
    echo -e "${YELLOW}⚠️  Bot is already running (PID: $PID)${NC}"
    echo ""
    read -p "Stop and restart? (y/n): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Stopping existing bot...${NC}"
        pkill -f "$SCRIPT_NAME"
        sleep 2
    else
        echo -e "${RED}Exiting. Use 'pkill -f trading_bot.py' to stop manually.${NC}"
        exit 1
    fi
fi

# Pre-flight checks
echo -e "${YELLOW}🔍 Pre-flight checks...${NC}"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python3 not found${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Python3: $(python3 --version)${NC}"

# Check dependencies
cd "$PROJECT_DIR"
echo -e "${YELLOW}📦 Checking dependencies...${NC}"

if ! python3 -c "import websockets" 2>/dev/null; then
    echo -e "${YELLOW}⚠️  websockets not found, installing...${NC}"
    pip3 install websockets
fi
echo -e "${GREEN}✅ All dependencies installed${NC}"

# Check credentials
if [ -z "$apicredentials" ]; then
    echo -e "${RED}❌ Environment variable 'apicredentials' not set${NC}"
    echo ""
    echo "Set it with:"
    echo "  export apicredentials='YOUR_API_KEY'"
    exit 1
fi
echo -e "${GREEN}✅ API credentials found${NC}"

# Check environment
ENVIRONMENT="${TRADING_ENVIRONMENT:-demo}"
echo -e "${BLUE}🌍 Environment: ${ENVIRONMENT^^}${NC}"

if [ "$ENVIRONMENT" = "live" ]; then
    echo -e "${RED}⚠️  WARNING: Running in LIVE mode (signal-only)${NC}"
else
    echo -e "${GREEN}✅ Running in DEMO mode (paper trading with auto-trade)${NC}"
fi

echo ""
echo -e "${YELLOW}Starting bot in ${MODE^^} mode...${NC}"
echo ""

# Start based on mode
case $MODE in
    screen)
        # Check if screen is available
        if ! command -v screen &> /dev/null; then
            echo -e "${RED}❌ Screen not found. Install with: brew install screen${NC}"
            exit 1
        fi
        
        # Check if session already exists
        if screen -list | grep -q "trading_bot"; then
            echo -e "${YELLOW}Killing existing screen session...${NC}"
            screen -S trading_bot -X quit 2>/dev/null || true
            sleep 1
        fi
        
        echo -e "${GREEN}🚀 Starting in screen session 'trading_bot'${NC}"
        echo ""
        echo "Commands:"
        echo "  - Detach: Ctrl+A, then D"
        echo "  - Reattach: screen -r trading_bot"
        echo "  - Monitor: ./scripts/monitor_bot.sh"
        echo ""
        
        sleep 2
        screen -dmS trading_bot bash -c "cd $PROJECT_DIR && python3 scripts/$SCRIPT_NAME"
        sleep 1
        
        if pgrep -f "$SCRIPT_NAME" > /dev/null; then
            PID=$(pgrep -f "$SCRIPT_NAME")
            echo -e "${GREEN}✅ Bot started successfully (PID: $PID)${NC}"
            echo ""
            echo "To view logs:"
            echo "  screen -r trading_bot"
            echo "  tail -f $LOG_FILE"
        else
            echo -e "${RED}❌ Failed to start bot${NC}"
            exit 1
        fi
        ;;
        
    nohup)
        echo -e "${GREEN}🚀 Starting with nohup (background process)${NC}"
        echo ""
        
        cd "$PROJECT_DIR"
        nohup python3 scripts/$SCRIPT_NAME > nohup_trading.log 2>&1 &
        
        PID=$!
        echo $PID > /tmp/trading_bot.pid
        sleep 2
        
        if ps -p $PID > /dev/null; then
            echo -e "${GREEN}✅ Bot started successfully (PID: $PID)${NC}"
            echo ""
            echo "To view logs:"
            echo "  tail -f nohup_trading.log"
            echo "  tail -f $LOG_FILE"
            echo ""
            echo "To stop:"
            echo "  kill $PID"
            echo "  # or: kill \$(cat /tmp/trading_bot.pid)"
        else
            echo -e "${RED}❌ Failed to start bot${NC}"
            exit 1
        fi
        ;;
        
    direct)
        echo -e "${GREEN}🚀 Starting directly (foreground)${NC}"
        echo ""
        echo -e "${YELLOW}Press Ctrl+C to stop${NC}"
        echo ""
        sleep 2
        
        cd "$PROJECT_DIR"
        python3 scripts/$SCRIPT_NAME
        ;;
        
    *)
        echo -e "${RED}❌ Unknown mode: $MODE${NC}"
        echo ""
        echo "Usage: $0 [screen|nohup|direct]"
        echo ""
        echo "Modes:"
        echo "  screen  - Run in detached screen session (recommended)"
        echo "  nohup   - Run as background process"
        echo "  direct  - Run in foreground (for testing)"
        exit 1
        ;;
esac

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}🎉 Bot is now running!${NC}"
echo ""
echo "Monitor health:"
echo "  ./scripts/monitor_bot.sh"
echo ""
echo "Check logs:"
echo "  tail -f $LOG_FILE"
echo ""
echo "Stop bot:"
echo "  pkill -f trading_bot.py"
echo ""
