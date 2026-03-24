"""
Capital.com WebSocket Client

Streams live price data from Capital.com:
- OHLC candles (M5 resolution for GOLD M15 strategy)
- Live quotes (bid/offer prices)
- Automatic keepalive ping every 8 minutes
"""

import asyncio
import json
import logging
from contextlib import suppress
from typing import Callable, Dict, Optional
from datetime import datetime

try:
    import websockets
except ImportError:
    raise ImportError("websockets package required: pip install websockets")

logger = logging.getLogger(__name__)


class CapitalWebSocketClient:
    """
    WebSocket client for Capital.com price streaming
    
    Usage:
        client = CapitalWebSocketClient(cst, security_token)
        await client.connect()
        await client.subscribe_ohlc(['GOLD_EPIC'], resolution='MINUTE_5')
        await client.run()
    """
    
    def __init__(
        self,
        cst: str,
        security_token: str,
        ws_url: str = 'wss://demo-api-streaming-capital.backend-capital.com/connect',
        ping_interval: int = 480  # 8 minutes
    ):
        """
        Initialize WebSocket client
        
        Args:
            cst: CST token from REST session
            security_token: X-SECURITY-TOKEN from REST session
            ws_url: WebSocket endpoint (demo or live)
            ping_interval: Keepalive ping interval in seconds (default 8 min)
        """
        self.cst = cst
        self.security_token = security_token
        self.ws_url = ws_url
        self.ping_interval = ping_interval
        
        self.ws = None
        self.keepalive_task = None
        self.running = False
        
        # Latest price data
        self.latest_quotes: Dict[str, Dict] = {}
        self.latest_candles: Dict[str, Dict] = {}
        
        # Callbacks for real-time processing
        self.on_quote: Optional[Callable] = None
        self.on_candle: Optional[Callable] = None
    
    async def connect(self):
        """Connect to Capital.com WebSocket"""
        try:
            self.ws = await websockets.connect(
                self.ws_url,
                ping_interval=None,  # We handle our own pings
                close_timeout=5
            )
            self.running = True
            self.keepalive_task = asyncio.create_task(self._keepalive())
            logger.info(f"✅ Connected to Capital.com WebSocket: {self.ws_url}")
        except Exception as e:
            logger.error(f"❌ WebSocket connection failed: {e}")
            raise
    
    async def _keepalive(self):
        """Send keepalive ping to prevent 10-minute timeout"""
        while self.running:
            try:
                await asyncio.sleep(self.ping_interval)
                await self._send({
                    'destination': 'ping',
                    'correlationId': f'ping-{datetime.now().timestamp()}',
                    'cst': self.cst,
                    'securityToken': self.security_token
                })
                logger.debug("💓 Keepalive ping sent")
            except Exception as e:
                logger.error(f"❌ Keepalive ping failed: {e}")
                break
    
    async def _send(self, message: dict):
        """Send message to WebSocket"""
        if self.ws:
            await self.ws.send(json.dumps(message))
        else:
            logger.warning("⚠️ WebSocket not connected, cannot send message")
    
    async def subscribe_quotes(self, epics: list[str]):
        """
        Subscribe to live bid/offer quotes
        
        Args:
            epics: List of instrument epic codes (e.g., ['CS.D.CFDGOLD.CFD.IP'])
        """
        await self._send({
            'destination': 'marketData.subscribe',
            'correlationId': 'quotes-sub',
            'cst': self.cst,
            'securityToken': self.security_token,
            'payload': {'epics': epics}
        })
        logger.info(f"📊 Subscribed to live quotes: {epics}")
    
    async def subscribe_ohlc(
        self,
        epics: list[str],
        resolution: str = 'MINUTE_5',
        bar_type: str = 'classic'
    ):
        """
        Subscribe to OHLC candle stream
        
        Args:
            epics: List of instrument epic codes
            resolution: Candle resolution (MINUTE_5, MINUTE_15, HOUR, etc.)
            bar_type: 'classic' or 'heikin_ashi'
        """
        await self._send({
            'destination': 'OHLCMarketData.subscribe',
            'correlationId': 'ohlc-sub',
            'cst': self.cst,
            'securityToken': self.security_token,
            'payload': {
                'epics': epics,
                'resolutions': [resolution],
                'type': bar_type
            }
        })
        logger.info(f"📊 Subscribed to {resolution} OHLC candles: {epics}")
    
    async def unsubscribe_quotes(self, epics: list[str]):
        """Unsubscribe from live quotes"""
        await self._send({
            'destination': 'marketData.unsubscribe',
            'correlationId': 'quotes-unsub',
            'cst': self.cst,
            'securityToken': self.security_token,
            'payload': {'epics': epics}
        })
        logger.info(f"📊 Unsubscribed from quotes: {epics}")
    
    async def _handle_message(self, raw: str):
        """Process incoming WebSocket message"""
        try:
            msg = json.loads(raw)
            destination = msg.get('destination')
            payload = msg.get('payload', {})
            
            if destination == 'quote':
                # Live bid/offer quote
                epic = payload.get('epic')
                bid = payload.get('bid')
                offer = payload.get('ofr')
                timestamp = payload.get('timestamp')
                
                quote_data = {
                    'epic': epic,
                    'bid': bid,
                    'offer': offer,
                    'mid': (bid + offer) / 2 if bid and offer else None,
                    'spread': offer - bid if bid and offer else None,
                    'timestamp': timestamp,
                    'time': datetime.fromtimestamp(timestamp / 1000) if timestamp else None
                }
                
                self.latest_quotes[epic] = quote_data
                logger.debug(f"💱 {epic}: bid={bid} offer={offer} mid={quote_data['mid']:.2f}")
                
                # Call user callback if set
                if self.on_quote:
                    await self.on_quote(quote_data)
            
            elif destination == 'ohlc.event':
                # OHLC candle update
                epic = payload.get('epic')
                candle_data = {
                    'epic': epic,
                    'resolution': payload.get('resolution'),
                    'open': payload.get('o'),
                    'high': payload.get('h'),
                    'low': payload.get('l'),
                    'close': payload.get('c'),
                    'price_type': payload.get('priceType'),  # BID or ASK
                    'timestamp': payload.get('t'),
                    'time': datetime.fromtimestamp(payload.get('t') / 1000) if payload.get('t') else None
                }
                
                self.latest_candles[epic] = candle_data
                logger.debug(
                    f"🕯️ {epic} {candle_data['resolution']} [{candle_data['price_type']}]: "
                    f"O={candle_data['open']} H={candle_data['high']} "
                    f"L={candle_data['low']} C={candle_data['close']}"
                )
                
                # Capital.com sends both BID and ASK/OFR candles — only process the offer
                # (ASK/OFR = the price you pay to BUY, consistent with entry/exit levels)
                # Use allowlist rather than denylist: Capital.com may use 'OFR' not 'ASK'
                price_type = candle_data.get('price_type', '')
                if price_type not in ('ASK', 'OFR'):
                    logger.debug(f"⏭️ Skipping {price_type} candle for {epic}")
                    return

                # Call user callback if set
                if self.on_candle:
                    await self.on_candle(candle_data)
            
            elif destination == 'ping':
                logger.debug("💓 Ping acknowledged")
            
            else:
                # Control messages, confirmations, errors
                logger.info(f"📩 {destination}: {msg}")
        
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse message: {e}")
        except Exception as e:
            logger.error(f"❌ Error handling message: {e}")
    
    async def run(self):
        """
        Main message loop - processes incoming WebSocket messages
        Call this after connecting and subscribing
        """
        try:
            logger.info("🚀 WebSocket message loop started")
            async for raw in self.ws:
                await self._handle_message(raw)
        except asyncio.CancelledError:
            logger.info("⏸️ WebSocket loop cancelled")
        except Exception as e:
            logger.error(f"❌ WebSocket error: {e}")
        finally:
            await self.close()
    
    async def close(self):
        """Gracefully close WebSocket connection"""
        self.running = False
        
        # Cancel keepalive task
        if self.keepalive_task:
            self.keepalive_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.keepalive_task
        
        # Close WebSocket
        if self.ws:
            await self.ws.close()
            logger.info("👋 WebSocket connection closed")
    
    def get_latest_quote(self, epic: str) -> Optional[Dict]:
        """Get latest quote for an instrument"""
        return self.latest_quotes.get(epic)
    
    def get_latest_candle(self, epic: str) -> Optional[Dict]:
        """Get latest candle for an instrument"""
        return self.latest_candles.get(epic)


# Example usage for testing
if __name__ == '__main__':
    async def main():
        # These would come from your REST session
        cst = "YOUR_CST_TOKEN"
        security_token = "YOUR_X_SECURITY_TOKEN"
        gold_epic = "CS.D.CFDGOLD.CFD.IP"  # Discover this via REST API
        
        # Create client
        client = CapitalWebSocketClient(cst, security_token)
        
        # Optional: Set callbacks for real-time processing
        async def handle_quote(quote):
            print(f"📊 Quote: {quote['epic']} @ {quote['mid']:.2f}")
        
        async def handle_candle(candle):
            print(f"🕯️ Candle: {candle['epic']} C={candle['close']:.2f}")
        
        client.on_quote = handle_quote
        client.on_candle = handle_candle
        
        # Connect and subscribe
        await client.connect()
        await client.subscribe_quotes([gold_epic])
        await client.subscribe_ohlc([gold_epic], resolution='MINUTE_5')
        
        # Run message loop
        await client.run()
    
    # Run with: python -m src.live_trading.capital_websocket
    asyncio.run(main())
