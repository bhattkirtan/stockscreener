#!/bin/bash
set -e

# ══════════════════════════════════════════════════════════════════════════════
# Deploy Scheduler Control API
# ══════════════════════════════════════════════════════════════════════════════

source "$(dirname "$0")/config.sh"

echo ""
echo "══════════════════════════════════════════════════════════════════════════"
echo "📡 Deploying Scheduler Control API"
echo "══════════════════════════════════════════════════════════════════════════"
echo ""
echo "   Project: $GCP_PROJECT_ID"
echo "   Region:  $GCP_REGION"
echo "   Bucket:  $GCS_BUCKET"
echo ""

# ── Deploy Cloud Function ─────────────────────────────────────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1️⃣  Deploying Scheduler Control Function"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

gcloud functions deploy scheduler-control \
  --gen2 \
  --region="$GCP_REGION" \
  --runtime=python311 \
  --source=.. \
  --entry-point=scheduler_control \
  --trigger-http \
  --allow-unauthenticated \
  --timeout=60s \
  --memory=512MB \
  --max-instances=10 \
  --set-env-vars="GCS_BUCKET=$GCS_BUCKET" \
  --service-account="$SERVICE_ACCOUNT"

echo ""
echo "✅ Scheduler Control API deployed"
echo ""

# Get function URL
FUNCTION_URL=$(gcloud functions describe scheduler-control \
  --gen2 \
  --region="$GCP_REGION" \
  --format="value(serviceConfig.uri)")

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Deployment Complete"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🔗 Scheduler Control URL:"
echo "   $FUNCTION_URL"
echo ""
echo "📝 Available Endpoints:"
echo "   GET  $FUNCTION_URL/scheduler/status  - Check scheduler status"
echo "   POST $FUNCTION_URL/scheduler/enable  - Enable scheduler"
echo "   POST $FUNCTION_URL/scheduler/disable - Disable scheduler"
echo "   POST $FUNCTION_URL/scheduler/trigger - Manually trigger update"
echo ""
echo "🧪 Test Commands:"
echo ""
echo "   # Check status"
echo "   curl $FUNCTION_URL/scheduler/status"
echo ""
echo "   # Enable scheduler"
echo "   curl -X POST $FUNCTION_URL/scheduler/enable"
echo ""
echo "   # Disable scheduler"
echo "   curl -X POST $FUNCTION_URL/scheduler/disable"
echo ""
echo "   # Manually trigger data update"
echo "   curl -X POST $FUNCTION_URL/scheduler/trigger"
echo ""
echo "══════════════════════════════════════════════════════════════════════════"
