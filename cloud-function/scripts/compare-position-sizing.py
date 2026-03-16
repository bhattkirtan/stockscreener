#!/usr/bin/env python3
"""
Compare position sizing strategies: Fixed vs Compounding

Tests the same strategy parameters with different position sizing approaches:
- Fixed: Same dollar amount per trade (current default)
- Compounding: Position size scales with equity (5%, 10%, 15% of capital)

Usage:
    python3 scripts/compare-position-sizing.py \
        --data-file data/GOLD_M5_150000bars.csv \
        --st-period 2.0 --st-mult 2.0 \
        --sma-fast 20 --sma-slow 30 \
        --use-rsi false \
        --atr-tp-mult 2.0 --atr-sl-mult 4.0

Or load from optimization results:
    python3 scripts/compare-position-sizing.py \
        --data-file data/GOLD_M5_150000bars.csv \
        --load-best --date 2026-03-08
"""

import os
import sys
import argparse
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.core.strategy import GoldScalpingStrategy
from src.core.backtester import IntraCandleBacktester, BacktestConfig


def load_best_params(date: str, run_dir: Path) -> Dict[str, Any]:
    """Load best parameters from optimization results"""
    
    # Find the run directory for this date
    pattern = f"run_{date.replace('-', '')}*"
    matching_dirs = list(run_dir.glob(pattern))
    
    if not matching_dirs:
        raise ValueError(f"No optimization results found for date {date}")
    
    # Use the most recent one if multiple exist
    latest_run = max(matching_dirs, key=lambda p: p.stat().st_mtime)
    
    # Read overview.txt to get best parameters
    overview_file = latest_run / "overview.txt"
    if not overview_file.exists():
        raise ValueError(f"No overview.txt found in {latest_run}")
    
    with open(overview_file, 'r') as f:
        lines = f.readlines()
    
    # Parse the rank 1 result
    for i, line in enumerate(lines):
        if line.startswith("rank01_"):
            # Extract parameters from filename
            # Format: rank01_ST{period}_SMA{fast}-{slow}_RSI{upper}-{lower}_ATR{tp}x-{sl}x
            filename = line.split()[0]
            parts = filename.split('_')
            
            params = {}
            
            for part in parts:
                if part.startswith('ST'):
                    params['supertrend_period'] = float(part[2:])
                elif part.startswith('SMA'):
                    fast, slow = part[3:].split('-')
                    params['sma_fast_period'] = int(fast)
                    params['sma_slow_period'] = int(slow)
                elif part.startswith('RSI'):
                    upper, lower = part[3:].split('-')
                    params['use_rsi_filter'] = True
                    params['rsi_overbought'] = int(upper)
                    params['rsi_oversold'] = int(lower)
                elif part.startswith('ATR'):
                    tp, sl = part[3:].replace('x', '').split('-')
                    params['atr_tp_multiplier'] = float(tp)
                    params['atr_sl_multiplier'] = float(sl)
            
            # Check if NO-RSI in filename
            if 'NO-RSI' in filename:
                params['use_rsi_filter'] = False
            
            print(f"✅ Loaded best parameters from: {latest_run.name}")
            print(f"   File: {filename}")
            return params
    
    raise ValueError("Could not parse best parameters from overview.txt")


def run_backtest(
    data: pd.DataFrame,
    params: Dict[str, Any],
    use_compounding: bool = False,
    compounding_pct: float = 0.10,
    initial_capital: float = 10000.0
) -> Dict[str, Any]:
    """Run backtest with specified position sizing"""
    
    # Create strategy
    strategy = GoldScalpingStrategy(
        supertrend_period=params.get('supertrend_period', 2.0),
        supertrend_multiplier=params.get('supertrend_multiplier', 2.0),
        sma_fast_period=params.get('sma_fast_period', 20),
        sma_slow_period=params.get('sma_slow_period', 30),
        use_rsi_filter=params.get('use_rsi_filter', False),
        rsi_overbought=params.get('rsi_overbought', 70),
        rsi_oversold=params.get('rsi_oversold', 30),
        atr_tp_multiplier=params.get('atr_tp_multiplier', 2.0),
        atr_sl_multiplier=params.get('atr_sl_multiplier', 4.0),
    )
    
    # Generate signals
    df = strategy.generate_signals(data.copy())
    
    # Create backtester config
    config = BacktestConfig(
        initial_capital=initial_capital,
        default_position_size=1.0,
        use_compounding=use_compounding,
        compounding_pct=compounding_pct,
        spread_cost_usd=0.50,
        slippage_cost_usd=0.05,
        pip_value=1.0,
        max_positions=1,
        verbose=False
    )
    
    # Run backtest
    backtester = IntraCandleBacktester(config)
    results = backtester.run(df)
    
    return results


def format_results(results: Dict[str, Any], label: str) -> None:
    """Print formatted results"""
    
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  Total Return:     {results['total_return']:>10.2f}%")
    print(f"  Final Equity:     ${results['final_equity']:>10,.2f}")
    print(f"  Max Drawdown:     {results['max_drawdown']:>10.2f}%")
    print(f"  Sharpe Ratio:     {results['sharpe_ratio']:>10.4f}")
    print(f"  Profit Factor:    {results['profit_factor']:>10.2f}")
    print(f"  Win Rate:         {results['win_rate']:>10.2f}%")
    print(f"  Total Trades:     {results['total_trades']:>10}")
    print(f"  Avg Win:          ${results['avg_win']:>10.2f}")
    print(f"  Avg Loss:         ${results['avg_loss']:>10.2f}")
    print(f"  Risk/Reward:      {results['total_return'] / max(results['max_drawdown'], 1):>10.2f}x")


def main():
    parser = argparse.ArgumentParser(description='Compare position sizing strategies')
    
    # Data file
    parser.add_argument('--data-file', required=True, help='Path to CSV data file')
    
    # Load from optimization or manual params
    parser.add_argument('--load-best', action='store_true', help='Load best params from optimization')
    parser.add_argument('--date', help='Date of optimization run (YYYY-MM-DD)')
    
    # Manual strategy parameters
    parser.add_argument('--st-period', type=float, help='Supertrend period')
    parser.add_argument('--st-mult', type=float, help='Supertrend multiplier')
    parser.add_argument('--sma-fast', type=int, help='Fast SMA period')
    parser.add_argument('--sma-slow', type=int, help='Slow SMA period')
    parser.add_argument('--use-rsi', type=str, choices=['true', 'false'], help='Use RSI filter')
    parser.add_argument('--rsi-ob', type=int, default=70, help='RSI overbought')
    parser.add_argument('--rsi-os', type=int, default=30, help='RSI oversold')
    parser.add_argument('--atr-tp-mult', type=float, help='ATR TP multiplier')
    parser.add_argument('--atr-sl-mult', type=float, help='ATR SL multiplier')
    
    # Position sizing tests
    parser.add_argument('--compound-pcts', type=str, default='5,10,15', 
                        help='Comma-separated compounding percentages to test (default: 5,10,15)')
    parser.add_argument('--initial-capital', type=float, default=10000.0,
                        help='Initial capital (default: 10000)')
    
    args = parser.parse_args()
    
    # Load data
    print(f"📊 Loading data from {args.data_file}...")
    data = pd.read_csv(args.data_file)
    data['timestamp'] = pd.to_datetime(data['timestamp'])
    print(f"✅ Loaded {len(data):,} bars")
    print(f"   Range: {data['timestamp'].iloc[0]} to {data['timestamp'].iloc[-1]}")
    
    # Get strategy parameters
    if args.load_best:
        if not args.date:
            raise ValueError("--date required when using --load-best")
        
        run_dir = Path('data/optimization')
        params = load_best_params(args.date, run_dir)
    else:
        # Validate manual params
        required = ['st_period', 'st_mult', 'sma_fast', 'sma_slow', 
                    'use_rsi', 'atr_tp_mult', 'atr_sl_mult']
        missing = [p for p in required if getattr(args, p.replace('-', '_')) is None]
        if missing:
            raise ValueError(f"Missing required parameters: {missing}")
        
        params = {
            'supertrend_period': args.st_period,
            'supertrend_multiplier': args.st_mult,
            'sma_fast_period': args.sma_fast,
            'sma_slow_period': args.sma_slow,
            'use_rsi_filter': args.use_rsi == 'true',
            'rsi_overbought': args.rsi_ob,
            'rsi_oversold': args.rsi_os,
            'atr_tp_multiplier': args.atr_tp_mult,
            'atr_sl_multiplier': args.atr_sl_mult,
        }
    
    print(f"\n🎯 Strategy Parameters:")
    print(f"   Supertrend: {params.get('supertrend_period', 'N/A')} period")
    print(f"   SMA: {params.get('sma_fast_period', 'N/A')}-{params.get('sma_slow_period', 'N/A')}")
    print(f"   RSI Filter: {'Yes' if params.get('use_rsi_filter', False) else 'No'}")
    print(f"   ATR TP/SL: {params.get('atr_tp_multiplier', 'N/A')}x / {params.get('atr_sl_multiplier', 'N/A')}x")
    
    # Parse compounding percentages
    compound_pcts = [float(x) / 100 for x in args.compound_pcts.split(',')]
    
    print(f"\n🚀 Running position sizing comparison...")
    print(f"   Initial Capital: ${args.initial_capital:,.2f}")
    print(f"   Testing: Fixed + {len(compound_pcts)} compounding strategies")
    
    # Test 1: Fixed position sizing (baseline)
    print(f"\n⏳ Testing Fixed position sizing...")
    fixed_results = run_backtest(
        data=data,
        params=params,
        use_compounding=False,
        initial_capital=args.initial_capital
    )
    format_results(fixed_results, "Fixed Position Sizing (1.0 contract)")
    
    # Test 2-N: Compounding position sizing
    compound_results = []
    for pct in compound_pcts:
        print(f"\n⏳ Testing Compounding at {pct*100:.0f}% of equity...")
        results = run_backtest(
            data=data,
            params=params,
            use_compounding=True,
            compounding_pct=pct,
            initial_capital=args.initial_capital
        )
        format_results(results, f"Compounding ({pct*100:.0f}% of Equity)")
        compound_results.append((pct, results))
    
    # Summary comparison
    print(f"\n{'='*60}")
    print(f"  COMPARISON SUMMARY")
    print(f"{'='*60}")
    print(f"  {'Strategy':<25} {'Return':<12} {'Max DD':<12} {'Risk/Reward':<12}")
    print(f"  {'-'*60}")
    
    # Fixed
    rr_fixed = fixed_results['total_return'] / max(fixed_results['max_drawdown'], 1)
    print(f"  {'Fixed (1.0 contract)':<25} "
          f"{fixed_results['total_return']:>9.2f}%  "
          f"{fixed_results['max_drawdown']:>9.2f}%  "
          f"{rr_fixed:>9.2f}x")
    
    # Compounding
    for pct, results in compound_results:
        rr = results['total_return'] / max(results['max_drawdown'], 1)
        print(f"  {f'Compound {pct*100:.0f}% equity':<25} "
              f"{results['total_return']:>9.2f}%  "
              f"{results['max_drawdown']:>9.2f}%  "
              f"{rr:>9.2f}x")
    
    # Best performer
    print(f"\n{'='*60}")
    all_results = [('Fixed', fixed_results)] + [(f'Compound {p*100:.0f}%', r) for p, r in compound_results]
    best = max(all_results, key=lambda x: x[1]['total_return'] / max(x[1]['max_drawdown'], 1))
    print(f"  🏆 Best Risk-Adjusted: {best[0]}")
    print(f"     Return: {best[1]['total_return']:.2f}%")
    print(f"     Max DD: {best[1]['max_drawdown']:.2f}%")
    print(f"     Risk/Reward: {best[1]['total_return'] / max(best[1]['max_drawdown'], 1):.2f}x")
    print(f"{'='*60}\n")
    
    # Recommendation
    print(f"💡 RECOMMENDATION:")
    if best[0] == 'Fixed':
        print(f"   Fixed position sizing provides the best risk/reward profile.")
        print(f"   Compounding may increase volatility and drawdowns in this case.")
    else:
        pct = best[0].split()[1][:-1]  # Extract percentage
        print(f"   Compounding at {pct}% of equity improves performance.")
        print(f"   This allows profits to compound while managing risk.")
        print(f"   Monitor drawdowns carefully - compounding increases volatility.")
    
    print(f"\n✅ Comparison complete!")


if __name__ == '__main__':
    main()
