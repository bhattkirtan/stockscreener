"""
Cloud Functions API for Strategy Optimization
Handles CRUD operations and triggers Cloud Run workers via Cloud Tasks
"""

import os
import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional
import functions_framework
from flask import Request, jsonify
from google.cloud import storage, tasks_v2
from google.protobuf import timestamp_pb2
import pandas as pd
from pathlib import Path

# Configuration
PROJECT_ID = os.environ.get('GCP_PROJECT_ID')
REGION = os.environ.get('REGION', 'us-central1')
QUEUE_NAME = os.environ.get('QUEUE_NAME', 'optimization-queue')
WORKER_URL = os.environ.get('WORKER_URL')  # Cloud Run worker URL
BUCKET_NAME = os.environ.get('BUCKET_NAME', f'{PROJECT_ID}-optimization-results')

# Initialize clients
storage_client = storage.Client()
tasks_client = tasks_v2.CloudTasksClient()


def get_bucket():
    """Get or create the storage bucket"""
    try:
        bucket = storage_client.bucket(BUCKET_NAME)
        if not bucket.exists():
            bucket = storage_client.create_bucket(BUCKET_NAME, location=REGION)
        return bucket
    except Exception as e:
        print(f"Error accessing bucket: {e}")
        return None


def upload_json_to_storage(run_id: str, filename: str, data: dict):
    """Upload JSON data to Cloud Storage"""
    bucket = get_bucket()
    if not bucket:
        return False
    
    blob = bucket.blob(f"{run_id}/{filename}")
    blob.upload_from_string(json.dumps(data, indent=2), content_type='application/json')
    return True


def download_json_from_storage(run_id: str, filename: str) -> Optional[dict]:
    """Download JSON data from Cloud Storage"""
    bucket = get_bucket()
    if not bucket:
        return None
    
    blob = bucket.blob(f"{run_id}/{filename}")
    if not blob.exists():
        return None
    
    return json.loads(blob.download_as_text())


def list_runs_from_storage() -> List[dict]:
    """List all optimization runs from Cloud Storage"""
    bucket = get_bucket()
    if not bucket:
        return []
    
    runs = {}
    blobs = bucket.list_blobs()
    
    for blob in blobs:
        parts = blob.name.split('/')
        if len(parts) >= 2:
            run_id = parts[0]
            if run_id not in runs and blob.name.endswith('metadata.json'):
                try:
                    metadata = json.loads(blob.download_as_text())
                    runs[run_id] = metadata
                except:
                    pass
    
    return sorted(runs.values(), key=lambda x: x.get('start_time', ''), reverse=True)


def delete_run_from_storage(run_id: str) -> bool:
    """Delete all files for a run from Cloud Storage"""
    bucket = get_bucket()
    if not bucket:
        return False
    
    blobs = bucket.list_blobs(prefix=f"{run_id}/")
    for blob in blobs:
        blob.delete()
    
    return True


def create_cloud_task(run_id: str, params: dict):
    """Create a Cloud Task to trigger the worker"""
    parent = tasks_client.queue_path(PROJECT_ID, REGION, QUEUE_NAME)
    
    # Task payload
    task_payload = {
        'run_id': run_id,
        'params': params
    }
    
    # Create the task
    task = {
        'http_request': {
            'http_method': tasks_v2.HttpMethod.POST,
            'url': WORKER_URL,
            'headers': {
                'Content-Type': 'application/json',
            },
            'body': json.dumps(task_payload).encode(),
        }
    }
    
    # Add OIDC token for authentication
    if WORKER_URL:
        task['http_request']['oidc_token'] = {
            'service_account_email': f'{PROJECT_ID}@appspot.gserviceaccount.com'
        }
    
    response = tasks_client.create_task(parent=parent, task=task)
    return response.name


@functions_framework.http
def optimize_api(request: Request):
    """Main entry point for all API requests"""
    
    # Handle CORS
    if request.method == 'OPTIONS':
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Max-Age': '3600'
        }
        return ('', 204, headers)
    
    headers = {
        'Access-Control-Allow-Origin': '*',
        'Content-Type': 'application/json'
    }
    
    # Route the request
    path = request.path.strip('/')
    method = request.method
    
    try:
        if path == 'health' or path == 'api/health':
            return jsonify({'status': 'healthy', 'service': 'optimization-api'}), 200, headers
        
        elif path == 'api/optimize' and method == 'POST':
            return handle_start_optimization(request, headers)
        
        elif path.startswith('api/optimize/status/'):
            run_id = path.split('/')[-1]
            return handle_get_status(run_id, headers)
        
        elif path == 'api/optimize/history' and method == 'GET':
            return handle_get_history(headers)
        
        elif path.startswith('api/optimize/results/'):
            run_id = path.split('/')[-1]
            return handle_get_results(run_id, headers)
        
        elif path.startswith('api/optimize/') and method == 'DELETE':
            run_id = path.split('/')[-1]
            return handle_delete_run(run_id, headers)
        
        elif path.startswith('api/analyze/'):
            if path == 'api/analyze/latest':
                return handle_analyze_latest(headers)
            else:
                run_id = path.split('/')[-1]
                mode = request.args.get('mode', 'overview')
                return handle_analyze_run(run_id, mode, headers)
        
        elif path == 'api/stats/summary':
            return handle_get_stats(headers)
        
        else:
            return jsonify({'error': 'Not found'}), 404, headers
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500, headers


def handle_start_optimization(request: Request, headers: dict):
    """Start a new optimization by creating a Cloud Task"""
    data = request.get_json() or {}
    
    # Generate run ID
    run_id = f"{data.get('instrument', 'UNKNOWN')}_{data.get('timeframe', 'M5')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    # Prepare parameters
    params = {
        'instrument': data.get('instrument', 'GOLD'),
        'timeframe': data.get('timeframe', 'M5'),
        'capital': data.get('capital', 10000),
        'position_size': data.get('position_size', 0.1),
        'mode': data.get('mode', 'full'),
        'n_jobs': data.get('n_jobs', -1)
    }
    
    # Create metadata
    metadata = {
        'run_id': run_id,
        'status': 'queued',
        'params': params,
        'start_time': datetime.now().isoformat(),
        'end_time': None,
        'error': None
    }
    
    # Save metadata to Cloud Storage
    upload_json_to_storage(run_id, 'metadata.json', metadata)
    
    # Create Cloud Task to trigger worker
    try:
        task_name = create_cloud_task(run_id, params)
        metadata['task_name'] = task_name
        upload_json_to_storage(run_id, 'metadata.json', metadata)
        
        return jsonify({
            'run_id': run_id,
            'status': 'queued',
            'message': 'Optimization task created',
            'task_name': task_name
        }), 202, headers
    
    except Exception as e:
        metadata['status'] = 'failed'
        metadata['error'] = str(e)
        upload_json_to_storage(run_id, 'metadata.json', metadata)
        
        return jsonify({
            'run_id': run_id,
            'status': 'failed',
            'error': str(e)
        }), 500, headers


def handle_get_status(run_id: str, headers: dict):
    """Get the status of an optimization run"""
    metadata = download_json_from_storage(run_id, 'metadata.json')
    
    if not metadata:
        return jsonify({'error': 'Run not found'}), 404, headers
    
    return jsonify(metadata), 200, headers


def handle_get_history(headers: dict):
    """Get the history of all optimization runs"""
    runs = list_runs_from_storage()
    return jsonify({'runs': runs, 'count': len(runs)}), 200, headers


def handle_get_results(run_id: str, headers: dict):
    """Get the top results for a run"""
    metadata = download_json_from_storage(run_id, 'metadata.json')
    
    if not metadata:
        return jsonify({'error': 'Run not found'}), 404, headers
    
    if metadata['status'] != 'completed':
        return jsonify({
            'run_id': run_id,
            'status': metadata['status'],
            'message': 'Optimization not completed yet'
        }), 200, headers
    
    # Try to load results
    results = download_json_from_storage(run_id, 'top_strategies.json')
    
    if not results:
        return jsonify({'error': 'Results not found'}), 404, headers
    
    return jsonify({
        'run_id': run_id,
        'status': 'completed',
        'results': results
    }), 200, headers


def handle_delete_run(run_id: str, headers: dict):
    """Delete an optimization run"""
    if delete_run_from_storage(run_id):
        return jsonify({'message': f'Run {run_id} deleted'}), 200, headers
    else:
        return jsonify({'error': 'Failed to delete run'}), 500, headers


def handle_analyze_run(run_id: str, mode: str, headers: dict):
    """Analyze a specific run"""
    metadata = download_json_from_storage(run_id, 'metadata.json')
    
    if not metadata:
        return jsonify({'error': 'Run not found'}), 404, headers
    
    if metadata['status'] != 'completed':
        return jsonify({
            'run_id': run_id,
            'status': metadata['status'],
            'message': 'Optimization not completed yet'
        }), 200, headers
    
    # Load analysis results
    analysis = download_json_from_storage(run_id, f'analysis_{mode}.json')
    
    if not analysis:
        return jsonify({'error': 'Analysis not found'}), 404, headers
    
    return jsonify(analysis), 200, headers


def handle_analyze_latest(headers: dict):
    """Analyze the latest completed run"""
    runs = list_runs_from_storage()
    
    completed_runs = [r for r in runs if r.get('status') == 'completed']
    
    if not completed_runs:
        return jsonify({'error': 'No completed runs found'}), 404, headers
    
    latest_run = completed_runs[0]
    run_id = latest_run['run_id']
    
    return handle_analyze_run(run_id, 'overview', headers)


def handle_get_stats(headers: dict):
    """Get summary statistics across all runs"""
    runs = list_runs_from_storage()
    
    stats = {
        'total_runs': len(runs),
        'completed': len([r for r in runs if r.get('status') == 'completed']),
        'running': len([r for r in runs if r.get('status') == 'running']),
        'queued': len([r for r in runs if r.get('status') == 'queued']),
        'failed': len([r for r in runs if r.get('status') == 'failed']),
    }
    
    return jsonify(stats), 200, headers
