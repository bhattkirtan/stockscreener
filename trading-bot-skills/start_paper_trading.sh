#!/bin/bash

# Run Trading Bot in Paper Trading Mode (Demo)
# This script starts the bot with Capital.com demo account for testing

echo "🚀 Starting Trading Bot in PAPER TRADING mode..."
echo ""
echo "✅ Phase 1 Features Enabled:"
echo "   - Reversal Logic (BUY↔SELL signal reversals)"
echo "   - IntraDayTimeExit (4 hour max holding)"
echo "   - EndOfDayClose (16:00 UTC cutoff)"
echo ""
echo "📊 Configuration:"
echo "   - Instrument: GOLD"
echo "   - Timeframe: M5"
echo "   - Environment: DEMO (Paper Trading)"
echo "   - SL: 20 pips | TP: 40 pips"
echo ""

cd /Users/kirtanbhatt/code/stockScreener/trading-bot-skills

# Load environment variables
export $(cat .env | grep -v '#' | xargs)

# Run bot in demo mode
python3 orchestrator/main.py --mode demo --config config/trading_config.yaml

echo ""
echo "👋 Paper trading session ended"
