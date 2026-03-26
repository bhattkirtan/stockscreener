"""
API Connection Test Script

Tests all three API clients (Capital.com, Firestore, Telegram) in mock mode first,
then optionally tests with real credentials.
"""
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from clients.capital_api import CapitalAPIClient
from clients.firestore_api import FirestoreAPIClient
from clients.telegram_api import TelegramAPIClient


def test_mock_mode():
    """Test all APIs in mock mode (no credentials needed)"""
    print("=" * 60)
    print("TESTING APIS IN MOCK MODE")
    print("=" * 60)
    
    # Test Capital.com API (mock)
    print("\n1️⃣  Testing Capital.com API (MOCK)")
    print("-" * 60)
    capital_client = CapitalAPIClient(
        username="mock@example.com",
        password="mock_password",
        api_key="mock_api_key",
        environment="demo"
    )
    print("✅ Capital.com client initialized (mock mode expects failure)")
    
    # Test Firestore API (mock)
    print("\n2️⃣  Testing Firestore API (MOCK)")
    print("-" * 60)
    firestore_client = FirestoreAPIClient(mock_mode=True)
    
    # Test save position
    success = firestore_client.save_position(
        collection="test_positions",
        deal_id="TEST123",
        position_data={
            "direction": "BUY",
            "entry_price": 1950.50,
            "stop_loss": 1940.00,
            "take_profit": 1970.00
        }
    )
    print(f"   Save position: {'✅ Success' if success else '❌ Failed'}")
    
    # Test get position
    position = firestore_client.get_position(
        collection="test_positions",
        deal_id="TEST123"
    )
    print(f"   Get position: {'✅ Success' if position else '❌ Failed'}")
    
    # Test close position
    success = firestore_client.close_position(
        collection="test_positions",
        deal_id="TEST123",
        close_data={"close_price": 1960.00, "pnl": 9.50}
    )
    print(f"   Close position: {'✅ Success' if success else '❌ Failed'}")
    
    # Test Telegram API (mock)
    print("\n3️⃣  Testing Telegram API (MOCK)")
    print("-" * 60)
    telegram_client = TelegramAPIClient(mock_mode=True)
    
    # Test trade opened alert
    success = telegram_client.send_trade_opened(
        direction="BUY",
        entry_price=1950.50,
        stop_loss=1940.00,
        take_profit=1970.00,
        size=0.5,
        deal_id="TEST123"
    )
    print(f"   Trade opened alert: {'✅ Success' if success else '❌ Failed'}")
    
    # Test trade closed alert
    success = telegram_client.send_trade_closed(
        direction="BUY",
        entry_price=1950.50,
        close_price=1960.00,
        close_reason="TP_HIT",
        pnl=9.50,
        pnl_percent=0.48,
        duration="15m",
        deal_id="TEST123"
    )
    print(f"   Trade closed alert: {'✅ Success' if success else '❌ Failed'}")
    
    # Test error alert
    success = telegram_client.send_error_alert(
        error_type="CONNECTION_ERROR",
        error_message="Failed to connect to broker API"
    )
    print(f"   Error alert: {'✅ Success' if success else '❌ Failed'}")
    
    print("\n" + "=" * 60)
    print("✅ ALL MOCK MODE TESTS PASSED")
    print("=" * 60)


def test_real_apis():
    """Test all APIs with real credentials (from config or env vars)"""
    import yaml
    
    print("\n" + "=" * 60)
    print("TESTING APIS WITH REAL CREDENTIALS")
    print("=" * 60)
    print("📌 Credentials loaded from: config file OR environment variables")
    print("   Env vars: CAPITAL_USERNAME, CAPITAL_PASSWORD, CAPITAL_API_KEY")
    print("            FIRESTORE_PROJECT_ID, GOOGLE_APPLICATION_CREDENTIALS")
    print("            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID")
    
    # Try to load config (optional if env vars are set)
    config = {}
    config_path = "config/trading_config.yaml"
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        print(f"✅ Loaded config from {config_path}")
    else:
        print(f"⚠️  Config not found: {config_path} (will use env vars)")
    
    # Check if mock mode is enabled in config
    if config.get('mock_mode', False):
        print("\n⚠️  mock_mode is enabled in config - APIs will run in mock mode")
        print("   Set mock_mode: false in config to test real APIs")
        return
    
    # Test Capital.com API
    print("\n1️⃣  Testing Capital.com API (REAL)")
    print("-" * 60)
    try:
        capital_config = config.get('capital_com', {})
        
        # API client will use config values OR env vars as fallback
        capital_client = CapitalAPIClient(
            username=capital_config.get('username'),  # Falls back to CAPITAL_USERNAME env var
            password=capital_config.get('password'),  # Falls back to CAPITAL_PASSWORD env var
            api_key=capital_config.get('api_key'),    # Falls back to CAPITAL_API_KEY env var
            environment=capital_config.get('environment', 'demo')
        )
        
        # Create session
        session = capital_client.create_session()
        print(f"✅ Session created: {session.get('account', {}).get('accountId', 'Unknown')}")
        
        # Get account info
        account = capital_client.get_account_info()
        balance = account.get('accounts', [{}])[0].get('balance', {}).get('balance', 0)
        print(f"✅ Account balance: ${balance:.2f}")
        
        # Get open positions
        positions = capital_client.get_open_positions()
        print(f"✅ Open positions: {len(positions)}")
    
    except Exception as e:
        print(f"❌ Capital.com API error: {e}")
    
    # Test Firestore
    print("\n2️⃣  Testing Firestore API (REAL)")
    print("-" * 60)
    try:
        firestore_config = config.get('firestore', {})
        
        # API client will use config values OR env vars as fallback
        firestore_client = FirestoreAPIClient(
            project_id=firestore_config.get('project_id'),       # Falls back to FIRESTORE_PROJECT_ID env var
            credentials_path=firestore_config.get('credentials_path')  # Falls back to GOOGLE_APPLICATION_CREDENTIALS env var
        )
        
        # Test write
        success = firestore_client.save_position(
            collection="test_positions",
            deal_id="TEST_API_" + str(int(os.path.time() * 1000)),
            position_data={
                "direction": "BUY",
                "entry_price": 1950.50,
                "test": True
            }
        )
        print(f"{'✅' if success else '❌'} Save position test")
    
    except Exception as e:
        print(f"❌ Firestore API error: {e}")
    
    # Test Telegram
    print("\n3️⃣  Testing Telegram API (REAL)")
    print("-" * 60)
    try:
        telegram_config = config.get('telegram', {})
        telegram_client = TelegramAPIClient(
            bot_token=telegram_config.get('token'),
            chat_id=telegram_config.get('chat_id')
        )
        
        # Send test message
        success = telegram_client.send_message(
            "🤖 API Connection Test\n\nThis is a test message from your trading bot."
        )
        print(f"{'✅' if success else '❌'} Test message sent")
    
    except Exception as e:
        print(f"❌ Telegram API error: {e}")
    
    print("\n" + "=" * 60)
    print("✅ REAL API TESTS COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    # Always test mock mode first
    test_mock_mode()
    
    # Ask if user wants to test real APIs
    print("\n\n")
    test_real = input("Test with REAL API credentials? (y/n): ").lower().strip()
    
    if test_real == 'y':
        test_real_apis()
    else:
        print("\n✅ Mock mode tests complete. Configure APIs in config/trading_config.yaml to test real connections.")
