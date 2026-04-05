#!/usr/bin/env python3
"""
validate_exits.py — Re-check backtest trade exits against M1 candles.

For each closed trade, loads the M1 bars between entry and exit and answers:
  1. Did the TP/SL actually get hit at the M5-assumed exit price, or did price
     gap through (real fill would be worse)?
  2. On TP_HIT trades: was the SL hit on an earlier M1 candle in the same M5 bar?
  3. On SL_HIT trades: was the TP hit first on an earlier M1 bar (optimistic M5)?
  4. On Reverse Signal exits: what was the actual M1 open at that candle?

Usage:
    python3 validate_exits.py --trades reports/GOLD_backtest_trades.csv \\
                               --m1    cloud-function/data/GOLD_M1_20240101_20251231.csv

    python3 validate_exits.py --trades reports/GOLD_backtest_trades.csv \\
                               --m1    cloud-function/data/GOLD_M1_20240101_20251231.csv \\
                               --tz-offset -1          # shift M1 timestamps by -1h

Output:
    reports/GOLD_exit_validation.csv   — per-trade comparison
    Console summary                    — aggregate impact on P&L
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
import numpy as np

REPORTS_DIR = Path(__file__).parent / "reports"


# ── M1 loader ─────────────────────────────────────────────────────────────────

def load_m1(path: str, tz_offset_hours: float = 0) -> pd.DataFrame:
    print(f"📂 Loading M1 data: {path}")
    df = pd.read_csv(path, parse_dates=["timestamp"])
    if tz_offset_hours:
        df["timestamp"] += pd.Timedelta(hours=tz_offset_hours)
        print(f"   Applied timezone offset: {tz_offset_hours:+.1f}h")
    df.sort_values("timestamp", inplace=True)
    df.set_index("timestamp", inplace=True)
    print(f"   {len(df):,} M1 bars  |  {df.index[0]} → {df.index[-1]}")
    return df


# ── Per-trade exit re-check ────────────────────────────────────────────────────

def recheck_exit(trade: pd.Series, m1: pd.DataFrame, pip_size: float = 1.0) -> dict:
    """
    For one trade, walk the M1 candles from entry to exit and determine the
    earliest bar where TP or SL was actually touched.

    Returns a dict with validation fields to append to the trade row.
    """
    entry_time  = pd.Timestamp(trade["entry_time"])
    exit_time   = pd.Timestamp(trade["exit_time"])
    side        = trade["side"]          # 'BUY' or 'SELL'
    stop_loss   = float(trade["stop_loss"])
    take_profit = float(trade["take_profit"])
    m5_exit_px  = float(trade["exit_price"])
    m5_reason   = trade["exit_reason"]

    # Slice M1 candles that fall inside this trade's lifetime
    # Include entry bar (first M1 after entry) through the M5 exit bar
    window = m1.loc[entry_time:exit_time]

    if window.empty:
        return {
            "m1_bars_in_trade": 0,
            "m1_first_sl_bar": None,
            "m1_first_tp_bar": None,
            "m1_actual_exit_reason": "NO_M1_DATA",
            "m1_actual_exit_price": None,
            "m1_actual_exit_time": None,
            "gap_vs_m5_pips": None,
            "pnl_impact": None,
            "issue": "NO_M1_DATA",
        }

    # Walk M1 bars in chronological order — first hit wins
    m1_sl_bar = m1_tp_bar = None
    for ts, bar in window.iterrows():
        if side == "BUY":
            if m1_sl_bar is None and bar["low"] <= stop_loss:
                m1_sl_bar = (ts, bar)
            if m1_tp_bar is None and bar["high"] >= take_profit:
                m1_tp_bar = (ts, bar)
        else:  # SELL
            if m1_sl_bar is None and bar["high"] >= stop_loss:
                m1_sl_bar = (ts, bar)
            if m1_tp_bar is None and bar["low"] <= take_profit:
                m1_tp_bar = (ts, bar)

        # Stop as soon as both are found
        if m1_sl_bar and m1_tp_bar:
            break

    # Determine what M1 says actually happened first
    if m1_sl_bar and m1_tp_bar:
        m1_actual_reason = "SL_HIT" if m1_sl_bar[0] <= m1_tp_bar[0] else "TP_HIT"
    elif m1_sl_bar:
        m1_actual_reason = "SL_HIT"
    elif m1_tp_bar:
        m1_actual_reason = "TP_HIT"
    else:
        m1_actual_reason = m5_reason  # neither SL nor TP touched — reverse/time exit

    # Resolve M1 exit price (gap-adjusted: use candle open if price gapped past level)
    m1_exit_price = None
    m1_exit_time  = None

    if m1_actual_reason == "SL_HIT" and m1_sl_bar:
        ts, bar = m1_sl_bar
        m1_exit_time = ts
        if side == "BUY":
            # Gap-down: if M1 opened below SL, real fill = open (worse than SL)
            m1_exit_price = min(bar["open"], stop_loss)
        else:
            # Gap-up: if M1 opened above SL, real fill = open (worse than SL)
            m1_exit_price = max(bar["open"], stop_loss)

    elif m1_actual_reason == "TP_HIT" and m1_tp_bar:
        ts, bar = m1_tp_bar
        m1_exit_time = ts
        # TP is a limit order — fills at TP or better, never worse
        m1_exit_price = take_profit

    else:
        # Reverse signal: M5 exits at candle open — M1 can't improve on this
        m1_exit_price = m5_exit_px
        m1_exit_time  = exit_time
        m1_actual_reason = m5_reason

    # Gap vs M5 assumption (positive = M5 was optimistic, real was worse)
    if m1_exit_price is not None:
        if side == "BUY":
            gap_price = m5_exit_px - m1_exit_price  # positive = M5 gave better exit
        else:
            gap_price = m1_exit_price - m5_exit_px
        gap_pips = gap_price / pip_size
    else:
        gap_pips = None

    # P&L impact: difference between M5 P&L and what M1 says it should be.
    # Only meaningful for SL/TP exits where M1 might give a different price.
    # Reverse-signal exits use the same price → impact is always 0, skip them.
    size = float(trade["size"])
    # spread_cost / slippage_cost in the trades CSV are already total USD (× size).
    total_costs = float(trade.get("spread_cost", 0)) + float(trade.get("slippage_cost", 0))

    if m1_exit_price is not None and m1_actual_reason in ("SL_HIT", "TP_HIT"):
        if side == "BUY":
            m1_gross = (m1_exit_price - float(trade["entry_price"])) * size
        else:
            m1_gross = (float(trade["entry_price"]) - m1_exit_price) * size
        m1_pnl = m1_gross - total_costs
        pnl_impact = m1_pnl - float(trade["pnl"])   # negative = M1 is worse
    else:
        # Reverse signal or no M1 data — exit price unchanged, no impact to report
        m1_pnl    = float(trade["pnl"]) if m1_exit_price is not None else None
        pnl_impact = 0.0 if m1_exit_price is not None else None

    # Flag issues worth investigating
    issues = []
    if m1_actual_reason != m5_reason and m5_reason in ("SL_HIT", "TP_HIT"):
        issues.append(f"WRONG_EXIT_TYPE:{m5_reason}→{m1_actual_reason}")
    if gap_pips is not None and abs(gap_pips) >= 1:
        issues.append(f"GAP_{gap_pips:+.1f}pips")
    if pnl_impact is not None and pnl_impact < -10:
        issues.append(f"PNL_IMPACT:{pnl_impact:+.2f}")

    return {
        "m1_bars_in_trade":     len(window),
        "m1_first_sl_bar":      m1_sl_bar[0] if m1_sl_bar else None,
        "m1_first_tp_bar":      m1_tp_bar[0] if m1_tp_bar else None,
        "m1_actual_exit_reason": m1_actual_reason,
        "m1_actual_exit_price":  round(m1_exit_price, 5) if m1_exit_price else None,
        "m1_actual_exit_time":   m1_exit_time,
        "m1_pnl":                round(m1_pnl, 2) if m1_pnl is not None else None,
        "gap_vs_m5_pips":        round(gap_pips, 2) if gap_pips is not None else None,
        "pnl_impact":            round(pnl_impact, 2) if pnl_impact is not None else None,
        "issue":                 " | ".join(issues) if issues else "OK",
    }


# ── Summary printer ────────────────────────────────────────────────────────────

def print_summary(trades: pd.DataFrame, val: pd.DataFrame):
    merged = pd.concat([trades, val], axis=1)

    print("\n" + "=" * 70)
    print("EXIT VALIDATION SUMMARY")
    print("=" * 70)

    total = len(merged)
    no_m1 = (val["m1_actual_exit_reason"] == "NO_M1_DATA").sum()
    covered = total - no_m1

    print(f"\nTrades:          {total:,}")
    print(f"M1 coverage:     {covered:,} / {total:,}  ({covered/total*100:.1f}%)")

    if covered == 0:
        print("\n⚠  No trades had M1 coverage. Check --tz-offset and date range.")
        return

    m = merged[merged["m1_actual_exit_reason"] != "NO_M1_DATA"]

    # Exit type correctness
    sl_tp_trades = m[m["exit_reason"].isin(["SL_HIT", "TP_HIT"])]
    if len(sl_tp_trades):
        correct = (sl_tp_trades["exit_reason"] == sl_tp_trades["m1_actual_exit_reason"]).sum()
        wrong   = len(sl_tp_trades) - correct
        print(f"\n📊 SL/TP exit correctness ({len(sl_tp_trades)} trades):")
        print(f"   Correct (M5 = M1):  {correct:,}  ({correct/len(sl_tp_trades)*100:.1f}%)")
        print(f"   Wrong exit type:    {wrong:,}  ({wrong/len(sl_tp_trades)*100:.1f}%)")
        if wrong:
            wrong_df = sl_tp_trades[sl_tp_trades["exit_reason"] != sl_tp_trades["m1_actual_exit_reason"]]
            for _, r in wrong_df.head(5).iterrows():
                print(f"     {r['entry_time']}  {r['side']}  M5={r['exit_reason']} → M1={r['m1_actual_exit_reason']}  PnL impact: ${r['pnl_impact']:+.2f}")

    # Gap analysis (SL exits only — TP fills at exact price)
    sl_exits = m[m["m1_actual_exit_reason"] == "SL_HIT"]
    if len(sl_exits):
        gaps = sl_exits["gap_vs_m5_pips"].dropna()
        gapped = (gaps.abs() >= 1).sum()
        print(f"\n📉 SL gap-through analysis ({len(sl_exits)} SL hits):")
        print(f"   Clean fills (gap < 1 pip): {len(gaps) - gapped:,}")
        print(f"   Gapped (≥ 1 pip worse):    {gapped:,}  ({gapped/len(gaps)*100:.1f}%)")
        if gapped:
            print(f"   Avg gap:  {gaps[gaps.abs() >= 1].mean():+.2f} pips")
            print(f"   Worst gap: {gaps.min():.2f} pips")

    # Total P&L impact — only count SL/TP trades where M1 gives a different price.
    # Reverse-signal and no-M1-data trades have pnl_impact=0/None — don't distort total.
    total_m5_pnl = merged["pnl"].sum()
    sl_tp_m = m[m["m1_actual_exit_reason"].isin(["SL_HIT", "TP_HIT"])]
    total_impact = sl_tp_m["pnl_impact"].fillna(0).sum()

    print(f"\n💰 P&L impact (SL/TP exits only — reverse signals unchanged):")
    print(f"   M5 backtest P&L:     ${total_m5_pnl:+,.2f}")
    print(f"   M1-adjusted P&L:     ${total_m5_pnl + total_impact:+,.2f}")
    if total_m5_pnl != 0:
        print(f"   SL/TP correction:    ${total_impact:+,.2f}  ({total_impact/abs(total_m5_pnl)*100:+.2f}%)")

    print(f"\n🚩 Issues found:")
    issues = m[m["issue"] != "OK"]["issue"].value_counts()
    if issues.empty:
        print("   None — exits look clean ✅")
    else:
        for issue, count in issues.head(10).items():
            print(f"   {count:4d}x  {issue}")

    print("\n" + "=" * 70)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Validate backtest exits against M1 candles")
    parser.add_argument("--trades",    required=True, help="Backtest trades CSV (e.g. reports/GOLD_backtest_trades.csv)")
    parser.add_argument("--m1",        required=True, help="M1 candle CSV (e.g. cloud-function/data/GOLD_M1_20240101_20251231.csv)")
    parser.add_argument("--pip-size",  type=float, default=1.0,
                        help="Pip size for the instrument (1.0 for GOLD/US100, 0.0001 for EURUSD). Default: 1.0")
    parser.add_argument("--tz-offset", type=float, default=-1.0,
                        help="Hours to shift M1 timestamps to align with backtest timezone (default: -1 for Kaggle XAU data)")
    parser.add_argument("--output",    default=None, help="Output CSV path (default: auto)")
    parser.add_argument("--max-trades", type=int, default=None,
                        help="Only validate first N trades (for quick testing)")
    args = parser.parse_args()

    # Load inputs
    print(f"📋 Loading trades: {args.trades}")
    trades = pd.read_csv(args.trades, parse_dates=["entry_time", "exit_time"])
    if args.max_trades:
        trades = trades.head(args.max_trades)
    print(f"   {len(trades):,} trades  |  {trades['entry_time'].min()} → {trades['exit_time'].max()}")

    m1 = load_m1(args.m1, tz_offset_hours=args.tz_offset)

    # Validate each trade
    print(f"\n🔍 Validating {len(trades):,} trades against M1...")
    results = []
    for i, (_, trade) in enumerate(trades.iterrows()):
        result = recheck_exit(trade, m1, pip_size=args.pip_size)
        results.append(result)
        if (i + 1) % 100 == 0:
            print(f"   {i + 1:,}/{len(trades):,}")

    val = pd.DataFrame(results)

    # Save output
    trades_path = Path(args.trades)
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = REPORTS_DIR / trades_path.name.replace("_trades.csv", "_exit_validation.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    merged = pd.concat([trades, val], axis=1)
    merged.to_csv(out_path, index=False)
    print(f"\n💾 Saved: {out_path}")

    # Print summary
    print_summary(trades, val)

    print(f"\n📄 Full per-trade results: {out_path}")


if __name__ == "__main__":
    main()
