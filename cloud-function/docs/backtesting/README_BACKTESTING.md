# 🚀 Quick Start - Backtesting Setup

## What Was Built

✅ **Shared API Client** (`src/capital_client.py`)
- Reusable authentication for prod & backtest
- Token caching, rate limiting, retry logic
- No code duplication!

✅ **Separate Data Fetcher** (`src/cache_data.py`)
- Fetches from Capital.com once
- Caches to `data/` directory as CSV
- 24-hour cache TTL

✅ **Separate Backtest Runner** (`src/run_backtest_from_cache.py`)
- Uses cached data only (no API calls!)
- Exports JSON for dashboard UI
- Fast: runs in 1-3 seconds

✅ **Updated Production Code** (`main.py`)
- Now uses shared `capital_client`
- Same auth logic everywhere

---

## ⚡ Start Here

### 1. Configure Credentials
```bash
python3 setup_local_env.py
```
Enter your Capital.com credentials (use **demo** account).

### 2. Test Authentication
```bash
python3 src/capital_client.py
```
Should show: ✅ Authentication successful  

### 3. Cache Historical Data
```bash
python3 src/cache_data.py
```
Fetches GOLD & EURUSD data, saves to `data/` directory.

### 4. Run Backtest
```bash
python3 src/run_backtest_from_cache.py
```
Generates `data/backtest_results.json` for your dashboard.

---

## 📊 Dashboard Integration

The JSON export contains:
- Performance metrics (P&L, returns, Sharpe)
- Trade statistics (win rate, avg win/loss)
- Risk metrics (drawdown, profit factor)
- Sample trades with entry/exit details

Load `data/backtest_results.json` in your UI to display charts and tables.

---

## 🎯 Key Benefits

✅ **No Code Duplication** - One auth client for everything  
✅ **Cache Once, Run Many** - Fetch data once, reuse for multiple backtests  
✅ **Production Safe** - Same logic in prod and test  
✅ **Dashboard Ready** - JSON export for easy UI integration  
✅ **Fast Iteration** - Backtests run in seconds from cache

---

## 📁 Files Created

```
cloud-function/
├── src/
│   ├── capital_client.py           # ✅ NEW - Shared auth
│   ├── cache_data.py               # ✅ NEW - Fetch & cache
│   ├── run_backtest_from_cache.py  # ✅ NEW - Backtest from cache
│   └── ...
├── main.py                          # ✅ UPDATED - Uses shared client
├── setup_local_env.py              # ✅ NEW - Credential setup
├── data/                            # Created by cache_data.py
│   ├── GOLD_M15_2000bars.csv
│   └── backtest_results.json        # For dashboard
└── docs/
    ├── WORKFLOW_SUMMARY.md          # ✅ NEW - Full guide
    └── BACKTEST_QUICKSTART.md       # Detailed docs
```

---

## 💡 Next Steps

1. **Run setup**: `python3 setup_local_env.py`
2. **Cache data**: `python3 src/cache_data.py`
3. **Run backtest**: `python3 src/run_backtest_from_cache.py`
4. **View results**: `cat data/backtest_results.json`
5. **Build dashboard**: Use JSON to display metrics

---

**Status:** ✅ Ready to configure and test!  
**Docs:** See `docs/WORKFLOW_SUMMARY.md` for details
