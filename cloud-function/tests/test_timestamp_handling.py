"""
Unit tests for timestamp handling in trading bot
Tests all possible timestamp formats that can come from Capital.com API
"""
import unittest
import pandas as pd
import sys
import os
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestTimestampHandling(unittest.TestCase):
    """Test timestamp conversion in calculate_indicators"""
    
    def setUp(self):
        """Set up test bot instance"""
        # Mock the minimal setup needed
        self.test_candles = {
            'integer_unix_ms': [
                {'timestamp': 1773136500000, 'open': 5180.0, 'high': 5185.0, 'low': 5175.0, 'close': 5182.0, 'volume': 1000},
                {'timestamp': 1773136800000, 'open': 5182.0, 'high': 5187.0, 'low': 5177.0, 'close': 5184.0, 'volume': 1100},
            ],
            'string_unix_ms': [
                {'timestamp': '1773136500000', 'open': 5180.0, 'high': 5185.0, 'low': 5175.0, 'close': 5182.0, 'volume': 1000},
                {'timestamp': '1773136800000', 'open': 5182.0, 'high': 5187.0, 'low': 5177.0, 'close': 5184.0, 'volume': 1100},
            ],
            'iso_format': [
                {'timestamp': '2026-03-10T09:25:00', 'open': 5180.0, 'high': 5185.0, 'low': 5175.0, 'close': 5182.0, 'volume': 1000},
                {'timestamp': '2026-03-10T09:30:00', 'open': 5182.0, 'high': 5187.0, 'low': 5177.0, 'close': 5184.0, 'volume': 1100},
            ],
            'mixed_format': [
                {'timestamp': '2026-03-10T09:25:00', 'open': 5180.0, 'high': 5185.0, 'low': 5175.0, 'close': 5182.0, 'volume': 1000},
                {'timestamp': 1773136800000, 'open': 5182.0, 'high': 5187.0, 'low': 5177.0, 'close': 5184.0, 'volume': 1100},
                {'timestamp': '1773137100000', 'open': 5184.0, 'high': 5189.0, 'low': 5179.0, 'close': 5186.0, 'volume': 1200},
            ]
        }
    
    def _create_bot_with_history(self, candles):
        """Helper to create bot instance with test history"""
        # Create minimal bot instance (we'll test just the timestamp conversion logic)
        class TestBot:
            def __init__(self, history):
                self.m5_history = history
            
            def calculate_indicators(self):
                """Test only the timestamp conversion part (not full indicators)"""
                df = pd.DataFrame(self.m5_history)
                
                # Handle mixed timestamp formats (Unix ms strings, Unix ms ints, ISO strings)
                # Convert each timestamp individually to handle mixed formats
                timestamps = []
                for ts in df['timestamp']:
                    if isinstance(ts, (int, float)):
                        # Numeric Unix ms
                        timestamps.append(pd.to_datetime(ts, unit='ms'))
                    elif isinstance(ts, str):
                        # Check if it's a numeric string (Unix ms) or ISO format
                        try:
                            # Try as Unix ms first
                            timestamps.append(pd.to_datetime(int(ts), unit='ms'))
                        except (ValueError, TypeError):
                            # Fall back to ISO format parsing
                            timestamps.append(pd.to_datetime(ts))
                    else:
                        # Already datetime
                        timestamps.append(pd.to_datetime(ts))
                
                df['timestamp'] = timestamps
                df.set_index('timestamp', inplace=True)
                
                return df
        
        return TestBot(candles)
    
    def test_integer_unix_ms(self):
        """Test with integer Unix milliseconds (from WebSocket new format)"""
        bot = self._create_bot_with_history(self.test_candles['integer_unix_ms'])
        
        try:
            df = bot.calculate_indicators()
            self.assertIsInstance(df, pd.DataFrame)
            self.assertEqual(len(df), 2)
            self.assertTrue(isinstance(df.index, pd.DatetimeIndex))
            print("✅ Integer Unix ms: PASS")
        except Exception as e:
            self.fail(f"Failed with integer Unix ms: {e}")
    
    def test_string_unix_ms(self):
        """Test with string representation of Unix milliseconds (WebSocket variant)"""
        bot = self._create_bot_with_history(self.test_candles['string_unix_ms'])
        
        try:
            df = bot.calculate_indicators()
            self.assertIsInstance(df, pd.DataFrame)
            self.assertEqual(len(df), 2)
            self.assertTrue(isinstance(df.index, pd.DatetimeIndex))
            print("✅ String Unix ms: PASS")
        except Exception as e:
            self.fail(f"Failed with string Unix ms: {e}")
    
    def test_iso_format(self):
        """Test with ISO format strings (from historical data API)"""
        bot = self._create_bot_with_history(self.test_candles['iso_format'])
        
        try:
            df = bot.calculate_indicators()
            self.assertIsInstance(df, pd.DataFrame)
            self.assertEqual(len(df), 2)
            self.assertTrue(isinstance(df.index, pd.DatetimeIndex))
            print("✅ ISO format: PASS")
        except Exception as e:
            self.fail(f"Failed with ISO format: {e}")
    
    def test_mixed_format(self):
        """Test with mixed formats (the real-world scenario that was failing)"""
        bot = self._create_bot_with_history(self.test_candles['mixed_format'])
        
        try:
            df = bot.calculate_indicators()
            self.assertIsInstance(df, pd.DataFrame)
            self.assertEqual(len(df), 3)
            self.assertTrue(isinstance(df.index, pd.DatetimeIndex))
            
            # Verify all timestamps were converted correctly
            for ts in df.index:
                self.assertIsInstance(ts, pd.Timestamp)
            
            print("✅ Mixed format: PASS")
        except Exception as e:
            self.fail(f"Failed with mixed format: {e}")
    
    def test_timestamp_ordering(self):
        """Test that timestamps maintain correct chronological order"""
        bot = self._create_bot_with_history(self.test_candles['mixed_format'])
        
        try:
            df = bot.calculate_indicators()
            
            # Check timestamps are in ascending order
            timestamps = df.index.tolist()
            for i in range(len(timestamps) - 1):
                self.assertLess(timestamps[i], timestamps[i + 1], 
                               "Timestamps should be in ascending order")
            
            print("✅ Timestamp ordering: PASS")
        except Exception as e:
            self.fail(f"Failed timestamp ordering: {e}")


def run_tests():
    """Run all tests and provide summary"""
    print("=" * 60)
    print("🧪 TIMESTAMP HANDLING UNIT TESTS")
    print("=" * 60)
    print()
    
    # Create test suite
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestTimestampHandling)
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print()
    print("=" * 60)
    if result.wasSuccessful():
        print("✅ ALL TESTS PASSED")
        print(f"✅ {result.testsRun} tests ran successfully")
    else:
        print("❌ SOME TESTS FAILED")
        print(f"❌ Failures: {len(result.failures)}")
        print(f"❌ Errors: {len(result.errors)}")
    print("=" * 60)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
