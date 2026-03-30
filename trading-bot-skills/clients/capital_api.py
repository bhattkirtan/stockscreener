"""
Capital.com API Client Wrapper

Handles REST API authentication and trading operations.
"""
import requests
import logging
from datetime import datetime
from typing import Dict, Optional, List
from cachetools import TTLCache

logger = logging.getLogger(__name__)


class CapitalAPIClient:
    """
    Capital.com REST API client for trading operations
    
    Features:
    - Session token caching (55 min TTL)
    - Auto-refresh on 401 Unauthorized
    - Support for demo/live environments
    - Position/order management
    """
    
    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        api_key: Optional[str] = None,
        environment: str = 'demo'
    ):
        """
        Initialize Capital.com API client
        
        Args:
            username: Capital.com username/email (or set CAPITAL_USERNAME env var)
            password: Capital.com password (or set CAPITAL_PASSWORD env var)
            api_key: Capital.com API key (or set CAPITAL_API_KEY env var)
            environment: 'demo' or 'live' (or set CAPITAL_ENVIRONMENT env var)
        """
        import os
        
        # Use env vars as fallback; CAPITAL_IDENTIFIER is the email used to log in
        self.username = username or os.getenv('CAPITAL_IDENTIFIER') or os.getenv('CAPITAL_USERNAME')
        self.password = password or os.getenv('CAPITAL_PASSWORD')
        self.api_key = api_key or os.getenv('CAPITAL_API_KEY')
        self.environment = (environment or os.getenv('CAPITAL_ENVIRONMENT', 'demo')).lower()
        
        # Set base URL based on environment
        if self.environment == 'live':
            self.base_url = 'https://api-capital.backend-capital.com'
        else:
            self.base_url = 'https://demo-api-capital.backend-capital.com'
        
        # Session tokens
        self.cst = None
        self.security_token = None
        
        # Token cache (55 min TTL, before 60 min expiry)
        self._token_cache = TTLCache(maxsize=1, ttl=55*60)
        
        logger.info(f"✅ CapitalAPIClient initialized ({self.environment.upper()} mode)")
    
    def create_session(self) -> Dict[str, str]:
        """
        Authenticate with Capital.com and get session tokens
        
        Returns:
            dict with CST and X-SECURITY-TOKEN
            
        Raises:
            Exception on authentication failure
        """
        url = f"{self.base_url}/api/v1/session"
        headers = {
            'X-CAP-API-KEY': self.api_key,
            'Content-Type': 'application/json'
        }
        payload = {
            'identifier': self.username,
            'password': self.password,
            'encryptedPassword': False
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            response.raise_for_status()
            
            self.cst = response.headers.get('CST')
            self.security_token = response.headers.get('X-SECURITY-TOKEN')
            
            if not self.cst or not self.security_token:
                raise Exception("Missing CST or X-SECURITY-TOKEN in response headers")
            
            # Cache tokens
            self._token_cache['valid'] = True
            
            logger.info(f"✅ Session created successfully ({self.environment})")
            return {
                'CST': self.cst,
                'X-SECURITY-TOKEN': self.security_token,
                'account': response.json()
            }
        
        except requests.exceptions.HTTPError as e:
            if e.response and e.response.status_code == 429:
                logger.error("❌ Rate limit hit on session creation")
                raise Exception("Capital.com API rate limit exceeded")
            raise Exception(f"Failed to create session: {e}")
        
        except Exception as e:
            logger.error(f"❌ Session creation error: {e}")
            raise
    
    def get_tokens(self) -> Dict[str, str]:
        """
        Get current session tokens (creates session if needed)
        
        Returns:
            dict with CST and X-SECURITY-TOKEN
        """
        if not self.cst or not self.security_token or 'valid' not in self._token_cache:
            self.create_session()
        
        return {
            'CST': self.cst,
            'X-SECURITY-TOKEN': self.security_token
        }
    
    def _request(
        self,
        method: str,
        path: str,
        retry_on_401: bool = True,
        **kwargs
    ) -> requests.Response:
        """
        Make authenticated request to Capital.com API
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            path: API endpoint path
            retry_on_401: Auto-refresh session on 401 and retry
            **kwargs: Additional arguments for requests
            
        Returns:
            requests.Response object
            
        Raises:
            Exception on request failure
        """
        tokens = self.get_tokens()
        headers = kwargs.pop('headers', {})
        headers.update({
            'CST': tokens['CST'],
            'X-SECURITY-TOKEN': tokens['X-SECURITY-TOKEN'],
            'Content-Type': 'application/json'
        })
        
        url = f"{self.base_url}{path}"
        
        try:
            response = requests.request(method, url, headers=headers, timeout=15, **kwargs)
            
            # Handle rate limiting
            if response.status_code == 429:
                logger.error(f"❌ Rate limit hit on {path}")
                raise Exception(f"Rate limit exceeded on {path}")
            
            # Handle 401 Unauthorized - session expired
            if response.status_code == 401 and retry_on_401:
                logger.warning(f"⚠️ 401 Unauthorized on {path} - refreshing session...")
                # Clear cached tokens
                self._token_cache.clear()
                self.cst = None
                self.security_token = None
                # Retry once with new session
                return self._request(method, path, retry_on_401=False, headers=headers, **kwargs)
            
            response.raise_for_status()
            return response
        
        except requests.exceptions.HTTPError as e:
            logger.error(f"❌ Request failed: {method} {path} - {e}")
            raise
    
    # ────────────────────────────────────────────────────────────────────
    #  Trading Operations
    # ────────────────────────────────────────────────────────────────────
    
    def place_order(
        self,
        epic: str,
        direction: str,
        size: float,
        stop_level: Optional[float] = None,
        profit_level: Optional[float] = None,
        guaranteed_stop: bool = False
    ) -> Dict:
        """
        Place a market order

        Args:
            epic: Market identifier (e.g., 'CS.D.CFDGOLD.CFD.IP')
            direction: 'BUY' or 'SELL'
            size: Position size (e.g., 0.5)
            stop_level: Stop loss price (optional)
            profit_level: Take profit price (optional)
            guaranteed_stop: Use guaranteed stop loss (default: False)

        Returns:
            dict with dealReference and dealId

        Raises:
            Exception on order placement failure
        """
        path = '/api/v1/positions'
        payload = {
            'epic': epic,
            'direction': direction.upper(),
            'size': size,
            'guaranteedStop': guaranteed_stop,
        }
        
        # Add stop loss if provided
        if stop_level is not None:
            payload['stopLevel'] = stop_level
        
        # Add take profit if provided
        if profit_level is not None:
            payload['profitLevel'] = profit_level
        
        try:
            response = self._request('POST', path, json=payload)
            result = response.json()
            
            deal_reference = result.get('dealReference')
            logger.info(f"✅ Order placed: {direction} {size} {epic} (ref: {deal_reference})")
            
            return result
        
        except Exception as e:
            logger.error(f"❌ Failed to place order: {e}")
            raise
    
    def get_open_positions(self) -> List[Dict]:
        """
        Get all open positions
        
        Returns:
            List of position dicts
        """
        try:
            response = self._request('GET', '/api/v1/positions')
            positions = response.json().get('positions', [])
            logger.info(f"✅ Retrieved {len(positions)} open positions")
            return positions
        
        except Exception as e:
            logger.error(f"❌ Failed to get positions: {e}")
            raise
    
    def close_position(self, deal_id: str) -> Dict:
        """
        Close an open position

        Args:
            deal_id: Deal ID of the position to close

        Returns:
            dict with dealReference
        """
        path = f'/api/v1/positions/{deal_id}'

        try:
            response = self._request('DELETE', path)
            result = response.json()

            deal_reference = result.get('dealReference')
            logger.info(f"✅ Position closed: {deal_id} (ref: {deal_reference})")

            return result

        except Exception as e:
            logger.error(f"❌ Failed to close position {deal_id}: {e}")
            raise
    
    def update_position(
        self,
        deal_id: str,
        stop_level: Optional[float] = None,
        profit_level: Optional[float] = None
    ) -> Dict:
        """
        Update stop loss or take profit on existing position
        
        Args:
            deal_id: Deal ID of the position
            stop_level: New stop loss price (optional)
            profit_level: New take profit price (optional)
            
        Returns:
            dict with dealReference
        """
        path = f'/api/v1/positions/{deal_id}'
        payload = {}
        
        if stop_level is not None:
            payload['stopLevel'] = stop_level
        
        if profit_level is not None:
            payload['profitLevel'] = profit_level
        
        if not payload:
            raise ValueError("Must provide at least one of stop_level or profit_level")
        
        try:
            response = self._request('PUT', path, json=payload)
            result = response.json()
            
            logger.info(f"✅ Position updated: {deal_id}")
            return result
        
        except Exception as e:
            logger.error(f"❌ Failed to update position {deal_id}: {e}")
            raise
    
    def get_account_info(self) -> Dict:
        """
        Get account information (balance, equity, etc.)
        
        Returns:
            dict with account details
        """
        try:
            response = self._request('GET', '/api/v1/accounts')
            account = response.json()
            logger.info(f"✅ Retrieved account info")
            return account
        
        except Exception as e:
            logger.error(f"❌ Failed to get account info: {e}")
            raise
    
    def find_market(self, search_term: str) -> List[Dict]:
        """
        Search for markets
        
        Args:
            search_term: Search query (e.g., 'GOLD', 'EUR/USD')
            
        Returns:
            List of market dicts
        """
        try:
            response = self._request('GET', '/api/v1/markets', params={'searchTerm': search_term})
            markets = response.json().get('markets', [])
            logger.info(f"✅ Found {len(markets)} markets for '{search_term}'")
            return markets
        
        except Exception as e:
            logger.error(f"❌ Failed to search markets: {e}")
            raise
    
    def get_historical_prices(
        self,
        epic: str,
        resolution: str = 'MINUTE_5',
        max_bars: int = 100,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None
    ) -> List[Dict]:
        """
        Fetch historical OHLC candles from Capital.com API
        
        Args:
            epic: Market identifier (e.g., 'CS.D.CFDGOLD.CFD.IP')
            resolution: Candle resolution - MINUTE, MINUTE_5, MINUTE_15, HOUR, DAY, WEEK
            max_bars: Maximum number of candles to fetch (default: 100, max: 1000)
            from_date: Start date in ISO format 'YYYY-MM-DDTHH:MM:SS' (optional)
            to_date: End date in ISO format 'YYYY-MM-DDTHH:MM:SS' (optional)
            
        Returns:
            List of candle dicts with OHLC data:
            [
                {
                    'timestamp': '2026-03-29T10:00:00',
                    'open': 2650.5,
                    'high': 2652.3,
                    'low': 2649.8,
                    'close': 2651.2,
                    'volume': 1234
                },
                ...
            ]
            
        Raises:
            Exception on request failure
            
        Example:
            # Get last 100 M5 candles for GOLD
            candles = client.get_historical_prices('CS.D.CFDGOLD.CFD.IP', 'MINUTE_5', 100)
            
            # Get specific date range
            candles = client.get_historical_prices(
                'CS.D.CFDGOLD.CFD.IP',
                'MINUTE_5',
                max_bars=500,
                from_date='2026-03-01T00:00:00',
                to_date='2026-03-29T23:59:59'
            )
        """
        from datetime import datetime, timedelta
        
        path = f'/api/v1/prices/{epic}'
        
        # Build query parameters
        params = {
            'resolution': resolution,
            'max': min(max_bars, 1000)  # Capital.com max is 1000
        }
        
        # If date range not provided, calculate based on resolution and bars
        if not from_date:
            to_dt = datetime.utcnow() if not to_date else datetime.fromisoformat(to_date.replace('Z', ''))
            
            # Calculate minutes per bar based on resolution
            minutes_per_bar = {
                'MINUTE': 1,
                'MINUTE_5': 5,
                'MINUTE_15': 15,
                'MINUTE_30': 30,
                'HOUR': 60,
                'HOUR_4': 240,
                'DAY': 1440,
                'WEEK': 10080
            }.get(resolution, 5)
            
            # Add 50% buffer for market closures/gaps
            minutes_back = max_bars * minutes_per_bar * 1.5
            from_dt = to_dt - timedelta(minutes=minutes_back)
            
            from_date = from_dt.strftime('%Y-%m-%dT%H:%M:%S')
            if not to_date:
                to_date = to_dt.strftime('%Y-%m-%dT%H:%M:%S')
        
        params['from'] = from_date
        params['to'] = to_date
        
        try:
            logger.info(f"📊 Fetching {max_bars} {resolution} candles for {epic}")
            response = self._request('GET', path, params=params)
            data = response.json()
            
            prices = data.get('prices', [])
            
            if not prices:
                logger.warning(f"⚠️ No historical data returned for {epic}")
                return []
            
            # Convert to standardized candle format
            candles = []
            for price in prices[-max_bars:]:  # Take last N candles
                candle = {
                    'timestamp': price.get('snapshotTime', price.get('snapshotTimeUTC', '')),
                    'open': float(price.get('openPrice', {}).get('bid', 0)),
                    'high': float(price.get('highPrice', {}).get('bid', 0)),
                    'low': float(price.get('lowPrice', {}).get('bid', 0)),
                    'close': float(price.get('closePrice', {}).get('bid', 0)),
                    'volume': int(price.get('lastTradedVolume', 0))
                }
                candles.append(candle)
            
            logger.info(f"✅ Fetched {len(candles)} candles (oldest: {candles[0]['timestamp']}, newest: {candles[-1]['timestamp']})")
            return candles
        
        except requests.exceptions.HTTPError as e:
            if hasattr(e, 'response') and e.response.status_code == 404:
                logger.error(f"❌ Epic '{epic}' not found or historical data unavailable")
            else:
                logger.error(f"❌ Failed to fetch historical prices: {e}")
            raise
        
        except Exception as e:
            logger.error(f"❌ Error fetching historical prices: {e}")
            raise
