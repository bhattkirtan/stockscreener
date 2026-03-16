# 📡 Automated Data Update Architecture

## Overview

Keeps market data CSV files fresh in GCS bucket by periodically fetching new bars from Capital.com API.

## Architecture

```
┌─────────────────────┐
│  Cloud Scheduler    │  Every 30 minutes
│  (data-updater-cron)│  Triggers HTTP POST
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Cloud Function     │  Gen2, Python 3.11
│  (data-updater)     │  No auth required*
└──────────┬──────────┘
           │
           ├─── 1. Authenticate with Capital.com
           │    (uses apicredentials secret)
           │
           ├─── 2. For each dataset:
           │    • Check last update time (GCS metadata)
           │    • If stale by timeframe rules:
           │      - M5: Update if ≥30 min old
           │      - M15: Update if ≥2 hours old
           │    • Fetch ONLY new bars (incremental)
           │    • Update local CSV
           │    • Upload to GCS bucket
           │
           └─── 3. Return summary JSON
                (updated count, skipped, failures)

┌─────────────────────┐
│  GCS Bucket         │  Updated CSV files
│  (optimization-     │  data/*.csv
│   results)          │
└─────────────────────┘
           │
           ▼
┌─────────────────────┐
│  Cloud Run Worker   │  Downloads on-demand
│  (optimizer-worker) │  for optimization runs
└─────────────────────┘
```

*Uses service account authentication via OIDC token

## Components

### 1. Data Updater Function (`data_updater.py`)

**Purpose**: Cloud Function that fetches incremental market data updates

**Features**:
- ✅ **Intelligent scheduling**: Different update frequencies per timeframe
  - M5 (5-minute) data: Updates every 30 minutes (real-time)
  - M15 (15-minute) data: Updates every 2 hours (less frequent)
- ✅ Incremental fetching (only new bars since last update)
- ✅ Checks GCS metadata to avoid redundant API calls
- ✅ Batch updates multiple datasets (GOLD, EURUSD, multiple resolutions)
- ✅ Uploads updated CSVs to GCS bucket
- ✅ Error handling per dataset (partial failures don't crash)
- ✅ Detailed logging for monitoring

**Configuration**:
```python
DATASETS = [
    ('GOLD', 'M15', 10000),   # Gold 15-min, 10K bars (~70 days)
    ('GOLD', 'M5', 5000),     # Gold 5-min, 5K bars (~17 days)
    ('GOLD', 'M5', 3000),     # Gold 5-min, 3K bars (~10 days)
    ('EURUSD', 'M15', 10000), # EUR/USD 15-min, 10K bars
    ('EURUSD', 'M15', 2000),  # EUR/USD 15-min, 2K bars
]
```

**Dependencies**:
- `src.api.capital_client`: Authentication & API requests
- `src.data.cache_data`: Incremental data fetching logic
- `google-cloud-storage`: Upload to GCS bucket

### 2. Cloud Scheduler Job (`data-updater-cron`)

**Schedule**: Every 30 minutes (UTC)
- Cron expression: `*/30 * * * *`
- Runs at: :00 and :30 of every hour

**Intelligent Updates**:
- **M5 (5-minute) charts**: Updates every run (30 minutes → ~6 new bars)
- **M15 (15-minute) charts**: Updates every 2 hours (→ 8 new bars)
- Function checks GCS metadata and skips datasets that aren't stale yet

**Why 30 minutes?**
- Keeps intraday M5 data fresh (critical for 5-min strategies)
- M15 data intelligently updates less often (every 4 runs = 2 hours)
- API-efficient: Incremental fetches are tiny (6-8 bars)
- Capital.com rate limits respected

**Configuration**:
- Timeout: 540s (9 minutes)
- Authentication: OIDC with service account
- Retry: Automatic Cloud Scheduler retry on failure
- Alerting: Monitor via Cloud Logging

### 3. Cache Data Module (`src/data/cache_data.py`)

**Purpose**: Core logic for incremental data fetching

**Features**:
```python
def cache_data(client, epic, resolution='M15', max_bars=10000, force_refresh=False):
    """
    Incremental data fetching:
    1. Check if cached data exists
    2. Load metadata (last fetch time)
    3. If data < 1 hour old: return cached
    4. Else: fetch ONLY new bars since last timestamp
    5. Merge with existing data
    6. Save + update metadata
    """
```

**Metadata Tracking** (`.fetch_metadata.json`):
```json
{
  "GOLD_M15_10000": {
    "last_fetch": "2026-03-05T10:30:00",
    "bars": 10000,
    "last_bar": "2026-03-05T10:15:00"
  }
}
```

**Incremental API Request**:
```python
# Only fetches bars AFTER last_timestamp
GET /api/v1/prices/{epic}?resolution=MINUTE_15&from=2026-03-05T10:15:00&max=1000
```

## Data Flow

### Initial Setup (One-time)
1. Upload baseline CSV files to GCS bucket
   ```bash
   gsutil -m cp data/*.csv gs://BUCKET_NAME/data/
   ```

### Scheduled Updates (Every 30 minutes, intelligent)
1. **Cloud Scheduler** triggers HTTP POST → Cloud Function
2. **Cloud Function** authenticates with Capital.com
3. For each dataset:
   - Check GCS blob metadata (last updated timestamp)
   - If stale by timeframe rules (M5: 30min, M15: 2hr):
     - Download current CSV from GCS (or use cached local)
     - Read metadata to find last fetch timestamp
     - Fetch only NEW bars from Capital.com API (`from=last_timestamp`)
     - Append new bars to DataFrame
     - Keep only most recent `max_bars` (rolling window)
     - Save CSV locally
     - Upload to GCS bucket (overwrite)
   - Else: Skip (not stale yet)
4. Return JSON summary:
   ```json
   {
     "timestamp": "2026-03-05T14:00:00",
     "summary": {
       "total": 5,
       "successful": 5,
       "failed": 0
     },
     "duration_seconds": 12.3
   }
   ```

### Optimization Request
1. **Worker** receives optimization request
2. Worker calls `ensure_csv_from_gcs(epic, resolution, max_bars)`
3. If not cached locally: download from GCS bucket
4. Run backtest with FRESH data
5. Return results

## Benefits

### ✅ Always Fresh Data
- Market data intelligently updated:
  - M5 timeframes: Every 30 minutes
  - M15 timeframes: Every 2 hours
- Optimizations use recent market conditions
- No stale data issues

### ✅ Efficient API Usage
- **Incremental fetching**: Only fetch new bars (not full history)
- **Metadata tracking**: Skip updates if < 1 hour old
- Example: M15 chart with 4-hour update interval fetches only 16 bars (vs 10,000)

### ✅ Cost Optimization
- Minimal data transfer (only deltas)
- Single CSV file in GCS (overwrite, not versions)
- Function runs quickly (~10-20 seconds typical)

### ✅ Reliability
- Partial failures don't crash (per-dataset error handling)
- Cloud Scheduler retries on failure
- Detailed logs for debugging

### ✅ Scalability
- Easy to add new instruments/resolutions
- Function scales to zero when not running
- No persistent infrastructure to manage

## Deployment

### Prerequisites
1. Capital.com API credentials in Secret Manager (`apicredentials`)
2. GCS bucket exists (`double-venture-442318-k8-optimization-results`)
3. Service account with permissions:
   - Cloud Functions Invoker
   - Secret Manager Secret Accessor
   - Storage Object Admin (for bucket)

### Deploy
```bash
cd cloud-function
./deploy-data-updater.sh
```

This script:
1. Deploys Cloud Function (Gen2, Python 3.11)
2. Creates Cloud Scheduler job (cron: `*/30 * * * *` - every 30 min)
3. Optionally triggers test run

### Manual Operations

**Trigger Update Now**:
```bash
gcloud scheduler jobs run data-updater-cron --location=us-central1
```

**View Logs**:
```bash
gcloud functions logs read data-updater --gen2 --region=us-central1 --limit=50
```

**Pause Scheduled Updates**:
```bash
gcloud scheduler jobs pause data-updater-cron --location=us-central1
```

**Resume Scheduled Updates**:
```bash
gcloud scheduler jobs resume data-updater-cron --location=us-central1
```

**Change Schedule** (e.g., every 2 hours):
```bash
gcloud scheduler jobs update http data-updater-cron \
  --location=us-central1 \
  --schedule="0 */2 * * *"
```

**Force Full Refresh** (re-download all data):
```bash
# Modify data_updater.py temporarily:
cache_data(client, epic, resolution, max_bars, force_refresh=True)

# Or delete metadata file in GCS to trigger full fetch
```

## Monitoring

### Key Metrics

**Success Rate**:
```bash
gcloud logging read "resource.type=cloud_function 
  AND resource.labels.function_name=data-updater
  AND jsonPayload.summary.successful" \
  --limit=10 --format=json \
  | jq '.[] | {time: .timestamp, successful: .jsonPayload.summary.successful, failed: .jsonPayload.summary.failed}'
```

**Duration**:
```bash
gcloud logging read "resource.type=cloud_function 
  AND resource.labels.function_name=data-updater
  AND jsonPayload.duration_seconds" \
  --limit=10 --format=json \
  | jq '.[] | {time: .timestamp, duration: .jsonPayload.duration_seconds}'
```

**Errors**:
```bash
gcloud logging read "resource.type=cloud_function 
  AND resource.labels.function_name=data-updater
  AND severity>=ERROR" \
  --limit=20
```

### Alerts (Optional)

Create alerting policy for:
- Function execution failures
- High failure rate (> 50% of datasets fail)
- Long execution time (> 300s)

## Cost Estimate

### Capital.com API Costs
- **Free tier**: 100 requests/minute (demo account)
- **Incremental fetches**: ~5 API calls per update cycle
- **Monthly**: ~7,200 API calls (5 datasets × 48 runs/day × 30 days)
  - But intelligent skipping reduces actual calls: M5 updates 48×, M15 updates 12× per day
  - **Effective**: ~2,160 API calls/month ((3 M5 datasets × 48) + (2 M15 datasets × 12)) × 30
- **Cost**: $0 (well within free tier)

### GCP Costs

**Cloud Function** (Gen2):
- Invocations: 1,440/month (48 per day)
- Duration: ~10s average (most datasets skipped per run)
- Memory: 512 MB
- **Cost**: ~$0.20/month (mostly free tier)

**Cloud Scheduler**:
- Jobs: 1
- **Cost**: $0.10/month (first 3 jobs free in some regions)

**Cloud Storage**:
- Storage: ~500 KB (5 CSV files)
- Operations: ~1,440 writes/month (but only when data actually updates)
- **Cost**: ~$0.01/month

**Total**: < $0.35/month 🎉

*Still incredibly cost-effective with 8× more frequent updates*

## Troubleshooting

### Issue: "Authentication failed"
**Cause**: `apicredentials` secret not configured or wrong format

**Fix**:
```bash
# Check secret exists
gcloud secrets describe apicredentials

# Recreate if needed
python3 scripts/setup_credentials.py
```

### Issue: "GCS upload failed"
**Cause**: Service account lacks Storage Object Admin role

**Fix**:
```bash
gsutil iam ch serviceAccount:SERVICE_ACCOUNT_EMAIL:objectAdmin \
  gs://BUCKET_NAME
```

### Issue: "No new data available"
**Cause**: Markets closed or last update was < 1 hour ago

**Resolution**: Normal behavior, check logs for timestamp

### Issue: Function timeout (540s exceeded)
**Cause**: Capital.com API slow or network issues

**Fix**:
- Check Capital.com API status
- Reduce number of datasets
- Increase memory (faster execution)

## Future Enhancements

### 1. Data Quality Checks
- Validate bar count before upload
- Detect gaps in timestamp series
- Alert on suspicious price movements

### 2. Multi-Region Redundancy
- Deploy function in multiple regions
- Use Cloud Storage Transfer for cross-region backup

### 3. Adaptive Scheduling
- Update more frequently during market hours
- Reduce frequency on weekends

### 4. Historical Backfill
- Separate job to fetch older data
- Build longer historical datasets (1+ years)

### 5. Real-time Streaming
- Use Capital.com WebSocket API
- Stream live data to Firestore/BigQuery
- Supplement CSV batch updates

## Security

### Credentials
- ✅ Capital.com credentials stored in Secret Manager
- ✅ Not embedded in code or environment variables
- ✅ Automatic rotation supported

### Access Control
- ✅ Function requires authentication (OIDC)
- ✅ Service account principle of least privilege
- ✅ Bucket not publicly accessible

### Audit Logging
- ✅ All function invocations logged
- ✅ API requests tracked
- ✅ GCS uploads audited

## Summary

The automated data update architecture ensures:
- 📊 **Fresh data**: M5 updated every 30min, M15 every 2hr (intelligent)
- 💰 **Cost-effective**: < $0.35/month
- ⚡ **Efficient**: Incremental fetching only
- 🛡️ **Reliable**: Error handling + retries
- 📈 **Scalable**: Easy to add instruments
- 🔒 **Secure**: Credentials in Secret Manager

Workers always have recent market data for optimization runs!
