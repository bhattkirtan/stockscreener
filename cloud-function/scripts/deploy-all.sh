#!/bin/bash
set -e

# ══════════════════════════════════════════════════════════════════════════════
# Deploy Complete Optimization System
# ══════════════════════════════════════════════════════════════════════════════

source "$(dirname "$0")/config.sh"

echo ""
echo "══════════════════════════════════════════════════════════════════════════"
echo "🚀 Deploying Complete Optimization System"
echo "══════════════════════════════════════════════════════════════════════════"
echo ""
echo "   Project: $GCP_PROJECT_ID"
echo "   Region:  $GCP_REGION"
echo "   Bucket:  $GCS_BUCKET"
echo ""

# ── Step 1: Deploy Worker (Handles optimizations) ────────────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1️⃣  Deploying Optimizer Worker (Cloud Run)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Build and deploy worker
gcloud run deploy optimizer-worker \
  --source=.. \
  --platform=managed \
  --region="$GCP_REGION" \
  --memory=4Gi \
  --cpu=4 \
  --timeout=3600 \
  --max-instances=3 \
  --min-instances=0 \
  --allow-unauthenticated \
  --set-env-vars="GCP_PROJECT_ID=$GCP_PROJECT_ID,BUCKET_NAME=$GCS_BUCKET" \
  --service-account="$SERVICE_ACCOUNT"

echo ""
echo "✅ Worker deployed"
echo ""

# Get worker URL
WORKER_URL=$(gcloud run services describe optimizer-worker \
  --platform=managed \
  --region="$GCP_REGION" \
  --format="value(status.url)")

echo "   Worker URL: $WORKER_URL"
echo ""

# ── Step 2: Deploy API (Receives UI requests) ─────────────────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "2️⃣  Deploying API Function (Cloud Functions Gen2)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

gcloud functions deploy optimize-api \
  --gen2 \
  --runtime=python311 \
  --region="$GCP_REGION" \
  --source=.. \
  --entry-point=optimize_api \
  --trigger-http \
  --allow-unauthenticated \
  --timeout=60s \
  --memory=512MB \
  --max-instances=10 \
  --set-env-vars="GCP_PROJECT_ID=$GCP_PROJECT_ID,REGION=$GCP_REGION,QUEUE_NAME=optimization-queue,WORKER_URL=$WORKER_URL,BUCKET_NAME=$GCS_BUCKET" \
  --service-account="$SERVICE_ACCOUNT"

echo ""
echo "✅ API deployed"
echo ""

# Get API URL
API_URL=$(gcloud functions describe optimize-api \
  --gen2 \
  --region="$GCP_REGION" \
  --format="value(serviceConfig.uri)")

echo "   API URL: $API_URL"
echo ""

# ── Step 3: Deploy Data Updater (Keeps CSV files fresh) ──────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "3️⃣  Deploying Data Updater + Scheduler"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Deploy data updater function
gcloud functions deploy data-updater \
  --gen2 \
  --runtime=python311 \
  --region="$GCP_REGION" \
  --source=.. \
  --entry-point=update_market_data \
  --trigger-http \
  --no-allow-unauthenticated \
  --timeout=540s \
  --memory=512MB \
  --max-instances=1 \
  --set-env-vars="GCS_BUCKET=$GCS_BUCKET" \
  --set-secrets="apicredentials=apicredentials:latest" \
  --service-account="$SERVICE_ACCOUNT"

echo ""
echo "✅ Data Updater deployed"
echo ""

# Get updater URL
UPDATER_URL=$(gcloud functions describe data-updater \
  --gen2 \
  --region="$GCP_REGION" \
  --format="value(serviceConfig.uri)")

echo "   Updater URL: $UPDATER_URL"
echo ""

# Delete existing scheduler job if exists
if gcloud scheduler jobs describe data-updater-cron \
   --location="$GCP_REGION" &>/dev/null; then
  echo "   Deleting existing scheduler job..."
  gcloud scheduler jobs delete data-updater-cron \
    --location="$GCP_REGION" \
    --quiet
fi

# Create scheduler job - every 30 minutes with intelligent updates
gcloud scheduler jobs create http data-updater-cron \
  --location="$GCP_REGION" \
  --schedule="*/30 * * * *" \
  --time-zone="UTC" \
  --uri="$UPDATER_URL" \
  --http-method=POST \
  --oidc-service-account-email="$SERVICE_ACCOUNT" \
  --attempt-deadline=540s \
  --description="Intelligent market data updates (M5: 30min, M15: 2hr)"

echo ""
echo "✅ Scheduler configured (runs every 30 minutes)"
echo ""

# ── Step 4: Verify GCS Bucket & Data ──────────────────────────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "4️⃣  Verifying GCS Bucket & Data Files"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check if bucket exists
if ! gsutil ls -b "gs://$GCS_BUCKET" &>/dev/null; then
  echo "   Creating GCS bucket..."
  gsutil mb -l "$GCP_REGION" "gs://$GCS_BUCKET"
fi

# Check for CSV files
CSV_COUNT=$(gsutil ls "gs://$GCS_BUCKET/data/*.csv" 2>/dev/null | wc -l || echo "0")

if [ "$CSV_COUNT" -eq 0 ]; then
  echo ""
  echo "   ⚠️  No CSV files found in gs://$GCS_BUCKET/data/"
  echo ""
  echo "   Upload data files:"
  echo "   gsutil -m cp data/*.csv gs://$GCS_BUCKET/data/"
  echo ""
else
  echo "   ✅ Found $CSV_COUNT CSV files"
  gsutil ls "gs://$GCS_BUCKET/data/*.csv"
fi

echo ""

# ── Step 5: Test Data Updater (Optional) ──────────────────────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "5️⃣  Test Data Updater? (Y/n)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

read -p "Trigger data update now? (Y/n): " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
  echo "   Triggering data update..."
  gcloud functions call data-updater \
    --gen2 \
    --region="$GCP_REGION" \
    --data='{}'
  
  echo ""
  echo "   View logs:"
  echo "   gcloud functions logs read data-updater --gen2 --region=$GCP_REGION --limit=50"
  echo ""
else
  echo "   Skipped manual test"
  echo ""
fi

# ── Deployment Summary ────────────────────────────────────────────────────────
echo "══════════════════════════════════════════════════════════════════════════"
echo "✅ Deployment Complete!"
echo "══════════════════════════════════════════════════════════════════════════"
echo ""
echo "📡 API Endpoint (for your UI):"
echo "   $API_URL"
echo ""
echo "🔧 Worker:"
echo "   $WORKER_URL"
echo ""
echo "📊 Data Updater:"
echo "   $UPDATER_URL"
echo "   Schedule: Every 30 minutes (intelligent)"
echo "   - M5 data: Updates every 30 min"
echo "   - M15 data: Updates every 2 hours"
echo ""
echo "💾 Storage:"
echo "   gs://$GCS_BUCKET"
echo ""
echo "──────────────────────────────────────────────────────────────────────────"
echo "Quick Test:"
echo "──────────────────────────────────────────────────────────────────────────"
echo ""
echo "curl -X POST $API_URL/optimize \\\\"
echo "  -H 'Content-Type: application/json' \\\\"
echo "  -d '{"
echo "    \"instrument\": \"GOLD\","
echo "    \"timeframe\": \"M5\","
echo "    \"initial_capital\": 10000,"
echo "    \"position_size\": 0.1,"
echo "    \"mode\": \"quick\""
echo "  }'"
echo ""
echo "──────────────────────────────────────────────────────────────────────────"
echo "Next Steps:"
echo "──────────────────────────────────────────────────────────────────────────"
echo ""
echo "1. Update your frontend API URL to: $API_URL"
echo "2. Test optimization with your UI"
echo "3. Monitor logs:"
echo "   - API: gcloud functions logs read optimize-api --gen2 --region=$GCP_REGION"
echo "   - Worker: gcloud run logs read optimizer-worker --region=$GCP_REGION"
echo "   - Data: gcloud functions logs read data-updater --gen2 --region=$GCP_REGION"
echo ""
echo "📚 Documentation:"
echo "   - API Guide: API_CUSTOMIZATION_GUIDE.md"
echo "   - UI Integration: UI_INTEGRATION_GUIDE.md"
echo "   - Data Updates: DATA_UPDATE_ARCHITECTURE.md"
echo ""
echo "══════════════════════════════════════════════════════════════════════════"
