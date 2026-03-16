#!/usr/bin/env python3
"""
API Test Client
Demonstrates all API endpoints and usage patterns
"""

import requests
import json
import time
from typing import Optional

API_BASE_URL = "http://localhost:8000"


class OptimizationAPIClient:
    """Client for interacting with Optimization API"""
    
    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url
    
    def health_check(self):
        """Check API health"""
        response = requests.get(f"{self.base_url}/health")
        return response.json()
    
    def start_optimization(
        self,
        instrument: str = "GOLD",
        timeframe: str = "M5",
        mode: str = "quick",
        initial_capital: float = 10000.0,
        position_size: float = 10.0,
        pip_values: Optional[list] = None,
        parallel: bool = True,
        n_jobs: int = -1
    ):
        """Start new optimization run"""
        payload = {
            "instrument": instrument,
            "timeframe": timeframe,
            "mode": mode,
            "initial_capital": initial_capital,
            "position_size": position_size,
            "pip_values": pip_values,
            "parallel": parallel,
            "n_jobs": n_jobs
        }
        
        response = requests.post(f"{self.base_url}/api/optimize", json=payload)
        return response.json()
    
    def get_status(self, run_id: str):
        """Get optimization status"""
        response = requests.get(f"{self.base_url}/api/optimize/status/{run_id}")
        return response.json()
    
    def wait_for_completion(self, run_id: str, poll_interval: int = 5, timeout: int = 600):
        """Wait for optimization to complete"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            status = self.get_status(run_id)
            
            print(f"Status: {status['status']}", end="")
            if status.get('progress'):
                print(f" - {status['progress']}")
            else:
                print()
            
            if status['status'] in ['completed', 'failed']:
                return status
            
            time.sleep(poll_interval)
        
        raise TimeoutError(f"Optimization {run_id} did not complete within {timeout}s")
    
    def get_history(self, limit: int = 20, skip: int = 0):
        """Get optimization history"""
        response = requests.get(
            f"{self.base_url}/api/optimize/history",
            params={"limit": limit, "skip": skip}
        )
        return response.json()
    
    def get_results(self, run_id: str = "latest", top_n: int = 20):
        """Get optimization results"""
        response = requests.get(
            f"{self.base_url}/api/optimize/results/{run_id}",
            params={"top_n": top_n}
        )
        return response.json()
    
    def get_analysis(self, run_id: str = "latest"):
        """Get comprehensive analysis"""
        response = requests.get(f"{self.base_url}/api/analyze/{run_id}")
        return response.json()
    
    def delete_run(self, run_id: str):
        """Delete optimization run"""
        response = requests.delete(f"{self.base_url}/api/optimize/{run_id}")
        return response.json()
    
    def get_overall_stats(self):
        """Get overall statistics"""
        response = requests.get(f"{self.base_url}/api/stats/summary")
        return response.json()


def print_section(title: str):
    """Print section header"""
    print()
    print("=" * 80)
    print(f"  {title}")
    print("=" * 80)
    print()


def demo_all_endpoints():
    """Demonstrate all API endpoints"""
    
    client = OptimizationAPIClient()
    
    print_section("1. HEALTH CHECK")
    health = client.health_check()
    print(json.dumps(health, indent=2))
    
    print_section("2. VIEW HISTORY")
    history = client.get_history(limit=5)
    print(f"Total runs: {history['total']}")
    print()
    for run in history['runs'][:3]:
        print(f"  {run['run_id']}")
        print(f"    Date: {run['date']} | Status: {run['status']}")
        if run['best_profit']:
            print(f"    Best: ${run['best_profit']:.2f} ({run['best_return']:.2f}%)")
        print()
    
    print_section("3. VIEW LATEST RESULTS")
    try:
        results = client.get_results("latest", top_n=5)
        print(f"Run: {results['run_id']}")
        print(f"Total strategies: {results['total_strategies']}")
        print()
        print("Top 5 strategies:")
        for strat in results['top_strategies'][:5]:
            print(f"  #{strat['rank']}: {strat['strategy_name']}")
            print(f"    Profit: ${strat['total_pnl']:.2f} ({strat['return_pct']:.2f}%)")
            print(f"    Win Rate: {strat['win_rate']:.1f}% | Sharpe: {strat['sharpe_ratio']:.2f}")
            print()
    except Exception as e:
        print(f"No results available: {e}")
    
    print_section("4. ANALYZE LATEST RUN")
    try:
        analysis = client.get_analysis("latest")
        print(f"Run: {analysis['run_id']}")
        print(f"Date: {analysis['date']}")
        print(f"Total combinations: {analysis['total_combinations']:,}")
        print()
        
        best = analysis['best_strategy']
        print("Best Strategy:")
        print(f"  Name: {best['strategy_name']}")
        print(f"  Profit: ${best['total_pnl']:.2f} ({best['return_pct']:.2f}%)")
        print(f"  Win Rate: {best['win_rate']:.1f}%")
        print(f"  Profit Factor: {best['profit_factor']:.2f}")
        print()
        
        print("pip_value Performance:")
        for pv, data in analysis['pip_value_analysis'].items():
            print(f"  {pv}: {data['profitable']}/{data['count']} profitable "
                  f"({data['profitable_pct']:.1f}%), Max profit: ${data['max_profit']:.2f}")
        print()
        
        print("Risk Metrics:")
        risk = analysis['risk_metrics']
        print(f"  Profitability Rate: {risk['profitability_rate']:.1f}%")
        print(f"  Avg Drawdown: {risk['avg_drawdown']:.2f}%")
        print(f"  Worst Drawdown: {risk['worst_drawdown']:.2f}%")
        print()
        
    except Exception as e:
        print(f"No analysis available: {e}")
    
    print_section("5. OVERALL STATISTICS")
    try:
        stats = client.get_overall_stats()
        print(f"Total runs: {stats['total_runs']}")
        print(f"Total strategies tested: {stats['total_strategies_tested']:,}")
        print(f"Best return ever: {stats['best_return_ever']:.2f}%")
        print(f"Best profit ever: ${stats['best_profit_ever']:.2f}")
        print(f"Best run: {stats['best_run']}")
    except Exception as e:
        print(f"No stats available: {e}")
    
    # Optional: Start new optimization (commented out by default)
    """
    print_section("6. START NEW OPTIMIZATION (Commented out)")
    print("To start new optimization, uncomment this section")
    
    result = client.start_optimization(
        instrument="GOLD",
        timeframe="M5",
        mode="quick",
        position_size=10.0,
        pip_values=[1.5, 2.0, 2.5, 3.0, 5.0]
    )
    
    print(f"Started: {result['run_id']}")
    print(f"Status: {result['status']}")
    
    # Wait for completion
    print("Waiting for completion...")
    final_status = client.wait_for_completion(result['run_id'])
    print(f"Final status: {final_status['status']}")
    
    if final_status['status'] == 'completed':
        # Get results
        results = client.get_results(result['run_id'])
        print(f"Best strategy: {results['top_strategies'][0]['strategy_name']}")
        print(f"Profit: ${results['top_strategies'][0]['total_pnl']:.2f}")
    """


def quick_analysis():
    """Quick analysis of latest run"""
    client = OptimizationAPIClient()
    
    try:
        analysis = client.get_analysis("latest")
        
        print("=" * 70)
        print(f"  LATEST RUN ANALYSIS - {analysis['date']}")
        print("=" * 70)
        print()
        
        best = analysis['best_strategy']
        print(f"🏆 BEST STRATEGY")
        print(f"   {best['strategy_name']}")
        print(f"   💰 Profit: ${best['total_pnl']:,.2f} ({best['return_pct']:.2f}%)")
        print(f"   📈 Trades: {best['total_trades']} | Win Rate: {best['win_rate']:.1f}%")
        print(f"   📊 Sharpe: {best['sharpe_ratio']:.2f} | PF: {best['profit_factor']:.2f}")
        print()
        
        print(f"📊 OVERVIEW")
        print(f"   Total Combinations: {analysis['total_combinations']:,}")
        print(f"   Profitability Rate: {analysis['risk_metrics']['profitability_rate']:.1f}%")
        print()
        
        print(f"🎯 TOP pip_values (by max profit):")
        pip_sorted = sorted(
            analysis['pip_value_analysis'].items(),
            key=lambda x: x[1]['max_profit'],
            reverse=True
        )
        for pv, data in pip_sorted[:3]:
            print(f"   {pv}: Max ${data['max_profit']:,.2f} | "
                  f"{data['profitable_pct']:.1f}% profitable")
        print()
        
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "quick":
        quick_analysis()
    else:
        print("=" * 80)
        print("  STRATEGY OPTIMIZATION API - TEST CLIENT")
        print("=" * 80)
        print()
        print("Usage:")
        print("  python3 test_api.py           - Demo all endpoints")
        print("  python3 test_api.py quick     - Quick analysis of latest run")
        print()
        
        try:
            demo_all_endpoints()
            
            print()
            print("=" * 80)
            print("  ✅ API TEST COMPLETE")
            print("=" * 80)
            print()
            
        except requests.exceptions.ConnectionError:
            print("❌ Error: Cannot connect to API server")
            print("   Make sure server is running: python3 api_server.py")
            sys.exit(1)
