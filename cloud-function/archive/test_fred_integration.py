"""
Quick test to verify FRED API integration

Run this to confirm your API key works and see current macro regime.
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from data.fred_adapter import FREDAdapter

# Load environment variables
from dotenv import load_dotenv
load_dotenv()


def test_fred_integration():
    """Test FRED API integration"""
    print("=" * 60)
    print("FRED API Integration Test")
    print("=" * 60)
    
    # Get API key from environment
    api_key = os.getenv('FRED_API_KEY')
    
    if not api_key:
        print("❌ ERROR: FRED_API_KEY not found in .env file")
        return False
    
    print(f"✅ API Key found: {api_key[:8]}...{api_key[-4:]}")
    print()
    
    # Initialize adapter
    print("📊 Initializing FRED Adapter...")
    fred = FREDAdapter(api_key=api_key)
    print("✅ Adapter initialized")
    print()
    
    # Test fetching current regime
    print("🔍 Fetching current macro regime...")
    print("   (This fetches 8 FRED series: DFF, DGS10, T10Y2Y, DTWEXBGS, CPI, UNRATE, GDP, USREC)")
    print()
    
    try:
        regime = fred.get_current_regime()
        
        if regime:
            print("=" * 60)
            print("📈 CURRENT MACRO REGIME")
            print("=" * 60)
            print(f"Regime:     {regime.regime.value.upper()}")
            print(f"Confidence: {regime.confidence:.1%}")
            print(f"Risk Mode:  {'🟢 RISK-ON' if regime.is_risk_on() else '🔴 RISK-OFF'}")
            print(f"Position Multiplier: {regime.get_position_size_multiplier():.1%}")
            print()
            
            print("-" * 60)
            print("📉 INDICATORS")
            print("-" * 60)
            if regime.fed_funds_rate is not None:
                print(f"Fed Funds Rate:    {regime.fed_funds_rate:.2f}%")
            if regime.treasury_10y is not None:
                print(f"10Y Treasury:      {regime.treasury_10y:.2f}%")
            if regime.yield_curve is not None:
                print(f"Yield Curve (10Y-2Y): {regime.yield_curve:+.2f}%")
            if regime.dollar_index is not None:
                print(f"Dollar Index:      {regime.dollar_index:.2f}")
            if regime.cpi_yoy is not None:
                print(f"CPI (YoY):         {regime.cpi_yoy:+.2f}%")
            if regime.unemployment_rate is not None:
                print(f"Unemployment Rate: {regime.unemployment_rate:.1f}%")
            if regime.gdp_growth is not None:
                print(f"GDP Growth (QoQ):  {regime.gdp_growth:+.2f}%")
            if regime.recession_probability is not None:
                print(f"Recession Indicator: {regime.recession_probability:.0f}")
            print()
            
            print("-" * 60)
            print("💡 TRADING IMPLICATIONS")
            print("-" * 60)
            
            if regime.regime.value == "expansion":
                print("✅ Full risk-on: Trade aggressively with full position sizes")
                print("   GDP growth strong, inflation controlled, markets favorable")
            elif regime.regime.value == "recovery":
                print("✅ Risk-on: Good environment for trading")
                print("   Economy recovering, trade with confidence")
            elif regime.regime.value == "slowdown":
                print("⚠️  Caution: Reduce position sizes to 75%")
                print("   Growth decelerating, be more selective with trades")
            elif regime.regime.value == "recession":
                print("🔴 High risk: Reduce position sizes to 50%")
                print("   Negative growth, trade defensively")
            elif regime.regime.value == "stagflation":
                print("🔴 High risk: Reduce position sizes to 50%")
                print("   Stagnant growth + high inflation, very challenging environment")
            else:
                print("❓ Unknown regime: Use default position sizing")
            
            print()
            print("✅ FRED Integration Working!")
            return True
            
        else:
            print("❌ Failed to fetch regime data")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_fred_integration()
    sys.exit(0 if success else 1)
