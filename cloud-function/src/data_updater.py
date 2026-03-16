#!/usr/bin/env python3
"""
Cloud Function for scheduled data updates
Fetches delta/incremental bars from Capital.com and updates GCS bucket

Triggered by Cloud Scheduler every 4-6 hours to keep data fresh
"""

import functions_framework
import logging
import os
import json
import io
import pandas as pd
from datetime import datetime, timedelta
from google.cloud import storage
from src.api.capital_client import create_client_from_env
from src.data.cache_data import cache_data

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
BUCKET_NAME = os.getenv('GCS_BUCKET', 'double-venture-442318-k8-optimization-results')
DATA_FOLDER = 'data'

# Update intervals based on timeframe (intelligent scheduling)
UPDATE_INTERVALS = {
    'M5': timedelta(minutes=30),   # M5: Update every 30 minutes (real-time)
    'M15': timedelta(hours=2),     # M15: Update every 2 hours (less frequent)
}

# Scheduler enable/disable flag (controlled via API)
SCHEDULER_ENABLED_FILE = 'scheduler_enabled.flag'
INSTRUMENTS_CONFIG_FILE = 'instruments_config.json'

# Default datasets (used if config file doesn't exist)
DEFAULT_DATASETS = [
    # Forex
    ('EURUSD', 'M15', 10000), # EUR/USD 15-min, 10K bars (~70 days)
    ('EURUSD', 'M15', 2000),  # EUR/USD 15-min, 2K bars (~14 days)
    ('EURGBP', 'M15', 5000),  # EUR/GBP 15-min, 5K bars
    ('GBPUSD', 'M15', 5000),  # GBP/USD 15-min, 5K bars
    
    # Commodities
    ('GOLD', 'M15', 10000),   # Gold 15-min, 10K bars
    ('GOLD', 'M5', 5000),     # Gold 5-min, 5K bars (~17 days)
    ('GOLD', 'M5', 3000),     # Gold 5-min, 3K bars (~10 days)
    ('SILVER', 'M15', 5000),  # Silver 15-min, 5K bars
    
    # Crypto
    ('BITCOIN', 'M15', 10000), # Bitcoin 15-min, 10K bars
    ('BITCOIN', 'M5', 5000),   # Bitcoin 5-min, 5K bars
    
    # Indices
    ('US30', 'M15', 5000),    # Dow Jones 15-min, 5K bars
    ('NASDAQ', 'M15', 5000),  # NASDAQ 15-min, 5K bars
]


def get_instruments_config():
    """Load instruments configuration from GCS"""
    try:
        logger.info(f"📥 Loading instruments config from gs://{BUCKET_NAME}/{INSTRUMENTS_CONFIG_FILE}")
        storage_client = storage.Client()
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(INSTRUMENTS_CONFIG_FILE)
        
        if blob.exists():
            logger.info(f"✅ Config file exists, loading...")
            config_json = blob.download_as_text()
            config = json.loads(config_json)
            instruments = config.get('instruments', DEFAULT_DATASETS)
            logger.info(f"✅ Loaded {len(instruments)} instruments from config")
            logger.info(f"   Config instruments: {instruments[:3]}...")  # Show first 3
            return instruments
        else:
            logger.warning(f"⚠️  Config file doesn't exist. Initializing with {len(DEFAULT_DATASETS)} defaults.")
            # Initialize with defaults
            save_instruments_config(DEFAULT_DATASETS)
            return DEFAULT_DATASETS
    except Exception as e:
        logger.error(f"❌ Failed to load instruments config: {e}. Using defaults.")
        logger.exception(e)  # Full stack trace
        return DEFAULT_DATASETS


def save_instruments_config(instruments):
    """Save instruments configuration to GCS"""
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(INSTRUMENTS_CONFIG_FILE)
        
        config = {
            'instruments': instruments,
            'updated': datetime.now().isoformat()
        }
        blob.upload_from_string(json.dumps(config, indent=2))
        logger.info(f"✅ Saved {len(instruments)} instruments to config")
        return True
    except Exception as e:
        logger.error(f"Failed to save instruments config: {e}")
        return False


def upload_to_gcs(local_path: str, gcs_path: str):
    """Upload file to GCS bucket"""
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(gcs_path)
        blob.upload_from_filename(local_path)
        logger.info(f"✅ Uploaded: gs://{BUCKET_NAME}/{gcs_path}")
        return True
    except Exception as e:
        logger.error(f"❌ Upload failed for {gcs_path}: {e}")
        return False


def get_last_update_time(epic: str, resolution: str, max_bars: int) -> datetime:
    """Get last update time from GCS metadata"""
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(BUCKET_NAME)
        gcs_path = f"{DATA_FOLDER}/{epic}_{resolution}_{max_bars}bars.csv"
        blob = bucket.blob(gcs_path)
        
        if blob.exists():
            blob.reload()  # Refresh metadata
            return blob.updated
        else:
            # File doesn't exist, needs initial upload
            return datetime.min.replace(tzinfo=None)
    except Exception as e:
        logger.warning(f"⚠️  Could not get metadata for {epic}_{resolution}: {e}")
        return datetime.min.replace(tzinfo=None)


def needs_update(epic: str, resolution: str, max_bars: int) -> bool:
    """Check if dataset needs updating based on timeframe and last update"""
    last_update = get_last_update_time(epic, resolution, max_bars)
    
    # Make last_update timezone-naive for comparison
    if last_update.tzinfo is not None:
        last_update = last_update.replace(tzinfo=None)
    
    interval = UPDATE_INTERVALS.get(resolution, timedelta(hours=4))  # Default 4hr
    time_since_update = datetime.now() - last_update
    
    should_update = time_since_update >= interval
    
    if should_update:
        logger.info(f"✓ {epic} {resolution}: Updated {time_since_update.total_seconds()/60:.1f}m ago → NEEDS UPDATE")
    else:
        remaining = interval - time_since_update
        logger.info(f"⏭  {epic} {resolution}: Updated {time_since_update.total_seconds()/60:.1f}m ago → Next in {remaining.total_seconds()/60:.1f}m")
    
    return should_update


def update_dataset(client, epic: str, resolution: str, max_bars: int, force: bool = False):
    """Update a single dataset with incremental fetch (only if needed)
    
    Maintains ONE master file per instrument/timeframe.
    Consolidates any existing files with different bar counts.
    
    Args:
        force: If True, bypass time checks and fetch full dataset
    """
    
    # Check if update is needed based on timeframe (skip check if force=True)
    if not force and not needs_update(epic, resolution, max_bars):
        return True  # Skip but count as success
    
    logger.info(f"\n{'='*70}")
    logger.info(f"📊 Updating: {epic} {resolution} ({max_bars} bars){'  [FORCE REFRESH]' if force else ''}")
    logger.info(f"{'='*70}")
    
    try:
        # Fetch data (force full refresh if requested, otherwise use incremental)
        df = cache_data(client, epic, resolution, max_bars, force_refresh=force)
        
        if df is None or len(df) == 0:
            logger.warning(f"⚠️  No data returned for {epic} {resolution}")
            return False
        
        # Get local file path
        local_file = f"data/{epic}_{resolution}_{max_bars}bars.csv"
        
        if not os.path.exists(local_file):
            logger.error(f"❌ Local file not found: {local_file}")
            return False
        
        # Check for existing files in GCS with different bar counts
        storage_client = storage.Client()
        bucket = storage_client.bucket(BUCKET_NAME)
        
        # List all files for this instrument/timeframe
        prefix = f"{DATA_FOLDER}/{epic}_{resolution}_"
        existing_blobs = list(bucket.list_blobs(prefix=prefix))
        existing_files = [b for b in existing_blobs if b.name.endswith('.csv')]
        
        # If multiple files exist, consolidate them first
        if len(existing_files) > 1:
            logger.info(f"🔀 Found {len(existing_files)} existing files for {epic} {resolution}")
            logger.info(f"   Consolidating before update...")
            
            # Download and merge all existing files
            all_dfs = [df]  # Start with new data
            
            for blob in existing_files:
                try:
                    csv_content = blob.download_as_text()
                    import io
                    existing_df = pd.read_csv(io.StringIO(csv_content), index_col=0, parse_dates=True)
                    all_dfs.append(existing_df)
                    logger.info(f"   ✓ Merged {blob.name.split('/')[-1]} ({len(existing_df)} bars)")
                except Exception as e:
                    logger.warning(f"   ⚠️  Failed to read {blob.name}: {e}")
            
            # Combine all dataframes
            df = pd.concat(all_dfs, axis=0)
            df = df[~df.index.duplicated(keep='first')]
            df.sort_index(inplace=True)
            
            # Keep only requested bars (trim to max_bars)
            if len(df) > max_bars:
                df = df.iloc[-max_bars:]
            
            logger.info(f"   ✅ Consolidated: {len(df)} unique bars")
            
            # Update local file with consolidated data
            df.to_csv(local_file)
            
            # Delete old files from GCS
            for blob in existing_files:
                try:
                    blob.delete()
                    logger.info(f"   🗑️  Deleted old file: {blob.name.split('/')[-1]}")
                except Exception as e:
                    logger.warning(f"   ⚠️  Failed to delete {blob.name}: {e}")
        
        # Use actual bar count in filename (not requested)
        actual_bars = len(df)
        master_filename = f"{epic}_{resolution}_{actual_bars}bars.csv"
        gcs_path = f"{DATA_FOLDER}/{master_filename}"
        
        # Save with actual bar count
        master_local = f"data/{master_filename}"
        if master_local != local_file:
            df.to_csv(master_local)
        
        success = upload_to_gcs(master_local, gcs_path)
        
        if success:
            logger.info(f"✅ Updated master dataset: {epic} {resolution}")
            logger.info(f"   Bars: {actual_bars}")
            logger.info(f"   Range: {df.index[0]} → {df.index[-1]}")
            logger.info(f"   Latest: {df.index[-1]}")
            logger.info(f"   File: {master_filename}")
        
        return success
        
    except Exception as e:
        logger.error(f"❌ Error updating {epic} {resolution}: {e}")
        logger.exception(e)
        return False


def is_scheduler_enabled() -> bool:
    """Check if scheduler is enabled via GCS flag file"""
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(SCHEDULER_ENABLED_FILE)
        
        if not blob.exists():
            # Default: enabled
            return True
        
        # Read flag value
        content = blob.download_as_text().strip().lower()
        return content == 'enabled'
    except Exception as e:
        logger.warning(f"Failed to check scheduler flag: {e}. Defaulting to enabled.")
        return True


@functions_framework.http
def update_market_data(request):
    """
    Cloud Function entry point
    
    Triggered by Cloud Scheduler to update all market data
    Can also be triggered manually via HTTP POST with optional filters:
    
    POST body (optional):
    {
      "instruments": ["GOLD", "EURUSD"],  // Filter by instrument
      "timeframes": ["M5"],                 // Filter by timeframe
      "force": false                         // Skip time checks if true
    }
    
    Returns:
        JSON response with update status
    """
    # Check if scheduler is enabled
    if not is_scheduler_enabled():
        logger.info("⏸️  Scheduler is disabled. Skipping data update.")
        return jsonify({
            'status': 'skipped',
            'message': 'Scheduler is currently disabled',
            'timestamp': datetime.now().isoformat()
        }), 200
    
    # Parse request body for filters
    filters = {}
    if request.method == 'POST':
        try:
            body = request.get_json(silent=True) or {}
            filters['instruments'] = body.get('instruments', [])
            filters['timeframes'] = body.get('timeframes', [])
            filters['force'] = body.get('force', False)
        except:
            pass
    
    start_time = datetime.now()
    
    # Load instruments from config
    DATASETS = get_instruments_config()
    
    # Apply filters
    filtered_datasets = DATASETS
    if filters.get('instruments'):
        filtered_datasets = [ds for ds in filtered_datasets if ds[0] in filters['instruments']]
    if filters.get('timeframes'):
        filtered_datasets = [ds for ds in filtered_datasets if ds[1] in filters['timeframes']]
    
    logger.info("\n" + "="*70)
    logger.info("📡 Starting scheduled data update")
    logger.info(f"   Timestamp: {start_time.isoformat()}")
    logger.info(f"   Bucket: gs://{BUCKET_NAME}")
    logger.info(f"   Total datasets: {len(DATASETS)}")
    logger.info(f"   Filtered datasets: {len(filtered_datasets)}")
    if filters.get('instruments'):
        logger.info(f"   Instrument filter: {filters['instruments']}")
    if filters.get('timeframes'):
        logger.info(f"   Timeframe filter: {filters['timeframes']}")
    logger.info("="*70)
    
    results = {
        'timestamp': start_time.isoformat(),
        'filters': filters,
        'datasets': {},
        'summary': {
            'total': len(filtered_datasets),
            'available': len(DATASETS),
            'successful': 0,
            'failed': 0
        }
    }
    
    try:
        # Create Capital.com API client
        logger.info("\n🔐 Authenticating with Capital.com...")
        client = create_client_from_env()
        logger.info("✅ Authentication successful")
        
        # Update each dataset
        for epic, resolution, max_bars in filtered_datasets:
            dataset_key = f"{epic}_{resolution}_{max_bars}"
            success = update_dataset(client, epic, resolution, max_bars, force=filters.get('force', False))
            
            results['datasets'][dataset_key] = {
                'success': success,
                'timestamp': datetime.now().isoformat()
            }
            
            if success:
                results['summary']['successful'] += 1
            else:
                results['summary']['failed'] += 1
        
        # Calculate duration
        duration = (datetime.now() - start_time).total_seconds()
        results['duration_seconds'] = duration
        
        # Log summary
        logger.info("\n" + "="*70)
        logger.info("📊 Update Summary:")
        logger.info(f"   Total: {results['summary']['total']}")
        logger.info(f"   Successful: {results['summary']['successful']}")
        logger.info(f"   Failed: {results['summary']['failed']}")
        logger.info(f"   Duration: {duration:.1f}s")
        logger.info("="*70 + "\n")
        
        # Return success if at least half succeeded
        status_code = 200 if results['summary']['failed'] < results['summary']['successful'] else 500
        
        return (json.dumps(results, indent=2), status_code, {'Content-Type': 'application/json'})
        
    except Exception as e:
        error_msg = f"Fatal error during update: {str(e)}"
        logger.error(f"\n❌ {error_msg}\n")
        
        results['error'] = error_msg
        results['summary']['failed'] = len(DATASETS)
        
        return (json.dumps(results, indent=2), 500, {'Content-Type': 'application/json'})


if __name__ == '__main__':
    """Test locally"""
    print("\n🧪 Testing data updater locally...\n")
    
    # Mock Flask request
    class MockRequest:
        def __init__(self):
            self.method = 'POST'
            self.args = {}
    
    response, status, headers = update_market_data(MockRequest())
    print(f"\nStatus: {status}")
    print(response)
