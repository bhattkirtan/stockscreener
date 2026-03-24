#!/bin/bash
# Deploy Logs API to Google Cloud Functions

set -e

PROJECT_ID="double-venture-442318-k8"
REGION="europe-west1"
FUNCTION_NAME="trading-bot-logs-api"

echo "🚀 Deploying Trading Bot Logs API..."

# Deploy get_bot_logs function
gcloud functions deploy ${FUNCTION_NAME}-get \
  --gen2 \
  --runtime=python312 \
  --region=${REGION} \
  --source=. \
  --entry-point=get_bot_logs \
  --trigger-http \
  --allow-unauthenticated \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID}" \
  --max-instances=10 \
  --memory=256MB \
  --timeout=60s

# Deploy list_log_dates function
gcloud functions deploy ${FUNCTION_NAME}-list \
  --gen2 \
  --runtime=python312 \
  --region=${REGION} \
  --source=. \
  --entry-point=list_log_dates \
  --trigger-http \
  --allow-unauthenticated \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID}" \
  --max-instances=5 \
  --memory=128MB \
  --timeout=30s

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📋 API Endpoints:"
echo "Get Logs: https://${REGION}-${PROJECT_ID}.cloudfunctions.net/${FUNCTION_NAME}-get"
echo "List Dates: https://${REGION}-${PROJECT_ID}.cloudfunctions.net/${FUNCTION_NAME}-list"
echo ""
echo "📖 Usage Examples:"
echo "# Get today's logs"
echo "curl 'https://${REGION}-${PROJECT_ID}.cloudfunctions.net/${FUNCTION_NAME}-get'"
echo ""
echo "# Get specific date"
echo "curl 'https://${REGION}-${PROJECT_ID}.cloudfunctions.net/${FUNCTION_NAME}-get?date=2026-03-24'"
echo ""
echo "# Get specific file"
echo "curl 'https://${REGION}-${PROJECT_ID}.cloudfunctions.net/${FUNCTION_NAME}-get?date=2026-03-24&file=bot-output.log&lines=500'"
echo ""
echo "# List available dates"
echo "curl 'https://${REGION}-${PROJECT_ID}.cloudfunctions.net/${FUNCTION_NAME}-list'"
