#!/bin/bash
# Quick Start Script for Trading Bot

cd ~/code/stockScreener/cloud-function

echo "🚀 Starting GOLD M5 Trading Bot..."
echo "📍 Directory: $(pwd)"
echo "🔑 Checking .env..."

if [ ! -f .env ]; then
    echo "❌ No .env file found!"
    exit 1
fi

echo "✅ .env found"
echo ""
echo "▶️  Starting bot (press Ctrl+C to stop)..."
echo ""

python3 scripts/trading_bot_m5.py
