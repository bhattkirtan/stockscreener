"""
Test the enhanced API locally before GCP deployment
"""

import requests
import json

BASE_URL = "http://localhost:8080"

def test_health():
    """Test health endpoint"""
    print("\n=== Testing /health ===")
    r = requests.get(f"{BASE_URL}/health")
    print(f"Status: {r.status_code}")
    print(json.dumps(r.json(), indent=2))

def test_calendar():
    """Test calendar endpoint"""
    print("\n=== Testing /api/v1/calendar ===")
    r = requests.get(f"{BASE_URL}/api/v1/calendar?days_ahead=7")
    print(f"Status: {r.status_code}")
    data = r.json()
    print(f"Total events: {data.get('total', 0)}")
    if data.get('events'):
        print(f"Next event: {data['events'][0]['title']}")

def test_news():
    """Test news endpoint"""
    print("\n=== Testing /api/v1/news ===")
    r = requests.get(f"{BASE_URL}/api/v1/news?hours_ago=24")
    print(f"Status: {r.status_code}")
    data = r.json()
    print(f"Total headlines: {data.get('total', 0)}")
    print(f"Updated at: {data.get('updated_at', 'N/A')}")

def test_macro():
    """Test macro regime endpoint"""
    print("\n=== Testing /api/v1/macro ===")
    r = requests.get(f"{BASE_URL}/api/v1/macro")
    print(f"Status: {r.status_code}")
    data = r.json()
    print(f"Regime: {data.get('regime', 'N/A')}")
    print(f"Confidence: {data.get('confidence', 0):.0%}")
    print(f"Risk mode: {data.get('risk_mode', 'N/A')}")

def test_blocked():
    """Test blocking check endpoint"""
    print("\n=== Testing /api/v1/is-blocked ===")
    r = requests.get(f"{BASE_URL}/api/v1/is-blocked")
    print(f"Status: {r.status_code}")
    data = r.json()
    print(f"Blocked: {data.get('blocked', False)}")
    if data.get('reasons'):
        print(f"Reasons: {', '.join(data['reasons'])}")

def test_status():
    """Test combined status endpoint"""
    print("\n=== Testing /api/v1/status ===")
    r = requests.get(f"{BASE_URL}/api/v1/status")
    print(f"Status: {r.status_code}")
    data = r.json()
    print(f"Health: {data.get('health', 'N/A')}")
    print(f"Available sources: {data.get('available_sources', 0)}/3")
    for source, info in data.get('sources', {}).items():
        print(f"  {source}: {info.get('status', 'N/A')}")

if __name__ == "__main__":
    print("Testing Enhanced API with External Data Endpoints")
    print("=" * 60)
    
    try:
        test_health()
        test_calendar()
        test_news()
        test_macro()
        test_blocked()
        test_status()
        
        print("\n✅ All tests completed!")
        
    except requests.exceptions.ConnectionError:
        print("\n❌ Connection error. Make sure the API is running:")
        print("   functions-framework --target=optimize_api --port=8080")
    except Exception as e:
        print(f"\n❌ Error: {e}")
