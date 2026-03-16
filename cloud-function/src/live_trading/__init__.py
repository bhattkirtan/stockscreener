"""
Live Trading Module - WebSocket Price Streaming

Works with any instrument: GOLD, US100, Ethereum, etc.
"""

from .capital_websocket import CapitalWebSocketClient
from .config import TradingConfig

__all__ = ['CapitalWebSocketClient', 'TradingConfig']
