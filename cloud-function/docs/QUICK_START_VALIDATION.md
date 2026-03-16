# Quick Start: Validated Strategy Optimization

## 🚀 Run Your First Validated Optimization

### Prerequisites
```bash
cd /Users/kirtanbhatt/code/stockScreener/cloud-function

# Install new dependencies
pip install scikit-learn>=1.3.0
```

---

## 📊 Step-by-Step Guide

### 1. Run Optimization with Validation (30 min runtime)
```bash
# Run with train/test split
python -m src.optimization.optimize_strategy \\
    --max-bars 10000 \\
    --validation-split 0.3 \\
    --mode intraday \\
    --capital 10000

# Look for this output:
# 📊 Train/Test Split:
#    Train: 6,994 bars (70%)
#    Test:  2,997 bars (30%)
```

---

### 2. Analyze Out-of-Sample Performance (2 min)
```bash
# Check for overfitting
python scripts/analyze-optimization-results.py --mode validate --top-n 20

# What to look for:
# ✅ Strategies with <20% degradation (GOOD)
# 🚨 Strategies with >30% degradation (DISCARD)
```

**Example Good Result**:
```
Rank #9 ✅
TRAIN: 157.9% | Sharpe 0.52 | DD 9.9%
TEST:  149.1% | Sharpe 0.48 | DD 11.2%
Degradation: -5.6%  ← LOW = Reliable!
```

**Example Bad Result**:
```
Rank #4 🚨
TRAIN: 172.3% | Sharpe 0.58 | DD 12.4%
TEST:  125.1% | Sharpe 0.35 | DD 18.7%
Degradation: -27.4%  ← HIGH = Overfit!
```

---

### 3. Check Clustering (1 min)
```bash
# Identify stable parameter regions
python scripts/analyze-optimization-results.py --mode cluster --top-n 100 --n-clusters 5

# What to look for:
# ✅ Large clusters (>20 strategies) = Stable
# 🚨 Small clusters (<5 strategies) = Lucky
```

**Example Output**:
```
🔹 CLUSTER 1 (45 strategies, 45.0%)
   Performance: 157.2% ± 8.3%
   ✅ LARGE = Robust parameter region

🔹 CLUSTER 2 (3 strategies, 3.0%)
   Performance: 174.8% ± 2.1%
   🚨 SMALL = Risky, potentially overfit
```

**Decision**: Choose from Cluster 1 (stable) instead of Cluster 2 (risky peak)

---

### 4. Compare Risk-Adjusted (1 min)
```bash
# Don't rank by return alone!
python scripts/analyze-optimization-results.py --mode risk --top-n 20
```

**Key Insight from Your Data**:
```
Rank #1: 174.8% return, 18.8% DD, Sharpe 0.47
Rank #9: 157.9% return,  9.9% DD, Sharpe 0.52

Rank #9 is BETTER for live trading:
- Only 10% less return
- 47% less drawdown (HUGE!)
- 11% better Sharpe
```

---

### 5. Make Final Selection

**Decision Matrix**:
```
Strategy: Rank #9
✅ Large cluster (45 strategies)
✅ Low degradation (-5.6%)
✅ Good test trades (24)
✅ Strong Sharpe (0.52)
✅ Low drawdown (9.9%)
✅ Validated performance

^ Production Ready!
```

---

## 🎯 Expected Runtime

| Step | Time | Command |
|------|------|---------|
| Optimization | 30 min | `optimize_strategy --validation-split 0.3` |
| Validation | 2 min | `--mode validate` |
| Clustering | 1 min | `--mode cluster` |
| Risk Analysis | 1 min | `--mode risk` |
| **Total** | **~35 min** | Complete validated workflow |

---

## 📋 Quick Commands Reference

```bash
# === OPTIMIZATION ===

# With validation (RECOMMENDED)
python -m src.optimization.optimize_strategy --max-bars 10000 --validation-split 0.3 --mode intraday

# Load more data (6 months)
python -m src.optimization.optimize_strategy --max-bars 50000 --validation-split 0.3 --mode intraday

# === ANALYSIS ===

# Check overfitting
python scripts/analyze-optimization-results.py --mode validate --top-n 20

# Identify stable clusters
python scripts/analyze-optimization-results.py --mode cluster --top-n 100 --n-clusters 5

# Risk-adjusted comparison
python scripts/analyze-optimization-results.py --mode risk --top-n 20

# Feature contribution
python scripts/analyze-optimization-results.py --mode intraday --top-n 20

# Top N detailed view
python scripts/analyze-optimization-results.py --mode top20 --top-n 20
```

---

## 🚨 Common Mistakes to Avoid

### ❌ DON'T DO THIS:
```bash
# Running without validation
python -m src.optimization.optimize_strategy --mode intraday
# ^ NO train/test split = Can't assess overfitting!

# Picking rank #1 blindly
# ^ Might be in small cluster = risky!

# Ranking by return alone
# ^ Higher DD = harder to trade live!
```

### ✅ DO THIS INSTEAD:
```bash
# Always use validation
python -m src.optimization.optimize_strategy --validation-split 0.3 --mode intraday

# Check clustering first
python scripts/analyze-optimization-results.py --mode cluster

# Pick from large cluster with low degradation
python scripts/analyze-optimization-results.py --mode validate
```

---

## 📚 Full Documentation

1. **This File** - Quick start guide (you are here!)
2. [`VALIDATION_FRAMEWORK_SUMMARY.md`](./VALIDATION_FRAMEWORK_SUMMARY.md) - Complete implementation details
3. [`OPTIMIZATION_BEST_PRACTICES.md`](./OPTIMIZATION_BEST_PRACTICES.md) - Methodology and best practices
4. Main README - Project overview

---

## ❓ FAQs

**Q: Do I always need to use `--validation-split`?**  
A: YES for production decisions. NO for quick parameter exploration.

**Q: What split percentage should I use?**  
A: 0.3 (30% test) is recommended for <6 months data. 0.2 (20% test) for >6 months.

**Q: My rank #1 has 30% degradation. What now?**  
A: It's overfit. Look at ranks 5-15 for strategies with <15% degradation.

**Q: Rank #1 is in a 3-strategy cluster. Should I use it?**  
A: NO. Choose from the largest cluster instead. More reliable.

**Q: How do I know if I have enough test trades?**  
A: Minimum 20 trades. Prefer 30+. If test has <10 trades, strategy likely broke.

**Q: Can I trust a strategy with -5% degradation?**  
A: YES! <10% degradation is excellent. <20% is acceptable.

---

## 🎯 Success Criteria

Your strategy is READY FOR PRODUCTION when:

- [ ] Loaded 6+ months of data (`--max-bars 50000`)
- [ ] Used 30% validation split (`--validation-split 0.3`)
- [ ] Degradation <20% (`--mode validate`)
- [ ] In large cluster >10% (`--mode cluster`)
- [ ] >20 test trades
- [ ] Sharpe ratio >0.4
- [ ] Max drawdown <15%
- [ ] Reviewed risk-adjusted comparison (`--mode risk`)

---

## 🆘 Need Help?

```bash
# Command help
python -m src.optimization.optimize_strategy --help
python scripts/analyze-optimization-results.py --help

# Check errors
python -m src.optimization.optimize_strategy --max-bars 100  # Quick test

# Read docs
cat docs/OPTIMIZATION_BEST_PRACTICES.md
```

---

## ✅ You're Ready!

Run this complete sequence:

```bash
# 1. Optimize (30 min)
python -m src.optimization.optimize_strategy --max-bars 10000 --validation-split 0.3 --mode intraday

# 2. Validate (1 min)
python scripts/analyze-optimization-results.py --mode validate --top-n 20

# 3. Cluster (1 min)
python scripts/analyze-optimization-results.py --mode cluster --top-n 100

# 4. Risk analysis (1 min)
python scripts/analyze-optimization-results.py --mode risk --top-n 20

# 5. Make decision using checklist above ✅
```

**Happy Trading! 🚀**

---

**Last Updated**: 2024-03-06  
**Framework Version**: 1.0.0
