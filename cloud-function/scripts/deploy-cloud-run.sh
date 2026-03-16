#!/bin/bash
# Deploy Strategy Optimization API to Google Cloud Run

set -e

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-your-project-id}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="strategy-optimizer-api"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

echo "================================================"
echo "Deploying Strategy Optimization API to Cloud Run"
echo "================================================"
echo ""
echo "Project ID: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Service: ${SERVICE_NAME}"
echo ""

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo "❌ Error: gcloud CLI is not installed"
    echo "Install from: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Authenticate (if needed)
echo "🔐 Checking authentication..."
gcloud auth list --filter=status:ACTIVE --format="value(account)" || {
    echo "Please authenticate:"
    gcloud auth login
}

# Set project
echo "📝 Setting project..."
gcloud config set project ${PROJECT_ID}

# Enable required APIs
echo "🔧 Enabling required APIs..."
gcloud services enable \
    cloudbuild.googleapis.com \
    run.googleapis.com \
    containerregistry.googleapis.com

# Build container image
echo "🏗️  Building container image..."
gcloud builds submit --tag ${IMAGE_NAME} --config ../docker/cloudbuild.yaml ..

# Deploy to Cloud Run
echo "🚀 Deploying to Cloud Run..."
gcloud run deploy ${SERVICE_NAME} \
    --image ${IMAGE_NAME} \
    --region ${REGION} \
    --platform managed \
    --allow-unauthenticated \
    --memory 4Gi \
    --cpu 4 \
    --timeout 3600 \
    --concurrency 10 \
    --max-instances 3 \
    --set-env-vars "PYTHONUNBUFFERED=1,N_JOBS=4"

# Get service URL
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} \
    --region ${REGION} \
    --format 'value(status.url)')

echo ""
echo "================================================"
echo "✅ Deployment Complete!"
echo "================================================"
echo ""
echo "🔗 Service URL: ${SERVICE_URL}"
echo "📖 API Docs: ${SERVICE_URL}/docs"
echo "💚 Health Check: ${SERVICE_URL}/health"
echo "🎨 Dashboard: ${SERVICE_URL}/"
echo ""
echo "Test your API:"
echo "  curl ${SERVICE_URL}/health"
echo ""
echo "To view logs:"
echo "  gcloud run logs read ${SERVICE_NAME} --region ${REGION}"
echo ""
