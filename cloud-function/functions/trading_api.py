"""
📡 Trading Bot API - HTTP endpoints for bot status, positions, and signals

Endpoints:
- GET /bot/status - Get current bot status
- GET /bot/positions - Get active positions
- GET /bot/signals?epic=GOLD&limit=20 - Get recent signals
- GET /bot/history?limit=100 - Get historical performance

Deploy: gcloud functions deploy trading-bot-api --runtime=python312 --trigger-http --allow-unauthenticated
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from google.cloud import firestore
from flask import Request, jsonify

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Firestore
project_id = os.getenv('GOOGLE_CLOUD_PROJECT', 'double-venture-442318-k8')
db = firestore.Client(project=project_id)


def handle_cors(request: Request):
    """Handle CORS preflight requests"""
    if request.method == 'OPTIONS':
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Max-Age': '3600'
        }
        return ('', 204, headers)
    
    # Set CORS headers for main request
    headers = {
        'Access-Control-Allow-Origin': '*'
    }
    return headers


def get_bot_status(request: Request):
    """
    Get current bot status
    
    GET /bot/status?bot_id=gold_m5_bot
    
    Returns:
        {
            "bot_id": "gold_m5_bot",
            "status": "running",
            "epic": "GOLD",
            "mode": "AUTO",
            "uptime_seconds": 3600,
            "last_heartbeat": "2026-03-24T10:30:00",
            "statistics": {
                "signals_generated": 5,
                "orders_placed": 3,
                "positions_closed": 2,
                "total_pnl": 150.50
            }
        }
    """
    # Handle CORS
    if request.method == 'OPTIONS':
        return handle_cors(request)
    
    headers = handle_cors(request)
    
    try:
        # Get bot_id from query params (default: gold_m5_bot)
        bot_id = request.args.get('bot_id', 'gold_m5_bot')
        
        # Fetch bot status from Firestore
        doc_ref = db.collection('bot_status').document(bot_id)
        doc = doc_ref.get()
        
        if not doc.exists:
            return jsonify({
                'error': 'Bot not found',
                'bot_id': bot_id,
                'status': 'unknown'
            }), 404, headers
        
        status_data = doc.to_dict()
        
        # Check if bot is stale (no heartbeat in last 2 minutes)
        if 'last_heartbeat' in status_data:
            last_heartbeat = datetime.fromisoformat(status_data['last_heartbeat'])
            if datetime.now() - last_heartbeat > timedelta(minutes=2):
                status_data['is_stale'] = True
                status_data['stale_reason'] = 'No heartbeat in last 2 minutes'
        
        return jsonify(status_data), 200, headers
        
    except Exception as e:
        logger.error(f"Error getting bot status: {e}")
        return jsonify({'error': str(e)}), 500, headers


def get_bot_positions(request: Request):
    """
    Get active positions
    
    GET /bot/positions?status=open&epic=GOLD
    
    Query params:
        - status: Filter by status (open, closed, all) - default: open
        - epic: Filter by epic (optional)
    
    Returns:
        {
            "positions": [
                {
                    "deal_id": "DEAL123",
                    "epic": "GOLD",
                    "direction": "BUY",
                    "size": 0.5,
                    "entry_price": 2650.25,
                    "current_price": 2655.50,
                    "pnl": 2.625,
                    "stop_loss": 2630.25,
                    "take_profit": 2690.25,
                    "opened_at": "2026-03-24T10:00:00",
                    "status": "open"
                }
            ],
            "count": 1,
            "total_pnl": 2.625
        }
    """
    # Handle CORS
    if request.method == 'OPTIONS':
        return handle_cors(request)
    
    headers = handle_cors(request)
    
    try:
        # Get query params
        status_filter = request.args.get('status', 'open')
        epic_filter = request.args.get('epic', None)
        
        # Build query
        query = db.collection('active_positions')
        
        # Filter by status
        if status_filter != 'all':
            query = query.where('status', '==', status_filter)
        
        # Filter by epic
        if epic_filter:
            query = query.where('epic', '==', epic_filter)
        
        # Order by opened_at (most recent first)
        query = query.order_by('opened_at', direction=firestore.Query.DESCENDING)
        
        # Fetch positions
        docs = query.stream()
        positions = []
        total_pnl = 0.0
        
        for doc in docs:
            position_data = doc.to_dict()
            position_data['id'] = doc.id
            positions.append(position_data)
            
            # Sum P&L
            if 'pnl' in position_data:
                total_pnl += position_data['pnl']
            elif 'realized_pnl' in position_data:
                total_pnl += position_data['realized_pnl']
        
        return jsonify({
            'positions': positions,
            'count': len(positions),
            'total_pnl': round(total_pnl, 2)
        }), 200, headers
        
    except Exception as e:
        logger.error(f"Error getting positions: {e}")
        return jsonify({'error': str(e)}), 500, headers


def get_bot_signals(request: Request):
    """
    Get recent trading signals
    
    GET /bot/signals?epic=GOLD&limit=20&mode=AUTO
    
    Query params:
        - epic: Filter by epic (optional)
        - limit: Max number of signals to return (default: 20, max: 100)
        - mode: Filter by mode (AUTO, SIGNAL_ONLY, all) - default: all
    
    Returns:
        {
            "signals": [
                {
                    "id": "GOLD_20260324_103000",
                    "epic": "GOLD",
                    "signal": "BUY",
                    "price": 2650.25,
                    "sl": 2630.25,
                    "tp": 2690.25,
                    "timestamp": "2026-03-24T10:30:00",
                    "strategy": "SupertrendVWAP",
                    "mode": "AUTO"
                }
            ],
            "count": 1
        }
    """
    # Handle CORS
    if request.method == 'OPTIONS':
        return handle_cors(request)
    
    headers = handle_cors(request)
    
    try:
        # Get query params
        epic_filter = request.args.get('epic', None)
        limit = min(int(request.args.get('limit', 20)), 100)  # Max 100
        mode_filter = request.args.get('mode', 'all')
        
        # Build query
        query = db.collection('trading_signals')
        
        # Filter by epic
        if epic_filter:
            query = query.where('epic', '==', epic_filter)
        
        # Filter by mode
        if mode_filter != 'all':
            query = query.where('mode', '==', mode_filter)
        
        # Order by timestamp (most recent first)
        query = query.order_by('timestamp', direction=firestore.Query.DESCENDING).limit(limit)
        
        # Fetch signals
        docs = query.stream()
        signals = []
        
        for doc in docs:
            signal_data = doc.to_dict()
            signal_data['id'] = doc.id
            signals.append(signal_data)
        
        return jsonify({
            'signals': signals,
            'count': len(signals)
        }), 200, headers
        
    except Exception as e:
        logger.error(f"Error getting signals: {e}")
        return jsonify({'error': str(e)}), 500, headers


def trading_bot_api(request: Request):
    """
    Main Cloud Function entry point - routes to appropriate handler
    
    Routes:
        GET /bot/status
        GET /bot/positions
        GET /bot/signals
    """
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        return handle_cors(request)
    
    # Get path from request
    path = request.path.strip('/')
    
    # Route to appropriate handler
    if path == 'bot/status' or path == 'status':
        return get_bot_status(request)
    elif path == 'bot/positions' or path == 'positions':
        return get_bot_positions(request)
    elif path == 'bot/signals' or path == 'signals':
        return get_bot_signals(request)
    else:
        # Return API documentation
        headers = handle_cors(request)
        return jsonify({
            'name': 'Trading Bot API',
            'version': '1.0.0',
            'endpoints': {
                'bot_status': '/bot/status?bot_id=gold_m5_bot',
                'active_positions': '/bot/positions?status=open&epic=GOLD',
                'recent_signals': '/bot/signals?epic=GOLD&limit=20'
            },
            'documentation': 'https://github.com/your-repo/trading-bot-api'
        }), 200, headers
