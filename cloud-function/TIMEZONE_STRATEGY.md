# ⏰ Timezone Handling Strategy

## 🎯 Core Principle: Everything in UTC

Our system follows the **"Store UTC, Display Local"** principle to avoid timezone confusion.

---

## ✅ Current Implementation

### 1. **Calendar Events (JSON)**
```json
{
  "date": "2026-03-18",
  "time_utc": "18:00",  ← Always UTC!
  "event": "FOMC",
  "country": "US"
}
```

### 2. **News Headlines (JSON)**
```json
{
  "published_at": "2026-03-13T14:50:00",  ← Timestamp in UTC
  "source": "Reuters",
  "title": "Fed holds rates steady"
}
```

### 3. **API Responses**
```json
{
  "time_utc": "18:00",  ← Field name indicates UTC
  "timestamp": "2026-03-18T18:00:00Z"  ← Z = Zulu = UTC
}
```

### 4. **Backtester**
- All OHLCV data indexed by UTC timestamps
- Event blocker checks against UTC times
- Trade execution times recorded in UTC

---

## 🌍 Real-World Examples

### FOMC Announcement (2:00 PM EST = 18:00 UTC)

| Location | Local Time | UTC Offset | Blocked Period |
|----------|------------|------------|----------------|
| 🇺🇸 New York | 2:00 PM EDT | UTC-4 | 1:45 PM - 2:15 PM |
| 🇺🇸 Los Angeles | 11:00 AM PDT | UTC-7 | 10:45 AM - 11:15 AM |
| 🇬🇧 London | 6:00 PM GMT | UTC+0 | 5:45 PM - 6:15 PM |
| 🇯🇵 Tokyo | 3:00 AM JST (next day) | UTC+9 | 2:45 AM - 3:15 AM |

**Block Window in UTC**: 17:45 - 18:15 UTC

### NFP Release (8:30 AM EST = 12:30 UTC)

| Location | Local Time | UTC Offset |
|----------|------------|------------|
| 🇺🇸 New York | 8:30 AM EDT | UTC-4 |
| 🇺🇸 Los Angeles | 5:30 AM PDT | UTC-7 |
| 🇬🇧 London | 12:30 PM GMT | UTC+0 |
| 🇯🇵 Tokyo | 9:30 PM JST | UTC+9 |

**Block Window in UTC**: 12:15 - 13:00 UTC (45 min for NFP)

---

## 🔄 DST (Daylight Saving Time) Handling

### US Daylight Saving Time
- **Standard Time (EST)**: November - March → UTC-5
- **Daylight Time (EDT)**: March - November → UTC-4

### Example: FOMC at 2:00 PM Eastern
- **March (EDT)**: 2:00 PM EDT = **18:00 UTC** ✅ (Our calendar)
- **December (EST)**: 2:00 PM EST = **19:00 UTC**

**Our Solution**: ForexFactory JSON already accounts for DST, returning correct UTC times year-round.

---

## ⚠️ Common Timezone Mistakes (Avoided)

### ❌ WRONG: Store Local Times
```json
{
  "time": "14:00",  ← Which timezone? EST? EDT? PST?
  "event": "FOMC"
}
```
**Problem**: Ambiguous! Is this New York time? London time?

### ✅ CORRECT: Store UTC Times
```json
{
  "time_utc": "18:00",  ← Unambiguous! Always UTC
  "event": "FOMC"
}
```
**Benefit**: Same time for everyone, convert locally for display.

---

## 🧪 Timezone Tests Coverage

Our test suite (`test_timezone_handling.py`) validates:

1. ✅ **UTC Storage**: Events stored in UTC
2. ✅ **Local Conversions**: NY, LA, London, Tokyo conversions
3. ✅ **Block Windows**: 15 min before/after in all timezones
4. ✅ **Midnight Crossings**: Event at 11:30 PM UTC crosses to next day in Tokyo
5. ✅ **DST Transitions**: EST/EDT and GMT/BST handled correctly
6. ✅ **NFP Times**: 8:30 AM EST = 12:30 UTC (March)
7. ✅ **FOMC Times**: 2:00 PM EST = 18:00 UTC (March)
8. ✅ **Year Boundaries**: New Year's Eve 11:00 PM UTC = Jan 1 in Tokyo
9. ✅ **Week Boundaries**: Monday 00:00 UTC = Sunday in Hawaii
10. ✅ **ForexFactory JSON**: Parse UTC times correctly
11. ✅ **API Responses**: Return UTC with clear notation
12. ✅ **Best Practices**: Store UTC, convert at display

**Total**: 15 comprehensive timezone tests

---

## 🔧 Implementation Details

### Backend (Python)
```python
from datetime import datetime, timedelta

# ✅ Store event time in UTC (naive datetime = UTC)
event_time = datetime(2026, 3, 18, 18, 0)

# ✅ Calculate block window in UTC
block_start = event_time - timedelta(minutes=15)
block_end = event_time + timedelta(minutes=15)

# ✅ Check current time (assumed UTC)
current_time = datetime.utcnow()
is_blocked = block_start <= current_time <= block_end
```

### Frontend (JavaScript) - For Future UI
```javascript
// API returns UTC
const eventUTC = "2026-03-18T18:00:00Z";

// Convert to user's local timezone
const localTime = new Date(eventUTC);
console.log(localTime.toLocaleString('en-US', { 
  timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone 
}));
// Output: "3/18/2026, 2:00:00 PM" (if user in New York)
```

---

## 📊 Timezone Data Sources

### 1. **ForexFactory JSON**
- ✅ Returns events in UTC
- ✅ Accounts for DST automatically
- ✅ Example: FOMC always shows correct UTC time regardless of season

### 2. **Federal Reserve Website**
- ✅ FOMC meetings listed in EST/EDT
- ✅ We convert to UTC when scraping
- ✅ March meetings: Add 4 hours (EDT)
- ✅ December meetings: Add 5 hours (EST)

### 3. **RSS News Feeds**
- ✅ Timestamps in ISO 8601 format with UTC indicator
- ✅ Example: `2026-03-13T14:50:00+00:00` or `2026-03-13T14:50:00Z`

---

## 🚀 Benefits of Our Approach

1. **No Ambiguity**: UTC is universal standard
2. **No DST Bugs**: Conversions handled at display layer
3. **Global Compatibility**: Works for traders anywhere
4. **Consistent Backtests**: Same results regardless of where run
5. **Simple Logic**: No complex timezone math in backend
6. **Future-Proof**: Adding new timezones doesn't break anything

---

## 📝 Key Takeaways

✅ **All calendar events**: Stored in UTC
✅ **All news timestamps**: Stored in UTC  
✅ **All block calculations**: Performed in UTC
✅ **All API responses**: Return UTC times
✅ **All backtest data**: Indexed by UTC
✅ **User display**: Convert to local timezone only at frontend

**Remember**: When in doubt, use UTC! 🌍

---

## 🧪 Run Timezone Tests

```bash
cd /Users/kirtanbhatt/code/stockScreener/cloud-function/tests

# Run timezone tests
python3 -m unittest test_timezone_handling -v

# Expected: 15 tests, all pass ✅
```

---

## 📚 Reference

- **ISO 8601**: International date/time standard
- **UTC**: Coordinated Universal Time (not affected by DST)
- **Z notation**: "Zulu time" = UTC (e.g., `2026-03-18T18:00:00Z`)
- **Naive datetime**: Python datetime without tzinfo (we treat as UTC)
- **Aware datetime**: Python datetime with tzinfo (we avoid for simplicity)

**Documentation**: [Python datetime](https://docs.python.org/3/library/datetime.html)
