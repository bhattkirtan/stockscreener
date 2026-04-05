"""
External market data endpoints — served under /v1/*
(nginx strips /api prefix, so browser /api/v1/... → backend /v1/...)

Endpoints:
  GET /v1/calendar?days_ahead=7&high_impact_only=false
  GET /v1/news?hours_ago=10
  GET /v1/macro
  GET /v1/is-blocked
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")

DATA_DIR = Path("/data")


def _load(filename: str) -> Optional[Dict]:
    path = DATA_DIR / filename
    if not path.exists():
        logger.warning("Data file not found: %s", path)
        return None
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        logger.error("Failed to load %s: %s", filename, exc)
        return None


# ── Calendar ──────────────────────────────────────────────────────────────────

@router.get("/calendar")
def get_calendar(
    days_ahead: int = Query(7, ge=1, le=90),
    high_impact_only: bool = Query(False),
):
    data = _load("economic_calendar.json")
    if data is None:
        return JSONResponse({"events": [], "total": 0, "high_impact_count": 0})

    today = datetime.utcnow().date()
    end_date = today + timedelta(days=days_ahead)

    events: List[Dict] = []
    for ev in data.get("events", []):
        try:
            ev_date = datetime.fromisoformat(ev["date"]).date()
        except (KeyError, ValueError):
            continue
        if not (today <= ev_date <= end_date):
            continue
        if high_impact_only and ev.get("importance") != "high":
            continue
        events.append(ev)

    high_count = sum(1 for e in events if e.get("importance") == "high")
    return {"events": events, "total": len(events), "high_impact_count": high_count}


# ── News ──────────────────────────────────────────────────────────────────────

@router.get("/news")
def get_news(
    hours_ago: int = Query(4, ge=1, le=24),
    high_impact_only: bool = Query(False),
):
    data = _load("news_headlines.json")
    if data is None:
        return JSONResponse({"headlines": [], "total": 0})

    cutoff = datetime.utcnow() - timedelta(hours=hours_ago)
    headlines: List[Dict] = []
    for h in data.get("headlines", []):
        try:
            published = datetime.fromisoformat(h["published_at"])
        except (KeyError, ValueError):
            continue
        if published < cutoff:
            continue
        if high_impact_only and h.get("severity") != "high":
            continue
        headlines.append(h)

    return {"headlines": headlines, "total": len(headlines)}


# ── Macro regime ──────────────────────────────────────────────────────────────

@router.get("/macro")
def get_macro():
    data = _load("macro_regime.json")
    if data is None:
        return {
            "regime": "unknown",
            "confidence": 0.5,
            "position_multiplier": 1.0,
            "risk_mode": "normal",
            "indicators": {},
        }
    return {
        "regime": data.get("regime", "unknown"),
        "confidence": data.get("confidence", 0.5),
        "position_multiplier": data.get("position_multiplier", 1.0),
        "risk_mode": data.get("risk_mode", "normal"),
        "indicators": data.get("indicators", {}),
    }


# ── Is-blocked ────────────────────────────────────────────────────────────────

@router.get("/is-blocked")
def is_blocked(
    block_window_minutes: int = Query(15),
):
    now = datetime.utcnow()

    # Check economic calendar
    cal = _load("economic_calendar.json")
    if cal:
        for ev in cal.get("events", []):
            try:
                ev_dt = datetime.fromisoformat(f"{ev['date']} {ev['time_utc']}")
            except (KeyError, ValueError):
                continue
            before = ev.get("block_minutes_before", block_window_minutes)
            after = ev.get("block_minutes_after", block_window_minutes)
            if ev_dt - timedelta(minutes=before) <= now <= ev_dt + timedelta(minutes=after):
                mins = max(0, int((ev_dt - now).total_seconds() / 60))
                return {
                    "is_blocked": True,
                    "reason": f"Calendar event: {ev.get('event')} – {ev.get('description')}",
                    "minutes_until_next_event": mins,
                    "next_event": ev,
                }

    # Check recent high-impact news (block for 10 min after)
    news = _load("news_headlines.json")
    if news:
        for h in news.get("headlines", []):
            if h.get("severity") != "high":
                continue
            try:
                published = datetime.fromisoformat(h["published_at"])
            except (KeyError, ValueError):
                continue
            if (now - published).total_seconds() / 60 < 10:
                return {
                    "is_blocked": True,
                    "reason": f"High-impact news: {h.get('title')}",
                    "minutes_until_next_event": None,
                    "next_event": None,
                }

    return {"is_blocked": False, "reason": None, "minutes_until_next_event": None, "next_event": None}
