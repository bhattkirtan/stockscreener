"""
External Data API

FastAPI endpoints to serve economic calendar, news headlines, and macro regime data.

Endpoints:
- GET /api/v1/calendar - Economic calendar events
- GET /api/v1/news - News headlines
- GET /api/v1/macro - Macro regime
- GET /api/v1/status - Combined status
- GET /api/v1/is-blocked - Check if trading is blocked

Run:
    uvicorn src.api.external_data_api:app --reload --port 8001
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict
from datetime import datetime, timedelta
from pathlib import Path
import json
import logging

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Trading External Data API",
    description="API for economic calendar, news, and macro regime data",
    version="1.0.0"
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Response models
class CalendarEvent(BaseModel):
    date: str
    time_utc: str
    event: str
    description: str
    country: str
    importance: str
    block_minutes_before: int
    block_minutes_after: int


class NewsHeadline(BaseModel):
    article_id: str
    published_at: str
    source: str
    title: str
    description: str
    url: str
    matched_keywords: List[str]
    severity: str


class MacroRegime(BaseModel):
    regime: str
    confidence: float
    position_multiplier: float
    risk_mode: str
    indicators: Dict


class BlockStatus(BaseModel):
    is_blocked: bool
    reason: Optional[str] = None
    minutes_until_next_event: Optional[int] = None
    next_event: Optional[Dict] = None


class CombinedStatus(BaseModel):
    timestamp: str
    calendar_status: str
    news_status: str
    macro_status: str
    is_blocked: bool
    block_reason: Optional[str]
    macro_regime: Optional[str]
    position_multiplier: Optional[float]


# Data directory
DATA_DIR = Path("data")


def load_json_file(filename: str) -> Optional[Dict]:
    """Load JSON file from data directory"""
    filepath = DATA_DIR / filename
    
    if not filepath.exists():
        logger.warning(f"File not found: {filepath}")
        return None
    
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load {filename}: {e}")
        return None


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Trading External Data API",
        "version": "1.0.0",
        "endpoints": {
            "calendar": "/api/v1/calendar",
            "news": "/api/v1/news",
            "macro": "/api/v1/macro",
            "status": "/api/v1/status",
            "is_blocked": "/api/v1/is-blocked"
        }
    }


@app.get("/api/v1/calendar", response_model=List[CalendarEvent])
async def get_calendar(
    days_ahead: int = Query(7, ge=1, le=90, description="Days to look ahead"),
    high_impact_only: bool = Query(True, description="Filter to high-impact only")
):
    """
    Get economic calendar events
    
    Args:
        days_ahead: Number of days ahead to fetch (1-90)
        high_impact_only: Filter to high-impact events only
    
    Returns:
        List of calendar events
    """
    data = load_json_file("economic_calendar.json")
    
    if not data:
        raise HTTPException(status_code=503, detail="Calendar data not available")
    
    events = data.get('events', [])
    
    # Filter by date range
    today = datetime.utcnow().date()
    end_date = today + timedelta(days=days_ahead)
    
    filtered_events = []
    for event in events:
        event_date = datetime.fromisoformat(event['date']).date()
        
        if today <= event_date <= end_date:
            if high_impact_only and event.get('importance') != 'high':
                continue
            
            filtered_events.append(event)
    
    return filtered_events


@app.get("/api/v1/news", response_model=List[NewsHeadline])
async def get_news(
    hours_ago: int = Query(2, ge=1, le=24, description="Hours to look back"),
    high_impact_only: bool = Query(True, description="Filter to high-impact only")
):
    """
    Get news headlines
    
    Args:
        hours_ago: Hours to look back (1-24)
        high_impact_only: Filter to high-impact headlines only
    
    Returns:
        List of news headlines
    """
    data = load_json_file("news_headlines.json")
    
    if not data:
        raise HTTPException(status_code=503, detail="News data not available")
    
    headlines = data.get('headlines', [])
    
    # Filter by time
    cutoff_time = datetime.utcnow() - timedelta(hours=hours_ago)
    
    filtered_headlines = []
    for headline in headlines:
        published_at = datetime.fromisoformat(headline['published_at'])
        
        if published_at >= cutoff_time:
            if high_impact_only and headline.get('severity') != 'high':
                continue
            
            filtered_headlines.append(headline)
    
    return filtered_headlines


@app.get("/api/v1/macro", response_model=MacroRegime)
async def get_macro():
    """
    Get current macro regime
    
    Returns:
        Macro regime data with indicators
    """
    data = load_json_file("macro_regime.json")
    
    if not data:
        raise HTTPException(status_code=503, detail="Macro data not available")
    
    return {
        "regime": data.get('regime', 'unknown'),
        "confidence": data.get('confidence', 0.5),
        "position_multiplier": data.get('position_multiplier', 1.0),
        "risk_mode": data.get('risk_mode', 'unknown'),
        "indicators": data.get('indicators', {})
    }


@app.get("/api/v1/is-blocked", response_model=BlockStatus)
async def check_blocked(
    block_window_minutes: int = Query(15, description="Block window before/after events")
):
    """
    Check if trading is currently blocked
    
    Checks both calendar events and news headlines.
    
    Args:
        block_window_minutes: Minutes before/after events to block
    
    Returns:
        Block status with reason
    """
    current_time = datetime.utcnow()
    
    # Check calendar
    calendar_data = load_json_file("economic_calendar.json")
    if calendar_data:
        events = calendar_data.get('events', [])
        
        for event in events:
            event_datetime = datetime.fromisoformat(f"{event['date']} {event['time_utc']}")
            
            before_minutes = event.get('block_minutes_before', block_window_minutes)
            after_minutes = event.get('block_minutes_after', block_window_minutes)
            
            block_start = event_datetime - timedelta(minutes=before_minutes)
            block_end = event_datetime + timedelta(minutes=after_minutes)
            
            if block_start <= current_time <= block_end:
                minutes_to_event = int((event_datetime - current_time).total_seconds() / 60)
                
                return {
                    "is_blocked": True,
                    "reason": f"Calendar event: {event['event']} - {event['description']}",
                    "minutes_until_next_event": max(0, minutes_to_event),
                    "next_event": event
                }
    
    # Check news
    news_data = load_json_file("news_headlines.json")
    if news_data:
        headlines = news_data.get('headlines', [])
        
        for headline in headlines:
            published_at = datetime.fromisoformat(headline['published_at'])
            age_minutes = (current_time - published_at).total_seconds() / 60
            
            # Block for 10 minutes after high-impact headline
            if headline.get('severity') == 'high' and age_minutes < 10:
                return {
                    "is_blocked": True,
                    "reason": f"News headline: {headline['title']} (keywords: {', '.join(headline['matched_keywords'])})",
                    "minutes_until_next_event": None,
                    "next_event": None
                }
    
    # Find next event
    next_event = None
    min_minutes = float('inf')
    
    if calendar_data:
        for event in calendar_data.get('events', []):
            event_datetime = datetime.fromisoformat(f"{event['date']} {event['time_utc']}")
            
            if event_datetime > current_time:
                minutes = int((event_datetime - current_time).total_seconds() / 60)
                if minutes < min_minutes:
                    min_minutes = minutes
                    next_event = event
    
    return {
        "is_blocked": False,
        "reason": None,
        "minutes_until_next_event": int(min_minutes) if next_event else None,
        "next_event": next_event
    }


@app.get("/api/v1/status", response_model=CombinedStatus)
async def get_combined_status():
    """
    Get combined status of all data sources
    
    Returns:
        Combined status including blocking, macro regime, and data freshness
    """
    # Load all data
    calendar_data = load_json_file("economic_calendar.json")
    news_data = load_json_file("news_headlines.json")
    macro_data = load_json_file("macro_regime.json")
    
    # Check blocking
    block_status = await check_blocked()
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "calendar_status": "ready" if calendar_data else "unavailable",
        "news_status": "ready" if news_data else "unavailable",
        "macro_status": "ready" if macro_data else "unavailable",
        "is_blocked": block_status["is_blocked"],
        "block_reason": block_status["reason"],
        "macro_regime": macro_data.get('regime') if macro_data else None,
        "position_multiplier": macro_data.get('position_multiplier') if macro_data else None
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    calendar_data = load_json_file("economic_calendar.json")
    news_data = load_json_file("news_headlines.json")
    macro_data = load_json_file("macro_regime.json")
    
    return {
        "status": "healthy",
        "data_sources": {
            "calendar": "available" if calendar_data else "missing",
            "news": "available" if news_data else "missing",
            "macro": "available" if macro_data else "missing"
        },
        "timestamp": datetime.utcnow().isoformat()
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "src.api.external_data_api:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        log_level="info"
    )
