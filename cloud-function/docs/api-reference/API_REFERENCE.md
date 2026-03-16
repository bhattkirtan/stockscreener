# API Reference

Complete API documentation for the Capital.com Trading Service.

## Table of Contents
- [Authentication](#authentication)
- [Position Management](#position-management)
- [Market Data](#market-data)
- [TradingView Integration](#tradingview-integration)
- [Examples](#examples)

## Authentication

All API endpoints require authentication via an API key passed in the request body:

```json
{
  "key": "your-api-key-here",
  ...
}
```

## Position Management

### Get Open Positions

```bash
curl https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/get_positions
```

**Response:**
```json
{
  "positions": [
    {
      "market": {
        "epic": "SILVER",
        "bid": 85.913,
        "offer": 85.993,
        ...
      },
      "position": {
        "dealId": "006011e7-0055-311e-0000-0000812f6c4e",
        "direction": "BUY",
        "size": 1.0,
        "stopLevel": 85.5,
        "profitLevel": 87.0,
        "upl": 0.03
      }
    }
  ]
}
```

### Create Position

```bash
curl -X POST https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/create_position \
  -H "Content-Type: application/json" \
  -d '{
    "key": "IuMfu0djI6ocgxgcbbQEdg",
    "action": "entry",
    "epic": "SILVER",
    "direction": "BUY",
    "stopLevel": 85.5,
    "fibLevel1": 87.0,
    "fibLevel2": 88.0,
    "fibLevel3": 89.0,
    "size1": 100,
    "size2": 60,
    "size3": 40,
    "inTradeTime": true
  }'
```

### Update Stop Loss

```bash
curl -X POST https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/create_position \
  -H "Content-Type: application/json" \
  -d '{
    "key": "IuMfu0djI6ocgxgcbbQEdg",
    "action": "update-sl",
    "epic": "SILVER",
    "stopLevel": 86.0,
    "inTradeTime": true
  }'
```

### Close Position

```bash
curl -X POST https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/create_position \
  -H "Content-Type: application/json" \
  -d '{
    "key": "IuMfu0djI6ocgxgcbbQEdg",
    "action": "exit",
    "epic": "SILVER",
    "inTradeTime": true
  }'
```

Or close by deal ID:

```bash
curl -X DELETE https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/close_position/006011e7-0055-311e-0000-0000812f6c4e
```

## Market Data

### Get Current Price

Get real-time market data for a specific instrument:

```bash
curl https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/market/SILVER
```

**Response:**
```json
{
  "epic": "SILVER",
  "instrumentName": "Silver",
  "instrumentType": "COMMODITIES",
  "bid": 85.913,
  "offer": 85.993,
  "high": 86.784,
  "low": 80.913,
  "netChange": -2.706,
  "percentageChange": 4.75,
  "marketStatus": "TRADEABLE",
  "updateTime": "2026-03-04T13:19:31.354"
}
```

**Available Epics:**
- Forex: `EURUSD`, `GBPUSD`, `USDJPY`, `AUDUSD`
- Commodities: `GOLD`, `SILVER`, `OIL_CRUDE`
- Indices: `US100`, `US500`, `GERMANY30`, `UK100`
- Crypto: `BITCOIN`, `ETHEREUM`

### Get Historical Prices

Get OHLC candlestick data for charting:

```bash
curl "https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/prices/GOLD?resolution=HOUR&max=100"
```

**Query Parameters:**
- `resolution`: `MINUTE`, `MINUTE_5`, `MINUTE_15`, `MINUTE_30`, `HOUR`, `HOUR_4`, `DAY`, `WEEK`
- `max`: Number of candles (1-1000, default: 50)
- `from`: ISO 8601 start date (optional)
- `to`: ISO 8601 end date (optional)

**Response:**
```json
{
  "prices": [
    {
      "snapshotTime": "2026-03-04T12:00:00",
      "openPrice": { "bid": 2680.5, "ask": 2681.0 },
      "closePrice": { "bid": 2682.0, "ask": 2682.5 },
      "highPrice": { "bid": 2683.5, "ask": 2684.0 },
      "lowPrice": { "bid": 2679.0, "ask": 2679.5 },
      "lastTradedVolume": 1500
    }
  ]
}
```

### Get Top Market Movers

Get the top 10 risers and fallers:

```bash
curl https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/markets
```

**Response:**
```json
{
  "topRisers": [
    {
      "epic": "BITCOIN",
      "instrumentName": "Bitcoin",
      "percentageChange": 5.2,
      "bid": 65000,
      "offer": 65100
    }
  ],
  "topFallers": [
    {
      "epic": "ETHEREUM",
      "instrumentName": "Ethereum",
      "percentageChange": -3.4,
      "bid": 3200,
      "offer": 3210
    }
  ],
  "totalMarkets": 150
}
```

**Search Markets:**
```bash
curl "https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/markets?searchTerm=EUR"
```

## TradingView Integration

### Setup Pine Script Alert

1. **Add the indicator** to your TradingView chart (use `strategy-with-webhooks.pine`)
2. **Create an alert**:
   - Condition: Choose your indicator
   - Alert name: "Trading Signal"
   - **Webhook URL**: `https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/create_position`
   - **Message**: The script automatically sends the JSON payload

### TradingView Webhook Payload

The Pine Script sends this JSON format:

```json
{
  "key": "IuMfu0djI6ocgxgcbbQEdg",
  "action": "entry",
  "epic": "SILVER",
  "direction": "BUY",
  "stopLevel": 85.5,
  "fibLevel1": 87.0,
  "fibLevel2": 88.0,
  "fibLevel3": 89.0,
  "size1": 100,
  "size2": 60,
  "size3": 40,
  "inTradeTime": true
}
```

### Signal Types

**Entry Signal:**
- `action: "entry"` - Opens new position (closes opposite direction first)

**Update Signal:**
- `action: "update-sl"` - Moves stop loss to entry after TP1 hit

**Exit Signal:**
- `action: "exit"` - Closes the position

## Examples

### Complete Trading Workflow

1. **TradingView sends BUY signal** → Backend creates position
2. **Price hits TP1 (50%)** → TradingView sends `update-sl` → Backend moves SL to entry
3. **Price hits TP2 (30%)** → TradingView sends `update-sl` → Backend moves SL to TP1
4. **Price hits TP3 (20%)** → TradingView sends `exit` → Backend closes remaining position

### Frontend Integration Example

**React Component:**
```javascript
// Fetch open positions
const fetchPositions = async () => {
  const response = await fetch('https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/get_positions');
  const data = await response.json();
  return data.positions;
};

// Get current price
const getCurrentPrice = async (epic) => {
  const response = await fetch(`https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/market/${epic}`);
  return response.json();
};

// Get historical data for chart
const getChartData = async (epic, resolution = 'HOUR', max = 100) => {
  const response = await fetch(
    `https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/prices/${epic}?resolution=${resolution}&max=${max}`
  );
  return response.json();
};

// Get top movers
const getTopMovers = async () => {
  const response = await fetch('https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/markets');
  return response.json();
};
```

### Manual Trading Example

```bash
# 1. Check top movers
curl https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/markets

# 2. Get current price
curl https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/market/SILVER

# 3. Create position
curl -X POST https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/create_position \
  -H "Content-Type: application/json" \
  -d '{
    "key": "IuMfu0djI6ocgxgcbbQEdg",
    "action": "entry",
    "epic": "SILVER",
    "direction": "BUY",
    "stopLevel": 85.5,
    "fibLevel1": 87.0,
    "size1": 1,
    "inTradeTime": true
  }'

# 4. Check positions
curl https://capital comservice-6ovej2yaoa-uc.a.run.app/get_positions

# 5. Close position
curl -X POST https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/create_position \
  -H "Content-Type: application/json" \
  -d '{
    "key": "IuMfu0djI6ocgxgcbbQEdg",
    "action": "exit",
    "epic": "SILVER",
    "inTradeTime": true
  }'
```

## Error Handling

### HTTP Status Codes

- `200` - Success
- `400` - Bad Request (missing fields, invalid action)
- `401` - Unauthorized (invalid API key)
- `404` - Not Found (invalid endpoint or epic)
- `429` - Rate Limited (too many requests)
- `500` - Internal Server Error

###Error Response Format

```json
{
  "error": "error.invalid.api.key",
  "description": "Unauthorized"
}
```

## Rate Limits

Capital.com API rate limits:
- **General**: 60 requests per minute
- **Price data**: 120 requests per minute
- **Positions**: 30 requests per minute

The backend automatically retries with exponential backoff on 429 errors.

## OpenAPI Specification

Full OpenAPI 3.0 specification available at:
`docs/openapi.yaml`

Import into Postman, Swagger UI, or any OpenAPI-compatible tool.
