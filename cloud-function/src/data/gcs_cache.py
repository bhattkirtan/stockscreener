"""
GCS Cache Manager - Download and cache CSV input data from Google Cloud Storage
"""

import os
import logging
import pandas as pd
from pathlib import Path
from google.cloud import storage
from .dataset_manager import get_best_dataset, list_all_datasets, group_datasets_by_instrument_timeframe

# Setup logging
logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = os.environ.get('GCP_PROJECT_ID')
BUCKET_NAME = os.environ.get('GCS_BUCKET', 'double-venture-442318-k8-optimization-results')
LOCAL_CACHE_DIR = Path('/tmp/data')

# Initialize storage client
_storage_client = None


def get_storage_client():
    """Get or create storage client"""
    global _storage_client
    if _storage_client is None:
        _storage_client = storage.Client()
    return _storage_client


def ensure_csv_from_gcs(epic: str, resolution: str, max_bars: int = None) -> Path:
    """
    Ensure CSV file is available locally, downloading from GCS if needed
    
    Enhanced to handle multiple datasets for same instrument/timeframe:
    - If max_bars specified: looks for exact match first
    - If no exact match: finds best available dataset (largest by default)
    - Caches locally to avoid repeated downloads
    
    Args:
        epic: Instrument name (e.g., 'GOLD', 'EURUSD')
        resolution: Timeframe (e.g., 'M5', 'M15')
        max_bars: Number of bars (optional - will auto-select if not specified)
        
    Returns:
        Path to local CSV file
        
    Raises:
        FileNotFoundError: If CSV not found in GCS or locally
    """
    # If max_bars specified, try exact filename first
    if max_bars:
        filename = f"{epic}_{resolution}_{max_bars}bars.csv"
        local_path = LOCAL_CACHE_DIR / filename
        
        # If file exists locally, use it
        if local_path.exists():
            logger.info(f"✅ Using local cache: {filename}")
            return local_path
        
        # Try to download exact file from GCS
        try:
            client = get_storage_client()
            bucket = client.bucket(BUCKET_NAME)
            blob = bucket.blob(f"data/{filename}")
            
            if blob.exists():
                # Ensure local directory exists
                LOCAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                
                # Download file
                logger.info(f"📥 Downloading {filename} from GCS...")
                blob.download_to_filename(str(local_path))
                logger.info(f"✅ Downloaded: {filename} ({local_path.stat().st_size / 1024:.1f} KB)")
                
                return local_path
            else:
                logger.warning(f"⚠️ Exact file not found: {filename}, searching for alternatives...")
        except Exception as e:
            logger.warning(f"⚠️ Failed to download {filename}: {e}, searching for alternatives...")
    
    # No exact match or max_bars not specified - find ALL datasets and consolidate
    logger.info(f"🔍 Finding datasets for {epic} {resolution}...")
    
    # Get all datasets for this instrument/timeframe
    from .dataset_manager import list_all_datasets, group_datasets_by_instrument_timeframe
    all_datasets = list_all_datasets(BUCKET_NAME)
    grouped = group_datasets_by_instrument_timeframe(all_datasets)
    
    key = (epic, resolution)
    if key not in grouped:
        # List available files for debugging
        try:
            available_str = ', '.join([f['filename'] for f in all_datasets[:10]])
            logger.error(f"❌ No dataset found for {epic} {resolution}")
            logger.info(f"📁 Available datasets: {available_str}...")
        except:
            pass
        
        raise FileNotFoundError(
            f"No dataset found for {epic} {resolution} in GCS bucket {BUCKET_NAME}"
        )
    
    matching_datasets = grouped[key]
    
    # If multiple files exist, consolidate them
    if len(matching_datasets) > 1:
        logger.info(f"🔀 Found {len(matching_datasets)} files for {epic} {resolution}, consolidating...")
        
        # Download all files
        client = get_storage_client()
        bucket = client.bucket(BUCKET_NAME)
        all_dfs = []
        
        import io
        for ds in matching_datasets:
            try:
                blob = bucket.blob(ds['gcs_path'])
                csv_content = blob.download_as_text()
                df = pd.read_csv(io.StringIO(csv_content), index_col=0, parse_dates=True)
                all_dfs.append(df)
                logger.info(f"   ✓ Loaded {ds['filename']} ({len(df)} bars)")
            except Exception as e:
                logger.warning(f"   ⚠️  Failed to load {ds['filename']}: {e}")
        
        if not all_dfs:
            raise FileNotFoundError(f"Failed to load any datasets for {epic} {resolution}")
        
        # Combine and deduplicate
        combined = pd.concat(all_dfs, axis=0)
        combined = combined[~combined.index.duplicated(keep='first')]
        combined.sort_index(inplace=True)
        
        logger.info(f"   ✅ Consolidated: {len(combined)} unique bars")
        logger.info(f"   Range: {combined.index[0]} to {combined.index[-1]}")
        
        # Save consolidated version locally
        filename = f"{epic}_{resolution}_{len(combined)}bars.csv"
        local_path = LOCAL_CACHE_DIR / filename
        LOCAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        combined.to_csv(local_path)
        
        logger.info(f"💾 Saved consolidated file: {filename}")
        return local_path
    
    # Single file - download it
    best_dataset = matching_datasets[0]
    filename = best_dataset['filename']
    local_path = LOCAL_CACHE_DIR / filename
    
    # If already cached, use it
    if local_path.exists():
        logger.info(f"✅ Using local cache: {filename} ({best_dataset['bars']} bars)")
        return local_path
    
    # Download from GCS
    try:
        client = get_storage_client()
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob(best_dataset['gcs_path'])
        
        # Ensure local directory exists
        LOCAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        
        # Download file
        logger.info(f"📥 Downloading {filename} from GCS ({best_dataset['bars']} bars)...")
        blob.download_to_filename(str(local_path))
        logger.info(f"✅ Downloaded: {filename} ({local_path.stat().st_size / 1024:.1f} KB)")
        
        return local_path
        
    except Exception as e:
        error_msg = f"Failed to download {filename} from GCS: {str(e)}"
        logger.error(f"❌ {error_msg}")
        raise FileNotFoundError(error_msg)


def list_available_csv_files() -> list:
    """List all CSV files available in the GCS data folder"""
    try:
        client = get_storage_client()
        bucket = client.bucket(BUCKET_NAME)
        
        blobs = bucket.list_blobs(prefix='data/')
        csv_files = [blob.name for blob in blobs if blob.name.endswith('.csv')]
        
        return csv_files
    except Exception as e:
        logger.error(f"Failed to list GCS files: {e}")
        return []


def download_all_csv_files():
    """
    Download all CSV files from GCS data folder to local cache
    
    DEPRECATED: This function downloads all CSV files upfront which is inefficient.
    Instead, use ensure_csv_from_gcs() which downloads files on-demand as needed.
    This provides:
    - Faster startup (no upfront downloads)
    - Less bandwidth usage (only download what's needed)
    - Better scalability (adding files doesn't slow startup)
    """
    try:
        client = get_storage_client()
        bucket = client.bucket(BUCKET_NAME)
        
        # List all CSV files
        blobs = bucket.list_blobs(prefix='data/')
        csv_blobs = [blob for blob in blobs if blob.name.endswith('.csv')]
        
        if not csv_blobs:
            logger.warning("⚠️ No CSV files found in GCS bucket data/ folder")
            return
        
        # Ensure local directory exists
        LOCAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        
        # Download each file
        logger.info(f"📥 Downloading {len(csv_blobs)} CSV files from GCS...")
        for blob in csv_blobs:
            filename = Path(blob.name).name  # Get just the filename, not the full path
            local_path = LOCAL_CACHE_DIR / filename
            
            blob.download_to_filename(str(local_path))
            logger.info(f"  ✅ {filename} ({local_path.stat().st_size / 1024:.1f} KB)")
        
        logger.info(f"✅ Downloaded {len(csv_blobs)} CSV files successfully")
        
    except Exception as e:
        logger.error(f"❌ Failed to download CSV files from GCS: {e}")
        raise
