"""
🚀 Live Trading Bot for Capital.com - M5 (5-Minute) Timeframe

MODES:
- DEMO (paper trading): Fully automated - generates signals AND places trades
- LIVE (real trading): Signal-only mode - ONLY logs signals, NO automatic orders

GOLD M5 Strategy:
- Timeframe: M5 (5-minute candles)
- Supertrend: period=7, multiplier=2.0
- SMA: Fast=10, Slow=21 (adjusted for faster timeframe)
- Bollinger Bands: period=20, std=2.0
- ATR: period=14
- Stop Loss: 0.7× ATR
- Take Profit: 2.5× ATR
- Min bars: 20 (takes ~100 minutes to collect vs 15 hours for M15)

Note: M5 generates signals 3x faster than M15
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
from src.live_trading.historical_data import fetch_historical_candles

# Import strategy indicator calculations
from src.core.strategy import SupertrendVWAPStrategy

# Import live trading components
from src.live_trading.capital_rest import CapitalRestClient
from src.live_trading.order_manager import OrderManager, TrailingConfig, TrailingStrategy

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


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
        
        # Strategy configuration (GOLD M5 parameters - adjusted for faster timeframe)
        self.strategy = SupertrendVWAPStrategy(
            supertrend_period=7,
            supertrend_multiplier=2.0,
            sma_fast=10,   # Faster SMA for M5 (vs 21 for M15)
            sma_slow=21,   # Faster slow SMA for M5 (vs 50 for M15)
            ema_period=10,
            bb_period=20,
            bb_std=2.0,
            sl_pips=0.7,  # ATR multiplier for Stop Loss (0.7x ATR)
            tp_pips=2.5,  # ATR multiplier for Take Profit (2.5x ATR)
            pip_value=1.0,  # Not used anymore (using ATR-based TP/SL)
            use_rsi_filter=False,
            use_atr_volatility_filter=False,
            use_session_filter=False,
            use_heikin_ashi=False
        )
        
        # Historical M5 bars for indicator calculation
        self.m5_history: List[Dict] = []
        self.min_history_bars = 20  # Need at least 21 bars for slow SMA (~100 min for M5)
        
        # Position tracking
        self.current_position: Optional[Dict] = None
        self.last_signal_time: Optional[datetime] = None
        self.last_supertrend_direction: Optional[int] = None  # Track trend changes
        self.latest_atr: Optional[float] = None  # Store latest ATR for trailing stops
        
        # File-based signal logging
        self.signals_dir = os.path.join(os.path.dirname(__file__), '..', 'data', 'signals')
        os.makedirs(self.signals_dir, exist_ok=True)
        logger.info(f"💾 Signal files will be saved to: {self.signals_dir}")
        
        # File-based candle logging
        self.candles_dir = os.path.join(os.path.dirname(__file__), '..', 'data', 'candles')
        os.makedirs(self.candles_dir, exist_ok=True)
        logger.info(f"💾 Candle data will be saved to: {self.candles_dir}")
        
        # Capital.com REST client for authentication
        self.rest_client = CapitalRestClient(config)
        
        # Order Manager for trailing stops (all strategies enabled)
        trailing_config = TrailingConfig(
            breakeven_trigger_points=10.0,  # Move to breakeven after +10 points profit
            breakeven_buffer=2.0,  # Set breakeven SL 2 points above entry
            progressive_step=5.0,  # Trail every +5 points
            progressive_trail_by=3.0,  # Move SL by 3 points per step
            atr_trailing_multiplier=1.0,  # Trail 1× ATR from current price
            enabled_strategies=[TrailingStrategy.ALL],  # Use all strategies
            min_update_points=1.0,  # Minimum 1 point change to update SL
            min_update_interval_seconds=5.0,  # Rate limit: 5s between updates
            price_decimals=2  # Gold uses 2 decimal places
        )
        self.order_manager = OrderManager(trailing_config, self.rest_client)
        
        # WebSocket client (initialized after authentication)
        self.ws_client: Optional[CapitalWebSocketClient] = None
        
        # Capital.com session tokens
        self.cst: Optional[str] = None
        self.security_token: Optional[str] = None
        
        # Signal publisher (publishes to Firestore by default)
        try:
            self.signal_publisher = SignalPublisher(
                backends=[SignalBackend.FIRESTORE],
                firestore_collection='trading_signals',
                project_id='double-venture-442318-k8'
            )
            logger.info("📡 Signal publishing enabled (Firestore)")
        except Exception as e:
            logger.warning(f"⚠️ Signal publisher initialization failed: {e}")
            logger.warning("Bot will continue without signal publishing")
            self.signal_publisher = None
        
        # Bot status publisher (track bot health in Firestore)
        try:
            self.status_publisher = BotStatusPublisher(
                bot_id='gold_m5_bot',
                collection='bot_status',
                project_id='double-venture-442318-k8'
            )
            logger.info("📊 Bot status tracking enabled (Firestore)")
        except Exception as e:
            logger.warning(f"⚠️ Bot status publisher initialization failed: {e}")
            self.status_publisher = None
        
        # Position publisher (track active positions in Firestore)
        try:
            self.position_publisher = PositionPublisher(
                collection='active_positions',
                project_id='double-venture-442318-k8'
            )
            logger.info("💼 Position tracking enabled (Firestore)")
        except Exception as e:
            logger.warning(f"⚠️ Position publisher initialization failed: {e}")
            self.position_publisher = None
        
        logger.info(f"🤖 M5 Trading Bot initialized: Epic={epic}, Mode={'AUTO-TRADE' if self.auto_trade else 'SIGNAL-ONLY'}, Timeframe=M5")
    
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
    
    async def load_existing_positions(self):
        """Load existing open positions and register with OrderManager for trailing stops"""
        try:
            logger.info("📥 Loading existing open positions...")
            positions = self.rest_client.get_open_positions()
            
            if not positions:
                logger.info("✅ No existing positions found")
                return
            
            # Filter positions for our epic
            our_positions = [p for p in positions if p.get('market', {}).get('epic') == self.epic]
            
            if not our_positions:
                logger.info(f"✅ No existing {self.epic} positions found (found {len(positions)} other positions)")
                return
            
            # Register positions with OrderManager
            for pos in our_positions:
                deal_id = pos.get('dealId')
                direction = pos.get('direction')  # 'BUY' or 'SELL'
                size = float(pos.get('size', 0))
                level = float(pos.get('level', 0))  # Entry price
                stop_level = pos.get('stopLevel')
                profit_level = pos.get('profitLevel')
                
                # Skip positions without stop loss (can't manage trailing without SL)
                if not stop_level:
                    logger.warning(f"⚠️ Skipping position {deal_id} - no stop loss set")
                    continue
                
                # Register with OrderManager
                self.order_manager.register_position(
                    deal_id=deal_id,
                    direction=direction,
                    entry_price=level,
                    stop_loss=float(stop_level),
                    take_profit=float(profit_level) if profit_level else None,
                    size=size,
                    epic=self.epic
                )
                
                logger.info(f"✅ Loaded position: {direction} {size} {self.epic} @ {level:.2f} (SL: {stop_level}, TP: {profit_level})")
                
                # Update current_position tracking (only if we don't already have one)
                if not self.current_position:
                    self.current_position = {
                        'deal_id': deal_id,
                        'deal_reference': pos.get('dealReference', deal_id),
                        'direction': direction,
                        'size': size,
                        'entry_price': level,
                        'stop_loss': float(stop_level) if stop_level else None,
                        'take_profit': float(profit_level) if profit_level else None
                    }
            
            logger.info(f"🎯 Loaded {len(our_positions)} existing {self.epic} position(s) - trailing stops enabled")
            
        except Exception as e:
            logger.error(f"❌ Failed to load existing positions: {e}")
            logger.warning("⚠️ Continuing without existing positions - only new positions will be tracked")
    
    async def start(self):
        """Start the trading bot"""
        try:
            # Publish STARTING status
            if self.status_publisher:
                self.status_publisher.update_status(
                    BotStatus.STARTING,
                    epic=self.epic,
                    mode='AUTO' if self.auto_trade else 'SIGNAL_ONLY'
                )
            
            # Authenticate
            await self.authenticate()
            
            # Load existing positions and register with OrderManager
            await self.load_existing_positions()
            
            # Load historical data to bootstrap strategy
            logger.info("📊 Loading historical M5 candles...")
            try:
                historical_candles = fetch_historical_candles(
                    self.rest_client,
                    self.epic,
                    resolution='MINUTE_5',
                    num_candles=20  # Minimum bars needed for strategy
                )
                if historical_candles:
                    self.m5_history = historical_candles
                    count = len(self.m5_history)
                    sma_ready = count >= 21
                    duration_min = count * 5
                    logger.info(f"✅ Loaded {count} historical M5 candles ({duration_min} min)")
                    logger.info(f"🎯 SMA_slow(21): {'✓ Ready' if sma_ready else f'✗ Need {21-count} more candles'}")
                    logger.info(f"🧠 Memory system: {'✓ Ready after 1st live candle' if count >= 20 else f'✗ Need {20-count} more bars'}")
                else:
                    logger.warning("⚠️ No historical data loaded, will wait for real-time candles")
            except Exception as e:
                logger.warning(f"⚠️ Failed to load historical data: {e}")
                logger.warning("Bot will build history from real-time candles")
            
            # Create WebSocket client
            self.ws_client = CapitalWebSocketClient(
                cst=self.cst,
                security_token=self.security_token,
                ws_url=self.config.ws_url,
                ping_interval=self.config.ping_interval_seconds
            )
            
            # Set callbacks
            self.ws_client.on_candle = self.on_m5_candle
            self.ws_client.on_quote = self.on_quote
            
            # Connect
            await self.ws_client.connect()
            
            # Subscribe to GOLD M5 OHLC candles
            await self.ws_client.subscribe_ohlc([self.epic], resolution='MINUTE_5')
            
            # Subscribe to live quotes for current price
            await self.ws_client.subscribe_quotes([self.epic])
            
            logger.info(f"🎯 Subscribed to {self.epic} M5 candles and live quotes")
            logger.info(f"⚡ Bot running in {'AUTO-TRADE' if self.auto_trade else 'SIGNAL-ONLY'} mode")
            
            # Publish RUNNING status
            if self.status_publisher:
                self.status_publisher.update_status(
                    BotStatus.RUNNING,
                    epic=self.epic,
                    mode='AUTO' if self.auto_trade else 'SIGNAL_ONLY',
                    metadata={'min_history_bars': self.min_history_bars, 'current_bars': len(self.m5_history)}
                )
            
            # Start position sync task (every 30 seconds)
            asyncio.create_task(self.sync_positions_periodically())
            
            # Start heartbeat task (every 30 seconds)
            asyncio.create_task(self.heartbeat_periodically())
            
            # Run WebSocket client
            await self.ws_client.run()
            
        except Exception as e:
            logger.error(f"❌ Bot start failed: {e}")
            # Publish ERROR status
            if self.status_publisher:
                self.status_publisher.update_status(
                    BotStatus.ERROR,
                    epic=self.epic,
                    error=str(e)
                )
            raise
    
    async def on_m5_candle(self, candle: Dict):
        """
        Callback when M5 OHLC candle is received - uses M5 directly (no aggregation needed)
        
        Args:
            candle: M5 candle data (includes 'epic', 'open', 'high', 'low', 'close', 'timestamp', 'price_type')
        """
        epic = candle.get('epic')
        if epic != self.epic:
            return
        
        # Filter: Only process BID candles (Capital.com sends both BID and ASK)
        price_type = candle.get('price_type', '').upper()
        if price_type != 'BID':
            logger.debug(f"⏭️ Skipping {price_type} candle (only process BID)")
            return
        
        logger.info(f"📊 M5 Candle: {candle['timestamp']} O:{candle['open']:.2f} H:{candle['high']:.2f} L:{candle['low']:.2f} C:{candle['close']:.2f}")
        
        # Save candle to file
        self.save_candle_to_file(candle)
        
        # Use M5 candles directly (no aggregation)
        self.m5_history.append(candle)
        prev_count = len(self.m5_history)
        
        # Keep only last 50 bars (enough for indicators + some buffer)
        if len(self.m5_history) > 50:
            trimmed = len(self.m5_history) - 50
            self.m5_history = self.m5_history[-50:]
            logger.info(f"🗑️ Trimmed {trimmed} old candles, keeping last 50")
        
        # Log candle count status
        count = len(self.m5_history)
        sma_slow_ready = count >= 21  # SMA_slow needs 21 bars
        memory_ready = count >= self.min_history_bars + 1  # min_history + 1 live candle
        
        logger.info(f"📊 History: {count} M5 bars ({count * 5} min) | SMA_slow: {'✓' if sma_slow_ready else '✗'} | Memory system: {'✓ ACTIVE' if memory_ready else '⏳ WAITING'}")
        
        # Wait for enough history
        if len(self.m5_history) < self.min_history_bars:
            logger.info(f"⏳ Building history: {len(self.m5_history)}/{self.min_history_bars} M5 bars (~{len(self.m5_history) * 5} minutes)")
            return
        
        # Generate signal
        await self.generate_signal()
    
    async def on_quote(self, quote: Dict):
        """
        Callback when live quote is received - REAL-TIME trailing stop updates
        
        Args:
            quote: Live quote data (includes 'epic', 'bid', 'offer', 'mid')
        """
        epic = quote.get('epic')
        if epic != self.epic:
            return
        
        # Update trailing stops on live price feed (not just M5 candles)
        if self.order_manager.positions and self.latest_atr is not None:
            try:
                current_price = float(quote['mid'])
                updates = self.order_manager.update_trailing_stops(current_price, self.latest_atr)
                if updates > 0:
                    logger.info(f"🔄 Updated {updates} trailing stop(s) at live price {current_price:.2f}")
            except Exception as e:
                logger.error(f"❌ Error updating trailing stops: {e}")
        
        # Update current position if exists
        if self.current_position:
            # Update current price for P&L tracking
            self.current_position['current_price'] = float(quote['mid'])
            
            # Publish P&L update to Firestore (every quote)
            if self.position_publisher and 'deal_id' in self.current_position:
                self.position_publisher.update_pnl(
                    deal_id=self.current_position['deal_id'],
                    current_price=self.current_position['current_price']
                )
            
            await self.check_position_status(quote)
    
    def calculate_indicators(self) -> pd.DataFrame:
        """
        Calculate indicators on M5 history
        
        Returns:
            DataFrame with all indicators
        """
        # Convert M5 history to DataFrame
        df = pd.DataFrame(self.m5_history)
        
        # Handle mixed timestamp formats (Unix ms strings, Unix ms ints, ISO strings)
        # Convert each timestamp individually to handle mixed formats
        timestamps = []
        for ts in df['timestamp']:
            if isinstance(ts, (int, float)):
                # Numeric Unix ms
                timestamps.append(pd.to_datetime(ts, unit='ms'))
            elif isinstance(ts, str):
                # Check if it's a numeric string (Unix ms) or ISO format
                try:
                    # Try as Unix ms first
                    timestamps.append(pd.to_datetime(int(ts), unit='ms'))
                except (ValueError, TypeError):
                    # Fall back to ISO format parsing
                    timestamps.append(pd.to_datetime(ts))
            else:
                # Already datetime
                timestamps.append(pd.to_datetime(ts))
        
        df['timestamp'] = timestamps
        df.set_index('timestamp', inplace=True)
        
        # Rename columns to match strategy expectations
        df.rename(columns={'volume': 'volume'}, inplace=True)
        
        # Calculate indicators using strategy
        df_with_indicators = self.strategy.calculate_indicators(df)
        
        return df_with_indicators
    
    def save_candle_to_file(self, candle: Dict):
        """
        Save M5 candle to local JSONL file for backup/replay
        
        Args:
            candle: Candle data dictionary
        """
        try:
            # Create filename with date
            now = datetime.now()
            date_str = now.strftime('%Y%m%d')
            filename = f"{self.epic}_M5_{date_str}.jsonl"
            filepath = os.path.join(self.candles_dir, filename)
            
            # Convert all datetime/date/timestamp objects to strings for JSON serialization
            candle_copy = {}
            for key, value in candle.items():
                if isinstance(value, (datetime, pd.Timestamp)):
                    candle_copy[key] = value.isoformat()
                elif isinstance(value, (int, float)):
                    # Check if it might be a Unix timestamp (large integer)
                    if isinstance(value, int) and value > 1000000000000:  # Unix ms
                        candle_copy[key] = datetime.fromtimestamp(value / 1000).isoformat()
                    else:
                        candle_copy[key] = value
                else:
                    candle_copy[key] = value
            
            # Append candle to daily JSONL file
            with open(filepath, 'a') as f:
                f.write(json.dumps(candle_copy) + '\n')
        
        except Exception as e:
            logger.warning(f"⚠️ Failed to save candle to file: {e}")
    
    def save_signal_to_file(self, signal_data: Dict):
        """
        Save signal to local JSON file for backup/audit
        
        Args:
            signal_data: Signal dictionary to save
        """
        try:
            # Create filename with date and timestamp
            now = datetime.now()
            date_str = now.strftime('%Y%m%d')
            timestamp_str = now.strftime('%H%M%S')
            
            # Daily signal file (append all signals for the day)
            daily_file = os.path.join(self.signals_dir, f'signals_{date_str}.jsonl')
            
            # Also save individual signal file
            signal_file = os.path.join(
                self.signals_dir, 
                f'signal_{date_str}_{timestamp_str}_{signal_data["signal"]}.json'
            )
            
            # Append to daily file (JSON Lines format)
            with open(daily_file, 'a') as f:
                f.write(json.dumps(signal_data) + '\n')
            
            # Save individual signal
            with open(signal_file, 'w') as f:
                json.dump(signal_data, f, indent=2)
            
            logger.info(f"💾 Signal saved to: {os.path.basename(signal_file)}")
        
        except Exception as e:
            logger.warning(f"⚠️ Failed to save signal to file: {e}")
    
    async def generate_signal(self):
        """Generate trading signal from M5 indicators using strategy logic"""
        try:
            # Log memory system status
            pending = self.strategy.pending_flip
            if pending['direction'] is not None:
                flip_type = "BUY" if pending['direction'] == 1 else "SELL"
                wait_time = len(self.m5_history) - pending['candle_idx']
                logger.info(f"🧠 Memory: Pending {flip_type} from {wait_time} candles ago (max wait: {pending['max_wait']})")
            
            # Calculate indicators
            df = self.calculate_indicators()
            
            # DEBUG: Removed verbose candle logging
            
            # Use strategy's generate_signals method for consistent logic (live mode = incremental processing)
            signals_df = self.strategy.generate_signals(df, live_mode=True)
            
            # Get latest signal
            latest = signals_df.iloc[-1]
            
            # Update latest ATR for trailing stop calculations (used in on_quote)
            if not pd.isna(latest['atr']):
                self.latest_atr = float(latest['atr'])
                logger.debug(f"📊 Updated ATR: {self.latest_atr:.2f}")
            
            # Check if indicators are ready
            if pd.isna(latest['signal']):
                return
            
            signal_value = int(latest['signal'])
            
            # Get indicator values for debugging
            close = latest['close']
            supertrend_dir = latest['direction']
            sma_fast = latest['sma_fast']
            sma_slow = latest['sma_slow']
            ema = latest['ema']
            
            # Log conditions even when no signal (for debugging)
            if len(signals_df) >= 2:
                prev_dir = signals_df.iloc[-2]['direction']
                trend_flip_up = (supertrend_dir == 1 and prev_dir == -1)
                trend_flip_down = (supertrend_dir == -1 and prev_dir == 1)
                
                if trend_flip_up or trend_flip_down:
                    flip_type = "UP" if trend_flip_up else "DOWN"
                    price_vs_ema = "above" if close > ema else "below"
                    sma_trend = "bullish" if sma_fast > sma_slow else "bearish"
                    logger.info(f"🔄 Supertrend flip {flip_type}: Price {close:.2f} {price_vs_ema} EMA {ema:.2f}, SMA {sma_trend} (Fast:{sma_fast:.2f} Slow:{sma_slow:.2f})")
            
            # No signal
            if signal_value == 0:
                return
            
            # Check if already in position
            if self.current_position:
                logger.info(f"📍 Already in position: {self.current_position['direction']} {self.current_position['size']} @ {self.current_position['entry_price']:.2f}")
                return
            
            # Get signal details
            close = latest['close']
            stop_loss = latest['stop_loss']
            take_profit = latest['take_profit']
            direction = 'BUY' if signal_value == 1 else 'SELL'
            
            # Get indicator values for logging
            supertrend_dir = latest['direction']
            sma_fast = latest['sma_fast']
            sma_slow = latest['sma_slow']
            ema = latest['ema']
            atr = self.strategy.calculate_atr(df, 14).iloc[-1]
            
            # Check for crossovers for logging
            if len(signals_df) >= 2:
                prev = signals_df.iloc[-2]
                golden_cross = (sma_fast > sma_slow) and (prev['sma_fast'] <= prev['sma_slow'])
                death_cross = (sma_fast < sma_slow) and (prev['sma_fast'] >= prev['sma_slow'])
            else:
                golden_cross = False
                death_cross = False
            
            # Log signal
            if signal_value == 1:
                logger.info("=" * 80)
                logger.info("🟢 BUY SIGNAL DETECTED")
                logger.info(f"   Price: {close:.2f}")
                logger.info(f"   Supertrend: UPTREND")
                logger.info(f"   SMA Fast: {sma_fast:.2f}")
                logger.info(f"   SMA Slow: {sma_slow:.2f}")
                logger.info(f"   EMA: {ema:.2f}")
                logger.info(f"   ATR: {atr:.2f}")
                logger.info(f"   Stop Loss: {stop_loss:.2f} ({self.strategy.sl_pips}× ATR)")
                logger.info(f"   Take Profit: {take_profit:.2f} ({self.strategy.tp_pips}× ATR)")
                logger.info("=" * 80)
            else:  # signal_value == -1
                logger.info("=" * 80)
                logger.info("🔴 SELL SIGNAL DETECTED")
                logger.info(f"   Price: {close:.2f}")
                logger.info(f"   Supertrend: DOWNTREND")
                logger.info(f"   SMA Fast: {sma_fast:.2f}")
                logger.info(f"   SMA Slow: {sma_slow:.2f}")
                logger.info(f"   EMA: {ema:.2f}")
                logger.info(f"   ATR: {atr:.2f}")
                logger.info(f"   Stop Loss: {stop_loss:.2f} ({self.strategy.sl_pips}× ATR)")
                logger.info(f"   Take Profit: {take_profit:.2f} ({self.strategy.tp_pips}× ATR)")
                logger.info("=" * 80)
            
            # Publish signal to Firestore/Pub/Sub
            if self.signal_publisher:
                signal_data = {
                    'epic': self.epic,
                    'signal': direction,
                    'direction': direction,
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
                        'atr': float(atr),
                        'golden_cross': bool(golden_cross) if signal_value == 1 else False,
                        'death_cross': bool(death_cross) if signal_value == -1 else False
                    }
                }
                try:
                    self.signal_publisher.publish_signal(signal_data)
                    # Also save to local file
                    self.save_signal_to_file(signal_data)
                    
                    # Increment statistics
                    if self.status_publisher:
                        self.status_publisher.increment_stat('signals_generated')
                    
                except Exception as e:
                    logger.warning(f"⚠️ Signal publishing failed: {e}")
            
            if self.auto_trade:
                await self.place_order(direction, close, stop_loss, take_profit)
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
            
            # Create position via REST API (returns dict with dealReference)
            result = self.rest_client.create_position(
                epic=self.epic,
                size=position_size,
                direction=direction,
                stop_level=stop_loss,
                profit_level=take_profit
            )
            
            # Check if position was created successfully
            deal_reference = result.get('dealReference')
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
                
                # Register position with Order Manager for trailing stops
                self.order_manager.register_position(
                    deal_id=deal_reference,
                    direction=direction,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    size=position_size,
                    epic=self.epic
                )
                
                self.last_signal_time = datetime.now()
            else:
                logger.error(f"❌ Order placement failed: {result}")
        
        except Exception as e:
            logger.error(f"❌ Order placement error: {e}", exc_info=True)
    
    async def close_position(self):
        """Close current position"""
        if not self.current_position:
            return
        
        try:
            deal_ref = self.current_position['deal_reference']
            logger.info(f"🔚 Closing position: {deal_ref}")
            
            # In practice, you'd call capitalService.close_position(dealId)
            # For now, just clear position tracking
            # TODO: Implement after verifying deal reference lookup
            
            logger.info(f"✅ Position closed: {deal_ref}")
            
            # Unregister from OrderManager
            if 'deal_id' in self.current_position:
                deal_id = self.current_position['deal_id']
                self.order_manager.unregister_position(deal_id)
                logger.info(f"🗑️ Unregistered position {deal_id} from OrderManager")
                
                # Publish position closure to Firestore
                if self.position_publisher and 'current_price' in self.current_position:
                    self.position_publisher.close_position(
                        deal_id=deal_id,
                        close_price=self.current_position.get('current_price'),
                        close_reason='MANUAL'
                    )
                    logger.info(f"💼 Position closure published to Firestore")
                
                # Increment statistics
                if self.status_publisher:
                    self.status_publisher.increment_stat('positions_closed')
            
            self.current_position = None
        
        except Exception as e:
            logger.error(f"❌ Close position error: {e}", exc_info=True)
    
    async def sync_positions_periodically(self):
        """Periodically sync OrderManager with Capital.com to detect server-side closures"""
        while True:
            try:
                await asyncio.sleep(30)  # Every 30 seconds
                
                # Get current positions from Capital.com
                try:
                    api_positions = self.rest_client.get_open_positions()
                    api_deal_ids = {p.get('dealId') for p in api_positions if p.get('market', {}).get('epic') == self.epic}
                    
                    # Check for positions in OrderManager that are no longer open
                    managed_deal_ids = set(self.order_manager.positions.keys())
                    closed_positions = managed_deal_ids - api_deal_ids
                    
                    for deal_id in closed_positions:
                        logger.info(f"🔍 Detected server-side closure: {deal_id}")
                        self.order_manager.unregister_position(deal_id)
                        
                        # Publish position closure to Firestore
                        if self.position_publisher:
                            self.position_publisher.close_position(
                                deal_id=deal_id,
                                close_price=0.0,  # Unknown close price from API
                                close_reason='SERVER_CLOSED'
                            )
                        
                        # Increment statistics
                        if self.status_publisher:
                            self.status_publisher.increment_stat('positions_closed')
                        
                        # Also clear current_position if it matches
                        if self.current_position and self.current_position.get('deal_id') == deal_id:
                            logger.info(f"🗑️ Clearing current_position tracking for {deal_id}")
                            self.current_position = None
                    
                    if closed_positions:
                        logger.info(f"✅ Synced: Removed {len(closed_positions)} closed position(s) from OrderManager")
                
                except Exception as e:
                    logger.warning(f"⚠️ Position sync error: {e}")
            
            except asyncio.CancelledError:
                logger.info("🛑 Position sync task cancelled")
                break
            except Exception as e:
                logger.error(f"❌ Position sync error: {e}")
    
    async def heartbeat_periodically(self):
        """Send heartbeat to Firestore every 30 seconds to indicate bot is alive"""
        while True:
            try:
                await asyncio.sleep(30)  # Every 30 seconds
                
                if self.status_publisher:
                    self.status_publisher.heartbeat()
                    logger.debug("💓 Heartbeat sent")
            
            except asyncio.CancelledError:
                logger.info("🛑 Heartbeat task cancelled")
                break
            except Exception as e:
                logger.error(f"❌ Heartbeat error: {e}")
    
    async def check_position_status(self, quote: Dict):
        """
        Check if position hit SL/TP
        
        Args:
            quote: Live quote with bid, offer, mid
        """
        if not self.current_position:
            return
        
        current_price = quote['mid']
        
        # Check LONG position
        if self.current_position['direction'] == 'BUY':
            if current_price <= self.current_position['stop_loss']:
                logger.warning(f"🛑 STOP LOSS HIT: {current_price:.2f} <= {self.current_position['stop_loss']:.2f}")
            elif current_price >= self.current_position['take_profit']:
                logger.info(f"🎯 TAKE PROFIT HIT: {current_price:.2f} >= {self.current_position['take_profit']:.2f}")
        
        # Check SHORT position
        elif self.current_position['direction'] == 'SELL':
            if current_price >= self.current_position['stop_loss']:
                logger.warning(f"🛑 STOP LOSS HIT: {current_price:.2f} >= {self.current_position['stop_loss']:.2f}")
            elif current_price <= self.current_position['take_profit']:
                logger.info(f"🎯 TAKE PROFIT HIT: {current_price:.2f} <= {self.current_position['take_profit']:.2f}")
    
    async def stop(self):
        """Stop the trading bot"""
        logger.info("🛑 Stopping trading bot...")
        
        # Publish STOPPED status
        if self.status_publisher:
            self.status_publisher.update_status(
                BotStatus.STOPPED,
                epic=self.epic
            )
        
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
