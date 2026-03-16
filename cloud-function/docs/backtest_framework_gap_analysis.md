# Backtest Framework Gap Analysis
## External Data Feeds Integration Assessment

**Date:** 2026-03-13  
**Purpose:** Identify what exists vs. what needs to be built for the 4-feed architecture  
**Reference:** [strategy.md](./strategy.md) Section 6.6 - External Data Feeds Architecture

---

## Executive Summary

### Current State ✅
Your backtest framework has:
- **Strong foundation**: Tick-level backtester with intra-candle simulation
- **Capital.com integration**: REST + WebSocket clients already working
- **Data caching**: Incremental data fetching with local + GCS cache
- **Risk management**: Position sizing, stop loss, take profit logic
- **Time-based filters**: EOD close, Friday filter, max holding hours
- **Analytics**: Trade tracking, PnL, drawdown, win rate

### Missing Components ❌
You need to add:
- **Trading Economics calendar** integration (news event blocking)
- **FRED macro series** integration (regime detection)
- **NewsAPI headlines** integration (unscheduled risk blocking)
- **Multi-feed orchestration** layer
- **Feed health monitoring** system
- **Backtest data replay** engine for all 4 feeds
- **Zone-based strategy engine** (H4/H1/M15/M5 structure from strategy.md)

### Effort Estimate
- **Adapt/extend existing**: ~40% of work
- **Build new components**: ~60% of work
- **Total development**: 6-8 weeks (following the 7-sprint roadmap)

---

## 1. Current Capabilities (What You Have)

### 1.1 Price Feed Infrastructure ✅ STRONG

| Component | Status | File Location | Notes |
|-----------|--------|---------------|-------|
| Capital.com REST client | ✅ Production-ready | `src/api/capital_client.py` | Token caching, retry logic, session pooling |
| Capital.com WebSocket | ✅ Production-ready | `src/live_trading/capital_websocket.py` | Real-time OHLC + quotes, keepalive pings |
| Historical data fetcher | ✅ Working | `src/data/cache_data.py` | Incremental fetching, 1000-bar pagination |
| Data caching | ✅ Working | `src/data/cache_data.py`, `src/data/gcs_cache.py` | Local + GCS with metadata tracking |
| Market data (spread) | ✅ Working | `src/data/market_data.py` | Real-time bid/ask, spread, market status |

**Assessment:** Your Capital.com integration is excellent and production-ready. This covers Feed 1 completely.

**What to adapt:**
- Ensure WebSocket can handle multiple instruments (Gold + US100)
- Add configurable staleness detection (currently missing explicit 30s threshold check)
- Add reconnection monitoring/alerting

---

### 1.2 Backtesting Engine ✅ STRONG

| Component | Status | File Location | Notes |
|-----------|--------|---------------|-------|
| Intra-candle backtester | ✅ Production-ready | `src/core/backtester.py` | Realistic SL/TP execution using OHLC simulation |
| Tick-level backtester | ✅ Working | `src/core/tick_backtester.py` | Uses 1-minute bars as ticks |
| BacktestConfig | ✅ Working | `src/core/backtester.py` (line 214) | Spread, slippage, position sizing |
| Trade lifecycle | ✅ Working | `src/core/backtester.py` | Order tracking, PnL, MAE (partially) |
| Time-based filters | ✅ Working | `src/core/backtester.py` | EOD close, Friday filter, max holding hours |
| Compounding | ✅ Working | `src/core/backtester.py` | Kelly criterion, % sizing |

**Assessment:** Your backtester is sophisticated and handles realistic execution well.

**What to adapt:**
- Add **zone-based stop loss** logic (strategy.md Section 15)
- Add **opposing-zone TP targeting** (strategy.md Section 16)
- Add **news event blocking** filter (currently time-based only)
- Add **multi-timeframe context** (H4/H1/M15/M5 hierarchy)
- Add **macro regime adjustment** to trade scores
- Add **headline blocking** filter

---

### 1.3 Strategy Engine ⚠️ NEEDS MAJOR EXTENSION

| Component | Status | File Location | Notes |
|-----------|--------|---------------|-------|
| Supertrend + VWAP strategy | ✅ Working | `src/core/strategy.py` | Current M15 scalping strategy |
| Indicator calculation | ✅ Working | `src/core/strategy.py` | RSI, BB, Supertrend, VWAP |
| Signal generation | ✅ Working | `src/core/strategy.py` | Buy/sell signals |
| **Zone engine** | ❌ Missing | *needs to be built* | H4/H1/M15 zone construction |
| **Zone scoring** | ❌ Missing | *needs to be built* | Strength, freshness, cluster detection |
| **Bias engine** | ❌ Missing | *needs to be built* | H4/H1 directional bias |
| **Trigger engine** | ❌ Missing | *needs to be built* | M5 reclaim/rejection/breakout |
| **Trade scorer** | ❌ Missing | *needs to be built* | 0-100 score with 8 components |

**Assessment:** You have a working strategy, but it's NOT the zone-based strategy defined in strategy.md.

**Critical gap:** The entire zone-based intraday strategy from strategy.md needs to be built as a new strategy class.

---

### 1.4 Configuration Management ⚠️ PARTIAL

| Component | Status | File Location | Notes |
|-----------|--------|---------------|-------|
| TradingConfig dataclass | ✅ Working | `src/live_trading/config.py` | Environment, credentials, strategy params |
| BacktestConfig dataclass | ✅ Working | `src/core/backtester.py` | Risk, costs, time filters |
| Environment variable loading | ✅ Working | Uses `.env` file | Credentials loaded from `apicredentials` |
| **YAML config support** | ❌ Missing | *needs to be built* | Strategy.md Section 21 shows YAML config |
| **External feed config** | ❌ Missing | *needs to be built* | API keys, endpoints, thresholds for 4 feeds |

**Assessment:** You have Python dataclasses, but not the comprehensive YAML config structure from strategy.md.

---

### 1.5 Analytics and Reporting ✅ MODERATE

| Component | Status | File Location | Notes |
|-----------|--------|---------------|-------|
| Trade tracking | ✅ Working | `src/core/backtester.py` | Entry/exit, PnL, reason |
| Equity curve | ✅ Working | `src/core/backtester.py` | Timestamped equity snapshots |
| Basic metrics | ✅ Working | Win rate, total PnL, trade count |
| **MAE/MFE analytics** | ⚠️ Partial | Mentioned in code, not fully implemented | Strategy.md Section 24.4 requires this |
| **Walk-forward testing** | ❌ Missing | *needs to be built* | Strategy.md Section 24 |
| **Robustness tests** | ❌ Missing | *needs to be built* | Strategy.md Section 24.5 |
| **Metrics report template** | ❌ Missing | *needs to be built* | Strategy.md Section 31 |

---

## 2. Missing Components (What You Need to Build)

### 2.1 Feed 2: Economic Calendar (Trading Economics) ❌ CRITICAL

**Status:** Completely missing

**Requirements:**
- API client for Trading Economics
- Calendar data fetcher (daily batch + 4-hour refresh)
- Event classification (high/medium/low impact)
- Time-based event blocking (15 min before/after)
- Caching strategy (48-hour TTL)
- Fallback to manual event list
- Historical calendar for backtest replay

**Files to create:**
```
src/feeds/trading_economics_adapter.py
src/feeds/event_blocker.py
tests/test_trading_economics_adapter.py
tests/test_event_blocking.py
```

**Integration points:**
- Add `is_blocked_by_news()` check to `IntraCandleBacktester.run()`
- Add event cache to backtest data loader
- Add calendar replay to backtest runner

**Effort:** 1.5 weeks

---

### 2.2 Feed 3: Macro Series (FRED) ❌ MODERATE PRIORITY

**Status:** Completely missing

**Requirements:**
- API client for FRED
- Series fetcher for 8 key series (DFF, DGS10, T10Y2Y, DTWEXBGS, CPI, UNRATE, USREC, etc.)
- Regime state machine (5 regimes from strategy.md Section 8.6)
- Trade score adjustment logic (-15 to +15 points)
- Daily update scheduler
- Staleness detection (7-day threshold)
- Historical series with vintage dates (no forward-looking revisions)

**Files to create:**
```
src/feeds/fred_adapter.py
src/feeds/regime_detector.py
tests/test_fred_adapter.py
tests/test_regime_detection.py
```

**Integration points:**
- Add `apply_macro_adjustment()` to trade scorer
- Add regime context to backtest logs
- Add regime state to equity curve snapshots

**Effort:** 1 week

---

### 2.3 Feed 4: News Headlines (NewsAPI) ❌ LOW PRIORITY (v2)

**Status:** Completely missing

**Requirements:**
- API client for NewsAPI
- Headline fetcher with keyword filtering
- High-impact keyword detection
- 10-minute trade blocking after detection
- Rate limit handling
- Historical headline corpus for backtest

**Files to create:**
```
src/feeds/newsapi_adapter.py
src/feeds/headline_blocker.py
tests/test_newsapi_adapter.py
tests/test_headline_blocking.py
```

**Integration points:**
- Add `check_headline_block()` to trade decision flow
- Add headline events to backtest logs

**Effort:** 1 week

**Note:** Strategy.md recommends starting with v1 (no NewsAPI), then adding it later. You can defer this to Sprint 4.

---

### 2.4 Feed Orchestration Layer ❌ CRITICAL

**Status:** Completely missing

**Requirements:**
- Feed health monitor (staleness, error tracking)
- Feed manager with priority and fallback logic
- Degraded mode handling
- Availability status reporting
- Integration testing framework

**Files to create:**
```
src/feeds/feed_health_monitor.py
src/feeds/feed_manager.py
tests/test_feed_fallback_logic.py
```

**Integration points:**
- Replace direct API calls with `FeedManager.get_calendar_events()`
- Add health check to bot startup
- Add feed status to monitoring dashboard

**Effort:** 1 week

---

### 2.5 Zone-Based Strategy Engine ❌ CRITICAL

**Status:** Completely missing (this is the core of strategy.md)

**Requirements:**
- Zone construction from H4/H1/M15 swing points
- Zone width calculation (ATR-based)
- Zone scoring (strength, freshness, touch count)
- Zone merge logic
- Zone cluster detection
- Bias detection (H4/H1 EMA crossover)
- M5 trigger detection (reclaim, rejection, breakout)
- Trade scoring (0-100 with 8 components)
- Stop loss placement (outside zone + buffer)
- Take profit mapping (opposing zones)
- Room-to-target filter

**Files to create:**
```
src/core/zone_engine.py
src/core/bias_engine.py
src/core/trigger_engine.py
src/core/trade_scorer.py
src/core/zone_based_strategy.py
tests/test_zone_engine.py
tests/test_bias_engine.py
tests/test_trigger_engine.py
tests/test_trade_scorer.py
```

**Integration points:**
- New strategy class: `ZoneBasedIntradayStrategy`
- Add zone context to backtest logs
- Add zone visualization to charts (optional)

**Effort:** 2.5 weeks (largest component)

---

### 2.6 Multi-Feed Backtest Replay Engine ❌ CRITICAL

**Status:** Completely missing

**Requirements:**
- Time-aligned data replay from 4 feeds
- Point-in-time data access (no lookahead)
- Multiple timeframe synchronization (H4/H1/M15/M5)
- Event window enforcement
- Regime state tracking
- Headline blocking tracking

**Files to create:**
```
src/backtest/data_replay_engine.py
src/backtest/multi_timeframe_loader.py
tests/test_data_replay.py
```

**Integration points:**
- Replace current `df` iteration with `ReplayEngine.next_bar()`
- Add event/regime context to each bar
- Add feed availability flags

**Effort:** 1.5 weeks

---

### 2.7 Walk-Forward Testing Infrastructure ❌ MODERATE PRIORITY

**Status:** Completely missing

**Requirements:**
- Walk-forward splitter (train/validation/test)
- Anchored expanding window mode
- Rolling window mode
- Out-of-sample performance tracking
- Parameter stability tests
- Robustness suite (spread/slippage/threshold shocks)

**Files to create:**
```
src/backtest/walkforward_runner.py
src/backtest/robustness_tester.py
tests/test_walkforward.py
```

**Integration points:**
- Extend existing optimization loop
- Add walk-forward mode to CLI

**Effort:** 1 week

---

## 3. Adaptation Plan (What to Modify)

### 3.1 Extend BacktestConfig for External Feeds

**File:** `src/core/backtester.py`

**Changes:**
```python
@dataclass
class BacktestConfig:
    # ... existing fields ...
    
    # External data feeds (NEW)
    enable_calendar_blocking: bool = True
    enable_regime_adjustment: bool = True
    enable_headline_blocking: bool = False  # v2 only
    
    # News blocking (NEW)
    block_minutes_before_high: int = 15
    block_minutes_after_high: int = 15
    
    # Macro regime (NEW)
    regime_score_penalty_hawkish_usd: int = 15  # for gold longs
    regime_score_bonus_easing: int = 10
    
    # Feed health (NEW)
    max_feed_staleness_seconds: int = 30  # for price feed
    max_calendar_staleness_hours: int = 24
    max_macro_staleness_days: int = 7
```

---

### 3.2 Add Event Blocking to IntraCandleBacktester

**File:** `src/core/backtester.py`

**Method:** `IntraCandleBacktester.run()`

**Changes:**
```python
def run(self, df: pd.DataFrame, signals: pd.DataFrame, 
        calendar_events: Optional[List[Dict]] = None,
        regime_state: Optional[Dict] = None) -> Dict:
    """
    Run backtest with optional external context
    
    Args:
        df: OHLC data
        signals: Trading signals
        calendar_events: Economic calendar (NEW)
        regime_state: Macro regime (NEW)
    """
    
    for idx, row in df.iterrows():
        current_time = idx
        
        # NEW: Check calendar blocking
        if self.config.enable_calendar_blocking and calendar_events:
            if self._is_blocked_by_event(current_time, calendar_events):
                continue  # Skip this bar
        
        # NEW: Check headline blocking (v2)
        if self.config.enable_headline_blocking:
            if self._is_blocked_by_headline(current_time):
                continue
        
        # Existing trade logic...
        if signals.loc[idx, 'signal'] == 1:
            # NEW: Apply regime adjustment
            trade_score = self._calculate_trade_score(row, signals.loc[idx])
            if regime_state:
                trade_score = self._apply_regime_adjustment(
                    trade_score, regime_state
                )
            
            if trade_score >= self.config.min_trade_score:
                self._open_position(...)
```

---

### 3.3 Add Multi-Timeframe Context to Backtester

**File:** `src/core/backtester.py`

**New method:**
```python
def run_multi_timeframe(
    self, 
    data_h4: pd.DataFrame,
    data_h1: pd.DataFrame,
    data_m15: pd.DataFrame,
    data_m5: pd.DataFrame,
    strategy: 'ZoneBasedStrategy',
    calendar_events: Optional[List[Dict]] = None,
    macro_series: Optional[pd.DataFrame] = None
) -> Dict:
    """
    Run backtest with multi-timeframe zone-based strategy
    
    This is the main entry point for the new zone-based strategy.
    """
    
    # Initialize zone engine
    zone_engine = ZoneEngine(
        atr_h4=self._calculate_atr(data_h4),
        atr_h1=self._calculate_atr(data_h1),
        atr_m15=self._calculate_atr(data_m15)
    )
    
    # Build zones from H4/H1/M15
    zones = zone_engine.build_zones(data_h4, data_h1, data_m15)
    
    # Detect regime from macro series
    regime = RegimeDetector.detect(macro_series) if macro_series else None
    
    # Main loop on M5 (trigger timeframe)
    for idx, row in data_m5.iterrows():
        # ... trade decision logic ...
```

---

### 3.4 Create Unified Config File (YAML)

**New file:** `config/strategy_config.yaml`

**Content:** (use template from strategy.md Section 21)

```yaml
strategy:
  symbols:
    - XAUUSD
    - US100
  # ... rest from strategy.md ...

external_data:
  capital_com:
    # ... from strategy.md Section 6.6.2 ...
  
  trading_economics:
    # ... from strategy.md Section 6.6.3 ...
  
  fred:
    # ... from strategy.md Section 6.6.4 ...
  
  news_api:
    # ... from strategy.md Section 6.6.5 ...
```

**Add config loader:**

**New file:** `src/config/config_loader.py`

```python
import yaml
from dataclasses import dataclass
from typing import Dict, List

def load_strategy_config(config_path: str = 'config/strategy_config.yaml'):
    """Load strategy configuration from YAML"""
    with open(config_path) as f:
        return yaml.safe_load(f)

def create_backtest_config(yaml_config: Dict) -> BacktestConfig:
    """Convert YAML config to BacktestConfig dataclass"""
    strategy = yaml_config['strategy']
    return BacktestConfig(
        initial_capital=strategy['risk']['initial_capital'],
        # ... map rest of fields ...
    )
```

---

## 4. Implementation Priority Matrix

### Sprint 1: Core Strategy + Price Feed (Week 1-2)
**Goal:** Get zone-based strategy working with existing Capital.com data

**Tasks:**
1. ✅ Capital.com adapter (already done, just verify)
2. 🔨 Build zone engine (`zone_engine.py`)
3. 🔨 Build bias engine (`bias_engine.py`)
4. 🔨 Build trigger engine (`trigger_engine.py`)
5. 🔨 Build trade scorer (`trade_scorer.py`)
6. 🔨 Integrate into `ZoneBasedStrategy` class
7. 🔨 Basic backtest with price-only context

**Deliverables:**
- `src/core/zone_engine.py`
- `src/core/bias_engine.py`
- `src/core/trigger_engine.py`
- `src/core/trade_scorer.py`
- `src/core/zone_based_strategy.py`
- Basic backtest results

---

### Sprint 2: Calendar + Event Blocking (Week 3)
**Goal:** Add scheduled news event awareness

**Tasks:**
1. 🔨 Build Trading Economics adapter
2. 🔨 Build event blocker module
3. 🔨 Integrate event blocking into backtester
4. 🔨 Add event caching
5. 🔨 Validate no trades during blocked windows

**Deliverables:**
- `src/feeds/trading_economics_adapter.py`
- `src/feeds/event_blocker.py`
- Updated `BacktestConfig`
- Backtest comparison: with vs without calendar

---

### Sprint 3: Macro Regime (Week 4)
**Goal:** Add macro context to trade scoring

**Tasks:**
1. 🔨 Build FRED adapter
2. 🔨 Build regime detector
3. 🔨 Integrate regime adjustments into trade scorer
4. 🔨 Add regime state to logs
5. 🔨 Backtest comparison: with vs without regime

**Deliverables:**
- `src/feeds/fred_adapter.py`
- `src/feeds/regime_detector.py`
- Updated trade scorer
- Regime performance report

---

### Sprint 4: Headline Filter (Week 5) [OPTIONAL FOR v1]
**Goal:** Add unscheduled risk detection

**Tasks:**
1. 🔨 Build NewsAPI adapter
2. 🔨 Build headline blocker
3. 🔨 Integrate into decision flow
4. 🔨 Test with historical headlines

**Deliverables:**
- `src/feeds/newsapi_adapter.py`
- `src/feeds/headline_blocker.py`

**Note:** Can defer to v2 if needed.

---

### Sprint 5: Feed Orchestration (Week 6)
**Goal:** Unify all feeds with health monitoring

**Tasks:**
1. 🔨 Build feed health monitor
2. 🔨 Build feed manager
3. 🔨 Implement fallback logic
4. 🔨 Add degraded mode handling
5. 🔨 Integration tests

**Deliverables:**
- `src/feeds/feed_health_monitor.py`
- `src/feeds/feed_manager.py`
- `tests/test_feed_fallback_logic.py`

---

### Sprint 6: Walk-Forward + Robustness (Week 7)
**Goal:** Production-grade validation

**Tasks:**
1. 🔨 Build walk-forward runner
2. 🔨 Build robustness tester
3. 🔨 Run parameter stability tests
4. 🔨 Generate metrics reports

**Deliverables:**
- `src/backtest/walkforward_runner.py`
- `src/backtest/robustness_tester.py`
- Walk-forward results
- Robustness report

---

### Sprint 7: Live Integration (Week 8)
**Goal:** Connect live bot to all feeds

**Tasks:**
1. 🔨 Build live bot with feed manager
2. 🔨 Add monitoring dashboard
3. 🔨 Dry-run testing
4. 🔨 Deploy with kill switches

**Deliverables:**
- `src/live/live_bot.py`
- `src/monitoring/feed_dashboard.py`
- Runbook
- Deployment checklist

---

## 5. Risk Assessment

### High Risk Areas

**1. Zone engine complexity**
- Risk: Zone construction logic is complex (merging, clustering, scoring)
- Mitigation: Build incrementally, test with fixed examples first

**2. Multi-timeframe synchronization**
- Risk: Aligning H4/H1/M15/M5 bars without lookahead bias
- Mitigation: Use explicit replay engine with timestamp matching

**3. API rate limits**
- Risk: Trading Economics, FRED, NewsAPI all have rate limits
- Mitigation: Aggressive caching, batch fetching, error handling

**4. Historical data availability**
- Risk: NewsAPI may not have comprehensive historical headlines
- Mitigation: Make headline filter optional in backtest, note as limitation

### Medium Risk Areas

**1. Config complexity**
- Risk: YAML config has 100+ parameters
- Mitigation: Use sensible defaults, validation on load

**2. Regime detection accuracy**
- Risk: Macro regime state machine may be too simplistic
- Mitigation: Start with simple rules, iterate based on results

**3. Feed staleness handling**
- Risk: Degraded mode behavior may be unclear
- Mitigation: Explicit state machine, comprehensive logging

---

## 6. Recommended Adaptation Strategy

### Phase 1: Foundation (Sprints 1-2)
**Focus:** Get zone-based strategy working with price + calendar

**Priority:** CRITICAL

**Rationale:** The zone-based strategy is the core of strategy.md. Without it, you can't validate the rest of the system.

**Success metric:** Backtest runs with realistic event blocking and produces trade logs with zone context.

---

### Phase 2: Context Enrichment (Sprints 3-4)
**Focus:** Add macro regime and optionally headlines

**Priority:** HIGH

**Rationale:** These improve trade quality but aren't blocking for basic functionality.

**Success metric:** Trade score adjustments visible in logs, regime-aware performance report generated.

---

### Phase 3: Production Hardening (Sprints 5-7)
**Focus:** Feed orchestration, walk-forward, live integration

**Priority:** MEDIUM (for backtest), HIGH (for live)

**Rationale:** You can backtest without perfect feed orchestration, but you can't go live safely.

**Success metric:** System survives feed failures gracefully, walk-forward shows parameter stability.

---

## 7. Code Reuse Opportunities

### High Reuse (>80%)

| Component | Reuse % | Notes |
|-----------|---------|-------|
| Capital.com REST client | 95% | Just add staleness check |
| Capital.com WebSocket | 90% | Add multi-instrument support |
| Data caching | 85% | Extend for calendar/macro cache |
| Trade tracking | 80% | Add zone context fields |

### Moderate Reuse (40-80%)

| Component | Reuse % | Notes |
|-----------|---------|-------|
| BacktestConfig | 60% | Add ~20 new fields |
| Backtester main loop | 50% | Add event/regime checks |
| Time filters | 70% | Extend for calendar-based blocks |

### Low Reuse (<40%)

| Component | Reuse % | Notes |
|-----------|---------|-------|
| Strategy logic | 10% | Zone-based is fundamentally different |
| Stop loss logic | 30% | Zone-aware stops are different |
| Signal generation | 20% | Trigger-based vs indicator-based |

---

## 8. Key Decision Points

### Decision 1: Monolithic vs Microservices
**Question:** Should feeds be separate services or modules in one codebase?

**Recommendation:** Start monolithic (modules in one repo), split later if needed.

**Rationale:** 
- Easier to develop and test
- Shared data models
- Faster iteration
- Can split later if feeds become bottlenecks

---

### Decision 2: YAML Config vs Python Config
**Question:** Should we use YAML (strategy.md) or Python dataclasses (current)?

**Recommendation:** Use YAML as source of truth, generate Python dataclasses.

**Rationale:**
- YAML is more readable for non-engineers
- YAML can be versioned separately
- Python dataclasses still used internally for type safety

---

### Decision 3: Backtest-First vs Live-First
**Question:** Should we optimize backtest experience or live trading first?

**Recommendation:** Backtest-first (current approach is correct).

**Rationale:**
- Validate strategy before risking capital
- Faster iteration cycle
- Walk-forward results inform live deploy decision

---

### Decision 4: v1 Without NewsAPI or v1 With
**Question:** Should we include NewsAPI in v1 or defer to v2?

**Recommendation:** Defer to v2 (strategy.md agrees).

**Rationale:**
- Trading Economics calendar covers most scheduled risk
- Headline blocking adds complexity without proven value
- Can add later once core system is validated

---

## 9. Final Recommendations

### Immediate Actions (This Week)

1. **Set up project structure**
   ```
   mkdir -p src/feeds
   mkdir -p src/backtest
   mkdir -p config
   mkdir -p tests/integration
   ```

2. **Create stub files**
   ```
   touch src/feeds/trading_economics_adapter.py
   touch src/feeds/fred_adapter.py
   touch src/feeds/feed_manager.py
   touch src/core/zone_engine.py
   touch config/strategy_config.yaml
   ```

3. **Update requirements.txt**
   ```
   pyyaml>=6.0
   # Trading Economics (check their SDK)
   # FRED: fredapi==0.5.0
   # NewsAPI: newsapi-python==0.2.7
   ```

4. **Review strategy.md with dev team**
   - Ensure everyone understands zone-based strategy
   - Agree on scope for v1
   - Assign Sprint 1 tasks

### Timeline Checkpoints

**Week 2:** Zone-based strategy produces trades in backtest  
**Week 3:** Event blocking validated  
**Week 4:** Regime adjustments visible in results  
**Week 6:** All feeds integrated and health-monitored  
**Week 7:** Walk-forward results available  
**Week 8:** Ready for paper trading dry-run

### Success Metrics

**Code quality:**
- 80%+ test coverage for new modules
- All feeds have fallback logic
- No lookahead bias in backtests

**Performance:**
- Backtest completes 2 years of data in <10 minutes
- Feed health checks don't slow down main loop
- Live bot latency <1 second per decision

**Strategy validation:**
- Zone-based strategy outperforms current Supertrend strategy
- Walk-forward shows consistent positive expectancy
- Robustness tests show strategy survives parameter shocks

---

## 10. Appendix: File Mapping

### Files You Have → Files You Need

**Data fetching:**
- ✅ `src/api/capital_client.py` → Keep as-is
- ✅ `src/data/cache_data.py` → Extend for calendar/macro cache
- ❌ Need: `src/feeds/trading_economics_adapter.py`
- ❌ Need: `src/feeds/fred_adapter.py`
- ❌ Need: `src/feeds/newsapi_adapter.py`

**Strategy:**
- ✅ `src/core/strategy.py` → Keep for legacy comparison
- ❌ Need: `src/core/zone_engine.py`
- ❌ Need: `src/core/bias_engine.py`
- ❌ Need: `src/core/trigger_engine.py`
- ❌ Need: `src/core/trade_scorer.py`
- ❌ Need: `src/core/zone_based_strategy.py`

**Backtesting:**
- ✅ `src/core/backtester.py` → Extend for multi-feed
- ❌ Need: `src/backtest/data_replay_engine.py`
- ❌ Need: `src/backtest/walkforward_runner.py`

**Live trading:**
- ✅ `src/live_trading/capital_rest.py` → Keep
- ✅ `src/live_trading/capital_websocket.py` → Keep
- ❌ Need: `src/live/live_bot.py` (new zone-based bot)

**Orchestration:**
- ❌ Need: `src/feeds/feed_manager.py`
- ❌ Need: `src/feeds/feed_health_monitor.py`
- ❌ Need: `src/feeds/event_blocker.py`
- ❌ Need: `src/feeds/regime_detector.py`

---

## Questions for Team Discussion

1. **Timeline pressure:** Is 6-8 weeks realistic? Can we parallelize?
2. **API access:** Do we have API keys for Trading Economics and FRED?
3. **Historical data:** Can we get historical headlines from NewsAPI for backtest validation?
4. **Resource allocation:** How many engineers on this? Full-time or part-time?
5. **Live deploy date:** What's the target date for live trading?
6. **v1 scope:** Agree to defer NewsAPI to v2?
7. **Testing strategy:** Unit tests only, or integration/E2E too?

---

**End of Gap Analysis**
