#!/bin/bash

# Update all deployment scripts to work with new directory structure
# This script fixes paths after reorganization

set -e

echo "🔧 Updating deployment scripts for new directory structure..."

cd "$(dirname "$0")"  # Change to scripts directory

# Update all deploy scripts to:
# 1. Source config.sh from current directory
# 2. Use parent directory as source
# 3. Work correctly when run from scripts/ directory

for script in deploy-*.sh; do
    if [ -f "$script" ]; then
        echo "   Updating $script..."
        
        # Fix config.sh source path
        sed -i.bak 's|source scripts/config.sh|source "$(dirname "$0")/config.sh"|g' "$script"
        
        # Fix source path in gcloud commands (change --source=. to --source=..)
        sed -i.bak 's|--source=\.|--source=..|g' "$script"
        
        # Remove backup files
        rm -f "$script.bak"
    fi
done

echo "✅ Deployment scripts updated!"
echo ""
echo "📋 Usage from cloud-function root:"
echo "   ./scripts/deploy-data-updater.sh"
echo "   ./scripts/deploy-scheduler-control.sh"
echo "   ./scripts/deploy-cloud-run.sh"
echo "   ./scripts/deploy-all.sh"
