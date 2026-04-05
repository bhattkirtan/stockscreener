"""
Data Updater Server

Runs the DataUpdateScheduler in a background thread and exposes
scheduler-control HTTP endpoints that the frontend expects:

  GET  /status              — scheduler status + data file ages
  POST /enable              — (no-op: always running; returns status)
  POST /disable             — (no-op: always running; returns status)
  POST /trigger             — force update now
  GET  /data                — data file freshness
  GET  /instruments         — list tracked instruments
  POST /instruments         — add instrument  (not persisted in this impl)
  DELETE /instruments       — remove instrument (not persisted in this impl)

These are proxied through nginx as /api/* → backend:8000/* so the
frontend VITE_SCHEDULER_API_URL=/api hits the main FastAPI app via the
scheduler_router included in app.py.

Run:
  python -m src.services.updater_server
"""

import logging
import os
import threading
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.services.data_update_scheduler import DataUpdateScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

DATA_DIR = os.getenv("DATA_DIR", "/data")
FRED_API_KEY = os.getenv("FRED_API_KEY")
NEWS_INTERVAL = int(os.getenv("NEWS_UPDATE_INTERVAL_MINUTES", "5"))

# Default configured instruments for scheduler controls.
# This endpoint is read by the optimizer UI and should always be available.
DEFAULT_DATASETS = [
    ("EURUSD", "M15", 10000),
    ("EURUSD", "M15", 2000),
    ("EURGBP", "M15", 5000),
    ("GBPUSD", "M15", 5000),
    ("GOLD", "M15", 10000),
    ("GOLD", "M5", 5000),
    ("GOLD", "M5", 3000),
    ("SILVER", "M15", 5000),
    ("BITCOIN", "M15", 10000),
    ("BITCOIN", "M5", 5000),
    ("US30", "M15", 5000),
    ("NASDAQ", "M15", 5000),
]

# ── Scheduler singleton ───────────────────────────────────────────────────────

_scheduler = DataUpdateScheduler(
    data_dir=DATA_DIR,
    news_update_minutes=NEWS_INTERVAL,
    fred_api_key=FRED_API_KEY,
)

def _run_scheduler():
    try:
        _scheduler.start_scheduler()
    except Exception as exc:
        logger.error("Scheduler crashed: %s", exc)

_thread = threading.Thread(target=_run_scheduler, daemon=True, name="data-updater")
_thread.start()

# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(title="Data Updater API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def health():
    return {"status": "ok", "service": "data-updater"}


@app.get("/status")
def status():
    s = _scheduler.get_status()
    s["enabled"] = True  # always running
    return s


@app.post("/enable")
def enable():
    return status()


@app.post("/disable")
def disable():
    # Scheduler keeps running — just report status
    return status()


@app.post("/trigger")
def trigger():
    """Force-run all updates immediately."""
    threading.Thread(target=_scheduler.run_all_updates, daemon=True).start()
    return {"triggered": True, "timestamp": datetime.utcnow().isoformat()}


@app.get("/data")
def data_status():
    data_dir = Path(DATA_DIR)
    files = ["economic_calendar.json", "news_headlines.json", "macro_regime.json"]
    result = {}
    for fname in files:
        path = data_dir / fname
        if path.exists():
            mtime = datetime.utcfromtimestamp(path.stat().st_mtime)
            age_minutes = (datetime.utcnow() - mtime).total_seconds() / 60
            result[fname] = {
                "exists": True,
                "updated_at": mtime.isoformat(),
                "age_minutes": round(age_minutes, 1),
            }
        else:
            result[fname] = {"exists": False}
    return {"data_dir": DATA_DIR, "files": result}


@app.get("/instruments")
def list_instruments():
    instruments = [
        {"epic": epic, "timeframe": res, "bars": bars}
        for epic, res, bars in DEFAULT_DATASETS
    ]
    return {
        "instruments": instruments,
        "total": len(instruments),
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/instruments")
def add_instrument(body: dict):
    # Static list in this impl — acknowledge receipt
    return {"status": "ok", "message": "Instrument noted (restart to persist)", "instrument": body}


@app.delete("/instruments")
def remove_instrument(body: dict):
    return {"status": "ok", "message": "Instrument noted (restart to persist)", "instrument": body}


if __name__ == "__main__":
    uvicorn.run("src.services.updater_server:app", host="0.0.0.0", port=8001, log_level="info")
