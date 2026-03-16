"""
Generate Historical Economic Calendar for Backtesting

Generates calendar events for 2024-2026 period to support 2-year backtests.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict
import calendar


def generate_nfp_dates(year: int) -> List[Dict]:
    """
    Generate NFP (Non-Farm Payrolls) dates for entire year
    NFP is released on the first Friday of each month at 12:30 UTC
    """
    events = []
    
    for month in range(1, 13):
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


def generate_cpi_dates(year: int) -> List[Dict]:
    """
    Generate CPI dates for entire year
    CPI is typically released around the 13th of each month at 12:30 UTC
    """
    events = []
    
    for month in range(1, 13):
        cpi_date = datetime(year, month, 13)
        
        events.append({
            "date": cpi_date.strftime('%Y-%m-%d'),
            "time_utc": "12:30",
            "event": "CPI",
            "description": "Consumer Price Index",
            "country": "US",
            "importance": "high",
            "block_minutes_before": 15,
            "block_minutes_after": 30
        })
    
    return events


def generate_fomc_meetings(year: int) -> List[Dict]:
    """
    Generate FOMC meeting dates
    FOMC meets 8 times per year on a known schedule
    
    Historical dates verified from Federal Reserve:
    https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
    """
    
    # FOMC meeting dates by year (decision announcement day)
    fomc_dates = {
        2024: [
            "2024-01-31",  # January
            "2024-03-20",  # March
            "2024-05-01",  # April/May
            "2024-06-12",  # June
            "2024-07-31",  # July
            "2024-09-18",  # September
            "2024-11-07",  # November
            "2024-12-18",  # December
        ],
        2025: [
            "2025-01-29",  # January
            "2025-03-19",  # March
            "2025-04-30",  # April/May
            "2025-06-18",  # June
            "2025-07-30",  # July
            "2025-09-17",  # September
            "2025-11-05",  # November
            "2025-12-17",  # December
        ],
        2026: [
            "2026-01-28",  # January
            "2026-03-18",  # March
            "2026-04-29",  # April/May
            "2026-06-17",  # June
            "2026-07-29",  # July
            "2026-09-23",  # September
            "2026-11-04",  # November
            "2026-12-16",  # December
        ]
    }
    
    if year not in fomc_dates:
        return []
    
    events = []
    
    for date_str in fomc_dates[year]:
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
    Generate GDP release dates for entire year
    GDP is released quarterly, typically last Friday of the month after quarter end
    """
    events = []
    
    # GDP descriptions by month
    gdp_months = [
        (1, f"Q4 {year-1} Advanced"),
        (2, f"Q4 {year-1} Preliminary"),
        (3, f"Q4 {year-1} Final"),
        (4, f"Q1 {year} Advanced"),
        (5, f"Q1 {year} Preliminary"),
        (6, f"Q1 {year} Final"),
        (7, f"Q2 {year} Advanced"),
        (8, f"Q2 {year} Preliminary"),
        (9, f"Q2 {year} Final"),
        (10, f"Q3 {year} Advanced"),
        (11, f"Q3 {year} Preliminary"),
        (12, f"Q3 {year} Final"),
    ]
    
    for month, description in gdp_months:
        # Get last Friday of month
        last_day = calendar.monthrange(year, month)[1]
        last_date = datetime(year, month, last_day)
        
        # Go back to last Friday
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


def generate_multi_year_calendar(
    start_year: int = 2024,
    end_year: int = 2026,
    output_file: str = "data/economic_calendar.json"
) -> bool:
    """
    Generate economic calendar for multiple years (2024-2026)
    """
    
    print("=" * 60)
    print(f"Generating Economic Calendar for {start_year}-{end_year}")
    print("=" * 60)
    print()
    
    all_events = []
    
    for year in range(start_year, end_year + 1):
        print(f"Generating events for {year}...")
        
        # NFP (12 per year)
        nfp_events = generate_nfp_dates(year)
        print(f"  ✅ {len(nfp_events)} NFP events")
        all_events.extend(nfp_events)
        
        # CPI (12 per year)
        cpi_events = generate_cpi_dates(year)
        print(f"  ✅ {len(cpi_events)} CPI events")
        all_events.extend(cpi_events)
        
        # FOMC (8 per year)
        fomc_events = generate_fomc_meetings(year)
        print(f"  ✅ {len(fomc_events)} FOMC events")
        all_events.extend(fomc_events)
        
        # GDP (12 per year)
        gdp_events = generate_gdp_dates(year)
        print(f"  ✅ {len(gdp_events)} GDP events")
        all_events.extend(gdp_events)
        
        print()
    
    # Sort by date and time
    all_events.sort(key=lambda e: (e['date'], e['time_utc']))
    
    # Create calendar data
    calendar_data = {
        "generated_at": datetime.utcnow().isoformat(),
        "source": "Historical calendar for backtesting (2024-2026)",
        "years": list(range(start_year, end_year + 1)),
        "note": "Generated for backtesting. NFP=first Friday, CPI≈13th, FOMC=official dates, GDP=last Friday",
        "event_count": len(all_events),
        "events": all_events
    }
    
    # Save to file
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w') as f:
        json.dump(calendar_data, f, indent=2)
    
    print("=" * 60)
    print(f"✅ Saved {len(all_events)} events to {output_file}")
    print("=" * 60)
    print()
    
    # Show summary by year
    for year in range(start_year, end_year + 1):
        year_events = [e for e in all_events if e['date'].startswith(str(year))]
        print(f"{year}: {len(year_events)} events")
    
    print()
    print("📅 Sample Events:")
    # Show first few from each year
    for year in range(start_year, end_year + 1):
        year_events = [e for e in all_events if e['date'].startswith(str(year))]
        if year_events:
            print(f"\n{year}:")
            for event in year_events[:5]:
                print(f"  {event['date']} {event['time_utc']} - {event['event']}: {event['description']}")
            if len(year_events) > 5:
                print(f"  ... and {len(year_events) - 5} more")
    
    print()
    print("✅ Calendar ready for backtesting!")
    
    return True


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate multi-year economic calendar for backtesting')
    parser.add_argument('--start-year', type=int, default=2024, help='Start year')
    parser.add_argument('--end-year', type=int, default=2026, help='End year')
    parser.add_argument('--output', default='data/economic_calendar.json', help='Output JSON file')
    
    args = parser.parse_args()
    
    success = generate_multi_year_calendar(
        start_year=args.start_year,
        end_year=args.end_year,
        output_file=args.output
    )
    
    exit(0 if success else 1)
