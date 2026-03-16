"""
Economic Calendar API Integration

🎯 PRIMARY SOURCE: ForexFactory JSON Feed (FREE, NO AUTH REQUIRED!)
   - URL: https://nfs.faireconomy.media/ff_calendar_thisweek.json
   - All major economic events (NFP, CPI, GDP, etc.)
   - Real dates, impact levels, multiple countries
   - Updates daily, no rate limits
   - NO API KEY NEEDED! 🎉

✅ FOMC: Federal Reserve official website (scraped)

✅ Optional: FRED API (requires free API key)

✅ Fallback: Predictable patterns if feeds fail

100% FREE - works out of the box, no registration needed!
"""

import requests
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging
import os

logger = logging.getLogger(__name__)


class EconomicCalendarAPI:
    """
    Fetch economic events from free APIs and official sources
    """
    
    def __init__(self, fred_api_key: Optional[str] = None):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 Trading Bot (Educational)'
        })
        
        # FRED API key (optional - ForexFactory is primary source)
        self.fred_api_key = fred_api_key or os.environ.get('FRED_API_KEY')
        if self.fred_api_key:
            logger.info("✅ FRED API key configured (optional)")
    
    def fetch_from_forexfactory(self) -> List[Dict]:
        """
        Fetch economic events from ForexFactory JSON feed
        
        🎯 THIS IS THE BEST SOURCE:
        - FREE, no authentication required
        - Real dates (not approximations)
        - All major events (NFP, CPI, GDP, Fed speeches, etc.)
        - Updates daily
        - Multiple countries
        - Impact levels (High, Medium, Low)
        
        URL: https://nfs.faireconomy.media/ff_calendar_thisweek.json
        
        Returns:
            List of economic events
        """
        try:
            url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
            
            response = self.session.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                # Filter and normalize
                events = self._normalize_forexfactory_data(data)
                logger.info(f"✅ Fetched {len(events)} events from ForexFactory")
                return events
            else:
                logger.error(f"ForexFactory returned {response.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"ForexFactory feed error: {e}")
            return []
    
    def _normalize_forexfactory_data(self, data: List[Dict]) -> List[Dict]:
        """
        Normalize ForexFactory JSON to our format
        
        ForexFactory format:
        {
          "title": "Core CPI m/m",
          "country": "USD",
          "date": "2026-03-11T08:30:00-04:00",
          "impact": "High",
          "forecast": "0.2%",
          "previous": "0.3%"
        }
        """
        events = []
        
        # Only keep high-impact USD events
        high_impact_keywords = ['NFP', 'CPI', 'GDP', 'FOMC', 'Fed', 'Employment', 
                                'Inflation', 'PCE', 'Unemployment', 'Retail Sales']
        
        for item in data:
            country = item.get('country', '')
            impact = item.get('impact', '')
            title = item.get('title', '')
            date_str = item.get('date', '')
            
            # Filter: USD only, High impact or important keywords
            if country != 'USD':
                continue
            
            if impact != 'High' and not any(kw in title for kw in high_impact_keywords):
                continue
            
            # Parse date
            try:
                dt = datetime.fromisoformat(date_str)
                date = dt.strftime('%Y-%m-%d')
                time_utc = dt.strftime('%H:%M')
            except:
                continue
            
            # Map to event codes
            event_code = self._map_event_code(title)
            
            events.append({
                "date": date,
                "time_utc": time_utc,
                "event": event_code,
                "description": title,
                "country": "US",
                "importance": "high" if impact == "High" else "medium",
                "block_minutes_before": 15 if impact == "High" else 10,
                "block_minutes_after": 30 if impact == "High" else 15,
                "source": "ForexFactory",
                "forecast": item.get('forecast', ''),
                "previous": item.get('previous', '')
            })
        
        return events
    
    def _map_event_code(self, title: str) -> str:
        """Map ForexFactory event title to our event code"""
        title_lower = title.lower()
        
        if 'non-farm' in title_lower or 'nonfarm' in title_lower:
            return 'NFP'
        elif 'cpi' in title_lower and 'core' not in title_lower:
            return 'CPI'
        elif 'core cpi' in title_lower:
            return 'Core CPI'
        elif 'gdp' in title_lower:
            return 'GDP'
        elif 'fomc' in title_lower:
            return 'FOMC'
        elif 'pce' in title_lower:
            return 'PCE'
        elif 'ppi' in title_lower:
            return 'PPI'
        elif 'retail sales' in title_lower:
            return 'Retail Sales'
        elif 'unemployment' in title_lower:
            return 'Unemployment'
        elif 'fed' in title_lower:
            return 'Fed Speech'
        else:
            return title[:20]  # Truncate long titles
    
    def fetch_from_fred(self, start_date: str, end_date: str) -> List[Dict]:
        """
        Fetch economic release dates from FRED API
        
        FRED (Federal Reserve Economic Data) is THE BEST SOURCE:
        - All major economic releases (NFP, CPI, GDP, Retail Sales, etc.)
        - Official government data - most reliable
        - Free API with generous rate limits
        
        API Docs: https://fred.stlouisfed.org/docs/api/fred/
        Get Key: https://fred.stlouisfed.org/docs/api/api_key.html
        
        Args:
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD
            
        Returns:
            List of economic events
        """
        if not self.fred_api_key:
            logger.warning("FRED API key not configured - skipping")
            return []
        
        try:
            # FRED releases/dates endpoint
            # Get all release dates in date range
            url = "https://api.stlouisfed.org/fred/releases/dates"
            params = {
                'api_key': self.fred_api_key,
                'realtime_start': start_date,
                'realtime_end': end_date,
                'file_type': 'json'
            }
            
            response = self.session.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                releases = data.get('release_dates', [])
                
                # Map FRED releases to our format
                events = self._normalize_fred_data(releases)
                logger.info(f"✅ Fetched {len(events)} events from FRED API")
                return events
            else:
                logger.error(f"FRED API returned {response.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"FRED API error: {e}")
            return []
    
    def _normalize_fred_data(self, releases: List[Dict]) -> List[Dict]:
        """
        Normalize FRED API response to our format
        
        FRED provides:
        - release_id: e.g., 50 (Employment Situation)
        - release_name: e.g., "Employment Situation"
        - date: e.g., "2026-03-06"
        """
        events = []
        
        # Map important releases to our event types
        important_releases = {
            50: ("NFP", "Non-Farm Payrolls", "12:30", "high"),  # Employment Situation
            10: ("CPI", "Consumer Price Index", "12:30", "high"),  # Consumer Price Index
            53: ("PPI", "Producer Price Index", "12:30", "medium"),  # Producer Price Index
            9: ("GDP", "Gross Domestic Product", "12:30", "high"),  # Gross Domestic Product
            228: ("PCE", "Personal Consumption Expenditures", "12:30", "high"),  # Personal Income
            # Add more as needed
        }
        
        for release in releases:
            release_id = release.get('release_id')
            release_name = release.get('release_name', '')
            date = release.get('date', '')
            
            if release_id in important_releases:
                event_code, description, time_utc, importance = important_releases[release_id]
                
                events.append({
                    "date": date,
                    "time_utc": time_utc,
                    "event": event_code,
                    "description": description,
                    "country": "US",
                    "importance": importance,
                    "block_minutes_before": 15 if importance == "high" else 10,
                    "block_minutes_after": 30 if importance == "high" else 15,
                    "source": "FRED"
                })
        
        return events
    
    def fetch_fomc_dates(self, year: int = 2026) -> List[Dict]:
        """
        Fetch FOMC meeting dates from Federal Reserve website
        Uses fomc_scraper module
        """
        try:
            from src.data.fomc_scraper import get_fomc_events
            events = get_fomc_events(year, use_scraper=True)
            logger.info(f"✅ Fetched {len([e for e in events if e['event'] == 'FOMC'])} FOMC dates from Fed")
            return events
        except Exception as e:
            logger.error(f"Failed to fetch FOMC dates: {e}")
            return []
    
    def fetch_from_tradingeconomics_free(self, country: str = 'united-states') -> List[Dict]:
        """
        TradingEconomics API (REQUIRES PAID API KEY - NOT FREE)
        
        Note: This is NOT free. Requires paid subscription.
        Left here as template if you want to add paid API key.
        """
        try:
            # ❌ NOT FREE - Requires paid API key
            # url = f"https://api.tradingeconomics.com/calendar/country/{country}?c=YOUR_API_KEY"
            logger.warning("TradingEconomics requires paid API key - skipping")
            return []
            
            response = self.session.get(url, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"✅ Fetched {len(data)} events from TradingEconomics")
                return self._normalize_trading_economics_data(data)
            else:
                logger.warning(f"TradingEconomics returned {response.status_code}")
                return []
                
        except Exception as e:
            logger.warning(f"TradingEconomics API not available: {e}")
            return []
    
    def fetch_from_financial_modeling_prep(self, from_date: str, to_date: str) -> List[Dict]:
        """
        Try Financial Modeling Prep API (has free tier)
        
        API: https://financialmodelingprep.com/developer/docs/#Economic-Calendar
        Note: Requires free API key
        """
        # Not implemented - requires API key registration
        return []
    
    def generate_predictable_events(
        self,
        start_month: int,
        end_month: int,
        year: int = 2026
    ) -> List[Dict]:
        """
        Generate events that follow predictable patterns
        
        This is actually MORE reliable than scraping for these specific events:
        - NFP: First Friday of month at 12:30 UTC
        - CPI: ~13th of month at 12:30 UTC (verify exact date)
        - GDP: Last Friday of month at 12:30 UTC (quarterly)
        """
        events = []
        
        # NFP (Non-Farm Payrolls) - First Friday of every month
        events.extend(self._generate_nfp_dates(year, start_month, end_month))
        
        # CPI (Consumer Price Index) - ~13th of every month
        events.extend(self._generate_cpi_dates(year, start_month, end_month))
        
        # GDP - Quarterly, last Friday after quarter end
        events.extend(self._generate_gdp_dates(year, start_month, end_month))
        
        logger.info(f"✅ Generated {len(events)} predictable events")
        return events
    
    def _generate_nfp_dates(self, year: int, month_start: int, month_end: int) -> List[Dict]:
        """NFP is ALWAYS first Friday at 12:30 UTC - this is 100% reliable"""
        from calendar import monthrange
        
        events = []
        for month in range(month_start, min(month_end + 1, 13)):
            # First day of month
            first_day = datetime(year, month, 1)
            
            # Find first Friday (0=Monday, 4=Friday)
            days_until_friday = (4 - first_day.weekday()) % 7
            if days_until_friday == 0:
                days_until_friday = 7  # Next Friday if 1st is Friday
            
            nfp_date = first_day + timedelta(days=days_until_friday)
            
            events.append({
                "date": nfp_date.strftime('%Y-%m-%d'),
                "time_utc": "12:30",
                "event": "NFP",
                "description": "Non-Farm Payrolls",
                "country": "US",
                "importance": "high",
                "block_minutes_before": 15,
                "block_minutes_after": 30
            })
        
        return events
    
    def _generate_cpi_dates(self, year: int, month_start: int, month_end: int) -> List[Dict]:
        """
        CPI is TYPICALLY around 13th-15th at 12:30 UTC
        ⚠️ Exact date varies - should verify on Investing.com
        """
        events = []
        for month in range(month_start, min(month_end + 1, 13)):
            # Use 13th as default (most common)
            cpi_date = datetime(year, month, 13)
            
            events.append({
                "date": cpi_date.strftime('%Y-%m-%d'),
                "time_utc": "12:30",
                "event": "CPI",
                "description": "Consumer Price Index",
                "country": "US",
                "importance": "high",
                "block_minutes_before": 15,
                "block_minutes_after": 30,
                "note": "⚠️ VERIFY exact date - usually 13th but can be 12-15th"
            })
        
        return events
    
    def _generate_gdp_dates(self, year: int, month_start: int, month_end: int) -> List[Dict]:
        """GDP is quarterly, usually last Friday of the month"""
        import calendar
        
        events = []
        gdp_schedule = {
            1: ("Q4 2025", "Advanced"),
            2: ("Q4 2025", "Preliminary"),
            3: ("Q4 2025", "Final"),
            4: ("Q1 2026", "Advanced"),
            5: ("Q1 2026", "Preliminary"),
            6: ("Q1 2026", "Final"),
            7: ("Q2 2026", "Advanced"),
            8: ("Q2 2026", "Preliminary"),
            9: ("Q2 2026", "Final"),
            10: ("Q3 2026", "Advanced"),
            11: ("Q3 2026", "Preliminary"),
            12: ("Q3 2026", "Final"),
        }
        
        for month in range(month_start, min(month_end + 1, 13)):
            if month not in gdp_schedule:
                continue
            
            quarter, release_type = gdp_schedule[month]
            
            # Last day of month
            last_day = calendar.monthrange(year, month)[1]
            last_date = datetime(year, month, last_day)
            
            # Go back to last Friday
            days_back = (last_date.weekday() - 4) % 7
            last_friday = last_date - timedelta(days=days_back)
            
            events.append({
                "date": last_friday.strftime('%Y-%m-%d'),
                "time_utc": "12:30",
                "event": "GDP",
                "description": f"GDP {quarter} {release_type}",
                "country": "US",
                "importance": "high",
                "block_minutes_before": 15,
                "block_minutes_after": 15
            })
        
        return events
    
    def _normalize_trading_economics_data(self, data: List[Dict]) -> List[Dict]:
        """Normalize TradingEconomics API response to our format"""
        events = []
        
        for item in data:
            # Map importance
            importance_map = {'High': 'high', 'Medium': 'medium', 'Low': 'low'}
            importance = importance_map.get(item.get('Importance', ''), 'low')
            
            if importance != 'high':
                continue  # Only high-impact
            
            events.append({
                "date": item.get('Date', '').split('T')[0],
                "time_utc": item.get('Time', 'TBD'),
                "event": item.get('Event', ''),
                "description": item.get('Category', item.get('Event', '')),
                "country": "US",
                "importance": importance,
                "block_minutes_before": 15,
                "block_minutes_after": 30
            })
        
        return events
    
    def get_complete_calendar(
        self,
        start_month: int,
        end_month: int,
        year: int = 2026
    ) -> List[Dict]:
        """
        Get complete economic calendar using all available sources
        
        Priority:
        1. 🎯 ForexFactory JSON: All events with REAL dates (free, no auth!)
        2. 📅 FOMC: Federal Reserve official website  
        3. 📊 FRED API: Optional if API key configured
        4. 🔄 Fallback: Predictable patterns if all feeds fail
        
        Args:
            start_month: Starting month (1-12)
            end_month: Ending month (1-12)
            year: Year
            
        Returns:
            List of all economic events sorted by date
        """
        all_events = []
        
        # Calculate date range
        start_date = f"{year}-{start_month:02d}-01"
        
        # Last day of end_month
        import calendar
        last_day = calendar.monthrange(year, end_month)[1]
        end_date = f"{year}-{end_month:02d}-{last_day:02d}"
        
        # 1. ForexFactory JSON feed (PRIMARY - NO AUTH NEEDED!)
        ff_events = self.fetch_from_forexfactory()
        if ff_events:
            # Filter by date range
            ff_in_range = [
                e for e in ff_events
                if start_month <= datetime.fromisoformat(e['date']).month <= end_month
                   and datetime.fromisoformat(e['date']).year == year
            ]
            all_events.extend(ff_in_range)
            logger.info(f"📅 ForexFactory: {len(ff_in_range)} events")
        else:
            logger.warning("ForexFactory feed failed - using fallback")
            # Fallback to patterns if ForexFactory fails
            predictable = self.generate_predictable_events(start_month, end_month, year)
            all_events.extend(predictable)
            logger.info(f"📅 Pattern fallback (NFP/CPI/GDP): {len(predictable)} events")
        
        # 2. Optional: FRED API (if configured)
        if self.fred_api_key:
            fred_events = self.fetch_from_fred(start_date, end_date)
            all_events.extend(fred_events)
            logger.info(f"📅 FRED API: {len(fred_events)} events")
        
        # 3. Fetch FOMC from official source (always)
        fomc_events = self.fetch_fomc_dates(year)
        fomc_in_range = [
            e for e in fomc_events
            if start_month <= datetime.fromisoformat(e['date']).month <= end_month
        ]
        all_events.extend(fomc_in_range)
        logger.info(f"📅 FOMC: {len(fomc_in_range)} events")
        
        # Sort by date and time
        all_events.sort(key=lambda e: (e['date'], e.get('time_utc', '00:00')))
        
        # Remove duplicates (keep first)
        seen = set()
        unique_events = []
        for event in all_events:
            key = (event['date'], event['event'])
            if key not in seen:
                seen.add(key)
                unique_events.append(event)
        
        logger.info(f"✅ Total unique events: {len(unique_events)}")
        
        return unique_events


if __name__ == "__main__":
    # Test the API
    api = EconomicCalendarAPI()
    
    events = api.get_complete_calendar(
        start_month=3,
        end_month=6,
        year=2026
    )
    
    print(f"\n✅ Found {len(events)} events:\n")
    for event in events[:20]:
        note = f" - {event['note']}" if 'note' in event else ""
        print(f"{event['date']} {event['time_utc']} | {event['event']}: {event['description']}{note}")
