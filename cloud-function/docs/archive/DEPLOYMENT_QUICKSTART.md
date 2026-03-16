# 🚀 Quick Deployment Guide

## Prerequisites Check

```bash
# Make sure you're authenticated
gcloud auth list

# Set project
gcloud config set project double-venture-442318-k8
```

## Step 1: Upload Data Files (First Time Only)

```bash
# Upload CSV files to GCS bucket
gsutil -m cp data/*.csv gs://double-venture-442318-k8-optimization-results/data/

# Verify upload
gsutil ls gs://double-venture-442318-k8-optimization-results/data/
```

**Expected output**: 6 CSV files (~55KB each)
- GOLD_M15_10000bars.csv
- GOLD_M15_2000bars.csv
- GOLD_M5_5000bars.csv
- GOLD_M5_3000bars.csv
- EURUSD_M15_10000bars.csv
- EURUSD_M15_2000bars.csv

---

## Step 2: Deploy Everything

```bash
cd /Users/kirtanbhatt/code/stockScreener/cloud-function

# Deploy all components (API + Worker + Data Updater + Scheduler)
./deploy-all.sh
```

**This will:**
1. ✅ Deploy optimizer worker (Cloud Run, 4CPU/4GB)
2. ✅ Deploy API function (Cloud Functions Gen2)
3. ✅ Deploy data updater function
4. ✅ Configure scheduler (every 30 min, intelligent)
5. ✅ Test connections

**Time**: ~8-10 minutes

---

## Step 3: Verify Deployment

```bash
# Check status
./check-status.sh

# Expected: All green ✅
```

---

## Step 4: Test API

```bash
# Get API URL (from deploy output or status check)
API_URL="https://optimize-api-6ovej2yaoa-uc.a.run.app"

# Test health
curl $API_URL/health

# Test optimization
curl -X POST $API_URL/optimize \
  -H 'Content-Type: application/json' \
  -d '{
    "instrument": "GOLD",
    "timeframe": "M5",
    "initial_capital": 10000,
    "position_size": 0.1,
    "mode": "quick"
  }'
```

**Expected response**:
```json
{
  "run_id": "a7f3c91b",
  "status": "queued",
  "estimated_combinations": 540,
  "task_name": "projects/.../tasks/..."
}
```

---

## Step 5: Check Optimization Status

```bash
# Using run_id from previous response
curl $API_URL/optimize/a7f3c91b
```

**Status progression**:
1. `queued` → Task created
2. `running` → Worker processing
3. `completed` → Results ready (or `failed` with error)

---

## Step 6: Update Your Frontend

Update the API URL in your frontend code:

```typescript
// capital-connect/src/services/api.ts
const API_BASE_URL = 'https://optimize-api-6ovej2yaoa-uc.a.run.app';
```

---

## Troubleshooting

### "Permission denied" during deployment
```bash
# Ensure you're authenticated
gcloud auth login
gcloud auth application-default login
```

### "CSV files not found" error
```bash
# Upload data files
gsutil -m cp data/*.csv gs://double-venture-442318-k8-optimization-results/data/
```

### "Function not responding"
```bash
# Check logs
gcloud functions logs read optimize-api --gen2 --region=us-central1 --limit=50
gcloud run logs read optimizer-worker --region=us-central1 --limit=50
```

### "Worker timeout"
```bash
# Check worker memory/CPU
gcloud run services describe optimizer-worker --region=us-central1
```

---

## Monitoring

### View Logs

```bash
# API logs
gcloud functions logs read optimize-api --gen2 --region=us-central1 --limit=50

# Worker logs
gcloud run logs read optimizer-worker --region=us-central1 --limit=50

# Data updater logs
gcloud functions logs read data-updater --gen2 --region=us-central1 --limit=50

# Scheduler logs
gcloud logging read "resource.type=cloud_scheduler_job AND resource.labels.job_id=data-updater-cron" --limit=10
```

### View Metrics

```bash
# Worker metrics
gcloud run services describe optimizer-worker --region=us-central1 --format="value(status.conditions)"

# API metrics
gcloud functions describe optimize-api --gen2 --region=us-central1
```

---

## Cost Monitoring

```bash
# Estimate monthly costs
echo "Expected monthly cost: $0.35-$1.00"
echo "  - Cloud Functions: ~$0.20"
echo "  - Cloud Run: ~$0.05 (scales to zero)"
echo "  - Cloud Storage: ~$0.01"
echo "  - Cloud Scheduler: ~$0.10"
```

---

## Quick Commands Reference

```bash
# Status check
./check-status.sh

# Full deployment
./deploy-all.sh

# Deploy only data updater
./deploy-data-updater.sh

# Trigger manual data update
gcloud functions call data-updater --gen2 --region=us-central1 --data='{}'

# Test API health
curl https://optimize-api-6ovej2yaoa-uc.a.run.app/health

# List all optimizations
curl https://optimize-api-6ovej2yaoa-uc.a.run.app/optimize

# Delete optimization results
curl -X DELETE https://optimize-api-6ovej2yaoa-uc.a.run.app/optimize/{run_id}
```

---

## Next Steps

1. ✅ Deploy system: `./deploy-all.sh`
2. ✅ Test API: See Step 4 above
3. ✅ Update frontend URL
4. ✅ Test from UI
5. 📚 Read customization guides:
   - [API_CUSTOMIZATION_GUIDE.md](API_CUSTOMIZATION_GUIDE.md)
   - [UI_INTEGRATION_GUIDE.md](UI_INTEGRATION_GUIDE.md)
   - [DATA_UPDATE_ARCHITECTURE.md](DATA_UPDATE_ARCHITECTURE.md)

---

## Ready to Deploy?

```bash
cd /Users/kirtanbhatt/code/stockScreener/cloud-function

# Step 1: Upload data (if not done)
gsutil -m cp data/*.csv gs://double-venture-442318-k8-optimization-results/data/

# Step 2: Deploy everything
./deploy-all.sh
```

That's it! 🚀
