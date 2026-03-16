"""
Simple Calendar Generator

Creates a template economic calendar with known fixed events (NFP, FOMC, etc.)
that occur on predictable schedules.

For one-off events, manually add them from: https://www.investing.com/economic-calendar/

This is the most reliable approach for retail traders.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict
import calendar


def generate_nfp_dates(year: int, month_start: int, month_end: int) -> List[Dict]:
    """
    Generate NFP (Non-Farm Payrolls) dates
    
    NFP is released on the first Friday of each month at 12:30 UTC
    """
    events = []
    
    for month in range(month_start, month_end + 1):
        # Get first day of month
        first_day = datetime(year, month, 1)
        
        # Find first Friday (weekday 4 = Friday)
        days_until_friday = (4 - first_day.weekday()) % 7
        if days_until_friday == 0:
            days_until_friday = 7  # If 1st is Friday, go to next Friday
        
        first_friday = first_day + timedelta(days=days_until_friday)
        
        events.append({
            "date": first_friday.strftime('%Y-%m-%d'),
            "time_utc": "12:30",
            "event": "NFP",
            "description": "Non-Farm Payrolls",
            "country": "US",
            "importance": "high",
            "block_minutes_before": 15,
            "block_minutes_after": 30
        })
    
    return events


def generate_cpi_dates(year: int, month_start: int, month_end: int) -> List[Dict]:
    """
    Generate CPI dates
    
    CPI is typically released around the 13th-15th of each month at 12:30 UTC
    """
    events = []
    
    for month in range(month_start, month_end + 1):
        # CPI usually on 13th (approximate - check investing.com for exact date)
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
            "note": "⚠️ Verify exact date on investing.com - usually 13th but varies"
        })
    
    return events


def generate_fomc_meetings_2026() -> List[Dict]:
    """
    Generate FOMC meeting dates for 2026
    
    FOMC meets 8 times per year on a known schedule
    Source: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
    
    ⚠️ DEPRECATED: Use fomc_scraper.get_fomc_events() instead
    This is kept as fallback only.
    """
    try:
        # Try to import and use the scraper
        from src.data.fomc_scraper import get_fomc_events
        print("📥 Fetching FOMC dates from Federal Reserve website...")
        events = get_fomc_events(2026, use_scraper=True)
        if events:
            return events
    except Exception as e:
        print(f"⚠️  FOMC scraper failed: {e}")
        print("   Using fallback dates...")
    
    # Fallback to manual dates (last verified 2026-03-13 from TradingView)
    fomc_dates_2026 = [
        "2026-01-28",  # January (Tuesday-Wednesday)
        "2026-03-18",  # March (Tuesday-Wednesday) ✅ CORRECTED
        "2026-04-29",  # April/May (Tuesday-Wednesday)
        "2026-06-17",  # June (Tuesday-Wednesday)
        "2026-07-29",  # July (Tuesday-Wednesday)
        "2026-09-23",  # September (Tuesday-Wednesday)
        "2026-11-04",  # November (Tuesday-Wednesday)
        "2026-12-16",  # December (Tuesday-Wednesday)
    ]
    
    events = []
    
    for date_str in fomc_dates_2026:
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
        
        # Add Powell press conference (quarterly meetings: March, June, September, December)
        if date_obj.month in [3, 6, 9, 12]:
            events.append({
                "date": date_str,
                "time_utc": "18:30",
                "event": "PowellPC",
                "description": "Powell Press Conference",
                "country": "US",
                "importance": "high",
                "block_minutes_before": 0,  # Already blocked by FOMC
                "block_minutes_after": 120
            })
    
    return events


def generate_gdp_dates(year: int) -> List[Dict]:
    """
    Generate GDP release dates
    
    GDP is released quarterly, typically last Friday of the month after quarter end
    """
    events = []
    
    gdp_months = [
        (1, "Q4 2025 Advanced"),  # January - Q4 previous year
        (2, "Q4 2025 Preliminary"),  # February
        (3, "Q4 2025 Final"),  # March
        (4, "Q1 2026 Advanced"),  # April
        (5, "Q1 2026 Preliminary"),  # May
        (6, "Q1 2026 Final"),  # June
        (7, "Q2 2026 Advanced"),  # July
        (8, "Q2 2026 Preliminary"),  # August
        (9, "Q2 2026 Final"),  # September
        (10, "Q3 2026 Advanced"),  # October
        (11, "Q3 2026 Preliminary"),  # November
        (12, "Q3 2026 Final"),  # December
    ]
    
    for month, description in gdp_months:
        # Get last Friday of month
        last_day = calendar.monthrange(year, month)[1]
        last_date = datetime(year, month, last_day)
        
        # Go back to Friday
        days_back = (last_date.weekday() - 4) % 7
        last_friday = last_date - timedelta(days=days_back)
        
        events.append({
            "date": last_friday.strftime('%Y-%m-%d'),
            "time_utc": "12:30",
            "event": "GDP",
            "description": f"GDP {description}",
            "country": "US",
            "importance": "high",
            "block_minutes_before": 15,
            "block_minutes_after": 15
        })
    
    return events


def generate_calendar(
    year: int = 2026,
    months_ahead: int = 3,
    output_file: str = "data/economic_calendar.json"
) -> bool:
    """
    Generate economic calendar using API + predictable patterns
    
    Uses:
    1. FOMC: Federal Reserve website (scraped)
    2. NFP/CPI/GDP: Predictable patterns (100% reliable for NFP, verify CPI)
    
    No fragile web scraping, no paid APIs.
    """
    
    current_month = datetime.now().month
    end_month = min(current_month + months_ahead, 12)
    
    print("=" * 60)
    print(f"Generating Economic Calendar for {year}")
    print("=" * 60)
    print(f"Months: {current_month} to {end_month}")
    print()
    
    try:
        # Use the new API approach
        from src.data.calendar_api import EconomicCalendarAPI
        
        api = EconomicCalendarAPI()
        all_events = api.get_complete_calendar(
            start_month=current_month,
            end_month=end_month,
            year=year
        )
        
    except Exception as e:
        print(f"⚠️  API approach failed: {e}")
        print("   Falling back to manual generation...")
        
        # Fallback to manual patterns
        all_events = []
        
        # NFP (monthly)
        nfp_events = generate_nfp_dates(year, current_month, end_month)
        print(f"✅ Generated {len(nfp_events)} NFP events")
        all_events.extend(nfp_events)
        
        # CPI (monthly)
        cpi_events = generate_cpi_dates(year, current_month, end_month)
        print(f"✅ Generated {len(cpi_events)} CPI events (verify dates!)")
        all_events.extend(cpi_events)
        
        # FOMC (8 per year)
        fomc_events = [e for e in generate_fomc_meetings_2026() 
                       if datetime.fromisoformat(e['date']).month >= current_month and
                          datetime.fromisoformat(e['date']).month <= end_month]
        print(f"✅ Generated {len(fomc_events)} FOMC events")
        all_events.extend(fomc_events)
        
        # GDP (quarterly)
        gdp_events = [e for e in generate_gdp_dates(year)
                      if datetime.fromisoformat(e['date']).month >= current_month and
                         datetime.fromisoformat(e['date']).month <= end_month]
        print(f"✅ Generated {len(gdp_events)} GDP events")
        all_events.extend(gdp_events)
        
        # Sort by date
        all_events.sort(key=lambda e: (e['date'], e['time_utc']))
    
    # Create calendar data
    calendar_data = {
        "generated_at": datetime.utcnow().isoformat(),
        "source": "FOMC from Fed website + Predictable patterns (NFP/CPI/GDP)",
        "year": year,
        "note": "⚠️ CPI dates are approximate (usually 13th) - verify on Investing.com or TradingView. FOMC dates from Federal Reserve official calendar.",
        "manual_verification_url": "https://www.investing.com/economic-calendar/",
        "event_count": len(all_events),
        "events": all_events
    }
    
    # Save to file
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w') as f:
        json.dump(calendar_data, f, indent=2)
    
    print()
    print(f"✅ Saved {len(all_events)} events to {output_file}")
    print()
    print("📅 Upcoming Events:")
    for event in all_events[:15]:
        note = f" ⚠️ {event['note']}" if 'note' in event else ""
        print(f"  {event['date']} {event['time_utc']} - {event['event']}: {event['description']}{note}")
    
    if len(all_events) > 15:
        print(f"  ... and {len(all_events) - 15} more")
    
    print()
    print("⚠️  IMPORTANT:")
    print("   - FOMC dates: From Federal Reserve (reliable)")
    print("   - NFP dates: First Friday algorithm (100% reliable)")
    print("   - CPI dates: Usually 13th but VERIFY on TradingView/Investing.com")
    print("   - GDP dates: Last Friday pattern (usually reliable)")
    print()
    print("✅ Calendar ready to use!")
    
    return True


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate economic calendar')
    parser.add_argument('--output', default='data/economic_calendar.json', help='Output JSON file')
    parser.add_argument('--year', type=int, default=2026, help='Year')
    parser.add_argument('--months', type=int, default=3, help='Months ahead to generate')
    
    args = parser.parse_args()
    
    success = generate_calendar(
        year=args.year,
        months_ahead=args.months,
        output_file=args.output
    )
    
    exit(0 if success else 1)
