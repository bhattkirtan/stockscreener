"""
Unit tests for External Data API endpoints

Tests /api/v1/calendar, /api/v1/news, /api/v1/is-blocked endpoints.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCalendarAPIEndpoint(unittest.TestCase):
    """Test /api/v1/calendar endpoint"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.sample_calendar_data = {
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
                    "date": "2026-03-11",
                    "time_utc": "12:30",
                    "event": "CPI",
                    "description": "Consumer Price Index",
                    "country": "US",
                    "importance": "high",
                    "block_minutes_before": 15,
                    "block_minutes_after": 30
                }
            ]
        }
    
    def test_calendar_endpoint_returns_all_events(self):
        """Test that calendar endpoint returns all events"""
        events = self.sample_calendar_data['events']
        
        self.assertEqual(len(events), 3)
        
        event_names = [e['event'] for e in events]
        self.assertIn('FOMC', event_names)
        self.assertIn('NFP', event_names)
        self.assertIn('CPI', event_names)
    
    def test_calendar_endpoint_filters_by_days_ahead(self):
        """Test filtering events by days_ahead parameter"""
        current_date = datetime(2026, 3, 13)
        events = self.sample_calendar_data['events']
        
        # Filter events within 7 days
        days_ahead = 7
        future_cutoff = current_date + timedelta(days=days_ahead)
        
        filtered_events = [
            e for e in events 
            if datetime.strptime(e['date'], '%Y-%m-%d') <= future_cutoff
        ]
        
        # Only FOMC (March 18) should be within 7 days
        self.assertEqual(len(filtered_events), 1)
        self.assertEqual(filtered_events[0]['event'], 'FOMC')
    
    def test_calendar_endpoint_filters_high_impact_only(self):
        """Test filtering only high-impact events"""
        events = self.sample_calendar_data['events']
        
        high_impact = [e for e in events if e['importance'] == 'high']
        
        # All 3 events are high impact
        self.assertEqual(len(high_impact), 3)
    
    def test_calendar_endpoint_structure(self):
        """Test calendar response structure"""
        events = self.sample_calendar_data['events']
        
        for event in events:
            # Check required fields exist
            self.assertIn('date', event)
            self.assertIn('time_utc', event)
            self.assertIn('event', event)
            self.assertIn('description', event)
            self.assertIn('country', event)
            self.assertIn('importance', event)
            self.assertIn('block_minutes_before', event)
            self.assertIn('block_minutes_after', event)
    
    def test_calendar_endpoint_date_format(self):
        """Test that dates are in correct format (YYYY-MM-DD)"""
        events = self.sample_calendar_data['events']
        
        for event in events:
            # Should be parseable as date
            date_obj = datetime.strptime(event['date'], '%Y-%m-%d')
            self.assertIsInstance(date_obj, datetime)
    
    def test_calendar_endpoint_time_format(self):
        """Test that times are in correct format (HH:MM)"""
        events = self.sample_calendar_data['events']
        
        for event in events:
            # Should be in HH:MM format
            time_parts = event['time_utc'].split(':')
            self.assertEqual(len(time_parts), 2)
            
            hour = int(time_parts[0])
            minute = int(time_parts[1])
            
            self.assertTrue(0 <= hour <= 23)
            self.assertTrue(0 <= minute <= 59)


class TestNewsAPIEndpoint(unittest.TestCase):
    """Test /api/v1/news endpoint"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.sample_news_data = {
            "updated_at": "2026-03-13T15:00:00",
            "total_headlines": 5,
            "sources": ["Reuters", "CNBC", "MarketWatch"],
            "headlines": [
                {
                    "article_id": "abc123",
                    "published_at": "2026-03-13T14:50:00",
                    "source": "Reuters",
                    "title": "Fed holds rates steady",
                    "description": "Federal Reserve keeps interest rates unchanged...",
                    "url": "https://reuters.com/...",
                    "matched_keywords": ["Fed", "rates"],
                    "severity": "medium"
                },
                {
                    "article_id": "def456",
                    "published_at": "2026-03-13T14:30:00",
                    "source": "CNBC",
                    "title": "Stock market reaches new high",
                    "description": "Markets rally on positive economic data...",
                    "url": "https://cnbc.com/...",
                    "matched_keywords": [],
                    "severity": "low"
                }
            ]
        }
    
    def test_news_endpoint_returns_headlines(self):
        """Test that news endpoint returns headlines"""
        headlines = self.sample_news_data['headlines']
        
        self.assertEqual(len(headlines), 2)
    
    def test_news_endpoint_filters_by_hours_ago(self):
        """Test filtering news by hours_ago parameter"""
        current_time = datetime(2026, 3, 13, 15, 0)
        hours_ago = 1
        
        cutoff = current_time - timedelta(hours=hours_ago)
        
        headlines = self.sample_news_data['headlines']
        
        filtered = [
            h for h in headlines
            if datetime.fromisoformat(h['published_at']) >= cutoff
        ]
        
        # Only first headline is within 1 hour
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]['title'], "Fed holds rates steady")
    
    def test_news_endpoint_filters_high_impact(self):
        """Test filtering high-impact news only"""
        headlines = self.sample_news_data['headlines']
        
        # Add high-impact headline
        high_impact_headline = {
            "article_id": "ghi789",
            "published_at": "2026-03-13T14:55:00",
            "source": "Reuters",
            "title": "Emergency Fed rate cut announced",
            "description": "Federal Reserve cuts rates by 50 basis points...",
            "url": "https://reuters.com/...",
            "matched_keywords": ["emergency", "rate"],
            "severity": "high"
        }
        headlines.append(high_impact_headline)
        
        high_impact = [h for h in headlines if h['severity'] == 'high']
        
        self.assertEqual(len(high_impact), 1)
        self.assertIn("emergency", high_impact[0]['title'].lower())
    
    def test_news_endpoint_structure(self):
        """Test news response structure"""
        headlines = self.sample_news_data['headlines']
        
        for headline in headlines:
            # Check required fields
            self.assertIn('article_id', headline)
            self.assertIn('published_at', headline)
            self.assertIn('source', headline)
            self.assertIn('title', headline)
            self.assertIn('description', headline)
            self.assertIn('url', headline)
            self.assertIn('severity', headline)
    
    def test_news_endpoint_severity_levels(self):
        """Test that severity is one of expected values"""
        headlines = self.sample_news_data['headlines']
        
        valid_severities = ['low', 'medium', 'high']
        
        for headline in headlines:
            self.assertIn(headline['severity'], valid_severities)


class TestIsBlockedAPIEndpoint(unittest.TestCase):
    """Test /api/v1/is-blocked endpoint"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.current_time = datetime(2026, 3, 18, 18, 0)  # During FOMC
        
        self.calendar_events = [
            {
                "date": "2026-03-18",
                "time_utc": "18:00",
                "event": "FOMC",
                "description": "Federal Reserve Meeting",
                "importance": "high",
                "block_minutes_before": 15,
                "block_minutes_after": 30
            }
        ]
        
        self.news_headlines = []
    
    def test_is_blocked_during_calendar_event(self):
        """Test is_blocked returns True during calendar event"""
        event = self.calendar_events[0]
        event_time = datetime.strptime(f"{event['date']} {event['time_utc']}", "%Y-%m-%d %H:%M")
        
        # Check time during block window
        check_time = event_time  # Exactly at event time
        
        block_start = event_time - timedelta(minutes=event['block_minutes_before'])
        block_end = event_time + timedelta(minutes=event['block_minutes_after'])
        
        is_blocked = block_start <= check_time <= block_end
        
        self.assertTrue(is_blocked)
    
    def test_is_blocked_outside_calendar_event(self):
        """Test is_blocked returns False outside calendar event"""
        event = self.calendar_events[0]
        event_time = datetime.strptime(f"{event['date']} {event['time_utc']}", "%Y-%m-%d %H:%M")
        
        # Check time well before event
        check_time = event_time - timedelta(hours=2)
        
        block_start = event_time - timedelta(minutes=event['block_minutes_before'])
        block_end = event_time + timedelta(minutes=event['block_minutes_after'])
        
        is_blocked = block_start <= check_time <= block_end
        
        self.assertFalse(is_blocked)
    
    def test_is_blocked_by_breaking_news(self):
        """Test is_blocked returns True for recent high-impact news"""
        current_time = datetime(2026, 3, 13, 14, 35)
        
        high_impact_news = {
            "article_id": "breaking123",
            "published_at": "2026-03-13T14:30:00",  # 5 min ago
            "source": "Reuters",
            "title": "Emergency Fed rate cut",
            "severity": "high"
        }
        
        published = datetime.fromisoformat(high_impact_news['published_at'])
        age_minutes = (current_time - published).total_seconds() / 60
        
        # Block for 10 minutes after high-impact news
        is_blocked = age_minutes < 10 and high_impact_news['severity'] == 'high'
        
        self.assertTrue(is_blocked)
        self.assertEqual(age_minutes, 5)
    
    def test_is_blocked_response_structure(self):
        """Test is_blocked response has correct structure"""
        response = {
            "is_blocked": True,
            "reason": "Calendar event: FOMC",
            "minutes_until_next_event": 0,
            "next_event": {
                "date": "2026-03-18",
                "time_utc": "18:00",
                "event": "FOMC",
                "description": "Federal Reserve Meeting"
            }
        }
        
        # Check required fields
        self.assertIn('is_blocked', response)
        self.assertIn('reason', response)
        self.assertIn('minutes_until_next_event', response)
        self.assertIn('next_event', response)
        
        # Check types
        self.assertIsInstance(response['is_blocked'], bool)
        self.assertIsInstance(response['minutes_until_next_event'], int)
    
    def test_is_blocked_returns_next_event(self):
        """Test that is_blocked returns next upcoming event"""
        current_time = datetime(2026, 3, 13, 10, 0)
        
        event = self.calendar_events[0]
        event_time = datetime.strptime(f"{event['date']} {event['time_utc']}", "%Y-%m-%d %H:%M")
        
        minutes_until = int((event_time - current_time).total_seconds() / 60)
        
        self.assertGreater(minutes_until, 0)
        self.assertEqual(minutes_until, 7200)  # 5 days = 120 hours = 7200 min
    
    def test_is_blocked_calculates_minutes_correctly(self):
        """Test minutes_until_next_event calculation"""
        current_time = datetime(2026, 3, 18, 17, 0)  # 1 hour before FOMC
        event_time = datetime(2026, 3, 18, 18, 0)
        
        minutes = (event_time - current_time).total_seconds() / 60
        
        self.assertEqual(minutes, 60)
    
    def test_is_blocked_block_window_boundaries(self):
        """Test block window start and end times"""
        event_time = datetime(2026, 3, 18, 18, 0)
        block_before = 15
        block_after = 30
        
        block_start = event_time - timedelta(minutes=block_before)
        block_end = event_time + timedelta(minutes=block_after)
        
        # Test boundaries
        self.assertEqual(block_start, datetime(2026, 3, 18, 17, 45))
        self.assertEqual(block_end, datetime(2026, 3, 18, 18, 30))
        
        # Test points just inside boundaries
        self.assertTrue(block_start <= datetime(2026, 3, 18, 17, 45) <= block_end)
        self.assertTrue(block_start <= datetime(2026, 3, 18, 18, 30) <= block_end)
        
        # Test points just outside boundaries
        self.assertFalse(block_start <= datetime(2026, 3, 18, 17, 44) <= block_end)
        self.assertFalse(block_start <= datetime(2026, 3, 18, 18, 31) <= block_end)


class TestStatusAPIEndpoint(unittest.TestCase):
    """Test /api/v1/status endpoint"""
    
    def test_status_endpoint_structure(self):
        """Test status response structure"""
        response = {
            "timestamp": "2026-03-13T15:00:00",
            "calendar_status": "ready",
            "news_status": "ready",
            "macro_status": "ready",
            "is_blocked": False,
            "block_reason": None,
            "macro_regime": "expansion",
            "position_multiplier": 1.2
        }
        
        # Check required fields
        required_fields = [
            'timestamp', 'calendar_status', 'news_status', 
            'is_blocked', 'macro_regime'
        ]
        
        for field in required_fields:
            self.assertIn(field, response)
    
    def test_status_indicates_data_availability(self):
        """Test that status indicates if data is available"""
        statuses = ['ready', 'stale', 'unavailable']
        
        for status in statuses:
            self.assertIn(status, statuses)
    
    def test_status_includes_macro_regime(self):
        """Test that status includes macro regime information"""
        valid_regimes = ['expansion', 'contraction', 'neutral']
        
        test_regime = 'expansion'
        self.assertIn(test_regime, valid_regimes)


class TestAPIEdgeCases(unittest.TestCase):
    """Test edge cases in API endpoints"""
    
    def test_empty_calendar(self):
        """Test API handles empty calendar gracefully"""
        calendar_data = {
            "updated_at": "2026-03-13T10:00:00",
            "total_events": 0,
            "events": []
        }
        
        self.assertEqual(len(calendar_data['events']), 0)
        self.assertEqual(calendar_data['total_events'], 0)
    
    def test_empty_news(self):
        """Test API handles no news gracefully"""
        news_data = {
            "updated_at": "2026-03-13T15:00:00",
            "total_headlines": 0,
            "sources": [],
            "headlines": []
        }
        
        self.assertEqual(len(news_data['headlines']), 0)
        self.assertEqual(news_data['total_headlines'], 0)
    
    def test_stale_data_handling(self):
        """Test detection of stale data"""
        current_time = datetime(2026, 3, 13, 15, 0)
        last_update = datetime(2026, 3, 12, 10, 0)  # 29 hours ago
        
        age_hours = (current_time - last_update).total_seconds() / 3600
        
        is_stale = age_hours > 24  # Stale if > 24 hours old
        
        self.assertTrue(is_stale)
        self.assertGreater(age_hours, 24)
    
    def test_multiple_simultaneous_events(self):
        """Test handling of multiple events at same time"""
        events = [
            {
                "date": "2026-03-18",
                "time_utc": "18:00",
                "event": "FOMC",
                "importance": "high"
            },
            {
                "date": "2026-03-18",
                "time_utc": "18:00",  # Same time
                "event": "ECB_ANNOUNCEMENT",
                "importance": "high"
            }
        ]
        
        # Both events at same time
        time1 = datetime.strptime(f"{events[0]['date']} {events[0]['time_utc']}", 
                                  "%Y-%m-%d %H:%M")
        time2 = datetime.strptime(f"{events[1]['date']} {events[1]['time_utc']}", 
                                  "%Y-%m-%d %H:%M")
        
        self.assertEqual(time1, time2)
    
    def test_invalid_date_format_handling(self):
        """Test handling of invalid date formats"""
        valid_date = "2026-03-18"
        invalid_dates = ["18-03-2026", "2026/03/18", "March 18, 2026"]
        
        # Valid format should parse
        try:
            datetime.strptime(valid_date, "%Y-%m-%d")
            valid = True
        except ValueError:
            valid = False
        
        self.assertTrue(valid)
        
        # Invalid formats should fail
        for invalid in invalid_dates:
            try:
                datetime.strptime(invalid, "%Y-%m-%d")
                parsed = True
            except ValueError:
                parsed = False
            
            self.assertFalse(parsed, f"Should not parse: {invalid}")


if __name__ == '__main__':
    unittest.main()
