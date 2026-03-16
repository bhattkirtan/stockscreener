# INTRADAY TRADING STRATEGY - EVALUATION & PLAN

**Date:** March 6, 2026  
**Objective:** Convert overnight swing strategy to TRUE intraday (all positions closed same day)

---

## 1. CURRENT STATE ANALYSIS

### Current Strategy Characteristics:
- **Average Holding Time:** 12.9 hours (774 minutes)
- **Trades:** 75 over 50 days = 1.5 trades/day
- **Market Time:** 80.7% (positions held overnight)
- **TP/SL:** ATR-based (2x:4x) - WIDE targets
- **NO time-based exits**
- **NO end-of-day closing rules**

### Why Positions Stay Overnight:
1. **ATR-based TP/SL creates WIDE targets:**
   - Gold ATR on M5 ≈ $15-25
   - SL: 2x ATR = $30-50 away
   - TP: 4x ATR = $60-100 away
   - Takes 12+ hours to reach these levels

2. **No Maximum Holding Period:**
   - Strategy waits indefinitely for TP/SL
   - No forced exit after X hours

3. **No Session-Based Rules:**
   - Trades continue 24/5 without regard to sessions
   - No "close all before market close" logic

### Risks of Overnight Holdings:
⚠️ **Gap Risk:** Price jumps at market open (news, events)  
⚠️ **Liquidity Risk:** Wider spreads during off-hours  
⚠️ **Weekend Risk:** 2-day exposure to global events  
⚠️ **Psychological:** Can't monitor positions while sleeping  
⚠️ **Margin Calls:** Overnight volatility can trigger stops

---

## 2. INTRADAY TRADING PRINCIPLES (From Literature)

### Key Concepts from Trading Books:

**"Day Trading and Swing Trading the Currency Market" - Kathy Lien:**
- Close ALL positions before end of trading day
- Use time stops (max 2-4 hours for intraday)
- Trade during highest liquidity periods
- Avoid holding through major news events

**"Trading in the Zone" - Mark Douglas:**
- Define your edge clearly (ours: close same day)
- Have consistent rules (time-based exits)
- Accept small wins over unpredictable overnight gaps

**"Technical Analysis of Financial Markets" - John Murphy:**
- Intraday traders use: Tight stops, small targets, high frequency
- Position traders use: Wide stops, large targets, low frequency
- Mix the two = CONFUSION and overnight drift

### Intraday Best Practices:
1. **Maximum Trade Duration:** 2-6 hours
2. **Session Trading:** Only trade during liquid hours (London/NY overlap)
3. **Time-Based Exits:** Close positions by 4 PM ET (or equivalent)
4. **Tighter TP/SL:** Use Fixed pips (5-15) instead of ATR
5. **Quick Profit Taking:** 1:1.5 to 1:2 risk-reward
6. **No Weekend Holdings:** Flat by Friday close

---

## 3. REQUIRED STRATEGY MODIFICATIONS

### A. Add Time-Based Exit Logic (Parameterizable)

```python
class IntraDayTimeExit:
    """Force close positions that exceed max holding time."""
    
    def __init__(self, max_hours: int = 4, enabled: bool = True):
        self.max_hours = max_hours
        self.max_bars = max_hours * 12  # 12 bars per hour on M5
        self.enabled = enabled
    
    def check_time_exit(self, entry_time, current_time):
        """Check if position should be closed due to time."""
        if not self.enabled:
            return False
        hours_open = (current_time - entry_time).total_seconds() / 3600
        return hours_open >= self.max_hours
```

### B. Add End-of-Day Close Logic

```python
class EndOfDayClose:
    """Close all positions before market close."""
    
    def __init__(self, close_hour: int = 16, enabled: bool = True):  # 4 PM ET
        self.close_hour = close_hour
        self.enabled = enabled
    
    def should_close_eod(self, current_time):
        """Check if we're approaching end of day."""
        if not self.enabled:
            return False
        return current_time.hour >= self.close_hour
```

### C. Add No-Entry-Before-EOD Logic (Parameterizable)

```python
class NoEntryBeforeEOD:
    """Prevent new entries too close to EOD close."""
    
    def __init__(self, no_entry_hours_before_eod: int = 1, eod_hour: int = 16, enabled: bool = True):
        self.no_entry_hours_before_eod = no_entry_hours_before_eod
        self.eod_hour = eod_hour
        self.blackout_start_hour = eod_hour - no_entry_hours_before_eod
        self.enabled = enabled
    
    def can_enter_trade(self, current_time):
        """Returns False if in blackout window before EOD."""
        if not self.enabled:
            return True  # Always allow entry if disabled
        current_hour = current_time.hour + current_time.minute / 60.0
        return current_hour < self.blackout_start_hour
```

**Why This Matters:**
- If we close all at 4 PM but allow entry at 3:30 PM → trade only has 30 minutes!
- Opening trade at 3:30 PM → closes at 4 PM = not enough time to develop
- Need "blackout window" (1-2 hours before EOD) where NO NEW ENTRIES allowed

**Example:** EOD close = 4 PM, blackout = 1 hour:
- ✅ Can open trades before 3:00 PM
- ❌ Cannot open trades after 3:00 PM  
- 🔒 Force close all at 4:00 PM

### D. Modify TP/SL Parameters

**Current (Problematic):**
- ATR 2x:4x = $30-50 SL, $60-100 TP
- Takes 12+ hours to hit

**Proposed (Intraday):**
- Fixed Tight: 5:10, 8:15, 10:20 pips
- With pip_value=1.0 → $5-10 SL, $10-20 TP
- Should hit in 1-4 hours

### E. Add Partial Exit Logic (Scale Out)

```python
class PartialExit:
    """Exit positions gradually at multiple TP levels."""
    
    def __init__(self, enabled: bool = True, 
                 tp1_pips: float = 10, tp1_percentage: float = 0.5,
                 tp2_pips: float = 20, tp2_percentage: float = 0.5):
        self.enabled = enabled
        self.tp1_pips = tp1_pips
        self.tp1_percentage = tp1_percentage
        self.tp2_pips = tp2_pips
        self.tp2_percentage = tp2_percentage
        self.tp1_hit = False
    
    def check_partial_exit(self, entry_price, current_price, direction, position_size):
        """Check if we should partially close position."""
        if not self.enabled:
            return None, position_size
        
        pips_moved = abs(current_price - entry_price)
        
        # Check TP1 (first partial exit)
        if not self.tp1_hit and pips_moved >= self.tp1_pips:
            close_size = position_size * self.tp1_percentage
            self.tp1_hit = True
            return 'TP1', close_size
        
        # Check TP2 (remaining position)
        if self.tp1_hit and pips_moved >= self.tp2_pips:
            remaining_size = position_size * (1 - self.tp1_percentage)
            return 'TP2', remaining_size
        
        return None, position_size
```

**Benefits:**
- Lock in profits early (50% at TP1)
- Let remaining position run to larger target (TP2)
- Reduces impact of reversals
- Better risk-adjusted returns

**Example:**
- Open: 10 contracts at $2500
- TP1 @ 10 pips: Close 5 contracts (+$50)
- TP2 @ 20 pips: Close 5 contracts (+$100)
- Total: +$150 vs +$200 if all hit TP2 (but 50% secured early!)

### F. Add Session Filter (Optional)

```python
class SessionFilter:
    """Only trade during liquid sessions."""
    
    LIQUID_SESSIONS = {
        'london_ny_overlap': (13, 17),  # 1 PM - 5 PM GMT (8 AM - 12 PM ET)
        'london_open': (8, 12),         # 8 AM - 12 PM GMT (3 AM - 7 AM ET)
    }
    
    def is_liquid_session(self, current_time):
        """Check if current time is during liquid trading."""
        hour = current_time.hour
        return any(start <= hour < end for start, end in self.LIQUID_SESSIONS.values())
```

---

## 4. PROPOSED OPTIMIZATION GRID (INTRADAY FOCUSED)

### New Parameter Grid:

```python
def define_intraday_grid(self):
    """TRUE intraday grid - positions close same day."""
    return {
        # Keep proven indicators
        'supertrend_period': [7, 10],
        'supertrend_multiplier': [1.5, 2.0, 2.5],
        'sma_fast': [15, 20],
        'sma_slow': [50],
        'ema_period': [21],
        'bb_period': [20],
        'bb_std': [2.0, 2.5],
        
        # CRITICAL: Only Fixed TP/SL for tight targets - OR use partial exit
        'tp_sl_strategy': ['fixed'],  # Remove 'atr'
        
        # TIGHT stops for quick exits (1-4 hour targets)
        'sl_pips': [5, 8, 10],       # $5-10 stops
        'tp_pips': [10, 15, 20],     # $10-20 targets
        
        # Fixed pip value
        'pip_value': [1.0],
        
        # NEW: Time-based parameters (optional - test enabled/disabled)
        'enable_time_exit': [True, False],  # Test with/without time exit
        'max_holding_hours': [2, 4, 6],      # Maximum hold time
        
        'enable_eod_close': [True, False],   # Test with/without EOD close
        'end_of_day_close': [True],          # Deprecated: use enable_eod_close
        'eod_close_hour': [16],              # 4 PM close
        
        'enable_eod_blackout': [True, False], # Test with/without blackout
        'no_entry_before_eod_hours': [1, 2], # Blackout window before close
        
        # NEW: Partial exit parameters (optional - test full vs scale out) 
        'enable_partial_exit': [True, False],  # Test full exit vs partial
        'partial_exit_tp1_pips': [8, 10],     # First TP level
        'partial_exit_tp1_pct': [0.5],        # Always 50% at TP1
        'partial_exit_tp2_pips': [15, 20],    # Second TP level
        'partial_exit_tp2_pct': [0.5],        # Remaining 50% at TP2
        'session_filter': [None, 'london_ny'], # Optional session filter
    }
```

**Why Parameterize Everything:**
- `enable_time_exit: True/False` → Test impact of max holding hours
- `enable_eod_close: True/False` → Test impact of forcing EOD close
- `enable_eod_blackout: True/False` → Test impact of entry restrictions
- `enable_partial_exit: True/False` → Test full exit vs scale out (50% @ TP1, 50% @ TP2)
- Optimization finds BEST combination of features

**Feature Combinations Examples:**
1. **Pure Intraday:** All enabled (time + EOD + blackout + partial)
2. **Time Exit Only:** `enable_time_exit=True`, others False
3. **EOD Close Only:** `enable_eod_close=True`, others False  
4. **Partial Exit Focus:** `enable_partial_exit=True`, others False
5. **Current Behavior:** All disabled (baseline comparison)

**Blackout Window Options:**
- `no_entry_before_eod_hours: 1` → No new trades after 3 PM = 1h buffer
- `no_entry_before_eod_hours: 2` → No new trades after 2 PM = 2h buffer (conservative)

**Estimated Combinations:** ~2,000-3,000 (need selective testing)

**Recommended Approach:**
- **Quick Mode:** Test core parameters only (~300 combinations)
- **Intraday Mode Full:** Test all feature combinations systematically
- **Best Practice:** Run quick first, then deep-dive on best feature sets

---

## 5. STEP-BY-STEP IMPLEMENTATION PLAN

### 🎯 Overview
**Total Time:** 3-4 hours  
**Validation Points:** 10 checkpoints  
**Rollback:** Each step independent

---

### STEP 1: Add NoEntryBeforeEOD Class ⏰ 15 min

**Goal:** Prevent opening trades too close to EOD close

**File:** `src/backtesting/intracandle.py`

**Add Class:**
```python
class NoEntryBeforeEOD:
    """Blocks new entries X hours before EOD close."""
    
    def __init__(self, no_entry_hours_before_eod: int = 1, eod_hour: int = 16, enabled: bool = True):
        self.no_entry_hours_before_eod = no_entry_hours_before_eod
        self.eod_hour = eod_hour
        self.blackout_start_hour = eod_hour - no_entry_hours_before_eod
        self.enabled = enabled
    
    def can_enter_trade(self, current_time):
        """Returns False if in blackout window."""
        if not self.enabled:
            return True  # Always allow if disabled
        current_hour = current_time.hour + current_time.minute / 60.0
        return current_hour < self.blackout_start_hour
```

**Test:**
```python
# Verify: No trades open after 3 PM if blackout = 1 hour
no_entry = NoEntryBeforeEOD(no_entry_hours_before_eod=1, eod_hour=16)
assert no_entry.can_enter_trade(pd.Timestamp('2026-03-06 14:30'))  # 2:30 PM = True
assert not no_entry.can_enter_trade(pd.Timestamp('2026-03-06 15:30'))  # 3:30 PM = False
```

---

### STEP 2: Add IntraDayTimeExit Class ⏰ 15 min

**Goal:** Force close positions after max_holding_hours

**File:** `src/backtesting/intracandle.py`

**Add Class:**
```python
class IntraDayTimeExit:
    """Close position after max_holding_hours."""
    
    def __init__(self, max_hours: int = 4, enabled: bool = True):
        self.max_hours = max_hours
        self.enabled = enabled
    
    def check_time_exit(self, entry_time, current_time):
        """Returns True if position should be closed."""
        if not self.enabled:
            return False
        hours_open = (current_time - entry_time).total_seconds() / 3600
        return hours_open >= self.max_hours
```

**Test:**
```python
# Verify: Trade opened at 10 AM closes by 2 PM if max_hours = 4
time_exit = IntraDayTimeExit(max_hours=4)
entry = pd.Timestamp('2026-03-06 10:00')
current = pd.Timestamp('2026-03-06 14:05')
assert time_exit.check_time_exit(entry, current)  # Should close
```

---

### STEP 3: Add EndOfDayClose Class ⏰ 15 min

**Goal:** Force close all positions at EOD hour

**File:** `src/backtesting/intracandle.py`

**Add Class:**
```python
class EndOfDayClose:
    """Force close all positions at eod_close_hour."""
    
    def __init__(self, close_hour: int = 16, enabled: bool = True):
        self.close_hour = close_hour
        self.enabled = enabled
    
    def should_close_eod(self, current_time):
        """Returns True if we've hit EOD close hour."""
        if not self.enabled:
            return False
        return current_time.hour >= self.close_hour
```

**Test:**
```python
# Verify: Any position open at 4 PM is force-closed
eod = EndOfDayClose(close_hour=16, enabled=True)
assert eod.should_close_eod(pd.Timestamp('2026-03-06 16:00'))  # 4 PM = True
assert not eod.should_close_eod(pd.Timestamp('2026-03-06 15:50'))  # 3:50 PM = False

# Verify: Disabled = never closes
eod_disabled = EndOfDayClose(close_hour=16, enabled=False)
assert not eod_disabled.should_close_eod(pd.Timestamp('2026-03-06 16:00'))  # Disabled
```

---

### STEP 4: Add PartialExit Class ⏰ 20 min

**Goal:** Enable scale out (partial position exit at TP1 and TP2)

**File:** `src/backtesting/intracandle.py`

**Add Class:**
```python
class PartialExit:
    """Exit positions gradually at multiple TP levels."""
    
    def __init__(self, enabled: bool = True,
                 tp1_pips: float = 10, tp1_percentage: float = 0.5,
                 tp2_pips: float = 20, tp2_percentage: float = 0.5):
        self.enabled = enabled
        self.tp1_pips = tp1_pips
        self.tp1_percentage = tp1_percentage
        self.tp2_pips = tp2_pips
        self.tp2_percentage = tp2_percentage
        self.tp1_hit = False
    
    def check_partial_exit(self, entry_price, current_price, direction, position_size):
        """Check if we should partially close position."""
        if not self.enabled:
            return None, position_size
        
        pips_moved = abs(current_price - entry_price)
        
        if not self.tp1_hit and pips_moved >= self.tp1_pips:
            close_size = position_size * self.tp1_percentage
            self.tp1_hit = True
            return 'TP1', close_size
        
        if self.tp1_hit and pips_moved >= self.tp2_pips:
            remaining_size = position_size * (1 - self.tp1_percentage)
            return 'TP2', remaining_size
        
        return None, position_size
```

**Test:**
```python
# Verify: 50% closes at TP1 (10 pips), 50% at TP2 (20 pips)
partial = PartialExit(enabled=True, tp1_pips=10, tp1_pct=0.5, tp2_pips=20)
reason, size = partial.check_partial_exit(2500, 2510, 'long', 10)  # +10 pips
assert reason == 'TP1' and size == 5  # 50% of 10 contracts
```

---

### STEP 5: Update BacktestConfig ⏰ 10 min

**Goal:** Add new time-based parameters

**File:** `src/backtesting/config.py`

**Add Fields:**
```python
@dataclass
class BacktestConfig:
    # ... existing fields ...
    
    # NEW: Time-based intraday parameters (ALL OPTIONAL)
    enable_time_exit: bool = False           # Enable/disable max_holding_hours
    max_holding_hours: Optional[int] = None  # Max hours before forced exit
    
    enable_eod_close: bool = False           # Enable/disable EOD close
    eod_close_hour: int = 16                 # Hour to close all positions
    
    enable_eod_blackout: bool = False        # Enable/disable entry blackout
    no_entry_before_eod_hours: int = 1       # Blackout window size
    
    # NEW: Partial exit parameters
    enable_partial_exit: bool = False        # Enable/disable scale out
    partial_exit_tp1_pips: float = 10        # First TP level
    partial_exit_tp1_pct: float = 0.5        # % to close at TP1 (0.5 = 50%)
    partial_exit_tp2_pips: float = 20        # Second TP level
    partial_exit_tp2_pct: float = 0.5        # % to close at TP2
```

**Test:**
```python
# Verify: Config accepts new parameters
config = BacktestConfig(
    max_holding_hours=4,
    end_of_day_close=True,
    eod_close_hour=16,
    no_entry_before_eod_hours=1
)
assert config.max_holding_hours == 4
```

---

### STEP 6: Integrate Into IntraCandleBacktester ⏰ 1 hour

**Goal:** Wire all logic into main backtest loop

**File:** `src/backtesting/intracandle.py`

**Modify run() method:**
```python
def run(self, config: BacktestConfig):
    # Initialize time-based classes (optional based on config)
    time_exit = IntraDayTimeExit(
        max_hours=config.max_holding_hours, 
        enabled=config.enable_time_exit
    ) if config.max_holding_hours else None
    
    eod_close = EndOfDayClose(
        close_hour=config.eod_close_hour,
        enabled=config.enable_eod_close
    )
    
    no_entry_eod = NoEntryBeforeEOD(
        no_entry_hours_before_eod=config.no_entry_before_eod_hours,
        eod_hour=config.eod_close_hour,
        enabled=config.enable_eod_blackout
    )
    
    partial_exit = PartialExit(
        enabled=config.enable_partial_exit,
        tp1_pips=config.partial_exit_tp1_pips,
        tp1_percentage=config.partial_exit_tp1_pct,
        tp2_pips=config.partial_exit_tp2_pips,
        tp2_percentage=config.partial_exit_tp2_pct
    )
    
    for i, row in df.iterrows():
        current_time = row['timestamp']
        
        # Check partial exit first (if position open)
        if position is not None and partial_exit.enabled:
            exit_reason, close_size = partial_exit.check_partial_exit(
                position.entry_price, row['close'], position.direction, position.size
            )
            if exit_reason:
                self._partial_close_position(row, close_size, reason=exit_reason)
                if position.size == 0:  # Fully closed
                    position = None
                    continue
        
        # Check if we need to close position due to time
        if position is not None:
            if time_exit and time_exit.check_time_exit(entry_time, current_time):
                self._close_position(row, reason='TIME_EXIT')
                continue
            
            if eod_close.should_close_eod(current_time):
                self._close_position(row, reason='EOD_CLOSE')
                continue
        
        # Check if we can open new position (block entries in EOD blackout)
        if position is None and signal is not None:
            if not no_entry_eod.can_enter_trade(current_time):
                # Skip entry - in blackout window
                self._log_skipped_entry(current_time, reason='EOD_BLACKOUT')
                continue
            else:
                # Open position
                self._open_position(row, signal)
```

**Test:**
```python
# Run single backtest with time limits
config = BacktestConfig(
    max_holding_hours=4,
    end_of_day_close=True,
    eod_close_hour=16,
    no_entry_before_eod_hours=1
)
result = backtester.run(config)
# Verify: No positions held > 4 hours, all closed by 4 PM, no entries after 3 PM
```

---

### STEP 7: Create Intraday Grid ⏰ 20 min

**Goal:** Add `define_intraday_grid()` to optimizer

**File:** `src/optimization/optimize_strategy.py`

**Add Method:**
```python
def define_intraday_grid(self) -> Dict[str, List]:
    """TRUE intraday grid - positions close same day."""
    return {
        'supertrend_period': [7, 10],
        'supertrend_multiplier': [2.0, 2.5, 3.0],
        'sma_short': [10, 15, 20],
        'sma_long': [30, 50, 100],
        'ema_short': [12, 21],
        'ema_long': [50, 100],
        'bb_period': [15, 20],
        'bb_std': [1.5, 2.0, 2.5],
        
        # ONLY Fixed TP/SL (remove ATR!) - OR use partial exit
        'tp_sl_strategy': ['fixed'],
        'sl_pips': [5, 8, 10],
        'tp_pips': [10, 15, 20],
        'pip_value': [0.5, 1.0],
        
        # Time-based parameters (optional - test enabled/disabled)
        'enable_time_exit': [True, False],  # Test with/without time exit
        'max_holding_hours': [2, 4, 6],
        
        'enable_eod_close': [True, False],  # Test with/without EOD close
        'eod_close_hour': [16],
        
        'enable_eod_blackout': [True, False],  # Test with/without blackout
        'no_entry_before_eod_hours': [1, 2],
        
        # Partial exit parameters (optional)
        'enable_partial_exit': [True, False],  # Test full exit vs partial
        'partial_exit_tp1_pips': [8, 10],
        'partial_exit_tp1_pct': [0.5],  # Always 50% at TP1
        'partial_exit_tp2_pips': [15, 20],
        'partial_exit_tp2_pct': [0.5],  # Remaining 50% at TP2
        
        'volume_multiplier': [1.2, 1.5],
    }
```

**Test:**
```python
# Verify grid combinations
grid = define_intraday_grid()
combinations = list(ParameterGrid(grid))
print(f"Intraday grid: {len(combinations)} combinations")
assert 'atr' not in grid['tp_sl_strategy']  # Verify ATR removed
```

---

### STEP 7: Update run_optimization() ⏰ 10 min

**Goal:** Add intraday mode support

**File:** `src/optimization/optimize_strategy.py`

**Add Mode:**
```python
def run_optimization(self, mode: str = 'quick', parallel: bool = True):
    if mode == 'intraday':
        grid = self.define_intraday_grid()
        print("🎯 INTRADAY Optimization Mode (same-day close with EOD blackout)")
    elif mode == 'medium':
        grid = self.define_medium_grid()
    # ... etc
```

**Test:**
```bash
# Verify help shows intraday mode
python3 scripts/run-local-optimization.py --help | grep intraday
```

---

### STEP 9: Run Intraday Optimization ⏰ 5-10 min

**Goal:** Execute full intraday optimization

**Command:**
```bash
python3 scripts/run-local-optimization.py \
  --mode intraday \
  --n-jobs 12 \
  --data-file data/GOLD_M5_10000bars.csv \
  --instrument GOLD \
  --timeframe M5 \
  --capital 10000
```

**Expected Output:**
- ~400-500 combinations tested
- Completes in 5-10 minutes with 12 workers
- Results saved to `data/optimization/intraday/GOLD_M5_intraday_*.csv`

---

### STEP 10: Validate Intraday Behavior ⏰ 20 min

**Goal:** Verify trades are truly intraday

**Create:** `scripts/validate-intraday-trades.py`

```python
def validate_intraday(results_file):
    """Verify 95%+ trades close same day."""
    df = pd.read_csv(results_file)
    
    # Parse timestamps
    df['entry_date'] = pd.to_datetime(df['entry_time']).dt.date
    df['exit_date'] = pd.to_datetime(df['exit_time']).dt.date
    df['same_day'] = df['entry_date'] == df['exit_date']
    
    # Calculate metrics
    intraday_pct = (df['same_day'].sum() / len(df)) * 100
    avg_hours = df['duration_minutes'].mean() / 60
    max_hours = df['duration_minutes'].max() / 60
    
    # Check no entries in blackout
    df['entry_hour'] = pd.to_datetime(df['entry_time']).dt.hour
    entries_in_blackout = df[df['entry_hour'] >= 15].shape[0]  # After 3 PM
    
    print(f"✅ Same-day close: {intraday_pct:.1f}%")
    print(f"✅ Avg hold time: {avg_hours:.1f} hours")
    print(f"✅ Max hold time: {max_hours:.1f} hours")
    print(f"✅ Entries in blackout: {entries_in_blackout}")
    
    assert intraday_pct >= 95, f"Failed: Only {intraday_pct:.1f}% same-day"
    assert entries_in_blackout == 0, "Failed: Entries in blackout window"
    
    return True
```

---

### STEP 11: Compare Intraday vs Overnight ⏰ 20 min

**Goal:** Side-by-side performance comparison

**Update:** `scripts/analyze-capital-exposure.py`

**Add Section:**
```python
def compare_intraday_vs_overnight():
    """Compare intraday vs overnight strategies."""
    
    overnight = load_results('data/optimization/2026-03-06/GOLD_M5_all_strategies_*.csv')
    intraday = load_results('data/optimization/intraday/GOLD_M5_intraday_*.csv')
    
    comparison = pd.DataFrame({
        'Metric': ['Return %', 'Trades', 'Avg Hold (h)', 'Overnight Risk', 'Spread Cost'],
        'Overnight': [171, 75, 12.9, 'HIGH', '$37'],
        'Intraday': [intraday_return, intraday_trades, intraday_avg_hold, 'ZERO', f'${intraday_cost}']
    })
    
    print("\n" + "="*60)
    print("INTRADAY vs OVERNIGHT COMPARISON")
    print("="*60)
    print(comparison.to_string(index=False))
    
    # Recommendation
    if intraday_return >= 60:
        print("\n✅ RECOMMENDATION: Use INTRADAY (good returns + zero overnight risk)")
    else:
        print("\n⚠️  RECOMMENDATION: Consider hybrid or review risk tolerance")
```

---

### ✅ SUCCESS CRITERIA (Validation Checklist)

**Must Pass ALL:**
- [ ] 95%+ trades close same day
- [ ] Average holding time < 6 hours
- [ ] Max holding time < 12 hours
- [ ] Zero entries in EOD blackout window
- [ ] All positions force-closed by EOD hour (4 PM)
- [ ] No weekend positions
- [ ] Return > 50% over 50 days

**Nice-to-Have:**
- [ ] Return > 80%
- [ ] Average holding 2-4 hours
- [ ] Optimal blackout (1h vs 2h tested)

---

### 📊 TIMELINE SUMMARY

| Step | Task | Time | Cumulative |
|------|------|------|------------|
| 1 | NoEntryBeforeEOD class (parameterizable) | 15 min | 15 min |
| 2 | IntraDayTimeExit class (parameterizable) | 15 min | 30 min |
| 3 | EndOfDayClose class (parameterizable) | 15 min | 45 min |
| 4 | PartialExit class (scale out) | 20 min | 1h 05min |
| 5 | Update BacktestConfig (all enable flags) | 10 min | 1h 15min |
| 6 | Integrate into backtester | 1 hour | 2h 15min |
| 7 | Create intraday grid (with all params) | 20 min | 2h 35min |
| 8 | Update run_optimization() | 10 min | 2h 45min |
| 9 | Run optimization | 10 min | 2h 55min |
| 10 | Validate intraday behavior | 20 min | 3h 15min |
| 11 | Compare vs overnight | 20 min | **3h 35min** |

**NEW FEATURES ADDED:**
- ✅ All time-based features are parameterizable (enable/disable flags)
- ✅ Partial exit (scale out): 50% @ TP1, 50% @ TP2  
- ✅ Optimization tests ALL combinations to find best feature set

---

## 5B. ORIGINAL PHASE-BASED PLAN (Alternative Approach)

If you prefer larger chunks instead of 10 granular steps, here's the original:

### Phase 1: Add All Time-Based Classes
    if self.config.eod_close_hour and self.position:
        if current_time.hour >= self.config.eod_close_hour:
            self._close_position(current_row, reason='EOD_CLOSE')
```

### Phase 2: Modify Optimization Grid
**File:** `src/optimization/optimize_strategy.py`

**Add new method:**
```python
def define_intraday_grid(self) -> Dict[str, List]:
    """Intraday-focused grid with tight TP/SL and time exits."""
    return {
        # ... (from section 4 above)
    }
```

**Update run_optimization():**
```python
def run_optimization(self, mode: str = 'quick', parallel: bool = True):
    if mode == 'intraday':
        grid = self.define_intraday_grid()
        print("🎯 INTRADAY Optimization Mode (same-day close)")
    elif mode == 'quick':
        grid = self.define_quick_grid()
    # ... etc
```

### Phase 3: Run Intraday Optimization
```bash
python3 scripts/run-local-optimization.py \
  --data-file data/GOLD_M5_10000bars.csv \
  --instrument GOLD \
  --timeframe M5 \
  --mode intraday \
  --capital 10000 \
  --n-jobs 12
```

### Phase 4: Validate Intraday Behavior
**Add validation check:**
```python
def validate_intraday(trades_df):
    """Verify all trades close same day."""
    trades_df['entry_date'] = trades_df['entry_time'].dt.date
    trades_df['exit_date'] = trades_df['exit_time'].dt.date
    trades_df['same_day'] = trades_df['entry_date'] == trades_df['exit_date']
    
    intraday_pct = (trades_df['same_day'].sum() / len(trades_df)) * 100
    
    if intraday_pct < 95:
        raise ValueError(f"NOT INTRADAY: Only {intraday_pct:.1f}% close same day")
    
    return True
```

---

## 6. EXPECTED OUTCOMES

### Performance Impact (Estimated):

**Current (Overnight) Strategy:**
- Return: 171% (50 days)
- Trades: 75
- Avg Hold: 12.9 hours
- Risk: Overnight gaps

**Expected Intraday Strategy:**
- Return: **80-120%** (50 days) - LOWER but safer
- Trades: **120-200** - MORE frequent (but limited by blackout window)
- Avg Hold: **2-4 hours** - Quick exits
- Risk: **LOWER** - no overnight exposure
- **Entry Window:** Limited (no entries 1-2h before EOD close)

### Trade-offs:

| Metric | Overnight | Intraday | Impact |
|--------|-----------|----------|---------|
| Return | 171% | 80-120% | ⬇️ -40% (safer profits) |
| Trades | 75 | 120-200 | ⬆️ +60% (more activity) |
| Holding Time | 12.9h | 2-4h | ⬇️ -70% (quick turnover) |
| Gap Risk | HIGH | NONE | ✅ Eliminated |
| Spread Cost | $37 (75×$0.51) | $60-100 (200×$0.51) | ⬆️ Higher costs |
| Entry Window | 24/5 | Limited (EOD blackout) | ⬇️ Fewer opportunities |
| Sleep Quality | LOW😰 | HIGH😴 | ✅ Peace of mind |

### Why Lower Returns Are ACCEPTABLE:

1. **Risk-Adjusted:** 80% with NO overnight risk > 171% with gap risk
2. **Consistent:** Multiple small wins > few large wins with exposure
3. **Scalable:** Can increase position size with lower risk
4. **Psychological:** Sleep better knowing positions are flat
5. **Real Trading:** Most retail traders CANNOT monitor overnight

---

## 7. ALTERNATIVE: HYBRID APPROACH

If pure intraday returns are too low, consider **SMART OVERNIGHT:**

### Overnight Filter Rules:
1. **Only hold IF:**
   - Trade is in profit by +50% of target
   - No major news scheduled next 12 hours
   - Position opened during liquid session
   - Stop loss moved to breakeven

2. **Force Close IF:**
   - Still negative after 4 hours
   - Major news event coming
   - Friday after 12 PM (no weekend holds)

**Implementation:**
```python
def should_allow_overnight(position, current_time):
    """Decide if position can stay overnight."""
    # Must be profitable
    if position.unrealized_pnl < position.target_profit * 0.5:
        return False
    
    # No weekend holds
    if current_time.weekday() == 4 and current_time.hour >= 12:  # Friday after noon
        return False
    
    # Check upcoming news (would need calendar integration)
    if has_major_news_next_12h(current_time):
        return False
    
    return True
```

---

## 8. RECOMMENDED ACTION PLAN

### Immediate Next Steps:

1. **✅ Implement Time-Based Exits** (1-2 hours)
   - Add max_holding_hours parameter
   - Add eod_close_hour parameter
   - Modify backtester to respect these

2. **✅ Create Intraday Grid** (30 min)
   - Remove ATR-based TP/SL
   - Add tight Fixed TP/SL (5:10, 8:15, 10:20)
   - Add time parameters to grid

3. **✅ Run Intraday Optimization** (5-10 min)
   - Use 12 workers
   - Test ~300 combinations
   - Validate all close same day

4. **✅ Compare Results** (Review)
   - Intraday vs Overnight performance
   - Risk vs Reward analysis
   - Choose based on risk tolerance

5. **⚠️ Decision Point:**
   - **If intraday returns > 60%:** Use intraday (safer)
   - **If intraday returns < 40%:** Use hybrid (smart overnight)
   - **If overnight returns 3x better:** Consider risk vs reward

### Timeline:
- **Coding:** 2-3 hours
- **Testing:** 10-15 minutes
- **Analysis:** 30 minutes
- **Total:** 3-4 hours to complete

---

## 9. SUCCESS CRITERIA

### Intraday Strategy MUST:
- ✅ 95%+ trades close same day
- ✅ Average holding time < 6 hours
- ✅ Max holding time < 12 hours
- ✅ NO positions held over weekend
- ✅ NO positions open during major news
- ✅ Return > 50% annually (after costs)

### Nice-to-Have:
- 🎯 Return > 80% annually
- 🎯 Sharpe ratio > 0.4
- 🎯 Max drawdown < 15%
- 🎯 Win rate > 45%
- 🎯 Average holding 2-4 hours

---

## 10. CONCLUSION

**Current Strategy Issue:**
- 12.9 hour average hold = NOT intraday
- Overnight exposure = UNACCEPTABLE risk for retail trader

**Solution:**
- Add time-based exits (max 4-6 hours)
- Add EOD close (all flat by 4 PM)
- Use TIGHT Fixed TP/SL instead of wide ATR
- Accept lower returns for ZERO overnight risk

**Trade-off:**
- Lose ~40% returns (171% → 80-120%)
- Gain peace of mind, scalability, and risk control

**Quote from "Market Wizards":**
> "The best traders don't take the most risk. They take the most CONTROLLED risk."

**Let's proceed with implementation!** 🚀

---

**Next Command:**
```bash
# Shall I implement the time-based exit logic now?
# Or would you like to review the plan first?
```
