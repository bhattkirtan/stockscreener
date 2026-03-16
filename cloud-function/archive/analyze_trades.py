#!/usr/bin/env python3
import pandas as pd
import numpy as np
import sys
import glob
from pathlib import Path

# Accept command-line argument or find latest rank01
if len(sys.argv) > 1:
    orders_file = Path(sys.argv[1])
    if not orders_file.exists():
        print(f"❌ File not found: {orders_file}")
        sys.exit(1)
else:
    # Find latest Phase 4 results (any ATR config)
    phase4_dirs = sorted(glob.glob('data/optimization/2026-03-09/run_*/rank01_*'))
    if not phase4_dirs:
        print("❌ No Phase 4 rank01 results found")
        sys.exit(1)
    orders_file = Path(phase4_dirs[-1]) / 'orders.csv'

print(f"📂 Loading: {orders_file}\n")

# Load orders
df = pd.read_csv(orders_file)

# Parse dates and calculate holding periods
df['entry_time'] = pd.to_datetime(df['entry_time'])
df['exit_time'] = pd.to_datetime(df['exit_time'])
df['holding_hours'] = (df['exit_time'] - df['entry_time']).dt.total_seconds() / 3600
df['holding_days'] = df['holding_hours'] / 24

# Add day of week analysis
df['entry_dow'] = df['entry_time'].dt.dayofweek  # 0=Mon, 4=Fri
df['entry_hour'] = df['entry_time'].dt.hour
df['exit_dow'] = df['exit_time'].dt.dayofweek
df['exit_hour'] = df['exit_time'].dt.hour

# Weekend holding: entered before weekend, exited after
df['crosses_weekend'] = ((df['entry_dow'] == 4) & (df['entry_hour'] >= 15)) | \
                        ((df['entry_dow'] == 4) & (df['exit_dow'] >= 5)) | \
                        ((df['entry_dow'] <= 4) & (df['exit_dow'] == 0) & (df['holding_hours'] > 48))

wins = df[df['pnl'] > 0]
losses = df[df['pnl'] < 0]
weekend_trades = df[df['crosses_weekend']]

print("=" * 80)
print("📊 TRADE ANALYSIS")
print("=" * 80)
print(f"Total Trades: {len(df)}")
print(f"Winners: {len(wins)} ({len(wins)/len(df)*100:.1f}%)")
print(f"Losers: {len(losses)} ({len(losses)/len(df)*100:.1f}%)")
print(f"Total P&L: ${df['pnl'].sum():,.2f}")

print("\n" + "=" * 80)
print("📊 HOLDING PERIOD ANALYSIS")
print("=" * 80)
print(f"\n📈 Overall ({len(df)} trades):")
print(f"  Average:  {df['holding_hours'].mean():.1f} hours ({df['holding_days'].mean():.1f} days)")
print(f"  Median:   {df['holding_hours'].median():.1f} hours ({df['holding_days'].median():.1f} days)")
print(f"  Min:      {df['holding_hours'].min():.1f} hours")
print(f"  Max:      {df['holding_hours'].max():.1f} hours ({df['holding_days'].max():.1f} days)")

print(f"\n🎯 Winning Trades ({len(wins)}):")
print(f"  Average:  {wins['holding_hours'].mean():.1f} hours ({wins['holding_days'].mean():.1f} days)")
print(f"  Median:   {wins['holding_hours'].median():.1f} hours")

print(f"\n❌ Losing Trades ({len(losses)}):")
print(f"  Average:  {losses['holding_hours'].mean():.1f} hours ({losses['holding_days'].mean():.1f} days)")
print(f"  Median:   {losses['holding_hours'].median():.1f} hours")

print(f"\n🔄 Ratio: Winners hold {wins['holding_hours'].mean()/losses['holding_hours'].mean():.2f}x longer than losers")

print("\n" + "=" * 80)
print("📅 WEEKEND HOLDING RISK ANALYSIS")
print("=" * 80)
print(f"\nTrades crossing weekend: {len(weekend_trades)} ({len(weekend_trades)/len(df)*100:.1f}%)")
if len(weekend_trades) > 0:
    weekend_wins = weekend_trades[weekend_trades['pnl'] > 0]
    weekend_losses = weekend_trades[weekend_trades['pnl'] < 0]
    print(f"  Winners: {len(weekend_wins)} ({len(weekend_wins)/len(weekend_trades)*100:.1f}%)")
    print(f"  Losers: {len(weekend_losses)} ({len(weekend_losses)/len(weekend_trades)*100:.1f}%)")
    print(f"  Total P&L: ${weekend_trades['pnl'].sum():,.2f}")
    print(f"  Avg P&L: ${weekend_trades['pnl'].mean():.2f}")
    
    # Compare to non-weekend trades
    non_weekend = df[~df['crosses_weekend']]
    print(f"\nNon-weekend trades: {len(non_weekend)}")
    print(f"  Win Rate: {(non_weekend['pnl'] > 0).sum()/len(non_weekend)*100:.1f}%")
    print(f"  Avg P&L: ${non_weekend['pnl'].mean():.2f}")
    
    print(f"\n⚠️  Weekend trade performance vs non-weekend:")
    weekend_wr = (weekend_trades['pnl'] > 0).sum()/len(weekend_trades)*100
    non_weekend_wr = (non_weekend['pnl'] > 0).sum()/len(non_weekend)*100
    print(f"  Win Rate: {weekend_wr:.1f}% vs {non_weekend_wr:.1f}% ({weekend_wr - non_weekend_wr:+.1f}%)")

print("\n" + "=" * 80)
print("🚪 EXIT REASON BREAKDOWN")
print("=" * 80)
for reason, count in df['exit_reason'].value_counts().items():
    pct = (count / len(df)) * 100
    avg_pnl = df[df['exit_reason'] == reason]['pnl'].mean()
    subset = df[df['exit_reason'] == reason]
    win_rate = (subset['pnl'] > 0).sum() / len(subset) * 100
    print(f"{reason:20s}: {count:3d} ({pct:5.1f}%) | Avg P&L: ${avg_pnl:7.2f} | Win Rate: {win_rate:5.1f}%")

print("\n" + "=" * 80)
print("🔍 RISK:REWARD VERIFICATION")
print("=" * 80)
sample = df.head(10)
sl_dist = []
tp_dist = []
for i in range(min(10, len(sample))):
    sl = abs(sample.iloc[i]['entry_price'] - sample.iloc[i]['stop_loss'])
    tp = abs(sample.iloc[i]['take_profit'] - sample.iloc[i]['entry_price'])
    sl_dist.append(sl)
    tp_dist.append(tp)
    print(f"Trade {i+1}: SL=${sl:.2f}, TP=${tp:.2f}, R:R=1:{tp/sl:.2f}")

avg_sl = np.mean(sl_dist)
avg_tp = np.mean(tp_dist)
print(f"\n✅ Average: SL=${avg_sl:.2f}, TP=${avg_tp:.2f}, R:R=1:{avg_tp/avg_sl:.2f}")

print("\n" + "=" * 80)
print("📉 LOSS TRADE DETAILED ANALYSIS")
print("=" * 80)
print(f"\nTotal Losing Trades: {len(losses)}")
print(f"Total Loss Amount: ${losses['pnl'].sum():,.2f}")
print(f"Average Loss: ${losses['pnl'].mean():.2f}")

print("\n🕐 Losses by Entry Hour (UTC):")
loss_by_hour = losses.groupby('entry_hour').agg({
    'pnl': ['count', 'sum', 'mean']
}).round(2)
loss_by_hour.columns = ['Count', 'Total_Loss', 'Avg_Loss']
loss_by_hour = loss_by_hour.sort_values('Count', ascending=False).head(10)
print(loss_by_hour)

print("\n📅 Losses by Day of Week:")
dow_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
loss_by_dow = losses.groupby('entry_dow').agg({
    'pnl': ['count', 'sum', 'mean']
}).round(2)
loss_by_dow.columns = ['Count', 'Total_Loss', 'Avg_Loss']
loss_by_dow.index = [dow_names[i] if i < 5 else f'Day_{i}' for i in loss_by_dow.index]
print(loss_by_dow)

# Friday afternoon analysis
friday_afternoon = losses[(losses['entry_dow'] == 4) & (losses['entry_hour'] >= 15)]
print(f"\n⚠️  Friday After 3 PM Losses: {len(friday_afternoon)} trades")
if len(friday_afternoon) > 0:
    print(f"   Total Loss: ${friday_afternoon['pnl'].sum():.2f}") 
    print(f"   % of all losses: {len(friday_afternoon)/len(losses)*100:.1f}%")

# Weekend crossing losses
weekend_losses_only = losses[losses['crosses_weekend']]
print(f"\n⚠️  Weekend-Crossing Losses: {len(weekend_losses_only)} trades")
if len(weekend_losses_only) > 0:
    print(f"   Total Loss: ${weekend_losses_only['pnl'].sum():.2f}")
    print(f"   Avg Hold: {weekend_losses_only['holding_hours'].mean():.1f} hours")
    print(f"   % of all losses: {len(weekend_losses_only)/len(losses)*100:.1f}%")

print("\n" + "=" * 80)
print("📉 TOP 10 WORST LOSING TRADES")
print("=" * 80)
worst = losses.sort_values('pnl').head(10)
print(f"\n{'Date':19s} | {'Side':4s} | {'P&L':>10s} | {'Hold(h)':>8s} | {'Day':9s} | {'Hour':4s} | {'Weekend?':8s}")
print("-" * 80)
for idx, row in worst.iterrows():
    weekend_flag = "YES" if row['crosses_weekend'] else "NO"
    day_name = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][row['entry_dow']]
    print(f"{row['entry_time'].strftime('%Y-%m-%d %H:%M'):19s} | {row['side']:4s} | ${row['pnl']:>9.2f} | {row['holding_hours']:>8.1f} | {day_name:9s} | {row['entry_hour']:>4d} | {weekend_flag:8s}")

print("\n" + "=" * 80)
print("💡 RECOMMENDATIONS TO FIX LOSSES")
print("=" * 80)

# Calculate impact of potential filters
friday_late_losses = len(losses[(losses['entry_dow'] == 4) & (losses['entry_hour'] >= 15)])
friday_late_loss_amt = losses[(losses['entry_dow'] == 4) & (losses['entry_hour'] >= 15)]['pnl'].sum()
friday_late_wins = len(wins[(wins['entry_dow'] == 4) & (wins['entry_hour'] >= 15)])
friday_late_win_amt = wins[(wins['entry_dow'] == 4) & (wins['entry_hour'] >= 15)]['pnl'].sum()

print(f"\n1️⃣  AVOID FRIDAY AFTERNOON ENTRIES (after 15:00 UTC):")
print(f"   Would eliminate: {friday_late_losses} losses (${friday_late_loss_amt:.2f})")
print(f"   Would also lose: {friday_late_wins} wins (${friday_late_win_amt:.2f})")
print(f"   Net impact: ${friday_late_loss_amt + friday_late_win_amt:+.2f}")

# Weekend crossing filter
weekend_cross_losses = len(weekend_losses_only)
weekend_cross_loss_amt = weekend_losses_only['pnl'].sum() if len(weekend_losses_only) > 0 else 0
weekend_cross_wins = len(weekend_trades[weekend_trades['pnl'] > 0])
weekend_cross_win_amt = weekend_trades[weekend_trades['pnl'] > 0]['pnl'].sum() if len(weekend_trades[weekend_trades['pnl'] > 0]) > 0 else 0

print(f"\n2️⃣  CLOSE ALL POSITIONS BEFORE WEEKEND:")
print(f"   Would eliminate: {weekend_cross_losses} losses (${weekend_cross_loss_amt:.2f})")
print(f"   Would also lose: {weekend_cross_wins} wins (${weekend_cross_win_amt:.2f})")
print(f"   Net impact: ${weekend_cross_loss_amt + weekend_cross_win_amt:+.2f}")

# Worst hour filter
if len(loss_by_hour) > 0:
    worst_hour = loss_by_hour.index[0]
    worst_hour_losses = len(losses[losses['entry_hour'] == worst_hour])
    worst_hour_loss_amt = losses[losses['entry_hour'] == worst_hour]['pnl'].sum()
    worst_hour_wins = len(wins[wins['entry_hour'] == worst_hour])
    worst_hour_win_amt = wins[wins['entry_hour'] == worst_hour]['pnl'].sum()

    print(f"\n3️⃣  AVOID WORST HOUR ({worst_hour}:00 UTC):")
    print(f"   Would eliminate: {worst_hour_losses} losses (${worst_hour_loss_amt:.2f})")
    print(f"   Would also lose: {worst_hour_wins} wins (${worst_hour_win_amt:.2f})")
    print(f"   Net impact: ${worst_hour_loss_amt + worst_hour_win_amt:+.2f}")

print("\n" + "=" * 80)
print("⚡ LEVERAGE ANALYSIS (20× LEVERAGE)")
print("=" * 80)

# Parse config to get initial capital
import json
config_file = Path(orders_file).parent / 'config.json'
if config_file.exists():
    with open(config_file) as f:
        config = json.load(f)
    initial_capital = config.get('initial_capital', 10000)
else:
    initial_capital = 10000

# Test with different capital amounts
CAPITAL_OPTIONS = [2000, 10000]
LEVERAGE = 20

# Calculate cumulative P&L and equity curve
df_sorted = df.sort_values('entry_time')
df_sorted['cumulative_pnl'] = df_sorted['pnl'].cumsum()
df_sorted['equity'] = initial_capital + df_sorted['cumulative_pnl']

# Calculate drawdown
df_sorted['peak'] = df_sorted['equity'].cummax()
df_sorted['drawdown_pct'] = ((df_sorted['equity'] - df_sorted['peak']) / df_sorted['peak'] * 100)
max_drawdown_pct = df_sorted['drawdown_pct'].min()

final_capital = initial_capital + df['pnl'].sum()
total_return_pct = (final_capital - initial_capital) / initial_capital * 100

print(f"\n📊 BASE BACKTEST PERFORMANCE (${initial_capital:,.0f} capital, no leverage):")
print(f"   Initial Capital: ${initial_capital:,.0f}")
print(f"   Final Capital: ${final_capital:,.0f}")
print(f"   Total Profit: ${df['pnl'].sum():,.0f}")
print(f"   Return: {total_return_pct:.2f}%")
print(f"   Max Drawdown: {max_drawdown_pct:.2f}%")

# Calculate days
days_traded = (df['entry_time'].max() - df['entry_time'].min()).days
months_traded = days_traded / 30
years_traded = days_traded / 365

# Analyze both capital scenarios
for USER_CAPITAL in CAPITAL_OPTIONS:
    print("\n" + "=" * 80)
    print(f"💰 SCENARIO: ${USER_CAPITAL:,.0f} CAPITAL")
    print("=" * 80)
    
    # Scale to user's capital
    # The return % is the same, but absolute dollars scale
    user_profit = USER_CAPITAL * (total_return_pct / 100)
    user_final = USER_CAPITAL + user_profit

    print(f"\n💵 NO LEVERAGE:")
    print(f"   • Initial: ${USER_CAPITAL:,.0f}")
    print(f"   • Return: {total_return_pct:.2f}%")
    print(f"   • Profit: ${user_profit:,.0f}")
    print(f"   • Final: ${user_final:,.0f}")
    print(f"   • Max Drawdown: {max_drawdown_pct:.2f}% (${USER_CAPITAL * abs(max_drawdown_pct)/100:,.0f} loss)")
    
    # Leveraged calculations with user's capital
    leveraged_position_size = USER_CAPITAL * LEVERAGE
    leveraged_profit = user_profit * LEVERAGE  # Profit scales with leverage
    leveraged_final = USER_CAPITAL + leveraged_profit
    leveraged_return_pct = (leveraged_final - USER_CAPITAL) / USER_CAPITAL * 100
    leveraged_max_dd_pct = max_drawdown_pct * LEVERAGE

    print(f"\n⚡ FULL {LEVERAGE}× LEVERAGE (using all ${USER_CAPITAL:,.0f}):")
    print(f"   • Position Size: ${leveraged_position_size:,.0f}")
    print(f"   • Profit: ${leveraged_profit:,.0f}")
    print(f"   • Final: ${leveraged_final:,.0f}")
    print(f"   • Return: {leveraged_return_pct:.2f}%")
    print(f"   • Max Drawdown: {leveraged_max_dd_pct:.2f}%")

    # Liquidation risk
    liquidation_threshold = 100 / LEVERAGE  # 5% for 20x leverage
    
    if abs(leveraged_max_dd_pct) > 100:
        times_liquidated = int(abs(leveraged_max_dd_pct) / 100)
        print(f"   🚨 WOULD BE LIQUIDATED {times_liquidated}× - NOT VIABLE!")
    else:
        print(f"   ✅ Would survive (drawdown < 100%)")

    # Calculate safe position sizing for 20x leverage
    max_safe_capital_pct = 95 / abs(leveraged_max_dd_pct)  # Percent of capital to use per trade
    safe_position_size = USER_CAPITAL * max_safe_capital_pct
    safe_effective_leverage = max_safe_capital_pct * LEVERAGE

    print(f"\n✅ SAFE {LEVERAGE}× LEVERAGE (recommended):")
    print(f"   • Use only {max_safe_capital_pct*100:.1f}% of ${USER_CAPITAL:,.0f} per trade")
    print(f"   • Position size per trade: ${safe_position_size:,.0f}")
    print(f"   • Effective leverage: {safe_effective_leverage:.1f}×")
    print(f"   • Reserve buffer: ${USER_CAPITAL * (1-max_safe_capital_pct):,.0f} ({(1-max_safe_capital_pct)*100:.1f}%)")
    print(f"   • Max drawdown: ~95% (safe)")

    safe_leveraged_return = total_return_pct * safe_effective_leverage
    safe_leveraged_profit = (USER_CAPITAL * safe_leveraged_return / 100)
    safe_leveraged_final = USER_CAPITAL + safe_leveraged_profit

    print(f"\n📊 SAFE LEVERAGE PERFORMANCE:")
    print(f"   • Total Return: {safe_leveraged_return:.2f}%")
    print(f"   • Total Profit: ${safe_leveraged_profit:,.0f}")
    print(f"   • Final Capital: ${safe_leveraged_final:,.0f}")
    print(f"   • Monthly Return: {safe_leveraged_return/months_traded:.2f}%/month")
    print(f"   • Avg Profit/Month: ${safe_leveraged_profit/months_traded:,.0f}/month")

print("\n" + "=" * 80)
print("📅 BACKTEST PERIOD")
print("=" * 80)
print(f"Duration: {days_traded} days ({months_traded:.1f} months, {years_traded:.1f} years)")
print(f"Base Monthly Return: {total_return_pct/months_traded:.2f}%/month")

print("\n" + "=" * 80)
