#!/usr/bin/env python3
"""
Validate top strategies by running them multiple times to ensure consistency.
This proves that the backtest results are reproducible and reliable.
"""

import sys
import os
from pathlib import Path
from typing import Dict, List, Tuple
import pandas as pd
import numpy as np
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.strategy import SupertrendVWAPStrategy
from src.core.backtester import IntraCandleBacktester, BacktestConfig


def load_data(data_file: str) -> pd.DataFrame:
    """Load market data."""
    df = pd.read_csv(data_file)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp')
    print(f"✓ Loaded {len(df)} bars from {data_file}")
    return df


def parse_strategy_params(strategy_name: str, row: pd.Series) -> Dict:
    """Parse strategy parameters from CSV row."""
    tp_sl_str = row['tp_sl']
    
    # Parse tp_sl string (e.g., "ATR 2.0x:4.0x" or "Fixed 8:10")
    tp_sl_strategy = 'atr' if 'ATR' in tp_sl_str else 'fixed'
    
    if tp_sl_strategy == 'atr':
        # Parse "ATR 2.0x:4.0x" -> sl_mult=2.0, tp_mult=4.0
        parts = tp_sl_str.split()[1].split(':')
        atr_sl_mult = float(parts[0].replace('x', ''))
        atr_tp_mult = float(parts[1].replace('x', ''))
        sl_pips = None
        tp_pips = None
    else:
        # Parse "Fixed 8:10" -> sl_pips=8, tp_pips=10
        parts = tp_sl_str.split()[1].split(':')
        sl_pips = float(parts[0])
        tp_pips = float(parts[1])
        atr_sl_mult = None
        atr_tp_mult = None
    
    return {
        'st_period': int(row['st_period']),
        'st_mult': float(row['st_mult']),
        'sma_fast': int(row['sma_fast']),
        'sma_slow': int(row['sma_slow']),
        'ema': int(row['ema']),
        'bb_period': int(row['bb_period']),
        'bb_std': float(row['bb_std']),
        'pip_value': float(row['pip_value']),
        'tp_sl_strategy': tp_sl_strategy,
        'sl_pips': sl_pips,
        'tp_pips': tp_pips,
        'atr_sl_mult': atr_sl_mult,
        'atr_tp_mult': atr_tp_mult
    }


def analyze_drawdowns(equity_curve: pd.DataFrame, initial_capital: float = 10000.0) -> Dict:
    """Analyze drawdown patterns from equity curve."""
    if equity_curve.empty:
        return {}
    
    equity = equity_curve['total_equity'].values
    timestamps = equity_curve['timestamp'].values
    
    # Calculate running maximum and drawdown
    running_max = np.maximum.accumulate(equity)
    drawdown_dollars = running_max - equity
    drawdown_pct = (drawdown_dollars / running_max) * 100
    
    # Find maximum drawdown
    max_dd_idx = np.argmax(drawdown_dollars)
    max_dd_dollars = drawdown_dollars[max_dd_idx]
    max_dd_pct = drawdown_pct[max_dd_idx]
    max_dd_time = timestamps[max_dd_idx]
    
    # Find when the drawdown started (peak before max DD)
    peak_idx = max_dd_idx
    for i in range(max_dd_idx, -1, -1):
        if equity[i] == running_max[max_dd_idx]:
            peak_idx = i
            break
    peak_time = timestamps[peak_idx]
    
    # Find recovery time (when equity returned to peak)
    recovery_bars = None
    recovery_time = None
    for i in range(max_dd_idx + 1, len(equity)):
        if equity[i] >= running_max[max_dd_idx]:
            recovery_bars = i - max_dd_idx
            recovery_time = timestamps[i]
            break
    
    # Count 5%+ drawdown periods
    dd_5pct_count = 0
    in_drawdown = False
    for dd_pct_val in drawdown_pct:
        if dd_pct_val >= 5.0 and not in_drawdown:
            dd_5pct_count += 1
            in_drawdown = True
        elif dd_pct_val < 1.0:  # Reset when recovered to < 1% DD
            in_drawdown = False
    
    return {
        'max_dd_dollars': max_dd_dollars,
        'max_dd_pct': max_dd_pct,
        'max_dd_time': max_dd_time,
        'peak_time': peak_time,
        'recovery_bars': recovery_bars,
        'recovery_time': recovery_time,
        'dd_5pct_count': dd_5pct_count,
        'total_bars': len(equity)
    }


def run_single_backtest(df: pd.DataFrame, params: Dict, run_num: int, analyze_dd: bool = False) -> Dict:
    """Run a single backtest with given parameters."""
    # Create strategy with default sl_pips and tp_pips
    # (will be overridden if using ATR strategy)
    sl_pips_value = params['sl_pips'] if params['sl_pips'] is not None else 20.0
    tp_pips_value = params['tp_pips'] if params['tp_pips'] is not None else 40.0
    
    strategy = SupertrendVWAPStrategy(
        supertrend_period=params['st_period'],
        supertrend_multiplier=params['st_mult'],
        sma_fast=params['sma_fast'],
        sma_slow=params['sma_slow'],
        ema_period=params['ema'],
        bb_period=params['bb_period'],
        bb_std=params['bb_std'],
        sl_pips=sl_pips_value,
        tp_pips=tp_pips_value,
        pip_value=params['pip_value']
    )
    
    # Calculate indicators
    df_with_indicators = strategy.calculate_indicators(df.copy())
    
    # Ensure timestamp is in index
    if df_with_indicators.index.name != 'timestamp' and 'timestamp' in df_with_indicators.columns:
        df_with_indicators = df_with_indicators.set_index('timestamp')
    
    # Generate signals
    signals = strategy.generate_signals(df_with_indicators)
    
    # Handle ATR-based TP/SL if needed
    if params['tp_sl_strategy'] == 'atr':
        pip_value = params['pip_value']
        
        for i in range(len(signals)):
            signal_val = float(signals.iloc[i]['signal'])
            
            if signal_val != 0:
                close = float(df_with_indicators.iloc[i]['close'])
                atr_val = df_with_indicators.iloc[i].get('atr', 20.0)
                if hasattr(atr_val, 'item'):
                    atr = float(atr_val)
                else:
                    atr = atr_val
                
                sl_distance = atr * params['atr_sl_mult'] * pip_value
                tp_distance = atr * params['atr_tp_mult'] * pip_value
                
                if signal_val == 1:  # BUY
                    signals.iloc[i, signals.columns.get_loc('stop_loss')] = close - sl_distance
                    signals.iloc[i, signals.columns.get_loc('take_profit')] = close + tp_distance
                elif signal_val == -1:  # SELL
                    signals.iloc[i, signals.columns.get_loc('stop_loss')] = close + sl_distance
                    signals.iloc[i, signals.columns.get_loc('take_profit')] = close - tp_distance
    
    # Create config
    config = BacktestConfig(
        initial_capital=10000.0,
        pip_value=params['pip_value'],
        default_position_size=10.0,
        max_positions=1
    )
    
    # Run backtest
    backtester = IntraCandleBacktester(config)
    results = backtester.run(df_with_indicators, signals)
    
    result_dict = {
        'run': run_num,
        'total_pnl': results['total_pnl'],
        'return_pct': results['return_pct'],
        'total_trades': results['total_trades'],
        'win_rate': results['win_rate'],
        'sharpe_ratio': results['sharpe_ratio'],
        'max_drawdown_pct': results['max_drawdown_pct'],
        'max_drawdown_dollars': results['max_drawdown'],
        'profit_factor': results['profit_factor'],
        'avg_win': results['avg_win'],
        'avg_loss': results['avg_loss']
    }
    
    # Add drawdown analysis if requested
    if analyze_dd:
        dd_analysis = analyze_drawdowns(results['equity_curve'], config.initial_capital)
        result_dict.update(dd_analysis)
    
    return result_dict


def run_multiple_validations(df: pd.DataFrame, params: Dict, strategy_name: str, num_runs: int = 5) -> Tuple[pd.DataFrame, Dict]:
    """Run strategy multiple times and collect results."""
    print(f"\n{'='*80}")
    print(f"Validating: {strategy_name}")
    print(f"{'='*80}")
    print(f"Parameters:")
    for k, v in params.items():
        print(f"  {k}: {v}")
    
    results = []
    dd_analysis = None
    
    for i in range(1, num_runs + 1):
        print(f"\nRun {i}/{num_runs}...", end=" ")
        # Only analyze drawdowns on first run for efficiency
        analyze_dd = (i == 1)
        result = run_single_backtest(df, params, i, analyze_dd=analyze_dd)
        
        # Store drawdown analysis from first run
        if i == 1 and 'max_dd_time' in result:
            dd_analysis = {k: v for k, v in result.items() if k in [
                'max_dd_dollars', 'max_dd_pct', 'max_dd_time', 'peak_time',
                'recovery_bars', 'recovery_time', 'dd_5pct_count', 'total_bars'
            ]}
        
        results.append(result)
        print(f"✓ P&L: ${result['total_pnl']:.2f} | Trades: {result['total_trades']} | DD: {result['max_drawdown_pct']:.2f}%")
    
    results_df = pd.DataFrame(results)
    
    # Calculate statistics
    print(f"\n{'─'*80}")
    print("VALIDATION RESULTS:")
    print(f"{'─'*80}")
    
    for col in ['total_pnl', 'return_pct', 'total_trades', 'win_rate', 'sharpe_ratio', 'max_drawdown_pct']:
        if col not in results_df.columns:
            continue
        mean = results_df[col].mean()
        std = results_df[col].std()
        min_val = results_df[col].min()
        max_val = results_df[col].max()
        
        if col in ['total_pnl', 'return_pct']:
            print(f"{col:20s}: Mean: ${mean:>10.2f}  Std: ${std:>8.2f}  Range: [${min_val:.2f}, ${max_val:.2f}]")
        elif col in ['win_rate', 'sharpe_ratio', 'max_drawdown_pct']:
            print(f"{col:20s}: Mean: {mean:>10.4f}  Std: {std:>8.4f}  Range: [{min_val:.4f}, {max_val:.4f}]")
        else:
            print(f"{col:20s}: Mean: {mean:>10.0f}  Std: {std:>8.2f}  Range: [{min_val:.0f}, {max_val:.0f}]")
    
    # Display drawdown analysis
    if dd_analysis:
        print(f"\n{'─'*80}")
        print("DRAWDOWN ANALYSIS:")
        print(f"{'─'*80}")
        print(f"Maximum Drawdown:        {dd_analysis['max_dd_pct']:.2f}% (${dd_analysis['max_dd_dollars']:.2f})")
        print(f"Peak Time:               {pd.to_datetime(dd_analysis['peak_time']).strftime('%Y-%m-%d %H:%M')}")
        print(f"Max DD Time:             {pd.to_datetime(dd_analysis['max_dd_time']).strftime('%Y-%m-%d %H:%M')}")
        
        if dd_analysis['recovery_time']:
            recovery_hours = dd_analysis['recovery_bars'] * 5 / 60  # M5 bars
            print(f"Recovery Time:           {dd_analysis['recovery_bars']} bars ({recovery_hours:.1f} hours)")
            print(f"Recovery Date:           {pd.to_datetime(dd_analysis['recovery_time']).strftime('%Y-%m-%d %H:%M')}")
        else:
            print(f"Recovery Time:           NOT RECOVERED (still in drawdown at end)")
        
        print(f"5%+ Drawdown Events:     {dd_analysis['dd_5pct_count']} times")
        print(f"Total Bars Analyzed:     {dd_analysis['total_bars']}")
    
    # Check consistency
    pnl_cv = (results_df['total_pnl'].std() / results_df['total_pnl'].mean()) * 100 if results_df['total_pnl'].mean() != 0 else 0
    trades_cv = (results_df['total_trades'].std() / results_df['total_trades'].mean()) * 100 if results_df['total_trades'].mean() != 0 else 0
    
    print(f"\n{'─'*80}")
    print("CONSISTENCY CHECK:")
    print(f"{'─'*80}")
    print(f"P&L Coefficient of Variation: {pnl_cv:.2f}%")
    print(f"Trades Coefficient of Variation: {trades_cv:.2f}%")
    
    if pnl_cv < 0.01 and trades_cv < 0.01:
        print("✓ EXCELLENT: Results are perfectly consistent (CV < 0.01%)")
    elif pnl_cv < 1.0 and trades_cv < 1.0:
        print("✓ GOOD: Results are highly consistent (CV < 1%)")
    else:
        print("⚠ WARNING: Results show variation (CV >= 1%)")
    
    return results_df, dd_analysis


def main():
    """Main validation routine."""
    # Configuration
    data_file = "data/GOLD_M5_5000bars.csv"
    
    # Use latest optimization run
    from pathlib import Path
    import glob
    latest_dir = Path('data/optimization/latest')
    csv_files = list(latest_dir.glob('GOLD_M5_all_strategies_*.csv'))
    if not csv_files:
        print("❌ No results found in latest/")
        return
    results_file = str(csv_files[0])
    num_runs = 5  # Run each strategy 5 times
    
    # Load optimization results
    print("="*80)
    print(" TOP 5 STRATEGY VALIDATION")
    print("="*80)
    print(f"Data: {data_file}")
    print(f"Results: {results_file}")
    print(f"Validation runs per strategy: {num_runs}")
    print("="*80)
    
    results_df = pd.read_csv(results_file)
    top5 = results_df.head(5)
    
    # Load market data
    df = load_data(data_file)
    
    # Summary of top 5
    print("\n" + "="*80)
    print(" TOP 5 STRATEGIES OVERVIEW")
    print("="*80)
    print(f"{'Rank':<8} {'Strategy Name':<45} {'P&L':>10} {'Trades':>8} {'Win%':>8} {'Sharpe':>8}")
    print("─"*80)
    for idx, row in top5.iterrows():
        print(f"{row['strategy_name'][:6]:<8} {row['strategy_name'][7:52]:<45} ${row['total_pnl']:>9.2f} {int(row['total_trades']):>8} {row['win_rate']:>7.2f}% {row['sharpe_ratio']:>8.3f}")
    
    # Validate each strategy
    all_validation_results = {}
    all_drawdown_analysis = {}
    
    for idx, row in top5.iterrows():
        strategy_name = row['strategy_name']
        params = parse_strategy_params(strategy_name, row)
        
        validation_results, dd_analysis = run_multiple_validations(df, params, strategy_name, num_runs)
        all_validation_results[strategy_name] = validation_results
        if dd_analysis:
            all_drawdown_analysis[strategy_name] = dd_analysis
    
    # Final summary
    print("\n" + "="*80)
    print(" FINAL VALIDATION SUMMARY")
    print("="*80)
    print(f"{'Strategy':<50} {'Mean P&L':>12} {'Max DD':>10} {'Consistent':>12}")
    print("─"*80)
    
    for strategy_name, results in all_validation_results.items():
        mean_pnl = results['total_pnl'].mean()
        max_dd_pct = results['max_drawdown_pct'].mean()
        std_pnl = results['total_pnl'].std()
        cv = (std_pnl / mean_pnl * 100) if mean_pnl != 0 else 0
        consistent = "✓ Yes" if cv < 0.01 else "⚠ No"
        print(f"{strategy_name[:50]:<50} ${mean_pnl:>11.2f} {max_dd_pct:>9.2f}% {consistent:>12}")
    
    # Drawdown summary
    if all_drawdown_analysis:
        print("\n" + "="*80)
        print(" DRAWDOWN TIMELINE SUMMARY")
        print("="*80)
        print(f"{'Strategy':<15} {'Max DD':>10} {'DD $':>10} {'Recovery':>12} {'5%+ Events':>12}")
        print("─"*80)
        
        for strategy_name, dd in all_drawdown_analysis.items():
            short_name = strategy_name.split('_')[0]  # e.g., "rank01"
            recovery_str = f"{dd['recovery_bars']} bars" if dd['recovery_time'] else "Not Recov."
            print(f"{short_name:<15} {dd['max_dd_pct']:>9.2f}% ${dd['max_dd_dollars']:>9.2f} {recovery_str:>12} {dd['dd_5pct_count']:>12}")
    
    print("\n" + "="*80)
    print(" VALIDATION COMPLETE")
    print("="*80)
    print("All strategies have been validated across multiple runs.")
    print("Consistent results (CV < 0.01%) indicate deterministic backtesting.")
    print("Drawdown analysis shows timing and recovery patterns.")
    print("="*80)


if __name__ == "__main__":
    main()
