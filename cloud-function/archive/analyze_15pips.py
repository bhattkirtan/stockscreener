#!/usr/bin/env python3
import pandas as pd
import os

# Load all strategies
df = pd.read_csv('data/optimization/2026-03-14/run_20260314_160407/GOLD_M5_all_strategies_20260314_160407.csv')

# Filter for 15 pips TP strategies
tp15_strategies = df[df['strategy_name'].str.contains('F5-15', na=False)].copy()

# Add rank based on original position in df
tp15_strategies['rank'] = tp15_strategies.index + 1

print('='*100)
print(f'ALL STRATEGIES WITH 15 PIPS TP (F5-15): {len(tp15_strategies)} total')
print('='*100)

# Sort by return
tp15_sorted = tp15_strategies.sort_values('return_pct', ascending=False)

print(f'\nTOP 15 PIPS TP STRATEGIES:\n')
for idx, (_, row) in enumerate(tp15_sorted.head(15).iterrows(), 1):
    print(f'{idx:2d}. Overall Rank {row["rank"]:3d} | Return: {row["return_pct"]:7.2f}% | Trades: {int(row["total_trades"]):3d} | WR: {row["win_rate"]:5.1f}% | Sharpe: {row["sharpe_ratio"]:6.3f}')
    print(f'    {row["strategy_name"]}')

# Now analyze orders.csv for top 3
print('\n' + '='*100)
print('DETAILED LOSING TRADE ANALYSIS FOR TOP 3:')
print('='*100)

for idx, (_, row) in enumerate(tp15_sorted.head(3).iterrows(), 1):
    rank_num = int(row['rank'])
    strategy_name = row['strategy_name']
    
    # Find orders.csv file - rank folders are 1-indexed
    orders_file = f'data/optimization/2026-03-14/run_20260314_160407/rank{rank_num:02d}_{strategy_name}/orders.csv'
    
    if os.path.exists(orders_file):
        print(f'\n{idx}. Rank #{rank_num}: {strategy_name}')
        print('-'*100)
        
        orders = pd.read_csv(orders_file)
        wins = orders[orders['pnl'] > 0]
        losses = orders[orders['pnl'] < 0]
        
        # Calculate duration in bars (5-min bars)
        orders['entry_time'] = pd.to_datetime(orders['entry_time'])
        orders['exit_time'] = pd.to_datetime(orders['exit_time'])
        orders['duration_bars'] = (orders['exit_time'] - orders['entry_time']).dt.total_seconds() / 300
        
        wins_duration = wins['duration_bars'].mean() if len(wins) > 0 else 0
        losses_duration = losses['duration_bars'].mean() if len(losses) > 0 else 0
        
        print(f'  Total Trades: {len(orders)} | Wins: {len(wins)} ({len(wins)/len(orders)*100:.1f}%) | Losses: {len(losses)} ({len(losses)/len(orders)*100:.1f}%)')
        print(f'  Avg Win Duration:  {wins_duration:7.1f} bars ({wins_duration/12:6.1f} hours)')
        print(f'  Avg Loss Duration: {losses_duration:7.1f} bars ({losses_duration/12:6.1f} hours)')
        print(f'  Avg Win:  {wins["pnl"].mean():8.2f} pips')
        print(f'  Avg Loss: {losses["pnl"].mean():8.2f} pips')
        print(f'  Total P&L: {orders["pnl"].sum():8.2f} pips')

# Summary
print('\n' + '='*100)
print('SUMMARY STATISTICS FOR ALL 15 PIPS TP STRATEGIES:')
print(f'  Total strategies:  {len(tp15_strategies)}')
print(f'  Avg return:        {tp15_strategies["return_pct"].mean():.2f}%')
print(f'  Best return:       {tp15_strategies["return_pct"].max():.2f}%')
print(f'  Avg win rate:      {tp15_strategies["win_rate"].mean():.1f}%')
print(f'  Avg trades:        {tp15_strategies["total_trades"].mean():.0f}')
print(f'  Avg Sharpe:        {tp15_strategies["sharpe_ratio"].mean():.3f}')
print('='*100)
