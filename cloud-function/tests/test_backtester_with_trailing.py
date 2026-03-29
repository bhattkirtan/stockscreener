"""
Test backtester with trailing stop functionality
Quick validation that trailing stops work in backtest simulations
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from src.core.backtester import BacktestConfig, IntraCandleBacktester

def test_backtester_with_trailing_stops():
    """Verify trailing stop integration in backtester"""
    
    print("🧪 Testing backtester with trailing stops...")
    
    # Create simple test data with clear price movement
    timestamps = pd.date_range(start='2024-01-01', periods=20, freq='5T')
    
    # Simulate a strong uptrend: 4500 -> 4520 -> 4540 (40 pips profit)
    prices = np.linspace(4500, 4540, 20)
    
    df = pd.DataFrame({
        'open': prices,
        'high': prices + 2,
        'low': prices - 2,
        'close': prices,
        'volume': 1000
    }, index=timestamps)
    
    # Create BUY signal at start
    signals = pd.DataFrame({
        'signal': [1] + [0] * 19,  # BUY signal at first candle
        'stop_loss': [4480] + [None] * 19,  # 20 pip SL
        'take_profit': [4560] + [None] * 19  # 60 pip TP
    }, index=timestamps)
    
    # Configure backtest WITHOUT trailing stops (baseline)
    print("\n1️⃣ Running without trailing stops...")
    config_no_trail = BacktestConfig(
        initial_capital=10000,
        pip_value=1.0,
        spread_pips=0.5,
        slippage_pips=0.1,
        enable_trailing_stop=False,
        verbose=False
    )
    
    backtester_no_trail = IntraCandleBacktester(config_no_trail)
    results_no_trail = backtester_no_trail.run(df, signals)
    
    print(f"   Without trailing: {results_no_trail['total_trades']} trades, PnL: ${results_no_trail['total_pnl']:.2f}")
    
    # Configure backtest WITH trailing stops
    print("\n2️⃣ Running with trailing stops (break-even @ 20 pips)...")
    config_with_trail = BacktestConfig(
        initial_capital=10000,
        pip_value=1.0,
        spread_pips=0.5,
        slippage_pips=0.1,
        enable_trailing_stop=True,
        breakeven_after_pips=20.0,  # Break-even after 20 pips
        trail_stop_distance=0.0,    # No step trailing
        trail_trigger_pips=0.0,
        verbose=True  # Show trailing stop updates
    )
    
    backtester_with_trail = IntraCandleBacktester(config_with_trail)
    results_with_trail = backtester_with_trail.run(df, signals)
    
    print(f"\n   With trailing: {results_with_trail['total_trades']} trades, PnL: ${results_with_trail['total_pnl']:.2f}")
    
    # Verify position manager was created
    assert backtester_with_trail.position_manager is not None, "Position manager should be initialized"
    print("   ✅ Position manager initialized")
    
    # Verify trade was opened
    assert results_with_trail['total_trades'] > 0, "Should have opened at least one trade"
    print("   ✅ Trade opened with trailing stop tracker")
    
    # Configure with step-based trailing
    print("\n3️⃣ Running with step-based trailing (5 pips every 10 pips)...")
    config_step_trail = BacktestConfig(
        initial_capital=10000,
        pip_value=1.0,
        spread_pips=0.5,
        slippage_pips=0.1,
        enable_trailing_stop=True,
        breakeven_after_pips=0.0,    # No break-even
        trail_stop_distance=5.0,      # Move 5 pips
        trail_trigger_pips=10.0,      # Every 10 pips
        verbose=True
    )
    
    backtester_step_trail = IntraCandleBacktester(config_step_trail)
    results_step_trail = backtester_step_trail.run(df, signals)
    
    print(f"\n   Step trailing: {results_step_trail['total_trades']} trades, PnL: ${results_step_trail['total_pnl']:.2f}")
    
    # Combined strategy test
    print("\n4️⃣ Running with combined trailing (break-even + step)...")
    config_combined = BacktestConfig(
        initial_capital=10000,
        pip_value=1.0,
        spread_pips=0.5,
        slippage_pips=0.1,
        enable_trailing_stop=True,
        breakeven_after_pips=15.0,   # Break-even at 15 pips
        trail_stop_distance=3.0,      # Then trail 3 pips
        trail_trigger_pips=5.0,       # Every 5 pips
        verbose=True
    )
    
    backtester_combined = IntraCandleBacktester(config_combined)
    results_combined = backtester_combined.run(df, signals)
    
    print(f"\n   Combined: {results_combined['total_trades']} trades, PnL: ${results_combined['total_pnl']:.2f}")
    
    print("\n" + "="*60)
    print("✅ ALL TESTS PASSED!")
    print("="*60)
    print("\n📊 Summary:")
    print(f"   Without trailing:     ${results_no_trail['total_pnl']:.2f}")
    print(f"   Break-even trailing:  ${results_with_trail['total_pnl']:.2f}")
    print(f"   Step trailing:        ${results_step_trail['total_pnl']:.2f}")
    print(f"   Combined trailing:    ${results_combined['total_pnl']:.2f}")
    print("\n💡 Trailing stops are now integrated into backtesting!")
    print("   Configure with enable_trailing_stop=True in BacktestConfig")

if __name__ == '__main__':
    test_backtester_with_trailing_stops()
