"""
Trading Bot FastAPI service — VM replacement for GCP Cloud Functions.

Endpoints:
  Bot monitoring (reads from SQLite):
    GET /bot/status?bot_id=gold_m5_bot
    GET /bot/positions?status=open&epic=GOLD
    GET /bot/signals?epic=GOLD&limit=20&mode=all
    GET /bot/logs/live?bot_id=...&limit=100&level=INFO&run_id=...
    GET /logs/dates
    GET /logs/get?date=YYYY-MM-DD&lines=100

  Backtest results (reads from RESULTS_DIR volume):
    GET /backtest/runs?instrument=GOLD        — list all run dirs
    GET /backtest/runs/{instrument}/{run_id}  — report.json for a run
    GET /backtest/trades/{instrument}/{run_id}— trades.csv as JSON rows

  Capital.com proxy (authenticates with Capital.com API):
    GET  /get_positions
    POST /create_position
    POST /updte_position          (typo kept for backwards compat)
    DELETE /close_position/{deal_id}
    GET  /market/{epic}
    GET  /prices/{epic}?resolution=HOUR&max=50
    GET  /markets?searchTerm=...

Run:
  uvicorn app:app --host 0.0.0.0 --port 8000
"""

import json
import logging
import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import database as db
import capital_proxy as cap
from capital_proxy import CapitalError
import external_data
import scheduler_proxy
import live_report as lr

# ── Setup ─────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

LOG_DIR = Path(os.getenv("LOG_DIR", "/data/logs"))
RESULTS_DIR = Path(os.getenv("RESULTS_DIR", "/data/results"))

# ── Auth ──────────────────────────────────────────────────────────────────────
# UI_PASSWORD is set via env var in the Docker .env file.
# A random session token is minted once at startup; clients receive it on
# successful login and must send it as:  Authorization: Bearer <token>
# Restarting the container invalidates all active sessions.

UI_PASSWORD = os.getenv("UI_PASSWORD", "")
_SESSION_TOKEN: str = secrets.token_hex(32)

_PUBLIC_PATHS = {"/", "/auth/login"}

app = FastAPI(title="Trading Bot API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(external_data.router)
app.include_router(scheduler_proxy.router)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if not UI_PASSWORD or request.url.path in _PUBLIC_PATHS:
        return await call_next(request)
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not secrets.compare_digest(token, _SESSION_TOKEN):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)


@app.on_event("startup")
def startup():
    db.init_db()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    auth_status = "enabled" if UI_PASSWORD else "disabled (UI_PASSWORD not set)"
    logger.info(f"DB initialised, log dir ready — auth {auth_status}")


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/")
def health():
    return {"status": "ok", "service": "trading-bot-api", "version": "2.0.0"}


# ── Auth ──────────────────────────────────────────────────────────────────────

class LoginBody(BaseModel):
    password: str

@app.post("/auth/login")
def login(body: LoginBody):
    if not UI_PASSWORD:
        # Auth disabled — return a dummy token so the frontend still works
        return {"token": "no-auth"}
    if secrets.compare_digest(body.password, UI_PASSWORD):
        return {"token": _SESSION_TOKEN}
    raise HTTPException(status_code=401, detail="Invalid password")


# ── Bot monitoring ────────────────────────────────────────────────────────────

@app.get("/bot/status")
def bot_status(bot_id: str = Query(default="gold_m5_bot")):
    data = db.kv_get("bot_status", bot_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")

    # Mark stale if no heartbeat for >2 min
    hb = data.get("last_heartbeat")
    if hb:
        try:
            last = datetime.fromisoformat(hb)
            if datetime.utcnow() - last > timedelta(minutes=2):
                data["is_stale"] = True
                data["stale_reason"] = "No heartbeat in last 2 minutes"
        except ValueError:
            pass

    return data


@app.get("/bot/positions")
def bot_positions(
    status: str = Query(default="open"),
    epic: Optional[str] = Query(default=None),
):
    rows = db.kv_get_all("active_positions")
    if status != "all":
        rows = [r for r in rows if r.get("status") == status]
    if epic:
        rows = [r for r in rows if r.get("epic") == epic]
    rows.sort(key=lambda r: r.get("opened_at", ""), reverse=True)
    total_pnl = sum(r.get("pnl", r.get("realized_pnl", 0)) for r in rows)
    return {"positions": rows, "count": len(rows), "total_pnl": round(total_pnl, 2)}


@app.get("/bot/signals")
def bot_signals(
    epic: Optional[str] = Query(default=None),
    limit: int = Query(default=20, le=100),
    mode: str = Query(default="all"),
):
    filters: Dict[str, Any] = {}
    if epic:
        filters["epic"] = epic
    if mode != "all":
        filters["mode"] = mode
    rows = db.log_query("trading_signals", limit=limit, filters=filters or None)
    return {"signals": rows, "count": len(rows)}


@app.get("/bot/logs/live")
def bot_logs_live(
    bot_id: str = Query(default="gold_m5_bot"),
    limit: int = Query(default=100, le=1000),
    level: Optional[str] = Query(default=None),
    run_id: Optional[str] = Query(default=None),
):
    filters: Dict[str, Any] = {"bot_id": bot_id}
    if level:
        filters["level"] = level.upper()
    if run_id:
        filters["run_id"] = run_id
    rows = db.log_query("bot_logs", limit=limit, filters=filters)
    return {"logs": rows, "count": len(rows)}


@app.get("/logs/dates")
def log_dates():
    dates = sorted(
        {p.name for p in LOG_DIR.iterdir() if p.is_dir()},
        reverse=True,
    )[:30]
    return {"dates": dates, "count": len(dates)}


@app.get("/logs/get")
def log_get(
    date: str = Query(default=None),
    lines: int = Query(default=100, le=1000),
    fmt: str = Query(default="json", alias="format"),
):
    if not date:
        date = datetime.utcnow().strftime("%Y-%m-%d")
    day_dir = LOG_DIR / date
    if not day_dir.exists():
        raise HTTPException(status_code=404, detail=f"No logs for {date}")

    log_lines = []
    for f in sorted(day_dir.glob("*.log")):
        log_lines.extend(f.read_text().splitlines())
    log_lines = log_lines[-lines:]

    if fmt == "text":
        return "\n".join(log_lines)
    return {"date": date, "lines": log_lines, "total_lines": len(log_lines)}


# ── Capital.com proxy ─────────────────────────────────────────────────────────

def _cap_error(e: CapitalError):
    raise HTTPException(status_code=e.status_code, detail=e.detail)


def _cap_env_from_request(request: Request) -> Optional[str]:
    env = request.headers.get("X-Trading-Env", "").strip().lower()
    if env in {"demo", "live"}:
        return env
    return None


@app.get("/get_positions")
def get_positions(request: Request):
    try:
        return cap.get_positions(env=_cap_env_from_request(request))
    except CapitalError as e:
        _cap_error(e)


class CreatePositionBody(BaseModel):
    epic: str
    direction: str
    size: float
    guaranteedStop: bool = False
    stopLevel: Optional[float] = None
    profitLevel: Optional[float] = None


@app.post("/create_position")
def create_position(body: CreatePositionBody, request: Request):
    payload = body.model_dump(exclude_none=True)
    try:
        return cap.create_position(payload, env=_cap_env_from_request(request))
    except CapitalError as e:
        _cap_error(e)


class UpdatePositionBody(BaseModel):
    dealId: str
    stopLevel: Optional[float] = None
    profitLevel: Optional[float] = None


@app.post("/updte_position")   # typo kept for backwards compat with React client
def update_position(body: UpdatePositionBody, request: Request):
    deal_id = body.dealId
    payload = body.model_dump(exclude={"dealId"}, exclude_none=True)
    try:
        return cap.update_position(deal_id, payload, env=_cap_env_from_request(request))
    except CapitalError as e:
        _cap_error(e)


@app.delete("/close_position/{deal_id}")
def close_position(deal_id: str, request: Request):
    try:
        return cap.close_position(deal_id, env=_cap_env_from_request(request))
    except CapitalError as e:
        _cap_error(e)


@app.get("/market/{epic}")
def market_info(epic: str, request: Request):
    try:
        return cap.get_market(epic, env=_cap_env_from_request(request))
    except CapitalError as e:
        _cap_error(e)


@app.get("/prices/{epic}")
def prices(
    request: Request,
    epic: str,
    resolution: str = Query(default="HOUR"),
    max: int = Query(default=50),
    from_ts: Optional[str] = Query(default=None, alias="from"),
    to_ts: Optional[str] = Query(default=None, alias="to"),
):
    try:
        return cap.get_prices(epic, resolution, max, from_ts, to_ts, env=_cap_env_from_request(request))
    except CapitalError as e:
        _cap_error(e)


@app.get("/markets")
def markets(request: Request, searchTerm: Optional[str] = Query(default=None)):
    try:
        result = cap.get_markets(searchTerm, env=_cap_env_from_request(request))
        market_list = result.get("markets", [])

        # Exclude closed markets before sending payload to the UI.
        open_markets = [m for m in market_list if str(m.get("marketStatus", "")).upper() != "CLOSED"]
        result["markets"] = open_markets

        movers_source = [m for m in open_markets if m.get("percentageChange") is not None]
        sorted_by_change = sorted(movers_source, key=lambda m: m.get("percentageChange", 0), reverse=True)
        result["topRisers"] = sorted_by_change[:10]
        result["topFallers"] = sorted_by_change[-10:][::-1]
        return result
    except CapitalError as e:
        _cap_error(e)


# ── Backtest results ──────────────────────────────────────────────────────────

@app.get("/backtest/runs")
def backtest_runs(instrument: Optional[str] = Query(default=None)):
    """List all run directories, newest first."""
    if not RESULTS_DIR.exists():
        return {"runs": [], "count": 0}

    runs = []
    search_dirs = [RESULTS_DIR / instrument.upper()] if instrument else sorted(RESULTS_DIR.iterdir())
    for inst_dir in search_dirs:
        if not inst_dir.is_dir():
            continue
        for run_dir in sorted(inst_dir.iterdir(), reverse=True):
            if not run_dir.is_dir():
                continue
            report_path = run_dir / "report.json"
            entry: Dict[str, Any] = {
                "instrument": inst_dir.name,
                "run_id": run_dir.name,
                "path": str(run_dir),
                "has_report": report_path.exists(),
            }
            if report_path.exists():
                try:
                    rpt = json.loads(report_path.read_text())
                    s = rpt.get("summary", {})
                    entry["summary"] = {
                        "total_trades": s.get("total_trades"),
                        "total_return_pct": round(s.get("total_return_pct", 0), 2),
                        "sharpe_ratio": round(s.get("sharpe_ratio", 0), 4),
                        "max_drawdown_pct": round(s.get("max_drawdown_pct", 0), 4),
                        "win_rate": round(s.get("win_rate", 0), 2),
                        "timestamp": rpt.get("timestamp"),
                    }
                except Exception:
                    pass
            runs.append(entry)
    return {"runs": runs, "count": len(runs)}


@app.get("/backtest/runs/{instrument}/{run_id}")
def backtest_run_detail(instrument: str, run_id: str):
    """Return full report.json for a run."""
    report_path = RESULTS_DIR / instrument.upper() / run_id / "report.json"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail=f"Run not found: {instrument}/{run_id}")
    return json.loads(report_path.read_text())


# ── Live performance report ───────────────────────────────────────────────────

@app.get("/live/report")
def live_report(
    bot_id: str = Query(default="gold_m5_bot"),
    initial_capital: float = Query(default=10000.0),
):
    """Performance report computed from live trade_history — same format as backtest report.json."""
    return lr.get_live_report(bot_id=bot_id, initial_capital=initial_capital)


@app.get("/live/trades")
def live_trades(
    bot_id: str = Query(default="gold_m5_bot"),
    epic: Optional[str] = Query(default=None),
    limit: int = Query(default=500, le=5000),
):
    """Closed trades from trade_history, newest first."""
    trades = db.kv_get_all("trade_history")
    if bot_id and bot_id != "all":
        trades = [t for t in trades if t.get("bot_id", bot_id) == bot_id]
    if epic:
        trades = [t for t in trades if t.get("epic") == epic]
    trades = trades[:limit]
    return {"trades": trades, "count": len(trades)}


# ── Backtest results ──────────────────────────────────────────────────────────

@app.get("/backtest/trades/{instrument}/{run_id}")
def backtest_trades(instrument: str, run_id: str, limit: int = Query(default=500, le=10000)):
    """Return trades.csv rows as JSON (newest first, limited)."""
    import csv
    trades_path = RESULTS_DIR / instrument.upper() / run_id / "trades.csv"
    if not trades_path.exists():
        raise HTTPException(status_code=404, detail=f"trades.csv not found: {instrument}/{run_id}")
    rows = []
    with trades_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    rows = rows[-limit:][::-1]   # last N, reversed (newest first)
    return {"trades": rows, "count": len(rows), "run_id": run_id, "instrument": instrument.upper()}
