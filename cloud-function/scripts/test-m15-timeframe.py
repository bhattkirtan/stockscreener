"""
Test the best M5 strategy on M15 timeframe for comparison
Strategy: ST 10, mult 2.0, SMA 15-50, BB 2.0, SL 0.7× ATR, TP 2.5× ATR
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from src.core.strategy import SupertrendVWAPStrategy
from src.core.backtester import IntraCandleBacktester, BacktestConfig
import pandas as pd

def test_m15():
    """Run best M5 strategy on M15 data"""
    
    # Load M15 data
    data_file = Path("data/GOLD_M15_10000bars.csv")
    if not data_file.exists():
        print(f"❌ File not found: {data_file}")
        return
    
    print(f"📂 Loading M15 data: {data_file}")
    df = pd.read_csv(data_file)
    
    # Convert time column
    if 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'])
        df.set_index('time', inplace=True)
    
    print(f"✅ Loaded {len(df):,} M15 bars")
    print(f"   Period: {df.index[0]} to {df.index[-1]}")
    print(f"   Days: {(df.index[-1] - df.index[0]).days}")
    
    # Best M5 strategy parameters
    strategy_params = {
        'supertrend_period': 10,
        'supertrend_multiplier': 2.0,
        'sma_fast': 15,
        'sma_slow': 50,
        'bb_period': 20,
        'bb_std': 2.0,
        'atr_period': 14,
        'stop_loss_atr_multiplier': 0.7,
        'take_profit_atr_multiplier': 2.5,
        'use_time_exit': False,
        'use_eod_close': False,
        'use_heikin_ashi': False
    }
    
    print(f"\n{'='*80}")
    print(f"🧪 TESTING M5 BEST STRATEGY ON M15 TIMEFRAME")
    print(f"{'='*80}")
    print(f"\nStrategy Parameters:")
    print(f"   Supertrend: period={strategy_params['supertrend_period']}, mult={strategy_params['supertrend_multiplier']}")
    print(f"   SMA: {strategy_params['sma_fast']}-{strategy_params['sma_slow']}")
    print(f"   Bollinger Bands: {strategy_params['bb_period']} period, {strategy_params['bb_std']}σ")
    print(f"   Stop Loss: {strategy_params['stop_loss_atr_multiplier']}× ATR")
    print(f"   Take Profit: {strategy_params['take_profit_atr_multiplier']}× ATR")
    print(f"   Time Exit: {strategy_params['use_time_exit']}")
    print(f"   EOD Close: {strategy_params['use_eod_close']}")
    
    # Initialize strategy
    strategy = SupertrendVWAPStrategy(**strategy_params)
    
    # Run backtest
    print(f"\n🔄 Running backtest on M15 data...")
    backtester = Backtester(strategy, initial_capital=10000)
    
    try:
        results = backtester.run(df)
        
        print(f"\n{'='*80}")
        print(f"📊 M15 BACKTEST RESULTS")
        print(f"{'='*80}")
        
        print(f"\n💰 Performance:")
        print(f"   Total Return: {results['total_return']:.2f}%")
        print(f"   Total Profit: ${results['total_profit']:.2f}")
        print(f"   Final Capital: ${results['final_capital']:.2f}")
        
        print(f"\n📈 Trade Statistics:")
        print(f"   Total Trades: {results['total_trades']}")
        print(f"   Winning Trades: {results['winning_trades']} ({results['win_rate']:.1f}%)")
        print(f"   Losing Trades: {results['losing_trades']}")
        print(f"   Average Win: ${results['avg_win']:.2f}")
        print(f"   Average Loss: ${results['avg_loss']:.2f}")
        print(f"   Profit Factor: {results['profit_factor']:.2f}")
        
        if results['avg_loss'] != 0:
            rr_ratio = abs(results['avg_win'] / results['avg_loss'])
            print(f"   Risk:Reward Ratio: 1:{rr_ratio:.2f}")
        
        print(f"\n📉 Risk Metrics:")
        print(f"   Max Drawdown: ${results['max_drawdown']:.2f} ({results['max_drawdown_pct']:.1f}%)")
        print(f"   Sharpe Ratio: {results['sharpe_ratio']:.2f}")
        
        # Calculate monthly metrics
        days = (df.index[-1] - df.index[0]).days
        months = days / 30.44
        monthly_return = results['total_return'] / months
        monthly_profit = results['total_profit'] / months
        trades_per_month = results['total_trades'] / months
        
        print(f"\n📅 Time-based Metrics:")
        print(f"   Backtest Period: {days} days ({months:.1f} months)")
        print(f"   Monthly Return: {monthly_return:.2f}%")
        print(f"   Monthly Profit: ${monthly_profit:.2f}")
        print(f"   Trades per Month: {trades_per_month:.1f}")
        
        # Load and compare with M5 results
        print(f"\n{'='*80}")
        print(f"⚖️  COMPARISON: M5 vs M15")
        print(f"{'='*80}")
        
        # M5 metrics (from best strategy)
        m5_return = 122.41
        m5_trades = 866
        m5_months = 25.3
        m5_trades_per_month = m5_trades / m5_months
        m5_monthly_return = m5_return / m5_months
        
        print(f"\n{'Metric':<30} | {'M5 (5-min)':<20} | {'M15 (15-min)':<20} | {'Difference':<20}")
        print(f"{'-'*30:30} | {'-'*20:20} | {'-'*20:20} | {'-'*20:20}")
        print(f"{'Total Return':<30} | {m5_return:>18.1f}% | {results['total_return']:>18.2f}% | {results['total_return']-m5_return:>18.2f}%")
        print(f"{'Monthly Return':<30} | {m5_monthly_return:>18.2f}% | {monthly_return:>18.2f}% | {monthly_return-m5_monthly_return:>18.2f}%")
        print(f"{'Total Trades':<30} | {m5_trades:>20} | {results['total_trades']:>20} | {results['total_trades']-m5_trades:>20}")
        print(f"{'Trades/Month':<30} | {m5_trades_per_month:>18.1f} | {trades_per_month:>18.1f} | {trades_per_month-m5_trades_per_month:>18.1f}")
        print(f"{'Win Rate':<30} | {25.2:>18.1f}% | {results['win_rate']:>18.1f}% | {results['win_rate']-25.2:>18.1f}%")
        print(f"{'Profit Factor':<30} | {1.99:>20.2f} | {results['profit_factor']:>20.2f} | {results['profit_factor']-1.99:>20.2f}")
        
        print(f"\n💡 Analysis:")
        if results['total_return'] > m5_return * 0.9:  # Within 10%
            if trades_per_month < m5_trades_per_month * 0.5:
                print(f"   ✅ M15 gives similar returns with {trades_per_month/m5_trades_per_month*100:.0f}% fewer trades!")
                print(f"   ✅ RECOMMENDED: Use M15 for less stress and lower costs")
            else:
                print(f"   ✅ M15 gives similar returns")
                print(f"   🤔 Trades still frequent, consider M30 or H1")
        elif results['total_return'] > m5_return:
            print(f"   ✅ M15 OUTPERFORMS M5 by {results['total_return']-m5_return:.1f}%!")
            print(f"   ✅ STRONGLY RECOMMENDED: Switch to M15")
        else:
            print(f"   ⚠️  M15 underperforms M5 by {m5_return-results['total_return']:.1f}%")
            if trades_per_month < m5_trades_per_month * 0.5:
                print(f"   💡 But has {(1-trades_per_month/m5_trades_per_month)*100:.0f}% fewer trades")
                print(f"   💡 Consider if lower stress is worth the trade-off")
            else:
                print(f"   ❌ Stick with M5 for better returns")
        
        print(f"\n{'='*80}")
        
    except Exception as e:
        print(f"❌ Error running backtest: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_m15()
