from dotenv import load_dotenv
from flask import jsonify, abort, request
import functions_framework
import google.cloud.logging
import json, logging, os, requests
import fs_client
from cachetools import TTLCache, cached

# ── Setup ────────────────────────────────────────────────────────────────────
db = fs_client.FirestoreDB()

# Cloud Logging
client = google.cloud.logging.Client()
client.setup_logging()
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

# Load secrets
load_dotenv()
secret_json = os.getenv('apicredentials') or '{}'
secrets     = json.loads(secret_json)
api_key     = secrets['apikey']
username    = secrets['username']
password    = secrets['password']
capKey      = secrets['capkey']

# ── Caches for encryption key & token ────────────────────────────────────────
# TTL 55 minutes to slightly undercut a 1h session expiry
enc_key_cache = TTLCache(maxsize=1, ttl=55*60)
token_cache   = TTLCache(maxsize=1, ttl=55*60)

@cached(enc_key_cache)
def get_encryption_key() -> str:
    url = 'https://demo-api-capital.backend-capital.com/api/v1/session/encryptionKey'
    resp = requests.get(url, headers={'X-CAP-API-KEY': capKey})
    if resp.status_code == 429:
        abort(429, description="Capital API rate limit on encryptionKey")
    if not resp.ok:
        logger.error("Failed to fetch encryption key: %s", resp.text)
        abort(resp.status_code, description="Failed to obtain encryption key")
    return resp.json().get('encryptionKey')

@cached(token_cache)
def get_token() -> dict:
    # We assume unencrypted login
    ek = get_encryption_key()
    payload = {
        'identifier': username,
        'password': password,
        'encryptedPassword': False
    }
    headers = {
        'X-CAP-API-KEY': capKey,
        'Content-Type': 'application/json'
    }
    resp = requests.post('https://demo-api-capital.backend-capital.com/api/v1/session',
                         headers=headers, json=payload)
    if resp.status_code == 429:
        abort(429, description="Capital API rate limit on session")
    if not resp.ok:
        logger.error("Failed to fetch session token: %s", resp.text)
        abort(resp.status_code, description="Failed to obtain session token")
    return {
        'CST': resp.headers.get('CST'),
        'X-SECURITY-TOKEN': resp.headers.get('X-SECURITY-TOKEN')
    }

def capital_request(method: str, path: str, **kwargs) -> requests.Response:
    """Helper to call Capital endpoints with proper headers."""
    tokens = get_token()
    headers = {
        'CST': tokens['CST'],
        'X-SECURITY-TOKEN': tokens['X-SECURITY-TOKEN'],
        'Content-Type': 'application/json'
    }    
    
    url = f'https://demo-api-capital.backend-capital.com{path}'
    logger.debug("Request: method=%s, url=%s, headers=%s, kwargs=%s",
                 method, url, {k: headers[k] for k in ('CST', 'X-SECURITY-TOKEN')}, kwargs)
    resp = requests.request(method, url, headers=headers, **kwargs)
    if resp.status_code == 429:
        abort(429, description=f"Capital API rate limit on {path}")
    return resp

# ── Helper: get open positions ───────────────────────────────────────────────
def get_open_positions() -> requests.Response:
    return capital_request('GET', '/api/v1/positions')

# ── Helper: create position ─────────────────────────────────────────────────
def create_position(epic, size, direction, stopLevel, profitLevel) -> requests.Response:
    body = {
        "epic": epic,
        "direction": direction,
        "size": size,
        "guaranteedStop": False,
        "stopLevel": stopLevel,
        "profitLevel": profitLevel
    }
    return capital_request('POST', '/api/v1/positions', json=body)

# ── Helper: update position ─────────────────────────────────────────────────
def update_position(dealId, profitLevel, stopLevel) -> requests.Response:
    body = {
        "profitLevel": profitLevel,
        "stopLevel": stopLevel
    }
    return capital_request('PUT', f'/api/v1/positions/{dealId}', json=body)

# ── Helper: close position ──────────────────────────────────────────────────
def close_position(dealId) -> requests.Response:
    return capital_request('DELETE', f'/api/v1/positions/{dealId}')

# ── HTTP Handlers ────────────────────────────────────────────────────────────
def handle_create_position(req):
    data = req.get_json(force=True)
    if data.get('key') != api_key:
        abort(401, description="Unauthorized")

    action = data.get('action')
    epic   = data.get('epic')
    size   = data.get('size1')
    dir_   = data.get('direction')
    sl     = data.get('stopLevel')
    tp     = data.get('fibLevel1')
    inTime = data.get('inTradeTime')

    # Early exit if outside trading hours
    if not inTime:
        return jsonify({'response': 'Outside trading hours, nothing done'}), 200

    # 1) Check for existing same-direction position
    resp = get_open_positions()
    positions = resp.json().get("positions", [])
    same = [p for p in positions
            if p["position"]["direction"] == dir_
            and p["market"]["epic"] == epic]
    if same:
        if action == "entry":
            return jsonify({'response': 'Position already exists'}), 400
        if action == "update-sl":
            for p in same:
                dealId = p["position"]["dealId"]
                profitLevel = p["position"]["profitLevel"]
                up_resp = update_position(dealId, tp, sl)
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

    
    # 2) Close any opposite positions
    opposite = [p for p in positions
                if p["position"]["direction"] != dir_
                and p["market"]["epic"] == epic]
    for p in opposite:
        close_position(p["position"]["dealId"])

    # 3) Create new position
    create_resp = create_position(epic, size, dir_, sl, tp)
    if not create_resp.ok:
        abort(create_resp.status_code,
              description=f"Failed to create position: {create_resp.text}")

    # 4) Persist to Firestore
    new_open = get_open_positions()
    docs = [p for p in new_open.json().get("positions", [])
            if p["market"]["epic"] == epic]
    db.add_document("positions", epic, {"responses": docs})

    result = create_resp.json()
    result.update({"tplevel": tp, "status_code": create_resp.status_code})
    return jsonify({"responses": [result]}), 200

def handle_update_position(req):
    data = req.get_json(force=True)
    if data.get('key') != api_key:
        abort(401, description="Unauthorized")
    if data.get('action') != "update-sl":
        abort(400, description="Invalid action")

    epic   = data.get('epic')
    sl     = data.get('stopLevel')

    resp = get_open_positions()
    positions = [p for p in resp.json().get("positions", [])
                 if p["market"]["epic"] == epic]

    responses = []
    for p in positions:
        dealId      = p["position"]["dealId"]
        profitLevel = p["position"]["profitLevel"]
        up_resp     = update_position(dealId, profitLevel, sl)
        if not up_resp.ok:
            abort(up_resp.status_code,
                  description=f"Failed to update {dealId}: {up_resp.text}")
        responses.append(up_resp.text)

    return jsonify(responses), 200

@functions_framework.http
def hello_http(req):
    path   = req.path
    method = req.method

    if method == 'GET' and path == '/get_positions':
        resp = get_open_positions()
        return jsonify(resp.json()), 200

    if method == 'POST' and path == '/create_position':
        return handle_create_position(req)

    if method == 'POST' and path == '/updte_position':
        return handle_update_position(req)

    if method == 'DELETE' and path.startswith('/close_position/'):
        dealId = path.rsplit('/', 1)[-1]
        resp   = close_position(dealId)
        return jsonify(resp.json()), resp.status_code

    abort(404, description="Not found")