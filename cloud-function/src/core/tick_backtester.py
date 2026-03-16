"""
Tick-level backtester using 1-second bar data
This is the most accurate backtest possible with Capital.com API
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Import base backtester
from src.core.backtester import (
    TickLevelBacktester,
    BacktestConfig,
    OrderSide,
    OrderStatus,
    Trade
)


class TickLevelBacktesterWithS1(TickLevelBacktester):
    """
    Enhanced backtester that uses 1-second bars for tick-level accuracy
    
    Key difference from base class:
    - Base class: simulates price path within candle (open->high->low->close)
    - This class: uses actual 1-second bars as "ticks" for precise SL/TP detection
    
    Usage:
        1. Generate signals on higher timeframe (e.g., M5, M15)
        2. Fetch 1-second bars for the same period
        3. For each signal:
           - Enter at signal time
           - Check every second if SL/TP hit
           - Exit when hit or new signal appears
    """
    
    def run_with_tick_data(
        self,
        strategy_df: pd.DataFrame,
        signals_df: pd.DataFrame,
        tick_df: pd.DataFrame
    ) -> Dict:
        """
        Run backtest using 1-second tick data
        
        Args:
            strategy_df: OHLCV data at strategy timeframe (e.g., M5)
            signals_df: Trading signals aligned with strategy_df
                       Columns: signal (1=BUY, -1=SELL, 0=none), stop_loss, take_profit
            tick_df: 1-second OHLCV data for precise exit detection
            
        Returns:
            Dictionary with backtest results
        """
        self.reset()
        
        logger.info(f"🚀 Starting tick-level backtest with 1-second bars")
        logger.info(f"   Strategy data: {len(strategy_df)} bars ({strategy_df.index[0]} to {strategy_df.index[-1]})")
        logger.info(f"   Tick data: {len(tick_df)} seconds")
        logger.info(f"   Initial capital: ${self.config.initial_capital:,.2f}")
        logger.info(f"   Spread: {self.config.spread_pips} pips, Slippage: {self.config.slippage_pips} pips")
        
        # Ensure data is sorted
        strategy_df = strategy_df.sort_index()
        signals_df = signals_df.sort_index()
        tick_df = tick_df.sort_index()
        
        # Align strategy and signals
        if len(strategy_df) != len(signals_df):
            logger.warning(f"Data length mismatch: {len(strategy_df)} vs {len(signals_df)}")
            strategy_df, signals_df = strategy_df.align(signals_df, join='inner', axis=0)
        
        # Process each strategy candle
        for i in range(len(strategy_df)):
            strategy_timestamp = strategy_df.index[i]
            strategy_candle = strategy_df.iloc[i]
            signal = signals_df.iloc[i]
            
            # Get signal values
            signal_value = signal.get('signal', 0)
            stop_loss = signal.get('stop_loss', None)
            take_profit = signal.get('take_profit', None)
            
            # Determine time range for this strategy candle
            if i < len(strategy_df) - 1:
                next_strategy_timestamp = strategy_df.index[i + 1]
            else:
                next_strategy_timestamp = strategy_df.index[-1] + (strategy_df.index[-1] - strategy_df.index[-2])
            
            # Get all 1-second ticks in this period
            ticks_in_period = tick_df[
                (tick_df.index >= strategy_timestamp) & 
                (tick_df.index < next_strategy_timestamp)
            ]
            
            if len(ticks_in_period) == 0:
                logger.warning(f"No tick data for period {strategy_timestamp}")
                continue
            
            # Check each second for existing positions
            for tick_idx in range(len(ticks_in_period)):
                tick_timestamp = ticks_in_period.index[tick_idx]
                tick = ticks_in_period.iloc[tick_idx]
                
                # Check if any open positions should be closed
                for trade in self.open_positions.copy():
                    should_exit = False
                    exit_price = None
                    exit_reason = None
                    
                    # Check stop loss
                    if trade.stop_loss is not None:
                        if trade.side == OrderSide.BUY:
                            # For BUY: check if price went at or below SL
                            if tick['low'] <= trade.stop_loss:
                                should_exit = True
                                exit_price = trade.stop_loss
                                exit_reason = 'Stop Loss'
                        else:  # SELL
                            # For SELL: check if price went at or above SL
                            if tick['high'] >= trade.stop_loss:
                                should_exit = True
                                exit_price = trade.stop_loss
                                exit_reason = 'Stop Loss'
                    
                    # Check take profit (only if SL not hit)
                    if not should_exit and trade.take_profit is not None:
                        if trade.side == OrderSide.BUY:
                            # For BUY: check if price went at or above TP
                            if tick['high'] >= trade.take_profit:
                                should_exit = True
                                exit_price = trade.take_profit
                                exit_reason = 'Take Profit'
                        else:  # SELL
                            # For SELL: check if price went at or below TP
                            if tick['low'] <= trade.take_profit:
                                should_exit = True
                                exit_price = trade.take_profit
                                exit_reason = 'Take Profit'
                    
                    if should_exit:
                        self.close_position(trade, tick_timestamp, exit_price, exit_reason)
                
                # Update equity curve every second (expensive but accurate)
                if tick_idx % 60 == 0:  # Update every minute to save computation
                    self.update_equity_curve(tick_timestamp, {'instrument': tick['close']})
            
            # After processing all ticks in period, check for new signal
            if signal_value == 1:  # BUY
                if len(self.open_positions) < self.config.max_positions:
                    # Enter at close of strategy candle
                    self.open_position(
                        timestamp=strategy_timestamp,
                        price=strategy_candle['close'],
                        side=OrderSide.BUY,
                        stop_loss=stop_loss,
                        take_profit=take_profit
                    )
            
            elif signal_value == -1:  # SELL
                if len(self.open_positions) < self.config.max_positions:
                    self.open_position(
                        timestamp=strategy_timestamp,
                        price=strategy_candle['close'],
                        side=OrderSide.SELL,
                        stop_loss=stop_loss,
                        take_profit=take_profit
                    )
        
        # Close any remaining positions
        if len(tick_df) > 0:
            final_tick = tick_df.iloc[-1]
            final_timestamp = tick_df.index[-1]
            for trade in self.open_positions.copy():
                self.close_position(trade, final_timestamp, final_tick['close'], 'End of Backtest')
        
        # Calculate metrics
        results = self._calculate_metrics()
        
        logger.info(f"\n{'='*70}")
        logger.info(f"📊 Backtest Results (1-Second Tick Data)")
        logger.info(f"{'='*70}")
        logger.info(f"Total Trades: {results['total_trades']}")
        logger.info(f"Win Rate: {results['win_rate']:.2f}%")
        logger.info(f"Total P&L: ${results['total_pnl']:.2f}")
        logger.info(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
        logger.info(f"Max Drawdown: {results['max_drawdown_pct']:.2f}%")
        logger.info(f"Final Capital: ${results['final_capital']:.2f}")
        logger.info(f"Return: {results['return_pct']:.2f}%")
        logger.info(f"{'='*70}\n")
        
        return results


def example_backtest_m5_with_s1_ticks():
    """
    Example: Backtest M5 strategy using S1 tick data
    
    This is the CORRECT way to backtest:
    1. Generate signals on M5 timeframe
    2. Fetch S1 data for the same period
    3. Use S1 bars to check every second if SL/TP hit
    
    Note: This example uses the old data_fetcher module which has been replaced.
    For current functionality, use cache_data.py or market_data.py instead.
    """
    # TODO: Update to use src.data.cache_data or src.data.market_data
    print("⚠️  This example needs to be updated to use the new data modules")
    print("    Old: from src.data_fetcher import CapitalComDataFetcher")
    print("    New: from src.data.cache_data import fetch_incremental")
    return
    
    from src.data.cache_data import fetch_incremental  # Updated import
    import json
    from dotenv import load_dotenv
    
    load_dotenv()
    secrets_str = os.getenv('apicredentials')
    if not secrets_str:
        print("❌ No credentials found")
        return
    
    secrets = json.loads(secrets_str)
    
    # Initialize fetcher
    fetcher = CapitalComDataFetcher(
        api_key=secrets.get('apikey', ''),
        username=secrets.get('username', ''),
        password=secrets.get('password', ''),
        capkey=secrets.get('capkey', '')
    )
    
    print("\n" + "="*70)
    print("Example: Backtest M5 Strategy with S1 Tick Data")
    print("="*70)
    
    # Step 1: Fetch M5 data for strategy
    print("\n📊 Step 1: Fetching M5 data for strategy signals...")
    df_m5 = fetcher.fetch_and_cache('GOLD', 'M5', total_bars=100)
    
    if df_m5 is None or len(df_m5) == 0:
        print("❌ Failed to fetch M5 data")
        return
    
    print(f"✅ Fetched {len(df_m5)} M5 bars")
    print(f"   Period: {df_m5.index[0]} to {df_m5.index[-1]}")
    print(f"   Span: {(df_m5.index[-1] - df_m5.index[0]).total_seconds() / 60:.0f} minutes")
    
    # Step 2: Generate simple signals (for demo purposes)
    print("\n📈 Step 2: Generating trading signals...")
    signals = []
    for i in range(len(df_m5)):
        # Simple momentum strategy: buy if price > MA
        ma_period = 20
        if i >= ma_period:
            ma = df_m5['close'].iloc[i-ma_period:i].mean()
            current_price = df_m5['close'].iloc[i]
            
            if current_price > ma and df_m5['close'].iloc[i-1] <= df_m5['close'].iloc[i-ma_period:i-1].mean():
                # Bullish crossover
                signals.append({
                    'signal': 1,
                    'stop_loss': current_price * 0.995,  # 0.5% stop loss
                    'take_profit': current_price * 1.01  # 1% take profit
                })
            elif current_price < ma and df_m5['close'].iloc[i-1] >= df_m5['close'].iloc[i-ma_period:i-1].mean():
                # Bearish crossover
                signals.append({
                    'signal': -1,
                    'stop_loss': current_price * 1.005,
                    'take_profit': current_price * 0.99
                })
            else:
                signals.append({'signal': 0, 'stop_loss': None, 'take_profit': None})
        else:
            signals.append({'signal': 0, 'stop_loss': None, 'take_profit': None})
    
    signals_df = pd.DataFrame(signals, index=df_m5.index)
    num_signals = (signals_df['signal'] != 0).sum()
    print(f"✅ Generated {num_signals} trading signals")
    
    # Step 3: Fetch S1 data for tick-level accuracy
    print("\n⏱️  Step 3: Fetching S1 (1-second) data for tick-level accuracy...")
    
    # Calculate how many seconds we need
    total_minutes = (df_m5.index[-1] - df_m5.index[0]).total_seconds() / 60
    total_seconds = int(total_minutes * 60)
    
    print(f"   Need {total_seconds} seconds of data...")
    
    # Fetch in chunks (Capital.com limit: 1000 bars per request)
    # For S1, we can only get ~1000 seconds (16 minutes) at a time
    # To backtest 100 M5 bars (500 minutes), we'd need 30,000 seconds
    # This is 30 API calls - might take a while!
    
    # For demo, let's just use the last 1000 seconds
    print(f"   [DEMO MODE] Fetching last 1000 seconds for demonstration...")
    df_s1 = fetcher.fetch_historical_prices('GOLD', 'S1', max_bars=1000)
    
    if df_s1 is None or len(df_s1) == 0:
        print("❌ Failed to fetch S1 data")
        return
    
    print(f"✅ Fetched {len(df_s1)} S1 bars")
    print(f"   Period: {df_s1.index[0]} to {df_s1.index[-1]}")
    print(f"   Span: {(df_s1.index[-1] - df_s1.index[0]).total_seconds():.0f} seconds ({(df_s1.index[-1] - df_s1.index[0]).total_seconds()/60:.1f} minutes)")
    
    # For demo, only backtest the period where we have S1 data
    df_m5_filtered = df_m5[(df_m5.index >= df_s1.index[0]) & (df_m5.index <= df_s1.index[-1])]
    signals_df_filtered = signals_df[(signals_df.index >= df_s1.index[0]) & (signals_df.index <= df_s1.index[-1])]
    
    print(f"\n   Backtesting period: {len(df_m5_filtered)} M5 bars with {len(df_s1)} S1 ticks")
    
    # Step 4: Run backtest
    print("\n🚀 Step 4: Running tick-level backtest...")
    
    config = BacktestConfig(
        initial_capital=10000,
        spread_pips=2.0,
        slippage_pips=0.5,
        pip_value=0.01,
        verbose=True
    )
    
    backtester = TickLevelBacktesterWithS1(config)
    results = backtester.run_with_tick_data(df_m5_filtered, signals_df_filtered, df_s1)
    
    # Step 5: Show results
    print("\n" + "="*70)
    print("📊 Final Results")
    print("="*70)
    print(f"Total Trades: {results['total_trades']}")
    print(f"Winning Trades: {results['winning_trades']}")
    print(f"Losing Trades: {results['losing_trades']}")
    print(f"Win Rate: {results['win_rate']:.2f}%")
    print(f"")
    print(f"Total P&L: ${results['total_pnl']:.2f}")
    print(f"Average Win: ${results['avg_win']:.2f}")
    print(f"Average Loss: ${results['avg_loss']:.2f}")
    print(f"Profit Factor: {results['profit_factor']:.2f}")
    print(f"")
    print(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
    print(f"Max Drawdown: ${results['max_drawdown']:.2f} ({results['max_drawdown_pct']:.2f}%)")
    print(f"")
    print(f"Initial Capital: ${config.initial_capital:.2f}")
    print(f"Final Capital: ${results['final_capital']:.2f}")
    print(f"Return: {results['return_pct']:.2f}%")
    print("="*70)
    
    # Show trade details
    if results['total_trades'] > 0:
        print("\n📋 Trade Details:")
        trades_df = backtester.get_trades_df()
        print(trades_df[['entry_time', 'entry_price', 'exit_time', 'exit_price', 'exit_reason', 'pnl', 'pnl_pct']])


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Run example
    example_backtest_m5_with_s1_ticks()
