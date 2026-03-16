"""
Test cases for 1-second tick-level backtester
"""

import unittest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.tick_backtester import TickLevelBacktesterWithS1
from src.core.backtester import BacktestConfig, OrderSide, OrderStatus


class TestS1TickData(unittest.TestCase):
    """Test 1-second tick data handling"""
    
    @unittest.skip("data_fetcher module removed - needs update to cache_data")
    def test_s1_resolution_available(self):
        """Test that S1 resolution is available in data fetcher"""
        from src.data_fetcher import CapitalComDataFetcher
        
        fetcher = CapitalComDataFetcher(
            api_key='test',
            username='test',
            password='test',
            capkey='test'
        )
        
        self.assertIn('S1', fetcher.RESOLUTIONS)
        self.assertEqual(fetcher.RESOLUTIONS['S1'], 'SECOND')
    
    @unittest.skip("data_fetcher module removed - needs update to cache_data")
    def test_s1_max_bars(self):
        """Test S1 maximum bars configuration"""
        from src.data_fetcher import CapitalComDataFetcher
        
        fetcher = CapitalComDataFetcher(
            api_key='test',
            username='test',
            password='test',
            capkey='test'
        )
        
        self.assertIn('S1', fetcher.MAX_BARS_AVAILABLE)
        # S1 should have reasonable limit (typically 1 hour = 3600 seconds)
        self.assertGreater(fetcher.MAX_BARS_AVAILABLE['S1'], 1000)


class TestTickLevelBacktestWithS1(unittest.TestCase):
    """Test tick-level backtesting with 1-second bars"""
    
    def create_m5_data(self, n_bars=10):
        """Create M5 (5-minute) sample data"""
        dates = pd.date_range('2024-01-01 10:00', periods=n_bars, freq='5min')
        
        close_prices = 2000 + np.cumsum(np.random.randn(n_bars) * 2)
        
        data = []
        for i, close in enumerate(close_prices):
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
        
        return pd.DataFrame(data, index=dates)
    
    def create_s1_data_for_m5(self, m5_df):
        """Create 1-second data matching M5 periods"""
        all_seconds = []
        
        for i in range(len(m5_df)):
            period_start = m5_df.index[i]
            period_end = period_start + timedelta(minutes=5)
            
            # Create 300 seconds (5 minutes) of data
            seconds = pd.date_range(period_start, period_end, freq='1s')[:-1]  # Exclude last second
            
            # Interpolate prices within the M5 candle
            m5_open = m5_df.iloc[i]['open']
            m5_high = m5_df.iloc[i]['high']
            m5_low = m5_df.iloc[i]['low']
            m5_close = m5_df.iloc[i]['close']
            
            # Simple price path: open -> low -> high -> close
            prices = np.linspace(m5_open, m5_close, len(seconds))
            
            # Add some volatility
            prices += np.random.randn(len(seconds)) * 0.1
            
            # Ensure high and low are hit
            prices[len(prices)//4] = m5_low
            prices[len(prices)//2] = m5_high
            
            for j, (timestamp, price) in enumerate(zip(seconds, prices)):
                all_seconds.append({
                    'open': prices[j-1] if j > 0 else m5_open,
                    'high': price + abs(np.random.randn() * 0.05),
                    'low': price - abs(np.random.randn() * 0.05),
                    'close': price,
                    'volume': int(np.random.randint(10, 50))
                })
        
        dates = pd.date_range(m5_df.index[0], m5_df.index[-1] + timedelta(minutes=5), freq='1s')[:-1]
        return pd.DataFrame(all_seconds, index=dates[:len(all_seconds)])
    
    def create_simple_signals(self, m5_df):
        """Create simple signals for testing"""
        signals = []
        for i in range(len(m5_df)):
            if i == 2:  # Buy signal at 3rd bar
                signals.append({
                    'signal': 1,
                    'stop_loss': m5_df.iloc[i]['close'] * 0.995,
                    'take_profit': m5_df.iloc[i]['close'] * 1.01
                })
            else:
                signals.append({
                    'signal': 0,
                    'stop_loss': None,
                    'take_profit': None
                })
        
        return pd.DataFrame(signals, index=m5_df.index)
    
    def test_backtest_with_s1_data_runs(self):
        """Test that backtest with S1 data executes without errors"""
        config = BacktestConfig(verbose=False)
        backtester = TickLevelBacktesterWithS1(config)
        
        # Create test data
        m5_df = self.create_m5_data(10)
        s1_df = self.create_s1_data_for_m5(m5_df)
        signals_df = self.create_simple_signals(m5_df)
        
        # Run backtest
        results = backtester.run_with_tick_data(m5_df, signals_df, s1_df)
        
        # Check results
        self.assertIsNotNone(results)
        self.assertIn('total_trades', results)
        self.assertIn('win_rate', results)
    
    def test_stop_loss_detected_in_s1_ticks(self):
        """
        CRITICAL: Test that stop loss is detected using S1 tick data.

        The backtester opens a position AFTER processing all ticks for the
        signal candle, so the SL can only be detected starting from the
        NEXT candle's tick window (10:05-10:10).
        """
        config = BacktestConfig(verbose=False)
        backtester = TickLevelBacktesterWithS1(config)

        # Create M5 data: 3 bars
        m5_dates = pd.date_range('2024-01-01 10:00', periods=3, freq='5min')
        m5_df = pd.DataFrame({
            'open':   [2000, 2010, 2005],
            'high':   [2015, 2020, 2015],
            'low':    [1998, 1993, 2000],   # 10:05 bar dips below SL=1995
            'close':  [2010, 2015, 2010],
            'volume': [1000, 1000, 1000]
        }, index=m5_dates)

        # Signal: BUY at 10:00, SL=1995, TP=2030
        signals_df = pd.DataFrame({
            'signal':      [1,    0,    0   ],
            'stop_loss':   [1995, None, None],
            'take_profit': [2030, None, None]
        }, index=m5_dates)

        # S1 data covering 10:00-10:15 (900 seconds):
        #   10:00-10:05 (i=0..299)  : stable at 2010 — position opens at end of this window
        #   10:05-10:07:30 (i=300..449): drops 2010→1990, crossing SL=1995 ~10:07:00
        #   10:07:30-10:15 (i=450+) : stable at 2000
        s1_dates = pd.date_range('2024-01-01 10:00:00', '2024-01-01 10:15:00', freq='1s')[:-1]
        n_secs = len(s1_dates)

        prices = []
        for i in range(n_secs):
            if i < 300:
                price = 2010.0
            elif i < 450:
                price = 2010 - (20 * (i - 300) / 150)   # drops to 1990 by 10:07:30
            else:
                price = 2000.0
            prices.append(price)

        s1_df = pd.DataFrame({
            'open':   prices,
            'high':   [p + 0.5 for p in prices],
            'low':    [p - 0.5 for p in prices],
            'close':  prices,
            'volume': [50] * n_secs
        }, index=s1_dates)

        results = backtester.run_with_tick_data(m5_df, signals_df, s1_df)

        # Should have exactly 1 trade that hit stop loss
        self.assertEqual(results['total_trades'], 1)

        trades_df = backtester.get_trades_df()
        self.assertEqual(len(trades_df), 1)

        trade = trades_df.iloc[0]
        self.assertEqual(trade['exit_reason'], 'Stop Loss')

        # Exit should be in the 10:05-10:08 window
        exit_time = pd.to_datetime(trade['exit_time'])
        self.assertGreaterEqual(exit_time, pd.Timestamp('2024-01-01 10:05:00'))
        self.assertLess(exit_time, pd.Timestamp('2024-01-01 10:08:00'))
    
    def test_take_profit_detected_in_s1_ticks(self):
        """Test that take profit is detected at specific second"""
        config = BacktestConfig(verbose=False)
        backtester = TickLevelBacktesterWithS1(config)
        
        # Create M5 data
        m5_dates = pd.date_range('2024-01-01 10:00', periods=3, freq='5min')
        m5_df = pd.DataFrame({
            'open': [2000, 2010, 2025],
            'high': [2015, 2025, 2030],
            'low': [1998, 2005, 2020],
            'close': [2010, 2020, 2025],
            'volume': [1000, 1000, 1000]
        }, index=m5_dates)
        
        # Signal: BUY at 10:00, SL=1990, TP=2020
        signals_df = pd.DataFrame({
            'signal': [1, 0, 0],
            'stop_loss': [1990, None, None],
            'take_profit': [2020, None, None]
        }, index=m5_dates)
        
        # Create S1 data where price hits 2020 at exactly 10:06:00 (in second M5 candle)
        s1_dates = pd.date_range('2024-01-01 10:00:00', '2024-01-01 10:15:00', freq='1s')[:-1]
        n_secs = len(s1_dates)
        
        # Price starts at 2010, rises to 2020 at 6 minutes
        prices = []
        for i in range(n_secs):
            if i < 360:  # First 6 minutes: rise to 2020
                price = 2010 + (10 * i / 360)
            else:  # After: stay around 2020
                price = 2020 + np.random.randn() * 0.5
            prices.append(price)
        
        s1_df = pd.DataFrame({
            'open': prices,
            'high': [p + 0.5 for p in prices],
            'low': [p - 0.5 for p in prices],
            'close': prices,
            'volume': [50] * n_secs
        }, index=s1_dates)
        
        # Run backtest
        results = backtester.run_with_tick_data(m5_df, signals_df, s1_df)
        
        # Should have 1 trade that hit take profit
        self.assertEqual(results['total_trades'], 1)
        
        # Get trade details
        trades_df = backtester.get_trades_df()
        trade = trades_df.iloc[0]
        self.assertEqual(trade['exit_reason'], 'Take Profit')
        
        # Should be profitable
        self.assertGreater(trade['pnl'], 0)
    
    def test_accuracy_s1_vs_simulated(self):
        """
        Test that S1 data provides more accurate results than simulated
        
        Scenario: SL is between low and close of M5 candle
        - Simulated: might miss it or detect it incorrectly
        - S1: will detect exact moment it hit
        """
        # This is more of a conceptual test
        # In reality, S1 will detect exits that simulated path might miss
        pass


@unittest.skip("data_fetcher module removed - needs update to cache_data")
class TestS1DataFetchingIntegration(unittest.TestCase):
    """
    Integration tests for fetching S1 data
    Requires valid API credentials
    """
    
    @classmethod
    def setUpClass(cls):
        from dotenv import load_dotenv
        import json
        
        load_dotenv()
        secrets_str = os.getenv('apicredentials')
        if not secrets_str:
            raise unittest.SkipTest("No credentials - skipping S1 integration tests")
        
        secrets = json.loads(secrets_str)
        
        from src.data_fetcher import CapitalComDataFetcher
        cls.fetcher = CapitalComDataFetcher(
            api_key=secrets.get('apikey', ''),
            username=secrets.get('username', ''),
            password=secrets.get('password', ''),
            capkey=secrets.get('capkey', ''),
            cache_dir='test_cache_s1'
        )
    
    @classmethod
    def tearDownClass(cls):
        import shutil
        if os.path.exists('test_cache_s1'):
            shutil.rmtree('test_cache_s1')
    
    def test_fetch_s1_data(self):
        """Test fetching real S1 data from Capital.com API"""
        df = self.fetcher.fetch_historical_prices('GOLD', 'S1', max_bars=100)
        
        self.assertIsNotNone(df)
        self.assertGreater(len(df), 0)
        self.assertLessEqual(len(df), 100)
        
        # Validate 1-second intervals
        if len(df) > 1:
            time_diffs = df.index.to_series().diff().dropna()
            most_common_diff = time_diffs.mode()[0]
            
            # Should be 1 second (or very close)
            self.assertLessEqual(abs(most_common_diff.total_seconds() - 1), 2)
    
    def test_s1_data_quality(self):
        """Test that S1 data has proper OHLC relationships"""
        df = self.fetcher.fetch_historical_prices('GOLD', 'S1', max_bars=500)
        
        self.assertIsNotNone(df)
        
        # OHLC validation
        self.assertTrue((df['high'] >= df['open']).all())
        self.assertTrue((df['high'] >= df['close']).all())
        self.assertTrue((df['low'] <= df['open']).all())
        self.assertTrue((df['low'] <= df['close']).all())
        self.assertTrue((df['high'] >= df['low']).all())
    
    def test_s1_data_span(self):
        """Test how much S1 data is available"""
        info = self.fetcher.get_available_data_info('GOLD', 'S1')
        
        self.assertNotIn('error', info)
        print(f"\nS1 Data availability:")
        print(f"  Oldest: {info['oldest_available']}")
        print(f"  Newest: {info['newest_available']}")
        print(f"  Span: {info['data_span_days']} days ({info['data_span_days'] * 24:.1f} hours)")


def run_tests(test_type='mock'):
    """Run tests"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    if test_type in ['mock', 'all']:
        suite.addTests(loader.loadTestsFromTestCase(TestS1TickData))
        suite.addTests(loader.loadTestsFromTestCase(TestTickLevelBacktestWithS1))
    
    if test_type in ['integration', 'all']:
        suite.addTests(loader.loadTestsFromTestCase(TestS1DataFetchingIntegration))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    import sys
    
    test_type = sys.argv[1] if len(sys.argv) > 1 else 'mock'
    
    print("\n" + "="*70)
    print(f"Running {test_type.upper()} tests for 1-Second Tick Backtester")
    print("="*70 + "\n")
    
    success = run_tests(test_type)
    
    print("\n" + "="*70)
    if success:
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed")
    print("="*70)
    
    sys.exit(0 if success else 1)
