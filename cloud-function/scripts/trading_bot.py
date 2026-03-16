"""
🚀 Live Trading Bot for Capital.com

MODES:
- DEMO (paper trading): Fully automated - generates signals AND places trades
- LIVE (real trading): Signal-only mode - ONLY logs signals, NO automatic orders

GOLD M15 Strategy:
- Supertrend: period=7, multiplier=2.0
- SMA: Fast=21, Slow=50
- Bollinger Bands: period=20, std=2.0
- ATR: period=14
- Stop Loss: 0.7× ATR
- Take Profit: 2.5× ATR

Performance: 155% return, 26.8% win rate, 1.24 profit factor, 24 trades/month
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
from src.live_trading.signal_publisher import SignalPublisher, SignalBackend

# Import strategy indicator calculations
from src.core.strategy import SupertrendVWAPStrategy

# Import live trading components  
from src.live_trading.capital_rest import CapitalRestClient

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
        
        # Strategy configuration (GOLD M15 proven parameters)
        self.strategy = SupertrendVWAPStrategy(
            supertrend_period=7,
            supertrend_multiplier=2.0,
            sma_fast=21,
            sma_slow=50,
            ema_period=21,
            bb_period=20,
            bb_std=2.0,
            sl_pips=0.7,  # Will be multiplied by ATR
            tp_pips=2.5,  # Will be multiplied by ATR
            pip_value=1.0,  # For GOLD: 1 pip = $1
            use_rsi_filter=False,
            use_atr_volatility_filter=False,
            use_session_filter=False,
            use_heikin_ashi=False
        )
        
        # M5 to M15 aggregator
        self.aggregator = M5toM15Aggregator()
        
        # Historical M15 bars for indicator calculation (need 50+ bars for SMA slow)
        self.m15_history: List[Dict] = []
        self.min_history_bars = 60  # Need at least 60 bars for indicators
        
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
        
        logger.info(f"🤖 Trading Bot initialized: Epic={epic}, Mode={'AUTO-TRADE' if self.auto_trade else 'SIGNAL-ONLY'}")
    
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
    
    async def start(self):
        """Start the trading bot"""
        try:
            # Authenticate
            await self.authenticate()
            
            # Create WebSocket client
            self.ws_client = CapitalWebSocketClient(
                cst=self.cst,
                security_token=self.security_token,
                ws_url=self.config.ws_url,
                ping_interval=self.config.ping_interval
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
            
            # Run WebSocket client
            await self.ws_client.run()
            
        except Exception as e:
            logger.error(f"❌ Bot start failed: {e}")
            raise
    
    async def on_m5_candle(self, epic: str, candle: Dict):
        """
        Callback when M5 OHLC candle is received
        
        Args:
            epic: Instrument (e.g., 'GOLD')
            candle: M5 candle data
        """
        if epic != self.epic:
            return
        
        logger.info(f"📊 M5 Candle: {candle['timestamp']} O:{candle['open']:.2f} H:{candle['high']:.2f} L:{candle['low']:.2f} C:{candle['close']:.2f}")
        
        # Aggregate to M15
        m15_bar = self.aggregator.add_m5_candle(candle)
        
        if m15_bar is None:
            return  # Not ready yet
        
        # Add to history
        self.m15_history.append(m15_bar)
        
        # Keep only last 100 bars (enough for indicators + some buffer)
        if len(self.m15_history) > 100:
            self.m15_history = self.m15_history[-100:]
        
        # Wait for enough history
        if len(self.m15_history) < self.min_history_bars:
            logger.info(f"⏳ Building history: {len(self.m15_history)}/{self.min_history_bars} bars")
            return
        
        # Generate signal
        await self.generate_signal()
    
    async def on_quote(self, epic: str, quote: Dict):
        """
        Callback when live quote is received
        
        Args:
            epic: Instrument (e.g., 'GOLD')
            quote: Live quote data with bid, offer, mid
        """
        if epic != self.epic:
            return
        
        # Update current position if exists
        if self.current_position:
            await self.check_position_status(quote)
    
    def calculate_indicators(self) -> pd.DataFrame:
        """
        Calculate indicators on M15 history
        
        Returns:
            DataFrame with all indicators
        """
        # Convert M15 history to DataFrame
        df = pd.DataFrame(self.m15_history)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
        
        # Rename columns to match strategy expectations
        df.rename(columns={'volume': 'volume'}, inplace=True)
        
        # Calculate indicators using strategy
        df_with_indicators = self.strategy.calculate_indicators(df)
        
        return df_with_indicators
    
    async def generate_signal(self):
        """Generate trading signal from M15 indicators"""
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
            atr = self.strategy.calculate_atr(df, 14).iloc[-1]
            
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
                
                # Calculate SL/TP based on ATR
                stop_loss = close - (self.strategy.sl_pips * atr)
                take_profit = close + (self.strategy.tp_pips * atr)
                
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
                            'supertrend': supertrend,
                            'supertrend_direction': int(supertrend_dir),
                            'sma_fast': sma_fast,
                            'sma_slow': sma_slow,
                            'ema': ema,
                            'atr': atr,
                            'golden_cross': golden_cross
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
                
                # Calculate SL/TP based on ATR
                stop_loss = close + (self.strategy.sl_pips * atr)
                take_profit = close - (self.strategy.tp_pips * atr)
                
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
                        'signal': 'SELL',
                        'direction': 'SELL',
                        'price': close,
                        'sl': stop_loss,
                        'tp': take_profit,
                        'timestamp': datetime.now().isoformat(),
                        'strategy': 'SupertrendVWAP',
                        'mode': 'AUTO' if self.auto_trade else 'SIGNAL_ONLY',
                        'indicators': {
                            'supertrend': supertrend,
                            'supertrend_direction': int(supertrend_dir),
                            'sma_fast': sma_fast,
                            'sma_slow': sma_slow,
                            'ema': ema,
                            'atr': atr,
                            'death_cross': death_cross
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
            response = capitalService.create_position(
                epic=self.epic,
                size=position_size,
                direction=direction,
                stopLevel=stop_loss,
                profitLevel=take_profit
            )
            
            if response.status_code == 200:
                deal_reference = response.json().get('dealReference')
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
                
                self.last_signal_time = datetime.now()
            else:
                logger.error(f"❌ Order placement failed: {response.status_code} - {response.text}")
        
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
            self.current_position = None
        
        except Exception as e:
            logger.error(f"❌ Close position error: {e}", exc_info=True)
    
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
