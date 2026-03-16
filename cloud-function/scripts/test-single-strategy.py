#!/usr/bin/env python3
"""
Test a single strategy with specific parameters
"""
import sys
import pandas as pd
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.backtester import IntraCandleBacktester, BacktestConfig
from src.core.strategy import SupertrendVWAPStrategy

def test_strategy():
    """Test rank03 strategy: ST2.0_SMA20-50_BB2.0_PIP1_F8-10 (2-year backtest with event blocking)"""
    
    print("="*80)
    print("🧪 TESTING: rank03_ST2.0_SMA20-50_BB2.0_PIP1_F8-10 (2-YEAR BACKTEST)")
    print("="*80)
    
    # Load FULL 2-year data
    df = pd.read_csv("data/GOLD_M5_150000bars.csv")
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df.set_index('timestamp', inplace=True)
    
    print(f"\n📊 Data Loaded:")
    print(f"   Bars: {len(df)}")
    print(f"   Period: {df.index[0]} to {df.index[-1]}")
    print(f"   Duration: {(df.index[-1] - df.index[0]).days} days")
    
    # Rank03 parameters (BEST RISK-ADJUSTED)
    strategy = SupertrendVWAPStrategy(
        supertrend_period=10,
        supertrend_multiplier=2.0,  # Lower = more signals
        sma_fast=20,
        sma_slow=50,
        ema_period=21,
        bb_period=20,
        bb_std=2.0,
        sl_pips=8.0,   # Fixed 8 pips SL
        tp_pips=10.0,  # Fixed 10 pips TP
        pip_value=1.5  # GOLD pip value (rank03 uses 1.5)
    )
    
    print(f"\n⚙️  Strategy Parameters:")
    print(f"   Supertrend: 10 period, 2.0 multiplier")
    print(f"   SMA: 20/50")
    print(f"   Bollinger Bands: 20 period, 2.0 std")
    print(f"   TP/SL: Fixed 8:10 pips (tight)")
    print(f"   Pip Value: 1.5 (GOLD)")
    print(f"   Strategy: Rank #3 - Best Sharpe (0.578), Lowest DD (9.87%)")
    
    # Calculate indicators and signals
    df_with_indicators = strategy.calculate_indicators(df.copy())
    signals = strategy.generate_signals(df_with_indicators)
    
    total_signals = (signals['signal'] != 0).sum()
    buy_signals = (signals['signal'] == 1).sum()
    sell_signals = (signals['signal'] == -1).sum()
    
    print(f"\n📡 Signals Generated:")
    print(f"   Total: {total_signals}")
    print(f"   Buy: {buy_signals}")
    print(f"   Sell: {sell_signals}")
    
    # Run backtest WITH EVENT BLOCKING
    config = BacktestConfig(
        initial_capital=10000.0,
        pip_value=1.5,  # Rank03 uses 1.5
        default_position_size=10.0,
        max_positions=1,
        enable_event_blocking=True,  # ✅ ENABLE EVENT BLOCKING
        calendar_path="data/economic_calendar.json"  # Use generated calendar
    )
    
    print(f"\n🚫 Event Blocking:")
    print(f"   Status: ENABLED")
    print(f"   Calendar: {config.calendar_path}")
    print(f"   Block Window: 15 min before + 30 min after high-impact events")
    
    backtester = IntraCandleBacktester(config)
    results = backtester.run(df_with_indicators, signals)
    
    # Display results
    print(f"\n" + "="*80)
    print("💰 BACKTEST RESULTS")
    print("="*80)
    
    print(f"\n📈 Capital:")
    print(f"   Initial: ${config.initial_capital:,.2f}")
    print(f"   Final: ${results['final_capital']:,.2f}")
    print(f"   Profit: ${results['total_pnl']:,.2f}")
    print(f"   Return: {results['return_pct']:.2f}%")
    
    print(f"\n📊 Performance:")
    print(f"   Total Trades: {results['total_trades']}")
    print(f"   Win Rate: {results['win_rate']:.2f}%")
    print(f"   Profit Factor: {results['profit_factor']:.2f}")
    print(f"   Sharpe Ratio: {results['sharpe_ratio']:.2f}")
    print(f"   Max Drawdown: {results['max_drawdown_pct']:.2f}%")
    
    print(f"\n💵 Trades:")
    print(f"   Wins: {results['winning_trades']}")
    print(f"   Losses: {results['losing_trades']}")
    print(f"   Avg Win: ${results['avg_win']:,.2f}")
    print(f"   Avg Loss: ${results['avg_loss']:,.2f}")
    
    # Show individual trades
    if results['trades']:
        print(f"\n📋 Trade Details:")
        print("-"*80)
        for i, trade in enumerate(results['trades'], 1):
            entry_time = pd.to_datetime(trade['entry_time'])
            exit_time = pd.to_datetime(trade['exit_time'])
            duration = exit_time - entry_time
            
            profit_emoji = "✅" if trade['pnl'] > 0 else "❌"
            
            print(f"\n{profit_emoji} Trade {i}:")
            print(f"   {trade['side']} @ {trade['entry_price']:.2f} → {trade['exit_price']:.2f}")
            print(f"   Entry: {entry_time.strftime('%b %d %H:%M')}")
            print(f"   Exit:  {exit_time.strftime('%b %d %H:%M')} ({trade['exit_reason']})")
            print(f"   Duration: {duration}")
            print(f"   P&L: ${trade['pnl']:,.2f} ({trade['pnl_pct']:.2f}%)")
    
    print("\n" + "="*80)
    print("✅ 2-YEAR BACKTEST WITH EVENT BLOCKING COMPLETE!")
    print("="*80)

if __name__ == "__main__":
    test_strategy()
