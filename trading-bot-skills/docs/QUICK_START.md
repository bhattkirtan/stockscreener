# Quick Start Guide

Get the skill-based trading bot running in 5 minutes.

## 1. Install Dependencies

```bash
cd /Users/kirtanbhatt/code/stockScreener/trading-bot-skills

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

## 2. Test Risk Skill (Already Implemented)

```bash
# Run the example in risk_skill.py
python skills/risk/risk_skill.py
```

**Expected Output:**
```
Test 1: BUY signal, no cooldown
  Allowed: True, Reason: Risk validation passed

Test 2: Close position with SL_HIT
📝 Updated last closed position: BUY closed at SL_HIT

Test 3: BUY signal, within SL cooldown
  Allowed: False, Reason: 🚫 SL cooldown: 0.0m < 15m

Test 4: SELL signal, opposite direction
  Allowed: True, Reason: Risk validation passed

Test 5: BUY signal after 15 minutes
  Allowed: True, Reason: ✅ SL cooldown passed: 16.0m
```

## 3. Run Unit Tests

```bash
# Install test dependencies
pip install pytest pytest-asyncio

# Run risk skill tests
pytest tests/unit/test_risk_skill.py -v
```

**Expected Output:**
```
tests/unit/test_risk_skill.py::TestCooldownLogic::test_no_cooldown_on_first_trade PASSED
tests/unit/test_risk_skill.py::TestCooldownLogic::test_sl_cooldown_blocks_same_direction PASSED
tests/unit/test_risk_skill.py::TestCooldownLogic::test_sl_cooldown_allows_opposite_direction PASSED
...
========================= 15 passed in 0.05s =========================
```

## 4. Run Orchestrator Demo

```bash
# Run orchestrator example
python orchestrator/trading_orchestrator.py
```

**Expected Output:**
```
✅ Registered skill: risk
🚀 Orchestrator started at 2024-01-15 10:30:00

--- Candle 1: BUY Signal ---
Signal allowed: True, Reason: Risk validation passed

--- Position Closed: SL_HIT ---
📝 Updated last closed position: BUY closed at SL_HIT
🔴 Position closed: DEAL123, SL_HIT, P&L: $-20.00

--- Candle 2: BUY Signal (immediate) ---
Signal allowed: False, Reason: 🚫 SL cooldown: 0.0m < 15m

--- Candle 3: SELL Signal (opposite) ---
Signal allowed: True, Reason: Different direction - cooldown bypassed

🛑 Orchestrator stopped
📊 Session Stats:
  Runtime: 0.0 minutes
  Total signals: 0
  Total trades: 0
✅ Bot stopped successfully
```

## 5. Try Main Entry Point

```bash
# Run main.py (configuration required)
python orchestrator/main.py --mode demo --config config/trading_config.yaml
```

**Expected Output:**
```
📄 Loading configuration from config/trading_config.yaml
🔧 Registering skills...
✅ Registered skill: risk

🚀 Starting bot in DEMO mode...
📝 Running in DEMO mode (paper trading)
⚠️ Demo mode not yet implemented
```

---

## Next Steps

### Verify Setup
✅ Dependencies installed  
✅ Risk skill working  
✅ Tests passing  
✅ Orchestrator running  

### Start Development
Choose one:
1. **Implement Market Data Skill** - Fetch OHLC data
2. **Implement Analysis Skill** - Calculate indicators
3. **Implement Execution Skill** - Place orders
4. **Add More Tests** - Increase coverage

### Read Documentation
- [README.md](README.md) - Project overview
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) - Architecture details
- [MIGRATION_GUIDE.md](docs/MIGRATION_GUIDE.md) - Migration steps

---

## Troubleshooting

### Import Errors
```bash
# Make sure you're in the right directory
cd /Users/kirtanbhatt/code/stockScreener/trading-bot-skills

# Check Python path
python -c "import sys; print(sys.path)"
```

### Config Not Found
```bash
# Verify config file exists
ls -la config/trading_config.yaml

# Check YAML syntax
python -c "import yaml; yaml.safe_load(open('config/trading_config.yaml'))"
```

### Test Failures
```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-mock

# Run with verbose output
pytest tests/unit/test_risk_skill.py -v -s
```

---

## What's Working Now?

✅ **Base Infrastructure**
- Skill abstract base class
- Context data structure
- Orchestrator skeleton

✅ **Risk Skill (Fully Implemented)**
- 15min SL cooldown
- 5min TP cooldown
- Direction-specific blocking
- Signal validation
- 15 unit tests passing

✅ **Test Framework**
- pytest configured
- Unit tests working
- Test fixtures ready

⏳ **Not Yet Implemented**
- Market Data Skill
- Analysis Skill
- Execution Skill
- Storage Skill
- Monitoring Skill
- Alerting Skill
- Full orchestrator event loop

---

## Development Workflow

1. **Pick a skill** from [MIGRATION_GUIDE.md](docs/MIGRATION_GUIDE.md)
2. **Write tests first** (TDD approach)
3. **Implement skill** in `skills/{skill_name}/`
4. **Run tests** `pytest tests/unit/test_{skill_name}.py`
5. **Integrate** with orchestrator
6. **Backtest** to validate

---

## Questions?

Check these resources:
- [Architecture Diagram](docs/ARCHITECTURE.md#architecture-principles)
- [Current Bot Code](../scripts/trading_bot.py) - Reference implementation
- [Backtest Results](../cloud-function/STRATEGY_COMPARISON_30vs15_TP.md)
- Server Logs: `ssh root@204.168.191.150 tail -f /tmp/bot.log`

**Ready to start? Pick a skill and start coding! 🚀**
