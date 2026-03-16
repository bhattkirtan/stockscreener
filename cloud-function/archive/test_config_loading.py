#!/usr/bin/env python3
"""
Local test script to debug instruments config loading
"""
import os
import sys
import json
from datetime import datetime
from google.cloud import storage
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Set required env vars
BUCKET_NAME = os.getenv('GCS_BUCKET', 'double-venture-442318-k8-optimization-results')
INSTRUMENTS_CONFIG_FILE = 'instruments_config.json'

# Copy DEFAULT_DATASETS from data_updater.py
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

# Copy get_instruments_config function
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
            logger.warning(f"⚠️  Config file doesn't exist. Using {len(DEFAULT_DATASETS)} defaults.")
            return DEFAULT_DATASETS
    except Exception as e:
        logger.error(f"❌ Failed to load instruments config: {e}. Using defaults.")
        import traceback
        traceback.print_exc()
        return DEFAULT_DATASETS

print("="*80)
print("🧪 Testing Instruments Config Loading")
print("="*80)
print()

print(f"1️⃣  Environment:")
print(f"   BUCKET_NAME: {BUCKET_NAME}")
print(f"   CONFIG_FILE: {INSTRUMENTS_CONFIG_FILE}")
print()

print(f"2️⃣  DEFAULT_DATASETS ({len(DEFAULT_DATASETS)} entries):")
for i, ds in enumerate(DEFAULT_DATASETS[:5], 1):
    print(f"   {i}. {ds}")
if len(DEFAULT_DATASETS) > 5:
    print(f"   ... and {len(DEFAULT_DATASETS) - 5} more")
print()

print(f"3️⃣  Checking GCS config file directly:")
try:
    storage_client = storage.Client()
    bucket = storage_client.bucket(BUCKET_NAME)
    blob = bucket.blob(INSTRUMENTS_CONFIG_FILE)
    
    if blob.exists():
        print(f"   ✅ Config file EXISTS in GCS")
        config_json = blob.download_as_text()
        config = json.loads(config_json)
        instruments = config.get('instruments', [])
        print(f"   📄 Config contents:")
        print(f"      - instruments count: {len(instruments)}")
        print(f"      - updated_at: {config.get('updated_at', 'N/A')}")
        print(f"   📋 Instruments in config:")
        for i, inst in enumerate(instruments, 1):
            print(f"      {i}. {inst}")
    else:
        print(f"   ❌ Config file DOES NOT EXIST")
except Exception as e:
    print(f"   ❌ Error accessing GCS: {e}")
print()

print(f"4️⃣  Testing get_instruments_config() function:")
try:
    loaded_config = get_instruments_config()
    print(f"   ✅ Function returned {len(loaded_config)} instruments")
    print(f"   📋 Returned instruments:")
    for i, inst in enumerate(loaded_config, 1):
        print(f"      {i}. {inst}")
    print()
    
    # Compare with DEFAULT_DATASETS
    if loaded_config == DEFAULT_DATASETS:
        print(f"   ⚠️  WARNING: Returned config is identical to DEFAULT_DATASETS")
        print(f"      This means the function used defaults instead of GCS config")
    else:
        print(f"   ✅ Config differs from defaults (correct behavior)")
except Exception as e:
    print(f"   ❌ Error calling function: {e}")
    import traceback
    traceback.print_exc()
print()

print(f"5️⃣  Testing filter logic:")
# Simulate filters from trigger endpoint
filters = {
    'instruments': ['GOLD'],
    'timeframes': ['M15'],
    'force': False
}
print(f"   Input filters: {json.dumps(filters, indent=6)}")
print()

# Load config
DATASETS = get_instruments_config()
print(f"   Loaded {len(DATASETS)} datasets from config")

# Apply filters (same logic as data_updater.py)
filtered_datasets = DATASETS
if filters.get('instruments'):
    filtered_datasets = [ds for ds in filtered_datasets if ds[0] in filters['instruments']]
    print(f"   After instrument filter: {len(filtered_datasets)} datasets")
if filters.get('timeframes'):
    filtered_datasets = [ds for ds in filtered_datasets if ds[1] in filters['timeframes']]
    print(f"   After timeframe filter: {len(filtered_datasets)} datasets")

print()
print(f"   📊 Final filtered datasets:")
for i, ds in enumerate(filtered_datasets, 1):
    print(f"      {i}. {ds}")
print()

print("="*80)
print("✅ Test Complete")
print("="*80)
print()
print("Expected behavior:")
print("  - Config file should exist in GCS with 3 instruments")
print("  - get_instruments_config() should return those 3 instruments")
print("  - With filters {instruments: ['GOLD'], timeframes: ['M15']}")
print("  - Final result should be 1 dataset: ('GOLD', 'M15', 10000)")
print()
