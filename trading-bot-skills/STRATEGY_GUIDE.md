# Strategy Architecture Guide
## Where Everything Lives in trading-bot-skills

---

## 📍 SIGNAL GENERATION

### Primary File: `skills/analysis/analysis_skill.py`

**Line 200: `_generate_signal()` method**
- THIS IS WHERE ALL SIGNALS ARE CREATED
- Called by: `on_candle_closed()` event handler
- Uses: `core/signal_engine.py` (shared with backtester)
- Returns: 'BUY', 'SELL', or None

```
Flow:
1. Candle arrives → MarketDataSkill buffers it
2. CANDLE_CLOSED event → AnalysisSkill.on_candle_closed()
3. Calculate indicators (supertrend, EMA, SMA, etc.)
4. Call _generate_signal() ← SIGNAL CREATED HERE
5. Publish SIGNAL_GENERATED event
6. RiskSkill validates → RISK_APPROVED event
7. ExecutionSkill places order (or BacktestingSkill simulates)
```

---

## 🎯 CURRENT STRATEGY: Supertrend + VWAP

### Indicators Used:
1. **Supertrend** (`_calculate_supertrend`)
   - ATR period: 7 (config: `analysis.supertrend.atr_period`)
   - Multiplier: 2.0 (config: `analysis.supertrend.multiplier`)
   - Direction: 1 (bullish) or -1 (bearish)

2. **EMA** (`_calculate_ema`)
   - Period: 21 (config: `analysis.ema_period`)
   - Used for: Momentum confirmation

3. **SMA Fast/Slow** (`_calculate_sma`)
   - Fast: 25 (config: `analysis.sma.fast_period`)
   - Slow: 30 (config: `analysis.sma.slow_period`)
   - Used for: Trend confirmation, crossover detection

4. **VWAP** (`_calculate_vwap`)
   - Volume Weighted Average Price
   - Resets: Daily at midnight
   - Used for: Price level validation

### Signal Logic (in `core/signal_engine.py`):
```python
BUY conditions:
- Supertrend direction = UP (1)
- Price > EMA (momentum)
- SMA Fast > SMA Slow OR Golden Cross

SELL conditions:
- Supertrend direction = DOWN (-1)
- Price < EMA (momentum)
- SMA Fast < SMA Slow OR Death Cross
```

---

## ➕ HOW TO ADD NEW STRATEGIES

### Option 1: Add New Indicator to Existing Strategy

**Step 1:** Add indicator calculation method in `AnalysisSkill`:

```python
def _calculate_rsi(self, df: pd.DataFrame) -> pd.DataFrame:
    """Calculate RSI indicator"""
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    return df
```

**Step 2:** Call it in `on_candle_closed()`:

```python
df = self._calculate_supertrend(df)
df = self._calculate_sma(df)
df = self._calculate_ema(df)
df = self._calculate_rsi(df)  # ← ADD THIS
```

**Step 3:** Use it in `_generate_signal()`:

```python
# RSI filter
if latest['rsi'] > 70:  # Overbought
    return None  # Skip SELL signal
elif latest['rsi'] < 30:  # Oversold
    return None  # Skip BUY signal
```

**Step 4:** Add config in `trading_config.yaml`:

```yaml
analysis:
  rsi:
    enabled: true
    period: 14
    overbought: 70
    oversold: 30
```

**Step 5:** Read config in `__init__()`:

```python
self.rsi_enabled = config.get('rsi', {}).get('enabled', False)
self.rsi_period = config.get('rsi', {}).get('period', 14)
self.rsi_overbought = config.get('rsi', {}).get('overbought', 70)
self.rsi_oversold = config.get('rsi', {}).get('oversold', 30)
```

---

### Option 2: Create Entirely New Strategy

**Step 1:** Add strategy selector in config:

```yaml
analysis:
  strategy: "rsi_macd"  # NEW: "supertrend_vwap", "rsi_macd", "bollinger_breakout"
```

**Step 2:** Modify `_generate_signal()` to branch based on strategy:

```python
def _generate_signal(self, df: pd.DataFrame) -> Optional[str]:
    """Generate signal based on configured strategy"""
    
    strategy = self.config.get('strategy', 'supertrend_vwap')
    
    if strategy == 'supertrend_vwap':
        return self._signal_supertrend_vwap(df)
    elif strategy == 'rsi_macd':
        return self._signal_rsi_macd(df)
    elif strategy == 'bollinger_breakout':
        return self._signal_bollinger_breakout(df)
    else:
        print(f"⚠️ Unknown strategy: {strategy}")
        return None
```

**Step 3:** Implement strategy-specific signal methods:

```python
def _signal_rsi_macd(self, df: pd.DataFrame) -> Optional[str]:
    """RSI + MACD crossover strategy"""
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    # RSI conditions
    rsi_oversold = latest['rsi'] < 30
    rsi_overbought = latest['rsi'] > 70
    
    # MACD crossover
    macd_bullish = (latest['macd'] > latest['macd_signal']) and \
                   (prev['macd'] <= prev['macd_signal'])
    macd_bearish = (latest['macd'] < latest['macd_signal']) and \
                   (prev['macd'] >= prev['macd_signal'])
    
    # BUY: RSI oversold + MACD bullish crossover
    if rsi_oversold and macd_bullish:
        return 'BUY'
    
    # SELL: RSI overbought + MACD bearish crossover
    if rsi_overbought and macd_bearish:
        return 'SELL'
    
    return None
```

---

## 🔧 CONFIG-DRIVEN STRATEGY SELECTION

### Example: Multiple Strategies in Config

```yaml
# trading_config.yaml

analysis:
  enabled: true
  strategy: "supertrend_vwap"  # ← CHANGE THIS TO SWITCH STRATEGIES
  
  # Strategy 1: Supertrend + VWAP
  supertrend:
    atr_period: 7
    multiplier: 2.0
  ema_period: 21
  sma:
    fast_period: 25
    slow_period: 30
  vwap:
    enabled: true
  
  # Strategy 2: RSI + MACD
  rsi:
    period: 14
    overbought: 70
    oversold: 30
  macd:
    fast_period: 12
    slow_period: 26
    signal_period: 9
  
  # Strategy 3: Bollinger Bands Breakout
  bollinger:
    period: 20
    std_dev: 2.0
    breakout_threshold: 0.5
```

### Enable/Disable Indicators:

```python
# In AnalysisSkill.__init__()
self.rsi_enabled = config.get('rsi', {}).get('enabled', False)
self.macd_enabled = config.get('macd', {}).get('enabled', False)

# In on_candle_closed()
if self.rsi_enabled:
    df = self._calculate_rsi(df)

if self.macd_enabled:
    df = self._calculate_macd(df)
```

---

## 📊 BACKTESTING WITH NEW STRATEGIES

### Using Skills-Based Backtest:

```bash
# 1. Edit config/trading_config.yaml
#    Set: analysis.strategy = "rsi_macd"

# 2. Run backtest with skills
python3 run_skills_backtest.py

# 3. Results will use your new strategy automatically!
```

### Why This Works:
- `run_skills_backtest.py` uses ACTUAL AnalysisSkill
- AnalysisSkill reads config and selects strategy
- Same code runs in backtest AND live bot
- **No code duplication = No bugs!**

---

## 🎯 FILES TO MODIFY FOR NEW STRATEGIES

| File | What to Change |
|------|---------------|
| `skills/analysis/analysis_skill.py` | Add indicators, modify `_generate_signal()` |
| `config/trading_config.yaml` | Add strategy config options |
| `core/signal_engine.py` | (Optional) Add shared signal logic |
| `run_skills_backtest.py` | Nothing! It uses skills automatically |

---

## 🚀 QUICK START: Add RSI Filter

**1. Edit `skills/analysis/analysis_skill.py`:**

```python
# Line ~44: Add to __init__()
self.rsi_enabled = config.get('rsi', {}).get('enabled', False)
self.rsi_period = config.get('rsi', {}).get('period', 14)

# Line ~90: Add to on_candle_closed()
if self.rsi_enabled:
    df = self._calculate_rsi(df)

# Line ~200: Add RSI method
def _calculate_rsi(self, df: pd.DataFrame) -> pd.DataFrame:
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    return df

# Line ~220: Add to _generate_signal()
if self.rsi_enabled:
    if latest['rsi'] > 70:  # Overbought
        return None  # Skip signal
```

**2. Edit `config/trading_config.yaml`:**

```yaml
analysis:
  rsi:
    enabled: true
    period: 14
    overbought: 70
    oversold: 30
```

**3. Test it:**

```bash
python3 run_skills_backtest.py
```

Done! Your RSI filter is now active in both backtest AND live bot.

---

## 💡 BEST PRACTICES

1. **Keep signal logic in signal_engine.py**
   - Pure functions (no side effects)
   - Shared between live bot and backtester
   - Easy to test

2. **Make everything config-driven**
   - Easy to tune parameters
   - Can A/B test strategies
   - No code changes needed

3. **Use skills architecture**
   - Each skill has one job
   - Skills communicate via events
   - Easy to add/remove features

4. **Test with backtest first**
   - Validate with historical data
   - Measure performance metrics
   - Compare with baseline

---

## 📚 NEXT STEPS

1. ✅ **You are here:** Understand where signals are created
2. ⏭️ **Add your first indicator:** Try RSI filter (see above)
3. ⏭️ **Create custom strategy:** Implement in `_generate_signal()`
4. ⏭️ **Backtest new strategy:** Run `run_skills_backtest.py`
5. ⏭️ **Compare results:** Check P&L, win rate, drawdown
6. ⏭️ **Deploy to paper trading:** Use `start_paper_trading.sh`
7. ⏭️ **Monitor live performance:** Watch for edge cases

---

## 🔗 KEY FILES REFERENCE

| File | Line | What It Does |
|------|------|-------------|
| `skills/analysis/analysis_skill.py` | 200 | **SIGNALS CREATED HERE** |
| `core/signal_engine.py` | 90 | Shared signal evaluation logic |
| `skills/risk/risk_skill.py` | 89 | Validates signals (cooldown, limits) |
| `skills/execution/execution_skill.py` | - | Places real orders (Capital.com API) |
| `skills/backtesting/backtesting_skill.py` | 200 | Simulates orders (no real money) |
| `config/trading_config.yaml` | 50 | Strategy configuration |
| `run_skills_backtest.py` | 40 | Wires all skills together for backtest |

---

**Created:** 2026-03-29  
**Purpose:** Guide for adding new strategies to trading-bot-skills
