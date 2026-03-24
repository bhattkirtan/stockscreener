#!/bin/bash
# Trading Bot Deployment Script for stockscreener-server
# Server: 204.168.191.150 (Helsinki)

set -e  # Exit on error

SERVER_IP="204.168.191.150"
SERVER_USER="root"
SSH_KEY="~/.ssh/stockscreener_server"
REMOTE_DIR="/opt/trading-bot"
SERVICE_NAME="trading-bot"

echo "🚀 Deploying Trading Bot to ${SERVER_IP}..."

# Step 1: Clean up and create remote directory
echo "🧹 Cleaning up destination..."
ssh -i ${SSH_KEY} ${SERVER_USER}@${SERVER_IP} << 'ENDSSH'
# Stop service if running
systemctl stop trading-bot 2>/dev/null || true

# Backup .env file if it exists
if [ -f /opt/trading-bot/.env ]; then
    cp /opt/trading-bot/.env /tmp/trading-bot.env.backup
    echo "✓ Backed up .env file"
fi

# Clean up old installation
rm -rf /opt/trading-bot
mkdir -p /opt/trading-bot

# Restore .env file
if [ -f /tmp/trading-bot.env.backup ]; then
    cp /tmp/trading-bot.env.backup /opt/trading-bot/.env
    echo "✓ Restored .env file"
fi
ENDSSH

# Step 2: Copy project files
echo "📤 Copying project files..."
rsync -avz --progress \
    -e "ssh -i ${SSH_KEY}" \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.git' \
    --exclude='node_modules' \
    --exclude='venv' \
    --exclude='*.log' \
    --exclude='*.md' \
    --exclude='archive/' \
    --exclude='tests/' \
    --exclude='docs/' \
    --exclude='results/' \
    --exclude='examples/' \
    --exclude='.pytest_cache/' \
    --exclude='docker/' \
    --exclude='deploy/' \
    --exclude='static/' \
    --exclude='cloud-function/' \
    --exclude='logs/*' \
    --exclude='data/optimization/' \
    --exclude='data/*.csv' \
    cloud-function/ \
    ${SERVER_USER}@${SERVER_IP}:${REMOTE_DIR}/

# Step 3: Install system dependencies
echo "📦 Installing system dependencies..."
ssh -i ${SSH_KEY} ${SERVER_USER}@${SERVER_IP} << 'ENDSSH'
apt-get update
apt-get install -y python3-pip python3-venv git
ENDSSH

# Step 4: Create virtual environment and install Python dependencies
echo "🐍 Setting up Python environment..."
ssh -i ${SSH_KEY} ${SERVER_USER}@${SERVER_IP} << 'ENDSSH'
cd /opt/trading-bot
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
ENDSSH

# Step 5: Create systemd service
echo "⚙️  Creating systemd service..."
ssh -i ${SSH_KEY} ${SERVER_USER}@${SERVER_IP} 'cat > /etc/systemd/system/trading-bot.service' << 'EOF'
[Unit]
Description=Capital.com Trading Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/trading-bot
Environment="PATH=/opt/trading-bot/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/opt/trading-bot/venv/bin/python3 /opt/trading-bot/scripts/trading_bot.py
Restart=always
RestartSec=10
StandardOutput=append:/opt/trading-bot/logs/bot-output.log
StandardError=append:/opt/trading-bot/logs/bot-error.log

# Resource limits
LimitNOFILE=65536
MemoryMax=2G
CPUQuota=150%

[Install]
WantedBy=multi-user.target
EOF

# Step 6: Create logs directory
echo "📝 Creating logs directory..."
ssh -i ${SSH_KEY} ${SERVER_USER}@${SERVER_IP} "mkdir -p ${REMOTE_DIR}/logs"

# Step 7: Set up log uploader systemd service and timer
echo "📤 Setting up automatic log uploads..."
ssh -i ${SSH_KEY} ${SERVER_USER}@${SERVER_IP} 'cat > /etc/systemd/system/log-uploader.service' << 'EOF'
[Unit]
Description=Upload Trading Bot Logs to GCS
After=network.target

[Service]
Type=oneshot
User=root
WorkingDirectory=/opt/trading-bot
Environment="PATH=/opt/trading-bot/venv/bin:/usr/local/bin:/usr/bin:/bin"
Environment="GOOGLE_APPLICATION_CREDENTIALS=/opt/trading-bot/.gcp/trading-bot-sa.json"
ExecStart=/opt/trading-bot/venv/bin/python3 /opt/trading-bot/scripts/upload_logs.py
StandardOutput=journal
StandardError=journal
EOF

ssh -i ${SSH_KEY} ${SERVER_USER}@${SERVER_IP} 'cat > /etc/systemd/system/log-uploader.timer' << 'EOF'
[Unit]
Description=Upload Trading Bot Logs Every 15 Minutes
Requires=log-uploader.service

[Timer]
OnBootSec=5min
OnUnitActiveSec=15min
Persistent=true

[Install]
WantedBy=timers.target
EOF

# Step 8: Reload systemd and enable services
echo "🔄 Enabling services..."
ssh -i ${SSH_KEY} ${SERVER_USER}@${SERVER_IP} << 'ENDSSH'
systemctl daemon-reload
systemctl enable trading-bot.service
systemctl enable log-uploader.timer
systemctl start log-uploader.timer
ENDSSH

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📋 Next steps:"
echo "1. Configure environment variables:"
echo "   ssh -i ${SSH_KEY} ${SERVER_USER}@${SERVER_IP}"
echo "   nano ${REMOTE_DIR}/.env"
echo ""
echo "2. Start the bot:"
echo "   systemctl start trading-bot"
echo ""
echo "3. Check status:"
echo "   systemctl status trading-bot"
echo ""
echo "4. View logs:"
echo "   journalctl -u trading-bot -f"
echo "   tail -f ${REMOTE_DIR}/logs/bot-output.log"
echo ""
echo "5. Manage service:"
echo "   systemctl stop trading-bot     # Stop"
echo "   systemctl restart trading-bot  # Restart"
echo "   systemctl status trading-bot   # Status"
