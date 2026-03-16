#!/usr/bin/env python3
"""
Strategy Optimization API Server
Provides REST API for triggering optimizations, viewing results, and managing run history
"""

from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from pathlib import Path
from datetime import datetime
import json
import pandas as pd
import subprocess
import uuid
import shutil
import threading
import time

app = FastAPI(
    title="Strategy Optimization API",
    description="API for running and analyzing trading strategy optimizations",
    version="1.0.0"
)

# Mount static files
static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# Enable CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure this for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state management
active_runs = {}  # run_id -> process info
run_lock = threading.Lock()

# Paths
OPTIMIZATION_DIR = Path("data/optimization")
LATEST_DIR = OPTIMIZATION_DIR / "latest"


# ============================================================================
# Models
# ============================================================================

class OptimizationRequest(BaseModel):
    """Request model for starting optimization"""
    instrument: str = Field(default="GOLD", description="Instrument to optimize (GOLD, EURUSD, etc)")
    timeframe: str = Field(default="M5", description="Timeframe (M5, M15, H1, etc)")
    mode: str = Field(default="quick", description="Optimization mode: quick, medium, or full")
    initial_capital: float = Field(default=10000.0, description="Initial capital amount")
    position_size: float = Field(default=10.0, description="Position size in lots")
    pip_values: Optional[List[float]] = Field(default=None, description="Custom pip_value range")
    parallel: bool = Field(default=True, description="Use parallel processing")
    n_jobs: int = Field(default=-1, description="Number of parallel workers (-1 = all cores)")


class OptimizationStatus(BaseModel):
    """Status of an optimization run"""
    run_id: str
    status: str  # queued, running, completed, failed
    started_at: Optional[str]
    completed_at: Optional[str]
    progress: Optional[Dict[str, Any]]
    error: Optional[str]
    config: Dict[str, Any]


class StrategyResult(BaseModel):
    """Individual strategy result"""
    rank: int
    strategy_name: str
    return_pct: float
    total_pnl: float
    sharpe_ratio: float
    win_rate: float
    total_trades: int
    profit_factor: float
    max_drawdown_pct: float


class AnalysisResponse(BaseModel):
    """Analysis results response"""
    run_id: str
    date: str
    instrument: str
    timeframe: str
    total_combinations: int
    best_strategy: Dict[str, Any]
    top_strategies: List[Dict[str, Any]]
    pip_value_analysis: Dict[str, Any]
    strategy_type_comparison: Dict[str, Any]
    risk_metrics: Dict[str, Any]


class RunHistory(BaseModel):
    """Historical run information"""
    run_id: str
    date: str
    timestamp: str
    instrument: str
    timeframe: str
    status: str
    total_combinations: int
    best_return: Optional[float]
    best_profit: Optional[float]


# ============================================================================
# Helper Functions
# ============================================================================

def get_run_directories() -> List[Path]:
    """Get all run directories sorted by date"""
    if not OPTIMIZATION_DIR.exists():
        return []
    
    run_dirs = []
    for date_dir in sorted(OPTIMIZATION_DIR.iterdir(), reverse=True):
        if date_dir.is_dir() and date_dir.name not in ['latest']:
            # Each date dir contains timestamped runs
            for run_dir in sorted(date_dir.iterdir(), reverse=True):
                if run_dir.is_dir():
                    run_dirs.append(run_dir)
    
    return run_dirs


def load_run_summary(run_path: Path) -> Optional[Dict]:
    """Load summary JSON for a run"""
    summary_file = run_path / "FINAL_SUMMARY.json"
    if summary_file.exists():
        with open(summary_file) as f:
            return json.load(f)
    return None


def load_run_results(run_path: Path) -> Optional[pd.DataFrame]:
    """Load results CSV for a run"""
    # Try to find CSV file (may have different instrument/timeframe names)
    csv_files = list(run_path.glob("*_all_strategies.csv"))
    if csv_files:
        return pd.read_csv(csv_files[0])
    return None


def get_latest_run() -> Optional[Path]:
    """Get the most recent run directory"""
    if LATEST_DIR.exists() and LATEST_DIR.is_symlink():
        return LATEST_DIR.resolve()
    
    runs = get_run_directories()
    return runs[0] if runs else None


def run_optimization_process(run_id: str, config: Dict[str, Any]):
    """Run optimization in background"""
    global active_runs
    
    try:
        # Update status
        with run_lock:
            active_runs[run_id]["status"] = "running"
            active_runs[run_id]["started_at"] = datetime.now().isoformat()
        
        # Build command with parameters
        cmd = [
            "python3", "src/optimization/optimize_strategy.py",
            "--instrument", config.get("instrument", "GOLD"),
            "--timeframe", config.get("timeframe", "M5"),
            "--capital", str(config.get("initial_capital", 10000.0)),
            "--position-size", str(config.get("position_size", 10.0)),
            "--mode", config.get("mode", "quick"),
            "--n-jobs", str(config.get("n_jobs", -1))
        ]
        
        if not config.get("parallel", True):
            cmd.append("--no-parallel")
        
        # Run optimization
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=Path.cwd()
        )
        
        # Store process
        with run_lock:
            active_runs[run_id]["process"] = process
        
        # Wait for completion
        stdout, stderr = process.communicate()
        
        # Update status
        with run_lock:
            active_runs[run_id]["completed_at"] = datetime.now().isoformat()
            if process.returncode == 0:
                active_runs[run_id]["status"] = "completed"
                active_runs[run_id]["output"] = stdout
            else:
                active_runs[run_id]["status"] = "failed"
                active_runs[run_id]["error"] = stderr
                
    except Exception as e:
        with run_lock:
            active_runs[run_id]["status"] = "failed"
            active_runs[run_id]["error"] = str(e)
            active_runs[run_id]["completed_at"] = datetime.now().isoformat()


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/")
def root():
    """Serve dashboard HTML"""
    dashboard_path = Path(__file__).parent / "static" / "dashboard.html"
    if dashboard_path.exists():
        return FileResponse(dashboard_path)
    
    # Fallback to API info
    return {
        "service": "Strategy Optimization API",
        "version": "1.0.0",
        "status": "running",
        "dashboard": "/static/dashboard.html",
        "api_docs": "/docs",
        "endpoints": {
            "health": "/health",
            "optimize": "/api/optimize",
            "status": "/api/optimize/status/{run_id}",
            "history": "/api/optimize/history",
            "results": "/api/optimize/results/{run_id}",
            "analyze": "/api/analyze/{run_id}",
            "latest": "/api/analyze/latest"
        }
    }


@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "active_runs": len([r for r in active_runs.values() if r["status"] == "running"])
    }


@app.post("/api/optimize", status_code=202)
def start_optimization(
    request: OptimizationRequest,
    background_tasks: BackgroundTasks
):
    """
    Start a new optimization run
    Returns immediately with run_id to track progress
    """
    global active_runs
    
    # Generate run ID
    run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    
    # Create run record
    run_info = {
        "run_id": run_id,
        "status": "queued",
        "created_at": datetime.now().isoformat(),
        "started_at": None,
        "completed_at": None,
        "config": request.dict(),
        "progress": None,
        "error": None,
        "process": None,
        "output": None
    }
    
    with run_lock:
        active_runs[run_id] = run_info
    
    # Start optimization in background
    background_tasks.add_task(run_optimization_process, run_id, request.dict())
    
    return {
        "run_id": run_id,
        "status": "queued",
        "message": "Optimization started",
        "check_status": f"/api/optimize/status/{run_id}"
    }


@app.get("/api/optimize/status/{run_id}")
def get_optimization_status(run_id: str):
    """Get status of a specific optimization run"""
    
    # Check active runs
    with run_lock:
        if run_id in active_runs:
            info = active_runs[run_id].copy()
            # Remove process object (not serializable)
            info.pop('process', None)
            info.pop('output', None)  # Don't send full output
            return info
    
    # Check historical runs
    runs = get_run_directories()
    for run_path in runs:
        if run_id in run_path.name:
            summary = load_run_summary(run_path)
            if summary:
                return {
                    "run_id": run_id,
                    "status": "completed",
                    "completed_at": summary.get("optimization_run", {}).get("timestamp"),
                    "config": {},
                    "results_available": True
                }
    
    raise HTTPException(status_code=404, detail=f"Run {run_id} not found")


@app.get("/api/optimize/history")
def get_optimization_history(
    limit: int = Query(default=20, ge=1, le=100),
    skip: int = Query(default=0, ge=0)
):
    """Get list of all optimization runs"""
    
    history = []
    
    # Get historical runs
    run_dirs = get_run_directories()
    
    for run_path in run_dirs[skip:skip+limit]:
        summary = load_run_summary(run_path)
        if summary:
            opt_run = summary.get("optimization_run", {})
            best = summary.get("overall_best", {})
            
            history.append({
                "run_id": run_path.name,
                "date": opt_run.get("date", ""),
                "timestamp": opt_run.get("timestamp", ""),
                "instrument": opt_run.get("instrument", ""),
                "timeframe": opt_run.get("timeframe", ""),
                "status": "completed",
                "total_combinations": summary.get("results_overview", {}).get("total_combinations_tested", 0),
                "best_return": best.get("return_pct"),
                "best_profit": best.get("total_pnl"),
                "data_bars": opt_run.get("data_bars", 0),
                "date_range_days": opt_run.get("date_range", {}).get("days", 0)
            })
    
    # Add active/recent runs
    with run_lock:
        for run_id, info in active_runs.items():
            if info["status"] in ["queued", "running"]:
                history.insert(0, {
                    "run_id": run_id,
                    "date": datetime.fromisoformat(info["created_at"]).strftime("%Y-%m-%d"),
                    "timestamp": info["created_at"],
                    "instrument": info["config"].get("instrument", ""),
                    "timeframe": info["config"].get("timeframe", ""),
                    "status": info["status"],
                    "total_combinations": None,
                    "best_return": None,
                    "best_profit": None
                })
    
    return {
        "total": len(history),
        "limit": limit,
        "skip": skip,
        "runs": history
    }


@app.get("/api/optimize/results/{run_id}")
def get_optimization_results(
    run_id: str,
    top_n: int = Query(default=20, ge=1, le=100)
):
    """Get detailed results for a specific run"""
    
    # Find run directory
    run_path = None
    if run_id == "latest":
        run_path = get_latest_run()
    else:
        run_dirs = get_run_directories()
        for rp in run_dirs:
            if run_id in rp.name:
                run_path = rp
                break
    
    if not run_path or not run_path.exists():
        raise HTTPException(status_code=404, detail=f"Results for run {run_id} not found")
    
    # Load data
    summary = load_run_summary(run_path)
    df = load_run_results(run_path)
    
    if not summary or df is None:
        raise HTTPException(status_code=500, detail="Failed to load results data")
    
    # Build response
    top_strategies = []
    for i in range(min(top_n, len(df))):
        row = df.iloc[i]
        top_strategies.append({
            "rank": i + 1,
            "strategy_name": row["strategy_name"],
            "return_pct": round(row["return_pct"], 2),
            "total_pnl": round(row["total_pnl"], 2),
            "sharpe_ratio": round(row["sharpe_ratio"], 2),
            "win_rate": round(row["win_rate"], 2),
            "total_trades": int(row["total_trades"]),
            "profit_factor": round(row["profit_factor"], 2),
            "max_drawdown_pct": round(row["max_drawdown_pct"], 2),
            "pip_value": row["pip_value"],
            "tp_sl": row["tp_sl"]
        })
    
    return {
        "run_id": run_id,
        "summary": summary,
        "top_strategies": top_strategies,
        "total_strategies": len(df)
    }


@app.get("/api/analyze/{run_id}")
def analyze_results(run_id: str):
    """Get comprehensive analysis for a specific run"""
    
    # Find run directory
    run_path = None
    if run_id == "latest":
        run_path = get_latest_run()
    else:
        run_dirs = get_run_directories()
        for rp in run_dirs:
            if run_id in rp.name:
                run_path = rp
                break
    
    if not run_path or not run_path.exists():
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    
    # Load data
    summary = load_run_summary(run_path)
    df = load_run_results(run_path)
    
    if not summary or df is None:
        raise HTTPException(status_code=500, detail="Failed to load results")
    
    # Analyze pip_values
    pip_analysis = {}
    for pv in sorted(df['pip_value'].unique()):
        subset = df[df['pip_value'] == pv]
        profitable = len(subset[subset['total_pnl'] > 0])
        pip_analysis[str(pv)] = {
            "count": len(subset),
            "profitable": profitable,
            "profitable_pct": round(100 * profitable / len(subset), 1),
            "avg_profit": round(subset['total_pnl'].mean(), 2),
            "max_profit": round(subset['total_pnl'].max(), 2),
            "best_return": round(subset['return_pct'].max(), 2)
        }
    
    # Strategy type comparison
    fixed = df[df['tp_sl'].str.contains('Fixed', na=False)]
    atr = df[df['tp_sl'].str.contains('ATR', na=False)]
    
    strategy_comparison = {
        "fixed": {
            "count": len(fixed),
            "avg_profit": round(fixed['total_pnl'].mean(), 2),
            "max_profit": round(fixed['total_pnl'].max(), 2),
            "avg_return": round(fixed['return_pct'].mean(), 2),
            "avg_win_rate": round(fixed['win_rate'].mean(), 2)
        },
        "atr": {
            "count": len(atr),
            "avg_profit": round(atr['total_pnl'].mean(), 2),
            "max_profit": round(atr['total_pnl'].max(), 2),
            "avg_return": round(atr['return_pct'].mean(), 2),
            "avg_win_rate": round(atr['win_rate'].mean(), 2)
        }
    }
    
    # Risk metrics
    profitable_count = len(df[df['total_pnl'] > 0])
    risk_metrics = {
        "profitability_rate": round(100 * profitable_count / len(df), 1),
        "avg_drawdown": round(df['max_drawdown_pct'].mean(), 2),
        "worst_drawdown": round(df['max_drawdown_pct'].max(), 2),
        "best_drawdown": round(df['max_drawdown_pct'].min(), 2)
    }
    
    # Best strategy
    best_row = df.iloc[0]
    best_strategy = {
        "strategy_name": best_row["strategy_name"],
        "return_pct": round(best_row["return_pct"], 2),
        "total_pnl": round(best_row["total_pnl"], 2),
        "sharpe_ratio": round(best_row["sharpe_ratio"], 2),
        "win_rate": round(best_row["win_rate"], 2),
        "total_trades": int(best_row["total_trades"]),
        "profit_factor": round(best_row["profit_factor"], 2),
        "max_drawdown_pct": round(best_row["max_drawdown_pct"], 2)
    }
    
    return {
        "run_id": run_id,
        "date": summary["optimization_run"]["date"],
        "instrument": summary["optimization_run"]["instrument"],
        "timeframe": summary["optimization_run"]["timeframe"],
        "total_combinations": summary["results_overview"]["total_combinations_tested"],
        "best_strategy": best_strategy,
        "pip_value_analysis": pip_analysis,
        "strategy_type_comparison": strategy_comparison,
        "risk_metrics": risk_metrics
    }


@app.get("/api/analyze/latest")
def analyze_latest():
    """Get analysis for the most recent run"""
    return analyze_results("latest")


@app.get("/api/analyze/{run_id}/detailed")
def get_detailed_analysis(run_id: str, mode: str = Query(default="full", pattern="^(full|overview|best|risk)$")):
    """
    Get detailed analysis using the analyze_results.py tool
    Modes: full, overview, best, risk
    """
    import subprocess
    
    # Find run directory
    run_path = None
    if run_id == "latest":
        run_path = get_latest_run()
    else:
        run_dirs = get_run_directories()
        for rp in run_dirs:
            if run_id in rp.name:
                run_path = rp
                break
    
    if not run_path or not run_path.exists():
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    
    # Run analyzer script
    try:
        result = subprocess.run(
            ["python3", "analyze_results.py", "--path", str(run_path), "--mode", mode],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            return {
                "run_id": run_id,
                "mode": mode,
                "analysis": result.stdout,
                "success": True
            }
        else:
            return {
                "run_id": run_id,
                "mode": mode,
                "error": result.stderr,
                "success": False
            }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Analysis timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@app.post("/api/optimize/{run_id}/cancel")
def cancel_optimization(run_id: str):
    """Cancel a running optimization"""
    
    with run_lock:
        if run_id not in active_runs:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        
        run_info = active_runs[run_id]
        
        if run_info["status"] not in ["queued", "running"]:
            raise HTTPException(status_code=400, detail=f"Run {run_id} is not active (status: {run_info['status']})")
        
        # Try to terminate process
        process = run_info.get("process")
        if process:
            try:
                process.terminate()
                process.wait(timeout=5)
            except:
                process.kill()
        
        # Update status
        active_runs[run_id]["status"] = "cancelled"
        active_runs[run_id]["completed_at"] = datetime.now().isoformat()
        
        return {
            "message": f"Run {run_id} cancelled successfully",
            "run_id": run_id,
            "status": "cancelled"
        }


@app.delete("/api/optimize/{run_id}")
def delete_optimization_run(run_id: str):
    """Delete a specific optimization run"""
    
    # Don't allow deleting active runs
    with run_lock:
        if run_id in active_runs and active_runs[run_id]["status"] in ["queued", "running"]:
            raise HTTPException(status_code=400, detail="Cannot delete active run. Cancel it first.")
    
    # Find and delete run directory
    run_dirs = get_run_directories()
    for run_path in run_dirs:
        if run_id in run_path.name:
            try:
                shutil.rmtree(run_path)
                
                # Also remove from active_runs if present
                with run_lock:
                    if run_id in active_runs:
                        del active_runs[run_id]
                
                return {
                    "message": f"Run {run_id} deleted successfully",
                    "deleted_path": str(run_path)
                }
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed to delete run: {str(e)}")
    
    raise HTTPException(status_code=404, detail=f"Run {run_id} not found")


@app.get("/api/stats/summary")
def get_overall_stats():
    """Get overall statistics across all runs"""
    
    all_runs = get_run_directories()
    
    stats = {
        "total_runs": len(all_runs),
        "total_strategies_tested": 0,
        "best_return_ever": 0,
        "best_profit_ever": 0,
        "best_run": None,
        "recent_runs": []
    }
    
    for run_path in all_runs[:10]:  # Last 10 runs
        summary = load_run_summary(run_path)
        if summary:
            total = summary["results_overview"]["total_combinations_tested"]
            best = summary["overall_best"]
            
            stats["total_strategies_tested"] += total
            
            if best["return_pct"] > stats["best_return_ever"]:
                stats["best_return_ever"] = best["return_pct"]
                stats["best_profit_ever"] = best["total_pnl"]
                stats["best_run"] = run_path.name
            
            stats["recent_runs"].append({
                "run_id": run_path.name,
                "date": summary["optimization_run"]["date"],
                "return": best["return_pct"],
                "profit": best["total_pnl"]
            })
    
    return stats


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    print("=" * 80)
    print("🚀 Starting Strategy Optimization API Server")
    print("=" * 80)
    print()
    print("📖 API Documentation: http://localhost:8000/docs")
    print("🔗 Interactive API: http://localhost:8000/redoc")
    print("💚 Health Check: http://localhost:8000/health")
    print()
    print("=" * 80)
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
