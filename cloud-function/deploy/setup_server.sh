#!/bin/bash
# ── Server Setup Script ──────────────────────────────────────────────────────
# Run once on a fresh Linux server to install dependencies and create the
# bot user. Tested on Ubuntu 22.04 / Debian 12.
#
# Usage:
#   sudo bash deploy/setup_server.sh
# ---------------------------------------------------------------------------

set -euo pipefail

BOT_USER="botuser"
BOT_HOME="/home/$BOT_USER"
APP_DIR="$BOT_HOME/stockScreener/cloud-function"

echo "==> Installing system packages..."
apt-get update -qq
apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3-pip git curl

echo "==> Creating bot user '$BOT_USER'..."
if ! id "$BOT_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$BOT_USER"
    echo "    User created."
else
    echo "    User already exists, skipping."
fi

echo "==> Creating virtualenv..."
sudo -u "$BOT_USER" python3.11 -m venv "$BOT_HOME/venv"

echo "==> Installing Python dependencies..."
sudo -u "$BOT_USER" "$BOT_HOME/venv/bin/pip" install --upgrade pip -q
sudo -u "$BOT_USER" "$BOT_HOME/venv/bin/pip" install --no-cache-dir \
    requests \
    websockets \
    python-dotenv \
    numpy \
    pandas \
    google-cloud-firestore \
    google-auth \
    cachetools \
    -q

echo ""
echo "✅ Setup complete."
echo ""
echo "Next steps:"
echo "  1. Copy project files to $APP_DIR"
echo "     rsync -av --exclude=__pycache__ --exclude='*.pyc' --exclude=results/ \\"
echo "       cloud-function/ $BOT_USER@<server-ip>:$APP_DIR"
echo ""
echo "  2. Fill in credentials:"
echo "     nano $APP_DIR/.env.m5"
echo "     nano $APP_DIR/.env.m15"
echo ""
echo "  3. Install and start services:"
echo "     sudo bash $APP_DIR/deploy/install_services.sh"
