import json
import os
import sqlite3
import subprocess
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


DB_PATH = os.getenv("DB_PATH", "/data/trading.db")
RESULTS_DIR = Path(os.getenv("RESULTS_DIR", "/data/results"))

app = FastAPI(title="Backtest Runner API", version="1.0.0")


class OptimizeRequest(BaseModel):
    instrument: str = "GOLD"
    timeframe: str = "M5"
    mode: str = "quick"
    bars: int = 215000
    config: Optional[Dict[str, Any]] = None


def _utc_now() -> str:
    return datetime.utcnow().isoformat()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_db() -> None:
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS optimization_runs (
                run_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                instrument TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                mode TEXT NOT NULL,
                bars INTEGER NOT NULL,
                config_json TEXT,
                results_json TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                start_time TEXT,
                end_time TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )


def _row_to_run(row: sqlite3.Row) -> Dict[str, Any]:
    run = {
        "run_id": row["run_id"],
        "status": row["status"],
        "instrument": row["instrument"],
        "timeframe": row["timeframe"],
        "mode": row["mode"],
        "created_at": row["created_at"],
        "start_time": row["start_time"],
        "end_time": row["end_time"],
        "config": json.loads(row["config_json"]) if row["config_json"] else {},
        "error": row["error"],
    }
    if row["results_json"]:
        run["results"] = json.loads(row["results_json"])
    return run


def _save_run(run_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = _utc_now()
    sets = ", ".join(f"{k}=?" for k in fields.keys())
    vals = list(fields.values()) + [run_id]
    with _conn() as conn:
        conn.execute(f"UPDATE optimization_runs SET {sets} WHERE run_id=?", vals)


def _load_report(instrument: str, run_id: str) -> Dict[str, Any]:
    report_file = RESULTS_DIR / instrument.upper() / run_id / "report.json"
    if not report_file.exists():
        raise FileNotFoundError(f"Missing report file: {report_file}")
    return json.loads(report_file.read_text())


def _to_ui_results(report: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    summary = report.get("summary", {})
    stats = report.get("statistics", {})

    strategy_name = f"skills_{run.get('instrument', 'GOLD').lower()}_{run.get('timeframe', 'M5').lower()}"
    return_pct = float(summary.get("total_return_pct", 0) or 0)
    sharpe = float(summary.get("sharpe_ratio", 0) or 0)
    pf = float(summary.get("profit_factor", 0) or 0)
    trades = int(summary.get("total_trades", 0) or 0)
    win_rate = float(summary.get("win_rate", 0) or 0)

    top = {
        "strategy_name": strategy_name,
        "return_pct": return_pct,
        "sharpe_ratio": sharpe,
        "profit_factor": pf,
        "total_trades": trades,
        "win_rate": win_rate,
    }

    return {
        "top_10_strategies": [top],
        "overall_best": {
            **top,
            "final_capital": float(summary.get("final_capital", 0) or 0),
            "initial_capital": float(summary.get("initial_capital", 0) or 0),
            "total_pnl": float(summary.get("total_pnl", 0) or 0),
        },
        "results_overview": {
            "total_combinations_tested": 1,
            "valid_strategies": 1,
            "fixed_sl_tp_strategies": 1,
            "atr_based_strategies": 0,
        },
        "best_by_metric": {
            "highest_return": {"strategy": strategy_name, "value": return_pct},
            "highest_sharpe": {"strategy": strategy_name, "value": sharpe},
            "highest_profit_factor": {"strategy": strategy_name, "value": pf},
            "highest_win_rate": {"strategy": strategy_name, "value": win_rate},
            "lowest_drawdown": {"strategy": strategy_name, "value": float(summary.get("max_drawdown_pct", 0) or 0)},
        },
        "recommendation": (
            f"Reference backtest completed with {trades} trades, {win_rate:.1f}% win rate, "
            f"and {return_pct:.2f}% return."
        ),
        "optimization_run": {
            "instrument": run.get("instrument", "GOLD"),
            "timeframe": run.get("timeframe", "M5"),
            "data_bars": run.get("bars", 0),
            "date": report.get("timestamp", _utc_now()),
            "date_range": {
                "days": 0,
                "start": report.get("timestamp", _utc_now()),
                "end": report.get("timestamp", _utc_now()),
            },
        },
        "parameter_insights": {
            "winning_trades": float(stats.get("winning_trades", 0) or 0),
            "losing_trades": float(stats.get("losing_trades", 0) or 0),
            "avg_win": float(stats.get("avg_win", 0) or 0),
            "avg_loss": float(stats.get("avg_loss", 0) or 0),
        },
    }


def _runner_thread(run_id: str) -> None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM optimization_runs WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        return

    run = dict(row)
    instrument = str(run["instrument"]).upper()
    bars = int(run["bars"])

    _save_run(run_id, status="running", start_time=_utc_now(), error=None)

    run_dir = RESULTS_DIR / instrument / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_file = run_dir / "run.log"

    cmd = [
        "python",
        "run_skills_backtest.py",
        "--instrument",
        instrument,
        "--bars",
        str(bars),
        "--results-dir",
        str(RESULTS_DIR),
        "--run-id",
        run_id,
    ]

    try:
        with log_file.open("w") as f:
            proc = subprocess.run(cmd, cwd="/app", stdout=f, stderr=subprocess.STDOUT, check=False)

        if proc.returncode != 0:
            _save_run(
                run_id,
                status="failed",
                end_time=_utc_now(),
                error=f"Backtest process exited with code {proc.returncode}",
            )
            return

        report = _load_report(instrument, run_id)
        ui_results = _to_ui_results(report, {"instrument": instrument, "timeframe": run["timeframe"], "bars": bars})

        _save_run(
            run_id,
            status="completed",
            end_time=_utc_now(),
            results_json=json.dumps(ui_results),
            error=None,
        )
    except Exception as exc:
        _save_run(run_id, status="failed", end_time=_utc_now(), error=str(exc))


@app.on_event("startup")
def startup() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    _init_db()


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "service": "backtest-runner"}


@app.post("/optimize")
def optimize(req: OptimizeRequest) -> Dict[str, Any]:
    run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    now = _utc_now()
    config = req.config or req.dict()

    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO optimization_runs
            (run_id, status, instrument, timeframe, mode, bars, config_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                "queued",
                req.instrument.upper(),
                req.timeframe.upper(),
                req.mode,
                req.bars,
                json.dumps(config),
                now,
                now,
            ),
        )

    t = threading.Thread(target=_runner_thread, args=(run_id,), daemon=True)
    t.start()

    with _conn() as conn:
        row = conn.execute("SELECT * FROM optimization_runs WHERE run_id=?", (run_id,)).fetchone()
    return _row_to_run(row)


@app.get("/optimize")
def list_runs() -> Dict[str, Any]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM optimization_runs ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    runs = [_row_to_run(r) for r in rows]
    return {"runs": runs, "count": len(runs)}


@app.get("/optimize/{run_id}")
def get_run(run_id: str) -> Dict[str, Any]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM optimization_runs WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return _row_to_run(row)


@app.get("/optimize/{run_id}/results")
def get_results(run_id: str) -> Dict[str, Any]:
    run = get_run(run_id)
    if run.get("status") != "completed" or "results" not in run:
        raise HTTPException(status_code=404, detail=f"Results for run '{run_id}' not available")
    return run


@app.delete("/optimize/{run_id}")
def delete_run(run_id: str) -> Dict[str, Any]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM optimization_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
        conn.execute("DELETE FROM optimization_runs WHERE run_id=?", (run_id,))
    return {"status": "deleted", "run_id": run_id}