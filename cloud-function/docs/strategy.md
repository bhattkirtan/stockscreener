# Production-Ready Strategy Specification
## Zone-Based Intraday Trading System for Gold and US100

Version: 2.0  
Status: Production-ready specification  
Audience: strategy developer, quant, backtester, execution engineer

---

## 1. Scope

This document defines a production-ready trading specification for a zone-based intraday bot trading:

- **Gold** (`XAUUSD` or broker-equivalent symbol)
- **US100** (`US100`, `NAS100`, or broker-equivalent symbol)

The system uses:

- **H4 / H1 / M15** zones for structure
- **M5** for execution trigger
- **zone-aware SL and TP**
- **strict risk controls**
- **maximum 2 entries per idea**
- **no adding after invalidation**
- **daily circuit breakers**
- **news / spread / session filters**

This specification is designed for both:

- **historical backtesting**
- **live deployment via broker adapter**

---

## 2. Strategic Objective

The system is not designed to predict every move.

It is designed to:

- avoid low-quality entries into strong opposing structure
- trade only when there is room to the next target zone
- reduce stop-outs caused by placing stops inside obvious noise
- improve robustness across changing market conditions
- survive adverse periods through strict risk control

The system should prefer:

- **fewer, higher-quality trades**
- **structure-aware entries**
- **planned execution**
- **controlled downside**

---

## 3. Design Principles

### 3.1 Zones, not lines
Support and resistance are modeled as **zones with width**, not exact prices.

### 3.2 Higher timeframe first
Lower timeframes can refine execution but must not override strong higher-timeframe structure without confirmed break and acceptance.

### 3.3 Context before trigger
A valid M5 trigger is insufficient without valid H4/H1/M15 context.

### 3.4 No trade is a valid action
The bot must be comfortable skipping trades in poor structure, poor session conditions, or poor reward-to-risk conditions.

### 3.5 Risk is fixed before entry
The bot must determine total risk before the first entry. Entry 2 is only allowed if it was preplanned and the original idea remains valid.

### 3.6 Trade invalidation beats hope
Once invalidation is reached, the trade is over. No rescue entry, no averaging after invalidation.

---

## 4. Instruments and Trading Style

### 4.1 Instruments
- Gold
- US100

### 4.2 Trading style
- Intraday swing / structured scalping hybrid
- Primary holding period: minutes to several hours
- Same-day flattening optional by config

### 4.3 Not designed for
- unattended high-frequency trading
- pure M1-only scalping
- martingale recovery systems
- unrestricted averaging down

---

## 5. Timeframe Hierarchy

### 5.1 H4: Macro structure
Use H4 to detect:
- major swing highs and lows
- multi-session range extremes
- major breakout-retest levels
- dominant structural danger / target zones

Use H4 for:
- broad directional context
- major TP2 / TP3
- major invalidation context

### 5.2 H1: Main directional map
Use H1 to detect:
- current structural trend
- reclaimed zones
- pullback zones in trend
- session-level support/resistance

Use H1 for:
- primary directional bias
- stop placement context
- filtering longs vs shorts

### 5.3 M15: Active trade map
Use M15 to detect:
- intraday support/resistance
- session highs/lows
- local range boundaries
- local break/retest opportunities

Use M15 for:
- trade area definition
- nearby target zones
- local zone confluence

### 5.4 M5: Trigger timeframe
Use M5 only for:
- reclaim
- rejection
- failed retest
- breakout follow-through confirmation
- execution timing

M5 must **not** be used as the primary zone source.

---

## 6. Data Requirements

### 6.1 Required OHLC fields
Each timeframe feed must provide:

- `timestamp`
- `open`
- `high`
- `low`
- `close`

### 6.2 Optional but strongly recommended
- `volume` or tick volume
- `spread`
- bid / ask snapshots
- session flags
- calendar flags

### 6.3 Data quality rules
- timestamps must be monotonic ascending
- bars must be timezone-normalized
- missing bars must be handled explicitly
- duplicate timestamps must be rejected
- incomplete current bar must not be used as closed-bar signal input

### 6.4 Live-vs-backtest consistency
The live engine must only use information that would have been available at decision time.

No future bar leakage is allowed.

### 6.5 External data feed requirements
The strategy requires 4 separate data feeds beyond core price data:

1. **Price feed** - real-time tradable prices, spreads, execution
2. **Economic calendar** - scheduled macro events, forecasts, actuals
3. **Macro series** - regime-level economic indicators
4. **News headlines** - unscheduled event detection and sentiment

Each feed must maintain:
- timestamp precision
- availability guarantees
- failure modes
- staleness detection
- backtest replay capability

---

## 6.6 External Data Feeds Architecture

### 6.6.1 Design principles

**Separation of concerns**

Each data source serves a distinct purpose:
- price feed = execution reality
- calendar = scheduled risk windows
- macro series = regime context
- headlines = unscheduled risk detection

**No single point of failure**

The bot must continue operating with degraded confidence when:
- calendar feed is unavailable → use conservative time-based blocks
- macro feed is stale → use last known regime
- headline feed is down → skip headline-based filters only

**Backtest-live consistency**

All external feeds must support:
- historical data access for backtesting
- point-in-time correctness
- realistic latency simulation
- versioned data schemas

---

### 6.6.2 Feed 1: Price Feed (Capital.com)

**Purpose**

Provide real-time tradable market data and execution capabilities.

**Required data**
- OHLC candles for H4, H1, M15, M5
- current bid/ask prices
- real-time spread
- instrument metadata (tick size, contract value, trading hours)
- account state (equity, margin, positions)
- order placement and management

**Access method**
- REST API for historical candles and account queries
- WebSocket for real-time price updates (up to 40 instruments)
- WebSocket for position/order updates

**Instruments**
- Gold: `XAUUSD` or broker-specific symbol
- US100: `US100` or `NAS100` or broker-specific symbol

**Update frequency**
- WebSocket: real-time tick-by-tick for M5/M15 bars
- REST: on-demand for H1/H4 bar completion
- Spread: checked before every trade decision

**Failure modes**
- WebSocket disconnect → reconnect with exponential backoff
- stale data (>30s for M5) → enter safe mode, block new trades
- REST timeout → retry up to 3 times, then fail safe

**Data schema**
```python
{
  "timestamp": "2026-03-13T14:30:00Z",
  "symbol": "XAUUSD",
  "timeframe": "M5",
  "open": 2150.25,
  "high": 2151.80,
  "low": 2149.90,
  "close": 2151.20,
  "volume": 12500,
  "bid": 2151.15,
  "ask": 2151.25,
  "spread": 0.10
}
```

**Backtest requirements**
- historical candle data for all timeframes
- realistic spread assumptions (95th percentile by session)
- simulated slippage model
- no lookahead bias in bar timestamps

**Configuration**
```yaml
capital_com:
  api_key: ${CAPITAL_COM_API_KEY}
  api_url: "https://api-capital.backend-capital.com/api/v1"
  ws_url: "wss://api-capital.backend-capital.com/streaming"
  demo_mode: false
  symbols:
    gold: "XAUUSD"
    us100: "US100"
  timeframes: ["M5", "M15", "H1", "H4"]
  spread_check_enabled: true
  max_spread_multiplier: 3.0
  stale_data_threshold_seconds: 30
  reconnect_max_attempts: 10
  reconnect_delay_seconds: 5
```

---

### 6.6.3 Feed 2: Economic Calendar (Trading Economics)

**Purpose**

Provide scheduled macro event data for trade blocking and risk reduction.

**Required data**
- event name, country, category
- scheduled timestamp (with timezone)
- importance level (low, medium, high)
- previous value
- forecast/consensus
- actual value (post-release)

**Key events for Gold**
- US CPI (all components)
- US NFP / unemployment
- FOMC rate decisions
- Fed Chair speeches
- US PPI
- US GDP
- US Retail Sales
- geopolitical risk events
- central bank decisions (ECB, BoE if relevant)

**Key events for US100**
- All Gold events plus:
- mega-cap tech earnings (if used for headline filter)
- US ISM Manufacturing/Services
- US Consumer Confidence
- US leading indicators

**Access method**
- REST API for calendar queries
- daily batch fetch for next 7 days
- intraday refresh every 4 hours
- immediate post-event fetch for actual values

**Update frequency**
- full calendar: daily at 00:00 UTC
- incremental: every 4 hours during trading day
- event window: 15 min before → 15 min after

**Data schema**
```python
{
  "event_id": "US_CPI_2026_03_13",
  "country": "United States",
  "category": "Inflation",
  "event": "Consumer Price Index YoY",
  "date": "2026-03-13T13:30:00Z",
  "importance": "high",
  "previous": "3.2%",
  "forecast": "3.1%",
  "actual": "3.4%",
  "revised": null,
  "impact_symbols": ["XAUUSD", "US100"],
  "block_minutes_before": 15,
  "block_minutes_after": 15
}
```

**Importance classification**
- **high**: FOMC, NFP, CPI, GDP, Fed speeches, rate decisions
- **medium**: PPI, Retail Sales, jobless claims, ISM
- **low**: most other indicators

**Trade blocking rules**
- high-impact: block 15min before → 15min after (configurable to 30min)
- medium-impact: block 10min before → 10min after (optional)
- low-impact: no block, but log for analysis

**Failure modes**
- API unavailable → use cached calendar + manual event list fallback
- stale calendar (>24h) → switch to conservative time-based blocks
- missing event → log warning, use default blocks for known recurring events

**Backtest requirements**
- historical event calendar with actual release times
- importance levels must match live classification
- surprise factor: `(actual - forecast) / previous`

**Configuration**
```yaml
trading_economics:
  api_key: ${TRADING_ECONOMICS_API_KEY}
  api_url: "https://api.tradingeconomics.com"
  countries: ["United States"]
  update_interval_hours: 4
  cache_duration_hours: 48
  high_impact_events:
    - "Consumer Price Index"
    - "Nonfarm Payrolls"
    - "FOMC Rate Decision"
    - "Fed Chair Speech"
    - "GDP Growth Rate"
  block_minutes_before_high: 15
  block_minutes_after_high: 15
  block_minutes_before_medium: 10
  block_minutes_after_medium: 10
  enable_surprise_factor: true
```

---

### 6.6.4 Feed 3: Macro Series (FRED)

**Purpose**

Provide regime-level economic context for bias adjustment and confidence scoring.

**Required series**

**Rates and yields**
- `DFF`: Federal Funds Effective Rate
- `DGS10`: 10-Year Treasury Constant Maturity Rate
- `DGS2`: 2-Year Treasury Constant Maturity Rate
- `T10Y2Y`: 10-Year minus 2-Year Treasury Spread

**USD proxies**
- `DTWEXBGS`: Trade Weighted U.S. Dollar Index: Broad, Goods and Services

**Inflation**
- `CPIAUCSL`: Consumer Price Index for All Urban Consumers
- `PCEPI`: Personal Consumption Expenditures Price Index

**Labor market**
- `UNRATE`: Unemployment Rate
- `PAYEMS`: All Employees, Total Nonfarm

**Growth and recession indicators**
- `GDP`: Gross Domestic Product
- `USREC`: NBER Recession Indicators (binary)

**Access method**
- REST API for series queries
- daily batch fetch for all series
- most series update monthly/quarterly, so daily fetch is sufficient

**Update frequency**
- daily fetch at 08:00 UTC
- on-demand fetch if specific indicator is released

**Data schema**
```python
{
  "series_id": "DFF",
  "date": "2026-03-12",
  "value": 4.50,
  "units": "Percent",
  "frequency": "Daily",
  "last_updated": "2026-03-13T08:00:00Z"
}
```

**Usage patterns**

**Rate regime detection**
- rising rates: `DFF` trend over 60 days
- inverted yield curve: `T10Y2Y < 0`
- high real rates: `DFF - CPI_YoY`

**USD regime detection**
- strong USD: `DTWEXBGS` above 90-day MA
- weakening USD: `DTWEXBGS` below 90-day MA

**Risk-on / risk-off proxy**
- recession flag: `USREC == 1`
- labor market strength: `UNRATE` trend

**Gold-specific context**
- real rates rising + strong USD = headwind for gold
- inverted curve + recession risk = tailwind for gold
- high inflation + dovish Fed = tailwind for gold

**US100-specific context**
- rising rates + strong growth = neutral to positive
- rising rates + weak growth = headwind
- rate cuts + recession = mixed (depends on depth)

**Regime state machine**
```python
if DFF_trend > 0 and T10Y2Y < 0:
    regime = "hawkish_inversion"  # caution for risk assets
elif DFF_trend < 0 and USREC == 1:
    regime = "easing_recession"   # mixed for equities, good for gold
elif DFF_trend > 0 and DTWEXBGS > DTWEXBGS_MA90:
    regime = "strong_dollar_tightening"  # headwind for gold
else:
    regime = "neutral"
```

**Failure modes**
- API unavailable → use last known regime (acceptable for daily data)
- stale data (>7 days) → log warning, switch to price-only mode

**Backtest requirements**
- historical series with correct vintage dates
- no forward-looking revisions

**Configuration**
```yaml
fred:
  api_key: ${FRED_API_KEY}
  api_url: "https://api.stlouisfed.org/fred"
  series:
    - id: "DFF"
      description: "Federal Funds Rate"
    - id: "DGS10"
      description: "10-Year Treasury Yield"
    - id: "DGS2"
      description: "2-Year Treasury Yield"
    - id: "T10Y2Y"
      description: "10Y-2Y Spread"
    - id: "DTWEXBGS"
      description: "USD Index Broad"
    - id: "CPIAUCSL"
      description: "CPI All Urban"
    - id: "UNRATE"
      description: "Unemployment Rate"
    - id: "USREC"
      description: "Recession Indicator"
  update_interval_hours: 24
  stale_threshold_days: 7
  regime_lookback_days: 90
```

---

### 6.6.5 Feed 4: News Headlines (NewsAPI)

**Purpose**

Detect unscheduled risk events and provide headline-based trade blocking.

**Required data**
- headline text
- source / publisher
- published timestamp
- category / tags
- relevance score to instruments

**Key topics for Gold**
- Fed policy surprises
- geopolitical escalation
- banking stress
- dollar moves
- inflation surprises
- central bank interventions

**Key topics for US100**
- mega-cap tech news
- rate surprise between scheduled events
- tech regulation
- earnings surprises for AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA
- market structure events (circuit breakers, flash crashes)

**Access method**
- REST API for headline search
- query every 5 minutes during active trading
- filter by keywords and sources

**Update frequency**
- polling: every 5 minutes during London/US sessions
- reduced frequency: every 15 minutes during Asia session

**Data schema**
```python
{
  "article_id": "newsapi_123456",
  "source": "Reuters",
  "title": "Fed signals pause on rate cuts amid inflation concerns",
  "published_at": "2026-03-13T14:22:00Z",
  "url": "https://...",
  "keywords": ["Fed", "rates", "inflation"],
  "impact_score": 0.85,
  "instruments": ["XAUUSD", "US100"],
  "sentiment": "risk_off",
  "block_recommended": true,
  "block_duration_minutes": 10
}
```

**Keyword filters**

**High-impact keywords (block trades)**
- "Fed emergency"
- "rate surprise"
- "geopolitical crisis"
- "bank failure"
- "circuit breaker"
- "flash crash"
- "market halt"

**Monitor keywords (reduce confidence, don't block)**
- "Fed official"
- "Treasury"
- "dollar surge"
- "inflation data"
- "tech earnings miss"

**Usage rules**

**v1 (conservative)**

Use headlines only as blockers, not as trade triggers.

If high-impact headline detected:
- block new trades for 10 to 15 minutes
- reduce position size by 50% if already planning entry
- tighten stops on open positions (optional)

**v2 (advanced, future)**

Use sentiment scoring to adjust:
- trade score penalty: `-10` to `-20` for risk-off headlines
- confidence multiplier: `0.5x` to `0.75x` during high news flow

**Never** use raw headlines to auto-generate trades in v1.

**Failure modes**
- API unavailable → disable headline filter, log warning
- rate limit exceeded → reduce polling frequency
- irrelevant noise → tighten keyword filters

**Backtest requirements**
- historical headline corpus with accurate timestamps
- keyword matching must be deterministic
- sentiment scores must be reproducible

**Configuration**
```yaml
news_api:
  api_key: ${NEWSAPI_API_KEY}
  api_url: "https://newsapi.org/v2"
  sources:
    - "reuters"
    - "bloomberg"
    - "ft"
    - "wsj"
  keywords:
    high_impact:
      - "Fed emergency"
      - "rate surprise"
      - "bank failure"
      - "geopolitical crisis"
    monitor:
      - "Fed official"
      - "inflation"
      - "dollar"
  polling_interval_minutes: 5
  block_duration_minutes: 10
  enable_sentiment_scoring: false  # v1: disabled
  enable_trade_blocking: true
```

---

### 6.6.6 Data feed priority and fallback logic

**Critical feeds (bot cannot run without these)**
- Capital.com price feed

**High-priority feeds (bot runs with reduced capabilities)**
- Trading Economics calendar

Fallback: use manual event list + conservative time blocks

**Medium-priority feeds (bot runs, loses regime awareness)**
- FRED macro series

Fallback: use neutral regime assumption

**Low-priority feeds (bot runs, loses headline filter)**
- NewsAPI headlines

Fallback: disable headline-based blocking

**Feed health monitoring**

Each feed must report:
- last successful update timestamp
- staleness (time since last update)
- error count in last hour
- current availability status: `healthy | degraded | failed`

**Bot decision logic**
```python
if capital_com_status == "failed":
    shutdown_bot("critical feed unavailable")

if trading_economics_status == "failed":
    switch_to_manual_event_blocks()
    reduce_trade_score_threshold(+10)  # more conservative

if fred_status == "failed":
    use_neutral_regime()
    log_warning("macro context unavailable")

if news_api_status == "failed":
    disable_headline_filter()
    log_warning("headline blocking disabled")
```

---

### 6.6.7 Integration testing requirements

**Unit tests**
- parse each feed's response schema
- handle malformed data gracefully
- validate timestamp formats
- test staleness detection

**Integration tests**
- simulate feed outages
- test fallback logic
- verify no trades during blocked windows
- confirm regime detection logic

**End-to-end tests**
- backtest with all feeds enabled
- backtest with each feed disabled independently
- verify performance doesn't collapse without optional feeds

**Live dry-run requirements**
- run bot in paper trading mode for 1 week
- monitor all feed health metrics
- verify event blocking works in real-time
- log all feed failures and recovery

---

## 7. Session Model

### 7.1 Session buckets
Each bar should be labeled into one of:
- Asia
- London
- US pre-open
- US cash open
- US afternoon
- rollover / thin liquidity

### 7.2 Default session preferences
#### Gold
Prefer:
- London
- London/US overlap
- active US session

Use caution during:
- rollover
- very thin periods
- major event windows

#### US100
Prefer:
- US pre-open only if tested
- US cash open
- first 2 to 3 hours of cash session
- active US session trend windows

Use caution during:
- first minutes of extreme open volatility unless explicitly modeled
- lunch drift
- post-close thin conditions

### 7.3 Session quality score
Assign a session quality multiplier:

- strong session = `1.0`
- acceptable session = `0.75`
- poor session = `0.25`
- blocked session = `0.0`

A blocked session cannot generate trades.

---

## 8. News Model

### 8.1 High-impact event windows
Examples include:
- CPI
- NFP
- FOMC / Fed rate decisions
- Powell speeches
- PPI
- GDP
- Retail Sales
- major US macro events relevant to Gold / US100

### 8.2 Default news rules
- No new entries from **15 minutes before** until **15 minutes after** a high-impact event
- No second entry inside the blocked window
- Optional stricter mode: 30 minutes before / after

### 8.3 Post-news stabilization rule
Even after the news block ends, the bot may require:
- spread normalization
- at least one closed bar beyond the event spike phase

### 8.4 News override
If the system lacks reliable calendar data in live mode, the default behavior should be:
- disable trading during manually configured known major event windows
- or run in safe mode with reduced risk

### 8.5 Trading Economics integration

**Implementation approach**

The bot queries Trading Economics API for events in next 7 days and current day:

```python
def fetch_calendar_events(start_date, end_date, countries=["United States"]):
    """Fetch economic calendar from Trading Economics."""
    events = trading_economics_api.get_calendar(
        country=countries,
        start_date=start_date,
        end_date=end_date
    )
    return [parse_event(e) for e in events if e["importance"] in ["high", "medium"]]

def is_blocked_by_news(current_time, events, config):
    """Check if current time is in a blocked event window."""
    for event in events:
        if event["importance"] == "high":
            block_before = config["block_minutes_before_high"]
            block_after = config["block_minutes_after_high"]
        else:
            block_before = config["block_minutes_before_medium"]
            block_after = config["block_minutes_after_medium"]
        
        window_start = event["date"] - timedelta(minutes=block_before)
        window_end = event["date"] + timedelta(minutes=block_after)
        
        if window_start <= current_time <= window_end:
            return True, event
    
    return False, None
```

**Event caching strategy**

1. Fetch calendar daily at 00:00 UTC
2. Refresh every 4 hours during trading day
3. Cache locally with 48-hour TTL
4. On API failure, use cached events + manual fallback list

**Manual fallback event list**

If Trading Economics API is unavailable, block these recurring times (US Eastern):
- First Friday of month, 08:30 ET (NFP)
- Mid-month, ~14:00 ET (FOMC, if scheduled)
- 13th of month, 08:30 ET (CPI, typically)

This is a safety net only, not a replacement for real calendar data.

---

### 8.6 Macro regime context integration (FRED)

**Purpose**

FRED macro series provide slower-moving context that can adjust:
- directional bias confidence
- trade score modifiers
- instrument preference (gold vs US100)

**Regime definitions**

**1. Hawkish tightening + strong USD**
- `DFF` rising over 90 days
- `DTWEXBGS` > 90-day MA
- Impact: headwind for gold, neutral for US100

**2. Inverted yield curve**
- `T10Y2Y < 0`
- Impact: caution for US100, mixed for gold

**3. Easing cycle with recession risk**
- `DFF` falling over 90 days
- `USREC == 1` or `UNRATE` rising
- Impact: tailwind for gold, headwind for US100

**4. High real rates**
- `DFF - CPI_YoY > 2.0`
- Impact: headwind for gold

**5. Neutral / balanced**
- None of the above conditions met
- Impact: no regime adjustment

**Trade score adjustments**

**Gold longs**
- hawkish + strong USD: `-15` score
- easing + recession risk: `+10` score
- high real rates: `-10` score

**Gold shorts**
- hawkish + strong USD: `+10` score
- easing + recession risk: `-15` score

**US100 longs**
- inverted curve + recession: `-15` score
- strong growth + stable rates: `+10` score

**US100 shorts**
- inverted curve + recession: `+10` score

**Implementation**

```python
def detect_macro_regime(fred_data):
    """Detect macro regime from FRED series."""
    dff_trend = compute_trend(fred_data["DFF"], days=90)
    usd_vs_ma = fred_data["DTWEXBGS"][-1] - moving_average(fred_data["DTWEXBGS"], 90)
    curve_spread = fred_data["T10Y2Y"][-1]
    recession_flag = fred_data["USREC"][-1]
    
    regime = {
        "hawkish_strong_usd": dff_trend > 0 and usd_vs_ma > 0,
        "inverted_curve": curve_spread < 0,
        "easing_recession": dff_trend < 0 and recession_flag == 1,
        "high_real_rates": fred_data["DFF"][-1] - compute_cpi_yoy(fred_data) > 2.0
    }
    
    return regime

def apply_macro_adjustment(trade_score, symbol, direction, regime):
    """Apply macro regime adjustment to trade score."""
    adjustment = 0
    
    if symbol == "XAUUSD":
        if direction == "long":
            if regime["hawkish_strong_usd"]:
                adjustment -= 15
            if regime["easing_recession"]:
                adjustment += 10
            if regime["high_real_rates"]:
                adjustment -= 10
        elif direction == "short":
            if regime["hawkish_strong_usd"]:
                adjustment += 10
            if regime["easing_recession"]:
                adjustment -= 15
    
    elif symbol == "US100":
        if direction == "long":
            if regime["inverted_curve"] and regime["easing_recession"]:
                adjustment -= 15
        elif direction == "short":
            if regime["inverted_curve"]:
                adjustment += 10
    
    return trade_score + adjustment
```

**Update frequency**

FRED data is daily, so regime updates once per day are sufficient.

---

### 8.7 Headline-based risk blocking (NewsAPI)

**Purpose**

Detect unscheduled high-impact events and block trades temporarily.

**v1 implementation (conservative)**

NewsAPI is used only as a blocker, not as a trade signal generator.

**Query logic**

```python
def fetch_recent_headlines(keywords, lookback_minutes=30):
    """Fetch headlines from NewsAPI matching high-impact keywords."""
    query = " OR ".join(keywords)
    articles = newsapi.get_everything(
        q=query,
        sources="reuters,bloomberg,financial-times,wsj",
        from_param=datetime.now() - timedelta(minutes=lookback_minutes),
        language="en",
        sort_by="publishedAt"
    )
    return articles["articles"]

def check_headline_block(current_time, config):
    """Check if recent headlines warrant trade blocking."""
    headlines = fetch_recent_headlines(
        keywords=config["high_impact_keywords"],
        lookback_minutes=30
    )
    
    for headline in headlines:
        for keyword in config["high_impact_keywords"]:
            if keyword.lower() in headline["title"].lower():
                time_since_publish = (current_time - headline["publishedAt"]).seconds / 60
                if time_since_publish < config["block_duration_minutes"]:
                    return True, headline
    
    return False, None
```

**High-impact keywords (block immediately)**
- "Fed emergency"
- "bank failure"
- "rate surprise"
- "geopolitical crisis"
- "market halt"
- "circuit breaker"

**Block duration**
- default: 10 minutes after headline detected
- configurable: 5 to 30 minutes

**Backtest handling**

In backtests, historical headline data must be available with accurate timestamps.

If unavailable, disable headline filter in backtest and note it as a limitation.

---

## 9. Zone Model

### 9.1 Zone schema
Each zone must include:

- `id`
- `symbol`
- `timeframe`
- `type` = `support | resistance | flip`
- `lower_bound`
- `upper_bound`
- `midpoint`
- `origin_type`
- `created_at`
- `last_tested_at`
- `touch_count`
- `freshness_score`
- `strength_score`
- `state`

### 9.2 Zone origin types
Allowed origin types:
- `swing`
- `range_edge`
- `breakout_retest`
- `impulse_base`
- `session_high_low`
- `previous_day_extreme`

### 9.3 Zone states
Each zone must be classified into one of:
- `fresh`
- `tested`
- `respected`
- `weakened`
- `broken`
- `flipped`
- `invalid`

### 9.4 Zone width
Zone width is volatility-adjusted.

Suggested half-width formulas:

- H4: `0.25 to 0.40 * ATR(H4, 14)`
- H1: `0.20 to 0.30 * ATR(H1, 14)`
- M15: `0.15 to 0.25 * ATR(M15, 14)`

Default recommended values:

- Gold:
  - H4 = `0.35 * ATR`
  - H1 = `0.25 * ATR`
  - M15 = `0.18 * ATR`
- US100:
  - H4 = `0.30 * ATR`
  - H1 = `0.22 * ATR`
  - M15 = `0.16 * ATR`

### 9.5 Zone merge rule
Zones of the same type should merge if they overlap or their gap is below a configurable merge threshold.

Recommended merge threshold:
- `0.10 * ATR(timeframe)`

Merged zone properties:
- lower = min(lower bounds)
- upper = max(upper bounds)
- midpoint = midpoint of merged bounds
- score = sum of scores + overlap bonus
- touch_count = sum or recomputed touch count

### 9.6 Cluster zones
When zones from multiple timeframes overlap, create a cluster.

Cluster score:

`cluster_score = sum(component_scores) + overlap_bonus`

Overlap bonus:
- 2 overlapping timeframes: `+1`
- 3 overlapping timeframes: `+2`

Clusters are prioritized for:
- reversal caution
- TP targets
- invalidation context

---

## 10. Zone Strength Scoring

### 10.1 Base timeframe weight
- H4 = `3`
- H1 = `2`
- M15 = `1`

### 10.2 Strength modifiers
Add:
- strong rejection = `+1`
- breakout then successful retest = `+2`
- aligns with previous day high/low = `+1`
- aligns with session high/low = `+1`
- aligns with round number = `+0.5`
- impulsive move away = `+1`
- fresh zone = `+1`
- 2 to 3 valid touches = `+0.25` each up to `+2`

Subtract:
- too many messy touches = `-1`
- stale zone = `-1`
- repeated intrazone chopping = `-1`

### 10.3 Minimum strong-zone threshold
Recommended thresholds:
- Gold: `zone_score >= 4.0` = strong
- US100: `zone_score >= 3.5` = strong

These values can be optimized but should remain stable across walk-forward tests.

---

## 11. Directional Bias Model

### 11.1 Bias sources
Bias is derived from H4 and H1.

Suggested v1 logic:
- EMA(20) vs EMA(50) on H1 and H4
- optional slope confirmation
- optional market structure confirmation (higher highs / lower lows)

### 11.2 Bias states
- `bullish`
- `bearish`
- `neutral`

### 11.3 Bias rules
- bullish if H1 fast > H1 slow and H4 fast >= H4 slow
- bearish if H1 fast < H1 slow and H4 fast <= H4 slow
- otherwise neutral

### 11.4 Directional trade preference
- bullish bias: prefer longs
- bearish bias: prefer shorts
- neutral bias: require higher trigger score and stronger room-to-target

---

## 12. Trigger Model (M5)

### 12.1 Allowed trigger types
- bullish reclaim
- bearish rejection
- breakdown + failed retest
- breakout + successful retest

### 12.2 Trigger definitions
#### Bullish reclaim
Current M5 bar closes above previous bar high and closes bullish.

#### Bearish rejection
Current M5 bar closes below previous bar low and closes bearish.

#### Breakdown + failed retest
Price breaks support, retests it from below, and M5 confirms rejection.

#### Breakout + successful retest
Price breaks resistance, retests it from above, and M5 confirms hold.

### 12.3 Invalid trigger context
A trigger is invalid if:
- spread is too wide
- news blocked
- daily loss limit reached
- no room to target
- signal goes directly into stronger opposing zone without confirmed break

---

## 13. Trade Selection Logic

### 13.1 Longs
A long is preferred when:
- H1/H4 bias is bullish or neutral with strong evidence
- price is near support or support cluster
- M5 reclaim/reversal trigger confirms
- room exists to next opposing zone
- no strong resistance immediately overhead unless breakout logic is used

### 13.2 Shorts
A short is preferred when:
- H1/H4 bias is bearish or neutral with strong evidence
- price is near resistance or resistance cluster
- M5 rejection or failed retest confirms
- room exists to next opposing zone
- no strong support immediately below unless breakdown logic is used

### 13.3 Explicit structural caution rules
#### No short directly into strong support
Unless:
- support breaks decisively
- retest from below fails
- M5 confirms rejection
- price accepts below the zone

#### No long directly into strong resistance
Unless:
- resistance breaks decisively
- retest from above holds
- M5 confirms continuation
- price accepts above the zone

---

## 14. Entry Model

### 14.1 Entry count
Maximum **2 entries per idea**.

### 14.2 Entry 1
Entry 1 is placed when the trade score passes the minimum threshold and trigger confirms.

### 14.3 Entry 2
Entry 2 is optional and allowed only if all conditions are true:
- it was preplanned before Entry 1
- total risk remains below hard cap
- original invalidation level is unchanged
- bias/regime is unchanged
- spread is normal
- no news block active
- entry count for the idea is less than 2

### 14.4 No adding after invalidation
Once the invalidation level is breached, the idea is over.

No third entry. No rescue entry.

---

## 15. Stop Loss Model

### 15.1 Primary rule
The stop must be placed **outside the zone plus buffer**.

### 15.2 Long stop formula
`SL = zone_low - stop_buffer`

### 15.3 Short stop formula
`SL = zone_high + stop_buffer`

### 15.4 Stop buffer
Recommended buffer:
- `0.10 to 0.20 * ATR(M5)` for fine execution
- or `0.10 to 0.20 * ATR(M15)` if M5 is too noisy

Recommended v1 default:
- `0.20 * ATR(M5)`

### 15.5 Catastrophic stop
An optional catastrophic stop may exist for account protection only.

It must not replace the strategy invalidation stop in backtests.

### 15.6 Stop quality rules
Reject trades where the stop would be:
- inside the zone
- too tight relative to current spread
- too tight relative to instrument volatility

---

## 16. Take Profit Model

### 16.1 Opposing-zone targeting
Take profit is mapped to the next meaningful opposing zone.

### 16.2 TP ladder
Recommended structure:
- TP1 = nearest M15 opposing zone
- TP2 = nearest H1 opposing zone
- optional runner = nearest H4 opposing zone or trailing exit

### 16.3 Reward-to-risk rule
Minimum acceptable RR before trade entry:
- default `1.5R`
- preferred `2.0R` when market is noisy or bias is neutral

### 16.4 Room-to-target filter
A trade is rejected if:

`distance_to_next_target_zone < min_rr * stop_distance`

### 16.5 Partial exits
Recommended v1:
- take partial at TP1
- move stop to managed level only if tested and robust

Break-even shifts must be backtested. Do not assume they help.

---

## 17. Trade Scoring Model

### 17.1 Objective
Each setup receives a score from `0` to `100`.

### 17.2 Suggested scoring components
- directional bias alignment: `20`
- zone quality / confluence: `20`
- trigger quality: `15`
- room to target: `15`
- volatility quality: `10`
- session quality: `10`
- spread quality: `5`
- no-news / event safety: `5`

### 17.3 Example adjustments
#### Longs
- near strong support + bullish reclaim: `+15`
- directly under strong resistance: `-15`

#### Shorts
- near strong resistance + bearish reject: `+15`
- directly above strong support: `-15`

### 17.4 Minimum score thresholds
Recommended:
- normal mode: `>= 65`
- conservative mode: `>= 72`
- neutral-bias mode: `>= 75`

---

## 18. Spread Filter

### 18.1 Spread rule
Reject trades if current spread exceeds a fraction of ATR on the execution timeframe.

Suggested default:
- `spread <= 0.12 * ATR(M5)`

### 18.2 Hard block conditions
Block trades if:
- spread spikes above max threshold
- spread is unavailable in live mode
- spread is above tested historical assumptions

### 18.3 Backtest realism
Backtests must include realistic spread assumptions. No zero-spread fantasy testing.

---

## 19. Risk Model

### 19.1 Hard risk per idea
Recommended v1:
- Gold: `0.75% to 1.00%` equity risk per idea
- US100: `0.50% to 0.75%` equity risk per idea

### 19.2 Daily loss limit
Recommended:
- soft limit: `-1.5%` → reduce size by 50%
- hard limit: `-2.0%` → stop trading for the day

### 19.3 Position sizing formula
Given:
- `equity`
- `risk_pct`
- `entry_price`
- `stop_price`
- instrument point value / contract value

Then:

`cash_risk = equity * risk_pct`

`risk_per_unit = abs(entry_price - stop_price) * contract_value`

`position_size = floor(cash_risk / risk_per_unit)`

Broker-specific minimum size and step size must be enforced.

### 19.4 Split-risk model for 2 entries
Example for total idea risk `R_total`:
- Entry 1 risk = `0.4 * R_total`
- Entry 2 risk = `0.6 * R_total`

Alternative tested split:
- `50 / 50`

### 19.5 Risk invariants
The system must always enforce:
- total planned idea risk <= hard cap
- adding cannot increase idea risk beyond hard cap
- open risk across all positions <= global account cap

---

## 20. Trade Lifecycle State Machine

Each idea moves through these states:

1. `candidate`
2. `validated`
3. `entry_1_active`
4. `entry_2_eligible`
5. `full_position_active`
6. `tp1_hit`
7. `closed_win`
8. `closed_loss`
9. `invalidated`
10. `blocked`

### 20.1 Candidate
Zones, bias, and trigger create a possible setup.

### 20.2 Validated
Setup passes all filters.

### 20.3 Entry 1 active
First order is live or filled.

### 20.4 Entry 2 eligible
Only allowed if still valid and preplanned.

### 20.5 Full position active
Entry 1 and Entry 2 are both filled.

### 20.6 Invalidated
Price breaches invalidation level.

No additional entries allowed.

---

## 21. Configuration Defaults

```yaml
strategy:
  symbols:
    - XAUUSD
    - US100

  timeframe_map:
    macro: H4
    bias: H1
    zone: M15
    trigger: M5

  risk:
    gold_risk_per_idea_pct: 0.0100
    us100_risk_per_idea_pct: 0.0075
    daily_soft_loss_limit_pct: 0.0150
    daily_hard_loss_limit_pct: 0.0200
    max_entries_per_idea: 2

  zone:
    h4_width_atr_fraction_gold: 0.35
    h1_width_atr_fraction_gold: 0.25
    m15_width_atr_fraction_gold: 0.18
    h4_width_atr_fraction_us100: 0.30
    h1_width_atr_fraction_us100: 0.22
    m15_width_atr_fraction_us100: 0.16
    strong_zone_threshold_gold: 4.0
    strong_zone_threshold_us100: 3.5

  stop:
    stop_buffer_atr_fraction: 0.20
    min_rr_for_trade: 1.5

  filters:
    max_spread_atr_fraction: 0.12
    no_trade_minutes_before_news: 15
    no_trade_minutes_after_news: 15
    min_trade_score: 65
    min_trade_score_neutral_bias: 75

# External data feeds
external_data:
  # Feed 1: Price and execution
  capital_com:
    api_key: ${CAPITAL_COM_API_KEY}
    api_url: "https://api-capital.backend-capital.com/api/v1"
    ws_url: "wss://api-capital.backend-capital.com/streaming"
    demo_mode: false
    symbols:
      gold: "XAUUSD"
      us100: "US100"
    timeframes: ["M5", "M15", "H1", "H4"]
    spread_check_enabled: true
    max_spread_multiplier: 3.0
    stale_data_threshold_seconds: 30
    reconnect_max_attempts: 10
    reconnect_delay_seconds: 5

  # Feed 2: Economic calendar
  trading_economics:
    api_key: ${TRADING_ECONOMICS_API_KEY}
    api_url: "https://api.tradingeconomics.com"
    countries: ["United States"]
    update_interval_hours: 4
    cache_duration_hours: 48
    high_impact_events:
      - "Consumer Price Index"
      - "Nonfarm Payrolls"
      - "FOMC Rate Decision"
      - "Fed Chair Speech"
      - "Fed Chair Testimony"
      - "GDP Growth Rate"
      - "Producer Price Index"
      - "Retail Sales"
    medium_impact_events:
      - "Jobless Claims"
      - "ISM Manufacturing PMI"
      - "ISM Services PMI"
      - "Consumer Confidence"
    block_minutes_before_high: 15
    block_minutes_after_high: 15
    block_minutes_before_medium: 10
    block_minutes_after_medium: 10
    enable_surprise_factor: true
    fallback_to_manual_events: true

  # Feed 3: Macro series
  fred:
    api_key: ${FRED_API_KEY}
    api_url: "https://api.stlouisfed.org/fred"
    series:
      - id: "DFF"
        description: "Federal Funds Rate"
      - id: "DGS10"
        description: "10-Year Treasury Yield"
      - id: "DGS2"
        description: "2-Year Treasury Yield"
      - id: "T10Y2Y"
        description: "10Y-2Y Spread"
      - id: "DTWEXBGS"
        description: "USD Index Broad"
      - id: "CPIAUCSL"
        description: "CPI All Urban"
      - id: "UNRATE"
        description: "Unemployment Rate"
      - id: "USREC"
        description: "Recession Indicator"
    update_interval_hours: 24
    stale_threshold_days: 7
    regime_lookback_days: 90
    enable_regime_adjustments: true
    # Regime adjustment magnitudes
    regime_score_adjustments:
      gold_long_hawkish_usd: -15
      gold_long_easing_recession: +10
      gold_long_high_real_rates: -10
      gold_short_hawkish_usd: +10
      gold_short_easing_recession: -15
      us100_long_inverted_recession: -15
      us100_long_strong_growth: +10
      us100_short_inverted: +10

  # Feed 4: News headlines
  news_api:
    api_key: ${NEWSAPI_API_KEY}
    api_url: "https://newsapi.org/v2"
    enabled: true
    sources:
      - "reuters"
      - "bloomberg"
      - "financial-times"
      - "the-wall-street-journal"
    keywords:
      high_impact:
        - "Fed emergency"
        - "emergency rate"
        - "bank failure"
        - "rate surprise"
        - "geopolitical crisis"
        - "market halt"
        - "circuit breaker"
        - "trading suspended"
      monitor:
        - "Fed official"
        - "inflation surprise"
        - "dollar surge"
        - "Powell speech"
        - "Treasury auction"
    polling_interval_minutes: 5
    lookback_minutes: 30
    block_duration_minutes: 10
    enable_sentiment_scoring: false  # v1: disabled, v2: enabled
    enable_trade_blocking: true

  # Feed health and fallback
  feed_health:
    staleness_check_interval_seconds: 60
    capital_com_critical: true
    trading_economics_critical: false
    fred_critical: false
    news_api_critical: false
    degraded_mode_score_penalty: 10
```

---

## 22. Pseudocode

```python
if daily_hard_loss_limit_hit:
    block_all_trades()

if news_blocked or spread_too_wide or poor_session:
    skip()

zones = build_zones(H4, H1, M15)
bias = compute_bias(H4, H1)
trigger = evaluate_m5_trigger(M5)
price = M5.close[-1]

support_context = nearest_support_clusters(price, zones)
resistance_context = nearest_resistance_clusters(price, zones)

long_score = 0
short_score = 0

if bias == 'bullish':
    long_score += 20
if bias == 'bearish':
    short_score += 20

long_score += score_long_zone_context(price, support_context, resistance_context)
short_score += score_short_zone_context(price, support_context, resistance_context)

long_score += score_long_trigger(trigger)
short_score += score_short_trigger(trigger)

long_candidate = long_score >= threshold
short_candidate = short_score >= threshold

if long_candidate:
    zone = selected_support_zone
    stop = zone.low - stop_buffer
    tp1, tp2 = map_long_targets(price, zones)
    if room_to_target_ok(price, stop, tp1):
        plan_entry_1_and_optional_entry_2()
        submit_or_emit_trade_idea()

if short_candidate:
    zone = selected_resistance_zone
    stop = zone.high + stop_buffer
    tp1, tp2 = map_short_targets(price, zones)
    if room_to_target_ok(price, stop, tp1):
        plan_entry_1_and_optional_entry_2()
        submit_or_emit_trade_idea()
```

---

## 23. Instrument-Specific Notes

### 23.1 Gold
Characteristics:
- can wick deeply around macro events
- often responds sharply to USD / rates / risk sentiment shifts
- London and US overlap often matter most

Production notes:
- use slightly wider zone widths
- avoid aggressive tiny stops
- treat macro windows with high caution

### 23.2 US100
Characteristics:
- highly session-driven
- sensitive to rates, mega-cap momentum, and market sentiment
- can whipsaw around cash open

Production notes:
- prioritize session-aware logic
- test open behavior separately
- allow slightly lower risk per idea than Gold

---

## 24. Backtesting Protocol

### 24.1 Minimum test segmentation
For 2 years of data:
- train / tune: first 12 to 15 months
- validation: next 4 to 6 months
- untouched out-of-sample: final 3 to 6 months

### 24.2 No random split
Use:
- walk-forward
- anchored expanding window
- rolling out-of-sample testing

### 24.3 Required backtest assumptions
Backtests must include:
- spread
- slippage
- realistic stop execution assumptions
- session / news exclusions
- broker lot sizing constraints

### 24.4 Required metrics
At minimum:
- total return
- max drawdown
- profit factor
- win rate
- average win / average loss
- expectancy per trade
- longest losing streak
- trade count
- monthly returns
- performance by weekday
- performance by session
- performance by volatility regime
- MAE / MFE

### 24.5 Robustness tests
The strategy must be tested under:
- higher spread
- slippage shock
- slightly wider stop
- slightly narrower stop
- no entry 2
- with entry 2
- stricter news block
- stricter trade score threshold
- session-only subsets

If performance collapses under small changes, the strategy is fragile.

---

## 25. Live Execution Requirements

### 25.1 Broker adapter responsibilities
The broker adapter must provide:
- historical candles by timeframe
- current bid/ask / spread
- instrument metadata
- account equity
- open positions
- order placement
- stop / TP placement
- order status updates

### 25.2 Order handling rules
- reject duplicate ideas for same symbol/direction if configured
- log intended risk before order submission
- confirm order fill or fail cleanly
- never assume stop or TP exists until broker confirms

### 25.3 Fail-safe behavior
If the adapter cannot confirm:
- market data freshness
- spread
- order status
- position state

then the bot must enter safe mode and stop opening new trades.

### 25.4 Live safety controls
- kill switch
- daily hard stop
- maximum simultaneous open ideas
- maximum correlated exposure
- stale-data timeout
- broker API error threshold shutdown

---

## 26. Logging and Observability

### 26.1 Required logs
For every evaluated bar:
- timestamp
- symbol
- bias
- nearest zones
- zone scores
- trigger state
- spread
- session state
- news state
- long score
- short score
- decision

For every trade:
- planned entry 1 / entry 2
- SL / TP
- cash risk
- position size
- fill details
- exit reason
- PnL
- MAE / MFE

### 26.2 Exit reason taxonomy
- stop_loss
- take_profit_1
- take_profit_2
- manual_flatten
- daily_limit_shutdown
- news_exit
- stale_data_exit
- catastrophic_stop

### 26.3 Monitoring dashboards
Recommended live dashboards:
- current open risk
- PnL by symbol
- win/loss streak
- API health
- spread health
- skipped trades by reason

---

## 27. Example Trade Scenarios

### 27.1 Good Gold long
- H4/H1 bullish
- price pulls into H1 + M15 support cluster
- M5 sweeps below and reclaims
- next resistance offers 2.0R+
- spread normal
- no high-impact news

Action:
- long Entry 1
- optional Entry 2 only at preplanned deeper support
- stop below cluster + ATR buffer
- TP1 at next M15 resistance
- TP2 at next H1 resistance

### 27.2 Bad Gold short
- bearish M5 trigger appears
- price is falling directly into strong H4/H1 support
- next support is too close for acceptable RR

Action:
- skip

### 27.3 Valid US100 short after breakdown
- H1 bearish
- strong support breaks on M15
- retest from below fails
- M5 rejects downward
- price accepts below zone

Action:
- short allowed despite being near former support because support has failed and flipped

---

## 28. Non-Negotiable Rules

1. Never use M5 alone as the market map.  
2. Never place SL inside the active zone.  
3. Never add after invalidation.  
4. Never exceed hard risk per idea.  
5. Never exceed daily hard loss limit.  
6. Never trade with stale or uncertain data.  
7. Never ignore spread expansion.  
8. Never remove the room-to-target filter.  
9. Never force trades in blocked news windows.  
10. Never let live behavior differ from backtest assumptions without documenting it.

---

## 29. Implementation Roadmap

### Phase 1: Core strategy engine
- zone construction
- zone scoring
- bias model
- trigger model
- trade scoring
- SL/TP calculation
- risk engine

### Phase 2: External data feeds integration
- Capital.com adapter (WebSocket + REST)
- Trading Economics calendar fetcher
- FRED macro series fetcher
- NewsAPI headline monitor
- feed health monitoring
- fallback logic
- staleness detection

### Phase 3: Backtest harness
- walk-forward engine
- spread/slippage model
- trade analytics
- MAE/MFE analytics
- robustness suite
- external data replay capability
- event-blocking validation

### Phase 4: Live adapter
- broker data adapter
- execution adapter
- kill switches
- structured logging
- monitoring
- feed status dashboard

### Phase 5: Production hardening
- config versioning
- dry-run mode
- replay mode
- alerting
- deployment checklist
- external feed failure drills

---

## 30. Final Production Definition

This strategy is considered **production-ready** only when all of the following are true:

- rules are documented and versioned
- backtests include realistic costs
- walk-forward results are acceptable
- live adapter handles failures safely
- risk limits are enforced at code level
- decision logs are complete
- no hidden discretionary overrides exist

Until then, it is a promising strategy implementation, not a production system.

---

## 31. Recommended Next Deliverables

To move from specification to deployment, the next files should be built:

### Core strategy files
1. `config.yaml` - comprehensive configuration including external feeds
2. `zone_engine.py` - zone construction and scoring
3. `risk_engine.py` - position sizing and risk management
4. `bias_engine.py` - directional bias detection
5. `trigger_engine.py` - M5 trigger detection
6. `trade_scorer.py` - setup scoring and filtering
7. `execution_adapter.py` - broker-agnostic execution interface

### External data feed adapters
8. `feeds/capital_com_adapter.py` - price feed + execution
9. `feeds/trading_economics_adapter.py` - economic calendar
10. `feeds/fred_adapter.py` - macro series
11. `feeds/newsapi_adapter.py` - headline monitor
12. `feeds/feed_health_monitor.py` - staleness and availability tracking
13. `feeds/feed_manager.py` - orchestration and fallback logic

### Backtesting infrastructure
14. `backtest/data_replay_engine.py` - time-aligned multi-feed replay
15. `backtest/backtest_runner.py` - single-run backtester
16. `backtest/walkforward_runner.py` - walk-forward optimization
17. `backtest/analytics_engine.py` - metrics, MAE/MFE, drawdown analysis

### Live trading infrastructure
18. `live/live_bot.py` - main live trading loop
19. `live/session_manager.py` - session detection and quality scoring
20. `live/event_blocker.py` - news/event-based trade blocking
21. `live/regime_detector.py` - macro regime state machine

### Monitoring and operations
22. `monitoring/feed_dashboard.py` - real-time feed health UI
23. `monitoring/trade_logger.py` - structured decision logging
24. `monitoring/alerting.py` - Slack/email/webhook alerts
25. `metrics_report.md` - template for backtest reports
26. `runbook.md` - operational procedures for failures and shutdowns

### Testing and validation
27. `tests/test_capital_com_adapter.py`
28. `tests/test_trading_economics_adapter.py`
29. `tests/test_fred_adapter.py`
30. `tests/test_newsapi_adapter.py`
31. `tests/test_feed_fallback_logic.py`
32. `tests/test_event_blocking.py`
33. `tests/test_regime_detection.py`
34. `tests/integration/test_full_backtest_with_feeds.py`

---

## 32. Development Priority Order

### Sprint 1: Core strategy + price feed
- Capital.com adapter (price only, no execution)
- zone engine
- bias engine
- trigger engine
- trade scorer
- basic backtest runner with price data only

### Sprint 2: Calendar and event blocking
- Trading Economics adapter
- event blocker module
- integrate event blocking into trade scorer
- backtest validation: no trades during blocked windows

### Sprint 3: Macro regime
- FRED adapter
- regime detector
- integrate regime adjustments into trade scorer
- backtest comparison: with vs without regime adjustments

### Sprint 4: Headline filter
- NewsAPI adapter
- headline blocker module
- integrate into live decision flow
- dry-run testing

### Sprint 5: Feed orchestration
- feed health monitor
- feed manager with fallback logic
- staleness detection
- degraded mode handling

### Sprint 6: Execution and live trading
- Capital.com execution adapter
- live bot loop
- risk engine with live position tracking
- kill switches and safety controls

### Sprint 7: Production hardening
- alerting
- monitoring dashboard
- feed failure drills
- deployment automation
- runbook finalization

