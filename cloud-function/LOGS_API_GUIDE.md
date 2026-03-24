# Trading Bot Logs - GCS Integration

> **📝 Note**: This guide describes **historical log archives** (GCS storage).  
> For **real-time log streaming** (Firestore, last 24h), see [`UNIFIED_API_GUIDE.md`](./UNIFIED_API_GUIDE.md#-live-logs-new) - `/bot/logs/live` endpoint.

## 🚀 Quick Comparison

| Feature | **Live Logs** (`/bot/logs/live`) | **Historical Logs** (This Guide) |
|---------|----------------------------------|----------------------------------|
| **Purpose** | Real-time monitoring | Historical analysis & audit trail |
| **Source** | Firestore (structured) | GCS Bucket (text files) |
| **Retention** | 24 hours | Permanent archives |
| **Latency** | ~5 seconds (real-time) | 15 minutes (batch upload) |
| **Format** | JSON with timestamps & levels | Plain text log files |
| **Cost** | ~$1/month | ~$0.02/GB/month |

**Use This Guide For**: Accessing logs older than 24 hours, downloading complete log files, audit trails.

---

## Overview

The trading bot automatically uploads logs to Google Cloud Storage every 15 minutes, and provides HTTP webhooks to access them from your UI.

## Architecture

```
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│  Trading Bot    │   →     │   GCS Bucket    │   ←     │  Cloud Function │
│  (Server)       │ Upload  │  (Logs Storage) │  Read   │  (Logs API)     │
└─────────────────┘         └─────────────────┘         └─────────────────┘
                                                                   ↓
                                                         ┌─────────────────┐
                                                         │   Your UI       │
                                                         │   (Webhook)     │
                                                         └─────────────────┘
```

## Setup

### 1. Create GCS Bucket (One-time)

```bash
# The bucket will be auto-created on first log upload
# Or create manually:
gsutil mb -l eu gs://double-venture-442318-k8-trading-logs
```

### 2. Deploy Logs API (One-time)

```bash
cd cloud-function
chmod +x deploy/deploy_logs_api.sh
./deploy/deploy_logs_api.sh
```

This creates two Cloud Function endpoints:
- **Get Logs**: Retrieve log files
- **List Dates**: Get available log dates

### 3. Automatic Log Uploads (Already configured)

The deployment script sets up:
- **Systemd timer**: Uploads logs every 15 minutes
- **Runs automatically**: Started on server boot

## API Endpoints

### Base URL
```
https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-logs-api-{function}
```

### 1. List Available Dates

**Endpoint**: `/trading-bot-logs-api-list`

```bash
curl 'https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-logs-api-list'
```

**Response**:
```json
{
  "dates": ["2026-03-24", "2026-03-23", "2026-03-22"],
  "count": 3,
  "bucket": "double-venture-442318-k8-trading-logs",
  "latest_url": "?date=2026-03-24"
}
```

### 2. Get Logs for Date

**Endpoint**: `/trading-bot-logs-api-get`

**Parameters**:
- `date` (optional): Date in YYYY-MM-DD format (default: today)
- `file` (optional): Specific log file name
- `lines` (optional): Number of lines to return (default: 100, max: 1000)
- `format` (optional): `json` or `text` (default: json)

**Examples**:

```bash
# List all log files for today
curl 'https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-logs-api-get'

# Get today's logs (last 100 lines)
curl 'https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-logs-api-get?file=bot-output.log'

# Get specific date and file (last 500 lines)
curl 'https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-logs-api-get?date=2026-03-24&file=bot-error.log&lines=500'

# Get logs as plain text
curl 'https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-logs-api-get?file=bot-output.log&format=text'

# Get latest log (symlink)
curl 'https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-logs-api-get?file=latest.log'
```

**Response (JSON)**:
```json
{
  "file": "bot-output.log",
  "date": "2026-03-24",
  "lines": [
    "2026-03-24 06:01:02 - INFO - Bot starting...",
    "2026-03-24 06:01:05 - INFO - Connected to Capital.com..."
  ],
  "total_lines": 100,
  "bucket": "double-venture-442318-k8-trading-logs",
  "path": "logs/2026-03-24/bot-output.log"
}
```

## React/UI Integration

### Example: Fetch Latest Logs

```typescript
// Fetch latest logs
async function fetchBotLogs(date?: string, lines: number = 100) {
  const params = new URLSearchParams({
    file: 'bot-output.log',
    lines: lines.toString(),
    ...(date && { date })
  });
  
  const response = await fetch(
    `https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-logs-api-get?${params}`
  );
  
  if (!response.ok) {
    throw new Error('Failed to fetch logs');
  }
  
  return await response.json();
}

// Usage
const logs = await fetchBotLogs();
console.log(logs.lines);
```

### Example: List Available Dates

```typescript
async function fetchAvailableDates() {
  const response = await fetch(
    'https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-logs-api-list'
  );
  return await response.json();
}

// Usage
const { dates } = await fetchAvailableDates();
```

### Example: Real-time Log Viewer Component

```tsx
import React, { useState, useEffect } from 'react';

function LogViewer() {
  const [logs, setLogs] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchLogs() {
      try {
        const response = await fetch(
          'https://europe-west1-double-venture-442318-k8.cloudfunctions.net/trading-bot-logs-api-get?file=bot-output.log&lines=200'
        );
        const data = await response.json();
        setLogs(data.lines || []);
      } catch (error) {
        console.error('Error fetching logs:', error);
      } finally {
        setLoading(false);
      }
    }

    fetchLogs();
    // Refresh logs every 30 seconds
    const interval = setInterval(fetchLogs, 30000);
    return () => clearInterval(interval);
  }, []);

  if (loading) return <div>Loading logs...</div>;

  return (
    <div className="log-viewer">
      <h2>Trading Bot Logs</h2>
      <pre className="log-output">
        {logs.map((line, i) => (
          <div key={i}>{line}</div>
        ))}
      </pre>
    </div>
  );
}
```

## Manual Commands

### Upload Logs Manually

```bash
# On the server
ssh -i ~/.ssh/stockscreener_server root@204.168.191.150
cd /opt/trading-bot
source venv/bin/activate
python3 scripts/upload_logs.py
```

### Check Upload Timer Status

```bash
ssh -i ~/.ssh/stockscreener_server root@204.168.191.150
systemctl status log-uploader.timer
systemctl list-timers log-uploader.timer
```

### Trigger Manual Upload

```bash
ssh -i ~/.ssh/stockscreener_server root@204.168.191.150
systemctl start log-uploader.service
journalctl -u log-uploader.service -n 20
```

### View Logs in GCS

```bash
# List all logs
gsutil ls gs://double-venture-442318-k8-trading-logs/logs/

# List logs for specific date
gsutil ls gs://double-venture-442318-k8-trading-logs/logs/2026-03-24/

# Download a log file
gsutil cp gs://double-venture-442318-k8-trading-logs/logs/2026-03-24/bot-output.log .

# View file directly
gsutil cat gs://double-venture-442318-k8-trading-logs/logs/latest.log | tail -100
```

## Log Files Structure

```
gs://double-venture-442318-k8-trading-logs/
└── logs/
    ├── latest.log               # Symlink to most recent log
    ├── 2026-03-24/
    │   ├── bot-output.log       # Standard output
    │   ├── bot-error.log        # Standard error (includes INFO logs)
    │   └── trading_bot_20260324_060102.log  # Timestamped log file
    ├── 2026-03-23/
    │   ├── bot-output.log
    │   └── ...
    └── ...
```

## Troubleshooting

### Logs not uploading

Check timer status:
```bash
systemctl status log-uploader.timer
systemctl status log-uploader.service
```

Check recent upload attempts:
```bash
journalctl -u log-uploader.service -n 50
```

### Permission errors

Verify service account has Storage permissions:
```bash
# Check service account file exists
ls -l /opt/trading-bot/.gcp/trading-bot-sa.json

# Test GCS access
gsutil ls gs://double-venture-442318-k8-trading-logs/
```

### API not returning logs

1. Check if logs are in GCS:
   ```bash
   gsutil ls gs://double-venture-442318-k8-trading-logs/logs/
   ```

2. Check Cloud Function logs:
   ```bash
   gcloud functions logs read trading-bot-logs-api-get --limit=50
   ```

## Security

- **Public API**: Logs API is publicly accessible (no authentication required)
- **Consider**: Add API key or authentication for production
- **Data**: Logs stored in GCS are private by default (only accessible via API)

## Cost Optimization

- **Storage**: Logs are small (~1-5 MB/day)
- **API Calls**: Free tier covers typical usage
- **Cleanup**: Consider adding lifecycle policy to delete old logs:

```bash
# Create lifecycle policy (delete logs older than 30 days)
cat > lifecycle.json << 'EOF'
{
  "rule": [
    {
      "action": {"type": "Delete"},
      "condition": {
        "age": 30,
        "matchesPrefix": ["logs/"]
      }
    }
  ]
}
EOF

gsutil lifecycle set lifecycle.json gs://double-venture-442318-k8-trading-logs
```

## Next Steps

1. ✅ Logs are automatically uploaded every 15 minutes
2. Deploy the Logs API: `./deploy/deploy_logs_api.sh`
3. Integrate webhooks into your UI
4. Set up log cleanup policy (optional)
5. Add authentication to API (optional)
