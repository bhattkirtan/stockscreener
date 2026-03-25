#!/usr/bin/env python3
"""
Run optimization using local data files (bypass GCS)
"""
import sys
import os
import pandas as pd
from pathlib import Path

# Add cloud-function to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.optimization.optimize_strategy import StrategyOptimizer


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _load_price_data(data_file: str) -> pd.DataFrame:
    """Load OHLCV CSV and set a datetime index."""
    df = pd.read_csv(data_file)
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
    else:
        df.index = pd.to_datetime(df.index)
    return df


def _csv_row_to_params(row: pd.Series) -> dict:
    """
    Reconstruct a full parameter dict from a results-CSV row.
    The CSV uses short column names; this maps them back to the
    param keys expected by build_strategy / build_backtest_config.
    """
    # Parse TP/SL from the formatted 'tp_sl' column, e.g. "Fixed 20:40" or "ATR 1.5x:3.0x"
    tp_sl_raw = str(row.get('tp_sl', 'Fixed 20:40'))
    if tp_sl_raw.startswith('ATR') or tp_sl_raw.startswith('atr'):
        tp_sl_strategy = 'atr'
        sl_pips = None
        tp_pips = None
        atr_sl = row.get('atr_sl_multiplier', 1.5)
        atr_tp = row.get('atr_tp_multiplier', 3.0)
    else:
        tp_sl_strategy = 'fixed'
        # "Fixed 20:40" → sl=20, tp=40
        try:
            parts = tp_sl_raw.replace('Fixed', '').strip().split(':')
            sl_pips = float(parts[0])
            tp_pips = float(parts[1])
        except Exception:
            sl_pips = row.get('sl_pips', 20)
            tp_pips = row.get('tp_pips', 40)
        atr_sl = None
        atr_tp = None

    return {
        'supertrend_period':        int(row.get('st_period', 14)),
        'supertrend_multiplier':    float(row.get('st_mult', 2.0)),
        'sma_fast':                 int(row.get('sma_fast', 25)),
        'sma_slow':                 int(row.get('sma_slow', 50)),
        'ema_period':               int(row.get('ema', 21)),
        'bb_period':                int(row.get('bb_period', 20)),
        'bb_std':                   float(row.get('bb_std', 2.0)),
        'pip_value':                float(row.get('pip_value', 1.0)),
        'tp_sl_strategy':           tp_sl_strategy,
        'sl_pips':                  sl_pips,
        'tp_pips':                  tp_pips,
        'atr_sl_multiplier':        atr_sl,
        'atr_tp_multiplier':        atr_tp,
        # Friday filter
        'enable_friday_filter':     bool(row.get('enable_friday_filter', False)),
        'friday_cutoff_hour':       int(row.get('friday_cutoff_hour', 15)),
        # Intraday gates
        'enable_time_exit':         bool(row.get('enable_time_exit', False)),
        'max_holding_hours':        row.get('max_holding_hours') or None,
        'enable_eod_close':         bool(row.get('enable_eod_close', False)),
        'eod_close_hour':           int(row.get('eod_close_hour', 16)),
        'enable_eod_blackout':      bool(row.get('enable_eod_blackout', False)),
        'no_entry_before_eod_hours': int(row.get('no_entry_before_eod_hours', 1)),
        'enable_partial_exit':      bool(row.get('enable_partial_exit', False)),
        'partial_exit_tp1_pips':    int(row.get('partial_exit_tp1_pips', 10)),
        'partial_exit_tp2_pips':    int(row.get('partial_exit_tp2_pips', 20)),
        # Phase-1 filters
        'use_rsi_filter':           bool(row.get('use_rsi_filter', False)),
        'rsi_period':               int(row.get('rsi_period', 14)),
        'rsi_overbought':           int(row.get('rsi_overbought', 70)),
        'rsi_oversold':             int(row.get('rsi_oversold', 30)),
        'use_atr_volatility_filter':bool(row.get('use_atr_volatility_filter', False)),
        'atr_volatility_period':    int(row.get('atr_volatility_period', 14)),
        'atr_sma_period':           int(row.get('atr_sma_period', 20)),
        'atr_min_ratio':            float(row.get('atr_min_ratio', 0.7)),
        'atr_max_ratio':            float(row.get('atr_max_ratio', 1.5)),
        'use_session_filter':       bool(row.get('use_session_filter', False)),
        'trading_sessions':         str(row.get('trading_sessions', 'london_ny')),
        'use_heikin_ashi':          bool(row.get('use_heikin_ashi', False)),
        # Zone
        'strategy_type':            str(row.get('strategy_type', 'supertrend')),
        'zone_block_distance':      float(row.get('zone_block_distance', 1.0)),
        'enable_zone_stops':        bool(row.get('enable_zone_stops', False)),
        # Event blocking — always off by default; winners mode overrides below
        'enable_event_blocking':    False,
        'calendar_path':            None,
    }


def _find_latest_results_csv(results_dir: str = 'data/optimization') -> Path:
    """Return the most recent all_strategies CSV across all date folders."""
    base = Path(results_dir)
    candidates = sorted(base.glob('**/GOLD_M5_all_strategies*.csv'),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError(f"No GOLD_M5_all_strategies*.csv found under {base}")
    return candidates[0]


def _print_winners_comparison(results_df: pd.DataFrame) -> None:
    """Print a side-by-side table comparing blocking vs no-blocking for each winner."""
    if 'enable_event_blocking' not in results_df.columns:
        print(results_df[['strategy_name', 'return_pct', 'total_trades',
                           'win_rate', 'max_drawdown_pct', 'profit_factor']].to_string(index=False))
        return

    no_block = results_df[results_df['enable_event_blocking'] == False].copy()
    blocked  = results_df[results_df['enable_event_blocking'] == True].copy()

    print(f"\n{'Strategy':<55} {'Return%':>8} {'→':>2} {'Return%':>8}  "
          f"{'Trades':>7} {'→':>2} {'Trades':>7}  "
          f"{'WinRate':>8} {'→':>2} {'WinRate':>8}  "
          f"{'DD%':>6} {'→':>2} {'DD%':>6}")
    print(f"{'(no block)':<55} {'no blk':>8} {'':>2} {'blocked':>8}  "
          f"{'no blk':>7} {'':>2} {'blocked':>7}  "
          f"{'no blk':>8} {'':>2} {'blocked':>8}  "
          f"{'no blk':>6} {'':>2} {'blocked':>6}")
    print("-" * 130)

    # Match blocked row to no-block row by _winner_rank tag (set when building combinations)
    for _, nb_row in no_block.sort_values('_winner_rank').iterrows():
        b_match = blocked[blocked['_winner_rank'] == nb_row['_winner_rank']]

        name_display = str(nb_row.get('strategy_name', ''))[:54]

        if b_match.empty:
            b_ret, b_trades, b_wr, b_dd = '—', '—', '—', '—'
            delta = ''
        else:
            b = b_match.iloc[0]
            b_ret    = f"{b['return_pct']:.1f}%"
            b_trades = f"{int(b['total_trades'])}"
            b_wr     = f"{b['win_rate']:.1f}%"
            b_dd     = f"{b['max_drawdown_pct']:.1f}%"
            ret_diff = b['return_pct'] - nb_row['return_pct']
            delta    = f"({'+'if ret_diff>=0 else ''}{ret_diff:.1f}%)"

        print(f"{name_display:<55} "
              f"{nb_row['return_pct']:>7.1f}%  {b_ret:>8} {delta:>10}  "
              f"{int(nb_row['total_trades']):>7}  {b_trades:>7}  "
              f"{nb_row['win_rate']:>7.1f}%  {b_wr:>8}  "
              f"{nb_row['max_drawdown_pct']:>5.1f}%  {b_dd:>7}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Local Strategy Optimization')
    parser.add_argument('--data-file', required=True, help='Path to CSV data file')
    parser.add_argument('--instrument', default='GOLD', help='Instrument name')
    parser.add_argument('--timeframe', default='M5', help='Timeframe')
    parser.add_argument('--capital', type=float, default=10000.0, help='Initial capital')
    parser.add_argument('--mode', default='quick',
                        choices=['short', 'quick', 'medium', 'full', 'intraday', 'zone', 'winners'],
                        help='Optimization mode. "winners" re-runs top-N from latest results with event-blocking comparison.')
    parser.add_argument('--validation-split', type=float, default=0.0,
                        help='Train/test split ratio (e.g., 0.3 for 70/30 split)')
    parser.add_argument('--n-jobs', type=int, default=12,
                        help='Number of parallel workers (default: 12, use -1 for all cores)')
    parser.add_argument('--no-parallel', action='store_true', help='Disable parallel processing')
    parser.add_argument('--enable-event-blocking', action='store_true',
                        help='Enable event blocking on all modes except winners (which always tests both)')
    parser.add_argument('--calendar-path', default='data/economic_calendar.json',
                        help='Path to economic calendar JSON file')
    parser.add_argument('--sample', type=int, default=0,
                        help='Randomly sample N combinations instead of testing all (0 = all).')
    parser.add_argument('--top-n', type=int, default=10,
                        help='How many top strategies to use in winners mode (default: 10)')
    parser.add_argument('--results-csv', default=None,
                        help='Path to a specific results CSV for winners mode (default: auto-detect latest)')

    # Grid overrides — useful for non-GOLD instruments (e.g. ETH needs larger SL/TP in $)
    parser.add_argument('--sl-pips', default=None,
                        help='Override SL values (comma-separated). e.g. "50,100,150" for ETH')
    parser.add_argument('--tp-pips', default=None,
                        help='Override TP values (comma-separated). e.g. "100,200,300" for ETH')
    parser.add_argument('--pip-value', default=None,
                        help='Override pip_value values (comma-separated). e.g. "1.0" for ETH')
    parser.add_argument('--fixed-only', action='store_true',
                        help='Test fixed TP/SL only (skip ATR combos) — simpler and faster')
    parser.add_argument('--atr-only', action='store_true',
                        help='Test ATR-based TP/SL only (skip fixed combos)')
    parser.add_argument('--st-mult', default=None,
                        help='Supertrend multipliers, comma-separated. e.g. "1.0,1.5,2.0"')
    parser.add_argument('--sma-fast', default=None,
                        help='SMA fast periods, comma-separated. e.g. "5,10,15"')
    parser.add_argument('--sma-slow', default=None,
                        help='SMA slow periods, comma-separated. e.g. "20,30,50"')
    parser.add_argument('--position-size', default=None, type=float,
                        help='Position size per trade. e.g. 1.0 for 1 ETH (default: 10.0)')
    parser.add_argument('--spread-usd', default=None, type=float,
                        help='Spread cost in USD per trade. e.g. 1.75 for ETH (default: 0.50 GOLD)')

    args = parser.parse_args()

    print("\n" + "="*70)
    print("🎯 Local Strategy Parameter Optimization")
    print("="*70 + "\n")

    # Load price data
    print(f"📊 Loading data from {args.data_file}...")
    try:
        df = _load_price_data(args.data_file)
        print(f"✅ Loaded {len(df)} bars")
        print(f"   Range: {df.index[0]} to {df.index[-1]}")
        print(f"   Columns: {list(df.columns)}\n")
    except Exception as e:
        print(f"❌ Failed to load data: {e}")
        sys.exit(1)

    print(f"🚀 Starting optimization...")
    print(f"   Mode: {args.mode}")
    print(f"   Capital: ${args.capital:,.2f}")
    if args.validation_split > 0:
        print(f"   Validation Split: {args.validation_split:.1%}")
    n_workers = args.n_jobs if args.n_jobs > 0 else os.cpu_count()
    print(f"   Parallel: {'Yes' if not args.no_parallel else 'No'} ({n_workers} workers)")
    print()

    optimizer = StrategyOptimizer(
        df=df,
        initial_capital=args.capital,
        epic=args.instrument,
        resolution=args.timeframe,
        validation_split=args.validation_split,
        n_jobs=args.n_jobs,
    )

    # ── WINNERS MODE ───────────────────────────────────────────────────────
    if args.mode == 'winners':
        # Find results CSV
        try:
            csv_path = Path(args.results_csv) if args.results_csv else _find_latest_results_csv()
        except FileNotFoundError as e:
            print(f"❌ {e}")
            sys.exit(1)

        print(f"🏆 Winners Mode — re-running top {args.top_n} strategies with/without event blocking")
        print(f"   Source: {csv_path}\n")

        winners_df = pd.read_csv(csv_path)

        # Deduplicate by return_pct + total_trades (same underlying combo appears multiple times
        # in zone runs due to zone_block_distance × enable_zone_stops expansion)
        winners_df = winners_df.drop_duplicates(subset=['return_pct', 'total_trades',
                                                         'st_mult', 'sma_fast', 'sma_slow',
                                                         'tp_sl'])
        top_rows = winners_df.head(args.top_n)

        print(f"   Top {len(top_rows)} unique strategies selected:")
        for i, (_, row) in enumerate(top_rows.iterrows(), 1):
            print(f"   {i:2d}. {row['strategy_name']:<55}  return={row['return_pct']:.1f}%  "
                  f"trades={int(row['total_trades'])}  dd={row['max_drawdown_pct']:.1f}%")

        # Build combinations: baseline (no blocking) + event-blocked copy
        # _winner_rank ties each pair together so the comparison table matches them correctly
        combinations = []
        for rank, (_, row) in enumerate(top_rows.iterrows()):
            base = _csv_row_to_params(row)

            # Version 1: no event blocking (baseline re-run to confirm)
            no_block = {**base, 'enable_event_blocking': False, 'calendar_path': None, '_winner_rank': rank}
            combinations.append(no_block)

            # Version 2: event blocking enabled
            blocked = {**base, 'enable_event_blocking': True, 'calendar_path': args.calendar_path, '_winner_rank': rank}
            combinations.append(blocked)

        print(f"\n   Running {len(combinations)} total combos ({len(top_rows)} × 2)...\n")

        results_df = optimizer.run_combinations(combinations, parallel=not args.no_parallel)

        # Show comparison table
        print("\n" + "="*130)
        print("📊 WINNERS — EVENT BLOCKING COMPARISON")
        print("="*130)
        _print_winners_comparison(results_df)

        # Export
        output_file = optimizer.export_results(results_df)
        if output_file:
            print(f"\n✅ Results saved to: {output_file}")

        print("\n✅ Winners analysis complete!\n")
        return

    # ── GRID OVERRIDES (sl_pips / tp_pips / pip_value / fixed-only) ─────────
    def _apply_grid_overrides(grid: dict) -> dict:
        if args.sl_pips:
            grid['sl_pips'] = [float(v) for v in args.sl_pips.split(',')]
        if args.tp_pips:
            grid['tp_pips'] = [float(v) for v in args.tp_pips.split(',')]
        if args.pip_value:
            grid['pip_value'] = [float(v) for v in args.pip_value.split(',')]
        if args.fixed_only:
            grid['tp_sl_strategy'] = ['fixed']
        if args.atr_only:
            grid['tp_sl_strategy'] = ['atr']
        if args.position_size is not None:
            grid['position_size'] = [args.position_size]
        if args.spread_usd is not None:
            grid['spread_usd'] = [args.spread_usd]
        if args.st_mult:
            grid['supertrend_multiplier'] = [float(v) for v in args.st_mult.split(',')]
        if args.sma_fast:
            grid['sma_fast'] = [int(v) for v in args.sma_fast.split(',')]
        if args.sma_slow:
            grid['sma_slow'] = [int(v) for v in args.sma_slow.split(',')]
        return grid

    _has_overrides = any([
        args.sl_pips, args.tp_pips, args.pip_value, args.fixed_only, args.atr_only,
        args.position_size is not None, args.spread_usd is not None,
        args.st_mult, args.sma_fast, args.sma_slow,
    ])
    if _has_overrides:
        _orig_short    = optimizer.define_short_grid
        _orig_quick    = optimizer.define_quick_grid
        _orig_medium   = optimizer.define_medium_grid
        _orig_intraday = optimizer.define_intraday_grid
        _orig_zone     = optimizer.define_zone_grid
        _orig_full     = optimizer.define_parameter_grid
        optimizer.define_short_grid     = lambda: _apply_grid_overrides(_orig_short())
        optimizer.define_quick_grid     = lambda: _apply_grid_overrides(_orig_quick())
        optimizer.define_medium_grid    = lambda: _apply_grid_overrides(_orig_medium())
        optimizer.define_intraday_grid  = lambda: _apply_grid_overrides(_orig_intraday())
        optimizer.define_zone_grid      = lambda: _apply_grid_overrides(_orig_zone())
        optimizer.define_parameter_grid = lambda: _apply_grid_overrides(_orig_full())
        overrides = []
        if args.st_mult:                    overrides.append(f'st_mult={args.st_mult}')
        if args.sma_fast:                   overrides.append(f'sma_fast={args.sma_fast}')
        if args.sma_slow:                   overrides.append(f'sma_slow={args.sma_slow}')
        if args.sl_pips:                    overrides.append(f'sl_pips={args.sl_pips}')
        if args.tp_pips:                    overrides.append(f'tp_pips={args.tp_pips}')
        if args.pip_value:                  overrides.append(f'pip_value={args.pip_value}')
        if args.fixed_only:                overrides.append('fixed TP/SL only')
        if args.atr_only:                  overrides.append('ATR TP/SL only')
        if args.position_size is not None: overrides.append(f'position_size={args.position_size}')
        if args.spread_usd is not None:    overrides.append(f'spread_usd=${args.spread_usd}')
        print(f"   🔧 Grid overrides: {', '.join(overrides)}\n")

    # ── ALL OTHER MODES ────────────────────────────────────────────────────
    if args.enable_event_blocking:
        original_short_grid    = optimizer.define_short_grid
        original_quick_grid    = optimizer.define_quick_grid
        original_medium_grid   = optimizer.define_medium_grid
        original_intraday_grid = optimizer.define_intraday_grid
        original_zone_grid     = optimizer.define_zone_grid
        original_full_grid     = optimizer.define_parameter_grid

        def add_event_blocking(grid):
            grid['enable_event_blocking'] = [True]
            grid['calendar_path'] = [args.calendar_path]
            return grid

        optimizer.define_short_grid    = lambda: add_event_blocking(original_short_grid())
        optimizer.define_quick_grid    = lambda: add_event_blocking(original_quick_grid())
        optimizer.define_medium_grid   = lambda: add_event_blocking(original_medium_grid())
        optimizer.define_intraday_grid = lambda: add_event_blocking(original_intraday_grid())
        optimizer.define_zone_grid     = lambda: add_event_blocking(original_zone_grid())
        optimizer.define_parameter_grid = lambda: add_event_blocking(original_full_grid())

        print(f"   🚫 Event Blocking: ENABLED  (calendar: {args.calendar_path})\n")

    results_df = optimizer.run_optimization(
        mode=args.mode,
        parallel=not args.no_parallel,
        max_combos=args.sample if args.sample > 0 else None,
    )

    print("\n" + "="*70)
    print("📊 OPTIMIZATION RESULTS")
    print("="*70 + "\n")

    optimizer.print_summary(results_df, top_n=20)

    output_file = optimizer.export_results(results_df)
    if output_file:
        print(f"\n✅ Results saved to: {output_file}")
        top_50 = results_df.head(50)
        top_50.to_csv(output_file.replace('.csv', '_top50.csv'), index=False)
        print(f"✅ Top 50 saved to: {output_file.replace('.csv', '_top50.csv')}")

    print("\n✅ Optimization complete!\n")


if __name__ == '__main__':
    main()

