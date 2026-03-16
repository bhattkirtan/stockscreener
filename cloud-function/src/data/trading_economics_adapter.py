"""
Trading Economics Calendar API Adapter

Fetches scheduled macro events (CPI, NFP, FOMC) for trade blocking.

Reference: strategy.md Section 6.6.2 (Feed 2: Trading Economics Calendar)
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, List
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import logging
import requests
import json

logger = logging.getLogger(__name__)


class EventImportance(Enum):
    """Event importance classification"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class EconomicEvent:
    """
    Economic calendar event
    
    From strategy.md Section 6.6.2 schema:
    - event_id: Unique identifier
    - time_utc: Event timestamp (UTC)
    - country: Country code (US, UK, EU)
    - category: Event type (CPI, NFP, FOMC, etc.)
    - importance: HIGH/MEDIUM/LOW
    - actual: Actual value (after release)
    - forecast: Expected value
    - previous: Previous value
    """
    event_id: str
    time_utc: datetime
    country: str
    category: str
    importance: EventImportance
    
    # Optional values
    actual: Optional[float] = None
    forecast: Optional[float] = None
    previous: Optional[float] = None
    
    def is_high_impact(self) -> bool:
        """Check if this is a high-impact event"""
        return self.importance == EventImportance.HIGH
    
    def time_until_event(self, current_time: datetime) -> timedelta:
        """Calculate time until event"""
        return self.time_utc - current_time
    
    def minutes_until_event(self, current_time: datetime) -> int:
        """Calculate minutes until event"""
        delta = self.time_until_event(current_time)
        return int(delta.total_seconds() / 60)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'event_id': self.event_id,
            'time_utc': self.time_utc.isoformat(),
            'country': self.country,
            'category': self.category,
            'importance': self.importance.value,
            'actual': self.actual,
            'forecast': self.forecast,
            'previous': self.previous
        }


class TradingEconomicsAdapter:
    """
    Adapter for Trading Economics API
    
    From strategy.md Section 6.6.2:
    - Endpoint: /calendar
    - Refresh: Every 4 hours
    - Cache: 48-hour TTL
    - Filter: Only US, UK, EU events
    - Importance: HIGH only for blocking
    
    Configuration from strategy.md Section 6.6.2:
    - CALENDAR_REFRESH_INTERVAL: 4 hours
    - CALENDAR_CACHE_TTL: 48 hours
    - HIGH_IMPACT_CATEGORIES: ['CPI', 'NFP', 'FOMC', 'GDP', 'Retail Sales']
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        refresh_interval_hours: int = 4,
        cache_ttl_hours: int = 48,
        countries: List[str] = None,
        high_impact_categories: List[str] = None,
        use_fallback: bool = True
    ):
        """
        Initialize Trading Economics adapter
        
        Args:
            api_key: Trading Economics API key (optional)
            refresh_interval_hours: Refresh interval (4 hours)
            cache_ttl_hours: Cache TTL (48 hours)
            countries: Country codes to filter (US, UK, EU)
            high_impact_categories: High-impact event categories
            use_fallback: Use manual fallback if API fails
        """
        self.api_key = api_key
        self.refresh_interval = timedelta(hours=refresh_interval_hours)
        self.cache_ttl = timedelta(hours=cache_ttl_hours)
        
        # Default countries
        if countries is None:
            countries = ['US', 'UK', 'EU']
        self.countries = countries
        
        # Default high-impact categories (strategy.md Section 6.6.2)
        if high_impact_categories is None:
            high_impact_categories = [
                'CPI',
                'NFP',
                'FOMC',
                'GDP',
                'Retail Sales',
                'Interest Rate Decision',
                'Unemployment Rate'
            ]
        self.high_impact_categories = high_impact_categories
        
        self.use_fallback = use_fallback
        
        # Cache
        self.cached_events: List[EconomicEvent] = []
        self.last_refresh: Optional[datetime] = None
        
        # API endpoint
        self.base_url = "https://api.tradingeconomics.com"
    
    def needs_refresh(self, current_time: datetime) -> bool:
        """
        Check if cache needs refresh
        
        Args:
            current_time: Current timestamp
        
        Returns:
            True if needs refresh
        """
        if self.last_refresh is None:
            return True
        
        time_since_refresh = current_time - self.last_refresh
        return time_since_refresh >= self.refresh_interval
    
    def fetch_calendar_from_api(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> List[EconomicEvent]:
        """
        Fetch calendar from Trading Economics API
        
        API endpoint: GET /calendar
        Query params: from, to, country
        
        Args:
            start_date: Start date
            end_date: End date
        
        Returns:
            List of economic events
        """
        if not self.api_key:
            logger.warning("No Trading Economics API key configured")
            return []
        
        try:
            # Format dates
            from_date = start_date.strftime('%Y-%m-%d')
            to_date = end_date.strftime('%Y-%m-%d')
            
            # Build URL
            url = f"{self.base_url}/calendar"
            params = {
                'c': self.api_key,
                'country': ','.join(self.countries),
                'from': from_date,
                'to': to_date
            }
            
            # Make request
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            # Parse response
            data = response.json()
            
            # Convert to EconomicEvent objects
            events = []
            for item in data:
                # Parse importance
                importance_str = item.get('importance', 'LOW').upper()
                if importance_str == 'HIGH':
                    importance = EventImportance.HIGH
                elif importance_str == 'MEDIUM':
                    importance = EventImportance.MEDIUM
                else:
                    importance = EventImportance.LOW
                
                # Parse time
                time_str = item.get('date')
                if not time_str:
                    continue
                
                try:
                    time_utc = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                except:
                    logger.warning(f"Failed to parse event time: {time_str}")
                    continue
                
                # Create event
                event = EconomicEvent(
                    event_id=item.get('calendarId', f"{time_str}_{item.get('event', 'unknown')}"),
                    time_utc=time_utc,
                    country=item.get('country', 'US'),
                    category=item.get('category', 'Unknown'),
                    importance=importance,
                    actual=item.get('actual'),
                    forecast=item.get('forecast'),
                    previous=item.get('previous')
                )
                
                events.append(event)
            
            logger.info(f"Fetched {len(events)} events from Trading Economics API")
            return events
        
        except Exception as e:
            logger.error(f"Failed to fetch calendar from Trading Economics API: {e}")
            return []
    
    def get_manual_calendar_fallback(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> List[EconomicEvent]:
        """
        Manual fallback calendar for known recurring events
        
        From strategy.md Section 6.6.2:
        - US CPI: 2nd week, 8:30 AM ET
        - US NFP: 1st Friday, 8:30 AM ET
        - FOMC: 8 times/year, 2:00 PM ET
        
        Args:
            start_date: Start date
            end_date: End date
        
        Returns:
            List of economic events
        """
        manual_events = []
        
        # Generate CPI events (2nd week of each month, 8:30 AM ET = 13:30 UTC)
        current = start_date
        while current <= end_date:
            # Find 2nd week (8th-14th)
            for day in range(8, 15):
                try:
                    event_date = datetime(current.year, current.month, day, 13, 30)
                    if start_date <= event_date <= end_date:
                        manual_events.append(EconomicEvent(
                            event_id=f"CPI_{event_date.strftime('%Y%m%d')}",
                            time_utc=event_date,
                            country='US',
                            category='CPI',
                            importance=EventImportance.HIGH
                        ))
                        break
                except ValueError:
                    continue
            
            # Next month
            if current.month == 12:
                current = datetime(current.year + 1, 1, 1)
            else:
                current = datetime(current.year, current.month + 1, 1)
        
        logger.info(f"Generated {len(manual_events)} manual fallback events")
        return manual_events
    
    def fetch_calendar(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        force_refresh: bool = False
    ) -> List[EconomicEvent]:
        """
        Fetch economic calendar
        
        Args:
            start_date: Start date (default: now)
            end_date: End date (default: +7 days)
            force_refresh: Force refresh even if cache valid
        
        Returns:
            List of economic events
        """
        current_time = datetime.utcnow()
        
        # Default date range: next 7 days
        if start_date is None:
            start_date = current_time
        if end_date is None:
            end_date = current_time + timedelta(days=7)
        
        # Check if refresh needed
        if not force_refresh and not self.needs_refresh(current_time):
            # Filter cached events by date range
            filtered = [
                e for e in self.cached_events
                if start_date <= e.time_utc <= end_date
            ]
            logger.debug(f"Using cached calendar: {len(filtered)} events")
            return filtered
        
        # Fetch from API
        events = self.fetch_calendar_from_api(start_date, end_date)
        
        # Use fallback if API failed
        if not events and self.use_fallback:
            logger.info("Using manual calendar fallback")
            events = self.get_manual_calendar_fallback(start_date, end_date)
        
        # Update cache
        self.cached_events = events
        self.last_refresh = current_time
        
        return events
    
    def get_next_high_impact_event(
        self,
        current_time: Optional[datetime] = None
    ) -> Optional[EconomicEvent]:
        """
        Get next high-impact event
        
        Args:
            current_time: Current time (default: now)
        
        Returns:
            Next high-impact event or None
        """
        if current_time is None:
            current_time = datetime.utcnow()
        
        # Fetch upcoming events
        events = self.fetch_calendar(
            start_date=current_time,
            end_date=current_time + timedelta(days=7)
        )
        
        # Filter high-impact events
        high_impact = [
            e for e in events
            if e.is_high_impact() and e.time_utc > current_time
        ]
        
        # Sort by time
        high_impact.sort(key=lambda e: e.time_utc)
        
        return high_impact[0] if high_impact else None
    
    def get_minutes_to_next_event(
        self,
        current_time: Optional[datetime] = None
    ) -> Optional[int]:
        """
        Get minutes until next high-impact event
        
        Used by trade scorer for news-safety score.
        
        Args:
            current_time: Current time (default: now)
        
        Returns:
            Minutes to next event or None
        """
        if current_time is None:
            current_time = datetime.utcnow()
        
        next_event = self.get_next_high_impact_event(current_time)
        
        if next_event is None:
            return None
        
        return next_event.minutes_until_event(current_time)
    
    def is_event_window(
        self,
        current_time: datetime,
        window_minutes: int = 15
    ) -> bool:
        """
        Check if we're in an event window
        
        From strategy.md Section 6.6.2:
        - Block trades 15 minutes before/after high-impact events
        
        Args:
            current_time: Current time
            window_minutes: Window size (15 minutes)
        
        Returns:
            True if in event window
        """
        # Fetch recent and upcoming events
        events = self.fetch_calendar(
            start_date=current_time - timedelta(minutes=window_minutes),
            end_date=current_time + timedelta(minutes=window_minutes)
        )
        
        # Check if any high-impact event is within window
        for event in events:
            if not event.is_high_impact():
                continue
            
            time_diff = abs((event.time_utc - current_time).total_seconds() / 60)
            if time_diff <= window_minutes:
                logger.info(
                    f"In event window: {event.category} at {event.time_utc} "
                    f"({time_diff:.0f} min away)"
                )
                return True
        
        return False
