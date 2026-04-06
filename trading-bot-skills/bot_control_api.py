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
from typing import Any, Dict, List, Optional

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

DATA_DIR       = Path(os.getenv("DATA_DIR", "/data"))
CONFIG_DIR     = Path(os.getenv("CONFIG_DIR", "/app/config/instruments"))
SCHEDULE_FILE  = DATA_DIR / "bot_schedule.json"
DB_PATH        = DATA_DIR / "trading.db"

app = FastAPI(title="Bot Control API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Process state (multi-bot) ────────────────────────────────────────────────
# Each entry: bot_id -> {proc, start_time, error, config, log_fh}

_bots:      Dict[str, Dict[str, Any]] = {}
_bots_lock  = threading.Lock()


def _is_running(bot_id: str) -> bool:
    entry = _bots.get(bot_id)
    return entry is not None and entry["proc"].poll() is None


def _bot_status(bot_id: str) -> Dict[str, Any]:
    entry = _bots.get(bot_id)
    if not entry:
        return {
            "running": False, "pid": None, "status": "stopped",
            "started_at": None, "mode": None, "instrument": None,
            "timeframe": None, "bot_id": bot_id, "exit_code": None, "error": None,
        }
    proc    = entry["proc"]
    running = proc.poll() is None
    rc      = None if running else proc.returncode
    cfg     = entry.get("config", {})
    return {
        "running":    running,
        "pid":        proc.pid if running else None,
        "status":     "running" if running else ("error" if entry.get("error") else "stopped"),
        "started_at": entry.get("start_time"),
        "mode":       cfg.get("mode"),
        "instrument": cfg.get("instrument"),
        "timeframe":  cfg.get("timeframe"),
        "bot_id":     bot_id,
        "exit_code":  rc,
        "error":      entry.get("error"),
    }


def _all_bots_status() -> List[Dict[str, Any]]:
    return [_bot_status(bid) for bid in list(_bots.keys())]


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


# ── Bot state persistence (SQLite kv_store) ──────────────────────────────────

import sqlite3 as _sqlite3


def _db_conn():
    return _sqlite3.connect(str(DB_PATH), check_same_thread=False)


def _db_ensure_table(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS kv_store "
        "(collection TEXT NOT NULL, doc_id TEXT NOT NULL, data TEXT NOT NULL, "
        "updated_at TEXT NOT NULL, PRIMARY KEY (collection, doc_id))"
    )
    conn.commit()


def _upsert_bot_state(conn, bot_id: str, cfg: Dict[str, Any]) -> None:
    """Upsert current state into kv_store(collection='bot_state')."""
    conn.execute(
        "INSERT INTO kv_store (collection, doc_id, data, updated_at) VALUES (?,?,?,?) "
        "ON CONFLICT(collection, doc_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
        ("bot_state", bot_id, json.dumps(cfg), datetime.utcnow().isoformat()),
    )


def _append_bot_event(conn, bot_id: str, event: str, cfg: Dict[str, Any]) -> None:
    """Append a start/stop event to append_log(collection='bot_events') for history."""
    now = datetime.utcnow().isoformat()
    data = {**cfg, "event": event, "timestamp": now}
    conn.execute(
        "INSERT INTO append_log (collection, doc_id, data, created_at) VALUES (?,?,?,?)",
        ("bot_events", bot_id, json.dumps(data), now),
    )


def _save_bot_state() -> None:
    """Upsert every known bot's current state into kv_store."""
    try:
        conn = _db_conn()
        _db_ensure_table(conn)
        for bot_id, entry in _bots.items():
            cfg = {**entry["config"], "status": "running" if _is_running(bot_id) else "stopped"}
            _upsert_bot_state(conn, bot_id, cfg)
        conn.commit()
        conn.close()
    except Exception:
        pass


def _record_bot_started(bot_id: str, cfg: Dict[str, Any]) -> None:
    try:
        conn = _db_conn()
        _db_ensure_table(conn)
        _upsert_bot_state(conn, bot_id, {**cfg, "status": "running"})
        _append_bot_event(conn, bot_id, "started", cfg)
        conn.commit()
        conn.close()
    except Exception:
        pass


def _record_bot_stopped(bot_id: str, cfg: Dict[str, Any]) -> None:
    try:
        conn = _db_conn()
        _db_ensure_table(conn)
        _upsert_bot_state(conn, bot_id, {**cfg, "status": "stopped"})
        _append_bot_event(conn, bot_id, "stopped", cfg)
        conn.commit()
        conn.close()
    except Exception:
        pass


def _load_bot_state() -> List[Dict[str, Any]]:
    """Return bot configs whose status is 'running' (i.e. were active at last shutdown)."""
    try:
        conn = _db_conn()
        _db_ensure_table(conn)
        rows = conn.execute(
            "SELECT data FROM kv_store WHERE collection='bot_state' "
            "AND json_extract(data, '$.status')='running'"
        ).fetchall()
        conn.close()
        return [json.loads(r[0]) for r in rows]
    except Exception:
        return []


# ── Bot lifecycle ─────────────────────────────────────────────────────────────

def _start_bot(mode: str = "demo", instrument: str = "GOLD", timeframe: str = "M5", quantity: float = None) -> str:
    """Start a bot for the given instrument/timeframe. Returns bot_id."""
    bot_id = f"{instrument.lower()}_{timeframe.lower()}_bot"

    with _bots_lock:
        if _is_running(bot_id):
            return bot_id  # already running, nothing to do

        cmd = [
            "python", "orchestrator/main.py",
            "--mode",       mode,
            "--instrument", instrument,
            "--timeframe",  timeframe,
            "--bot-id",     bot_id,
        ]
        if quantity is not None:
            cmd += ["--quantity", str(quantity)]

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        log_path = DATA_DIR / f"{bot_id}.log"
        log_fh   = open(log_path, "a")
        cfg = {"mode": mode, "instrument": instrument, "timeframe": timeframe, "bot_id": bot_id, "quantity": quantity}
        try:
            proc = subprocess.Popen(
                cmd,
                cwd="/app",
                stdout=log_fh,
                stderr=subprocess.STDOUT,
            )
            _bots[bot_id] = {
                "proc":       proc,
                "start_time": datetime.utcnow().isoformat(),
                "error":      None,
                "log_fh":     log_fh,
                "config":     cfg,
            }
        except Exception as exc:
            log_fh.close()
            raise

    _record_bot_started(bot_id, cfg)
    return bot_id


def _stop_bot(bot_id: str) -> None:
    with _bots_lock:
        entry = _bots.get(bot_id)
        if not entry or not _is_running(bot_id):
            return
        try:
            entry["proc"].send_signal(signal.SIGTERM)
            entry["proc"].wait(timeout=15)
        except subprocess.TimeoutExpired:
            entry["proc"].kill()
        except Exception:
            pass
        finally:
            try:
                entry["log_fh"].close()
            except Exception:
                pass
            cfg = entry.get("config", {"bot_id": bot_id})
            _record_bot_stopped(bot_id, cfg)
            _bots.pop(bot_id, None)


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
                instrument = schedule.get("instrument", "GOLD")
                timeframe  = schedule.get("timeframe",  "M5")
                bot_id     = f"{instrument.lower()}_{timeframe.lower()}_bot"
                should     = _in_trading_hours(schedule)
                if should and not _is_running(bot_id):
                    _start_bot(
                        mode=       schedule.get("mode", "demo"),
                        instrument= instrument,
                        timeframe=  timeframe,
                    )
                elif not should and _is_running(bot_id):
                    _stop_bot(bot_id)
        except Exception:
            pass
        time.sleep(60)


# ── App startup ───────────────────────────────────────────────────────────────

@app.on_event("startup")
def on_startup():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Restore bots that were running before the last shutdown/restart
    for cfg in _load_bot_state():
        try:
            _start_bot(
                mode=       cfg.get("mode", "demo"),
                instrument= cfg.get("instrument", "GOLD"),
                timeframe=  cfg.get("timeframe", "M5"),
                quantity=   cfg.get("quantity"),
            )
        except Exception:
            pass
    threading.Thread(target=_scheduler_loop, daemon=True).start()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "bot-control"}


@app.get("/process")
def process_status():
    """Returns all known bot statuses as a list."""
    return {"bots": _all_bots_status()}


class StartRequest(BaseModel):
    mode:       str = "demo"
    instrument: str = "GOLD"
    timeframe:  str = "M5"
    quantity:   float = None


@app.post("/start")
def start(req: StartRequest):
    bot_id = f"{req.instrument.lower()}_{req.timeframe.lower()}_bot"
    if _is_running(bot_id):
        raise HTTPException(status_code=409, detail=f"{bot_id} is already running")
    try:
        _start_bot(req.mode, req.instrument, req.timeframe, req.quantity)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return _bot_status(bot_id)


@app.post("/stop")
def stop(bot_id: str):
    if not _is_running(bot_id):
        raise HTTPException(status_code=409, detail=f"{bot_id} is not running")
    _stop_bot(bot_id)
    return _bot_status(bot_id)


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


@app.get("/configs")
def list_configs():
    """Return available bot configs derived from instrument YAML files."""
    configs: List[Dict[str, Any]] = []
    if not CONFIG_DIR.exists():
        return {"configs": configs, "count": 0}
    for yaml_path in sorted(CONFIG_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(yaml_path.read_text())
            md   = data.get("market_data", {})
            risk = data.get("risk", {})
            instrument = md.get("instrument", yaml_path.stem)
            timeframe  = md.get("timeframe", "M5")
            bot_id     = f"{instrument.lower()}_{timeframe.lower()}_bot"
            configs.append({
                "id":               bot_id,
                "name":             data.get("bot", {}).get("name", f"{instrument} {timeframe} Bot"),
                "instrument":       instrument,
                "timeframe":        timeframe,
                "pip_size":         risk.get("pip_size", 1.0),
                "stop_loss_pips":   risk.get("stop_loss_pips", 20),
                "take_profit_pips": risk.get("take_profit_pips", 60),
            })
        except Exception:
            pass
    return {"configs": configs, "count": len(configs)}
