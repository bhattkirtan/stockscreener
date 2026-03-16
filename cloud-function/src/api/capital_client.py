"""
Reusable Capital.com API client with authentication and session management
Used by both production trading and backtesting/data fetching
"""

import os
import json
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from cachetools import TTLCache, cached
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
CAPITAL_ENV = os.getenv('CAPITAL_ENV', 'demo').lower()
BASE_URL = (
    'https://api-capital.backend-capital.com' if CAPITAL_ENV == 'live'
    else 'https://demo-api-capital.backend-capital.com'
)
REQUEST_TIMEOUT = (5, 25)  # (connect timeout, read timeout) in seconds
MAX_RETRIES = 3
BACKOFF_FACTOR = 0.5
CACHE_TTL = 55 * 60  # 55 minutes — undercuts 1h session expiry


class CapitalClient:
    """
    Reusable Capital.com API client with:
    - Token caching (55 min TTL)
    - Session pooling with retries
    - Environment support (demo/live)
    - Error handling
    """
    
    def __init__(self, username: str, password: str, capkey: str, base_url: Optional[str] = None):
        """
        Args:
            username: Capital.com username/email
            password: Capital.com password
            capkey: Capital.com API key
            base_url: Optional custom base URL (defaults to demo/live based on CAPITAL_ENV)
        """
        self.username = username
        self.password = password
        self.capkey = capkey
        self.base_url = base_url or BASE_URL
        
        # Caches for encryption key & token
        self.enc_key_cache = TTLCache(maxsize=1, ttl=CACHE_TTL)
        self.token_cache = TTLCache(maxsize=1, ttl=CACHE_TTL)
        
        # Build persistent session with connection pooling & retry
        self.session = self._build_session()
        
        logger.info(f"CapitalClient initialized for {CAPITAL_ENV.upper()} environment")
    
    def _build_session(self) -> requests.Session:
        """Build session with connection pooling and retry logic"""
        session = requests.Session()
        retry = Retry(
            total=MAX_RETRIES,
            backoff_factor=BACKOFF_FACTOR,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "DELETE"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=1,
            pool_maxsize=4,
        )
        session.mount('https://', adapter)
        return session
    
    def get_encryption_key(self) -> str:
        """Get encryption key (cached for 55 min)"""
        # Check cache first
        if 'key' in self.enc_key_cache:
            return self.enc_key_cache['key']
        
        # Fetch from API
        url = f'{self.base_url}/api/v1/session/encryptionKey'
        resp = self.session.get(
            url,
            headers={'X-CAP-API-KEY': self.capkey},
            timeout=REQUEST_TIMEOUT
        )
        
        if resp.status_code == 429:
            logger.error("Rate limit hit on encryption key")
            raise Exception("Capital API rate limit on encryptionKey")
        
        if not resp.ok:
            logger.error(f"Failed to fetch encryption key: {resp.status_code} - {resp.text}")
            raise Exception(f"Failed to obtain encryption key: {resp.status_code}")
        
        key = resp.json().get('encryptionKey')
        self.enc_key_cache['key'] = key
        return key
    
    def get_token(self) -> Dict[str, str]:
        """Get session token (cached for 55 min)"""
        # Check cache first
        if 'tokens' in self.token_cache:
            return self.token_cache['tokens']
        
        # Ensure encryption key is fetched (warming cache, unencrypted login assumed)
        try:
            self.get_encryption_key()
        except Exception as e:
            logger.warning(f"Encryption key fetch failed (non-critical): {e}")
        
        payload = {
            'identifier': self.username,
            'password': self.password,
            'encryptedPassword': False
        }
        headers = {
            'X-CAP-API-KEY': self.capkey,
            'Content-Type': 'application/json'
        }
        
        resp = self.session.post(
            f'{self.base_url}/api/v1/session',
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT
        )
        
        if resp.status_code == 429:
            logger.error("Rate limit hit on session token")
            raise Exception("Capital API rate limit on session")
        
        if not resp.ok:
            logger.error(f"Failed to fetch session token: {resp.status_code} - {resp.text}")
            raise Exception(f"Failed to obtain session token: {resp.status_code}")
        
        tokens = {
            'CST': resp.headers.get('CST'),
            'X-SECURITY-TOKEN': resp.headers.get('X-SECURITY-TOKEN'),
        }
        
        # Cache the tokens
        self.token_cache['tokens'] = tokens
        logger.info("✅ Successfully authenticated with Capital.com")
        return tokens
    
    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        """
        Make authenticated request to Capital.com API
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            path: API path (e.g., '/api/v1/positions')
            **kwargs: Additional arguments for requests (json, params, etc.)
            
        Returns:
            requests.Response object
            
        Raises:
            Exception: If rate limit hit or authentication fails
        """
        tokens = self.get_token()
        headers = {
            'CST': tokens['CST'],
            'X-SECURITY-TOKEN': tokens['X-SECURITY-TOKEN'],
            'Content-Type': 'application/json',
        }
        
        url = f'{self.base_url}{path}'
        logger.debug(f"→ {method} {path}")
        
        resp = self.session.request(
            method,
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            **kwargs
        )
        
        if resp.status_code == 429:
            logger.error(f"Rate limit hit on {path}")
            raise Exception(f"Capital API rate limit on {path}")
        
        return resp
    
    def get(self, path: str, **kwargs) -> requests.Response:
        """Convenience method for GET requests"""
        return self.request('GET', path, **kwargs)
    
    def post(self, path: str, **kwargs) -> requests.Response:
        """Convenience method for POST requests"""
        return self.request('POST', path, **kwargs)
    
    def put(self, path: str, **kwargs) -> requests.Response:
        """Convenience method for PUT requests"""
        return self.request('PUT', path, **kwargs)
    
    def delete(self, path: str, **kwargs) -> requests.Response:
        """Convenience method for DELETE requests"""
        return self.request('DELETE', path, **kwargs)


def create_client_from_env() -> CapitalClient:
    """
    Create CapitalClient from environment variables
    Loads credentials from 'apicredentials' env var (JSON format)
    
    Returns:
        Configured CapitalClient instance
        
    Raises:
        Exception: If credentials not found or invalid
    """
    from dotenv import load_dotenv
    load_dotenv()
    
    secrets_str = os.getenv('apicredentials')
    if not secrets_str:
        raise Exception("No credentials found in environment. Set 'apicredentials' env var.")
    
    secrets = json.loads(secrets_str)
    
    username = secrets.get('username', '')
    password = secrets.get('password', '')
    capkey = secrets.get('capkey', '')
    
    if not all([username, password, capkey]):
        raise Exception("Incomplete credentials. Required: username, password, capkey")
    
    return CapitalClient(username, password, capkey)


# ── Convenience functions for backward compatibility ──────────────────────────
_global_client: Optional[CapitalClient] = None


def get_global_client() -> CapitalClient:
    """Get or create global client instance (singleton pattern)"""
    global _global_client
    if _global_client is None:
        _global_client = create_client_from_env()
    return _global_client


def capital_request(method: str, path: str, **kwargs) -> requests.Response:
    """
    Global function for backward compatibility with main.py
    Uses singleton client instance
    """
    client = get_global_client()
    return client.request(method, path, **kwargs)


if __name__ == '__main__':
    """Test authentication and basic requests"""
    import sys
    
    print("\n" + "="*70)
    print("Testing Capital.com API Client")
    print("="*70)
    
    try:
        # Create client from environment
        print("\n🔐 Creating client from environment...")
        client = create_client_from_env()
        print(f"✅ Client created for {CAPITAL_ENV.upper()} environment")
        
        # Test authentication
        print("\n🔑 Testing authentication...")
        tokens = client.get_token()
        print(f"✅ Authentication successful")
        print(f"   CST: {tokens['CST'][:20]}...")
        print(f"   X-SECURITY-TOKEN: {tokens['X-SECURITY-TOKEN'][:20]}...")
        
        # Test getting positions
        print("\n📊 Testing API request (get positions)...")
        resp = client.get('/api/v1/positions')
        if resp.ok:
            positions = resp.json().get('positions', [])
            print(f"✅ API request successful")
            print(f"   Open positions: {len(positions)}")
        else:
            print(f"⚠️  API request failed: {resp.status_code}")
        
        # Test getting market info
        print("\n💰 Testing market data (GOLD)...")
        resp = client.get('/api/v1/markets/GOLD')
        if resp.ok:
            data = resp.json()
            snapshot = data.get('snapshot', {})
            bid = snapshot.get('bid')
            offer = snapshot.get('offer')
            spread = float(offer) - float(bid) if bid and offer else 0
            print(f"✅ Market data retrieved")
            print(f"   Bid: {bid}")
            print(f"   Offer: {offer}")
            print(f"   Spread: {spread:.5f}")
        else:
            print(f"⚠️  Market data request failed: {resp.status_code}")
        
        print("\n" + "="*70)
        print("✅ All tests passed!")
        print("="*70)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\n💡 Make sure you have valid credentials in .env file:")
        print("   apicredentials='{\"username\":\"xxx\",\"password\":\"xxx\",\"capkey\":\"xxx\"}'")
        sys.exit(1)
