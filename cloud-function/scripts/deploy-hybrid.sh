#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Strategy Optimizer - Hybrid Deployment${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check if GCP_PROJECT_ID is set
if [ -z "$GCP_PROJECT_ID" ]; then
    echo -e "${RED}Error: GCP_PROJECT_ID environment variable is not set${NC}"
    echo "Please run: export GCP_PROJECT_ID='your-project-id'"
    exit 1
fi

# Configuration
REGION="${REGION:-us-central1}"
QUEUE_NAME="${QUEUE_NAME:-optimization-queue}"
FUNCTION_NAME="${FUNCTION_NAME:-optimize-api}"
WORKER_NAME="${WORKER_NAME:-optimizer-worker}"
BUCKET_NAME="${BUCKET_NAME:-${GCP_PROJECT_ID}-optimization-results}"

echo -e "${YELLOW}Configuration:${NC}"
echo "  Project ID:    $GCP_PROJECT_ID"
echo "  Region:        $REGION"
echo "  Queue Name:    $QUEUE_NAME"
echo "  Function Name: $FUNCTION_NAME"
echo "  Worker Name:   $WORKER_NAME"
echo "  Bucket Name:   $BUCKET_NAME"
echo ""

# Confirm with user
read -p "Proceed with deployment? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Deployment cancelled"
    exit 1
fi

echo ""
echo -e "${GREEN}Step 1: Enabling required APIs...${NC}"
gcloud services enable \
    cloudfunctions.googleapis.com \
    cloudtasks.googleapis.com \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    storage.googleapis.com \
    --project=$GCP_PROJECT_ID

echo -e "${GREEN}✅ APIs enabled${NC}"
echo ""

echo -e "${GREEN}Step 2: Creating Cloud Storage bucket...${NC}"
if gsutil ls -b gs://$BUCKET_NAME 2>/dev/null; then
    echo -e "${YELLOW}Bucket already exists, skipping creation${NC}"
else
    gsutil mb -p $GCP_PROJECT_ID -l $REGION gs://$BUCKET_NAME
    echo -e "${GREEN}✅ Bucket created: gs://$BUCKET_NAME${NC}"
fi
echo ""

echo -e "${GREEN}Step 3: Creating Cloud Tasks queue...${NC}"
if gcloud tasks queues describe $QUEUE_NAME --location=$REGION --project=$GCP_PROJECT_ID 2>/dev/null; then
    echo -e "${YELLOW}Queue already exists, updating configuration...${NC}"
    gcloud tasks queues update $QUEUE_NAME \
        --location=$REGION \
        --max-concurrent-dispatches=3 \
        --max-dispatches-per-second=1 \
        --max-attempts=3 \
        --project=$GCP_PROJECT_ID
else
    gcloud tasks queues create $QUEUE_NAME \
        --location=$REGION \
        --max-concurrent-dispatches=3 \
        --max-dispatches-per-second=1 \
        --max-attempts=3 \
        --project=$GCP_PROJECT_ID
fi
echo -e "${GREEN}✅ Queue configured with concurrency limit: 3${NC}"
echo ""

echo -e "${GREEN}Step 4: Building and deploying Cloud Run worker...${NC}"
# Create temporary cloudbuild.yaml for worker
cat > /tmp/cloudbuild-worker.yaml << EOF
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'gcr.io/$GCP_PROJECT_ID/$WORKER_NAME', '-f', 'Dockerfile.worker', '.']
images:
  - 'gcr.io/$GCP_PROJECT_ID/$WORKER_NAME'
EOF

gcloud builds submit --config=/tmp/cloudbuild-worker.yaml \
    --project=$GCP_PROJECT_ID

gcloud run deploy $WORKER_NAME \
    --image gcr.io/$GCP_PROJECT_ID/$WORKER_NAME \
    --region $REGION \
    --platform managed \
    --no-allow-unauthenticated \
    --memory 4Gi \
    --cpu 4 \
    --timeout 3600 \
    --max-instances 3 \
    --set-env-vars GCP_PROJECT_ID=$GCP_PROJECT_ID,BUCKET_NAME=$BUCKET_NAME \
    --project=$GCP_PROJECT_ID

# Get worker URL
WORKER_URL=$(gcloud run services describe $WORKER_NAME \
    --region $REGION \
    --project=$GCP_PROJECT_ID \
    --format 'value(status.url)')

echo -e "${GREEN}✅ Worker deployed: $WORKER_URL${NC}"
echo ""

echo -e "${GREEN}Step 5: Deploying Cloud Functions API...${NC}"

# Create temporary directory with only Cloud Function files
TEMP_DIR=$(mktemp -d)
cp api_functions.py $TEMP_DIR/main.py
cp requirements-functions.txt $TEMP_DIR/requirements.txt

gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime python311 \
    --region $REGION \
    --source $TEMP_DIR \
    --entry-point optimize_api \
    --trigger-http \
    --allow-unauthenticated \
    --memory 512Mi \
    --timeout 60s \
    --set-env-vars GCP_PROJECT_ID=$GCP_PROJECT_ID,REGION=$REGION,QUEUE_NAME=$QUEUE_NAME,WORKER_URL=$WORKER_URL,BUCKET_NAME=$BUCKET_NAME \
    --project=$GCP_PROJECT_ID

# Clean up temp directory
rm -rf $TEMP_DIR

# Get function URL
FUNCTION_URL=$(gcloud functions describe $FUNCTION_NAME \
    --gen2 \
    --region $REGION \
    --project=$GCP_PROJECT_ID \
    --format 'value(serviceConfig.uri)')

echo -e "${GREEN}✅ Cloud Function deployed: $FUNCTION_URL${NC}"
echo ""

echo -e "${GREEN}Step 6: Setting up IAM permissions...${NC}"

# Allow Cloud Functions to create tasks
SERVICE_ACCOUNT="${GCP_PROJECT_ID}@appspot.gserviceaccount.com"

gcloud projects add-iam-policy-binding $GCP_PROJECT_ID \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/cloudtasks.enqueuer" \
    --project=$GCP_PROJECT_ID

# Allow Cloud Tasks to invoke Cloud Run worker
gcloud run services add-iam-policy-binding $WORKER_NAME \
    --region=$REGION \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/run.invoker" \
    --project=$GCP_PROJECT_ID

echo -e "${GREEN}✅ IAM permissions configured${NC}"
echo ""

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}🎉 Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${YELLOW}API URL:${NC} $FUNCTION_URL"
echo -e "${YELLOW}Worker URL:${NC} $WORKER_URL (private)"
echo -e "${YELLOW}Storage Bucket:${NC} gs://$BUCKET_NAME"
echo -e "${YELLOW}Task Queue:${NC} $QUEUE_NAME (max 3 concurrent)"
echo ""
echo -e "${YELLOW}Test your API:${NC}"
echo "curl $FUNCTION_URL/health"
echo ""
echo -e "${YELLOW}Trigger an optimization:${NC}"
echo "curl -X POST $FUNCTION_URL/api/optimize \\"
echo "  -H 'Content-Type: application/json' \\"
echo "  -d '{\"instrument\": \"GOLD\", \"timeframe\": \"M5\"}'"
echo ""
echo -e "${YELLOW}Check status:${NC}"
echo "curl $FUNCTION_URL/api/optimize/history"
echo ""
echo -e "${GREEN}Next steps:${NC}"
echo "1. Update your frontend API_BASE URL to: $FUNCTION_URL"
echo "2. Monitor logs: gcloud functions logs read $FUNCTION_NAME --gen2 --region=$REGION"
echo "3. Monitor worker: gcloud run logs read --service $WORKER_NAME --region=$REGION"
echo "4. View results: gsutil ls gs://$BUCKET_NAME"
echo ""
