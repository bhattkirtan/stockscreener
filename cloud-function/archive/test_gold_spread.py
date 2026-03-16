#!/usr/bin/env python3
"""
Quick test to fetch real Gold spread from Capital.com API
"""
import os
import json
import sys
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.api.capital_client import CapitalClient

def main():
    load_dotenv()
    secrets_str = os.getenv('apicredentials')
    
    if not secrets_str:
        print("\n❌ No credentials found")
        print("   Set apicredentials in .env file")
        return
    
    secrets = json.loads(secrets_str)
    
    # Initialize
    print("\n🔐 Connecting to Capital.com...")
    client = CapitalClient(
        username=secrets.get('username', ''),
        password=secrets.get('password', ''),
        capkey=secrets.get('capkey', '')
    )
    
    # Get authentication token
    print("   Authenticating...")
    tokens = client.get_token()
    if not tokens:
        print("❌ Authentication failed")
        return
    
    print("✅ Authenticated")
    
    # Get Gold market details directly via API
    print("\n💰 Fetching GOLD spread...\n")
    
    try:
        url = f'{client.base_url}/api/v1/markets/GOLD'
        headers = {
            'X-CAP-API-KEY': client.capkey,
            'CST': tokens['CST'],
            'X-SECURITY-TOKEN': tokens['X-SECURITY-TOKEN']
        }
        
        response = client.session.get(url, headers=headers, timeout=10)
        
        if response.ok:
            data = response.json()
            snapshot = data.get('snapshot', {})
            instrument = data.get('instrument', {})
            
            bid = float(snapshot.get('bid', 0))
            offer = float(snapshot.get('offer', 0))
            spread = offer - bid
            
            print(f"✅ Current GOLD prices:")
            print(f"   Bid:    {bid:.2f}")
            print(f"   Ask:    {offer:.2f}")
            print(f"   Spread: {spread:.2f} points")
            print(f"   Name:   {instrument.get('name', 'N/A')}")
            
            # Calculate for backtesting
            print(f"\n📊 For backtesting (per 1 contract):")
            print(f"   Spread cost:   ${spread:.2f}")
            print(f"   Slippage est: ${spread * 0.1:.3f} (10% of spread)")
            print(f"   Total cost:    ${spread * 1.1:.2f} per round-trip trade")
            
            print(f"\n📊 For 10 contracts (your position size):")
            print(f"   Spread cost:   ${spread * 10:.2f}")
            print(f"   Slippage est: ${spread * 0.1 * 10:.2f}")
            print(f"   Total cost:    ${spread * 1.1 * 10:.2f} per round-trip trade")
            
            print(f"\n💡 Current BacktestConfig values:")
            print(f"   spread_cost_usd = {spread:.2f}")
            print(f"   slippage_cost_usd = {spread * 0.1:.3f}")
            
        else:
            print(f"❌ Failed: {response.status_code}")
            print(f"   {response.text}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
