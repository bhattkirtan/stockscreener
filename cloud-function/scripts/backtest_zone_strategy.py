"""Backtest zone-based strategy on historical data.

This script:
1. Loads M5 data
2. Resamples to H4, H1, M15
3. Runs zone strategy backtest
4. Generates performance report
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from src.strategies.zone_strategy import ZoneStrategy, TradeSetup


def resample_to_timeframe(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Resample M5 data to higher timeframe.
    
    Args:
        df: M5 OHLC dataframe
        timeframe: Target timeframe (H4, H1, M15)
        
    Returns:
        Resampled dataframe
    """
    # Map timeframe to pandas frequency
    freq_map = {
        'H4': '4H',
        'H1': '1H',
        'M15': '15T',
        'M5': '5T'
    }
    
    freq = freq_map.get(timeframe, '1H')
    
    # Set timestamp as index
    df_copy = df.copy()
    df_copy.set_index('timestamp', inplace=True)
    
    # Resample OHLC
    resampled = df_copy.resample(freq).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last'
    }).dropna()
    
    # Reset index
    resampled.reset_index(inplace=True)
    
    return resampled


def load_and_prepare_data(csv_path: str):
    """Load M5 data and create multi-timeframe views.
    
    Args:
        csv_path: Path to M5 CSV file
        
    Returns:
        Dictionary with H4, H1, M15, M5 dataframes
    """
    print(f"📊 Loading data from {csv_path}...")
    
    # Load M5 data
    df_m5 = pd.read_csv(csv_path)
    df_m5['timestamp'] = pd.to_datetime(df_m5['timestamp'])
    
    print(f"   ✓ Loaded {len(df_m5)} M5 bars")
    print(f"   ✓ Range: {df_m5['timestamp'].min()} to {df_m5['timestamp'].max()}")
    
    # Resample to higher timeframes
    print("\n📈 Resampling to multiple timeframes...")
    
    df_h4 = resample_to_timeframe(df_m5, 'H4')
    print(f"   ✓ H4: {len(df_h4)} bars")
    
    df_h1 = resample_to_timeframe(df_m5, 'H1')
    print(f"   ✓ H1: {len(df_h1)} bars")
    
    df_m15 = resample_to_timeframe(df_m5, 'M15')
    print(f"   ✓ M15: {len(df_m15)} bars")
    
    return {
        'H4': df_h4,
        'H1': df_h1,
        'M15': df_m15,
        'M5': df_m5
    }


def run_zone_backtest(df_dict: dict, initial_capital: float = 10000.0, 
                      spread_pips: float = 0.3) -> dict:
    """Run zone strategy backtest.
    
    Args:
        df_dict: Multi-timeframe data
        initial_capital: Starting capital
        spread_pips: Spread in pips
        
    Returns:
        Backtest results dictionary
    """
    print("\n🎯 Initializing Zone Strategy...")
    strategy = ZoneStrategy(symbol="GOLD")
    print(f"   ✓ Strategy initialized")
    print(f"   ✓ Risk per trade: {strategy.config['risk_per_idea_pct'] * 100:.1f}%")
    print(f"   ✓ Min R:R: {strategy.config['min_rr_for_trade']:.1f}")
    print(f"   ✓ Min score: {strategy.config['min_trade_score']}")
    
    print(f"\n🚀 Running backtest...")
    print(f"   Capital: ${initial_capital:,.2f}")
    print(f"   Spread: {spread_pips} pips")
    
    # Backtest state
    equity = initial_capital
    trades = []
    equity_curve = [initial_capital]
    timestamps = []
    
    # Get M5 bars for iteration
    m5_df = df_dict['M5']
    
    # Minimum bars needed for analysis
    min_bars_h4 = 100
    min_bars_h1 = 200
    min_bars_m15 = 400
    min_bars_m5 = 2000
    
    print(f"\n   Warming up ({min_bars_m5} bars)...")
    
    # Iterate through M5 bars
    for i in range(min_bars_m5, len(m5_df)):
        current_bar = m5_df.iloc[i]
        current_price = current_bar['close']
        current_time = current_bar['timestamp']
        
        # Build multi-timeframe view up to current bar
        # Find corresponding indices in other timeframes
        h4_idx = len(df_dict['H4'][df_dict['H4']['timestamp'] <= current_time])
        h1_idx = len(df_dict['H1'][df_dict['H1']['timestamp'] <= current_time])
        m15_idx = len(df_dict['M15'][df_dict['M15']['timestamp'] <= current_time])
        
        if h4_idx < min_bars_h4 or h1_idx < min_bars_h1 or m15_idx < min_bars_m15:
            continue
        
        # Create historical views (no future leakage)
        df_view = {
            'H4': df_dict['H4'].iloc[:h4_idx].copy(),
            'H1': df_dict['H1'].iloc[:h1_idx].copy(),
            'M15': df_dict['M15'].iloc[:m15_idx].copy(),
            'M5': m5_df.iloc[max(0, i-500):i+1].copy()  # Last 500 M5 bars
        }
        
        # Evaluate setup
        setup = strategy.evaluate_setup(
            df_dict=df_view,
            current_price=current_price,
            spread=spread_pips,
            equity=equity,
            is_news_blocked=False  # TODO: Add news blocking
        )
        
        if setup:
            # Simulate trade execution
            entry_price = setup.entry_price
            stop_loss = setup.stop_loss
            take_profit_1 = setup.take_profit_1
            
            # Calculate actual filled price (add spread)
            if setup.direction == 'long':
                filled_price = entry_price + spread_pips
            else:
                filled_price = entry_price - spread_pips
            
            # Simulate forward to find exit
            exit_price = None
            exit_reason = None
            exit_time = None
            mae = 0.0  # Maximum adverse excursion
            mfe = 0.0  # Maximum favorable excursion
            
            # Look ahead for exit (max 200 bars)
            for j in range(i+1, min(i+201, len(m5_df))):
                bar = m5_df.iloc[j]
                
                if setup.direction == 'long':
                    # Track MAE/MFE
                    mae = min(mae, bar['low'] - filled_price)
                    mfe = max(mfe, bar['high'] - filled_price)
                    
                    # Check stop
                    if bar['low'] <= stop_loss:
                        exit_price = stop_loss
                        exit_reason = 'stop_loss'
                        exit_time = bar['timestamp']
                        break
                    
                    # Check TP1
                    if bar['high'] >= take_profit_1:
                        exit_price = take_profit_1
                        exit_reason = 'take_profit_1'
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
                    
                    # Check TP1
                    if bar['low'] <= take_profit_1:
                        exit_price = take_profit_1
                        exit_reason = 'take_profit_1'
                        exit_time = bar['timestamp']
                        break
            
            # If no exit found, skip trade (couldn't complete)
            if exit_price is None:
                continue
            
            # Calculate P&L
            if setup.direction == 'long':
                pnl = (exit_price - filled_price) * setup.position_size
            else:
                pnl = (filled_price - exit_price) * setup.position_size
            
            # Update equity
            equity += pnl
            
            # Record trade
            trades.append({
                'entry_time': current_time,
                'exit_time': exit_time,
                'direction': setup.direction,
                'entry_price': filled_price,
                'exit_price': exit_price,
                'stop_loss': stop_loss,
                'take_profit': take_profit_1,
                'position_size': setup.position_size,
                'pnl': pnl,
                'pnl_pct': pnl / (equity - pnl) * 100,
                'exit_reason': exit_reason,
                'setup_score': setup.score,
                'rr_ratio': setup.room_to_target,
                'mae': mae,
                'mfe': mfe,
                'bias': setup.bias.value,
                'trigger': setup.trigger.value,
                'zone_tf': setup.zone.timeframe
            })
            
            # Update strategy daily stats
            strategy.update_daily_pnl(pnl / (equity - pnl))
            
            # Print trade
            if len(trades) % 10 == 0:
                print(f"\r   Progress: {i}/{len(m5_df)} bars | Trades: {len(trades)} | "
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
        'final_equity': equity
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
        return {'error': 'No trades executed'}
    
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
    
    # MAE/MFE analysis
    avg_mae = abs(trades_df['mae'].mean())
    avg_mfe = abs(trades_df['mfe'].mean())
    
    return {
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
        'initial_capital': initial_capital,
        'final_equity': final_equity
    }


def print_results(metrics: dict):
    """Print backtest results."""
    
    print("\n" + "=" * 70)
    print("ZONE STRATEGY BACKTEST RESULTS")
    print("=" * 70)
    
    if 'error' in metrics:
        print(f"\n❌ {metrics['error']}")
        return
    
    print(f"\n📊 TRADE STATISTICS")
    print(f"   Total Trades:        {metrics['total_trades']}")
    print(f"   Winning Trades:      {metrics['winning_trades']}")
    print(f"   Losing Trades:       {metrics['losing_trades']}")
    print(f"   Win Rate:            {metrics['win_rate']:.2f}%")
    
    print(f"\n💰 PERFORMANCE")
    print(f"   Initial Capital:     ${metrics['initial_capital']:,.2f}")
    print(f"   Final Equity:        ${metrics['final_equity']:,.2f}")
    print(f"   Total Return:        {metrics['total_return_pct']:+.2f}%")
    print(f"   Total P&L:           ${metrics['total_pnl']:+,.2f}")
    print(f"   Max Drawdown:        {metrics['max_drawdown']:.2f}%")
    
    print(f"\n📈 TRADE QUALITY")
    print(f"   Avg Win:             ${metrics['avg_win']:,.2f}")
    print(f"   Avg Loss:            ${metrics['avg_loss']:,.2f}")
    print(f"   Avg Win/Loss:        {metrics['avg_win_loss_ratio']:.2f}")
    print(f"   Profit Factor:       {metrics['profit_factor']:.2f}")
    print(f"   Expectancy:          ${metrics['expectancy']:,.2f}")
    print(f"   Sharpe Ratio:        {metrics['sharpe_ratio']:.2f}")
    
    print(f"\n🎯 EXECUTION ANALYSIS")
    print(f"   Avg MAE:             ${metrics['avg_mae']:,.2f}")
    print(f"   Avg MFE:             ${metrics['avg_mfe']:,.2f}")
    
    print("\n" + "=" * 70)


def main():
    """Main execution."""
    
    print("\n" + "=" * 70)
    print("ZONE STRATEGY BACKTEST")
    print("=" * 70)
    
    # Configuration
    data_path = "/Users/kirtanbhatt/code/stockScreener/cloud-function/data/GOLD_M5_150000bars.csv"
    initial_capital = 10000.0
    spread_pips = 0.3
    
    # Load data
    df_dict = load_and_prepare_data(data_path)
    
    # Run backtest
    results = run_zone_backtest(df_dict, initial_capital, spread_pips)
    
    # Calculate metrics
    print("\n📊 Calculating metrics...")
    metrics = calculate_metrics(results)
    
    # Print results
    print_results(metrics)
    
    # Save trades to CSV
    if results['trades']:
        trades_df = pd.DataFrame(results['trades'])
        output_path = "/Users/kirtanbhatt/code/stockScreener/cloud-function/zone_strategy_trades.csv"
        trades_df.to_csv(output_path, index=False)
        print(f"\n💾 Trades saved to: {output_path}")
    
    print("\n✅ Backtest complete!\n")


if __name__ == "__main__":
    main()
