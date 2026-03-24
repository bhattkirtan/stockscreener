#!/bin/bash
#
# Deploy Unified Trading Bot API to Google Cloud Functions
#
# This creates a single HTTP endpoint for:
# ✅ Capital.com trading (positions, markets, prices)
# ✅ Bot monitoring (status, active positions)
# ✅ Trading signals (recent, latest)
# ✅ Bot logs (GCS bucket access)
#

set -e

PROJECT_ID="double-venture-442318-k8"
REGION="us-central1"  # Using us-central1 where other functions are deployed
FUNCTION_NAME="trading-bot-unified-api"

echo "🚀 Deploying Unified Trading Bot API to Google Cloud Functions..."
echo "   Project: $PROJECT_ID"
echo "   Region: $REGION"
echo "   Function: $FUNCTION_NAME"
echo ""
echo "📦 Contents:"
echo "   • Capital.com trading endpoints"
echo "   • Bot status monitoring"
echo "   • Active positions tracker"
echo "   • Trading signals archive"
echo "   • GCS log file access"
echo ""

# Deploy the function
gcloud functions deploy $FUNCTION_NAME \
  --gen2 \
  --runtime=python312 \
  --region=$REGION \
  --source=./functions \
  --entry-point=hello_http \
  --trigger-http \
  --allow-unauthenticated \
  --project=$PROJECT_ID \
  --set-env-vars=GOOGLE_CLOUD_PROJECT=$PROJECT_ID \
  --timeout=60s \
  --memory=512MB

echo ""
echo "✅ Unified Trading Bot API deployed successfully!"
echo ""
echo "📡 Base URL:"
echo "   https://$REGION-$PROJECT_ID.cloudfunctions.net/$FUNCTION_NAME"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📋 AVAILABLE ENDPOINTS:"
echo ""
echo "🤖 Bot Monitoring:"
echo "   GET /bot/status?bot_id=gold_m5_bot"
echo "   GET /bot/positions?status=open&epic=GOLD"
echo "   GET /bot/signals?epic=GOLD&limit=20"
echo ""
echo "📊 Capital.com Trading:"
echo "   GET /get_positions"
echo "   POST /create_position"
echo "   POST /updte_position"
echo "   DELETE /close_position/{dealId}"
echo ""
echo "📈 Market Data:"
echo "   GET /market/{epic}"
echo "   GET /prices/{epic}?resolution=HOUR"
echo "   GET /markets?searchTerm=GOLD"
echo ""
echo "📝 Logs:"
echo "   GET /logs/get?date=YYYY-MM-DD&file=bot-output.log"
echo "   GET /logs/dates"
echo ""
echo "📡 Trading Signals:"
echo "   GET /signals?epic=GOLD&limit=20"
echo "   GET /signals/latest?epic=GOLD"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🧪 Test Commands:"
echo ""
BASE_URL="https://$REGION-$PROJECT_ID.cloudfunctions.net/$FUNCTION_NAME"
echo "# Get API info"
echo "curl '$BASE_URL/'"
echo ""
echo "# Get bot status"
echo "curl '$BASE_URL/bot/status'"
echo ""
echo "# Get active positions"
echo "curl '$BASE_URL/bot/positions?status=open'"
echo ""
echo "# Get recent signals"
echo "curl '$BASE_URL/signals?epic=GOLD&limit=10'"
echo ""
echo "# Get logs"
echo "curl '$BASE_URL/logs/dates'"
echo ""
