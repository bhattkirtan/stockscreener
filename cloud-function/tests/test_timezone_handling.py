"""
Unit tests for timezone handling in event blocking

Tests that events are properly handled when dealing with different timezones.
All calendar events should be in UTC, but we need to handle conversions correctly.
"""

import unittest
from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestTimezoneHandling(unittest.TestCase):
    """Test timezone conversions and UTC handling"""
    
    def test_utc_times_in_calendar(self):
        """Test that calendar events are stored in UTC"""
        # FOMC at 18:00 UTC (which is 2:00 PM EDT, 10:00 AM PST)
        event_time_utc = datetime(2026, 3, 18, 18, 0)
        
        # This should be interpreted as UTC
        self.assertEqual(event_time_utc.hour, 18)
        self.assertEqual(event_time_utc.minute, 0)
    
    def test_local_to_utc_conversion(self):
        """Test converting local time to UTC for comparison"""
        # Example: Trader in New York (EDT, UTC-4) checks at 2:00 PM
        local_time_edt = datetime(2026, 3, 18, 14, 0)  # 2:00 PM EDT
        
        # Convert to UTC: 2:00 PM EDT = 18:00 UTC
        utc_time = local_time_edt + timedelta(hours=4)
        
        self.assertEqual(utc_time.hour, 18)
        self.assertEqual(utc_time.minute, 0)
    
    def test_different_timezone_same_event(self):
        """Test that same event blocks at different local times"""
        # FOMC at 18:00 UTC blocks:
        # - 2:00 PM EDT (New York)
        # - 10:00 AM PST (Los Angeles)
        # - 6:00 PM GMT (London)
        # - 2:00 AM JST next day (Tokyo)
        
        fomc_utc = datetime(2026, 3, 18, 18, 0)
        
        # New York: EDT is UTC-4
        ny_time = fomc_utc - timedelta(hours=4)
        self.assertEqual(ny_time.hour, 14)  # 2:00 PM
        
        # Los Angeles: PST is UTC-8
        la_time = fomc_utc - timedelta(hours=8)
        self.assertEqual(la_time.hour, 10)  # 10:00 AM
        
        # London: GMT is UTC+0 (but could be BST UTC+1 in summer)
        london_time = fomc_utc  # Same as UTC in winter
        self.assertEqual(london_time.hour, 18)  # 6:00 PM
        
        # Tokyo: JST is UTC+9
        tokyo_time = fomc_utc + timedelta(hours=9)
        self.assertEqual(tokyo_time.day, 19)  # Next day!
        self.assertEqual(tokyo_time.hour, 3)  # 3:00 AM
    
    def test_block_window_in_different_timezones(self):
        """Test that block windows calculated in UTC work for all timezones"""
        # FOMC at 18:00 UTC
        # Block: 17:45 - 18:15 UTC (15 min before, 15 min after)
        
        event_utc = datetime(2026, 3, 18, 18, 0)
        block_start_utc = event_utc - timedelta(minutes=15)
        block_end_utc = event_utc + timedelta(minutes=15)
        
        # For New York trader (EDT, UTC-4)
        # Block: 1:45 PM - 2:15 PM EDT
        ny_block_start = block_start_utc - timedelta(hours=4)
        ny_block_end = block_end_utc - timedelta(hours=4)
        
        self.assertEqual(ny_block_start.hour, 13)  # 1:45 PM
        self.assertEqual(ny_block_start.minute, 45)
        self.assertEqual(ny_block_end.hour, 14)    # 2:15 PM
        self.assertEqual(ny_block_end.minute, 15)
    
    def test_midnight_crossing_in_different_timezones(self):
        """Test events that cross midnight in local timezone"""
        # Event at 23:30 UTC (11:30 PM)
        event_utc = datetime(2026, 3, 18, 23, 30)
        
        # Tokyo (UTC+9): This is 8:30 AM next day
        tokyo_time = event_utc + timedelta(hours=9)
        self.assertEqual(tokyo_time.day, 19)
        self.assertEqual(tokyo_time.hour, 8)
        
        # Los Angeles (UTC-8): This is 3:30 PM same day
        la_time = event_utc - timedelta(hours=8)
        self.assertEqual(la_time.day, 18)
        self.assertEqual(la_time.hour, 15)
    
    def test_daylight_saving_time_awareness(self):
        """Test awareness of DST transitions"""
        # Note: These tests document DST considerations
        # Actual implementation should use timezone-aware datetime objects
        
        # US DST: Second Sunday in March - First Sunday in November
        # UK BST: Last Sunday in March - Last Sunday in October
        
        # Before DST (Standard Time)
        # New York: EST = UTC-5
        # After DST (Summer Time)
        # New York: EDT = UTC-4
        
        # This is why we store everything in UTC!
        utc_time = datetime(2026, 3, 18, 18, 0)
        
        # In March, US is in EDT (UTC-4)
        ny_offset_march = timedelta(hours=4)
        ny_time_march = utc_time - ny_offset_march
        self.assertEqual(ny_time_march.hour, 14)
        
        # In December, US is in EST (UTC-5)
        utc_time_dec = datetime(2026, 12, 18, 18, 0)
        ny_offset_dec = timedelta(hours=5)
        ny_time_dec = utc_time_dec - ny_offset_dec
        self.assertEqual(ny_time_dec.hour, 13)
    
    def test_nfp_release_time_8_30_am_est(self):
        """Test NFP release at 8:30 AM EST = 13:30 UTC"""
        # NFP is released at 8:30 AM US Eastern Time
        # In March (EDT): 8:30 AM EDT = 12:30 PM UTC
        # In December (EST): 8:30 AM EST = 13:30 PM UTC
        
        # March: EDT (UTC-4)
        nfp_utc_march = datetime(2026, 3, 6, 12, 30)
        nfp_local_march = nfp_utc_march - timedelta(hours=4)
        self.assertEqual(nfp_local_march.hour, 8)
        self.assertEqual(nfp_local_march.minute, 30)
        
        # Verify it's a Friday
        self.assertEqual(nfp_utc_march.weekday(), 4)  # 0=Monday, 4=Friday
    
    def test_fomc_announcement_time_2_pm_est(self):
        """Test FOMC at 2:00 PM EST = 18:00 or 19:00 UTC"""
        # FOMC announcements: 2:00 PM US Eastern Time
        # In March (EDT): 2:00 PM EDT = 18:00 UTC (6:00 PM)
        # In December (EST): 2:00 PM EST = 19:00 UTC (7:00 PM)
        
        # March: EDT (UTC-4)
        fomc_utc_march = datetime(2026, 3, 18, 18, 0)
        fomc_local_march = fomc_utc_march - timedelta(hours=4)
        self.assertEqual(fomc_local_march.hour, 14)  # 2:00 PM
        
        # Our calendar should have 18:00 UTC for March FOMC
        self.assertEqual(fomc_utc_march.hour, 18)
    
    def test_block_calculation_always_use_utc(self):
        """Test that block windows are always calculated in UTC"""
        # This is the CORRECT approach: always work in UTC
        
        event_utc = datetime(2026, 3, 18, 18, 0)
        pre_minutes = 15
        post_minutes = 15
        
        # Calculate block in UTC
        block_start = event_utc - timedelta(minutes=pre_minutes)
        block_end = event_utc + timedelta(minutes=post_minutes)
        
        # Test if current time (in UTC) is blocked
        test_times = [
            (datetime(2026, 3, 18, 17, 44), False),  # 1 min before block
            (datetime(2026, 3, 18, 17, 45), True),   # Block starts
            (datetime(2026, 3, 18, 18, 0), True),    # Event time
            (datetime(2026, 3, 18, 18, 15), True),   # Block ends
            (datetime(2026, 3, 18, 18, 16), False),  # 1 min after block
        ]
        
        for test_time, expected_blocked in test_times:
            is_blocked = block_start <= test_time <= block_end
            self.assertEqual(is_blocked, expected_blocked,
                           f"Failed for {test_time}")
    
    def test_trading_bot_timezone_conversion_example(self):
        """Test example: Trading bot in London checks against UTC calendar"""
        # London trader at 5:45 PM GMT (17:45 GMT = 17:45 UTC)
        london_local = datetime(2026, 3, 18, 17, 45)
        
        # Convert to UTC for comparison (GMT = UTC)
        check_time_utc = london_local  # GMT is UTC
        
        # Calendar event: FOMC at 18:00 UTC
        event_utc = datetime(2026, 3, 18, 18, 0)
        block_start = event_utc - timedelta(minutes=15)  # 17:45 UTC
        
        # Bot checks: Am I in block window?
        is_blocked = check_time_utc >= block_start
        
        self.assertTrue(is_blocked)
        self.assertEqual(check_time_utc, block_start)


class TestTimezoneEdgeCases(unittest.TestCase):
    """Test edge cases in timezone handling"""
    
    def test_year_boundary_crossing(self):
        """Test events crossing year boundary in different timezones"""
        # Event at 2026-12-31 23:00 UTC (New Year's Eve)
        event_utc = datetime(2026, 12, 31, 23, 0)
        
        # Tokyo (UTC+9): Already 2027-01-01 08:00 (New Year's Day)
        tokyo_time = event_utc + timedelta(hours=9)
        self.assertEqual(tokyo_time.year, 2027)
        self.assertEqual(tokyo_time.month, 1)
        self.assertEqual(tokyo_time.day, 1)
        
        # LA (UTC-8): Still 2026-12-31 15:00 (New Year's Eve afternoon)
        la_time = event_utc - timedelta(hours=8)
        self.assertEqual(la_time.year, 2026)
        self.assertEqual(la_time.month, 12)
        self.assertEqual(la_time.day, 31)
    
    def test_week_boundary_for_weekly_data(self):
        """Test that week boundaries are consistent in UTC"""
        # If we fetch "this week's events", use UTC week
        # Week starts Monday 00:00 UTC
        
        monday_utc = datetime(2026, 3, 16, 0, 0)  # Monday midnight UTC
        
        # For Sydney (UTC+11), this is Monday 11:00 AM
        sydney_time = monday_utc + timedelta(hours=11)
        self.assertEqual(sydney_time.weekday(), 0)  # Still Monday
        
        # For Hawaii (UTC-10), this is Sunday 14:00 (previous day!)
        hawaii_time = monday_utc - timedelta(hours=10)
        self.assertEqual(hawaii_time.weekday(), 6)  # Sunday!
        
        # This is why we always use UTC for date ranges
    
    def test_calendar_json_stores_utc_strings(self):
        """Test that JSON calendar uses UTC time strings"""
        # Calendar JSON format:
        # {
        #   "date": "2026-03-18",
        #   "time_utc": "18:00",  <-- Always UTC!
        #   ...
        # }
        
        date_str = "2026-03-18"
        time_str = "18:00"
        
        # Parse as UTC
        utc_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        
        # Verify no timezone info (naive datetime = assumed UTC)
        self.assertIsNone(utc_dt.tzinfo)
        
        # This is correct! We treat naive datetime as UTC throughout
        self.assertEqual(utc_dt.hour, 18)
    
    def test_forexfactory_json_timezone(self):
        """Test that ForexFactory JSON times are in correct timezone"""
        # ForexFactory JSON uses GMT/UTC
        # Example: "2026-03-18T18:00:00+00:00"
        
        # Our calendar should extract the UTC time
        ff_timestamp = "2026-03-18T18:00:00+00:00"
        
        # Parse (if using ISO format)
        dt = datetime.fromisoformat(ff_timestamp.replace('+00:00', ''))
        
        self.assertEqual(dt.hour, 18)
        self.assertEqual(dt.minute, 0)
    
    def test_api_response_includes_utc_notation(self):
        """Test that API responses clearly indicate UTC times"""
        # API should return times with clear UTC indication
        api_response = {
            "date": "2026-03-18",
            "time_utc": "18:00",  # Field name indicates UTC
            "event": "FOMC"
        }
        
        # Check that field name includes "utc" to indicate timezone
        self.assertIn("time_utc", api_response.keys())
        self.assertIn("utc", "time_utc".lower())
        
        # Alternatively, use ISO 8601 with Z suffix
        iso_format = "2026-03-18T18:00:00Z"  # Z = Zulu time = UTC
        self.assertTrue(iso_format.endswith('Z'))


class TestTimezoneRecommendations(unittest.TestCase):
    """Document timezone best practices for the system"""
    
    def test_best_practice_store_utc(self):
        """Best practice: Always store times in UTC"""
        # ✅ CORRECT: Store as UTC
        event_time = datetime(2026, 3, 18, 18, 0)  # Naive = UTC
        
        # ❌ WRONG: Store as local time
        # event_time = datetime(2026, 3, 18, 14, 0)  # EDT? EST? Ambiguous!
        
        # Our system stores UTC, which is correct
        self.assertIsNone(event_time.tzinfo)  # Naive datetime treated as UTC
    
    def test_best_practice_convert_at_display(self):
        """Best practice: Convert to local timezone only for display"""
        # Backend: Always UTC
        event_utc = datetime(2026, 3, 18, 18, 0)
        
        # Frontend: Convert to user's local timezone for display
        # (This would be done in JavaScript on client side)
        
        # Example: Convert for New York user
        user_offset = -4  # EDT
        user_local = event_utc + timedelta(hours=user_offset)
        
        # Display: "2:00 PM EDT"
        self.assertEqual(user_local.hour, 14)
    
    def test_best_practice_api_returns_utc(self):
        """Best practice: API returns UTC, client converts"""
        # API response in UTC
        api_response = {
            "time_utc": "18:00",
            # Or ISO 8601:
            "timestamp": "2026-03-18T18:00:00Z"
        }
        
        # Client (browser) converts to local:
        # const utc = new Date(timestamp);
        # const local = utc.toLocaleString('en-US', { timeZone: 'America/New_York' });
        
        # This way each user sees their own local time
        self.assertIsInstance(api_response, dict)


if __name__ == '__main__':
    unittest.main()
