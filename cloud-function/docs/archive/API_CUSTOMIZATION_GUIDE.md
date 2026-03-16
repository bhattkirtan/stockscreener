# 🎯 Strategy Optimizer API - Full Customization Guide

## Overview

The enhanced API exposes **ALL** strategy parameters for complete UI control. Users can run quick optimizations with defaults or dive deep into custom parameter ranges.

## API Endpoint

```
POST https://optimize-api-6ovej2yaoa-uc.a.run.app/optimize
```

## Request Models

### Quick Start (Minimal Request)

Use defaults for fast optimization:

```json
{
  "instrument": "GOLD",
  "timeframe": "M5",
  "initial_capital": 10000,
  "position_size": 0.1,
  "mode": "quick"
}
```

This uses smart defaults and tests **~500 combinations** in **2-3 minutes**.

---

## Full Customization Options

### 1. Core Settings

```json
{
  "instrument": "GOLD",           // GOLD, EURUSD, GBPUSD, US100, etc
  "timeframe": "M5",              // M5, M15, H1, H4, D1
  "initial_capital": 10000.0,     // Starting capital (100-1000000)
  "position_size": 10.0,          // Default position size in lots
  "mode": "quick",                // "quick" | "medium" | "full"
  "parallel": true,               // Use parallel processing
  "n_jobs": -1                    // CPU cores (-1 = all)
}
```

**Modes**:
- `quick`: ~500 combinations, 2-3 min ⚡
- `medium`: ~2000 combinations, 5-8 min ⚙️
- `full`: ~10000 combinations, 15-30 min 🔥

---

### 2. Strategy Indicators (Override Ranges)

#### Supertrend
```json
{
  "supertrend_periods": [7, 10, 14],          // ATR period (default: [10])
  "supertrend_multipliers": [2.0, 2.5, 3.0]   // ATR multiplier (default: [2.0, 2.5, 3.0])
}
```

#### Moving Averages
```json
{
  "sma_fast_periods": [15, 20, 25],     // Fast SMA (default: [15, 20])
  "sma_slow_periods": [40, 50, 60],     // Slow SMA (default: [50])
  "ema_periods": [18, 21, 25]           // EMA (default: [21])
}
```

**Constraint**: `sma_fast` < `sma_slow` (automatically filtered)

#### Bollinger Bands
```json
{
  "bb_periods": [18, 20, 22],           // BB period (default: [20])
  "bb_stds": [1.8, 2.0, 2.2, 2.5]       // Std deviations (default: [2.0, 2.5])
}
```

---

### 3. Take Profit / Stop Loss Strategy

#### Choose TP/SL Type
```json
{
  "tp_sl_strategy": "both"    // "fixed" | "atr" | "both"
}
```

#### Fixed TP/SL (Pip Distance)
```json
{
  "sl_pips_range": [15, 20, 25, 30],         // Stop loss in pips
  "tp_pips_range": [30, 40, 50, 60, 75]      // Take profit in pips
}
```

**Risk/Reward Examples**:
- SL: 20, TP: 40 → 1:2 RR
- SL: 25, TP: 75 → 1:3 RR
- SL: 30, TP: 90 → 1:3 RR

**Constraint**: `tp_pips` > `sl_pips` (automatically filtered)

#### ATR-Based Dynamic TP/SL
```json
{
  "atr_sl_multipliers": [1.5, 2.0, 2.5],     // Stop loss = ATR × multiplier
  "atr_tp_multipliers": [3.0, 4.0, 5.0, 6.0] // Take profit = ATR × multiplier
}
```

**Example**: If ATR = 10 pips:
- SL: 2.0 × 10 = 20 pips
- TP: 5.0 × 10 = 50 pips (1:2.5 RR)

**Advantage**: Adapts to market volatility automatically

**Constraint**: `atr_tp_multiplier` > `atr_sl_multiplier`

---

### 4. Pip Value Optimization (Leverage Scaling)

```json
{
  "pip_values": [1.0, 1.5, 2.0, 2.5, 3.0, 5.0]
}
```

**What is pip_value?**
- Multiplier for position sizing
- Higher values = aggressive leverage usage
- Lower values = conservative risk

**Examples**:
- `1.0` → Standard position size
- `2.0` → 2x leverage
- `5.0` → 5x leverage (high risk/reward)

**Use Case**: Find optimal leverage for max profit vs acceptable risk

---

### 5. Advanced Filters

Filter out strategies that don't meet criteria:

```json
{
  "min_trades": 10,              // Minimum number of trades (default: 10)
  "min_win_rate": 0.45,          // Minimum win rate (0-1, default: 0)
  "max_drawdown_pct": 30.0       // Maximum acceptable drawdown %
}
```

---

### 6. Data Selection

Override automatic CSV file selection:

```json
{
  "csv_filename": "GOLD_M5_5000bars.csv",   // Custom CSV file
  "max_bars": 3000                           // Use only first N bars
}
```

**Auto-selection** (if not specified):
- M5: Uses `{instrument}_M5_5000bars.csv`
- M15: Uses `{instrument}_M15_10000bars.csv`

---

## Complete Example Requests

### Example 1: Conservative Gold Strategy (High Win Rate)

```json
{
  "instrument": "GOLD",
  "timeframe": "M5",
  "initial_capital": 10000,
  "position_size": 5.0,
  "mode": "medium",
  
  "supertrend_multipliers": [2.5, 3.0, 3.5],
  "sma_fast_periods": [20, 25],
  "sma_slow_periods": [50, 60],
  
  "tp_sl_strategy": "atr",
  "atr_sl_multipliers": [2.0, 2.5, 3.0],
  "atr_tp_multipliers": [4.0, 5.0, 6.0],
  
  "pip_values": [1.0, 1.5, 2.0],
  "min_win_rate": 0.50,
  "max_drawdown_pct": 20.0
}
```

**Goal**: Find strategies with 50%+ win rate and <20% drawdown

---

### Example 2: Aggressive EUR/USD Scalping

```json
{
  "instrument": "EURUSD",
  "timeframe": "M5",
  "initial_capital": 10000,
  "position_size": 10.0,
  "mode": "full",
  
  "supertrend_periods": [7, 10],
  "supertrend_multipliers": [1.5, 2.0, 2.5],
  "sma_fast_periods": [10, 15, 20],
  "sma_slow_periods": [40, 50],
  
  "tp_sl_strategy": "fixed",
  "sl_pips_range": [10, 15, 20],
  "tp_pips_range": [20, 30, 40, 50],
  
  "pip_values": [3.0, 5.0, 7.5, 10.0],
  "min_trades": 20
}
```

**Goal**: Maximum profit with high leverage, more trades

---

### Example 3: Test Both TP/SL Strategies (Comprehensive)

```json
{
  "instrument": "GOLD",
  "timeframe": "M15",
  "initial_capital": 10000,
  "position_size": 10.0,
  "mode": "full",
  
  "tp_sl_strategy": "both",
  
  "sl_pips_range": [15, 20, 25, 30],
  "tp_pips_range": [30, 40, 50, 60, 75, 90],
  
  "atr_sl_multipliers": [1.5, 2.0, 2.5],
  "atr_tp_multipliers": [3.0, 4.0, 5.0, 6.0],
  
  "pip_values": [1.0, 1.5, 2.0, 2.5, 3.0, 5.0]
}
```

**Result**: Tests **thousands** of combinations to find absolute best

---

## Response Examples

### Success (202 Accepted - Queued)

```json
{
  "run_id": "a7f3c91b",
  "status": "queued",
  "estimated_combinations": 2340,
  "task_name": "projects/.../tasks/12345"
}
```

### Check Status (GET /optimize/{run_id})

```json
{
  "run_id": "a7f3c91b",
  "status": "running",
  "instrument": "GOLD",
  "timeframe": "M5",
  "mode": "medium",
  "created_at": "2026-03-05T10:30:00",
  "started_at": "2026-03-05T10:30:15",
  "estimated_combinations": 2340,
  "tested_combinations": 850,
  "progress": {
    "percent": 36,
    "current_best_return": 45.2
  }
}
```

### Completed Results

```json
{
  "run_id": "a7f3c91b",
  "status": "completed",
  "completed_at": "2026-03-05T10:37:22",
  "results": {
    "total_combinations": 2340,
    "valid_strategies": 1847,
    "best_strategy": {
      "rank": 1,
      "return_pct": 67.5,
      "total_pnl": 6750.0,
      "sharpe_ratio": 2.8,
      "win_rate": 0.58,
      "total_trades": 45,
      "profit_factor": 2.4,
      "max_drawdown_pct": 12.3,
      "params": {
        "supertrend_period": 10,
        "supertrend_multiplier": 2.5,
        "sma_fast": 20,
        "sma_slow": 50,
        "ema_period": 21,
        "tp_sl_strategy": "atr",
        "atr_sl_multiplier": 2.0,
        "atr_tp_multiplier": 5.0,
        "pip_value": 2.5
      }
    },
    "top_10_strategies": [...],
    "execution_time_seconds": 432.5
  }
}
```

---

## UI Integration Examples

### Basic Form

```html
<select name="instrument">
  <option value="GOLD">Gold</option>
  <option value="EURUSD">EUR/USD</option>
</select>

<select name="timeframe">
  <option value="M5">5 Minutes</option>
  <option value="M15">15 Minutes</option>
</select>

<input type="number" name="initial_capital" value="10000" />
<input type="number" name="position_size" value="0.1" step="0.01" />

<select name="mode">
  <option value="quick">Fast (~2 min)</option>
  <option value="medium">Medium (~5 min)</option>
  <option value="full">Full (~30 min)</option>
</select>
```

### Advanced Parameters (Collapsible Section)

```html
<details>
  <summary>⚙️ Advanced Parameters</summary>
  
  <h4>Supertrend</h4>
  <input type="text" name="supertrend_periods" placeholder="7,10,14" />
  <input type="text" name="supertrend_multipliers" placeholder="2.0,2.5,3.0" />
  
  <h4>Moving Averages</h4>
  <input type="text" name="sma_fast_periods" placeholder="15,20,25" />
  <input type="text" name="sma_slow_periods" placeholder="40,50,60" />
  
  <h4>TP/SL Strategy</h4>
  <select name="tp_sl_strategy">
    <option value="both">Test Both</option>
    <option value="fixed">Fixed Pips</option>
    <option value="atr">ATR-Based</option>
  </select>
  
  <h4>Pip Value (Leverage)</h4>
  <input type="text" name="pip_values" placeholder="1.0,2.0,3.0,5.0" />
</details>
```

### JavaScript Submit

```javascript
async function startOptimization() {
  const request = {
    instrument: document.querySelector('[name=instrument]').value,
    timeframe: document.querySelector('[name=timeframe]').value,
    initial_capital: parseFloat(document.querySelector('[name=initial_capital]').value),
    position_size: parseFloat(document.querySelector('[name=position_size]').value),
    mode: document.querySelector('[name=mode]').value,
    
    // Parse advanced params if provided
    supertrend_periods: parseArray('[name=supertrend_periods]'),
    pip_values: parseArray('[name=pip_values]'),
    // ... other fields
  };
  
  const response = await fetch('https://optimize-api-6ovej2yaoa-uc.a.run.app/optimize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request)
  });
  
  const result = await response.json();
  console.log('Optimization started:', result.run_id);
  
  // Poll for status
  pollStatus(result.run_id);
}

function parseArray(selector) {
  const input = document.querySelector(selector)?.value;
  if (!input) return null;
  return input.split(',').map(v => parseFloat(v.trim())).filter(v => !isNaN(v));
}
```

---

## Best Practices

### 1. Start Simple
- Use `mode: "quick"` with defaults
- Add custom params gradually
- Avoid testing everything at once

### 2. Realistic Constraints
- Set `min_trades: 10+` to avoid lucky streaks
- Set `min_win_rate: 0.45+` for realistic strategies
- Set `max_drawdown_pct: 30` to avoid high-risk strategies

### 3. Timeframe-Specific Tuning
**M5 (5-minute)**:
- Shorter SMA periods (10-30)
- Tighter TP/SL (10-40 pips)
- More trades expected

**M15+ (15-minute+)**:
- Longer SMA periods (20-100)
- Wider TP/SL (20-100 pips)
- Fewer, higher-quality trades

### 4. Leverage Testing
- Start with `pip_values: [1.0, 1.5, 2.0]`
- Increase gradually if drawdown acceptable
- Never test beyond your risk tolerance

---

## Cost Estimate Optimization:

| Mode | Combinations | Time | Cost |
|------|--------------|------|------|
| Quick | ~500 | 2-3 min | ~$0.02 |
| Medium | ~2000 | 5-8 min | ~$0.08 |
| Full | ~10000 | 15-30 min | ~$0.30 |

**Custom**: Cost scales linearly with combinations

---

## Summary

✅ **Full control** over all strategy parameters  
✅ **Smart defaults** for quick testing  
✅ **Flexible** - test one param or everything  
✅ **Production-ready** - validated inputs, clear errors  
✅ **Cost-effective** - parallel processing, GCS caching  

**Next Steps**:
1. Deploy enhanced API (`api_functions_enhanced.py`)
2. Update your UI to expose desired parameters
3. Test with quick mode first
4. Add advanced options behind collapsible/modal UI
