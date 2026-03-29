"""
Capital.com REST API Client

Handles authentication and REST API calls for:
- Session management
- Account information
- Market search/discovery
- Position management (create, update, close)
"""

import requests
import logging
from datetime import datetime
from typing import Dict, Optional, List
from cachetools import TTLCache, cached

from .config import TradingConfig

logger = logging.getLogger(__name__)


class CapitalRestClient:
    """REST API client for Capital.com"""
    
    def __init__(self, config: TradingConfig):
        self.config = config
        self.cst = None
        self.security_token = None
        
        # Cache tokens for 55 minutes (before 60 min expiry)
        self._token_cache = TTLCache(maxsize=1, ttl=55*60)
    
    def create_session(self) -> Dict[str, str]:
        """
        Authenticate with Capital.com and get session tokens
        Returns: dict with CST and X-SECURITY-TOKEN
        """
        url = f"{self.config.rest_base_url}/api/v1/session"
        headers = {
            'X-CAP-API-KEY': self.config.api_key,
            'Content-Type': 'application/json'
        }
        payload = {
            'identifier': self.config.username,
            'password': self.config.password,
            'encryptedPassword': False
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            response.raise_for_status()
            
            self.cst = response.headers['CST']
            self.security_token = response.headers['X-SECURITY-TOKEN']
            
            logger.info(f"✅ Session created successfully ({self.config.environment})")
            return {
                'CST': self.cst,
                'X-SECURITY-TOKEN': self.security_token,
                'account': response.json()
            }
        
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                logger.error("❌ Rate limit hit on session creation")
            raise Exception(f"Failed to create session: {e}")
        except Exception as e:
            logger.error(f"❌ Session creation error: {e}")
            raise
    
    def get_tokens(self) -> Dict[str, str]:
        """Get current session tokens (cached)"""
        if not self.cst or not self.security_token:
            self.create_session()
        return {
            'CST': self.cst,
            'X-SECURITY-TOKEN': self.security_token
        }
    
    def _request(self, method: str, path: str, retry_on_401: bool = True, **kwargs) -> requests.Response:
        """Make authenticated request to Capital.com API with auto-refresh on 401"""
        tokens = self.get_tokens()
        headers = kwargs.pop('headers', {})
        headers.update({
            'CST': tokens['CST'],
            'X-SECURITY-TOKEN': tokens['X-SECURITY-TOKEN'],
            'Content-Type': 'application/json'
        })
        
        url = f"{self.config.rest_base_url}{path}"
        
        try:
            response = requests.request(method, url, headers=headers, **kwargs)
            
            if response.status_code == 429:
                logger.error(f"❌ Rate limit hit on {path}")
                raise Exception(f"Rate limit exceeded on {path}")
            
            # Handle 401 Unauthorized - session expired, refresh and retry once
            if response.status_code == 401 and retry_on_401:
                logger.warning(f"⚠️ 401 Unauthorized on {path} - refreshing session...")
                # Clear tokens to force re-authentication
                self.cst = None
                self.security_token = None
                # Retry request with new session (prevent infinite loop)
                return self._request(method, path, retry_on_401=False, headers=headers, **kwargs)
            
            response.raise_for_status()
            return response
        
        except requests.exceptions.HTTPError as e:
            logger.error(f"❌ Request failed: {method} {path} - {e}")
            raise
    
    def find_gold_epic(self) -> str:
        """
        Discover GOLD epic code via markets search
        Returns: epic code (e.g., "CS.D.CFDGOLD.CFD.IP")
        """
        if self.config.gold_epic:
            return self.config.gold_epic
        
        try:
            response = self._request('GET', '/api/v1/markets', params={'searchTerm': 'GOLD'})
            markets = response.json().get('markets', [])
            
            # Find XAU/USD or GOLD spot CFD
            for market in markets:
                if 'GOLD' in market.get('instrumentName', '').upper() or \
                   'XAU/USD' in market.get('instrumentName', ''):
                    epic = market.get('epic')
                    logger.info(f"✅ Found GOLD epic: {epic} - {market.get('instrumentName')}")
                    self.config.gold_epic = epic
                    return epic
            
            raise Exception("GOLD market not found")
        
        except Exception as e:
            logger.error(f"❌ Failed to find GOLD epic: {e}")
            raise
    
    def get_account_info(self) -> Dict:
        """Get account information"""
        response = self._request('GET', '/api/v1/accounts')
        return response.json()
    
    def get_open_positions(self) -> List[Dict]:
        """Get all open positions"""
        response = self._request('GET', '/api/v1/positions')
        return response.json().get('positions', [])
    
    def get_position_for_epic(self, epic: str) -> Optional[Dict]:
        """
        Get open position for specific epic (instrument).
        Returns position dict if exists, None if no position.
        
        Args:
            epic: Instrument epic code (e.g., 'GOLD')
            
        Returns:
            Dict with position details if found, None otherwise
            Position includes: dealId, dealReference, direction, size, level (entry), stopLevel, limitLevel
        """
        positions = self.get_open_positions()
        for item in positions:
            pos = item.get('position', {})
            mkt = item.get('market', {})
            if mkt.get('epic') == epic:
                return {
                    'deal_id': pos.get('dealId'),
                    'deal_reference': pos.get('dealReference'),
                    'direction': pos.get('direction'),
                    'size': pos.get('size'),
                    'entry_price': pos.get('level'),
                    'stop_loss': pos.get('stopLevel'),
                    'take_profit': pos.get('limitLevel'),
                    'created_date': pos.get('createdDate')
                }
        return None
    
    def create_position(
        self,
        epic: str,
        direction: str,  # 'BUY' or 'SELL'
        size: float,
        stop_level: Optional[float] = None,
        profit_level: Optional[float] = None
    ) -> Dict:
        """
        Create a new position
        
        Args:
            epic: Instrument epic code
            direction: 'BUY' or 'SELL'
            size: Position size
            stop_level: Stop loss price
            profit_level: Take profit price
        
        Returns: Response with dealId
        """
        payload = {
            'epic': epic,
            'direction': direction,
            'size': size,
            'guaranteedStop': False
        }
        
        if stop_level is not None:
            payload['stopLevel'] = stop_level
        if profit_level is not None:
            payload['profitLevel'] = profit_level
        
        logger.info(f"📊 Creating {direction} position: {epic} size={size} SL={stop_level} TP={profit_level}")
        response = self._request('POST', '/api/v1/positions', json=payload)
        result = response.json()
        logger.info(f"✅ Position created: dealId={result.get('dealReference')}")
        return result
    
    def update_position(
        self,
        deal_id: str,
        stop_level: Optional[float] = None,
        profit_level: Optional[float] = None
    ) -> Dict:
        """Update stop loss or take profit for existing position"""
        payload = {}
        if stop_level is not None:
            payload['stopLevel'] = stop_level
        if profit_level is not None:
            payload['profitLevel'] = profit_level
        
        logger.info(f"📊 Updating position {deal_id}: SL={stop_level} TP={profit_level}")
        response = self._request('PUT', f'/api/v1/positions/{deal_id}', json=payload)
        logger.info(f"✅ Position updated: {deal_id}")
        return response.json()
    
    def close_position(self, deal_id: str) -> Dict:
        """Close an open position"""
        logger.info(f"📊 Closing position: {deal_id}")
        response = self._request('DELETE', f'/api/v1/positions/{deal_id}')
        logger.info(f"✅ Position closed: {deal_id}")
        return response.json()

    def get_historical_candles(self, epic: str, resolution: str = 'MINUTE_5', count: int = 100) -> List[Dict]:
        """
        Fetch historical OHLC candles via REST API.
        Returns list of candle dicts in the same format as WebSocket candle callbacks.
        """
        response = self._request('GET', f'/api/v1/prices/{epic}', params={
            'resolution': resolution,
            'max': count
        })
        data = response.json()
        candles = []
        for item in data.get('prices', []):
            snap = item.get('snapshotTimeUTC', '')
            # Handle ISO "2026-03-17T12:55:00" and slashed "2026/03/17 12:55:00:000"
            try:
                dt = datetime.fromisoformat(snap[:19].replace('/', '-').replace(' ', 'T'))
            except ValueError:
                logger.warning(f"⚠️ Could not parse candle timestamp: {snap!r}")
                continue
            epoch_ms = int(dt.timestamp() * 1000)

            def mid(price_obj):
                bid = price_obj.get('bid') or 0
                ask = price_obj.get('ask') or 0
                return (bid + ask) / 2.0 if bid and ask else (bid or ask)

            candles.append({
                'epic': epic,
                'resolution': resolution,
                'open': mid(item.get('openPrice', {})),
                'high': mid(item.get('highPrice', {})),
                'low': mid(item.get('lowPrice', {})),
                'close': mid(item.get('closePrice', {})),
                'volume': item.get('lastTradedVolume', 0),
                'timestamp': epoch_ms,
                'time': dt,
            })
        logger.info(f"📥 Fetched {len(candles)} historical {resolution} candles for {epic}")
        return candles
