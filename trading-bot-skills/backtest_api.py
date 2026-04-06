import json
import os
import sqlite3
import subprocess
import threading
import uuid
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel


DB_PATH = os.getenv("DB_PATH", "/data/trading.db")
RESULTS_DIR = Path(os.getenv("RESULTS_DIR", "/data/results"))
PRICE_DATA_DIR = Path(os.getenv("PRICE_DATA_DIR", "/data/price_data"))

app = FastAPI(title="Backtest Runner API", version="1.0.0")


class OptimizeRequest(BaseModel):
    instrument: str = "GOLD"
    timeframe: str = "M5"
    mode: str = "quick"
    bars: Optional[int] = None
    years: Optional[float] = None
    set_values: Optional[list[str]] = None
    config: Optional[Dict[str, Any]] = None


def _timeframe_to_minutes(timeframe: str) -> int:
    tf = str(timeframe).strip().upper()
    if tf.startswith("M") and tf[1:].isdigit():
        return int(tf[1:])
    if tf.startswith("H") and tf[1:].isdigit():
        return int(tf[1:]) * 60
    if tf in {"D", "D1", "1D", "DAY"}:
        return 24 * 60
    return 5


def _resolve_bars(bars: Optional[int], years: Optional[float], timeframe: str) -> int:
    if isinstance(bars, int) and bars > 0:
        return bars
    if years is not None and years > 0:
        minutes_per_bar = _timeframe_to_minutes(timeframe)
        return max(1, int((years * 365 * 24 * 60) / minutes_per_bar))
    return 215000


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
        "bars": row["bars"],
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


def _run_dir(instrument: str, run_id: str) -> Path:
    return RESULTS_DIR / instrument.upper() / run_id


def _compact_equity_curve(equity_curve: list[Dict[str, Any]], max_points: int = 1200) -> list[Dict[str, Any]]:
    """Downsample equity points to keep API payloads responsive for UI charts."""
    if not equity_curve or len(equity_curve) <= max_points:
        return equity_curve
    stride = max(1, len(equity_curve) // max_points)
    sampled = equity_curve[::stride]
    if sampled[-1] != equity_curve[-1]:
        sampled.append(equity_curve[-1])
    return sampled


def _build_reporting_payload(report: Dict[str, Any], instrument: str, run_id: str) -> Dict[str, Any]:
    run_dir = RESULTS_DIR / instrument / run_id
    return {
        "summary": report.get("summary", {}),
        "statistics": report.get("statistics", {}),
        "equity_curve": _compact_equity_curve(report.get("equity_curve", [])),
        "drawdown_analysis": report.get("drawdown_analysis", {}),
        "trade_distribution": report.get("trade_distribution", {}),
        "monthly_performance": report.get("monthly_performance", []),
        "artifacts": {
            "report_json": str((run_dir / "report.json").name),
            "trades_csv": str((run_dir / "trades.csv").name),
            "report_html": str((run_dir / "report.html").name),
            "analysis_xlsx": str((run_dir / "analysis.xlsx").name),
            "chart_st_trades_html": str((run_dir / "chart_st_trades.html").name),
            "chart_data_json": str((run_dir / "chart_data.json").name),
        },
    }


def _load_chart_data(
    instrument: str,
    run_id: str,
    from_ts: Optional[int] = None,
    to_ts: Optional[int] = None,
) -> Dict[str, Any]:
    data_file = RESULTS_DIR / instrument.upper() / run_id / "chart_data.json"
    if not data_file.exists():
        raise FileNotFoundError(f"Missing chart data file: {data_file}")
    payload = json.loads(data_file.read_text())

    def _parse_ts(s: str) -> int:
        """Parse ISO timestamp string → unix int (UTC). Uses stdlib only."""
        try:
            s = str(s).strip()
            # Replace space separator with T for fromisoformat compatibility
            if " " in s and "T" not in s:
                s = s.replace(" ", "T", 1)
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except Exception:
            return 0

    # Always expose the full range in meta so the frontend knows total extent
    series = payload.get("series", [])
    payload.setdefault("meta", {})
    payload["meta"].setdefault("total_bars", len(series))
    # Use pre-computed full_range from chart_data.json if available; otherwise derive it
    if "full_range" not in payload["meta"] and series:
        all_ts = [_parse_ts(p.get("timestamp", "")) for p in series]
        payload["meta"]["full_range"] = {"from": min(all_ts), "to": max(all_ts)}

    # Filter series to requested range
    if from_ts is not None or to_ts is not None:
        def _in_range_series(p: Dict) -> bool:
            t = _parse_ts(p.get("timestamp", ""))
            if from_ts is not None and t < from_ts:
                return False
            if to_ts is not None and t > to_ts:
                return False
            return True

        def _in_range_trade(t: Dict) -> bool:
            et = t.get("entry_time") or t.get("exit_time")
            if not et:
                return True
            ts = _parse_ts(str(et))
            if from_ts is not None and ts < from_ts:
                return False
            if to_ts is not None and ts > to_ts:
                return False
            return True

        payload["series"] = [p for p in series if _in_range_series(p)]
        payload["trades"] = [t for t in payload.get("trades", []) if _in_range_trade(t)]
        payload["meta"]["bars"] = len(payload["series"])

    return payload


def _load_trades_csv(instrument: str, run_id: str) -> list[Dict[str, Any]]:
    trades_file = _run_dir(instrument, run_id) / "trades.csv"
    if not trades_file.exists():
        return []
    rows: list[Dict[str, Any]] = []
    with trades_file.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def _build_legacy_chart_data(instrument: str, run_id: str) -> Dict[str, Any]:
    """Build chart data from the saved historical price CSV + trades.csv.

    This is used when chart_data.json was not generated at run time (old runs).
    We read the real OHLC candles directly from the downloaded price file so the
    chart shows actual market prices rather than the equity curve.
    """
    run = get_run(run_id)
    timeframe = str(run.get("timeframe", "M5")).upper()
    bars = int(run.get("bars", 5000) or 5000)
    instr = instrument.upper()

    # Check for data_source.json written by the backtest runner (most accurate)
    run_dir = RESULTS_DIR / instr / run_id
    data_source_file = run_dir / "data_source.json"
    sourced_path = None
    if data_source_file.exists():
        try:
            import json as _json
            sourced_path = Path(_json.loads(data_source_file.read_text()).get("data_path", ""))
        except Exception:
            sourced_path = None

    # Find the best matching price file: data_source.json > exact bar count > any candidate
    price_dir = PRICE_DATA_DIR
    candidates = sorted(price_dir.glob(f"{instr}_{timeframe}_*.csv"))
    exact = price_dir / f"{instr}_{timeframe}_{bars}bars.csv"
    if sourced_path and sourced_path.exists():
        price_file = sourced_path
    elif exact.exists():
        price_file = exact
    else:
        price_file = candidates[-1] if candidates else None

    trades = []
    for t in _load_trades_csv(instrument, run_id):
        trades.append(
            {
                "entry_time": t.get("entry_time") or None,
                "entry_price": float(t.get("entry_price", 0) or 0),
                "exit_time": t.get("exit_time") or None,
                "exit_price": float(t.get("exit_price", 0) or 0),
                "side": str(t.get("side", "")),
                "pnl": float(t.get("pnl", 0) or 0),
                "exit_reason": str(t.get("exit_reason", "")),
            }
        )

    if price_file is None or not price_file.exists():
        raise FileNotFoundError(f"No price data file found for {instr} {timeframe}")

    import pandas as pd
    import sys
    sys.path.insert(0, "/app")
    from core.indicators import calculate_supertrend

    df = pd.read_csv(price_file)
    # Normalise timestamp column name
    for col in ("timestamp", "time", "date"):
        if col in df.columns:
            df = df.rename(columns={col: "timestamp"})
            break
    df = df.dropna(subset=["timestamp"])
    df["close"] = pd.to_numeric(df.get("close", 0), errors="coerce").fillna(0)
    df["open"]  = pd.to_numeric(df.get("open",  df["close"]), errors="coerce").fillna(df["close"])
    df["high"]  = pd.to_numeric(df.get("high",  df["close"]), errors="coerce").fillna(df["close"])
    df["low"]   = pd.to_numeric(df.get("low",   df["close"]), errors="coerce").fillna(df["close"])
    if "volume" not in df.columns:
        df["volume"] = 0

    # Calculate supertrend using default params (atr_period=7, multiplier=2.0)
    try:
        st_values, st_dir, st_upper, st_lower = calculate_supertrend(df, period=7, multiplier=2.0)
        df["supertrend"] = st_values.fillna(0)
        df["supertrend_direction"] = st_dir.fillna(1).astype(int)
        df["st_upper"] = st_upper.fillna(0)
        df["st_lower"] = st_lower.fillna(0)
    except Exception:
        df["supertrend"] = 0
        df["supertrend_direction"] = 1
        df["st_upper"] = 0
        df["st_lower"] = 0

    def _sf(val, default=0.0):
        try:
            f = float(val)
            return f if f == f else default
        except (TypeError, ValueError):
            return default

    series = []
    for _, row in df.iterrows():
        ts = str(row["timestamp"])
        if not ts or ts in ("nan", "None"):
            continue
        c = _sf(row["close"])
        series.append(
            {
                "timestamp": ts,
                "open": _sf(row["open"], c),
                "high": _sf(row["high"], c),
                "low": _sf(row["low"], c),
                "close": c,
                "supertrend": _sf(row["supertrend"]),
                "supertrend_direction": int(row["supertrend_direction"]),
                "st_upper": _sf(row["st_upper"]),
                "st_lower": _sf(row["st_lower"]),
            }
        )

    return {
        "series": series,
        "trades": trades,
        "meta": {
            "bars": len(series),
            "trades": len(trades),
            "generated_at": _utc_now(),
            "source": "price-csv-fallback",
        },
    }


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

    instrument = str(run.get("instrument", "GOLD")).upper()
    run_id = str(run.get("run_id", ""))
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
        "reporting": _build_reporting_payload(report, instrument, run_id),
    }


def _runner_thread(run_id: str) -> None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM optimization_runs WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        return

    run = dict(row)
    instrument = str(run["instrument"]).upper()
    bars = int(run["bars"])
    config = json.loads(run["config_json"]) if run.get("config_json") else {}
    set_values = config.get("set_values") or []

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
    for item in set_values:
        cmd.extend(["--set", str(item)])

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
        ui_results = _to_ui_results(
            report,
            {
                "run_id": run_id,
                "instrument": instrument,
                "timeframe": run["timeframe"],
                "bars": bars,
            },
        )

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
    resolved_bars = _resolve_bars(req.bars, req.years, req.timeframe)
    config = req.model_dump(exclude_none=True)
    if req.config:
        config.update(req.config)
    config["bars"] = resolved_bars

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
                resolved_bars,
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


@app.get("/optimize/{run_id}/report")
def get_report(run_id: str) -> Dict[str, Any]:
    run = get_run(run_id)
    instrument = str(run.get("instrument", "GOLD")).upper()
    try:
        return _load_report(instrument, run_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Report for run '{run_id}' not available")


@app.get("/optimize/{run_id}/chart")
def get_trade_chart(run_id: str):
    run = get_run(run_id)
    instrument = str(run.get("instrument", "GOLD")).upper()
    run_dir = _run_dir(instrument, run_id)
    chart_file = run_dir / "chart_st_trades.html"
    if chart_file.exists():
        return FileResponse(chart_file, media_type="text/html")

    # Legacy fallback for historical runs that only have report.html.
    report_html = run_dir / "report.html"
    if report_html.exists():
        return FileResponse(report_html, media_type="text/html")

    raise HTTPException(status_code=404, detail=f"Chart for run '{run_id}' not available")


@app.get("/optimize/{run_id}/chart-data")
def get_trade_chart_data(
    run_id: str,
    from_ts: Optional[int] = Query(None, alias="from"),
    to_ts: Optional[int] = Query(None, alias="to"),
) -> Dict[str, Any]:
    run = get_run(run_id)
    instrument = str(run.get("instrument", "GOLD")).upper()
    try:
        return _load_chart_data(instrument, run_id, from_ts, to_ts)
    except FileNotFoundError:
        try:
            return _build_legacy_chart_data(instrument, run_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Chart data for run '{run_id}' not available")


@app.delete("/optimize/{run_id}")
def delete_run(run_id: str) -> Dict[str, Any]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM optimization_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
        conn.execute("DELETE FROM optimization_runs WHERE run_id=?", (run_id,))
    return {"status": "deleted", "run_id": run_id}