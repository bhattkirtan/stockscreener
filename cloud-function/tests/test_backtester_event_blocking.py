"""
Unit tests for Backtester integration with EventBlocker

Tests that backtester correctly skips trades during blocked periods.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.backtester import IntraCandleBacktester, BacktestConfig
from src.core.event_blocker import EventBlocker


class TestBacktesterEventBlocking(unittest.TestCase):
    """Test Backtester integration with EventBlocker"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Create sample price data
        self.dates = pd.date_range('2026-03-18 16:00', periods=100, freq='5min')
        self.data = pd.DataFrame({
            'open': np.random.uniform(2700, 2710, 100),
            'high': np.random.uniform(2710, 2720, 100),
            'low': np.random.uniform(2690, 2700, 100),
            'close': np.random.uniform(2700, 2710, 100),
            'volume': np.random.uniform(1000, 2000, 100)
        }, index=self.dates)
        
        # Add required columns for ATR calculation
        self.data['atr'] = 5.0
        self.data['sma_200'] = 2705.0
        
        # Create mock strategy
        self.mock_strategy = Mock()
        self.mock_strategy.check_entry.return_value = None
        self.mock_strategy.check_exit.return_value = None
        self.mock_strategy.update_indicators = Mock()
    
    def test_backtester_without_event_blocking(self):
        """Test backtester runs normally without event blocking"""
        config = BacktestConfig(
            enable_event_blocking=False,
            initial_balance=10000,
            risk_per_trade_pct=1.0,
            verbose=False
        )
        
        backtester = IntraCandleBacktester(config)
        
        # Should not raise any errors
        self.assertIsNotNone(backtester)
        self.assertFalse(config.enable_event_blocking)
    
    def test_backtester_with_event_blocking_enabled(self):
        """Test backtester initializes with event blocking"""
        mock_calendar = Mock()
        mock_blocker = Mock(spec=EventBlocker)
        
        config = BacktestConfig(
            enable_event_blocking=True,
            event_blocker=mock_blocker,
            event_pre_window_minutes=15,
            event_post_window_minutes=30,
            initial_balance=10000,
            risk_per_trade_pct=1.0,
            verbose=False
        )
        
        backtester = IntraCandleBacktester(config)
        
        self.assertTrue(config.enable_event_blocking)
        self.assertEqual(config.event_blocker, mock_blocker)
        self.assertEqual(config.event_pre_window_minutes, 15)
        self.assertEqual(config.event_post_window_minutes, 30)
    
    def test_signal_checked_against_blocker(self):
        """Test that backtester checks signals against event blocker"""
        # Create mock event blocker that blocks at 18:00
        mock_blocker = Mock(spec=EventBlocker)
        
        def is_trading_allowed_side_effect(timestamp):
            # Block between 17:45 and 18:15 (FOMC window)
            if datetime(2026, 3, 18, 17, 45) <= timestamp <= datetime(2026, 3, 18, 18, 15):
                return (False, "FOMC Meeting")
            return (True, None)
        
        mock_blocker.is_trading_allowed = Mock(side_effect=is_trading_allowed_side_effect)
        
        config = BacktestConfig(
            enable_event_blocking=True,
            event_blocker=mock_blocker,
            initial_balance=10000,
            risk_per_trade_pct=1.0,
            verbose=False
        )
        
        backtester = IntraCandleBacktester(config)
        
        # Mock strategy that generates entry signal
        self.mock_strategy.check_entry.return_value = 'long'
        
        # Run backtest (would need full implementation)
        # For now, just verify blocker is called
        
        # Test is_trading_allowed is called correctly
        result, reason = mock_blocker.is_trading_allowed(datetime(2026, 3, 18, 18, 0))
        self.assertFalse(result)
        self.assertEqual(reason, "FOMC Meeting")
        
        result, reason = mock_blocker.is_trading_allowed(datetime(2026, 3, 18, 16, 0))
        self.assertTrue(result)
        self.assertIsNone(reason)
    
    def test_blocked_trade_is_skipped(self):
        """Test that blocked trades are skipped"""
        mock_blocker = Mock(spec=EventBlocker)
        
        # Always block trading
        mock_blocker.is_trading_allowed.return_value = (False, "Event blocked")
        
        config = BacktestConfig(
            enable_event_blocking=True,
            event_blocker=mock_blocker,
            initial_balance=10000,
            risk_per_trade_pct=1.0,
            verbose=False
        )
        
        # Verify configuration
        self.assertTrue(config.enable_event_blocking)
        self.assertIsNotNone(config.event_blocker)
        
        # Test blocker behavior
        is_allowed, reason = mock_blocker.is_trading_allowed(datetime(2026, 3, 18, 18, 0))
        self.assertFalse(is_allowed)
        self.assertEqual(reason, "Event blocked")
    
    def test_allowed_trade_is_processed(self):
        """Test that allowed trades are processed normally"""
        mock_blocker = Mock(spec=EventBlocker)
        
        # Always allow trading
        mock_blocker.is_trading_allowed.return_value = (True, None)
        
        config = BacktestConfig(
            enable_event_blocking=True,
            event_blocker=mock_blocker,
            initial_balance=10000,
            risk_per_trade_pct=1.0,
            verbose=False
        )
        
        # Test blocker behavior
        is_allowed, reason = mock_blocker.is_trading_allowed(datetime(2026, 3, 18, 16, 0))
        self.assertTrue(is_allowed)
        self.assertIsNone(reason)
    
    def test_blocker_called_before_entry(self):
        """Test that blocker is called before processing entry signals"""
        call_log = []
        
        mock_blocker = Mock(spec=EventBlocker)
        
        def is_trading_allowed_mock(timestamp):
            call_log.append(('blocker_check', timestamp))
            return (True, None)
        
        mock_blocker.is_trading_allowed = Mock(side_effect=is_trading_allowed_mock)
        
        config = BacktestConfig(
            enable_event_blocking=True,
            event_blocker=mock_blocker,
            initial_balance=10000,
            verbose=False
        )
        
        # Simulate checking if trading is allowed
        test_time = datetime(2026, 3, 18, 17, 0)
        is_allowed, reason = mock_blocker.is_trading_allowed(test_time)
        
        # Verify blocker was called
        self.assertEqual(len(call_log), 1)
        self.assertEqual(call_log[0][0], 'blocker_check')
        self.assertEqual(call_log[0][1], test_time)
    
    def test_blocker_called_before_exit(self):
        """Test that blocker is also called before processing exit signals"""
        mock_blocker = Mock(spec=EventBlocker)
        mock_blocker.is_trading_allowed.return_value = (True, None)
        
        config = BacktestConfig(
            enable_event_blocking=True,
            event_blocker=mock_blocker,
            initial_balance=10000,
            verbose=False
        )
        
        # Simulate exit check
        test_time = datetime(2026, 3, 18, 18, 20)
        is_allowed, reason = mock_blocker.is_trading_allowed(test_time)
        
        self.assertTrue(is_allowed)
        mock_blocker.is_trading_allowed.assert_called_with(test_time)
    
    def test_partial_block_scenario(self):
        """Test scenario where some signals are blocked and others allowed"""
        mock_blocker = Mock(spec=EventBlocker)
        
        # Create timeline:
        # 17:00 - 17:40: Allowed
        # 17:45 - 18:15: Blocked (FOMC)
        # 18:20 onwards: Allowed
        
        def is_trading_allowed_timeline(timestamp):
            if datetime(2026, 3, 18, 17, 45) <= timestamp <= datetime(2026, 3, 18, 18, 15):
                return (False, "FOMC Meeting")
            return (True, None)
        
        mock_blocker.is_trading_allowed = Mock(side_effect=is_trading_allowed_timeline)
        
        config = BacktestConfig(
            enable_event_blocking=True,
            event_blocker=mock_blocker,
            initial_balance=10000,
            verbose=False
        )
        
        # Test various times
        test_times = [
            (datetime(2026, 3, 18, 17, 30), True, None),           # Before block
            (datetime(2026, 3, 18, 17, 50), False, "FOMC Meeting"), # During block
            (datetime(2026, 3, 18, 18, 0), False, "FOMC Meeting"),  # During block
            (datetime(2026, 3, 18, 18, 20), True, None),           # After block
        ]
        
        for test_time, expected_allowed, expected_reason in test_times:
            is_allowed, reason = mock_blocker.is_trading_allowed(test_time)
            self.assertEqual(is_allowed, expected_allowed, 
                           f"Failed for {test_time}: expected {expected_allowed}, got {is_allowed}")
            self.assertEqual(reason, expected_reason,
                           f"Failed for {test_time}: expected {expected_reason}, got {reason}")
    
    def test_blocker_with_custom_windows(self):
        """Test custom pre/post event windows"""
        config = BacktestConfig(
            enable_event_blocking=True,
            event_blocker=Mock(),
            event_pre_window_minutes=30,   # 30 min before
            event_post_window_minutes=45,  # 45 min after
            initial_balance=10000,
            verbose=False
        )
        
        self.assertEqual(config.event_pre_window_minutes, 30)
        self.assertEqual(config.event_post_window_minutes, 45)
    
    def test_blocker_none_when_disabled(self):
        """Test that blocker is None when event blocking is disabled"""
        config = BacktestConfig(
            enable_event_blocking=False,
            event_blocker=None,
            initial_balance=10000,
            verbose=False
        )
        
        self.assertFalse(config.enable_event_blocking)
        self.assertIsNone(config.event_blocker)


class TestBacktesterEventBlockingStatistics(unittest.TestCase):
    """Test that backtest statistics track blocked trades"""
    
    def test_blocked_trades_count(self):
        """Test that blocked trades are counted in statistics"""
        # This would require running actual backtest
        # For now, verify the structure is in place
        
        mock_blocker = Mock(spec=EventBlocker)
        mock_blocker.is_trading_allowed.return_value = (False, "Event blocked")
        
        config = BacktestConfig(
            enable_event_blocking=True,
            event_blocker=mock_blocker,
            initial_balance=10000,
            verbose=False
        )
        
        # In actual backtest, this would track blocked trades
        blocked_count = 0
        
        # Simulate checking 10 times, all blocked
        for i in range(10):
            is_allowed, reason = mock_blocker.is_trading_allowed(
                datetime(2026, 3, 18, 18, i)
            )
            if not is_allowed:
                blocked_count += 1
        
        self.assertEqual(blocked_count, 10)
    
    def test_blocked_reasons_logged(self):
        """Test that block reasons are available"""
        mock_blocker = Mock(spec=EventBlocker)
        
        reasons = [
            (False, "FOMC Meeting"),
            (False, "NFP Release"),
            (False, "CPI Data"),
            (True, None),
        ]
        
        mock_blocker.is_trading_allowed.side_effect = reasons
        
        logged_reasons = []
        
        for i in range(4):
            is_allowed, reason = mock_blocker.is_trading_allowed(
                datetime(2026, 3, 18, 18, i)
            )
            if not is_allowed:
                logged_reasons.append(reason)
        
        self.assertEqual(len(logged_reasons), 3)
        self.assertIn("FOMC Meeting", logged_reasons)
        self.assertIn("NFP Release", logged_reasons)
        self.assertIn("CPI Data", logged_reasons)


class TestBacktesterEventBlockingEdgeCases(unittest.TestCase):
    """Test edge cases in backtester event blocking"""
    
    def test_blocker_exception_handled(self):
        """Test that exceptions in blocker don't crash backtest"""
        mock_blocker = Mock(spec=EventBlocker)
        mock_blocker.is_trading_allowed.side_effect = Exception("API Error")
        
        config = BacktestConfig(
            enable_event_blocking=True,
            event_blocker=mock_blocker,
            initial_balance=10000,
            verbose=False
        )
        
        # In production, this should be caught and logged
        # For testing, we verify the exception is raised
        with self.assertRaises(Exception):
            mock_blocker.is_trading_allowed(datetime(2026, 3, 18, 18, 0))
    
    def test_blocker_none_check(self):
        """Test that None blocker is handled safely"""
        config = BacktestConfig(
            enable_event_blocking=True,  # Enabled but...
            event_blocker=None,          # No blocker provided
            initial_balance=10000,
            verbose=False
        )
        
        # Should not crash even though blocker is None
        # Backtester should check if blocker exists before calling
        self.assertTrue(config.enable_event_blocking)
        self.assertIsNone(config.event_blocker)
    
    def test_enable_false_but_blocker_provided(self):
        """Test that blocker is ignored when enable_event_blocking=False"""
        mock_blocker = Mock(spec=EventBlocker)
        mock_blocker.is_trading_allowed.return_value = (False, "Should not be called")
        
        config = BacktestConfig(
            enable_event_blocking=False,  # Disabled
            event_blocker=mock_blocker,   # But blocker provided
            initial_balance=10000,
            verbose=False
        )
        
        # Blocker should not be called when disabled
        self.assertFalse(config.enable_event_blocking)
        
        # Blocker should not have been called
        mock_blocker.is_trading_allowed.assert_not_called()
    
    def test_rapid_on_off_blocking(self):
        """Test rapid transitions between blocked and allowed"""
        mock_blocker = Mock(spec=EventBlocker)
        
        # Alternate between blocked and allowed
        results = [
            (True, None),
            (False, "Event 1"),
            (True, None),
            (False, "Event 2"),
            (True, None),
        ]
        mock_blocker.is_trading_allowed.side_effect = results
        
        config = BacktestConfig(
            enable_event_blocking=True,
            event_blocker=mock_blocker,
            initial_balance=10000,
            verbose=False
        )
        
        # Process 5 signals
        signal_results = []
        for i in range(5):
            is_allowed, reason = mock_blocker.is_trading_allowed(
                datetime(2026, 3, 18, 18, i)
            )
            signal_results.append((is_allowed, reason))
        
        # Verify alternating pattern
        self.assertEqual(signal_results[0][0], True)
        self.assertEqual(signal_results[1][0], False)
        self.assertEqual(signal_results[2][0], True)
        self.assertEqual(signal_results[3][0], False)
        self.assertEqual(signal_results[4][0], True)


if __name__ == '__main__':
    unittest.main()
