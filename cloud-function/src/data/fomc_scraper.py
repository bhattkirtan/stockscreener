"""
FOMC Meeting Scraper

Fetches actual FOMC meeting dates from the Federal Reserve official calendar.
Source: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
"""

import re
import requests
from datetime import datetime
from typing import List, Dict, Optional
from bs4 import BeautifulSoup


def scrape_fomc_dates(year: int = 2026) -> List[Dict]:
    """
    Scrape FOMC meeting dates from the Federal Reserve website
    
    Args:
        year: Year to fetch FOMC dates for
        
    Returns:
        List of FOMC events with dates and times
    """
    url = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
    
    try:
        print(f"🔍 Fetching FOMC calendar from Federal Reserve...")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find the year section
        year_section = None
        for panel in soup.find_all('div', class_='panel'):
            heading = panel.find(['h3', 'h4', 'h5'])
            if heading and str(year) in heading.get_text():
                year_section = panel
                break
        
        if not year_section:
            print(f"❌ Could not find {year} FOMC calendar section")
            return []
        
        # Extract dates from the section
        events = []
        date_pattern = re.compile(r'([A-Z][a-z]+)\s+(\d{1,2})(?:-(\d{1,2}))?')
        
        # Look for date text patterns
        for text_element in year_section.find_all(['p', 'li', 'div']):
            text = text_element.get_text()
            
            # Match patterns like "March 18-19" or "March 18"
            matches = date_pattern.finditer(text)
            
            for match in matches:
                month_name = match.group(1)
                day_start = int(match.group(2))
                day_end = int(match.group(3)) if match.group(3) else day_start
                
                try:
                    # FOMC meetings typically end on the second day at 2:00 PM ET (18:00 UTC)
                    # Use the END date (when decision is announced)
                    meeting_date = datetime.strptime(
                        f"{year} {month_name} {day_end}", 
                        "%Y %B %d"
                    )
                    
                    # Check if this is a press conference meeting
                    # Usually March, June, September, December have press conferences
                    has_press_conf = meeting_date.month in [3, 6, 9, 12]
                    
                    event = {
                        "date": meeting_date.strftime('%Y-%m-%d'),
                        "time_utc": "18:00",  # 2:00 PM ET
                        "event": "FOMC",
                        "description": "FOMC Rate Decision + Statement",
                        "country": "US",
                        "importance": "high",
                        "block_minutes_before": 60,
                        "block_minutes_after": 180
                    }
                    events.append(event)
                    
                    # Add press conference if applicable
                    if has_press_conf:
                        press_event = {
                            "date": meeting_date.strftime('%Y-%m-%d'),
                            "time_utc": "18:30",
                            "event": "PowellPC",
                            "description": "Powell Press Conference",
                            "country": "US",
                            "importance": "high",
                            "block_minutes_before": 0,  # Already blocked by FOMC
                            "block_minutes_after": 120
                        }
                        events.append(press_event)
                    
                    print(f"  ✅ Found FOMC meeting: {meeting_date.strftime('%Y-%m-%d')} ({month_name} {day_end})")
                    
                except ValueError as e:
                    print(f"  ⚠️  Could not parse date: {month_name} {day_end} - {e}")
                    continue
        
        print(f"✅ Scraped {len([e for e in events if e['event'] == 'FOMC'])} FOMC meetings from Fed website")
        return events
        
    except requests.RequestException as e:
        print(f"❌ Failed to fetch FOMC calendar: {e}")
        return []
    except Exception as e:
        print(f"❌ Error parsing FOMC calendar: {e}")
        return []


def get_fomc_fallback_dates_2026() -> List[Dict]:
    """
    Fallback FOMC dates for 2026 if scraping fails
    
    Based on typical Fed schedule (8 meetings per year)
    Source: Fed typically meets every 6-7 weeks
    
    ⚠️ These are ESTIMATED - should be updated from official Fed calendar
    """
    # Last verified: 2026-03-13 from TradingView economic calendar
    fomc_dates = [
        "2026-01-28",  # January (Tuesday-Wednesday)
        "2026-03-18",  # March (Tuesday-Wednesday) - CORRECTED from TradingView
        "2026-04-29",  # April/May (Tuesday-Wednesday)
        "2026-06-17",  # June (Tuesday-Wednesday)
        "2026-07-29",  # July (Tuesday-Wednesday)
        "2026-09-23",  # September (Tuesday-Wednesday)
        "2026-11-04",  # November (Tuesday-Wednesday)
        "2026-12-16",  # December (Tuesday-Wednesday)
    ]
    
    events = []
    
    for date_str in fomc_dates:
        date_obj = datetime.fromisoformat(date_str)
        
        events.append({
            "date": date_str,
            "time_utc": "18:00",  # 2:00 PM ET
            "event": "FOMC",
            "description": "FOMC Rate Decision + Statement",
            "country": "US",
            "importance": "high",
            "block_minutes_before": 60,
            "block_minutes_after": 180
        })
        
        # Add Powell press conference for quarterly meetings
        if date_obj.month in [3, 6, 9, 12]:
            events.append({
                "date": date_str,
                "time_utc": "18:30",
                "event": "PowellPC",
                "description": "Powell Press Conference",
                "country": "US",
                "importance": "high",
                "block_minutes_before": 0,
                "block_minutes_after": 120
            })
    
    return events


def get_fomc_events(year: int = 2026, use_scraper: bool = True) -> List[Dict]:
    """
    Get FOMC events - try scraping first, fallback to manual dates
    
    Args:
        year: Year to fetch
        use_scraper: If True, attempt to scrape from Fed website
        
    Returns:
        List of FOMC events
    """
    if use_scraper:
        events = scrape_fomc_dates(year)
        if events:
            return events
        else:
            print("⚠️  Scraping failed, using fallback dates")
    
    return get_fomc_fallback_dates_2026()


if __name__ == "__main__":
    print("=" * 60)
    print("FOMC Calendar Scraper")
    print("=" * 60)
    print()
    
    # Try scraping
    events = get_fomc_events(2026, use_scraper=True)
    
    print()
    print(f"Found {len([e for e in events if e['event'] == 'FOMC'])} FOMC meetings:")
    for event in events:
        if event['event'] == 'FOMC':
            print(f"  📅 {event['date']} at {event['time_utc']} UTC")
    
    print()
    print("✅ Done!")
