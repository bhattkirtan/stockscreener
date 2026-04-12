#!/bin/bash
# Deploy Trading Bot (Skills Architecture) to stockscreener-server
# Server: 204.168.191.150 (Helsinki)
# Usage:
#   bash deploy_skills_bot.sh                    → GOLD, DEMO mode
#   bash deploy_skills_bot.sh demo GOLD          → GOLD, DEMO mode
#   bash deploy_skills_bot.sh live GOLD          → GOLD, LIVE mode
#   bash deploy_skills_bot.sh demo SILVER        → SILVER, DEMO mode
#   bash deploy_skills_bot.sh demo EURUSD        → EURUSD, DEMO mode
#   bash deploy_skills_bot.sh demo BTCUSD        → BTCUSD, DEMO mode
#   bash deploy_skills_bot.sh demo ETHUSD        → ETHUSD, DEMO mode
#   bash deploy_skills_bot.sh demo US100         → US100, DEMO mode
#
# Supported instruments: GOLD, SILVER, EURUSD, BTCUSD, ETHUSD, US100

set -e

MODE="${1:-demo}"
INSTRUMENT="${2:-GOLD}"
INSTRUMENT="${INSTRUMENT^^}"  # uppercase
SERVER_IP="204.168.191.150"
SERVER_USER="root"
SSH_KEY="~/.ssh/stockscreener_server"
REMOTE_DIR="/opt/trading-bot-skills"
SERVICE_NAME="trading-bot-skills"
LOCAL_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/trading-bot-skills" && pwd)"

echo "🚀 Deploying Trading Bot Skills to ${SERVER_IP} (instrument=${INSTRUMENT}, mode=${MODE})..."

# ── Step 1: Stop & disable old trading-bot service ────────────────────────────
echo ""
echo "🛑 Stopping old trading-bot service (cloud-function)..."
ssh -i ${SSH_KEY} ${SERVER_USER}@${SERVER_IP} << 'ENDSSH'
if systemctl is-active --quiet trading-bot 2>/dev/null; then
    systemctl stop trading-bot
    echo "✓ Stopped trading-bot"
fi
if systemctl is-enabled --quiet trading-bot 2>/dev/null; then
    systemctl disable trading-bot
    echo "✓ Disabled trading-bot (will not start on reboot)"
fi
ENDSSH

# ── Step 3: Backup .env and wipe remote dir ───────────────────────────────────
echo ""
echo "🧹 Preparing remote directory..."
ssh -i ${SSH_KEY} ${SERVER_USER}@${SERVER_IP} << ENDSSH
systemctl stop ${SERVICE_NAME} 2>/dev/null || true

if [ -f ${REMOTE_DIR}/.env ]; then
    cp ${REMOTE_DIR}/.env /tmp/trading-bot-skills.env.backup
    echo "✓ Backed up .env"
fi

rm -rf ${REMOTE_DIR}
mkdir -p ${REMOTE_DIR}/logs
mkdir -p ${REMOTE_DIR}/reports

if [ -f /tmp/trading-bot-skills.env.backup ]; then
    cp /tmp/trading-bot-skills.env.backup ${REMOTE_DIR}/.env
    echo "✓ Restored .env"
fi
ENDSSH

# ── Step 4: Rsync source files ────────────────────────────────────────────────
echo ""
echo "📤 Uploading source files..."
rsync -avz --progress \
    -e "ssh -i ${SSH_KEY}" \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.git' \
    --exclude='venv' \
    --exclude='*.log' \
    --exclude='reports/' \
    --exclude='.pytest_cache/' \
    --exclude='tests/' \
    --exclude='docs/' \
    "${LOCAL_SRC}/" \
    ${SERVER_USER}@${SERVER_IP}:${REMOTE_DIR}/

# ── Step 5: System dependencies ───────────────────────────────────────────────
echo ""
echo "📦 Installing system dependencies..."
ssh -i ${SSH_KEY} ${SERVER_USER}@${SERVER_IP} << 'ENDSSH'
apt-get update -qq
apt-get install -y --no-install-recommends python3-pip python3-venv gcc > /dev/null
ENDSSH

# ── Step 6: Python virtual environment ────────────────────────────────────────
echo ""
echo "🐍 Setting up Python environment..."
ssh -i ${SSH_KEY} ${SERVER_USER}@${SERVER_IP} << ENDSSH
cd ${REMOTE_DIR}
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "✓ Python environment ready"
ENDSSH

# ── Step 7: systemd service ───────────────────────────────────────────────────
echo ""
echo "⚙️  Installing systemd service (${SERVICE_NAME})..."
ssh -i ${SSH_KEY} ${SERVER_USER}@${SERVER_IP} "cat > /etc/systemd/system/${SERVICE_NAME}.service" << EOF
[Unit]
Description=Capital.com Trading Bot — ${INSTRUMENT} ${MODE}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${REMOTE_DIR}
Environment="PATH=${REMOTE_DIR}/venv/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=-${REMOTE_DIR}/.env
ExecStart=${REMOTE_DIR}/venv/bin/python3 ${REMOTE_DIR}/orchestrator/main.py \
    --config ${REMOTE_DIR}/config/trading_config.yaml \
    --instrument ${INSTRUMENT} \
    --mode ${MODE}
Restart=always
RestartSec=15
StandardOutput=append:${REMOTE_DIR}/logs/bot-output.log
StandardError=append:${REMOTE_DIR}/logs/bot-error.log

# Resource limits
LimitNOFILE=65536
MemoryMax=1G
CPUQuota=100%

[Install]
WantedBy=multi-user.target
EOF

# ── Step 8: Enable and start ──────────────────────────────────────────────────
echo ""
echo "🔄 Enabling and starting service..."
ssh -i ${SSH_KEY} ${SERVER_USER}@${SERVER_IP} << ENDSSH
systemctl daemon-reload
systemctl enable ${SERVICE_NAME}
systemctl start ${SERVICE_NAME}
sleep 3
systemctl status ${SERVICE_NAME} --no-pager
ENDSSH

echo ""
echo "✅ Deployment complete! (instrument=${INSTRUMENT}, mode=${MODE})"
echo ""
echo "📋 Useful commands (run on server):"
echo "   ssh -i ${SSH_KEY} ${SERVER_USER}@${SERVER_IP}"
echo ""
echo "   # Logs"
echo "   journalctl -u ${SERVICE_NAME} -f"
echo "   tail -f ${REMOTE_DIR}/logs/bot-output.log"
echo ""
echo "   # Control"
echo "   systemctl status  ${SERVICE_NAME}"
echo "   systemctl restart ${SERVICE_NAME}"
echo "   systemctl stop    ${SERVICE_NAME}"
echo ""
echo "   # First-time: set credentials if .env doesn't exist yet"
echo "   nano ${REMOTE_DIR}/.env"
echo ""
echo "   # Switch demo ↔ live (redeploy with mode flag)"
echo "   # From local: bash deploy_skills_bot.sh live"
