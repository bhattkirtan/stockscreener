"""
Cloud Function: Trading Bot Logs API
Provides webhook endpoints to access trading bot logs from GCS
"""

import os
import json
from datetime import datetime, timedelta
from flask import jsonify, Request
from google.cloud import storage
import functions_framework


def get_storage_client():
    """Get authenticated storage client"""
    project_id = os.getenv('GOOGLE_CLOUD_PROJECT', 'double-venture-442318-k8')
    return storage.Client(project=project_id)


def get_logs_bucket():
    """Get logs bucket"""
    project_id = os.getenv('GOOGLE_CLOUD_PROJECT', 'double-venture-442318-k8')
    bucket_name = os.getenv('GCS_LOGS_BUCKET', f'{project_id}-trading-logs')
    client = get_storage_client()
    return client.bucket(bucket_name)


@functions_framework.http
def get_bot_logs(request: Request):
    """
    HTTP Cloud Function to retrieve bot logs
    
    Query Parameters:
    - date: YYYY-MM-DD (default: today)
    - file: specific log file name (optional)
    - lines: number of lines to return (default: 100, max: 1000)
    - format: 'json' | 'text' (default: json)
    
    Examples:
    - /get_bot_logs?date=2026-03-24
    - /get_bot_logs?date=2026-03-24&file=bot-output.log
    - /get_bot_logs?lines=500&format=text
    """
    
    # Enable CORS
    if request.method == 'OPTIONS':
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Max-Age': '3600'
        }
        return ('', 204, headers)
    
    headers = {
        'Access-Control-Allow-Origin': '*'
    }
    
    try:
        # Parse query parameters
        date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
        file_name = request.args.get('file', None)
        lines = min(int(request.args.get('lines', 100)), 1000)
        output_format = request.args.get('format', 'json')
        
        # Validate date
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            return jsonify({
                'error': 'Invalid date format. Use YYYY-MM-DD'
            }), 400, headers
        
        bucket = get_logs_bucket()
        
        # Get specific file or all files for date
        if file_name:
            # Get specific file
            blob_path = f"logs/{date_str}/{file_name}"
            blob = bucket.blob(blob_path)
            
            if not blob.exists():
                # Try latest.log
                blob = bucket.blob("logs/latest.log")
                if not blob.exists():
                    return jsonify({
                        'error': f'Log file not found: {file_name}',
                        'date': date_str
                    }), 404, headers
            
            content = blob.download_as_text()
            
            # Return last N lines
            log_lines = content.splitlines()
            log_lines = log_lines[-lines:] if len(log_lines) > lines else log_lines
            
            if output_format == 'text':
                return '\n'.join(log_lines), 200, {**headers, 'Content-Type': 'text/plain'}
            
            return jsonify({
                'file': file_name,
                'date': date_str,
                'lines': log_lines,
                'total_lines': len(log_lines),
                'bucket': bucket.name,
                'path': blob.name
            }), 200, headers
        
        else:
            # List all log files for date
            prefix = f"logs/{date_str}/"
            blobs = list(bucket.list_blobs(prefix=prefix))
            
            if not blobs:
                return jsonify({
                    'error': f'No logs found for date: {date_str}',
                    'date': date_str,
                    'available_dates': get_available_dates(bucket)
                }), 404, headers
            
            log_files = []
            for blob in blobs:
                log_files.append({
                    'name': blob.name.split('/')[-1],
                    'size': blob.size,
                    'updated': blob.updated.isoformat() if blob.updated else None,
                    'path': blob.name,
                    'url': f"?date={date_str}&file={blob.name.split('/')[-1]}"
                })
            
            return jsonify({
                'date': date_str,
                'files': log_files,
                'count': len(log_files),
                'bucket': bucket.name
            }), 200, headers
    
    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500, headers


def get_available_dates(bucket):
    """Get list of available log dates"""
    blobs = bucket.list_blobs(prefix='logs/')
    dates = set()
    for blob in blobs:
        parts = blob.name.split('/')
        if len(parts) >= 2 and parts[1] != 'latest.log':
            dates.add(parts[1])
    return sorted(list(dates), reverse=True)[:30]  # Last 30 days


@functions_framework.http
def list_log_dates(request: Request):
    """
    HTTP Cloud Function to list available log dates
    
    Returns:
    {
        "dates": ["2026-03-24", "2026-03-23", ...],
        "count": 10
    }
    """
    
    # Enable CORS
    if request.method == 'OPTIONS':
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Max-Age': '3600'
        }
        return ('', 204, headers)
    
    headers = {
        'Access-Control-Allow-Origin': '*'
    }
    
    try:
        bucket = get_logs_bucket()
        dates = get_available_dates(bucket)
        
        return jsonify({
            'dates': dates,
            'count': len(dates),
            'bucket': bucket.name,
            'latest_url': '?date=' + dates[0] if dates else None
        }), 200, headers
    
    except Exception as e:
        return jsonify({
            'error': str(e)
        }), 500, headers
