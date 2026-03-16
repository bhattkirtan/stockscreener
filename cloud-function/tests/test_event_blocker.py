"""
Unit tests for EventBlocker class

Tests calendar event blocking, news blocking, and integration with backtester.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta
from dataclasses import dataclass
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.event_blocker import EventBlocker, BlockedPeriod
from src.data.manual_calendar_adapter import ManualCalendarAdapter, CalendarEvent


class TestBlockedPeriod(unittest.TestCase):
    """Test BlockedPeriod dataclass"""
    
    def test_blocked_period_creation(self):
        """Test creating a blocked period"""
        start = datetime(2026, 3, 18, 17, 45)
        end = datetime(2026, 3, 18, 18, 15)
        
        period = BlockedPeriod(
            start_time=start,
            end_time=end,
            reason="FOMC Meeting"
        )
        
        self.assertEqual(period.start_time, start)
        self.assertEqual(period.end_time, end)
        self.assertEqual(period.reason, "FOMC Meeting")
    
    def test_is_blocked_inside_window(self):
        """Test is_blocked returns True when time is inside window"""
        start = datetime(2026, 3, 18, 17, 45)
        end = datetime(2026, 3, 18, 18, 15)
        
        period = BlockedPeriod(start_time=start, end_time=end, reason="Test")
        
        # Test time inside window
        test_time = datetime(2026, 3, 18, 18, 0)
        self.assertTrue(period.is_blocked(test_time))
        
        # Test at boundaries
        self.assertTrue(period.is_blocked(start))
        self.assertTrue(period.is_blocked(end))
    
    def test_is_blocked_outside_window(self):
        """Test is_blocked returns False when time is outside window"""
        start = datetime(2026, 3, 18, 17, 45)
        end = datetime(2026, 3, 18, 18, 15)
        
        period = BlockedPeriod(start_time=start, end_time=end, reason="Test")
        
        # Before window
        self.assertFalse(period.is_blocked(datetime(2026, 3, 18, 17, 44)))
        
        # After window
        self.assertFalse(period.is_blocked(datetime(2026, 3, 18, 18, 16)))
    
    def test_to_dict(self):
        """Test conversion to dictionary"""
        start = datetime(2026, 3, 18, 17, 45)
        end = datetime(2026, 3, 18, 18, 15)
        
        period = BlockedPeriod(start_time=start, end_time=end, reason="FOMC")
        
        result = period.to_dict()
        
        self.assertEqual(result['start_time'], '2026-03-18T17:45:00')
        self.assertEqual(result['end_time'], '2026-03-18T18:15:00')
        self.assertEqual(result['reason'], 'FOMC')


class TestEventBlocker(unittest.TestCase):
    """Test EventBlocker class"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Create mock calendar adapter
        self.mock_calendar = Mock(spec=ManualCalendarAdapter)
        self.mock_calendar.fetch_calendar = Mock(return_value=[])
        
        # Create EventBlocker with default settings
        self.blocker = EventBlocker(
            calendar_adapter=self.mock_calendar,
            pre_event_minutes=15,
            post_event_minutes=15,
            stabilization_minutes=15
        )
    
    def test_initialization(self):
        """Test EventBlocker initialization"""
        self.assertEqual(self.blocker.pre_event_minutes, 15)
        self.assertEqual(self.blocker.post_event_minutes, 15)
        self.assertEqual(self.blocker.stabilization_minutes, 15)
        self.assertEqual(len(self.blocker.blocked_periods), 0)
        self.assertIsNone(self.blocker.last_update)
    
    def test_custom_initialization(self):
        """Test EventBlocker with custom parameters"""
        blocker = EventBlocker(
            calendar_adapter=self.mock_calendar,
            pre_event_minutes=30,
            post_event_minutes=45,
            stabilization_minutes=20,
            volatility_spike_threshold=2.0
        )
        
        self.assertEqual(blocker.pre_event_minutes, 30)
        self.assertEqual(blocker.post_event_minutes, 45)
        self.assertEqual(blocker.stabilization_minutes, 20)
        self.assertEqual(blocker.volatility_spike_threshold, 2.0)
    
    def test_update_blocked_periods_no_events(self):
        """Test update_blocked_periods with no events"""
        current_time = datetime(2026, 3, 13, 10, 0)
        
        # Mock fetch_calendar to return empty list
        self.mock_calendar.fetch_calendar.return_value = []
        
        self.blocker.update_blocked_periods(current_time)
        
        self.assertEqual(len(self.blocker.blocked_periods), 0)
        self.assertEqual(self.blocker.last_update, current_time)
        
        # Verify fetch_calendar was called with correct params
        self.mock_calendar.fetch_calendar.assert_called_once()
    
    def test_update_blocked_periods_with_events(self):
        """Test update_blocked_periods with high-impact events"""
        current_time = datetime(2026, 3, 13, 10, 0)
        
        # Create mock event (FOMC on March 18 at 18:00)
        mock_event = Mock()
        mock_event.time_utc = datetime(2026, 3, 18, 18, 0)
        mock_event.category = "FOMC"
        mock_event.is_high_impact.return_value = True
        
        self.mock_calendar.fetch_calendar.return_value = [mock_event]
        
        self.blocker.update_blocked_periods(current_time)
        
        # Should create 1 blocked period
        self.assertEqual(len(self.blocker.blocked_periods), 1)
        
        period = self.blocker.blocked_periods[0]
        
        # Check block window: 15 min before, 15 min after
        expected_start = datetime(2026, 3, 18, 17, 45)  # 18:00 - 15 min
        expected_end = datetime(2026, 3, 18, 18, 15)    # 18:00 + 15 min
        
        self.assertEqual(period.start_time, expected_start)
        self.assertEqual(period.end_time, expected_end)
        self.assertIn("FOMC", period.reason)
    
    def test_update_blocked_periods_multiple_events(self):
        """Test update_blocked_periods with multiple high-impact events"""
        current_time = datetime(2026, 3, 1, 10, 0)
        
        # Create multiple mock events
        fomc_event = Mock()
        fomc_event.time_utc = datetime(2026, 3, 18, 18, 0)
        fomc_event.category = "FOMC"
        fomc_event.is_high_impact.return_value = True
        
        nfp_event = Mock()
        nfp_event.time_utc = datetime(2026, 3, 6, 12, 30)
        nfp_event.category = "NFP"
        nfp_event.is_high_impact.return_value = True
        
        cpi_event = Mock()
        cpi_event.time_utc = datetime(2026, 3, 11, 12, 30)
        cpi_event.category = "CPI"
        cpi_event.is_high_impact.return_value = True
        
        self.mock_calendar.fetch_calendar.return_value = [fomc_event, nfp_event, cpi_event]
        
        self.blocker.update_blocked_periods(current_time)
        
        # Should create 3 blocked periods
        self.assertEqual(len(self.blocker.blocked_periods), 3)
    
    def test_update_blocked_periods_filters_low_impact(self):
        """Test that low-impact events are NOT blocked"""
        current_time = datetime(2026, 3, 13, 10, 0)
        
        # Create low-impact event
        low_impact = Mock()
        low_impact.time_utc = datetime(2026, 3, 15, 12, 0)
        low_impact.category = "Minor Data"
        low_impact.is_high_impact.return_value = False
        
        # Create high-impact event
        high_impact = Mock()
        high_impact.time_utc = datetime(2026, 3, 18, 18, 0)
        high_impact.category = "FOMC"
        high_impact.is_high_impact.return_value = True
        
        self.mock_calendar.fetch_calendar.return_value = [low_impact, high_impact]
        
        self.blocker.update_blocked_periods(current_time)
        
        # Should only create 1 blocked period (high impact only)
        self.assertEqual(len(self.blocker.blocked_periods), 1)
        self.assertIn("FOMC", self.blocker.blocked_periods[0].reason)
    
    def test_is_blocked_by_event_during_block(self):
        """Test is_blocked_by_event returns True during blocked period"""
        current_time = datetime(2026, 3, 18, 18, 0)  # During FOMC
        
        # Create blocked period (17:45 - 18:15)
        period = BlockedPeriod(
            start_time=datetime(2026, 3, 18, 17, 45),
            end_time=datetime(2026, 3, 18, 18, 15),
            reason="FOMC Meeting"
        )
        self.blocker.blocked_periods = [period]
        self.blocker.last_update = current_time  # Prevent re-fetching
        
        is_blocked, reason = self.blocker.is_blocked_by_event(
            current_time,
            update_if_stale=False  # Don't update
        )
        
        self.assertTrue(is_blocked)
        self.assertEqual(reason, "FOMC Meeting")
    
    def test_is_blocked_by_event_outside_block(self):
        """Test is_blocked_by_event returns False outside blocked period"""
        current_time = datetime(2026, 3, 18, 18, 30)  # After FOMC block
        
        # Create blocked period (17:45 - 18:15)
        period = BlockedPeriod(
            start_time=datetime(2026, 3, 18, 17, 45),
            end_time=datetime(2026, 3, 18, 18, 15),
            reason="FOMC Meeting"
        )
        self.blocker.blocked_periods = [period]
        
        is_blocked, reason = self.blocker.is_blocked_by_event(current_time)
        
        self.assertFalse(is_blocked)
        self.assertIsNone(reason)
    
    def test_is_trading_allowed_not_blocked(self):
        """Test is_trading_allowed returns True when not blocked"""
        current_time = datetime(2026, 3, 13, 10, 0)  # Normal trading time
        
        # No blocked periods
        self.blocker.blocked_periods = []
        
        is_allowed, reason = self.blocker.is_trading_allowed(current_time)
        
        self.assertTrue(is_allowed)
        self.assertIsNone(reason)
    
    def test_is_trading_allowed_blocked_by_event(self):
        """Test is_trading_allowed returns False when blocked by event"""
        current_time = datetime(2026, 3, 18, 18, 0)  # During FOMC
        
        # Create blocked period
        period = BlockedPeriod(
            start_time=datetime(2026, 3, 18, 17, 45),
            end_time=datetime(2026, 3, 18, 18, 15),
            reason="FOMC Meeting"
        )
        self.blocker.blocked_periods = [period]
        self.blocker.last_update = current_time  # Prevent re-fetching
        
        # Mock is_blocked_by_event to return blocked
        with patch.object(self.blocker, 'is_blocked_by_event', return_value=(True, "FOMC Meeting")):
            is_allowed, reason = self.blocker.is_trading_allowed(current_time)
        
        self.assertFalse(is_allowed)
        self.assertIn("FOMC", reason)
    
    def test_get_next_blocked_period(self):
        """Test get_next_blocked_period finds upcoming block"""
        current_time = datetime(2026, 3, 13, 10, 0)
        
        # Create future blocked period (FOMC on March 18)
        period = BlockedPeriod(
            start_time=datetime(2026, 3, 18, 17, 45),
            end_time=datetime(2026, 3, 18, 18, 15),
            reason="FOMC Meeting"
        )
        self.blocker.blocked_periods = [period]
        self.blocker.last_update = current_time  # Prevent re-fetching
        
        next_period = self.blocker.get_next_blocked_period(current_time)
        
        self.assertIsNotNone(next_period)
        self.assertEqual(next_period.reason, "FOMC Meeting")
    
    def test_get_next_blocked_period_none(self):
        """Test get_next_blocked_period returns None when no upcoming blocks"""
        current_time = datetime(2026, 3, 20, 10, 0)
        
        # Create past blocked period
        period = BlockedPeriod(
            start_time=datetime(2026, 3, 18, 17, 45),
            end_time=datetime(2026, 3, 18, 18, 15),
            reason="FOMC Meeting"
        )
        self.blocker.blocked_periods = [period]
        
        next_period = self.blocker.get_next_blocked_period(current_time)
        
        self.assertIsNone(next_period)
    
    def test_get_minutes_to_next_block(self):
        """Test get_minutes_to_next_block calculates time correctly"""
        current_time = datetime(2026, 3, 18, 17, 0)  # 45 min before block
        
        # Blocked period starts at 17:45
        period = BlockedPeriod(
            start_time=datetime(2026, 3, 18, 17, 45),
            end_time=datetime(2026, 3, 18, 18, 15),
            reason="FOMC Meeting"
        )
        self.blocker.blocked_periods = [period]
        self.blocker.last_update = current_time  # Prevent re-fetching
        
        minutes = self.blocker.get_minutes_to_next_block(current_time)
        
        self.assertEqual(minutes, 45)
    
    def test_get_minutes_to_next_block_during_block(self):
        """Test get_minutes_to_next_block returns None when currently blocked"""
        current_time = datetime(2026, 3, 18, 18, 0)  # During block
        
        period = BlockedPeriod(
            start_time=datetime(2026, 3, 18, 17, 45),
            end_time=datetime(2026, 3, 18, 18, 15),
            reason="FOMC Meeting"
        )
        self.blocker.blocked_periods = [period]
        self.blocker.last_update = current_time  # Prevent re-fetching
        
        minutes = self.blocker.get_minutes_to_next_block(current_time)
        
        # When currently blocked, there's no "next" block (it's now)
        # The method returns None if no future blocks
        self.assertIsNone(minutes)
    
    def test_get_blocked_periods_summary(self):
        """Test get_blocked_periods_summary returns formatted data"""
        current_time = datetime(2026, 3, 1, 12, 0)
        
        # Create multiple blocked periods
        period1 = BlockedPeriod(
            start_time=datetime(2026, 3, 18, 17, 45),
            end_time=datetime(2026, 3, 18, 18, 15),
            reason="FOMC Meeting"
        )
        period2 = BlockedPeriod(
            start_time=datetime(2026, 3, 6, 12, 15),
            end_time=datetime(2026, 3, 6, 13, 0),
            reason="NFP Release"
        )
        
        self.blocker.blocked_periods = [period1, period2]
        
        # Patch update_blocked_periods to not clear our manually set periods
        with patch.object(self.blocker, 'update_blocked_periods'):
            summary = self.blocker.get_blocked_periods_summary(current_time)
        
        # Summary is a list of dicts, not a dict with total_blocked_periods
        self.assertEqual(len(summary), 2)
        self.assertIn('start_time', summary[0])
        self.assertIn('reason', summary[0])


class TestEventBlockerEdgeCases(unittest.TestCase):
    """Test edge cases and error handling"""
    
    def test_blocker_without_news_adapter(self):
        """Test EventBlocker works without news adapter (optional)"""
        mock_calendar = Mock(spec=ManualCalendarAdapter)
        mock_calendar.fetch_calendar = Mock(return_value=[])
        
        blocker = EventBlocker(
            calendar_adapter=mock_calendar,
            news_adapter=None  # No news adapter
        )
        
        self.assertIsNone(blocker.news_adapter)
        
        # Should still work for calendar blocking
        current_time = datetime(2026, 3, 13, 10, 0)
        is_allowed, reason = blocker.is_trading_allowed(current_time)
        
        self.assertTrue(is_allowed)  # No blocks, so allowed
    
    def test_multiple_overlapping_blocks(self):
        """Test handling of overlapping blocked periods"""
        mock_calendar = Mock(spec=ManualCalendarAdapter)
        mock_calendar.fetch_calendar = Mock(return_value=[])
        
        blocker = EventBlocker(
            calendar_adapter=mock_calendar,
            pre_event_minutes=15,
            post_event_minutes=15
        )
        
        # Create overlapping periods
        period1 = BlockedPeriod(
            start_time=datetime(2026, 3, 18, 17, 45),
            end_time=datetime(2026, 3, 18, 18, 15),
            reason="Event 1"
        )
        period2 = BlockedPeriod(
            start_time=datetime(2026, 3, 18, 18, 0),
            end_time=datetime(2026, 3, 18, 18, 30),
            reason="Event 2"
        )
        
        blocker.blocked_periods = [period1, period2]
        blocker.last_update = datetime(2026, 3, 18, 17, 0)
        
        # Time during overlap
        test_time = datetime(2026, 3, 18, 18, 10)
        
        is_blocked, reason = blocker.is_blocked_by_event(
            test_time,
            update_if_stale=False
        )
        
        self.assertTrue(is_blocked)
        # Should return first matching reason
        self.assertIn("Event", reason)
    
    def test_boundary_precision(self):
        """Test that block boundaries are precise to the minute"""
        mock_calendar = Mock(spec=ManualCalendarAdapter)
        mock_calendar.fetch_calendar = Mock(return_value=[])
        
        blocker = EventBlocker(
            calendar_adapter=mock_calendar,
            pre_event_minutes=15,
            post_event_minutes=15
        )
        
        period = BlockedPeriod(
            start_time=datetime(2026, 3, 18, 17, 45, 0),  # Exactly 17:45:00
            end_time=datetime(2026, 3, 18, 18, 15, 0),    # Exactly 18:15:00
            reason="FOMC"
        )
        blocker.blocked_periods = [period]
        blocker.last_update = datetime(2026, 3, 18, 17, 0)
        
        # Test one second before start
        self.assertFalse(blocker.is_blocked_by_event(
            datetime(2026, 3, 18, 17, 44, 59),
            update_if_stale=False
        )[0])
        
        # Test at exact start
        self.assertTrue(blocker.is_blocked_by_event(
            datetime(2026, 3, 18, 17, 45, 0),
            update_if_stale=False
        )[0])
        
        # Test at exact end
        self.assertTrue(blocker.is_blocked_by_event(
            datetime(2026, 3, 18, 18, 15, 0),
            update_if_stale=False
        )[0])
        
        # Test one second after end
        self.assertFalse(blocker.is_blocked_by_event(
            datetime(2026, 3, 18, 18, 15, 1),
            update_if_stale=False
        )[0])


if __name__ == '__main__':
    unittest.main()
