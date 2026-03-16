#!/usr/bin/env python3
"""
Check if trades are truly intraday (open and close within same day)
"""

import sys
import os
from pathlib import Path
import pandas as pd

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.strategy import SupertrendVWAPStrategy
from src.core.backtester import IntraCandleBacktester, BacktestConfig


def analyze_trade_timing(strategy_name: str, params: dict, df: pd.DataFrame):
    """Analyze if trades are intraday."""
    
    print(f"\n{'='*110}")
    print(f" INTRADAY TRADE ANALYSIS: {strategy_name}")
    print(f"{'='*110}\n")
    
    # Create strategy
    strategy = SupertrendVWAPStrategy(
        supertrend_period=params['st_period'],
        supertrend_multiplier=params['st_mult'],
        sma_fast=params['sma_fast'],
        sma_slow=params['sma_slow'],
        ema_period=params['ema'],
        bb_period=params['bb_period'],
        bb_std=params['bb_std'],
        sl_pips=params['sl_pips'],
        tp_pips=params['tp_pips'],
        pip_value=params['pip_value']
    )
    
    # Calculate indicators
    df_with_indicators = strategy.calculate_indicators(df.copy())
    if df_with_indicators.index.name != 'timestamp' and 'timestamp' in df_with_indicators.columns:
        df_with_indicators = df_with_indicators.set_index('timestamp')
    
    # Generate signals
    signals = strategy.generate_signals(df_with_indicators)
    
    # Run backtest
    config = BacktestConfig(
        initial_capital=10000.0,
        pip_value=params['pip_value'],
        default_position_size=10.0,
        max_positions=1,
        spread_cost_usd=0.02,
        slippage_cost_usd=0.005
    )
    
    backtester = IntraCandleBacktester(config)
    results = backtester.run(df_with_indicators, signals)
    
    # Analyze trades
    trades = results['all_trades']
    
    if not trades:
        print("❌ No trades found!")
        return
    
    trades_df = pd.DataFrame(trades)
    
    # Calculate timing metrics
    trades_df['entry_time'] = pd.to_datetime(trades_df['entry_time'])
    trades_df['exit_time'] = pd.to_datetime(trades_df['exit_time'])
    
    # Check if same day
    trades_df['entry_date'] = trades_df['entry_time'].dt.date
    trades_df['exit_date'] = trades_df['exit_time'].dt.date
    trades_df['same_day'] = trades_df['entry_date'] == trades_df['exit_date']
    
    # Calculate duration
    trades_df['duration_hours'] = (trades_df['exit_time'] - trades_df['entry_time']).dt.total_seconds() / 3600
    trades_df['duration_minutes'] = trades_df['duration_hours'] * 60
    
    # Statistics
    total_trades = len(trades_df)
    intraday_trades = trades_df['same_day'].sum()
    multi_day_trades = total_trades - intraday_trades
    intraday_pct = (intraday_trades / total_trades) * 100
    
    print(f"TRADE TIMING SUMMARY:")
    print(f"  Total Trades:        {total_trades}")
    print(f"  Intraday (same day): {intraday_trades} ({intraday_pct:.1f}%)")
    print(f"  Multi-day:           {multi_day_trades} ({100-intraday_pct:.1f}%)")
    
    print(f"\nDURATION STATISTICS:")
    print(f"  Avg Duration:        {trades_df['duration_hours'].mean():.1f} hours ({trades_df['duration_minutes'].mean():.0f} min)")
    print(f"  Min Duration:        {trades_df['duration_hours'].min():.1f} hours ({trades_df['duration_minutes'].min():.0f} min)")
    print(f"  Max Duration:        {trades_df['duration_hours'].max():.1f} hours ({trades_df['duration_minutes'].max():.0f} min)")
    print(f"  Median Duration:     {trades_df['duration_hours'].median():.1f} hours ({trades_df['duration_minutes'].median():.0f} min)")
    
    # Duration distribution
    bins = [0, 4, 8, 12, 24, 48, 100]
    labels = ['0-4h', '4-8h', '8-12h', '12-24h', '24-48h', '48h+']
    trades_df['duration_bin'] = pd.cut(trades_df['duration_hours'], bins=bins, labels=labels)
    
    print(f"\nDURATION DISTRIBUTION:")
    dist = trades_df['duration_bin'].value_counts().sort_index()
    for bin_label, count in dist.items():
        pct = (count / total_trades) * 100
        print(f"  {bin_label:8}: {count:3} trades ({pct:5.1f}%)")
    
    # Show multi-day trades
    if multi_day_trades > 0:
        print(f"\n⚠️  MULTI-DAY TRADES (NOT INTRADAY):")
        multi_day_df = trades_df[~trades_df['same_day']].head(10)
        print(f"{'Entry Date':<12} {'Entry Time':<10} {'Exit Date':<12} {'Exit Time':<10} {'Duration':<12} {'P&L':<10}")
        print("─" * 80)
        
        for _, row in multi_day_df.iterrows():
            entry_date = row['entry_time'].strftime('%Y-%m-%d')
            entry_time = row['entry_time'].strftime('%H:%M')
            exit_date = row['exit_time'].strftime('%Y-%m-%d')
            exit_time = row['exit_time'].strftime('%H:%M')
            duration = f"{row['duration_hours']:.1f}h"
            pnl = f"${row['pnl']:.2f}"
            
            print(f"{entry_date:<12} {entry_time:<10} {exit_date:<12} {exit_time:<10} {duration:<12} {pnl:<10}")
        
        if multi_day_trades > 10:
            print(f"... ({multi_day_trades - 10} more multi-day trades)")
    
    # Verdict
    print(f"\n{'='*110}")
    if intraday_pct >= 95:
        print("✅ INTRADAY STRATEGY: 95%+ trades close same day")
    elif intraday_pct >= 80:
        print("⚠️  MOSTLY INTRADAY: 80-95% trades close same day, some overnight holds")
    elif intraday_pct >= 50:
        print("⚠️  HYBRID STRATEGY: 50-80% intraday, significant overnight positions")
    else:
        print("❌ NOT INTRADAY: Less than 50% trades close same day - this is swing trading")
    
    print(f"{'='*110}\n")


def main():
    """Main analysis routine."""
    
    # Load data
    data_file = "data/GOLD_M5_10000bars.csv"
    
    # Use latest optimization run
    from pathlib import Path
    import glob
    latest_dir = Path('data/optimization/latest')
    csv_files = list(latest_dir.glob('GOLD_M5_all_strategies_*.csv'))
    if not csv_files:
        print("❌ No results found in latest/")
        return
    results_file = str(csv_files[0])
    
    print("="*110)
    print(" INTRADAY TRADE VERIFICATION - TOP 3 STRATEGIES".center(110))
    print("="*110)
    print("\nChecking if trades truly close within the same trading day...")
    print("="*110)
    
    # Load market data
    df = pd.read_csv(data_file)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp')
    print(f"\n✓ Loaded {len(df)} bars from {data_file}\n")
    
    # Load optimization results
    results_df = pd.read_csv(results_file)
    
    # Analyze top 3 strategies
    for rank_idx in range(3):
        row = results_df.iloc[rank_idx]
        
        # Parse parameters (ATR-based)
        tp_sl_str = row['tp_sl']
        parts = tp_sl_str.split()[1].split(':')
        atr_sl_mult = float(parts[0].replace('x', ''))
        atr_tp_mult = float(parts[1].replace('x', ''))
        
        params = {
            'st_period': int(row['st_period']),
            'st_mult': float(row['st_mult']),
            'sma_fast': int(row['sma_fast']),
            'sma_slow': int(row['sma_slow']),
            'ema': int(row['ema']),
            'bb_period': int(row['bb_period']),
            'bb_std': float(row['bb_std']),
            'pip_value': float(row['pip_value']),
            'sl_pips': None,
            'tp_pips': None,
            'atr_sl_mult': atr_sl_mult,
            'atr_tp_mult': atr_tp_mult
        }
        
        # Analyze
        analyze_trade_timing(row['strategy_name'], params, df)


if __name__ == "__main__":
    main()
