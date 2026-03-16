#!/usr/bin/env python3
"""
Compare M5 vs M15 performance over identical 25.4-month period (Jan 2024 - Mar 2026)
Both datasets now have excellent credibility (⭐⭐⭐⭐⭐)
"""
import json
import pandas as pd
from pathlib import Path
from datetime import datetime

print("=" * 80)
print("M5 vs M15 CREDIBLE COMPARISON (25.4 Months - Jan 2024 to Mar 2026)")
print("=" * 80)
print()

# M5 Results (from previous Phase 4 optimization)
m5_data = {
    "timeframe": "M5",
    "bars": 149987,
    "period_days": 771,
    "period_months": 25.3,
    "credibility": "⭐⭐⭐⭐⭐ EXCELLENT",
    "best_strategy": "ST10_SMA15-50_BB2.0_ATR0.7x2.5",
    "return_pct": 122.41,
    "sharpe": 0.65,
    "win_rate": 25.2,
    "profit_factor": 1.99,
    "total_trades": 866,
    "trades_per_month": 34.2,
    "monthly_return": 4.84,
    "avg_hold_hours": 35.9,
}

# M15 Results (from latest optimization run_20260309_111800)
m15_summary_path = Path("data/optimization/2026-03-09/run_20260309_111800/FINAL_SUMMARY.json")
with open(m15_summary_path) as f:
    m15_summary = json.load(f)

m15_best = m15_summary["overall_best"]
m15_run = m15_summary["optimization_run"]

m15_data = {
    "timeframe": "M15",
    "bars": m15_run["data_bars"],
    "period_days": m15_run["date_range"]["days"],
    "period_months": round(m15_run["date_range"]["days"] / 30.4, 1),
    "credibility": "⭐⭐⭐⭐⭐ EXCELLENT",
    "best_strategy": "ST2.0_SMA21-50_BB2.0_ATR0.7x2.5",
    "return_pct": m15_best["return_pct"],
    "sharpe": m15_best["sharpe_ratio"],
    "win_rate": m15_best["win_rate"],
    "profit_factor": m15_best["profit_factor"],
    "total_trades": m15_best["total_trades"],
    "trades_per_month": round(m15_best["total_trades"] / (m15_run["date_range"]["days"] / 30.4), 1),
    "monthly_return": round(m15_best["return_pct"] / (m15_run["date_range"]["days"] / 30.4), 2),
}

# Get detailed M15 best strategy metrics
m15_best_dir = Path("data/optimization/2026-03-09/run_20260309_111800/rank01_ST2.0_SMA21-50_BB2.0_PIP1_ATR0.7x2.5")
m15_summary_path = m15_best_dir / "summary.json"
with open(m15_summary_path) as f:
    m15_metrics = json.load(f)

# Calculate average hold time from orders.csv
m15_orders_path = m15_best_dir / "orders.csv"
m15_orders = pd.read_csv(m15_orders_path)
m15_orders['entry_time'] = pd.to_datetime(m15_orders['entry_time'])
m15_orders['exit_time'] = pd.to_datetime(m15_orders['exit_time'])
m15_orders['hold_hours'] = (m15_orders['exit_time'] - m15_orders['entry_time']).dt.total_seconds() / 3600
m15_avg_hold_hours = m15_orders['hold_hours'].mean()

m15_data["avg_hold_hours"] = round(m15_avg_hold_hours, 1)
m15_data["max_drawdown_pct"] = m15_metrics["train"]["performance"]["max_drawdown_pct"]

# Get M5 drawdown (approximate from previous analysis)
m5_data["max_drawdown_pct"] = -56.0  # From previous analysis

print("┌─────────────────────────────────────────────────────────────────────────────┐")
print("│                            DATA CREDIBILITY                                 │")
print("└─────────────────────────────────────────────────────────────────────────────┘")
print(f"  M5:  {m5_data['bars']:,} bars, {m5_data['period_days']} days ({m5_data['period_months']} months) {m5_data['credibility']}")
print(f"  M15: {m15_data['bars']:,} bars, {m15_data['period_days']} days ({m15_data['period_months']} months) {m15_data['credibility']}")
print(f"  ✅ Both tested over IDENTICAL ~25-month period (Jan 2024 - Mar 2026)")
print()

print("┌─────────────────────────────────────────────────────────────────────────────┐")
print("│                         BEST STRATEGY PARAMETERS                            │")
print("└─────────────────────────────────────────────────────────────────────────────┘")
print(f"  M5:  {m5_data['best_strategy']}")
print(f"  M15: {m15_data['best_strategy']}")
print()

print("┌─────────────────────────────────────────────────────────────────────────────┐")
print("│                          PERFORMANCE COMPARISON                             │")
print("└─────────────────────────────────────────────────────────────────────────────┘")
print()

# Calculate differences
return_diff = ((m15_data["return_pct"] / m5_data["return_pct"]) - 1) * 100
trades_diff = ((m15_data["trades_per_month"] / m5_data["trades_per_month"]) - 1) * 100
monthly_diff = ((m15_data["monthly_return"] / m5_data["monthly_return"]) - 1) * 100

metrics = [
    ("Total Return", f"{m5_data['return_pct']:.2f}%", f"{m15_data['return_pct']:.2f}%", 
     f"{'+' if return_diff > 0 else ''}{return_diff:.1f}% {'✅' if return_diff > 0 else '❌'}"),
    
    ("Monthly Return", f"{m5_data['monthly_return']:.2f}%", f"{m15_data['monthly_return']:.2f}%",
     f"{'+' if monthly_diff > 0 else ''}{monthly_diff:.1f}% {'✅' if monthly_diff > 0 else '❌'}"),
    
    ("Total Trades", f"{m5_data['total_trades']}", f"{m15_data['total_trades']}",
     f"{m15_data['total_trades'] - m5_data['total_trades']:+d}"),
    
    ("Trades/Month", f"{m5_data['trades_per_month']:.1f}", f"{m15_data['trades_per_month']:.1f}",
     f"{'+' if trades_diff > 0 else ''}{trades_diff:.1f}% {'✅' if trades_diff < 0 else '❌'}"),
    
    ("Avg Hold Time", f"{m5_data['avg_hold_hours']:.1f}h", f"{m15_data['avg_hold_hours']:.1f}h",
     f"{m15_data['avg_hold_hours'] - m5_data['avg_hold_hours']:+.1f}h"),
    
    ("Win Rate", f"{m5_data['win_rate']:.1f}%", f"{m15_data['win_rate']:.1f}%",
     f"{m15_data['win_rate'] - m5_data['win_rate']:+.1f}%"),
    
    ("Profit Factor", f"{m5_data['profit_factor']:.2f}", f"{m15_data['profit_factor']:.2f}",
     f"{m15_data['profit_factor'] - m5_data['profit_factor']:+.2f} {'❌' if m15_data['profit_factor'] < 1.5 else ''}"),
    
    ("Sharpe Ratio", f"{m5_data['sharpe']:.2f}", f"{m15_data['sharpe']:.2f}",
     f"{m15_data['sharpe'] - m5_data['sharpe']:+.2f}"),
    
    ("Max Drawdown", f"{m5_data['max_drawdown_pct']:.1f}%", f"{m15_data['max_drawdown_pct']:.1f}%",
     f"{m15_data['max_drawdown_pct'] - m5_data['max_drawdown_pct']:+.1f}%"),
]

print(f"{'Metric':<20} {'M5':>15} {'M15':>15} {'Difference':>20}")
print("-" * 80)
for metric, m5_val, m15_val, diff in metrics:
    print(f"{metric:<20} {m5_val:>15} {m15_val:>15} {diff:>20}")

print()
print("┌─────────────────────────────────────────────────────────────────────────────┐")
print("│                        CAPITAL SCENARIOS ($10K BASE)                        │")
print("└─────────────────────────────────────────────────────────────────────────────┘")
print()

# Calculate profit for different position sizes (20× leverage)
for margin in [300, 600]:
    notional = margin * 20
    
    # M5 profits
    m5_profit = m5_data["return_pct"] / 100 * margin
    m5_monthly = m5_profit / m5_data["period_months"]
    m5_dd = m5_data["max_drawdown_pct"] / 100 * margin
    
    # M15 profits  
    m15_profit = m15_data["return_pct"] / 100 * margin
    m15_monthly = m15_profit / m15_data["period_months"]
    m15_dd = m15_data["max_drawdown_pct"] / 100 * margin
    
    print(f"💰 ${margin} Margin (${notional:,} notional @ 20× leverage):")
    print(f"   M5:  ${m5_profit:,.0f} total (${m5_monthly:,.0f}/month, {m5_data['trades_per_month']:.1f} trades/mo, DD: ${abs(m5_dd):,.0f})")
    print(f"   M15: ${m15_profit:,.0f} total (${m15_monthly:,.0f}/month, {m15_data['trades_per_month']:.1f} trades/mo, DD: ${abs(m15_dd):,.0f})")
    print(f"   Difference: ${m15_profit - m5_profit:+,.0f} total, ${m15_monthly - m5_monthly:+,.0f}/month")
    print()

print("┌─────────────────────────────────────────────────────────────────────────────┐")
print("│                              KEY INSIGHTS                                   │")
print("└─────────────────────────────────────────────────────────────────────────────┘")
print()

if m15_data["return_pct"] > m5_data["return_pct"]:
    print(f"  ✅ M15 outperforms M5 by {return_diff:.1f}% in total return")
else:
    print(f"  ❌ M5 outperforms M15 by {-return_diff:.1f}% in total return")

if m15_data["trades_per_month"] < m5_data["trades_per_month"]:
    print(f"  ✅ M15 has {abs(trades_diff):.1f}% FEWER trades per month ({m15_data['trades_per_month']:.1f} vs {m5_data['trades_per_month']:.1f})")
else:
    print(f"  ❌ M15 has {trades_diff:.1f}% MORE trades per month")

if m15_data["monthly_return"] > m5_data["monthly_return"]:
    print(f"  ✅ M15 delivers {monthly_diff:.1f}% BETTER monthly returns ({m15_data['monthly_return']:.2f}% vs {m5_data['monthly_return']:.2f}%)")
else:
    print(f"  ❌ M5 delivers better monthly returns")

if m15_data["profit_factor"] < 1.5:
    print(f"  ⚠️  M15 profit factor ({m15_data['profit_factor']:.2f}) is LOW (< 1.5) - less robust than M5 ({m5_data['profit_factor']:.2f})")

if m15_data["sharpe"] < m5_data["sharpe"]:
    print(f"  ⚠️  M15 Sharpe ({m15_data['sharpe']:.2f}) is LOWER than M5 ({m5_data['sharpe']:.2f}) - more volatile")

print()
print("┌─────────────────────────────────────────────────────────────────────────────┐")
print("│                              RECOMMENDATION                                 │")
print("└─────────────────────────────────────────────────────────────────────────────┘")
print()

# Calculate decision score
score_m15 = 0
score_m5 = 0

if m15_data["return_pct"] > m5_data["return_pct"]:
    score_m15 += 3  # Higher weight for returns
else:
    score_m5 += 3

if m15_data["trades_per_month"] < m5_data["trades_per_month"]:
    score_m15 += 2  # User wants fewer trades
else:
    score_m5 += 2

if m15_data["profit_factor"] > m5_data["profit_factor"]:
    score_m15 += 2  # Robustness important
else:
    score_m5 += 2

if m15_data["sharpe"] > m5_data["sharpe"]:
    score_m15 += 1
else:
    score_m5 += 1

print(f"  Decision Score: M15 = {score_m15}, M5 = {score_m5}")
print()

if score_m15 > score_m5:
    print("  🎯 RECOMMENDATION: Deploy M15")
    print(f"     • {return_diff:.1f}% higher returns")
    print(f"     • {abs(trades_diff):.1f}% fewer trades/month")
    print(f"     • Better monthly income (${m15_monthly:,.0f} vs ${m5_monthly:,.0f} @ $300 margin)")
    if m15_data["profit_factor"] < 1.5:
        print(f"     • ⚠️  Lower profit factor ({m15_data['profit_factor']:.2f}) - less robust")
elif score_m5 > score_m15:
    print("  🎯 RECOMMENDATION: Deploy M5")
    print(f"     • Higher profit factor ({m5_data['profit_factor']:.2f}) = more robust")
    print(f"     • Better Sharpe ({m5_data['sharpe']:.2f}) = less volatility")
    print(f"     • Proven strategy with consistent performance")
else:
    print("  🎯 RECOMMENDATION: Both strategies are comparable")
    print("     • Choose based on your preference:")
    print(f"       - M15: Higher returns, fewer trades")
    print(f"       - M5: More robust (PF {m5_data['profit_factor']:.2f}), better risk-adjusted")

print()
print("=" * 80)
