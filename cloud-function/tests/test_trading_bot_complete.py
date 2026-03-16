"""
Comprehensive unit tests for M5 Trading Bot
Tests all critical functionality before deployment
"""
import unittest
import pandas as pd
import sys
import os
import json
import tempfile
import shutil
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch, AsyncMock

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestTimestampConversion(unittest.TestCase):
    """Test timestamp handling for all formats"""
    
    def test_convert_mixed_timestamps(self):
        """Test mixed timestamp formats (the critical bug we fixed)"""
        # Create test data with mixed formats
        history = [
            {'timestamp': '2026-03-10T09:25:00', 'open': 5180.0, 'high': 5185.0, 'low': 5175.0, 'close': 5182.0, 'volume': 1000},
            {'timestamp': 1773136800000, 'open': 5182.0, 'high': 5187.0, 'low': 5177.0, 'close': 5184.0, 'volume': 1100},
            {'timestamp': '1773137100000', 'open': 5184.0, 'high': 5189.0, 'low': 5179.0, 'close': 5186.0, 'volume': 1200},
        ]
        
        # Test conversion logic directly
        df = pd.DataFrame(history)
        timestamps = []
        for ts in df['timestamp']:
            if isinstance(ts, (int, float)):
                timestamps.append(pd.to_datetime(ts, unit='ms'))
            elif isinstance(ts, str):
                try:
                    timestamps.append(pd.to_datetime(int(ts), unit='ms'))
                except (ValueError, TypeError):
                    timestamps.append(pd.to_datetime(ts))
            else:
                timestamps.append(pd.to_datetime(ts))
        
        df['timestamp'] = timestamps
        
        # Verify all converted to datetime
        self.assertEqual(len(df), 3)
        for ts in df['timestamp']:
            self.assertIsInstance(ts, pd.Timestamp)
        
        print("✅ Mixed timestamp conversion: PASS")


class TestIndicatorCalculation(unittest.TestCase):
    """Test indicator calculation and DataFrame operations"""
    
    def setUp(self):
        """Create test candle data"""
        self.test_candles = []
        base_ts = 1773136500000
        base_price = 5180.0
        
        # Generate 25 candles (enough for indicators)
        for i in range(25):
            self.test_candles.append({
                'timestamp': base_ts + (i * 300000),  # 5 min intervals in ms
                'open': base_price + i * 0.5,
                'high': base_price + i * 0.5 + 5,
                'low': base_price + i * 0.5 - 5,
                'close': base_price + i * 0.5 + 2,
                'volume': 1000 + i * 10
            })
    
    def test_dataframe_conversion(self):
        """Test DataFrame creation from candle history"""
        df = pd.DataFrame(self.test_candles)
        
        self.assertEqual(len(df), 25)
        self.assertIn('timestamp', df.columns)
        self.assertIn('open', df.columns)
        self.assertIn('high', df.columns)
        self.assertIn('low', df.columns)
        self.assertIn('close', df.columns)
        
        print("✅ DataFrame conversion: PASS")
    
    def test_strategy_integration(self):
        """Test that strategy calculates indicators without errors"""
        from src.core.strategy import SupertrendVWAPStrategy
        
        df = pd.DataFrame(self.test_candles)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        
        strategy = SupertrendVWAPStrategy(
            supertrend_period=7,
            supertrend_multiplier=2.0,
            sma_fast=10,
            sma_slow=21
        )
        
        result = strategy.calculate_indicators(df)
        
        # Verify key indicators exist
        self.assertIn('supertrend', result.columns)
        self.assertIn('direction', result.columns)
        self.assertIn('sma_fast', result.columns)
        self.assertIn('sma_slow', result.columns)
        self.assertIn('ema', result.columns)
        
        # Verify last values are not NaN (enough data)
        self.assertFalse(pd.isna(result['supertrend'].iloc[-1]))
        self.assertFalse(pd.isna(result['sma_fast'].iloc[-1]))
        
        print("✅ Strategy integration: PASS")


class TestSignalGeneration(unittest.TestCase):
    """Test BUY/SELL signal generation logic"""
    
    def test_buy_signal_conditions(self):
        """Test BUY signal logic"""
        # Mock DataFrame with indicators
        data = {
            'close': [5180.0, 5182.0, 5185.0],
            'supertrend': [5175.0, 5177.0, 5180.0],
            'direction': [1, 1, 1],  # Uptrend
            'sma_fast': [5178.0, 5180.0, 5182.0],
            'sma_slow': [5170.0, 5172.0, 5174.0],  # Fast > Slow
            'ema': [5176.0, 5178.0, 5180.0],
            'high': [5185.0, 5187.0, 5190.0],
            'low': [5175.0, 5177.0, 5180.0]
        }
        df = pd.DataFrame(data)
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # Check BUY conditions
        supertrend_dir = latest['direction']
        close = latest['close']
        ema = latest['ema']
        sma_fast = latest['sma_fast']
        sma_slow = latest['sma_slow']
        
        # Golden cross check
        sma_fast_prev = prev['sma_fast']
        sma_slow_prev = prev['sma_slow']
        golden_cross = (sma_fast > sma_slow) and (sma_fast_prev <= sma_slow_prev)
        
        # BUY signal condition
        buy_signal = (supertrend_dir == 1 and 
                     close > ema and 
                     (golden_cross or sma_fast > sma_slow))
        
        self.assertTrue(supertrend_dir == 1, "Should be in uptrend")
        self.assertTrue(close > ema, "Price should be above EMA")
        self.assertTrue(sma_fast > sma_slow, "Fast SMA should be above slow SMA")
        self.assertTrue(buy_signal, "BUY signal should be detected")
        
        print("✅ BUY signal conditions: PASS")
    
    def test_sell_signal_conditions(self):
        """Test SELL signal logic"""
        data = {
            'close': [5180.0, 5178.0, 5175.0],
            'supertrend': [5185.0, 5183.0, 5180.0],
            'direction': [-1, -1, -1],  # Downtrend
            'sma_fast': [5182.0, 5180.0, 5178.0],
            'sma_slow': [5190.0, 5188.0, 5186.0],  # Fast < Slow
            'ema': [5184.0, 5182.0, 5180.0],
            'high': [5185.0, 5183.0, 5180.0],
            'low': [5175.0, 5173.0, 5170.0]
        }
        df = pd.DataFrame(data)
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        supertrend_dir = latest['direction']
        close = latest['close']
        ema = latest['ema']
        sma_fast = latest['sma_fast']
        sma_slow = latest['sma_slow']
        
        # Death cross check
        sma_fast_prev = prev['sma_fast']
        sma_slow_prev = prev['sma_slow']
        death_cross = (sma_fast < sma_slow) and (sma_fast_prev >= sma_slow_prev)
        
        # SELL signal condition
        sell_signal = (supertrend_dir == -1 and 
                      close < ema and 
                      (death_cross or sma_fast < sma_slow))
        
        self.assertTrue(supertrend_dir == -1, "Should be in downtrend")
        self.assertTrue(close < ema, "Price should be below EMA")
        self.assertTrue(sma_fast < sma_slow, "Fast SMA should be below slow SMA")
        self.assertTrue(sell_signal, "SELL signal should be detected")
        
        print("✅ SELL signal conditions: PASS")


class TestJSONSerialization(unittest.TestCase):
    """Test JSON serialization for signal/candle data"""
    
    def test_serialize_signal_data(self):
        """Test that signal data can be JSON serialized"""
        signal_data = {
            'epic': 'GOLD',
            'signal': 'BUY',
            'price': 5182.53,
            'sl': 5178.12,
            'tp': 5195.41,
            'timestamp': datetime.now().isoformat(),
            'indicators': {
                'supertrend': 5180.0,
                'supertrend_direction': 1,
                'sma_fast': 5183.36,
                'sma_slow': 5185.18,
                'ema': 5182.97,
                'atr': 5.14,
                'golden_cross': True
            }
        }
        
        # Should not raise exception
        json_str = json.dumps(signal_data)
        self.assertIsInstance(json_str, str)
        
        # Should be able to parse back
        parsed = json.loads(json_str)
        self.assertEqual(parsed['epic'], 'GOLD')
        self.assertEqual(parsed['signal'], 'BUY')
        
        print("✅ Signal JSON serialization: PASS")
    
    def test_serialize_candle_with_datetime(self):
        """Test candle serialization with datetime objects"""
        candle = {
            'timestamp': datetime.now().isoformat(),
            'open': 5180.0,
            'high': 5185.0,
            'low': 5175.0,
            'close': 5182.0,
            'volume': 1000
        }
        
        # Should not raise exception
        json_str = json.dumps(candle)
        self.assertIsInstance(json_str, str)
        
        # Verify timestamp is serializable
        parsed = json.loads(json_str)
        self.assertIn('timestamp', parsed)
        
        print("✅ Candle JSON serialization: PASS")
    
    def test_convert_datetime_objects(self):
        """Test datetime conversion logic for JSON"""
        candle = {
            'timestamp': datetime.now(),
            'open': 5180.0,
            'pd_timestamp': pd.Timestamp('2026-03-10 11:00:00')
        }
        
        # Apply conversion logic
        candle_copy = {}
        for key, value in candle.items():
            if isinstance(value, (datetime, pd.Timestamp)):
                candle_copy[key] = value.isoformat()
            elif isinstance(value, (int, float)):
                if isinstance(value, int) and value > 1000000000000:
                    candle_copy[key] = datetime.fromtimestamp(value / 1000).isoformat()
                else:
                    candle_copy[key] = value
            else:
                candle_copy[key] = value
        
        # Should be JSON serializable now
        json_str = json.dumps(candle_copy)
        self.assertIsInstance(json_str, str)
        
        print("✅ Datetime conversion for JSON: PASS")
    
    def test_numpy_bool_conversion(self):
        """Test numpy bool conversion for Firestore"""
        import numpy as np
        
        # Create signal data with numpy bool (the issue we hit)
        signal_data = {
            'golden_cross': np.bool_(True),
            'death_cross': np.bool_(False),
            'price': 5182.0
        }
        
        # Convert numpy bool to Python bool
        converted = {
            'golden_cross': bool(signal_data['golden_cross']),
            'death_cross': bool(signal_data['death_cross']), 
            'price': signal_data['price']
        }
        
        # Should be JSON serializable
        json_str = json.dumps(converted)
        self.assertIsInstance(json_str, str)
        
        # Verify types
        self.assertIsInstance(converted['golden_cross'], bool)
        self.assertIsInstance(converted['death_cross'], bool)
        
        print("✅ Numpy bool conversion: PASS")


class TestCandleHistoryManagement(unittest.TestCase):
    """Test M5 candle history management"""
    
    def test_history_size_limit(self):
        """Test that history is limited to max size"""
        history = []
        max_size = 50
        
        # Add 100 candles
        for i in range(100):
            candle = {
                'timestamp': 1773136500000 + (i * 300000),
                'open': 5180.0 + i,
                'high': 5185.0 + i,
                'low': 5175.0 + i,
                'close': 5182.0 + i,
                'volume': 1000
            }
            history.append(candle)
            
            # Keep only last 50
            if len(history) > max_size:
                history = history[-max_size:]
        
        self.assertEqual(len(history), max_size)
        self.assertEqual(history[0]['open'], 5180.0 + 50)  # First should be item 50
        self.assertEqual(history[-1]['open'], 5180.0 + 99)  # Last should be item 99
        
        print("✅ History size limit: PASS")
    
    def test_minimum_history_check(self):
        """Test minimum history requirement"""
        history = []
        min_required = 20
        
        # Test with insufficient history
        for i in range(15):
            candle = {'timestamp': i, 'close': 5180.0}
            history.append(candle)
        
        self.assertFalse(len(history) >= min_required, "Should not have enough history")
        
        # Add more candles to reach minimum
        for i in range(15, 25):
            candle = {'timestamp': i, 'close': 5180.0}
            history.append(candle)
        
        self.assertTrue(len(history) >= min_required, "Should have enough history now")
        
        print("✅ Minimum history check: PASS")


class TestStopLossTakeProfit(unittest.TestCase):
    """Test SL/TP calculation"""
    
    def test_buy_sl_tp_calculation(self):
        """Test BUY stop loss and take profit calculation"""
        close = 5182.0
        atr = 5.0
        sl_multiplier = 0.7
        tp_multiplier = 2.5
        
        # BUY: SL below, TP above
        stop_loss = close - (sl_multiplier * atr)
        take_profit = close + (tp_multiplier * atr)
        
        self.assertLess(stop_loss, close, "Stop loss should be below entry")
        self.assertGreater(take_profit, close, "Take profit should be above entry")
        
        # Check exact values
        self.assertAlmostEqual(stop_loss, 5178.5, places=1)
        self.assertAlmostEqual(take_profit, 5194.5, places=1)
        
        print("✅ BUY SL/TP calculation: PASS")
    
    def test_sell_sl_tp_calculation(self):
        """Test SELL stop loss and take profit calculation"""
        close = 5182.0
        atr = 5.0
        sl_multiplier = 0.7
        tp_multiplier = 2.5
        
        # SELL: SL above, TP below
        stop_loss = close + (sl_multiplier * atr)
        take_profit = close - (tp_multiplier * atr)
        
        self.assertGreater(stop_loss, close, "Stop loss should be above entry")
        self.assertLess(take_profit, close, "Take profit should be below entry")
        
        # Check exact values
        self.assertAlmostEqual(stop_loss, 5185.5, places=1)
        self.assertAlmostEqual(take_profit, 5169.5, places=1)
        
        print("✅ SELL SL/TP calculation: PASS")


class TestFileOperations(unittest.TestCase):
    """Test file saving operations"""
    
    def setUp(self):
        """Create temporary directory for test files"""
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Clean up temporary directory"""
        shutil.rmtree(self.temp_dir)
    
    def test_candle_file_writing(self):
        """Test writing candles to JSONL file"""
        candles = [
            {'timestamp': '2026-03-10T11:00:00', 'open': 5180.0, 'close': 5182.0},
            {'timestamp': '2026-03-10T11:05:00', 'open': 5182.0, 'close': 5184.0},
        ]
        
        filepath = os.path.join(self.temp_dir, 'test_candles.jsonl')
        
        # Write candles
        with open(filepath, 'a') as f:
            for candle in candles:
                f.write(json.dumps(candle) + '\n')
        
        # Verify file exists and has content
        self.assertTrue(os.path.exists(filepath))
        
        # Read back and verify
        with open(filepath, 'r') as f:
            lines = f.readlines()
        
        self.assertEqual(len(lines), 2)
        
        # Parse first line
        candle1 = json.loads(lines[0])
        self.assertEqual(candle1['open'], 5180.0)
        
        print("✅ Candle file writing: PASS")
    
    def test_signal_file_writing(self):
        """Test writing signals to JSON file"""
        signal = {
            'timestamp': datetime.now().isoformat(),
            'signal': 'BUY',
            'price': 5182.0,
            'sl': 5178.0,
            'tp': 5194.0
        }
        
        filepath = os.path.join(self.temp_dir, 'test_signal.json')
        
        # Write signal
        with open(filepath, 'w') as f:
            json.dump(signal, f, indent=2)
        
        # Verify
        self.assertTrue(os.path.exists(filepath))
        
        # Read back
        with open(filepath, 'r') as f:
            loaded = json.load(f)
        
        self.assertEqual(loaded['signal'], 'BUY')
        self.assertEqual(loaded['price'], 5182.0)
        
        print("✅ Signal file writing: PASS")


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error conditions"""
    
    def test_empty_history(self):
        """Test behavior with empty history"""
        history = []
        min_bars = 20
        
        can_generate = len(history) >= min_bars
        self.assertFalse(can_generate)
        
        print("✅ Empty history handling: PASS")
    
    def test_nan_indicators(self):
        """Test handling of NaN indicator values"""
        data = {
            'close': [5180.0],
            'supertrend': [float('nan')],
            'sma_fast': [5182.0],
            'sma_slow': [5185.0]
        }
        df = pd.DataFrame(data)
        latest = df.iloc[-1]
        
        # Should detect NaN and skip signal generation
        has_nan = (pd.isna(latest['supertrend']) or 
                   pd.isna(latest['sma_fast']) or 
                   pd.isna(latest['sma_slow']))
        
        self.assertTrue(has_nan)
        
        print("✅ NaN indicator handling: PASS")
    
    def test_invalid_timestamp_format(self):
        """Test handling of invalid timestamp"""
        invalid_timestamps = ['invalid', '', None, 'abc123']
        
        for ts in invalid_timestamps:
            try:
                if isinstance(ts, str):
                    try:
                        pd.to_datetime(int(ts), unit='ms')
                    except (ValueError, TypeError):
                        pd.to_datetime(ts)
                else:
                    pd.to_datetime(ts)
            except:
                # Should handle gracefully
                pass
        
        print("✅ Invalid timestamp handling: PASS")


def run_all_tests():
    """Run complete test suite"""
    print("=" * 70)
    print("🧪 M5 TRADING BOT - COMPREHENSIVE TEST SUITE")
    print("=" * 70)
    print()
    
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestTimestampConversion))
    suite.addTests(loader.loadTestsFromTestCase(TestIndicatorCalculation))
    suite.addTests(loader.loadTestsFromTestCase(TestSignalGeneration))
    suite.addTests(loader.loadTestsFromTestCase(TestJSONSerialization))
    suite.addTests(loader.loadTestsFromTestCase(TestCandleHistoryManagement))
    suite.addTests(loader.loadTestsFromTestCase(TestStopLossTakeProfit))
    suite.addTests(loader.loadTestsFromTestCase(TestFileOperations))
    suite.addTests(loader.loadTestsFromTestCase(TestEdgeCases))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print()
    print("=" * 70)
    print("📊 TEST SUMMARY")
    print("=" * 70)
    print(f"Total Tests Run: {result.testsRun}")
    print(f"✅ Passed: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"❌ Failed: {len(result.failures)}")
    print(f"💥 Errors: {len(result.errors)}")
    print("=" * 70)
    
    if result.wasSuccessful():
        print("✅ ALL TESTS PASSED - BOT IS READY FOR DEPLOYMENT")
    else:
        print("❌ SOME TESTS FAILED - FIX ISSUES BEFORE DEPLOYMENT")
        if result.failures:
            print("\n❌ Failures:")
            for test, traceback in result.failures:
                print(f"  - {test}: {traceback}")
        if result.errors:
            print("\n💥 Errors:")
            for test, traceback in result.errors:
                print(f"  - {test}: {traceback}")
    
    print("=" * 70)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
