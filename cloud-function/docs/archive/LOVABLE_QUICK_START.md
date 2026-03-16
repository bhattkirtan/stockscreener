# 🚀 Lovable Quick Start - Trading API Integration

**Ready-to-use code for your Lovable project**

---

## 📋 Step 1: Environment Setup

In your Lovable project settings, add:

```env
# For Development (Virtual Money)
REACT_APP_TRADING_ENV=demo

# For Production (Real Money) ⚠️
REACT_APP_TRADING_ENV=production
```

---

## 📝 Step 2: Create Config File

Create `src/config/trading.config.ts`:

```typescript
export const TRADING_ENV = {
  DEMO: 'https://us-central1-double-venture-442318-k8.cloudfunctions.net/capitalComService',
  PRODUCTION: 'https://marketservicelive-6ovej2yaoa-uc.a.run.app'
} as const;

export const API_BASE_URL = process.env.REACT_APP_TRADING_ENV === 'production' 
  ? TRADING_ENV.PRODUCTION 
  : TRADING_ENV.DEMO;

export const IS_PRODUCTION = process.env.REACT_APP_TRADING_ENV === 'production';
```

---

## 🔌 Step 3: Create API Client

Create `src/lib/api/tradingClient.ts`:

```typescript
import { API_BASE_URL } from '@/config/trading.config';

export interface Position {
  dealId: string;
  epic: string;
  direction: 'BUY' | 'SELL';
  size: number;
  openLevel: number;
  level: number;
  currency: string;
  stopLevel?: number;
  profitLevel?: number;
}

export interface CreatePositionRequest {
  epic: string;
  direction: 'BUY' | 'SELL';
  size: number;
  stopLevel?: number;
  profitLevel?: number;
  guaranteedStop?: boolean;
}

export interface MarketInfo {
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
    marketStatus: 'TRADEABLE' | 'CLOSED';
    percentageChange: number;
  };
  dealingRules: {
    minDealSize: { value: number };
    maxDealSize: { value: number };
  };
}

class TradingAPI {
  private baseURL = API_BASE_URL;

  async getPositions(): Promise<{ positions: Position[] }> {
    const response = await fetch(`${this.baseURL}/get_positions`);
    if (!response.ok) throw new Error('Failed to fetch positions');
    return response.json();
  }

  async getMarketInfo(epic: string): Promise<MarketInfo> {
    const response = await fetch(`${this.baseURL}/market/${epic}`);
    if (!response.ok) throw new Error('Failed to fetch market info');
    return response.json();
  }

  async createPosition(request: CreatePositionRequest): Promise<{ dealReference: string }> {
    const response = await fetch(`${this.baseURL}/create_position`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request)
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || 'Failed to create position');
    }
    return response.json();
  }

  async closePosition(dealId: string): Promise<{ dealReference: string }> {
    const response = await fetch(`${this.baseURL}/close_position/${dealId}`, {
      method: 'DELETE'
    });
    if (!response.ok) throw new Error('Failed to close position');
    return response.json();
  }

  async getHistoricalPrices(epic: string, resolution: string = '1H', max: number = 50) {
    const response = await fetch(
      `${this.baseURL}/prices/${epic}?resolution=${resolution}&max=${max}`
    );
    if (!response.ok) throw new Error('Failed to fetch historical prices');
    return response.json();
  }

  async searchMarkets(searchTerm?: string) {
    const url = searchTerm 
      ? `${this.baseURL}/markets?searchTerm=${encodeURIComponent(searchTerm)}`
      : `${this.baseURL}/markets`;
    const response = await fetch(url);
    if (!response.ok) throw new Error('Failed to search markets');
    return response.json();
  }
}

export const tradingAPI = new TradingAPI();
```

---

## ⚛️ Step 4: Create React Hooks

Create `src/hooks/useTrading.ts`:

```typescript
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { tradingAPI, CreatePositionRequest } from '@/lib/api/tradingClient';
import { toast } from 'sonner';

export const usePositions = () => {
  return useQuery({
    queryKey: ['positions'],
    queryFn: () => tradingAPI.getPositions(),
    refetchInterval: 5000, // Refresh every 5 seconds
  });
};

export const useMarketInfo = (epic: string) => {
  return useQuery({
    queryKey: ['market', epic],
    queryFn: () => tradingAPI.getMarketInfo(epic),
    refetchInterval: 1000, // Refresh every second
    enabled: !!epic,
  });
};

export const useCreatePosition = () => {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: (request: CreatePositionRequest) => tradingAPI.createPosition(request),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['positions'] });
      toast.success('Position opened successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
};

export const useClosePosition = () => {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: (dealId: string) => tradingAPI.closePosition(dealId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['positions'] });
      toast.success('Position closed successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
};

export const useSearchMarkets = (searchTerm?: string) => {
  return useQuery({
    queryKey: ['markets', searchTerm],
    queryFn: () => tradingAPI.searchMarkets(searchTerm),
  });
};
```

---

## 🎨 Step 5: Create UI Component

Create `src/components/PositionsList.tsx`:

```typescript
import { usePositions, useClosePosition } from '@/hooks/useTrading';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { IS_PRODUCTION } from '@/config/trading.config';

export function PositionsList() {
  const { data, isLoading } = usePositions();
  const closePosition = useClosePosition();

  if (isLoading) return <div>Loading positions...</div>;

  return (
    <div className="space-y-4">
      {IS_PRODUCTION && (
        <div className="bg-red-500 text-white px-4 py-2 rounded-lg text-center font-bold">
          🔴 LIVE TRADING - Real Money at Risk
        </div>
      )}
      
      <h2 className="text-2xl font-bold">
        Open Positions ({data?.positions?.length || 0})
      </h2>

      {data?.positions?.map((position) => (
        <Card key={position.dealId}>
          <CardHeader>
            <CardTitle className="flex justify-between items-center">
              <span>{position.epic}</span>
              <span className={position.direction === 'BUY' ? 'text-green-500' : 'text-red-500'}>
                {position.direction}
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <div className="flex justify-between">
                <span>Size:</span>
                <span className="font-bold">{position.size}</span>
              </div>
              <div className="flex justify-between">
                <span>Open Level:</span>
                <span>{position.openLevel}</span>
              </div>
              <div className="flex justify-between">
                <span>Current Level:</span>
                <span>{position.level}</span>
              </div>
              {position.stopLevel && (
                <div className="flex justify-between">
                  <span>Stop Loss:</span>
                  <span className="text-red-500">{position.stopLevel}</span>
                </div>
              )}
              {position.profitLevel && (
                <div className="flex justify-between">
                  <span>Take Profit:</span>
                  <span className="text-green-500">{position.profitLevel}</span>
                </div>
              )}
              <Button
                variant="destructive"
                className="w-full mt-4"
                onClick={() => closePosition.mutate(position.dealId)}
                disabled={closePosition.isPending}
              >
                {closePosition.isPending ? 'Closing...' : 'Close Position'}
              </Button>
            </div>
          </CardContent>
        </Card>
      ))}

      {(!data?.positions || data.positions.length === 0) && (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            No open positions
          </CardContent>
        </Card>
      )}
    </div>
  );
}
```

---

## ✅ Step 6: Setup Query Provider

In your `src/App.tsx` or `src/main.tsx`:

```typescript
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'sonner';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000,
      refetchOnWindowFocus: true,
    },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Toaster position="top-right" />
      {/* Your app components */}
    </QueryClientProvider>
  );
}
```

---

## 🧪 Step 7: Test the Integration

```typescript
// Quick test in browser console or a test component
import { tradingAPI } from '@/lib/api/tradingClient';

// Test connection
tradingAPI.getPositions()
  .then(data => console.log('✅ Connected!', data))
  .catch(err => console.error('❌ Error:', err));

// Get market info
tradingAPI.getMarketInfo('GOLD')
  .then(data => console.log('Gold price:', data.snapshot.bid));
```

---

## 📦 Required Dependencies

Add these to your Lovable project:

```json
{
  "@tanstack/react-query": "^5.0.0",
  "sonner": "^1.0.0"
}
```

---

## ⚠️ Important Notes

### Before Going Live (Production):

1. **Test everything on DEMO first**
2. **Start with minimum position sizes** (0.01)
3. **Always use stop losses**
4. **Monitor trades closely**
5. **Have emergency plan ready**

### Switching to Production:

```env
# Change this in Lovable settings:
REACT_APP_TRADING_ENV=production
```

### Emergency Kill Switch:

```bash
# Run this to disable trading immediately:
gcloud functions deploy marketServiceLive \
  --region=us-central1 \
  --max-instances=0 \
  --project=double-venture-442318-k8
```

---

## 📚 Full Documentation

For complete details, see:
- [Full Integration Guide](./LOVABLE_INTEGRATION.md)
- [API Reference](./API_REFERENCE.md)
- [Production Setup](./PRODUCTION_SETUP.md)
- [OpenAPI Spec](./openapi.yaml)

---

## 🎯 What You Get

✅ **Real-time position tracking**  
✅ **Live market data**  
✅ **One-click trading**  
✅ **TradingView webhook support**  
✅ **Risk management (stop loss/take profit)**  
✅ **Environment switching (demo/live)**  
✅ **Error handling**  
✅ **Loading states**  

---

**🚀 You're ready to build! Start with the PositionsList component and expand from there.**
