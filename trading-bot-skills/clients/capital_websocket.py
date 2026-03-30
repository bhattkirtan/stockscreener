"""
Capital.com WebSocket Client

Streams live price data from Capital.com:
- OHLC candles (M5 resolution)
- Live quotes (bid/offer prices)
- Automatic keepalive ping every 8 minutes
- Auto-reconnect with exponential backoff
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

# Capital.com uses one streaming URL for both demo and live accounts
WS_URL = 'wss://api-streaming-capital.backend-capital.com/connect'


class CapitalWebSocketClient:
    """
    WebSocket client for Capital.com price streaming.

    Usage:
        tokens = capital_api.get_tokens()
        client = CapitalWebSocketClient(tokens['CST'], tokens['X-SECURITY-TOKEN'])
        client.on_candle = my_candle_handler   # async callable
        await client.connect()
        await client.subscribe_ohlc(['CS.D.CFDGOLD.CFD.IP'], resolution='MINUTE_5')
        await client.run()
    """

    def __init__(
        self,
        cst: str,
        security_token: str,
        ws_url: str = WS_URL,
        ping_interval: int = 480,  # 8 minutes — Capital.com times out at 10 min
    ):
        self.cst = cst
        self.security_token = security_token
        self.ws_url = ws_url
        self.ping_interval = ping_interval

        self.ws = None
        self.keepalive_task = None
        self.running = False

        # Latest data cache
        self.latest_quotes: Dict[str, Dict] = {}
        self.latest_candles: Dict[str, Dict] = {}

        # Callbacks — set these before calling run()
        self.on_quote: Optional[Callable] = None           # async fn(quote_data: dict)
        self.on_candle: Optional[Callable] = None          # async fn(candle_data: dict)
        self.on_position_update: Optional[Callable] = None # async fn(update: dict)

    # ── Connection ────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Open WebSocket connection to Capital.com."""
        try:
            self.ws = await websockets.connect(
                self.ws_url,
                ping_interval=None,  # We handle our own keepalive pings
                close_timeout=5,
            )
            self.running = True
            self.keepalive_task = asyncio.create_task(self._keepalive())
            logger.info(f"✅ Connected to Capital.com WebSocket: {self.ws_url}")
        except Exception as e:
            logger.error(f"❌ WebSocket connection failed: {e}")
            raise

    async def close(self) -> None:
        """Gracefully close the WebSocket connection."""
        self.running = False

        if self.keepalive_task:
            self.keepalive_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.keepalive_task

        if self.ws:
            await self.ws.close()
            logger.info("👋 WebSocket connection closed")

    # ── Subscriptions ─────────────────────────────────────────────────────────

    async def subscribe_quotes(self, epics: list) -> None:
        """Subscribe to live bid/offer quotes for the given epics."""
        await self._send({
            'destination': 'marketData.subscribe',
            'correlationId': 'quotes-sub',
            'cst': self.cst,
            'securityToken': self.security_token,
            'payload': {'epics': epics},
        })
        logger.info(f"📊 Subscribed to live quotes: {epics}")

    async def subscribe_ohlc(
        self,
        epics: list,
        resolution: str = 'MINUTE_5',
        bar_type: str = 'classic',
    ) -> None:
        """
        Subscribe to OHLC candle stream.

        Args:
            epics: List of instrument epics, e.g. ['CS.D.CFDGOLD.CFD.IP']
            resolution: MINUTE_5 | MINUTE_15 | HOUR | DAY
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
                'type': bar_type,
            },
        })
        logger.info(f"📊 Subscribed to {resolution} OHLC candles: {epics}")

    async def subscribe_trades(self) -> None:
        """
        Subscribe to trade/position lifecycle events.
        Fires whenever a position is opened, updated, or closed (SL/TP/manual).
        """
        await self._send({
            'destination': 'trade.subscribe',
            'correlationId': 'trade-sub',
            'cst': self.cst,
            'securityToken': self.security_token,
            'payload': {},
        })
        logger.info("📋 Subscribed to trade position updates")

    async def unsubscribe_quotes(self, epics: list) -> None:
        """Unsubscribe from live quotes."""
        await self._send({
            'destination': 'marketData.unsubscribe',
            'correlationId': 'quotes-unsub',
            'cst': self.cst,
            'securityToken': self.security_token,
            'payload': {'epics': epics},
        })

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """
        Main message loop — processes incoming WebSocket messages.
        Blocks until connection drops or close() is called.
        """
        try:
            logger.info("🚀 WebSocket message loop started")
            async for raw in self.ws:
                await self._handle_message(raw)
        except asyncio.CancelledError:
            logger.info("⏸️ WebSocket loop cancelled")
        except Exception as e:
            logger.error(f"❌ WebSocket error: {e}")
            raise
        finally:
            await self.close()

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _send(self, message: dict) -> None:
        if self.ws:
            await self.ws.send(json.dumps(message))
        else:
            logger.warning("⚠️ WebSocket not connected, cannot send message")

    async def _keepalive(self) -> None:
        """Send ping every ping_interval seconds to prevent 10-minute timeout."""
        while self.running:
            try:
                await asyncio.sleep(self.ping_interval)
                await self._send({
                    'destination': 'ping',
                    'correlationId': f'ping-{datetime.now().timestamp()}',
                    'cst': self.cst,
                    'securityToken': self.security_token,
                })
                logger.debug("💓 Keepalive ping sent")
            except Exception as e:
                logger.error(f"❌ Keepalive ping failed: {e}")
                break

    async def _handle_message(self, raw: str) -> None:
        """Dispatch incoming WebSocket message to the right handler."""
        try:
            msg = json.loads(raw)
            destination = msg.get('destination')
            payload = msg.get('payload', {})

            if destination == 'quote':
                await self._handle_quote(payload)

            elif destination == 'ohlc.event':
                await self._handle_ohlc(payload)

            elif destination in ('trade.event', 'opu'):
                await self._handle_trade_update(payload)

            elif destination == 'ping':
                logger.debug("💓 Ping acknowledged")

            else:
                # Subscription confirmations, errors, etc.
                logger.info(f"📩 {destination}: {msg}")

        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse message: {e}")
        except Exception as e:
            logger.error(f"❌ Error handling message: {e}")

    async def _handle_quote(self, payload: dict) -> None:
        """Handle live bid/offer quote."""
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
            'time': datetime.fromtimestamp(timestamp / 1000) if timestamp else None,
        }

        self.latest_quotes[epic] = quote_data
        logger.debug(f"💱 {epic}: bid={bid} offer={offer}")

        if self.on_quote:
            await self.on_quote(quote_data)

    async def _handle_ohlc(self, payload: dict) -> None:
        """
        Handle OHLC candle update.

        Capital.com sends both BID and ASK/OFR candles for each bar.
        Only the ASK/OFR candle is passed to on_candle — that's the price
        you pay to BUY, consistent with entry/exit SL/TP levels.
        """
        epic = payload.get('epic')
        t = payload.get('t')

        candle_data = {
            'epic': epic,
            'resolution': payload.get('resolution'),
            'open': payload.get('o'),
            'high': payload.get('h'),
            'low': payload.get('l'),
            'close': payload.get('c'),
            'price_type': payload.get('priceType'),
            'timestamp': t,
            'time': datetime.fromtimestamp(t / 1000) if t else None,
        }

        self.latest_candles[epic] = candle_data

        logger.info(
            f"🕯️ {epic} {candle_data['resolution']} [{candle_data['price_type']}]: "
            f"O={candle_data['open']} H={candle_data['high']} "
            f"L={candle_data['low']} C={candle_data['close']}"
        )

        # Skip BID candles — only fire callback on ASK/OFR
        price_type = (candle_data.get('price_type') or '').upper()
        if price_type not in ('ASK', 'OFR'):
            logger.debug(f"⏭️ Skipping {price_type} candle for {epic}")
            return

        if self.on_candle:
            await self.on_candle(candle_data)

    async def _handle_trade_update(self, payload: dict) -> None:
        """
        Handle position lifecycle events from Capital.com.

        Capital.com sends these via 'trade.event' / 'opu' destination.
        Status values:
          OPEN        — position just opened
          UPDATED     — SL/TP modified
          CLOSED      — position closed (SL, TP, or manual)
          DELETED     — order cancelled

        Close reasons (payload['reason']):
          STOP_CLOSE  — stop loss hit
          LIMIT_CLOSE — take profit hit
          MANUAL      — manually closed / reverse signal
        """
        status = (payload.get('status') or payload.get('dealStatus') or '').upper()

        deal_id = payload.get('dealId') or payload.get('dealReference', '')
        direction = (payload.get('direction') or '').upper()
        close_price = payload.get('level') or payload.get('closeLevel') or 0.0
        profit = payload.get('profit') or payload.get('pnl') or 0.0
        reason_raw = (payload.get('reason') or payload.get('dealStatus') or '').upper()

        # Map Capital.com reason → internal close_reason
        reason_map = {
            'STOP_CLOSE': 'SL_HIT',
            'LIMIT_CLOSE': 'TP_HIT',
            'MANUAL': 'SIGNAL',
        }
        close_reason = reason_map.get(reason_raw, reason_raw or 'UNKNOWN')

        logger.info(
            f"📋 Trade event: deal={deal_id} status={status} "
            f"reason={close_reason} pnl={profit}"
        )

        if status == 'CLOSED' and self.on_position_update:
            update = {
                'deal_id': deal_id,
                'direction': direction,
                'close_price': float(close_price),
                'pnl': float(profit),
                'close_reason': close_reason,
            }
            await self.on_position_update(update)

    # ── Accessors ─────────────────────────────────────────────────────────────

    def get_latest_quote(self, epic: str) -> Optional[Dict]:
        return self.latest_quotes.get(epic)

    def get_latest_candle(self, epic: str) -> Optional[Dict]:
        return self.latest_candles.get(epic)
