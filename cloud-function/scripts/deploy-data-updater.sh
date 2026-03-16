#!/bin/bash
set -e

# ──────────────────────────────────────────────────────────────────────────────
# Deploy Data Updater Cloud Function + Cloud Scheduler
# ──────────────────────────────────────────────────────────────────────────────

source "$(dirname "$0")/config.sh"

echo ""
echo "══════════════════════════════════════════════════════════════════════════"
echo "📡 Deploying Data Updater Function + Scheduler"
echo "══════════════════════════════════════════════════════════════════════════"
echo ""
echo "   Project: $GCP_PROJECT_ID"
echo "   Region:  $GCP_REGION"
echo "   Bucket:  $GCS_BUCKET"
echo ""

# ── Step 1: Deploy Cloud Function ─────────────────────────────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1️⃣  Deploying Cloud Function (Gen2)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

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
  --set-secrets="apicredentials=capitalService:latest" \
  --service-account="$SERVICE_ACCOUNT"

echo ""
echo "✅ Cloud Function deployed"
echo ""

# Get function URL
FUNCTION_URL=$(gcloud functions describe data-updater \
  --gen2 \
  --region="$GCP_REGION" \
  --format="value(serviceConfig.uri)")

echo "   URL: $FUNCTION_URL"
echo ""

# ── Step 2: Create Cloud Scheduler Job ────────────────────────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "2️⃣  Creating Cloud Scheduler Job"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Delete existing job if exists
if gcloud scheduler jobs describe data-updater-cron \
   --location="$GCP_REGION" &>/dev/null; then
  echo "   Deleting existing scheduler job..."
  gcloud scheduler jobs delete data-updater-cron \
    --location="$GCP_REGION" \
    --quiet
fi

# Create scheduler job - runs every 30 minutes with intelligent updates
# Schedule: "*/30 * * * *" = Every 30 minutes
# M5 data: Updates every 30 min
# M15 data: Updates every 2 hours
gcloud scheduler jobs create http data-updater-cron \
  --location="$GCP_REGION" \
  --schedule="*/30 * * * *" \
  --time-zone="UTC" \
  --uri="$FUNCTION_URL" \
  --http-method=POST \
  --oidc-service-account-email="$SERVICE_ACCOUNT" \
  --attempt-deadline=540s \
  --description="Intelligent market data updates (M5: 30min, M15: 2hr)"

echo ""
echo "✅ Scheduler job created: data-updater-cron"
echo "   Schedule: Every 30 minutes (*/30 * * * *)"
echo "   Intelligent Updates:"
echo "     • M5 timeframes: Every 30 minutes"
echo "     • M15 timeframes: Every 2 hours"
echo "   Timezone: UTC"
echo ""

# ── Step 3: Manual Test ───────────────────────────────────────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "3️⃣  Testing (Manual Trigger)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

read -p "   Trigger test run now? (y/N) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
  echo ""
  echo "   Running test update..."
  gcloud scheduler jobs run data-updater-cron \
    --location="$GCP_REGION"
  
  echo ""
  echo "   Job triggered! Check logs:"
  echo "   https://console.cloud.google.com/functions/details/$GCP_REGION/data-updater?project=$GCP_PROJECT_ID&tab=logs"
fi

echo ""
echo "══════════════════════════════════════════════════════════════════════════"
echo "✅ Data Updater Deployment Complete!"
echo "══════════════════════════════════════════════════════════════════════════"
echo ""
echo "📋 Summary:"
echo "   • Function: data-updater"
echo "   • Schedule: Every 4 hours"
echo "   • Datasets: 5 CSV files (GOLD + EURUSD)"
echo "   • Bucket:   gs://$GCS_BUCKET/data/"
echo ""
echo "🔧 Management Commands:"
echo "   • View logs:    gcloud functions logs read data-updater --gen2 --region=$GCP_REGION --limit=50"
echo "   • Manual run:   gcloud scheduler jobs run data-updater-cron --location=$GCP_REGION"
echo "   • Pause cron:   gcloud scheduler jobs pause data-updater-cron --location=$GCP_REGION"
echo "   • Resume cron:  gcloud scheduler jobs resume data-updater-cron --location=$GCP_REGION"
echo ""
echo "💡 The data will be incrementally updated every 4 hours"
echo "   Only NEW bars since last update will be fetched (efficient!)"
echo ""
