#!/usr/bin/env python3
"""
📤 Upload Trading Bot Logs to GCS

Uploads completed log files to GCS for API access via /logs/dates endpoint.
Runs every minute via systemd timer.
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from google.cloud import storage

# Configuration
LOGS_DIR = Path("/opt/trading-bot/logs")
GCS_BUCKET = os.getenv("GCS_LOGS_BUCKET", "double-venture-442318-k8-trading-logs")
GCS_PREFIX = "logs/"

# Only upload logs older than 2 minutes (to avoid uploading incomplete files)
MIN_AGE_MINUTES = 2

def upload_logs():
    """Upload completed log files to GCS"""
    try:
        # Initialize GCS client
        storage_client = storage.Client()
        bucket = storage_client.bucket(GCS_BUCKET)
        
        # Get current timestamp
        now = datetime.now()
        cutoff_time = now - timedelta(minutes=MIN_AGE_MINUTES)
        
        uploaded_count = 0
        skipped_count = 0
        
        # Find log files
        for log_file in LOGS_DIR.glob("trading_bot_*.log"):
            # Get file modification time
            mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
            
            # Skip if file is too recent (might still be written to)
            if mtime > cutoff_time:
                skipped_count += 1
                continue
            
            # GCS destination path
            blob_name = f"{GCS_PREFIX}{log_file.name}"
            blob = bucket.blob(blob_name)
            
            # Skip if already uploaded (completed logs don't change)
            if blob.exists():
                skipped_count += 1
                continue
            
            # Upload file
            blob.upload_from_filename(str(log_file))
            print(f"✅ Uploaded: {log_file.name} → gs://{GCS_BUCKET}/{blob_name}")
            uploaded_count += 1
        
        if uploaded_count == 0 and skipped_count == 0:
            print("ℹ️  No log files found to upload")
        elif uploaded_count == 0:
            print(f"ℹ️  No new logs to upload ({skipped_count} skipped)")
        else:
            print(f"✅ Upload complete: {uploaded_count} files uploaded, {skipped_count} skipped")
        
        return 0
        
    except Exception as e:
        print(f"❌ Error uploading logs: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(upload_logs())
