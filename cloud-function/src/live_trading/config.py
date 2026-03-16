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
    
    # GOLD M15 Strategy Parameters (from optimization results)
    supertrend_period: int = 7
    supertrend_multiplier: float = 2.0
    sma_fast: int = 21
    sma_slow: int = 50
    bb_period: int = 20
    bb_std: float = 2.0
    atr_sl_multiplier: float = 0.7
    atr_tp_multiplier: float = 2.5
    
    # Position sizing
    position_size: float = 0.1  # Size per trade (adjust based on capital)
    max_capital_per_trade: float = 300.0  # Max $300 margin per trade
    
    # Risk management
    max_open_positions: int = 1  # Only 1 GOLD position at a time
    
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
            # WebSocket uses same endpoint for both demo and live
            self.ws_url = 'wss://api-streaming-capital.backend-capital.com/connect'
        else:
            self.rest_base_url = 'https://api-capital.backend-capital.com'
            self.ws_url = 'wss://api-streaming-capital.backend-capital.com/connect'
    
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
