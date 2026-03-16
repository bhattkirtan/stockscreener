# 🔧 GOLD CFD Configuration Fix

## Problem Identified

Your strategy is correctly functioning but using **wrong scale for GOLD trading**:

### Current Wrong Configuration:
```python
pip_value = 0.01  # Wrong for GOLD!
position_size = 1.0  # Too small
```

Results in:
- TP = 30 pips × 0.01 = **$0.30 target** ❌
- SL = 15 pips × 0.01 = **$0.15 risk** ❌
- Win profit = **$0.27** ❌
- 25 trades = **$13.82 total** ❌

### Correct Configuration for GOLD:

**Option A: Use Full Dollar Points** (Recommended)
```python
pip_value = 1.0  # 1 pip = $1 for GOLD
position_size = 1.0  # 1 oz
```
Results in:
- TP = 30 pips × 1.0 = **$30 target** ✅
- SL = 15 pips × 1.0 = **$15 risk** ✅
- Win profit = **$27** ✅
- 25 trades = **$1,382 total** ✅ (100x improvement!)

**Option B: Increase Position Size**
```python
pip_value = 0.01  # Keep current
position_size = 100.0  # 100 oz instead of 1
```
Results in:
- Same $0.30 targets but 100x position
- Win profit = **$27** ✅
- 25 trades = **$1,382 total** ✅
- ⚠️ Higher risk: $524,200 exposure per trade

**Option C: Add Leverage Multiplier**
```python
pip_value = 0.01
position_size = 1.0
contract_multiplier = 100  # Standard CFD lot size
```

## Capital.com GOLD Specifications

According to Capital.com:
- **Instrument**: GOLD (XAU/USD)
- **Contract Size**: 1 troy oz
- **Pip Value**: $1 per pip for 1 oz
- **Min Trade**: 1 oz
- **Typical Spread**: $0.30-$0.50
- **Leverage**: Up to 1:20

## Recommended Fix

### Step 1: Update pip_value to 1.0

File: `src/backtester.py`
```python
@dataclass
class BacktestConfig:
    initial_capital: float = 10000.0
    spread_pips: float = 0.5    # GOLD spread in dollars
    slippage_pips: float = 0.1  # GOLD slippage in dollars  
    pip_value: float = 1.0      # ✅ CHANGED: $1 per point for GOLD
    default_position_size: float = 1.0  # 1 oz
```

### Step 2: Update strategy pip_value

File: `src/strategy.py`
```python
def __init__(self,
             ...
             pip_value: float = 1.0):  # ✅ CHANGED from 0.01 to 1.0
    self.pip_value = pip_value
```

### Step 3: Update optimizer

File: `src/optimize_strategy.py`
```python
strategy = SupertrendVWAPStrategy(
    ...
    pip_value=1.0  # ✅ CHANGED for GOLD
)
```

## Expected Results After Fix

With pip_value = 1.0:
- **Same 64% win rate**
- **Same 25 trades**
- **Same strategy logic**
- But now:
  - Average win: **$27** (was $0.27)
  - Average loss: **-$19** (was -$0.19)
  - Total P&L: **~$1,380** (was $13.82)
  - Return: **13.8%** (was 0.138%)

## Quick Test Command

```bash
cd /Users/kirtanbhatt/code/stockScreener/cloud-function

# Test with corrected pip_value
python3 -c "
from src.strategy import SupertrendVWAPStrategy
from src.backtester import BacktestConfig
import pandas as pd

df = pd.read_csv('data/GOLD_M5_5000bars.csv', parse_dates=['time'])
df.set_index('time', inplace=True)

strategy = SupertrendVWAPStrategy(
    pip_value=1.0,  # FIXED!
    sl_pips=15,
    tp_pips=90
)

config = BacktestConfig(
    initial_capital=10000,
    pip_value=1.0,  # FIXED!
    default_position_size=1.0
)

results = strategy.backtest(df.tail(1000), initial_capital=10000.0)
print(f'📊 Fixed Results:')
print(f'Initial: \${config.initial_capital:,.2f}')
print(f'Final: \${results[\"final_capital\"]:,.2f}')
print(f'P&L: \${results[\"total_pnl\"]:,.2f}')
print(f'Return: {results[\"return_pct\"]:.2f}%')
"
```

## Risk Considerations

### With pip_value = 1.0:
- **Position Value**: Still 1 oz × $5,200 = $5,200 (52% of capital)
- **Risk per trade**: $15 (0.15% of capital) ✅ Good
- **Reward per trade**: $30 (0.30% of capital) ✅ Good
- **R:R Ratio**: 1:2 ✅ Good

### Recommendations:
1. ✅ **Use pip_value = 1.0** for realistic GOLD trading
2. ✅ **Keep position_size = 1.0** (proper risk management)
3. ⚠️ **Consider reducing position**: 0.5 oz for safer 25% exposure
4. ⚠️ **Test on longer periods**: 30+ days before live trading

## Files to Update

1. `src/backtester.py` - Line 105
2. `src/strategy.py` - Line 33, 560
3. `src/optimize_strategy.py` - Strategy initialization
4. `src/tick_backtester.py` - If used

## Next Steps

1. Apply the fixes above
2. Re-run optimization:
   ```bash
   python3 src/optimize_strategy.py
   ```
3. Verify results show realistic profits ($500-2000 range)
4. Update documentation
5. Paper trade for 1-2 weeks before going live
