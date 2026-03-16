# Phase 1 Parameter Changes - Backup Reference

**Date:** March 7, 2026  
**Purpose:** Document parameter changes between baseline and Phase 1 optimization

---

## Overview

Phase 1 removes ineffective parameters and adds gold-specific filters to improve strategy performance.

---

## Parameters REMOVED from Grid

These parameters created duplicate strategies without affecting performance:

### 1. Bollinger Band Standard Deviation
```python
# OLD (Baseline)
'bb_std': [2.0, 2.5]

# NEW (Phase 1)
'bb_std': [2.0]  # Fixed value
```
**Reason:** BB not used in entry/exit signal logic, only for reference

### 2. Time-Based Exit
```python
# OLD (Baseline)
'enable_time_exit': [True, False]
'max_holding_hours': [4]

# NEW (Phase 1)
# REMOVED - trades naturally close < 4h
```
**Reason:** Average trade duration 2.3h, time exit never triggered

### 3. End-of-Day Close
```python
# OLD (Baseline)
'enable_eod_close': [True, False]
'eod_close_hour': [16]

# NEW (Phase 1)
# REMOVED - not helping top performers
```
**Reason:** EOD close didn't improve results; EOD blackout more effective

### 4. Partial Exit
```python
# OLD (Baseline)
'enable_partial_exit': [True, False]
'partial_exit_tp1_pips': [10]
'partial_exit_tp1_pct': [0.5]
'partial_exit_tp2_pips': [15]
'partial_exit_tp2_pct': [0.5]

# NEW (Phase 1)
# REMOVED - doesn't execute in practice
```
**Reason:** TP levels hit before partial exit triggers

---

## Parameters ADDED to Grid

Gold-specific filters to improve entry quality:

### 1. RSI Filter (Overbought/Oversold Protection)
```python
'use_rsi_filter': [True, False],
'rsi_period': [14],
'rsi_overbought': [70],
'rsi_oversold': [30],
```
**Purpose:** Prevent buying at tops (RSI > 70) or selling at bottoms (RSI < 30)  
**Expected Impact:** +5-8% win rate

### 2. ATR Volatility Filter (Extreme Volatility Protection)
```python
'use_atr_volatility_filter': [True, False],
'atr_volatility_period': [14],
'atr_sma_period': [20],
'atr_min_ratio': [0.7],
'atr_max_ratio': [1.5],
```
**Purpose:** Skip trades when ATR ratio outside 0.7-1.5 range  
**Calculation:** `atr_ratio = current_atr / sma(atr, 20)`  
**Expected Impact:** +3-5% return, reduce extreme volatility losses

### 3. Session Filter (Liquidity-Based Timing)
```python
'use_session_filter': [True, False],
'trading_sessions': ['london_ny', 'london_only'],
```
**Sessions:**
- `london_only`: 7:00-16:00 UTC (London trading hours)
- `london_ny`: 7:00-21:00 UTC (London + NY combined)
- `all`: No restrictions (when filter disabled)

**Purpose:** Trade only during liquid hours, avoid Asian low-liquidity  
**Expected Impact:** +2-4% return, reduce slippage

### 4. EOD Blackout (KEPT - Proven Effective)
```python
'enable_eod_blackout': [True, False],
'no_entry_before_eod_hours': [1],
```
**Purpose:** Prevent new entries 1 hour before market close  
**Reason:** Reduces overnight risk (64% trades had overnight exposure in baseline)

---

## Grid Size Comparison

| Version | Combinations | Run Time (12 cores) | Notes |
|---------|--------------|---------------------|-------|
| **Baseline** | 1,536 | ~4-5 hours | Many duplicates due to ineffective params |
| **Phase 1** | 1,152 | ~3-4 hours | 25% fewer, all meaningful variants |

**Phase 1 Calculation:**
- Base combos: 2 ST × 4 SMA pairs × 6 TP/SL = **48**
- Filter variants: 2 RSI × 2 ATR × 3 Session × 2 EOD = **24**
- **Total: 48 × 24 = 1,152**

---

## Backward Compatibility

**Strategy instantiation uses `.get()` with defaults:**
```python
# Old parameters have safe defaults (won't crash on old results)
enable_time_exit=params.get('enable_time_exit', False),
enable_eod_close=params.get('enable_eod_close', False),
enable_partial_exit=params.get('enable_partial_exit', False),

# New parameters also have safe defaults
use_rsi_filter=params.get('use_rsi_filter', False),
use_atr_volatility_filter=params.get('use_atr_volatility_filter', False),
use_session_filter=params.get('use_session_filter', False),
```

**This means:**
- Old optimization results can still be loaded/analyzed
- New code can run strategies with or without Phase 1 filters
- Gradual migration from baseline to Phase 1

---

## Strategy Class Changes

### New Parameters in `SupertrendVWAPStrategy.__init__`

```python
# Phase 1 filter parameters (13 new parameters)
use_rsi_filter: bool = False,
rsi_period: int = 14,
rsi_overbought: float = 70,
rsi_oversold: float = 30,
use_atr_volatility_filter: bool = False,
atr_volatility_period: int = 14,
atr_sma_period: int = 20,
atr_min_ratio: float = 0.7,
atr_max_ratio: float = 1.5,
use_session_filter: bool = False,
trading_sessions: str = 'london_ny',
```

### New Methods

**`is_trading_session(hour: int) -> bool`**
- Checks if hour (UTC) is within allowed trading sessions
- Supports: `london_only`, `london_ny`, `all`

### Modified Methods

**`calculate_indicators()`**
- Now calculates RSI if `use_rsi_filter=True`
- Now calculates ATR ratio if `use_atr_volatility_filter=True`
- Adds `hour` column if `use_session_filter=True`

**`generate_signals()`**
- Applies RSI filter before entry (skip if overbought/oversold)
- Applies ATR volatility filter before entry (skip if ratio outside range)
- Applies session filter before entry (skip if outside trading hours)

---

## Baseline Results (For Reference)

**Run:** `run_20260307_103606`  
**Data:** Oct 28, 2025 - Mar 6, 2026 (24,987 bars, 70/30 train/test)

**Top Strategy:** `rank01_ST3.0_SMA15-30_BB2.0_PIP1_ATR2x4`
- Train Return: **44.86%**
- Test Return: **78.18%**
- Win Rate: **41.8%**
- Sharpe: **0.18**
- Max Drawdown: **29.12%**
- Total Trades: **55** (35 overnight)

**Issues Identified:**
1. Top 20 strategies have only 5 unique performance levels (duplicates)
2. Low win rate (41.8%) - losing more trades than winning
3. 64% trades with overnight exposure
4. No filtering for overbought/oversold conditions
5. No filtering for extreme volatility spikes
6. Trading during low-liquidity Asian session

---

## Phase 1 Expected Results

**Target Improvements:**
- Train Return: **52-58%** (+16-29%)
- Test Return: **70-90%** (stable or better)
- Win Rate: **48-54%** (+6-12%)
- Sharpe: **0.22-0.26** (+22-44%)
- Max Drawdown: **22-26%** (-24% to -11%)

**Validation Criteria:**
- ✅ Meets target if train return ≥ 52%
- ✅ Meets target if win rate ≥ 48%
- ✅ Meets target if Sharpe ≥ 0.22
- ✅ Meets target if max drawdown ≤ 26%
- ✅ Meets target if trade count ≥ 45

---

## Files Modified

1. **src/optimization/optimize_strategy.py**
   - `get_intraday_focused_grid()`: Removed 4 params, added 3 filters
   - `generate_combinations()`: Updated to handle Phase 1 filters
   - `run_single_backtest_on_data()`: Pass Phase 1 params to strategy (2 locations)

2. **src/core/strategy.py**
   - `SupertrentVWAPStrategy.__init__`: Added 13 Phase 1 parameters
   - `is_trading_session()`: New method for session filtering
   - `calculate_indicators()`: Calculate RSI, ATR ratio, hour
   - `generate_signals()`: Apply RSI, ATR, session filters before entry

3. **docs/PHASE1_IMPLEMENTATION.md**
   - Complete implementation guide and testing plan

4. **docs/PHASE1_PARAMETER_CHANGES.md** (this file)
   - Backup reference for parameter changes

---

## Recovery Instructions

If Phase 1 results are worse than baseline:

1. **Revert to Baseline Grid:**
   ```python
   # In get_intraday_focused_grid(), change:
   'use_rsi_filter': [False],  # Disable
   'use_atr_volatility_filter': [False],  # Disable
   'use_session_filter': [False],  # Disable
   ```

2. **Or Restore Old Parameters:**
   ```python
   # Add back removed parameters to grid
   'enable_time_exit': [True, False],
   'max_holding_hours': [4],
   'enable_eod_close': [True, False],
   'eod_close_hour': [16],
   'enable_partial_exit': [True, False],
   # ... etc
   ```

3. **Or Use Baseline Results:**
   - Latest baseline: `data/optimization/2026-03-07/run_20260307_103606/`
   - Best strategy: rank01 (44.86% train, 78.18% test)

---

## Next Steps After Phase 1

**If Phase 1 successful (52-58% return achieved):**

**Phase 2 Additions:**
1. ADX Trend Filter (only trade strong trends, ADX > 25)
2. BB Position Sizing (larger positions at BB extremes)
3. Vol-Adjusted TP/SL (dynamic targets based on ATR)

**Expected Phase 2 Results:**
- Return: 62-72%
- Win rate: 52-58%
- Sharpe: 0.28-0.35

**Phase 3 Additions:**
1. Multi-timeframe confirmation (15M + 1H)
2. Support/Resistance levels
3. Divergence detection

**Expected Phase 3 Results:**
- Return: 75-95%
- Win rate: 56-62%
- Sharpe: 0.35-0.45
