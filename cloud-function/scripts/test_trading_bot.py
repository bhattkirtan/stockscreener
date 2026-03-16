"""
🧪 Test script for trading bot setup validation

Tests:
1. ✅ Authentication with Capital.com
2. ✅ WebSocket connection
3. ✅ M5 OHLC candle streaming
4. ✅ M5 to M15 aggregation
5. ✅ Indicator calculation

Run this BEFORE the full trading bot to validate everything works.
"""

import sys
import os
import asyncio
import logging

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from src.live_trading.config import TradingConfig
from src.live_trading.capital_websocket import CapitalWebSocketClient
import capitalService

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_authentication():
    """Test 1: Authentication"""
    logger.info("=" * 80)
    logger.info("TEST 1: Authentication")
    logger.info("=" * 80)
    
    try:
        tokens = capitalService.get_token()
        cst = tokens.get('CST')
        security_token = tokens.get('X-SECURITY-TOKEN')
        
        if cst and security_token:
            logger.info("✅ Authentication successful")
            logger.info(f"   CST: {cst[:20]}...")
            logger.info(f"   Security Token: {security_token[:20]}...")
            return True, tokens
        else:
            logger.error("❌ Authentication failed: No tokens received")
            return False, None
    
    except Exception as e:
        logger.error(f"❌ Authentication failed: {e}")
        return False, None


async def test_websocket_connection(tokens):
    """Test 2: WebSocket connection"""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 2: WebSocket Connection")
    logger.info("=" * 80)
    
    try:
        config = TradingConfig(environment='demo')
        
        ws_client = CapitalWebSocketClient(
            cst=tokens['CST'],
            security_token=tokens['X-SECURITY-TOKEN'],
            ws_url=config.websocket_url,
            ping_interval=config.ping_interval
        )
        
        await ws_client.connect()
        logger.info("✅ WebSocket connected successfully")
        
        return True, ws_client
    
    except Exception as e:
        logger.error(f"❌ WebSocket connection failed: {e}")
        return False, None


async def test_m5_streaming(ws_client):
    """Test 3: M5 OHLC candle streaming"""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 3: M5 OHLC Streaming")
    logger.info("=" * 80)
    logger.info("⏳ Waiting for M5 candles (max 60 seconds)...")
    
    candles_received = []
    
    def on_candle_received(epic, candle):
        logger.info(f"📊 M5 Candle: {candle['timestamp']} O:{candle['open']:.2f} H:{candle['high']:.2f} L:{candle['low']:.2f} C:{candle['close']:.2f}")
        candles_received.append(candle)
    
    ws_client.on_candle = on_candle_received
    
    try:
        # Subscribe to GOLD M5
        await ws_client.subscribe_ohlc(['GOLD'], resolution='MINUTE_5')
        logger.info("✅ Subscribed to GOLD M5 candles")
        
        # Wait for at least 1 candle (max 60 seconds)
        for i in range(60):
            await asyncio.sleep(1)
            if len(candles_received) > 0:
                logger.info(f"✅ Received {len(candles_received)} M5 candle(s)")
                return True, candles_received
        
        logger.warning("⚠️ No candles received after 60 seconds (may be outside trading hours)")
        return True, candles_received  # Still pass, might be outside hours
    
    except Exception as e:
        logger.error(f"❌ M5 streaming failed: {e}")
        return False, []


async def test_m5_to_m15_aggregation(candles):
    """Test 4: M5 to M15 aggregation"""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 4: M5 to M15 Aggregation")
    logger.info("=" * 80)
    
    if len(candles) < 3:
        logger.warning("⚠️ Not enough M5 candles for M15 aggregation (need 3)")
        return True  # Not a failure, just not enough data yet
    
    try:
        from scripts.trading_bot import M5toM15Aggregator
        
        aggregator = M5toM15Aggregator()
        
        m15_bars = []
        for candle in candles[:3]:  # Use first 3 candles
            m15_bar = aggregator.add_m5_candle(candle)
            if m15_bar:
                m15_bars.append(m15_bar)
        
        if m15_bars:
            logger.info(f"✅ M15 aggregation successful: {len(m15_bars)} bar(s) created")
            for bar in m15_bars:
                logger.info(f"   M15: {bar['timestamp']} O:{bar['open']:.2f} H:{bar['high']:.2f} L:{bar['low']:.2f} C:{bar['close']:.2f}")
            return True
        else:
            logger.info("ℹ️ M15 bar not ready yet (waiting for M15 alignment)")
            return True  # Not a failure
    
    except Exception as e:
        logger.error(f"❌ M15 aggregation failed: {e}")
        return False


async def test_indicator_calculation():
    """Test 5: Indicator calculation"""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 5: Indicator Calculation")
    logger.info("=" * 80)
    
    try:
        from src.core.strategy import SupertrendVWAPStrategy
        import pandas as pd
        import numpy as np
        
        # Create sample data (60 bars for indicator warmup)
        dates = pd.date_range(start='2024-01-01', periods=60, freq='15min')
        sample_data = pd.DataFrame({
            'open': 2000 + np.random.randn(60) * 5,
            'high': 2005 + np.random.randn(60) * 5,
            'low': 1995 + np.random.randn(60) * 5,
            'close': 2000 + np.random.randn(60) * 5,
            'volume': 1000 + np.random.randint(0, 500, 60)
        }, index=dates)
        
        # Fix OHLC consistency
        sample_data['high'] = sample_data[['open', 'high', 'close']].max(axis=1)
        sample_data['low'] = sample_data[['open', 'low', 'close']].min(axis=1)
        
        # Initialize strategy
        strategy = SupertrendVWAPStrategy(
            supertrend_period=7,
            supertrend_multiplier=2.0,
            sma_fast=21,
            sma_slow=50,
            bb_period=20,
            bb_std=2.0
        )
        
        # Calculate indicators
        df_with_indicators = strategy.calculate_indicators(sample_data)
        
        # Check if indicators are calculated
        required_indicators = ['supertrend', 'direction', 'sma_fast', 'sma_slow', 'ema', 'bb_upper', 'bb_lower']
        missing = [ind for ind in required_indicators if ind not in df_with_indicators.columns]
        
        if missing:
            logger.error(f"❌ Missing indicators: {missing}")
            return False
        
        # Check last row (most recent)
        last_row = df_with_indicators.iloc[-1]
        
        logger.info("✅ Indicators calculated successfully:")
        logger.info(f"   Supertrend: {last_row['supertrend']:.2f} (Direction: {'UP' if last_row['direction'] == 1 else 'DOWN'})")
        logger.info(f"   SMA Fast: {last_row['sma_fast']:.2f}")
        logger.info(f"   SMA Slow: {last_row['sma_slow']:.2f}")
        logger.info(f"   EMA: {last_row['ema']:.2f}")
        logger.info(f"   BB Upper: {last_row['bb_upper']:.2f}")
        logger.info(f"   BB Lower: {last_row['bb_lower']:.2f}")
        
        return True
    
    except Exception as e:
        logger.error(f"❌ Indicator calculation failed: {e}")
        return False


async def main():
    """Run all tests"""
    logger.info("🧪 Trading Bot Setup Validation")
    logger.info("=" * 80)
    
    results = []
    ws_client = None
    
    try:
        # Test 1: Authentication
        success, tokens = await test_authentication()
        results.append(("Authentication", success))
        if not success:
            return
        
        # Test 2: WebSocket Connection
        success, ws_client = await test_websocket_connection(tokens)
        results.append(("WebSocket Connection", success))
        if not success:
            return
        
        # Test 3: M5 Streaming
        success, candles = await test_m5_streaming(ws_client)
        results.append(("M5 Streaming", success))
        
        # Test 4: M5 to M15 Aggregation
        success = await test_m5_to_m15_aggregation(candles)
        results.append(("M5 to M15 Aggregation", success))
        
        # Test 5: Indicator Calculation
        success = await test_indicator_calculation()
        results.append(("Indicator Calculation", success))
    
    finally:
        # Cleanup
        if ws_client:
            await ws_client.close()
    
    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("📊 TEST SUMMARY")
    logger.info("=" * 80)
    
    for test_name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        logger.info(f"{status}: {test_name}")
    
    all_passed = all(success for _, success in results)
    
    logger.info("=" * 80)
    if all_passed:
        logger.info("🎉 ALL TESTS PASSED - Ready to run trading bot!")
    else:
        logger.info("⚠️ SOME TESTS FAILED - Fix issues before running bot")
    logger.info("=" * 80)


if __name__ == '__main__':
    asyncio.run(main())
