# Hybrid Architecture - Quick Reference

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    User / Frontend                       │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│              Cloud Functions API (api_functions.py)      │
│              • GET/POST/DELETE endpoints                 │
│              • Instant responses (<100ms)                │
│              • 512MB RAM                                 │
│              Cost: ~$1-2/month                           │
└────────────────────────┬────────────────────────────────┘
                         │ Creates Task
                         ▼
┌─────────────────────────────────────────────────────────┐
│              Cloud Tasks Queue                           │
│              • max-concurrent-dispatches: 3              │
│              • max-attempts: 3 (retry on failure)        │
│              • Rate limit: 1/second                      │
│              Cost: $0.40 per 1M tasks                    │
└────────────────────────┬────────────────────────────────┘
                         │ Dispatches to
                         ▼
┌─────────────────────────────────────────────────────────┐
│          Cloud Run Worker (optimizer_worker.py)          │
│          • Receives task via HTTP POST                   │
│          • Runs optimize_strategy.py                     │
│          • 4 vCPU, 4GB RAM                               │
│          • Scales to 0 when idle ($0)                    │
│          • Only runs during optimization                 │
│          Cost: ~$0.05 per 2-min run                      │
└────────────────────────┬────────────────────────────────┘
                         │ Saves to
                         ▼
┌─────────────────────────────────────────────────────────┐
│              Cloud Storage Bucket                        │
│              • Stores all results permanently            │
│              • CSV files, JSON files                     │
│              • 50GB standard storage                     │
│              Cost: ~$1/month                             │
└─────────────────────────────────────────────────────────┘
```

## 💰 Cost Comparison

| Scenario | Hybrid | Cloud Run | VM (n2-standard-4) |
|----------|--------|-----------|-------------------|
| **10 runs/day** | $3/mo | $10/mo | $140/mo |
| **50 runs/day** | $10/mo | $20/mo | $140/mo |
| **100 runs/day** | $18/mo | $30/mo | $140/mo |
| **Idle (0 runs)** | $0.50/mo | $0 | $140/mo |

## 🚀 Deployment

### One-Command Deploy

```bash
export GCP_PROJECT_ID="your-project-id"
./deploy-hybrid.sh
```

### What Gets Deployed

1. **Cloud Storage Bucket**: `{PROJECT_ID}-optimization-results`
2. **Cloud Tasks Queue**: `optimization-queue` (max 3 concurrent)
3. **Cloud Run Worker**: `optimizer-worker` (4 CPU, 4GB RAM)
4. **Cloud Functions API**: `optimize-api` (512MB RAM)

### Deployment Time

- Initial: ~8 minutes
- Updates (API only): ~1 minute
- Updates (Worker only): ~3 minutes

## 📡 API Endpoints

All endpoints are the same as before:

```
POST   /api/optimize              - Start new optimization (returns instantly)
GET    /api/optimize/status/:id   - Check status (queued/running/completed/failed)
GET    /api/optimize/history      - List all runs
GET    /api/optimize/results/:id  - Get top strategies
GET    /api/analyze/:id           - Comprehensive analysis
DELETE /api/optimize/:id          - Delete a run
GET    /health                    - Health check
```

## 🔄 How It Works

### Starting an Optimization

```bash
curl -X POST https://{REGION}-{PROJECT}.cloudfunctions.net/optimize-api/api/optimize \
  -H 'Content-Type: application/json' \
  -d '{
    "instrument": "GOLD",
    "timeframe": "M5",
    "capital": 10000,
    "position_size": 0.1
  }'
```

**Response** (instant):
```json
{
  "run_id": "GOLD_M5_20260305_123456",
  "status": "queued",
  "message": "Optimization task created"
}
```

### What Happens

1. **Cloud Function** (0.1s):
   - Generates unique `run_id`
   - Saves metadata to Cloud Storage
   - Creates task in Cloud Tasks queue
   - Returns immediately

2. **Cloud Tasks** (0-10s delay):
   - Queues the task
   - Checks concurrency (max 3)
   - Dispatches to Cloud Run worker

3. **Cloud Run Worker** (2-5 minutes):
   - Receives task
   - Updates status to "running"
   - Runs optimization with 4 CPUs
   - Saves results to Cloud Storage
   - Updates status to "completed"

4. **Frontend** (polling):
   - Calls `/api/optimize/status/:id` every 5 seconds
   - Shows progress
   - Fetches results when completed

## 🎛️ Configuration

### Adjust Concurrency

```bash
gcloud tasks queues update optimization-queue \
  --location=us-central1 \
  --max-concurrent-dispatches=5  # Increase to 5

# Warning: Higher concurrency = higher costs
# 3 concurrent = $15/month max
# 5 concurrent = $25/month max
```

### Adjust Worker Resources

```bash
gcloud run deploy optimizer-worker \
  --memory 8Gi \    # Increase RAM
  --cpu 8 \         # Increase CPUs (faster optimization)
  --region us-central1

# Note: 8 CPU will be 2x faster but 2x more expensive
```

### Adjust Timeout

```bash
gcloud run deploy optimizer-worker \
  --timeout 14400 \  # 4 hours max
  --region us-central1
```

## 📊 Monitoring

### View Logs

```bash
# API logs
gcloud functions logs read optimize-api --gen2 --region=us-central1 --limit=50

# Worker logs
gcloud run logs read --service optimizer-worker --region=us-central1 --limit=50

# Tail logs in real-time
gcloud run logs tail --service optimizer-worker --region=us-central1
```

### View Queue Status

```bash
gcloud tasks queues describe optimization-queue --location=us-central1

# Output shows:
# - Tasks in queue
# - Tasks running
# - Rate limits
```

### View Storage

```bash
# List all runs
gsutil ls gs://{PROJECT_ID}-optimization-results

# List files for specific run
gsutil ls gs://{PROJECT_ID}-optimization-results/GOLD_M5_20260305_123456/

# Download results
gsutil cp -r gs://{PROJECT_ID}-optimization-results/GOLD_M5_20260305_123456/ ./local/
```

## 🔧 Troubleshooting

### Task Stuck in Queue

```bash
# Check queue status
gcloud tasks queues describe optimization-queue --location=us-central1

# Check if worker is healthy
curl https://optimizer-worker-xxx.run.app/health

# Purge stuck tasks (last resort)
gcloud tasks queues purge optimization-queue --location=us-central1
```

### Worker Timeout

```bash
# Check worker logs for errors
gcloud run logs read --service optimizer-worker --region=us-central1

# Increase timeout (default: 2 hours)
gcloud run deploy optimizer-worker --timeout 14400 --region=us-central1
```

### High Costs

```bash
# Check actual costs
gcloud billing accounts list
gcloud billing accounts get-current-project

# Reduce concurrency
gcloud tasks queues update optimization-queue --max-concurrent-dispatches=2

# Reduce worker instances
gcloud run services update optimizer-worker --max-instances=2
```

## 🔐 Security

The deployment uses:

- **Cloud Run**: `--no-allow-unauthenticated` (private, only Cloud Tasks can invoke)
- **Cloud Functions**: `--allow-unauthenticated` (public API)
- **IAM**: Service account has minimal required permissions

To add authentication to Cloud Functions:

```bash
gcloud functions deploy optimize-api \
  --gen2 \
  --no-allow-unauthenticated

# Then use API key or OAuth tokens
```

## 📈 Scaling

### Current Limits

- Max concurrent optimizations: 3
- Max instances per worker: 3
- Max queue throughput: 1 task/second

### To Scale Up

```bash
# Increase concurrent workers
gcloud tasks queues update optimization-queue --max-concurrent-dispatches=10

# Increase worker instances
gcloud run services update optimizer-worker --max-instances=10

# Warning: 10 concurrent optimizations = ~$50/month
```

## 🎯 Best Practices

1. **Start with defaults** (3 concurrent)
2. **Monitor costs** for first week
3. **Adjust concurrency** based on usage patterns
4. **Set budget alerts** in GCP Console
5. **Clean up old results** periodically:

```bash
# Delete runs older than 30 days
gsutil -m rm -r gs://{BUCKET}/GOLD_M5_202602*
```

## 🆚 vs Other Architectures

| Feature | Hybrid | Cloud Run All-in-One |
|---------|--------|----------------------|
| API Response Time | <100ms | 2-5 minutes |
| Concurrency Control | Built-in (queue) | Manual (max-instances) |
| Cost at 10 runs/day | $3 | $10 |
| Complexity | Medium | Simple |
| Best For | Production | Quick start |
