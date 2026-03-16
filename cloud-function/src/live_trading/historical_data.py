"""
Fetch historical OHLC data from Capital.com REST API
"""
import requests
import logging
from datetime import datetime, timedelta
from typing import List, Dict

logger = logging.getLogger(__name__)


def fetch_historical_candles(
    rest_client,
    epic: str,
    resolution: str = 'MINUTE_5',
    num_candles: int = 30
) -> List[Dict]:
    """
    Fetch historical OHLC candles from Capital.com API
    
    Args:
        rest_client: CapitalRestClient instance with valid tokens
        epic: Instrument epic (e.g., 'GOLD')
        resolution: Candle resolution (MINUTE_5, MINUTE_15, HOUR, DAY)
        num_candles: Number of candles to fetch
    
    Returns:
        List of candle dictionaries with OHLC data
    """
    try:
        # Capital.com historical prices API endpoint
        # GET /api/v1/prices/{epic}
        tokens = rest_client.get_tokens()
        url = f"{rest_client.config.rest_base_url}/api/v1/prices/{epic}"
        
        headers = {
            'CST': tokens['CST'],
            'X-SECURITY-TOKEN': tokens['X-SECURITY-TOKEN'],
            'Content-Type': 'application/json'
        }
        
        # Calculate time range - fetch only what's needed
        to_time = datetime.utcnow()
        
        # M5 = 5 minutes per candle
        minutes_back = num_candles * 5
        from_time = to_time - timedelta(minutes=minutes_back)
        
        params = {
            'resolution': resolution,
            'max': num_candles,
            'from': from_time.strftime('%Y-%m-%dT%H:%M:%S'),
            'to': to_time.strftime('%Y-%m-%dT%H:%M:%S')
        }
        
        logger.info(f"📊 Fetching {num_candles} historical {resolution} candles for {epic}")
        response = requests.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        
        data = response.json()
        prices = data.get('prices', [])
        
        if not prices:
            logger.warning(f"⚠️ No historical data returned for {epic}")
            return []
        
        # Convert to our candle format
        candles = []
        for price in prices[-num_candles:]:  # Take last N candles
            candle = {
                'epic': epic,
                'timestamp': price.get('snapshotTime', price.get('snapshotTimeUTC')),
                'open': float(price.get('openPrice', {}).get('bid', 0)),
                'high': float(price.get('highPrice', {}).get('bid', 0)),
                'low': float(price.get('lowPrice', {}).get('bid', 0)),
                'close': float(price.get('closePrice', {}).get('bid', 0)),
                'volume': int(price.get('lastTradedVolume', 0))
            }
            candles.append(candle)
        
        logger.info(f"✅ Fetched {len(candles)} historical candles (oldest: {candles[0]['timestamp']}, newest: {candles[-1]['timestamp']})")
        return candles
    
    except requests.exceptions.HTTPError as e:
        logger.error(f"❌ Failed to fetch historical data: {e}")
        if e.response.status_code == 404:
            logger.error(f"❌ Epic '{epic}' not found or historical data not available")
        return []
    except Exception as e:
        logger.error(f"❌ Error fetching historical candles: {e}")
        return []
