# Strategy Optimization API

Complete REST API for running and analyzing trading strategy optimizations with a modern web dashboard.

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip3 install -r requirements.txt
```

### 2. Start API Server

```bash
python3 api_server.py
```

The server will start on `http://localhost:8000`

### 3. Access Dashboard

Open your browser: **http://localhost:8000**

Or use the interactive API docs: **http://localhost:8000/docs**

## 📊 Features

- **Web Dashboard**: Modern UI for managing optimizations
- **Async Execution**: Run optimizations in background
- **Real-time Status**: Track optimization progress
- **Run History**: View all past optimization runs
- **Detailed Analysis**: Comprehensive results analysis
- **RESTful API**: Full API for integration

## 🔌 API Endpoints

### Health & Info

#### `GET /health`
Check API health status

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2026-03-05T12:00:00",
  "active_runs": 0
}
```

### Optimization

#### `POST /api/optimize`
Start new optimization run

**Request Body:**
```json
{
  "instrument": "GOLD",
  "timeframe": "M5",
  "mode": "quick",
  "initial_capital": 10000.0,
  "position_size": 10.0,
  "pip_values": [1.5, 2.0, 2.5, 3.0, 5.0],
  "parallel": true,
  "n_jobs": -1
}
```

**Response:**
```json
{
  "run_id": "run_20260305_120000_abc123",
  "status": "queued",
  "message": "Optimization started",
  "check_status": "/api/optimize/status/run_20260305_120000_abc123"
}
```

#### `GET /api/optimize/status/{run_id}`
Get optimization run status

**Response:**
```json
{
  "run_id": "run_20260305_120000_abc123",
  "status": "running",
  "started_at": "2026-03-05T12:00:00",
  "completed_at": null,
  "progress": {"current": 1200, "total": 2340},
  "config": {...}
}
```

**Status values:** `queued`, `running`, `completed`, `failed`

#### `GET /api/optimize/history`
Get list of all optimization runs

**Query Parameters:**
- `limit` (default: 20): Number of runs to return
- `skip` (default: 0): Number of runs to skip

**Response:**
```json
{
  "total": 45,
  "limit": 20,
  "skip": 0,
  "runs": [
    {
      "run_id": "run_20260305_120000_abc123",
      "date": "2026-03-05",
      "timestamp": "2026-03-05T12:00:00",
      "instrument": "GOLD",
      "timeframe": "M5",
      "status": "completed",
      "total_combinations": 2340,
      "best_return": 35.33,
      "best_profit": 3532.60
    }
  ]
}
```

#### `GET /api/optimize/results/{run_id}`
Get detailed results for specific run

**Query Parameters:**
- `top_n` (default: 20): Number of top strategies to return

**Response:**
```json
{
  "run_id": "run_20260305_120000_abc123",
  "summary": {...},
  "top_strategies": [
    {
      "rank": 1,
      "strategy_name": "rank01_ST2.0_SMA15-50_BB2.0_PIP2_F20-75",
      "return_pct": 35.33,
      "total_pnl": 3532.60,
      "sharpe_ratio": 0.83,
      "win_rate": 75.0,
      "total_trades": 4,
      "profit_factor": 8.06,
      "max_drawdown_pct": 12.13
    }
  ],
  "total_strategies": 2340
}
```

#### `DELETE /api/optimize/{run_id}`
Delete optimization run

**Response:**
```json
{
  "message": "Run deleted successfully",
  "deleted_path": "/path/to/run"
}
```

### Analysis

#### `GET /api/analyze/{run_id}`
Get comprehensive analysis for specific run

**Response:**
```json
{
  "run_id": "run_20260305_120000_abc123",
  "date": "2026-03-05",
  "instrument": "GOLD",
  "timeframe": "M5",
  "total_combinations": 2340,
  "best_strategy": {
    "strategy_name": "rank01_ST2.0_SMA15-50_BB2.0_PIP2_F20-75",
    "return_pct": 35.33,
    "total_pnl": 3532.60,
    "sharpe_ratio": 0.83,
    "win_rate": 75.0,
    "total_trades": 4,
    "profit_factor": 8.06
  },
  "pip_value_analysis": {
    "1.5": {
      "count": 468,
      "profitable": 279,
      "profitable_pct": 59.6,
      "avg_profit": 403.49,
      "max_profit": 3282.60
    }
  },
  "strategy_type_comparison": {
    "fixed": {"count": 1620, "avg_profit": -472.21},
    "atr": {"count": 720, "avg_profit": -1562.75}
  },
  "risk_metrics": {
    "profitability_rate": 31.2,
    "avg_drawdown": 23.84,
    "worst_drawdown": 52.72
  }
}
```

#### `GET /api/analyze/latest`
Get analysis for most recent run

Same response format as `/api/analyze/{run_id}`

### Statistics

#### `GET /api/stats/summary`
Get overall statistics across all runs

**Response:**
```json
{
  "total_runs": 45,
  "total_strategies_tested": 105300,
  "best_return_ever": 35.33,
  "best_profit_ever": 3532.60,
  "best_run": "run_20260305_120000_abc123",
  "recent_runs": [...]
}
```

## 🖥️ Using the API

### Python Client

```python
from test_api import OptimizationAPIClient

client = OptimizationAPIClient()

# Start optimization
result = client.start_optimization(
    instrument="GOLD",
    timeframe="M5",
    position_size=10.0,
    pip_values=[1.5, 2.0, 2.5, 3.0, 5.0]
)
print(f"Started: {result['run_id']}")

# Check status
status = client.get_status(result['run_id'])
print(f"Status: {status['status']}")

# Wait for completion
final_status = client.wait_for_completion(result['run_id'])

# Get analysis
if final_status['status'] == 'completed':
    analysis = client.get_analysis(result['run_id'])
    print(f"Best profit: ${analysis['best_strategy']['total_pnl']:.2f}")
```

### cURL Examples

```bash
# Health check
curl http://localhost:8000/health

# Start optimization
curl -X POST http://localhost:8000/api/optimize \
  -H "Content-Type: application/json" \
  -d '{
    "instrument": "GOLD",
    "timeframe": "M5",
    "position_size": 10.0,
    "mode": "quick"
  }'

# Check status
curl http://localhost:8000/api/optimize/status/run_20260305_120000_abc123

# Get history
curl http://localhost:8000/api/optimize/history?limit=10

# Get analysis
curl http://localhost:8000/api/analyze/latest

# Get results
curl http://localhost:8000/api/optimize/results/latest?top_n=10

# Delete run
curl -X DELETE http://localhost:8000/api/optimize/{run_id}
```

### JavaScript/Fetch

```javascript
// Start optimization
const response = await fetch('http://localhost:8000/api/optimize', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    instrument: 'GOLD',
    timeframe: 'M5',
    position_size: 10.0,
    mode: 'quick'
  })
});
const data = await response.json();
console.log('Run ID:', data.run_id);

// Get latest analysis
const analysis = await fetch('http://localhost:8000/api/analyze/latest')
  .then(r => r.json());
console.log('Best profit:', analysis.best_strategy.total_pnl);
```

## 🧪 Testing

### Test All Endpoints

```bash
python3 test_api.py
```

### Quick Analysis

```bash
python3 test_api.py quick
```

### Test from Browser

1. Open http://localhost:8000/docs
2. Try out each endpoint interactively
3. View request/response schemas

## 📁 File Structure

```
cloud-function/
├── api_server.py           # FastAPI server
├── test_api.py            # Test client & examples
├── analyze_results.py     # CLI analysis tool
├── static/
│   └── dashboard.html     # Web dashboard
├── src/
│   └── optimization/
│       └── optimize_strategy.py  # Core optimizer
└── data/
    └── optimization/      # Results storage
        ├── latest/        # Symlink to latest run
        └── 2026-03-05/   # Run directories by date
```

## 🔧 Configuration

### Environment Variables

```bash
# API Server
export API_HOST=0.0.0.0
export API_PORT=8000

# Optimization defaults
export INITIAL_CAPITAL=10000
export POSITION_SIZE=10.0
export N_JOBS=-1
```

### CORS Configuration

By default, CORS is enabled for all origins. For production:

```python
# In api_server.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],  # Specific origins
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)
```

## 📊 Web Dashboard Features

### Overview Tab
- Overall statistics
- Latest run summary
- Best strategy ever
- Recent runs table

### Run Optimization Tab
- Configure optimization parameters
- Start new optimization runs
- Monitor run status

### History Tab
- View all past runs
- Sort and filter results
- Delete old runs

### Analysis Tab
- Detailed performance analysis
- pip_value comparison
- Strategy type comparison
- Risk metrics

## ⚡ Performance

- **Parallel Processing**: Uses all CPU cores by default
- **Background Execution**: API responds immediately
- **Efficient Storage**: Results stored in optimized CSV/JSON
- **Fast Queries**: In-memory caching for recent runs

## 🚀 Production Deployment

### Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000"]
```

### systemd Service

```ini
[Unit]
Description=Strategy Optimization API
After=network.target

[Service]
Type=simple
User=trader
WorkingDirectory=/opt/strategy-optimizer
ExecStart=/usr/bin/python3 api_server.py
Restart=always

[Install]
WantedBy=multi-user.target
```

### Nginx Reverse Proxy

```nginx
server {
    listen 80;
    server_name optimizer.yourdomain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 🔒 Security Considerations

1. **Authentication**: Add API key or JWT authentication
2. **Rate Limiting**: Implement rate limiting for public APIs
3. **CORS**: Restrict origins in production
4. **Input Validation**: Already implemented via Pydantic models
5. **File Access**: Results stored in controlled directory

## 📈 Monitoring

Monitor these metrics in production:

- Active optimization runs
- API response times
- Error rates
- Storage usage
- CPU/Memory utilization

## 🐛 Troubleshooting

### API won't start
```bash
# Check if port is in use
lsof -i :8000

# Use different port
uvicorn api_server:app --port 8001
```

### Optimization fails
```bash
# Check optimizer directly
python3 src/optimization/optimize_strategy.py

# View logs
tail -f logs/optimizer.log
```

### No results showing
```bash
# Verify data directory
ls -la data/optimization/latest/

# Check symlink
ls -la data/optimization/
```

## 📚 Additional Resources

- **Interactive API Docs**: http://localhost:8000/docs
- **ReDoc Documentation**: http://localhost:8000/redoc
- **CLI Analysis Tool**: `python3 analyze_results.py --help`
- **Test Client**: `python3 test_api.py`

## 🎯 Next Steps

1. Add authentication/authorization
2. Implement WebSocket for real-time progress
3. Add result visualization/charts
4. Implement optimization presets
5. Add email notifications on completion
6. Create mobile-responsive dashboard
7. Add comparison between runs
8. Export results to Excel/PDF

## 💡 Tips

- Use `mode="quick"` for testing (2-3 minutes)
- Use `mode="full"` for production (10-15 minutes)
- Monitor `/health` endpoint for system status
- Use `test_api.py` for integration testing
- Check `/docs` for latest API schema

---

**Version**: 1.0.0  
**Last Updated**: March 5, 2026  
**License**: MIT
