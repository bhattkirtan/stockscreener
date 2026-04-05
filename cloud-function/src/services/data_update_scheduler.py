"""
Data Update Scheduler

Periodically updates economic calendar and news feeds.
Saves JSON files directly to DATA_DIR for API consumption.

Run as background service:
    python -m src.services.data_update_scheduler --mode production

Or run once:
    python -m src.services.data_update_scheduler --mode once
"""

import os
import sys
import json
import time
import logging
import signal
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List
import schedule
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.data.calendar_generator import generate_calendar
from src.data.news_rss_adapter import NewsRSSAdapter
from src.data.fred_adapter import FREDAdapter

logger = logging.getLogger(__name__)

# Default data directory — matches the /data volume mounted in Docker
DEFAULT_DATA_DIR = os.getenv("DATA_DIR", "/data")


class DataUpdateScheduler:
    """
    Scheduler for updating all external data feeds.

    Updates:
    - Economic calendar: Daily at 00:00 UTC
    - News headlines: Every 5 minutes
    - FRED macro data: Daily at 06:00 UTC

    Writes directly to DATA_DIR (default: /data):
    - economic_calendar.json
    - news_headlines.json
    - macro_regime.json
    """

    def __init__(
        self,
        data_dir: str = DEFAULT_DATA_DIR,
        calendar_update_hour: int = 0,   # Midnight UTC
        news_update_minutes: int = 5,
        fred_update_hour: int = 6,       # 6 AM UTC
        fred_api_key: str = None,
    ):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.calendar_update_hour = calendar_update_hour
        self.news_update_minutes = news_update_minutes
        self.fred_update_hour = fred_update_hour

        # Initialize adapters
        self.news_adapter = NewsRSSAdapter()
        self.fred_adapter = FREDAdapter(api_key=fred_api_key) if fred_api_key else None

        # Track last updates
        self.last_calendar_update = None
        self.last_news_update = None
        self.last_fred_update = None

        # Running flag
        self.is_running = False

        logger.info(f"DataUpdateScheduler initialized → writing to {self.data_dir}")
    
    def update_calendar(self):
        """Update economic calendar"""
        logger.info("Updating economic calendar...")
        
        try:
            output_file = self.data_dir / "economic_calendar.json"
            
            # Generate calendar for next 3 months
            success = generate_calendar(
                year=datetime.now().year,
                months_ahead=3,
                output_file=str(output_file)
            )
            
            if success:
                self.last_calendar_update = datetime.utcnow()
                logger.info("✅ Calendar updated successfully")
            else:
                logger.error("❌ Calendar update failed")
        
        except Exception as e:
            logger.error(f"Calendar update error: {e}")
            import traceback
            traceback.print_exc()
    
    def update_news(self):
        """Update news headlines"""
        logger.info("Updating news headlines...")
        
        try:
            # Fetch headlines
            headlines = self.news_adapter.fetch_headlines(
                max_age_minutes=120  # Last 2 hours
            )
            
            # Filter to high-impact only
            high_impact = [h for h in headlines if h.is_high_impact()]
            
            # Prepare data
            news_data = {
                'updated_at': datetime.utcnow().isoformat(),
                'total_headlines': len(headlines),
                'high_impact_count': len(high_impact),
                'headlines': [h.to_dict() for h in high_impact]
            }
            
            # Save to JSON
            output_file = self.data_dir / "news_headlines.json"
            with open(output_file, 'w') as f:
                json.dump(news_data, f, indent=2)

            self.last_news_update = datetime.utcnow()
            logger.info(f"✅ News updated: {len(high_impact)} high-impact headlines")
        
        except Exception as e:
            logger.error(f"News update error: {e}")
            import traceback
            traceback.print_exc()
    
    def update_fred(self):
        """Update FRED macro regime"""
        if not self.fred_adapter:
            logger.warning("FRED adapter not configured (no API key)")
            return
        
        logger.info("Updating FRED macro regime...")
        
        try:
            # Get current regime
            regime = self.fred_adapter.get_current_regime()
            
            if not regime:
                logger.error("❌ FRED update failed - no regime data")
                return
            
            # Prepare data (convert numpy types to Python types for JSON)
            fred_data = {
                'updated_at': datetime.utcnow().isoformat(),
                'regime': regime.regime.value,
                'confidence': float(regime.confidence),
                'position_multiplier': float(regime.get_position_size_multiplier()),
                'risk_mode': 'risk-on' if regime.is_risk_on() else 'risk-off',
                'indicators': {
                    'fed_funds_rate': float(regime.fed_funds_rate) if regime.fed_funds_rate is not None else None,
                    'treasury_10y': float(regime.treasury_10y) if regime.treasury_10y is not None else None,
                    'yield_curve': float(regime.yield_curve) if regime.yield_curve is not None else None,
                    'dollar_index': float(regime.dollar_index) if regime.dollar_index is not None else None,
                    'cpi_yoy': float(regime.cpi_yoy) if regime.cpi_yoy is not None else None,
                    'unemployment_rate': float(regime.unemployment_rate) if regime.unemployment_rate is not None else None,
                    'gdp_growth': float(regime.gdp_growth) if regime.gdp_growth is not None else None,
                    'recession_probability': float(regime.recession_probability) if regime.recession_probability is not None else None
                }
            }
            
            # Save to JSON
            output_file = self.data_dir / "macro_regime.json"
            with open(output_file, 'w') as f:
                json.dump(fred_data, f, indent=2)

            self.last_fred_update = datetime.utcnow()
            logger.info(f"✅ FRED updated: {regime.regime.value} regime")
        
        except Exception as e:
            logger.error(f"FRED update error: {e}")
            import traceback
            traceback.print_exc()
    
    def check_and_update_calendar(self):
        """Check if calendar needs update"""
        if self.last_calendar_update is None:
            self.update_calendar()
            return
        
        # Update daily
        hours_since = (datetime.utcnow() - self.last_calendar_update).total_seconds() / 3600
        if hours_since >= 24:
            self.update_calendar()
    
    def check_and_update_fred(self):
        """Check if FRED needs update"""
        if not self.fred_adapter:
            return
        
        if self.last_fred_update is None:
            self.update_fred()
            return
        
        # Update daily
        hours_since = (datetime.utcnow() - self.last_fred_update).total_seconds() / 3600
        if hours_since >= 24:
            self.update_fred()
    
    def run_all_updates(self):
        """Run all updates once"""
        logger.info("Running all data updates...")
        self.update_calendar()
        self.update_news()
        self.update_fred()
        logger.info("All updates complete")
    
    def start_scheduler(self):
        """Start scheduler with periodic updates"""
        logger.info("Starting data update scheduler...")
        logger.info(f"  - Calendar: Daily at {self.calendar_update_hour:02d}:00 UTC")
        logger.info(f"  - News: Every {self.news_update_minutes} minutes")
        logger.info(f"  - FRED: Daily at {self.fred_update_hour:02d}:00 UTC")
        
        # Initial update
        self.run_all_updates()
        
        # Schedule periodic updates
        schedule.every().day.at(f"{self.calendar_update_hour:02d}:00").do(self.update_calendar)
        schedule.every(self.news_update_minutes).minutes.do(self.update_news)
        schedule.every().day.at(f"{self.fred_update_hour:02d}:00").do(self.update_fred)
        
        # Run scheduler loop
        self.is_running = True
        
        while self.is_running:
            schedule.run_pending()
            time.sleep(10)  # Check every 10 seconds
    
    def stop_scheduler(self):
        """Stop scheduler gracefully"""
        logger.info("Stopping scheduler...")
        self.is_running = False
    
    def get_status(self) -> Dict:
        """Get scheduler status"""
        return {
            'running': self.is_running,
            'last_calendar_update': self.last_calendar_update.isoformat() if self.last_calendar_update else None,
            'last_news_update': self.last_news_update.isoformat() if self.last_news_update else None,
            'last_fred_update': self.last_fred_update.isoformat() if self.last_fred_update else None,
            'data_directory': str(self.data_dir)
        }


def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info(f"Received signal {signum}, shutting down...")
    global scheduler
    if scheduler:
        scheduler.stop_scheduler()
    sys.exit(0)


if __name__ == "__main__":
    import argparse
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Parse arguments
    parser = argparse.ArgumentParser(description='Data update scheduler')
    parser.add_argument('--mode', choices=['once', 'production'], default='once',
                        help='Run once or continuously')
    parser.add_argument('--data-dir', default='data', help='Data directory')
    parser.add_argument('--news-interval', type=int, default=5,
                        help='News update interval (minutes)')
    
    args = parser.parse_args()
    
    # Load environment
    load_dotenv()
    fred_api_key = os.getenv('FRED_API_KEY')
    
    # Create scheduler
    scheduler = DataUpdateScheduler(
        data_dir=args.data_dir,
        news_update_minutes=args.news_interval,
        fred_api_key=fred_api_key
    )
    
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Run
    if args.mode == 'once':
        logger.info("Running updates once...")
        scheduler.run_all_updates()
        logger.info("Done!")
    else:
        logger.info("Starting in production mode (continuous)...")
        scheduler.start_scheduler()
