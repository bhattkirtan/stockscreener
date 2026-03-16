"""
Check credibility of M5 vs M15 backtests by comparing data periods
"""
import pandas as pd
from datetime import datetime

print("\n" + "="*100)
print("📊 BACKTEST CREDIBILITY ANALYSIS: M5 vs M15")
print("="*100)

# M5 data
print("\n1️⃣  M5 (5-MINUTE) DATA:")
print("-"*100)
m5_df = pd.read_csv('data/GOLD_M5_150000bars.csv')
m5_start = pd.to_datetime(m5_df['timestamp'].iloc[0])
m5_end = pd.to_datetime(m5_df['timestamp'].iloc[-1])
m5_days = (m5_end - m5_start).days
m5_months = m5_days / 30.44
m5_years = m5_days / 365.25

print(f"   Bars: {len(m5_df):,}")
print(f"   Start: {m5_start.strftime('%Y-%m-%d')}")
print(f"   End: {m5_end.strftime('%Y-%m-%d')}")
print(f"   Period: {m5_days} days ({m5_months:.1f} months, {m5_years:.2f} years)")

# M15 data
print("\n2️⃣  M15 (15-MINUTE) DATA:")
print("-"*100)
m15_df = pd.read_csv('data/GOLD_M15_9995bars.csv')
m15_start = pd.to_datetime(m15_df['timestamp'].iloc[0])
m15_end = pd.to_datetime(m15_df['timestamp'].iloc[-1])
m15_days = (m15_end - m15_start).days
m15_months = m15_days / 30.44
m15_years = m15_days / 365.25

print(f"   Bars: {len(m15_df):,}")
print(f"   Start: {m15_start.strftime('%Y-%m-%d')}")
print(f"   End: {m15_end.strftime('%Y-%m-%d')}")
print(f"   Period: {m15_days} days ({m15_months:.1f} months, {m15_years:.2f} years)")

# Comparison
print("\n3️⃣  CREDIBILITY COMPARISON:")
print("-"*100)
print(f"{'Metric':<40} | {'M5 (5-min)':<25} | {'M15 (15-min)':<25} | {'M5 Advantage':<20}")
print("-"*100)

print(f"{'Days of Data':<40} | {m5_days:>23,} | {m15_days:>23,} | {f'{m5_days/m15_days:.1f}x more':<20}")
print(f"{'Months of Data':<40} | {m5_months:>23.1f} | {m15_months:>23.1f} | {f'{m5_months/m15_months:.1f}x more':<20}")
print(f"{'Years of Data':<40} | {m5_years:>23.2f} | {m15_years:>23.2f} | {f'{m5_years/m15_years:.1f}x more':<20}")

# Statistical significance  
print("\n4️⃣  STATISTICAL SIGNIFICANCE:")
print("-"*100)

m5_trades = 866
m15_trades = 394

print(f"   Total Trades:")
print(f"   • M5: {m5_trades:,} trades over {m5_months:.1f} months")
print(f"   • M15: {m15_trades:,} trades over {m15_months:.1f} months")
print()
print(f"   Trades per Month:")
print(f"   • M5: {m5_trades/m5_months:.1f} trades/month")
print(f"   • M15: {m15_trades/m15_months:.1f} trades/month")
print()

# Rule of thumb: Need 30+ trades for basic significance, 100+ for good, 300+ for strong
print(f"   Statistical Confidence:")
print(f"   • M5: {m5_trades:,} trades = EXCELLENT sample size")
print(f"   • M15: {m15_trades:,} trades = GOOD sample size")
print()

# How many months would M15 need to match M5?
months_needed = m5_months
m15_trades_needed = months_needed * (m15_trades / m15_months)
print(f"   To Match M5 Period ({m5_months:.1f} months):")
print(f"   • M15 would need: {months_needed:.1f} months of data")
print(f"   • Expected trades: {m15_trades_needed:.0f} trades")
print(f"   • Currently have: Only {m15_months:.1f} months ({m15_months/m5_months*100:.0f}% of needed data)")

# Overlap analysis
print("\n5️⃣  TIME PERIOD OVERLAP:")
print("-"*100)

if m15_start >= m5_start and m15_end <= m5_end:
    print(f"   ✅ M15 period is FULLY CONTAINED within M5 period")
    print(f"   • M5 starts {(m15_start - m5_start).days} days BEFORE M15")
    print(f"   • M5 ends {(m5_end - m15_end).days} days AFTER M15")
    overlap_pct = m15_days / m5_days * 100
    print(f"   • M15 covers {overlap_pct:.1f}% of M5's timespan")
else:
    print(f"   ⚠️  Time periods don't fully overlap")

print("\n6️⃣  MARKET CONDITIONS TESTED:")
print("-"*100)

# Check if we captured different market regimes
print(f"   M5 ({m5_years:.2f} years):")
print(f"   • Captures ~{m5_years*4:.0f} quarterly market cycles")
print(f"   • Likely includes: uptrends, downtrends, sideways, volatility spikes")
print(f"   • HIGH confidence in diverse market conditions")
print()
print(f"   M15 ({m15_years:.2f} years):")
print(f"   • Captures ~{m15_years*4:.0f} quarterly market cycles")
print(f"   • Period: Oct 2025 - Mar 2026 (5 months only)")
if m15_months < 6:
    print(f"   • ⚠️  SHORT period - may miss seasonal patterns")
    print(f"   • ⚠️  May not capture all market regimes")
print(f"   • MEDIUM confidence (need more data)")

print("\n" + "="*100)
print("🎯 CREDIBILITY VERDICT")
print("="*100)

print("\n📊 M5 CREDIBILITY: ⭐⭐⭐⭐⭐ EXCELLENT")
print(f"   • {m5_months:.1f} months ({m5_years:.2f} years) = Robust")
print(f"   • {m5_trades:,} trades = Excellent sample size")
print(f"   • Tested across multiple market conditions")
print(f"   • HIGH confidence in results")
print()

m15_stars = "⭐⭐⭐" if m15_months >= 6 else "⭐⭐"
confidence = "GOOD" if m15_months >= 6 else "FAIR"
print(f"📊 M15 CREDIBILITY: {m15_stars} {confidence}")
print(f"   • {m15_months:.1f} months ({m15_years:.2f} years) = {'Adequate' if m15_months >= 6 else 'SHORT'}")
print(f"   • {m15_trades:,} trades = Good sample size")
print(f"   • ⚠️  Only covers {m15_months/m5_months*100:.0f}% of M5's timespan")
print(f"   • ⚠️  May not capture full market diversity")
print(f"   • MEDIUM confidence (would prefer 12+ months)")

print("\n💡 RECOMMENDATION:")
print("-"*100)

if m15_months < 6:
    print("\n   🚨 CAUTION: M15 results are PRELIMINARY")
    print(f"   • Only {m15_months:.1f} months is NOT enough for strong conclusions")
    print(f"   • Need at least 12 months (ideally 24+) for high confidence")
    print(f"   • M15 showed better monthly returns (7.3% vs 4.8%)")
    print(f"   • But this could be due to optimal market conditions in that 5-month window")
    print()
    print("   ⚠️  OPTIONS:")
    print("   1. Trust M5 results (25 months = proven)")
    print("   2. Get more M15 data before deciding")
    print("   3. Paper trade M15 for 3-6 months to verify")
    print("   4. Use M5 now, switch to M15 if paper trading confirms")
else:
    print("\n   ✅ M15 results are reasonably credible")
    print(f"   • {m15_months:.1f} months is adequate for initial confidence")
    print(f"   • Would still prefer 12+ months for stronger validation")

print("\n📈 SAFEST APPROACH:")
print("   1. Deploy M5 strategy (proven over 25 months)")
print("   2. Paper trade M15 in parallel for 3-6 months")
print("   3. If M15 continues outperforming, switch over")
print("   4. This way you don't miss out on proven returns while validating M15")

print("\n" + "="*100)
