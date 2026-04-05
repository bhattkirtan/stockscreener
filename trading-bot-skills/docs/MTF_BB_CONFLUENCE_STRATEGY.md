# Multi-Timeframe Bollinger Band Confluence Strategy

## 1. Core Concept

Every Bollinger Band has three lines: upper, middle, lower.
Across multiple timeframes, these lines create a price map of likely reaction zones.

**When price is near any BB line — from any timeframe — it is at a decision point.**
The significance of that level is determined by how many BB lines from different timeframes
cluster at the same price.

```
Timeframes × 3 lines each = total BB levels on chart

5m  × 3 =  3 levels  (fast, local)
15m × 3 =  3 levels
1h  × 3 =  3 levels
4h  × 3 =  3 levels
Daily × 3 = 3 levels
─────────────────────
Total      15 BB levels on the chart at any moment
```

When 3+ lines from different timeframes cluster within ATR threshold of each other
→ high-probability reaction zone.

---

## 2. Dual Role of Every BB Line

A BB line acts as either a **magnet** or a **wall** depending on where price is relative to it.

```
WALL (resistance/support) — price IS at the line
    Upper band → resistance → push DOWN
    Lower band → support    → push UP
    Middle     → pivot      → direction determined by slope

MAGNET (target) — price is AWAY from the line
    Below upper → pulled upward toward it
    Above lower → pulled downward toward it
    Either side of middle → pulled toward it
```

**In both cases the direction signal is consistent:**
- Near lower band (or approaching from above) → bullish
- Near upper band (or approaching from below) → bearish

The only exception: price walking a band in a strong trend (slope confirms breakout, not rejection).

---

## 3. Timeframe Stack

| Timeframe | Role | Typical move size | Look-back for BB(20) |
|---|---|---|---|
| 5m | Trigger (entry) | Minutes–hours | ~100 bars = 8h |
| 15m | Micro context | Hours | ~300 bars = ~2.5d |
| 1h | Setup | Half-day to day | ~480 bars = 20d |
| 4h | Context | Days | ~120 bars = 20d |
| Daily | Trend direction | Weeks | ~20 bars = 1 month |

All computed by resampling M5 candles. Only **closed** candles used — never partially formed bars.

---

## 4. Confluence Detection

### 4.1 Band PCT

For each timeframe, at each bar:

```
band_pct = (close - lower) / (upper - lower)
```

Zones:
```
band_pct < 0.15   → AT lower band    = strong support
0.15 – 0.45       → lower half       = bullish pull
0.45 – 0.55       → middle zone      = use slope
0.55 – 0.85       → upper half       = bearish pull
band_pct > 0.85   → AT upper band    = strong resistance
```

### 4.2 Finding Clusters

At each 5m candle close, compute the absolute price of every BB line across all timeframes.
A cluster exists when 2+ lines from **different** timeframes are within `confluence_threshold`
of each other (default: 0.3 × ATR14 on 5m).

```python
bb_levels = {
    '5m_upper':    ..., '5m_middle':    ..., '5m_lower':    ...,
    '15m_upper':   ..., '15m_middle':   ..., '15m_lower':   ...,
    '1h_upper':    ..., '1h_middle':    ..., '1h_lower':    ...,
    '4h_upper':    ..., '4h_middle':    ..., '4h_lower':    ...,
    'daily_upper': ..., 'daily_middle': ..., 'daily_lower': ...,
}
```

Cluster score = number of distinct timeframes contributing a line to the cluster.

### 4.3 Zone Strength

| Cluster score | Strength |
|---|---|
| 1 line | Ignore |
| 2 lines, 1 TF | Weak |
| 2+ lines, 2+ TFs | Moderate |
| 3+ lines, 3+ TFs | Strong |
| HTF lines (4h/Daily) present | Significant upgrade |

---

## 5. Signal Logic

### 5.1 Direction at Cluster

```
Price approaching cluster from below → cluster is RESISTANCE → bearish
Price approaching cluster from above → cluster is SUPPORT    → bullish
```

Slope confirmation (prevent walking-band false signals):
```
Bearish cluster valid only if: 4h middle slope ≤ 0 OR 4h band_pct < 0.90
Bullish cluster valid only if: 4h middle slope ≥ 0 OR 4h band_pct > 0.10
```

### 5.2 Full Entry Conditions

**Long Entry:**
1. Nearest overhead cluster score ≥ 2 (or no cluster nearby) — room to run up
2. Nearest support cluster below price — something to bounce from
3. 4h band_pct < 0.80 — not already at 4h resistance
4. 5m Supertrend flips bullish
5. 5m close > EMA20
6. 5m band_pct < 0.85 — entry not overextended on 5m

**Short Entry:**
1. Nearest support cluster score ≥ 2 (or no cluster nearby) — room to fall
2. Nearest resistance cluster above price — something to reject from
3. 4h band_pct > 0.20 — not already at 4h support
4. 5m Supertrend flips bearish
5. 5m close < EMA20
6. 5m band_pct > 0.15 — entry not overextended on 5m

### 5.3 No-Trade Conditions

- 4h band_pct is neutral (0.40–0.60) and slope is flat → no directional bias
- 5m BB width extremely narrow (< 0.5 × ATR) → Supertrend unreliable
- Price is directly inside a high-strength cluster (3+ TFs) with no clear side — let it resolve first

---

## 6. Stop Loss

**Structural SL** — place beyond the nearest BB cluster that price is NOT at:

```
Long SL:  just below the nearest support cluster below entry
Short SL: just above the nearest resistance cluster above entry
```

Buffer: `0.25 × ATR14` on 5m, added beyond the cluster edge.

Minimum SL: instrument pip_size × min_sl_pips (from config) to prevent too-tight stops on volatile assets.

Hard invalidation (secondary, not main SL):
- Opposite 5m Supertrend fires AND price crosses EMA20 against trade → exit immediately.

---

## 7. Take Profit

Two-stage exit:

| Stage | Level | Action |
|---|---|---|
| TP1 | Nearest opposing BB cluster | Close 50%, move SL to breakeven |
| TP2 | Next opposing cluster or 2R | Trail: exit if 5m Supertrend flips or price crosses EMA20 |

**Why clusters as TP targets?**
The next BB cluster in the direction of the trade is where price is most likely to pause or reverse.
This is more adaptive than fixed R multiples — it respects where the market structure actually is.

---

## 8. Mapping to Current Codebase

### 8.1 What Exists

| Component | File | Current State |
|---|---|---|
| H1 BB computation | `analysis_skill.py` `_check_mtf_confluence()` | H1 only, look-ahead fixed |
| H1 resampling | `run_skills_backtest.py` | H1 only |
| Fixed SL/TP | `backtesting_skill.py` | Fixed pips or ATR |
| Single TP | `backtesting_skill.py` | One TP level |
| Supertrend + EMA trigger | `analysis_skill.py` | Working |

### 8.2 What Needs to Change

| Change | File | Complexity |
|---|---|---|
| Add 15m, 4h, Daily resampling | `run_skills_backtest.py` | Low |
| Attach `df_15m`, `df_4h`, `df_daily` to AnalysisSkill | `run_skills_backtest.py` | Low |
| Replace `_check_mtf_confluence()` with full cluster detection | `analysis_skill.py` | Medium |
| Structural SL (cluster-based) | `analysis_skill.py` + `sl_tp_engine.py` | Medium |
| Two-stage TP (partial close + trail) | `backtesting_skill.py` | High |
| Breakeven SL move after TP1 | `backtesting_skill.py` | High |
| Config keys for timeframes + thresholds | `trading_config.yaml` | Low |

### 8.3 Implementation Phases

**Phase 1 — Confluence detection + structural SL (backtest valid)**
- Add 15m, 4h, Daily resampling in `run_skills_backtest.py`
- Rewrite `_check_mtf_confluence()` to compute cluster score
- Replace fixed SL with cluster-based structural SL
- Keep single TP at nearest opposing cluster (no partial close yet)
- Config flag: `mtf_bb.enabled: true/false`

**Phase 2 — Two-stage TP**
- Add partial position tracking to `BacktestingSkill`
- Implement TP1 (close 50%, breakeven SL)
- Implement TP2 trail (exit on Supertrend flip or EMA cross)

**Phase 3 — Live trading**
- Same cluster logic runs in real-time per candle close
- No code change needed — event-driven architecture already handles per-candle events

---

## 9. Config Schema (proposed additions to trading_config.yaml)

```yaml
analysis:
  indicators:
    mtf_bb:
      enabled: true
      bb_period: 20
      bb_std: 2.0
      timeframes:
        - 5m
        - 15m
        - 1h
        - 4h
        - daily
      confluence_threshold_atr_mult: 0.3   # cluster radius = 0.3 × ATR14
      min_cluster_score: 2                  # minimum lines to call it a zone
      htf_weight: true                      # 4h/daily clusters weighted higher

  signal_rules:
    require_mtf_bb_confluence: false        # Phase 1: off by default, opt-in per instrument
    max_4h_band_pct_long: 0.80             # don't enter long if 4h already at upper band
    min_4h_band_pct_short: 0.20            # don't enter short if 4h already at lower band

  sl_tp:
    method: cluster                         # new method: structural cluster-based
    atr_buffer_mult: 0.25                  # SL buffer beyond cluster edge
    min_sl_pips: 10                        # instrument floor

backtesting:
  two_stage_tp:
    enabled: false                          # Phase 2
    tp1_close_pct: 0.50
    tp2_trail_on_supertrend_flip: true
    tp2_trail_on_ema_cross: true
```

---

## 10. One-Line Summary

**Enter 5m Supertrend + EMA signals only when price has room to move — measured by
multi-timeframe BB cluster proximity — and exit at the next cluster in the trade direction.**
