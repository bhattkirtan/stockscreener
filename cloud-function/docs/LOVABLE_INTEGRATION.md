# 💜 Lovable Integration Guide

Complete guide for integrating the Strategy Optimizer API with your Lovable project.

## 🚀 Quick Start

### 1. Project Setup

In your Lovable project, the structure should look like:

```
src/
├── components/
│   └── optimizer/
│       ├── OptimizerForm.tsx
│       ├── OptimizerResults.tsx
│       └── OptimizerHistory.tsx
├── hooks/
│   └── useOptimizer.ts
├── services/
│   └── api.ts
└── types/
    └── optimizer.ts
```

### 2. Environment Configuration

In Lovable, add your API URL as an environment variable:

1. Go to your project settings in Lovable
2. Add environment variable:
   - Key: `VITE_OPTIMIZER_API_URL`
   - Value: `https://optimize-api-6ovej2yaoa-uc.a.run.app`

---

## 📦 Type Definitions

Create `src/types/optimizer.ts`:

```typescript
export interface OptimizationParams {
  instrument: 'GOLD' | 'EURUSD';
  timeframe: 'M5' | 'M15' | 'H1' | 'H4' | 'D1';
  capital?: number;
  position_size?: number;
  mode?: 'full' | 'fast';
}

export interface Strategy {
  'BB Period': number;
  'BB Std Dev': number;
  'RSI Period': number;
  'Risk Reward': number;
  'TP Multiplier': number;
  'Total Profit ($)': number;
  'Win Rate (%)': number;
  'Total Trades': number;
  'Profit Factor': number;
  'Max Drawdown (%)': number;
}

export interface OptimizationRun {
  run_id: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  params: OptimizationParams;
  start_time?: string;
  end_time?: string;
  error?: string;
}

export interface OptimizationResults {
  run_id: string;
  status: 'completed';
  results: {
    top_10: Strategy[];
    total_combinations: number;
    valid_strategies: number;
  };
}
```

---

## 🔌 API Service

Create `src/services/api.ts`:

```typescript
import type { OptimizationParams, OptimizationRun, OptimizationResults } from '@/types/optimizer';

const API_URL = import.meta.env.VITE_OPTIMIZER_API_URL || 'https://optimize-api-6ovej2yaoa-uc.a.run.app';

class OptimizerAPI {
  private baseUrl: string;

  constructor() {
    this.baseUrl = API_URL;
  }

  async startOptimization(params: OptimizationParams): Promise<OptimizationRun> {
    const response = await fetch(`${this.baseUrl}/api/optimize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || 'Failed to start optimization');
    }

    return response.json();
  }

  async getStatus(runId: string): Promise<OptimizationRun> {
    const response = await fetch(`${this.baseUrl}/api/optimize/status/${runId}`);
    
    if (!response.ok) {
      throw new Error('Failed to get status');
    }

    return response.json();
  }

  async getResults(runId: string): Promise<OptimizationResults> {
    const response = await fetch(`${this.baseUrl}/api/optimize/results/${runId}`);
    
    if (!response.ok) {
      throw new Error('Failed to get results');
    }

    return response.json();
  }

  async getHistory(): Promise<{ runs: OptimizationRun[]; count: number }> {
    const response = await fetch(`${this.baseUrl}/api/optimize/history`);
    
    if (!response.ok) {
      throw new Error('Failed to get history');
    }

    return response.json();
  }

  async deleteRun(runId: string): Promise<void> {
    const response = await fetch(`${this.baseUrl}/api/optimize/${runId}`, {
      method: 'DELETE',
    });

    if (!response.ok) {
      throw new Error('Failed to delete run');
    }
  }

  async healthCheck(): Promise<{ status: string; service: string }> {
    const response = await fetch(`${this.baseUrl}/health`);
    return response.json();
  }
}

export const optimizerAPI = new OptimizerAPI();
```

---

## 🪝 Custom Hook

Create `src/hooks/useOptimizer.ts`:

```typescript
import { useState, useEffect, useCallback } from 'react';
import { optimizerAPI } from '@/services/api';
import type { OptimizationParams, OptimizationRun, OptimizationResults } from '@/types/optimizer';
import { useToast } from '@/hooks/use-toast';

export function useOptimizer() {
  const [currentRun, setCurrentRun] = useState<OptimizationRun | null>(null);
  const [results, setResults] = useState<OptimizationResults | null>(null);
  const [history, setHistory] = useState<OptimizationRun[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const { toast } = useToast();

  // Start optimization
  const startOptimization = useCallback(async (params: OptimizationParams) => {
    try {
      setIsLoading(true);
      const run = await optimizerAPI.startOptimization(params);
      setCurrentRun(run);
      setResults(null);
      
      toast({
        title: 'Optimization Started',
        description: `Run ID: ${run.run_id}`,
      });

      return run;
    } catch (error) {
      toast({
        title: 'Error',
        description: error instanceof Error ? error.message : 'Failed to start optimization',
        variant: 'destructive',
      });
      throw error;
    } finally {
      setIsLoading(false);
    }
  }, [toast]);

  // Poll status
  const pollStatus = useCallback(async (runId: string) => {
    try {
      const status = await optimizerAPI.getStatus(runId);
      setCurrentRun(status);

      if (status.status === 'completed') {
        const results = await optimizerAPI.getResults(runId);
        setResults(results);
        
        toast({
          title: 'Optimization Complete!',
          description: `Found ${results.results.valid_strategies} valid strategies`,
        });
      } else if (status.status === 'failed') {
        toast({
          title: 'Optimization Failed',
          description: status.error || 'Unknown error',
          variant: 'destructive',
        });
      }

      return status;
    } catch (error) {
      console.error('Failed to poll status:', error);
    }
  }, [toast]);

  // Auto-poll when there's an active run
  useEffect(() => {
    if (!currentRun || (currentRun.status !== 'running' && currentRun.status !== 'queued')) {
      return;
    }

    const interval = setInterval(() => {
      pollStatus(currentRun.run_id);
    }, 5000);

    return () => clearInterval(interval);
  }, [currentRun, pollStatus]);

  // Load history
  const loadHistory = useCallback(async () => {
    try {
      const data = await optimizerAPI.getHistory();
      setHistory(data.runs);
    } catch (error) {
      toast({
        title: 'Error',
        description: 'Failed to load history',
        variant: 'destructive',
      });
    }
  }, [toast]);

  // Delete run
  const deleteRun = useCallback(async (runId: string) => {
    try {
      await optimizerAPI.deleteRun(runId);
      setHistory(prev => prev.filter(run => run.run_id !== runId));
      
      toast({
        title: 'Deleted',
        description: 'Run deleted successfully',
      });
    } catch (error) {
      toast({
        title: 'Error',
        description: 'Failed to delete run',
        variant: 'destructive',
      });
    }
  }, [toast]);

  return {
    currentRun,
    results,
    history,
    isLoading,
    startOptimization,
    pollStatus,
    loadHistory,
    deleteRun,
  };
}
```

---

## 🎨 Optimizer Form Component

Create `src/components/optimizer/OptimizerForm.tsx`:

```tsx
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Input } from '@/components/ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { useOptimizer } from '@/hooks/useOptimizer';
import type { OptimizationParams } from '@/types/optimizer';
import { Loader2 } from 'lucide-react';

export function OptimizerForm() {
  const { startOptimization, isLoading, currentRun } = useOptimizer();
  
  const [params, setParams] = useState<OptimizationParams>({
    instrument: 'GOLD',
    timeframe: 'M5',
    capital: 10000,
    position_size: 0.1,
    mode: 'fast',
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    startOptimization(params);
  };

  const isRunning = currentRun?.status === 'running' || currentRun?.status === 'queued';

  return (
    <Card>
      <CardHeader>
        <CardTitle>Strategy Optimizer</CardTitle>
        <CardDescription>
          Configure and run backtesting optimization
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Instrument Selection */}
          <div className="space-y-2">
            <Label htmlFor="instrument">Instrument</Label>
            <Select
              value={params.instrument}
              onValueChange={(value: 'GOLD' | 'EURUSD') =>
                setParams({ ...params, instrument: value })
              }
            >
              <SelectTrigger id="instrument">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="GOLD">Gold (XAU/USD)</SelectItem>
                <SelectItem value="EURUSD">EUR/USD</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Timeframe Selection */}
          <div className="space-y-2">
            <Label htmlFor="timeframe">Timeframe</Label>
            <Select
              value={params.timeframe}
              onValueChange={(value) =>
                setParams({ ...params, timeframe: value as any })
              }
            >
              <SelectTrigger id="timeframe">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="M5">5 Minutes</SelectItem>
                <SelectItem value="M15">15 Minutes</SelectItem>
                <SelectItem value="H1">1 Hour</SelectItem>
                <SelectItem value="H4">4 Hours</SelectItem>
                <SelectItem value="D1">Daily</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Capital Input */}
          <div className="space-y-2">
            <Label htmlFor="capital">Starting Capital ($)</Label>
            <Input
              id="capital"
              type="number"
              value={params.capital}
              onChange={(e) =>
                setParams({ ...params, capital: parseFloat(e.target.value) })
              }
              min={1000}
              step={1000}
            />
          </div>

          {/* Position Size */}
          <div className="space-y-2">
            <Label htmlFor="positionSize">Position Size (lots)</Label>
            <Input
              id="positionSize"
              type="number"
              value={params.position_size}
              onChange={(e) =>
                setParams({ ...params, position_size: parseFloat(e.target.value) })
              }
              min={0.01}
              step={0.01}
              max={10}
            />
          </div>

          {/* Mode Selection */}
          <div className="space-y-3">
            <Label>Optimization Mode</Label>
            <RadioGroup
              value={params.mode}
              onValueChange={(value: 'fast' | 'full') =>
                setParams({ ...params, mode: value })
              }
            >
              <div className="flex items-center space-x-2">
                <RadioGroupItem value="fast" id="fast" />
                <Label htmlFor="fast" className="font-normal">
                  Fast (~2 min) - Limited parameter ranges
                </Label>
              </div>
              <div className="flex items-center space-x-2">
                <RadioGroupItem value="full" id="full" />
                <Label htmlFor="full" className="font-normal">
                  Full (~5 min) - Complete parameter sweep
                </Label>
              </div>
            </RadioGroup>
          </div>

          {/* Submit Button */}
          <Button type="submit" className="w-full" disabled={isLoading || isRunning}>
            {isLoading || isRunning ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                {isRunning ? 'Optimization Running...' : 'Starting...'}
              </>
            ) : (
              'Start Optimization'
            )}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
```

---

## 📊 Results Component

Create `src/components/optimizer/OptimizerResults.tsx`:

```tsx
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useOptimizer } from '@/hooks/useOptimizer';
import { TrendingUp, TrendingDown, Target, Percent } from 'lucide-react';

export function OptimizerResults() {
  const { results, currentRun } = useOptimizer();

  if (!currentRun) {
    return (
      <Card>
        <CardContent className="pt-6">
          <p className="text-muted-foreground text-center">No active optimization</p>
        </CardContent>
      </Card>
    );
  }

  const statusColors = {
    queued: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
    running: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
    completed: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
    failed: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
  };

  return (
    <div className="space-y-4">
      {/* Status Card */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Run Status</CardTitle>
              <CardDescription className="mt-1.5">
                {currentRun.run_id}
              </CardDescription>
            </div>
            <Badge className={statusColors[currentRun.status]}>
              {currentRun.status.toUpperCase()}
            </Badge>
          </div>
        </CardHeader>
        {currentRun.status === 'running' && (
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Optimization in progress... This typically takes 2-5 minutes.
            </p>
          </CardContent>
        )}
        {currentRun.status === 'failed' && currentRun.error && (
          <CardContent>
            <p className="text-sm text-destructive">{currentRun.error}</p>
          </CardContent>
        )}
      </Card>

      {/* Results Card */}
      {results && currentRun.status === 'completed' && (
        <>
          {/* Summary Stats */}
          <div className="grid gap-4 md:grid-cols-3">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Valid Strategies</CardTitle>
                <Target className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{results.results.valid_strategies}</div>
                <p className="text-xs text-muted-foreground">
                  out of {results.results.total_combinations} tested
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Top Profit</CardTitle>
                <TrendingUp className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-green-600">
                  ${results.results.top_10[0]['Total Profit ($)'].toFixed(2)}
                </div>
                <p className="text-xs text-muted-foreground">Best performing strategy</p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Win Rate</CardTitle>
                <Percent className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">
                  {results.results.top_10[0]['Win Rate (%)'].toFixed(1)}%
                </div>
                <p className="text-xs text-muted-foreground">Top strategy win rate</p>
              </CardContent>
            </Card>
          </div>

          {/* Top Strategies Table */}
          <Card>
            <CardHeader>
              <CardTitle>Top 10 Strategies</CardTitle>
              <CardDescription>
                Best performing parameter combinations
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-12">#</TableHead>
                      <TableHead>BB Period</TableHead>
                      <TableHead>BB Std</TableHead>
                      <TableHead>RSI Period</TableHead>
                      <TableHead>R:R</TableHead>
                      <TableHead className="text-right">Profit</TableHead>
                      <TableHead className="text-right">Win Rate</TableHead>
                      <TableHead className="text-right">Trades</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {results.results.top_10.map((strategy, index) => (
                      <TableRow key={index}>
                        <TableCell className="font-medium">{index + 1}</TableCell>
                        <TableCell>{strategy['BB Period']}</TableCell>
                        <TableCell>{strategy['BB Std Dev']}</TableCell>
                        <TableCell>{strategy['RSI Period']}</TableCell>
                        <TableCell>{strategy['Risk Reward']}</TableCell>
                        <TableCell className="text-right font-medium text-green-600">
                          ${strategy['Total Profit ($)'].toFixed(2)}
                        </TableCell>
                        <TableCell className="text-right">
                          {strategy['Win Rate (%)'].toFixed(1)}%
                        </TableCell>
                        <TableCell className="text-right">
                          {strategy['Total Trades']}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
```

---

## 📋 History Component

Create `src/components/optimizer/OptimizerHistory.tsx`:

```tsx
import { useEffect } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { useOptimizer } from '@/hooks/useOptimizer';
import { Trash2, RefreshCw } from 'lucide-react';

export function OptimizerHistory() {
  const { history, loadHistory, deleteRun, pollStatus } = useOptimizer();

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  const formatDate = (isoString: string) => {
    return new Date(isoString).toLocaleString();
  };

  const statusColors = {
    queued: 'bg-yellow-100 text-yellow-800',
    running: 'bg-blue-100 text-blue-800',
    completed: 'bg-green-100 text-green-800',
    failed: 'bg-red-100 text-red-800',
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Optimization History</CardTitle>
            <CardDescription>Past optimization runs</CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={loadHistory}>
            <RefreshCw className="h-4 w-4 mr-2" />
            Refresh
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {history.length === 0 ? (
            <p className="text-muted-foreground text-center py-8">No optimization runs yet</p>
          ) : (
            history.map((run) => (
              <div
                key={run.run_id}
                className="flex items-center justify-between p-4 border rounded-lg"
              >
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <p className="font-medium text-sm">{run.run_id}</p>
                    <Badge className={statusColors[run.status]}>
                      {run.status}
                    </Badge>
                  </div>
                  <p className="text-sm text-muted-foreground">
                    {run.params.instrument} • {run.params.timeframe} • {run.params.mode} mode
                  </p>
                  {run.start_time && (
                    <p className="text-xs text-muted-foreground">
                      Started: {formatDate(run.start_time)}
                    </p>
                  )}
                </div>
                <div className="flex gap-2">
                  {(run.status === 'running' || run.status === 'queued') && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => pollStatus(run.run_id)}
                    >
                      <RefreshCw className="h-4 w-4" />
                    </Button>
                  )}
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => deleteRun(run.run_id)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            ))
          )}
        </div>
      </CardContent>
    </Card>
  );
}
```

---

## 🏠 Main Dashboard Page

Create your main page (e.g., `src/pages/Optimizer.tsx`):

```tsx
import { OptimizerForm } from '@/components/optimizer/OptimizerForm';
import { OptimizerResults } from '@/components/optimizer/OptimizerResults';
import { OptimizerHistory } from '@/components/optimizer/OptimizerHistory';

export default function Optimizer() {
  return (
    <div className="container mx-auto py-8 space-y-8">
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold">Trading Strategy Optimizer</h1>
        <p className="text-muted-foreground">
          Optimize your trading strategies with backtesting
        </p>
      </div>

      <div className="grid gap-8 lg:grid-cols-2">
        <div className="space-y-8">
          <OptimizerForm />
          <OptimizerHistory />
        </div>
        <OptimizerResults />
      </div>
    </div>
  );
}
```

---

## ✅ Testing in Lovable

1. **Preview your app** - Click the preview button in Lovable
2. **Test the form** - Fill out the optimization parameters
3. **Start optimization** - Click "Start Optimization"
4. **Watch status updates** - Status should update every 5 seconds
5. **View results** - Results appear when status changes to "completed"

---

## 🎯 Key Features Implemented

✅ **Type-safe API client** with TypeScript  
✅ **Auto-polling** for status updates  
✅ **Toast notifications** for user feedback  
✅ **shadcn/ui components** (Button, Card, Select, Input, etc.)  
✅ **Responsive layout** with Tailwind CSS  
✅ **Error handling** with user-friendly messages  
✅ **Loading states** with spinners  
✅ **History management** with delete functionality  

---

## 🔧 Troubleshooting

### Issue: API not responding
**Solution**: Check that the API URL is correct in your environment variables.

```bash
# In Lovable, verify:
VITE_OPTIMIZER_API_URL=https://optimize-api-6ovej2yaoa-uc.a.run.app
```

### Issue: CORS errors
**Solution**: CORS is already configured on the API. If you see CORS errors, it's likely a browser extension blocking requests. Try disabling extensions.

### Issue: Polling not working
**Solution**: The `useOptimizer` hook automatically polls. Ensure:
- The run status is 'running' or 'queued'
- No errors in the browser console
- Network tab shows regular polling requests every 5 seconds

### Issue: Results not displaying
**Solution**: Check:
- Run status is 'completed'
- Results are returned from `/api/optimize/results/{runId}`
- No JavaScript errors in console

---

## 📱 Mobile Responsiveness

The provided components are mobile-ready:
- Forms stack vertically on small screens
- Tables scroll horizontally on mobile
- Cards adapt to screen size with Tailwind's responsive utilities

---

## 🚀 Next Steps

1. **Add charts**: Use Recharts or Chart.js to visualize equity curves
2. **Add filters**: Filter history by instrument, date, or status
3. **Add export**: Allow exporting results to CSV/JSON
4. **Add comparisons**: Compare multiple optimization runs side-by-side
5. **Add alerts**: Email or push notifications when optimization completes

---

## 📚 Resources

- **API Documentation**: [FRONTEND_INTEGRATION.md](./FRONTEND_INTEGRATION.md)
- **Hybrid Architecture**: [HYBRID_ARCHITECTURE.md](./HYBRID_ARCHITECTURE.md)
- **shadcn/ui Docs**: https://ui.shadcn.com
- **Lovable Docs**: https://docs.lovable.dev

---

## 💡 Pro Tips

1. **Use the fast mode** during development to get quick results
2. **Test with different instruments** - GOLD and EURUSD have different characteristics
3. **Validate inputs** - Add form validation to prevent invalid parameters
4. **Cache results** - Store completed results in localStorage for offline access
5. **Add loading skeletons** - Use shadcn/ui Skeleton components for better UX

---

Need help? The API is designed to be simple and reliable. All responses include clear error messages to help you debug issues quickly!
