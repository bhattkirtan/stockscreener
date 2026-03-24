#!/bin/bash
# ── Install systemd Services ─────────────────────────────────────────────────
# Run after setup_server.sh has been executed and project files have been
# copied to the server.
#
# Usage (run as root or with sudo):
#   sudo bash deploy/install_services.sh [m5|m15|both]
#
# Default: installs both services.
# ---------------------------------------------------------------------------

set -euo pipefail

APP_DIR="/home/botuser/stockScreener/cloud-function"
DEPLOY_DIR="$APP_DIR/deploy"
TARGET="${1:-both}"

install_service() {
    local name="$1"
    local env_file="$APP_DIR/.env.$name"

    if [ ! -f "$env_file" ]; then
        echo "❌ Missing $env_file — fill in credentials before installing the $name service."
        exit 1
    fi

    echo "==> Installing bot-$name.service..."
    cp "$DEPLOY_DIR/bot-$name.service" /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable "bot-$name"
    systemctl restart "bot-$name"
    echo "    ✅ bot-$name started and enabled on boot."
    echo "    View logs: journalctl -u bot-$name -f"
}

case "$TARGET" in
    m5)   install_service m5 ;;
    m15)  install_service m15 ;;
    both) install_service m5; install_service m15 ;;
    *)
        echo "Usage: $0 [m5|m15|both]"
        exit 1
        ;;
esac

echo ""
echo "Quick status check:"
systemctl status "bot-${TARGET:-m5}" --no-pager || true
