"""
NewsAPI Adapter for Unscheduled Headline Monitoring

Monitors breaking news headlines for high-impact events that require
immediate trade blocking.

Reference: strategy.md Section 6.6.4 (Feed 4: NewsAPI Headlines)
"""

import pandas as pd
from typing import Optional, Dict, List, Set
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import requests
import re

logger = logging.getLogger(__name__)


@dataclass
class NewsHeadline:
    """
    News article headline
    
    From strategy.md Section 6.6.4 schema:
    - article_id: Unique identifier
    - published_at: Publication timestamp (UTC)
    - source: News source (e.g., 'Reuters')
    - title: Headline text
    - description: Article description
    - url: Article URL
    - matched_keywords: Keywords that triggered alert
    """
    article_id: str
    published_at: datetime
    source: str
    title: str
    description: Optional[str] = None
    url: Optional[str] = None
    matched_keywords: List[str] = None
    
    def is_high_impact(self) -> bool:
        """Check if this is a high-impact headline"""
        return bool(self.matched_keywords)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'article_id': self.article_id,
            'published_at': self.published_at.isoformat(),
            'source': self.source,
            'title': self.title,
            'description': self.description,
            'url': self.url,
            'matched_keywords': self.matched_keywords or []
        }


class NewsAPIAdapter:
    """
    Adapter for NewsAPI headline monitoring
    
    From strategy.md Section 6.6.4:
    - Monitor: Reuters, Bloomberg, FT, WSJ
    - Keywords: "emergency", "crash", "attack", "intervention", "default"
    - Block duration: 10 minutes after headline
    - Refresh: Every 5 minutes
    
    Configuration:
    - NEWS_REFRESH_INTERVAL: 5 minutes
    - NEWS_BLOCK_DURATION: 10 minutes
    - NEWS_KEYWORDS: High-impact terms
    - TRUSTED_SOURCES: Reuters, Bloomberg, FT, WSJ
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        refresh_interval_minutes: int = 5,
        block_duration_minutes: int = 10,
        keywords: List[str] = None,
        trusted_sources: List[str] = None,
        use_fallback: bool = False
    ):
        """
        Initialize NewsAPI adapter
        
        Args:
            api_key: NewsAPI.org API key (optional)
            refresh_interval_minutes: Refresh interval (5 minutes)
            block_duration_minutes: Block duration after headline (10 min)
            keywords: High-impact keywords to monitor
            trusted_sources: Trusted news sources
            use_fallback: Use manual test headlines if API fails
        """
        self.api_key = api_key
        self.refresh_interval = timedelta(minutes=refresh_interval_minutes)
        self.block_duration = timedelta(minutes=block_duration_minutes)
        self.use_fallback = use_fallback
        
        # Default high-impact keywords (strategy.md Section 6.6.4)
        if keywords is None:
            keywords = [
                'emergency',
                'crash',
                'attack',
                'intervention',
                'default',
                'bankruptcy',
                'collapse',
                'crisis',
                'war',
                'outbreak',
                'pandemic',
                'cyber attack',
                'data breach',
                'terrorist',
                'assassination',
                'coup',
                'nuclear',
                'earthquake',
                'disaster'
            ]
        self.keywords = [k.lower() for k in keywords]
        
        # Default trusted sources (strategy.md Section 6.6.4)
        if trusted_sources is None:
            trusted_sources = [
                'reuters.com',
                'bloomberg.com',
                'ft.com',
                'wsj.com',
                'cnbc.com',
                'marketwatch.com',
                'bbc.com',
                'apnews.com'
            ]
        self.trusted_sources = trusted_sources
        
        # Cache
        self.recent_headlines: List[NewsHeadline] = []
        self.last_refresh: Optional[datetime] = None
        self.blocked_until: Optional[datetime] = None
        
        # API endpoint
        self.base_url = "https://newsapi.org/v2"
    
    def needs_refresh(self, current_time: datetime) -> bool:
        """Check if cache needs refresh"""
        if self.last_refresh is None:
            return True
        
        time_since_refresh = current_time - self.last_refresh
        return time_since_refresh >= self.refresh_interval
    
    def match_keywords(self, text: str) -> List[str]:
        """
        Check if text contains high-impact keywords
        
        Args:
            text: Headline or description text
        
        Returns:
            List of matched keywords
        """
        text_lower = text.lower()
        matched = []
        
        for keyword in self.keywords:
            if keyword in text_lower:
                matched.append(keyword)
        
        return matched
    
    def fetch_headlines_from_api(
        self,
        lookback_minutes: int = 60
    ) -> List[NewsHeadline]:
        """
        Fetch recent headlines from NewsAPI
        
        API endpoint: GET /everything
        Query params: q, sources, from, sortBy
        
        Args:
            lookback_minutes: Minutes to look back (60)
        
        Returns:
            List of news headlines
        """
        if not self.api_key:
            logger.warning("No NewsAPI key configured")
            return []
        
        try:
            current_time = datetime.utcnow()
            from_time = current_time - timedelta(minutes=lookback_minutes)
            
            # Build URL
            url = f"{self.base_url}/everything"
            params = {
                'apiKey': self.api_key,
                'domains': ','.join(self.trusted_sources),
                'from': from_time.isoformat(),
                'sortBy': 'publishedAt',
                'language': 'en',
                'pageSize': 100
            }
            
            # Make request
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            # Parse response
            data = response.json()
            articles = data.get('articles', [])
            
            # Convert to NewsHeadline objects
            headlines = []
            for article in articles:
                # Parse timestamp
                published_str = article.get('publishedAt')
                if not published_str:
                    continue
                
                try:
                    published_at = datetime.fromisoformat(
                        published_str.replace('Z', '+00:00')
                    )
                except:
                    logger.warning(f"Failed to parse timestamp: {published_str}")
                    continue
                
                # Extract source
                source_obj = article.get('source', {})
                source = source_obj.get('name', 'Unknown')
                
                # Get title and description
                title = article.get('title', '')
                description = article.get('description', '')
                
                # Check for high-impact keywords
                combined_text = f"{title} {description}"
                matched_keywords = self.match_keywords(combined_text)
                
                # Only keep headlines with matched keywords
                if not matched_keywords:
                    continue
                
                # Create headline
                headline = NewsHeadline(
                    article_id=article.get('url', '').split('/')[-1],
                    published_at=published_at,
                    source=source,
                    title=title,
                    description=description,
                    url=article.get('url'),
                    matched_keywords=matched_keywords
                )
                
                headlines.append(headline)
            
            logger.info(
                f"Fetched {len(headlines)} high-impact headlines from NewsAPI "
                f"(out of {len(articles)} total)"
            )
            return headlines
        
        except Exception as e:
            logger.error(f"Failed to fetch headlines from NewsAPI: {e}")
            return []
    
    def get_fallback_headlines(self) -> List[NewsHeadline]:
        """
        Manual fallback for testing (no API required)
        
        Returns:
            Empty list (no test headlines in production)
        """
        # In production, return empty list
        # For testing, you could add manual test headlines here
        return []
    
    def fetch_headlines(
        self,
        lookback_minutes: int = 60,
        force_refresh: bool = False
    ) -> List[NewsHeadline]:
        """
        Fetch recent high-impact headlines
        
        Args:
            lookback_minutes: Minutes to look back (60)
            force_refresh: Force refresh even if cache valid
        
        Returns:
            List of high-impact headlines
        """
        current_time = datetime.utcnow()
        
        # Check if refresh needed
        if not force_refresh and not self.needs_refresh(current_time):
            # Filter recent headlines
            cutoff = current_time - timedelta(minutes=lookback_minutes)
            recent = [
                h for h in self.recent_headlines
                if h.published_at >= cutoff
            ]
            logger.debug(f"Using cached headlines: {len(recent)}")
            return recent
        
        # Fetch from API
        headlines = self.fetch_headlines_from_api(lookback_minutes)
        
        # Use fallback if API failed
        if not headlines and self.use_fallback:
            logger.info("Using manual headline fallback")
            headlines = self.get_fallback_headlines()
        
        # Update cache
        self.recent_headlines = headlines
        self.last_refresh = current_time
        
        return headlines
    
    def get_most_recent_alert(
        self,
        current_time: Optional[datetime] = None
    ) -> Optional[NewsHeadline]:
        """
        Get most recent high-impact headline
        
        Args:
            current_time: Current time (default: now)
        
        Returns:
            Most recent headline or None
        """
        if current_time is None:
            current_time = datetime.utcnow()
        
        # Fetch recent headlines
        headlines = self.fetch_headlines(lookback_minutes=60)
        
        if not headlines:
            return None
        
        # Sort by time
        headlines.sort(key=lambda h: h.published_at, reverse=True)
        
        return headlines[0]
    
    def is_blocked_by_news(
        self,
        current_time: datetime,
        update_if_stale: bool = True
    ) -> tuple[bool, Optional[str]]:
        """
        Check if trading is blocked by recent headline
        
        From strategy.md Section 6.6.4:
        - Block trades for 10 minutes after high-impact headline
        
        Args:
            current_time: Current time
            update_if_stale: Update headlines if stale
        
        Returns:
            Tuple of (is_blocked, reason)
        """
        # Update if needed
        if update_if_stale and self.needs_refresh(current_time):
            headlines = self.fetch_headlines()
        else:
            headlines = self.recent_headlines
        
        # Check each headline
        for headline in headlines:
            time_since_headline = current_time - headline.published_at
            
            # Within block window?
            if time_since_headline <= self.block_duration:
                reason = (
                    f"High-impact headline: '{headline.title[:50]}...' "
                    f"({headline.source}, "
                    f"{int(time_since_headline.total_seconds() / 60)} min ago)"
                )
                return True, reason
        
        return False, None
    
    def get_minutes_since_last_alert(
        self,
        current_time: Optional[datetime] = None
    ) -> Optional[int]:
        """
        Get minutes since last high-impact headline
        
        Args:
            current_time: Current time (default: now)
        
        Returns:
            Minutes since last alert or None
        """
        if current_time is None:
            current_time = datetime.utcnow()
        
        latest = self.get_most_recent_alert(current_time)
        
        if latest is None:
            return None
        
        delta = current_time - latest.published_at
        return int(delta.total_seconds() / 60)
    
    def is_trading_allowed(
        self,
        current_time: datetime
    ) -> tuple[bool, Optional[str]]:
        """
        Complete check: Is trading allowed based on news?
        
        Args:
            current_time: Current time
        
        Returns:
            Tuple of (is_allowed, block_reason)
        """
        is_blocked, reason = self.is_blocked_by_news(current_time)
        
        if is_blocked:
            logger.debug(f"Trading blocked by news: {reason}")
            return False, reason
        
        # Trading allowed
        return True, None
    
    def get_blocked_headlines_summary(
        self,
        current_time: datetime,
        lookback_minutes: int = 60
    ) -> List[Dict]:
        """
        Get summary of recent blocking headlines
        
        Args:
            current_time: Current time
            lookback_minutes: Minutes to look back (60)
        
        Returns:
            List of headline summaries
        """
        # Fetch headlines
        headlines = self.fetch_headlines(lookback_minutes=lookback_minutes)
        
        # Convert to summaries
        summaries = []
        for headline in headlines:
            summary = headline.to_dict()
            
            # Add time since headline
            time_since = current_time - headline.published_at
            minutes_since = int(time_since.total_seconds() / 60)
            summary['minutes_since'] = minutes_since
            
            # Add blocking status
            is_blocking = time_since <= self.block_duration
            summary['is_blocking'] = is_blocking
            
            summaries.append(summary)
        
        return summaries
