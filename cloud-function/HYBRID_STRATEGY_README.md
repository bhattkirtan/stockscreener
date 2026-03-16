# Hybrid Zone-SuperTrend Strategy

## Overview

The Hybrid Zone-SuperTrend Strategy combines the best of both approaches:

1. **SuperTrend Trend-Following** (proven 122% return with 0.7×2.5 ATR)
2. **Zone Structural Awareness** (blocks poor setups into opposing zones)

This is a **conservative enhancement** that keeps the proven SuperTrend core while adding intelligent structural filtering.

## Architecture

```
HybridZoneSuperTrendStrategy
    ↓ inherits from
SupertrendVWAPStrategy (proven base)
    ↓ adds
Zone Detection & Filtering
```

## Key Features

### 1. Proven SuperTrend Core
- ✅ Supertrend indicator for trend direction
- ✅ SMA and Bollinger Bands for confirmation
- ✅ ATR-based TP/SL (0.7×2.5 historical winner)
- ✅ Event blocking (15 min before/30 min after news)
- ✅ Volume and spread filters
- ✅ All existing SuperTrend logic intact

### 2. Zone Structural Filtering (NEW)
- 🆕 Multi-timeframe zone detection (H4/H1/M15)
- 🆕 Blocks longs into strong overhead resistance
- 🆕 Blocks shorts into strong support below
- 🆕 Zones scored by strength (H4 > H1 > M15)
- 🆕 Optional: Adjust stops to zone boundaries

### 3. Intelligent Integration
- Zones update every 15 bars (75 minutes) to minimize overhead
- Zone filter only blocks when strong structure conflicts with signals
- ATR-based TP/SL logic remains unchanged
- Backward compatible: can disable zone filter entirely

## How Zone Filtering Works

### Long Entry Filter

```python
# SuperTrend generates long signal
if supertrend_long_signal:
    # Check for resistance overhead
    nearest_resistance = find_resistance_above(price)
    
    if resistance is nearby AND resistance is strong:
        BLOCK LONG  # Don't fight strong structure
    else:
        ALLOW LONG  # Clear path to targets
```

### Short Entry Filter

```python
# SuperTrend generates short signal
if supertrend_short_signal:
    # Check for support below
    nearest_support = find_support_below(price)
    
    if support is nearby AND support is strong:
        BLOCK SHORT  # Don't fight strong structure
    else:
        ALLOW SHORT  # Clear path to targets
```

### Zone Strength Determination

A zone is considered **strong** when:
- Score ≥ 4.0 (Gold) or ≥ 3.5 (US100)
- Factors: timeframe weight, rejections, impulse moves, touches
- H4 zones weighted 3×, H1 zones 2×, M15 zones 1×

### Distance Threshold

Zone blocks entry when:
- Distance to zone < 1.0 × zone width (configurable)
- Example: If resistance zone is 10 pips wide, blocks if within 10 pips

## Configuration

### Basic Usage (Zone Filter Enabled)

```python
from src.strategies.hybrid_zone_supertrend_strategy import HybridZoneSuperTrendStrategy

strategy = HybridZoneSuperTrendStrategy(
    # SuperTrend parameters (unchanged)
    supertrend_atr_multiplier=3.0,
    supertrend_period=10,
    atr_sl_multiplier=0.7,  # Proven winner
    atr_tp_multiplier=2.5,  # Proven winner
    
    # Zone filter parameters (NEW)
    enable_zone_filter=True,
    zone_block_distance=1.0,  # Block if within 1× zone width
    enable_zone_stops=False   # Keep ATR stops (recommended)
)
```

### Advanced Usage (Zone-Based Stop Adjustment)

```python
strategy = HybridZoneSuperTrendStrategy(
    # ... SuperTrend params ...
    
    enable_zone_filter=True,
    enable_zone_stops=True,   # Adjust stops to zone boundaries
    zone_block_distance=1.5,  # More conservative blocking
    
    # Custom zone configuration
    zone_config={
        'zone_widths': {
            'H4': 0.35,  # Gold defaults
            'H1': 0.25,
            'M15': 0.18
        },
        'strong_zone_threshold': 4.5,  # Higher threshold = fewer blocks
        'atr_period': 14
    }
)
```

### Disable Zone Filter (Pure SuperTrend)

```python
strategy = HybridZoneSuperTrendStrategy(
    # ... SuperTrend params ...
    
    enable_zone_filter=False  # Reverts to pure SuperTrend
)
```

## Integration with Optimization

The hybrid strategy can be optimized using the existing framework:

```python
# In optimize_strategy.py, add hybrid grid:
def define_hybrid_grid(self):
    """Define hybrid strategy optimization grid."""
    
    # Base SuperTrend parameters
    base_grid = {
        'supertrend_atr_multiplier': [2.5, 3.0, 3.5],
        'supertrend_period': [8, 10, 12],
        'atr_sl_multiplier': [0.5, 0.7, 1.0],
        'atr_tp_multiplier': [2.0, 2.5, 3.0],
        
        # Zone filter parameters
        'enable_zone_filter': [True, False],  # Test with/without
        'zone_block_distance': [0.8, 1.0, 1.5],
        'enable_zone_stops': [False]  # Keep ATR stops for now
    }
    
    return base_grid
```

### Run Hybrid Optimization

```bash
python3 scripts/run-local-optimization.py \
    --data-file data/GOLD_M5_150000bars.csv \
    --strategy hybrid \
    --mode quick \
    --enable-event-blocking \
    --capital 10000 \
    --n-jobs 12
```

## Expected Behavior

### What Changes:
- **Fewer total trades** (some signals blocked by zones)
- **Higher win rate** (avoids trades into strong structure)
- **Reduced drawdown** (structural stop-outs avoided)
- **Similar or better Sharpe** (quality over quantity)

### What Stays the Same:
- SuperTrend trend detection logic
- ATR-based TP/SL sizing (0.7×2.5)
- Event blocking (news windows)
- Spread and volume filters
- Trade risk management (1% per trade)

### Performance Trade-offs:

| Metric | Pure SuperTrend | Hybrid (Conservative) |
|--------|----------------|----------------------|
| Total Trades | Higher | Lower (-10% to -30%) |
| Win Rate | Baseline | Higher (+3% to +8%) |
| Profit Factor | Baseline | Higher (+0.1 to +0.3) |
| Max Drawdown | Baseline | Lower (-2% to -5%) |
| Total Return | Baseline | Similar or better |

## Backtest Validation Protocol

### Phase 1: Side-by-Side Comparison (CURRENT)
1. Run pure SuperTrend backtest (baseline)
2. Run hybrid backtest with zone filter
3. Compare metrics:
   - Total return
   - Win rate improvement
   - Drawdown reduction
   - Trade count reduction
   - Sharpe ratio change

### Phase 2: Robustness Tests
1. Test with different `zone_block_distance` (0.5, 1.0, 1.5, 2.0)
2. Test with different `strong_zone_threshold` (3.5, 4.0, 4.5)
3. Test with/without zone-based stops
4. Verify performance across different market regimes

### Phase 3: Walk-Forward Validation
1. Train on 12 months → validate on 6 months
2. Roll forward 3 months at a time
3. Confirm zone filter adds value consistently

## Non-Negotiable Rules

1. ✅ **Never remove proven SuperTrend logic**
   - Keep 0.7×2.5 ATR TP/SL as default
   - Keep Supertrend + SMA + BB confirmation
   
2. ✅ **Zone filter is additive only**
   - Can only BLOCK trades, never force trades
   - Must improve or maintain performance
   
3. ✅ **No future leakage**
   - Zones detected only on historical data up to current bar
   - Resample respects time boundaries
   
4. ✅ **Performance validation required**
   - Must beat pure SuperTrend in walk-forward tests
   - Must pass robustness tests
   - If underperforms, disable zone filter
   
5. ✅ **Computational efficiency**
   - Zone updates every 15 bars (not every bar)
   - Keep top 10 zones per timeframe only
   - Avoid expensive operations in hot path

## Troubleshooting

### "No zones detected"
- Check: Need minimum 50 bars per timeframe
- Check: ATR calculation working correctly
- Solution: Ensure data loaded and resampled properly

### "All trades blocked"
- Check: `zone_block_distance` too aggressive (>2.0)
- Check: `strong_zone_threshold` too low (<3.0)
- Solution: Tune parameters, start with defaults

### "No performance improvement"
- Check: Zone filter might be too lenient
- Check: Reduce `zone_block_distance` to 0.8
- Check: Lower `strong_zone_threshold` to 3.5

### "Performance worse than SuperTrend"
- Solution: Disable zone filter (`enable_zone_filter=False`)
- Solution: Return to pure SuperTrend approach
- Note: Zone filter should ADD value, not subtract

## Implementation Status

### ✅ Completed (Phase 1)
- Hybrid strategy class implementation
- Zone detection integration
- Long/short blocking logic
- Zone strength scoring
- Multi-timeframe resampling
- Stop adjustment logic (optional)
- Configuration system
- Documentation

### ⏳ In Progress (Phase 2)
- Zone strategy pure backtest (RUNNING NOW)
- Hybrid strategy backtest script
- Side-by-side comparison report
- Performance metrics analysis

### 📋 Pending (Phase 3)
- Optimization framework integration
- Walk-forward validation tests
- Robustness testing suite
- Production deployment readiness
- Live broker adapter with zones

## Next Steps

1. **Wait for zone strategy results** (~30-60 min)
2. **Run hybrid backtest** with same data
3. **Compare performance**:
   - Pure SuperTrend (baseline from yesterday)
   - Pure Zone Strategy (running now)
   - Hybrid (to run next)
4. **Analyze trade-off**:
   - Did zone filter improve win rate?
   - Did it reduce drawdown?
   - Is trade reduction acceptable?
5. **Decision**:
   - If hybrid wins → run full optimization
   - If SuperTrend wins → keep original
   - If zone strategy wins → switch approaches

## Code Example: Running Hybrid Backtest

```python
from src.strategies.hybrid_zone_supertrend_strategy import HybridZoneSuperTrendStrategy
from src.core.backtester import Backtester, BacktestConfig

# Configuration
config = BacktestConfig(
    initial_capital=10000,
    risk_per_trade=0.01,
    enable_event_blocking=True,
    calendar_path='data/economic_calendar.json'
)

# Initialize hybrid strategy
strategy = HybridZoneSuperTrendStrategy(
    supertrend_period=10,
    supertrend_atr_multiplier=3.0,
    atr_sl_multiplier=0.7,
    atr_tp_multiplier=2.5,
    enable_zone_filter=True,
    zone_block_distance=1.0
)

# Run backtest
backtester = Backtester(config)
results = backtester.run(df, strategy)

print(f"Total Return: {results.total_return_pct:.2f}%")
print(f"Win Rate: {results.win_rate:.2f}%")
print(f"Max DD: {results.max_drawdown:.2f}%")
print(f"Trades: {results.total_trades}")
```

## Conclusion

The Hybrid Zone-SuperTrend Strategy is a **conservative enhancement** that:
- Keeps everything that works (SuperTrend + ATR TP/SL)
- Adds intelligent structural filtering (zones)
- Can be toggled on/off for comparison
- Must prove value through backtest validation

**Philosophy**: Start with what's proven (SuperTrend), add structure awareness (zones), validate rigorously, and deploy only if demonstrably better.
