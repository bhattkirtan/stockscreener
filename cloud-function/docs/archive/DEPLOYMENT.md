# Deployment Guide - Strategy Optimization API

This guide covers **4 deployment options** for your optimization API.

## 📊 Deployment Options Comparison

| Feature | Hybrid ⭐ | Cloud Run | Cloud Functions | Local/VM |
|---------|---------|-------------|-----------------|----------|
| **Best For** | Production | Simple deploy | Read-only | Development |
| **Architecture** | Functions + Worker | All-in-one | Limited | Flexible |
| **Timeout** | 2 hours | 60 min | 9 min max | Unlimited |
| **CPU Cores** | 4 (worker) | Up to 8 | 1-2 | Unlimited |
| **Cost** | **$2-5/mo** | $5-30/mo | $0.50/mo | $100-140/mo |
| **API Response** | Instant | Waits | Instant | Instant |
| **Concurrency** | Limited (3) | Limited (3) | Limited | Unlimited |
| **Auto-scale** | Yes | Yes | Yes | No |
| **Recommendation** | **BEST** | Good | Read-only | Dev/Testing |

---

## Option 1: Hybrid Architecture (RECOMMENDED) ⭐⭐⭐

**Cloud Functions (API) + Cloud Tasks (Queue) + Cloud Run (Worker)**

This is the **most cost-effective** production architecture. It separates cheap CRUD operations from expensive compute tasks.

### Architecture Flow

```
User Request
    ↓
Cloud Functions API ($1-2/month)
    ├─ GET/POST/DELETE (instant response)
    ↓
Cloud Tasks Queue ($0.40/1M tasks)
    ├─ Max 3 concurrent jobs
    ├─ Automatic retries
    ↓
Cloud Run Worker ($0.05/run)
    ├─ 4 CPU, 4GB RAM
    ├─ Runs only when needed
    ├─ Scales to 0 when idle
    ↓
Cloud Storage
    └─ Results persist forever
```

### Key Benefits

- ✅ **80% cheaper** than all-in-one Cloud Run
- ✅ **Instant API responses** (doesn't wait for optimization)
- ✅ **Built-in concurrency control** (max 3 simultaneous)
- ✅ **Automatic retries** on failure
- ✅ **Workers scale to 0** = $0 when idle
- ✅ **Same parallelization** (4 CPUs per optimization)

### Cost Breakdown

**Light use** (10 optimizations/day):
- Cloud Functions API: ~$1/month (300 requests/day)
- Cloud Storage: ~$0.50/month (10GB)
- Cloud Run Worker: ~$1.50/month (10 runs × 2 min × $0.05)
- **Total: ~$3/month**

**Heavy use** (100 optimizations/day):
- Cloud Functions API: ~$2/month (3,000 requests/day)
- Cloud Storage: ~$1/month (50GB)
- Cloud Run Worker: ~$15/month (100 runs × 2 min × $0.05)
- **Total: ~$18/month** (vs $100-140/month for VM)

### Quick Deploy

```bash
# 1. Make deploy script executable
chmod +x deploy-hybrid.sh

# 2. Set your project ID
export GCP_PROJECT_ID="your-project-id"

# 3. Deploy (takes ~8 minutes)
./deploy-hybrid.sh
```

The script will:
1. Enable required APIs
2. Create Cloud Storage bucket
3. Create Cloud Tasks queue (max 3 concurrent)
4. Deploy Cloud Run worker (4 CPU, 4GB RAM)
5. Deploy Cloud Functions API
6. Configure IAM permissions

### Manual Deploy

If you prefer step-by-step deployment:

```bash
PROJECT_ID="your-project-id"
REGION="us-central1"

# 1. Enable APIs
gcloud services enable \
  cloudfunctions.googleapis.com \
  cloudtasks.googleapis.com \
  run.googleapis.com \
  storage.googleapis.com

# 2. Create Storage bucket
gsutil mb -p $PROJECT_ID -l $REGION gs://${PROJECT_ID}-optimization-results

# 3. Create Cloud Tasks queue
gcloud tasks queues create optimization-queue \
  --location=$REGION \
  --max-concurrent-dispatches=3 \
  --max-attempts=3

# 4. Build and deploy worker
gcloud builds submit --tag gcr.io/$PROJECT_ID/optimizer-worker \
  --dockerfile=Dockerfile.worker

gcloud run deploy optimizer-worker \
  --image gcr.io/$PROJECT_ID/optimizer-worker \
  --region $REGION \
  --no-allow-unauthenticated \
  --memory 4Gi \
  --cpu 4 \
  --timeout 7200 \
  --max-instances 3 \
  --set-env-vars GCP_PROJECT_ID=$PROJECT_ID,BUCKET_NAME=${PROJECT_ID}-optimization-results

# 5. Get worker URL
WORKER_URL=$(gcloud run services describe optimizer-worker \
  --region $REGION \
  --format 'value(status.url)')

# 6. Deploy Cloud Functions
gcloud functions deploy optimize-api \
  --gen2 \
  --runtime python311 \
  --region $REGION \
  --source . \
  --entry-point optimize_api \
  --trigger-http \
  --allow-unauthenticated \
  --memory 512Mi \
  --set-env-vars GCP_PROJECT_ID=$PROJECT_ID,REGION=$REGION,QUEUE_NAME=optimization-queue,WORKER_URL=$WORKER_URL,BUCKET_NAME=${PROJECT_ID}-optimization-results

# 7. Get API URL
FUNCTION_URL=$(gcloud functions describe optimize-api \
  --gen2 \
  --region $REGION \
  --format 'value(serviceConfig.uri)')

echo "API URL: $FUNCTION_URL"
```

### Testing

```bash
# Health check
curl $FUNCTION_URL/health

# Start optimization
curl -X POST $FUNCTION_URL/api/optimize \
  -H 'Content-Type: application/json' \
  -d '{"instrument": "GOLD", "timeframe": "M5"}'

# Check history
curl $FUNCTION_URL/api/optimize/history

# Get results (after completion)
curl $FUNCTION_URL/api/optimize/results/GOLD_M5_20260305_123456
```

### Monitoring

```bash
# View API logs
gcloud functions logs read optimize-api --gen2 --region=$REGION

# View worker logs
gcloud run logs read --service optimizer-worker --region=$REGION

# Check queue
gcloud tasks queues describe optimization-queue --location=$REGION

# View storage
gsutil ls gs://${PROJECT_ID}-optimization-results
```

### Updating

```bash
# Update API only (fast)
gcloud functions deploy optimize-api --gen2 --region=$REGION

# Update worker only
gcloud builds submit --tag gcr.io/$PROJECT_ID/optimizer-worker --dockerfile=Dockerfile.worker
gcloud run deploy optimizer-worker --image gcr.io/$PROJECT_ID/optimizer-worker --region=$REGION
```

---

## Option 2: Cloud Run (All-in-One)

Best for running full optimization API with background tasks.

### Prerequisites

```bash
# Install gcloud CLI
# macOS:
brew install google-cloud-sdk

# Authenticate
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

### Quick Deploy

```bash
# 1. Make deploy script executable
chmod +x deploy-cloud-run.sh

# 2. Set your project ID
export GCP_PROJECT_ID="your-project-id"

# 3. Deploy (takes ~5 minutes)
./deploy-cloud-run.sh
```

### Manual Deploy

```bash
# 1. Enable APIs
gcloud services enable cloudbuild.googleapis.com run.googleapis.com

# 2. Build image
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/strategy-optimizer-api

# 3. Deploy
gcloud run deploy strategy-optimizer-api \
  --image gcr.io/YOUR_PROJECT_ID/strategy-optimizer-api \
  --region us-central1 \
  --platform managed \
  --allow-unauthenticated \
  --memory 4Gi \
  --cpu 4 \
  --timeout 3600 \
  --max-instances 3

# 4. Get URL
gcloud run services describe strategy-optimizer-api \
  --region us-central1 \
  --format 'value(status.url)'
```

### Configuration

Edit [`cloudbuild.yaml`](cloudbuild.yaml ):

```yaml
--memory '4Gi'        # Increase for larger datasets
--cpu '4'             # 4 cores for parallel processing
--timeout '3600'      # 1 hour timeout
--max-instances '3'   # Scale up to 3 instances
```

### Costs (Approximate)

- **Idle**: $0 (no requests = no charges)
- **Light use** (10 optimizations/day): ~$5/month
- **Heavy use** (100 optimizations/day): ~$30/month

**Pricing**: $0.00002400 per vCPU-second, $0.00000250 per GiB-second

---

## Option 3: Cloud Functions (Read-Only)

For viewing results only. Run optimizations locally, store results in Cloud Storage.

### Architecture

```
Local Machine → Run Optimization → Upload to Cloud Storage
                                           ↓
                            Cloud Function (Read-Only) → View Results
```

### Setup

1. **Create Cloud Storage Bucket**

```bash
gsutil mb gs://your-optimization-results
```

2. **Deploy Function**

```bash
gcloud functions deploy optimize-api \
  --runtime python311 \
  --trigger-http \
  --allow-unauthenticated \
  --entry-point optimize_api \
  --source . \
  --memory 512MB \
  --timeout 60s \
  --set-env-vars BUCKET_NAME=your-optimization-results
```

3. **Upload Results After Local Optimization**

```bash
# After running optimization locally
gsutil -m cp -r data/optimization/latest/* \
  gs://your-optimization-results/latest/
```

### Limitations

- ❌ Cannot run optimizations (timeout)
- ✅ Can view results
- ✅ Can analyze data
- ✅ Very cheap (~$0.50/month)

---

## Option 4: Local/VM Deployment

Run on your local machine or cloud VM.

### Local Development

```bash
# 1. Install dependencies
pip3 install -r requirements.txt

# 2. Run server
python3 api_server.py

# Server runs on http://localhost:8000
```

### Deploy on Google Compute Engine VM

```bash
# 1. Create VM
gcloud compute instances create optimizer-vm \
  --machine-type n2-standard-4 \
  --zone us-central1-a \
  --image-family ubuntu-2204-lts \
  --image-project ubuntu-os-cloud \
  --boot-disk-size 50GB

# 2. SSH to VM
gcloud compute ssh optimizer-vm --zone us-central1-a

# 3. Install dependencies
sudo apt update
sudo apt install -y python3-pip git
git clone YOUR_REPO
cd stockScreener/cloud-function
pip3 install -r requirements.txt

# 4. Run as service
sudo tee /etc/systemd/system/optimizer-api.service << EOF
[Unit]
Description=Strategy Optimizer API
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=/home/$USER/stockScreener/cloud-function
ExecStart=/usr/bin/python3 api_server.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable optimizer-api
sudo systemctl start optimizer-api

# 5. Open firewall
gcloud compute firewall-rules create allow-optimizer \
  --allow tcp:8000 \
  --source-ranges 0.0.0.0/0
```

### Costs

- **n2-standard-4** (4 vCPU, 16GB RAM): ~$140/month
- **e2-standard-4** (4 vCPU, 16GB RAM): ~$100/month
- **Spot/Preemptible**: ~$30/month (can be interrupted)

---

## 🆚 Which Should You Choose?

### Choose **Hybrid Architecture** (Option 1) if: ⭐⭐⭐
- ✅ You want the **most cost-effective** solution
- ✅ You want instant API responses (not waiting for optimization)
- ✅ You want built-in concurrency control
- ✅ You want production-ready with auto-scaling
- ✅ **Recommended for 90% of users**
- 💰 **Cost: ~$2-5/month**

### Choose **Cloud Run** (Option 2) if:
- ✅ You want simpler deployment (all-in-one)
- ✅ You don't mind API waiting during optimization
- ✅ You're okay with higher costs
- ✅ Good for getting started quickly
- 💰 **Cost: ~$5-30/month**

### Choose **Cloud Functions** (Option 3) if:
- ✅ You only need to VIEW results
- ✅ You run optimizations locally
- ✅ You want absolute minimal costs
- ✅ You don't need heavy compute
- 💰 **Cost: ~$0.50/month**

### Choose **VM/Local** (Option 4) if:
- ✅ You're still developing/testing
- ✅ You need unlimited timeouts
- ✅ You want full control
- ✅ You run 100+ optimizations daily (VM may be cheaper)
- 💰 **Cost: ~$100-140/month (fixed)**

---

## 🚀 Recommended Setup (Best Practices)

### Production Setup - Hybrid Architecture ⭐

```
User Request
    ↓
┌─────────────────────┐
│  Cloud Functions    │  ← Instant CRUD API ($1-2/mo)
│  (512MB, <100ms)    │  ← GET/POST/DELETE
└──────────┬──────────┘
           │
    ┌──────▼──────┐
    │ Cloud Tasks │  ← Queue (max 3 concurrent)
    │    Queue    │  ← Retry logic
    └──────┬──────┘
           │
┌──────────▼──────────┐
│  Cloud Run Worker   │  ← Heavy compute only when needed
│  (4 CPU, 4GB RAM)   │  ← Scales to 0 = $0
│  ~$0.05 per run     │  ← 2-min optimization
└──────────┬──────────┘
           │
    ┌──────▼──────┐
    │   Storage   │  ← Results persist forever
    └─────────────┘
```

**Total Cost**: ~$3-5/month (80% cheaper than Cloud Run)

### Simple Setup - Cloud Run All-in-One

```
┌─────────────────┐
│   Cloud Run     │  ← Main API (4 cores, 4GB RAM)
│  Full API       │  ← Handles ALL requests
└─────────────────┘  ← Auto-scales 0-3 instances
```

**Cost**: ~$10-30/month depending on usage

### Budget Setup - Read-Only

```
┌──────────────────┐     ┌──────────────────┐
│  Local Machine   │────→│ Cloud Storage    │
│  Run Optimizer   │     │ Store Results    │
└──────────────────┘     └────────┬─────────┘
                                  │
                         ┌────────▼─────────┐
                         │ Cloud Function   │
                         │ View Results     │
                         └──────────────────┘
```

**Cost**: ~$0.50/month

---

## 📝 Next Steps

### 1. Deploy to Cloud Run (Recommended)

```bash
export GCP_PROJECT_ID="your-project-id"
./deploy-cloud-run.sh
```

### 2. Test Deployment

```bash
# Get your service URL
SERVICE_URL=$(gcloud run services describe strategy-optimizer-api \
  --region us-central1 \
  --format 'value(status.url)')

# Test health
curl $SERVICE_URL/health

# Open dashboard
open $SERVICE_URL
```

### 3. Update Frontend

Update your dashboard [`static/dashboard.html`](static/dashboard.html):

```javascript
// Change this line:
const API_BASE = 'http://localhost:8000';

// To your Cloud Run URL:
const API_BASE = 'https://strategy-optimizer-api-xxx.run.app';
```

### 4. Monitor Logs

```bash
gcloud run logs read strategy-optimizer-api --region us-central1
```

---

## 🔒 Security (Optional)

### Add Authentication

```bash
# Deploy with authentication required
gcloud run deploy strategy-optimizer-api \
  --no-allow-unauthenticated \
  ...

# Generate auth token
gcloud auth print-identity-token
```

Update API calls:

```bash
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  https://your-service.run.app/api/analyze/latest
```

---

## 🐛 Troubleshooting

### Build Fails

```bash
# Check logs
gcloud builds log --limit 10

# Test Docker build locally
docker build -t test-optimizer .
docker run -p 8080:8080 test-optimizer
```

### Timeout Errors

```bash
# Increase timeout (max 3600s = 1 hour)
gcloud run services update strategy-optimizer-api \
  --timeout 3600
```

### Out of Memory

```bash
# Increase memory (max 8GB)
gcloud run services update strategy-optimizer-api \
  --memory 8Gi
```

### Check Resource Usage

```bash
# View metrics
gcloud monitoring dashboards list
gcloud run services describe strategy-optimizer-api --region us-central1
```

---

## 💰 Cost Optimization

### Reduce Costs

1. **Set min-instances to 0** (default) - scales to zero when idle
2. **Use smaller CPU** (2 cores) if optimization runs are infrequent  
3. **Set max-instances** to limit concurrent runs
4. **Use Cloud Build cache** to speed up deployments

```bash
# Lower resource limits
gcloud run services update strategy-optimizer-api \
  --cpu 2 \
  --memory 2Gi \
  --max-instances 2
```

---

## 📚 Additional Resources

- [Cloud Run Documentation](https://cloud.google.com/run/docs)
- [Cloud Functions Documentation](https://cloud.google.com/functions/docs)
- [Pricing Calculator](https://cloud.google.com/products/calculator)
- [Cloud Run Pricing](https://cloud.google.com/run/pricing)

---

## Quick Commands Cheat Sheet

```bash
# Deploy to Cloud Run
./deploy-cloud-run.sh

# View logs
gcloud run logs tail strategy-optimizer-api

# Delete service
gcloud run services delete strategy-optimizer-api --region us-central1

# Update service
gcloud run services update strategy-optimizer-api --memory 8Gi

# Get service URL
gcloud run services describe strategy-optimizer-api \
  --region us-central1 --format 'value(status.url)'

# Deploy new version
gcloud builds submit --tag gcr.io/$PROJECT_ID/strategy-optimizer-api
gcloud run services update strategy-optimizer-api \
  --image gcr.io/$PROJECT_ID/strategy-optimizer-api
```

---

**Ready to deploy? Start with Cloud Run!**

```bash
chmod +x deploy-cloud-run.sh
export GCP_PROJECT_ID="your-project-id"  
./deploy-cloud-run.sh
```
