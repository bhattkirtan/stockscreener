"""
Market data utilities for Capital.com API
Get spreads, bid/ask prices, and market info
"""

import requests
import logging
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class MarketDataFetcher:
    """
    Fetch real-time market data from Capital.com
    - Current spreads
    - Bid/Ask prices  
    - Market status
    - Instrument details
    """
    
    def __init__(self, data_fetcher):
        """
        Args:
            data_fetcher: CapitalComDataFetcher instance (for auth tokens)
        """
        self.fetcher = data_fetcher
    
    def get_market_details(self, epic: str) -> Optional[Dict]:
        """
        Get detailed market information for an instrument
        
        Returns spread, min deal size, margin requirements, etc.
        
        Args:
            epic: Instrument identifier (e.g., 'GOLD', 'EURUSD')
            
        Returns:
            Dict with market details or None if error
        """
        if not self.fetcher._ensure_authenticated():
            logger.error("Failed to authenticate")
            return None
        
        url = f'{self.fetcher.base_url}/api/v1/markets/{epic}'
        headers = {
            'X-CAP-API-KEY': self.fetcher.capkey,
            'CST': self.fetcher.token,
            'X-SECURITY-TOKEN': self.fetcher.security_token
        }
        
        try:
            self.fetcher._wait_for_rate_limit()
            response = requests.get(url, headers=headers, timeout=10)
            
            if not response.ok:
                logger.error(f"Failed to get market details: {response.status_code}")
                return None
            
            data = response.json()
            snapshot = data.get('snapshot', {})
            instrument = data.get('instrument', {})
            dealing_rules = data.get('dealingRules', {})
            
            return {
                'epic': epic,
                'instrument_name': instrument.get('name', ''),
                'instrument_type': instrument.get('type', ''),
                
                # Current prices
                'bid': float(snapshot.get('bid', 0)),
                'offer': float(snapshot.get('offer', 0)),  # Same as 'ask'
                'current_spread': float(snapshot.get('offer', 0)) - float(snapshot.get('bid', 0)),
                
                # Market status
                'market_status': snapshot.get('marketStatus', ''),
                'decimal_places': snapshot.get('decimalPlacesFactor', 0),
                
                # Dealing rules
                'min_deal_size': dealing_rules.get('minDealSize', {}).get('value', 0),
                'max_deal_size': dealing_rules.get('maxDealSize', {}).get('value', 0),
                'min_step_distance': dealing_rules.get('minNormalStopOrLimitDistance', {}).get('value', 0),
                
                # Margin
                'margin_factor': instrument.get('marginFactor', 0),
                'margin_factor_unit': instrument.get('marginFactorUnit', ''),
                
                # Timestamp
                'update_time': snapshot.get('updateTime', ''),
                'fetched_at': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error fetching market details: {e}")
            return None
    
    def get_current_spread(self, epic: str) -> Optional[float]:
        """
        Get current spread for an instrument
        
        Args:
            epic: Instrument identifier
            
        Returns:
            Current spread in price units or None
        """
        details = self.get_market_details(epic)
        if details:
            return details['current_spread']
        return None
    
    def get_current_prices(self, epic: str) -> Optional[Dict]:
        """
        Get current bid/ask prices
        
        Args:
            epic: Instrument identifier
            
        Returns:
            Dict with bid, ask, mid prices or None
        """
        details = self.get_market_details(epic)
        if details:
            bid = details['bid']
            ask = details['offer']
            return {
                'bid': bid,
                'ask': ask,
                'mid': (bid + ask) / 2,
                'spread': ask - bid,
                'timestamp': details['update_time']
            }
        return None
    
    def get_average_spread(self, epic: str, samples: int = 10, interval_seconds: int = 1) -> Optional[float]:
        """
        Get average spread over multiple samples
        Useful for backtesting to get realistic spread
        
        Args:
            epic: Instrument identifier
            samples: Number of samples to take
            interval_seconds: Seconds between samples
            
        Returns:
            Average spread or None
        """
        import time
        
        spreads = []
        for i in range(samples):
            spread = self.get_current_spread(epic)
            if spread is not None:
                spreads.append(spread)
            
            if i < samples - 1:  # Don't sleep after last sample
                time.sleep(interval_seconds)
        
        if spreads:
            avg_spread = sum(spreads) / len(spreads)
            logger.info(f"Average spread for {epic}: {avg_spread:.5f} (from {len(spreads)} samples)")
            return avg_spread
        
        return None


def convert_spread_to_pips(spread_price: float, pip_value: float = 0.01) -> float:
    """
    Convert price spread to pips
    
    Args:
        spread_price: Spread in price units (e.g., 0.02 for gold)
        pip_value: Value of 1 pip (0.01 for gold, 0.0001 for forex)
        
    Returns:
        Spread in pips
    """
    return spread_price / pip_value


def get_instrument_spread_config(epic: str, market_data: MarketDataFetcher) -> Dict:
    """
    Get recommended spread configuration for backtesting
    
    Args:
        epic: Instrument identifier
        market_data: MarketDataFetcher instance
        
    Returns:
        Dict with spread_pips, slippage_pips, pip_value for BacktestConfig
    """
    # Default configurations
    defaults = {
        'GOLD': {'pip_value': 1.0, 'typical_spread_pips': 0.50, 'slippage_pips': 0.05},
        'EURUSD': {'pip_value': 0.0001, 'typical_spread_pips': 0.8, 'slippage_pips': 0.3},
        'GBPUSD': {'pip_value': 0.0001, 'typical_spread_pips': 1.0, 'slippage_pips': 0.3},
        'USDJPY': {'pip_value': 0.01, 'typical_spread_pips': 1.0, 'slippage_pips': 0.3},
        'BTCUSD': {'pip_value': 1.0, 'typical_spread_pips': 5.0, 'slippage_pips': 2.0},
    }
    
    config = defaults.get(epic, {'pip_value': 0.01, 'typical_spread_pips': 2.0, 'slippage_pips': 0.5})
    
    # Try to get real-time spread
    try:
        current_spread_price = market_data.get_current_spread(epic)
        if current_spread_price:
            current_spread_pips = convert_spread_to_pips(current_spread_price, config['pip_value'])
            config['current_spread_pips'] = current_spread_pips
            config['spread_pips'] = current_spread_pips  # Use real spread
            logger.info(f"Using real-time spread for {epic}: {current_spread_pips:.2f} pips")
    except Exception as e:
        logger.warning(f"Could not get real-time spread, using defaults: {e}")
    
    return config


if __name__ == '__main__':
    """Test market data fetcher"""
    print("⚠️  Test code needs update - data_fetcher module removed")
    print("    This test needs to be rewritten to use cache_data")
    exit(1)
    
    # TODO: Rewrite this test to use cache_data instead of data_fetcher
    # import json
    # import os
    # from dotenv import load_dotenv
    # from data_fetcher import CapitalComDataFetcher  # REMOVED
    
    load_dotenv()
    secrets_str = os.getenv('apicredentials')
    
    if not secrets_str:
        print("\n❌ No credentials found in environment")
        print("\n💡 Create a .env file with your Capital.com credentials:")
        print("   cp .env.example .env")
        print("   Then edit .env and add: apicredentials='{\"apikey\":\"xxx\",...}'")
        exit(1)
    
    secrets = json.loads(secrets_str)
    
    # Initialize fetchers
    data_fetcher = CapitalComDataFetcher(
        api_key=secrets.get('apikey', ''),
        username=secrets.get('username', ''),
        password=secrets.get('password', ''),
        capkey=secrets.get('capkey', '')
    )
    
    market_data = MarketDataFetcher(data_fetcher)
    
    print("\n" + "="*70)
    print("Testing Market Data Fetcher")
    print("="*70)
    
    # Test 1: Get market details
    print("\n📊 Test 1: Get market details for GOLD")
    details = market_data.get_market_details('GOLD')
    if details:
        print(f"✅ Instrument: {details['instrument_name']}")
        print(f"   Bid: {details['bid']}")
        print(f"   Ask: {details['offer']}")
        print(f"   Spread: {details['current_spread']:.5f}")
        print(f"   Market Status: {details['market_status']}")
        print(f"   Min Deal Size: {details['min_deal_size']}")
        print(f"   Margin Factor: {details['margin_factor']}{details['margin_factor_unit']}")
    
    # Test 2: Get current spread
    print("\n📏 Test 2: Get current spread")
    spread = market_data.get_current_spread('GOLD')
    if spread:
        spread_pips = convert_spread_to_pips(spread, 0.01)
        print(f"✅ Current spread: {spread:.5f} ({spread_pips:.2f} pips)")
    
    # Test 3: Get spread config for backtesting
    print("\n⚙️  Test 3: Get spread config for backtesting")
    config = get_instrument_spread_config('GOLD', market_data)
    print(f"✅ Backtest config:")
    print(f"   Pip value: {config['pip_value']}")
    print(f"   Spread: {config['spread_pips']:.2f} pips")
    print(f"   Slippage: {config['slippage_pips']:.2f} pips")
    
    # Test 4: Get prices for multiple instruments
    print("\n💰 Test 4: Get prices for multiple instruments")
    for epic in ['GOLD', 'EURUSD', 'GBPUSD']:
        prices = market_data.get_current_prices(epic)
        if prices:
            print(f"✅ {epic}: Bid={prices['bid']}, Ask={prices['ask']}, Spread={prices['spread']:.5f}")
    
    print("\n" + "="*70)
    print("All tests completed!")
    print("="*70)
