"""
Scheduler & Optimizer proxy router.

Forwards scheduler-control calls to the data-updater sidecar (port 8001),
optimizer/backtest calls to backtest-runner (port 8010), and bot-control
calls to the trading-bot service (port 8020).

Frontend endpoints expected (all under /api → stripped by nginx → /...):
  Scheduler:
    GET  /status
    POST /enable
    POST /disable
    POST /trigger
    GET  /data
    GET  /instruments
    POST /instruments
    DELETE /instruments

  Optimizer:
    GET  /health
    GET  /optimize
    POST /optimize
    GET  /optimize/{run_id}
    GET  /optimize/{run_id}/results
    DELETE /optimize/{run_id}

  Bot Control:
    GET  /bot/process
    POST /bot/start
    POST /bot/stop
    GET  /bot/schedule
    POST /bot/schedule
"""

import logging
import os
from typing import Any, Optional

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

UPDATER_URL     = os.getenv("UPDATER_URL",  "http://data-updater:8001")
BACKTEST_URL    = os.getenv("BACKTEST_URL", "http://backtest-runner:8010")
BOT_CONTROL_URL = os.getenv("BOT_CONTROL_URL", "http://trading-bot:8020")

router = APIRouter()


def _forward(method: str, path: str, body: Any = None) -> JSONResponse:
    """Forward a request to the data-updater service."""
    url = f"{UPDATER_URL}{path}"
    try:
        resp = requests.request(
            method,
            url,
            json=body,
            timeout=15,
        )
        try:
            payload = resp.json()
        except ValueError:
            payload = {
                "detail": "Upstream returned non-JSON response",
                "status_code": resp.status_code,
                "body": resp.text[:500],
            }
        return JSONResponse(status_code=resp.status_code, content=payload)
    except requests.exceptions.ConnectionError:
        logger.warning("data-updater not reachable at %s", url)
        return JSONResponse(
            status_code=503,
            content={"detail": "Data updater service unavailable"},
        )
    except Exception as exc:
        logger.error("Proxy error: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))


def _forward_bot_control(method: str, path: str, body: Any = None) -> JSONResponse:
    """Forward a request to the trading-bot control service."""
    url = f"{BOT_CONTROL_URL}{path}"
    try:
        resp = requests.request(method, url, json=body, timeout=20)
        try:
            payload = resp.json()
        except ValueError:
            payload = {
                "detail": "Upstream returned non-JSON response",
                "status_code": resp.status_code,
                "body": resp.text[:500],
            }
        return JSONResponse(status_code=resp.status_code, content=payload)
    except requests.exceptions.ConnectionError:
        logger.warning("bot-control not reachable at %s", url)
        return JSONResponse(
            status_code=503,
            content={"detail": "Bot control service unavailable"},
        )
    except Exception as exc:
        logger.error("Bot control proxy error: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))


def _forward_backtest(method: str, path: str, body: Any = None) -> JSONResponse:
    """Forward a request to the backtest-runner service."""
    url = f"{BACKTEST_URL}{path}"
    try:
        resp = requests.request(
            method,
            url,
            json=body,
            timeout=30,
        )
        try:
            payload = resp.json()
        except ValueError:
            payload = {
                "detail": "Upstream returned non-JSON response",
                "status_code": resp.status_code,
                "body": resp.text[:500],
            }
        return JSONResponse(status_code=resp.status_code, content=payload)
    except requests.exceptions.ConnectionError:
        logger.warning("backtest-runner not reachable at %s", url)
        return JSONResponse(
            status_code=503,
            content={"detail": "Backtest runner unavailable"},
        )
    except Exception as exc:
        logger.error("Backtest proxy error: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))


def _forward_backtest_raw(method: str, path: str) -> Response:
    """Forward a request to backtest-runner and return raw body (e.g. HTML chart)."""
    url = f"{BACKTEST_URL}{path}"
    try:
        resp = requests.request(method, url, timeout=30)
        return Response(
            status_code=resp.status_code,
            content=resp.content,
            media_type=resp.headers.get("content-type", "text/plain"),
        )
    except requests.exceptions.ConnectionError:
        logger.warning("backtest-runner not reachable at %s", url)
        return JSONResponse(
            status_code=503,
            content={"detail": "Backtest runner unavailable"},
        )
    except Exception as exc:
        logger.error("Backtest raw proxy error: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))


# ── Scheduler control ─────────────────────────────────────────────────────────

@router.get("/status")
def scheduler_status():
    return _forward("GET", "/status")


@router.post("/enable")
def scheduler_enable():
    return _forward("POST", "/enable")


@router.post("/disable")
def scheduler_disable():
    return _forward("POST", "/disable")


@router.post("/trigger")
async def scheduler_trigger(request: Request):
    body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    return _forward("POST", "/trigger", body)


@router.get("/data")
def data_status():
    return _forward("GET", "/data")


@router.get("/instruments")
def list_instruments():
    return _forward("GET", "/instruments")


@router.post("/instruments")
async def add_instrument(request: Request):
    body = await request.json()
    return _forward("POST", "/instruments", body)


@router.delete("/instruments")
async def remove_instrument(request: Request):
    body = await request.json()
    return _forward("DELETE", "/instruments", body)


# ── Optimizer stubs ──────────────────────────────────────────────────────────

@router.get("/health")
def optimizer_health():
    return {"status": "ok", "service": "trading-bot-api", "version": "2.0.0"}


@router.get("/optimize")
def list_runs():
    return _forward_backtest("GET", "/optimize")


@router.post("/optimize")
async def start_optimization(request: Request):
    body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    return _forward_backtest("POST", "/optimize", body)


@router.get("/optimize/{run_id}")
def get_run(run_id: str):
    return _forward_backtest("GET", f"/optimize/{run_id}")


@router.get("/optimize/{run_id}/results")
def get_run_results(run_id: str):
    return _forward_backtest("GET", f"/optimize/{run_id}/results")


@router.get("/optimize/{run_id}/report")
def get_run_report(run_id: str):
    return _forward_backtest("GET", f"/optimize/{run_id}/report")


@router.get("/optimize/{run_id}/chart")
def get_run_chart(run_id: str):
    return _forward_backtest_raw("GET", f"/optimize/{run_id}/chart")


@router.get("/optimize/{run_id}/chart-data")
def get_run_chart_data(run_id: str):
    return _forward_backtest("GET", f"/optimize/{run_id}/chart-data")


@router.delete("/optimize/{run_id}")
def delete_run(run_id: str):
    return _forward_backtest("DELETE", f"/optimize/{run_id}")


# ── Bot control ──────────────────────────────────────────────────────────────

@router.get("/bot/process")
def bot_process():
    return _forward_bot_control("GET", "/process")


@router.post("/bot/start")
async def bot_start(request: Request):
    body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    return _forward_bot_control("POST", "/start", body)


@router.post("/bot/stop")
def bot_stop():
    return _forward_bot_control("POST", "/stop")


@router.get("/bot/schedule")
def bot_schedule_get():
    return _forward_bot_control("GET", "/schedule")


@router.post("/bot/schedule")
async def bot_schedule_set(request: Request):
    body = await request.json()
    return _forward_bot_control("POST", "/schedule", body)
