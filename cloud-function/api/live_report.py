"""
Live performance report — computed from SQLite trade_history.

Returns the same JSON structure as backtest report.json so the
frontend can render identical metric cards for both live and backtest.
"""

import statistics
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

import database as db


def _normalize(t: Dict) -> Dict:
    """Map live-trade field names to the canonical backtest trade schema."""
    return {
        "entry_time":   t.get("opened_at") or t.get("entry_time", ""),
        "exit_time":    t.get("closed_at") or t.get("exit_time", ""),
        "entry_price":  float(t.get("open_level") or t.get("entry_price") or 0),
        "exit_price":   float(t.get("close_level") or t.get("exit_price") or 0),
        "side":         t.get("direction") or t.get("side", "BUY"),
        "size":         float(t.get("size") or 1),
        "pnl":          float(t.get("pnl") or t.get("realized_pnl") or 0),
        "pnl_pct":      float(t.get("pnl_pct") or 0),
        "exit_reason":  t.get("exit_reason", "UNKNOWN"),
        "epic":         t.get("epic", ""),
    }


def _compute(trades: List[Dict], initial_capital: float) -> Dict[str, Any]:
    if not trades:
        return _empty(initial_capital)

    norm = sorted([_normalize(t) for t in trades], key=lambda x: x["exit_time"])

    total_pnl    = sum(t["pnl"] for t in norm)
    final_cap    = initial_capital + total_pnl
    total_return = (total_pnl / initial_capital * 100) if initial_capital else 0
    n            = len(norm)

    wins   = [t for t in norm if t["pnl"] > 0]
    losses = [t for t in norm if t["pnl"] < 0]
    win_rate    = len(wins) / n * 100 if n else 0
    avg_win     = (sum(t["pnl"] for t in wins)   / len(wins))   if wins   else 0
    avg_loss    = (sum(t["pnl"] for t in losses) / len(losses)) if losses else 0
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss   = abs(sum(t["pnl"] for t in losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss else (999.0 if gross_profit > 0 else 0)

    # Equity curve
    equity = initial_capital
    equity_curve = [{"timestamp": None, "equity": initial_capital, "pnl": 0}]
    for t in norm:
        equity += t["pnl"]
        equity_curve.append({"timestamp": t["exit_time"], "equity": round(equity, 2), "pnl": round(t["pnl"], 2)})

    # Drawdown
    equities = [e["equity"] for e in equity_curve]
    peak = equities[0]
    max_dd = 0.0
    max_dd_pct = 0.0
    drawdowns = []
    for eq in equities:
        if eq > peak:
            peak = eq
        dd = peak - eq
        dd_pct = (dd / peak * 100) if peak else 0
        drawdowns.append(dd)
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd_pct

    # Sharpe (annualised, simplified)
    pnls = [t["pnl"] for t in norm]
    if len(pnls) > 1:
        mean_p = statistics.mean(pnls)
        std_p  = statistics.stdev(pnls)
        sharpe = (mean_p / std_p * (252 ** 0.5)) if std_p else 0
    else:
        sharpe = 0.0

    expectancy = (win_rate / 100 * avg_win) + ((1 - win_rate / 100) * avg_loss)

    # Streaks
    win_streak = loss_streak = cur_win = cur_loss = 0
    for t in norm:
        if t["pnl"] > 0:
            cur_win += 1; cur_loss = 0
        else:
            cur_loss += 1; cur_win = 0
        win_streak  = max(win_streak, cur_win)
        loss_streak = max(loss_streak, cur_loss)

    # Monthly breakdown
    monthly_map: Dict[str, Dict] = defaultdict(lambda: {"total_pnl": 0.0, "trades": 0})
    for t in norm:
        if t["exit_time"]:
            try:
                month = t["exit_time"][:7]
                monthly_map[month]["total_pnl"] += t["pnl"]
                monthly_map[month]["trades"]    += 1
            except Exception:
                pass
    monthly_list = [
        {
            "month":        k,
            "total_pnl":    round(v["total_pnl"], 2),
            "trades":       v["trades"],
            "avg_pnl":      round(v["total_pnl"] / v["trades"], 2) if v["trades"] else 0,
            "max_drawdown": 0.0,
        }
        for k, v in sorted(monthly_map.items())
    ]

    # Trade distribution
    by_dir: Dict[str, Any]    = {}
    by_reason: Dict[str, Any] = {}
    by_hour: Dict[str, Any]   = {}

    for t in norm:
        for bucket, key in [(by_dir, t["side"]), (by_reason, t["exit_reason"])]:
            if key not in bucket:
                bucket[key] = {"count": 0, "sum": 0.0, "mean": 0.0}
            bucket[key]["count"] += 1
            bucket[key]["sum"]   += t["pnl"]

        if t.get("entry_time"):
            try:
                h = str(int(t["entry_time"][11:13]))
                if h not in by_hour:
                    by_hour[h] = {"count": 0, "sum": 0.0, "mean": 0.0}
                by_hour[h]["count"] += 1
                by_hour[h]["sum"]   += t["pnl"]
            except Exception:
                pass

    for bucket in (by_dir, by_reason, by_hour):
        for key in bucket:
            if bucket[key]["count"]:
                bucket[key]["mean"] = round(bucket[key]["sum"] / bucket[key]["count"], 2)
                bucket[key]["sum"]  = round(bucket[key]["sum"], 2)

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "mode": "live",
        "summary": {
            "initial_capital":      round(initial_capital, 2),
            "final_capital":        round(final_cap, 2),
            "total_pnl":            round(total_pnl, 2),
            "total_return_pct":     round(total_return, 4),
            "avg_margin_per_trade": 0.0,
            "return_on_margin_pct": 0.0,
            "total_trades":         n,
            "win_rate":             round(win_rate, 2),
            "sharpe_ratio":         round(sharpe, 4),
            "profit_factor":        round(min(profit_factor, 999.0), 4),
            "max_drawdown":         round(max_dd, 2),
            "max_drawdown_pct":     round(max_dd_pct, 4),
            "expectancy_per_trade": round(expectancy, 2),
        },
        "statistics": {
            "winning_trades":     len(wins),
            "losing_trades":      len(losses),
            "avg_win":            round(avg_win, 2),
            "avg_loss":           round(avg_loss, 2),
            "max_win":            round(max((t["pnl"] for t in wins),   default=0), 2),
            "max_loss":           round(min((t["pnl"] for t in losses), default=0), 2),
            "largest_win_streak": win_streak,
            "longest_loss_streak": loss_streak,
        },
        "equity_curve":   equity_curve,
        "drawdown_analysis": {
            "max_drawdown":     round(max_dd, 2),
            "max_drawdown_pct": round(max_dd_pct, 4),
            "avg_drawdown":     round(sum(drawdowns) / len(drawdowns), 2) if drawdowns else 0,
            "drawdown_series":  [round(d, 2) for d in drawdowns],
        },
        "trade_distribution": {
            "by_direction":  by_dir,
            "by_exit_reason": by_reason,
            "by_hour":       {str(k): v for k, v in sorted(by_hour.items(), key=lambda x: int(x[0]))},
        },
        "monthly_performance": monthly_list,
        "trades": norm,
    }


def _empty(initial_capital: float) -> Dict[str, Any]:
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "mode": "live",
        "summary": {
            "initial_capital": round(initial_capital, 2),
            "final_capital":   round(initial_capital, 2),
            "total_pnl": 0.0, "total_return_pct": 0.0,
            "avg_margin_per_trade": 0.0, "return_on_margin_pct": 0.0,
            "total_trades": 0, "win_rate": 0.0, "sharpe_ratio": 0.0,
            "profit_factor": 0.0, "max_drawdown": 0.0,
            "max_drawdown_pct": 0.0, "expectancy_per_trade": 0.0,
        },
        "statistics": {},
        "equity_curve": [],
        "drawdown_analysis": {},
        "trade_distribution": {},
        "monthly_performance": [],
        "trades": [],
    }


def get_live_report(bot_id: str = "gold_m5_bot", initial_capital: float = 10000.0) -> Dict[str, Any]:
    """Build a live performance report from trade_history in SQLite."""
    trades = db.kv_get_all("trade_history")
    if bot_id and bot_id != "all":
        trades = [t for t in trades if t.get("bot_id", bot_id) == bot_id]
    return _compute(trades, initial_capital)
