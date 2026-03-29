# Backtester vs Bot Feature Comparison

**Date:** March 28, 2026  
**Purpose:** Ensure feature parity between backtester (cloud-function) and live bot (trading-bot-skills)

---

## Executive Summary

✅ **PHASE 1 COMPLETE:** Reversal logic + time-based exits implemented AND tested  
⏸️ **PHASE 2 PENDING:** Trailing stops + NoEntryBeforeEOD filter  
📊 **TEST COVERAGE:** 28 new tests (14 reversal + 14 time-based exits) - ALL PASSING  

---

## 1. Reversal Logic (Close Opposite Position)

### Status: ✅ COMPLETE (Implemented + Tested)

| Feature | Backtester (cloud-function) | Bot (trading-bot-skills) | Status |
|---------|----------------------------|--------------------------|--------|
| Detect reverse signal | ✅ `signal_engine.check_reverse_signal()` | ✅ `production_orchestrator._check_reverse_signals()` | ✅ MATCH |
| Close opposite position | ✅ `backtester.py` lines 998-999, 1124-1125 | ✅ `production_orchestrator.py` lines 409-413 | ✅ MATCH |
| Bypass cooldown | ✅ `signal_engine.check_cooldown()` lines 393-395 | ✅ `risk_skill._check_cooldown()` line 277 | ✅ MATCH |
| Unit tests | ✅ `validate_reverse_signals_fast.py` | ✅ `test_reversal_logic.py` (14 tests) | ✅ COMPLETE |
| Integration tests | ✅ Multiple validation scripts | ✅ Included in test suite | ✅ COMPLETE |

**Test Coverage (14 tests - ALL PASSING):**
- `TestReversalDetection`: BUY↔SELL detection (5 tests)
- `TestCooldownBypass`: Cooldown bypass logic (3 tests)
- `TestReversalIntegration`: Full reversal flow (2 tests)
- `TestReversalErrorHandling`: Error scenarios (2 tests)
- `TestBacktesterParity`: Consistency checks (2 tests)

**Action Items:**
- ✅ Reversal logic working in ProductionOrchestrator
- ✅ Unit tests added: `tests/unit/test_reversal_logic.py`
- ✅ Integration tests for BUY→SELL and SELL→BUY scenarios
- ✅ Cooldown bypass verified against backtester

---

## 2. Trailing Stop Loss

### Status: ❌ MISSING IN BOT

| Feature | Backtester | Bot | Status |
|---------|-----------|-----|--------|
| Break-even trailing | ✅ `PositionManager` with `TrailingStopConfig` | ❌ **NOT IMPLEMENTED** | ❌ GAP |
| Step-based trailing | ✅ Move X pips after Y pips profit | ❌ **NOT IMPLEMENTED** | ❌ GAP |
| PositionTracker | ✅ Tracks highest/lowest prices | ❌ **NOT IMPLEMENTED** | ❌ GAP |

**Backtester Implementation:**
```python
# cloud-function/src/core/position_manager.py
class TrailingStopConfig:
    breakeven_enabled: bool = False
    breakeven_trigger_pips: float = 0.0
    step_trailing_enabled: bool = False
    trail_step_pips: float = 0.0
    trail_move_pips: float = 0.0

class PositionTracker:
    highest_price_reached: float
    lowest_price_reached: float
    last_trail_level: int
    breakeven_applied: bool

class PositionManager:
    def calculate_trailing_stop(tracker, current_price) -> (new_sl, should_update)
```

**Action Items:**
- ❌ **TODO:** Port `PositionManager`, `PositionTracker`, `TrailingStopConfig` to bot
- ❌ **TODO:** Add trailing stop logic to execution skill or create new skill
- ❌ **TODO:** Update SL via Capital.com API when trailing triggers
- ❌ **TODO:** Add tests for trailing stop scenarios

---

## 3. Time-Based Filters & Exits

### Status: ⚠️ PHASE 1 COMPLETE, PHASE 2 PENDING

| Feature | Backtester | Bot | Status |
|---------|-----------|-----|--------|
| **Entry Filters** | | | |
| NoEntryBeforeEOD | ✅ Block entries X hours before EOD | ❌ **PHASE 2** | ⏸️ TODO |
| FridayFilter | ✅ Block entries Friday after cutoff | ✅ RiskSkill has `friday_no_new_trades_hour` | ✅ MATCH |
| Weekend blocking | ✅ Implicit in trading hours | ✅ RiskSkill `saturday_enabled`, `sunday_enabled` | ✅ MATCH |
| **Exit Filters** | | | |
| IntraDayTimeExit | ✅ Force close after max hours | ✅ `IntraDayTimeExit` class (4 hours default) | ✅ COMPLETE |
| EndOfDayClose | ✅ Force close at EOD hour | ✅ `EndOfDayClose` class (16:00 UTC default) | ✅ COMPLETE |
| Unit tests | ✅ Validation scripts | ✅ `test_time_based_exits.py` (14 tests) | ✅ COMPLETE |

**Test Coverage (14 tests - ALL PASSING):**
- `TestIntraDayTimeExit`: Max hours logic (4 tests)
- `TestEndOfDayClose`: EOD closure logic (4 tests)
- `TestTimeBasedExitsIntegration`: Orchestrator integration (4 tests)
- `TestTimeExitErrorHandling`: Error scenarios (2 tests)

**Configuration:**
```yaml
time_based_exits:
  max_hours: 4              # IntraDayTimeExit: Close positions > 4 hours old
  intraday_enabled: true
  eod_hour: 16              # EndOfDayClose: Close all at 4 PM UTC
  eod_enabled: true
```

**Action Items:**
- ✅ IntraDayTimeExit implemented and tested
- ✅ EndOfDayClose implemented and tested
- ✅ Integrated into monitoring loop (60s checks)
- ⏸️ **PHASE 2:** Add NoEntryBeforeEOD filter
| EndOfDayClose | ✅ Force close at EOD hour | ❌ **MISSING** | ❌ GAP |

**Backtester Implementation:**
```python
# cloud-function/src/core/backtester.py
class NoEntryBeforeEOD:
    def __init__(self, no_entry_hours_before_eod: int = 1, eod_hour: int = 16):
        self.blackout_start_hour = eod_hour - no_entry_hours_before_eod

class IntraDayTimeExit:
    def __init__(self, max_hours: int = 4):
        self.max_hours = max_hours
    
    def check_time_exit(self, entry_time, current_time):
        hours_open = (current_time - entry_time).total_seconds() / 3600
        return hours_open >= self.max_hours

class EndOfDayClose:
    def should_close_eod(self, current_time):
        return current_time.hour >= self.close_hour
```

**Action Items:**
- ❌ **TODO:** Add `NoEntryBeforeEOD` filter to RiskSkill (e.g., `no_entry_hours_before_eod = 1`)
- ❌ **TODO:** Add `IntraDayTimeExit` - create monitoring task to close positions after max hours
- ❌ **TODO:** Add `EndOfDayClose` - create monitoring task to close all positions at EOD
- ❌ **TODO:** Add tests for time-based filters

---

## 4. Partial Exits (TP1/TP2)

### Status: ❌ MISSING IN BOT

| Feature | Backtester | Bot | Status |
|---------|-----------|-----|--------|
| TP1 partial exit | ✅ Close X% at TP1 pips | ❌ **NOT IMPLEMENTED** | ❌ GAP |
| TP2 partial exit | ✅ Close remaining at TP2 pips | ❌ **NOT IMPLEMENTED** | ❌ GAP |
| Position size tracking | ✅ Tracks remaining size | ❌ **NOT IMPLEMENTED** | ❌ GAP |

**Backtester Implementation:**
```python
# cloud-function/src/core/backtester.py
class PartialExit:
    def __init__(self, tp1_pips=10, tp1_percentage=0.5, tp2_pips=20, tp2_percentage=0.5):
        self.tp1_pips = tp1_pips
        self.tp1_percentage = tp1_percentage
        self.tp2_pips = tp2_pips
        self.tp2_percentage = tp2_percentage
    
    def check_partial_exit(self, entry_price, current_price, direction, position_size):
        if pips_moved >= self.tp1_pips and not self.tp1_hit:
            close_size = position_size * self.tp1_percentage
            return 'TP1', close_size
```

**Action Items:**
- ❌ **TODO:** Add `PartialExit` configuration to ExecutionSkill
- ❌ **TODO:** Monitor price movements and close partial positions at TP1/TP2
- ❌ **TODO:** Update Capital.com API integration to support partial closes
- ❌ **TODO:** Track remaining position size after partial close
- ❌ **TODO:** Add tests for partial exit scenarios

---

## 5. Transaction Costs

### Status: ✅ IMPLEMENTED

| Feature | Backtester | Bot | Status |
|---------|-----------|-----|--------|
| Spread calculation | ✅ `GOLD_COST_CONFIG` | ✅ ExecutionSkill lines 78-82 | ✅ MATCH |
| Slippage calculation | ✅ Included in backtester | ✅ Included in ExecutionSkill | ✅ MATCH |
| Cost tracking | ✅ Tracked per trade | ✅ Tracked per trade | ✅ MATCH |

**Action Items:**
- ✅ Transaction costs already implemented consistently

---

## 6. Position State Management

### Status: ✅ IMPLEMENTED

| Feature | Backtester | Bot | Status |
|---------|-----------|-----|--------|
| Open position tracking | ✅ `self.open_positions` list | ✅ `PositionStateManager` | ✅ MATCH |
| Position state | ✅ Trade dataclass | ✅ `Position` dataclass | ✅ MATCH |
| Position closure | ✅ `close_position()` | ✅ `close_position()` | ✅ MATCH |
| Persistence | ✅ In-memory (backtester) | ✅ Firestore (live bot) | ✅ MATCH |

**Action Items:**
- ✅ Position state management already working

---

## 7. Risk Management

### Status: ✅ IMPLEMENTED (Bot has MORE features)

| Feature | Backtester | Bot | Status |
|---------|-----------|-----|--------|
| Cooldown period | ✅ 15min SL, 5min TP | ✅ RiskSkill with same settings | ✅ MATCH |
| Trading hours | ✅ Implicit | ✅ RiskSkill with configurable hours | ✅ ENHANCED |
| Circuit breakers | ❌ Not in backtester | ✅ Daily/weekly loss limits | ✅ ENHANCED |
| Session filtering | ❌ Not in backtester | ✅ LONDON/NEW_YORK only | ✅ ENHANCED |
| News kill switch | ❌ Not in backtester | ✅ Block trades on news | ✅ ENHANCED |
| Position sizing | ✅ Fixed size | ✅ Percentage-based | ✅ MATCH |

**Action Items:**
- ✅ Bot has MORE risk features than backtester (this is good!)

---

## 8. Event-Driven Architecture

### Status: ✅ IMPLEMENTED

| Feature | Backtester | Bot | Status |
|---------|-----------|-----|--------|
| Event bus | ❌ Not event-driven | ✅ EventBus with 10+ event types | ✅ ENHANCED |
| Skill decoupling | ❌ Monolithic | ✅ Skills subscribe to events | ✅ ENHANCED |
| Idempotency | ❌ Not needed | ✅ IdempotencyManager | ✅ ENHANCED |
| Retry policy | ❌ Not needed | ✅ RetryPolicy with backoff | ✅ ENHANCED |

**Action Items:**
- ✅ Bot architecture is MORE robust than backtester

---

## Priority Action Items

### ✅ PHASE 1 COMPLETE (HIGH PRIORITY)

1. ✅ **Reversal Logic** - Implemented AND tested
   - ✅ Added unit tests: `tests/unit/test_reversal_logic.py` (14 tests)
   - ✅ Added integration tests for BUY→SELL and SELL→BUY scenarios
   - ⏸️ Verify in production with paper trading

2. ✅ **IntraDayTimeExit** - Force close after max hours
   - ✅ Created `IntraDayTimeExit` class in ProductionOrchestrator
   - ✅ Closes positions after 4 hours (configurable)
   - ✅ Added unit tests: `tests/unit/test_time_based_exits.py` (14 tests)
   - ✅ Integrated into monitoring loop (60s checks)

3. ✅ **EndOfDayClose** - Force close at EOD
   - ✅ Created `EndOfDayClose` class in ProductionOrchestrator
   - ✅ Closes all positions at 16:00 UTC (configurable)
   - ✅ Takes priority over IntraDayTimeExit
   - ✅ Added unit tests (included in test_time_based_exits.py)

**Phase 1 Test Coverage: 28 tests - ALL PASSING ✅**

### ⏸️ PHASE 2 PENDING (MEDIUM PRIORITY)

4. ❌ **Trailing Stop Loss** - Break-even and step-based
   - Port `PositionManager`, `PositionTracker`, `TrailingStopConfig`
   - Create new skill or add to ExecutionSkill
   - Update SL via Capital.com API
   - Test with paper trading first

5. ❌ **NoEntryBeforeEOD** - Block entries before EOD
   - Add to RiskSkill (e.g., `no_entry_hours_before_eod = 1`)
   - Align with backtester's blackout window
   - Test with Friday trading

### LOW PRIORITY (Advanced Features)

6. ❌ **Partial Exits** - TP1/TP2 with percentage closes
   - Add to ExecutionSkill
   - Monitor price movements for TP1/TP2 levels
   - Update Capital.com API integration
   - Test thoroughly before production

---

## Testing Requirements

### ✅ Phase 1 Test Coverage (28 tests - ALL PASSING)

1. ✅ **Reversal scenarios:**
   - ✅ `test_buy_to_sell_reversal_detected()` - Holding BUY + SELL signal
   - ✅ `test_sell_to_buy_reversal_detected()` - Holding SELL + BUY signal
   - ✅ `test_cooldown_bypassed_for_opposite_direction()` - Reversal bypasses cooldown
   - ✅ `test_full_reversal_flow_buy_to_sell()` - Complete integration test
   - ✅ 10 additional reversal tests (error handling, backtester parity)

2. ✅ **Time-based filters:**
   - ✅ `test_intraday_time_exit_closes_old_position()` - 4+ hours → Closed
   - ✅ `test_intraday_time_exit_ignores_fresh_position()` - < 4 hours → Not closed
   - ✅ `test_eod_close_closes_all_positions()` - At 16:00 UTC → All closed
   - ✅ `test_before_eod_hour_no_close()` - Before 16:00 → Not closed
   - ✅ 10 additional time-based tests (disable flags, error handling)

### ⏸️ Missing Test Coverage (Phase 2/3)

3. ❌ **Trailing stops:**
   - `test_breakeven_trailing_stop()`
   - `test_step_based_trailing_stop()`

4. ❌ **Partial exits:**
   - `test_tp1_partial_close()`
   - `test_tp2_final_close()`

5. ❌ **NoEntryBeforeEOD filter:**
   - `test_no_entry_before_eod()`

---

## Recommendation

**✅ Phase 1 COMPLETE (CRITICAL - DONE):**
1. ✅ Add tests for existing reversal logic (14 tests passing)
2. ✅ Implement IntraDayTimeExit (force close after 4 hours)
3. ✅ Implement EndOfDayClose (force close at 4 PM UTC)
4. ⏸️ Test in paper trading for 1 week

**⏸️ Phase 2 (PROFIT OPTIMIZATION - NEXT):**
5. ❌ Implement trailing stop loss (break-even first, then step-based)
6. ❌ Add NoEntryBeforeEOD filter
7. ⏸️ Backtest new features against historical data
8. ⏸️ Compare results with cloud-function backtester

**⏸️ Phase 3 (ADVANCED - FUTURE):**
9. ❌ Implement partial exits if results show benefit
10. ⏸️ Optimize parameters based on live trading data

---

## Files to Review

### Backtester (cloud-function)
- ✅ `src/core/signal_engine.py` - Reversal detection logic
- ✅ `src/core/backtester.py` - Main backtest logic with reversals
- ✅ `src/core/position_manager.py` - Trailing stop logic
- ✅ `check_exit_signal.py` - Reversal validation script

### Bot (trading-bot-skills)
- ✅ `orchestrator/production_orchestrator.py` - Reversal logic (lines 377-432)
- ✅ `skills/risk/risk_skill.py` - Cooldown bypass (line 277)
- ✅ `skills/execution/execution_skill.py` - Order execution and close_position()
- ❌ `tests/` - Missing reversal tests

---

## Conclusion

**✅ Phase 1 Status:** COMPLETE  
- Reversal Logic: ✅ IMPLEMENTED + TESTED (14 tests)
- Time-Based Exits: ✅ IMPLEMENTED + TESTED (14 tests)
- Test Coverage: **28 tests - ALL PASSING**

**Critical Features Now Working:**
- ✅ BUY↔SELL reversal detection
- ✅ Opposite position closure
- ✅ Cooldown bypass for reversals
- ✅ IntraDayTimeExit (4 hour max holding)
- ✅ EndOfDayClose (16:00 UTC cutoff)

**⏸️ Phase 2 Features Pending:**
- ❌ Trailing stop loss (break-even + step-based)
- ❌ NoEntryBeforeEOD filter

**⏸️ Phase 3 Features Pending:**
- ❌ Partial exits (TP1/TP2)

**Next Steps:**
1. Deploy Phase 1 features to paper trading
2. Monitor for 1 week to validate behavior
3. Start Phase 2 implementation (trailing stops)

**Risk Assessment:**
- Bot now has CRITICAL risk management features (time exits)
- Gold trading safer (no overnight exposure)
- Reversal logic matches backtester exactly
- Ready for paper trading validation  
**Other Gaps:** ⚠️ Missing 5 important features (IntraDayTimeExit, EndOfDayClose, TrailingStops, NoEntryBeforeEOD, PartialExits)  
**Next Steps:** Add tests first, then implement time-based exits (HIGH PRIORITY)

The bot has a more robust architecture than the backtester (event-driven, idempotency, circuit breakers), but is missing some trading logic that the backtester has. Priority should be on time-based exits to avoid overnight risk in Gold trading.
