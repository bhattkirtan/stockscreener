#!/usr/bin/env python3
"""
Parameter Grid-Search Optimizer
================================
Best practice for evaluating SL/TP combinations:

  1. Define a grid of SL and TP values
  2. Run a full backtest for each combination (same signal logic, only exits change)
  3. Rank by Profit Factor (robust metric) — NOT just total PnL
  4. Apply robustness filters: min trades, max drawdown cap
  5. Save full results to CSV for further analysis

Usage:
    python3 optimize_params.py --instrument US100
    python3 optimize_params.py --instrument US100 --size 1
    python3 optimize_params.py --instrument GOLD --sl-range 15 50 5 --tp-range 30 150 15

Output:
    reports/US100_optimization_results.csv
    (ranked table printed to console)
"""
import sys
import os
import copy
import argparse
import asyncio
import itertools
from pathlib import Path
from datetime import datetime

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

# Reuse helpers from run_skills_backtest
from run_skills_backtest import load_config, load_historical_data, resample_ohlcv, run_skills_backtest


# ── Default grids ──────────────────────────────────────────────────────────────

# For US100 (points): realistic range given ~2-3pt spread + intraday swings
US100_SL_RANGE  = [15, 20, 25, 30, 40, 50]
US100_TP_RANGE  = [50, 75, 100, 125, 150, 200]

# For GOLD (pips): typical range
GOLD_SL_RANGE   = [10, 15, 20, 25, 30]
GOLD_TP_RANGE   = [30, 45, 60, 75, 90]

# For EURUSD (pips)
EURUSD_SL_RANGE = [10, 12, 15, 18, 20]
EURUSD_TP_RANGE = [25, 30, 40, 50, 60]

DEFAULT_GRIDS = {
    'US100':  (US100_SL_RANGE,  US100_TP_RANGE),
    'GOLD':   (GOLD_SL_RANGE,   GOLD_TP_RANGE),
    'EURUSD': (EURUSD_SL_RANGE, EURUSD_TP_RANGE),
}

# ── Filters (skip statistically unreliable combinations) ──────────────────────
MIN_TRADES   = 30     # Need at least 30 trades to trust the stats
MAX_DRAWDOWN = 50.0   # Skip combos with > 50% max drawdown


def score(row: dict) -> float:
    """
    Composite score (higher = better).
    Weights: Profit Factor (primary) + Sharpe bonus + win-rate stability.
    """
    pf = row.get('profit_factor', 0) or 0
    sharpe = row.get('sharpe_ratio', 0) or 0
    return round(pf * 0.6 + sharpe * 0.4, 4)


async def _single_run(config: dict, df: pd.DataFrame) -> dict:
    """Run one backtest and return results dict."""
    return await run_skills_backtest(df, config)


def run_grid(instrument: str, sl_values: list, tp_values: list,
             position_size: float, base_config: dict, df: pd.DataFrame) -> pd.DataFrame:
    """
    Iterate over all (SL, TP) combinations, run backtest for each,
    collect metrics into a DataFrame.
    """
    combos = list(itertools.product(sl_values, tp_values))
    total = len(combos)
    print(f"\n🔬 Grid search: {len(sl_values)} SL × {len(tp_values)} TP = {total} combinations")
    print(f"   Position size: {position_size} unit(s)")
    print("=" * 60)

    rows = []

    for i, (sl, tp) in enumerate(combos, 1):
        rr = round(tp / sl, 2)
        print(f"\n[{i:3d}/{total}] SL={sl:5.0f}  TP={tp:5.0f}  R:R=1:{rr}", end="  ", flush=True)

        # Build per-run config (deep-copy so runs don't pollute each other)
        cfg = copy.deepcopy(base_config)
        cfg.setdefault('analysis', {}).setdefault('sl_tp', {})['stop_loss_pips']   = sl
        cfg.setdefault('analysis', {}).setdefault('sl_tp', {})['take_profit_pips'] = tp
        cfg.setdefault('risk', {})['stop_loss_pips']   = sl
        cfg.setdefault('risk', {})['take_profit_pips'] = tp
        cfg.setdefault('backtesting', {})['position_size'] = position_size
        cfg.setdefault('backtest', {})['position_size']    = position_size

        try:
            results = asyncio.run(_single_run(cfg, df.copy()))
        except Exception as e:
            print(f"ERROR: {e}")
            continue

        total_trades   = results.get('total_trades', 0)
        win_rate       = results.get('win_rate', 0)
        total_pnl      = results.get('total_pnl', 0)
        total_return   = results.get('total_return_pct', 0)
        max_dd         = abs(results.get('max_drawdown_pct', results.get('max_drawdown', 0)))
        sharpe         = results.get('sharpe_ratio', 0)
        profit_factor  = results.get('profit_factor', 0)
        avg_win        = results.get('avg_win', 0)
        avg_loss       = results.get('avg_loss', 0)
        expectancy     = results.get('expectancy_per_trade', 0)

        # Filter unreliable
        if total_trades < MIN_TRADES:
            print(f"⚠  skipped (only {total_trades} trades < {MIN_TRADES} min)")
            continue
        if max_dd > MAX_DRAWDOWN:
            print(f"⚠  skipped (DD={max_dd:.1f}% > {MAX_DRAWDOWN}% cap)")
            continue

        row = {
            'sl': sl, 'tp': tp, 'rr': rr,
            'total_trades': total_trades,
            'win_rate': round(win_rate, 1),
            'total_pnl': round(total_pnl, 2),
            'total_return_pct': round(total_return, 2),
            'max_drawdown_pct': round(max_dd, 2),
            'profit_factor': round(profit_factor, 3),
            'sharpe_ratio': round(sharpe, 3),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'expectancy': round(expectancy, 2),
        }
        row['score'] = score(row)
        rows.append(row)
        print(f"✅ trades={total_trades:3d}  WR={win_rate:.0f}%  PnL=${total_pnl:+,.0f}  PF={profit_factor:.2f}  Sharpe={sharpe:.2f}  DD={max_dd:.1f}%")

    if not rows:
        print("\n⚠  No valid combinations passed the filters.")
        return pd.DataFrame()

    df_results = pd.DataFrame(rows).sort_values('score', ascending=False).reset_index(drop=True)
    df_results.index += 1  # 1-based rank
    return df_results


def print_summary(df_results: pd.DataFrame, instrument: str, position_size: float):
    if df_results.empty:
        return
    print("\n" + "=" * 80)
    print(f"📊 OPTIMIZATION RESULTS — {instrument}  (size={position_size} unit, ranked by score)")
    print("=" * 80)
    cols = ['sl', 'tp', 'rr', 'total_trades', 'win_rate', 'total_pnl',
            'profit_factor', 'sharpe_ratio', 'max_drawdown_pct', 'score']
    print(df_results[cols].head(20).to_string())
    print("\n🏆 Best combination:")
    best = df_results.iloc[0]
    print(f"   SL={best['sl']:.0f}  TP={best['tp']:.0f}  R:R=1:{best['rr']}")
    print(f"   Win Rate: {best['win_rate']:.1f}%  |  PnL: ${best['total_pnl']:+,.2f}  |  Profit Factor: {best['profit_factor']:.3f}")
    print(f"   Sharpe: {best['sharpe_ratio']:.3f}  |  Max DD: {best['max_drawdown_pct']:.1f}%  |  Trades: {best['total_trades']:.0f}")
    print("\n💡 Best practice tip: Choose the combo with the best Profit Factor (>1.5)")
    print("   that also has: Sharpe > 1.0, MaxDD < 20%, and enough trades (>50).")
    print("   The #1 ranked combo above is a good starting point but verify on")
    print("   out-of-sample data before going live.")


def main():
    parser = argparse.ArgumentParser(description='Parameter Grid-Search Optimizer')
    parser.add_argument('--instrument', default='US100', help='GOLD, US100, EURUSD')
    parser.add_argument('--size', type=float, default=1.0, help='Position size in units (default: 1)')
    parser.add_argument('--sl-range', nargs=3, type=float, metavar=('MIN', 'MAX', 'STEP'),
                        help='SL range: --sl-range 15 50 5  (overrides default grid)')
    parser.add_argument('--tp-range', nargs=3, type=float, metavar=('MIN', 'MAX', 'STEP'),
                        help='TP range: --tp-range 50 200 25  (overrides default grid)')
    args = parser.parse_args()

    instrument = args.instrument.upper()

    # Build SL/TP grids
    if args.sl_range:
        mn, mx, step = args.sl_range
        sl_values = [round(mn + i * step, 2) for i in range(int((mx - mn) / step) + 1)]
    else:
        sl_values = DEFAULT_GRIDS.get(instrument, (US100_SL_RANGE, US100_TP_RANGE))[0]

    if args.tp_range:
        mn, mx, step = args.tp_range
        tp_values = [round(mn + i * step, 2) for i in range(int((mx - mn) / step) + 1)]
    else:
        tp_values = DEFAULT_GRIDS.get(instrument, (US100_SL_RANGE, US100_TP_RANGE))[1]

    print("🔬 PARAMETER GRID-SEARCH OPTIMIZER")
    print("=" * 60)
    print(f"   Instrument : {instrument}")
    print(f"   SL values  : {sl_values}")
    print(f"   TP values  : {tp_values}")
    print(f"   Size       : {args.size} unit(s)")
    print(f"   Min trades : {MIN_TRADES}  |  Max DD: {MAX_DRAWDOWN}%")

    # Load config + data once (reused across all runs)
    config = load_config(instrument)
    data_path = config.get('backtest', {}).get('data_path',
                    f'../cloud-function/data/{instrument}_M5_150000bars.csv')
    df = load_historical_data(data_path)

    # Resample if needed
    resample_to = config.get('market_data', {}).get('resample_to')
    if resample_to and str(resample_to).upper() not in ('M5', '5'):
        minutes = int(str(resample_to).upper().replace('M', ''))
        df = resample_ohlcv(df, minutes)

    start = datetime.now()
    df_results = run_grid(instrument, sl_values, tp_values, args.size, config, df)
    elapsed = (datetime.now() - start).total_seconds()

    print_summary(df_results, instrument, args.size)

    if not df_results.empty:
        out_dir = Path(__file__).parent / 'reports'
        out_dir.mkdir(exist_ok=True)
        out_file = out_dir / f'{instrument}_optimization_results.csv'
        df_results.to_csv(out_file, index_label='rank')
        print(f"\n💾 Full results saved: {out_file}")

    print(f"\n⏱  Total time: {elapsed:.0f}s  ({elapsed/60:.1f} min)")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⏸️  Optimization interrupted by user")
    except Exception as e:
        import traceback
        print(f"\n❌ Error: {e}")
        traceback.print_exc()
        sys.exit(1)
