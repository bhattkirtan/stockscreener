"""
Test cases for data fetcher
Tests Capital.com API integration with real and mock data

⚠️  OBSOLETE: This test file is for the removed data_fetcher module.
It needs to be rewritten to test src.data.cache_data instead.
All tests in this file are currently skipped.
"""

import unittest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os
import json
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# from src.data_fetcher import CapitalComDataFetcher  # REMOVED


@unittest.skip("data_fetcher module removed - tests need rewrite for cache_data")
class TestDataFetcherMock(unittest.TestCase):
    """Test data fetcher with mocked API responses"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.fetcher = CapitalComDataFetcher(
            api_key='test_api_key',
            username='test@example.com',
            password='test_password',
            capkey='test_capkey',
            cache_dir='test_cache'
        )
    
    def tearDown(self):
        """Clean up test cache"""
        import shutil
        if os.path.exists('test_cache'):
            shutil.rmtree('test_cache')
    
    @patch('requests.post')
    def test_authentication_success(self, mock_post):
        """Test successful authentication"""
        # Mock successful auth response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.headers = {
            'CST': 'test_token',
            'X-SECURITY-TOKEN': 'test_security_token'
        }
        mock_post.return_value = mock_response
        
        result = self.fetcher.authenticate()
        
        self.assertTrue(result)
        self.assertEqual(self.fetcher.token, 'test_token')
        self.assertEqual(self.fetcher.security_token, 'test_security_token')
        self.assertIsNotNone(self.fetcher.token_expiry)
    
    @patch('requests.post')
    def test_authentication_failure(self, mock_post):
        """Test authentication failure"""
        mock_response = Mock()
        mock_response.ok = False
        mock_response.status_code = 401
        mock_response.text = 'Invalid credentials'
        mock_post.return_value = mock_response
        
        result = self.fetcher.authenticate()
        
        self.assertFalse(result)
        self.assertIsNone(self.fetcher.token)
    
    def test_token_validation(self):
        """Test token expiry validation"""
        # No token
        self.assertFalse(self.fetcher._is_token_valid())
        
        # Valid token
        self.fetcher.token = 'test_token'
        self.fetcher.token_expiry = datetime.now() + timedelta(hours=1)
        self.assertTrue(self.fetcher._is_token_valid())
        
        # Expired token
        self.fetcher.token_expiry = datetime.now() - timedelta(hours=1)
        self.assertFalse(self.fetcher._is_token_valid())
    
    @patch('requests.get')
    def test_fetch_historical_prices_success(self, mock_get):
        """Test fetching historical prices successfully"""
        # Set up valid token
        self.fetcher.token = 'test_token'
        self.fetcher.security_token = 'test_security_token'
        self.fetcher.token_expiry = datetime.now() + timedelta(hours=1)
        
        # Mock API response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {
            'prices': [
                {
                    'snapshotTimeUTC': '2024-01-01T10:00:00',
                    'openPrice': {'bid': 2000.0},
                    'highPrice': {'bid': 2010.0},
                    'lowPrice': {'bid': 1995.0},
                    'closePrice': {'bid': 2005.0},
                    'lastTradedVolume': 1000
                },
                {
                    'snapshotTimeUTC': '2024-01-01T10:05:00',
                    'openPrice': {'bid': 2005.0},
                    'highPrice': {'bid': 2015.0},
                    'lowPrice': {'bid': 2000.0},
                    'closePrice': {'bid': 2010.0},
                    'lastTradedVolume': 1500
                }
            ]
        }
        mock_get.return_value = mock_response
        
        df = self.fetcher.fetch_historical_prices('GOLD', 'M5', max_bars=2)
        
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 2)
        self.assertIn('open', df.columns)
        self.assertIn('high', df.columns)
        self.assertIn('low', df.columns)
        self.assertIn('close', df.columns)
        self.assertIn('volume', df.columns)
        
        # Check data types
        self.assertEqual(df['open'].dtype, np.float64)
        self.assertEqual(df['volume'].dtype, np.int64)
        
        # Check values
        self.assertEqual(df.iloc[0]['open'], 2000.0)
        self.assertEqual(df.iloc[0]['high'], 2010.0)
        self.assertEqual(df.iloc[1]['close'], 2010.0)
    
    def test_resolution_validation(self):
        """Test resolution code validation"""
        self.fetcher.token = 'test_token'
        self.fetcher.security_token = 'test_security_token'
        self.fetcher.token_expiry = datetime.now() + timedelta(hours=1)
        
        # Invalid resolution
        df = self.fetcher.fetch_historical_prices('GOLD', 'INVALID', max_bars=10)
        self.assertIsNone(df)
    
    def test_max_bars_limit(self):
        """Test that max_bars is capped at 1000 (Capital.com limit)"""
        self.fetcher.token = 'test_token'
        self.fetcher.security_token = 'test_security_token'
        self.fetcher.token_expiry = datetime.now() + timedelta(hours=1)
        
        with patch('requests.get') as mock_get:
            mock_get.return_value = Mock(ok=True, json=lambda: {'prices': []})
            
            # Request 2000 bars - should be capped to 1000
            self.fetcher.fetch_historical_prices('GOLD', 'M5', max_bars=2000)
            
            # Check that API was called with max=1000
            call_args = mock_get.call_args
            self.assertEqual(call_args[1]['params']['max'], 1000)
    
    def test_rate_limiting(self):
        """Test that rate limiting enforces minimum interval"""
        start_time = self.fetcher.last_request_time
        
        self.fetcher._wait_for_rate_limit()
        first_request = self.fetcher.last_request_time
        
        self.fetcher._wait_for_rate_limit()
        second_request = self.fetcher.last_request_time
        
        # Second request should be at least min_interval after first
        time_diff = second_request - first_request
        self.assertGreaterEqual(time_diff, self.fetcher.min_request_interval)


class TestDataValidation(unittest.TestCase):
    """Test data quality and validation"""
    
    def test_ohlc_relationships(self):
        """Test that OHLC data maintains proper relationships"""
        # Create sample data
        data = {
            'open': [100, 105, 102],
            'high': [105, 110, 108],
            'low': [98, 103, 100],
            'close': [103, 107, 105],
            'volume': [1000, 1500, 1200]
        }
        df = pd.DataFrame(data, index=pd.date_range('2024-01-01', periods=3, freq='5min'))
        
        # Validate OHLC relationships
        # High should be >= open, close
        self.assertTrue((df['high'] >= df['open']).all())
        self.assertTrue((df['high'] >= df['close']).all())
        
        # Low should be <= open, close
        self.assertTrue((df['low'] <= df['open']).all())
        self.assertTrue((df['low'] <= df['close']).all())
        
        # High >= Low
        self.assertTrue((df['high'] >= df['low']).all())
    
    def test_missing_data_detection(self):
        """Test detection of gaps in timeseries data"""
        # Create data with a gap
        dates = pd.date_range('2024-01-01 10:00', periods=5, freq='5min').tolist()
        dates.append(pd.Timestamp('2024-01-01 11:00'))  # 30 minute gap
        
        df = pd.DataFrame({
            'open': [100] * 6,
            'high': [101] * 6,
            'low': [99] * 6,
            'close': [100] * 6,
            'volume': [1000] * 6
        }, index=dates)
        
        # Check for gaps (5-minute data should have 5-minute intervals)
        time_diffs = df.index.to_series().diff()
        expected_freq = pd.Timedelta('5min')
        gaps = time_diffs[time_diffs > expected_freq * 1.5]
        
        self.assertGreater(len(gaps), 0)  # Should detect the gap
    
    def test_duplicate_timestamps(self):
        """Test detection and handling of duplicate timestamps"""
        # Create data with duplicates
        dates = ['2024-01-01 10:00'] * 2 + ['2024-01-01 10:05', '2024-01-01 10:10']
        df = pd.DataFrame({
            'open': [100, 101, 102, 103],
            'high': [105, 106, 107, 108],
            'low': [98, 99, 100, 101],
            'close': [103, 104, 105, 106],
            'volume': [1000, 1500, 1200, 1300]
        }, index=pd.to_datetime(dates))
        
        # Check for duplicates
        has_duplicates = df.index.duplicated().any()
        self.assertTrue(has_duplicates)
        
        # Remove duplicates (keep first)
        df_clean = df[~df.index.duplicated(keep='first')]
        self.assertEqual(len(df_clean), 3)


class TestDataFetcherIntegration(unittest.TestCase):
    """
    Integration tests with real Capital.com API
    These tests require valid credentials in .env file
    """
    
    @classmethod
    def setUpClass(cls):
        """Set up for integration tests"""
        from dotenv import load_dotenv
        load_dotenv()
        
        secrets_str = os.getenv('apicredentials')
        if not secrets_str:
            raise unittest.SkipTest("No credentials found - skipping integration tests")
        
        secrets = json.loads(secrets_str)
        cls.fetcher = CapitalComDataFetcher(
            api_key=secrets.get('apikey', ''),
            username=secrets.get('username', ''),
            password=secrets.get('password', ''),
            capkey=secrets.get('capkey', ''),
            cache_dir='test_cache_integration'
        )
    
    @classmethod
    def tearDownClass(cls):
        """Clean up"""
        import shutil
        if os.path.exists('test_cache_integration'):
            shutil.rmtree('test_cache_integration')
    
    def test_real_authentication(self):
        """Test authentication with real API"""
        result = self.fetcher.authenticate()
        self.assertTrue(result, "Authentication should succeed with valid credentials")
        self.assertIsNotNone(self.fetcher.token)
        self.assertIsNotNone(self.fetcher.security_token)
    
    def test_real_data_fetch(self):
        """Test fetching real data"""
        df = self.fetcher.fetch_historical_prices('GOLD', 'M5', max_bars=100)
        
        self.assertIsNotNone(df, "Should fetch data successfully")
        self.assertGreater(len(df), 0, "Should have at least some bars")
        self.assertLessEqual(len(df), 100, "Should not exceed requested bars")
        
        # Validate data structure
        required_columns = ['open', 'high', 'low', 'close', 'volume']
        for col in required_columns:
            self.assertIn(col, df.columns)
        
        # Validate OHLC relationships
        self.assertTrue((df['high'] >= df['open']).all())
        self.assertTrue((df['high'] >= df['close']).all())
        self.assertTrue((df['low'] <= df['open']).all())
        self.assertTrue((df['low'] <= df['close']).all())
    
    def test_real_data_pagination(self):
        """Test fetching more than 1000 bars with pagination"""
        df = self.fetcher.fetch_historical_prices_paginated('GOLD', 'M15', total_bars=1500)
        
        self.assertIsNotNone(df, "Should fetch paginated data")
        self.assertGreater(len(df), 1000, "Should fetch more than 1000 bars")
        
        # Check for duplicates
        self.assertFalse(df.index.duplicated().any(), "Should not have duplicate timestamps")
        
        # Check data is sorted
        self.assertTrue(df.index.is_monotonic_increasing, "Data should be sorted by timestamp")
    
    def test_real_data_caching(self):
        """Test data caching functionality"""
        # First fetch (from API)
        df1 = self.fetcher.fetch_and_cache('GOLD', 'H1', total_bars=100, force_refresh=True)
        self.assertIsNotNone(df1)
        
        # Check cache file exists
        cache_file = os.path.join(self.fetcher.cache_dir, 'GOLD_H1_100.csv')
        self.assertTrue(os.path.exists(cache_file))
        
        # Second fetch (from cache)
        df2 = self.fetcher.fetch_and_cache('GOLD', 'H1', total_bars=100)
        self.assertIsNotNone(df2)
        
        # Should be identical
        pd.testing.assert_frame_equal(df1, df2)
    
    def test_real_multiple_instruments(self):
        """Test fetching data for multiple instruments"""
        instruments = ['GOLD', 'EURUSD']
        
        for epic in instruments:
            with self.subTest(instrument=epic):
                df = self.fetcher.fetch_historical_prices(epic, 'M15', max_bars=50)
                self.assertIsNotNone(df, f"Should fetch data for {epic}")
                self.assertGreater(len(df), 0, f"Should have data for {epic}")
    
    def test_real_data_info(self):
        """Test getting data availability information"""
        info = self.fetcher.get_available_data_info('GOLD', 'M5')
        
        self.assertNotIn('error', info)
        self.assertIn('oldest_available', info)
        self.assertIn('newest_available', info)
        self.assertIn('data_span_days', info)
        self.assertGreater(info['data_span_days'], 0)


def run_tests(test_type='all'):
    """
    Run tests
    
    Args:
        test_type: 'mock', 'integration', or 'all'
    """
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    if test_type in ['mock', 'all']:
        suite.addTests(loader.loadTestsFromTestCase(TestDataFetcherMock))
        suite.addTests(loader.loadTestsFromTestCase(TestDataValidation))
    
    if test_type in ['integration', 'all']:
        suite.addTests(loader.loadTestsFromTestCase(TestDataFetcherIntegration))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    import sys
    
    # Default to mock tests only (don't hit API unless requested)
    test_type = sys.argv[1] if len(sys.argv) > 1 else 'mock'
    
    print("\n" + "="*70)
    print(f"Running {test_type.upper()} tests for Data Fetcher")
    print("="*70 + "\n")
    
    success = run_tests(test_type)
    
    print("\n" + "="*70)
    if success:
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed")
    print("="*70)
    
    sys.exit(0 if success else 1)
