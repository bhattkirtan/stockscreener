# Migration Guide: Monolithic Bot → Skill-Based Architecture

Step-by-step guide to migrate from `trading_bot.py` (~900 lines) to modular skill-based architecture.

---

## Prerequisites

- [ ] Current `trading_bot.py` is stable and working in production
- [ ] All tests pass for current implementation
- [ ] Backtest results documented as baseline
- [ ] Production bot is running and monitored

---

## Migration Strategy

**Approach:** Gradual extraction (strangler pattern)

- Extract one skill at a time
- Keep old `trading_bot.py` running in production
- Test new skill-based version in parallel
- Switch when confidence is high

**Do NOT:** Rewrite everything from scratch

---

## Phase 1: Foundation (Week 1)

### 1.1 Set Up Project Structure ✅ COMPLETE
- [x] Create `trading-bot-skills/` folder
- [x] Create skills folders (market_data, analysis, execution, risk, etc.)
- [x] Create base_skill.py with Skill abstract class
- [x] Create Context data structure
- [x] Create trading_orchestrator.py skeleton
- [x] Create trading_config.yaml

### 1.2 Write Tests First
- [ ] Create test fixtures in `tests/conftest.py`
- [ ] Write integration test for simple flow (candle → signal → validate)
- [ ] Define expected behavior (what should pass/fail)

### 1.3 Set Up CI/CD
- [ ] Add GitHub Actions workflow to run tests
- [ ] Add linting (flake8, black)
- [ ] Add type checking (mypy)

---

## Phase 2: Extract Market Data Skill (Week 2)

### 2.1 Identify Code to Extract
From `trading_bot.py`:
- Line ~150-200: WebSocket client initialization
- Line ~300-350: Candle buffering logic
- Line ~400-450: REST API historical data fetch

### 2.2 Create Market Data Skill
```python
# skills/market_data/market_data_skill.py
class MarketDataSkill(Skill):
    async def execute(self, context):
        # Buffer candle
        # Update context.candle_history
        return context
```

### 2.3 Write Tests
```python
# tests/unit/test_market_data_skill.py
async def test_candle_buffering():
    skill = MarketDataSkill(config)
    context = Context(current_candle={...})
    result = await skill.execute(context)
    assert len(result.candle_history) == 1
```

### 2.4 Integration Test
- [ ] Test WebSocket connection
- [ ] Test candle parsing
- [ ] Test buffer size limit (e.g., max 100 candles)

---

## Phase 3: Extract Analysis Skill (Week 3)

### 3.1 Identify Code to Extract
From `trading_bot.py`:
- Line ~500-600: Indicator calculations (Supertrend, SMA, BB)
- Line ~650-700: Signal generation logic
- Line ~750-800: Signal validation

### 3.2 Create Analysis Skill
```python
# skills/analysis/analysis_skill.py
class AnalysisSkill(Skill):
    async def execute(self, context):
        # Calculate indicators
        indicators = self.calculate_indicators(context.candle_history)
        
        # Generate signal
        signal = self.generate_signal(indicators)
        
        context.indicators = indicators
        context.signal = signal
        return context
```

### 3.3 Extract Indicators Module
```python
# skills/analysis/indicators.py
def calculate_supertrend(df, period=10, multiplier=2.0):
    # Existing Supertrend code
    return st_direction

def calculate_sma(df, period=25):
    # Existing SMA code
    return sma
```

### 3.4 Write Tests
- [ ] Test Supertrend calculation (known input → expected output)
- [ ] Test SMA crossover detection
- [ ] Test signal generation (bullish conditions → BUY signal)
- [ ] Test edge detection (continuous signal → no duplicate)

---

## Phase 4: Extract Risk Skill (Week 3-4) ✅ READY

### 4.1 Migrate Cooldown Logic
**Already implemented in `skills/risk/risk_skill.py`**

Copy from `trading_bot.py`:
- Line 191-195: Cooldown state variables ✅
- Line 499-536: Cooldown check logic ✅
- Line 859-873: Track close_reason (SL_HIT, TP_HIT) ✅

### 4.2 Add Position Sizing
```python
def _calculate_position_size(self, context):
    # Kelly Criterion or fixed percentage
    capital = 10000  # Get from context
    risk_pct = self.position_size_pct / 100
    position_size = capital * risk_pct / sl_pips
    return position_size
```

### 4.3 Add Drawdown Check
```python
def _check_drawdown_limit(self, context):
    current_dd = context.monitoring.max_drawdown_pct
    if current_dd > self.max_drawdown_pct:
        return False
    return True
```

### 4.4 Tests ✅ COMPLETE
- [x] Test cooldown logic (already in `tests/unit/test_risk_skill.py`)
- [ ] Test position sizing
- [ ] Test drawdown limit

---

## Phase 5: Extract Execution Skill (Week 4)

### 5.1 Identify Code to Extract
From `trading_bot.py`:
- Line ~600-650: place_order() method
- Line ~700-750: close_position() method
- Line ~800-850: check_position_status() method

### 5.2 Create Execution Skill
```python
# skills/execution/execution_skill.py
class ExecutionSkill(Skill):
    async def execute(self, context):
        if not context.is_allowed:
            return context  # Risk blocked this signal
        
        # Place order via Capital.com API
        deal_id = await self.order_manager.place_market_order(
            direction=context.signal,
            size=context.position_size,
            sl_pips=self.config['sl_pips'],
            tp_pips=self.config['tp_pips']
        )
        
        context.deal_id = deal_id
        return context
```

### 5.3 Extract Order Manager
```python
# skills/execution/order_manager.py
class OrderManager:
    def __init__(self, api_client):
        self.api_client = api_client
    
    async def place_market_order(self, direction, size, sl_pips, tp_pips):
        # Existing order placement logic
        return deal_id
```

### 5.4 Write Tests
- [ ] Mock Capital.com API
- [ ] Test order placement (signal → API call)
- [ ] Test error handling (400 error → retry?)
- [ ] Test SL/TP calculation

---

## Phase 6: Extract Storage Skill (Week 5)

### 6.1 Identify Code to Extract
From `trading_bot.py`:
- Line ~100-150: Firestore client initialization
- Line ~763-792: Firestore close in finally block (CRITICAL)
- Line ~850-900: Update position status

### 6.2 Create Storage Skill
```python
# skills/storage/storage_skill.py
class StorageSkill(Skill):
    async def execute(self, context):
        if context.deal_id:
            # Save new position
            await self.position_repo.create_position({
                'deal_id': context.deal_id,
                'direction': context.signal,
                'entry_price': context.current_candle['close'],
                'timestamp': context.timestamp
            })
        
        return context
```

### 6.3 Critical: Firestore Close in Finally
```python
# orchestrator/trading_orchestrator.py
async def on_position_closed(self, deal_id, direction, close_reason):
    try:
        # Close via Capital.com API
        await execution_skill.close_position(deal_id)
    finally:
        # ALWAYS close in Firestore, even on 400 error
        try:
            await storage_skill.close_position(deal_id, close_reason)
        except Exception as e:
            logger.error(f"Firestore close failed: {e}")
```

### 6.4 Write Tests
- [ ] Test position create
- [ ] Test position close (even on API error)
- [ ] Test batch writes
- [ ] Test Firestore connection failure

---

## Phase 7: Build Orchestrator (Week 6)

### 7.1 Implement Full Event Loop
```python
# orchestrator/trading_orchestrator.py
async def on_candle(self, candle):
    context = Context(current_candle=candle)
    
    # Execute skills in sequence
    context = await self.skills['market_data'].execute(context)
    context = await self.skills['analysis'].execute(context)
    context = await self.skills['risk'].execute(context)
    
    if context.is_allowed:
        context = await self.skills['execution'].execute(context)
        context = await self.skills['storage'].execute(context)
        context = await self.skills['monitoring'].execute(context)
        context = await self.skills['alerting'].execute(context)
```

### 7.2 Error Handling
- [ ] Wrap each skill in try/except
- [ ] Log errors to context.errors
- [ ] Decide on retry logic (retry at skill or orchestrator level?)
- [ ] Implement circuit breaker for Firestore

### 7.3 WebSocket Integration
- [ ] Start WebSocket in orchestrator.start()
- [ ] Route candle events to on_candle()
- [ ] Route position close events to on_position_closed()

---

## Phase 8: Testing & Validation (Week 7-8)

### 8.1 Unit Tests
- [ ] Run all unit tests: `pytest tests/unit/ -v`
- [ ] Code coverage > 80%: `pytest --cov=skills`

### 8.2 Integration Tests
- [ ] Test full flow: candle → signal → validate → execute
- [ ] Test error scenarios (API down, Firestore unavailable)
- [ ] Test cooldown logic in full context

### 8.3 Backtest Validation
```bash
# Run backtest with new skill-based version
python orchestrator/main.py --mode backtest --data data/GOLD_M5_150000bars.csv

# Compare with baseline (old trading_bot.py backtest)
# Metrics should match exactly:
# - Total trades (within 1%)
# - Win rate (within 0.5%)
# - Sharpe ratio (within 5%)
```

### 8.4 Paper Trading
- [ ] Deploy to demo account
- [ ] Run for 1 week alongside old bot
- [ ] Compare trade decisions (should be identical)

---

## Phase 9: Deployment (Week 9)

### 9.1 Pre-Deployment Checklist
- [ ] All tests pass
- [ ] Backtest results match baseline
- [ ] Paper trading successful (1 week)
- [ ] Configuration reviewed
- [ ] Error handling tested
- [ ] Firestore close in finally block verified

### 9.2 Deploy to Production
```bash
# Deploy to server
scp -r trading-bot-skills/ root@204.168.191.150:/opt/

# SSH to server
ssh root@204.168.191.150

# Install dependencies
cd /opt/trading-bot-skills
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Test configuration
python -c "import yaml; yaml.safe_load(open('config/trading_config.yaml'))"

# Start new bot (alongside old one)
nohup python orchestrator/main.py --config config/trading_config.yaml > /tmp/skill_bot.log 2>&1 &

# Monitor both bots for 24 hours
tail -f /tmp/bot.log /tmp/skill_bot.log
```

### 9.3 Switch Over
Once skill-based bot is validated:
- [ ] Kill old bot: `pkill -f trading_bot.py`
- [ ] Rename skill bot log: `mv /tmp/skill_bot.log /tmp/bot.log`
- [ ] Update systemd service (if applicable)

---

## Phase 10: Post-Migration (Week 10+)

### 10.1 Monitoring
- [ ] Monitor for 2 weeks
- [ ] Compare P&L with baseline
- [ ] Check for any new errors
- [ ] Verify Firestore positions stay clean

### 10.2 Documentation
- [ ] Update README with new architecture
- [ ] Document skill interfaces
- [ ] Create troubleshooting guide

### 10.3 Future Improvements
- [ ] Add ML prediction skill
- [ ] Add portfolio optimization skill
- [ ] Add multi-symbol support (EURUSD, etc.)
- [ ] Add A/B testing framework

---

## Rollback Plan

If skill-based bot has issues:

1. **Immediate:** Kill skill bot, old bot still running
   ```bash
   pkill -f "orchestrator/main.py"
   ```

2. **Investigate:** Check logs
   ```bash
   grep ERROR /tmp/skill_bot.log
   ```

3. **Fix & Redeploy:** Fix issue, test in demo, redeploy

4. **Last Resort:** Revert to old `trading_bot.py`
   ```bash
   cd /opt/trading-bot
   git checkout trading_bot.py
   python scripts/trading_bot.py
   ```

---

## Code Comparison Checklist

When extracting code from `trading_bot.py`, ensure:

- [ ] All variables copied (no missing state)
- [ ] All logic copied (no missing conditions)
- [ ] All error handling copied
- [ ] All logging copied
- [ ] Behavior is IDENTICAL (test with backtest)

---

## Success Metrics

Migration is successful when:

✅ Backtest results match baseline (within 1%)  
✅ All unit tests pass (>80% coverage)  
✅ Integration tests pass  
✅ Paper trading successful (1+ week)  
✅ Production runs stable (2+ weeks)  
✅ No Firestore ghost positions  
✅ No duplicate trades  
✅ P&L matches expectations

---

## Common Pitfalls

🚫 **Don't:**
- Rewrite everything from scratch
- Change behavior during migration
- Skip testing (unit + integration + backtest)
- Deploy without paper trading first

✅ **Do:**
- Extract one skill at a time
- Test each extraction thoroughly
- Keep backtest as validation
- Run old and new bots in parallel

---

## Questions?

If stuck, check:
- [ARCHITECTURE.md](ARCHITECTURE.md) - Full architecture details
- [README.md](README.md) - Quick start guide
- Production logs: `ssh root@204.168.191.150 tail -f /tmp/bot.log`
- Backtest baseline: `cloud-function/STRATEGY_COMPARISON_30vs15_TP.md`
