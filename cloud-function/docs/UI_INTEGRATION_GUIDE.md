# 🚀 Lovable UI Integration Guide

## API Overview

Your backend **already has** an enhanced API deployed and running with ALL strategy parameters exposed for UI control:

- ✅ Strategy indicators (Supertrend, SMA, EMA, Bollinger Bands)
- ✅ TP/SL strategies (Fixed pips vs ATR-based)
- ✅ Pip value optimization (leverage scaling)
- ✅ Advanced filters (min trades, win rate, drawdown)
- ✅ Data selection options (12 instruments across Forex/Commodities/Crypto/Indices)

## Production Endpoints

### Optimization API
- **URL**: `https://optimize-api-6ovej2yaoa-uc.a.run.app`
- **Endpoint**: `POST /optimize`
- **Status**: ✅ Deployed & Healthy

### Scheduler Control API (Data Sync)
- **URL**: `https://scheduler-control-6ovej2yaoa-uc.a.run.app`
- **Endpoints**: 
  - `GET /scheduler/status` - Check if auto-updates are enabled
  - `POST /scheduler/enable` - Enable automatic data updates
  - `POST /scheduler/disable` - Disable automatic data updates
  - `POST /scheduler/trigger` - Manually trigger data update
- **Status**: ✅ Deployed & Healthy

### Health Checks
```bash
# Verify all services are running
curl https://optimize-api-6ovej2yaoa-uc.a.run.app/health
curl https://optimizer-worker-6ovej2yaoa-uc.a.run.app/health
curl https://scheduler-control-6ovej2yaoa-uc.a.run.app/scheduler/status
```

## Available Instruments

The system currently supports **12 instruments** across 4 categories:

### Forex (M15 data)
- **EURUSD** - Euro vs US Dollar
- **EURGBP** - Euro vs British Pound
- **GBPUSD** - British Pound vs US Dollar

### Commodities
- **GOLD** - Gold (M5 and M15 data available)
- **SILVER** - Silver (M15 data)

### Crypto
- **BITCOIN** - Bitcoin (M5 and M15 data available)

### Indices (M15 data)
- **US30** - Dow Jones Industrial Average
- **NASDAQ** - NASDAQ 100

**Note**: Data is automatically updated every 30 minutes when the scheduler is enabled. New instruments can be added by updating the backend configuration.

---

## UI Integration for Lovable

### 1. Basic UI (Current - Minimal Changes)

Your current UI already works! Just update the API call:

```typescript
// frontend/src/utils/api.ts
export async function startOptimization(params: {
  instrument: string;
  timeframe: string;
  initial_capital: number;
  position_size: number;
  mode: 'quick' | 'medium' | 'full';
}) {
  const response = await fetch('https://optimize-api-6ovej2yaoa-uc.a.run.app/optimize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params)
  });
  return response.json();
}

// Usage (no changes needed)
const result = await startOptimization({
  instrument: 'GOLD',
  timeframe: 'M5',
  initial_capital: 10000,
  position_size: 0.1,
  mode: 'quick'
});
```

**This works immediately** - no UI changes required!

---

### 2. Enhanced UI - Add Advanced Options

Add a collapsible "Advanced" section for power users:

```typescript
// frontend/src/components/OptimizationForm.tsx
import { useState } from 'react';

export function OptimizationForm() {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [params, setParams] = useState({
    // Basic (always visible)
    instrument: 'GOLD',
    timeframe: 'M5',
    initial_capital: 10000,
    position_size: 0.1,
    mode: 'quick',
    
    // Advanced (optional overrides)
    pip_values: null as number[] | null,
    tp_sl_strategy: 'both',
    sl_pips_range: null as number[] | null,
    tp_pips_range: null as number[] | null,
    min_win_rate: 0,
    max_drawdown_pct: null as number | null,
  });
  
  return (
    <div className="optimization-form">
      {/* Basic Fields */}
      <select value={params.instrument} onChange={e => setParams({...params, instrument: e.target.value})}>
        <option value="GOLD">Gold</option>
        <option value="EURUSD">EUR/USD</option>
        <option value="GBPUSD">GBP/USD</option>
      </select>
      
      <select value={params.timeframe} onChange={e => setParams({...params, timeframe: e.target.value})}>
        <option value="M5">5 Minutes</option>
        <option value="M15">15 Minutes</option>
        <option value="H1">1 Hour</option>
      </select>
      
      <input type="number" value={params.initial_capital} 
             onChange={e => setParams({...params, initial_capital: +e.target.value})} />
      
      <input type="number" step="0.01" value={params.position_size}
             onChange={e => setParams({...params, position_size: +e.target.value})} />
      
      <select value={params.mode} onChange={e => setParams({...params, mode: e.target.value as any})}>
        <option value="quick">Fast (~2 min)</option>
        <option value="medium">Medium (~5 min)</option>
        <option value="full">Full (~30 min)</option>
      </select>
      
      {/* Advanced Toggle */}
      <button onClick={() => setShowAdvanced(!showAdvanced)} className="text-sm text-blue-500">
        {showAdvanced ? '▼' : '▶'} Advanced Parameters
      </button>
      
      {/* Advanced Section */}
      {showAdvanced && (
        <div className="advanced-params mt-4 p-4 bg-gray-50 rounded">
          <h3 className="font-semibold mb-3">Advanced Options</h3>
          
          {/* TP/SL Strategy */}
          <label className="block mb-2">
            <span className="text-sm">TP/SL Strategy:</span>
            <select value={params.tp_sl_strategy} 
                    onChange={e => setParams({...params, tp_sl_strategy: e.target.value})}>
              <option value="both">Test Both (Recommended)</option>
              <option value="fixed">Fixed Pips Only</option>
              <option value="atr">ATR-Based Only</option>
            </select>
          </label>
          
          {/* Stop Loss Range */}
          <label className="block mb-2">
            <span className="text-sm">Stop Loss Pips (comma-separated):</span>
            <input type="text" placeholder="15,20,25,30" 
                   onChange={e => {
                     const vals = e.target.value.split(',').map(v => +v.trim()).filter(v => !isNaN(v));
                     setParams({...params, sl_pips_range: vals.length ? vals : null});
                   }} />
          </label>
          
          {/* Take Profit Range */}
          <label className="block mb-2">
            <span className="text-sm">Take Profit Pips (comma-separated):</span>
            <input type="text" placeholder="30,40,50,60,75" 
                   onChange={e => {
                     const vals = e.target.value.split(',').map(v => +v.trim()).filter(v => !isNaN(v));
                     setParams({...params, tp_pips_range: vals.length ? vals : null});
                   }} />
          </label>
          
          {/* Pip Values (Leverage) */}
          <label className="block mb-2">
            <span className="text-sm">Pip Values (Leverage Multiplier):</span>
            <input type="text" placeholder="1.0,2.0,3.0,5.0" 
                   onChange={e => {
                     const vals = e.target.value.split(',').map(v => +v.trim()).filter(v => !isNaN(v));
                     setParams({...params, pip_values: vals.length ? vals : null});
                   }} />
            <span className="text-xs text-gray-500">Higher = more aggressive</span>
          </label>
          
          {/* Filters */}
          <label className="block mb-2">
            <span className="text-sm">Minimum Win Rate (0-1):</span>
            <input type="number" step="0.05" min="0" max="1" value={params.min_win_rate}
                   onChange={e => setParams({...params, min_win_rate: +e.target.value})} />
          </label>
          
          <label className="block mb-2">
            <span className="text-sm">Max Drawdown %:</span>
            <input type="number" step="5" min="0" max="100" placeholder="30"
                   onChange={e => setParams({...params, max_drawdown_pct: e.target.value ? +e.target.value : null})} />
          </label>
        </div>
      )}
      
      <button onClick={() => startOptimization(params)} className="btn-primary mt-4">
        START OPTIMIZATION
      </button>
    </div>
  );
}
```

---

### 3. Progressive Disclosure UI (Best UX)

Show parameters progressively based on expertise level:

```typescript
export function SmartOptimizationForm() {
  const [expertise, setExpertise] = useState<'beginner' | 'intermediate' | 'expert'>('beginner');
  
  return (
    <div>
      {/* Expertise Level Selector */}
      <div className="mb-6">
        <label>Experience Level:</label>
        <div className="flex gap-2">
          <button 
            className={expertise === 'beginner' ? 'active' : ''}
            onClick={() => setExpertise('beginner')}
          >
            🎯 Beginner
          </button>
          <button 
            className={expertise === 'intermediate' ? 'active' : ''}
            onClick={() => setExpertise('intermediate')}
          >
            ⚙️ Intermediate
          </button>
          <button 
            className={expertise === 'expert' ? 'active' : ''}
            onClick={() => setExpertise('expert')}
          >
            🔬 Expert
          </button>
        </div>
      </div>
      
      {/* Beginner: Only basics */}
      {expertise === 'beginner' && <BeginnerForm />}
      
      {/* Intermediate: + TP/SL + Filters */}
      {expertise === 'intermediate' && <IntermediateForm />}
      
      {/* Expert: All parameters */}
      {expertise === 'expert' && <ExpertForm />}
    </div>
  );
}
```

---

### 4. Preset Strategies (User-Friendly)

Offer pre-configured optimization profiles:

```typescript
const PRESETS = {
  conservative: {
    name: "Conservative (High Win Rate)",
    description: "Focus on consistent wins with low drawdown",
    params: {
      mode: 'medium',
      tp_sl_strategy: 'atr',
      atr_sl_multipliers: [2.0, 2.5, 3.0],
      atr_tp_multipliers: [4.0, 5.0, 6.0],
      pip_values: [1.0, 1.5, 2.0],
      min_win_rate: 0.50,
      max_drawdown_pct: 20
    }
  },
  aggressive: {
    name: "Aggressive (Max Profit)",
    description: "High leverage optimization for maximum returns",
    params: {
      mode: 'full',
      tp_sl_strategy: 'both',
      pip_values: [2.0, 3.0, 5.0, 7.5, 10.0],
      min_win_rate: 0.40,
      max_drawdown_pct: 35
    }
  },
  balanced: {
    name: "Balanced",
    description: "Good risk/reward balance",
    params: {
      mode: 'medium',
      tp_sl_strategy: 'both',
      pip_values: [1.5, 2.0, 2.5, 3.0],
      min_win_rate: 0.45,
      max_drawdown_pct: 25
    }
  }
};

export function PresetSelector({ onSelect }: { onSelect: (params: any) => void }) {
  return (
    <div className="grid grid-cols-3 gap-4">
      {Object.entries(PRESETS).map(([key, preset]) => (
        <div key={key} className="preset-card p-4 border rounded cursor-pointer hover:border-blue-500"
             onClick={() => onSelect(preset.params)}>
          <h3 className="font-semibold">{preset.name}</h3>
          <p className="text-sm text-gray-600">{preset.description}</p>
        </div>
      ))}
    </div>
  );
}
```

---

## Quick Wins for Your UI

### 1. Add Mode Selection (5 min)
```typescript
// Just change the radio buttons to show time estimates
<label>
  <input type="radio" value="quick" checked={mode === 'quick'} />
  Fast (~2 min) - 500 combinations
</label>
<label>
  <input type="radio" value="medium" checked={mode === 'medium'} />
  Medium (~5 min) - 2000 combinations  
</label>
<label>
  <input type="radio" value="full" checked={mode === 'full'} />
  Full (~30 min) - 10000 combinations
</label>
```

### 2. Add Pip Value Slider (10 min)
```typescript
<label>
  Leverage Aggressiveness: {pipValue}x
  <input type="range" min="1" max="10" step="0.5" value={pipValue}
         onChange={e => setPipValue(+e.target.value)} />
  <span className="text-xs">
    {pipValue < 2 ? '🟢 Conservative' : pipValue < 5 ? '🟡 Moderate' : '🔴 Aggressive'}
  </span>
</label>
```

### 3. Add TP/SL Strategy Toggle (5 min)
```typescript
<select value={tpSlStrategy}>
  <option value="both">Smart (Test Both)</option>
  <option value="fixed">Fixed Pips</option>
  <option value="atr">Dynamic (ATR-based)</option>
</select>
```

---

## Testing

### 1. Test Basic Request (No Changes)
```bash
curl -X POST https://optimize-api-6ovej2yaoa-uc.a.run.app/optimize \
  -H "Content-Type: application/json" \
  -d '{
    "instrument": "GOLD",
    "timeframe": "M5",
    "initial_capital": 10000,
    "position_size": 0.1,
    "mode": "quick"
  }'
```

### 2. Test Advanced Request
```bash
curl -X POST https://optimize-api-6ovej2yaoa-uc.a.run.app/optimize \
  -H "Content-Type: application/json" \
  -d '{
    "instrument": "GOLD",
    "timeframe": "M5",
    "initial_capital": 10000,
    "position_size": 0.1,
    "mode": "medium",
    "pip_values": [1.5, 2.0, 2.5, 3.0],
    "tp_sl_strategy": "atr",
    "min_win_rate": 0.45
  }'
```

---

## Summary

✅ **Production Ready** - APIs deployed and tested  
✅ **Backward compatible** - Existing UI works without changes  
✅ **Progressive enhancement** - Add features incrementally  
✅ **User-friendly** - Presets + expertise levels  
✅ **Flexible** - From simple to expert control  

**Recommendation**: Start with basic mode selection and pip value slider, add advanced options later based on user feedback.

---

## Quick Reference for Lovable

### 🔗 API Endpoints

| Service | URL | Purpose |
|---------|-----|---------|
| Optimization API | `https://optimize-api-6ovej2yaoa-uc.a.run.app/optimize` | Run strategy backtests |
| Worker Health | `https://optimizer-worker-6ovej2yaoa-uc.a.run.app/health` | Check worker status |
| Scheduler Status | `https://scheduler-control-6ovej2yaoa-uc.a.run.app/scheduler/status` | Check auto-update status |
| Enable Scheduler | `https://scheduler-control-6ovej2yaoa-uc.a.run.app/scheduler/enable` | Enable data sync |
| Disable Scheduler | `https://scheduler-control-6ovej2yaoa-uc.a.run.app/scheduler/disable` | Disable data sync |

### 📊 Supported Instruments

**Forex**: EURUSD, EURGBP, GBPUSD  
**Commodities**: GOLD, SILVER  
**Crypto**: BITCOIN  
**Indices**: US30, NASDAQ

### ⏱️ Timeframes

- **M5** - 5 minutes (available for GOLD, BITCOIN)
- **M15** - 15 minutes (available for all instruments)
- **H1** - 1 hour (coming soon)

### 🎯 Optimization Modes

- `quick` - ~2 minutes, 500 combinations
- `medium` - ~5 minutes, 2000 combinations
- `full` - ~30 minutes, 10000+ combinations

### 🔧 Minimum Request (5 required fields)

```json
{
  "instrument": "GOLD",
  "timeframe": "M5",
  "initial_capital": 10000,
  "position_size": 0.1,
  "mode": "quick"
}
```

### 🚀 Advanced Parameters (20+ optional fields)

See [API_CUSTOMIZATION_GUIDE.md](./API_CUSTOMIZATION_GUIDE.md) for complete parameter documentation.

### 💾 Response Format

```json
{
  "status": "queued",
  "run_id": "uuid-here",
  "status_url": "https://optimize-api-6ovej2yaoa-uc.a.run.app/status/uuid-here",
  "estimated_time": "~2 minutes"
}
```

Poll the `status_url` to get results when optimization completes.

### 🔐 Authentication

**Current**: No authentication required (APIs are public)  
**Future**: Can add API keys or OAuth if needed

### 📚 Additional Documentation

- [API_CUSTOMIZATION_GUIDE.md](./API_CUSTOMIZATION_GUIDE.md) - All 20+ parameters explained
- [UI_CONTROL_API.md](./UI_CONTROL_API.md) - Complete API reference
- [DEPLOYMENT_COMPLETE.md](./DEPLOYMENT_COMPLETE.md) - Full system architecture
- [FOLDER_STRUCTURE.md](../FOLDER_STRUCTURE.md) - Project organization

---

**Last Updated**: March 5, 2026  
**Backend Version**: v2.0 (Enhanced API with 12 instruments)  
**Status**: ✅ Production Ready

