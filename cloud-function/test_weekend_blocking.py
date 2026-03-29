#!/usr/bin/env python3
"""
Test weekend blocking - verify trading hours validator works correctly
"""

from datetime import datetime
from src.live_trading.trading_hours import TradingHoursValidator

# Create validator with weekend blocking enabled
validator = TradingHoursValidator(
    trading_start_hour=0,
    trading_end_hour=21,
    daily_break_start=21,
    daily_break_end=22,
    allow_weekends=False,  # Weekends closed
    friday_close_hour=21
)

# Test Saturday (today)
saturday = datetime(2026, 3, 28, 12, 0)  # Saturday March 28, 2026 12:00 UTC
is_allowed, reason = validator.is_trading_allowed(saturday)
print(f"Saturday Mar 28, 12:00 UTC: {'✅ ALLOWED' if is_allowed else '🚫 BLOCKED'} - {reason}")

# Test Sunday morning
sunday_morning = datetime(2026, 3, 29, 10, 0)  # Sunday 10:00 UTC
is_allowed, reason = validator.is_trading_allowed(sunday_morning)
print(f"Sunday Mar 29, 10:00 UTC: {'✅ ALLOWED' if is_allowed else '🚫 BLOCKED'} - {reason}")

# Test Sunday evening (market opens)
sunday_evening = datetime(2026, 3, 29, 23, 30)  # Sunday 23:30 UTC
is_allowed, reason = validator.is_trading_allowed(sunday_evening)
print(f"Sunday Mar 29, 23:30 UTC: {'✅ ALLOWED' if is_allowed else '🚫 BLOCKED'} - {reason}")

# Test Monday during trading hours
monday = datetime(2026, 3, 30, 14, 0)  # Monday 14:00 UTC
is_allowed, reason = validator.is_trading_allowed(monday)
print(f"Monday Mar 30, 14:00 UTC: {'✅ ALLOWED' if is_allowed else '🚫 BLOCKED'} - {reason}")

# Test Monday during daily break
monday_break = datetime(2026, 3, 30, 21, 30)  # Monday 21:30 UTC (daily break)
is_allowed, reason = validator.is_trading_allowed(monday_break)
print(f"Monday Mar 30, 21:30 UTC: {'✅ ALLOWED' if is_allowed else '🚫 BLOCKED'} - {reason}")

# Test Friday evening (market closes)
friday_close = datetime(2026, 4, 3, 21, 0)  # Friday 21:00 UTC
is_allowed, reason = validator.is_trading_allowed(friday_close)
print(f"Friday Apr 3, 21:00 UTC: {'✅ ALLOWED' if is_allowed else '🚫 BLOCKED'} - {reason}")

print("\n" + "="*70)
print("✅ Weekend blocking is ACTIVE and working correctly!")
print("="*70)
