#!/usr/bin/env python3
"""
Validate consistency between backtester and live bot configurations.
"""

import sys
import os

# Add both code paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
sys.path.insert(0, '/Users/kirtanbhatt/code/stockScreener/trading-bot-skills')

from core.backtester import BacktestConfig

# Import from trading-bot-skills
sys.path.insert(0, '/Users/kirtanbhatt/code/stockScreener/trading-bot-skills/core')
from cost_calculator import GOLD_COST_CONFIG

def validate_costs():
    """Check if transaction costs match between systems."""
    backtest_config = BacktestConfig()
    
    print("=" * 70)
    print("TRANSACTION COST VALIDATION")
    print("=" * 70)
    
    print("\n📊 BACKTESTER COST CONFIG:")
    print(f"   Spread Cost:   ${backtest_config.spread_cost_usd:.2f}")
    print(f"   Slippage Cost: ${backtest_config.slippage_cost_usd:.2f}")
    print(f"   Pip Value:     {backtest_config.pip_value}")
    backtest_total = backtest_config.spread_cost_usd + backtest_config.slippage_cost_usd
    print(f"   TOTAL:         ${backtest_total:.2f}")
    
    print("\n🤖 LIVE BOT COST CONFIG:")
    print(f"   Spread Pips:   {GOLD_COST_CONFIG.spread_pips}")
    print(f"   Slippage Pips: {GOLD_COST_CONFIG.slippage_pips}")
    print(f"   Pip Value:     {GOLD_COST_CONFIG.pip_value}")
    live_total = (GOLD_COST_CONFIG.spread_pips * GOLD_COST_CONFIG.pip_value + 
                  GOLD_COST_CONFIG.slippage_pips * GOLD_COST_CONFIG.pip_value)
    print(f"   TOTAL:         ${live_total:.2f}")
    
    print("\n" + "=" * 70)
    if abs(backtest_total - live_total) < 0.01:
        print("✅ PASS: Transaction costs match perfectly!")
    else:
        print(f"❌ FAIL: Cost mismatch! Backtest=${backtest_total:.2f}, Live=${live_total:.2f}")
    print("=" * 70)

if __name__ == "__main__":
    validate_costs()
