# Capital.com API Limitations & Differences

## 🔍 Why You Can't See API Calls in Capital.com's Network Logs

When you use Capital.com's web platform, you **cannot see HTTP REST API calls** in your browser's Network tab for market data. Here's why:

### Capital.com Uses WebSocket for Real-Time Data

```
Capital.com Web Platform Architecture:

Browser ─────WebSocket─────► Capital.com Servers
   │                              │
   └─ (No HTTP REST for prices) ─┘
                                  │
Our API ─────HTTP REST────────────┘ (Different protocol)
```

**What Capital.com Uses:**
- ✅ **WebSocket (wss://)** - Bidirectional, persistent connection for real-time streaming
- ✅ **Internal APIs** - Proprietary endpoints not documented publicly
- ✅ **GraphQL** - Some platforms use GraphQL instead of REST
- ✅ **Binary Protocols** - Efficient data transfer (not visible as JSON)

**What We Use:**
- ✅ **REST API (https://)** - Request/response pattern from their public API
- ✅ **Documented endpoints** - Only what's available in their API docs
- ✅ **Polling** - We fetch data periodically (not streaming)

---

## 📊 Top Risers/Fallers Discrepancy

### Why Results Are Different

Looking at your screenshot, Capital.com shows:
- **Gemini Space Station, Inc. CFD** +29.77%
- **Babcock & Wilcox** +32.55%
- **Coinbase Global Inc** +15.78%

But our API might show different results because:

### 1. **Different Market Categories**

Capital.com's UI has filters:
```
├── Most traded    (not in public API ❌)
├── Top risers     (we calculate from ALL markets ✅)
├── Top fallers    (we calculate from ALL markets ✅)
└── Most volatile  (not in public API ❌)
```

**Our Implementation:**
```python
# We get ALL markets and sort by percentageChange
markets = get_all_markets()
top_risers = sorted(markets, key=lambda x: x['percentageChange'], reverse=True)[:10]
```

**What Capital.com Does:**
- Pre-filtered by **category** (Stocks, Crypto, Commodities, etc.)
- Pre-filtered by **liquidity/trading volume**
- Pre-calculated on their backend
- May use **internal categorization** we can't access

### 2. **"Most Traded" vs "Top Risers"**

In your screenshot, you selected **"Most traded"**, not "Top risers":

```
Capital.com Sidebar:
├── 📊 Most traded    ← Selected (shows popular instruments by volume)
├── 📈 Top risers     ← Not selected (highest % gains)
├── 📉 Top fallers
└── 🎢 Most volatile
```

**Most Traded** = Sorted by **trading volume**, not price change
**Top Risers** = Sorted by **percentage change**, which we can provide

### 3. **Time Frame Differences**

- **Their UI**: May use 1-minute updates via WebSocket
- **Our API**: Fetches data when requested (snapshot in time)
- **Caching**: They might cache differently

---

## ✅ What We CAN Do

### 1. Top Risers/Fallers (Currently Implemented)

```bash
# Get top risers and fallers
curl https://marketservicelive-6ovej2yaoa-uc.a.run.app/markets
```

**Returns:**
```json
{
  "topRisers": [
    {
      "epic": "CFGUSD",
      "instrumentName": "CFG/USD",
      "percentageChange": 15.23,
      "bid": 0.245
    }
  ],
  "topFallers": [...]
}
```

### 2. Filter by Category

```bash
# Search for specific market types
curl "https://marketservicelive-6ovej2yaoa-uc.a.run.app/markets?searchTerm=CRYPTO"
curl "https://marketservicelive-6ovej2yaoa-uc.a.run.app/markets?searchTerm=EUR"
```

### 3. Real-Time Price Updates

```typescript
// Poll every second for live prices
useQuery({
  queryKey: ['market', 'GOLD'],
  queryFn: () => capitalComAPI.getMarketInfo('GOLD'),
  refetchInterval: 1000, // 1 second updates
});
```

---

## ❌ What We CANNOT Do

### 1. Most Traded (No API Endpoint)

❌ **Trading volume ranking** - Not exposed in public API

**Workaround:**
- Manually maintain a list of popular instruments
- Track our own position volumes in Firestore
- Use a static list of commonly traded epics

### 2. Category-Specific Top Movers

❌ **Filter top risers by category** (Stocks, Crypto, Commodities)

The API doesn't provide category filtering for top movers.

**Workaround:**
```python
# We could implement manual categorization:
CRYPTO_EPICS = ['BTCUSD', 'ETHUSD', 'BNBUSD', ...]
FOREX_EPICS = ['EURUSD', 'GBPUSD', 'USDJPY', ...]

# Then filter top risers by category
crypto_risers = [m for m in top_risers if m['epic'] in CRYPTO_EPICS]
```

### 3. WebSocket Streaming

❌ **Real-time streaming prices** via WebSocket

The public API only provides REST endpoints, not WebSocket.

**Workaround:**
- Aggressive polling (every 1 second)
- Accept slight delays in data
- Use TradingView webhooks for signal-based trading

---

## 🎯 Recommendations

### For Top Movers (Like Capital.com)

**Option 1: Enhanced Filtering**
```python
def get_top_movers_by_category(category='CRYPTO'):
    """Get top risers filtered by category."""
    markets = get_all_markets().json()['markets']
    
    # Define category filters
    categories = {
        'CRYPTO': ['BTCUSD', 'ETHUSD', 'BNBUSD', 'ADAUSD', ...],
        'FOREX': ['EURUSD', 'GBPUSD', 'USDJPY', ...],
        'STOCKS': ['AAPL', 'GOOGL', 'TSLA', ...],
        'COMMODITIES': ['GOLD', 'SILVER', 'OIL_CRUDE', ...],
    }
    
    # Filter by category
    filtered = [m for m in markets if m['epic'] in categories.get(category, [])]
    
    # Sort by percentage change
    risers = sorted(filtered, key=lambda x: x.get('percentageChange', 0), reverse=True)[:10]
    
    return risers
```

**Option 2: Use instrumentType from API**
```python
# Filter by instrumentType field (if available)
def get_top_risers_by_type(instrument_type='CRYPTOCURRENCIES'):
    markets = get_all_markets().json()['markets']
    
    filtered = [m for m in markets if m.get('instrumentType') == instrument_type]
    risers = sorted(filtered, key=lambda x: x.get('percentageChange', 0), reverse=True)[:10]
    
    return risers
```

### For "Most Traded" Simulation

Since we can't get actual trading volume, we can:

**Option 1: Static Popular List**
```python
POPULAR_INSTRUMENTS = [
    'EURUSD', 'GBPUSD', 'USDJPY',  # Forex
    'BTCUSD', 'ETHUSD',             # Crypto
    'GOLD', 'SILVER', 'OIL_CRUDE',  # Commodities
    'US500', 'GERMANY40', 'UK100',  # Indices
    'AAPL', 'GOOGL', 'TSLA',        # Stocks
]

def get_popular_markets():
    """Get current prices for popular instruments."""
    markets = []
    for epic in POPULAR_INSTRUMENTS:
        try:
            market = get_market_info(epic).json()
            markets.append(market)
        except:
            continue
    return markets
```

**Option 2: Track Our Own Metrics**
```python
# Store in Firestore whenever positions are created
def track_instrument_usage(epic):
    """Increment counter for this epic."""
    db.increment_field('instrument_usage', epic, 'count', 1)
    db.set_field('instrument_usage', epic, 'last_used', datetime.now())

def get_most_used_instruments(limit=10):
    """Get instruments sorted by our usage."""
    return db.query('instrument_usage', order_by='count', desc=True, limit=limit)
```

---

## 🔧 Implementation Plan

### Phase 1: Add Category Filtering (2 hours)

1. Create `INSTRUMENT_CATEGORIES` dictionary
2. Add `/markets?category=CRYPTO` endpoint
3. Return top risers/fallers per category

### Phase 2: Popular Instruments (1 hour)

1. Define `POPULAR_INSTRUMENTS` list
2. Add `/markets/popular` endpoint
3. Return current prices for popular epics

### Phase 3: Usage Tracking (3 hours)

1. Track position creation by epic
2. Store counters in Firestore
3. Add `/markets/trending` endpoint based on our usage

---

## 📝 Summary

**Why Network Logs Are Different:**
- Capital.com uses **WebSocket** (not visible as HTTP)
- We use **REST API** (visible in network logs)
- Different protocols for different purposes

**Why Top Movers Are Different:**
- They filter by **category** + **volume**
- We sort **all markets** by percentage change
- They have internal APIs we don't have access to

**What You Should Do:**
1. ✅ Use our `/markets` endpoint for top risers/fallers
2. ✅ Accept that "Most Traded" requires manual curation
3. ✅ Implement category filtering if needed (see above)
4. ✅ Use aggressive polling (1s intervals) to simulate real-time

**Trade-offs:**
| Feature | Capital.com UI | Our API |
|---------|---------------|---------|
| Real-time prices | ✅ WebSocket | ⚠️ Polling (1s) |
| Top risers | ✅ Pre-calculated | ✅ On-demand |
| Most traded | ✅ By volume | ❌ Not available |
| Category filter | ✅ Built-in | ⚠️ Manual implementation |

---

**🎯 For your use case:** If you want top risers/fallers that match Capital.com's UI, you'll need to implement category filtering manually. The data is available, but the categorization is on us to build.
