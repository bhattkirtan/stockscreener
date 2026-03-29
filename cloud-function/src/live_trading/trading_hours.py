"""
Trading Hours Validator

Enforces trading hours restrictions for GOLD market:
- Market hours: Sunday 23:00 UTC - Friday 21:00 UTC
- Daily break: 21:00-22:00 UTC (1 hour maintenance)
- Weekends: Closed (Saturday/Sunday except Sunday 23:00 open)
"""

from datetime import datetime, timedelta
from typing import Tuple


class TradingHoursValidator:
    """Validates if trading is allowed based on market hours and daily breaks"""
    
    def __init__(
        self,
        trading_start_hour: int = 0,
        trading_end_hour: int = 21,
        daily_break_start: int = 21,
        daily_break_end: int = 22,
        allow_weekends: bool = False,
        friday_close_hour: int = 21
    ):
        """
        Initialize trading hours validator
        
        Args:
            trading_start_hour: Daily trading start hour (UTC, 0-23)
            trading_end_hour: Daily trading end hour (UTC, 0-23)
            daily_break_start: Daily break start hour (UTC, 0-23)
            daily_break_end: Daily break end hour (UTC, 0-23)
            allow_weekends: Allow trading on Saturday/Sunday
            friday_close_hour: Friday early close hour (UTC, 0-23)
        """
        self.trading_start_hour = trading_start_hour
        self.trading_end_hour = trading_end_hour
        self.daily_break_start = daily_break_start
        self.daily_break_end = daily_break_end
        self.allow_weekends = allow_weekends
        self.friday_close_hour = friday_close_hour
    
    def is_trading_allowed(self, check_time: datetime = None) -> Tuple[bool, str]:
        """
        Check if trading is allowed at the given time
        
        Args:
            check_time: Time to check (default: now UTC)
            
        Returns:
            Tuple of (is_allowed, reason)
            - is_allowed: True if trading is allowed, False otherwise
            - reason: Explanation of why trading is or is not allowed
        """
        if check_time is None:
            check_time = datetime.utcnow()
        
        # Get day of week (0=Monday, 6=Sunday)
        weekday = check_time.weekday()
        hour = check_time.hour
        
        # Check weekend closure
        if not self.allow_weekends:
            # Saturday (5) - closed all day
            if weekday == 5:
                return False, "Weekend closure (Saturday)"
            
            # Sunday (6) - closed until market opens at 23:00 UTC
            if weekday == 6 and hour < 23:
                return False, "Weekend closure (Sunday before 23:00 UTC)"
        
        # Check Friday early close
        if weekday == 4 and hour >= self.friday_close_hour:
            return False, f"Friday early close (after {self.friday_close_hour}:00 UTC)"
        
        # Check daily break (applies to all weekdays)
        if self.daily_break_start <= hour < self.daily_break_end:
            return False, f"Daily break ({self.daily_break_start}:00-{self.daily_break_end}:00 UTC)"
        
        # Check daily trading hours (general)
        # Note: GOLD market is 24/5, so this is typically 0-21 (Sunday 23:00 - Friday 21:00)
        # We already handled Sunday special case above
        if weekday == 6:  # Sunday after 23:00 - market is open
            if hour >= 23:
                return True, "Market open (Sunday evening)"
        
        # All passed - trading allowed
        return True, "Market open"
    
    def get_next_trading_window(self, check_time: datetime = None) -> datetime:
        """
        Get the next time when trading will be allowed
        
        Args:
            check_time: Time to check from (default: now UTC)
            
        Returns:
            DateTime when trading will next be allowed
        """
        if check_time is None:
            check_time = datetime.utcnow()
        
        weekday = check_time.weekday()
        hour = check_time.hour
        
        # If Saturday, wait until Sunday 23:00
        if weekday == 5:
            days_to_add = 1
            next_open = check_time.replace(hour=23, minute=0, second=0, microsecond=0)
            return next_open + timedelta(days=days_to_add)
        
        # If Sunday before 23:00, wait until 23:00
        if weekday == 6 and hour < 23:
            return check_time.replace(hour=23, minute=0, second=0, microsecond=0)
        
        # If Friday after close, wait until Sunday 23:00
        if weekday == 4 and hour >= self.friday_close_hour:
            days_to_add = 2 if self.friday_close_hour < 24 else 1
            next_open = check_time.replace(hour=23, minute=0, second=0, microsecond=0)
            return next_open + timedelta(days=days_to_add)
        
        # If during daily break, wait until break ends
        if self.daily_break_start <= hour < self.daily_break_end:
            return check_time.replace(hour=self.daily_break_end, minute=0, second=0, microsecond=0)
        
        # Otherwise, market is open
        return check_time


def create_trading_hours_validator(
    enable_trading_hours: bool = True,
    trading_start_hour: int = 0,
    trading_end_hour: int = 21,
    daily_break_start: int = 21,
    daily_break_end: int = 22,
    allow_weekends: bool = False,
    friday_close_hour: int = 21
) -> TradingHoursValidator:
    """
    Factory function to create TradingHoursValidator from config
    
    Args:
        enable_trading_hours: Enable/disable trading hours validation
        trading_start_hour: Daily trading start hour (UTC)
        trading_end_hour: Daily trading end hour (UTC)
        daily_break_start: Daily break start hour (UTC)
        daily_break_end: Daily break end hour (UTC)
        allow_weekends: Allow trading on Saturday/Sunday
        friday_close_hour: Friday early close hour (UTC)
        
    Returns:
        TradingHoursValidator instance or None if disabled
    """
    if not enable_trading_hours:
        return None
    
    return TradingHoursValidator(
        trading_start_hour=trading_start_hour,
        trading_end_hour=trading_end_hour,
        daily_break_start=daily_break_start,
        daily_break_end=daily_break_end,
        allow_weekends=allow_weekends,
        friday_close_hour=friday_close_hour
    )
