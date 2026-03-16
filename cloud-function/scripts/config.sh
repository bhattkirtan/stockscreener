# ============================================================================
# Deployment Configuration for Optimization System
# ============================================================================
#
# This file contains deployment configuration for:
# - Optimizer Worker (Cloud Run)
# - Optimize API (Cloud Functions Gen2)  
# - Data Updater (Cloud Functions Gen2)
#
# Last Updated: 2026-03-05
# ============================================================================

# Project Information
export GCP_PROJECT_ID="double-venture-442318-k8"
export PROJECT_NUMBER="361802071308"
export GCP_REGION="us-central1"
export GCS_BUCKET="double-venture-442318-k8-optimization-results"

# Worker Configuration (Cloud Run)
export WORKER_NAME="optimizer-worker"
export WORKER_CPU="4"
export WORKER_MEMORY="4Gi"
export WORKER_TIMEOUT="3600s"
export WORKER_MAX_INSTANCES="10"
export WORKER_MIN_INSTANCES="0"

# API Configuration (Cloud Functions)
export API_NAME="optimize-api"
export API_MEMORY="512Mi"
export API_TIMEOUT="540s"
export API_MAX_INSTANCES="100"

# Data Updater Configuration (Cloud Functions)
export DATA_UPDATER_NAME="data-updater"
export DATA_UPDATER_MEMORY="512Mi"
export DATA_UPDATER_TIMEOUT="540s"

# Service Account
export SERVICE_ACCOUNT="361802071308-compute@developer.gserviceaccount.com"

# Secrets
SECRET_NAME="capitalService"
SECRET_VERSION="latest"

# Network Configuration
INGRESS="all"
ALLOW_UNAUTHENTICATED="true"

# Build Configuration
BUILD_SERVICE_ACCOUNT="projects/double-venture-442318-k8/serviceAccounts/361802071308-compute@developer.gserviceaccount.com"
BUILD_ENABLE_AUTOMATIC_UPDATES="true"

# URLs
PRIMARY_URL="https://capitalcomservice-6ovej2yaoa-uc.a.run.app"
FUNCTION_URL="https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService"
RUN_URL="https://capitalcomservice-361802071308.us-central1.run.app"

# Deployment Commands
#
# Quick Deploy:
#   ./deploy.sh
#
# Deploy with Skip Confirmation:
#   ./deploy.sh --confirm-overwrite
#
# Manual Deploy:
#   gcloud functions deploy ${FUNCTION_NAME} \
#     --gen2 \
#     --runtime ${RUNTIME} \
#     --trigger-http \
#     --entry-point ${ENTRY_POINT} \
#     --region ${REGION} \
#     --memory ${MEMORY} \
#     --cpu ${CPU} \
#     --timeout ${TIMEOUT} \
#     --max-instances ${MAX_INSTANCES} \
#     --concurrency ${CONCURRENCY} \
#     --service-account ${SERVICE_ACCOUNT} \
#     --set-secrets "apicredentials=${SECRET_NAME}:${SECRET_VERSION}" \
#     --allow-unauthenticated

# Environment Variables (from Secret Manager)
#   apicredentials=${SECRET_NAME}:${SECRET_VERSION}

# Required GCP APIs
#   - Cloud Functions API (cloudfunctions.googleapis.com)
#   - Cloud Run API (run.googleapis.com)
#   - Cloud Build API (cloudbuild.googleapis.com)
#   - Secret Manager API (secretmanager.googleapis.com)
#   - Firestore API (firestore.googleapis.com)
#   - Cloud Logging API (logging.googleapis.com)

# Required IAM Roles for Service Account
#   - Cloud Functions Developer
#   - Secret Manager Secret Accessor
#   - Cloud Datastore User
#   - Logs Writer

# Container Configuration
CONTAINER_REGISTRY="us-central1-docker.pkg.dev"
CONTAINER_IMAGE="${CONTAINER_REGISTRY}/double-venture-442318-k8/cloud-run-source-deploy/capitalcomservice"

# Health Check
STARTUP_PROBE_TIMEOUT="240s"
STARTUP_PROBE_PERIOD="240s"
STARTUP_PROBE_FAILURE_THRESHOLD="1"
STARTUP_PROBE_TYPE="Default"

# Monitoring & Logging
LOG_EXECUTION_ID="true"
