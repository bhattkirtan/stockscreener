#!/usr/bin/env python3
"""
Complete validation: Compare ALL settings between backtester and live bot.
Validates ORIGINAL bot (cloud-function/src/live_trading/config.py)
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))

# Import live bot config (ORIGINAL bot, not skills bot)
from src.live_trading.config import TradingConfig

# Load live bot config
live_config = TradingConfig()

# Backtest parameters (from rank01 config)
backtest_params = {
    'supertrend_period': 7,
    'supertrend_multiplier': 2.0,
    'sma_fast': 25,
    'sma_slow': 30,
    'bb_period': 20,
    'bb_std': 2.0,
    'sl_pips': 20,
    'tp_pips': 40
}

# Extract live bot parameters from ORIGINAL bot config
live_params = {
    'supertrend_period': live_config.supertrend_period,
    'supertrend_multiplier': live_config.supertrend_multiplier,
    'sma_fast': live_config.sma_fast,
    'sma_slow': live_config.sma_slow,
    'bb_period': live_config.bb_period,
    'bb_std': live_config.bb_std,
    'sl_pips': live_config.sl_pips_fixed,
    'tp_pips': live_config.tp_pips_fixed
}

print("=" * 70)
print("COMPLETE PARAMETER VALIDATION - ORIGINAL BOT")
print("Source: cloud-function/src/live_trading/config.py")
print("=" * 70)
print()
print(f"{'Parameter':<25} {'Backtest':<15} {'Live Bot':<15} {'Status':<10}")
print("-" * 70)

all_match = True
for key in backtest_params:
    backtest_val = backtest_params[key]
    live_val = live_params[key]
    match = backtest_val == live_val
    status = "✅ MATCH" if match else "❌ MISMATCH"
    if not match:
        all_match = False
    print(f"{key:<25} {str(backtest_val):<15} {str(live_val):<15} {status:<10}")

print("=" * 70)
if all_match:
    print("✅ PERFECT SYNC: All parameters match 100%!")
    print()
    print("Trading Hours Configuration:")
    print(f"  - Enabled: {live_config.enable_trading_hours}")
    print(f"  - Daily break: {live_config.daily_break_start}:00-{live_config.daily_break_end}:00 UTC")
    print(f"  - Friday close: {live_config.friday_close_hour}:00 UTC")
    print(f"  - Weekends: {'Allowed' if live_config.allow_weekends else 'Closed'}")
else:
    print("❌ SYNC FAILED: Some parameters don't match")
print("=" * 70)
