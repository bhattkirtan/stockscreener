"""
🎯 Standalone Order Manager Service

Manages trailing stops for ALL Capital.com positions:
- Bot-generated trades
- Manual trades
- Any epic (GOLD, EURUSD, etc.)

Auto-discovers positions every 10s and:
1. Spins up WebSocket for each epic with open positions
2. Subscribes to live price quotes
3. Applies trailing stops (breakeven, progressive, ATR-based)
4. Tears down WebSocket when epic has no more positions

Run independently from trading bot:
    python3 scripts/standalone_order_manager.py
"""

import sys
import os
import asyncio
import logging
import signal
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional, Set
from collections import defaultdict

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.live_trading.config import TradingConfig
from src.live_trading.capital_rest import CapitalRestClient
from src.live_trading.capital_websocket import CapitalWebSocketClient
from src.live_trading.order_manager import OrderManager, TrailingConfig, TrailingStrategy, PositionState
from src.live_trading.historical_data import fetch_historical_candles

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,  # Changed to DEBUG to see position details
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class StandaloneOrderManager:
    """
    Standalone service that manages trailing stops for ALL positions.
    
    Flow:
    1. Poll Capital.com API for all open positions
    2. For each unique epic, spin up WebSocket and subscribe to quotes
    3. Update trailing stops on live price feed
    4. Auto-cleanup WebSockets when epic has no positions
    """
    
    def __init__(self, config: TradingConfig, trailing_config: TrailingConfig):
        self.config = config
        self.trailing_config = trailing_config
        
        # Capital.com REST client
        self.rest_client = CapitalRestClient(config)
        
        # Order manager (core trailing logic)
        self.order_manager = OrderManager(trailing_config, self.rest_client)
        
        # WebSocket clients per epic (created dynamically)
        self.ws_clients: Dict[str, CapitalWebSocketClient] = {}
        
        # Latest ATR per epic
        self.epic_atr: Dict[str, float] = {}
        
        # Authentication tokens
        self.cst: Optional[str] = None
        self.security_token: Optional[str] = None
        
        # Shutdown flag
        self.running = True
        
        logger.info("🎯 Standalone Order Manager initialized")
        logger.info(f"📊 Trailing strategies: {[s.value for s in trailing_config.enabled_strategies]}")
    
    async def authenticate(self):
        """Authenticate with Capital.com"""
        try:
            logger.info("🔐 Authenticating with Capital.com...")
            tokens = self.rest_client.create_session()
            self.cst = tokens['CST']
            self.security_token = tokens['X-SECURITY-TOKEN']
            logger.info("✅ Authentication successful")
        except Exception as e:
            logger.error(f"❌ Authentication failed: {e}")
            raise
    
    async def run(self):
        """Main service loop"""
        try:
            # Authenticate
            await self.authenticate()
            
            # Start background tasks
            tasks = [
                asyncio.create_task(self.discover_positions_loop()),
                asyncio.create_task(self.update_atr_loop()),
            ]
            
            logger.info("🚀 Standalone Order Manager running")
            logger.info("📡 Auto-discovering positions and managing trailing stops...")
            
            # Wait for all tasks
            await asyncio.gather(*tasks)
            
        except asyncio.CancelledError:
            logger.info("🛑 Shutting down...")
        except Exception as e:
            logger.error(f"❌ Service error: {e}", exc_info=True)
            raise
    
    async def discover_positions_loop(self):
        """Continuously discover positions and manage WebSocket subscriptions"""
        while self.running:
            try:
                # Fetch all open positions from Capital.com
                positions = self.rest_client.get_open_positions()
                
                if not positions:
                    logger.debug("No open positions found")
                    # Close all WebSockets if no positions
                    await self.cleanup_all_websockets()
                    await asyncio.sleep(10)
                    continue
                
                # Group positions by epic
                positions_by_epic = defaultdict(list)
                for pos in positions:
                    epic = pos.get('market', {}).get('epic')
                    if epic:
                        positions_by_epic[epic].append(pos)
                
                # Debug: Log raw position structure
                if positions:
                    logger.debug(f"📦 Raw position sample: {positions[0]}")
                
                # Get deal IDs currently managed
                managed_deal_ids = set(self.order_manager.positions.keys())
                
                # Get deal IDs from API (position data is nested under 'position' key)
                api_deal_ids = {p.get('position', {}).get('dealId') for p in positions if p.get('position', {}).get('dealId')}
                
                # Register new positions
                for epic, epic_positions in positions_by_epic.items():
                    for pos in epic_positions:
                        deal_id = pos.get('position', {}).get('dealId')
                        
                        if deal_id and deal_id not in managed_deal_ids:
                            # New position discovered
                            await self.register_position(pos, epic)
                
                # Unregister closed positions
                closed_deal_ids = managed_deal_ids - api_deal_ids
                for deal_id in closed_deal_ids:
                    logger.info(f"✅ Position closed: {deal_id}")
                    self.order_manager.unregister_position(deal_id)
                
                # Manage WebSocket subscriptions based on active epics
                await self.manage_websocket_subscriptions(set(positions_by_epic.keys()))
                
                # Log status
                total_positions = len(api_deal_ids)
                total_epics = len(positions_by_epic)
                logger.info(f"📊 Managing {total_positions} position(s) across {total_epics} epic(s): {list(positions_by_epic.keys())}")
                
            except Exception as e:
                logger.error(f"❌ Position discovery error: {e}")
            
            await asyncio.sleep(5)  # Poll every 5 seconds
    
    async def register_position(self, pos: Dict, epic: str):
        """Register a newly discovered position"""
        try:
            # Position data is nested under 'position' key
            position_data = pos.get('position', {})
            
            deal_id = position_data.get('dealId')
            direction = position_data.get('direction')
            size = float(position_data.get('size', 0))
            entry_price = float(position_data.get('level', 0))
            stop_level = position_data.get('stopLevel')
            profit_level = position_data.get('profitLevel')
            
            # Debug: Log the raw position data
            logger.debug(f"🔍 Position data for {epic}: dealId={deal_id}, direction={direction}, "
                        f"size={size}, entry={entry_price}, stopLevel={stop_level}, profitLevel={profit_level}")
            
            # Skip positions without stop loss
            if not stop_level:
                logger.warning(f"⚠️ Skipping {deal_id} ({epic}) - no stop loss set")
                return
            
            # Register with OrderManager
            self.order_manager.register_position(
                deal_id=deal_id,
                direction=direction,
                entry_price=entry_price,
                stop_loss=float(stop_level),
                take_profit=float(profit_level) if profit_level else None,
                size=size
            )
            
            # Store epic in position state (need to add epic field)
            if deal_id in self.order_manager.positions:
                # Extend PositionState with epic (stored as attribute)
                pos_state = self.order_manager.positions[deal_id]
                pos_state.epic = epic  # Add epic attribute dynamically
            
            logger.info(f"🆕 Discovered: {direction} {size} {epic} @ {entry_price:.2f} (SL: {stop_level}, TP: {profit_level})")
            
        except Exception as e:
            logger.error(f"❌ Failed to register position {deal_id}: {e}")
    
    async def manage_websocket_subscriptions(self, active_epics: Set[str]):
        """Manage WebSocket subscriptions based on active epics"""
        # Unsubscribe from epics with no positions
        for epic in list(self.ws_clients.keys()):
            if epic not in active_epics:
                await self.close_websocket(epic)
        
        # Subscribe to new epics
        for epic in active_epics:
            if epic not in self.ws_clients:
                await self.create_websocket(epic)
    
    async def create_websocket(self, epic: str):
        """Create and start WebSocket for an epic"""
        try:
            logger.info(f"📡 Creating WebSocket for {epic}...")
            
            ws_client = CapitalWebSocketClient(
                cst=self.cst,
                security_token=self.security_token,
                ws_url=self.config.ws_url,
                ping_interval=self.config.ping_interval_seconds
            )
            
            # Set quote callback (must be async for WebSocket client)
            async def on_quote(quote: Dict):
                await self.on_quote(epic, quote)
            
            ws_client.on_quote = on_quote
            
            # Connect
            await ws_client.connect()
            
            # Subscribe to live quotes
            await ws_client.subscribe_quotes([epic])
            
            # Store client and start run loop in background
            self.ws_clients[epic] = ws_client
            asyncio.create_task(self.run_websocket(epic, ws_client))
            
            logger.info(f"✅ WebSocket active for {epic}")
            
        except Exception as e:
            logger.error(f"❌ Failed to create WebSocket for {epic}: {e}")
    
    async def run_websocket(self, epic: str, ws_client: CapitalWebSocketClient):
        """Run WebSocket in background"""
        try:
            await ws_client.run()
        except Exception as e:
            logger.warning(f"⚠️ WebSocket closed for {epic}: {e}")
            if epic in self.ws_clients:
                del self.ws_clients[epic]
    
    async def close_websocket(self, epic: str):
        """Close WebSocket for an epic"""
        try:
            if epic in self.ws_clients:
                logger.info(f"🔌 Closing WebSocket for {epic}")
                await self.ws_clients[epic].close()
                del self.ws_clients[epic]
        except Exception as e:
            logger.warning(f"⚠️ Error closing WebSocket for {epic}: {e}")
    
    async def cleanup_all_websockets(self):
        """Close all WebSockets"""
        for epic in list(self.ws_clients.keys()):
            await self.close_websocket(epic)
    
    async def on_quote(self, epic: str, quote: Dict):
        """Handle live quote for trailing stop updates"""
        try:
            # Check if we have ATR for this epic
            if epic not in self.epic_atr:
                logger.debug(f"⏳ ATR not ready for {epic}, skipping trailing update")
                return
            
            current_price = float(quote.get('mid', 0))
            current_atr = self.epic_atr[epic]
            
            # Update trailing stops for all positions of this epic
            positions_updated = 0
            for deal_id, pos in list(self.order_manager.positions.items()):
                # Check if position belongs to this epic
                if hasattr(pos, 'epic') and pos.epic == epic:
                    updates = self.order_manager.update_trailing_stops(current_price, current_atr)
                    positions_updated += updates
            
            if positions_updated > 0:
                logger.info(f"🔄 {epic}: Updated {positions_updated} trailing stop(s) at {current_price:.2f}")
                
        except Exception as e:
            logger.error(f"❌ Error processing quote for {epic}: {e}")
    
    async def update_atr_loop(self):
        """Periodically fetch ATR for each active epic"""
        while self.running:
            try:
                await asyncio.sleep(30)  # Update ATR every 30 seconds
                
                # Get active epics from managed positions
                active_epics = set()
                for pos in self.order_manager.positions.values():
                    if hasattr(pos, 'epic'):
                        active_epics.add(pos.epic)
                
                # Fetch ATR for each epic
                for epic in active_epics:
                    await self.fetch_atr(epic)
                
            except Exception as e:
                logger.error(f"❌ ATR update error: {e}")
    
    async def fetch_atr(self, epic: str):
        """Fetch latest ATR for an epic"""
        try:
            # Fetch recent candles (M5 timeframe)
            candles = fetch_historical_candles(
                self.rest_client,
                epic,
                resolution='MINUTE_5',
                num_candles=20  # Need 14+ for ATR
            )
            
            if not candles or len(candles) < 14:
                logger.warning(f"⚠️ Insufficient candles for {epic} ATR calculation")
                return
            
            # Convert to DataFrame
            df = pd.DataFrame(candles)
            
            # Calculate ATR (simple implementation)
            df['high_low'] = df['high'] - df['low']
            df['high_close'] = abs(df['high'] - df['close'].shift())
            df['low_close'] = abs(df['low'] - df['close'].shift())
            df['true_range'] = df[['high_low', 'high_close', 'low_close']].max(axis=1)
            atr = df['true_range'].rolling(14).mean().iloc[-1]
            
            # Store ATR
            old_atr = self.epic_atr.get(epic)
            self.epic_atr[epic] = float(atr)
            
            if old_atr != atr:
                logger.info(f"📊 {epic} ATR updated: {atr:.2f}")
            
        except Exception as e:
            logger.error(f"❌ Failed to fetch ATR for {epic}: {e}")
    
    async def stop(self):
        """Stop the service gracefully"""
        logger.info("🛑 Stopping Standalone Order Manager...")
        self.running = False
        await self.cleanup_all_websockets()
        logger.info("✅ Service stopped")


async def main():
    """Main entry point with graceful shutdown"""
    # Load configuration (default to demo mode)
    environment = os.getenv('TRADING_ENVIRONMENT', 'demo')
    config = TradingConfig(environment=environment)
    
    # Trailing stop configuration
    trailing_config = TrailingConfig(
        breakeven_trigger_points=10.0,  # Move to breakeven after +10 points
        breakeven_buffer=2.0,  # SL at entry+2 points
        progressive_step=5.0,  # Trail every +5 points
        progressive_trail_by=3.0,  # Move SL by 3 points
        atr_trailing_multiplier=1.0,  # Trail by 1× ATR
        enabled_strategies=[TrailingStrategy.ALL],
        min_update_points=1.0,  # Min 1 point change to update
        min_update_interval_seconds=5.0,  # Rate limit: 5s
        price_decimals=2  # 2 decimals for most instruments
    )
    
    # Create service
    service = StandaloneOrderManager(config, trailing_config)
    
    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()
    
    def signal_handler(signum, frame):
        logger.info(f"📡 Received signal {signum}, shutting down...")
        asyncio.create_task(service.stop())
        loop.stop()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await service.run()
    except KeyboardInterrupt:
        await service.stop()
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        await service.stop()


if __name__ == "__main__":
    asyncio.run(main())
