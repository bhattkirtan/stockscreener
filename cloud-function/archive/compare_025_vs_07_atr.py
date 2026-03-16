"""
Compare 0.25× ATR SL vs 0.7× ATR SL (previous best)
"""

# Previous best (M5 with 0.7× ATR SL, 2.5× ATR TP)
m5_07 = {
    'sl': '0.7× ATR',
    'tp': '2.5× ATR',
    'rr': '1:3.56',
    'return': 122.41,
    'trades': 866,
    'win_rate': 25.2,
    'profit_factor': 1.99,
    'sharpe': 0.65,
    'max_dd': 56.0,
    'days': 771,
    'months': 25.3
}

# New test (M5 with 0.25× ATR SL, 2.5× ATR TP)
m5_025 = {
    'sl': '0.25× ATR',
    'tp': '2.5× ATR',
    'rr': '1:10',
    'return': 83.29,
    'trades': 1773,
    'win_rate': 11.17,
    'profit_factor': 1.09,
    'sharpe': 0.056,
    'max_dd': 23.49,
    'days': 771,
    'months': 25.3
}

# Calculate monthly metrics
m5_07['monthly_return'] = m5_07['return'] / m5_07['months']
m5_07['trades_per_month'] = m5_07['trades'] / m5_07['months']

m5_025['monthly_return'] = m5_025['return'] / m5_025['months']
m5_025['trades_per_month'] = m5_025['trades'] / m5_025['months']

print("\n" + "="*100)
print("⚖️  M5: 0.7× ATR SL (Previous Best) vs 0.25× ATR SL (New Test)")
print("="*100)

print("\n1️⃣  PERFORMANCE COMPARISON")
print("-"*100)
print(f"{'Metric':<35} | {'0.7× ATR SL (Best)':<30} | {'0.25× ATR SL (New)':<30} | {'Winner':<15}")
print("-"*100)

# Returns
winner = "0.7× ATR" if m5_07['return'] > m5_025['return'] else "0.25× ATR"
diff = abs(m5_07['return'] - m5_025['return'])
print(f"{'Total Return':<35} | {m5_07['return']:>28.2f}% | {m5_025['return']:>28.2f}% | {winner} (+{diff:.1f}%)")

winner = "0.7× ATR" if m5_07['monthly_return'] > m5_025['monthly_return'] else "0.25× ATR"
diff = abs(m5_07['monthly_return'] - m5_025['monthly_return'])
print(f"{'Monthly Return':<35} | {m5_07['monthly_return']:>28.2f}% | {m5_025['monthly_return']:>28.2f}% | {winner} (+{diff:.2f}%)")

print("\n2️⃣  TRADE CHARACTERISTICS")
print("-"*100)
print(f"{'Metric':<35} | {'0.7× ATR SL (Best)':<30} | {'0.25× ATR SL (New)':<30} | {'Difference':<15}")
print("-"*100)

print(f"{'Total Trades':<35} | {m5_07['trades']:>30,} | {m5_025['trades']:>30,} | {'+' if m5_025['trades'] > m5_07['trades'] else ''}{m5_025['trades']-m5_07['trades']:,}")

pct_diff = (m5_025['trades_per_month'] - m5_07['trades_per_month']) / m5_07['trades_per_month'] * 100
print(f"{'Trades per Month':<35} | {m5_07['trades_per_month']:>30.1f} | {m5_025['trades_per_month']:>30.1f} | {'+' if pct_diff > 0 else ''}{pct_diff:.0f}%")

winner = "0.7× ATR" if m5_07['win_rate'] > m5_025['win_rate'] else "0.25× ATR"
diff = abs(m5_07['win_rate'] - m5_025['win_rate'])
print(f"{'Win Rate':<35} | {m5_07['win_rate']:>28.1f}% | {m5_025['win_rate']:>28.1f}% | {winner} ({'-' if m5_025['win_rate'] < m5_07['win_rate'] else '+'}{diff:.1f}%)")

winner = "0.7× ATR" if m5_07['profit_factor'] > m5_025['profit_factor'] else "0.25× ATR"
diff = abs(m5_07['profit_factor'] - m5_025['profit_factor'])
print(f"{'Profit Factor':<35} | {m5_07['profit_factor']:>30.2f} | {m5_025['profit_factor']:>30.2f} | {winner} ({'-' if m5_025['profit_factor'] < m5_07['profit_factor'] else '+'}{diff:.2f})")

print("\n3️⃣  RISK METRICS")
print("-"*100)
print(f"{'Metric':<35} | {'0.7× ATR SL (Best)':<30} | {'0.25× ATR SL (New)':<30} | {'Winner':<15}")
print("-"*100)

winner = "0.7× ATR" if m5_07['sharpe'] > m5_025['sharpe'] else "0.25× ATR"
diff = abs(m5_07['sharpe'] - m5_025['sharpe'])
print(f"{'Sharpe Ratio':<35} | {m5_07['sharpe']:>30.2f} | {m5_025['sharpe']:>30.2f} | {winner} ({'-' if m5_025['sharpe'] < m5_07['sharpe'] else '+'}{diff:.2f})")

winner = "0.7× ATR" if m5_07['max_dd'] < m5_025['max_dd'] else "0.25× ATR"
pct_diff = (1 - m5_025['max_dd'] / m5_07['max_dd']) * 100
print(f"{'Max Drawdown':<35} | {m5_07['max_dd']:>28.1f}% | {m5_025['max_dd']:>28.1f}% | {winner} ({pct_diff:+.0f}%)")

# Return/DD ratio
m5_07_ret_dd = m5_07['return'] / m5_07['max_dd']
m5_025_ret_dd = m5_025['return'] / m5_025['max_dd']
winner = "0.7× ATR" if m5_07_ret_dd > m5_025_ret_dd else "0.25× ATR"
print(f"{'Return/Drawdown Ratio':<35} | {m5_07_ret_dd:>30.2f} | {m5_025_ret_dd:>30.2f} | {winner}")

print("\n4️⃣  STRATEGY PARAMETERS")
print("-"*100)
print(f"{'Parameter':<35} | {'0.7× ATR SL':<30} | {'0.25× ATR SL':<30} | {'Impact':<15}")
print("-"*100)
print(f"{'Stop Loss':<35} | {m5_07['sl']:<30} | {m5_025['sl']:<30} | {'71% tighter':<15}")
print(f"{'Take Profit':<35} | {m5_07['tp']:<30} | {m5_025['tp']:<30} | {'Same':<15}")
print(f"{'Risk:Reward Ratio':<35} | {m5_07['rr']:<30} | {m5_025['rr']:<30} | {'2.8× better':<15}")

print("\n" + "="*100)
print("🏆 VERDICT")
print("="*100)

print("\n📊 KEY FINDINGS:\n")

print("1. RETURNS:")
return_pct_diff = (m5_07['return'] - m5_025['return']) / m5_07['return'] * 100
print(f"   • 0.7× ATR: {m5_07['return']:.1f}% return")
print(f"   • 0.25× ATR: {m5_025['return']:.1f}% return")
print(f"   ❌ 0.25× ATR gives {return_pct_diff:.0f}% LESS return!")
print(f"   • Monthly: 0.7× = {m5_07['monthly_return']:.2f}% vs 0.25× = {m5_025['monthly_return']:.2f}%")

print("\n2. TRADE FREQUENCY:")
print(f"   • 0.7× ATR: {m5_07['trades_per_month']:.1f} trades/month")
print(f"   • 0.25× ATR: {m5_025['trades_per_month']:.1f} trades/month")
trades_increase = (m5_025['trades_per_month'] - m5_07['trades_per_month']) / m5_07['trades_per_month'] * 100
print(f"   ❌ 0.25× ATR has {trades_increase:.0f}% MORE trades! (70/mo vs 34/mo)")

print("\n3. WIN RATE:")
print(f"   • 0.7× ATR: {m5_07['win_rate']:.1f}% win rate")
print(f"   • 0.25× ATR: {m5_025['win_rate']:.1f}% win rate")
win_drop = m5_07['win_rate'] - m5_025['win_rate']
print(f"   ❌ 0.25× ATR has {win_drop:.1f}% LOWER win rate!")
print(f"   💀 Only 11% win rate means 89% of trades LOSE!")

print("\n4. PROFIT FACTOR:")
print(f"   • 0.7× ATR: {m5_07['profit_factor']:.2f} (excellent)")
print(f"   • 0.25× ATR: {m5_025['profit_factor']:.2f} (barely profitable)")
pf_drop = (m5_07['profit_factor'] - m5_025['profit_factor']) / m5_07['profit_factor'] * 100
print(f"   ❌ 0.25× ATR is {pf_drop:.0f}% worse!")

print("\n5. RISK:")
print(f"   • 0.7× ATR: {m5_07['max_dd']:.1f}% max drawdown")
print(f"   • 0.25× ATR: {m5_025['max_dd']:.1f}% max drawdown")
dd_improvement = (1 - m5_025['max_dd'] / m5_07['max_dd']) * 100
print(f"   ✅ 0.25× ATR has {dd_improvement:.0f}% less drawdown")
print(f"   ⚠️  But Sharpe ratio is {m5_07['sharpe']/m5_025['sharpe']:.1f}× worse!")

print("\n" + "="*100)
print("🎯 FINAL RECOMMENDATION")
print("="*100)

print("\n❌ DO NOT USE 0.25× ATR SL!\n")

print("   WHY IT FAILS:")
print(f"   1. {return_pct_diff:.0f}% lower returns (122% → 83%)")
print(f"   2. {trades_increase:.0f}% more trades (34/mo → 70/mo)")
print(f"   3. Only 11% win rate (89% trades lose!)")
print(f"   4. Profit factor barely above 1.0 (1.09 vs 1.99)")
print(f"   5. Sharpe ratio destroyed (0.65 → 0.06)")
print()
print("   THE PROBLEM:")
print("   • Stop too tight = getting stopped out on normal noise")
print("   • Can't ride winning trades = cutting winners short")
print("   • Need to win 9:1 to break even, only winning 1:9")
print("   • Transaction costs would eat most profit")
print()
print("   ✅ STICK WITH 0.7× ATR SL / 2.5× ATR TP")
print("   This is the PROVEN winner:")
print("   • 122% return over 25 months")
print("   • 34 trades/month (manageable)")
print("   • 25% win rate (sustainable)")
print("   • 1.99 profit factor (excellent)")
print("   • 0.65 Sharpe ratio (strong)")

print("\n💡 LESSON LEARNED:")
print("   Tighter stops ≠ Better strategy")
print("   You need room for price to breathe!")

print("\n" + "="*100)
