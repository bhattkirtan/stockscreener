# Capital.com Trading API - Quick Reference for Lovable

## ⚡ Quick Start

**Base URL:** `https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService`

**Architecture:** Frontend → Backend Proxy → Capital.com API

**Security:** All Capital.com credentials are secured in backend. Frontend never accesses trading API directly.

---

## 📡 API Endpoints

### Trading
```typescript
// Get all open positions
GET /get_positions

// Create new position
POST /create_position
Body: { epic: "GOLD", direction: "BUY", size: 1, guaranteedStop: false, stopLevel?: number }

// Update stop loss or take profit
POST /updte_position
Body: { dealId: "xxx", stopLevel?: number, profitLevel?: number }

// Close position
DELETE /close_position/{dealId}
```

### Market Data
```typescript
// Get current price and trading rules
GET /market/{epic}
Example: /market/SILVER

// Get historical OHLC candlestick data
GET /prices/{epic}?resolution=HOUR&max=50
Resolutions: MINUTE, MINUTE_5, MINUTE_15, HOUR, HOUR_4, DAY, WEEK

// Get top movers and search markets
GET /markets?searchTerm=EUR
Returns: { topRisers: [...], topFallers: [...], markets: [...] }
```

---

## 🚀 TypeScript Integration

### Installation
```bash
npm install @tanstack/react-query
```

### API Client (Copy this file)
```typescript
// lib/api/capitalCom.ts
const API_URL = 'https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService';

export const api = {
  getPositions: () => 
    fetch(`${API_URL}/get_positions`).then(r => r.json()),
  
  createPosition: (data: any) =>
    fetch(`${API_URL}/create_position`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    }).then(r => r.json()),
  
  getMarket: (epic: string) =>
    fetch(`${API_URL}/market/${epic}`).then(r => r.json()),
  
  getPrices: (epic: string, resolution = 'HOUR', max = 50) =>
    fetch(`${API_URL}/prices/${epic}?resolution=${resolution}&max=${max}`).then(r => r.json()),
  
  getTopMovers: () =>
    fetch(`${API_URL}/markets`).then(r => r.json()),
};
```

### React Hooks
```typescript
// hooks/usePositions.ts
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api/capitalCom';

export const usePositions = () => {
  return useQuery({
    queryKey: ['positions'],
    queryFn: api.getPositions,
    refetchInterval: 5000, // Update every 5 seconds
  });
};

export const useMarket = (epic: string) => {
  return useQuery({
    queryKey: ['market', epic],
    queryFn: () => api.getMarket(epic),
    refetchInterval: 1000, // Real-time updates
  });
};
```

### Example Component
```typescript
import { usePositions } from '@/hooks/usePositions';

export const PositionsList = () => {
  const { data, isLoading } = usePositions();
  
  if (isLoading) return <div>Loading...</div>;
  
  return (
    <div>
      {data?.positions.map(pos => (
        <div key={pos.position.dealId}>
          <h3>{pos.market.instrumentName}</h3>
          <p>{pos.position.direction} {pos.position.size} @ {pos.position.level}</p>
          <p className={pos.position.upl >= 0 ? 'text-green-600' : 'text-red-600'}>
            P/L: {pos.position.upl.toFixed(2)}
          </p>
        </div>
      ))}
    </div>
  );
};
```

---

## 📊 Response Types

```typescript
interface Position {
  market: {
    epic: string;
    instrumentName: string;
    bid: number;
    offer: number;
    percentageChange: number;
  };
  position: {
    dealId: string;
    direction: 'BUY' | 'SELL';
    size: number;
    level: number;
    upl: number; // Unrealized profit/loss
    stopLevel?: number;
    profitLevel?: number;
  };
}

interface MarketInfo {
  instrument: {
    epic: string;
    name: string;
    type: string;
    currency: string;
  };
  snapshot: {
    bid: number;
    offer: number;
    high: number;
    low: number;
    percentageChange: number;
    marketStatus: 'TRADEABLE' | 'CLOSED';
  };
}

interface HistoricalPrice {
  snapshotTime: string;
  openPrice: { bid: number; ask: number };
  closePrice: { bid: number; ask: number };
  highPrice: { bid: number; ask: number };
  lowPrice: { bid: number; ask: number };
  lastTradedVolume: number;
}
```

---

## 🎨 UI Components Example

```typescript
// Top Movers Card
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api/capitalCom';
import { Card } from '@/components/ui/card';

export const TopMovers = () => {
  const { data } = useQuery({
    queryKey: ['top-movers'],
    queryFn: api.getTopMovers,
    refetchInterval: 30000,
  });
  
  return (
    <div className="grid md:grid-cols-2 gap-4">
      <Card className="p-4">
        <h3 className="font-bold text-green-600 mb-3">Top Risers 📈</h3>
        {data?.topRisers.slice(0, 5).map(m => (
          <div key={m.epic} className="flex justify-between py-1">
            <span>{m.instrumentName}</span>
            <span className="text-green-600">+{m.percentageChange.toFixed(2)}%</span>
          </div>
        ))}
      </Card>
      
      <Card className="p-4">
        <h3 className="font-bold text-red-600 mb-3">Top Fallers 📉</h3>
        {data?.topFallers.slice(0, 5).map(m => (
          <div key={m.epic} className="flex justify-between py-1">
            <span>{m.instrumentName}</span>
            <span className="text-red-600">{m.percentageChange.toFixed(2)}%</span>
          </div>
        ))}
      </Card>
    </div>
  );
};
```

---

## 🔄 Trading Flow

### Open Position
```typescript
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api/capitalCom';

const { mutate: createPosition } = useMutation({
  mutationFn: api.createPosition,
  onSuccess: () => {
    queryClient.invalidateQueries(['positions']);
    toast.success('Position opened!');
  },
});

// Usage
createPosition({
  epic: 'GOLD',
  direction: 'BUY',
  size: 1,
  guaranteedStop: false,
  stopLevel: 5100, // Optional stop loss
});
```

### Close Position
```typescript
const closePosition = async (dealId: string) => {
  const response = await fetch(
    `https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/close_position/${dealId}`,
    { method: 'DELETE' }
  );
  return response.json();
};
```

---

## 🔍 Search Markets
```typescript
const SearchMarkets = () => {
  const [search, setSearch] = useState('');
  
  const { data } = useQuery({
    queryKey: ['markets', search],
    queryFn: () => fetch(
      `https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/markets?searchTerm=${search}`
    ).then(r => r.json()),
    enabled: search.length > 0,
  });
  
  return (
    <div>
      <input 
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search markets..."
      />
      {data?.markets.map(m => (
        <div key={m.epic}>{m.instrumentName}</div>
      ))}
    </div>
  );
};
```

---

## 📈 Chart Integration

```typescript
// Using recharts
import { LineChart, Line, XAxis, YAxis } from 'recharts';
import { useQuery } from '@tanstack/react-query';

const PriceChart = ({ epic }: { epic: string }) => {
  const { data } = useQuery({
    queryKey: ['prices', epic],
    queryFn: () => api.getPrices(epic, 'HOUR', 100),
  });
  
  const chartData = data?.prices.map(p => ({
    time: p.snapshotTime,
    price: p.closePrice.bid,
  }));
  
  return (
    <LineChart width={800} height={400} data={chartData}>
      <XAxis dataKey="time" />
      <YAxis />
      <Line type="monotone" dataKey="price" stroke="#8884d8" />
    </LineChart>
  );
};
```

---

## ⚠️ Error Handling

```typescript
try {
  await api.createPosition(data);
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

## 🧪 Test Endpoints

```bash
# Test get positions
curl https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/get_positions

# Test market data
curl https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/market/GOLD

# Test search
curl "https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService/markets?searchTerm=EUR"
```

---

## 📖 Full Documentation

For complete documentation with detailed examples:
- **[LOVABLE_INTEGRATION.md](./LOVABLE_INTEGRATION.md)** - Complete integration guide
- **[API_REFERENCE.md](./API_REFERENCE.md)** - Full API documentation
- **[openapi.yaml](./openapi.yaml)** - OpenAPI/Swagger specification

---

## 🔒 Security Note

**NEVER call Capital.com API directly from frontend!**

✅ **Correct:** Frontend → Your Backend Proxy → Capital.com  
❌ **Wrong:** Frontend → Capital.com API directly

The backend proxy protects your trading credentials and API keys.
