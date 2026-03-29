"""
Trading Configuration

Manages configuration for live/paper trading with Capital.com
Loads credentials from environment variables
"""

import os
import json
from dataclasses import dataclass
from typing import Literal
from dotenv import load_dotenv


@dataclass
class TradingConfig:
    """Configuration for Capital.com trading"""
    
    # Environment: 'demo' for paper trading, 'live' for real trading
    environment: Literal['demo', 'live'] = 'demo'
    
    # Capital.com credentials (loaded from .env)
    api_key: str = None
    username: str = None
    password: str = None
    
    # URLs (automatically set based on environment)
    rest_base_url: str = None
    ws_url: str = None
    
    # Trading instrument
    gold_epic: str = None  # Will be discovered via API
    
    # Timeframe — controls WebSocket subscription and history prefetch
    # Values: 'MINUTE_5' | 'MINUTE_15' — override with BOT_TIMEFRAME env var
    timeframe: str = 'MINUTE_5'

    # Strategy Parameters — defaults are best M5 params from optimization 2026-03-17
    # rank01: ST2.0 SMA25-30 BB2.0 Fixed F20-40 + event blocking → 373.7% return, 14.0% DD
    # Override each via env vars (BOT_SMA_FAST, BOT_SMA_SLOW, etc.)
    supertrend_period: int = 7
    supertrend_multiplier: float = 2.0
    sma_fast: int = 25
    sma_slow: int = 30
    bb_period: int = 20
    bb_std: float = 2.0
    # Fixed pip TP/SL (not ATR-based) — override with BOT_SL_PIPS / BOT_TP_PIPS
    sl_pips_fixed: float = 20.0
    tp_pips_fixed: float = 40.0
    # Event blocking
    enable_event_blocking: bool = True
    calendar_path: str = 'data/economic_calendar.json'
    
    # Trading hours (GOLD market: Sunday 23:00 - Friday 21:00 UTC)
    enable_trading_hours: bool = True  # Enable/disable trading hours restrictions
    trading_start_hour: int = 0  # Daily trading start hour (UTC)
    trading_end_hour: int = 21  # Daily trading end hour (UTC)
    daily_break_start: int = 21  # Daily break start hour (UTC)
    daily_break_end: int = 22  # Daily break end hour (UTC) 
    allow_weekends: bool = False  # Allow trading on Saturday/Sunday
    friday_close_hour: int = 21  # Friday early close hour (UTC)

    # Position sizing
    position_size: float = 0.1  # Size per trade (adjust based on capital)
    max_capital_per_trade: float = 300.0  # Max $300 margin per trade
    
    # Risk management
    max_open_positions: int = 1  # Only 1 GOLD position at a time
    
    # Trailing Stop Loss Configuration
    enable_trailing_stop: bool = False  # Enable/disable trailing stop loss
    breakeven_after_pips: float = 0.0  # Config 1: Move SL to entry after Z pips profit (0 = disabled)
    trail_stop_distance: float = 0.0  # Config 2: Move SL by X pips...
    trail_trigger_pips: float = 0.0  # Config 2: ...after every Y pips of profit (0 = disabled)
    
    # WebSocket settings
    ping_interval_seconds: int = 480  # 8 minutes (before 10 min timeout)
    
    def __post_init__(self):
        """Load credentials and set URLs based on environment"""
        load_dotenv()
        
        # Load credentials from environment
        secret_json = os.getenv('apicredentials') or os.getenv('CAPITAL_CREDENTIALS') or '{}'
        try:
            secrets = json.loads(secret_json)
            self.api_key = secrets.get('capkey') or secrets.get('apikey')
            self.username = secrets.get('username')
            self.password = secrets.get('password')
        except json.JSONDecodeError:
            # Fallback to individual env vars
            self.api_key = os.getenv('CAPITAL_API_KEY')
            self.username = os.getenv('CAPITAL_USERNAME')
            self.password = os.getenv('CAPITAL_PASSWORD')
        
        # Set URLs based on environment
        if self.environment == 'demo':
            self.rest_base_url = 'https://demo-api-capital.backend-capital.com'
            self.ws_url = 'wss://api-streaming-capital.backend-capital.com/connect'
        else:
            self.rest_base_url = 'https://api-capital.backend-capital.com'
            self.ws_url = 'wss://api-streaming-capital.backend-capital.com/connect'

        # Strategy overrides from environment variables
        self.timeframe = os.getenv('BOT_TIMEFRAME', self.timeframe)
        if os.getenv('BOT_SMA_FAST'):
            self.sma_fast = int(os.getenv('BOT_SMA_FAST'))
        if os.getenv('BOT_SMA_SLOW'):
            self.sma_slow = int(os.getenv('BOT_SMA_SLOW'))
        if os.getenv('BOT_SL_PIPS'):
            self.sl_pips_fixed = float(os.getenv('BOT_SL_PIPS'))
        if os.getenv('BOT_TP_PIPS'):
            self.tp_pips_fixed = float(os.getenv('BOT_TP_PIPS'))
        if os.getenv('BOT_ST_MULTIPLIER'):
            self.supertrend_multiplier = float(os.getenv('BOT_ST_MULTIPLIER'))
        
        # Trailing stop loss overrides
        if os.getenv('BOT_ENABLE_TRAILING_STOP'):
            self.enable_trailing_stop = os.getenv('BOT_ENABLE_TRAILING_STOP').lower() in ['true', '1', 'yes']
        if os.getenv('BOT_BREAKEVEN_PIPS'):
            self.breakeven_after_pips = float(os.getenv('BOT_BREAKEVEN_PIPS'))
        if os.getenv('BOT_TRAIL_DISTANCE'):
            self.trail_stop_distance = float(os.getenv('BOT_TRAIL_DISTANCE'))
        if os.getenv('BOT_TRAIL_TRIGGER'):
            self.trail_trigger_pips = float(os.getenv('BOT_TRAIL_TRIGGER'))
        if os.getenv('BOT_EVENT_BLOCKING'):
            self.enable_event_blocking = os.getenv('BOT_EVENT_BLOCKING', 'true').lower() == 'true'
    
    def validate(self) -> bool:
        """Validate configuration has required credentials"""
        if not self.api_key:
            raise ValueError("Missing Capital.com API key")
        if not self.username:
            raise ValueError("Missing Capital.com username")
        if not self.password:
            raise ValueError("Missing Capital.com password")
        return True
    
    @classmethod
    def for_paper_trading(cls) -> 'TradingConfig':
        """Create config for paper trading (DEMO environment)"""
        config = cls(environment='demo')
        config.validate()
        return config
    
    @classmethod
    def for_live_trading(cls) -> 'TradingConfig':
        """Create config for live trading (LIVE environment)"""
        config = cls(environment='live')
        config.validate()
        return config
