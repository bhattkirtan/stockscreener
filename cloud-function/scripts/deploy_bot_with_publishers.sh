#!/bin/bash
# 🚀 Deploy Trading Bot with Publishers to Server

set -e

SERVER_IP="204.168.191.150"
SSH_KEY="~/.ssh/stockscreener_server"
BOT_DIR="/opt/trading-bot"

echo "🚀 Deploying Trading Bot with Publishers"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Upload publisher modules
echo "📦 Uploading publisher modules..."
scp -i $SSH_KEY \
    src/live_trading/bot_status_publisher.py \
    src/live_trading/position_publisher.py \
    root@$SERVER_IP:$BOT_DIR/src/live_trading/

# Upload updated bot script
echo "📦 Uploading trading bot..."
scp -i $SSH_KEY \
    scripts/trading_bot.py \
    root@$SERVER_IP:$BOT_DIR/scripts/

# Restart bot service
echo "🔄 Restarting bot service..."
ssh -i $SSH_KEY root@$SERVER_IP "systemctl restart trading-bot && sleep 2 && systemctl status trading-bot --no-pager"

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📊 Check bot status API:"
echo "   curl 'https://capitalcomservice-6ovej2yaoa-uc.a.run.app/bot/status'"
echo ""
echo "📈 Check positions API:"
echo "   curl 'https://capitalcomservice-6ovej2yaoa-uc.a.run.app/bot/positions'"
echo ""
echo "📝 View bot logs:"
echo "   ssh -i $SSH_KEY root@$SERVER_IP 'journalctl -u trading-bot -f'"
