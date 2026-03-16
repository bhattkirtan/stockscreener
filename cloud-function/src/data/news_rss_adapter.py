"""
News RSS Feed Adapter (FREE Alternative to NewsAPI)

Monitors breaking news from RSS feeds instead of paid NewsAPI.

Why RSS feeds are better:
- ✅ 100% FREE forever
- ✅ Real-time (no 15-min delay like NewsAPI free tier)
- ✅ No API key needed
- ✅ No rate limits
- ✅ Legal (RSS is designed for this)
- ✅ More reliable than web scraping

RSS Sources:
- Reuters: https://www.reutersagency.com/feed/
- CNBC: https://www.cnbc.com/id/100003114/device/rss/rss.html
- MarketWatch: http://feeds.marketwatch.com/marketwatch/topstories/
- BBC Business: http://feeds.bbci.co.uk/news/business/rss.xml
- AP Business: https://hosted.ap.org/lineups/BUSINESS.rss
"""

import feedparser
import logging
from typing import List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import re

logger = logging.getLogger(__name__)


@dataclass
class NewsHeadline:
    """
    News headline from RSS feed
    
    Compatible with news_adapter.py schema
    """
    article_id: str
    published_at: datetime
    source: str
    title: str
    description: Optional[str] = None
    url: Optional[str] = None
    matched_keywords: List[str] = field(default_factory=list)
    severity: str = "high"  # high, medium, low
    
    def is_high_impact(self) -> bool:
        """Check if this is a high-impact headline"""
        return self.severity == "high" and bool(self.matched_keywords)
    
    def should_block_trading(self, block_duration_minutes: int = 10) -> bool:
        """Check if this headline should block trading"""
        age_minutes = (datetime.utcnow() - self.published_at).total_seconds() / 60
        return self.is_high_impact() and age_minutes < block_duration_minutes
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            'article_id': self.article_id,
            'published_at': self.published_at.isoformat(),
            'source': self.source,
            'title': self.title,
            'description': self.description,
            'url': self.url,
            'matched_keywords': self.matched_keywords,
            'severity': self.severity
        }


class NewsRSSAdapter:
    """
    FREE news monitoring via RSS feeds
    
    Replaces NewsAPI ($449/month) with free RSS feeds
    
    From strategy.md Section 6.6.4:
    - Monitor: Reuters, Bloomberg, FT, WSJ, CNBC, MarketWatch, BBC, AP
    - Keywords: "emergency", "crash", "attack", "intervention", "default"
    - Block duration: 10 minutes after headline
    - Refresh: Every 5 minutes
    
    RSS Feed Advantages:
    - No API key needed
    - Real-time updates (no delay)
    - Unlimited requests
    - Completely free
    """
    
    # Free RSS feeds (no authentication needed)
    RSS_FEEDS = {
        'Reuters': 'https://www.reutersagency.com/feed/',
        'CNBC': 'https://www.cnbc.com/id/100003114/device/rss/rss.html',
        'MarketWatch': 'http://feeds.marketwatch.com/marketwatch/topstories/',
        'BBC': 'http://feeds.bbci.co.uk/news/business/rss.xml',
        'AP': 'https://hosted.ap.org/lineups/BUSINESS.rss',
        'Bloomberg': 'https://www.bloomberg.com/feed/podcast/etf-report.xml',
        'FT': 'https://www.ft.com/?format=rss',  # Limited free access
        'WSJ': 'https://feeds.a.dj.com/rss/RSSMarketsMain.xml'
    }
    
    # High-impact keywords (from strategy.md Section 6.6.4)
    DEFAULT_KEYWORDS = [
        # Crises
        'emergency', 'crash', 'collapse', 'crisis', 'panic',
        
        # Conflicts
        'attack', 'war', 'conflict', 'invasion', 'strike',
        
        # Financial events
        'default', 'bankruptcy', 'bailout', 'intervention',
        
        # Policy shocks
        'emergency rate', 'surprise', 'unexpected',
        
        # Disasters
        'disaster', 'outbreak', 'pandemic', 'earthquake',
        
        # Security
        'cyber attack', 'terrorist', 'assassination',
        
        # Political
        'coup', 'impeachment', 'resignation',
        
        # Market specific
        'circuit breaker', 'trading halt', 'flash crash'
    ]
    
    def __init__(
        self,
        keywords: Optional[List[str]] = None,
        block_duration_minutes: int = 10,
        lookback_minutes: int = 60,
        feed_timeout: int = 10
    ):
        """
        Initialize RSS news adapter
        
        Args:
            keywords: High-impact keywords to monitor (uses defaults if None)
            block_duration_minutes: Block duration after headline (10 min)
            lookback_minutes: How far back to check (60 min)
            feed_timeout: RSS feed fetch timeout (10 sec)
        """
        self.keywords = keywords or self.DEFAULT_KEYWORDS
        self.block_duration = timedelta(minutes=block_duration_minutes)
        self.lookback_window = timedelta(minutes=lookback_minutes)
        self.feed_timeout = feed_timeout
        
        # Cache recent headlines to avoid duplicates
        self.seen_urls: Set[str] = set()
        self.recent_headlines: List[NewsHeadline] = []
        
        logger.info(f"Initialized RSS adapter with {len(self.keywords)} keywords")
    
    def fetch_headlines(
        self,
        sources: Optional[List[str]] = None,
        max_age_minutes: Optional[int] = None
    ) -> List[NewsHeadline]:
        """
        Fetch headlines from RSS feeds
        
        Args:
            sources: List of source names to fetch (None = all)
            max_age_minutes: Only return headlines newer than this (None = use lookback_window)
        
        Returns:
            List of news headlines
        """
        if sources is None:
            sources = list(self.RSS_FEEDS.keys())
        
        max_age = timedelta(minutes=max_age_minutes) if max_age_minutes else self.lookback_window
        cutoff_time = datetime.utcnow() - max_age
        
        all_headlines = []
        
        for source_name in sources:
            if source_name not in self.RSS_FEEDS:
                logger.warning(f"Unknown source: {source_name}")
                continue
            
            feed_url = self.RSS_FEEDS[source_name]
            
            try:
                # Fetch RSS feed
                feed = feedparser.parse(feed_url)
                
                if feed.bozo:
                    logger.warning(f"RSS parse error for {source_name}: {feed.bozo_exception}")
                
                # Parse entries
                for entry in feed.entries:
                    # Get publication time
                    pub_time = self._parse_published_time(entry)
                    
                    if not pub_time:
                        continue
                    
                    # Filter by age
                    if pub_time < cutoff_time:
                        continue
                    
                    # Get title and description
                    title = entry.get('title', '')
                    description = entry.get('summary', '') or entry.get('description', '')
                    url = entry.get('link', '')
                    
                    # Skip if already seen
                    if url in self.seen_urls:
                        continue
                    
                    # Check for keyword matches
                    matched = self._match_keywords(title, description)
                    
                    # Only keep high-impact headlines
                    if not matched:
                        continue
                    
                    # Classify severity
                    severity = self._classify_severity(matched, title)
                    
                    # Create headline
                    headline = NewsHeadline(
                        article_id=self._generate_article_id(url),
                        published_at=pub_time,
                        source=source_name,
                        title=title,
                        description=description,
                        url=url,
                        matched_keywords=matched,
                        severity=severity
                    )
                    
                    # Validate before adding
                    if self._validate_headline(headline):
                        all_headlines.append(headline)
                        self.seen_urls.add(url)
                    else:
                        logger.debug(f"Skipped invalid headline: {title[:50]}")
                
                logger.debug(f"Fetched {len(feed.entries)} entries from {source_name}")
                
            except Exception as e:
                logger.error(f"Failed to fetch RSS from {source_name}: {e}")
                continue
        
        # Update cache
        self.recent_headlines.extend(all_headlines)
        self._cleanup_old_headlines()
        
        logger.info(f"Found {len(all_headlines)} high-impact headlines")
        return all_headlines
    
    def _parse_published_time(self, entry: dict) -> Optional[datetime]:
        """Parse publication time from RSS entry"""
        # Try different time fields
        time_fields = ['published_parsed', 'updated_parsed', 'created_parsed']
        
        for field in time_fields:
            if field in entry and entry[field]:
                try:
                    import time
                    time_tuple = entry[field]
                    timestamp = time.mktime(time_tuple)
                    return datetime.utcfromtimestamp(timestamp)
                except:
                    continue
        
        # Fallback: try ISO string
        for field in ['published', 'updated', 'created']:
            if field in entry:
                try:
                    return datetime.fromisoformat(entry[field].replace('Z', '+00:00'))
                except:
                    continue
        
        return None
    
    def _match_keywords(self, title: str, description: str) -> List[str]:
        """
        Check if title/description contains high-impact keywords
        
        Returns list of matched keywords (empty if none)
        """
    
    def _classify_severity(self, matched_keywords: List[str], title: str) -> str:
        """
        Classify headline severity based on matched keywords
        
        Returns: "high", "medium", or "low"
        """
        if not matched_keywords:
            return "low"
        
        # Critical keywords = immediate high severity
        critical_keywords = [
            "emergency", "crash", "attack", "war", "nuclear",
            "intervention", "default", "bankruptcy", "collapse",
            "circuit breaker", "trading halt", "flash crash"
        ]
        
        for keyword in matched_keywords:
            if keyword.lower() in critical_keywords:
                return "high"
        
        # Multiple keywords = medium severity
        if len(matched_keywords) >= 2:
            return "medium"
        
        # Single non-critical keyword = medium
        return "medium"
    
    def _validate_headline(self, headline: NewsHeadline) -> bool:
        """
        Validate headline quality before saving
        
        Returns: True if headline is valid and worth storing
        """
        # Must have title
        if not headline.title or len(headline.title.strip()) < 10:
            return False
        
        # Must have source
        if not headline.source:
            return False
        
        # Must have URL
        if not headline.url or not headline.url.startswith('http'):
            return False
        
        # Must have recent timestamp (not older than 24 hours)
        age_hours = (datetime.utcnow() - headline.published_at).total_seconds() / 3600
        if age_hours > 24:
            return False
        
        # For high-impact, must have matched keywords
        if headline.severity == "high" and not headline.matched_keywords:
            return False
        
        return True
        text = f"{title} {description}".lower()
        matched = []
        
        for keyword in self.keywords:
            if keyword.lower() in text:
                matched.append(keyword)
        
        return matched
    
    def _generate_article_id(self, url: str) -> str:
        """Generate unique article ID from URL"""
        import hashlib
        return f"rss_{hashlib.md5(url.encode()).hexdigest()[:16]}"
    
    def _cleanup_old_headlines(self):
        """Remove headlines older than lookback window"""
        cutoff = datetime.utcnow() - self.lookback_window
        self.recent_headlines = [
            h for h in self.recent_headlines
            if h.published_at >= cutoff
        ]
    
    def is_blocked_by_news(
        self,
        current_time: Optional[datetime] = None,
        custom_block_duration: Optional[int] = None
    ) -> tuple[bool, Optional[str]]:
        """
        Check if trading should be blocked due to recent headlines
        
        Args:
            current_time: Current time (UTC) - uses now() if None
            custom_block_duration: Override block duration (minutes)
        
        Returns:
            (is_blocked, reason) - True if blocked with reason
        """
        if current_time is None:
            current_time = datetime.utcnow()
        
        block_duration = timedelta(minutes=custom_block_duration) if custom_block_duration else self.block_duration
        
        # Check recent headlines
        for headline in self.recent_headlines:
            time_since_headline = current_time - headline.published_at
            
            if time_since_headline <= block_duration:
                reason = f"{headline.source}: {headline.title} ({', '.join(headline.matched_keywords[:3])})"
                return True, reason
        
        return False, None
    
    def get_minutes_since_last_alert(self, current_time: Optional[datetime] = None) -> Optional[int]:
        """
        Get minutes since most recent high-impact headline
        
        Returns None if no recent headlines
        """
        if not self.recent_headlines:
            return None
        
        if current_time is None:
            current_time = datetime.utcnow()
        
        # Get most recent headline
        most_recent = max(self.recent_headlines, key=lambda h: h.published_at)
        
        delta = current_time - most_recent.published_at
        return int(delta.total_seconds() / 60)
    
    def get_recent_alerts(self, minutes: int = 60) -> List[NewsHeadline]:
        """Get high-impact headlines from last N minutes"""
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        
        return [
            h for h in self.recent_headlines
            if h.published_at >= cutoff
        ]


# Example usage
if __name__ == "__main__":
    import sys
    import time
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("=" * 60)
    print("RSS News Monitor (FREE Alternative to NewsAPI)")
    print("=" * 60)
    print()
    print("Monitoring RSS feeds from:")
    for source in NewsRSSAdapter.RSS_FEEDS.keys():
        print(f"  ✅ {source}")
    print()
    print(f"Checking for {len(NewsRSSAdapter.DEFAULT_KEYWORDS)} high-impact keywords...")
    print()
    
    # Initialize adapter
    adapter = NewsRSSAdapter(lookback_minutes=120)  # Last 2 hours
    
    # Fetch headlines
    print("Fetching headlines...")
    headlines = adapter.fetch_headlines()
    
    if headlines:
        print(f"\n🚨 Found {len(headlines)} high-impact headlines:\n")
        
        for headline in headlines:
            print(f"📰 {headline.source} - {headline.published_at.strftime('%H:%M UTC')}")
            print(f"   {headline.title}")
            print(f"   Keywords: {', '.join(headline.matched_keywords)}")
            print()
        
        # Check if blocked
        is_blocked, reason = adapter.is_blocked_by_news()
        
        if is_blocked:
            print(f"⛔ TRADING BLOCKED")
            print(f"   Reason: {reason}")
        else:
            mins_since = adapter.get_minutes_since_last_alert()
            print(f"✅ Trading allowed")
            if mins_since:
                print(f"   Last alert: {mins_since} minutes ago")
    else:
        print("✅ No high-impact headlines in last 2 hours")
        print("   Trading allowed")
    
    print()
    print("-" * 60)
    print("💡 This is 100% FREE (no API key needed)")
    print("   Saves $449/month vs NewsAPI paid tier")
    print("-" * 60)
    
    sys.exit(0)
