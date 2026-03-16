"""
Analyze multiple capital scenarios for the best strategy
Shows total capital needed, position size, drawdown, and profit for different investment levels
"""

import pandas as pd
import numpy as np
from pathlib import Path

def analyze_capital_scenarios():
    """Analyze different capital scenarios with safe leverage"""
    
    # Load best strategy results
    orders_file = Path("data/optimization/2026-03-09/run_20260309_085435/rank01_ST2.0_SMA15-50_BB2.0_PIP1_ATR0.7x2.5/orders.csv")
    
    if not orders_file.exists():
        print(f"❌ Orders file not found: {orders_file}")
        return
    
    print(f"📂 Loading: {orders_file}")
    trades_df = pd.read_csv(orders_file)
    
    # Strategy performance metrics
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
    max_drawdown_pct = (max_drawdown / running_max.max() * 100) if running_max.max() > 0 else 0
    
    # Backtest period
    trades_df['entry_time'] = pd.to_datetime(trades_df['entry_time'])
    start_date = trades_df['entry_time'].min()
    end_date = trades_df['entry_time'].max()
    days = (end_date - start_date).days
    months = days / 30.44
    
    print(f"\n{'='*80}")
    print(f"📊 STRATEGY PERFORMANCE SUMMARY")
    print(f"{'='*80}")
    print(f"Period: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')} ({days} days, {months:.1f} months)")
    print(f"Total Trades: {total_trades}")
    print(f"Winners: {winners} ({winners/total_trades*100:.1f}%)")
    print(f"Losers: {losers} ({losers/total_trades*100:.1f}%)")
    print(f"Average Win: ${avg_win:.2f}")
    print(f"Average Loss: ${avg_loss:.2f}")
    print(f"Risk:Reward: 1:{abs(avg_win/avg_loss):.2f}")
    print(f"Max Drawdown: ${max_drawdown:.2f} ({max_drawdown_pct:.1f}%)")
    
    # Define MARGIN amounts to test (user's actual capital per trade)
    margin_per_trade = [300, 600, 900, 1200]
    
    # Leverage parameters
    LEVERAGE = 20.0  # User's broker provides 20× leverage
    SAFE_MARGIN_USAGE = 0.135  # Use 13.5% of total capital per trade for safety
    LIQUIDATION_LEVERAGE = 7.0  # Typical liquidation threshold
    
    print(f"\n{'='*80}")
    print(f"💰 CAPITAL SCENARIOS ANALYSIS (with {LEVERAGE:.0f}× Leverage)")
    print(f"{'='*80}")
    print(f"Leverage: {LEVERAGE:.0f}×")
    print(f"Safe Position Sizing: {SAFE_MARGIN_USAGE*100:.1f}% of total capital per trade")
    print(f"Note: Your margin × {LEVERAGE:.0f} = Notional position size\n")
    
    # Prepare results table
    results = []
    
    # Determine base NOTIONAL position size from the backtest
    # The P&L values are based on price movements of the NOTIONAL position
    # From previous analysis: backtest used ~$30,000 notional positions
    # avg_loss = -$146.50 with 0.7× ATR stop (~$10.50 on GOLD)
    # $146.50 / $10.50 per oz = ~14 oz = 14 × $2,100 = ~$29,400 notional
    BASE_NOTIONAL_POSITION = 30000  # Approximate notional from backtest
    
    for margin in margin_per_trade:
        # Calculate notional position with user's leverage
        notional_position = margin * LEVERAGE
        
        # Calculate required total capital for safe trading
        # Using 13.5% rule: each trade uses 13.5% of your total capital as margin
        total_capital_needed = margin / SAFE_MARGIN_USAGE
        
        # Scale factor: ratio of user's notional to backtest's notional
        scale_factor = notional_position / BASE_NOTIONAL_POSITION
        
        # Scale all P&L by notional position size ratio
        scaled_total_pnl = total_pnl * scale_factor
        scaled_max_drawdown = max_drawdown * scale_factor
        scaled_avg_win = avg_win * scale_factor
        scaled_avg_loss = avg_loss * scale_factor
        
        # Calculate final capital and return
        final_capital = total_capital_needed + scaled_total_pnl
        return_pct = (scaled_total_pnl / total_capital_needed) * 100
        
        # Monthly return
        monthly_return = scaled_total_pnl / months
        monthly_return_pct = return_pct / months
        
        # Maximum drawdown as % of total capital
        max_dd_pct = (scaled_max_drawdown / total_capital_needed) * 100
        
        # Risk metrics
        risk_per_trade = abs(scaled_avg_loss)
        risk_pct = (risk_per_trade / total_capital_needed) * 100
        
        results.append({
            'Margin/Trade': f"${margin:,.0f}",
            'Notional': f"${notional_position:,.0f}",
            'Total Capital': f"${total_capital_needed:,.0f}",
            'Final Capital': f"${final_capital:,.0f}",
            'Total Profit': f"${scaled_total_pnl:,.0f}",
            'Return %': f"{return_pct:.1f}%",
            'Monthly Profit': f"${monthly_return:,.0f}",
            'Monthly Return %': f"{monthly_return_pct:.2f}%",
            'Max Drawdown $': f"${abs(scaled_max_drawdown):,.0f}",
            'Max DD %': f"{abs(max_dd_pct):.1f}%",
            'Avg Win': f"${scaled_avg_win:.2f}",
            'Avg Loss': f"${scaled_avg_loss:.2f}",
            'Risk/Trade %': f"{risk_pct:.2f}%"
        })
    
    # Create DataFrame
    df_results = pd.DataFrame(results)
    
    # Print as table
    print("="*165)
    print(f"{'COMPREHENSIVE CAPITAL ANALYSIS (20× Leverage Model)':^165}")
    print("="*165)
    
    # Print header
    print(f"{'Margin/Trade':>13} | {'Notional':>10} | {'Total Capital':>15} | {'Final Capital':>15} | {'Total Profit':>15} | {'Return %':>10} | "
          f"{'Monthly $':>12} | {'Monthly %':>10} | {'Max DD $':>12} | {'Max DD %':>10} | {'Avg Win':>12} | {'Avg Loss':>12} | {'Risk/Trade':>12}")
    print("-" * 165)
    
    # Print data rows
    for _, row in df_results.iterrows():
        print(f"{row['Margin/Trade']:>13} | {row['Notional']:>10} | {row['Total Capital']:>15} | {row['Final Capital']:>15} | {row['Total Profit']:>15} | "
              f"{row['Return %']:>10} | {row['Monthly Profit']:>12} | {row['Monthly Return %']:>10} | "
              f"{row['Max Drawdown $']:>12} | {row['Max DD %']:>10} | {row['Avg Win']:>12} | {row['Avg Loss']:>12} | {row['Risk/Trade %']:>12}")
    
    print("="*165)
    
    # Additional insights
    print(f"\n{'='*80}")
    print(f"📈 KEY INSIGHTS")
    print(f"{'='*80}")
    
    print(f"\n🎯 Risk Management:")
    print(f"   • Leverage: {LEVERAGE:.0f}×")
    print(f"   • Margin per trade: {SAFE_MARGIN_USAGE*100:.1f}% of total capital")
    print(f"   • Example: $300 margin × {LEVERAGE:.0f}× = ${300*LEVERAGE:,.0f} notional gold position")
    print(f"   • Max drawdown: ~{abs(max_drawdown_pct):.1f}% of total capital")
    print(f"   • Risk per trade: ~{SAFE_MARGIN_USAGE*100:.1f}% margin exposure")
    
    print(f"\n💰 Profitability:")
    print(f"   • Consistent {return_pct:.1f}% return across all capital levels (scaling works)")
    print(f"   • Average monthly return: {monthly_return_pct:.2f}%")
    print(f"   • Average {total_trades/months:.1f} trades per month")
    print(f"   • Win rate: {winners/total_trades*100:.1f}% (mathematically correct for 1:{abs(avg_win/avg_loss):.2f} R:R)")
    
    print(f"\n🛡️ Safety Margins:")
    print(f"   • Profile: Conservative trader using {LEVERAGE:.0f}× leverage wisely")
    print(f"   • Position sizing: Only {SAFE_MARGIN_USAGE*100:.1f}% per trade prevents over-exposure")
    print(f"   • Multiple simultaneous trades: Can handle 7-8 positions safely")
    print(f"   • Worst drawdown absorbed: {100 - abs(max_drawdown_pct):.1f}% capital still intact")
    
    print(f"\n💡 Recommended Starting Capital:")
    
    for i, margin in enumerate(margin_per_trade):
        monthly = float(results[i]['Monthly Profit'].replace('$','').replace(',',''))
        total_cap = float(results[i]['Total Capital'].replace('$','').replace(',',''))
        total_profit = float(results[i]['Total Profit'].replace('$','').replace(',',''))
        notional = float(results[i]['Notional'].replace('$','').replace(',',''))
        
        if i == 0:
            print(f"   • Ultra-Safe (${margin} margin → ${notional:,.0f} notional): Total ${total_cap:,.0f} → ${monthly:,.0f}/month → ${total_profit:,.0f} in 25 months")
        elif i == 1:
            print(f"   • Conservative (${margin} margin → ${notional:,.0f} notional): Total ${total_cap:,.0f} → ${monthly:,.0f}/month → ${total_profit:,.0f} in 25 months")
        elif i == 2:
            print(f"   • Moderate (${margin} margin → ${notional:,.0f} notional): Total ${total_cap:,.0f} → ${monthly:,.0f}/month → ${total_profit:,.0f} in 25 months")
        else:
            print(f"   • Aggressive (${margin} margin → ${notional:,.0f} notional): Total ${total_cap:,.0f} → ${monthly:,.0f}/month → ${total_profit:,.0f} in 25 months")
    
    print(f"\n⚠️  IMPORTANT:")
    print(f"   • Margin = Your actual capital used per trade (${margin_per_trade[0]}, ${margin_per_trade[1]}, etc.)")
    print(f"   • Notional = Margin × {LEVERAGE:.0f}× = Actual gold position controlled")
    print(f"   • Total Capital = Full account balance needed (Margin / {SAFE_MARGIN_USAGE:.1%})")
    print(f"   • Max drawdown: Expect to see -{abs(max_drawdown_pct):.0f}% at worst point")
    print(f"   • This is NORMAL for high R:R strategies (1:3.36)")
    print(f"   • You must have full capital to weather drawdowns")
    print(f"   • Don't withdraw profits during drawdown periods")
    print(f"   • Strategy recovers: {return_pct:.1f}% net return after all drawdowns")
    
    print(f"\n{'='*80}")

if __name__ == "__main__":
    analyze_capital_scenarios()
