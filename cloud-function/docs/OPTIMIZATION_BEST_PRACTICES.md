# Optimization Best Practices
## Strategy Validation & Testing Framework

### 📋 Table of Contents
1. [Data Window Requirements](#data-window-requirements)
2. [Train/Test Split Guidelines](#train-test-split-guidelines)
3. [Parameter Grid Design](#parameter-grid-design)
4. [Clustering Analysis](#clustering-analysis)
5. [Overfitting Detection](#overfitting-detection)
6. [Trade Count Requirements](#trade-count-requirements)
7. [Risk-Adjusted Evaluation](#risk-adjusted-evaluation)
8. [Feature Contribution Analysis](#feature-contribution-analysis)

---

## Data Window Requirements

### ⚠️ Minimum Data Recommendations

**Short-Term (Intraday M5)**
- **Minimum**: 3-6 months of data (~40,000-80,000 bars)
- **Recommended**: 6-12 months (~80,000-160,000 bars)
- **Why**: M5 timeframe needs large samples for statistical significance

**Current Status (7 weeks)**
- ❌ **TOO SHORT** for production decisions
- ✅ OK for initial parameter exploration
- ⚠️ High overfitting risk

### 💡 Actionable Steps
```bash
# Load more data (recommended: 6 months minimum)
python -m src.optimization.optimize_strategy \\
    --max-bars 50000 \\  # ~6 months of M5 data
    --validation-split 0.3 \\  # 70% train, 30% test
    --mode intraday
```

---

## Train/Test Split Guidelines

### 📊 Recommended Splits

| Data Duration | Train % | Test % | Notes |
|---------------|---------|--------|-------|
| < 2 months    | ❌ Don't use | - | Too short for any split |
| 2-4 months    | 60-70% | 30-40% | Minimum acceptable |
| 4-12 months   | 70% | 30% | **Recommended** |
| > 12 months   | 70-80% | 20-30% | Or use walk-forward |

### 🎯 Current 7-Week Window Split
```
Total: 9,991 bars (7 weeks)
Train: 6,994 bars (70% = ~5 weeks)
Test: 2,997 bars (30% = ~2 weeks)
```

**Status**: ⚠️ Marginal - Use for exploration only, NOT production decisions

### ✅ Best Practices
1. **Always use validation split** for optimization runs
2. **Sort by TEST performance**, not train
3. **Flag strategies with >20% degradation**
4. **Prefer consistent train/test Sharpe ratios**

### 🚨 Red Flags
- Train return >>test return (>30% degradation)
- Test has few trades (<10 on 2-week window)
- Test Sharpe <<train Sharpe (>40% drop)

---

## Parameter Grid Design

### ⚠️ Current Grid Issues
```
Current: 1,536 combinations
Problem: Too many parameters → noise risk
```

### 💡 Recommended Approach

**Phase 1: Coarse Grid (200-500 combos)**
- Test wide parameter ranges
- Identify promising regions
- Use clustering to find stable zones

**Phase 2: Fine Grid (500-1000 combos)**
- Focus on best-performing clusters
- Narrow parameter ranges
- Validate with 30% holdout

**Phase 3: Walk-Forward (final validation)**
- Use top 10 from Phase 2
- Run walk-forward on full dataset
- Pick strategy with most consistent results

### 📐 Grid Recommendations by Feature

| Feature | Current | Recommended | Why |
|---------|---------|-------------|-----|
| Supertrend Multiplier | [2.5, 3.0] | [2.0, 2.5, 3.0] | Current winners use 2.5 |
| SMA Fast | [15, 20] | [15, 20] | ✅ Good range |
| SMA Slow | [30, 50] | [50] | Morning winner used 50 |
| BB Std | [2.0, 2.5] | [2.0] | Morning winner used 2.0 |
| ATR TP Mult | [3.0, 4.0] | [4.0] | Morning winner used 4x |
| Fixed TP/SL | Test both | Focus on ATR | ATR outperformed |

### 🎯 Simplified Grid Example
```python
# Focus on proven parameters from morning run
simplified_grid = {
    'st_mult': [2.5],  # Keep winner
    'sma_fast': [15],  # Keep winner
    'sma_slow': [50],  # Keep winner
    'bb_std': [2.0],  # Keep winner
    'tp_sl_strategy': ['atr'],  # ATR clearly better
    'atr_tp_multiplier': [4.0],  # Keep winner
    'atr_sl_multiplier': [2.0],  # Keep winner
    
    # Only vary intraday features (16 combos instead of 1,536!)
    'enable_time_exit': [True, False],
    'enable_eod_close': [True, False],
    'enable_eod_blackout': [True, False],
    'enable_partial_exit': [True, False]
}
# Result: 2^4 = 16 combinations (highly focused)
```

---

## Clustering Analysis

### 🔬 Purpose
Identify **stable parameter regions** (good) vs **isolated peaks** (risky)

### ✅ What to Look For

**Good Signs** (✅ Use these)
- **Dense clusters**: 20+ strategies with similar params
- **Low variance**: Std dev <10% of mean return
- **Broad plateau**: Small param changes → small performance changes

**Bad Signs** (🚨 Avoid these)
- **Isolated strategies**: Only 1-2 similar configs
- **High variance**: Std dev >20% of mean return
- **Sharp peak**: Tiny param change → huge performance drop

### 💡 How to Use
```bash
# Run clustering on top 100 strategies
python scripts/analyze-optimization-results.py \\
    --mode cluster \\
    --top-n 100 \\
    --n-clusters 5
```

### 📊 Interpretation
```
Example Output:
🔹 CLUSTER 1 (45 strategies, 45%)
   Performance: 150.2% ± 12.1% return
   ✅ GOOD: Large, stable cluster

🔹 CLUSTER 2 (3 strategies, 3%)
   Performance: 174.8% ± 3.2% return
   🚨 RISKY: Small, potentially lucky
```

### 🎯 Decision Rules
1. **If rank #1 is in large cluster**: ✅ More reliable
2. **If rank #1 is isolated**: ⚠️ Choose cluster centroid instead
3. **Pick from largest cluster with best avg return**: ✅ Most robust

---

## Overfitting Detection

### 📊 Degradation Thresholds

| Degradation | Assessment | Action |
|-------------|------------|--------|
| < 10% | ✅ Excellent | Safe for production |
| 10-20% | ⚠️ Acceptable | Monitor closely |
| 20-30% | 🚨 High risk | Avoid for live trading |
| > 30% | ❌ Severe overfit | Discard |

### 🔍 Signs of Overfitting
- Train: 175% return → Test: 120% return (31% degradation)
- Train: 78 trades → Test: 15 trades (strategy broke)
- Train: Sharpe 2.5 → Test: Sharpe 1.2 (52% drop)

### ✅ Validation Workflow
```bash
# 1. Run with validation
python -m src.optimization.optimize_strategy \\
    --validation-split 0.3 \\
    --mode intraday

# 2. Analyze overfitting
python scripts/analyze-optimization-results.py --mode validate --top-n 20
```

### 💡 Interpretation
```
Output Example:
⚠️  OVERFITTING DETECTION:
   Strategies with >20% drop: 3/20 (15%)
   
✅ BEST VALIDATED STRATEGIES:
   1. Rank #12 ✅
      TRAIN: 157.9% | Sharpe 0.52 | DD 9.9%
      TEST:  149.1% | Sharpe 0.48 | DD 11.2%
      Degradation: -5.6% return, -7.7% Sharpe
      ^ LOW degradation = reliable
```

---

## Trade Count Requirements

### 📊 Minimum Trades by Window

| Window | Minimum Trades | Preferred |
|--------|----------------|-----------|
| 2 weeks | 10 | 20+ |
| 1 month | 20 | 30+ |
| 2 months | 30 | 50+ |
| 6 months | 50 | 100+ |

### ⚠️ Current 7-Week Results
```
Best Strategy: 78 trades over 7 weeks
= 11.1 trades/week
= ~1.6 trades/day

Assessment: ✅ Acceptable for 7 weeks
BUT: ⚠️ Need more data to confirm consistency
```

### 🚨 Red Flags
- High return on <10 trades (very noisy)
- Test trades <<train trades (strategy broke)
- Win rate >70% with few trades (lucky)

### 💡 Trade Density Check
```python
# Good: Consistent trade frequency
Train: 78 trades / 5 weeks = 15.6 trades/week ✅
Test:  35 trades / 2 weeks = 17.5 trades/week ✅
^ Similar density = reliable

# Bad: Inconsistent frequency
Train: 78 trades / 5 weeks = 15.6 trades/week
Test:  5 trades / 2 weeks = 2.5 trades/week ❌
^ Strategy stopped working!
```

---

## Risk-Adjusted Evaluation

### 📊 Don't Rank by Return Alone!

**Example from Current Results:**
```
Rank #1: 174.82% return, 18.79% DD, Sharpe 0.47
Rank #9: 157.90% return,  9.94% DD, Sharpe 0.52

Rank #9 is BETTER for live trading:
- Only 10% less return
- 47% less drawdown (huge!)
- 11% better Sharpe ratio
- 54.7% WR vs 52.6%
```

### 💡 Evaluation Hierarchy
```
1. Risk-Adjusted Return (Sharpe Ratio)
   → Prefer Sharpe >0.5 over raw return

2. Drawdown
   → Prefer MaxDD <15% for peace of mind
   → Lower DD = easier to trade psychologically

3. Consistency
   → Prefer strategies in dense clusters
   → Prefer low train/test degradation

4. Raw Return (last!)
   → Only compare within similar DD ranges
```

### 🎯 Decision Matrix
```
175% return + 20% DD + isolated = 🚨 High risk
160% return + 10% DD + cluster  = ✅ Better choice
150% return +  5% DD + cluster  = ✅✅ Safest choice
```

### 📊 Use Risk Mode
```bash
python scripts/analyze-optimization-results.py --mode risk --top-n 20
```

---

## Feature Contribution Analysis

### 🔬 Purpose
Identify which features consistently improve performance

### ❌ Current Problem
```
From morning run:
- 5 unique performance groups
- Each group has 4 BB/PartialExit variations
- All 4 variations = IDENTICAL returns

Conclusion: BB period and partial_exit don't affect results
```

### ✅ Ablation Study Approach

**Test each feature on/off independently:**
```
Baseline (no intraday):     +100% return
+ EOD Blackout only:        +110% return → +10% contribution
+ Time Exit only:           +105% return →  +5% contribution  
+ EOD Close only:           +103% return →  +3% contribution
+ Partial Exit only:        +100% return →   0% contribution ❌

Conclusion: EOD Blackout provides most value
```

### 💡 Current Feature Analysis
```bash
python scripts/analyze-optimization-results.py --mode intraday --top-n 20
```

### 🎯 Interpretation
```
If top 20 shows:
- With EOD Blackout: avg 155% return
- Without EOD Blackout: avg 170% return

^ EOD Blackout HURTS performance! ❌ Remove it.

If:
- With Time Exit: avg 160% return
- Without Time Exit: avg 145% return

^ Time Exit HELPS! ✅ Keep it.
```

---

## Workflow Summary

### 🎯 Recommended Process

**Phase 1: Exploration (Current)**
```bash
# Use 7-week window to test ideas
python -m src.optimization.optimize_strategy \\
    --max-bars 10000 \\
    --mode intraday
    
# Identify promising parameter regions
python scripts/analyze-optimization-results.py --mode cluster
```

**Phase 2: Validation (REQUIRED)**
```bash
# Load 6+ months data, run with train/test split
python -m src.optimization.optimize_strategy \\
    --max-bars 50000 \\  # 6 months
    --validation-split 0.3 \\
    --mode intraday
    
# Check for overfitting
python scripts/analyze-optimization-results.py --mode validate

# Identify stable clusters
python scripts/analyze-optimization-results.py --mode cluster --top-n 100
```

**Phase 3: Final Selection**
```bash
# 1. Look at validation results
python scripts/analyze-optimization-results.py --mode validate

# 2. Check clustering
python scripts/analyze-optimization-results.py --mode cluster

# 3. Compare risk-adjusted
python scripts/analyze-optimization-results.py --mode risk

# 4. Pick strategy from:
#    - Large cluster (>10% of strategies)
#    - Low degradation (<15%)
#    - Good Sharpe (>0.4)
#    - Reasonable DD (<15%)
```

---

## Transaction Costs

### ✅ Already Configured
```python
# In BacktestConfig:
spread_cost_usd: $0.02    # Capital.com typical for GOLD
slippage_cost_usd: $0.005 # Realistic M5 slippage
pip_value: 1.0            # For GOLD
```

### 💡 Cost Impact Analysis
```
Per Trade Cost: $0.025 per lot
For 78 trades with 10 lots: $19.50 total cost
On $10,000 capital: -0.2% return impact

^ Already realistic, no changes needed
```

---

## Key Takeaways

### ✅ DO THIS
1. **Use validation split**: `--validation-split 0.3`
2. **Load more data**: `--max-bars 50000` (6 months minimum)
3. **Check clustering**: `--mode cluster`
4. **Validate out-of-sample**: `--mode validate`
5. **Sort by TEST performance**, not train
6. **Pick from large clusters**, not isolated peaks
7. **Prefer low drawdown** over maximum return
8. **Require >20 trades** on test set

### 🚨 DON'T DO THIS
1. ❌ Trust 7-week optimization for production
2. ❌ Pick rank #1 without checking cluster
3. ❌ Ignore train/test degradation
4. ❌ Rank by return alone (use Sharpe/DD)
5. ❌ Deploy without out-of-sample validation
6. ❌ Accept >30% degradation strategies
7. ❌ Trust results with <10 test trades
8. ❌ Optimize 1,500+ parameters (overfitting)

---

## Quick Reference

### Commands
```bash
# Full validation run (RECOMMENDED)
python -m src.optimization.optimize_strategy \\
    --max-bars 50000 \\
    --validation-split 0.3 \\
    --mode intraday

# Analysis suite
python scripts/analyze-optimization-results.py --mode validate
python scripts/analyze-optimization-results.py --mode cluster --top-n 100
python scripts/analyze-optimization-results.py --mode risk --top-n 20
python scripts/analyze-optimization-results.py --mode intraday
```

### Decision Checklist
- [ ] Loaded >6 months of data
- [ ] Used 30% validation split
- [ ] Checked overfitting (<20% degradation)
- [ ] Identified stable clusters
- [ ] Strategy in large cluster
- [ ] Test has >20 trades
- [ ] Sharpe ratio >0.4
- [ ] Max DD <15%
- [ ] Low train/test variance

---

## References

Based on:
- User's algorithmic trading best practices book
- 7-week optimization run analysis (2026-01-14 to 2026-03-06)
- Current results: 1,536 strategies, best = 174.82% return
- Expert feedback on overfitting risks and validation requirements

**Last Updated**: 2024-03-06
