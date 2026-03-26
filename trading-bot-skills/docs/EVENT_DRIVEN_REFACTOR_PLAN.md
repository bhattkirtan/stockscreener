# Event-Driven Orchestrator Refactor Plan

## Executive Summary

**Objective:** Complete transition to event-driven architecture by removing context-passing and moving all trading logic from orchestrator into skill event handlers.

**Current State:** Hybrid approach - Event bus exists but orchestrator still calls skills with `context` objects
**Target State:** Pure event-driven - Skills subscribe to events, process them, and publish new events

**Effort:** 2-3 hours
**Risk:** Low (existing test suite validates behavior)
**Impact:** High (cleaner architecture, true skill decoupling)

---

## Current Architecture Problems

### Problem 1: Orchestrator Contains Trading Logic
```python
# orchestrator/production_orchestrator.py (CURRENT - BAD)
async def _on_candle_closed_for_analysis(self, event: Event) -> None:
    """Orchestrator knows HOW to call Analysis Skill"""
    analysis_skill = self.skills.get('analysis')
    
    # Orchestrator creates context
    context = Context(
        current_candle=event.payload,
        timestamp=event.timestamp
    )
    
    # Orchestrator calls skill
    context = await analysis_skill.execute(context)
    
    # Orchestrator checks result and publishes event
    if context.signal:
        # Publish SIGNAL_GENERATED event
        pass
```

**Issues:**
- Orchestrator knows about Context structure
- Orchestrator knows how to call skills
- Orchestrator decides when to publish events
- Adds 300+ lines of trading logic to orchestrator

### Problem 2: Skills Don't Subscribe Directly
```python
# skills/analysis/analysis_skill.py (CURRENT - BAD)
class AnalysisSkill(Skill):
    async def execute(self, context: Context) -> Context:
        """Skill receives context, returns context"""
        # Calculate indicators
        # Generate signal
        # Return modified context
        return context
```

**Issues:**
- Skills are passive (wait to be called)
- Skills don't choose which events they care about
- Skills can't independently subscribe to multiple event types
- Context dict becomes a "god object"

### Problem 3: Tight Coupling via Context
```python
@dataclass
class Context:
    """40+ fields shared across ALL skills"""
    current_candle: Optional[Dict] = None
    candle_history: list = None
    indicators: Dict = None
    signal: Optional[str] = None
    position_size: float = 0.0
    is_allowed: bool = False
    order_id: Optional[str] = None
    # ... 30 more fields
```

**Issues:**
- Every skill knows about every field
- Adding new skill requires changing Context
- Hard to track data flow
- Violates single responsibility

---

## Target Architecture

### Principle 1: Skills Subscribe to Events
```python
# orchestrator/production_orchestrator.py (TARGET - GOOD)
def _wire_event_subscriptions(self) -> None:
    """Orchestrator only wires, doesn't call"""
    # Analysis skill subscribes to CANDLE_CLOSED
    if 'analysis' in self.skills:
        self.event_bus.subscribe(
            EventType.CANDLE_CLOSED,
            self.skills['analysis'].on_candle_closed  # Skill handles it
        )
    
    # Risk skill subscribes to SIGNAL_GENERATED
    if 'risk' in self.skills:
        self.event_bus.subscribe(
            EventType.SIGNAL_GENERATED,
            self.skills['risk'].on_signal_generated  # Skill handles it
        )
```

### Principle 2: Skills Handle Events Directly
```python
# skills/analysis/analysis_skill.py (TARGET - GOOD)
class AnalysisSkill(Skill):
    def __init__(self, config: Dict, event_bus: EventBus):
        self.event_bus = event_bus
        # ...
    
    async def on_candle_closed(self, event: Event) -> None:
        """Skill directly handles CANDLE_CLOSED event"""
        # Extract data from event
        candle = event.payload
        
        # Calculate indicators
        indicators = self._calculate_indicators(candle)
        
        # Generate signal
        signal = self._generate_signal(indicators)
        
        # Skill publishes its own event
        if signal:
            await self.event_bus.publish(
                create_signal_generated_event(
                    signal=signal,
                    indicators=indicators,
                    correlation_id=event.correlation_id  # Track lineage
                )
            )
```

### Principle 3: Orchestrator Is Wire-Only
```python
# orchestrator/production_orchestrator.py (TARGET - GOOD)
class ProductionOrchestrator:
    """
    Responsibilities:
    - Lifecycle: start, stop, restart
    - Wiring: connect skills to event bus
    - Monitoring: track health
    
    NOT responsible for:
    - Trading logic (skills handle events)
    - Risk decisions (Risk Skill)
    - Signal generation (Analysis Skill)
    - Order execution (Execution Skill)
    """
    
    async def start(self):
        # 1. Load state
        # 2. Reconcile
        # 3. Wire skills <--- ONLY wiring, no logic
        # 4. Start monitoring
        pass
```

---

## Detailed Refactoring Steps

### Step 1: Add Event Bus to Skills (30 minutes)

**File:** `skills/base_skill.py`

**Changes:**
```python
# BEFORE
class Skill(ABC):
    def __init__(self, config: Dict):
        self.config = config
    
    @abstractmethod
    async def execute(self, context: Context) -> Context:
        """Execute skill logic"""
        pass

# AFTER
from core.event_bus import EventBus

class Skill(ABC):
    def __init__(self, config: Dict, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
    
    # Remove execute() - skills implement event handlers instead
```

**Impact:** All 9 skills need event_bus in `__init__`

---

### Step 2: Refactor Analysis Skill (30 minutes)

**File:** `skills/analysis/analysis_skill.py`

**Changes:**
```python
# BEFORE
class AnalysisSkill(Skill):
    async def execute(self, context: Context) -> Context:
        df = pd.DataFrame(context.candle_history)
        # Calculate indicators
        # Generate signal
        context.signal = signal
        return context

# AFTER
from core.event_bus import EventBus, Event, EventType, create_signal_generated_event

class AnalysisSkill(Skill):
    def __init__(self, config: Dict, event_bus: EventBus, market_data_skill):
        super().__init__(config, event_bus)
        self.market_data = market_data_skill  # Access candle history
        self.last_signal_state = None
    
    async def on_candle_closed(self, event: Event) -> None:
        """Handle CANDLE_CLOSED event"""
        # Get candle history from market data skill
        candles = self.market_data.get_candle_history()
        if len(candles) < 50:
            return
        
        # Calculate indicators
        df = pd.DataFrame(candles)
        df = self._calculate_supertrend(df)
        df = self._calculate_sma(df)
        
        # Generate signal
        signal = self._generate_signal(df)
        
        # Edge detection
        if signal and signal != self.last_signal_state:
            self.last_signal_state = signal
            
            # Publish SIGNAL_GENERATED event
            await self.event_bus.publish(
                create_signal_generated_event(
                    instrument=event.instrument,
                    signal=signal,
                    indicators=self._extract_indicators(df),
                    correlation_id=event.correlation_id  # Preserve lineage
                )
            )
```

**Benefits:**
- Analysis skill owns signal generation logic
- No context passing
- Orchestrator doesn't know about indicator calculations
- Event correlation ID tracks candle → signal → trade

---

### Step 3: Refactor Risk Skill (30 minutes)

**File:** `skills/risk/risk_skill.py`

**Changes:**
```python
# BEFORE
class RiskSkill(Skill):
    async def execute(self, context: Context) -> Context:
        if not context.signal:
            return context
        
        # Check cooldown, exposure, position size
        context.is_allowed = validation_result
        context.position_size = calculated_size
        return context

# AFTER
from core.event_bus import create_risk_approved_event, create_risk_rejected_event
from core.circuit_breakers import CircuitBreaker, TradingSessionFilter

class RiskSkill(Skill):
    def __init__(self, config: Dict, event_bus: EventBus, 
                 circuit_breaker: CircuitBreaker,
                 session_filter: TradingSessionFilter,
                 spread_filter, news_killswitch):
        super().__init__(config, event_bus)
        self.circuit_breaker = circuit_breaker
        self.session_filter = session_filter
        self.spread_filter = spread_filter
        self.news_killswitch = news_killswitch
        self.cooldown_manager = CooldownManager(config)
        self.portfolio_manager = PortfolioManager(config)
    
    async def on_signal_generated(self, event: Event) -> None:
        """Handle SIGNAL_GENERATED event"""
        signal = event.payload['signal']
        
        # 1. Circuit breaker check
        current_capital = await self._get_current_capital()
        status, reason = self.circuit_breaker.check_status(current_capital)
        if status != CircuitBreakerStatus.CLOSED:
            await self._publish_risk_rejected(event, f"Circuit breaker: {reason}")
            return
        
        # 2. Session filter
        allowed, reason = self.session_filter.is_trading_allowed()
        if not allowed:
            await self._publish_risk_rejected(event, f"Session: {reason}")
            return
        
        # 3. Spread filter
        spread = await self._get_current_spread(event.instrument)
        allowed, reason = self.spread_filter.is_spread_acceptable(spread)
        if not allowed:
            await self._publish_risk_rejected(event, f"Spread: {reason}")
            return
        
        # 4. News kill switch
        allowed, reason = self.news_killswitch.is_trading_allowed()
        if not allowed:
            await self._publish_risk_rejected(event, f"News: {reason}")
            return
        
        # 5. Cooldown check
        allowed, reason = self.cooldown_manager.is_allowed(signal)
        if not allowed:
            await self._publish_risk_rejected(event, f"Cooldown: {reason}")
            return
        
        # 6. Position size calculation
        position_size = self.portfolio_manager.calculate_position_size(
            current_capital,
            risk_pct=self.config['position_size_pct']
        )
        
        # 7. Calculate SL/TP levels
        sl_pips = self.config['sl_pips']
        tp_pips = self.config['tp_pips']
        entry_price = event.payload['current_price']
        
        stop_loss, take_profit = self._calculate_sl_tp(
            entry_price, signal, sl_pips, tp_pips
        )
        
        # APPROVED - Publish RISK_APPROVED event
        await self.event_bus.publish(
            create_risk_approved_event(
                instrument=event.instrument,
                signal=signal,
                position_size=position_size,
                stop_loss=stop_loss,
                take_profit=take_profit,
                indicators=event.payload.get('indicators', {}),
                correlation_id=event.correlation_id
            )
        )
    
    async def _publish_risk_rejected(self, event: Event, reason: str):
        """Publish RISK_REJECTED event"""
        await self.event_bus.publish(
            create_risk_rejected_event(
                instrument=event.instrument,
                signal=event.payload['signal'],
                reason=reason,
                correlation_id=event.correlation_id
            )
        )
```

**Benefits:**
- Risk skill owns all risk logic (circuit breakers, cooldowns, sizing)
- Orchestrator doesn't know about risk rules
- Risk skill can evolve independently
- All 8 risk controls in one place

---

### Step 4: Refactor Execution Skill (30 minutes)

**File:** `skills/execution/execution_skill.py`

**Changes:**
```python
# BEFORE
class ExecutionSkill(Skill):
    async def execute(self, context: Context) -> Context:
        if context.signal and context.is_allowed:
            result = await self.capital_api.place_order(...)
            context.deal_id = result['deal_id']
        return context

# AFTER
from core.idempotency import IdempotencyManager, OrderRequest
from core.event_bus import create_order_filled_event, create_order_rejected_event

class ExecutionSkill(Skill):
    def __init__(self, config: Dict, event_bus: EventBus,
                 capital_api,
                 idempotency_manager: IdempotencyManager,
                 retry_policy):
        super().__init__(config, event_bus)
        self.capital_api = capital_api
        self.idempotency = idempotency_manager
        self.retry_policy = retry_policy
    
    async def on_risk_approved(self, event: Event) -> None:
        """Handle RISK_APPROVED event"""
        # Create order request with idempotency
        order = OrderRequest.create(
            instrument=event.instrument,
            direction=event.payload['signal'],
            size=event.payload['position_size'],
            stop_loss=event.payload['stop_loss'],
            take_profit=event.payload['take_profit'],
            signal_timestamp=event.timestamp
        )
        
        # Check for duplicate
        if self.idempotency.is_duplicate(order.idempotency_key):
            cached = self.idempotency.get_cached_result(order.idempotency_key)
            print(f"⚠️ Duplicate order: {order.idempotency_key}")
            # Return cached result instead of re-executing
            await self._publish_cached_fill(cached, event.correlation_id)
            return
        
        # Register submission
        self.idempotency.register_submission(order)
        
        # Execute with retry
        try:
            result = await self.retry_policy.execute_with_retry(
                self._place_order_with_api,
                order
            )
            
            # Register fill
            self.idempotency.register_fill(order.idempotency_key, result['deal_id'])
            
            # Publish ORDER_FILLED event
            await self.event_bus.publish(
                create_order_filled_event(
                    deal_id=result['deal_id'],
                    instrument=event.instrument,
                    direction=event.payload['signal'],
                    entry_price=result['level'],
                    size=event.payload['position_size'],
                    stop_loss=event.payload['stop_loss'],
                    take_profit=event.payload['take_profit'],
                    correlation_id=event.correlation_id
                )
            )
            
        except Exception as e:
            # Register rejection
            self.idempotency.register_rejection(order.idempotency_key, str(e))
            
            # Publish ORDER_REJECTED event
            await self.event_bus.publish(
                create_order_rejected_event(
                    instrument=event.instrument,
                    reason=str(e),
                    correlation_id=event.correlation_id
                )
            )
    
    async def _place_order_with_api(self, order: OrderRequest):
        """Actual API call (for retry wrapper)"""
        return await self.capital_api.place_order(
            instrument=order.instrument,
            direction=order.direction,
            size=order.size,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit
        )
```

**Benefits:**
- Execution skill owns idempotency and retry logic
- Orchestrator doesn't know about order placement
- Execution skill can be replaced without touching orchestrator
- Cached results handled automatically

---

### Step 5: Refactor Orchestrator (60 minutes)

**File:** `orchestrator/production_orchestrator.py`

**Changes:**
```python
# BEFORE: 600 lines with trading logic in event handlers

# AFTER: ~300 lines - pure wiring + lifecycle
class ProductionOrchestrator:
    """
    Production orchestrator - WIRE ONLY.
    
    Responsibilities:
    - Lifecycle: start, stop, restart
    - Wiring: connect skills to event bus
    - Health: monitor system health
    - State: reconcile broker state on startup
    
    NOT responsible for:
    - Trading logic (in skills)
    - Risk decisions (Risk Skill)
    - Order execution (Execution Skill)
    """
    
    def __init__(self, config: Dict, capital_api, firestore, telegram):
        # Core components
        self.event_bus = EventBus()
        self.position_manager = PositionStateManager(...)
        self.idempotency = IdempotencyManager(...)
        self.circuit_breaker = CircuitBreaker(...)
        self.session_filter = TradingSessionFilter(...)
        self.spread_filter = SpreadSlippageFilter(...)
        self.news_killswitch = NewsEventKillSwitch(...)
        self.op_monitor = OperationalMonitor(...)
        
        # Skills (will be registered)
        self.skills: Dict[str, Skill] = {}
    
    async def start(self) -> bool:
        """Start with full recovery"""
        # 1. Load state
        await self.position_manager.load_snapshot()
        
        # 2. Reconcile with broker
        await self._reconcile_broker()
        
        # 3. Wire event subscriptions (ONLY WIRING)
        self._wire_event_subscriptions()
        
        # 4. Start monitoring
        asyncio.create_task(self._monitoring_loop())
        
        self.running = True
        return True
    
    def _wire_event_subscriptions(self) -> None:
        """
        Wire skills to event bus.
        
        This is THE ONLY place orchestrator knows about skills.
        No trading logic here - just wiring.
        """
        # Market Data -> Analysis
        if 'analysis' in self.skills:
            self.event_bus.subscribe(
                EventType.CANDLE_CLOSED,
                self.skills['analysis'].on_candle_closed
            )
        
        # Analysis -> Risk
        if 'risk' in self.skills:
            self.event_bus.subscribe(
                EventType.SIGNAL_GENERATED,
                self.skills['risk'].on_signal_generated
            )
        
        # Risk -> Execution
        if 'execution' in self.skills:
            self.event_bus.subscribe(
                EventType.RISK_APPROVED,
                self.skills['execution'].on_risk_approved
            )
        
        # Execution -> Storage (update position state)
        self.event_bus.subscribe(
            EventType.ORDER_FILLED,
            self._on_order_filled_update_state  # Only state management
        )
        
        # Position closed -> Circuit breaker
        self.event_bus.subscribe(
            EventType.POSITION_CLOSED,
            self._on_position_closed_update_state  # Only state management
        )
        
        # Errors -> Alerting
        if 'alerting' in self.skills:
            self.event_bus.subscribe(
                EventType.BOT_ERROR,
                self.skills['alerting'].on_error
            )
        
        print(f"✅ Wired {len(self.event_bus.subscribers)} event subscriptions")
    
    # Simple state management handlers (NO TRADING LOGIC)
    
    async def _on_order_filled_update_state(self, event: Event) -> None:
        """ONLY update position state - no decisions"""
        position = Position(
            deal_id=event.payload['deal_id'],
            instrument=event.instrument,
            direction=event.payload['direction'],
            entry_price=event.payload['entry_price'],
            size=event.payload['size'],
            stop_loss=event.payload['stop_loss'],
            take_profit=event.payload['take_profit'],
            status=PositionStatus.OPEN,
            opened_at=event.timestamp
        )
        
        self.position_manager.add_position(position)
        await self.position_manager.save_snapshot()
    
    async def _on_position_closed_update_state(self, event: Event) -> None:
        """ONLY update position state and circuit breaker - no decisions"""
        position = self.position_manager.close_position(
            deal_id=event.payload['deal_id'],
            close_price=event.payload['close_price'],
            close_reason=event.payload['close_reason']
        )
        
        if position:
            self.circuit_breaker.record_trade(position.realized_pnl)
            await self.position_manager.save_snapshot()
    
    async def _monitoring_loop(self) -> None:
        """Periodic health checks and cleanup"""
        while self.running:
            # Health checks
            await self.op_monitor.run_health_checks()
            
            # Cleanup
            await self.idempotency.cleanup_expired()
            await self.position_manager.save_snapshot()
            
            await asyncio.sleep(60)
```

**Impact:**
- Orchestrator goes from 600 lines to ~300 lines
- All trading logic removed from orchestrator
- Orchestrator becomes configuration/wiring code
- Easy to understand and maintain

---

## Testing Strategy

### Phase 1: Unit Tests Still Pass
```bash
pytest tests/unit/ -v
# All 82 existing tests should pass
```

### Phase 2: Integration Tests
```python
# tests/integration/test_event_driven_flow.py

@pytest.mark.asyncio
async def test_event_driven_candle_to_trade():
    """Test full event flow: candle → signal → risk → order"""
    # Setup
    event_bus = EventBus()
    market_data = MarketDataSkill(config, event_bus)
    analysis = AnalysisSkill(config, event_bus, market_data)
    risk = RiskSkill(config, event_bus, circuit_breaker, ...)
    execution = ExecutionSkill(config, event_bus, mock_api, ...)
    
    # Wire subscriptions
    event_bus.subscribe(EventType.CANDLE_CLOSED, analysis.on_candle_closed)
    event_bus.subscribe(EventType.SIGNAL_GENERATED, risk.on_signal_generated)
    event_bus.subscribe(EventType.RISK_APPROVED, execution.on_risk_approved)
    
    # Trigger flow
    await event_bus.publish(create_candle_closed_event(...))
    
    # Wait for async processing
    await asyncio.sleep(0.5)
    
    # Verify
    order_filled_events = event_bus.get_events_by_type(EventType.ORDER_FILLED)
    assert len(order_filled_events) == 1
    
    # Verify correlation
    candle_event = event_bus.history[0]
    order_event = order_filled_events[0]
    assert order_event.correlation_id == candle_event.correlation_id
```

### Phase 3: Event Correlation Tests
```python
def test_event_correlation_tracks_lifecycle():
    """Verify correlation ID tracks candle → signal → trade"""
    # Candle event
    candle = create_candle_closed_event(...)
    
    # Signal event (should copy correlation_id)
    signal = create_signal_generated_event(..., correlation_id=candle.correlation_id)
    
    # Trade event (should copy correlation_id)
    trade = create_order_filled_event(..., correlation_id=signal.correlation_id)
    
    # All linked
    assert candle.correlation_id == signal.correlation_id == trade.correlation_id
```

---

## Migration Checklist

### Pre-Migration (10 minutes)
- [ ] Create git branch: `git checkout -b event-driven-refactor`
- [ ] Backup production_orchestrator.py
- [ ] Run full test suite: `pytest tests/ -v`
- [ ] Document baseline: 180 tests passing

### Phase 1: Base Skill (20 minutes)
- [ ] Update `skills/base_skill.py` - add event_bus to `__init__`
- [ ] Remove `execute()` abstract method
- [ ] Add event handler documentation
- [ ] Run tests: `pytest tests/unit/test_base_skill.py`

### Phase 2: Analysis Skill (30 minutes)
- [ ] Refactor `AnalysisSkill.__init__()` - accept event_bus
- [ ] Replace `execute()` with `on_candle_closed()`
- [ ] Add `create_signal_generated_event()` calls
- [ ] Update tests: `pytest tests/unit/test_analysis_skill.py`

### Phase 3: Risk Skill (30 minutes)
- [ ] Refactor `RiskSkill.__init__()` - accept circuit breakers
- [ ] Replace `execute()` with `on_signal_generated()`
- [ ] Add `create_risk_approved_event()` calls
- [ ] Update tests: `pytest tests/unit/test_risk_skill.py`

### Phase 4: Execution Skill (30 minutes)
- [ ] Refactor `ExecutionSkill.__init__()` - accept idempotency
- [ ] Replace `execute()` with `on_risk_approved()`
- [ ] Add `create_order_filled_event()` calls
- [ ] Update tests: `pytest tests/unit/test_execution_skill.py`

### Phase 5: Orchestrator (60 minutes)
- [ ] Simplify `_wire_event_subscriptions()` - use skill methods
- [ ] Remove trading logic from event handlers
- [ ] Keep only state management handlers
- [ ] Update `register_skill()` to pass event_bus
- [ ] Update tests: `pytest tests/integration/test_orchestrator.py`

### Post-Migration (30 minutes)
- [ ] Run full test suite: `pytest tests/ -v`
- [ ] Validate 180 tests still pass
- [ ] Manual smoke test with paper trading
- [ ] Update documentation
- [ ] Code review
- [ ] Merge to main

---

## Code Size Impact

### Before Event-Driven Refactor
```
orchestrator/production_orchestrator.py:  600 lines (300 wiring + 300 trading logic)
skills/analysis/analysis_skill.py:        200 lines
skills/risk/risk_skill.py:                250 lines
skills/execution/execution_skill.py:      200 lines
Total:                                   1250 lines
```

### After Event-Driven Refactor
```
orchestrator/production_orchestrator.py:  300 lines (wiring + lifecycle only)
skills/analysis/analysis_skill.py:        250 lines (+50 for event handling)
skills/risk/risk_skill.py:                300 lines (+50 for event handling)
skills/execution/execution_skill.py:      250 lines (+50 for event handling)
Total:                                   1100 lines (-150 lines)
```

**Benefits:**
- 150 fewer lines (12% reduction)
- Orchestrator 50% smaller
- Trading logic moved to appropriate skills
- Clearer separation of concerns

---

## Success Criteria

### Must Have
- [ ] All 180 tests pass
- [ ] Orchestrator < 350 lines
- [ ] Skills subscribe to events (not called by orchestrator)
- [ ] Event correlation IDs track full lifecycle
- [ ] No Context object passing between skills

### Nice to Have
- [ ] Event flow diagram generated from live events
- [ ] Correlation ID viewer in monitoring dashboard
- [ ] Event replay capability for debugging

---

## Rollback Plan

If issues arise during refactor:

1. **Git reset:** `git reset --hard HEAD`
2. **Restore backup:** `cp production_orchestrator.py.backup production_orchestrator.py`
3. **Run tests:** `pytest tests/ -v` (should pass)
4. **Debug specific issue:** Create isolated test case
5. **Retry refactor:** Fix one skill at a time

---

## Next Steps After Refactor

1. **Event Replay:** Add ability to replay events for debugging
2. **Event Store:** Persist event history beyond rolling buffer
3. **Multi-Strategy:** Run 3-5 strategies simultaneously (easy with event bus)
4. **Event Dashboard:** Visualize event flow in real-time
5. **Distributed Event Bus:** Replace in-process with RabbitMQ/Redis (if needed)

---

## Questions?

**Q: Will this break existing behavior?**
A: No - same events, same logic, just better organized. Tests validate behavior.

**Q: Why not use external message broker (RabbitMQ)?**
A: In-process event bus sufficient for single-bot deployment. Can upgrade later if needed.

**Q: What if I need to pass large data (candle history)?**
A: Store in Market Data Skill, reference by instrument in event. Skills can call `market_data.get_candles()`.

**Q: How do I debug event flow?**
A: Use EventBus history + correlation IDs. Filter events: `event_bus.filter_by_correlation(corr_id)`.

---

## Estimated Timeline

| Phase | Task | Duration | Cumulative |
|-------|------|----------|------------|
| 0 | Planning & backup | 10 min | 10 min |
| 1 | Base skill refactor | 20 min | 30 min |
| 2 | Analysis skill | 30 min | 60 min |
| 3 | Risk skill | 30 min | 90 min |
| 4 | Execution skill | 30 min | 120 min |
| 5 | Orchestrator | 60 min | 180 min |
| 6 | Testing & validation | 30 min | 210 min |

**Total:** 3.5 hours (conservative estimate)
**Optimistic:** 2-2.5 hours if no issues
**Pessimistic:** 4-5 hours with debugging

---

## Conclusion

The event-driven refactor completes the architectural vision from Phase 15. By removing context-passing and moving trading logic into skills, we achieve:

✅ **True decoupling** - Skills don't know about each other
✅ **Clean orchestrator** - 50% smaller, pure wiring
✅ **Better testing** - Test skills in isolation with event mocks
✅ **Event tracing** - Correlation IDs track full lifecycle
✅ **Future-proof** - Easy to add new skills/strategies

Let's do this! 🚀
