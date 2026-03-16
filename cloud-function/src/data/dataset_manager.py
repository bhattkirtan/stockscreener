"""
Dataset Manager - List, select, and manage CSV datasets in GCS
Handles multiple datasets for the same instrument/timeframe
"""

import os
import re
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from google.cloud import storage
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID')
BUCKET_NAME = os.environ.get('BUCKET_NAME', f'{PROJECT_ID}-optimization-results')


def get_storage_client():
    """Get storage client"""
    return storage.Client()


def parse_csv_filename(filename: str) -> Optional[Dict[str, any]]:
    """
    Parse CSV filename to extract metadata
    
    Expected format: {INSTRUMENT}_{TIMEFRAME}_{BARS}bars.csv
    Example: GOLD_M15_10000bars.csv
    
    Returns:
        Dict with keys: instrument, timeframe, bars, filename
        None if filename doesn't match pattern
    """
    # Pattern: INSTRUMENT_TIMEFRAME_BARSbars.csv
    pattern = r'^([A-Z]+)_([MH]\d+)_(\d+)bars\.csv$'
    match = re.match(pattern, filename)
    
    if match:
        return {
            'instrument': match.group(1),
            'timeframe': match.group(2),
            'bars': int(match.group(3)),
            'filename': filename
        }
    return None


def list_all_datasets(bucket_name: str = None) -> List[Dict]:
    """
    List all available CSV datasets with metadata
    
    Returns:
        List of dicts with: instrument, timeframe, bars, filename, size_kb, updated_at
    """
    if bucket_name is None:
        bucket_name = BUCKET_NAME
    
    try:
        client = get_storage_client()
        bucket = client.bucket(bucket_name)
        
        blobs = bucket.list_blobs(prefix='data/')
        datasets = []
        
        for blob in blobs:
            if not blob.name.endswith('.csv'):
                continue
            
            filename = Path(blob.name).name
            parsed = parse_csv_filename(filename)
            
            if parsed:
                datasets.append({
                    **parsed,
                    'size_kb': round(blob.size / 1024, 1),
                    'updated_at': blob.updated.isoformat() if blob.updated else None,
                    'gcs_path': blob.name
                })
        
        # Sort by instrument, timeframe, bars (descending)
        datasets.sort(key=lambda x: (x['instrument'], x['timeframe'], -x['bars']))
        
        logger.info(f"📊 Found {len(datasets)} datasets in GCS")
        return datasets
        
    except Exception as e:
        logger.error(f"❌ Failed to list datasets: {e}")
        return []


def group_datasets_by_instrument_timeframe(datasets: List[Dict]) -> Dict[Tuple[str, str], List[Dict]]:
    """
    Group datasets by (instrument, timeframe)
    
    Returns:
        Dict with keys like ('GOLD', 'M15'), values are lists of dataset dicts
    """
    grouped = {}
    
    for ds in datasets:
        key = (ds['instrument'], ds['timeframe'])
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(ds)
    
    return grouped


def get_best_dataset(instrument: str, timeframe: str, 
                     prefer_largest: bool = True,
                     min_bars: Optional[int] = None,
                     max_bars: Optional[int] = None,
                     bucket_name: str = None) -> Optional[Dict]:
    """
    Get the best dataset for a given instrument/timeframe
    
    Args:
        instrument: e.g., 'GOLD', 'EURUSD'
        timeframe: e.g., 'M5', 'M15'
        prefer_largest: If True, prefer dataset with most bars (default)
        min_bars: Minimum bars required (optional filter)
        max_bars: Maximum bars allowed (optional filter)
        bucket_name: GCS bucket name (optional)
    
    Returns:
        Dataset dict or None if not found
    """
    datasets = list_all_datasets(bucket_name)
    
    # Filter by instrument and timeframe
    matching = [
        ds for ds in datasets 
        if ds['instrument'] == instrument and ds['timeframe'] == timeframe
    ]
    
    if not matching:
        logger.warning(f"⚠️ No datasets found for {instrument} {timeframe}")
        return None
    
    # Apply bars filters
    if min_bars:
        matching = [ds for ds in matching if ds['bars'] >= min_bars]
    if max_bars:
        matching = [ds for ds in matching if ds['bars'] <= max_bars]
    
    if not matching:
        logger.warning(f"⚠️ No datasets match bar filters: min={min_bars}, max={max_bars}")
        return None
    
    # Sort by bars (descending or ascending)
    matching.sort(key=lambda x: x['bars'], reverse=prefer_largest)
    
    best = matching[0]
    logger.info(f"✅ Selected dataset: {best['filename']} ({best['bars']} bars)")
    
    return best


def find_duplicate_datasets(datasets: List[Dict] = None) -> List[Tuple[str, str, List[Dict]]]:
    """
    Find instruments/timeframes with multiple datasets (potential duplicates)
    
    Returns:
        List of (instrument, timeframe, list_of_datasets) tuples where count > 1
    """
    if datasets is None:
        datasets = list_all_datasets()
    
    grouped = group_datasets_by_instrument_timeframe(datasets)
    
    duplicates = [
        (instrument, timeframe, ds_list)
        for (instrument, timeframe), ds_list in grouped.items()
        if len(ds_list) > 1
    ]
    
    return duplicates


def get_dataset_summary() -> Dict:
    """
    Get summary of all datasets grouped by instrument/timeframe
    
    Returns:
        {
            'total_datasets': int,
            'instruments': List[str],
            'by_instrument': {
                'GOLD': {
                    'M5': [{'bars': 5000, 'size_kb': 1234, ...}],
                    'M15': [...]
                }
            },
            'duplicates': [...]
        }
    """
    datasets = list_all_datasets()
    grouped = group_datasets_by_instrument_timeframe(datasets)
    
    # Build nested structure
    by_instrument = {}
    instruments = set()
    
    for (instrument, timeframe), ds_list in grouped.items():
        instruments.add(instrument)
        
        if instrument not in by_instrument:
            by_instrument[instrument] = {}
        
        by_instrument[instrument][timeframe] = [
            {
                'bars': ds['bars'],
                'filename': ds['filename'],
                'size_kb': ds['size_kb'],
                'updated_at': ds['updated_at']
            }
            for ds in ds_list
        ]
    
    duplicates = find_duplicate_datasets(datasets)
    
    return {
        'total_datasets': len(datasets),
        'instruments': sorted(instruments),
        'by_instrument': by_instrument,
        'duplicates': [
            {
                'instrument': inst,
                'timeframe': tf,
                'count': len(ds_list),
                'variants': [{'bars': ds['bars'], 'filename': ds['filename']} for ds in ds_list]
            }
            for inst, tf, ds_list in duplicates
        ]
    }


def delete_dataset(filename: str, bucket_name: str = None) -> bool:
    """
    Delete a specific dataset from GCS
    
    Args:
        filename: CSV filename (e.g., 'GOLD_M15_2000bars.csv')
        bucket_name: GCS bucket name (optional)
    
    Returns:
        True if deleted, False if failed
    """
    if bucket_name is None:
        bucket_name = BUCKET_NAME
    
    try:
        client = get_storage_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(f'data/{filename}')
        
        if not blob.exists():
            logger.warning(f"⚠️ Dataset not found: {filename}")
            return False
        
        blob.delete()
        logger.info(f"🗑️  Deleted dataset: {filename}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to delete dataset {filename}: {e}")
        return False


if __name__ == '__main__':
    """Test dataset manager functions"""
    logging.basicConfig(level=logging.INFO)
    
    print("\n" + "="*70)
    print("📊 Dataset Summary")
    print("="*70)
    
    summary = get_dataset_summary()
    
    print(f"\nTotal Datasets: {summary['total_datasets']}")
    print(f"Instruments: {', '.join(summary['instruments'])}")
    
    print("\n" + "-"*70)
    print("Available Datasets by Instrument/Timeframe:")
    print("-"*70)
    
    for instrument in sorted(summary['by_instrument'].keys()):
        print(f"\n{instrument}:")
        for timeframe in sorted(summary['by_instrument'][instrument].keys()):
            datasets = summary['by_instrument'][instrument][timeframe]
            print(f"  {timeframe}:")
            for ds in datasets:
                print(f"    • {ds['bars']:,} bars - {ds['size_kb']} KB - {ds['filename']}")
    
    if summary['duplicates']:
        print("\n" + "-"*70)
        print("⚠️  Found Multiple Datasets (Potential Duplicates):")
        print("-"*70)
        for dup in summary['duplicates']:
            print(f"\n{dup['instrument']} {dup['timeframe']} - {dup['count']} variants:")
            for var in dup['variants']:
                print(f"  • {var['bars']:,} bars - {var['filename']}")
    
    print("\n" + "="*70)
    print("✅ Test complete")
    print("="*70 + "\n")
