# Trading Bot - Skill-Based Architecture

Modular, maintainable trading bot for Capital.com with skill-based design for testability and scalability.

## 🎯 Purpose

Refactor monolithic `trading_bot.py` (~900 lines) into modular skills (~200 lines each) for:
- **Better Testing**: Mock individual skills in isolation
- **Easier Maintenance**: Clear separation of concerns
- **Parallel Development**: Teams work on different skills independently
- **Reusability**: Use skills across multiple bots (GOLD, EURUSD, etc.)

---

## 📁 Project Structure

```
trading-bot-skills/
├── orchestrator/           # Central controller
│   ├── main.py            # Bot entry point
│   └── trading_orchestrator.py
├── skills/                # Domain-specific modules
│   ├── market_data/       # Fetch OHLC, WebSocket
│   ├── analysis/          # Indicators, signals
│   ├── execution/         # Place orders, manage positions
│   ├── risk/              # Cooldown, position sizing
│   ├── storage/           # Firestore persistence
│   ├── monitoring/        # P&L, health checks
│   ├── alerting/          # Telegram, email alerts
│   ├── backtesting/       # Strategy simulation
│   └── reporting/         # Performance reports
├── config/                # YAML configuration
├── tests/                 # Unit & integration tests
└── docs/                  # Architecture docs
```

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
cd /Users/kirtanbhatt/code/stockScreener/trading-bot-skills
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Bot
```bash
cp config/trading_config.yaml.example config/trading_config.yaml
# Edit config with your Capital.com credentials
```

### 3. Run Backtest
```bash
python orchestrator/main.py --mode backtest --data data/GOLD_M5.csv
```

### 4. Run Live Bot
```bash
python orchestrator/main.py --mode live --config config/trading_config.yaml
```

---

## 🧩 Skills Overview

### Core Skills

| Skill | Purpose | Key Files |
|-------|---------|-----------|
| **Market Data** | Fetch OHLC, WebSocket | `market_data_skill.py`, `websocket_client.py` |
| **Analysis** | Calculate indicators, generate signals | `analysis_skill.py`, `indicators.py` |
| **Execution** | Place orders via Capital.com API | `execution_skill.py`, `order_manager.py` |
| **Risk** | Cooldown logic, position sizing | `risk_skill.py`, `cooldown_manager.py` |
| **Storage** | Firestore persistence | `storage_skill.py`, `firestore_client.py` |
| **Monitoring** | P&L tracking, health checks | `monitoring_skill.py`, `pnl_tracker.py` |
| **Alerting** | Telegram/email notifications | `alerting_skill.py`, `telegram_notifier.py` |
| **Backtesting** | Simulate strategy on historical data | `backtesting_skill.py`, `simulator.py` |
| **Reporting** | Generate performance reports | `reporting_skill.py`, `chart_generator.py` |

---

## 🔄 Data Flow

### Live Trading Flow
```
WebSocket Tick → Market Data → Analysis → Risk Validation → Execution → Storage → Alerting
```

1. **Market Data** receives candle from WebSocket
2. **Analysis** calculates Supertrend, SMA, BB → generates BUY/SELL signal
3. **Risk** validates signal (cooldown, position size, drawdown limits)
4. **Execution** places order via Capital.com API
5. **Storage** saves position to Firestore
6. **Monitoring** updates P&L metrics
7. **Alerting** sends Telegram notification

### Backtest Flow
```
Historical Data → Analysis → Risk → Backtesting (Simulate) → Reporting (Metrics)
```

---

## 🛠️ Configuration

### Example: `config/trading_config.yaml`
```yaml
market_data:
  instrument: GOLD
  timeframe: M5

analysis:
  supertrend_multiplier: 2.0
  sma_fast: 25
  sma_slow: 30

risk:
  sl_cooldown_minutes: 15  # Wait 15min after SL before same-direction trade
  tp_cooldown_minutes: 5   # Wait 5min after TP
  position_size_pct: 2.0

execution:
  mode: AUTO  # AUTO or SIGNAL_ONLY
  sl_pips: 20
  tp_pips: 40
```

---

## 🧪 Testing

### Run Unit Tests (All Skills)
```bash
pytest tests/unit/
```

### Run Integration Tests
```bash
pytest tests/integration/
```

### Run Specific Skill Tests
```bash
pytest tests/unit/test_risk_skill.py -v
```

### Run Backtest with Validation
```bash
python orchestrator/main.py --mode backtest --validate-against-baseline
```

---

## 📊 Key Features

### 1. **Cooldown System** (Risk Skill)
Prevents duplicate trades after SL/TP hits:
- **15 minutes after SL hit** - Thesis was wrong, wait longer
- **5 minutes after TP hit** - Quick re-entry okay
- **Direction-specific** - Only blocks same direction, allows reversals

### 2. **Signal Edge Detection** (Analysis Skill)
Only trades on signal transitions:
- Tracks `last_signal_state` (None, BUY, SELL)
- Only opens position when signal changes (e.g., None → BUY)
- Prevents continuous re-entry on unchanged conditions

### 3. **Firestore Persistence** (Storage Skill)
Robust position tracking:
- Always closes Firestore position (even on API errors)
- Uses `finally` block to ensure cleanup
- Logs SL_HIT, TP_HIT, SIGNAL close reasons

### 4. **Performance Monitoring** (Monitoring Skill)
Real-time metrics:
- P&L tracking (daily, total)
- Win rate, profit factor
- Max drawdown, Sharpe ratio
- API latency monitoring

---

## 📈 Backtest Results (Current Strategy)

**Strategy:** SupertrendVWAP 2.0, SMA 25/30, BB 2.0, SL20/TP40  
**Data:** 149,987 bars GOLD M5 (Jan 2024 - Mar 2026)  
**Capital:** $10,000

| Metric | Without Cooldown | With Cooldown | Improvement |
|--------|------------------|---------------|-------------|
| Total Trades | 3,595 | 1,816 | **-49.5%** |
| Win Rate | 37.25% | 41.57% | **+4.3%** |
| Sharpe Ratio | 0.178 | 0.253 | **+42%** |
| Max Drawdown | -$2,456 | -$1,517 | **-38%** |
| Expectancy | $10.27 | $18.07 | **+76%** |

**Conclusion:** Cooldown system significantly improves risk-adjusted returns by filtering out low-quality trades.

---

## 🧑‍💻 Development Workflow

### Add New Skill
1. Create folder: `skills/my_new_skill/`
2. Implement `MyNewSkill` class extending `Skill` base class
3. Add configuration in `config/trading_config.yaml`
4. Write unit tests in `tests/unit/test_my_new_skill.py`
5. Register skill in `orchestrator/trading_orchestrator.py`

### Modify Existing Skill
1. Edit skill files in `skills/{skill_name}/`
2. Update tests if behavior changed
3. Run tests: `pytest tests/unit/test_{skill_name}.py`
4. Run backtest to validate: `python orchestrator/main.py --mode backtest`

### Deploy to Production
```bash
# Test locally first
pytest tests/
python orchestrator/main.py --mode backtest

# Deploy to server
scp -r trading-bot-skills/ root@204.168.191.150:/opt/
ssh root@204.168.191.150
cd /opt/trading-bot-skills
source venv/bin/activate
python orchestrator/main.py --mode live --config config/production.yaml
```

---

## 📝 Migration Plan

**Goal:** Migrate from monolithic `trading_bot.py` to skill-based architecture

| Phase | Task | Status |
|-------|------|--------|
| 1 | Design architecture | ✅ Complete |
| 2 | Create folder structure | ✅ Complete |
| 3 | Extract Market Data Skill | ⏳ Not Started |
| 4 | Extract Analysis Skill | ⏳ Not Started |
| 5 | Extract Execution Skill | ⏳ Not Started |
| 6 | Extract Risk Skill (cooldown) | ⏳ Not Started |
| 7 | Extract Storage Skill (Firestore) | ⏳ Not Started |
| 8 | Build Orchestrator | ⏳ Not Started |
| 9 | Write tests | ⏳ Not Started |
| 10 | Backtest validation | ⏳ Not Started |
| 11 | Deploy to production | ⏳ Not Started |

---

## 🔗 Related Documentation

- [Architecture Details](docs/ARCHITECTURE.md) - Full architecture explanation
- [Current Bot Fixes](../cloud-function/README.md) - Cooldown + Firestore fixes deployed
- [Backtest Results](../cloud-function/STRATEGY_COMPARISON_30vs15_TP.md) - Performance analysis

---

## 🐛 Known Issues

- [ ] Need to implement base `Skill` abstract class
- [ ] Need to define shared `Context` data structure
- [ ] Need to decide on event system (direct calls vs pub/sub)
- [ ] Need to migrate existing cooldown logic from `trading_bot.py`

---

## 🤝 Contributing

1. Pick a skill from Migration Plan
2. Create feature branch: `git checkout -b feature/market-data-skill`
3. Implement skill with tests
4. Run tests: `pytest tests/unit/test_market_data_skill.py`
5. Submit PR for review

---

## 📧 Contact

For questions or issues, check:
- [Deployment Checklist](../cloud-function/DEPLOYMENT_CHECKLIST.md)
- [Strategy Status](../cloud-function/STRATEGY_STATUS.md)
- Server logs: `ssh root@204.168.191.150 tail -f /tmp/bot.log`

---

## 📜 License

Private project - not for public distribution
