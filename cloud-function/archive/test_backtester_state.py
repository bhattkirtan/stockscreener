import sys
sys.path.insert(0, '/Users/kirtanbhatt/code/stockScreener/cloud-function')

import pandas as pd
import logging
logging.basicConfig(level=logging.ERROR)

from src.core.backtester import IntraCandleBacktester, BacktestConfig
from src.core.strategy import SupertrendVWAPStrategy

# Load data
df = pd.read_csv("data/GOLD_M5_5000bars.csv")
df['timestamp'] = pd.to_datetime(df['timestamp'])
df.set_index('timestamp', inplace=True)

print("="*80)
print("DIAGNOSTIC: Backtester Internal State")
print("="*80)

# Create strategy with rank02 parameters
strategy = SupertrendVWAPStrategy(
    supertrend_period=10,
    supertrend_multiplier=3.0,
    sma_fast=20,
    sma_slow=50,
    ema_period=21,
    bb_period=20,
    bb_std=2.0,
    sl_pips=30.0,
    tp_pips=90.0,
    pip_value=5.0
)

# Calculate indicators and signals
df_with_indicators = strategy.calculate_indicators(df.copy())
signals = strategy.generate_signals(df_with_indicators)

# Configure backtest
config = BacktestConfig(
    initial_capital=10000.0,
    pip_value=5.0,
    default_position_size=10.0,
    max_positions=1
)

# Run backtest
backtester = IntraCandleBacktester(config)
results = backtester.run(df_with_indicators, signals)

# Now inspect internal state
print(f"\nBacktester Internal Lists:")
print(f"  len(backtester.trades): {len(backtester.trades)}")
print(f"  len(backtester.closed_positions): {len(backtester.closed_positions)}")
print(f"  len(backtester.open_positions): {len(backtester.open_positions)}")

print(f"\nResults Dict:")
print(f"  results['total_trades']: {results['total_trades']}")
print(f"  len(results['trades']): {len(results['trades'])}")

# Check if they match
if len(backtester.trades) == len(backtester.closed_positions):
    print("\n✅ All trades are in closed_positions - no bug here!")
else:
    print(f"\n❌ BUG FOUND!")
    print(f"   backtester.trades has {len(backtester.trades)} entries")
    print(f"   backtester.closed_positions has {len(backtester.closed_positions)} entries")
    print(f"   MISSING: {len(backtester.trades) - len(backtester.closed_positions)} trades")
