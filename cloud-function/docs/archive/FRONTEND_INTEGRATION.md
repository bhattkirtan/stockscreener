# Frontend Integration Guide
## Strategy Optimizer API

This guide explains how to integrate the Strategy Optimizer API with your frontend (Lovable, React, Vue, or any JavaScript framework).

---

## 🌐 API Endpoint

**Production URL**: `https://optimize-api-6ovej2yaoa-uc.a.run.app`

**Local Development**: `http://localhost:8000`

---

## 📡 Available Endpoints

| Method | Endpoint | Description | Response Time |
|--------|----------|-------------|---------------|
| `POST` | `/api/optimize` | Start new optimization | Instant (~100ms) |
| `GET` | `/api/optimize/status/:id` | Check optimization status | Instant |
| `GET` | `/api/optimize/history` | List all runs | Instant |
| `GET` | `/api/optimize/results/:id` | Get top strategies | Instant |
| `GET` | `/api/analyze/:id` | Comprehensive analysis | Instant |
| `GET` | `/api/analyze/latest` | Analyze latest run | Instant |
| `DELETE` | `/api/optimize/:id` | Delete a run | Instant |
| `GET` | `/api/stats/summary` | Overall statistics | Instant |
| `GET` | `/health` | Health check | Instant |

---

## 🚀 Quick Start

### 1. Configure API URL

```javascript
// config.js
export const API_CONFIG = {
  baseURL: 'https://optimize-api-6ovej2yaoa-uc.a.run.app',
  timeout: 10000, // 10 seconds for API calls
};
```

### 2. Create API Client

```javascript
// api/optimizer.js
const API_BASE = 'https://optimize-api-6ovej2yaoa-uc.a.run.app';

export const optimizerAPI = {
  // Start a new optimization
  async startOptimization(params) {
    const response = await fetch(`${API_BASE}/api/optimize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params)
    });
    return response.json();
  },

  // Check status
  async getStatus(runId) {
    const response = await fetch(`${API_BASE}/api/optimize/status/${runId}`);
    return response.json();
  },

  // Get results
  async getResults(runId) {
    const response = await fetch(`${API_BASE}/api/optimize/results/${runId}`);
    return response.json();
  },

  // Get history
  async getHistory(limit = 50) {
    const response = await fetch(`${API_BASE}/api/optimize/history?limit=${limit}`);
    return response.json();
  },

  // Delete run
  async deleteRun(runId) {
    const response = await fetch(`${API_BASE}/api/optimize/${runId}`, {
      method: 'DELETE'
    });
    return response.json();
  },

  // Get stats
  async getStats() {
    const response = await fetch(`${API_BASE}/api/stats/summary`);
    return response.json();
  }
};
```

---

## 💡 Usage Examples

### Starting an Optimization

```javascript
// Example: Start optimization
async function runOptimization() {
  try {
    const result = await optimizerAPI.startOptimization({
      instrument: 'GOLD',
      timeframe: 'M5',
      capital: 10000,
      position_size: 0.1,
      mode: 'full',      // or 'fast'
      n_jobs: -1         // -1 = use all CPUs
    });

    console.log('Optimization started:', result);
    // Response: { run_id: "GOLD_M5_20260305_123456", status: "queued" }

    // Start polling for status
    pollOptimizationStatus(result.run_id);
  } catch (error) {
    console.error('Failed to start optimization:', error);
  }
}
```

### Polling for Status

```javascript
// Poll every 5 seconds until completion
async function pollOptimizationStatus(runId) {
  const pollInterval = 5000; // 5 seconds
  
  const poll = async () => {
    try {
      const status = await optimizerAPI.getStatus(runId);
      
      console.log(`Status: ${status.status}`);
      
      if (status.status === 'completed') {
        // Get results
        const results = await optimizerAPI.getResults(runId);
        console.log('Optimization complete!', results);
        return results;
      }
      
      if (status.status === 'failed') {
        console.error('Optimization failed:', status.error);
        return null;
      }
      
      // Still running or queued - poll again
      if (status.status === 'running' || status.status === 'queued') {
        setTimeout(poll, pollInterval);
      }
    } catch (error) {
      console.error('Polling error:', error);
      setTimeout(poll, pollInterval); // Retry on error
    }
  };
  
  poll();
}
```

---

## 🎨 React Integration

### Custom Hook

```javascript
// hooks/useOptimizer.js
import { useState, useEffect, useCallback } from 'react';
import { optimizerAPI } from '../api/optimizer';

export function useOptimizer() {
  const [optimizations, setOptimizations] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Start optimization
  const startOptimization = useCallback(async (params) => {
    setLoading(true);
    setError(null);
    
    try {
      const result = await optimizerAPI.startOptimization(params);
      
      // Add to list and start polling
      setOptimizations(prev => [...prev, result]);
      pollStatus(result.run_id);
      
      return result;
    } catch (err) {
      setError(err.message);
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  // Poll status
  const pollStatus = useCallback(async (runId) => {
    const poll = async () => {
      try {
        const status = await optimizerAPI.getStatus(runId);
        
        // Update in list
        setOptimizations(prev =>
          prev.map(opt => opt.run_id === runId ? { ...opt, ...status } : opt)
        );

        // Continue polling if not complete
        if (status.status === 'running' || status.status === 'queued') {
          setTimeout(() => poll(), 5000);
        }
      } catch (err) {
        console.error('Polling error:', err);
        setTimeout(() => poll(), 5000); // Retry
      }
    };
    
    poll();
  }, []);

  // Load history on mount
  useEffect(() => {
    optimizerAPI.getHistory().then(data => {
      setOptimizations(data.runs || []);
    });
  }, []);

  return {
    optimizations,
    loading,
    error,
    startOptimization
  };
}
```

### Component Example

```jsx
// components/OptimizerPanel.jsx
import React, { useState } from 'react';
import { useOptimizer } from '../hooks/useOptimizer';

export function OptimizerPanel() {
  const { optimizations, loading, startOptimization } = useOptimizer();
  const [params, setParams] = useState({
    instrument: 'GOLD',
    timeframe: 'M5',
    capital: 10000,
    position_size: 0.1
  });

  const handleSubmit = async (e) => {
    e.preventDefault();
    await startOptimization(params);
  };

  return (
    <div className="optimizer-panel">
      <h2>Strategy Optimizer</h2>
      
      {/* Input Form */}
      <form onSubmit={handleSubmit}>
        <select 
          value={params.instrument}
          onChange={e => setParams({...params, instrument: e.target.value})}
        >
          <option value="GOLD">Gold</option>
          <option value="EURUSD">EUR/USD</option>
        </select>
        
        <select
          value={params.timeframe}
          onChange={e => setParams({...params, timeframe: e.target.value})}
        >
          <option value="M5">5 Minutes</option>
          <option value="M15">15 Minutes</option>
        </select>
        
        <button type="submit" disabled={loading}>
          {loading ? 'Starting...' : 'Start Optimization'}
        </button>
      </form>

      {/* Optimizations List */}
      <div className="optimizations-list">
        {optimizations.map(opt => (
          <div key={opt.run_id} className="optimization-card">
            <h3>{opt.run_id}</h3>
            <span className={`status ${opt.status}`}>{opt.status}</span>
            
            {opt.status === 'completed' && (
              <button onClick={() => viewResults(opt.run_id)}>
                View Results
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
```

---

## 🎯 Lovable.dev Integration

### API Service

```typescript
// services/optimizer.service.ts
const API_URL = 'https://optimize-api-6ovej2yaoa-uc.a.run.app';

interface OptimizationParams {
  instrument: string;
  timeframe: string;
  capital?: number;
  position_size?: number;
  mode?: 'full' | 'fast';
}

interface OptimizationStatus {
  run_id: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  start_time?: string;
  end_time?: string;
  error?: string;
}

export const OptimizerService = {
  async startOptimization(params: OptimizationParams): Promise<OptimizationStatus> {
    const response = await fetch(`${API_URL}/api/optimize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params)
    });
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    
    return response.json();
  },

  async getStatus(runId: string): Promise<OptimizationStatus> {
    const response = await fetch(`${API_URL}/api/optimize/status/${runId}`);
    return response.json();
  },

  async getResults(runId: string) {
    const response = await fetch(`${API_URL}/api/optimize/results/${runId}`);
    return response.json();
  },

  async getHistory() {
    const response = await fetch(`${API_URL}/api/optimize/history`);
    return response.json();
  }
};
```

### Lovable Component

```tsx
// In your Lovable component
import { useState } from 'react';
import { OptimizerService } from './services/optimizer.service';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

export default function OptimizerDashboard() {
  const [runId, setRunId] = useState<string | null>(null);
  const [status, setStatus] = useState<string>('idle');
  
  const startOptimization = async () => {
    const result = await OptimizerService.startOptimization({
      instrument: 'GOLD',
      timeframe: 'M5',
      capital: 10000,
      position_size: 0.1
    });
    
    setRunId(result.run_id);
    setStatus(result.status);
    pollStatus(result.run_id);
  };
  
  const pollStatus = async (id: string) => {
    const interval = setInterval(async () => {
      const statusData = await OptimizerService.getStatus(id);
      setStatus(statusData.status);
      
      if (statusData.status === 'completed' || statusData.status === 'failed') {
        clearInterval(interval);
      }
    }, 5000);
  };
  
  return (
    <Card className="p-6">
      <h1 className="text-2xl font-bold mb-4">Strategy Optimizer</h1>
      
      <Button onClick={startOptimization} disabled={status === 'running'}>
        Start Optimization
      </Button>
      
      {runId && (
        <div className="mt-4">
          <p>Run ID: {runId}</p>
          <Badge>{status}</Badge>
        </div>
      )}
    </Card>
  );
}
```

---

## 🔄 Status States

Your UI should handle these status states:

| Status | Description | UI Action |
|--------|-------------|-----------|
| `queued` | Task in queue | Show "Waiting in queue..." |
| `running` | Optimization in progress | Show progress spinner |
| `completed` | Finished successfully | Show "View Results" button |
| `failed` | Error occurred | Show error message |

---

## ⏱️ Timing Guidelines

- **API Response**: <100ms (instant)
- **Optimization Duration**: 2-5 minutes (depending on parameters)
- **Polling Interval**: 5 seconds (recommended)
- **Max Concurrent**: 3 optimizations at once

---

## 🎨 UI/UX Best Practices

### 1. Show Status Clearly

```jsx
const StatusBadge = ({ status }) => {
  const colors = {
    queued: 'bg-yellow-100 text-yellow-800',
    running: 'bg-blue-100 text-blue-800',
    completed: 'bg-green-100 text-green-800',
    failed: 'bg-red-100 text-red-800'
  };
  
  return (
    <span className={`px-2 py-1 rounded ${colors[status]}`}>
      {status.toUpperCase()}
    </span>
  );
};
```

### 2. Progress Indicator

```jsx
{status === 'running' && (
  <div className="flex items-center gap-2">
    <Spinner />
    <span>Optimizing... (Estimated 2-5 minutes)</span>
  </div>
)}
```

### 3. Results Preview

```jsx
{status === 'completed' && results && (
  <div className="results-preview">
    <h3>Top Strategy</h3>
    <p>Profit: ${results.top_10[0]['Total Profit ($)'].toFixed(2)}</p>
    <p>Win Rate: {results.top_10[0]['Win Rate (%)'].toFixed(1)}%</p>
    <Button onClick={() => showFullResults(runId)}>
      View All Strategies
    </Button>
  </div>
)}
```

---

## 📊 Example: Full Integration

```javascript
// Complete example with all features
class OptimizerClient {
  constructor(apiUrl) {
    this.apiUrl = apiUrl;
    this.activeRuns = new Map();
  }

  async startOptimization(params) {
    const response = await fetch(`${this.apiUrl}/api/optimize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params)
    });
    
    const data = await response.json();
    
    // Start monitoring
    this.monitorRun(data.run_id);
    
    return data;
  }

  monitorRun(runId) {
    const poll = async () => {
      try {
        const status = await this.getStatus(runId);
        
        // Emit event
        this.emit('statusUpdate', { runId, ...status });
        
        // Continue polling if active
        if (status.status === 'running' || status.status === 'queued') {
          this.activeRuns.set(runId, setTimeout(poll, 5000));
        } else {
          this.activeRuns.delete(runId);
        }
      } catch (error) {
        this.emit('error', { runId, error });
      }
    };
    
    poll();
  }

  async getStatus(runId) {
    const response = await fetch(`${this.apiUrl}/api/optimize/status/${runId}`);
    return response.json();
  }

  async getResults(runId) {
    const response = await fetch(`${this.apiUrl}/api/optimize/results/${runId}`);
    return response.json();
  }

  stopMonitoring(runId) {
    const timerId = this.activeRuns.get(runId);
    if (timerId) {
      clearTimeout(timerId);
      this.activeRuns.delete(runId);
    }
  }

  // Simple event emitter
  on(event, callback) {
    this.listeners = this.listeners || {};
    this.listeners[event] = this.listeners[event] || [];
    this.listeners[event].push(callback);
  }

  emit(event, data) {
    const callbacks = this.listeners?.[event] || [];
    callbacks.forEach(cb => cb(data));
  }
}

// Usage in application
const optimizer = new OptimizerClient('https://optimize-api-6ovej2yaoa-uc.a.run.app');

optimizer.on('statusUpdate', ({ runId, status }) => {
  console.log(`${runId}: ${status}`);
  updateUI(runId, status);
});

optimizer.on('error', ({ runId, error }) => {
  console.error(`Error in ${runId}:`, error);
  showErrorToUser(error);
});

// Start optimization
await optimizer.startOptimization({
  instrument: 'GOLD',
  timeframe: 'M5'
});
```

---

## 🐛 Error Handling

```javascript
async function safeApiCall(apiFunction, ...args) {
  try {
    return await apiFunction(...args);
  } catch (error) {
    // Network error
    if (!navigator.onLine) {
      return { error: 'No internet connection' };
    }
    
    // API error
    if (error.response) {
      const data = await error.response.json();
      return { error: data.error || 'API error' };
    }
    
    // Unknown error
    return { error: error.message || 'Unknown error' };
  }
}

// Usage
const result = await safeApiCall(optimizerAPI.startOptimization, params);
if (result.error) {
  showError(result.error);
} else {
  showSuccess(result);
}
```

---

## 🔗 API Reference URLs

- **API Base**: https://optimize-api-6ovej2yaoa-uc.a.run.app
- **Health Check**: https://optimize-api-6ovej2yaoa-uc.a.run.app/health
- **OpenAPI Docs**: Auto-generated documentation available at the base URL

---

## 📝 Summary

1. **Use the production API**: `https://optimize-api-6ovej2yaoa-uc.a.run.app`
2. **API calls are instant** - they return immediately with a `run_id`
3. **Poll for status** every 5 seconds
4. **Handle 4 states**: queued, running, completed, failed
5. **Optimizations take 2-5 minutes** to complete
6. **Max 3 concurrent** optimizations

Need help? Check the deployment logs or contact support!
