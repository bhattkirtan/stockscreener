#!/bin/bash
set -e

echo "════════════════════════════════════════════════════════════════════════════"
echo "Step 1/6: Loading configuration..."
echo "════════════════════════════════════════════════════════════════════════════"

# Deploy only optimize-api function
source "$(dirname "$0")/config.sh"

echo ""
echo "✅ Configuration loaded successfully"
echo "   Project: $GCP_PROJECT_ID"
echo "   Region:  $GCP_REGION"
echo ""

echo "════════════════════════════════════════════════════════════════════════════"
echo "Step 2/6: Checking worker URL..."
echo "════════════════════════════════════════════════════════════════════════════"

# Get worker URL (must exist)
WORKER_URL=$(gcloud run services describe optimizer-worker \
  --platform=managed \
  --region="$GCP_REGION" \
  --format="value(status.url)" 2>/dev/null || echo "")

if [ -z "$WORKER_URL" ]; then
  echo "⚠️  Warning: optimizer-worker not found. Using placeholder URL."
  WORKER_URL="https://optimizer-worker-placeholder"
else
  echo "✅ Worker URL found: $WORKER_URL"
fi

echo ""
echo "════════════════════════════════════════════════════════════════════════════"
echo "Step 3/6: Verifying deployment directory..."
echo "════════════════════════════════════════════════════════════════════════════"

# Deploy from parent directory (stockScreener)
cd "$(dirname "$0")/../.."

echo "✅ Deploying from: $(pwd)"
echo ""

echo "════════════════════════════════════════════════════════════════════════════"
echo "Step 4/6: Checking/Uploading data to GCS..."
echo "════════════════════════════════════════════════════════════════════════════"

# Upload external data JSON files to GCS (only if they don't exist)
BUCKET="double-venture-442318-k8-optimization-results"
echo "   Bucket: gs://$BUCKET/external-data/"

if [ -f "cloud-function/data/economic_calendar.json" ]; then
  if gsutil -q stat gs://$BUCKET/external-data/economic_calendar.json 2>/dev/null; then
    echo "   ⏭️  economic_calendar.json already exists in GCS (skipping)"
  else
    echo "   Uploading economic_calendar.json..."
    gsutil cp cloud-function/data/economic_calendar.json gs://$BUCKET/external-data/economic_calendar.json
    echo "   ✅ Calendar uploaded"
  fi
else
  echo "   ⚠️  economic_calendar.json not found locally"
fi

if [ -f "cloud-function/data/news_headlines.json" ]; then
  if gsutil -q stat gs://$BUCKET/external-data/news_headlines.json 2>/dev/null; then
    echo "   ⏭️  news_headlines.json already exists in GCS (skipping)"
  else
    echo "   Uploading news_headlines.json..."
    gsutil cp cloud-function/data/news_headlines.json gs://$BUCKET/external-data/news_headlines.json
    echo "   ✅ News uploaded"
  fi
else
  echo "   ⚠️  news_headlines.json not found locally"
fi

if [ -f "cloud-function/data/macro_regime.json" ]; then
  if gsutil -q stat gs://$BUCKET/external-data/macro_regime.json 2>/dev/null; then
    echo "   ⏭️  macro_regime.json already exists in GCS (skipping)"
  else
    echo "   Uploading macro_regime.json..."
    gsutil cp cloud-function/data/macro_regime.json gs://$BUCKET/external-data/macro_regime.json
    echo "   ✅ Macro regime uploaded"
  fi
else
  echo "   ⚠️  macro_regime.json not found locally"
fi

echo ""
echo "════════════════════════════════════════════════════════════════════════════"
echo "Step 5/6: Deploying Cloud Function..."
echo "════════════════════════════════════════════════════════════════════════════"
echo ""

gcloud functions deploy optimize-api \
  --gen2 \
  --runtime=python311 \
  --region="$GCP_REGION" \
  --source=cloud-function \
  --entry-point=optimize_api \
  --trigger-http \
  --allow-unauthenticated \
  --timeout=60s \
  --memory=512MB \
  --max-instances=10 \
  --set-env-vars="GCP_PROJECT_ID=$GCP_PROJECT_ID,REGION=$GCP_REGION,GCS_BUCKET=double-venture-442318-k8-optimization-results,WORKER_URL=$WORKER_URL" \
  --service-account="$SERVICE_ACCOUNT"

echo ""
echo "✅ Function deployment command executed"
echo ""

echo "════════════════════════════════════════════════════════════════════════════"
echo "Step 6/6: Retrieving API URL..."
echo "════════════════════════════════════════════════════════════════════════════"

# Get API URL
API_URL=$(gcloud functions describe optimize-api \
  --gen2 \
  --region="$GCP_REGION" \
  --format="value(serviceConfig.uri)")

echo ""
echo "✅ API URL retrieved: $API_URL"
echo ""

echo "════════════════════════════════════════════════════════════════════════════"
echo "🎉 DEPLOYMENT COMPLETE"
echo "════════════════════════════════════════════════════════════════════════════"
echo ""
echo "📡 API URL: $API_URL"
echo ""
echo "🧪 Test endpoints:"
echo "   Health:        curl $API_URL/health"
echo "   Calendar:      curl $API_URL/api/v1/calendar"
echo "   News:          curl $API_URL/api/v1/news"
echo "   Macro:         curl $API_URL/api/v1/macro"
echo "   Blocking:      curl $API_URL/api/v1/is-blocked"
echo "   Status:        curl $API_URL/api/v1/status"
echo "   Optimizations: curl $API_URL/"
echo ""
