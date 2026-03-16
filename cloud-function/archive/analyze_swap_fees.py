#!/usr/bin/env python3
"""Calculate overnight swap fee impact on Phase 4 winner"""
import pandas as pd

# Load Phase 4 winner orders
orders = pd.read_csv('data/optimization/2026-03-09/run_20260309_081022/rank01_ST2.0_SMA15-50_BB2.0_PIP1_ATR2x6/orders.csv')
orders['entry_time'] = pd.to_datetime(orders['entry_time'])
orders['exit_time'] = pd.to_datetime(orders['exit_time'])
orders['holding_hours'] = (orders['exit_time'] - orders['entry_time']).dt.total_seconds() / 3600
orders['holding_days'] = orders['holding_hours'] / 24
orders['entry_dow'] = orders['entry_time'].dt.dayofweek

# Overnight trades (held > 17 hours crosses day boundary)
overnight_trades = orders[orders['holding_hours'] > 17]

print('='*80)
print('💤 OVERNIGHT HOLDING & SWAP FEE ANALYSIS')
print('='*80)
print(f'\nTrades held overnight: {len(overnight_trades)} / {len(orders)} ({len(overnight_trades)/len(orders)*100:.1f}%)')
print(f'Total holding days: {overnight_trades["holding_days"].sum():.1f} days')
print(f'Average hold per overnight trade: {overnight_trades["holding_days"].mean():.1f} days')

# Capital.com Gold swap rates (typical):
# Long: -0.0082% per day
# Short: -0.0074% per day  
# Average: ~0.008% = $0.80 per $10k position per day
# Weekend: 3x charge (applied Friday close)

position_size = 10000  # Effective $10k position
daily_swap_rate = 0.00008  # 0.008%
daily_swap_cost = position_size * daily_swap_rate  # $0.80/day

print(f'\n📊 SWAP FEE RATES (Capital.com Gold typical):')
print(f'Daily rate: {daily_swap_rate*100:.4f}% = ${daily_swap_cost:.2f}/day per $10k position')
print(f'Weekend charge: 3x (${daily_swap_cost * 3:.2f} applied Friday)')

# Calculate total swap costs
total_swap_cost = 0
for idx, trade in overnight_trades.iterrows():
    days = trade['holding_days']
    # Count weekends (roughly 1 per 7 days)
    weekends = int(days / 7)
    normal_days = days - (weekends * 2)  
    
    # Normal: 1x daily rate, Weekends: 3x daily rate
    swap_cost = (normal_days * daily_swap_cost) + (weekends * 3 * daily_swap_cost)
    total_swap_cost += swap_cost

print(f'\n💰 TOTAL SWAP COST ESTIMATE:')
print(f'Total swap fees: ${total_swap_cost:.2f}')
print(f'Avg per overnight trade: ${total_swap_cost/len(overnight_trades):.2f}')

# Performance impact
original_pnl = orders['pnl'].sum()
adjusted_pnl = original_pnl - total_swap_cost
original_return = (original_pnl / 10000) * 100
adjusted_return = (adjusted_pnl / 10000) * 100

print(f'\n📈 PERFORMANCE IMPACT:')
print(f'Original P&L:    ${original_pnl:,.2f} ({original_return:.2f}%)')
print(f'Swap fees:       -${total_swap_cost:.2f}')
print(f'Adjusted P&L:    ${adjusted_pnl:,.2f} ({adjusted_return:.2f}%)')
print(f'Return reduction: {original_return - adjusted_return:.2f}%')
print(f'Profit lost to fees: {(total_swap_cost/original_pnl)*100:.2f}%')

# Weekend-specific analysis
orders['crosses_weekend'] = ((orders['entry_dow'] == 4) & (orders['holding_hours'] >= 15)) | \
                             ((orders['entry_dow'] <= 4) & (orders['holding_days'] > 2))
weekend_trades = orders[orders['crosses_weekend']]

weekend_swap = 0
for idx, trade in weekend_trades.iterrows():
    days = trade['holding_days']
    weekends = max(1, int(days / 7))  # At least 1 weekend
    normal_days = days - (weekends * 2)
    swap_cost = (normal_days * daily_swap_cost) + (weekends * 3 * daily_swap_cost)
    weekend_swap += swap_cost

weekend_original_pnl = weekend_trades['pnl'].sum()
weekend_adjusted_pnl = weekend_original_pnl - weekend_swap
non_weekend_pnl = orders[~orders['crosses_weekend']]['pnl'].sum()

print(f'\n⚠️  WEEKEND HOLDING DETAIL:')
print(f'Weekend trades: {len(weekend_trades)} trades')
print(f'Original weekend P&L:  ${weekend_original_pnl:,.2f}')
print(f'Weekend swap fees:     -${weekend_swap:.2f}')
print(f'Adjusted weekend P&L:  ${weekend_adjusted_pnl:,.2f}')
print(f'Fee % of weekend profit: {(weekend_swap/weekend_original_pnl)*100:.1f}%')

print(f'\n✅ WEEKEND vs NON-WEEKEND (after fees):')
print(f'Weekend (adj):  ${weekend_adjusted_pnl:,.2f} from {len(weekend_trades)} trades')
print(f'Non-weekend:    ${non_weekend_pnl:,.2f} from {len(orders)-len(weekend_trades)} trades')
print(f'Weekend avg P&L: ${weekend_adjusted_pnl/len(weekend_trades):.2f}/trade')
print(f'Non-weekend avg: ${non_weekend_pnl/(len(orders)-len(weekend_trades)):.2f}/trade')

if weekend_adjusted_pnl > 0:
    print(f'\n✅ Weekend trades STILL profitable after swap fees!')
else:
    print(f'\n❌ Weekend trades LOSE money after swap fees!')

print('\n' + '='*80)
print('💡 CONCLUSION')
print('='*80)
print(f'Swap fees reduce return by {original_return - adjusted_return:.2f}%')
print(f'Final adjusted return: {adjusted_return:.2f}% (was {original_return:.2f}%)')
if weekend_adjusted_pnl/len(weekend_trades) > non_weekend_pnl/(len(orders)-len(weekend_trades)):
    print('Weekend trades STILL better than non-weekend even with fees')
else:
    print('⚠️  Swap fees make weekend trades WORSE than non-weekend!')
print('='*80)
