#!/bin/bash
# Quick setup script to configure environment on the server

SERVER_IP="204.168.191.150"
SERVER_USER="root"
SSH_KEY="~/.ssh/stockscreener_server"

echo "🔧 Configuring environment on server..."

# Create .env file on server
ssh -i ${SSH_KEY} ${SERVER_USER}@${SERVER_IP} 'cat > /tmp/setup_env.sh' << 'SETUPSCRIPT'
#!/bin/bash
cd /opt/trading-bot

# Create .env file
cat > .env << 'ENVFILE'
# Capital.com API Credentials
TRADING_MODE=DEMO

# Replace these with your actual Capital.com credentials
CAPITAL_API_KEY=your_api_key_here
CAPITAL_USERNAME=your_username_here
CAPITAL_PASSWORD=your_password_here

# Trading Configuration
INSTRUMENT=GOLD
TIMEFRAME=M5
POSITION_SIZE=0.1
MAX_CONSECUTIVE_LOSSES=3

# Event Blocking
EVENT_BLOCKING_ENABLED=true
EVENT_BLOCK_BEFORE_MINUTES=15
EVENT_BLOCK_AFTER_MINUTES=15

# Signal Publisher Backend (none, firestore, postgres)
SIGNAL_BACKEND=none

# Logging
LOG_LEVEL=INFO
ENVFILE

echo "✅ Created .env file at /opt/trading-bot/.env"
echo ""
echo "⚠️  IMPORTANT: Edit this file and add your Capital.com API credentials!"
echo ""
echo "Run: nano /opt/trading-bot/.env"
SETUPSCRIPT

# Execute setup script on server
ssh -i ${SSH_KEY} ${SERVER_USER}@${SERVER_IP} 'bash /tmp/setup_env.sh && rm /tmp/setup_env.sh'

echo ""
echo "✅ Environment setup complete!"
