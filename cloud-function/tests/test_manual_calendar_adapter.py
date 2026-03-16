"""
Unit tests for ManualCalendarAdapter

Tests loading, filtering, and querying of economic calendar events from JSON file.
"""

import unittest
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.manual_calendar_adapter import ManualCalendarAdapter, CalendarEvent


class TestCalendarEvent(unittest.TestCase):
    """Test CalendarEvent dataclass"""
    
    def test_calendar_event_creation(self):
        """Test creating a calendar event"""
        event = CalendarEvent(
            date="2026-03-18",
            time_utc="18:00",
            event="FOMC",
            description="Federal Reserve Meeting",
            country="US",
            importance="high",
            block_minutes_before=15,
            block_minutes_after=30
        )
        
        self.assertEqual(event.date, "2026-03-18")
        self.assertEqual(event.time_utc, "18:00")
        self.assertEqual(event.event, "FOMC")
        self.assertEqual(event.country, "US")
        self.assertEqual(event.importance, "high")
    
    def test_datetime_utc_property(self):
        """Test datetime_utc property converts date+time correctly"""
        event = CalendarEvent(
            date="2026-03-18",
            time_utc="18:00",
            event="FOMC",
            description="Federal Reserve Meeting",
            country="US",
            importance="high"
        )
        
        expected = datetime(2026, 3, 18, 18, 0)
        self.assertEqual(event.datetime_utc, expected)
    
    def test_is_high_impact_true(self):
        """Test is_high_impact returns True for high importance"""
        event = CalendarEvent(
            date="2026-03-18",
            time_utc="18:00",
            event="FOMC",
            description="FOMC Meeting",
            country="US",
            importance="high"
        )
        
        self.assertTrue(event.is_high_impact())
    
    def test_is_high_impact_false(self):
        """Test is_high_impact returns False for medium/low importance"""
        event_medium = CalendarEvent(
            date="2026-03-15",
            time_utc="12:00",
            event="Minor Data",
            description="Some data",
            country="US",
            importance="medium"
        )
        
        event_low = CalendarEvent(
            date="2026-03-15",
            time_utc="12:00",
            event="Minor Data",
            description="Some data",
            country="US",
            importance="low"
        )
        
        self.assertFalse(event_medium.is_high_impact())
        self.assertFalse(event_low.is_high_impact())
    
    def test_minutes_until_event_future(self):
        """Test minutes_until_event for future event"""
        event = CalendarEvent(
            date="2026-03-18",
            time_utc="18:00",
            event="FOMC",
            description="FOMC Meeting",
            country="US",
            importance="high"
        )
        
        # Current time: 1 hour before event
        current_time = datetime(2026, 3, 18, 17, 0)
        
        minutes = event.minutes_until_event(current_time)
        
        self.assertEqual(minutes, 60)
    
    def test_minutes_until_event_past(self):
        """Test minutes_until_event for past event (negative)"""
        event = CalendarEvent(
            date="2026-03-18",
            time_utc="18:00",
            event="FOMC",
            description="FOMC Meeting",
            country="US",
            importance="high"
        )
        
        # Current time: 30 min after event
        current_time = datetime(2026, 3, 18, 18, 30)
        
        minutes = event.minutes_until_event(current_time)
        
        self.assertEqual(minutes, -30)


class TestManualCalendarAdapter(unittest.TestCase):
    """Test ManualCalendarAdapter class"""
    
    def setUp(self):
        """Set up test fixtures with temporary JSON file"""
        self.test_data = {
            "updated_at": "2026-03-13T10:00:00",
            "total_events": 3,
            "events": [
                {
                    "date": "2026-03-18",
                    "time_utc": "18:00",
                    "event": "FOMC",
                    "description": "Federal Reserve Meeting",
                    "country": "US",
                    "importance": "high",
                    "block_minutes_before": 15,
                    "block_minutes_after": 30
                },
                {
                    "date": "2026-03-06",
                    "time_utc": "12:30",
                    "event": "NFP",
                    "description": "Non-Farm Payrolls",
                    "country": "US",
                    "importance": "high",
                    "block_minutes_before": 15,
                    "block_minutes_after": 30
                },
                {
                    "date": "2026-03-15",
                    "time_utc": "09:30",
                    "event": "UK_RETAIL",
                    "description": "UK Retail Sales",
                    "country": "UK",
                    "importance": "medium",
                    "block_minutes_before": 10,
                    "block_minutes_after": 10
                }
            ]
        }
        
        # Create temporary file
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        json.dump(self.test_data, self.temp_file)
        self.temp_file.close()
    
    def tearDown(self):
        """Clean up temporary file"""
        Path(self.temp_file.name).unlink()
    
    def test_load_calendar_success(self):
        """Test successfully loading calendar from JSON file"""
        adapter = ManualCalendarAdapter(calendar_file=self.temp_file.name)
        
        # Should load 2 US events + 1 UK event = 3 total (with default filter)
        self.assertEqual(len(adapter.events), 3)
    
    def test_load_calendar_file_not_found(self):
        """Test handling of missing calendar file"""
        adapter = ManualCalendarAdapter(calendar_file="nonexistent.json")
        
        # Should not crash, just have empty events
        self.assertEqual(len(adapter.events), 0)
    
    def test_filter_by_country(self):
        """Test filtering events by country"""
        # Filter only US events
        adapter = ManualCalendarAdapter(
            calendar_file=self.temp_file.name,
            filter_countries=['US']
        )
        
        # Should only have 2 US events (FOMC, NFP)
        self.assertEqual(len(adapter.events), 2)
        
        for event in adapter.events:
            self.assertEqual(event.country, 'US')
    
    def test_filter_multiple_countries(self):
        """Test filtering with multiple countries"""
        adapter = ManualCalendarAdapter(
            calendar_file=self.temp_file.name,
            filter_countries=['US', 'UK']
        )
        
        # Should have all 3 events
        self.assertEqual(len(adapter.events), 3)
    
    def test_fetch_calendar_date_range(self):
        """Test fetching events within date range"""
        adapter = ManualCalendarAdapter(calendar_file=self.temp_file.name)
        
        # Fetch events in March 2026
        start_date = datetime(2026, 3, 1)
        end_date = datetime(2026, 3, 31)
        
        events = adapter.fetch_calendar(start_date, end_date)
        
        # Should return all 3 events (all in March)
        self.assertEqual(len(events), 3)
    
    def test_fetch_calendar_narrow_range(self):
        """Test fetching events in narrow date range"""
        adapter = ManualCalendarAdapter(calendar_file=self.temp_file.name)
        
        # Fetch only March 18-19 (should get FOMC only)
        start_date = datetime(2026, 3, 18)
        end_date = datetime(2026, 3, 19)
        
        events = adapter.fetch_calendar(start_date, end_date)
        
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event, "FOMC")
    
    def test_fetch_calendar_outside_range(self):
        """Test fetching events outside available range"""
        adapter = ManualCalendarAdapter(calendar_file=self.temp_file.name)
        
        # Fetch events in April (none available)
        start_date = datetime(2026, 4, 1)
        end_date = datetime(2026, 4, 30)
        
        events = adapter.fetch_calendar(start_date, end_date)
        
        self.assertEqual(len(events), 0)
    
    def test_get_events_today(self):
        """Test getting events for today"""
        adapter = ManualCalendarAdapter(calendar_file=self.temp_file.name)
        
        # Mock "today" as March 18, 2026
        test_date = datetime(2026, 3, 18)
        
        # Use get_events_in_range for same day
        events = adapter.get_events_in_range(
            start_time=test_date,
            end_time=test_date + timedelta(days=1),
            high_impact_only=False
        )
        
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event, "FOMC")
    
    def test_get_high_impact_events(self):
        """Test filtering only high-impact events"""
        adapter = ManualCalendarAdapter(calendar_file=self.temp_file.name)
        
        start_date = datetime(2026, 3, 1)
        end_date = datetime(2026, 3, 31)
        
        # Use get_events_in_range with high_impact_only=True
        events = adapter.get_events_in_range(
            start_time=start_date,
            end_time=end_date,
            high_impact_only=True
        )
        
        # Should only return FOMC and NFP (both high impact)
        self.assertEqual(len(events), 2)
        
        event_names = [e.event for e in events]
        self.assertIn("FOMC", event_names)
        self.assertIn("NFP", event_names)
        self.assertNotIn("UK_RETAIL", event_names)
    
    def test_is_blocked(self):
        """Test is_blocked method"""
        adapter = ManualCalendarAdapter(calendar_file=self.temp_file.name)
        
        # Check during FOMC block window (17:45 - 18:30)
        blocked_time = datetime(2026, 3, 18, 18, 0)
        
        is_blocked, event = adapter.is_blocked(blocked_time)
        
        self.assertTrue(is_blocked)
        self.assertIsNotNone(event)
        self.assertEqual(event.event, "FOMC")
    
    def test_is_blocked_outside_window(self):
        """Test is_blocked returns False outside block window"""
        adapter = ManualCalendarAdapter(calendar_file=self.temp_file.name)
        
        # Check time well before FOMC
        normal_time = datetime(2026, 3, 18, 10, 0)
        
        is_blocked, event = adapter.is_blocked(normal_time)
        
        self.assertFalse(is_blocked)
        self.assertIsNone(event)
    
    def test_get_next_event(self):
        """Test get_next_event finds nearest future event"""
        adapter = ManualCalendarAdapter(calendar_file=self.temp_file.name)
        
        # Current time: March 10 (between NFP on 6th and FOMC on 18th)
        current_time = datetime(2026, 3, 10, 12, 0)
        
        # Get next event without filtering by impact
        next_event = adapter.get_next_event(current_time, high_impact_only=False)
        
        self.assertIsNotNone(next_event)
        # Should be UK_RETAIL on March 15 (closest future event)
        self.assertEqual(next_event.event, "UK_RETAIL")
    
    def test_get_next_event_none(self):
        """Test get_next_event returns None when no future events"""
        adapter = ManualCalendarAdapter(calendar_file=self.temp_file.name)
        
        # Current time: After all events in March
        current_time = datetime(2026, 3, 25, 12, 0)
        
        next_event = adapter.get_next_event(current_time)
        
        self.assertIsNone(next_event)


class TestManualCalendarAdapterEdgeCases(unittest.TestCase):
    """Test edge cases and error handling"""
    
    def test_empty_calendar_file(self):
        """Test handling empty calendar file"""
        empty_data = {
            "updated_at": "2026-03-13T10:00:00",
            "total_events": 0,
            "events": []
        }
        
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        json.dump(empty_data, temp_file)
        temp_file.close()
        
        try:
            adapter = ManualCalendarAdapter(calendar_file=temp_file.name)
            
            self.assertEqual(len(adapter.events), 0)
            
            # fetch_calendar should return empty list
            events = adapter.fetch_calendar(
                datetime(2026, 3, 1),
                datetime(2026, 3, 31)
            )
            self.assertEqual(len(events), 0)
        finally:
            Path(temp_file.name).unlink()
    
    def test_malformed_json(self):
        """Test handling of malformed JSON file"""
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        temp_file.write("{ invalid json }")
        temp_file.close()
        
        try:
            adapter = ManualCalendarAdapter(calendar_file=temp_file.name)
            
            # Should not crash, just have empty events
            self.assertEqual(len(adapter.events), 0)
        finally:
            Path(temp_file.name).unlink()
    
    def test_missing_fields_in_event(self):
        """Test handling of events with missing required fields"""
        incomplete_data = {
            "updated_at": "2026-03-13T10:00:00",
            "total_events": 1,
            "events": [
                {
                    "date": "2026-03-18",
                    # Missing time_utc
                    "event": "FOMC",
                    "country": "US"
                }
            ]
        }
        
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        json.dump(incomplete_data, temp_file)
        temp_file.close()
        
        try:
            adapter = ManualCalendarAdapter(calendar_file=temp_file.name)
            
            # Should handle gracefully (skip incomplete events)
            # Implementation may vary - test that it doesn't crash
            self.assertIsInstance(adapter.events, list)
        finally:
            Path(temp_file.name).unlink()
    
    def test_invalid_date_format(self):
        """Test handling of invalid date format"""
        invalid_data = {
            "updated_at": "2026-03-13T10:00:00",
            "total_events": 1,
            "events": [
                {
                    "date": "18-03-2026",  # Wrong format (should be YYYY-MM-DD)
                    "time_utc": "18:00",
                    "event": "FOMC",
                    "description": "FOMC Meeting",
                    "country": "US",
                    "importance": "high"
                }
            ]
        }
        
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        json.dump(invalid_data, temp_file)
        temp_file.close()
        
        try:
            adapter = ManualCalendarAdapter(calendar_file=temp_file.name)
            
            # Should handle gracefully
            self.assertIsInstance(adapter.events, list)
        finally:
            Path(temp_file.name).unlink()
    
    def test_boundary_times(self):
        """Test events at midnight boundaries"""
        boundary_data = {
            "updated_at": "2026-03-13T10:00:00",
            "total_events": 2,
            "events": [
                {
                    "date": "2026-03-18",
                    "time_utc": "00:00",  # Midnight start
                    "event": "EVENT1",
                    "description": "Midnight event",
                    "country": "US",
                    "importance": "high",
                    "block_minutes_before": 15,
                    "block_minutes_after": 15
                },
                {
                    "date": "2026-03-18",
                    "time_utc": "23:59",  # End of day
                    "event": "EVENT2",
                    "description": "End of day event",
                    "country": "US",
                    "importance": "high",
                    "block_minutes_before": 15,
                    "block_minutes_after": 15
                }
            ]
        }
        
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        json.dump(boundary_data, temp_file)
        temp_file.close()
        
        try:
            adapter = ManualCalendarAdapter(calendar_file=temp_file.name)
            
            self.assertEqual(len(adapter.events), 2)
            
            # Test midnight event
            midnight_event = adapter.events[0]
            self.assertEqual(midnight_event.datetime_utc.hour, 0)
            self.assertEqual(midnight_event.datetime_utc.minute, 0)
            
            # Test end-of-day event
            eod_event = adapter.events[1]
            self.assertEqual(eod_event.datetime_utc.hour, 23)
            self.assertEqual(eod_event.datetime_utc.minute, 59)
        finally:
            Path(temp_file.name).unlink()


if __name__ == '__main__':
    unittest.main()
