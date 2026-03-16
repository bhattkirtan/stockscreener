# Strategy Optimization API - Complete Guide

## 🎯 Overview

You have **TWO separate services**:

1. **`main.py`** = Google Cloud Function for Capital.com trading
2. **`api_server.py`** = FastAPI server for strategy optimization (THIS API)

## 🚀 Start the API Server

```bash
cd cloud-function
python3 api_server.py
```

Server runs on: **http://localhost:8000**

- Dashboard: http://localhost:8000
- API Docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

## 📡 Key API Endpoints

### Start Optimization
```bash
curl -X POST http://localhost:8000/api/optimize \
  -H "Content-Type: application/json" \
  -d '{
    "instrument": "GOLD",
    "timeframe": "M5",
    "mode": "quick",
    "initial_capital": 10000,
    "position_size": 10.0
  }'
```

### Check Status
```bash
curl http://localhost:8000/api/optimize/status/{run_id}
```

### View History
```bash
curl http://localhost:8000/api/optimize/history
```

### Get Results
```bash
curl http://localhost:8000/api/optimize/results/latest?top_n=10
```

### Analyze Results
```bash
curl http://localhost:8000/api/analyze/latest
```

### Cancel Running Optimization
```bash
curl -X POST http://localhost:8000/api/optimize/{run_id}/cancel
```

### Delete Old Run
```bash
curl -X DELETE http://localhost:8000/api/optimize/{run_id}
```

## 🧪 Test It

```bash
python3 test_api_client.py
```

## 🔧 Parameters You Can Control

| Parameter | Default | Options |
|-----------|---------|---------|
| instrument | GOLD | GOLD, EURUSD, etc |
| timeframe | M5 | M5, M15, H1, etc |
| mode | quick | quick, medium, full |
| initial_capital | 10000 | Any number |
| position_size | 10.0 | 1.0-20.0 lots |
| parallel | true | true/false |
| n_jobs | -1 | -1 (all cores) or specific count |

## 📊 What You Get Back

### Best Strategy
- Strategy name
- Profit in dollars
- Return percentage
- Win rate
- Sharpe ratio
- Max drawdown

### Analysis
- pip_value comparison
- Fixed vs ATR strategies
- Risk metrics
- Top 10/20/50 strategies

## 🎯 Full Workflow Example

```python
import requests
import time

# 1. Start
response = requests.post("http://localhost:8000/api/optimize", json={
    "instrument": "GOLD",
    "position_size": 10.0,
    "mode": "quick"
})
run_id = response.json()["run_id"]

# 2. Wait
while True:
    status = requests.get(f"http://localhost:8000/api/optimize/status/{run_id}").json()
    if status["status"] == "completed":
        break
    print(f"Status: {status['status']}")
    time.sleep(5)

# 3. Get Results
results = requests.get(f"http://localhost:8000/api/optimize/results/{run_id}?top_n=5").json()
for strat in results["top_strategies"]:
    print(f"{strat['rank']}. {strat['strategy_name']}")
    print(f"   Profit: ${strat['total_pnl']:.2f} ({strat['return_pct']:.2f}%)")
```

## 🆘 Troubleshooting

**Port already in use:**
```bash
lsof -i :8000
kill -9 <PID>
```

**Can't connect:**
Make sure server is running: `python3 api_server.py`

**Optimization fails:**
Check data files exist in `data/` folder

