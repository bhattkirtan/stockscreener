#!/usr/bin/env python3
"""
🧪 Test Signal Publishing & Consumption

Quick test to verify signal flow works end-to-end:
1. Publish test signal to Firestore
2. Retrieve it back
3. Verify data integrity
"""

import sys
import os
import asyncio
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.live_trading.signal_publisher import SignalPublisher, SignalBackend

def test_signal_publishing():
    """Test publishing a signal to Firestore"""
    print("=" * 80)
    print("🧪 TESTING SIGNAL PUBLISHING")
    print("=" * 80)
    print()
    
    # Create publisher
    print("1️⃣ Creating SignalPublisher...")
    try:
        publisher = SignalPublisher(
            backends=[SignalBackend.FIRESTORE],
            firestore_collection='trading_signals_test'  # Use test collection
        )
        print("   ✅ SignalPublisher created")
    except Exception as e:
        print(f"   ❌ Failed to create publisher: {e}")
        print()
        print("💡 Troubleshooting:")
        print("   1. Run: gcloud auth application-default login")
        print("   2. Ensure Firestore is enabled in your GCP project")
        print("   3. Check GCP_PROJECT_ID environment variable")
        return False
    
    print()
    
    # Create test signal
    print("2️⃣ Creating test signal...")
    test_signal = {
        'epic': 'GOLD',
        'signal': 'BUY',
        'direction': 'BUY',
        'price': 1950.25,
        'sl': 1935.0,
        'tp': 1980.0,
        'timestamp': datetime.now().isoformat(),
        'strategy': 'TEST',
        'mode': 'TEST',
        'indicators': {
            'test': True,
            'atr': 15.0
        }
    }
    print(f"   Epic: {test_signal['epic']}")
    print(f"   Signal: {test_signal['signal']}")
    print(f"   Price: {test_signal['price']}")
    print()
    
    # Publish signal
    print("3️⃣ Publishing signal to Firestore...")
    try:
        results = publisher.publish_signal(test_signal, signal_id='TEST_SIGNAL_001')
        
        if results.get('firestore'):
            print("   ✅ Signal published successfully!")
        else:
            print("   ❌ Signal publishing failed")
            return False
    except Exception as e:
        print(f"   ❌ Publishing failed: {e}")
        return False
    
    print()
    
    # Retrieve signal
    print("4️⃣ Retrieving signals from Firestore...")
    try:
        from google.cloud import firestore
        db = firestore.Client()
        
        # Get the test signal we just published
        doc_ref = db.collection('trading_signals_test').document('TEST_SIGNAL_001')
        doc = doc_ref.get()
        
        if doc.exists:
            retrieved_signal = doc.to_dict()
            print("   ✅ Signal retrieved successfully!")
            print()
            print("   Retrieved data:")
            print(f"      Epic: {retrieved_signal['epic']}")
            print(f"      Signal: {retrieved_signal['signal']}")
            print(f"      Price: {retrieved_signal['price']}")
            print(f"      SL: {retrieved_signal['sl']}")
            print(f"      TP: {retrieved_signal['tp']}")
            
            # Verify data integrity
            if (retrieved_signal['epic'] == test_signal['epic'] and
                retrieved_signal['signal'] == test_signal['signal'] and
                retrieved_signal['price'] == test_signal['price']):
                print()
                print("   ✅ Data integrity verified!")
            else:
                print()
                print("   ❌ Data mismatch!")
                return False
        else:
            print("   ❌ Signal not found in Firestore")
            return False
            
    except Exception as e:
        print(f"   ❌ Retrieval failed: {e}")
        return False
    
    print()
    
    # Cleanup
    print("5️⃣ Cleaning up test data...")
    try:
        doc_ref.delete()
        print("   ✅ Test signal deleted")
    except Exception as e:
        print(f"   ⚠️ Cleanup failed (non-critical): {e}")
    
    print()
    print("=" * 80)
    print("✅ ALL TESTS PASSED!")
    print("=" * 80)
    print()
    print("Signal publishing is working correctly. Your bot will:")
    print("  • Publish signals to Firestore automatically")
    print("  • Your app can consume with 50-200ms latency")
    print("  • Signals are persistent and queryable")
    print()
    print("Next steps:")
    print("  1. Start bot: python3 scripts/trading_bot.py")
    print("  2. Consume signals: python3 scripts/signal_consumer.py realtime")
    print("  3. Integrate React (see SIGNAL_FLOW.md)")
    print()
    
    return True


def test_signal_retrieval():
    """Test retrieving recent signals"""
    print("=" * 80)
    print("🧪 TESTING SIGNAL RETRIEVAL")
    print("=" * 80)
    print()
    
    try:
        from google.cloud import firestore
        publisher = SignalPublisher(backends=[SignalBackend.FIRESTORE])
        
        # Get recent signals
        print("Fetching recent signals from production collection...")
        signals = publisher.get_recent_signals(limit=5)
        
        if signals:
            print(f"✅ Found {len(signals)} recent signals:")
            print()
            for i, signal in enumerate(signals, 1):
                print(f"{i}. {signal.get('signal', 'N/A')} {signal.get('epic', 'N/A')} "
                      f"@ {signal.get('price', 'N/A')} "
                      f"({signal.get('timestamp', 'N/A')})")
        else:
            print("ℹ️  No signals found yet")
            print("   This is normal if bot hasn't generated signals yet")
            print("   Bot needs 60+ M15 bars (~15 hours) before first signal")
        
        print()
        return True
        
    except Exception as e:
        print(f"❌ Retrieval test failed: {e}")
        return False


def main():
    """Run all tests"""
    print()
    print("🚀 Signal Flow Test Suite")
    print()
    
    # Test 1: Publishing
    success1 = test_signal_publishing()
    
    print()
    print()
    
    # Test 2: Retrieval
    success2 = test_signal_retrieval()
    
    print()
    print("=" * 80)
    
    if success1 and success2:
        print("🎉 ALL TESTS PASSED - Signal flow is working!")
        print("=" * 80)
        return 0
    else:
        print("❌ SOME TESTS FAILED - Check errors above")
        print("=" * 80)
        return 1


if __name__ == '__main__':
    sys.exit(main())
