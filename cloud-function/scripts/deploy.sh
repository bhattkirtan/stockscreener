#!/bin/bash

# Deployment script for Capital.com Trading Cloud Function
# Based on existing deployment: capitalComService
# 
# Usage: ./deploy.sh [options]
# Options:
#   --confirm-overwrite   Skip confirmation prompt
#   --update-traffic      Deploy with gradual traffic migration

set -e

# Configuration from existing deployment
PROJECT_ID="double-venture-442318-k8"
FUNCTION_NAME="capitalComService"
REGION="us-central1"
RUNTIME="python310"
ENTRY_POINT="hello_http"
MEMORY="512Mi"
CPU="1"
TIMEOUT="540s"
MAX_INSTANCES="100"
CONCURRENCY="80"
SERVICE_ACCOUNT="361802071308-compute@developer.gserviceaccount.com"
SECRET_NAME="capitalService"

# Environment variables
CAPITAL_ENV="demo"  # Can be overridden with --env=live

# Parse arguments
SKIP_CONFIRM=false
UPDATE_TRAFFIC=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --confirm-overwrite)
            SKIP_CONFIRM=true
            shift
            ;;
        --update-traffic)
            UPDATE_TRAFFIC=true
            shift
            ;;
        --env=*)
            CAPITAL_ENV="${1#*=}"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: ./deploy.sh [--confirm-overwrite] [--update-traffic] [--env=demo|live]"
            exit 1
            ;;
    esac
done

echo "🚀 Deploying Cloud Function to Google Cloud"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📦 Function: ${FUNCTION_NAME}"
echo "📍 Region: ${REGION}"
echo "🔧 Runtime: ${RUNTIME}"
echo "🎯 Entry Point: ${ENTRY_POINT}"
echo "💾 Memory: ${MEMORY}"
echo "⚡ CPU: ${CPU}"
echo "⏱️  Timeout: ${TIMEOUT}"
echo "📊 Max Instances: ${MAX_INSTANCES}"
echo "🔒 Secret: ${SECRET_NAME}"
echo "🌍 Environment: ${CAPITAL_ENV}"
echo ""

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo "❌ Error: gcloud CLI not found. Please install Google Cloud SDK."
    exit 1
fi

# Set project
echo "🔧 Setting project: ${PROJECT_ID}"
gcloud config set project ${PROJECT_ID}

# Confirm deployment
if [ "$SKIP_CONFIRM" = false ]; then
    read -p "Continue with deployment? This will update the existing function. (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "❌ Deployment cancelled"
        exit 1
    fi
fi

echo ""
echo "📤 Deploying function..."
echo ""

# Deploy using Gen2 with Secret Manager and environment variables
gcloud functions deploy ${FUNCTION_NAME} \
    --gen2 \
    --runtime ${RUNTIME} \
    --trigger-http \
    --entry-point ${ENTRY_POINT} \
    --region ${REGION} \
    --memory ${MEMORY} \
    --cpu ${CPU} \
    --timeout ${TIMEOUT} \
    --max-instances ${MAX_INSTANCES} \
    --concurrency ${CONCURRENCY} \
    --service-account ${SERVICE_ACCOUNT} \
    --set-secrets "apicredentials=${SECRET_NAME}:latest" \
    --set-env-vars "CAPITAL_ENV=${CAPITAL_ENV},GCP_PROJECT_ID=${PROJECT_ID},GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GCS_LOGS_BUCKET=${PROJECT_ID}-trading-logs" \
    --allow-unauthenticated

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📡 Function URLs:"
gcloud functions describe ${FUNCTION_NAME} --region ${REGION} --gen2 --format='value(serviceConfig.uri)'
echo ""
echo "🆕 New Bot Monitoring Endpoints:"
echo "   /bot/status - Bot health & statistics"
echo "   /bot/positions - Active positions with P&L"
echo "   /bot/signals - Trading signals archive"
echo "   /logs/get - Bot logs from GCS"
echo "   /logs/dates - Available log dates"
echo ""
echo "📊 View logs:"
echo "   gcloud functions logs read ${FUNCTION_NAME} --region ${REGION} --gen2 --limit 50"
echo ""
echo "🔍 Check status:"
echo "   gcloud functions describe ${FUNCTION_NAME} --region ${REGION} --gen2"

