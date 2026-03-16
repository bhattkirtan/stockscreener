"""
Complete backtest workflow with real Capital.com data
- Fetches historical data with caching
- Gets current spreads
- Runs strategy backtest
- Shows detailed results
"""

import json
import os
import logging
from dotenv import load_dotenv
from datetime import datetime

from src.data.cache_data import fetch_incremental
from src.data.market_data import MarketDataFetcher, get_instrument_spread_config
from src.core.strategy import SupertrendVWAPStrategy, SentimentAwareStrategy
from src.core.backtester import BacktestConfig, IntraCandleBacktester

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_backtest(
    instrument: str = 'GOLD',
    timeframe: str = 'M15',
    max_bars: int = 2000,
    initial_capital: float = 10000.0,
    use_sentiment: bool = False
):
    """
    Run complete backtest workflow
    
    Args:
        instrument: Trading instrument (GOLD, EURUSD, etc.)
        timeframe: Timeframe (M5, M15, H1, etc.)
        max_bars: Number of bars to fetch
        initial_capital: Starting capital
        use_sentiment: Use sentiment-aware strategy
    
    Returns:
        Dict with backtest results
    """
    
    print("\n" + "="*80)
    print(f"🚀 BACKTEST: {instrument} on {timeframe} timeframe")
    print(f"   Initial Capital: ${initial_capital:,.2f}")
    print(f"   Bars to fetch: {max_bars}")
    print("="*80)
    
    # 1. Load credentials
    load_dotenv()
    secrets_str = os.getenv('apicredentials')
    
    if not secrets_str:
        logger.error("❌ No credentials found!")
        print("\n" + "="*80)
        print("⚠️  CREDENTIALS NOT CONFIGURED")
        print("="*80)
        print("\nTo run backtests locally, you need to create a .env file:")
        print("\n1. Copy the example file:")
        print("   cp .env.example .env")
        print("\n2. Edit .env and add your Capital.com credentials:")
        print("   apicredentials='{\"apikey\":\"xxx\",\"username\":\"xxx\",\"password\":\"xxx\",\"capkey\":\"xxx\"}'")
        print("\n3. Get your credentials from:")
        print("   - Capital.com API key: https://capital.com/trading/platform/")
        print("   - Use demo account for testing (recommended)")
        print("\n" + "="*80)
        return None
    
    secrets = json.loads(secrets_str)
    
    # 2. Initialize data fetcher
    logger.info("Initializing Capital.com connection...")
    data_fetcher = CapitalComDataFetcher(
        api_key=secrets.get('apikey', ''),
        username=secrets.get('username', ''),
        password=secrets.get('password', ''),
        capkey=secrets.get('capkey', ''),
        cache_dir='data'  # Save to data/ directory
    )
    
    # 3. Fetch historical data (uses cache if available)
    print(f"\n📊 Fetching {instrument} {timeframe} data...")
    df = data_fetcher.fetch_and_cache(
        epic=instrument,
        resolution=timeframe,
        max_bars=max_bars,
        cache_hours=24  # Cache for 24 hours
    )
    
    if df is None or len(df) == 0:
        logger.error("Failed to fetch data")
        return None
    
    print(f"✅ Loaded {len(df)} bars")
    print(f"   Date range: {df.index[0]} to {df.index[-1]}")
    print(f"   Duration: {(df.index[-1] - df.index[0]).days} days")
    
    # 4. Get current spreads for realistic costs
    print(f"\n💰 Getting current spread for {instrument}...")
    market_data = MarketDataFetcher(data_fetcher)
    spread_config = get_instrument_spread_config(instrument, market_data)
    
    print(f"✅ Spread configuration:")
    print(f"   Pip value: {spread_config['pip_value']}")
    print(f"   Spread: {spread_config['spread_pips']:.2f} pips")
    print(f"   Slippage: {spread_config['slippage_pips']:.2f} pips")
    if 'current_spread_pips' in spread_config:
        print(f"   (Using real-time spread: {spread_config['current_spread_pips']:.2f} pips)")
    
    # 5. Initialize strategy
    print(f"\n⚙️  Initializing {'sentiment-aware' if use_sentiment else 'standard'} strategy...")
    
    StrategyClass = SentimentAwareStrategy if use_sentiment else SupertrendVWAPStrategy
    
    strategy = StrategyClass(
        supertrend_period=10,
        supertrend_multiplier=3.0,
        bb_period=20,
        bb_std=2.0,
        rsi_period=14,
        rsi_overbought=70,
        rsi_oversold=30,
        sl_pips=20.0,
        tp_pips=40.0,
        pip_value=spread_config['pip_value']
    )
    
    # 6. Calculate indicators
    print("\n📈 Calculating indicators...")
    df_with_indicators = strategy.calculate_indicators(df)
    
    print(f"✅ Latest indicator values:")
    print(f"   Close: {df_with_indicators['close'].iloc[-1]:.2f}")
    print(f"   Supertrend: {df_with_indicators['supertrend'].iloc[-1]:.2f}")
    print(f"   Direction: {'UP' if df_with_indicators['direction'].iloc[-1] == 1 else 'DOWN'}")
    print(f"   VWAP: {df_with_indicators['vwap'].iloc[-1]:.2f}")
    print(f"   RSI: {df_with_indicators['rsi'].iloc[-1]:.1f}")
    print(f"   BB Upper: {df_with_indicators['bb_upper'].iloc[-1]:.2f}")
    print(f"   BB Lower: {df_with_indicators['bb_lower'].iloc[-1]:.2f}")
    
    # 7. Generate signals
    print("\n🎯 Generating trading signals...")
    signals = strategy.generate_signals(df_with_indicators)
    
    buy_signals = (signals['signal'] == 1).sum()
    sell_signals = (signals['signal'] == -1).sum()
    total_signals = buy_signals + sell_signals
    
    print(f"✅ Signal summary:")
    print(f"   Buy signals: {buy_signals}")
    print(f"   Sell signals: {sell_signals}")
    print(f"   Total signals: {total_signals}")
    
    if total_signals == 0:
        print("\n⚠️  No trading signals generated!")
        print("   Try adjusting strategy parameters or using more data")
        return None
    
    # Show last few signals
    if total_signals > 0:
        print(f"\n📋 Last 5 signals:")
        signal_rows = signals[signals['signal'] != 0].tail(5)
        for idx, row in signal_rows.iterrows():
            signal_type = "🟢 BUY " if row['signal'] == 1 else "🔴 SELL"
            print(f"   {idx.strftime('%Y-%m-%d %H:%M')}: {signal_type} @ {row['entry_price']:.2f}")
            print(f"      SL={row['stop_loss']:.2f}, TP={row['take_profit']:.2f}")
    
    # 8. Configure backtest with real spreads
    print("\n🔧 Configuring backtest...")
    config = BacktestConfig(
        initial_capital=initial_capital,
        spread_pips=spread_config['spread_pips'],
        slippage_pips=spread_config['slippage_pips'],
        pip_value=spread_config['pip_value'],
        position_size_pct=1.0,  # Use 100% of capital per trade
        max_positions=1  # One trade at a time
    )
    
    print(f"✅ Backtest config:")
    print(f"   Initial capital: ${config.initial_capital:,.2f}")
    print(f"   Transaction costs: {config.spread_pips + config.slippage_pips:.2f} pips per trade")
    print(f"   Position size: {config.position_size_pct * 100}% of capital")
    print(f"   Max concurrent positions: {config.max_positions}")
    
    # 9. Run backtest
    print("\n🏃 Running backtest...")
    start_time = datetime.now()
    
    backtester = IntraCandleBacktester(config)
    results = backtester.run(signals)
    
    duration = (datetime.now() - start_time).total_seconds()
    print(f"✅ Backtest completed in {duration:.2f} seconds")
    
    # 10. Display results
    print("\n" + "="*80)
    print("📊 BACKTEST RESULTS")
    print("="*80)
    
    print(f"\n💵 Performance:")
    print(f"   Initial Capital: ${results['initial_capital']:,.2f}")
    print(f"   Final Capital: ${results['final_capital']:,.2f}")
    print(f"   Total P&L: ${results['total_pnl']:,.2f} ({results['total_return_pct']:.2f}%)")
    
    print(f"\n📈 Trade Statistics:")
    print(f"   Total Trades: {results['total_trades']}")
    print(f"   Winning Trades: {results['winning_trades']}")
    print(f"   Losing Trades: {results['losing_trades']}")
    print(f"   Win Rate: {results['metrics']['win_rate']:.1f}%")
    
    print(f"\n💰 P&L Breakdown:")
    print(f"   Gross Profit: ${results['gross_profit']:,.2f}")
    print(f"   Gross Loss: ${results['gross_loss']:,.2f}")
    print(f"   Average Win: ${results['avg_win']:,.2f}")
    print(f"   Average Loss: ${results['avg_loss']:,.2f}")
    print(f"   Profit Factor: {results['metrics']['profit_factor']:.2f}")
    
    print(f"\n📊 Risk Metrics:")
    print(f"   Max Drawdown: {results['metrics']['max_drawdown_pct']:.2f}%")
    print(f"   Sharpe Ratio: {results['metrics']['sharpe_ratio']:.2f}")
    print(f"   Calmar Ratio: {results['metrics']['calmar_ratio']:.2f}")
    
    print(f"\n💸 Transaction Costs:")
    print(f"   Total Costs: ${results['total_transaction_costs']:,.2f}")
    print(f"   Cost per Trade: ${results['total_transaction_costs'] / results['total_trades'] if results['total_trades'] > 0 else 0:.2f}")
    
    # Performance assessment
    print("\n🎯 Performance Assessment:")
    sharpe = results['metrics']['sharpe_ratio']
    win_rate = results['metrics']['win_rate']
    max_dd = results['metrics']['max_drawdown_pct']
    
    if sharpe > 2.0 and win_rate > 50:
        print("   ✅ EXCELLENT - Strong risk-adjusted returns")
    elif sharpe > 1.0 and win_rate > 40:
        print("   ✅ GOOD - Positive risk-adjusted returns")
    elif sharpe > 0.5:
        print("   ⚠️  ACCEPTABLE - Marginal performance")
    else:
        print("   ❌ POOR - Needs improvement")
    
    if max_dd > 30:
        print("   ⚠️  WARNING: High drawdown - consider reducing position size")
    elif max_dd > 20:
        print("   ⚠️  Note: Moderate drawdown - monitor risk carefully")
    
    # Show trade history sample
    if len(results['trades']) > 0:
        print(f"\n📜 Sample trades (first 5):")
        for i, trade in enumerate(results['trades'][:5]):
            direction = "LONG" if trade.direction == 1 else "SHORT"
            status = "WIN" if trade.pnl > 0 else "LOSS"
            print(f"   {i+1}. {direction} @ {trade.entry_price:.2f} -> {trade.exit_price:.2f}")
            print(f"      P&L: ${trade.pnl:,.2f} ({status})")
    
    print("\n" + "="*80)
    
    return results


if __name__ == '__main__':
    """
    Run backtest examples
    """
    
    # Example 1: GOLD M15
    print("\n" + "🏆 "*30)
    print("EXAMPLE 1: Gold on 15-minute timeframe")
    print("🏆 "*30)
    
    results = run_backtest(
        instrument='GOLD',
        timeframe='M15',
        max_bars=2000,  # ~20 days of M15 data
        initial_capital=10000.0,
        use_sentiment=False
    )
    
    # Example 2: EURUSD M5 with sentiment
    print("\n" + "🏆 "*30)
    print("EXAMPLE 2: EURUSD on 5-minute timeframe (with sentiment)")
    print("🏆 "*30)
    
    results2 = run_backtest(
        instrument='EURUSD',
        timeframe='M5',
        max_bars=3000,  # ~10 days of M5 data
        initial_capital=5000.0,
        use_sentiment=True
    )
    
    print("\n✅ All backtests completed!")
    print("\n💡 Tips:")
    print("   - Data is cached in data/ directory for 24 hours")
    print("   - Adjust strategy parameters in strategy.py")
    print("   - Transaction costs use real-time spreads from Capital.com")
    print("   - For walk-forward analysis, split data into 70/30 train/test")
