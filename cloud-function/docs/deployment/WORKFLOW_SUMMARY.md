# Complete Backtesting Workflow Summary

## ✅ Implementation Complete!

### 📦 What's Been Built

**1. Shared Capital API Client** (`src/capital_client.py`)
- ✅ Reusable authentication with 55-min token caching
- ✅ Session pooling with automatic retries
- ✅ Used by BOTH production trading AND backtesting
- ✅ Test with: `python3 src/capital_client.py`

**2. Data Caching Script** (`src/cache_data.py`)
- ✅ Fetches from Capital.com API
- ✅ Saves to `data/` directory as CSV
- ✅ 24-hour cache TTL
- ✅ Handles 1000-bar API limit with pagination

**3. Backtest Runner** (`src/run_backtest_from_cache.py`)
- ✅ Uses ONLY cached data (no API calls during backtest)
- ✅ Runs strategy with realistic spreads/slippage
- ✅ Exports JSON for dashboard UI
- ✅ Shows detailed performance metrics

**4. Production Code** (`main.py`)
- ✅ Updated to use shared `capital_client`
- ✅ Same authentication logic as backtesting
- ✅ No code duplication

---

## 🚀 Usage Workflow

### Step 1: Configure Credentials (One-Time)
```bash
# Interactive setup (recommended)
python3 setup_local_env.py

# OR manually copy and edit
cp .env.example .env
# Edit .env and add your Capital.com credentials
```

### Step 2: Cache Historical Data
```bash
python3 src/cache_data.py
```
**Output:**
- Fetches GOLD M15 (2000 bars)
- Fetches GOLD M5 (3000 bars)
- Fetches EURUSD M15 (2000 bars)
- Saves as CSV in `data/` directory
- **Duration:** ~10-15 seconds for first run, instant thereafter  

### Step 3: Run Backtest
```bash
python3 src/run_backtest_from_cache.py
```
**Output:**
- Loads from cache (no API calls!)
- Runs strategy with indicators
- Calculates performance metrics
- **Exports:** `data/backtest_results.json` for dashboard

---

## 📊 Dashboard Integration

The backtest exports JSON in this format:

```json
{
  "instrument": "GOLD",
  "timeframe": "M15",
  "timestamp": "2026-03-04T20:30:00",
  "performance": {
    "initial_capital": 10000.0,
    "final_capital": 12500.0,
    "total_pnl": 2500.0,
    "total_return_pct": 25.0
  },
  "trades": {
    "total": 45,
    "wins": 28,
    "losses": 17,
    "win_rate": 62.2
  },
  "pnl": {
    "gross_profit": 4200.0,
    "gross_loss": -1700.0,
    "avg_win": 150.0,
    "avg_loss": -100.0,
    "profit_factor": 2.47
  },
  "risk": {
    "max_drawdown_pct": 12.5,
    "sharpe_ratio": 1.85,
    "calmar_ratio": 2.0
  },
  "costs": {
    "total_transaction_costs": 112. 50,
    "cost_per_trade": 2.50
  },
  "trades_sample": [...]  // First 10 trades with details
}
```

**Use this JSON in your dashboard UI to display:**
- Equity curve chart
- Trade history table
- Performance metrics cards
- Risk analysis graphs

---

## 📁 File Structure

```
cloud-function/
├── .env                          # Your credentials (create this!)
├── .env.example                  # Template
├── setup_local_env.py            # Interactive setup
├── main.py                       # Production (uses shared client)
├── src/
│   ├── capital_client.py         # ✅ SHARED authentication
│   ├── cache_data.py             # ✅ Fetch & cache
│   ├── run_backtest_from_cache.py # ✅ Backtest from cache
│   ├── strategy.py               # Strategy implementation
│   ├── backtester.py             # Backtest engine
│   ├── market_data.py            # Spread fetching
│   └── ...
├── data/                         # CSV cache (created by cache_data.py)
│   ├── GOLD_M15_2000bars.csv
│   ├── GOLD_M5_3000bars.csv
│   ├── EURUSD_M15_2000bars.csv
│   └── backtest_results.json     # Dashboard data
└── docs/
    └── BACKTEST_QUICKSTART.md    # Full documentation
```

---

## 🎯 Benefits of This Approach

✅ **No Code Duplication:** `capital_client.py` used everywhere
✅ **Efficient:** Cache data once, run backtests instantly
✅ **Separated Concerns:** Fetch vs Backtest vs Analytics
✅ **Dashboard Ready:** JSON export for UI integration
✅ **Production Safe:** Same auth logic in prod & backtest

---

## 💡 Next Steps

1. **Configure credentials** (if not done):
   ```bash
   python3 setup_local_env.py
   ```

2. **Test authentication**:
   ```bash
   python3 src/capital_client.py
   ```

3. **Cache data**:
   ```bash
   python3 src/cache_data.py
   ```

4. **Run backtest**:
   ```bash
   python3 src/run_backtest_from_cache.py
   ```

5. **Use JSON in dashboard:**
   - Load `data/backtest_results.json`
   - Display metrics, charts, tables
   - Refresh by re-running backtest

---

## 🔧 Troubleshooting

**"No credentials found"**
→ Run `python3 setup_local_env.py`

**"❌ Cache not found"**
→ Run `python3 src/cache_data.py` first

**"Authentication failed"**
→ Check credentials in `.env` file
→ Verify using demo account (not live)

**"API error 404"**
→ Instrument name might be wrong (use 'GOLD' not 'XAUUSD')

---

**Status:** ✅ Ready to use!  
**Next:** Configure credentials and run first backtest
