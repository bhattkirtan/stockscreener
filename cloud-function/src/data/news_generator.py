"""
News Generator - Fetches news from RSS feeds and saves to JSON

Generates news_headlines.json from free RSS feeds:
- Reuters, CNBC, MarketWatch, BBC, AP
- No API key needed
- Fetches ALL recent headlines (not just crisis keywords)

Run: python -m src.data.news_generator
"""

import json
import logging
import feedparser
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict
import hashlib

logger = logging.getLogger(__name__)


def generate_news_headlines(
    max_articles: int = 50,
    output_file: str = "data/news_headlines.json"
) -> bool:
    """
    Generate news headlines JSON from RSS feeds
    
    Fetches recent headlines from major news sources without time restrictions.
    Returns the latest articles from each feed.
    
    Args:
        max_articles: Maximum articles per source
        output_file: Output JSON file path
        
    Returns:
        bool: Success status
    """
    
    print("=" * 60)
    print(f"Generating News Headlines")
    print("=" * 60)
    print(f"Max articles per source: {max_articles}")
    print()
    
    # News RSS feeds
    RSS_FEEDS = {
        'Reuters': 'https://www.reutersagency.com/feed/',
        'CNBC': 'https://www.cnbc.com/id/100003114/device/rss/rss.html',
        'MarketWatch': 'http://feeds.marketwatch.com/marketwatch/topstories/',
        'BBC': 'http://feeds.bbci.co.uk/news/business/rss.xml',
        'AP': 'https://hosted.ap.org/lineups/BUSINESS.rss',
    }
    
    all_headlines = []
    
    for source_name, feed_url in RSS_FEEDS.items():
        try:
            print(f"📡 Fetching from {source_name}...")
            feed = feedparser.parse(feed_url)
            
            if feed.bozo:
                logger.warning(f"RSS parse error for {source_name}: {feed.bozo_exception}")
                print(f"  ⚠️  Parse warning for {source_name}")
                # Continue anyway - some feeds work despite warnings
            
            count = 0
            for entry in feed.entries[:max_articles]:
                # Get publication time
                pub_time = None
                for field in ['published_parsed', 'updated_parsed', 'created_parsed']:
                    if field in entry and entry[field]:
                        try:
                            import time
                            pub_time = datetime.utcfromtimestamp(time.mktime(entry[field]))
                            break
                        except:
                            continue
                
                if not pub_time:
                    pub_time = datetime.utcnow()
                
                # Get title and description
                title = entry.get('title', '')
                description = entry.get('summary', '') or entry.get('description', '')
                url = entry.get('link', '')
                
                if not title or not url:
                    continue
                
                # Create article ID from URL
                article_id = hashlib.md5(url.encode()).hexdigest()[:16]
                
                headline = {
                    'article_id': article_id,
                    'published_at': pub_time.isoformat(),
                    'source': source_name,
                    'title': title,
                    'description': description[:200] if description else None,
                    'url': url
                }
                
                all_headlines.append(headline)
                count += 1
            
            print(f"  ✅ {count} articles from {source_name}")
            
        except Exception as e:
            logger.error(f"Failed to fetch from {source_name}: {e}")
            print(f"  ❌ Failed: {source_name} - {e}")
            continue
    
    # Sort by publication time (newest first)
    all_headlines.sort(key=lambda h: h['published_at'], reverse=True)
    
    # Create output data
    output_data = {
        "updated_at": datetime.utcnow().isoformat(),
        "total_headlines": len(all_headlines),
        "sources": list(RSS_FEEDS.keys()),
        "headlines": all_headlines
    }
    
    # Save to file
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print()
    print(f"✅ Saved {len(all_headlines)} headlines to {output_file}")
    print()
    print("📰 Latest Headlines:")
    for h in all_headlines[:10]:
        age = datetime.utcnow() - datetime.fromisoformat(h['published_at'])
        age_str = f"{int(age.total_seconds() / 3600)}h ago" if age.total_seconds() >= 3600 else f"{int(age.total_seconds() / 60)}m ago"
        print(f"  [{h['source']}] {h['title'][:70]}... ({age_str})")
    
    if len(all_headlines) > 10:
        print(f"  ... and {len(all_headlines) - 10} more")
    
    print()
    print("✅ News headlines ready!")
    
    return True


if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
    
    # Generate news
    success = generate_news_headlines(max_articles=50)
    
    if success:
        print("\n🎉 Success!")
    else:
        print("\n❌ Failed to generate news headlines")
        exit(1)
