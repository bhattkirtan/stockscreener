#!/usr/bin/env python3
import pandas as pd
import sys
from pathlib import Path
import glob

# Use latest optimization run
latest_dir = Path('data/optimization/latest')
csv_files = list(latest_dir.glob('GOLD_M5_all_strategies_*.csv'))
if not csv_files:
    print("❌ No results found in latest/")
    sys.exit(1)
results_file = csv_files[0]
print(f"📊 Loading: {results_file}\n")

df = pd.read_csv(results_file)
rank1 = df.iloc[0]

print('=' * 80)
print('🏆 RANK #1 STRATEGY: ST3.0, SMA 15-30, BB 2.0, ATR 2x:4x')
print('=' * 80)
print()
print('📊 TRAINING SET (70% of data - Oct 28 to Feb 10):')
print(f'   Return:        {rank1["return_pct"]:.2f}%')
print(f'   Profit:        ${rank1["total_pnl"]:.2f}')
print(f'   Sharpe Ratio:  {rank1["sharpe_ratio"]:.3f}')
print(f'   Max Drawdown:  {rank1["max_drawdown_pct"]:.2f}%')
print(f'   Win Rate:      {rank1["win_rate"]:.2f}%')
print(f'   Profit Factor: {rank1["profit_factor"]:.2f}')
print(f'   Total Trades:  {int(rank1["total_trades"])}')
print()
print('📊 TEST SET (30% of data - Feb 10 to Mar 6):')
print(f'   Return:        {rank1["test_return_pct"]:.2f}%')
print(f'   Profit:        ${rank1["test_total_pnl"]:.2f}')
print(f'   Sharpe Ratio:  {rank1["test_sharpe_ratio"]:.3f}')
print(f'   Max Drawdown:  {rank1["test_max_drawdown_pct"]:.2f}%')
print(f'   Win Rate:      {rank1["test_win_rate"]:.2f}%')
print(f'   Profit Factor: {rank1["test_profit_factor"]:.2f}')
print(f'   Total Trades:  {int(rank1["test_total_trades"])}')
print()
print('📈 VALIDATION METRICS:')
print(f'   Degradation:   {rank1["oos_degradation_pct"]:.2f}%')
if rank1['oos_degradation_pct'] < 0:
    print('   ✅ TEST OUTPERFORMED TRAIN (negative degradation = good!)')
else:
    status = "✅ Good" if rank1["oos_degradation_pct"] < 20 else "⚠️ Review"
    print(f'   Status: {status}')
print()
print('💰 COMBINED PERFORMANCE (4 months total):')
train_capital_final = 10000 + rank1["total_pnl"]
test_capital_final = 10000 + rank1["test_total_pnl"]
print(f'   Train: $10,000 → ${train_capital_final:.2f}')
print(f'   Test:  $10,000 → ${test_capital_final:.2f}')
print()
print('💡 FOR PRODUCTION (conservative estimate = use train metrics):')
print(f'   Expected Return:     {rank1["return_pct"]:.2f}%')
print(f'   Expected Drawdown:   {rank1["max_drawdown_pct"]:.2f}%')
print(f'   Risk/Reward Ratio:   {rank1["return_pct"] / rank1["max_drawdown_pct"]:.2f}x')
print(f'   Sharpe Ratio:        {rank1["sharpe_ratio"]:.3f}')
print('=' * 80)
