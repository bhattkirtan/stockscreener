#!/usr/bin/env python3
"""
Test client for Strategy Optimization API
Usage: python3 test_api_client.py
"""

import requests
import time
import json

BASE_URL = "http://localhost:8000"

def test_health():
    """Test health check"""
    print("🏥 Testing health check...")
    response = requests.get(f"{BASE_URL}/health")
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.json()}\n")
    return response.status_code == 200

def test_start_optimization():
    """Test starting optimization"""
    print("🚀 Starting optimization...")
    
    payload = {
        "instrument": "GOLD",
        "timeframe": "M5",
        "mode": "quick",
        "initial_capital": 10000.0,
        "position_size": 10.0,
        "parallel": True,
        "n_jobs": -1
    }
    
    response = requests.post(f"{BASE_URL}/api/optimize", json=payload)
    print(f"   Status: {response.status_code}")
    data = response.json()
    print(f"   Run ID: {data.get('run_id')}\n")
    
    return data.get('run_id')

def test_check_status(run_id):
    """Test checking status"""
    print(f"📊 Checking status of {run_id}...")
    
    while True:
        response = requests.get(f"{BASE_URL}/api/optimize/status/{run_id}")
        data = response.json()
        status = data.get('status')
        
        print(f"   Status: {status}", end="")
        
        if status == "completed":
            print(" ✅")
            break
        elif status == "failed":
            print(" ❌")
            print(f"   Error: {data.get('error')}")
            break
        elif status in ["queued", "running"]:
            print(" ⏳")
            time.sleep(5)
        else:
            print(" ❓")
            break
    
    print()
    return status == "completed"

def test_get_history():
    """Test getting history"""
    print("📜 Getting optimization history...")
    response = requests.get(f"{BASE_URL}/api/optimize/history?limit=5")
    data = response.json()
    
    print(f"   Total runs: {data.get('total')}")
    for run in data.get('runs', [])[:3]:
        print(f"   - {run['run_id']}: {run['status']} ({run.get('best_return', 'N/A')}%)")
    print()

def test_get_results(run_id):
    """Test getting results"""
    print(f"📈 Getting results for {run_id}...")
    response = requests.get(f"{BASE_URL}/api/optimize/results/{run_id}?top_n=3")
    
    if response.status_code == 200:
        data = response.json()
        print(f"   Total strategies: {data.get('total_strategies')}")
        print(f"   Top 3 strategies:")
        for strat in data.get('top_strategies', [])[:3]:
            print(f"   {strat['rank']}. {strat['strategy_name']}")
            print(f"      Profit: ${strat['total_pnl']:.2f} ({strat['return_pct']:.2f}%)")
    else:
        print(f"   Error: {response.status_code}")
    print()

def test_analyze(run_id):
    """Test analysis"""
    print(f"🔍 Analyzing {run_id}...")
    response = requests.get(f"{BASE_URL}/api/analyze/{run_id}")
    
    if response.status_code == 200:
        data = response.json()
        best = data.get('best_strategy', {})
        print(f"   Best Strategy: {best.get('strategy_name')}")
        print(f"   Profit: ${best.get('total_pnl'):.2f}")
        print(f"   Win Rate: {best.get('win_rate'):.1f}%")
        
        pip_analysis = data.get('pip_value_analysis', {})
        print(f"\n   pip_value Analysis:")
        for pv, stats in list(pip_analysis.items())[:3]:
            print(f"   - pip={pv}: {stats['profitable']}/{stats['count']} profitable, avg ${stats['avg_profit']:.2f}")
    else:
        print(f"   Error: {response.status_code}")
    print()

def test_stats():
    """Test overall stats"""
    print("📊 Getting overall statistics...")
    response = requests.get(f"{BASE_URL}/api/stats/summary")
    
    if response.status_code == 200:
        data = response.json()
        print(f"   Total runs: {data.get('total_runs')}")
        print(f"   Total strategies tested: {data.get('total_strategies_tested'):,}")
        print(f"   Best return ever: {data.get('best_return_ever'):.2f}%")
        print(f"   Best profit ever: ${data.get('best_profit_ever'):.2f}")
    print()

def main():
    """Run all tests"""
    print("\n" + "="*80)
    print("🧪 Strategy Optimization API Test Suite")
    print("="*80 + "\n")
    
    # Check if server is running
    try:
        if not test_health():
            print("❌ Server is not healthy. Make sure api_server.py is running.")
            return
    except requests.ConnectionError:
        print("❌ Could not connect to server. Run: python3 api_server.py")
        return
    
    # Test endpoints
    test_get_history()
    test_stats()
    
    # Test optimization workflow
    print("="*80)
    print("🔄 Testing Full Optimization Workflow")
    print("="*80 + "\n")
    
    run_id = test_start_optimization()
    
    if run_id:
        success = test_check_status(run_id)
        
        if success:
            test_get_results(run_id)
            test_analyze(run_id)
            test_get_history()
    
    print("="*80)
    print("✅ Test Suite Complete!")
    print("="*80 + "\n")

if __name__ == '__main__':
    main()
