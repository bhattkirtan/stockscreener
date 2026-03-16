#!/bin/bash
# Quick system status check

source scripts/config.sh

echo "══════════════════════════════════════════════════════════════════════════"
echo "📊 System Status Check"
echo "══════════════════════════════════════════════════════════════════════════"
echo ""

# Check API
echo "🔍 API Function..."
if gcloud functions describe optimize-api --gen2 --region="$GCP_REGION" &>/dev/null; then
  API_URL=$(gcloud functions describe optimize-api --gen2 --region="$GCP_REGION" --format="value(serviceConfig.uri)")
  echo "   ✅ Deployed: $API_URL"
  
  # Test health
  echo "   Testing health endpoint..."
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/health" 2>/dev/null || echo "000")
  if [ "$STATUS" = "200" ]; then
    echo "   ✅ Health check passed"
  else
    echo "   ⚠️  Health check failed (HTTP $STATUS)"
  fi
else
  echo "   ❌ Not deployed"
fi
echo ""

# Check Worker
echo "🔍 Optimizer Worker..."
if gcloud run services describe optimizer-worker --platform=managed --region="$GCP_REGION" &>/dev/null; then
  WORKER_URL=$(gcloud run services describe optimizer-worker --platform=managed --region="$GCP_REGION" --format="value(status.url)")
  echo "   ✅ Deployed: $WORKER_URL"
  
  # Test health
  echo "   Testing health endpoint..."
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$WORKER_URL/health" 2>/dev/null || echo "000")
  if [ "$STATUS" = "200" ]; then
    echo "   ✅ Health check passed"
  else
    echo "   ⚠️  Health check failed (HTTP $STATUS)"
  fi
else
  echo "   ❌ Not deployed"
fi
echo ""

# Check Data Updater
echo "🔍 Data Updater..."
if gcloud functions describe data-updater --gen2 --region="$GCP_REGION" &>/dev/null; then
  UPDATER_URL=$(gcloud functions describe data-updater --gen2 --region="$GCP_REGION" --format="value(serviceConfig.uri)")
  echo "   ✅ Deployed: $UPDATER_URL"
else
  echo "   ❌ Not deployed"
fi
echo ""

# Check Scheduler
echo "🔍 Scheduler Job..."
if gcloud scheduler jobs describe data-updater-cron --location="$GCP_REGION" &>/dev/null; then
  SCHEDULE=$(gcloud scheduler jobs describe data-updater-cron --location="$GCP_REGION" --format="value(schedule)")
  NEXT_RUN=$(gcloud scheduler jobs describe data-updater-cron --location="$GCP_REGION" --format="value(scheduleTime)")
  echo "   ✅ Configured: $SCHEDULE"
  echo "   Next run: $NEXT_RUN"
else
  echo "   ❌ Not configured"
fi
echo ""

# Check GCS Bucket
echo "🔍 GCS Bucket..."
if gsutil ls -b "gs://$GCS_BUCKET" &>/dev/null; then
  echo "   ✅ Bucket exists: gs://$GCS_BUCKET"
  
  # Count CSV files
  CSV_COUNT=$(gsutil ls "gs://$GCS_BUCKET/data/*.csv" 2>/dev/null | wc -l || echo "0")
  echo "   📊 CSV files: $CSV_COUNT"
  
  if [ "$CSV_COUNT" -gt 0 ]; then
    echo ""
    echo "   Available datasets:"
    gsutil ls "gs://$GCS_BUCKET/data/*.csv" | sed 's|gs://.*data/||g' | sed 's/^/     • /'
  fi
else
  echo "   ❌ Bucket not found"
fi
echo ""

# Check Cloud Tasks Queue
echo "🔍 Cloud Tasks Queue..."
if gcloud tasks queues describe optimization-queue --location="$GCP_REGION" &>/dev/null; then
  QUEUE_STATE=$(gcloud tasks queues describe optimization-queue --location="$GCP_REGION" --format="value(state)")
  echo "   ✅ Queue exists: $QUEUE_STATE"
else
  echo "   ⚠️  Queue not found (will be created on first use)"
fi
echo ""

echo "══════════════════════════════════════════════════════════════════════════"
echo "Summary"
echo "══════════════════════════════════════════════════════════════════════════"
echo ""

# Overall status
ALL_GOOD=true

if ! gcloud functions describe optimize-api --gen2 --region="$GCP_REGION" &>/dev/null; then
  ALL_GOOD=false
fi

if ! gcloud run services describe optimizer-worker --platform=managed --region="$GCP_REGION" &>/dev/null; then
  ALL_GOOD=false
fi

if ! gsutil ls -b "gs://$GCS_BUCKET" &>/dev/null; then
  ALL_GOOD=false
fi

CSV_COUNT=$(gsutil ls "gs://$GCS_BUCKET/data/*.csv" 2>/dev/null | wc -l || echo "0")
if [ "$CSV_COUNT" -eq 0 ]; then
  ALL_GOOD=false
fi

if [ "$ALL_GOOD" = true ]; then
  echo "✅ All critical components operational"
  echo ""
  echo "Ready to use! Test with:"
  echo "curl -X POST $API_URL/optimize -H 'Content-Type: application/json' -d '{\"instrument\":\"GOLD\",\"timeframe\":\"M5\",\"mode\":\"quick\"}'"
else
  echo "⚠️  Some components missing or need attention"
  echo ""
  echo "Run: ./deploy-all.sh"
fi

echo ""
echo "══════════════════════════════════════════════════════════════════════════"
