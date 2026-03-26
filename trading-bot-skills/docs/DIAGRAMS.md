# Architecture Diagram

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      Trading Orchestrator                        │
│                    (Central Coordinator)                         │
└────┬────────────────────────────────────────────────────────┬────┘
     │                                                        │
     ├─ Start/Stop Bot                                       │
     ├─ Event Loop (WebSocket, Timers)                       │
     ├─ Error Handling                                       │
     └─ Metrics Tracking                                     │
                                                             │
     ┌───────────────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────────────────────────┐
│                          Skills Layer                            │
└─────────────────────────────────────────────────────────────────┘

┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│ Market Data │──▶│  Analysis   │──▶│    Risk     │──▶│  Execution  │
└─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘
      │                  │                  │                  │
      │ Candles          │ Signal           │ Validated        │ Deal ID
      │                  │                  │ Signal           │
      ▼                  ▼                  ▼                  ▼
┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│  Storage    │   │ Monitoring  │   │  Alerting   │   │  Reporting  │
└─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘
      │                  │                  │                  │
   Firestore           P&L              Telegram           Charts
```

## Data Flow: Trading Cycle

### 1. Market Data Flow
```
Capital.com WebSocket
        │
        ├─ OHLC Tick
        │
        ▼
Market Data Skill
        │
        ├─ Parse & Validate
        ├─ Buffer (last 100 candles)
        │
        ▼
Context.candle_history = [...]
```

### 2. Analysis Flow
```
Context.candle_history
        │
        ▼
Analysis Skill
        │
        ├─ Calculate Indicators
        │   ├─ Supertrend 2.0
        │   ├─ SMA 25/30
        │   ├─ Bollinger Bands 2.0
        │   └─ VWAP
        │
        ├─ Detect Crossovers
        ├─ Check Entry Conditions
        │
        ▼
Context.signal = 'BUY' | 'SELL' | None
Context.indicators = {...}
```

### 3. Risk Flow
```
Context.signal = 'BUY'
        │
        ▼
Risk Skill
        │
        ├─ Check Cooldown
        │   ├─ Last direction = 'BUY'?
        │   ├─ Last close reason = 'SL_HIT'?
        │   ├─ Time since close < 15min?
        │   └─ BLOCK or ALLOW
        │
        ├─ Check Position Limit
        ├─ Check Drawdown
        ├─ Calculate Position Size
        │
        ▼
Context.is_allowed = True/False
Context.risk_reason = "..."
Context.position_size = 0.5
```

### 4. Execution Flow
```
Context.is_allowed = True
        │
        ▼
Execution Skill
        │
        ├─ Build Order Request
        │   ├─ Direction: BUY
        │   ├─ Size: 0.5
        │   ├─ SL: 20 pips
        │   └─ TP: 40 pips
        │
        ├─ Call Capital.com API
        │   POST /positions
        │
        ▼
Context.deal_id = "DEAL123"
Context.current_position = {...}
```

### 5. Storage Flow
```
Context.deal_id = "DEAL123"
        │
        ▼
Storage Skill
        │
        ├─ Create Firestore Document
        │   {
        │     deal_id: "DEAL123"
        │     direction: "BUY"
        │     entry_price: 2650.5
        │     sl: 2630.5
        │     tp: 2690.5
        │     timestamp: "2024-01-15T10:30:00"
        │     status: "OPEN"
        │   }
        │
        ▼
Firestore: active_positions/DEAL123
```

### 6. Monitoring & Alerting
```
Context.deal_id = "DEAL123"
        │
        ├─────────────────────┬────────────────────┐
        │                     │                    │
        ▼                     ▼                    ▼
Monitoring Skill      Alerting Skill      Reporting Skill
        │                     │                    │
    Update P&L          Send Telegram       Update Charts
    Track Win Rate      Notification        Generate Report
```

## Position Close Flow

### When SL/TP Hits
```
Capital.com (Auto-Close)
        │
        ├─ SL Hit at 2630.5
        │
        ▼
Bot Detects Close (WebSocket event)
        │
        ▼
Orchestrator.on_position_closed()
        │
        ├─ Update Risk Skill
        │   └─ last_closed_position = {
        │         direction: 'BUY',
        │         close_reason: 'SL_HIT',
        │         close_time: now()
        │       }
        │
        ├─ Update Storage (Firestore)
        │   └─ FINALLY block (always executes)
        │       └─ close_position(deal_id, 'SL_HIT')
        │
        ├─ Update Monitoring
        │   └─ pnl -= 20.0
        │
        └─ Send Alert
            └─ "🔴 GOLD BUY closed at SL: -$20"
```

## Cooldown Logic Diagram

```
Trade 1: BUY @ 17:55
        │
        ▼
SL Hit @ 18:01 (-$20)
        │
        ├─ Risk Skill Updates:
        │   last_closed_position = {
        │     direction: 'BUY',
        │     close_reason: 'SL_HIT',
        │     close_time: 18:01
        │   }
        │
        ▼
New Candle @ 18:05
        │
        ├─ Signal: BUY (bearish conditions persist)
        │
        ▼
Risk Skill Check:
        │
        ├─ current_signal = 'BUY'
        ├─ last_direction = 'BUY' ✓ SAME
        ├─ last_close_reason = 'SL_HIT'
        ├─ minutes_since_close = 4min
        ├─ 4min < 15min ✓ BLOCKED
        │
        ▼
Context.is_allowed = False
Context.risk_reason = "🚫 SL cooldown: 4.0m < 15m"
        │
        ▼
No Trade Executed ✅
```

### Opposite Direction Allowed
```
Trade 1: BUY @ 17:55
        │
        ▼
SL Hit @ 18:01
        │
        ▼
New Candle @ 18:05
        │
        ├─ Signal: SELL (trend reversed)
        │
        ▼
Risk Skill Check:
        │
        ├─ current_signal = 'SELL'
        ├─ last_direction = 'BUY' 
        ├─ 'SELL' != 'BUY' ✓ DIFFERENT
        │
        ▼
Context.is_allowed = True
Context.risk_reason = "Different direction - cooldown bypassed"
        │
        ▼
Trade Executed ✅
```

## Error Handling Flow

```
Orchestrator.on_candle()
        │
        ├─ Execute Skills in Sequence
        │
        ▼
   try:
       market_data_skill.execute()
       analysis_skill.execute()
       risk_skill.execute()
       execution_skill.execute()
       storage_skill.execute()
   except Exception as e:
       │
       ├─ Log Error
       ├─ Add to context.errors
       ├─ Send Alert (critical errors only)
       └─ Continue (don't crash bot)
   finally:
       │
       └─ ALWAYS close Firestore position
           └─ try:
                   storage_skill.close_position()
               except Exception:
                   log_error()  # Don't rethrow
```

## Testing Architecture

```
┌─────────────────────────────────────┐
│         Unit Tests                  │
├─────────────────────────────────────┤
│  test_market_data_skill.py          │
│  test_analysis_skill.py             │
│  test_risk_skill.py         ✅      │
│  test_execution_skill.py            │
│  test_storage_skill.py              │
└─────────────────────────────────────┘
            │
            │ Mock Dependencies
            │
            ▼
┌─────────────────────────────────────┐
│      Integration Tests              │
├─────────────────────────────────────┤
│  test_full_trading_flow.py          │
│  test_position_close_flow.py        │
│  test_cooldown_integration.py       │
└─────────────────────────────────────┘
            │
            │ Real Data, Mock Broker
            │
            ▼
┌─────────────────────────────────────┐
│         Backtest Tests              │
├─────────────────────────────────────┤
│  Validate against baseline          │
│  Compare metrics (Sharpe, Win Rate) │
│  Test on 149k bars historical data  │
└─────────────────────────────────────┘
            │
            │ Historical Data
            │
            ▼
┌─────────────────────────────────────┐
│       Paper Trading Tests           │
├─────────────────────────────────────┤
│  Demo account (1 week)              │
│  Compare with prod bot              │
│  Validate trade decisions match     │
└─────────────────────────────────────┘
            │
            │ Real Broker API
            │
            ▼
┌─────────────────────────────────────┐
│       Production Deploy             │
└─────────────────────────────────────┘
```

## Configuration Flow

```
config/trading_config.yaml
        │
        ├─ market_data:
        │     instrument: GOLD
        │     timeframe: M5
        │
        ├─ risk:
        │     sl_cooldown_minutes: 15
        │     tp_cooldown_minutes: 5
        │
        └─ execution:
              sl_pips: 20
              tp_pips: 40
        │
        ▼
Orchestrator.__init__(config)
        │
        ├─ Create Skills
        │   ├─ MarketDataSkill(config['market_data'])
        │   ├─ RiskSkill(config['risk'])
        │   └─ ExecutionSkill(config['execution'])
        │
        └─ Register Skills
            └─ orchestrator.register_skill('risk', risk_skill)
```

## Deployment Architecture

```
┌─────────────────────────────────────────────────────┐
│         Production Server                           │
│         root@204.168.191.150                       │
├─────────────────────────────────────────────────────┤
│                                                     │
│  /opt/trading-bot/                (OLD BOT)        │
│    ├── scripts/trading_bot.py                      │
│    └── venv/                                        │
│                                                     │
│  /opt/trading-bot-skills/         (NEW BOT)        │
│    ├── orchestrator/main.py                        │
│    ├── skills/                                      │
│    ├── config/trading_config.yaml                  │
│    └── venv/                                        │
│                                                     │
└─────────────────────────────────────────────────────┘
        │
        ├─ WebSocket ──▶ Capital.com API
        │
        ├─ Firestore ──▶ Google Cloud
        │
        └─ Telegram ──▶ Notifications
```

This demonstrates the complete architecture from data ingestion through signal generation, risk validation, order execution, and monitoring. Each skill is independent and testable, communicating through the shared Context object.
