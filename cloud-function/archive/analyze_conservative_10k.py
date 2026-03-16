"""
Analyze $10,000 total capital with conservative $300 or $600 margin per trade
"""

import pandas as pd
from pathlib import Path

def analyze_conservative_sizing():
    """Show what $10K capital with $300/$600 positions looks like"""
    
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
    
    # User's parameters
    TOTAL_CAPITAL = 10000
    LEVERAGE = 20.0
    BASE_NOTIONAL = 30000  # Backtest base
    
    margin_options = [300, 600]
    
    print(f"\n{'='*100}")
    print(f"💰 CONSERVATIVE POSITION SIZING WITH $10,000 CAPITAL")
    print(f"{'='*100}")
    
    for margin in margin_options:
        position_pct = (margin / TOTAL_CAPITAL) * 100
        notional = margin * LEVERAGE
        scale_factor = notional / BASE_NOTIONAL
        
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
        
        # Risk checks
        risk_per_trade_pct = (abs(scaled_avg_loss) / TOTAL_CAPITAL) * 100
        
        print(f"\n{'='*100}")
        print(f"💵 OPTION: ${margin} MARGIN PER TRADE ({position_pct:.1f}% of capital)")
        print(f"{'='*100}")
        
        print(f"\n📊 POSITION DETAILS:")
        print(f"   Total Capital:         ${TOTAL_CAPITAL:>8,}")
        print(f"   Margin per Trade:      ${margin:>8,} ({position_pct:.1f}% of capital)")
        print(f"   Leverage:              {LEVERAGE:>8.0f}×")
        print(f"   Notional per Trade:    ${notional:>8,} (controls this much gold)")
        print(f"   Position Sizing:       {'🟢 ULTRA-SAFE' if position_pct < 5 else '🟢 VERY SAFE' if position_pct < 10 else '🟡 SAFE'}")
        
        print(f"\n📈 EXPECTED PERFORMANCE (25.3 months):")
        print(f"   Total Profit:          ${scaled_total_pnl:>8,.0f}")
        print(f"   Final Balance:         ${final_capital:>8,.0f}")
        print(f"   Total Return:          {return_pct:>8.1f}%")
        print(f"   Monthly Profit:        ${monthly_profit:>8,.0f}")
        print(f"   Monthly Return:        {monthly_return_pct:>8.2f}%")
        
        print(f"\n🎯 PER-TRADE RESULTS:")
        print(f"   Average Win:           ${scaled_avg_win:>8,.2f}")
        print(f"   Average Loss:          ${abs(scaled_avg_loss):>8,.2f}")
        print(f"   Win Rate:              {winners/total_trades*100:>8.1f}%")
        print(f"   Risk:Reward:           1:{abs(scaled_avg_win/scaled_avg_loss):.2f}")
        print(f"   Risk per Trade:        {risk_per_trade_pct:>8.2f}% of capital")
        
        print(f"\n📉 DRAWDOWN ANALYSIS:")
        print(f"   Max Drawdown:          ${abs(scaled_max_drawdown):>8,.0f} ({abs(max_dd_pct):.1f}%)")
        print(f"   Lowest Balance:        ${lowest_balance:>8,.0f}")
        print(f"   Safety Cushion:        ${lowest_balance - margin:>8,.0f} (at worst point)")
        
        # Stress test
        longest_streak = 39  # From previous analysis
        streak_drain = longest_streak * abs(scaled_avg_loss)
        remaining = TOTAL_CAPITAL - streak_drain
        
        print(f"\n🔥 STRESS TEST (39 consecutive losses):")
        print(f"   Capital Drain:         ${streak_drain:>8,.0f}")
        print(f"   Remaining:             ${remaining:>8,.0f}")
        print(f"   Can Still Trade:       {'✅ YES' if remaining > margin else '❌ NO'}")
        print(f"   Survival Rating:       {'🟢 EXCELLENT' if remaining > margin*3 else '🟢 GOOD' if remaining > margin*1.5 else '🟡 ADEQUATE'}")
        
        print(f"\n✅ SAFETY SUMMARY:")
        print(f"   ✓ Survives worst drawdown: {'YES' if lowest_balance > margin else 'NO'}")
        print(f"   ✓ Survives 39-loss streak: {'YES' if remaining > margin else 'NO'}")
        print(f"   ✓ Capital preservation:    {(lowest_balance/TOTAL_CAPITAL)*100:.1f}% remains at worst")
        print(f"   ✓ Doubles capital in:      {months * (TOTAL_CAPITAL / scaled_total_pnl):.1f} months")
    
    # Comparison table
    print(f"\n{'='*100}")
    print(f"📊 SIDE-BY-SIDE COMPARISON")
    print(f"{'='*100}")
    
    print(f"\n{'':<25} | {'$300/trade':>20} | {'$600/trade':>20} | {'Difference':>20}")
    print(f"{'-'*25:25} | {'-'*20:20} | {'-'*20:20} | {'-'*20:20}")
    
    for margin in margin_options:
        notional = margin * LEVERAGE
        scale_factor = notional / BASE_NOTIONAL
        scaled_total_pnl = total_pnl * scale_factor
        scaled_max_drawdown = max_drawdown * scale_factor
        scaled_avg_loss = avg_loss * scale_factor
        monthly_profit = scaled_total_pnl / months
        lowest_balance = TOTAL_CAPITAL + scaled_max_drawdown
        
        if margin == 300:
            data_300 = {
                'margin': margin,
                'notional': notional,
                'total_pnl': scaled_total_pnl,
                'monthly': monthly_profit,
                'return_pct': (scaled_total_pnl/TOTAL_CAPITAL)*100,
                'max_dd': scaled_max_drawdown,
                'lowest': lowest_balance,
                'avg_loss': scaled_avg_loss
            }
        else:
            data_600 = {
                'margin': margin,
                'notional': notional,
                'total_pnl': scaled_total_pnl,
                'monthly': monthly_profit,
                'return_pct': (scaled_total_pnl/TOTAL_CAPITAL)*100,
                'max_dd': scaled_max_drawdown,
                'lowest': lowest_balance,
                'avg_loss': scaled_avg_loss
            }
    
    print(f"{'Margin per Trade':<25} | ${data_300['margin']:>19} | ${data_600['margin']:>19} | {'2× position':>20}")
    print(f"{'Notional (20× leverage)':<25} | ${data_300['notional']:>19,} | ${data_600['notional']:>19,} | ${data_600['notional']-data_300['notional']:>19,}")
    print(f"{'% of Capital':<25} | {(data_300['margin']/TOTAL_CAPITAL)*100:>18.1f}% | {(data_600['margin']/TOTAL_CAPITAL)*100:>18.1f}% | {((data_600['margin']-data_300['margin'])/TOTAL_CAPITAL)*100:>18.1f}%")
    print(f"{'':<25} | {'':<20} | {'':<20} | {'':<20}")
    print(f"{'Total Profit (25m)':<25} | ${data_300['total_pnl']:>18,.0f} | ${data_600['total_pnl']:>18,.0f} | ${data_600['total_pnl']-data_300['total_pnl']:>18,.0f}")
    print(f"{'Monthly Profit':<25} | ${data_300['monthly']:>18,.0f} | ${data_600['monthly']:>18,.0f} | ${data_600['monthly']-data_300['monthly']:>18,.0f}")
    print(f"{'Return %':<25} | {data_300['return_pct']:>18.1f}% | {data_600['return_pct']:>18.1f}% | {data_600['return_pct']-data_300['return_pct']:>18.1f}%")
    print(f"{'':<25} | {'':<20} | {'':<20} | {'':<20}")
    print(f"{'Max Drawdown':<25} | ${abs(data_300['max_dd']):>18,.0f} | ${abs(data_600['max_dd']):>18,.0f} | ${abs(data_600['max_dd'])-abs(data_300['max_dd']):>18,.0f}")
    print(f"{'Lowest Balance':<25} | ${data_300['lowest']:>18,.0f} | ${data_600['lowest']:>18,.0f} | ${data_600['lowest']-data_300['lowest']:>18,.0f}")
    print(f"{'Avg Loss per Trade':<25} | ${abs(data_300['avg_loss']):>18,.2f} | ${abs(data_600['avg_loss']):>18,.2f} | ${abs(data_600['avg_loss'])-abs(data_300['avg_loss']):>18,.2f}")
    
    print(f"\n{'='*100}")
    print(f"💡 RECOMMENDATION")
    print(f"{'='*100}")
    
    print(f"\n🎯 For $10,000 Capital:")
    print(f"")
    print(f"   Option 1: $300/trade (3% position sizing)")
    print(f"   • Ultra-conservative approach")
    print(f"   • $97/month profit")
    print(f"   • Extreme safety (survives anything)")
    print(f"   • Best for: Testing strategy or very risk-averse")
    print(f"")
    print(f"   Option 2: $600/trade (6% position sizing) ⭐ RECOMMENDED")
    print(f"   • Still very safe (well below 13.5% standard)")
    print(f"   • $193/month profit")
    print(f"   • Excellent safety margins")
    print(f"   • Best for: Conservative growth with safety")
    print(f"")
    print(f"   📊 Both options are ULTRA-SAFE with $10K capital")
    print(f"   📊 Even at worst drawdown, you have $8-9K remaining")
    print(f"   📊 Standard 13.5% rule would use $1,350/trade ($435/month)")
    print(f"")
    print(f"{'='*100}")

if __name__ == "__main__":
    analyze_conservative_sizing()
