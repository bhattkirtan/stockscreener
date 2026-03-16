# Trading Platform - Frontend Integration Guide

> **📅 Last Updated:** March 4, 2026

## 🌍 Available Environments

### Demo Environment (Virtual Money)
- **URL:** `https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService`
- **Purpose:** Testing, development, paper trading
- **Risk:** ✅ No real money at risk
- **Use for:** Development, feature testing, webhook testing

### Production Environment (Real Money) ⚠️
- **URL:** `https://marketservicelive-6ovej2yaoa-uc.a.run.app`
- **Purpose:** Live trading with real funds
- **Risk:** 🔴 Real money at risk
- **Use for:** Production trading only

**💡 Recommendation:** Always develop and test on demo first, then switch to production.

---

## ⚡ Quick Start for Lovable

Copy this into your Lovable project:

```typescript
// 1. Create .env file in Lovable
REACT_APP_TRADING_ENV=demo  // Use 'demo' for testing, 'production' for live

// 2. Create config/trading.config.ts
export const TRADING_ENV = {
  DEMO: 'https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService',
  PRODUCTION: 'https://marketservicelive-6ovej2yaoa-uc.a.run.app'
} as const;

export const API_BASE_URL = process.env.REACT_APP_TRADING_ENV === 'production' 
  ? TRADING_ENV.PRODUCTION 
  : TRADING_ENV.DEMO;

// 3. Test the connection
fetch(`${API_BASE_URL}/get_positions`)
  .then(r => r.json())
  .then(console.log);
```

**📦 Required Dependencies:**
```bash
npm install @tanstack/react-query axios
```

---

## 🏗️ Architecture Decision: Backend Proxy Pattern

### ✅ USE THIS APPROACH: Frontend → Backend → Capital.com

```
┌─────────────┐         ┌─────────────┐         ┌──────────────┐
│             │  HTTPS  │             │  HTTPS  │              │
│   Lovable   │────────►│   Backend   │────────►│ Capital.com  │
│  Frontend   │         │  (Proxy)    │         │     API      │
│             │◄────────│             │◄────────│              │
└─────────────┘         └─────────────┘         └──────────────┘
     React                Google Cloud            Trading API
                          Functions
```

### 🔒 Why Backend Proxy is MANDATORY

| Concern | Direct Frontend Calls | Backend Proxy |
|---------|----------------------|---------------|
| **API Credentials** | ❌ Exposed in browser | ✅ Secure in Cloud Secrets |
| **Trading Keys** | ❌ Visible in DevTools | ✅ Hidden in backend |
| **Rate Limiting** | ❌ Hard to control | ✅ Backend enforces limits |
| **Audit Trail** | ❌ No logging | ✅ Full activity logs |
| **Business Logic** | ❌ Client-side only | ✅ Server validation |
| **CORS Issues** | ❌ Potential problems | ✅ No CORS restrictions |
| **Error Handling** | ❌ Complex retry logic | ✅ Built-in retries |

**⚠️ CRITICAL:** Never expose Capital.com API keys in frontend code. This would allow anyone to:
- Steal your trading credentials
- Place unauthorized trades
- Close your positions
- Access your account balance

---

## 📡 API Endpoints Overview

### Trading Operations
| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/get_positions` | Fetch all open positions |
| POST | `/create_position` | Open new position or handle TradingView webhooks |
| POST | `/updte_position` | Update stop loss or take profit |
| DELETE | `/close_position/{dealId}` | Close a specific position |

### Market Data
| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/market/{epic}` | Get current price and trading rules |
| GET | `/prices/{epic}` | Get historical OHLC candlestick data |
| GET | `/markets` | Get top movers and search markets |

---

## 🔐 Authentication

### Backend Authentication
The backend uses **Secret Manager** to securely store Capital.com credentials. No authentication is required from the frontend for basic operations.

### Recommended Frontend Authentication
For production, implement authentication in your frontend:

1. **Add API Key validation** to backend
2. **Use Firebase Auth** or similar
3. **Pass token in headers:**

```typescript
const headers = {
  'Content-Type': 'application/json',
  'Authorization': `Bearer ${userToken}` // Add in future
};
```

---

## 🚀 Quick Start - React/TypeScript Integration

### 1. Environment Configuration

```typescript
// src/config/trading.config.ts

export const TRADING_ENV = {
  DEMO: 'https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService',
  PRODUCTION: 'https://marketservicelive-6ovej2yaoa-uc.a.run.app'
} as const;

// Set your environment (use environment variable in production)
export const API_BASE_URL = process.env.REACT_APP_TRADING_ENV === 'production' 
  ? TRADING_ENV.PRODUCTION 
  : TRADING_ENV.DEMO;

// Or use a config flag
export const IS_PRODUCTION = process.env.REACT_APP_TRADING_ENV === 'production';
```

### 2. Create API Client

```typescript
// src/lib/api/capitalComClient.ts

import { API_BASE_URL } from '@/config/trading.config';

export interface Position {
  market: {
    epic: string;
    instrumentName: string;
    instrumentType: string;
    bid: number;
    offer: number;
    high: number;
    low: number;
    netChange: number;
    percentageChange: number;
    marketStatus: string;
  };
  position: {
    dealId: string;
    direction: 'BUY' | 'SELL';
    size: number;
    level: number;
    currency: string;
    guaranteedStop: boolean;
    stopLevel?: number;
    profitLevel?: number;
    upl: number;
    createdDate: string;
  };
}

export interface CreatePositionRequest {
  epic: string;
  direction: 'BUY' | 'SELL';
  size: number;
  guaranteedStop: boolean;
  stopLevel?: number;
  profitLevel?: number;
}

export interface MarketInfo {
  instrument: {
    epic: string;
    name: string;
    type: string;
    currency: string;
    lotSize: number;
    streamingPricesAvailable: boolean;
  };
  snapshot: {
    bid: number;
    offer: number;
    high: number;
    low: number;
    netChange: number;
    percentageChange: number;
    marketStatus: string;
    updateTime: string;
  };
  dealingRules: {
    minDealSize: { value: number; unit: string };
    maxDealSize: { value: number; unit: string };
    minStopOrProfitDistance: { value: number; unit: string };
  };
}

export interface HistoricalPrice {
  snapshotTime: string;
  openPrice: { bid: number; ask: number };
  closePrice: { bid: number; ask: number };
  highPrice: { bid: number; ask: number };
  lowPrice: { bid: number; ask: number };
  lastTradedVolume: number;
}

export class CapitalComAPI {
  private baseURL: string;

  constructor(baseURL: string = API_BASE_URL) {
    this.baseURL = baseURL;
  }

  private async request<T>(
    endpoint: string,
    options?: RequestInit
  ): Promise<T> {
    const response = await fetch(`${this.baseURL}${endpoint}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || `HTTP ${response.status}: ${response.statusText}`);
    }

    return response.json();
  }

  // Trading Operations
  async getPositions(): Promise<{ positions: Position[] }> {
    return this.request('/get_positions');
  }

  async createPosition(data: CreatePositionRequest): Promise<any> {
    return this.request('/create_position', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async updatePosition(data: {
    dealId: string;
    stopLevel?: number;
    profitLevel?: number;
  }): Promise<any> {
    return this.request('/updte_position', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async closePosition(dealId: string): Promise<any> {
    return this.request(`/close_position/${dealId}`, {
      method: 'DELETE',
    });
  }

  // Market Data Operations
  async getMarketInfo(epic: string): Promise<MarketInfo> {
    return this.request(`/market/${epic}`);
  }

  async getHistoricalPrices(
    epic: string,
    resolution: 'MINUTE' | 'MINUTE_5' | 'MINUTE_15' | 'HOUR' | 'HOUR_4' | 'DAY' | 'WEEK' = 'HOUR',
    max: number = 50,
    from?: string,
    to?: string
  ): Promise<{ prices: HistoricalPrice[] }> {
    const params = new URLSearchParams({
      resolution,
      max: max.toString(),
      ...(from && { from }),
      ...(to && { to }),
    });
    return this.request(`/prices/${epic}?${params}`);
  }

  async getMarkets(searchTerm?: string): Promise<{
    markets: any[];
    topRisers: any[];
    topFallers: any[];
  }> {
    const params = searchTerm ? `?searchTerm=${encodeURIComponent(searchTerm)}` : '';
    return this.request(`/markets${params}`);
  }
}

// Export singleton instance
export const capitalComAPI = new CapitalComAPI();
```

### 2. React Hooks for Trading

```typescript
// src/hooks/usePositions.ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { capitalComAPI } from '@/lib/api/capitalComClient';

export function usePositions() {
  return useQuery({
    queryKey: ['positions'],
    queryFn: () => capitalComAPI.getPositions(),
    refetchInterval: 5000, // Refresh every 5 seconds
  });
}

export function useCreatePosition() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: capitalComAPI.createPosition.bind(capitalComAPI),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['positions'] });
    },
  });
}

export function useUpdatePosition() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: capitalComAPI.updatePosition.bind(capitalComAPI),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['positions'] });
    },
  });
}

export function useClosePosition() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: (dealId: string) => capitalComAPI.closePosition(dealId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['positions'] });
    },
  });
}
```

```typescript
// src/hooks/useMarketData.ts
import { useQuery } from '@tanstack/react-query';
import { capitalComAPI } from '@/lib/api/capitalComClient';

export function useMarketInfo(epic: string) {
  return useQuery({
    queryKey: ['market', epic],
    queryFn: () => capitalComAPI.getMarketInfo(epic),
    enabled: !!epic,
    refetchInterval: 1000, // Real-time updates every 1 second
  });
}

export function useHistoricalPrices(
  epic: string,
  resolution: Parameters<typeof capitalComAPI.getHistoricalPrices>[1] = 'HOUR',
  max: number = 50
) {
  return useQuery({
    queryKey: ['prices', epic, resolution, max],
    queryFn: () => capitalComAPI.getHistoricalPrices(epic, resolution, max),
    enabled: !!epic,
  });
}

export function useTopMovers() {
  return useQuery({
    queryKey: ['markets', 'top-movers'],
    queryFn: () => capitalComAPI.getMarkets(),
    refetchInterval: 30000, // Refresh every 30 seconds
  });
}

export function useMarketSearch(searchTerm: string) {
  return useQuery({
    queryKey: ['markets', 'search', searchTerm],
    queryFn: () => capitalComAPI.getMarkets(searchTerm),
    enabled: searchTerm.length > 0,
  });
}
```

### 3. Example Component - Positions List

```typescript
// src/components/PositionsList.tsx
import { usePositions, useClosePosition } from '@/hooks/usePositions';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';

export function PositionsList() {
  const { data, isLoading, error } = usePositions();
  const closePosition = useClosePosition();

  if (isLoading) return <div>Loading positions...</div>;
  if (error) return <div>Error: {error.message}</div>;

  return (
    <div className="space-y-4">
      {data?.positions.map((pos) => (
        <Card key={pos.position.dealId} className="p-4">
          <div className="flex justify-between items-start">
            <div>
              <h3 className="font-bold text-lg">
                {pos.market.instrumentName} ({pos.market.epic})
              </h3>
              <div className="text-sm text-gray-600">
                {pos.position.direction} {pos.position.size} @ {pos.position.level}
              </div>
            </div>
            <div className="text-right">
              <div className={pos.position.upl >= 0 ? 'text-green-600' : 'text-red-600'}>
                {pos.position.upl >= 0 ? '+' : ''}{pos.position.upl.toFixed(2)} {pos.position.currency}
              </div>
              <div className="text-sm text-gray-600">
                Current: {pos.market.bid} / {pos.market.offer}
              </div>
            </div>
          </div>
          <div className="mt-4 flex gap-2">
            <Button
              variant="destructive"
              onClick={() => closePosition.mutate(pos.position.dealId)}
              disabled={closePosition.isPending}
            >
              Close Position
            </Button>
          </div>
        </Card>
      ))}
      {data?.positions.length === 0 && (
        <p className="text-center text-gray-500">No open positions</p>
      )}
    </div>
  );
}
```

### 4. Example Component - Price Chart

```typescript
// src/components/PriceChart.tsx
import { useHistoricalPrices } from '@/hooks/useMarketData';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';

interface PriceChartProps {
  epic: string;
  resolution?: 'MINUTE' | 'MINUTE_5' | 'MINUTE_15' | 'HOUR' | 'HOUR_4' | 'DAY' | 'WEEK';
}

export function PriceChart({ epic, resolution = 'HOUR' }: PriceChartProps) {
  const { data, isLoading } = useHistoricalPrices(epic, resolution, 100);

  if (isLoading) return <div>Loading chart...</div>;

  const chartData = data?.prices.map(price => ({
    time: new Date(price.snapshotTime).toLocaleString(),
    price: price.closePrice.bid,
  })) || [];

  return (
    <ResponsiveContainer width="100%" height={400}>
      <LineChart data={chartData}>
        <XAxis dataKey="time" />
        <YAxis domain={['auto', 'auto']} />
        <Tooltip />
        <Line type="monotone" dataKey="price" stroke="#8884d8" dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}
```

### 5. Example Component - Top Movers

```typescript
// src/components/TopMovers.tsx
import { useTopMovers } from '@/hooks/useMarketData';
import { Card } from '@/components/ui/card';

export function TopMovers() {
  const { data, isLoading } = useTopMovers();

  if (isLoading) return <div>Loading...</div>;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
      <Card className="p-4">
        <h3 className="font-bold text-lg mb-4 text-green-600">Top Risers 📈</h3>
        <div className="space-y-2">
          {data?.topRisers.slice(0, 5).map((market) => (
            <div key={market.epic} className="flex justify-between">
              <span className="font-medium">{market.instrumentName}</span>
              <span className="text-green-600">+{market.percentageChange.toFixed(2)}%</span>
            </div>
          ))}
        </div>
      </Card>

      <Card className="p-4">
        <h3 className="font-bold text-lg mb-4 text-red-600">Top Fallers 📉</h3>
        <div className="space-y-2">
          {data?.topFallers.slice(0, 5).map((market) => (
            <div key={market.epic} className="flex justify-between">
              <span className="font-medium">{market.instrumentName}</span>
              <span className="text-red-600">{market.percentageChange.toFixed(2)}%</span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
```

---

## 📦 Required Dependencies

```bash
npm install @tanstack/react-query
# For charts (optional)
npm install recharts
# Or for TradingView charts
npm install react-tradingview-widget
```

---

## 🔗 OpenAPI Specification

**Full OpenAPI documentation available at:** [`docs/openapi.yaml`](./openapi.yaml)

### Import into Swagger/Postman
```bash
# View in Swagger Editor
https://editor.swagger.io/

# Import the openapi.yaml file
```

### Quick Reference

<details>
<summary><strong>GET /get_positions</strong></summary>

**Response:**
```json
{
  "positions": [
    {
      "market": {
        "epic": "GOLD",
        "instrumentName": "Gold",
        "bid": 5166.39,
        "offer": 5166.89,
        "percentageChange": 1.53
      },
      "position": {
        "dealId": "00601567-0055-311e-0000-0000843b29a1",
        "direction": "BUY",
        "size": 1.0,
        "level": 5190.76,
        "upl": -20.96
      }
    }
  ]
}
```
</details>

<details>
<summary><strong>POST /create_position</strong></summary>

**Request:**
```json
{
  "epic": "GOLD",
  "direction": "BUY",
  "size": 1,
  "guaranteedStop": false,
  "stopLevel": 5100,
  "profitLevel": 5300
}
```

**Response:**
```json
{
  "dealId": "00601567-0055-311e-0000-0000843b29a1",
  "dealReference": "p_00601567-0055-311e-0000-0000843b29a1",
  "affectedDeals": [...]
}
```
</details>

<details>
<summary><strong>GET /market/{epic}</strong></summary>

**Example:** `/market/SILVER`

**Response:**
```json
{
  "instrument": {
    "epic": "SILVER",
    "name": "Silver",
    "type": "COMMODITIES",
    "currency": "USD"
  },
  "snapshot": {
    "bid": 85.268,
    "offer": 85.348,
    "high": 86.784,
    "low": 80.913,
    "percentageChange": 3.97,
    "marketStatus": "TRADEABLE"
  },
  "dealingRules": {
    "minDealSize": { "value": 1, "unit": "POINTS" },
    "maxDealSize": { "value": 100000, "unit": "POINTS" }
  }
}
```
</details>

<details>
<summary><strong>GET /prices/{epic}</strong></summary>

**Example:** `/prices/GOLD?resolution=HOUR&max=50`

**Response:**
```json
{
  "prices": [
    {
      "snapshotTime": "2026-03-04T13:00:00",
      "openPrice": { "bid": 5192.44, "ask": 5191.94 },
      "closePrice": { "bid": 5164.93, "ask": 5164.43 },
      "highPrice": { "bid": 5206.5, "ask": 5205.86 },
      "lowPrice": { "bid": 5156.64, "ask": 5156.11 },
      "lastTradedVolume": 21805
    }
  ]
}
```
</details>

<details>
<summary><strong>GET /markets</strong></summary>

**Optional parameter:** `?searchTerm=EUR`

**Response:**
```json
{
  "topRisers": [
    {
      "epic": "CFGUSD",
      "instrumentName": "CFG/USD",
      "percentageChange": 15.23,
      "bid": 0.245,
      "offer": 0.247
    }
  ],
  "topFallers": [
    {
      "epic": "PERPUSD",
      "instrumentName": "PERP/USD",
      "percentageChange": -11.19,
      "bid": 0.0254,
      "offer": 0.0257
    }
  ],
  "markets": [...]
}
```
</details>

---

## 🎨 Design System Integration

### Lovable Component Patterns

Use these shadcn/ui components in your Lovable project:

```typescript
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
```

### Recommended Dashboard Layout

```
┌─────────────────────────────────────────────────┐
│  Header (Logo, User, Balance)                   │
├──────────────┬──────────────────────────────────┤
│              │                                  │
│  Sidebar     │  Main Content Area              │
│  - Dashboard │  ┌─────────────────────────┐    │
│  - Positions │  │  Top Movers             │    │
│  - Markets   │  └─────────────────────────┘    │
│  - Trade     │  ┌─────────────────────────┐    │
│  - History   │  │  Open Positions         │    │
│              │  └─────────────────────────┘    │
│              │  ┌─────────────────────────┐    │
│              │  │  Price Chart            │    │
│              │  └─────────────────────────┘    │
└──────────────┴──────────────────────────────────┘
```

---

## 🔄 TradingView Integration

Your backend already handles TradingView webhook alerts. Configure in TradingView:

1. **Copy Pine Script:** Use `docs/strategy-with-webhooks.pine`
2. **Create Alert:** Set webhook URL to `https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/create_position`
3. **Webhook Payload:**
```json
{
  "action": "entry",
  "epic": "{{ticker}}",
  "direction": "{{strategy.order.action}}",
  "size": 1,
  "price": {{close}},
  "stopLevel": {{plot_0}},
  "guaranteedStop": false
}
```

The backend automatically handles:
- `action: "entry"` → Opens new position
- `action: "update-sl"` → Updates stop loss (trailing)
- `action: "exit"` → Closes position

---

## 🚦 Error Handling

```typescript
try {
  await capitalComAPI.createPosition({
    epic: 'GOLD',
    direction: 'BUY',
    size: 1,
    guaranteedStop: false,
  });
} catch (error) {
  if (error.message.includes('market.closed')) {
    toast.error('Market is closed');
  } else if (error.message.includes('insufficient.funds')) {
    toast.error('Insufficient funds');
  } else {
    toast.error('Failed to create position');
  }
}
```

---

## 📊 Real-time Updates

For live price updates, use polling or WebSockets:

```typescript
// Polling approach (already implemented in hooks)
useQuery({
  queryKey: ['market', epic],
  queryFn: () => capitalComAPI.getMarketInfo(epic),
  refetchInterval: 1000, // 1 second
});

// Future: WebSocket implementation
// Backend could add Socket.IO or native WebSocket support
```

---

## 🧪 Testing

### Environment Variables in Lovable

Set this in your Lovable project settings:

**For Development (Demo):**
```env
REACT_APP_TRADING_ENV=demo
```

**For Production (Live Trading):**
```env
REACT_APP_TRADING_ENV=production
```

### Test with cURL

**Demo Environment:**
```bash
# Get positions
curl https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/get_positions

# Get market info
curl https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/market/GOLD

# Create position (virtual money)
curl -X POST https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/create_position \
  -H "Content-Type: application/json" \
  -d '{
    "epic": "GOLD",
    "direction": "BUY",
    "size": 1,
    "guaranteedStop": false,
    "stopLevel": 5100
  }'
```

**Production Environment:** ⚠️ Real Money!
```bash
# Get positions
curl https://marketservicelive-6ovej2yaoa-uc.a.run.app/get_positions

# Get market info
curl https://marketservicelive-6ovej2yaoa-uc.a.run.app/market/GOLD

# ⚠️ CAUTION: This trades with real money!
curl -X POST https://marketservicelive-6ovej2yaoa-uc.a.run.app/create_position \
  -H "Content-Type: application/json" \
  -d '{
    "epic": "GOLD",
    "direction": "BUY",
    "size": 0.01,
    "guaranteedStop": true,
    "stopLevel": 5100
  }'
```

---

## � Deploying to Production - Safety Checklist

### Before You Switch to Production

- [ ] **Test thoroughly on demo** - All features work correctly
- [ ] **Test TradingView webhooks** - Signals execute as expected
- [ ] **Verify stop losses** - All positions have proper risk management
- [ ] **Set position limits** - Configure max position size
- [ ] **Test error handling** - Frontend handles API errors gracefully
- [ ] **Review trading strategy** - Confident in the logic
- [ ] **Set up monitoring** - Track all trades and errors
- [ ] **Start with small sizes** - Use minimum position sizes initially
- [ ] **Have kill switch ready** - Know how to disable trading quickly

### Switching to Production

1. **Update environment variable in Lovable:**
   ```env
   REACT_APP_TRADING_ENV=production
   ```

2. **Add warning badge in UI:**
   ```typescript
   {API_BASE_URL.includes('marketservicelive') && (
     <div className="bg-red-500 text-white px-4 py-2 rounded">
       🔴 LIVE TRADING - Real Money at Risk
     </div>
   )}
   ```

3. **Deploy and monitor closely**
4. **Test with minimal position first** (0.01 size)
5. **Watch logs for any errors**
6. **Verify positions in trading platform**

### Emergency Procedures

**To disable trading immediately:**

```bash
# Scale function to zero (stop accepting requests)
gcloud functions deploy marketServiceLive \
  --region=us-central1 \
  --max-instances=0 \
  --project=double-venture-442318-k8

# Or delete the function completely
gcloud functions delete marketServiceLive \
  --region=us-central1 \
  --project=double-venture-442318-k8 \
  --quiet
```

**Switch back to demo:**
```env
REACT_APP_TRADING_ENV=demo
```

---

## �📝 Next Steps

1. **Import this guide into Lovable**
2. **Copy the API client code** into your project
3. **Install dependencies** (`@tanstack/react-query`, etc.)
4. **Create your first component** (PositionsList)
5. **Test with live data** using the hooks
6. **Enhance with shadcn/ui** components
7. **Deploy frontend** to Vercel or Netlify

---

## 🆘 Support & Resources

### API Endpoints
- **Demo API (Virtual Money):** https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService
- **Production API (Real Money):** https://marketservicelive-6ovej2yaoa-uc.a.run.app ⚠️

### Documentation
- **OpenAPI Spec:** [`docs/openapi.yaml`](./openapi.yaml)
- **API Reference:** [`docs/API_REFERENCE.md`](./API_REFERENCE.md)
- **Production Setup:** [`docs/PRODUCTION_SETUP.md`](./PRODUCTION_SETUP.md)
- **TradingView Pine Script:** [`docs/strategy-with-webhooks.pine`](./strategy-with-webhooks.pine)

### Quick Links
- **Google Cloud Console:** https://console.cloud.google.com/functions?project=double-venture-442318-k8
- **View Logs:** `gcloud functions logs read marketServiceLive --region=us-central1`

---

## 🔒 Security Checklist

- [ ] Never expose Capital.com credentials in frontend
- [ ] All API calls go through backend proxy
- [ ] Add authentication layer (Firebase Auth, etc.)
- [ ] Implement rate limiting on sensitive endpoints
- [ ] Use HTTPS only (already configured)
- [ ] Add input validation on frontend
- [ ] Log all trading activity
- [ ] Set up monitoring and alerts

---

**✨ You're ready to build your trading dashboard in Lovable!**
