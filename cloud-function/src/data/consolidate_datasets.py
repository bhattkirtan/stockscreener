"""
Consolidate Multiple CSV Files into Master Datasets
Merges all files for same instrument/timeframe into ONE master file
Removes duplicates, keeps all unique bars sorted by timestamp
"""

import os
import pandas as pd
import logging
from pathlib import Path
from datetime import datetime
from google.cloud import storage
from typing import List, Dict, Tuple
from .dataset_manager import get_dataset_summary, parse_csv_filename

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID')
BUCKET_NAME = os.environ.get('BUCKET_NAME', f'{PROJECT_ID}-optimization-results')
LOCAL_TEMP_DIR = Path('/tmp/consolidation')


def download_csv_from_gcs(gcs_path: str, local_path: Path) -> bool:
    """Download CSV file from GCS"""
    try:
        client = storage.Client()
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob(gcs_path)
        
        local_path.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(local_path))
        
        logger.info(f"📥 Downloaded: {gcs_path}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to download {gcs_path}: {e}")
        return False


def upload_csv_to_gcs(local_path: Path, gcs_path: str) -> bool:
    """Upload CSV file to GCS"""
    try:
        client = storage.Client()
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob(gcs_path)
        
        blob.upload_from_filename(str(local_path))
        logger.info(f"📤 Uploaded: {gcs_path}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to upload {gcs_path}: {e}")
        return False


def delete_csv_from_gcs(gcs_path: str) -> bool:
    """Delete CSV file from GCS"""
    try:
        client = storage.Client()
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob(gcs_path)
        blob.delete()
        logger.info(f"🗑️  Deleted: {gcs_path}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to delete {gcs_path}: {e}")
        return False


def consolidate_instrument_timeframe(instrument: str, timeframe: str, 
                                     datasets: List[Dict],
                                     dry_run: bool = False) -> Dict:
    """
    Consolidate all datasets for a specific instrument/timeframe
    
    Args:
        instrument: e.g., 'GOLD'
        timeframe: e.g., 'M15'
        datasets: List of dataset dicts for this instrument/timeframe
        dry_run: If True, don't actually modify files
    
    Returns:
        Dict with consolidation results
    """
    if len(datasets) <= 1:
        logger.info(f"✓ {instrument} {timeframe}: Only 1 dataset, no consolidation needed")
        return {
            'instrument': instrument,
            'timeframe': timeframe,
            'action': 'skipped',
            'reason': 'single_dataset',
            'datasets': datasets
        }
    
    logger.info(f"\n{'='*70}")
    logger.info(f"🔄 Consolidating {instrument} {timeframe} ({len(datasets)} files)")
    logger.info(f"{'='*70}")
    
    # Sort by bars (largest first)
    datasets.sort(key=lambda x: x['bars'], reverse=True)
    
    # Download all files
    LOCAL_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    dataframes = []
    
    for ds in datasets:
        local_path = LOCAL_TEMP_DIR / ds['filename']
        logger.info(f"  📥 {ds['filename']} ({ds['bars']} bars, {ds['size_kb']} KB)")
        
        if not download_csv_from_gcs(ds['gcs_path'], local_path):
            logger.warning(f"     ⚠️  Failed to download, skipping")
            continue
        
        try:
            df = pd.read_csv(local_path, index_col=0, parse_dates=True)
            logger.info(f"     ✓ Loaded {len(df)} rows, range: {df.index[0]} to {df.index[-1]}")
            dataframes.append(df)
        except Exception as e:
            logger.error(f"     ❌ Failed to read CSV: {e}")
    
    if not dataframes:
        logger.error(f"❌ No valid dataframes to consolidate")
        return {
            'instrument': instrument,
            'timeframe': timeframe,
            'action': 'failed',
            'reason': 'no_valid_data'
        }
    
    # Combine all dataframes
    logger.info(f"\n🔀 Combining {len(dataframes)} dataframes...")
    combined = pd.concat(dataframes, axis=0)
    
    # Remove duplicates (keep first occurrence)
    original_len = len(combined)
    combined = combined[~combined.index.duplicated(keep='first')]
    duplicates_removed = original_len - len(combined)
    
    # Sort by timestamp
    combined.sort_index(inplace=True)
    
    logger.info(f"   Original rows: {original_len:,}")
    logger.info(f"   Duplicates removed: {duplicates_removed:,}")
    logger.info(f"   Final rows: {len(combined):,}")
    logger.info(f"   Date range: {combined.index[0]} to {combined.index[-1]}")
    
    # Create master filename using the largest bar count
    max_bars = max(ds['bars'] for ds in datasets)
    master_filename = f"{instrument}_{timeframe}_{len(combined)}bars.csv"
    master_gcs_path = f"data/{master_filename}"
    
    result = {
        'instrument': instrument,
        'timeframe': timeframe,
        'action': 'consolidated' if not dry_run else 'dry_run',
        'source_files': [ds['filename'] for ds in datasets],
        'master_file': master_filename,
        'total_bars': len(combined),
        'duplicates_removed': duplicates_removed,
        'date_range': {
            'start': combined.index[0].isoformat(),
            'end': combined.index[-1].isoformat()
        }
    }
    
    if dry_run:
        logger.info(f"\n🔍 DRY RUN - Would create: {master_filename}")
        logger.info(f"   Would delete: {', '.join([ds['filename'] for ds in datasets])}")
        return result
    
    # Save consolidated file
    logger.info(f"\n💾 Saving master file: {master_filename}")
    master_local_path = LOCAL_TEMP_DIR / master_filename
    combined.to_csv(master_local_path)
    
    # Upload master file
    if not upload_csv_to_gcs(master_local_path, master_gcs_path):
        logger.error(f"❌ Failed to upload master file")
        result['action'] = 'failed'
        result['reason'] = 'upload_failed'
        return result
    
    # Delete old files
    logger.info(f"\n🗑️  Removing old files:")
    deleted = []
    for ds in datasets:
        if delete_csv_from_gcs(ds['gcs_path']):
            logger.info(f"   ✓ Deleted: {ds['filename']}")
            deleted.append(ds['filename'])
        else:
            logger.warning(f"   ⚠️  Failed to delete: {ds['filename']}")
    
    result['deleted_files'] = deleted
    logger.info(f"\n✅ Consolidation complete: {instrument} {timeframe}")
    
    return result


def consolidate_all_datasets(dry_run: bool = True) -> List[Dict]:
    """
    Consolidate all duplicate datasets in GCS
    
    Args:
        dry_run: If True, only show what would be done (default)
    
    Returns:
        List of consolidation results
    """
    logger.info(f"\n{'='*70}")
    logger.info(f"🔄 Dataset Consolidation")
    logger.info(f"   Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    logger.info(f"{'='*70}\n")
    
    # Get dataset summary
    summary = get_dataset_summary()
    
    if not summary['duplicates']:
        logger.info("✅ No duplicate datasets found. All clean!")
        return []
    
    logger.info(f"📊 Found {len(summary['duplicates'])} instrument/timeframe pairs with multiple files:")
    for dup in summary['duplicates']:
        logger.info(f"   • {dup['instrument']} {dup['timeframe']}: {dup['count']} files")
    
    # Consolidate each duplicate group
    results = []
    
    for dup in summary['duplicates']:
        instrument = dup['instrument']
        timeframe = dup['timeframe']
        
        # Get full dataset info for this pair
        datasets = summary['by_instrument'][instrument][timeframe]
        
        result = consolidate_instrument_timeframe(
            instrument, 
            timeframe, 
            datasets,
            dry_run=dry_run
        )
        results.append(result)
    
    # Summary
    logger.info(f"\n{'='*70}")
    logger.info(f"📊 Consolidation Summary")
    logger.info(f"{'='*70}")
    logger.info(f"   Total pairs processed: {len(results)}")
    
    consolidated = [r for r in results if r['action'] == 'consolidated']
    skipped = [r for r in results if r['action'] == 'skipped']
    failed = [r for r in results if r['action'] == 'failed']
    
    logger.info(f"   ✅ Consolidated: {len(consolidated)}")
    logger.info(f"   ⏭️  Skipped: {len(skipped)}")
    logger.info(f"   ❌ Failed: {len(failed)}")
    
    if consolidated:
        logger.info(f"\n✅ Consolidated datasets:")
        for r in consolidated:
            logger.info(f"   • {r['instrument']} {r['timeframe']}: {r['total_bars']:,} bars")
            logger.info(f"     Master: {r['master_file']}")
    
    logger.info(f"\n{'='*70}")
    logger.info(f"✅ Consolidation complete")
    logger.info(f"{'='*70}\n")
    
    return results


if __name__ == '__main__':
    """Run consolidation"""
    import sys
    
    # Check for --live flag
    dry_run = '--live' not in sys.argv
    
    if not dry_run:
        confirm = input("\n⚠️  LIVE MODE - This will modify GCS data. Continue? (yes/no): ")
        if confirm.lower() != 'yes':
            print("❌ Cancelled")
            sys.exit(0)
    
    results = consolidate_all_datasets(dry_run=dry_run)
    
    if dry_run:
        print("\n💡 To run for real: python3 -m src.data.consolidate_datasets --live\n")
