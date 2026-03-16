#!/bin/bash
set -e

# ──────────────────────────────────────────────────────────────────────────────
# Deploy Optimizer Worker (Cloud Run)
# ──────────────────────────────────────────────────────────────────────────────

source "$(dirname "$0")/config.sh"

echo ""
echo "══════════════════════════════════════════════════════════════════════════"
echo "🚀 Deploying Optimizer Worker (Cloud Run)"
echo "══════════════════════════════════════════════════════════════════════════"
echo ""
echo "   Project: $GCP_PROJECT_ID"
echo "   Region:  $GCP_REGION"
echo "   Bucket:  $GCS_BUCKET"
echo ""

# ── Step 1: Build and Push Container Image ────────────────────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1️⃣  Building Container Image"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Navigate to project root
cd "$(dirname "$0")/.."

IMAGE_NAME="gcr.io/$GCP_PROJECT_ID/optimizer-worker"
IMAGE_TAG="latest"
FULL_IMAGE="$IMAGE_NAME:$IMAGE_TAG"

echo "Building: $FULL_IMAGE"
echo ""

# Build using Cloud Build with custom yaml
gcloud builds submit \
  --config=cloudbuild-worker.yaml \
  --timeout=15m \
  --project="$GCP_PROJECT_ID"

echo ""
echo "✅ Container image built and pushed"
echo ""

# ── Step 2: Deploy to Cloud Run ───────────────────────────────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "2️⃣  Deploying to Cloud Run"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

gcloud run deploy optimizer-worker \
  --image="$FULL_IMAGE" \
  --platform=managed \
  --region="$GCP_REGION" \
  --memory=4Gi \
  --cpu=4 \
  --timeout=900 \
  --concurrency=1 \
  --max-instances=2 \
  --min-instances=0 \
  --no-cpu-throttling \
  --no-allow-unauthenticated \
  --set-env-vars="GCP_PROJECT_ID=$GCP_PROJECT_ID,GCS_BUCKET=$GCS_BUCKET" \
  --service-account="$SERVICE_ACCOUNT" \
  --project="$GCP_PROJECT_ID"

echo ""
echo "✅ Worker deployed successfully"
echo ""

# Get worker URL
WORKER_URL=$(gcloud run services describe optimizer-worker \
  --platform=managed \
  --region="$GCP_REGION" \
  --format="value(status.url)" \
  --project="$GCP_PROJECT_ID")

echo "   URL: $WORKER_URL"
echo ""

# ── Step 3: Grant Cloud Tasks permissions ─────────────────────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "3️⃣  Granting Cloud Tasks Permission"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Allow Cloud Tasks service account to invoke the worker
gcloud run services add-iam-policy-binding optimizer-worker \
  --member="serviceAccount:service-$PROJECT_NUMBER@gcp-sa-cloudtasks.iam.gserviceaccount.com" \
  --role="roles/run.invoker" \
  --region="$GCP_REGION" \
  --project="$GCP_PROJECT_ID"

echo ""
echo "✅ Cloud Tasks can now invoke worker"
echo ""

echo "══════════════════════════════════════════════════════════════════════════"
echo "✅ Worker Deployment Complete"
echo "══════════════════════════════════════════════════════════════════════════"
echo ""
echo "Worker URL: $WORKER_URL"
echo ""
echo "Next steps:"
echo "  1. Tasks in optimization-queue will be sent to this worker"
echo "  2. Monitor logs: gcloud run logs read optimizer-worker --region=$GCP_REGION"
echo "  3. Check metrics in Cloud Console"
echo ""
