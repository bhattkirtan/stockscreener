"""
Event-Based Trade Blocker

Blocks trades during high-impact economic events, post-event stabilization,
and breaking news headlines.

Reference: strategy.md Section 13 (Event-Driven Blocking)
"""

import pandas as pd
from typing import Optional, Dict, List
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

from ..data.trading_economics_adapter import (
    TradingEconomicsAdapter,
    EconomicEvent,
    EventImportance
)

logger = logging.getLogger(__name__)

# Import news adapter (optional)
try:
    from ..data.news_adapter import NewsAPIAdapter
except ImportError:
    NewsAPIAdapter = None
    logger.debug("NewsAPI adapter not available")


@dataclass
class BlockedPeriod:
    """
    Time period during which trading is blocked
    """
    start_time: datetime
    end_time: datetime
    reason: str
    event: Optional[EconomicEvent] = None
    
    def is_blocked(self, current_time: datetime) -> bool:
        """Check if current time is in blocked period"""
        return self.start_time <= current_time <= self.end_time
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'start_time': self.start_time.isoformat(),
            'end_time': self.end_time.isoformat(),
            'reason': self.reason,
            'event': self.event.to_dict() if self.event else None
        }


class EventBlocker:
    """
    Blocks trades during high-impact events
    
    From strategy.md Section 13:
    - Block window: 15 minutes before + 15 minutes after
    - Total: 30-minute block per high-impact event
    - Post-event stabilization: Additional 15 minutes if volatility spike
    
    High-impact events from strategy.md Section 6.6.2:
    - US CPI
    - US NFP (Non-Farm Payrolls)
    - FOMC meetings
    - UK/EU GDP releases
    - Central bank rate decisions
    """
    
    def __init__(
        self,
        calendar_adapter: TradingEconomicsAdapter,
        news_adapter: Optional[object] = None,  # NewsAPIAdapter if available
        pre_event_minutes: int = 15,
        post_event_minutes: int = 15,
        stabilization_minutes: int = 15,
        volatility_spike_threshold: float = 1.5  # 1.5x normal ATR
    ):
        """
        Initialize event blocker
        
        Args:
            calendar_adapter: Trading Economics adapter
            news_adapter: NewsAPI adapter (optional)
            pre_event_minutes: Minutes to block before event (15)
            post_event_minutes: Minutes to block after event (15)
            stabilization_minutes: Additional block if volatility spike (15)
            volatility_spike_threshold: ATR multiplier for spike (1.5x)
        """
        self.calendar_adapter = calendar_adapter
        self.news_adapter = news_adapter
        self.pre_event_minutes = pre_event_minutes
        self.post_event_minutes = post_event_minutes
        self.stabilization_minutes = stabilization_minutes
        self.volatility_spike_threshold = volatility_spike_threshold
        
        # Cache of blocked periods
        self.blocked_periods: List[BlockedPeriod] = []
        self.last_update: Optional[datetime] = None
    
    def update_blocked_periods(
        self,
        current_time: datetime,
        lookahead_hours: int = 24
    ):
        """
        Update list of blocked periods from calendar
        
        Args:
            current_time: Current time
            lookahead_hours: Hours to look ahead (24)
        """
        # Fetch upcoming events
        end_time = current_time + timedelta(hours=lookahead_hours)
        events = self.calendar_adapter.fetch_calendar(
            start_date=current_time,
            end_date=end_time
        )
        
        # Create blocked periods for high-impact events
        self.blocked_periods = []
        
        for event in events:
            if not event.is_high_impact():
                continue
            
            # Calculate block window
            block_start = event.datetime_utc - timedelta(minutes=self.pre_event_minutes)
            block_end = event.datetime_utc + timedelta(minutes=self.post_event_minutes)
            
            blocked_period = BlockedPeriod(
                start_time=block_start,
                end_time=block_end,
                reason=f"High-impact event: {event.event}",
                event=event
            )
            
            self.blocked_periods.append(blocked_period)
        
        self.last_update = current_time
        
        logger.info(
            f"Updated blocked periods: {len(self.blocked_periods)} events "
            f"from {current_time} to {end_time}"
        )
    
    def is_blocked_by_event(
        self,
        current_time: datetime,
        update_if_stale: bool = True
    ) -> tuple[bool, Optional[str]]:
        """
        Check if trading is blocked by calendar event
        
        Args:
            current_time: Current time
            update_if_stale: Update periods if stale (>1 hour old)
        
        Returns:
            Tuple of (is_blocked, reason)
        """
        # Update if stale
        if update_if_stale:
            if (self.last_update is None or 
                (current_time - self.last_update) > timedelta(hours=1)):
                self.update_blocked_periods(current_time)
        
        # Check each blocked period
        for period in self.blocked_periods:
            if period.is_blocked(current_time):
                return True, period.reason
        
        return False, None
    
    def check_post_event_stabilization(
        self,
        current_time: datetime,
        current_atr: float,
        normal_atr: float
    ) -> tuple[bool, Optional[str]]:
        """
        Check if market needs more time to stabilize after event
        
        From strategy.md Section 13.2:
        - If ATR > 1.5x normal after event, extend block by 15 min
        
        Args:
            current_time: Current time
            current_atr: Current ATR
            normal_atr: Normal ATR
        
        Returns:
            Tuple of (needs_stabilization, reason)
        """
        if normal_atr == 0:
            return False, None
        
        atr_ratio = current_atr / normal_atr
        
        # Check if we're within stabilization window of any event
        for period in self.blocked_periods:
            if period.event is None:
                continue
            
            # Check if event just ended
            time_since_event = (current_time - period.event.time_utc).total_seconds() / 60
            
            # Within stabilization window (post_event + stabilization)
            max_window = self.post_event_minutes + self.stabilization_minutes
            
            if 0 <= time_since_event <= max_window:
                # Check for volatility spike
                if atr_ratio >= self.volatility_spike_threshold:
                    reason = (
                        f"Post-event stabilization: "
                        f"{period.event.category} "
                        f"(ATR {atr_ratio:.2f}x normal)"
                    )
                    return True, reason
        
        return False, None
    
    def is_trading_allowed(
        self,
        current_time: datetime,
        current_atr: Optional[float] = None,
        normal_atr: Optional[float] = None
    ) -> tuple[bool, Optional[str]]:
        """
        Complete check: Is trading allowed at this time?
        
        Checks calendar events, post-event stabilization, and news headlines.
        
        Args:
            current_time: Current time
            current_atr: Current ATR (optional, for stabilization check)
            normal_atr: Normal ATR (optional, for stabilization check)
        
        Returns:
            Tuple of (is_allowed, block_reason)
        """
        # Check calendar event blocking
        is_blocked, reason = self.is_blocked_by_event(current_time)
        
        if is_blocked:
            logger.debug(f"Trading blocked by calendar: {reason}")
            return False, reason
        
        # Check post-event stabilization
        if current_atr is not None and normal_atr is not None:
            needs_stab, stab_reason = self.check_post_event_stabilization(
                current_time, current_atr, normal_atr
            )
            
            if needs_stab:
                logger.debug(f"Trading blocked by stabilization: {stab_reason}")
                return False, stab_reason
        
        # Check news headlines (if news adapter configured)
        if self.news_adapter is not None:
            is_news_blocked, news_reason = self.news_adapter.is_blocked_by_news(
                current_time
            )
            
            if is_news_blocked:
                logger.debug(f"Trading blocked by news: {news_reason}")
                return False, news_reason
        
        # Trading allowed
        return True, None
    
    def get_next_blocked_period(
        self,
        current_time: datetime
    ) -> Optional[BlockedPeriod]:
        """
        Get next upcoming blocked period
        
        Args:
            current_time: Current time
        
        Returns:
            Next blocked period or None
        """
        # Update if needed
        if (self.last_update is None or 
            (current_time - self.last_update) > timedelta(hours=1)):
            self.update_blocked_periods(current_time)
        
        # Filter future periods
        future_periods = [
            p for p in self.blocked_periods
            if p.start_time > current_time
        ]
        
        if not future_periods:
            return None
        
        # Sort by start time
        future_periods.sort(key=lambda p: p.start_time)
        
        return future_periods[0]
    
    def get_minutes_to_next_block(
        self,
        current_time: datetime
    ) -> Optional[int]:
        """
        Get minutes until next blocked period
        
        Args:
            current_time: Current time
        
        Returns:
            Minutes to next block or None
        """
        next_period = self.get_next_blocked_period(current_time)
        
        if next_period is None:
            return None
        
        delta = next_period.start_time - current_time
        return int(delta.total_seconds() / 60)
    
    def get_blocked_periods_summary(
        self,
        current_time: datetime,
        hours_ahead: int = 24
    ) -> List[Dict]:
        """
        Get summary of blocked periods
        
        Args:
            current_time: Current time
            hours_ahead: Hours to look ahead (24)
        
        Returns:
            List of blocked period summaries
        """
        # Update if needed
        self.update_blocked_periods(current_time, lookahead_hours=hours_ahead)
        
        # Convert to dictionaries
        summaries = []
        for period in self.blocked_periods:
            summary = period.to_dict()
            
            # Add time until block
            if period.start_time > current_time:
                minutes_until = int((period.start_time - current_time).total_seconds() / 60)
                summary['minutes_until'] = minutes_until
            else:
                summary['minutes_until'] = 0
            
            # Add duration
            duration = int((period.end_time - period.start_time).total_seconds() / 60)
            summary['duration_minutes'] = duration
            
            summaries.append(summary)
        
        return summaries
