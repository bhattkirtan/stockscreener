"""
Bot Control API — manages the live trading-bot process on the same container.

Endpoints:
  GET  /health           - Health check
  GET  /process          - Process status (running / stopped / error + pid)
  POST /start            - Start the orchestrator
  POST /stop             - Stop the orchestrator gracefully
  GET  /schedule         - Get schedule config
  POST /schedule         - Update schedule config

Run (from docker-compose):
  uvicorn bot_control_api:app --host 0.0.0.0 --port 8020
"""

import json
import os
import signal
import subprocess
import threading
import time
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

DATA_DIR      = Path(os.getenv("DATA_DIR", "/data"))
SCHEDULE_FILE = DATA_DIR / "bot_schedule.json"
BOT_LOG_FILE  = DATA_DIR / "bot_process.log"

app = FastAPI(title="Bot Control API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Process state ─────────────────────────────────────────────────────────────

_proc:            Optional[subprocess.Popen] = None
_proc_lock        = threading.Lock()
_proc_start_time: Optional[str] = None
_last_error:      Optional[str] = None
_last_config:     Dict[str, Any] = {}


def _is_running() -> bool:
    return _proc is not None and _proc.poll() is None


def _proc_status() -> Dict[str, Any]:
    running = _is_running()
    rc = None if running else (_proc.returncode if _proc else None)
    return {
        "running":    running,
        "pid":        _proc.pid if running and _proc else None,
        "status":     "running" if running else ("error" if _last_error else "stopped"),
        "started_at": _proc_start_time,
        "mode":       _last_config.get("mode"),
        "instrument": _last_config.get("instrument"),
        "timeframe":  _last_config.get("timeframe"),
        "exit_code":  rc,
        "error":      _last_error,
    }


# ── Schedule helpers ──────────────────────────────────────────────────────────

def _default_schedule() -> Dict[str, Any]:
    return {
        "enabled":    False,
        "mode":       "demo",
        "instrument": "GOLD",
        "timeframe":  "M5",
        "trading_hours": {
            "start":    "08:00",
            "end":      "17:00",
            "timezone": "UTC",
            "days":     ["Mon", "Tue", "Wed", "Thu", "Fri"],
        },
    }


def _load_schedule() -> Dict[str, Any]:
    if SCHEDULE_FILE.exists():
        try:
            return json.loads(SCHEDULE_FILE.read_text())
        except Exception:
            pass
    return _default_schedule()


def _save_schedule(schedule: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SCHEDULE_FILE.write_text(json.dumps(schedule, indent=2))


# ── Bot lifecycle ─────────────────────────────────────────────────────────────

def _start_bot(mode: str = "demo", instrument: str = "GOLD", timeframe: str = "M5") -> None:
    global _proc, _proc_start_time, _last_error, _last_config

    with _proc_lock:
        if _is_running():
            return

        _last_error  = None
        _last_config = {"mode": mode, "instrument": instrument, "timeframe": timeframe}

        cmd = [
            "python", "orchestrator/main.py",
            "--mode",       mode,
            "--instrument", instrument,
            "--timeframe",  timeframe,
        ]

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        log_fh = open(BOT_LOG_FILE, "a")
        try:
            _proc = subprocess.Popen(
                cmd,
                cwd="/app",
                stdout=log_fh,
                stderr=subprocess.STDOUT,
            )
            _proc_start_time = datetime.utcnow().isoformat()
        except Exception as exc:
            _last_error = str(exc)
            log_fh.close()
            raise


def _stop_bot() -> None:
    global _proc, _last_error

    with _proc_lock:
        if _proc is None or not _is_running():
            return
        try:
            _proc.send_signal(signal.SIGTERM)
            _proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            _proc.kill()
        except Exception as exc:
            _last_error = str(exc)
        finally:
            _proc = None


# ── Scheduler thread ──────────────────────────────────────────────────────────

def _in_trading_hours(schedule: Dict[str, Any]) -> bool:
    """Return True if current UTC time is within configured trading window."""
    try:
        hours    = schedule.get("trading_hours", {})
        day_map  = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        now      = datetime.utcnow()
        if day_map[now.weekday()] not in hours.get("days", []):
            return False
        sh, sm = map(int, hours["start"].split(":"))
        eh, em = map(int, hours["end"].split(":"))
        return dtime(sh, sm) <= now.time() <= dtime(eh, em)
    except Exception:
        return False


def _scheduler_loop() -> None:
    while True:
        try:
            schedule = _load_schedule()
            if schedule.get("enabled"):
                should = _in_trading_hours(schedule)
                if should and not _is_running():
                    _start_bot(
                        mode=       schedule.get("mode",       "demo"),
                        instrument= schedule.get("instrument", "GOLD"),
                        timeframe=  schedule.get("timeframe",  "M5"),
                    )
                elif not should and _is_running():
                    _stop_bot()
        except Exception:
            pass
        time.sleep(60)


# ── App startup ───────────────────────────────────────────────────────────────

@app.on_event("startup")
def on_startup():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=_scheduler_loop, daemon=True).start()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "bot-control"}


@app.get("/process")
def process_status():
    return _proc_status()


class StartRequest(BaseModel):
    mode:       str = "demo"
    instrument: str = "GOLD"
    timeframe:  str = "M5"


@app.post("/start")
def start(req: StartRequest):
    if _is_running():
        raise HTTPException(status_code=409, detail="Bot is already running")
    try:
        _start_bot(req.mode, req.instrument, req.timeframe)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return _proc_status()


@app.post("/stop")
def stop():
    if not _is_running():
        raise HTTPException(status_code=409, detail="Bot is not running")
    _stop_bot()
    return _proc_status()


@app.get("/schedule")
def get_schedule():
    return _load_schedule()


class ScheduleRequest(BaseModel):
    enabled:       bool = False
    mode:          str  = "demo"
    instrument:    str  = "GOLD"
    timeframe:     str  = "M5"
    trading_hours: Optional[Dict[str, Any]] = None


@app.post("/schedule")
def update_schedule(req: ScheduleRequest):
    schedule = _load_schedule()
    schedule["enabled"]    = req.enabled
    schedule["mode"]       = req.mode
    schedule["instrument"] = req.instrument
    schedule["timeframe"]  = req.timeframe
    if req.trading_hours is not None:
        schedule["trading_hours"] = req.trading_hours
    _save_schedule(schedule)
    return schedule
