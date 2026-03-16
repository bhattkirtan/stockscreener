"""
Enhanced Cloud Functions API for Strategy Optimization
Exposes ALL customizable parameters for full UI control
Plus External Data feeds (Calendar, News, Macro Regime)
"""

import os
import json
import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path
import functions_framework
from flask import Request, jsonify, make_response
from google.cloud import storage, tasks_v2
from google.protobuf import timestamp_pb2
from pydantic import BaseModel, Field, validator
from enum import Enum

# Configuration
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'double-venture-442318-k8')
REGION = os.environ.get('REGION', 'us-central1')
QUEUE_NAME = os.environ.get('QUEUE_NAME', 'optimization-queue')
WORKER_URL = os.environ.get('WORKER_URL')
BUCKET_NAME = os.environ.get('GCS_BUCKET', 'double-venture-442318-k8-optimization-results')

# Data directory for external feeds
DATA_DIR = Path(__file__).parent.parent / 'data'

# Initialize clients
storage_client = storage.Client()
tasks_client = tasks_v2.CloudTasksClient()

# Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# Request/Response Models
# ============================================================================

class OptimizationMode(str, Enum):
    """Optimization modes with different parameter grid sizes"""
    QUICK = "quick"      # ~200-500 combinations, ~2-3 min
    MEDIUM = "medium"    # ~1000-2000 combinations, ~5-8 min
    FULL = "full"        # ~5000+ combinations, ~15-30 min


class TPSLStrategy(str, Enum):
    """Take Profit / Stop Loss strategy types"""
    FIXED = "fixed"      # Fixed pip distance
    ATR = "atr"          # ATR-based dynamic
    BOTH = "both"        # Test both strategies


class OptimizationRequest(BaseModel):
    """
    Enhanced optimization request with ALL customizable parameters
    Provides defaults for quick start, allows deep customization
    """
    
    # ── Core Settings ─────────────────────────────────────────────────────
    instrument: str = Field(default="GOLD", description="Trading instrument (GOLD, EURUSD, etc)")
    timeframe: str = Field(default="M5", description="Chart timeframe (M5, M15, H1, etc)")
    initial_capital: float = Field(default=10000.0, description="Starting capital (USD)", ge=100, le=1000000)
    position_size: float = Field(default=10.0, description="Default position size (lots)", ge=0.01, le=100)
    
    # ── Optimization Mode ─────────────────────────────────────────────────
    mode: OptimizationMode = Field(default=OptimizationMode.QUICK, description="Optimization depth")
    parallel: bool = Field(default=True, description="Use parallel processing")
    n_jobs: int = Field(default=-1, description="Number of CPU cores (-1 = all)", ge=-1, le=64)
    
    # ── Strategy Parameters (Override default ranges) ────────────────────
    # Supertrend
    supertrend_periods: Optional[List[int]] = Field(default=None, description="Supertrend ATR periods [7-15]")
    supertrend_multipliers: Optional[List[float]] = Field(default=None, description="Supertrend ATR multipliers [1.5-4.0]")
    
    # Moving Averages
    sma_fast_periods: Optional[List[int]] = Field(default=None, description="Fast SMA periods [10-30]")
    sma_slow_periods: Optional[List[int]] = Field(default=None, description="Slow SMA periods [40-100]")
    ema_periods: Optional[List[int]] = Field(default=None, description="EMA periods [15-30]")
    
    # Bollinger Bands
    bb_periods: Optional[List[int]] = Field(default=None, description="BB periods [15-25]")
    bb_stds: Optional[List[float]] = Field(default=None, description="BB std deviations [1.5-3.0]")
    
    # ── Take Profit / Stop Loss ───────────────────────────────────────────
    tp_sl_strategy: TPSLStrategy = Field(default=TPSLStrategy.BOTH, description="TP/SL calculation method")
    
    # Fixed TP/SL (pip distances)
    sl_pips_range: Optional[List[float]] = Field(default=None, description="Stop loss pips [10-50]")
    tp_pips_range: Optional[List[float]] = Field(default=None, description="Take profit pips [20-100]")
    
    # ATR-based TP/SL (multipl of ATR)
    atr_sl_multipliers: Optional[List[float]] = Field(default=None, description="ATR SL multipliers [1.0-3.0]")
    atr_tp_multipliers: Optional[List[float]] = Field(default=None, description="ATR TP multipliers [2.0-8.0]")
    
    # ── Pip Value Optimization ────────────────────────────────────────────
    pip_values: Optional[List[float]] = Field(
        default=None, 
        description="Pip value scaling for leverage optimization [0.5-10.0]"
    )
    
    # ── Advanced Options ──────────────────────────────────────────────────
    min_trades: int = Field(default=10, description="Min trades for valid strategy", ge=1)
    min_win_rate: float = Field(default=0.0, description="Min win rate filter [0-1]", ge=0, le=1)
    max_drawdown_pct: Optional[float] = Field(default=None, description="Max acceptable drawdown %", le=100)
    
    # ── Data Selection ────────────────────────────────────────────────────
    csv_filename: Optional[str] = Field(default=None, description="Override auto CSV selection")
    max_bars: Optional[int] = Field(default=None, description="Override max bars to use")
    
    @validator('sl_pips_range', 'tp_pips_range', 'atr_sl_multipliers', 'atr_tp_multipliers')
    def validate_positive_list(cls, v):
        if v is not None and any(x <= 0 for x in v):
            raise ValueError("All values must be positive")
        return v
    
    @validator('pip_values')
    def validate_pip_values(cls, v):
        if v is not None:
            if any(x <= 0 or x > 20 for x in v):
                raise ValueError("Pip values must be between 0 and 20")
        return v


class OptimizationStatus(BaseModel):
    """Current status of an optimization run"""
    run_id: str
    status: str  # queued, running, completed, failed
    instrument: str
    timeframe: str
    mode: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    progress: Optional[Dict[str, Any]] = None
    total_combinations: Optional[int] = None
    tested_combinations: Optional[int] = None
    best_return_pct: Optional[float] = None
    error: Optional[str] = None


class OptimizationResult(BaseModel):
    """Optimization results summary"""
    run_id: str
    instrument: str
    timeframe: str
    total_combinations: int
    valid_strategies: int
    best_strategy: Dict[str, Any]
    top_10_strategies: List[Dict[str, Any]]
    execution_time_seconds: float
    completed_at: str


# ============================================================================
# Helper Functions
# ============================================================================

def get_bucket():
    """Get GCS bucket"""
    return storage_client.bucket(BUCKET_NAME)


def get_default_param_grid(mode: OptimizationMode) -> Dict[str, List]:
    """
    Get default parameter grid based on mode
    Matches optimizer's define_parameter_grid() and define_quick_grid()
    """
    if mode == OptimizationMode.QUICK:
        return {
            'supertrend_period': [10],
            'supertrend_multiplier': [2.0, 2.5, 3.0],
            'sma_fast': [15, 20],
            'sma_slow': [50],
            'ema_period': [21],
            'bb_period': [20],
            'bb_std': [2.0, 2.5],
            'sl_pips': [15, 20, 25, 30],
            'tp_pips': [30, 40, 45, 50, 60, 75, 90],
            'atr_sl_multiplier': [1.5, 2.0, 2.5],
            'atr_tp_multiplier': [3.0, 4.0, 5.0, 6.0],
            'pip_value': [1.5, 2.0, 2.5, 3.0, 5.0],
        }
    elif mode == OptimizationMode.MEDIUM:
        return {
            'supertrend_period': [7, 10, 14],
            'supertrend_multiplier': [2.0, 2.5, 3.0],
            'sma_fast': [15, 20, 25],
            'sma_slow': [40, 50, 60],
            'ema_period': [18, 21, 25],
            'bb_period': [18, 20, 22],
            'bb_std': [1.8, 2.0, 2.2, 2.5],
            'sl_pips': [12, 15, 18, 20, 25, 30],
            'tp_pips': [25, 30, 40, 45, 50, 60, 75, 90],
            'atr_sl_multiplier': [1.2, 1.5, 2.0, 2.5, 3.0],
            'atr_tp_multiplier': [2.5, 3.0, 4.0, 5.0, 6.0, 8.0],
            'pip_value': [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0],
        }
    else:  # FULL
        return {
            'supertrend_period': [7, 10, 12, 14, 17],
            'supertrend_multiplier': [1.5, 2.0, 2.5, 3.0, 3.5],
            'sma_fast': [10, 15, 20, 25, 30],
            'sma_slow': [40, 50, 60, 75, 100],
            'ema_period': [15, 18, 21, 25, 30],
            'bb_period': [15, 18, 20, 22, 25],
            'bb_std': [1.5, 1.8, 2.0, 2.2, 2.5, 3.0],
            'sl_pips': [10, 12, 15, 18, 20, 22, 25, 30, 40, 50],
            'tp_pips': [20, 25, 30, 40, 45, 50, 60, 75, 90, 100],
            'atr_sl_multiplier': [1.0, 1.2, 1.5, 1.8, 2.0, 2.5, 3.0],
            'atr_tp_multiplier': [2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
            'pip_value': [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.5, 10.0],
        }


def merge_custom_params(defaults: Dict[str, List], request: OptimizationRequest) -> Dict[str, List]:
    """Merge custom parameters with defaults"""
    grid = defaults.copy()
    
    # Override with custom values if provided
    if request.supertrend_periods: grid['supertrend_period'] = request.supertrend_periods
    if request.supertrend_multipliers: grid['supertrend_multiplier'] = request.supertrend_multipliers
    if request.sma_fast_periods: grid['sma_fast'] = request.sma_fast_periods
    if request.sma_slow_periods: grid['sma_slow'] = request.sma_slow_periods
    if request.ema_periods: grid['ema_period'] = request.ema_periods
    if request.bb_periods: grid['bb_period'] = request.bb_periods
    if request.bb_stds: grid['bb_std'] = request.bb_stds
    if request.sl_pips_range: grid['sl_pips'] = request.sl_pips_range
    if request.tp_pips_range: grid['tp_pips'] = request.tp_pips_range
    if request.atr_sl_multipliers: grid['atr_sl_multiplier'] = request.atr_sl_multipliers
    if request.atr_tp_multipliers: grid['atr_tp_multiplier'] = request.atr_tp_multipliers
    if request.pip_values: grid['pip_value'] = request.pip_values
    
    return grid


def create_cloud_task(run_id: str, payload: dict):
    """Create Cloud Task to trigger optimization worker"""
    parent = tasks_client.queue_path(PROJECT_ID, REGION, QUEUE_NAME)
    
    task = {
        'http_request': {
            'http_method': tasks_v2.HttpMethod.POST,
            'url': WORKER_URL,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps(payload).encode(),
            'oidc_token': {
                'service_account_email': f'{PROJECT_ID}@appspot.gserviceaccount.com'
            }
        }
    }
    
    response = tasks_client.create_task(request={"parent": parent, "task": task})
    return response.name


def add_cors_headers(response):
    """Add CORS headers to response"""
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


def load_json_file(filename: str) -> Optional[Dict]:
    """Load JSON file from GCS external-data folder"""
    try:
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(f'external-data/{filename}')
        
        if blob.exists():
            data = blob.download_as_text()
            return json.loads(data)
        else:
            logging.warning(f"File not found in GCS: external-data/{filename}")
            return None
    except Exception as e:
        logging.error(f"Error loading {filename} from GCS: {e}")
        return None


def start_optimization(request: Request):
    """Start new optimization run"""
    try:
        data = request.get_json()
        req = OptimizationRequest(**data)
        
        # Generate run ID
        run_id = str(uuid.uuid4())[:8]
        
        # Get parameter grid (defaults + custom overrides)
        default_grid = get_default_param_grid(req.mode)
        final_grid = merge_custom_params(default_grid, req)
        
        # Estimate combinations
        from itertools import product
        base_params = ['supertrend_period', 'supertrend_multiplier', 'sma_fast', 'sma_slow', 
                      'ema_period', 'bb_period', 'bb_std', 'pip_value']
        base_count = 1
        for p in base_params:
            base_count *= len(final_grid.get(p, [1]))
        
        # TP/SL combinations
        fixed_count = len(final_grid.get('sl_pips', [])) * len(final_grid.get('tp_pips', []))
        atr_count = len(final_grid.get('atr_sl_multiplier', [])) * len(final_grid.get('atr_tp_multiplier', []))
        
        if req.tp_sl_strategy == TPSLStrategy.BOTH:
            est_combinations = base_count * (fixed_count + atr_count)
        elif req.tp_sl_strategy == TPSLStrategy.FIXED:
            est_combinations = base_count * fixed_count
        else:  # ATR
            est_combinations = base_count * atr_count
        
        # Create metadata
        metadata = {
            'run_id': run_id,
            'status': 'queued',
            'instrument': req.instrument,
            'timeframe': req.timeframe,
            'mode': req.mode.value,
            'created_at': datetime.now().isoformat(),
            'estimated_combinations': est_combinations,
            'config': req.dict()
        }
        
        # Save metadata to GCS
        bucket = get_bucket()
        blob = bucket.blob(f"{run_id}/metadata.json")
        blob.upload_from_string(json.dumps(metadata, indent=2))
        
        # Create Cloud Task payload (send full config to worker)
        task_payload = {
            'run_id': run_id,
            'config': req.dict(),
            'param_grid': final_grid
        }
        
        # Enqueue task
        task_name = create_cloud_task(run_id, task_payload)
        
        response = jsonify({
            'run_id': run_id,
            'status': 'queued',
            'estimated_combinations': est_combinations,
            'task_name': task_name
        })
        return add_cors_headers(response), 202
        
    except Exception as e:
        return add_cors_headers(jsonify({"error": str(e)})), 400


def get_optimization_status(run_id: str):
    """Get optimization status and results"""
    try:
        bucket = get_bucket()
        
        # Load metadata
        metadata_blob = bucket.blob(f"{run_id}/metadata.json")
        if not metadata_blob.exists():
            return add_cors_headers(jsonify({"error": "Run not found"})), 404
        
        metadata = json.loads(metadata_blob.download_as_text())
        
        # Check for results (try multiple filenames for backward compatibility)
        results_blob = bucket.blob(f"{run_id}/FINAL_SUMMARY.json")
        if not results_blob.exists():
            results_blob = bucket.blob(f"{run_id}/results.json")
        
        if results_blob.exists():
            results = json.loads(results_blob.download_as_text())
            metadata['results'] = results
        
        return add_cors_headers(jsonify(metadata)), 200
        
    except Exception as e:
        return add_cors_headers(jsonify({"error": str(e)})), 500


def list_optimizations():
    """List all optimization runs"""
    try:
        bucket = get_bucket()
        runs = []
        
        # List all run directories
        blobs = bucket.list_blobs()
        seen_runs = set()
        
        for blob in blobs:
            parts = blob.name.split('/')
            if len(parts) >= 2:
                run_id = parts[0]
                if run_id not in seen_runs and blob.name.endswith('metadata.json'):
                    try:
                        metadata = json.loads(blob.download_as_text())
                        runs.append(metadata)
                        seen_runs.add(run_id)
                    except:
                        pass
        
        # Sort by created_at descending
        runs.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        return add_cors_headers(jsonify({"runs": runs, "total": len(runs)})), 200
        
    except Exception as e:
        return add_cors_headers(jsonify({"error": str(e)})), 500


def delete_optimization(run_id: str):
    """Delete optimization results"""
    try:
        bucket = get_bucket()
        blobs = bucket.list_blobs(prefix=f"{run_id}/")
        
        deleted = 0
        for blob in blobs:
            blob.delete()
            deleted += 1
        
        if deleted == 0:
            return add_cors_headers(jsonify({"error": "Run not found"})), 404
        
        return add_cors_headers(jsonify({"deleted": deleted})), 200
        
    except Exception as e:
        return add_cors_headers(jsonify({"error": str(e)})), 500


# ============================================================================
# External Data Endpoints
# ============================================================================

def get_calendar(request: Request):
    """
    Get economic calendar events
    
    Query params:
    - days_ahead: int (default: 7) - How many days ahead to include
    - high_impact_only: bool (default: false) - Only high-impact events
    """
    try:
        # Load calendar data
        calendar_json = load_json_file('economic_calendar.json')
        if not calendar_json or 'events' not in calendar_json:
            return add_cors_headers(jsonify({
                "error": "Calendar data not available",
                "events": []
            })), 200
        
        calendar_data = calendar_json.get('events', [])
        
        # Get query params
        days_ahead = int(request.args.get('days_ahead', 7))
        high_impact_only = request.args.get('high_impact_only', 'false').lower() == 'true'
        
        # Filter events
        now = datetime.utcnow()
        cutoff = now + timedelta(days=days_ahead)
        
        filtered_events = []
        for event in calendar_data:
            # Parse event time from date + time_utc
            event_date = datetime.fromisoformat(event['date'])
            time_parts = event.get('time_utc', '00:00').split(':')
            event_time = event_date.replace(hour=int(time_parts[0]), minute=int(time_parts[1]))
            
            # Check if within time range
            if event_time < now or event_time > cutoff:
                continue
            
            # Check if high-impact filter applies
            if high_impact_only and event.get('importance') != 'high':
                continue
            
            # Add time until event
            time_until = event_time - now
            event['hours_until'] = round(time_until.total_seconds() / 3600, 1)
            event['event_time_utc'] = event_time.isoformat()
            
            filtered_events.append(event)
        
        # Sort by date  +time
        filtered_events.sort(key=lambda x: x.get('event_time_utc', x['date']))
        
        return add_cors_headers(jsonify({
            "events": filtered_events,
            "total": len(filtered_events),
            "filters": {
                "days_ahead": days_ahead,
                "high_impact_only": high_impact_only
            }
        })), 200
        
    except Exception as e:
        return add_cors_headers(jsonify({"error": str(e)})), 500


def get_news(request: Request):
    """
    Get news headlines
    
    Query params:
    - hours_ago: int (default: 2) - How many hours back to include
    """
    try:
        # Load news data
        news_data = load_json_file('news_headlines.json')
        if not news_data:
            return add_cors_headers(jsonify({
                "error": "News data not available",
                "headlines": [],
                "updated_at": None
            })), 200
        
        # Get query params
        hours_ago = int(request.args.get('hours_ago', 2))
        
        # Filter headlines by time
        cutoff = datetime.utcnow() - timedelta(hours=hours_ago)
        
        filtered_headlines = []
        for headline in news_data.get('headlines', []):
            pub_time = datetime.fromisoformat(headline['published_at'].replace('Z', '+00:00'))
            
            if pub_time >= cutoff:
                # Add age in minutes
                age = datetime.utcnow() - pub_time
                headline['age_minutes'] = int(age.total_seconds() / 60)
                filtered_headlines.append(headline)
        
        # Sort by published_at descending (newest first)
        filtered_headlines.sort(key=lambda x: x['published_at'], reverse=True)
        
        return add_cors_headers(jsonify({
            "headlines": filtered_headlines,
            "total": len(filtered_headlines),
            "updated_at": news_data.get('updated_at'),
            "total_high_impact": news_data.get('high_impact_count', 0),
            "filters": {
                "hours_ago": hours_ago
            }
        })), 200
        
    except Exception as e:
        return add_cors_headers(jsonify({"error": str(e)})), 500


def get_macro(request: Request):
    """Get current macro regime from FRED data"""
    try:
        # Load macro regime data
        macro_data = load_json_file('macro_regime.json')
        if not macro_data:
            return add_cors_headers(jsonify({
                "error": "Macro data not available",
                "regime": "unknown",
                "confidence": 0.0
            })), 200
        
        # Calculate data age
        updated_at = datetime.fromisoformat(macro_data['updated_at'].replace('Z', '+00:00'))
        age_hours = (datetime.utcnow() - updated_at).total_seconds() / 3600
        
        macro_data['data_age_hours'] = round(age_hours, 1)
        macro_data['is_fresh'] = age_hours < 24
        
        return add_cors_headers(jsonify(macro_data)), 200
        
    except Exception as e:
        return add_cors_headers(jsonify({"error": str(e)})), 500


def check_blocked(request: Request):
    """
    Check if trading should be blocked based on calendar + news
    
    Returns:
    - blocked: bool
    - reason: str (if blocked)
    - next_event: dict (if calendar event upcoming)
    - recent_news: list (if news headlines recent)
    """
    try:
        blocked = False
        reasons = []
        next_event = None
        recent_news = []
        
        # Check calendar
        calendar_json = load_json_file('economic_calendar.json')
        calendar_data = calendar_json.get('events', []) if calendar_json else []
        
        if calendar_data:
            now = datetime.utcnow()
            
            for event in calendar_data:
                # Parse event time from date + time_utc
                event_date = datetime.fromisoformat(event['date'])
                time_parts = event.get('time_utc', '00:00').split(':')
                event_time = event_date.replace(hour=int(time_parts[0]), minute=int(time_parts[1]))
                
                # Get custom block window or use defaults
                block_before = event.get('block_minutes_before', 30)
                block_after = event.get('block_minutes_after', 10)
                
                # Check block window
                block_start = event_time - timedelta(minutes=block_before)
                block_end = event_time + timedelta(minutes=block_after)
                
                if block_start <= now <= block_end:
                    blocked = True
                    minutes_until = (event_time - now).total_seconds() / 60
                    reasons.append(f"Economic event: {event.get('description', event.get('event'))} in {int(minutes_until)} min")
                    next_event = event
                    break
        
        # Check news
        news_data = load_json_file('news_headlines.json')
        if news_data:
            now = datetime.utcnow()
            
            for headline in news_data.get('headlines', []):
                pub_time = datetime.fromisoformat(headline['published_at'].replace('Z', '+00:00'))
                age_minutes = (now - pub_time).total_seconds() / 60
                
                # Block for 10 minutes after high-impact news
                if age_minutes < 10 and headline.get('severity') == 'high':
                    blocked = True
                    reasons.append(f"High-impact news: {headline['title'][:50]}...")
                    recent_news.append(headline)
        
        return add_cors_headers(jsonify({
            "blocked": blocked,
            "reasons": reasons,
            "next_event": next_event,
            "recent_news": recent_news,
            "checked_at": datetime.utcnow().isoformat()
        })), 200
        
    except Exception as e:
        return add_cors_headers(jsonify({"error": str(e)})), 500


def get_external_data_status(request: Request):
    """Get combined status of all external data sources"""
    try:
        status = {
            "timestamp": datetime.utcnow().isoformat(),
            "sources": {}
        }
        
        # Calendar status
        calendar_json = load_json_file('economic_calendar.json')
        if calendar_json and 'events' in calendar_json:
            events = calendar_json.get('events', [])
            status["sources"]["calendar"] = {
                "status": "available",
                "total_events": len(events),
                "generated_at": calendar_json.get('generated_at'),
                "event_count": calendar_json.get('event_count', 0)
            }
        else:
            status["sources"]["calendar"] = {"status": "unavailable"}
        
        # News status
        news_data = load_json_file('news_headlines.json')
        if news_data:
            status["sources"]["news"] = {
                "status": "available",
                "updated_at": news_data.get('updated_at'),
                "high_impact_count": news_data.get('high_impact_count', 0),
                "total_headlines": news_data.get('total_headlines', 0)
            }
        else:
            status["sources"]["news"] = {"status": "unavailable"}
        
        # Macro regime status
        macro_data = load_json_file('macro_regime.json')
        if macro_data:
            updated_at = datetime.fromisoformat(macro_data['updated_at'].replace('Z', '+00:00'))
            age_hours = (datetime.utcnow() - updated_at).total_seconds() / 3600
            
            status["sources"]["macro"] = {
                "status": "available",
                "regime": macro_data.get('regime'),
                "confidence": macro_data.get('confidence'),
                "updated_at": macro_data.get('updated_at'),
                "age_hours": round(age_hours, 1),
                "is_fresh": age_hours < 24
            }
        else:
            status["sources"]["macro"] = {"status": "unavailable"}
        
        # Overall health
        available = sum(1 for s in status["sources"].values() if s.get("status") == "available")
        status["health"] = "healthy" if available == 3 else "degraded" if available > 0 else "down"
        status["available_sources"] = available
        
        return add_cors_headers(jsonify(status)), 200
        
    except Exception as e:
        return add_cors_headers(jsonify({"error": str(e)})), 500


def optimize_api(request: Request):
    """
    Main entry point for the Cloud Function
    
=== Optimization Endpoints ===
    POST /optimize - Start new optimization
    POST / - Start new optimization (alias)
    GET /optimize/{run_id} - Get optimization status
    GET /optimize - List all optimizations
    GET / - List all optimizations (alias)
    DELETE /optimize/{run_id} - Delete optimization results
    
    === External Data Endpoints ===
    GET /api/v1/calendar - Economic calendar events
    GET /api/v1/news - News headlines  
    GET /api/v1/macro - Macro regime (FRED data)
    GET /api/v1/is-blocked - Check if trading blocked
    GET /api/v1/status - Combined external data status
    GET /health - Health check
    """
    
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = make_response('', 204)
        return add_cors_headers(response)
    
    # Normalize path
    path = request.path.rstrip('/')
    if path == '':
        path = '/'
    
    # === External Data Routes ===
    if path == '/api/v1/calendar':
        return get_calendar(request)
    if path == '/api/v1/news':
        return get_news(request)
    if path == '/api/v1/macro':
        return get_macro(request)
    if path == '/api/v1/is-blocked':
        return check_blocked(request)
    if path == '/api/v1/status':
        return get_external_data_status(request)
    if path == '/health':
        return add_cors_headers(jsonify({"status": "healthy"})), 200
    
    # === Optimization Routes ===
    if path == '/' and request.method == 'GET':
        return list_optimizations()
    if path in ['/optimize', '/'] and request.method == 'POST':
        return start_optimization(request)
    if path.startswith('/optimize/'):
        run_id = path.split('/')[-1]
        if request.method == 'GET':
            return get_optimization_status(run_id)
        elif request.method == 'DELETE':
            return delete_optimization(run_id)
    if path == '/optimize' and request.method == 'GET':
        return list_optimizations()
    
    return add_cors_headers(jsonify({"error": "Not found"})), 404
