#!/usr/bin/env python3
"""
Log Uploader Script for Trading Bot
Uploads bot logs to Google Cloud Storage for remote access
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from google.cloud import storage
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def upload_logs_to_gcs():
    """Upload trading bot logs to GCS bucket"""
    
    # Configuration
    project_id = os.getenv('GOOGLE_CLOUD_PROJECT', 'double-venture-442318-k8')
    bucket_name = os.getenv('GCS_LOGS_BUCKET', f'{project_id}-trading-logs')
    logs_dir = Path('/opt/trading-bot/logs')
    
    if not logs_dir.exists():
        print(f"❌ Logs directory not found: {logs_dir}")
        return False
    
    try:
        # Initialize storage client
        storage_client = storage.Client(project=project_id)
        
        # Get or create bucket
        try:
            bucket = storage_client.bucket(bucket_name)
            if not bucket.exists():
                bucket = storage_client.create_bucket(bucket_name, location='EU')
                print(f"✅ Created bucket: {bucket_name}")
            else:
                bucket = storage_client.get_bucket(bucket_name)
        except Exception as e:
            print(f"⚠️  Using existing bucket: {bucket_name}")
            bucket = storage_client.bucket(bucket_name)
        
        # Upload all log files
        uploaded_count = 0
        today = datetime.now().strftime('%Y-%m-%d')
        
        for log_file in logs_dir.glob('*.log'):
            if log_file.stat().st_size == 0:
                continue  # Skip empty files
                
            # Create GCS path: logs/YYYY-MM-DD/filename.log
            gcs_path = f"logs/{today}/{log_file.name}"
            blob = bucket.blob(gcs_path)
            
            # Upload with metadata
            blob.upload_from_filename(
                str(log_file),
                content_type='text/plain'
            )
            blob.metadata = {
                'uploaded_at': datetime.now().isoformat(),
                'bot_instance': os.getenv('HOSTNAME', 'unknown'),
                'file_size': str(log_file.stat().st_size)
            }
            blob.patch()
            
            uploaded_count += 1
            print(f"✅ Uploaded: {log_file.name} → gs://{bucket_name}/{gcs_path}")
        
        # Create latest log symlink
        latest_log = logs_dir / 'trading_bot.log'
        if latest_log.exists() or latest_log.is_symlink():
            target = latest_log.resolve() if latest_log.is_symlink() else latest_log
            if target.exists():
                latest_blob = bucket.blob(f"logs/latest.log")
                latest_blob.upload_from_filename(str(target), content_type='text/plain')
                print(f"✅ Uploaded latest log: gs://{bucket_name}/logs/latest.log")
        
        print(f"\n📊 Upload Summary:")
        print(f"   Bucket: gs://{bucket_name}")
        print(f"   Files uploaded: {uploaded_count}")
        print(f"   Date: {today}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error uploading logs: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = upload_logs_to_gcs()
    sys.exit(0 if success else 1)
