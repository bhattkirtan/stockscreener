"""
Capital.com Authentication Module
Calls deployed capitalComService Cloud Function
"""

from dotenv import load_dotenv
import json
import logging
import os
import requests
from cachetools import TTLCache, cached

# Setup logging
logger = logging.getLogger(__name__)

# Load secrets from .env
load_dotenv()
secret_json = os.getenv('apicredentials') or '{}'
secrets = json.loads(secret_json)
api_key = secrets['apikey']

# Deployed Cloud Function URL (DEMO service)
CAPITAL_SERVICE_URL = os.getenv(
    'CAPITAL_SERVICE_URL',
    'https://capitalcomservice-6ovej2yaoa-uc.a.run.app'
)

# Cache for session tokens (TTL 55 minutes)
token_cache = TTLCache(maxsize=1, ttl=55*60)


@cached(token_cache)
def get_token() -> dict:
    """
    Get session tokens from deployed capitalComService Cloud Function
    Cached for 55 minutes
    
    Returns:
        dict: {'CST': str, 'X-SECURITY-TOKEN': str}
    """
    url = f'{CAPITAL_SERVICE_URL}/token'
    
    headers = {
        'Content-Type': 'application/json'
    }
    
    payload = {
        'key': api_key
    }
    
    logger.debug(f"Requesting token from: {url}")
    
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        
        if resp.status_code == 429:
            raise Exception("Capital Service rate limit")
        
        if not resp.ok:
            logger.error(f"Token request failed: {resp.status_code} - {resp.text}")
            raise Exception(f"Failed to obtain session token: {resp.status_code}")
        
        data = resp.json()
        
        return {
            'CST': data.get('CST'),
            'X-SECURITY-TOKEN': data.get('X-SECURITY-TOKEN')
        }
        
    except requests.exceptions.Timeout:
        raise Exception("Capital Service timeout (10s)")
    except requests.exceptions.ConnectionError:
        raise Exception("Cannot connect to Capital Service")
    except Exception as e:
        logger.error(f"Token request error: {e}")
        raise


def capital_request(method: str, path: str, **kwargs) -> requests.Response:
    """
    Helper to call Capital.com endpoints with proper authentication headers
    
    Args:
        method: HTTP method (GET, POST, etc.)
        path: API path (e.g., '/api/v1/positions')
        **kwargs: Additional arguments to pass to requests.request()
    
    Returns:
        requests.Response: API response
    """
    tokens = get_token()
    
    headers = kwargs.pop('headers', {})
    headers.update({
        'CST': tokens['CST'],
        'X-SECURITY-TOKEN': tokens['X-SECURITY-TOKEN'],
    })
    return headers

def clear_cache():
    """Clear authentication cache (force re-auth on next call)"""
    token_cache.clear()
    logger.info("🔄 Authentication cache cleared")

def test_authentication():
    """Test authentication with Capital.com via Cloud Function"""
    print("=" * 60)
    print("Testing Capital.com Authentication via Cloud Function")
    print("=" * 60)
    print(f"Service URL: {CAPITAL_SERVICE_URL}")
    print()
    
    try:
        print("Requesting session tokens...")
        tokens = get_token()
        print(f"✅ Authentication successful!")
        print(f"   CST: {tokens['CST'][:30]}...")
        print(f"   Security Token: {tokens['X-SECURITY-TOKEN'][:30]}...")
        print()
        print("✅ Bot is ready to connect to Capital.com WebSocket!")
    except Exception as e:
        print(f"❌ Authentication failed: {e}")
        print()
        print("Troubleshooting:")
        print("  1. Check .env file has correct credentials")
        print("  2. Verify Cloud Function is deployed and accessible")
        print(f"  3. Test manually: curl -X POST {CAPITAL_SERVICE_URL}/token -H 'Content-Type: application/json' -d '{{\"key\":\"YOUR_API_KEY\"}}'")
        import sys
        sys.exit(1)