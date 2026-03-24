"""
🚀 Live Trading Bot for Capital.com

MODES:
- DEMO (paper trading): Fully automated - generates signals AND places trades
- LIVE (real trading): Signal-only mode - ONLY logs signals, NO automatic orders

GOLD M5 Strategy — rank01 from optimization 2026-03-17:
- Supertrend: period=7, multiplier=2.0
- SMA: Fast=25, Slow=30
- Bollinger Bands: period=20, std=2.0
- Stop Loss: 20 pips (fixed)
- Take Profit: 40 pips (fixed)
- Event Blocking: enabled (15 min before / 15 min after high-impact events)

Performance (backtest 2024-2026): 373.7% return, 14.0% max DD, 0.18 Sharpe
"""

import sys
import os
import asyncio
import logging
import json
import signal
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import deque

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Import live trading components
from src.live_trading.config import TradingConfig
from src.live_trading.capital_websocket import CapitalWebSocketClient
from src.live_trading.signal_publisher import SignalPublisher, SignalBackend
from src.live_trading.bot_status_publisher import BotStatusPublisher, BotStatus
from src.live_trading.position_publisher import PositionPublisher, PositionStatus
from src.live_trading.log_publisher import LogPublisher, FirestoreLogHandler

# Import strategy indicator calculations
from src.core.strategy import SupertrendVWAPStrategy

# Import live trading components  
from src.live_trading.capital_rest import CapitalRestClient

# Import event blocking
from src.data.manual_calendar_adapter import ManualCalendarAdapter
from src.core.event_blocker import EventBlocker

# Setup logging — new timestamped file each run, plus symlink trading_bot.log → latest
_log_dir = os.path.join(os.path.dirname(__file__), '..', 'logs')
os.makedirs(_log_dir, exist_ok=True)
_log_ts = datetime.now().strftime('%Y%m%d_%H%M%S')
_log_file = os.path.join(_log_dir, f'trading_bot_{_log_ts}.log')
_symlink = os.path.join(os.path.dirname(__file__), '..', 'trading_bot.log')
# Update symlink so `tail -f trading_bot.log` always follows the current run
try:
    if os.path.islink(_symlink) or os.path.exists(_symlink):
        os.remove(_symlink)
    os.symlink(os.path.abspath(_log_file), _symlink)
except OSError:
    pass  # non-fatal if symlink can't be created

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(_log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class M5toM15Aggregator:
    """Aggregates M5 candles to M15 bars (3 M5 candles = 1 M15 bar)"""
    
    def __init__(self):
        self.m5_buffer: deque = deque(maxlen=3)  # Buffer for 3 M5 candles
        self.last_m15_time: Optional[datetime] = None
    
    def add_m5_candle(self, candle: Dict) -> Optional[Dict]:
        """
        Add M5 candle to buffer and return completed M15 bar if ready
        
        Args:
            candle: M5 OHLC candle dict with keys: timestamp, open, high, low, close, volume
            
        Returns:
            M15 bar dict if complete, None otherwise
        """
        timestamp = datetime.fromisoformat(candle['timestamp'].replace('Z', '+00:00'))
        
        # Add to buffer
        self.m5_buffer.append(candle)
        
        # Check if we have 3 M5 candles (= 1 M15 bar)
        if len(self.m5_buffer) < 3:
            return None
        
        # Check if timestamps are consecutive (M15 alignment)
        expected_interval = timedelta(minutes=5)
        buffer_list = list(self.m5_buffer)
        
        # Verify timestamps are aligned to M15 (00, 15, 30, 45 minutes)
        minute = timestamp.minute
        if minute not in [0, 15, 30, 45]:
            # Not aligned to M15 boundary yet
            return None
        
        # Create M15 bar from 3 M5 candles
        m15_bar = {
            'timestamp': timestamp,  # Use last M5 timestamp
            'open': buffer_list[0]['open'],
            'high': max(c['high'] for c in buffer_list),
            'low': min(c['low'] for c in buffer_list),
            'close': buffer_list[-1]['close'],
            'volume': sum(c.get('volume', 0) for c in buffer_list)
        }
        
        # Clear buffer after creating M15 bar
        self.m5_buffer.clear()
        self.last_m15_time = timestamp
        
        logger.info(f"✅ M15 bar created: {timestamp} O:{m15_bar['open']:.2f} H:{m15_bar['high']:.2f} L:{m15_bar['low']:.2f} C:{m15_bar['close']:.2f}")
        
        return m15_bar


class TradingBot:
    """Live trading bot with signal generation and optional automated execution"""
    
    def __init__(self, config: TradingConfig, epic: str = 'GOLD'):
        """
        Initialize trading bot
        
        Args:
            config: TradingConfig with credentials and settings
            epic: Instrument to trade (default: GOLD)
        """
        self.config = config
        self.epic = epic
        self.auto_trade = (config.environment == 'demo')  # Auto-trade only in DEMO
        
        # Best strategy: ST2.0 SMA25-30 BB2.0 Fixed F20-40 on M5
        # Source: rank01 optimization run 2026-03-17 → 373.7% return, 14.0% DD
        self.strategy = SupertrendVWAPStrategy(
            supertrend_period=config.supertrend_period,
            supertrend_multiplier=config.supertrend_multiplier,
            sma_fast=config.sma_fast,
            sma_slow=config.sma_slow,
            ema_period=config.sma_fast,
            bb_period=config.bb_period,
            bb_std=config.bb_std,
            sl_pips=config.sl_pips_fixed,
            tp_pips=config.tp_pips_fixed,
            pip_value=1.0,  # For GOLD: 1 pip = $1 price move
            use_rsi_filter=False,
            use_atr_volatility_filter=False,
            use_session_filter=False,
            use_heikin_ashi=False
        )
        
        # Historical bars for indicator calculation
        self.m5_history: List[Dict] = []
        _bars_by_tf = {'MINUTE_5': 60, 'MINUTE_15': 100, 'MINUTE_30': 120, 'HOUR': 150}
        self.min_history_bars = _bars_by_tf.get(self.config.timeframe, 60)

        # Event blocker
        if config.enable_event_blocking and config.calendar_path:
            try:
                calendar = ManualCalendarAdapter(config.calendar_path)
                self.event_blocker = EventBlocker(
                    calendar_adapter=calendar,
                    pre_event_minutes=15,
                    post_event_minutes=15
                )
                logger.info(f"🚫 Event blocking enabled: {config.calendar_path}")
            except Exception as e:
                logger.warning(f"⚠️ Event blocker init failed: {e} — blocking disabled")
                self.event_blocker = None
        else:
            self.event_blocker = None
        
        # Position tracking
        self.current_position: Optional[Dict] = None
        self.last_signal_time: Optional[datetime] = None
        
        # Capital.com REST client for authentication
        self.rest_client = CapitalRestClient(config)
        
        # WebSocket client (initialized after authentication)
        self.ws_client: Optional[CapitalWebSocketClient] = None
        
        # Capital.com session tokens
        self.cst: Optional[str] = None
        self.security_token: Optional[str] = None
        
        # Signal publisher (publishes to Firestore by default)
        try:
            self.signal_publisher = SignalPublisher(
                backends=[SignalBackend.FIRESTORE],
                firestore_collection='trading_signals'
            )
            logger.info("📡 Signal publishing enabled (Firestore)")
        except Exception as e:
            logger.warning(f"⚠️ Signal publisher initialization failed: {e}")
            logger.warning("Bot will continue without signal publishing")
            self.signal_publisher = None
        
        # Bot status publisher (tracks bot health and heartbeat)
        try:
            self.status_publisher = BotStatusPublisher(
                bot_id=f"{epic.lower()}_m5_bot"
            )
            logger.info("📡 Bot status publishing enabled (Firestore)")
        except Exception as e:
            logger.warning(f"⚠️ Bot status publisher initialization failed: {e}")
            self.status_publisher = None
        
        # Position publisher (tracks active positions with P&L)
        try:
            self.position_publisher = PositionPublisher()
            logger.info("📡 Position publishing enabled (Firestore)")
        except Exception as e:
            logger.warning(f"⚠️ Position publisher initialization failed: {e}")
            self.position_publisher = None
        
        # Log publisher (streams live logs to Firestore for UI)
        try:
            run_id = _log_ts  # Use same timestamp as log file
            bot_id = f"{epic.lower()}_m5_bot"
            self.log_publisher = LogPublisher(bot_id=bot_id, run_id=run_id)
            
            # Add Firestore handler to root logger
            firestore_handler = FirestoreLogHandler(self.log_publisher, level=logging.INFO)
            firestore_handler.setFormatter(logging.Formatter('%(message)s'))
            logging.getLogger().addHandler(firestore_handler)
            
            logger.info("📡 Log publishing enabled (Firestore)")
        except Exception as e:
            logger.warning(f"⚠️ Log publisher initialization failed: {e}")
            self.log_publisher = None
        
        logger.info(f"🤖 Trading Bot initialized: Epic={epic}, Mode={'AUTO-TRADE' if self.auto_trade else 'SIGNAL-ONLY'}")
        logger.info(f"   Timeframe: {config.timeframe} | Strategy: ST{config.supertrend_multiplier} SMA{config.sma_fast}/{config.sma_slow} BB{config.bb_std} SL={config.sl_pips_fixed}pip TP={config.tp_pips_fixed}pip")
        logger.info(f"   Event blocking: {'ON' if self.event_blocker else 'OFF'}")
    
    async def authenticate(self):
        """Authenticate with Capital.com and get session tokens"""
        try:
            logger.info("🔐 Authenticating with Capital.com...")
            tokens = self.rest_client.create_session()
            self.cst = tokens['CST']
            self.security_token = tokens['X-SECURITY-TOKEN']
            logger.info("✅ Authentication successful")
        except Exception as e:
            logger.error(f"❌ Authentication failed: {e}")
            raise
    
    async def _prefetch_history(self):
        """Pre-populate M5 history from REST API so the bot is ready to trade immediately."""
        try:
            count = max(self.min_history_bars + 20, 100)
            logger.info(f"📥 Fetching {count} historical {self.config.timeframe} candles for {self.epic}...")
            candles = self.rest_client.get_historical_candles(
                self.epic, resolution=self.config.timeframe, count=count
            )
            if candles:
                self.m5_history = candles
                logger.info(f"✅ Pre-loaded {len(candles)} historical candles — strategy ready immediately")
            else:
                logger.warning("⚠️ No historical candles returned — will build from live feed")
        except Exception as e:
            logger.warning(f"⚠️ History prefetch failed: {e} — will build from live feed")

    async def start(self):
        """Start the trading bot with auto-reconnect on WebSocket drop"""
        # Update bot status to STARTING
        if self.status_publisher:
            self.status_publisher.update_status(
                BotStatus.STARTING,
                epic=self.epic,
                mode='AUTO' if self.auto_trade else 'SIGNAL_ONLY'
            )
        
        # Authenticate and prefetch once
        await self.authenticate()
        await self._prefetch_history()
        await self._sync_open_position()
        
        # Update bot status to RUNNING
        if self.status_publisher:
            self.status_publisher.update_status(
                BotStatus.RUNNING,
                epic=self.epic,
                mode='AUTO' if self.auto_trade else 'SIGNAL_ONLY'
            )
        
        # Start log publisher batch writer
        if self.log_publisher:
            self.log_publisher.start_batch_writer()
        
        # Start heartbeat task
        asyncio.create_task(self._heartbeat_loop())

        reconnect_delay = 5  # seconds
        while True:
            try:
                # Fresh WebSocket client each reconnect
                self.ws_client = CapitalWebSocketClient(
                    cst=self.cst,
                    security_token=self.security_token,
                    ws_url=self.config.ws_url,
                    ping_interval=self.config.ping_interval_seconds
                )

                # Set callbacks
                self.ws_client.on_candle = self.on_m5_candle
                self.ws_client.on_quote = self.on_quote

                # Connect and subscribe
                await self.ws_client.connect()
                await self.ws_client.subscribe_ohlc([self.epic], resolution=self.config.timeframe)
                await self.ws_client.subscribe_quotes([self.epic])

                logger.info(f"🎯 Subscribed to {self.epic} {self.config.timeframe} candles and live quotes")
                logger.info(f"⚡ Bot running in {'AUTO-TRADE' if self.auto_trade else 'SIGNAL-ONLY'} mode")

                reconnect_delay = 5  # reset on clean connection
                await self.ws_client.run()

                # run() returned cleanly (WebSocket closed)
                logger.warning("⚠️ WebSocket closed — reconnecting in 5s...")

            except asyncio.CancelledError:
                raise  # propagate shutdown
            except Exception as e:
                logger.error(f"❌ WebSocket error: {e} — reconnecting in {reconnect_delay}s...")

            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 60)  # back-off up to 60s

            # Re-authenticate if tokens may have expired
            try:
                await self.authenticate()
                await self._sync_open_position()
            except Exception as e:
                logger.warning(f"⚠️ Re-auth failed: {e}")
    
    async def _heartbeat_loop(self):
        """Send periodic heartbeat to bot_status collection (every 30 seconds)"""
        while True:
            try:
                await asyncio.sleep(30)  # Heartbeat every 30 seconds
                if self.status_publisher:
                    self.status_publisher.heartbeat()
                    
                    # Update position count
                    position_count = 1 if self.current_position else 0
                    self.status_publisher.update_statistics({
                        'position_count': position_count
                    })
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Heartbeat error: {e}")
    
    async def on_m5_candle(self, candle: Dict):
        """
        Callback when M5 OHLC candle is received. Strategy runs directly on M5.
        
        Args:
            candle: M5 candle dict (includes 'epic' key)
        """
        epic = candle.get('epic')
        if epic != self.epic:
            return

        # Deduplicate: skip if same candle timestamp already processed this bar
        candle_ts = candle.get('timestamp')
        if candle_ts == getattr(self, '_last_candle_ts', None):
            logger.debug(f"⏭️ Skipping duplicate candle ts={candle_ts}")
            return
        self._last_candle_ts = candle_ts
        
        logger.info(f"📊 {self.config.timeframe} Candle: {candle['timestamp']} O:{candle['open']:.2f} H:{candle['high']:.2f} L:{candle['low']:.2f} C:{candle['close']:.2f}")
        
        # Add directly to M5 history (no M15 aggregation)
        self.m5_history.append(candle)
        
        # Keep only last 200 bars
        if len(self.m5_history) > 200:
            self.m5_history = self.m5_history[-200:]
        
        # Wait for enough history
        if len(self.m5_history) < self.min_history_bars:
            logger.info(f"⏳ Building history: {len(self.m5_history)}/{self.min_history_bars} bars")
            return
        
        # Generate signal
        await self.generate_signal()
    
    async def on_quote(self, quote: Dict):
        """
        Callback when live quote is received.
        
        Args:
            quote: Live quote dict (includes 'epic' key) with bid, offer, mid
        """
        epic = quote.get('epic')
        if epic != self.epic:
            return
        
        # Update current position if exists
        if self.current_position:
            await self.check_position_status(quote)
    
    def calculate_indicators(self) -> pd.DataFrame:
        """
        Calculate indicators on M5 history
        
        Returns:
            DataFrame with all indicators
        """
        # Convert M5 history to DataFrame
        df = pd.DataFrame(self.m5_history)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
        
        # Rename columns to match strategy expectations
        df.rename(columns={'volume': 'volume'}, inplace=True)
        
        # Calculate indicators using strategy
        df_with_indicators = self.strategy.calculate_indicators(df)
        
        return df_with_indicators
    
    async def generate_signal(self):
        """Generate trading signal from M5 indicators"""
        try:
            # Calculate indicators
            df = self.calculate_indicators()
            
            # Get latest bar (most recent completed M15)
            latest = df.iloc[-1]
            
            # Check if indicators are ready
            if pd.isna(latest['supertrend']) or pd.isna(latest['sma_fast']) or pd.isna(latest['sma_slow']):
                logger.warning("⚠️ Indicators not ready yet (NaN values)")
                return
            
            # Get values
            close = latest['close']
            supertrend_dir = latest['direction']
            sma_fast = latest['sma_fast']
            sma_slow = latest['sma_slow']
            ema = latest['ema']

            # Event blocking check before evaluating signals
            if self.event_blocker:
                is_allowed, block_reason = self.event_blocker.is_trading_allowed(datetime.utcnow())
                if not is_allowed:
                    logger.info(f"🚫 Trade blocked by event filter: {block_reason}")
                    return

            # Check if already in position
            if self.current_position:
                logger.info(f"📍 Already in position: {self.current_position['direction']} {self.current_position['size']} @ {self.current_position['entry_price']:.2f}")
                
                # Check for exit signal
                if self.current_position['direction'] == 'BUY' and supertrend_dir == -1:
                    logger.info("🚨 EXIT SIGNAL: Supertrend turned bearish, close LONG")
                    if self.auto_trade:
                        await self.close_position()
                
                elif self.current_position['direction'] == 'SELL' and supertrend_dir == 1:
                    logger.info("🚨 EXIT SIGNAL: Supertrend turned bullish, close SHORT")
                    if self.auto_trade:
                        await self.close_position()
                
                return
            
            # Check for crossovers
            sma_fast_prev = df.iloc[-2]['sma_fast']
            sma_slow_prev = df.iloc[-2]['sma_slow']
            golden_cross = (sma_fast > sma_slow) and (sma_fast_prev <= sma_slow_prev)
            death_cross = (sma_fast < sma_slow) and (sma_fast_prev >= sma_slow_prev)
            
            # BUY Signal
            if (supertrend_dir == 1 and 
                close > ema and 
                (golden_cross or sma_fast > sma_slow)):
                
                # Fixed pip TP/SL (best strategy uses 20 SL / 40 TP)
                stop_loss = close - self.config.sl_pips_fixed
                take_profit = close + self.config.tp_pips_fixed
                
                logger.info("=" * 80)
                logger.info("🟢 BUY SIGNAL DETECTED")
                logger.info(f"   Price: {close:.2f}")
                logger.info(f"   Supertrend: UPTREND")
                logger.info(f"   SMA Fast: {sma_fast:.2f}")
                logger.info(f"   SMA Slow: {sma_slow:.2f}")
                logger.info(f"   EMA: {ema:.2f}")
                logger.info(f"   Stop Loss: {stop_loss:.2f} ({self.config.sl_pips_fixed} pips fixed)")
                logger.info(f"   Take Profit: {take_profit:.2f} ({self.config.tp_pips_fixed} pips fixed)")
                logger.info("=" * 80)
                
                # Publish signal to Firestore/Pub/Sub
                if self.signal_publisher:
                    signal_data = {
                        'epic': self.epic,
                        'signal': 'BUY',
                        'direction': 'BUY',
                        'price': close,
                        'sl': stop_loss,
                        'tp': take_profit,
                        'timestamp': datetime.now().isoformat(),
                        'strategy': 'SupertrendVWAP',
                        'mode': 'AUTO' if self.auto_trade else 'SIGNAL_ONLY',
                        'indicators': {
                            'supertrend': float(latest['supertrend']),
                            'supertrend_direction': int(supertrend_dir),
                            'sma_fast': float(sma_fast),
                            'sma_slow': float(sma_slow),
                            'ema': float(ema),
                            'golden_cross': bool(golden_cross)
                        }
                    }
                    try:
                        self.signal_publisher.publish_signal(signal_data)
                    except Exception as e:
                        logger.warning(f"⚠️ Signal publishing failed: {e}")
                
                if self.auto_trade:
                    await self.place_order('BUY', close, stop_loss, take_profit)
                else:
                    logger.info("📋 SIGNAL-ONLY MODE: No order placed (manual execution required)")
            
            # SELL Signal
            elif (supertrend_dir == -1 and 
                  close < ema and 
                  (death_cross or sma_fast < sma_slow)):
                
                # Fixed pip TP/SL
                stop_loss = close + self.config.sl_pips_fixed
                take_profit = close - self.config.tp_pips_fixed
                
                logger.info("=" * 80)
                logger.info("🔴 SELL SIGNAL DETECTED")
                logger.info(f"   Price: {close:.2f}")
                logger.info(f"   Supertrend: DOWNTREND")
                logger.info(f"   SMA Fast: {sma_fast:.2f}")
                logger.info(f"   SMA Slow: {sma_slow:.2f}")
                logger.info(f"   EMA: {ema:.2f}")
                logger.info(f"   Stop Loss: {stop_loss:.2f} ({self.config.sl_pips_fixed} pips fixed)")
                logger.info(f"   Take Profit: {take_profit:.2f} ({self.config.tp_pips_fixed} pips fixed)")
                logger.info("=" * 80)
                
                # Publish signal to Firestore/Pub/Sub
                if self.signal_publisher:
                    signal_data = {
                        'epic': self.epic,
                        'signal': 'SELL',
                        'direction': 'SELL',
                        'price': close,
                        'sl': stop_loss,
                        'tp': take_profit,
                        'timestamp': datetime.now().isoformat(),
                        'strategy': 'SupertrendVWAP',
                        'mode': 'AUTO' if self.auto_trade else 'SIGNAL_ONLY',
                        'indicators': {
                            'supertrend': float(latest['supertrend']),
                            'supertrend_direction': int(supertrend_dir),
                            'sma_fast': float(sma_fast),
                            'sma_slow': float(sma_slow),
                            'ema': float(ema),
                            'death_cross': bool(death_cross)
                        }
                    }
                    try:
                        self.signal_publisher.publish_signal(signal_data)
                    except Exception as e:
                        logger.warning(f"⚠️ Signal publishing failed: {e}")
                
                if self.auto_trade:
                    await self.place_order('SELL', close, stop_loss, take_profit)
                else:
                    logger.info("📋 SIGNAL-ONLY MODE: No order placed (manual execution required)")
        
        except Exception as e:
            logger.error(f"❌ Signal generation failed: {e}", exc_info=True)
    
    async def place_order(self, direction: str, entry_price: float, stop_loss: float, take_profit: float):
        """
        Place order via Capital.com REST API
        
        Args:
            direction: 'BUY' or 'SELL'
            entry_price: Entry price
            stop_loss: Stop loss level
            take_profit: Take profit level
        """
        try:
            # Calculate position size
            # Target: $300-600 margin per trade
            # With 20× leverage: $300 margin = $6000 position
            # For GOLD at ~$2000: 3 contracts = $6000
            position_size = 0.5  # Start conservative: 0.5 contracts = ~$1000 position = $50 margin @ 20×
            
            logger.info(f"📤 Placing {direction} order: {position_size} contracts @ {entry_price:.2f}")
            logger.info(f"   SL: {stop_loss:.2f} | TP: {take_profit:.2f}")
            
            # Create position via REST API
            response = self.rest_client.create_position(
                epic=self.epic,
                size=position_size,
                direction=direction,
                stop_level=stop_loss,
                profit_level=take_profit
            )
            deal_reference = response.get('dealReference')
            if deal_reference:
                logger.info(f"✅ Order placed successfully: {deal_reference}")
                
                # Track position
                self.current_position = {
                    'deal_reference': deal_reference,
                    'direction': direction,
                    'size': position_size,
                    'entry_price': entry_price,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'entry_time': datetime.now()
                }
                
                # Publish position to Firestore
                if self.position_publisher:
                    self.position_publisher.publish_position({
                        'deal_id': deal_reference,
                        'epic': self.epic,
                        'direction': direction,
                        'size': position_size,
                        'entry_price': entry_price,
                        'stop_loss': stop_loss,
                        'take_profit': take_profit
                    }, status=PositionStatus.OPEN)
                
                self.last_signal_time = datetime.now()
            else:
                logger.error(f"❌ Order placement failed: no dealReference in response: {response}")
        
        except Exception as e:
            logger.error(f"❌ Order placement error: {e}", exc_info=True)
    
    async def close_position(self):
        """Close current position via REST API"""
        if not self.current_position:
            return

        deal_id = self.current_position.get('deal_id') or self.current_position.get('deal_reference')
        logger.info(f"🔚 Closing position: {deal_id}")
        try:
            self.rest_client.close_position(deal_id)
            logger.info(f"✅ Position closed: {deal_id}")
            
            # Update position status in Firestore
            if self.position_publisher:
                self.position_publisher.close_position(deal_id)
                
        except Exception as e:
            logger.error(f"❌ Close position error: {e} — clearing local tracking anyway")
        finally:
            # Always clear local state — Capital.com may have already closed it via SL/TP
            self.current_position = None

    async def _sync_open_position(self):
        """On startup, re-hydrate self.current_position from any live open position on Capital.com."""
        try:
            positions = self.rest_client.get_open_positions()
            for item in positions:
                pos = item.get('position', {})
                mkt = item.get('market', {})
                if mkt.get('epic') == self.epic:
                    self.current_position = {
                        'deal_id': pos.get('dealId'),
                        'deal_reference': pos.get('dealReference'),
                        'direction': pos.get('direction'),
                        'size': pos.get('size'),
                        'entry_price': pos.get('level'),
                        'stop_loss': pos.get('stopLevel'),
                        'take_profit': pos.get('limitLevel'),
                        'entry_time': None,
                    }
                    logger.info(
                        f"🔄 Resumed existing {pos.get('direction')} position: "
                        f"dealId={pos.get('dealId')} entry={pos.get('level')}"
                    )
                    return
            logger.info("✅ No open positions found — starting fresh")
        except Exception as e:
            logger.warning(f"⚠️ Position sync failed: {e} — assuming no open position")
    
    async def check_position_status(self, quote: Dict):
        """
        Check if position hit SL/TP, and update P&L in Firestore
        
        Args:
            quote: Live quote with bid, offer, mid
        """
        if not self.current_position:
            return

        current_price = quote.get('mid')
        if current_price is None:
            return
        
        # Update P&L in Firestore (if publisher enabled)
        if self.position_publisher:
            deal_id = self.current_position.get('deal_id') or self.current_position.get('deal_reference')
            if deal_id:
                self.position_publisher.update_pnl(deal_id, current_price=current_price)

        stop_loss = self.current_position.get('stop_loss')
        take_profit = self.current_position.get('take_profit')

        # Check LONG position
        if self.current_position['direction'] == 'BUY':
            if stop_loss and current_price <= stop_loss:
                logger.warning(f"🛑 STOP LOSS HIT: {current_price:.2f} <= {stop_loss:.2f}")
                await self.close_position()
            elif take_profit and current_price >= take_profit:
                logger.info(f"🎯 TAKE PROFIT HIT: {current_price:.2f} >= {take_profit:.2f}")
                await self.close_position()

        # Check SHORT position
        elif self.current_position['direction'] == 'SELL':
            if stop_loss and current_price >= stop_loss:
                logger.warning(f"🛑 STOP LOSS HIT: {current_price:.2f} >= {stop_loss:.2f}")
                await self.close_position()
            elif take_profit and current_price <= take_profit:
                logger.info(f"🎯 TAKE PROFIT HIT: {current_price:.2f} <= {take_profit:.2f}")
                await self.close_position()
    
    async def stop(self):
        """Stop the trading bot"""
        logger.info("🛑 Stopping trading bot...")
        
        # Update bot status to STOPPED
        if self.status_publisher:
            self.status_publisher.update_status(BotStatus.STOPPED)
        
        # Stop log publisher and flush remaining logs
        if self.log_publisher:
            self.log_publisher.stop_batch_writer()
        
        if self.ws_client:
            await self.ws_client.close()
        logger.info("✅ Trading bot stopped")


async def main():
    """Main entry point with graceful shutdown"""
    # Load configuration
    # Set environment: 'demo' for paper trading (AUTO), 'live' for real trading (SIGNAL-ONLY)
    environment = os.getenv('TRADING_ENVIRONMENT', 'demo')  # Default to demo/paper trading
    
    config = TradingConfig(environment=environment)
    
    # Create bot
    bot = TradingBot(config, epic='GOLD')
    
    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()
    shutdown_event = asyncio.Event()
    
    def signal_handler(signum, frame):
        """Handle shutdown signals"""
        logger.info(f"⛔ Received signal {signum}, initiating graceful shutdown...")
        shutdown_event.set()
    
    # Register signal handlers (SIGINT = Ctrl+C, SIGTERM = kill command)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Start bot in background task
        bot_task = asyncio.create_task(bot.start())
        
        # Wait for shutdown signal
        logger.info("🤖 Trading bot running... Press Ctrl+C to stop gracefully")
        await shutdown_event.wait()
        
        # Cancel bot task
        logger.info("🛑 Stopping bot gracefully...")
        bot_task.cancel()
        
        try:
            await bot_task
        except asyncio.CancelledError:
            pass
            
    except KeyboardInterrupt:
        logger.info("⛔ Keyboard interrupt received")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
    finally:
        await bot.stop()
        logger.info("✅ Clean shutdown complete")


if __name__ == '__main__':
    # Log startup information
    logger.info("=" * 80)
    logger.info("🚀 TRADING BOT STARTING")
    logger.info(f"📅 Start Time: {datetime.now()}")
    logger.info(f"🌍 Environment: {os.getenv('TRADING_ENVIRONMENT', 'demo').upper()}")
    logger.info(f"💻 PID: {os.getpid()}")
    logger.info("=" * 80)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("=" * 80)
        logger.info("🏁 TRADING BOT STOPPED")
        logger.info(f"📅 Stop Time: {datetime.now()}")
        logger.info("=" * 80)
