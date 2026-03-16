# Standalone OrderManager Architecture

## Problem: Current Design Limitations

**Current State:**
- OrderManager is tightly coupled to trading bot
- Only manages positions from bot trades
- Manual trades are NOT managed
- Separate bot needed for each epic (GOLD, EURUSD, etc.)
- Can't share trailing logic across bots

**User's Valid Concern:**
> "Should OrderManager be separate? We might do manual trades too. Based on active orders, we can establish WebSocket for the epic."

## 🎯 Recommended: Standalone OrderManager Service

### Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│         Standalone OrderManager Service                  │
│  (Runs independently, manages ALL positions)            │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  1. Poll Capital.com API every 10s for ALL positions    │
│  2. Subscribe to WebSocket quotes for active epics      │
│  3. Apply trailing stops to ALL positions (bot+manual)  │
│  4. Auto-discover new positions and epics               │
│                                                           │
└───────────────┬─────────────────────────────────────────┘
                │
                ├──> Manages: Bot Trades (GOLD M5)
                ├──> Manages: Bot Trades (EURUSD M15)
                ├──> Manages: Manual Trades (Any Epic)
                └──> Manages: Trades from Other Bots
```

### Key Benefits

1. **Universal Coverage**: Manages ALL positions regardless of source
2. **Manual Trade Support**: Your manual trades get same trailing stops
3. **Multi-Epic**: Automatically handles any epic with open positions
4. **Separation of Concerns**: Bot focuses on signals, OrderManager focuses on risk
5. **Always Running**: Even when bot offline, positions still managed

### Implementation Design

#### `scripts/standalone_order_manager.py`

```python
"""
Standalone Order Manager Service
Manages trailing stops for ALL Capital.com positions (bot + manual trades)
"""

class StandaloneOrderManager:
    def __init__(self, config: TrailingConfig, capital_rest: CapitalRestClient):
        self.config = config
        self.capital = capital_rest
        
        # Track all positions across all epics
        self.positions: Dict[str, PositionState] = {}
        
        # WebSocket clients per epic (created dynamically)
        self.ws_clients: Dict[str, CapitalWebSocketClient] = {}
        
        # Latest ATR per epic (fetched periodically)
        self.epic_atr: Dict[str, float] = {}
    
    async def run(self):
        """Main loop: Discover positions, manage trailing stops"""
        while True:
            # 1. Discover all open positions
            await self.discover_positions()
            
            # 2. Ensure WebSocket subscriptions for active epics
            await self.manage_subscriptions()
            
            # 3. Update ATR for each epic
            await self.update_atr_values()
            
            await asyncio.sleep(10)  # Poll every 10 seconds
    
    async def discover_positions(self):
        """Poll API for all open positions and register new ones"""
        positions = self.capital.get_open_positions()
        
        api_deal_ids = set()
        for pos in positions:
            deal_id = pos['dealId']
            api_deal_ids.add(deal_id)
            
            # Register new positions
            if deal_id not in self.positions:
                self.register_position_from_api(pos)
                logger.info(f"🆕 Discovered new position: {deal_id}")
        
        # Unregister closed positions
        closed = set(self.positions.keys()) - api_deal_ids
        for deal_id in closed:
            self.unregister_position(deal_id)
            logger.info(f"✅ Position closed: {deal_id}")
    
    async def manage_subscriptions(self):
        """Subscribe to live quotes for all active epics"""
        active_epics = {pos.epic for pos in self.positions.values()}
        
        # Unsubscribe from epics with no positions
        for epic in list(self.ws_clients.keys()):
            if epic not in active_epics:
                await self.ws_clients[epic].close()
                del self.ws_clients[epic]
                logger.info(f"🔌 Unsubscribed from {epic}")
        
        # Subscribe to new epics
        for epic in active_epics:
            if epic not in self.ws_clients:
                ws = await self.create_ws_client(epic)
                self.ws_clients[epic] = ws
                logger.info(f"📡 Subscribed to {epic} quotes")
    
    def on_quote(self, epic: str, quote: Dict):
        """Handle live quote for trailing stop updates"""
        if epic not in self.epic_atr:
            return  # ATR not ready yet
        
        current_price = quote['mid']
        current_atr = self.epic_atr[epic]
        
        # Update all positions for this epic
        for pos in self.positions.values():
            if pos.epic == epic:
                self.update_trailing_stop(pos, current_price, current_atr)
```

### Deployment Options

#### **Option 1: Separate Service** (Recommended)
Run as independent process:
```bash
# Terminal 1: Trading Bot
python3 scripts/trading_bot_m5.py

# Terminal 2: Order Manager
python3 scripts/standalone_order_manager.py
```

**Pros:**
- ✅ Survives bot crashes
- ✅ Works with manual trades
- ✅ Can restart bot without affecting position management

**Cons:**
- ❌ Two processes to manage
- ❌ Slightly more complex deployment

#### **Option 2: Integrated (Current)**
OrderManager runs inside bot:
```bash
# Single process
python3 scripts/trading_bot_m5.py  # Includes OrderManager
```

**Pros:**
- ✅ Simple deployment
- ✅ Single process

**Cons:**
- ❌ OrderManager dies when bot crashes
- ❌ No manual trade management
- ❌ Need separate bot per epic

### Migration Path

**Phase 1 (Current):** ✅ OrderManager integrated in bot
- Works for bot-generated trades
- Good for testing/validation

**Phase 2 (Next):** Extract to standalone service
- Refactor OrderManager to discover all positions
- Add dynamic WebSocket subscription
- Deploy as separate process

**Phase 3 (Future):** Advanced features
- Multi-account support
- Web dashboard for monitoring
- Configurable strategies per position/epic

## Recommendation

**For Now (Testing Phase):**
✅ Keep current integrated design - it's simpler and works well for validation

**For Production:**
🎯 Move to standalone service once proven:
1. You're actively trading (bot + manual)
2. Multiple epics need management
3. Want trailing stops even when bot offline

**Your Call:** If you do frequent manual trades NOW, start with standalone. Otherwise, validate with current design first.

## Files to Create for Standalone

```
cloud-function/scripts/
  ├── standalone_order_manager.py      # Main service
  └── order_manager_config.yaml        # Configuration

cloud-function/src/live_trading/
  └── order_manager_service.py         # Core logic (extracted from current)
```

Would you like me to implement the standalone version now, or validate the current integrated design first?
