import pandas as pd

df = pd.read_csv('/tmp/top20_strategies_comparison.csv')

print("\n" + "="*120)
print("📊 RISK-ADJUSTED COMPARISON: Top Strategy vs Lower Drawdown Alternative")
print("="*120)

# Compare ranks 1-4 vs 9-12
best_return = df.iloc[0]
best_risk_adj = df.iloc[8]  # Rank 9

print("\n1️⃣  HEAD-TO-HEAD COMPARISON")
print("-"*120)
print(f"{'Metric':<30} {'Rank 1-4 (Best Return)':<35} {'Rank 9-12 (Best Risk-Adj)':<35} {'Winner'}")
print("-"*120)

# Return metrics
print(f"{'Return':<30} {best_return['return_pct']:>6.2f}%  {'(Higher)':<26} {best_risk_adj['return_pct']:>6.2f}%  {'':>26} {'👑 Rank 1-4 (+17%)'}")
print(f"{'Final Value':<30} ${10000+best_return['total_pnl']:>9,.0f}  {'':>26} ${10000+best_risk_adj['total_pnl']:>9,.0f}  {'':>26} {'👑 Rank 1-4 (+$1,692)'}")

# Risk metrics
dd_diff = best_return['max_drawdown_pct'] - best_risk_adj['max_drawdown_pct']
print(f"{'Max Drawdown':<30} {best_return['max_drawdown_pct']:>6.2f}%  {'(Higher risk)':<26} {best_risk_adj['max_drawdown_pct']:>6.2f}%  {'(47% less!)':<26} {'👑 Rank 9-12 (-{:.1f}%)'.format(dd_diff)}")

sharpe_diff = best_risk_adj['sharpe_ratio'] - best_return['sharpe_ratio']
print(f"{'Sharpe Ratio':<30} {best_return['sharpe_ratio']:>6.2f}  {'':>26} {best_risk_adj['sharpe_ratio']:>6.2f}  {'(+11% better)':<26} {'👑 Rank 9-12 (+{:.2f})'.format(sharpe_diff)}")

# Trade metrics
print(f"{'Win Rate':<30} {best_return['win_rate']:>6.2f}%  {'':>26} {best_risk_adj['win_rate']:>6.2f}%  {'(+2.1% better)':<26} {'👑 Rank 9-12'}")
print(f"{'Profit Factor':<30} {best_return['profit_factor']:>6.2f}  {'':>26} {best_risk_adj['profit_factor']:>6.2f}  {'(+8% better)':<26} {'👑 Rank 9-12'}")
print(f"{'Total Trades':<30} {int(best_return['total_trades']):>6}  {'':>26} {int(best_risk_adj['total_trades']):>6}  {'(18% fewer)':<26} {'↔️  More selective'}")

print("-"*120)

# Calculated risk-adjusted metrics
print("\n2️⃣  RISK-ADJUSTED PERFORMANCE METRICS")
print("-"*120)
print(f"{'Metric':<30} {'Rank 1-4':<20} {'Rank 9-12':<20} {'Winner'}")
print("-"*120)

# Return/DD ratio
ret_dd_1 = best_return['return_pct'] / best_return['max_drawdown_pct']
ret_dd_2 = best_risk_adj['return_pct'] / best_risk_adj['max_drawdown_pct']
print(f"{'Return/Drawdown Ratio':<30} {ret_dd_1:>6.2f}  {'':>13} {ret_dd_2:>6.2f}  {'':>13} {'👑 Rank 9-12' if ret_dd_2 > ret_dd_1 else '👑 Rank 1-4'}")

# Calmar ratio (Return / MaxDD)
calmar_1 = best_return['return_pct'] / best_return['max_drawdown_pct']
calmar_2 = best_risk_adj['return_pct'] / best_risk_adj['max_drawdown_pct']
print(f"{'Calmar Ratio':<30} {calmar_1:>6.2f}  {'':>13} {calmar_2:>6.2f}  {'':>13} {'👑 Rank 9-12 (+70%!)' if calmar_2 > calmar_1 else '👑 Rank 1-4'}")

# Return per trade
ret_trade_1 = best_return['return_pct'] / best_return['total_trades']
ret_trade_2 = best_risk_adj['return_pct'] / best_risk_adj['total_trades']
print(f"{'Return per Trade':<30} {ret_trade_1:>6.2f}%  {'':>13} {ret_trade_2:>6.2f}%  {'':>13} {'👑 Rank 9-12' if ret_trade_2 > ret_trade_1 else '👑 Rank 1-4'}")

print("-"*120)

# Configuration differences
print("\n3️⃣  CONFIGURATION DIFFERENCES")
print("-"*120)
print(f"{'Parameter':<25} {'Rank 1-4':<25} {'Rank 9-12':<25} {'Impact'}")
print("-"*120)
print(f"{'Supertrend':<25} {best_return['st_mult']:<25} {best_risk_adj['st_mult']:<25} {'Same'}")
sma_return = f"{int(best_return['sma_fast'])}/{int(best_return['sma_slow'])}"
sma_risk = f"{int(best_risk_adj['sma_fast'])}/{int(best_risk_adj['sma_slow'])}"
print(f"{'SMA':<25} {sma_return:<25} {sma_risk:<25} {'20/50 = slower trend'}")
print(f"{'TP/SL':<25} {best_return['tp_sl']:<25} {best_risk_adj['tp_sl']:<25} {'Same'}")
print(f"{'EOD Blackout':<25} {'No':<25} {'Yes':<25} {'Avoids risky EOD trades'}")
print("-"*120)

print("\n4️⃣  VERDICT & RECOMMENDATIONS")
print("="*120)
print("\n🎯 WHICH IS BETTER? It depends on your goals:\n")

print("   Choose RANK 1-4 (174.82% return, 18.79% DD) if:")
print("   ✓ Maximum profit is your priority")
print("   ✓ You can tolerate 18.79% drawdown")
print("   ✓ You want aggressive growth")
print("   ✓ You're comfortable with higher volatility\n")

print("   Choose RANK 9-12 (157.90% return, 9.94% DD) if:")
print("   ✓ Risk-adjusted returns matter more")
print("   ✓ You want to sleep better (47% less drawdown)")
print("   ✓ You prefer consistency over maximum returns")
print("   ✓ You're building compound growth strategy\n")

print("   📈 RECOMMENDATION:")
ret_dd_improve = ((ret_dd_2 - ret_dd_1) / ret_dd_1 * 100)
print(f"   → Rank 9-12 has {ret_dd_improve:.1f}% better return/drawdown ratio")
print(f"   → You give up 17% return but reduce drawdown by 47%")
print(f"   → Sharpe ratio is 11% better (0.52 vs 0.47)")
print(f"   → This is the CLASSIC risk/reward trade-off!\n")

print("   💰 PRACTICAL EXAMPLE:")
print(f"   With $10,000:")
print(f"   • Rank 1-4:  End with ${10000+best_return['total_pnl']:,.0f}, but face -${10000*best_return['max_drawdown_pct']/100:,.0f} worst drop")
print(f"   • Rank 9-12: End with ${10000+best_risk_adj['total_pnl']:,.0f}, but face -${10000*best_risk_adj['max_drawdown_pct']/100:,.0f} worst drop")
print(f"   • Difference: ${(best_return['total_pnl']-best_risk_adj['total_pnl']):,.0f} more profit vs ${10000*(best_return['max_drawdown_pct']-best_risk_adj['max_drawdown_pct'])/100:,.0f} less risk\n")

print("="*120)
print("\n✅ YES, Rank 9-12 is arguably BETTER from a risk management perspective!")
print("   The question is: Are you optimizing for max returns or risk-adjusted returns?\n")
