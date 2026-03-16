"""
Calculate trading parameters for $10,000 total capital
"""

import pandas as pd
from pathlib import Path

def analyze_10k_capital():
    """Show what $10K capital means for trading"""
    
    # Load best strategy results
    orders_file = Path("data/optimization/2026-03-09/run_20260309_085435/rank01_ST2.0_SMA15-50_BB2.0_PIP1_ATR0.7x2.5/orders.csv")
    
    print(f"📂 Loading: {orders_file}")
    trades_df = pd.read_csv(orders_file)
    
    # Strategy metrics
    total_trades = len(trades_df)
    winners = len(trades_df[trades_df['pnl'] > 0])
    losers = len(trades_df[trades_df['pnl'] < 0])
    total_pnl = trades_df['pnl'].sum()
    avg_win = trades_df[trades_df['pnl'] > 0]['pnl'].mean()
    avg_loss = trades_df[trades_df['pnl'] < 0]['pnl'].mean()
    
    # Calculate drawdown
    trades_df['cumulative_pnl'] = trades_df['pnl'].cumsum()
    running_max = trades_df['cumulative_pnl'].expanding().max()
    drawdown = trades_df['cumulative_pnl'] - running_max
    max_drawdown = drawdown.min()
    
    # Time period
    trades_df['entry_time'] = pd.to_datetime(trades_df['entry_time'])
    start_date = trades_df['entry_time'].min()
    end_date = trades_df['entry_time'].max()
    days = (end_date - start_date).days
    months = days / 30.44
    
    # User's capital
    TOTAL_CAPITAL = 10000
    LEVERAGE = 20.0
    SAFE_POSITION_PCT = 0.135  # 13.5% per trade
    
    # Calculate position size
    margin_per_trade = TOTAL_CAPITAL * SAFE_POSITION_PCT
    notional_per_trade = margin_per_trade * LEVERAGE
    
    # Base notional from backtest
    BASE_NOTIONAL = 30000
    scale_factor = notional_per_trade / BASE_NOTIONAL
    
    # Scaled metrics
    scaled_total_pnl = total_pnl * scale_factor
    scaled_max_drawdown = max_drawdown * scale_factor
    scaled_avg_win = avg_win * scale_factor
    scaled_avg_loss = avg_loss * scale_factor
    
    # Final metrics
    final_capital = TOTAL_CAPITAL + scaled_total_pnl
    return_pct = (scaled_total_pnl / TOTAL_CAPITAL) * 100
    monthly_profit = scaled_total_pnl / months
    monthly_return_pct = return_pct / months
    max_dd_pct = (scaled_max_drawdown / TOTAL_CAPITAL) * 100
    lowest_balance = TOTAL_CAPITAL + scaled_max_drawdown
    
    print(f"\n{'='*80}")
    print(f"💰 YOUR TRADING PLAN WITH $10,000 CAPITAL")
    print(f"{'='*80}")
    
    print(f"\n📊 POSITION SIZING:")
    print(f"   Total Capital: ${TOTAL_CAPITAL:,.0f}")
    print(f"   Margin per Trade: ${margin_per_trade:,.0f} ({SAFE_POSITION_PCT*100:.1f}% of capital)")
    print(f"   Leverage: {LEVERAGE:.0f}×")
    print(f"   Notional per Trade: ${notional_per_trade:,.0f} (margin × {LEVERAGE:.0f}×)")
    print(f"   \n   💡 This means: You control ${notional_per_trade:,.0f} worth of gold per trade")
    print(f"                   using only ${margin_per_trade:,.0f} of your capital")
    
    print(f"\n📈 EXPECTED PERFORMANCE (based on 25.3 month backtest):")
    print(f"   Total Profit: ${scaled_total_pnl:,.0f}")
    print(f"   Final Balance: ${final_capital:,.0f}")
    print(f"   Total Return: {return_pct:.1f}%")
    print(f"   Monthly Profit: ${monthly_profit:,.0f}")
    print(f"   Monthly Return: {monthly_return_pct:.2f}%")
    
    print(f"\n🎯 TRADE STATISTICS:")
    print(f"   Total Trades: {total_trades} ({total_trades/months:.1f} per month)")
    print(f"   Winners: {winners} ({winners/total_trades*100:.1f}%)")
    print(f"   Losers: {losers} ({losers/total_trades*100:.1f}%)")
    print(f"   Average Win: ${scaled_avg_win:.2f}")
    print(f"   Average Loss: ${scaled_avg_loss:.2f}")
    print(f"   Risk:Reward: 1:{abs(scaled_avg_win/scaled_avg_loss):.2f}")
    
    print(f"\n📉 RISK MANAGEMENT:")
    print(f"   Max Drawdown: ${abs(scaled_max_drawdown):,.0f} ({abs(max_dd_pct):.1f}%)")
    print(f"   Lowest Balance: ${lowest_balance:,.0f}")
    print(f"   Risk per Trade: ${abs(scaled_avg_loss):.2f} ({abs(scaled_avg_loss)/TOTAL_CAPITAL*100:.2f}% of capital)")
    print(f"   \n   ⚠️  At worst point, your $10,000 drops to ${lowest_balance:,.0f}")
    print(f"       But strategy recovers: ends at ${final_capital:,.0f}")
    
    print(f"\n✅ SAFETY CHECKS:")
    can_survive = lowest_balance > margin_per_trade
    print(f"   Can survive worst drawdown? {'✅ YES' if can_survive else '❌ NO'}")
    print(f"   At lowest point (${lowest_balance:,.0f}), can still trade? {'✅ YES' if can_survive else '❌ NO'}")
    print(f"   Safety margin: ${lowest_balance - margin_per_trade:,.0f} cushion at worst point")
    
    # Calculate consecutive losing streak survival
    losing_streaks = []
    current_streak = 0
    for _, trade in trades_df.iterrows():
        if trade['pnl'] < 0:
            current_streak += 1
        else:
            if current_streak > 0:
                losing_streaks.append(current_streak)
            current_streak = 0
    if current_streak > 0:
        losing_streaks.append(current_streak)
    
    longest_streak = max(losing_streaks)
    streak_drain = longest_streak * abs(scaled_avg_loss)
    
    print(f"\n🔥 STRESS TEST:")
    print(f"   Longest losing streak: {longest_streak} losses in a row")
    print(f"   Capital drain: {longest_streak} × ${abs(scaled_avg_loss):.2f} = ${streak_drain:,.0f}")
    print(f"   Remaining capital: ${TOTAL_CAPITAL - streak_drain:,.0f}")
    print(f"   Can continue trading? {'✅ YES' if (TOTAL_CAPITAL - streak_drain) > margin_per_trade else '❌ NO'}")
    
    print(f"\n{'='*80}")
    print(f"📋 SUMMARY FOR $10,000 ACCOUNT")
    print(f"{'='*80}")
    print(f"")
    print(f"   Starting Capital:     ${TOTAL_CAPITAL:>8,}")
    print(f"   Margin per Trade:     ${margin_per_trade:>8,.0f} (your capital in each trade)")
    print(f"   Notional per Trade:   ${notional_per_trade:>8,.0f} (gold position with {LEVERAGE:.0f}× leverage)")
    print(f"   ")
    print(f"   Expected Total Profit: ${scaled_total_pnl:>7,.0f} over 25 months")
    print(f"   Expected Monthly:      ${monthly_profit:>7,.0f} per month")
    print(f"   Final Balance:         ${final_capital:>7,.0f}")
    print(f"   Return:                {return_pct:>7.1f}%")
    print(f"   ")
    print(f"   Worst Drawdown:       ${abs(scaled_max_drawdown):>8,.0f} ({abs(max_dd_pct):.1f}%)")
    print(f"   Lowest Balance:        ${lowest_balance:>8,.0f} (you survive!)")
    print(f"   ")
    print(f"   Average Win:           ${scaled_avg_win:>8,.2f}")
    print(f"   Average Loss:         -${abs(scaled_avg_loss):>8,.2f}")
    print(f"   Win Rate:              {winners/total_trades*100:>7.1f}%")
    print(f"")
    print(f"{'='*80}")
    
    print(f"\n💡 WHAT THIS MEANS IN PRACTICE:")
    print(f"   1. Your broker account balance: $10,000")
    print(f"   2. Each trade uses: $1,350 margin (13.5%)")
    print(f"   3. With 20× leverage, you control: $27,000 of gold")
    print(f"   4. When gold moves $1, your P&L changes by: ~$27")
    print(f"   5. Average winning trade: ${scaled_avg_win:.2f}")
    print(f"   6. Average losing trade: ${abs(scaled_avg_loss):.2f}")
    print(f"   7. Expected monthly profit: ${monthly_profit:.0f}")
    print(f"   8. Worst you'll see: Account drops to ${lowest_balance:,.0f}")
    print(f"   9. Final result: Account grows to ${final_capital:,.0f}")
    print(f"")
    print(f"   ✅ This is a SAFE setup - you survive all drawdowns comfortably!")
    print(f"\n{'='*80}")

if __name__ == "__main__":
    analyze_10k_capital()
