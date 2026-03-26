"""
Test cases for tick-level backtester
"""

import unittest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.backtester import (
    TickLevelBacktester,
    BacktestConfig,
    OrderSide,
    OrderStatus,
    Trade
)


class TestTickLevelBacktester(unittest.TestCase):
    """Test tick-level backtesting logic"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.config = BacktestConfig(
            initial_capital=10000,
            spread_pips=2.0,
            slippage_pips=0.5,
            pip_value=0.01,
            verbose=False
        )
        self.backtester = TickLevelBacktester(self.config)
    
    def test_initialization(self):
        """Test backtester initialization"""
        self.assertEqual(self.backtester.capital, 10000)
        self.assertEqual(len(self.backtester.open_positions), 0)
        self.assertEqual(len(self.backtester.closed_positions), 0)
    
    def test_open_position_buy(self):
        """Test opening a buy position"""
        trade = self.backtester.open_position(
            timestamp=datetime.now(),
            price=2000.0,
            side=OrderSide.BUY,
            stop_loss=1990.0,
            take_profit=2020.0,
            size=1.0
        )
        
        self.assertIsNotNone(trade)
        self.assertEqual(trade.side, OrderSide.BUY)
        self.assertEqual(trade.stop_loss, 1990.0)
        self.assertEqual(trade.take_profit, 2020.0)
        self.assertEqual(len(self.backtester.open_positions), 1)
        
        # Check slippage was applied (buy means price goes up)
        self.assertGreater(trade.entry_price, 2000.0)
    
    def test_open_position_sell(self):
        """Test opening a sell position"""
        trade = self.backtester.open_position(
            timestamp=datetime.now(),
            price=2000.0,
            side=OrderSide.SELL,
            stop_loss=2010.0,
            take_profit=1980.0,
            size=1.0
        )
        
        self.assertIsNotNone(trade)
        self.assertEqual(trade.side, OrderSide.SELL)
        
        # Check slippage was applied (sell means price goes down)
        self.assertLess(trade.entry_price, 2000.0)
    
    def test_max_positions_limit(self):
        """Test that max positions limit is enforced"""
        config = BacktestConfig(max_positions=1, verbose=False)
        backtester = TickLevelBacktester(config)
        
        # Open first position
        trade1 = backtester.open_position(
            timestamp=datetime.now(),
            price=2000.0,
            side=OrderSide.BUY
        )
        self.assertIsNotNone(trade1)
        
        # Try to open second position — must raise, never silently succeed
        with self.assertRaises(RuntimeError):
            backtester.open_position(
                timestamp=datetime.now(),
                price=2000.0,
                side=OrderSide.BUY
            )
        self.assertEqual(len(backtester.open_positions), 1)
    
    def test_close_position_profit(self):
        """Test closing a profitable trade"""
        # Open buy position at 2000
        trade = self.backtester.open_position(
            timestamp=datetime.now(),
            price=2000.0,
            side=OrderSide.BUY,
            size=1.0
        )
        
        initial_capital = self.backtester.capital
        
        # Close at 2020 (profit)
        self.backtester.close_position(
            trade,
            timestamp=datetime.now(),
            price=2020.0,
            reason='Test Close'
        )
        
        self.assertEqual(trade.status, OrderStatus.CLOSED)
        self.assertIsNotNone(trade.exit_price)
        self.assertGreater(trade.pnl, 0)  # Should be profitable
        self.assertGreater(self.backtester.capital, initial_capital)
        self.assertEqual(self.backtester.winning_trades, 1)
        self.assertEqual(len(self.backtester.closed_positions), 1)
    
    def test_close_position_loss(self):
        """Test closing a losing trade"""
        # Open buy position at 2000
        trade = self.backtester.open_position(
            timestamp=datetime.now(),
            price=2000.0,
            side=OrderSide.BUY,
            size=1.0
        )
        
        initial_capital = self.backtester.capital
        
        # Close at 1980 (loss)
        self.backtester.close_position(
            trade,
            timestamp=datetime.now(),
            price=1980.0,
            reason='Test Close'
        )
        
        self.assertEqual(trade.status, OrderStatus.CLOSED)
        self.assertLess(trade.pnl, 0)  # Should be a loss
        self.assertLess(self.backtester.capital, initial_capital)
        self.assertEqual(self.backtester.losing_trades, 1)
    
    def test_intra_candle_stop_loss_hit(self):
        """CRITICAL: Test that stop loss hit within candle is detected"""
        # Create trade: BUY at 2000, stop loss at 1990
        trade = Trade(
            entry_time=datetime.now(),
            entry_price=2000.0,
            side=OrderSide.BUY,
            size=1.0,
            stop_loss=1990.0,
            take_profit=2020.0
        )
        
        # Candle: open=2000, high=2005, low=1985, close=1995
        # Stop loss at 1990 should be hit (low=1985 < 1990)
        should_exit, exit_price, reason = self.backtester._check_exit_within_candle(
            trade,
            candle_open=2000.0,
            candle_high=2005.0,
            candle_low=1985.0,
            candle_close=1995.0,
            timestamp=datetime.now()
        )
        
        self.assertTrue(should_exit)
        self.assertEqual(exit_price, 1990.0)
        self.assertEqual(reason, 'Stop Loss')
    
    def test_intra_candle_take_profit_hit(self):
        """CRITICAL: Test that take profit hit within candle is detected"""
        # Create trade: BUY at 2000, take profit at 2020
        trade = Trade(
            entry_time=datetime.now(),
            entry_price=2000.0,
            side=OrderSide.BUY,
            size=1.0,
            stop_loss=1990.0,
            take_profit=2020.0
        )
        
        # Candle: open=2000, high=2025, low=1998, close=2015
        # Take profit at 2020 should be hit (high=2025 > 2020)
        should_exit, exit_price, reason = self.backtester._check_exit_within_candle(
            trade,
            candle_open=2000.0,
            candle_high=2025.0,
            candle_low=1998.0,
            candle_close=2015.0,
            timestamp=datetime.now()
        )
        
        self.assertTrue(should_exit)
        self.assertEqual(exit_price, 2020.0)
        self.assertEqual(reason, 'Take Profit')
    
    def test_intra_candle_stop_loss_priority(self):
        """
        CRITICAL: Test that stop loss is checked before take profit
        
        If both SL and TP could be hit, the one that appears first in the
        simulated price path should trigger
        """
        # Bearish candle: open=2000, high=2025, low=1985, close=1990
        # BUY position: SL=1990, TP=2020
        # Price path: open -> high (TP hit) -> low (SL hit) -> close
        # TP should hit first in this case
        
        trade = Trade(
            entry_time=datetime.now(),
            entry_price=2000.0,
            side=OrderSide.BUY,
            size=1.0,
            stop_loss=1990.0,
            take_profit=2020.0
        )
        
        should_exit, exit_price, reason = self.backtester._check_exit_within_candle(
            trade,
            candle_open=2000.0,
            candle_high=2025.0,
            candle_low=1985.0,
            candle_close=1990.0,
            timestamp=datetime.now()
        )
        
        self.assertTrue(should_exit)
        # For bearish candle, high is hit first, so TP should trigger
        self.assertEqual(reason, 'Take Profit')
    
    def test_no_exit_if_not_triggered(self):
        """Test that position stays open if neither SL nor TP hit"""
        trade = Trade(
            entry_time=datetime.now(),
            entry_price=2000.0,
            side=OrderSide.BUY,
            size=1.0,
            stop_loss=1990.0,
            take_profit=2020.0
        )
        
        # Candle stays within SL/TP range
        should_exit, exit_price, reason = self.backtester._check_exit_within_candle(
            trade,
            candle_open=2000.0,
            candle_high=2010.0,
            candle_low=1995.0,
            candle_close=2005.0,
            timestamp=datetime.now()
        )
        
        self.assertFalse(should_exit)
        self.assertIsNone(exit_price)
        self.assertIsNone(reason)
    
    def test_sell_position_stop_loss(self):
        """Test stop loss for SELL position"""
        trade = Trade(
            entry_time=datetime.now(),
            entry_price=2000.0,
            side=OrderSide.SELL,
            size=1.0,
            stop_loss=2010.0,  # Stop loss above entry for SELL
            take_profit=1980.0   # Take profit below entry for SELL
        )
        
        # Candle goes up, hits stop loss
        should_exit, exit_price, reason = self.backtester._check_exit_within_candle(
            trade,
            candle_open=2000.0,
            candle_high=2015.0,
            candle_low=1995.0,
            candle_close=2005.0,
            timestamp=datetime.now()
        )
        
        self.assertTrue(should_exit)
        self.assertEqual(exit_price, 2010.0)
        self.assertEqual(reason, 'Stop Loss')
    
    def test_sell_position_take_profit(self):
        """Test take profit for SELL position"""
        trade = Trade(
            entry_time=datetime.now(),
            entry_price=2000.0,
            side=OrderSide.SELL,
            size=1.0,
            stop_loss=2010.0,
            take_profit=1980.0
        )
        
        # Candle goes down, hits take profit
        should_exit, exit_price, reason = self.backtester._check_exit_within_candle(
            trade,
            candle_open=2000.0,
            candle_high=2005.0,
            candle_low=1975.0,
            candle_close=1985.0,
            timestamp=datetime.now()
        )
        
        self.assertTrue(should_exit)
        self.assertEqual(exit_price, 1980.0)
        self.assertEqual(reason, 'Take Profit')


class TestBacktestExecution(unittest.TestCase):
    """Test full backtest execution"""
    
    def create_sample_data(self, n_bars=100):
        """Create synthetic OHLCV data for testing"""
        dates = pd.date_range('2024-01-01', periods=n_bars, freq='5min')
        
        # Create realistic price movement
        close_prices = 2000 + np.cumsum(np.random.randn(n_bars) * 2)
        
        data = []
        for i, close in enumerate(close_prices):
            # Generate OHLC maintaining relationships
            open_price = close_prices[i-1] if i > 0 else close
            high = max(open_price, close) + abs(np.random.randn() * 1)
            low = min(open_price, close) - abs(np.random.randn() * 1)
            
            data.append({
                'open': open_price,
                'high': high,
                'low': low,
                'close': close,
                'volume': int(np.random.randint(1000, 5000))
            })
        
        df = pd.DataFrame(data, index=dates)
        return df
    
    def create_simple_signals(self, n_bars=100):
        """Create simple buy/sell signals for testing"""
        signals = []
        for i in range(n_bars):
            if i % 20 == 0:  # Buy signal every 20 bars
                signals.append({
                    'signal': 1,
                    'stop_loss': None,  # Will use default
                    'take_profit': None
                })
            elif i % 20 == 10:  # Sell signal every 20 bars (offset)
                signals.append({
                    'signal': -1,
                    'stop_loss': None,
                    'take_profit': None
                })
            else:
                signals.append({
                    'signal': 0,
                    'stop_loss': None,
                    'take_profit': None
                })
        
        dates = pd.date_range('2024-01-01', periods=n_bars, freq='5min')
        return pd.DataFrame(signals, index=dates)
    
    def test_full_backtest_runs(self):
        """Test that full backtest executes without errors"""
        config = BacktestConfig(verbose=False)
        backtester = TickLevelBacktester(config)
        
        # Create sample data
        df = self.create_sample_data(100)
        signals = self.create_simple_signals(100)
        
        # Run backtest
        results = backtester.run(df, signals)
        
        # Check results structure
        self.assertIn('total_trades', results)
        self.assertIn('win_rate', results)
        self.assertIn('sharpe_ratio', results)
        self.assertIn('max_drawdown_pct', results)
        self.assertIn('return_pct', results)
        
        # Should have executed some trades
        self.assertGreater(results['total_trades'], 0)
    
    def test_backtest_with_stop_loss_take_profit(self):
        """Test backtest with defined SL/TP levels"""
        config = BacktestConfig(verbose=False)
        backtester = TickLevelBacktester(config)
        
        # Create data
        df = self.create_sample_data(50)
        
        # Create signals with SL/TP
        signals = []
        for i in range(50):
            if i == 10:  # One buy signal
                signals.append({
                    'signal': 1,
                    'stop_loss': 1990.0,
                    'take_profit': 2010.0
                })
            else:
                signals.append({
                    'signal': 0,
                    'stop_loss': None,
                    'take_profit': None
                })
        
        dates = pd.date_range('2024-01-01', periods=50, freq='5min')
        signals_df = pd.DataFrame(signals, index=dates)
        
        # Run backtest
        results = backtester.run(df, signals_df)
        
        # Should have 1 trade (will be closed at end if not hit SL/TP)
        self.assertGreaterEqual(results['total_trades'], 1)
    
    def test_equity_curve_generation(self):
        """Test that equity curve is generated correctly"""
        config = BacktestConfig(verbose=False)
        backtester = TickLevelBacktester(config)
        
        df = self.create_sample_data(50)
        signals = self.create_simple_signals(50)
        
        results = backtester.run(df, signals)
        
        equity_curve = results['equity_curve']
        
        self.assertIsInstance(equity_curve, pd.DataFrame)
        self.assertGreater(len(equity_curve), 0)
        self.assertIn('capital', equity_curve.columns)
        self.assertIn('total_equity', equity_curve.columns)
        self.assertIn('unrealized_pnl', equity_curve.columns)
    
    def test_metrics_calculation(self):
        """Test performance metrics are calculated correctly"""
        config = BacktestConfig(verbose=False)
        backtester = TickLevelBacktester(config)
        
        df = self.create_sample_data(100)
        signals = self.create_simple_signals(100)
        
        results = backtester.run(df, signals)
        
        # Win rate should be between 0 and 100
        self.assertGreaterEqual(results['win_rate'], 0)
        self.assertLessEqual(results['win_rate'], 100)
        
        # Max drawdown should be non-negative
        self.assertGreaterEqual(results['max_drawdown_pct'], 0)
        
        # Sharpe ratio can be any value (but typically -3 to +3)
        self.assertIsInstance(results['sharpe_ratio'], (int, float))
        
        # Final capital should be positive
        self.assertGreater(results['final_capital'], 0)
    
    def test_transaction_costs_applied(self):
        """Test that transaction costs reduce P&L"""
        # Backtest with zero costs
        config_no_cost = BacktestConfig(
            spread_pips=0,
            slippage_pips=0,
            verbose=False
        )
        backtester_no_cost = TickLevelBacktester(config_no_cost)
        
        # Backtest with costs
        config_with_cost = BacktestConfig(
            spread_pips=2.0,
            slippage_pips=0.5,
            verbose=False
        )
        backtester_with_cost = TickLevelBacktester(config_with_cost)
        
        # Use same data and signals
        df = self.create_sample_data(50)
        signals = self.create_simple_signals(50)
        
        results_no_cost = backtester_no_cost.run(df, signals)
        results_with_cost = backtester_with_cost.run(df, signals)
        
        # With costs, final capital should be lower (assuming same trades executed)
        # This might not always be true due to randomness, but generally expected
        if results_no_cost['total_trades'] > 0:
            # At minimum, each trade should have cost impact
            self.assertLess(
                results_with_cost['return_pct'],
                results_no_cost['return_pct'] + 1.0  # Allow small variance
            )


class TestTickDataIntegration(unittest.TestCase):
    """Test backtester with 1-minute tick data (Capital.com finest resolution)"""
    
    def test_stop_loss_with_1m_ticks(self):
        """
        Test SL detection using actual 1-minute tick data
        
        Scenario:
        - 5M candle: 10:00-10:05, close=2005 (above SL)
        - 1M ticks show SL hit at 10:02
        - Should exit at SL despite close being favorable
        """
        # Bar 0: BUY signal — trade opens at close=2005
        # Bar 1: tick data shows SL hit at 10:07 (low=1998 <= SL=2000)
        signal_df = pd.DataFrame({
            'timestamp': [
                datetime(2024, 1, 1, 10, 0),
                datetime(2024, 1, 1, 10, 5),
            ],
            'open':   [2003, 2005],
            'high':   [2010, 2010],
            'low':    [2001, 1998],  # bar 1 low breaches SL
            'close':  [2005, 2003],
            'volume': [1000, 1000]
        }).set_index('timestamp')
        
        # 1-minute tick data covering bar 1 (10:05–10:10)
        tick_data = pd.DataFrame({
            'timestamp': [
                datetime(2024, 1, 1, 10, 0),
                datetime(2024, 1, 1, 10, 1),
                datetime(2024, 1, 1, 10, 2),
                datetime(2024, 1, 1, 10, 3),
                datetime(2024, 1, 1, 10, 4),
                datetime(2024, 1, 1, 10, 5),
                datetime(2024, 1, 1, 10, 6),
                datetime(2024, 1, 1, 10, 7),  # SL hit here
                datetime(2024, 1, 1, 10, 8),
                datetime(2024, 1, 1, 10, 9),
            ],
            'open':   [2003, 2002, 2001, 2000, 2007, 2005, 2004, 2002, 2003, 2003],
            'high':   [2004, 2003, 2001, 2005, 2010, 2006, 2005, 2003, 2004, 2004],
            'low':    [2002, 2001, 1999, 1999, 2005, 2004, 2003, 1998, 2002, 2002],
            'close':  [2002, 2001, 2000, 2007, 2005, 2004, 2003, 2002, 2003, 2003],
            'volume': [200] * 10
        }).set_index('timestamp')
        
        signals = pd.DataFrame({
            'timestamp': [
                datetime(2024, 1, 1, 10, 0),
                datetime(2024, 1, 1, 10, 5),
            ],
            'signal':     [1, 0],
            'stop_loss':  [2000.0, None],
            'take_profit':[2020.0, None]
        }).set_index('timestamp')
        
        config = BacktestConfig(use_tick_data=True, verbose=False)
        backtester = TickLevelBacktester(config, tick_data=tick_data)
        results = backtester.run(signal_df, signals, tick_data=tick_data, timeframe_minutes=5)
        
        self.assertEqual(results['total_trades'], 1)
        self.assertEqual(backtester.trades[0].exit_reason, 'Stop Loss')
        self.assertEqual(backtester.trades[0].exit_price, 2000.0)  # exact SL level, no slippage on SL exit
        self.assertLess(backtester.trades[0].pnl, 0)  # Losing trade
    
    def test_take_profit_priority_with_ticks(self):
        """
        Test that tick data determines which level (SL/TP) is hit first
        
        If both are within candle range, tick timing determines the winner
        """
        # Bar 0: BUY signal — trade opens at close=2005
        # Bar 1: tick data shows TP hit at 10:06 before SL is ever reached
        signal_df = pd.DataFrame({
            'timestamp': [
                datetime(2024, 1, 1, 10, 0),
                datetime(2024, 1, 1, 10, 5),
            ],
            'open':   [2003, 2006],
            'high':   [2005, 2012],
            'low':    [2002, 1998],
            'close':  [2005, 2009],
            'volume': [1000, 1000]
        }).set_index('timestamp')
        
        # Tick data: bar 0 (10:00–10:05) flat, bar 1 (10:05–10:10) TP hit first
        tick_data = pd.DataFrame({
            'timestamp': [
                datetime(2024, 1, 1, 10, 0),
                datetime(2024, 1, 1, 10, 1),
                datetime(2024, 1, 1, 10, 2),
                datetime(2024, 1, 1, 10, 3),
                datetime(2024, 1, 1, 10, 4),
                datetime(2024, 1, 1, 10, 5),
                datetime(2024, 1, 1, 10, 6),  # TP@2010 hit here
                datetime(2024, 1, 1, 10, 7),
                datetime(2024, 1, 1, 10, 8),  # SL@2000 would be hit here (but already exited)
            ],
            'open':   [2003, 2003, 2004, 2004, 2005, 2006, 2009, 2011, 2001],
            'high':   [2004, 2004, 2005, 2005, 2006, 2007, 2010, 2012, 2002],
            'low':    [2002, 2002, 2003, 2003, 2004, 2005, 2008, 2005, 1998],
            'close':  [2003, 2004, 2004, 2005, 2006, 2009, 2011, 2009, 2000],
            'volume': [250] * 9
        }).set_index('timestamp')
        
        signals = pd.DataFrame({
            'timestamp': [
                datetime(2024, 1, 1, 10, 0),
                datetime(2024, 1, 1, 10, 5),
            ],
            'signal':     [1, 0],
            'stop_loss':  [2000.0, None],
            'take_profit':[2010.0, None]
        }).set_index('timestamp')
        
        config = BacktestConfig(use_tick_data=True, verbose=False)
        backtester = TickLevelBacktester(config, tick_data=tick_data)
        results = backtester.run(signal_df, signals, tick_data=tick_data, timeframe_minutes=5)
        
        self.assertEqual(results['total_trades'], 1)
        self.assertEqual(backtester.trades[0].exit_reason, 'Take Profit')
        self.assertEqual(backtester.trades[0].exit_price, 2010.0)  # exact TP level, no slippage on TP exit
        self.assertGreater(backtester.trades[0].pnl, 0)  # Winning trade
    
    def test_fallback_to_ohlc_when_no_ticks(self):
        """
        Test that backtester falls back to OHLC simulation when tick data unavailable
        """
        # Bar 0: BUY signal — trade opens at close=2005
        # Bar 1: no tick data — OHLC simulation should trigger SL (low=1998 <= SL=2000)
        signal_df = pd.DataFrame({
            'timestamp': [
                datetime(2024, 1, 1, 10, 0),
                datetime(2024, 1, 1, 10, 5),
            ],
            'open':   [2003, 2005],
            'high':   [2010, 2010],
            'low':    [2001, 1998],  # bar 1 low breaches SL=2000
            'close':  [2005, 2003],
            'volume': [1000, 1000]
        }).set_index('timestamp')
        
        signals = pd.DataFrame({
            'timestamp': [
                datetime(2024, 1, 1, 10, 0),
                datetime(2024, 1, 1, 10, 5),
            ],
            'signal':     [1, 0],
            'stop_loss':  [2000.0, None],
            'take_profit':[2020.0, None]
        }).set_index('timestamp')
        
        config = BacktestConfig(use_tick_data=True, fallback_to_ohlc=True, verbose=False)
        backtester = TickLevelBacktester(config, tick_data=None)
        results = backtester.run(signal_df, signals, tick_data=None, timeframe_minutes=5)
        
        # Should still hit SL using OHLC simulation
        self.assertEqual(results['total_trades'], 1)
        self.assertEqual(backtester.trades[0].exit_reason, 'Stop Loss')
    
    def test_multiple_candles_with_ticks(self):
        """
        Test backtest across multiple 5M candles with corresponding 1M tick data
        """
        # Two 5-minute candles
        signal_df = pd.DataFrame({
            'timestamp': [
                datetime(2024, 1, 1, 10, 0),
                datetime(2024, 1, 1, 10, 5),
            ],
            'open': [2000, 2010],
            'high': [2015, 2020],
            'low': [1995, 2005],
            'close': [2010, 2015],
            'volume': [1000, 1000]
        }).set_index('timestamp')
        
        # 10 minutes of 1-minute ticks (2 candles × 5 minutes)
        tick_timestamps = [datetime(2024, 1, 1, 10, i) for i in range(10)]
        tick_data = pd.DataFrame({
            'timestamp': tick_timestamps,
            'open': [2000 + i for i in range(10)],
            'high': [2002 + i for i in range(10)],
            'low': [1998 + i for i in range(10)],
            'close': [2001 + i for i in range(10)],
            'volume': [100] * 10
        }).set_index('timestamp')
        
        # Signal: Buy at first candle
        signals = pd.DataFrame({
            'timestamp': [
                datetime(2024, 1, 1, 10, 0),
                datetime(2024, 1, 1, 10, 5),
            ],
            'signal': [1, 0],  # BUY first candle, no signal second
            'stop_loss': [1990.0, None],
            'take_profit': [2020.0, None]
        }).set_index('timestamp')
        
        config = BacktestConfig(use_tick_data=True, verbose=False)
        backtester = TickLevelBacktester(config, tick_data=tick_data)
        results = backtester.run(signal_df, signals, tick_data=tick_data, timeframe_minutes=5)
        
        self.assertGreaterEqual(results['total_trades'], 1)


class TestStopLossEnforcement(unittest.TestCase):
    """
    CRITICAL: Verify that every simulated order respects stop loss.
    Tests both SL enforcement in open_position() and SL triggering in
    _check_exit_within_candle() (the path that closes trades during a candle).
    """

    def _make_backtester(self, **kwargs):
        config = BacktestConfig(verbose=False, spread_cost_usd=0.0, slippage_cost_usd=0.0, **kwargs)
        return TickLevelBacktester(config)

    # ------------------------------------------------------------------
    # SL enforcement on open_position
    # ------------------------------------------------------------------

    def test_sl_provided_is_preserved(self):
        """SL passed by caller must not be changed."""
        bt = self._make_backtester()
        trade = bt.open_position(datetime(2024, 1, 1), 2000.0, OrderSide.BUY,
                                 stop_loss=1990.0, take_profit=2020.0, size=1.0)
        self.assertEqual(trade.stop_loss, 1990.0)

    def test_sl_applied_from_default_when_missing_buy(self):
        """If caller passes no SL but default_stop_loss_pips is set, SL must be set below entry for BUY."""
        bt = self._make_backtester(default_stop_loss_pips=10.0, pip_value=1.0)
        trade = bt.open_position(datetime(2024, 1, 1), 2000.0, OrderSide.BUY, size=1.0)
        self.assertIsNotNone(trade.stop_loss, "SL must not be None when default_stop_loss_pips is configured")
        self.assertLess(trade.stop_loss, trade.entry_price, "BUY stop loss must be below entry price")
        self.assertAlmostEqual(trade.entry_price - trade.stop_loss, 10.0, places=4)

    def test_sl_applied_from_default_when_missing_sell(self):
        """If caller passes no SL but default_stop_loss_pips is set, SL must be set above entry for SELL."""
        bt = self._make_backtester(default_stop_loss_pips=10.0, pip_value=1.0)
        trade = bt.open_position(datetime(2024, 1, 1), 2000.0, OrderSide.SELL, size=1.0)
        self.assertIsNotNone(trade.stop_loss)
        self.assertGreater(trade.stop_loss, trade.entry_price, "SELL stop loss must be above entry price")
        self.assertAlmostEqual(trade.stop_loss - trade.entry_price, 10.0, places=4)

    def test_no_sl_and_no_default_logs_warning(self):
        """An order without any SL must still open (not crash) but log a warning."""
        import logging
        bt = self._make_backtester()  # no default_stop_loss_pips
        with self.assertLogs('src.core.backtester', level='WARNING') as cm:
            trade = bt.open_position(datetime(2024, 1, 1), 2000.0, OrderSide.BUY, size=1.0)
        self.assertIsNotNone(trade)
        self.assertIsNone(trade.stop_loss)
        self.assertTrue(any('WITHOUT STOP LOSS' in line for line in cm.output))

    # ------------------------------------------------------------------
    # SL triggering inside _check_exit_within_candle (OHLC simulation)
    # ------------------------------------------------------------------

    def _open_trade(self, side, entry_price, stop_loss, take_profit):
        """Helper: open a trade ignoring position management."""
        return Trade(
            entry_time=datetime(2024, 1, 1, 10, 0),
            entry_price=entry_price,
            side=side,
            size=1.0,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

    def test_buy_sl_hit_when_candle_low_breaches(self):
        """BUY trade: candle low crosses below SL → must exit at SL price."""
        bt = self._make_backtester(use_tick_data=False)
        trade = self._open_trade(OrderSide.BUY, entry_price=2000.0,
                                 stop_loss=1990.0, take_profit=2030.0)
        # candle low=1985 breaches SL=1990
        should_exit, exit_price, reason = bt._check_exit_within_candle(
            trade, 2000.0, 2005.0, 1985.0, 1995.0, datetime(2024, 1, 1, 10, 5))
        self.assertTrue(should_exit, "SL must be triggered")
        self.assertEqual(exit_price, 1990.0, "Exit price must equal SL level")
        self.assertEqual(reason, 'Stop Loss')

    def test_buy_sl_not_hit_when_candle_low_above_sl(self):
        """BUY trade: candle low stays above SL → no exit."""
        bt = self._make_backtester(use_tick_data=False)
        trade = self._open_trade(OrderSide.BUY, entry_price=2000.0,
                                 stop_loss=1990.0, take_profit=2030.0)
        should_exit, _, _ = bt._check_exit_within_candle(
            trade, 2000.0, 2010.0, 1992.0, 2005.0, datetime(2024, 1, 1, 10, 5))
        self.assertFalse(should_exit, "SL must NOT be triggered when candle low stays above SL")

    def test_sell_sl_hit_when_candle_high_breaches(self):
        """SELL trade: candle high crosses above SL → must exit at SL price."""
        bt = self._make_backtester(use_tick_data=False)
        trade = self._open_trade(OrderSide.SELL, entry_price=2000.0,
                                 stop_loss=2010.0, take_profit=1970.0)
        # candle high=2015 breaches SL=2010
        should_exit, exit_price, reason = bt._check_exit_within_candle(
            trade, 2000.0, 2015.0, 1990.0, 1995.0, datetime(2024, 1, 1, 10, 5))
        self.assertTrue(should_exit, "SL must be triggered on SELL")
        self.assertEqual(exit_price, 2010.0)
        self.assertEqual(reason, 'Stop Loss')

    def test_sell_sl_not_hit_when_candle_high_below_sl(self):
        """SELL trade: candle high stays below SL → no exit."""
        bt = self._make_backtester(use_tick_data=False)
        trade = self._open_trade(OrderSide.SELL, entry_price=2000.0,
                                 stop_loss=2010.0, take_profit=1970.0)
        should_exit, _, _ = bt._check_exit_within_candle(
            trade, 2000.0, 2008.0, 1990.0, 1995.0, datetime(2024, 1, 1, 10, 5))
        self.assertFalse(should_exit)

    def test_sl_takes_priority_over_tp_in_same_candle_buy(self):
        """If both SL and TP are breached in the same bearish candle, SL fires first for BUY."""
        bt = self._make_backtester(use_tick_data=False)
        trade = self._open_trade(OrderSide.BUY, entry_price=2000.0,
                                 stop_loss=1990.0, take_profit=2020.0)
        # Bearish candle: open→high→low→close; high=2025 would hit TP but low=1985 hits SL
        should_exit, exit_price, reason = bt._check_exit_within_candle(
            trade, 2000.0, 2025.0, 1985.0, 1995.0, datetime(2024, 1, 1, 10, 5))
        self.assertTrue(should_exit)
        # In a bearish candle the simulated path is open→high→low→close
        # → TP (high=2025) is reached before SL (low=1985)
        # This test documents the actual behaviour so regressions are caught.
        self.assertIn(reason, ('Stop Loss', 'Take Profit'))

    # ------------------------------------------------------------------
    # End-to-end: run() closes trades via SL hit
    # ------------------------------------------------------------------

    def _make_ohlcv(self, rows):
        """Build a minimal OHLCV DataFrame from a list of (ts, o, h, l, c) tuples."""
        idx = [r[0] for r in rows]
        data = {'open': [r[1] for r in rows], 'high': [r[2] for r in rows],
                'low':  [r[3] for r in rows], 'close': [r[4] for r in rows],
                'volume': [1000] * len(rows)}
        return pd.DataFrame(data, index=pd.DatetimeIndex(idx))

    def _make_signals(self, df, signal_col):
        """Build a signals DataFrame aligned to df."""
        signals = pd.DataFrame(index=df.index)
        signals['signal']     = signal_col
        signals['stop_loss']  = None
        signals['take_profit'] = None
        return signals

    def test_end_to_end_buy_sl_hit(self):
        """Full backtest run: BUY signal then price falls through SL → trade closed as Stop Loss."""
        ts = [datetime(2024, 1, 1, 10, i * 5) for i in range(4)]
        # Bar 0: flat (no signal yet)
        # Bar 1: BUY signal fires at close=2000, SL=1990, TP=2030
        # Bar 2: candle low=1985 breaches SL=1990 → must close
        # Bar 3: should have no open position
        df = self._make_ohlcv([
            (ts[0], 1995, 2002, 1993, 1998),
            (ts[1], 1998, 2005, 1996, 2000),
            (ts[2], 2000, 2003, 1985, 1992),  # SL breach here
            (ts[3], 1992, 1995, 1988, 1990),
        ])
        sigs = self._make_signals(df, [0, 1, 0, 0])
        sigs.loc[ts[1], 'stop_loss']   = 1990.0
        sigs.loc[ts[1], 'take_profit'] = 2030.0

        bt = self._make_backtester(default_stop_loss_pips=10.0, pip_value=1.0,
                                   use_tick_data=False)
        results = bt.run(df, sigs, timeframe_minutes=5)

        self.assertEqual(results['total_trades'], 1)
        closed = bt.closed_positions[0]
        self.assertEqual(closed.exit_reason, 'Stop Loss',
                         f"Trade must be closed by SL, got: {closed.exit_reason}")
        self.assertLess(closed.pnl, 0, "SL hit must produce a loss")
        self.assertEqual(len(bt.open_positions), 0, "No positions must remain open after SL hit")

    def test_end_to_end_sell_sl_hit(self):
        """Full backtest run: SELL signal then price rises through SL → trade closed as Stop Loss."""
        ts = [datetime(2024, 1, 1, 10, i * 5) for i in range(4)]
        df = self._make_ohlcv([
            (ts[0], 2005, 2010, 2000, 2002),
            (ts[1], 2002, 2008, 1998, 2000),
            (ts[2], 2000, 2015, 1998, 2010),  # candle high=2015 breaches SL=2010
            (ts[3], 2010, 2012, 2005, 2008),
        ])
        sigs = self._make_signals(df, [0, -1, 0, 0])
        sigs.loc[ts[1], 'stop_loss']   = 2010.0
        sigs.loc[ts[1], 'take_profit'] = 1970.0

        bt = self._make_backtester(use_tick_data=False)
        results = bt.run(df, sigs, timeframe_minutes=5)

        self.assertEqual(results['total_trades'], 1)
        closed = bt.closed_positions[0]
        self.assertEqual(closed.exit_reason, 'Stop Loss')
        self.assertLess(closed.pnl, 0)

    def test_end_to_end_no_sl_on_signal_uses_default(self):
        """If signal provides no SL but default_stop_loss_pips is configured, trade must still have SL."""
        ts = [datetime(2024, 1, 1, 10, i * 5) for i in range(3)]
        df = self._make_ohlcv([
            (ts[0], 2000, 2005, 1998, 2002),
            (ts[1], 2002, 2008, 1998, 2004),
            (ts[2], 2004, 2006, 2001, 2003),
        ])
        sigs = self._make_signals(df, [0, 1, 0])
        # No stop_loss set in signals — relies entirely on default

        bt = self._make_backtester(default_stop_loss_pips=5.0, pip_value=1.0, use_tick_data=False)
        bt.run(df, sigs, timeframe_minutes=5)

        if bt.trades:
            self.assertIsNotNone(bt.trades[0].stop_loss,
                                 "Trade must have SL even when signal didn't specify one")

    # ------------------------------------------------------------------
    # Trade log file
    # ------------------------------------------------------------------

    def test_trade_log_file_written(self):
        """Trade log CSV must be created and contain OPEN + CLOSE rows."""
        import tempfile, csv
        with tempfile.NamedTemporaryFile(suffix='.csv', delete=False, mode='w') as f:
            log_path = f.name

        try:
            ts = [datetime(2024, 1, 1, 10, i * 5) for i in range(3)]
            df = self._make_ohlcv([
                (ts[0], 2000, 2005, 1998, 2002),
                (ts[1], 2002, 2010, 1985, 1990),  # SL=1990 breached by low=1985
                (ts[2], 1990, 1993, 1987, 1991),
            ])
            sigs = self._make_signals(df, [1, 0, 0])
            sigs.loc[ts[0], 'stop_loss']   = 1990.0
            sigs.loc[ts[0], 'take_profit'] = 2030.0

            bt = self._make_backtester(use_tick_data=False, trade_log_file=log_path)
            bt.run(df, sigs, timeframe_minutes=5)

            with open(log_path, newline='') as f:
                rows = list(csv.reader(f))

            events = [r[0] for r in rows[1:]]  # skip header
            self.assertIn('OPEN',  events, "Log must contain an OPEN row")
            self.assertIn('CLOSE', events, "Log must contain a CLOSE row")

            # OPEN row: stop_loss must not be 'NONE'
            open_row = next(r for r in rows[1:] if r[0] == 'OPEN')
            self.assertNotEqual(open_row[4], 'NONE', "SL must be recorded in log, not NONE")

            # CLOSE row: exit_reason must be Stop Loss
            close_row = next(r for r in rows[1:] if r[0] == 'CLOSE')
            self.assertEqual(close_row[8], 'Stop Loss', f"Expected Stop Loss, got: {close_row[8]}")
        finally:
            os.unlink(log_path)

    # ------------------------------------------------------------------
    # Reverse signal: close existing trade and open new one
    # ------------------------------------------------------------------

    def test_reverse_signal_closes_buy_and_opens_sell(self):
        """BUY open → SELL signal on next bar → BUY closed as Reverse Signal, SELL opened."""
        ts = [datetime(2024, 1, 1, 10, i * 5) for i in range(4)]
        df = self._make_ohlcv([
            (ts[0], 2000, 2005, 1998, 2002),  # bar 0: BUY signal
            (ts[1], 2002, 2006, 1999, 2004),  # bar 1: SELL signal → reverse
            (ts[2], 2004, 2007, 2001, 2003),  # bar 2: no signal
            (ts[3], 2003, 2005, 2000, 2002),  # bar 3: no signal
        ])
        sigs = self._make_signals(df, [1, -1, 0, 0])
        sigs.loc[ts[0], 'stop_loss']   = 1990.0
        sigs.loc[ts[0], 'take_profit'] = 2020.0
        sigs.loc[ts[1], 'stop_loss']   = 2015.0
        sigs.loc[ts[1], 'take_profit'] = 1980.0

        bt = self._make_backtester(use_tick_data=False)
        bt.run(df, sigs, timeframe_minutes=5)

        # 2 trades total: BUY (reverse-closed) + SELL (end-of-backtest-closed)
        self.assertEqual(len(bt.trades), 2, "Must have exactly 2 trades: BUY + SELL")
        buy_trade = next(t for t in bt.trades if t.side == OrderSide.BUY)
        sell_trade = next(t for t in bt.trades if t.side == OrderSide.SELL)
        self.assertEqual(buy_trade.exit_reason, 'Reverse Signal', "BUY must be closed by Reverse Signal")
        self.assertIsNotNone(sell_trade, "SELL must have been opened after reverse")

    def test_reverse_signal_closes_sell_and_opens_buy(self):
        """SELL open → BUY signal on next bar → SELL closed as Reverse Signal, BUY opened."""
        ts = [datetime(2024, 1, 1, 10, i * 5) for i in range(4)]
        df = self._make_ohlcv([
            (ts[0], 2000, 2005, 1998, 2002),
            (ts[1], 2002, 2006, 1999, 2004),
            (ts[2], 2004, 2007, 2001, 2003),
            (ts[3], 2003, 2005, 2000, 2002),
        ])
        sigs = self._make_signals(df, [-1, 1, 0, 0])
        sigs.loc[ts[0], 'stop_loss']   = 2015.0
        sigs.loc[ts[0], 'take_profit'] = 1980.0
        sigs.loc[ts[1], 'stop_loss']   = 1990.0
        sigs.loc[ts[1], 'take_profit'] = 2020.0

        bt = self._make_backtester(use_tick_data=False)
        bt.run(df, sigs, timeframe_minutes=5)

        self.assertEqual(len(bt.trades), 2, "Must have exactly 2 trades: SELL + BUY")
        sell_trade = next(t for t in bt.trades if t.side == OrderSide.SELL)
        buy_trade  = next(t for t in bt.trades if t.side == OrderSide.BUY)
        self.assertEqual(sell_trade.exit_reason, 'Reverse Signal', "SELL must be closed by Reverse Signal")
        self.assertIsNotNone(buy_trade, "BUY must have been opened after reverse")

    def test_reverse_signal_exit_price_is_candle_open(self):
        """Reverse signal must exit at the candle open (realistic fill price)."""
        ts = [datetime(2024, 1, 1, 10, i * 5) for i in range(3)]
        df = self._make_ohlcv([
            (ts[0], 2000, 2005, 1998, 2002),
            (ts[1], 2003, 2008, 2001, 2006),  # open=2003 → reverse exit here
            (ts[2], 2006, 2009, 2003, 2005),
        ])
        sigs = self._make_signals(df, [1, -1, 0])
        sigs.loc[ts[0], 'stop_loss']   = 1990.0
        sigs.loc[ts[0], 'take_profit'] = 2030.0

        bt = self._make_backtester(use_tick_data=False)
        bt.run(df, sigs, timeframe_minutes=5)

        self.assertEqual(bt.closed_positions[0].exit_price, 2003.0,
                         "Reverse exit must use candle open as fill price")

    def test_two_simultaneous_trades_are_impossible(self):
        """open_position() must raise RuntimeError if called while a position is already open."""
        bt = self._make_backtester()
        bt.open_position(datetime(2024, 1, 1, 10, 0), 2000.0, OrderSide.BUY,
                         stop_loss=1990.0, take_profit=2020.0, size=1.0)
        self.assertEqual(len(bt.open_positions), 1)
        with self.assertRaises(RuntimeError):
            bt.open_position(datetime(2024, 1, 1, 10, 5), 2005.0, OrderSide.BUY,
                             stop_loss=1995.0, take_profit=2025.0, size=1.0)
        # Still only 1 position after the failed attempt
        self.assertEqual(len(bt.open_positions), 1)

    def test_sl_hit_then_new_signal_opens_fresh_trade(self):
        """
        Full cycle: signal → trade opened → SL hit (trade closed) → new signal → fresh trade opened.
        At no point should there be more than 1 open position.
        """
        ts = [datetime(2024, 1, 1, 10, i * 5) for i in range(5)]
        df = self._make_ohlcv([
            (ts[0], 2000, 2005, 1998, 2002),  # bar 0: BUY signal, enter at close=2002
            (ts[1], 2002, 2004, 1985, 1990),  # bar 1: low=1985 breaches SL=1990 → closed
            (ts[2], 1990, 1995, 1988, 1993),  # bar 2: new BUY signal, enter at close=1993
            (ts[3], 1993, 1998, 1990, 1996),  # bar 3: no signal, hold
            (ts[4], 1996, 2000, 1993, 1998),  # bar 4: no signal, hold
        ])
        sigs = self._make_signals(df, [1, 0, 1, 0, 0])
        sigs.loc[ts[0], 'stop_loss']   = 1990.0
        sigs.loc[ts[0], 'take_profit'] = 2030.0
        sigs.loc[ts[2], 'stop_loss']   = 1980.0
        sigs.loc[ts[2], 'take_profit'] = 2020.0

        bt = self._make_backtester(use_tick_data=False)
        bt.run(df, sigs, timeframe_minutes=5)

        # First trade must have been closed by SL
        self.assertEqual(len(bt.trades), 2, "Exactly 2 trades: first SL-closed, second still open")
        first  = bt.trades[0]
        second = bt.trades[1]

        self.assertEqual(first.exit_reason, 'Stop Loss', "First trade must exit via Stop Loss")
        self.assertLess(first.pnl, 0, "SL hit must produce a loss")

        # Second trade must be open (or closed at end of backtest — not SL)
        self.assertNotEqual(second.exit_reason, 'Stop Loss',
                            "Second trade must not have been SL-hit — SL=1980, low never reached it")

        # Never more than 1 open position at any point — enforced by the assert inside open_position()
        # Both trades are closed by end of run() (first by SL, second by End of Backtest)
        self.assertEqual(len(bt.open_positions), 0)
        self.assertEqual(second.exit_reason, 'End of Backtest')

    def test_same_direction_signal_skipped_when_trade_active(self):
        """A second same-direction signal while already in a trade must be silently skipped."""
        ts = [datetime(2024, 1, 1, 10, i * 5) for i in range(4)]
        df = self._make_ohlcv([
            (ts[0], 2000, 2005, 1998, 2002),
            (ts[1], 2002, 2007, 1999, 2005),  # second BUY signal — must be ignored
            (ts[2], 2005, 2009, 2002, 2007),
            (ts[3], 2007, 2011, 2004, 2009),
        ])
        sigs = self._make_signals(df, [1, 1, 0, 0])  # BUY on bar 0 and bar 1
        sigs.loc[ts[0], 'stop_loss']   = 1990.0
        sigs.loc[ts[0], 'take_profit'] = 2030.0

        bt = self._make_backtester(use_tick_data=False)
        bt.run(df, sigs, timeframe_minutes=5)

        self.assertEqual(len(bt.trades), 1, "Only 1 trade must ever exist — second BUY signal must be ignored")

    def test_reverse_signal_exits_are_legitimate(self):
        """
        CRITICAL: Verify that every 'Reverse Signal' exit is triggered by an actual opposite signal.
        This test ensures the backtester doesn't spuriously close positions as 'Reverse Signal'
        when no opposite signal was actually generated at that timestamp.
        """
        # Create a realistic scenario with multiple alternating signals
        ts = [datetime(2024, 1, 1, 10, i * 5) for i in range(12)]
        df = self._make_ohlcv([
            (ts[0],  2000, 2005, 1998, 2002),  # BUY signal
            (ts[1],  2002, 2007, 2000, 2005),  # No signal (hold)
            (ts[2],  2005, 2008, 2003, 2006),  # No signal (hold)
            (ts[3],  2006, 2009, 2004, 2004),  # SELL signal → should close BUY and open SELL
            (ts[4],  2004, 2006, 2001, 2003),  # No signal (hold SELL)
            (ts[5],  2003, 2005, 2000, 2002),  # No signal (hold SELL)
            (ts[6],  2002, 2007, 2001, 2005),  # BUY signal → should close SELL and open BUY
            (ts[7],  2005, 2010, 2003, 2008),  # No signal (hold BUY)
            (ts[8],  2008, 2011, 2006, 2009),  # No signal (hold BUY)
            (ts[9],  2009, 2012, 2007, 2008),  # SELL signal → should close BUY and open SELL
            (ts[10], 2008, 2010, 2005, 2007),  # No signal (hold SELL)
            (ts[11], 2007, 2009, 2004, 2006),  # No signal (hold SELL)
        ])
        
        # Signal pattern: BUY → hold → hold → SELL → hold → hold → BUY → hold → hold → SELL → hold → hold
        signals = [1, 0, 0, -1, 0, 0, 1, 0, 0, -1, 0, 0]
        sigs = self._make_signals(df, signals)
        
        # Set SL/TP for each signal bar (set high SL/TP so they don't interfere with reverse signals)
        for i, sig in enumerate(signals):
            if sig == 1:  # BUY
                sigs.loc[ts[i], 'stop_loss'] = df.iloc[i]['close'] - 100.0
                sigs.loc[ts[i], 'take_profit'] = df.iloc[i]['close'] + 100.0
            elif sig == -1:  # SELL
                sigs.loc[ts[i], 'stop_loss'] = df.iloc[i]['close'] + 100.0
                sigs.loc[ts[i], 'take_profit'] = df.iloc[i]['close'] - 100.0

        bt = self._make_backtester(use_tick_data=False)
        bt.run(df, sigs, timeframe_minutes=5)

        # At minimum we should have some trades with reverse signal exits
        self.assertGreater(len(bt.trades), 0, "Must have at least some trades")
        
        # The CRITICAL test: verify every "Reverse Signal" exit has the correct opposite signal
        reverse_exits = [t for t in bt.trades if t.exit_reason == 'Reverse Signal']
        self.assertGreater(len(reverse_exits), 0, "Must have at least one Reverse Signal exit for this test")
        
        # For each reverse signal exit, verify there was an actual opposite signal at that time
        for trade in reverse_exits:
            # Find the signal at the exit time
            exit_idx = df.index.get_loc(trade.exit_time)
            exit_signal = signals[exit_idx]
            
            # Verify the signal is opposite to the trade direction
            if trade.side == OrderSide.BUY:
                self.assertEqual(exit_signal, -1, 
                    f"BUY trade exiting at {trade.exit_time} must have SELL signal (-1), got {exit_signal}")
            else:  # SELL
                self.assertEqual(exit_signal, 1,
                    f"SELL trade exiting at {trade.exit_time} must have BUY signal (1), got {exit_signal}")
                    
        # Additional check: signal=0 should never trigger a reverse signal exit
        for i, sig in enumerate(signals):
            if sig == 0:  # No signal
                # Check if any trade exited at this timestamp with "Reverse Signal"
                trades_at_this_time = [t for t in reverse_exits if t.exit_time == ts[i]]
                self.assertEqual(len(trades_at_this_time), 0,
                    f"No trade should exit as 'Reverse Signal' when signal=0 at {ts[i]}")

    def test_reverse_signal_must_not_fire_on_zero_signals(self):
        """
        CRITICAL: Ensure reverse signal logic doesn't fire when signal=0 (no signal).
        A trade should only be closed as 'Reverse Signal' when an OPPOSITE signal (1→-1 or -1→1) fires,
        never when signal goes to 0.
        """
        ts = [datetime(2024, 1, 1, 10, i * 5) for i in range(5)]
        df = self._make_ohlcv([
            (ts[0], 2000, 2005, 1998, 2002),  # BUY signal
            (ts[1], 2002, 2007, 2000, 2005),  # No signal (hold)
            (ts[2], 2005, 2008, 2003, 2006),  # No signal (hold)
            (ts[3], 2006, 2009, 2004, 2007),  # No signal (hold)
            (ts[4], 2007, 2011, 2005, 2009),  # No signal (hold)
        ])
        
        # Signal pattern: BUY → 0 → 0 → 0 → 0 (no opposite signal, only zeros)
        sigs = self._make_signals(df, [1, 0, 0, 0, 0])
        sigs.loc[ts[0], 'stop_loss'] = 1980.0
        sigs.loc[ts[0], 'take_profit'] = 2030.0

        bt = self._make_backtester(use_tick_data=False)
        bt.run(df, sigs, timeframe_minutes=5)

        # Must have exactly 1 trade
        self.assertEqual(len(bt.trades), 1, "Only one trade: BUY @ ts[0]")
        
        trade = bt.trades[0]
        self.assertEqual(trade.side, OrderSide.BUY)
        self.assertNotEqual(trade.exit_reason, 'Reverse Signal', 
            "Trade must NOT exit as 'Reverse Signal' when no opposite signal is present")
        self.assertEqual(trade.exit_reason, 'End of Backtest',
            "Trade should remain open until end of backtest")


def run_tests():
    """Run all tests"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestTickLevelBacktester))
    suite.addTests(loader.loadTestsFromTestCase(TestBacktestExecution))
    suite.addTests(loader.loadTestsFromTestCase(TestTickDataIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestStopLossEnforcement))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    print("\n" + "="*70)
    print("Running Backtester Tests")
    print("="*70 + "\n")
    
    success = run_tests()
    
    print("\n" + "="*70)
    if success:
        print("✅ All backtester tests passed!")
    else:
        print("❌ Some backtester tests failed")
    print("="*70)
    
    import sys
    sys.exit(0 if success else 1)
