"""
Cloud Run Worker for Strategy Optimization
Receives tasks from Cloud Tasks queue and runs optimizations
"""

import os
import sys
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict
from flask import Flask, request, jsonify
from google.cloud import storage
import traceback
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
PROJECT_ID = os.environ.get('GCP_PROJECT_ID')
BUCKET_NAME = os.environ.get('BUCKET_NAME', f'{PROJECT_ID}-optimization-results')
DATA_DIR = Path('/app/data')
OPTIMIZATION_DIR = DATA_DIR / 'optimization'

# Initialize storage client
storage_client = storage.Client()


def get_bucket():
    """Get the storage bucket"""
    return storage_client.bucket(BUCKET_NAME)


def upload_file_to_storage(run_id: str, local_path: Path, remote_filename: str):
    """Upload a file to Cloud Storage"""
    bucket = get_bucket()
    blob = bucket.blob(f"{run_id}/{remote_filename}")
    blob.upload_from_filename(str(local_path))
    print(f"✅ Uploaded {remote_filename} to Cloud Storage")


def upload_json_to_storage(run_id: str, filename: str, data: dict):
    """Upload JSON data to Cloud Storage"""
    bucket = get_bucket()
    blob = bucket.blob(f"{run_id}/{filename}")
    blob.upload_from_string(json.dumps(data, indent=2), content_type='application/json')
    print(f"✅ Uploaded {filename} to Cloud Storage")


def update_metadata(run_id: str, updates: dict):
    """Update metadata in Cloud Storage"""
    bucket = get_bucket()
    blob = bucket.blob(f"{run_id}/metadata.json")
    
    # Download current metadata
    try:
        metadata = json.loads(blob.download_as_text())
    except:
        metadata = {'run_id': run_id}
    
    # Update with new values
    metadata.update(updates)
    
    # Upload updated metadata
    blob.upload_from_string(json.dumps(metadata, indent=2), content_type='application/json')
    print(f"✅ Updated metadata: {updates}")


def run_optimization(run_id: str, params: dict) -> dict:
    """Run the optimization strategy"""
    print(f"\n{'='*60}")
    print(f"Starting optimization: {run_id}")
    print(f"Parameters: {json.dumps(params, indent=2)}")
    print(f"{'='*60}\n")
    
    # Update status to running
    update_metadata(run_id, {
        'status': 'running',
        'start_time': datetime.now().isoformat()
    })
    
    # Extract parameters (support both old and new API formats)
    config = params.get('config', params)  # Enhanced API wraps in 'config'
    
    # Prepare command
    cmd = [
        sys.executable,
        'src/optimization/optimize_strategy.py',
        '--instrument', config.get('instrument', 'GOLD'),
        '--timeframe', config.get('timeframe', 'M5'),
        '--capital', str(config.get('initial_capital', 10000)),
        '--position-size', str(config.get('position_size', 0.1)),
        '--mode', config.get('mode', 'quick'),
    ]
    
    # Add max_bars if specified
    if 'max_bars' in config:
        cmd.extend(['--max-bars', str(config['max_bars'])])
    
    # Handle parallel processing
    parallel = config.get('parallel', True)
    n_jobs = config.get('n_jobs', -1)
    
    # In Cloud Run, limit workers to actual CPU count to avoid thrashing
    if n_jobs == -1:
        # Cloud Run: use actual CPU count (4), not hyperthreads
        n_jobs = 4
    
    if not parallel or n_jobs == 1:
        cmd.append('--no-parallel')
    else:
        cmd.extend(['--n-jobs', str(n_jobs)])
    
    # Handle custom parameter grid if provided
    if 'param_grid' in params:
        # Save custom grid to temp file
        grid_file = DATA_DIR / f'grid_{run_id}.json'
        with open(grid_file, 'w') as f:
            json.dump(params['param_grid'], f)
        cmd.extend(['--param-grid-file', str(grid_file)])
    
    print(f"Running command: {' '.join(cmd)}\n")
    
    # Run optimization with real-time output streaming
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Combine stderr with stdout
            text=True,
            bufsize=1,  # Line buffered
            cwd='/app'
        )
        
        stdout_lines = []
        
        # Stream output line by line
        for line in process.stdout:
            print(line.rstrip())  # Print to Cloud Logging immediately
            stdout_lines.append(line)
        
        # Wait for process to complete (with timeout)
        try:
            returncode = process.wait(timeout=780)  # 13 min timeout
        except subprocess.TimeoutExpired:
            process.kill()
            raise Exception("Optimization timed out (13 minutes)")
        
        stdout_text = ''.join(stdout_lines)
        
        if returncode != 0:
            raise Exception(f"Optimization failed with return code {returncode}")
        
        return {
            'success': True,
            'stdout': stdout_text,
            'stderr': ''
        }
    
    except subprocess.TimeoutExpired:
        raise Exception("Optimization timed out (13 minutes)")
    
    except Exception as e:
        raise Exception(f"Optimization failed: {str(e)}")


def upload_results(run_id: str, params: dict):
    """Upload optimization results to Cloud Storage"""
    # Extract config (support both old and new API formats)
    config = params.get('config', params)
    instrument = config.get('instrument', 'GOLD')
    timeframe = config.get('timeframe', 'M5')
    
    # Find the results directory
    latest_dir = OPTIMIZATION_DIR / 'latest'
    
    if not latest_dir.exists():
        print("⚠️ No results directory found")
        return
    
    # Upload all CSV files
    csv_files = list(latest_dir.glob('*.csv'))
    for csv_file in csv_files:
        try:
            upload_file_to_storage(run_id, csv_file, csv_file.name)
        except Exception as e:
            print(f"⚠️ Failed to upload {csv_file.name}: {e}")
    
    # Upload all JSON files
    json_files = list(latest_dir.glob('*.json'))
    for json_file in json_files:
        try:
            upload_file_to_storage(run_id, json_file, json_file.name)
        except Exception as e:
            print(f"⚠️ Failed to upload {json_file.name}: {e}")
    
    # Create a summary of top strategies
    try:
        # Find the all_strategies CSV
        csv_pattern = f"*_all_strategies.csv"
        csv_files = list(latest_dir.glob(csv_pattern))
        
        if csv_files:
            import pandas as pd
            df = pd.read_csv(csv_files[0])
            
            # Get top 10 strategies by profit
            top_10 = df.nlargest(10, 'Total Profit ($)')
            
            # Convert to dict
            top_strategies = top_10.to_dict('records')
            
            # Upload as JSON
            upload_json_to_storage(run_id, 'top_strategies.json', {
                'count': len(df),
                'top_10': top_strategies
            })
            
            print(f"✅ Found {len(df)} strategies, uploaded top 10")
    
    except Exception as e:
        print(f"⚠️ Failed to process top strategies: {e}")


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'service': 'optimizer-worker'}), 200


@app.route('/', methods=['POST'])
def process_task():
    """Process an optimization task from Cloud Tasks"""
    try:
        # Parse request
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        run_id = data.get('run_id')
        params = data.get('params', {})
        
        if not run_id:
            return jsonify({'error': 'run_id is required'}), 400
        
        print(f"\n{'='*60}")
        print(f"Received task: {run_id}")
        print(f"{'='*60}\n")
        
        # Run optimization
        result = run_optimization(run_id, params)
        
        # Upload results
        upload_results(run_id, params)
        
        # Update metadata to completed
        update_metadata(run_id, {
            'status': 'completed',
            'end_time': datetime.now().isoformat(),
            'error': None
        })
        
        print(f"\n{'='*60}")
        print(f"✅ Optimization completed: {run_id}")
        print(f"{'='*60}\n")
        
        return jsonify({
            'run_id': run_id,
            'status': 'completed',
            'message': 'Optimization completed successfully'
        }), 200
    
    except Exception as e:
        error_msg = str(e)
        error_trace = traceback.format_exc()
        
        print(f"\n{'='*60}")
        print(f"❌ Optimization failed: {run_id}")
        print(f"Error: {error_msg}")
        print(f"Traceback:\n{error_trace}")
        print(f"{'='*60}\n")
        
        # Update metadata to failed
        try:
            update_metadata(run_id, {
                'status': 'failed',
                'end_time': datetime.now().isoformat(),
                'error': error_msg
            })
        except:
            pass
        
        return jsonify({
            'run_id': run_id,
            'status': 'failed',
            'error': error_msg
        }), 500


if __name__ == '__main__':
    # Create data directories
    OPTIMIZATION_DIR.mkdir(parents=True, exist_ok=True)
    
    # Worker startup - CSV files will be downloaded on-demand
    logger.info("🚀 Worker starting up...")
    logger.info("📦 CSV files will be downloaded from GCS on-demand as needed")
    logger.info("✅ Worker ready")
    
    # Run the Flask app
    port = int(os.environ.get('PORT', 8080))
    logger.info(f"🔥 Worker listening on port {port}")
    app.run(host='0.0.0.0', port=port)
