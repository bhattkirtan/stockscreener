#!/bin/bash
#
# Deploy Trading Bot API to Google Cloud Functions
#
# This creates HTTP endpoints for:
# - Bot status (running/stopped, statistics)
# - Active positions (with P&L)
# - Trading signals (historical)
#

set -e

PROJECT_ID="double-venture-442318-k8"
REGION="europe-west1"
FUNCTION_NAME="trading-bot-api"

echo "🚀 Deploying Trading Bot API to Google Cloud Functions..."
echo "   Project: $PROJECT_ID"
echo "   Region: $REGION"
echo "   Function: $FUNCTION_NAME"
echo ""

# Deploy the function
gcloud functions deploy $FUNCTION_NAME \
  --gen2 \
  --runtime=python312 \
  --region=$REGION \
  --source=./functions \
  --entry-point=trading_bot_api \
  --trigger-http \
  --allow-unauthenticated \
  --project=$PROJECT_ID \
  --set-env-vars=GOOGLE_CLOUD_PROJECT=$PROJECT_ID \
  --timeout=60s \
  --memory=256MB

echo ""
echo "✅ Trading Bot API deployed successfully!"
echo ""
echo "📡 API Endpoints:"
echo "   Base URL: https://$REGION-$PROJECT_ID.cloudfunctions.net/$FUNCTION_NAME"
echo ""
echo "   Bot Status:"
echo "   curl 'https://$REGION-$PROJECT_ID.cloudfunctions.net/$FUNCTION_NAME/bot/status'"
echo ""
echo "   Active Positions:"
echo "   curl 'https://$REGION-$PROJECT_ID.cloudfunctions.net/$FUNCTION_NAME/bot/positions'"
echo ""
echo "   Recent Signals:"
echo "   curl 'https://$REGION-$PROJECT_ID.cloudfunctions.net/$FUNCTION_NAME/bot/signals?epic=GOLD&limit=10'"
echo ""
