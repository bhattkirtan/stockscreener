"""
Backtest Validation Script

Runs backtests with skill-based architecture and compares results
with the original monolithic bot to validate correctness.

Usage:
    python3 validate_backtest.py --data data/EURUSD_M5_2022.csv --config config/trading_config.yaml

Features:
- Load historical data
- Run backtest with skill-based orchestrator
- Compare metrics with baseline
- Generate comparison report
"""
import sys
import os
import argparse
import pandas as pd
from datetime import datetime
from typing import Dict, List

sys.path.insert(0, os.path.dirname(__file__))

from skills.backtesting.backtesting_skill import BacktestingSkill


def load_data(file_path: str) -> pd.DataFrame:
    """
    Load historical candle data from CSV
    
    Expected format:
    timestamp,open,high,low,close,volume
    """
    print(f"📊 Loading data from {file_path}...")
    
    df = pd.read_csv(file_path)
    
    # Convert timestamp column
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    print(f"✅ Loaded {len(df)} candles")
    print(f"   Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    
    return df


def run_backtest(data: pd.DataFrame, config: Dict) -> Dict:
    """Run backtest with skills"""
    print("\n🔄 Running backtest with skill-based architecture...")
    
    # Initialize backtesting skill
    backtest_config = {
        'start_date': data['timestamp'].min().isoformat(),
        'end_date': data['timestamp'].max().isoformat(),
        'initial_capital': config.get('initial_capital', 10000),
        'commission_per_trade': config.get('commission_per_trade', 2.0),
        'intra_candle_simulation': True
    }
    
    backtesting = BacktestingSkill(backtest_config)
    
    # Run backtest
    results = backtesting.run_backtest(data)
    
    print("✅ Backtest complete")
    
    return results


def print_results(results: Dict):
    """Print backtest results"""
    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)
    
    print(f"\n📈 Performance Metrics:")
    print(f"   Total Trades: {results.get('total_trades', 0)}")
    print(f"   Wins: {results.get('wins', 0)}")
    print(f"   Losses: {results.get('losses', 0)}")
    print(f"   Win Rate: {results.get('win_rate', 0):.2%}")
    print(f"   Total P&L: ${results.get('total_pnl', 0):.2f}")
    print(f"   Average Trade: ${results.get('avg_trade', 0):.2f}")
    
    if 'sharpe_ratio' in results:
        print(f"   Sharpe Ratio: {results.get('sharpe_ratio', 0):.2f}")
    
    if 'max_drawdown' in results:
        print(f"   Max Drawdown: ${results.get('max_drawdown', 0):.2f}")
    
    if 'best_trade' in results:
        print(f"   Best Trade: ${results.get('best_trade', 0):.2f}")
    
    if 'worst_trade' in results:
        print(f"   Worst Trade: ${results.get('worst_trade', 0):.2f}")


def compare_with_baseline(results: Dict, baseline: Dict):
    """Compare results with baseline (monolithic bot)"""
    print("\n" + "=" * 60)
    print("COMPARISON WITH BASELINE")
    print("=" * 60)
    
    metrics = [
        ('total_trades', 'Total Trades'),
        ('win_rate', 'Win Rate'),
        ('total_pnl', 'Total P&L'),
        ('sharpe_ratio', 'Sharpe Ratio')
    ]
    
    print(f"\n{'Metric':<20} {'Baseline':<15} {'Current':<15} {'Difference':<15}")
    print("-" * 65)
    
    for key, label in metrics:
        baseline_val = baseline.get(key, 0)
        current_val = results.get(key, 0)
        
        if key == 'win_rate':
            diff = (current_val - baseline_val) * 100  # Percentage points
            print(f"{label:<20} {baseline_val:.2%}{'  ':<8} {current_val:.2%}{'  ':<8} {diff:+.2f}pp")
        else:
            diff = current_val - baseline_val
            diff_pct = (diff / baseline_val * 100) if baseline_val != 0 else 0
            print(f"{label:<20} {baseline_val:<15.2f} {current_val:<15.2f} {diff:+.2f} ({diff_pct:+.1f}%)")
    
    # Verdict
    print("\n" + "=" * 60)
    
    pnl_diff = results.get('total_pnl', 0) - baseline.get('total_pnl', 0)
    pnl_diff_pct = abs(pnl_diff) / baseline.get('total_pnl', 1) * 100
    
    if pnl_diff_pct <= 1.0:
        print("✅ VALIDATION PASSED: Results within 1% of baseline")
    elif pnl_diff_pct <= 5.0:
        print("⚠️  VALIDATION WARNING: Results differ by 1-5% from baseline")
    else:
        print("❌ VALIDATION FAILED: Results differ by >5% from baseline")
    
    print("=" * 60)


def load_baseline_results(baseline_file: str) -> Dict:
    """Load baseline results from JSON"""
    import json
    
    if not os.path.exists(baseline_file):
        print(f"⚠️  No baseline file found: {baseline_file}")
        return {}
    
    with open(baseline_file, 'r') as f:
        baseline = json.load(f)
    
    print(f"✅ Loaded baseline results from {baseline_file}")
    
    return baseline


def save_results(results: Dict, output_file: str):
    """Save results to JSON"""
    import json
    
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"\n💾 Results saved to {output_file}")


def main():
    parser = argparse.ArgumentParser(description='Validate backtest results')
    parser.add_argument('--data', required=True, help='Path to historical data CSV')
    parser.add_argument('--config', default='config/trading_config.yaml', help='Path to config file')
    parser.add_argument('--baseline', default='results/baseline_results.json', help='Path to baseline results')
    parser.add_argument('--output', default='results/validation_results.json', help='Path to save results')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("BACKTEST VALIDATION")
    print("=" * 60)
    
    # Load config
    import yaml
    with open(args.config, 'r') as f:
        config = yaml.safe_load(f)
    
    # Load data
    data = load_data(args.data)
    
    # Run backtest
    results = run_backtest(data, config)
    
    # Print results
    print_results(results)
    
    # Load and compare with baseline
    baseline = load_baseline_results(args.baseline)
    if baseline:
        compare_with_baseline(results, baseline)
    
    # Save results
    save_results(results, args.output)
    
    print("\n✅ Validation complete!")


if __name__ == '__main__':
    main()
