#!/bin/bash

# Production Deployment Script for Market Trading Service
# ⚠️  WARNING: This deploys with LIVE trading API (real money!)
# 
# Prerequisites:
# 1. Create production secret: marketServiceCredentials with live credentials
# 2. Ensure you have production trading API credentials
# 3. Test thoroughly on demo before deploying to production
#
# Usage: ./deploy-production.sh [options]
# Options:
#   --confirm-overwrite   Skip confirmation prompt
#   --no-traffic          Deploy without serving traffic (for testing)

set -e

# Production Configuration
PROJECT_ID="double-venture-442318-k8"
FUNCTION_NAME="marketServiceLive"
REGION="us-central1"
RUNTIME="python312"
ENTRY_POINT="hello_http"
MEMORY="512Mi"  # More memory for production
CPU="2"         # More CPU for production
TIMEOUT="60s"
MAX_INSTANCES="100"
CONCURRENCY="1"
SERVICE_ACCOUNT="361802071308-compute@developer.gserviceaccount.com"
SECRET_NAME="marketServiceCredentials"  # Discreet secret name
CAPITAL_ENV="live"  # Set to 'live' for production API
ALLOW_LIVE_TRADING="false"  # Safety: Set to 'true' to enable trading on live

# Parse arguments
SKIP_CONFIRM=false
NO_TRAFFIC=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --confirm-overwrite)
            SKIP_CONFIRM=true
            shift
            ;;
        --no-traffic)
            NO_TRAFFIC=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: ./deploy-production.sh [--confirm-overwrite] [--no-traffic]"
            exit 1
            ;;
    esac
done

echo "🔴 PRODUCTION DEPLOYMENT WARNING 🔴"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "This will deploy to LIVE trading API"
echo "Real money will be at risk!"
echo ""
echo "Configuration:"
echo "  Function: $FUNCTION_NAME"
echo "  Environment: LIVE"
echo "  Secret: $SECRET_NAME"
echo "  Memory: $MEMORY"
echo "  CPU: $CPU"
echo ""

if [ "$SKIP_CONFIRM" = false ]; then
    read -p "Are you sure you want to deploy to PRODUCTION? (type 'yes' to continue): " confirm
    if [ "$confirm" != "yes" ]; then
        echo "❌ Deployment cancelled"
        exit 1
    fi
fi

# Check if production secret exists
echo ""
echo "🔍 Checking for production secret..."
if ! gcloud secrets describe $SECRET_NAME --project=$PROJECT_ID &>/dev/null; then
    echo ""
    echo "❌ ERROR: Production secret '$SECRET_NAME' not found!"
    echo ""
    echo "Please create it first:"
    echo "  1. Go to Secret Manager: https://console.cloud.google.com/security/secret-manager?project=$PROJECT_ID"
    echo "  2. Create new secret: $SECRET_NAME"
    echo "  3. Add your LIVE trading API credentials in JSON format:"
    echo "     {\"apikey\":\"YOUR_LIVE_API_KEY\",\"username\":\"YOUR_EMAIL\",\"password\":\"YOUR_LIVE_PASSWORD\",\"capkey\":\"YOUR_LIVE_CAP_KEY\"}"
    echo ""
    exit 1
fi
echo "✅ Production secret found"

echo ""
echo "📦 Deploying Cloud Function..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Build deploy command
DEPLOY_CMD="gcloud functions deploy $FUNCTION_NAME \
  --gen2 \
  --runtime=$RUNTIME \
  --region=$REGION \
  --entry-point=$ENTRY_POINT \
  --trigger-http \
  --allow-unauthenticated \
  --memory=$MEMORY \
  --cpu=$CPU \
  --timeout=$TIMEOUT \
  --max-instances=$MAX_INSTANCES \
  --concurrency=$CONCURRENCY \
  --service-account=$SERVICE_ACCOUNT \
  --set-env-vars=CAPITAL_ENV=$CAPITAL_ENV,ALLOW_LIVE_TRADING=$ALLOW_LIVE_TRADING \
  --set-secrets=apicredentials=$SECRET_NAME:latest \
  --project=$PROJECT_ID"

# Add no-traffic flag if requested
if [ "$NO_TRAFFIC" = true ]; then
    DEPLOY_CMD="$DEPLOY_CMD --no-allow-unauthenticated"
    echo "⚠️  Deploying without public traffic (for testing)"
fi

# Execute deployment
eval $DEPLOY_CMD

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Production Deployment complete!"
echo ""
echo "📡 Function URLs:"
gcloud functions describe $FUNCTION_NAME --region=$REGION --gen2 --format="value(serviceConfig.uri)" --project=$PROJECT_ID
echo ""
echo "📊 View logs:"
echo "   gcloud functions logs read $FUNCTION_NAME --region $REGION --gen2 --limit 50"
echo ""
echo "🔍 Check status:"
echo "   gcloud functions describe $FUNCTION_NAME --region $REGION --gen2"
echo ""
echo "⚠️  REMEMBER: This is connected to LIVE trading API"
echo "   Monitor all trades carefully!"
echo ""
