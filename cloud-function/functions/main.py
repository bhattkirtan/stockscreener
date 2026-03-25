from dotenv import load_dotenv
from flask import jsonify, abort, make_response, Request
import functions_framework
import google.cloud.logging
from google.cloud import firestore, storage
import json, logging, os
from datetime import datetime, timedelta
from src.api.firestore_client import FirestoreDB
from src.api.capital_client import CapitalClient

# ── Constants ─────────────────────────────────────────────────────────────────
CAPITAL_ENV = os.getenv('CAPITAL_ENV', 'demo').lower()
# Safety: Disable trading on live environment unless explicitly enabled
ALLOW_LIVE_TRADING = os.getenv('ALLOW_LIVE_TRADING', 'false').lower() == 'true'

# ── Setup ────────────────────────────────────────────────────────────────────
db = FirestoreDB()

# Cloud Logging — INFO in production, DEBUG only when env var set
client = google.cloud.logging.Client()
client.setup_logging()
logger = logging.getLogger()
logger.setLevel(logging.DEBUG if os.getenv('DEBUG') == 'true' else logging.INFO)
logger.info(f"⚡ Capital.com API Environment: {CAPITAL_ENV.upper()}")
if CAPITAL_ENV == 'live' and not ALLOW_LIVE_TRADING:
    logger.warning("🔒 CREATE NEW POSITIONS DISABLED - Set ALLOW_LIVE_TRADING=true to enable (updates/closes still allowed)")

# ── Load secrets and initialize Capital client ──────────────────────────────
load_dotenv()
_raw = os.getenv('apicredentials') or '{}'
_secrets = json.loads(_raw)
api_key  = _secrets.get('apikey', '')
username = _secrets.get('username', '')
password = _secrets.get('password', '')
capKey   = _secrets.get('capkey', '')

# Initialize Capital.com API clients for both demo and live
capital_client_demo = CapitalClient(
    username, password, capKey, 
    base_url='https://demo-api-capital.backend-capital.com'
)
capital_client_live = CapitalClient(
    username, password, capKey, 
    base_url='https://api-capital.backend-capital.com'
)

# Clear plaintext secret from memory
del _raw, _secrets

# ── GCS Storage Client (for logs) ────────────────────────────────────────────
project_id = os.getenv('GOOGLE_CLOUD_PROJECT', 'double-venture-442318-k8')
storage_client = storage.Client(project=project_id)
logs_bucket_name = os.getenv('GCS_LOGS_BUCKET', f'{project_id}-trading-logs')

# ── Helper to get the right client based on request ─────────────────────────
def get_capital_client():
    """Get the appropriate Capital.com client based on request headers"""
    from flask import request
    env = request.headers.get('X-Trading-Env', 'demo').lower()
    if env == 'live':
        logger.debug("Using LIVE Capital.com client")
        return capital_client_live
    logger.debug("Using DEMO Capital.com client")
    return capital_client_demo

# ── CORS Configuration ───────────────────────────────────────────────────────
def _add_cors_headers(response):
    """Add CORS headers to any response."""
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Trading-Env'
    response.headers['Access-Control-Max-Age'] = '3600'
    return response

# ── Capital.com API request wrapper ──────────────────────────────────────────
def capital_request(method: str, path: str, **kwargs):
    """Wrapper for Capital client requests with Flask abort on errors"""
    try:
        client = get_capital_client()  # Get client based on request headers
        return client.request(method, path, **kwargs)
    except Exception as e:
        if "rate limit" in str(e).lower():
            abort(429, description=str(e))
        logger.error(f"Capital API error: {e}")
        abort(500, description=str(e))

# ── Capital.com API helpers ───────────────────────────────────────────────────
def get_open_positions():
    return capital_request('GET', '/api/v1/positions')

def create_position(epic, size, direction, stopLevel, profitLevel):
    return capital_request('POST', '/api/v1/positions', json={
        "epic": epic,
        "direction": direction,
        "size": size,
        "guaranteedStop": False,
        "stopLevel": stopLevel,
        "profitLevel": profitLevel,
    })

def update_position(dealId, profitLevel, stopLevel):
    return capital_request('PUT', f'/api/v1/positions/{dealId}', json={
        "profitLevel": profitLevel,
        "stopLevel": stopLevel,
    })

def close_position(dealId):
    return capital_request('DELETE', f'/api/v1/positions/{dealId}')

def get_market_info(epic):
    """Get current price and market info for a specific epic."""
    return capital_request('GET', f'/api/v1/markets/{epic}')

def get_historical_prices(epic, resolution='HOUR', max_points=50, from_date=None, to_date=None):
    """Get historical price data for a specific epic.
    
    Args:
        epic: Market epic (e.g., EURUSD, GOLD, US100)
        resolution: MINUTE, MINUTE_5, MINUTE_15, MINUTE_30, HOUR, HOUR_4, DAY, WEEK
        max_points: Max number of data points (default 50, max 1000)
        from_date: ISO 8601 datetime string (optional)
        to_date: ISO 8601 datetime string (optional)
    """
    params = {'resolution': resolution, 'max': max_points}
    if from_date:
        params['from'] = from_date
    if to_date:
        params['to'] = to_date
    return capital_request('GET', f'/api/v1/prices/{epic}', params=params)

def get_all_markets(searchTerm=None):
    """Get all available markets, optionally filtered by search term."""
    params = {}
    if searchTerm:
        params['searchTerm'] = searchTerm
    return capital_request('GET', '/api/v1/markets', params=params)

# ── Input validation ──────────────────────────────────────────────────────────
def _validate_key(data: dict):
    if data.get('key') != api_key:
        abort(401, description="Unauthorized")

def _require_fields(data: dict, *fields):
    missing = [f for f in fields if data.get(f) is None]
    if missing:
        abort(400, description=f"Missing required fields: {', '.join(missing)}")

# ── Bot Monitoring & Logs Handlers ───────────────────────────────────────────
def handle_get_bot_status(request: Request):
    """Get current bot status from Firestore"""
    try:
        bot_id = request.args.get('bot_id', 'gold_m5_bot')
        doc_ref = db.db.collection('bot_status').document(bot_id)
        doc = doc_ref.get()
        
        if not doc.exists:
            return jsonify({
                'error': 'Bot not found',
                'bot_id': bot_id,
                'status': 'unknown'
            }), 404
        
        status_data = doc.to_dict()
        
        # Check if bot is stale (no heartbeat in last 2 minutes)
        if 'last_heartbeat' in status_data:
            last_heartbeat = datetime.fromisoformat(status_data['last_heartbeat'])
            if datetime.now() - last_heartbeat > timedelta(minutes=2):
                status_data['is_stale'] = True
                status_data['stale_reason'] = 'No heartbeat in last 2 minutes'
        
        return jsonify(status_data), 200
    except Exception as e:
        logger.error(f"Error getting bot status: {e}")
        return jsonify({'error': str(e)}), 500


def handle_get_bot_positions(request: Request):
    """Get active positions from Firestore"""
    try:
        status_filter = request.args.get('status', 'open')
        epic_filter = request.args.get('epic', None)
        
        query = db.db.collection('active_positions')
        
        if status_filter != 'all':
            query = query.where('status', '==', status_filter)
        
        if epic_filter:
            query = query.where('epic', '==', epic_filter)
        
        query = query.order_by('opened_at', direction=firestore.Query.DESCENDING)
        
        docs = query.stream()
        positions = []
        total_pnl = 0.0
        
        for doc in docs:
            position_data = doc.to_dict()
            position_data['id'] = doc.id
            positions.append(position_data)
            
            if 'pnl' in position_data:
                total_pnl += position_data['pnl']
            elif 'realized_pnl' in position_data:
                total_pnl += position_data['realized_pnl']
        
        return jsonify({
            'positions': positions,
            'count': len(positions),
            'total_pnl': round(total_pnl, 2)
        }), 200
    except Exception as e:
        logger.error(f"Error getting positions: {e}")
        return jsonify({'error': str(e)}), 500


def handle_get_bot_signals(request: Request):
    """Get recent trading signals from Firestore"""
    try:
        epic_filter = request.args.get('epic', None)
        limit = min(int(request.args.get('limit', 20)), 100)
        mode_filter = request.args.get('mode', 'all')
        
        query = db.db.collection('trading_signals')
        
        if epic_filter:
            query = query.where('epic', '==', epic_filter)
        
        if mode_filter != 'all':
            query = query.where('mode', '==', mode_filter)
        
        query = query.order_by('timestamp', direction=firestore.Query.DESCENDING).limit(limit)
        
        docs = query.stream()
        signals = []
        
        for doc in docs:
            signal_data = doc.to_dict()
            signal_data['id'] = doc.id
            signals.append(signal_data)
        
        return jsonify({
            'signals': signals,
            'count': len(signals)
        }), 200
    except Exception as e:
        logger.error(f"Error getting signals: {e}")
        return jsonify({'error': str(e)}), 500


def handle_get_live_logs(request: Request):
    """Get live logs from Firestore (recent logs from current bot run)"""
    try:
        bot_id = request.args.get('bot_id', 'gold_m5_bot')
        run_id = request.args.get('run_id', None)
        limit = min(int(request.args.get('limit', 200)), 500)
        level_filter = request.args.get('level', 'all')
        
        # If no run_id specified, get the latest run_id first
        if not run_id:
            # Query for most recent log to get latest run_id
            latest_query = db.db.collection('bot_logs')\
                .where('bot_id', '==', bot_id)\
                .order_by('timestamp', direction=firestore.Query.DESCENDING)\
                .limit(1)
            latest_docs = list(latest_query.stream())
            if latest_docs:
                run_id = latest_docs[0].to_dict().get('run_id')
        
        query = db.db.collection('bot_logs')
        query = query.where('bot_id', '==', bot_id)
        
        if run_id:
            query = query.where('run_id', '==', run_id)
        
        if level_filter != 'all':
            query = query.where('level', '==', level_filter.upper())
        
        # Order by timestamp for accurate chronological order across runs
        query = query.order_by('timestamp', direction=firestore.Query.DESCENDING).limit(limit)
        
        docs = query.stream()
        logs = []
        
        for doc in docs:
            log_data = doc.to_dict()
            log_data['id'] = doc.id
            
            # Convert timestamp to ISO string if it's a Firestore timestamp
            if 'timestamp' in log_data and hasattr(log_data['timestamp'], 'isoformat'):
                log_data['timestamp'] = log_data['timestamp'].isoformat()
            
            logs.append(log_data)
        
        # Reverse to show oldest first
        logs.reverse()
        
        return jsonify({
            'logs': logs,
            'count': len(logs),
            'bot_id': bot_id,
            'run_id': run_id if run_id else 'latest',
            'source': 'firestore_live'
        }), 200
    except Exception as e:
        logger.error(f"Error getting live logs: {e}")
        return jsonify({'error': str(e)}), 500


def handle_get_bot_logs(request: Request):
    """Get bot logs from GCS bucket"""
    try:
        date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
        file_name = request.args.get('file', None)
        lines = min(int(request.args.get('lines', 100)), 1000)
        output_format = request.args.get('format', 'json')
        
        # Validate date
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
        
        bucket = storage_client.bucket(logs_bucket_name)
        
        if file_name:
            # Get specific file
            blob_path = f"logs/{date_str}/{file_name}"
            blob = bucket.blob(blob_path)
            
            if not blob.exists():
                blob = bucket.blob("logs/latest.log")
                if not blob.exists():
                    return jsonify({
                        'error': f'Log file not found: {file_name}',
                        'date': date_str
                    }), 404
            
            content = blob.download_as_text()
            log_lines = content.splitlines()
            log_lines = log_lines[-lines:] if len(log_lines) > lines else log_lines
            
            if output_format == 'text':
                return '\n'.join(log_lines), 200, {'Content-Type': 'text/plain'}
            
            return jsonify({
                'file': file_name,
                'date': date_str,
                'lines': log_lines,
                'total_lines': len(log_lines),
                'bucket': bucket.name,
                'path': blob.name
            }), 200
        else:
            # List all log files for date
            prefix = f"logs/{date_str}/"
            blobs = list(bucket.list_blobs(prefix=prefix))
            
            if not blobs:
                # Get available dates
                dates_blobs = bucket.list_blobs(prefix='logs/')
                dates = set()
                for b in dates_blobs:
                    parts = b.name.split('/')
                    if len(parts) >= 2 and parts[1] != 'latest.log':
                        dates.add(parts[1])
                available_dates = sorted(list(dates), reverse=True)[:30]
                
                return jsonify({
                    'error': f'No logs found for date: {date_str}',
                    'date': date_str,
                    'available_dates': available_dates
                }), 404
            
            log_files = []
            for blob in blobs:
                log_files.append({
                    'name': blob.name.split('/')[-1],
                    'size': blob.size,
                    'updated': blob.updated.isoformat() if blob.updated else None,
                    'path': blob.name,
                    'url': f"/logs/get?date={date_str}&file={blob.name.split('/')[-1]}"
                })
            
            return jsonify({
                'date': date_str,
                'files': log_files,
                'count': len(log_files),
                'bucket': bucket.name
            }), 200
    except Exception as e:
        logger.error(f"Error getting logs: {e}")
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


def handle_list_log_dates(request: Request):
    """List available log dates from GCS"""
    try:
        bucket = storage_client.bucket(logs_bucket_name)
        blobs = bucket.list_blobs(prefix='logs/')
        dates = set()
        
        for blob in blobs:
            parts = blob.name.split('/')
            if len(parts) >= 2 and parts[1] != 'latest.log':
                dates.add(parts[1])
        
        dates_list = sorted(list(dates), reverse=True)[:30]
        
        return jsonify({
            'dates': dates_list,
            'count': len(dates_list),
            'bucket': bucket.name,
            'latest_url': f'/logs/get?date={dates_list[0]}' if dates_list else None
        }), 200
    except Exception as e:
        logger.error(f"Error listing log dates: {e}")
        return jsonify({'error': str(e)}), 500

# ── HTTP Handlers ─────────────────────────────────────────────────────────────
def handle_create_position(req):
    # Safety check: Block creating new positions on live environment unless explicitly enabled
    if CAPITAL_ENV == 'live' and not ALLOW_LIVE_TRADING:
        logger.warning("🚫 Attempted to create NEW position on LIVE environment (blocked)")
        abort(403, description="Creating new positions disabled on live environment. Set ALLOW_LIVE_TRADING=true to enable.")
    
    data = req.get_json(force=True, silent=True) or {}
    _validate_key(data)
    _require_fields(data, 'action', 'epic', 'size1', 'direction', 'stopLevel', 'fibLevel1')

    action = data['action']
    epic   = data['epic']
    size   = data['size1']
    dir_   = data['direction']
    sl     = data['stopLevel']
    tp     = data['fibLevel1']

    # Early exit if outside     
    if not data.get('inTradeTime'):
        return jsonify({'response': 'Outside trading hours, nothing done'}), 200

    # 1) Fetch positions once — split in a single pass
    positions = get_open_positions().json().get("positions", [])
    same, opposite = [], []
    for p in positions:
        pos_epic = p["market"]["epic"]
        pos_dir  = p["position"]["direction"]
        if pos_epic != epic:
            continue
        (same if pos_dir == dir_ else opposite).append(p)

    # 2) Handle existing same-direction positions
    if same:
        if action == "entry":
            return jsonify({'response': 'Position already exists'}), 400

        if action == "update-sl":
            for p in same:
                dealId = p["position"]["dealId"]
                up_resp = update_position(dealId, p["position"]["profitLevel"], sl)
                if not up_resp.ok:
                    abort(up_resp.status_code,
                          description=f"Failed to update {dealId}: {up_resp.text}")
            return jsonify({'response': 'Stop loss updated'}), 200

        if action == "exit":
            for p in same:
                dealId = p["position"]["dealId"]
                close_resp = close_position(dealId)
                if not close_resp.ok:
                    abort(close_resp.status_code,
                          description=f"Failed to close {dealId}: {close_resp.text}")
            return jsonify({'response': 'Position closed'}), 200

    # 3) Close any opposite positions
    for p in opposite:
        close_position(p["position"]["dealId"])

    # 4) Create new position
    create_resp = create_position(epic, size, dir_, sl, tp)
    if not create_resp.ok:
        abort(create_resp.status_code,
              description=f"Failed to create position: {create_resp.text}")

    # 5) Persist to Firestore (single fetch, filtered for this epic)
    new_positions = get_open_positions().json().get("positions", [])
    docs = [p for p in new_positions if p["market"]["epic"] == epic]
    try:
        db.add_document("positions", epic, {"responses": docs})
    except Exception as e:
        logger.warning("Firestore write failed (non-critical): %s", e)

    result = create_resp.json()
    result.update({"tplevel": tp, "status_code": create_resp.status_code})
    return jsonify({"responses": [result]}), 200


def handle_update_position(req):
    data = req.get_json(force=True, silent=True) or {}
    _validate_key(data)
    _require_fields(data, 'epic', 'stopLevel')
    if data.get('action') != "update-sl":
        abort(400, description="Invalid action")

    epic = data['epic']
    sl   = data['stopLevel']

    positions = [
        p for p in get_open_positions().json().get("positions", [])
        if p["market"]["epic"] == epic
    ]

    responses = []
    for p in positions:
        dealId = p["position"]["dealId"]
        up_resp = update_position(dealId, p["position"]["profitLevel"], sl)
        if not up_resp.ok:
            abort(up_resp.status_code,
                  description=f"Failed to update {dealId}: {up_resp.text}")
        responses.append(up_resp.text)

    return jsonify(responses), 200


# ── Entry point ───────────────────────────────────────────────────────────────
@functions_framework.http
def hello_http(req):
    # Handle CORS preflight requests
    if req.method == 'OPTIONS':
        response = make_response('', 204)
        return _add_cors_headers(response)
    
    path   = req.path
    method = req.method

    if method == 'GET' and path == '/get_positions':
        response = jsonify(get_open_positions().json())
        return _add_cors_headers(response), 200

    if method == 'POST' and path == '/create_position':
        result = handle_create_position(req)
        if isinstance(result, tuple):
            return _add_cors_headers(result[0]), result[1]
        return _add_cors_headers(result)

    if method == 'POST' and path == '/updte_position':
        result = handle_update_position(req)
        if isinstance(result, tuple):
            return _add_cors_headers(result[0]), result[1]
        return _add_cors_headers(result)

    if method == 'DELETE' and path.startswith('/close_position/'):
        dealId = path.rsplit('/', 1)[-1]
        resp   = close_position(dealId)
        response = jsonify(resp.json())
        return _add_cors_headers(response), resp.status_code

    # Market data endpoints
    if method == 'GET' and path.startswith('/market/'):
        epic = path.rsplit('/', 1)[-1]
        resp = get_market_info(epic)
        response = jsonify(resp.json())
        return _add_cors_headers(response), resp.status_code

    if method == 'GET' and path.startswith('/prices/'):
        parts = path.split('/')
        if len(parts) < 3:
            abort(400, description="Epic required")
        epic = parts[2]
        resolution = req.args.get('resolution', 'HOUR')
        max_points = int(req.args.get('max', 50))
        from_date = req.args.get('from')
        to_date = req.args.get('to')
        resp = get_historical_prices(epic, resolution, max_points, from_date, to_date)
        response = jsonify(resp.json())
        return _add_cors_headers(response), resp.status_code

    if method == 'GET' and path == '/markets':
        search_term = req.args.get('searchTerm')
        resp = get_all_markets(search_term)
        markets = resp.json().get('markets', [])
        
        # If no search term, calculate top risers and fallers
        if not search_term and markets:
            # Sort by percentageChange
            risers = sorted(
                [m for m in markets if m.get('percentageChange', 0) > 0],
                key=lambda x: x.get('percentageChange', 0),
                reverse=True
            )[:10]
            
            fallers = sorted(
                [m for m in markets if m.get('percentageChange', 0) < 0],
                key=lambda x: x.get('percentageChange', 0)
            )[:10]
            
            response = jsonify({
                'topRisers': risers,
                'topFallers': fallers,
                'totalMarkets': len(markets)
            })
            return _add_cors_headers(response), 200
        
        response = jsonify(resp.json())
        return _add_cors_headers(response), resp.status_code

    # Trading signals endpoints
    if method == 'GET' and path == '/signals':
        limit = int(req.args.get('limit', 20))
        epic = req.args.get('epic')
        
        try:
            query = db.db.collection('trading_signals')
            
            if epic:
                query = query.where('epic', '==', epic)
            
            query = query.order_by('timestamp', direction='DESCENDING').limit(limit)
            
            docs = query.stream()
            signals = []
            for doc in docs:
                signal_data = doc.to_dict()
                signal_data['id'] = doc.id
                signals.append(signal_data)
            
            response = jsonify({
                'signals': signals,
                'count': len(signals)
            })
            return _add_cors_headers(response), 200
        except Exception as e:
            logger.error(f"Failed to fetch signals: {e}")
            response = jsonify({'error': str(e)})
            return _add_cors_headers(response), 500

    if method == 'GET' and path == '/signals/latest':
        epic = req.args.get('epic')
        if not epic:
            response = jsonify({'error': 'epic parameter required'})
            return _add_cors_headers(response), 400
        
        try:
            query = db.db.collection('trading_signals')\
                .where('epic', '==', epic)\
                .order_by('timestamp', direction='DESCENDING')\
                .limit(1)
            
            docs = list(query.stream())
            if docs:
                signal_data = docs[0].to_dict()
                signal_data['id'] = docs[0].id
                response = jsonify(signal_data)
                return _add_cors_headers(response), 200
            else:
                response = jsonify({'error': 'No signals found'})
                return _add_cors_headers(response), 404
        except Exception as e:
            logger.error(f"Failed to fetch latest signal: {e}")
            response = jsonify({'error': str(e)})
            return _add_cors_headers(response), 500

    # Bot monitoring endpoints
    if method == 'GET' and (path == '/bot/status' or path == '/status'):
        result, status_code = handle_get_bot_status(req)
        return _add_cors_headers(result), status_code

    if method == 'GET' and (path == '/bot/positions' or path == '/positions'):
        result, status_code = handle_get_bot_positions(req)
        return _add_cors_headers(result), status_code

    if method == 'GET' and (path == '/bot/signals' or path == '/bot_signals'):
        result, status_code = handle_get_bot_signals(req)
        return _add_cors_headers(result), status_code

    if method == 'GET' and (path == '/bot/logs/live' or path == '/bot/live_logs'):
        result, status_code = handle_get_live_logs(req)
        return _add_cors_headers(result), status_code

    # Logs endpoints
    if method == 'GET' and (path == '/logs/get' or path == '/logs'):
        result, status_code = handle_get_bot_logs(req)
        if isinstance(result, str):  # text format
            return result, status_code
        return _add_cors_headers(result), status_code

    if method == 'GET' and path == '/logs/dates':
        result, status_code = handle_list_log_dates(req)
        return _add_cors_headers(result), status_code

    # API info endpoint
    if method == 'GET' and path == '/':
        response = jsonify({
            'name': 'Trading Bot Unified API',
            'version': '2.0.0',
            'endpoints': {
                'capital_com': {
                    'positions': '/get_positions',
                    'create_position': '/create_position',
                    'update_position': '/updte_position',
                    'close_position': '/close_position/{dealId}',
                    'market_info': '/market/{epic}',
                    'prices': '/prices/{epic}?resolution=HOUR',
                    'markets': '/markets?searchTerm=GOLD'
                },
                'bot_monitoring': {
                    'bot_status': '/bot/status?bot_id=gold_m5_bot',
                    'active_positions': '/bot/positions?status=open&epic=GOLD',
                    'bot_signals': '/bot/signals?epic=GOLD&limit=20'
                },
                'logs': {
                    'get_logs': '/logs/get?date=YYYY-MM-DD&file=bot-output.log',
                    'list_dates': '/logs/dates'
                },
                'signals': {
                    'recent_signals': '/signals?epic=GOLD&limit=20',
                    'latest_signal': '/signals/latest?epic=GOLD'
                }
            }
        })
        return _add_cors_headers(response), 200

    # 404 with CORS headers
    response = jsonify({'error': 'Not found', 'path': path})
    return _add_cors_headers(response), 404


# ── Data Updater Function ────────────────────────────────────────────────────
# Import the data updater function for Cloud Scheduler
from src.data_updater import update_market_data


# ── Scheduler Control API ────────────────────────────────────────────────────
@functions_framework.http
def scheduler_control(request):
    """
    Control the data updater scheduler (enable/disable from UI)
    
    GET /scheduler/status - Check scheduler status
    POST /scheduler/enable - Enable scheduler
    POST /scheduler/disable - Disable scheduler
    POST /scheduler/trigger - Manually trigger data update (with optional filters)
    GET /data - Get available datasets
    GET /instruments - List configured instruments  
    POST /instruments - Add new instrument
    DELETE /instruments - Remove instrument
    """
    from google.cloud import storage
    from flask import jsonify
    
    BUCKET_NAME = os.getenv('GCS_BUCKET', 'double-venture-442318-k8-optimization-results')
    FLAG_FILE = 'scheduler_enabled.flag'
    INSTRUMENTS_CONFIG_FILE = 'instruments_config.json'
    
    # CORS
    if request.method == 'OPTIONS':
        response = make_response('', 204)
        return _add_cors_headers(response)
    
    path = request.path.lower().rstrip('/')  # Remove trailing slash
    method = request.method
    
    logger.info(f"📥 Request: {method} {path}")
    
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(FLAG_FILE)
        
        # GET /scheduler/status - Check status
        if method == 'GET' and '/status' in path:
            try:
                if not blob.exists():
                    status = 'enabled'  # Default
                else:
                    status = blob.download_as_text().strip().lower()
                
                response = jsonify({
                    'status': status,
                    'timestamp': datetime.now().isoformat(),
                    'message': f'Scheduler is currently {status}'
                })
                return _add_cors_headers(response), 200
            except Exception as e:
                response = jsonify({
                    'status': 'unknown',
                    'error': str(e)
                })
                return _add_cors_headers(response), 500
        
        # POST /scheduler/enable - Enable
        elif method == 'POST' and '/enable' in path:
            blob.upload_from_string('enabled')
            response = jsonify({
                'status': 'enabled',
                'message': 'Scheduler enabled successfully',
                'timestamp': datetime.now().isoformat()
            })
            return _add_cors_headers(response), 200
        
        # POST /scheduler/disable - Disable
        elif method == 'POST' and '/disable' in path:
            blob.upload_from_string('disabled')
            response = jsonify({
                'status': 'disabled',
                'message': 'Scheduler disabled successfully',
                'timestamp': datetime.now().isoformat()
            })
            return _add_cors_headers(response), 200
        
        # POST /scheduler/trigger - Manual trigger
        elif method == 'POST' and '/trigger' in path:
            # Trigger the data updater Cloud Function via HTTP (with auth)
            import requests
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account
            import google.auth
            
            DATA_UPDATER_URL = os.getenv('DATA_UPDATER_URL', 
                'https://data-updater-6ovej2yaoa-uc.a.run.app')
            
            try:
                # Parse request body for filters
                body = request.get_json(silent=True) or {}
                filters = {
                    'instruments': body.get('instruments', []),  # e.g., ['GOLD', 'EURUSD']
                    'timeframes': body.get('timeframes', []),    # e.g., ['M5']
                    'force': body.get('force', False)
                }
                
                logger.info(f"🔄 Triggering data updater: {DATA_UPDATER_URL}")
                if filters['instruments']:
                    logger.info(f"   Instruments: {filters['instruments']}")
                if filters['timeframes']:
                    logger.info(f"   Timeframes: {filters['timeframes']}")
                
                # Get ID token for authentication (Cloud Function to Cloud Function)
                auth_req = Request()
                credentials, project = google.auth.default()
                
                # Refresh credentials to get ID token
                if hasattr(credentials, 'refresh'):
                    credentials.refresh(auth_req)
                
                # Get ID token for the target service
                if hasattr(credentials, 'id_token'):
                    id_token = credentials.id_token
                else:
                    # For service accounts, create ID token with target audience
                    from google.oauth2 import id_token as id_token_lib
                    id_token = id_token_lib.fetch_id_token(auth_req, DATA_UPDATER_URL)
                
                # Call data updater with authentication and filters
                headers = {
                    'Authorization': f'Bearer {id_token}',
                    'Content-Type': 'application/json'
                }
                resp = requests.post(DATA_UPDATER_URL, json=filters, headers=headers, timeout=540)
                
                if resp.status_code == 200:
                    response = jsonify({
                        'status': 'triggered',
                        'message': 'Data update started successfully',
                        'filters': filters,
                        'timestamp': datetime.now().isoformat(),
                        'updater_response': resp.json()
                    })
                    return _add_cors_headers(response), 200
                else:
                    logger.error(f"❌ Data updater error: {resp.status_code} - {resp.text}")
                    response = jsonify({
                        'status': 'error',
                        'message': f'Data updater returned error: {resp.status_code}',
                        'details': resp.text[:200],
                        'timestamp': datetime.now().isoformat()
                    })
                    return _add_cors_headers(response), 500
            except Exception as e:
                logger.error(f"❌ Failed to trigger data updater: {e}")
                response = jsonify({
                    'status': 'error',
                    'message': f'Failed to trigger data updater: {str(e)}',
                    'timestamp': datetime.now().isoformat()
                })
                return _add_cors_headers(response), 500
        
        # GET /instruments - Get configured instruments
        elif method == 'GET' and (path == '/instruments' or path.endswith('/instruments')):
            try:
                logger.info(f"📋 Fetching instruments config")
                config_blob = bucket.blob(INSTRUMENTS_CONFIG_FILE)
                
                if config_blob.exists():
                    config_json = config_blob.download_as_text()
                    config = json.loads(config_json)
                    instruments = config.get('instruments', [])
                else:
                    instruments = []
                
                # Format for display
                formatted = []
                for item in instruments:
                    if isinstance(item, (list, tuple)) and len(item) >= 3:
                        formatted.append({
                            'epic': item[0],
                            'timeframe': item[1],
                            'bars': item[2]
                        })
                
                response = jsonify({
                    'total': len(formatted),
                    'instruments': formatted,
                    'timestamp': datetime.now().isoformat()
                })
                return _add_cors_headers(response), 200
            except Exception as e:
                logger.error(f"❌ Failed to get instruments: {e}")
                response = jsonify({'error': str(e)})
                return _add_cors_headers(response), 500
        
        # POST /instruments - Add new instrument
        elif method == 'POST' and (path == '/instruments' or path.endswith('/instruments')):
            try:
                body = request.get_json()
                if not body:
                    response = jsonify({'error': 'Request body required'})
                    return _add_cors_headers(response), 400
                
                epic = body.get('epic')
                timeframe = body.get('timeframe')
                bars = body.get('bars')
                
                if not all([epic, timeframe, bars]):
                    response = jsonify({'error': 'epic, timeframe, and bars are required'})
                    return _add_cors_headers(response), 400
                
                logger.info(f"➕ Adding instrument: {epic} {timeframe} {bars} bars")
                
                # Load current config
                config_blob = bucket.blob(INSTRUMENTS_CONFIG_FILE)
                if config_blob.exists():
                    config_json = config_blob.download_as_text()
                    config = json.loads(config_json)
                    instruments = config.get('instruments', [])
                else:
                    instruments = []
                
                # Add new instrument (check for duplicates)
                new_instrument = [epic, timeframe, int(bars)]
                if new_instrument not in instruments:
                    instruments.append(new_instrument)
                    
                    # Save updated config
                    config = {
                        'instruments': instruments,
                        'updated_at': datetime.now().isoformat()
                    }
                    config_blob.upload_from_string(json.dumps(config, indent=2))
                    
                    logger.info(f"✅ Instrument added: {epic} {timeframe} {bars}")
                    response = jsonify({
                        'status': 'added',
                        'instrument': {'epic': epic, 'timeframe': timeframe, 'bars': bars},
                        'total_instruments': len(instruments)
                    })
                    return _add_cors_headers(response), 201
                else:
                    response = jsonify({
                        'status': 'already_exists',
                        'instrument': {'epic': epic, 'timeframe': timeframe, 'bars': bars}
                    })
                    return _add_cors_headers(response), 200
                    
            except Exception as e:
                logger.error(f"❌ Failed to add instrument: {e}")
                response = jsonify({'error': str(e)})
                return _add_cors_headers(response), 500
        
        # DELETE /instruments - Remove instrument
        elif method == 'DELETE' and (path == '/instruments' or path.endswith('/instruments')):
            try:
                body = request.get_json()
                if not body:
                    response = jsonify({'error': 'Request body required'})
                    return _add_cors_headers(response), 400
                
                epic = body.get('epic')
                timeframe = body.get('timeframe')
                bars = body.get('bars')
                
                if not all([epic, timeframe, bars]):
                    response = jsonify({'error': 'epic, timeframe, and bars are required'})
                    return _add_cors_headers(response), 400
                
                logger.info(f"➖ Removing instrument: {epic} {timeframe} {bars} bars")
                
                # Load current config
                config_blob = bucket.blob(INSTRUMENTS_CONFIG_FILE)
                if config_blob.exists():
                    config_json = config_blob.download_as_text()
                    config = json.loads(config_json)
                    instruments = config.get('instruments', [])
                else:
                    response = jsonify({'error': 'No instruments configured'})
                    return _add_cors_headers(response), 404
                
                # Remove instrument
                target = [epic, timeframe, int(bars)]
                if target in instruments:
                    instruments.remove(target)
                    
                    # Save updated config
                    config = {
                        'instruments': instruments,
                        'updated_at': datetime.now().isoformat()
                    }
                    config_blob.upload_from_string(json.dumps(config, indent=2))
                    
                    logger.info(f"✅ Instrument removed: {epic} {timeframe} {bars}")
                    response = jsonify({
                        'status': 'removed',
                        'instrument': {'epic': epic, 'timeframe': timeframe, 'bars': bars},
                        'total_instruments': len(instruments)
                    })
                    return _add_cors_headers(response), 200
                else:
                    response = jsonify({
                        'status': 'not_found',
                        'instrument': {'epic': epic, 'timeframe': timeframe, 'bars': bars}
                    })
                    return _add_cors_headers(response), 404
                    
            except Exception as e:
                logger.error(f"❌ Failed to remove instrument: {e}")
                response = jsonify({'error': str(e)})
                return _add_cors_headers(response), 500
        
        # GET /data - Get available data status
        elif method == 'GET' and (path == '/data' or path.endswith('/data')):
            try:
                logger.info(f"📊 Fetching data status from bucket: {BUCKET_NAME}")
                # List all CSV files in data/ folder
                blobs = bucket.list_blobs(prefix='data/')
                datasets = []
                
                for blob in blobs:
                    if blob.name.endswith('.csv'):
                        # Parse filename: data/GOLD_M5_5000bars.csv
                        filename = blob.name.split('/')[-1]
                        parts = filename.replace('.csv', '').split('_')
                        
                        if len(parts) >= 3:
                            instrument = parts[0]
                            timeframe = parts[1]
                            bars = parts[2].replace('bars', '')
                            
                            # Get file metadata
                            blob.reload()  # Refresh metadata
                            
                            datasets.append({
                                'instrument': instrument,
                                'timeframe': timeframe,
                                'bars': int(bars) if bars.isdigit() else 0,
                                'filename': filename,
                                'size_bytes': blob.size,
                                'size_mb': round(blob.size / (1024 * 1024), 2),
                                'last_updated': blob.updated.isoformat() if blob.updated else None,
                                'gcs_path': blob.name
                            })
                
                # Sort by instrument, then timeframe
                datasets.sort(key=lambda x: (x['instrument'], x['timeframe'], -x['bars']))
                
                logger.info(f"✅ Found {len(datasets)} datasets")
                response = jsonify({
                    'total_datasets': len(datasets),
                    'datasets': datasets,
                    'timestamp': datetime.now().isoformat()
                })
                return _add_cors_headers(response), 200
            except Exception as e:
                logger.error(f"❌ Failed to get data status: {e}")
                response = jsonify({
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                })
                return _add_cors_headers(response), 500
        
        # GET /datasets/summary - Get dataset summary with duplicates detection
        elif method == 'GET' and '/datasets/summary' in path:
            try:
                import sys
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
                from data.dataset_manager import get_dataset_summary
                
                logger.info("📊 Fetching dataset summary")
                summary = get_dataset_summary()
                
                response = jsonify(summary)
                return _add_cors_headers(response), 200
            except Exception as e:
                logger.error(f"❌ Failed to get dataset summary: {e}")
                response = jsonify({'error': str(e)})
                return _add_cors_headers(response), 500
        
        # DELETE /datasets/{filename} - Delete a specific dataset
        elif method == 'DELETE' and '/datasets/' in path:
            try:
                import sys
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
                from data.dataset_manager import delete_dataset
                
                # Extract filename from path
                filename = path.split('/datasets/')[-1]
                
                if not filename or not filename.endswith('.csv'):
                    response = jsonify({'error': 'Invalid filename. Must end with .csv'})
                    return _add_cors_headers(response), 400
                
                logger.info(f"🗑️  Deleting dataset: {filename}")
                success = delete_dataset(filename)
                
                if success:
                    response = jsonify({
                        'message': f'Dataset {filename} deleted successfully',
                        'filename': filename
                    })
                    return _add_cors_headers(response), 200
                else:
                    response = jsonify({
                        'error': f'Failed to delete {filename}',
                        'filename': filename
                    })
                    return _add_cors_headers(response), 404
            except Exception as e:
                logger.error(f"❌ Failed to delete dataset: {e}")
                response = jsonify({'error': str(e)})
                return _add_cors_headers(response), 500
        
        # GET /instruments - List configured instruments
        elif method == 'GET' and '/instruments' in path:
            try:
                # Import from data_updater
                import sys
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
                from data_updater import get_instruments_config
                
                logger.info("📋 Fetching instruments configuration")
                instruments = get_instruments_config()
                
                response = jsonify({
                    'total_instruments': len(instruments),
                    'instruments': [
                        {
                            'epic': epic,
                            'timeframe': timeframe,
                            'bars': bars
                        }
                        for epic, timeframe, bars in instruments
                    ],
                    'timestamp': datetime.now().isoformat()
                })
                return _add_cors_headers(response), 200
            except Exception as e:
                logger.error(f"❌ Failed to get instruments: {e}")
                response = jsonify({
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                })
                return _add_cors_headers(response), 500
        
        # POST /instruments - Add new instrument
        elif method == 'POST' and '/instruments' in path:
            try:
                # Import from data_updater
                import sys
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
                from data_updater import get_instruments_config, save_instruments_config
                
                # Parse request
                body = request.get_json()
                if not body:
                    response = jsonify({'error': 'Request body required'})
                    return _add_cors_headers(response), 400
                
                epic = body.get('epic')
                timeframe = body.get('timeframe')
                bars = body.get('bars')
                
                # Validate inputs
                if not epic or not timeframe or not bars:
                    response = jsonify({
                        'error': 'Missing required fields',
                        'required': ['epic', 'timeframe', 'bars']
                    })
                    return _add_cors_headers(response), 400
                
                if timeframe not in ['M5', 'M15']:
                    response = jsonify({
                        'error': f'Invalid timeframe: {timeframe}',
                        'valid_timeframes': ['M5', 'M15']
                    })
                    return _add_cors_headers(response), 400
                
                if not isinstance(bars, int) or bars <= 0:
                    response = jsonify({'error': 'bars must be a positive integer'})
                    return _add_cors_headers(response), 400
                
                logger.info(f"➕ Adding instrument: {epic} {timeframe} {bars}")
                
                # Load current config
                instruments = get_instruments_config()
                
                # Check if already exists
                exists = any(i[0] == epic and i[1] == timeframe for i in instruments)
                if exists:
                    response = jsonify({
                        'error': 'Instrument already exists',
                        'epic': epic,
                        'timeframe': timeframe
                    })
                    return _add_cors_headers(response), 409
                
                # Add new instrument
                instruments.append([epic, timeframe, bars])
                save_instruments_config(instruments)
                
                logger.info(f"✅ Added instrument: {epic} {timeframe} {bars}")
                response = jsonify({
                    'status': 'added',
                    'instrument': {
                        'epic': epic,
                        'timeframe': timeframe,
                        'bars': bars
                    },
                    'total_instruments': len(instruments),
                    'timestamp': datetime.now().isoformat()
                })
                return _add_cors_headers(response), 201
            except Exception as e:
                logger.error(f"❌ Failed to add instrument: {e}")
                response = jsonify({
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                })
                return _add_cors_headers(response), 500
        
        # DELETE /instruments - Remove instrument
        elif method == 'DELETE' and '/instruments' in path:
            try:
                # Import from data_updater
                import sys
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
                from data_updater import get_instruments_config, save_instruments_config
                
                # Parse request
                body = request.get_json()
                if not body:
                    response = jsonify({'error': 'Request body required'})
                    return _add_cors_headers(response), 400
                
                epic = body.get('epic')
                timeframe = body.get('timeframe')
                
                if not epic or not timeframe:
                    response = jsonify({
                        'error': 'Missing required fields',
                        'required': ['epic', 'timeframe']
                    })
                    return _add_cors_headers(response), 400
                
                logger.info(f"➖ Removing instrument: {epic} {timeframe}")
                
                # Load current config
                instruments = get_instruments_config()
                
                # Find and remove
                original_count = len(instruments)
                instruments = [i for i in instruments if not (i[0] == epic and i[1] == timeframe)]
                
                if len(instruments) == original_count:
                    response = jsonify({
                        'error': 'Instrument not found',
                        'epic': epic,
                        'timeframe': timeframe
                    })
                    return _add_cors_headers(response), 404
                
                # Save updated config
                save_instruments_config(instruments)
                
                logger.info(f"✅ Removed instrument: {epic} {timeframe}")
                response = jsonify({
                    'status': 'removed',
                    'instrument': {
                        'epic': epic,
                        'timeframe': timeframe
                    },
                    'total_instruments': len(instruments),
                    'timestamp': datetime.now().isoformat()
                })
                return _add_cors_headers(response), 200
            except Exception as e:
                logger.error(f"❌ Failed to remove instrument: {e}")
                response = jsonify({
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                })
                return _add_cors_headers(response), 500
        
        else:
            logger.warning(f"❌ Invalid endpoint: {method} {path}")
            response = jsonify({'error': 'Invalid endpoint', 'path': path, 'method': method})
            return _add_cors_headers(response), 404
            
    except Exception as e:
        response = jsonify({
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        })
        return _add_cors_headers(response), 500
