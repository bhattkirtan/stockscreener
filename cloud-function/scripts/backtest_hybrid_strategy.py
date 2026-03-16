"""Backtest hybrid zone-supertrend strategy on historical data.

This script:
1. Loads M5 data
2. Runs hybrid strategy with zone filter ENABLED
3. Runs hybrid strategy with zone filter DISABLED (pure SuperTrend baseline)
4. Compares both approaches side-by-side
5. Generates performance report
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from src.strategies.hybrid_zone_supertrend_strategy import HybridZoneSuperTrendStrategy


def load_data(csv_path: str) -> pd.DataFrame:
    """Load M5 OHLC data.
    
    Args:
        csv_path: Path to M5 CSV file
        
    Returns:
        M5 dataframe
    """
    print(f"📊 Loading data from {csv_path}...")
    
    df = pd.read_csv(csv_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    print(f"   ✓ Loaded {len(df)} M5 bars")
    print(f"   ✓ Range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    
    return df


def run_hybrid_backtest(df: pd.DataFrame, enable_zone_filter: bool,
                        initial_capital: float = 10000.0,
                        spread_pips: float = 0.3) -> dict:
    """Run hybrid strategy backtest.
    
    Args:
        df: M5 OHLC dataframe
        enable_zone_filter: Whether to enable zone filtering
        initial_capital: Starting capital
        spread_pips: Spread in pips
        
    Returns:
        Backtest results dictionary
    """
    mode_name = "HYBRID (Zone Filter ON)" if enable_zone_filter else "BASELINE (Pure SuperTrend)"
    
    print(f"\n🎯 Initializing {mode_name}...")
    
    # Initialize strategy with tested parameters
    strategy = HybridZoneSuperTrendStrategy(
        # SuperTrend parameters (proven)
        supertrend_period=10,
        supertrend_atr_multiplier=3.0,
        atr_sl_multiplier=0.7,  # Proven winner
        atr_tp_multiplier=2.5,  # Proven winner
        
        # Zone filter parameters
        enable_zone_filter=enable_zone_filter,
        zone_block_distance=1.0,
        enable_zone_stops=False,  # Keep ATR stops
        
        symbol='GOLD'
    )
    
    print(f"   ✓ Strategy initialized")
    print(f"   ✓ Zone filter: {'ENABLED' if enable_zone_filter else 'DISABLED'}")
    print(f"   ✓ ATR SL: {0.7}×")
    print(f"   ✓ ATR TP: {2.5}×")
    
    print(f"\n🚀 Running backtest...")
    print(f"   Capital: ${initial_capital:,.2f}")
    print(f"   Spread: {spread_pips} pips")
    
    # Backtest state
    equity = initial_capital
    trades = []
    equity_curve = [initial_capital]
    timestamps = [df['timestamp'].iloc[0]]
    
    # Minimum bars for indicator calculation
    min_bars = 2000
    
    print(f"   Warming up ({min_bars} bars)...")
    
    # Simple backtest loop
    for i in range(min_bars, len(df)):
        current_bar = df.iloc[i]
        current_price = current_bar['close']
        current_time = current_bar['timestamp']
        
        # Call strategy's _on_data method
        signal = strategy._on_data(df, i)
        
        if signal:
            # Calculate filled price with spread
            if signal['direction'] == 'long':
                filled_price = signal['entry_price'] + spread_pips
            else:
                filled_price = signal['entry_price'] - spread_pips
            
            stop_loss = signal['stop_loss']
            take_profit = signal['take_profit']
            
            # Simulate forward to find exit
            exit_price = None
            exit_reason = None
            exit_time = None
            mae = 0.0
            mfe = 0.0
            
            # Look ahead for exit (max 200 bars)
            for j in range(i+1, min(i+201, len(df))):
                bar = df.iloc[j]
                
                if signal['direction'] == 'long':
                    # Track MAE/MFE
                    mae = min(mae, bar['low'] - filled_price)
                    mfe = max(mfe, bar['high'] - filled_price)
                    
                    # Check stop
                    if bar['low'] <= stop_loss:
                        exit_price = stop_loss
                        exit_reason = 'stop_loss'
                        exit_time = bar['timestamp']
                        break
                    
                    # Check TP
                    if bar['high'] >= take_profit:
                        exit_price = take_profit
                        exit_reason = 'take_profit'
                        exit_time = bar['timestamp']
                        break
                
                else:  # short
                    # Track MAE/MFE
                    mae = max(mae, filled_price - bar['high'])
                    mfe = min(mfe, filled_price - bar['low'])
                    
                    # Check stop
                    if bar['high'] >= stop_loss:
                        exit_price = stop_loss
                        exit_reason = 'stop_loss'
                        exit_time = bar['timestamp']
                        break
                    
                    # Check TP
                    if bar['low'] <= take_profit:
                        exit_price = take_profit
                        exit_reason = 'take_profit'
                        exit_time = bar['timestamp']
                        break
            
            # If no exit found, skip trade
            if exit_price is None:
                continue
            
            # Calculate P&L (simplified position sizing)
            risk_amount = equity * 0.01  # 1% risk
            stop_distance = abs(filled_price - stop_loss)
            position_size = risk_amount / stop_distance if stop_distance > 0 else 0
            
            if signal['direction'] == 'long':
                pnl = (exit_price - filled_price) * position_size
            else:
                pnl = (filled_price - exit_price) * position_size
            
            # Update equity
            equity += pnl
            
            # Record trade
            trades.append({
                'entry_time': current_time,
                'exit_time': exit_time,
                'direction': signal['direction'],
                'entry_price': filled_price,
                'exit_price': exit_price,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'position_size': position_size,
                'pnl': pnl,
                'pnl_pct': pnl / (equity - pnl) * 100,
                'exit_reason': exit_reason,
                'mae': mae,
                'mfe': mfe
            })
            
            # Print progress
            if len(trades) % 10 == 0:
                print(f"\r   Progress: {i}/{len(df)} bars | Trades: {len(trades)} | "
                      f"Equity: ${equity:,.2f} ({(equity/initial_capital - 1)*100:+.1f}%)", end='')
        
        # Record equity curve every 100 bars
        if i % 100 == 0:
            equity_curve.append(equity)
            timestamps.append(current_time)
    
    print(f"\n   ✓ Backtest complete!")
    
    return {
        'trades': trades,
        'equity_curve': equity_curve,
        'timestamps': timestamps,
        'initial_capital': initial_capital,
        'final_equity': equity,
        'mode': mode_name,
        'zone_filter_enabled': enable_zone_filter
    }


def calculate_metrics(results: dict) -> dict:
    """Calculate performance metrics.
    
    Args:
        results: Backtest results
        
    Returns:
        Dictionary of metrics
    """
    trades_df = pd.DataFrame(results['trades'])
    
    if len(trades_df) == 0:
        return {
            'error': 'No trades executed',
            'mode': results['mode']
        }
    
    # Basic metrics
    total_trades = len(trades_df)
    winning_trades = len(trades_df[trades_df['pnl'] > 0])
    losing_trades = len(trades_df[trades_df['pnl'] < 0])
    
    win_rate = winning_trades / total_trades * 100 if total_trades > 0 else 0
    
    total_pnl = trades_df['pnl'].sum()
    avg_win = trades_df[trades_df['pnl'] > 0]['pnl'].mean() if winning_trades > 0 else 0
    avg_loss = abs(trades_df[trades_df['pnl'] < 0]['pnl'].mean()) if losing_trades > 0 else 0
    
    avg_win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0
    
    # Returns
    initial_capital = results['initial_capital']
    final_equity = results['final_equity']
    total_return_pct = (final_equity / initial_capital - 1) * 100
    
    # Drawdown
    equity_curve = np.array(results['equity_curve'])
    running_max = np.maximum.accumulate(equity_curve)
    drawdowns = (equity_curve - running_max) / running_max * 100
    max_drawdown = abs(drawdowns.min())
    
    # Profit factor
    gross_profit = trades_df[trades_df['pnl'] > 0]['pnl'].sum()
    gross_loss = abs(trades_df[trades_df['pnl'] < 0]['pnl'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
    
    # Expectancy
    expectancy = trades_df['pnl'].mean()
    
    # Sharpe ratio (simplified)
    returns = trades_df['pnl_pct']
    sharpe_ratio = returns.mean() / returns.std() if returns.std() > 0 else 0
    
    # MAE/MFE
    avg_mae = abs(trades_df['mae'].mean())
    avg_mfe = abs(trades_df['mfe'].mean())
    
    # Winning/losing streaks
    trades_df['win'] = (trades_df['pnl'] > 0).astype(int)
    trades_df['streak'] = (trades_df['win'] != trades_df['win'].shift()).cumsum()
    
    win_streaks = trades_df[trades_df['win'] == 1].groupby('streak').size()
    loss_streaks = trades_df[trades_df['win'] == 0].groupby('streak').size()
    
    max_win_streak = win_streaks.max() if len(win_streaks) > 0 else 0
    max_loss_streak = loss_streaks.max() if len(loss_streaks) > 0 else 0
    
    return {
        'mode': results['mode'],
        'zone_filter_enabled': results['zone_filter_enabled'],
        'total_trades': total_trades,
        'winning_trades': winning_trades,
        'losing_trades': losing_trades,
        'win_rate': win_rate,
        'total_return_pct': total_return_pct,
        'total_pnl': total_pnl,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'avg_win_loss_ratio': avg_win_loss_ratio,
        'max_drawdown': max_drawdown,
        'profit_factor': profit_factor,
        'expectancy': expectancy,
        'sharpe_ratio': sharpe_ratio,
        'avg_mae': avg_mae,
        'avg_mfe': avg_mfe,
        'max_win_streak': max_win_streak,
        'max_loss_streak': max_loss_streak,
        'initial_capital': initial_capital,
        'final_equity': final_equity
    }


def print_comparison(baseline_metrics: dict, hybrid_metrics: dict):
    """Print side-by-side comparison.
    
    Args:
        baseline_metrics: Pure SuperTrend metrics
        hybrid_metrics: Hybrid with zone filter metrics
    """
    print("\n" + "=" * 90)
    print("HYBRID STRATEGY COMPARISON")
    print("=" * 90)
    
    if 'error' in baseline_metrics or 'error' in hybrid_metrics:
        print("\n❌ Error in one or both backtests")
        if 'error' in baseline_metrics:
            print(f"   Baseline: {baseline_metrics['error']}")
        if 'error' in hybrid_metrics:
            print(f"   Hybrid: {hybrid_metrics['error']}")
        return
    
    print(f"\n{'Metric':<30} {'Baseline':<20} {'Hybrid':<20} {'Change':<15}")
    print("-" * 90)
    
    # Trade statistics
    print(f"{'Total Trades':<30} {baseline_metrics['total_trades']:<20} "
          f"{hybrid_metrics['total_trades']:<20} "
          f"{hybrid_metrics['total_trades'] - baseline_metrics['total_trades']:+d}")
    
    print(f"{'Win Rate':<30} {baseline_metrics['win_rate']:<20.2f}% "
          f"{hybrid_metrics['win_rate']:<20.2f}% "
          f"{hybrid_metrics['win_rate'] - baseline_metrics['win_rate']:+.2f}%")
    
    # Performance
    print(f"\n{'PERFORMANCE':<30}")
    print("-" * 90)
    
    print(f"{'Total Return':<30} {baseline_metrics['total_return_pct']:<20.2f}% "
          f"{hybrid_metrics['total_return_pct']:<20.2f}% "
          f"{hybrid_metrics['total_return_pct'] - baseline_metrics['total_return_pct']:+.2f}%")
    
    print(f"{'Max Drawdown':<30} {baseline_metrics['max_drawdown']:<20.2f}% "
          f"{hybrid_metrics['max_drawdown']:<20.2f}% "
          f"{hybrid_metrics['max_drawdown'] - baseline_metrics['max_drawdown']:+.2f}%")
    
    print(f"{'Profit Factor':<30} {baseline_metrics['profit_factor']:<20.2f} "
          f"{hybrid_metrics['profit_factor']:<20.2f} "
          f"{hybrid_metrics['profit_factor'] - baseline_metrics['profit_factor']:+.2f}")
    
    print(f"{'Sharpe Ratio':<30} {baseline_metrics['sharpe_ratio']:<20.2f} "
          f"{hybrid_metrics['sharpe_ratio']:<20.2f} "
          f"{hybrid_metrics['sharpe_ratio'] - baseline_metrics['sharpe_ratio']:+.2f}")
    
    # Trade quality
    print(f"\n{'TRADE QUALITY':<30}")
    print("-" * 90)
    
    print(f"{'Avg Win':<30} ${baseline_metrics['avg_win']:<19,.2f} "
          f"${hybrid_metrics['avg_win']:<19,.2f} "
          f"${hybrid_metrics['avg_win'] - baseline_metrics['avg_win']:+,.2f}")
    
    print(f"{'Avg Loss':<30} ${baseline_metrics['avg_loss']:<19,.2f} "
          f"${hybrid_metrics['avg_loss']:<19,.2f} "
          f"${hybrid_metrics['avg_loss'] - baseline_metrics['avg_loss']:+,.2f}")
    
    print(f"{'Expectancy':<30} ${baseline_metrics['expectancy']:<19,.2f} "
          f"${hybrid_metrics['expectancy']:<19,.2f} "
          f"${hybrid_metrics['expectancy'] - baseline_metrics['expectancy']:+,.2f}")
    
    # Streaks
    print(f"\n{'STREAKS':<30}")
    print("-" * 90)
    
    print(f"{'Max Win Streak':<30} {baseline_metrics['max_win_streak']:<20} "
          f"{hybrid_metrics['max_win_streak']:<20}")
    
    print(f"{'Max Loss Streak':<30} {baseline_metrics['max_loss_streak']:<20} "
          f"{hybrid_metrics['max_loss_streak']:<20}")
    
    # Summary
    print("\n" + "=" * 90)
    print("SUMMARY")
    print("=" * 90)
    
    improvements = 0
    
    if hybrid_metrics['win_rate'] > baseline_metrics['win_rate']:
        print("✅ Win rate improved")
        improvements += 1
    else:
        print("❌ Win rate declined")
    
    if hybrid_metrics['max_drawdown'] < baseline_metrics['max_drawdown']:
        print("✅ Drawdown reduced")
        improvements += 1
    else:
        print("❌ Drawdown increased")
    
    if hybrid_metrics['total_return_pct'] >= baseline_metrics['total_return_pct']:
        print("✅ Returns maintained or improved")
        improvements += 1
    else:
        print("❌ Returns declined")
    
    if hybrid_metrics['profit_factor'] > baseline_metrics['profit_factor']:
        print("✅ Profit factor improved")
        improvements += 1
    else:
        print("❌ Profit factor declined")
    
    if hybrid_metrics['sharpe_ratio'] > baseline_metrics['sharpe_ratio']:
        print("✅ Risk-adjusted returns improved")
        improvements += 1
    else:
        print("❌ Risk-adjusted returns declined")
    
    print("\n" + "=" * 90)
    
    if improvements >= 4:
        print("🎉 HYBRID STRATEGY WINS - Zone filter adds significant value!")
        print("   Recommendation: Use hybrid with zone filter enabled")
    elif improvements >= 3:
        print("✅ HYBRID STRATEGY COMPETITIVE - Zone filter adds some value")
        print("   Recommendation: Consider hybrid for production, test further")
    elif improvements >= 2:
        print("⚠️  MIXED RESULTS - Zone filter has pros and cons")
        print("   Recommendation: More testing needed, possibly tune parameters")
    else:
        print("❌ BASELINE STRATEGY WINS - Zone filter degraded performance")
        print("   Recommendation: Use pure SuperTrend, skip zone filter")
    
    print("\n" + "=" * 90)


def main():
    """Main execution."""
    
    print("\n" + "=" * 90)
    print("HYBRID ZONE-SUPERTREND STRATEGY BACKTEST")
    print("=" * 90)
    
    # Configuration
    data_path = "/Users/kirtanbhatt/code/stockScreener/cloud-function/data/GOLD_M5_150000bars.csv"
    initial_capital = 10000.0
    spread_pips = 0.3
    
    # Load data once
    df = load_data(data_path)
    
    # Run baseline (pure SuperTrend)
    print("\n" + "=" * 90)
    print("TEST 1: BASELINE (Pure SuperTrend)")
    print("=" * 90)
    baseline_results = run_hybrid_backtest(df, enable_zone_filter=False, 
                                          initial_capital=initial_capital, 
                                          spread_pips=spread_pips)
    
    # Run hybrid (with zone filter)
    print("\n" + "=" * 90)
    print("TEST 2: HYBRID (Zone Filter Enabled)")
    print("=" * 90)
    hybrid_results = run_hybrid_backtest(df, enable_zone_filter=True,
                                        initial_capital=initial_capital,
                                        spread_pips=spread_pips)
    
    # Calculate metrics
    print("\n📊 Calculating metrics...")
    baseline_metrics = calculate_metrics(baseline_results)
    hybrid_metrics = calculate_metrics(hybrid_results)
    
    # Print comparison
    print_comparison(baseline_metrics, hybrid_metrics)
    
    # Save trades
    if baseline_results['trades']:
        baseline_df = pd.DataFrame(baseline_results['trades'])
        baseline_path = "/Users/kirtanbhatt/code/stockScreener/cloud-function/hybrid_baseline_trades.csv"
        baseline_df.to_csv(baseline_path, index=False)
        print(f"\n💾 Baseline trades saved to: {baseline_path}")
    
    if hybrid_results['trades']:
        hybrid_df = pd.DataFrame(hybrid_results['trades'])
        hybrid_path = "/Users/kirtanbhatt/code/stockScreener/cloud-function/hybrid_zone_trades.csv"
        hybrid_df.to_csv(hybrid_path, index=False)
        print(f"💾 Hybrid trades saved to: {hybrid_path}")
    
    print("\n✅ Backtest complete!\n")


if __name__ == "__main__":
    main()
