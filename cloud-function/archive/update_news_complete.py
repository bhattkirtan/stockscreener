#!/usr/bin/env python3
"""
Complete News Update Job - Generate and Upload

Run this to update news headlines:
  python3 update_news_complete.py

Or schedule with cron:
  */15 * * * * cd /path/to/cloud-function && python3 update_news_complete.py >> logs/news.log 2>&1
"""

import json
import logging
import feedparser
import subprocess
from datetime import datetime
from pathlib import Path
import hashlib

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


def fetch_news_headlines(max_articles: int = 50) -> dict:
    """Fetch news from RSS feeds"""
    
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
            logger.info(f"Fetching from {source_name}...")
            feed = feedparser.parse(feed_url)
            
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
                
                # Get data
                title = entry.get('title', '')
                description = entry.get('summary', '') or entry.get('description', '')
                url = entry.get('link', '')
                
                if not title or not url:
                    continue
                
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
            
            logger.info(f"  ✅ {count} articles from {source_name}")
            
        except Exception as e:
            logger.error(f"Failed to fetch from {source_name}: {e}")
            continue
    
    # Sort by publication time (newest first)
    all_headlines.sort(key=lambda h: h['published_at'], reverse=True)
    
    return {
        "updated_at": datetime.utcnow().isoformat(),
        "total_headlines": len(all_headlines),
        "sources": list(RSS_FEEDS.keys()),
        "headlines": all_headlines
    }


def save_to_file(data: dict, output_file: str = "data/news_headlines.json") -> bool:
    """Save news data to file"""
    try:
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"✅ Saved {data['total_headlines']} headlines to {output_file}")
        return True
    except Exception as e:
        logger.error(f"Failed to save file: {e}")
        return False


def upload_to_gcs(local_file: str, gcs_path: str) -> bool:
    """Upload file to Google Cloud Storage"""
    try:
        cmd = ['gsutil', 'cp', local_file, gcs_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            logger.info(f"✅ Uploaded to {gcs_path}")
            return True
        else:
            logger.error(f"GCS upload failed: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"Failed to upload to GCS: {e}")
        return False


def main():
    """Main update job"""
    print("=" * 60)
    print(f"News Update Job - {datetime.utcnow().isoformat()}")
    print("=" * 60)
    
    # 1. Fetch news
    logger.info("📰 Fetching news headlines...")
    data = fetch_news_headlines(max_articles=50)
    
    if data['total_headlines'] == 0:
        logger.warning("⚠️  No headlines fetched")
        return False
    
    logger.info(f"✅ Fetched {data['total_headlines']} headlines from {len(data['sources'])} sources")
    
    # Show latest
    print("\n📰 Latest Headlines:")
    for h in data['headlines'][:5]:
        print(f"  [{h['source']}] {h['title'][:70]}...")
    print()
    
    # 2. Save locally
    local_file = "data/news_headlines.json"
    if not save_to_file(data, local_file):
        return False
    
    # 3. Upload to GCS
    gcs_path = "gs://double-venture-442318-k8-optimization-results/external-data/news_headlines.json"
    if not upload_to_gcs(local_file, gcs_path):
        logger.warning("⚠️  GCS upload failed (continuing anyway)")
    
    print("\n✅ News update complete!")
    return True


if __name__ == "__main__":
    try:
        success = main()
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        logger.exception(e)
        exit(1)
