#!/usr/bin/env python3
"""
Deep Analysis of Losing Trades
- 1H timeframe trend context
- Market sentiment/momentum
- Partial TP analysis
- Outlier detection in winning trades
"""
import pandas as pd
import numpy as np
from pathlib import Path
import sys

def calculate_1h_trend(df_m5, timestamp):
    """Calculate 1H trend at given timestamp"""
    # Get 1H data up to this point (last 12 bars = 1H on M5)
    idx = df_m5.index.get_indexer([timestamp], method='nearest')[0]
    
    if idx < 12:
        return None, None, None
    
    # Get last 1H of data (12 M5 bars)
    lookback_1h = df_m5.iloc[idx-12:idx]
    
    if len(lookback_1h) < 12:
        return None, None, None
    
    # Calculate 1H trend indicators
    h1_open = lookback_1h['open'].iloc[0]
    h1_close = lookback_1h['close'].iloc[-1]
    h1_high = lookback_1h['high'].max()
    h1_low = lookback_1h['low'].min()
    
    # Trend direction
    h1_trend = 'UP' if h1_close > h1_open else 'DOWN'
    h1_change_pct = ((h1_close - h1_open) / h1_open) * 100
    
    # Momentum (price vs 1H MA)
    h1_ma = lookback_1h['close'].mean()
    momentum = 'BULLISH' if h1_close > h1_ma else 'BEARISH'
    
    return h1_trend, h1_change_pct, momentum

def calculate_sentiment_indicators(df_m5, timestamp):
    """Calculate market sentiment indicators at timestamp"""
    idx = df_m5.index.get_indexer([timestamp], method='nearest')[0]
    
    if idx < 50:
        return None, None, None
    
    # Get recent data
    recent = df_m5.iloc[:idx+1]
    
    # RSI (14 period on M5)
    if len(recent) >= 14:
        delta = recent['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        current_rsi = rsi.iloc[-1]
    else:
        current_rsi = None
    
    # ATR volatility (14 period)
    if len(recent) >= 14:
        high_low = recent['high'] - recent['low']
        high_close = (recent['high'] - recent['close'].shift()).abs()
        low_close = (recent['low'] - recent['close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(window=14).mean().iloc[-1]
    else:
        atr = None
    
    # Price vs 50-period SMA
    if len(recent) >= 50:
        sma_50 = recent['close'].rolling(window=50).mean().iloc[-1]
        price_vs_sma = 'ABOVE' if recent['close'].iloc[-1] > sma_50 else 'BELOW'
    else:
        price_vs_sma = None
    
    return current_rsi, atr, price_vs_sma

def analyze_partial_tp_potential(df_m5, trade):
    """Analyze if partial TP levels would have been hit before stop loss"""
    entry_time = pd.to_datetime(trade['entry_time'])
    exit_time = pd.to_datetime(trade['exit_time'])
    entry_price = trade['entry_price']
    sl_price = trade['stop_loss']
    tp_price = trade['take_profit']
    side = trade['side']
    
    # Get trade period data
    trade_mask = (df_m5.index >= entry_time) & (df_m5.index <= exit_time)
    trade_bars = df_m5[trade_mask]
    
    if len(trade_bars) < 2:
        return None
    
    # Calculate partial TP levels (25%, 50%, 75% of full TP)
    full_tp_distance = abs(tp_price - entry_price)
    tp1_distance = full_tp_distance * 0.25
    tp2_distance = full_tp_distance * 0.50
    tp3_distance = full_tp_distance * 0.75
    
    if side == 'BUY':
        tp1_price = entry_price + tp1_distance
        tp2_price = entry_price + tp2_distance
        tp3_price = entry_price + tp3_distance
        
        # Check if any TP was hit
        tp1_hit = (trade_bars['high'] >= tp1_price).any()
        tp2_hit = (trade_bars['high'] >= tp2_price).any()
        tp3_hit = (trade_bars['high'] >= tp3_price).any()
    else:  # SELL
        tp1_price = entry_price - tp1_distance
        tp2_price = entry_price - tp2_distance
        tp3_price = entry_price - tp3_distance
        
        # Check if any TP was hit
        tp1_hit = (trade_bars['low'] <= tp1_price).any()
        tp2_hit = (trade_bars['low'] <= tp2_price).any()
        tp3_hit = (trade_bars['low'] <= tp3_price).any()
    
    return {
        'tp1_hit': tp1_hit,
        'tp2_hit': tp2_hit,
        'tp3_hit': tp3_hit,
        'tp1_price': tp1_price,
        'tp2_price': tp2_price,
        'tp3_price': tp3_price
    }

# Load orders
if len(sys.argv) > 1:
    orders_file = Path(sys.argv[1])
else:
    orders_file = Path('data/optimization/2026-03-09/run_20260309_085435/rank01_ST2.0_SMA15-50_BB2.0_PIP1_ATR0.7x2.5/orders.csv')

print(f"📂 Loading: {orders_file}")
df_orders = pd.read_csv(orders_file)
df_orders['entry_time'] = pd.to_datetime(df_orders['entry_time'])
df_orders['exit_time'] = pd.to_datetime(df_orders['exit_time'])

# Load M5 data
data_file = Path('data/GOLD_M5_150000bars.csv')
print(f"📂 Loading M5 data: {data_file}")
df_m5 = pd.read_csv(data_file)
df_m5['timestamp'] = pd.to_datetime(df_m5['timestamp'])
df_m5.set_index('timestamp', inplace=True)
print(f"✅ Loaded {len(df_m5):,} M5 bars")

# Separate winners and losers
winners = df_orders[df_orders['pnl'] > 0]
losers = df_orders[df_orders['pnl'] < 0]

print(f"\n{'='*80}")
print(f"📊 TRADING SUMMARY")
print(f"{'='*80}")
print(f"Total Trades: {len(df_orders)}")
print(f"Winners: {len(winners)} ({len(winners)/len(df_orders)*100:.1f}%)")
print(f"Losers: {len(losers)} ({len(losers)/len(df_orders)*100:.1f}%)")
print(f"Total P&L: ${df_orders['pnl'].sum():,.2f}")

# Analyze winning trades for outliers
print(f"\n{'='*80}")
print(f"🎯 WINNING TRADES ANALYSIS (Outlier Detection)")
print(f"{'='*80}")

if len(winners) > 0:
    win_pnl = winners['pnl'].values
    win_mean = win_pnl.mean()
    win_median = np.median(win_pnl)
    win_std = win_pnl.std()
    win_q1 = np.percentile(win_pnl, 25)
    win_q3 = np.percentile(win_pnl, 75)
    win_iqr = win_q3 - win_q1
    
    # Outliers: values > Q3 + 1.5*IQR
    outlier_threshold = win_q3 + (1.5 * win_iqr)
    outliers = winners[winners['pnl'] > outlier_threshold]
    
    print(f"\n📊 Winner P&L Distribution:")
    print(f"   Mean: ${win_mean:.2f}")
    print(f"   Median: ${win_median:.2f}")
    print(f"   Std Dev: ${win_std:.2f}")
    print(f"   Q1 (25%): ${win_q1:.2f}")
    print(f"   Q3 (75%): ${win_q3:.2f}")
    print(f"   IQR: ${win_iqr:.2f}")
    
    print(f"\n🔍 Outlier Detection (> ${outlier_threshold:.2f}):")
    print(f"   Outliers: {len(outliers)} trades ({len(outliers)/len(winners)*100:.1f}%)")
    
    if len(outliers) > 0:
        print(f"\n   Top 5 Outlier Wins:")
        for idx, row in outliers.nlargest(5, 'pnl').iterrows():
            print(f"   {row['entry_time']}: ${row['pnl']:.2f} ({row['side']}, {(row['exit_time']-row['entry_time']).total_seconds()/3600:.1f}h hold)")
    
    # Remove outliers and recalculate
    normal_winners = winners[winners['pnl'] <= outlier_threshold]
    if len(normal_winners) > 0:
        print(f"\n📊 Without Outliers ({len(normal_winners)} trades):")
        print(f"   Mean: ${normal_winners['pnl'].mean():.2f}")
        print(f"   Median: ${normal_winners['pnl'].median():.2f}")
        print(f"   Impact: Outliers add ${outliers['pnl'].sum():.2f} (${outliers['pnl'].sum()/len(winners):.2f} per trade)")

# Analyze winning trades with 1H context and partial TP
print(f"\n{'='*80}")
print(f"🏆 WINNING TRADES: 1H TREND & PARTIAL TP ANALYSIS")
print(f"{'='*80}")

print(f"\nAnalyzing {len(winners)} winning trades...")

# Counter-trend analysis for winners
winner_counter_trend_count = 0
winner_with_trend_count = 0
winner_tp1_count = 0
winner_tp2_count = 0
winner_tp3_count = 0

for idx, trade in winners.iterrows():
    h1_trend, h1_change, momentum = calculate_1h_trend(df_m5, trade['entry_time'])
    
    # Check if counter-trend
    if h1_trend and trade['side']:
        if trade['side'] == 'BUY' and h1_trend == 'DOWN':
            winner_counter_trend_count += 1
        elif trade['side'] == 'SELL' and h1_trend == 'UP':
            winner_counter_trend_count += 1
        else:
            winner_with_trend_count += 1
    
    # Check partial TP progression
    entry_time = trade['entry_time']
    exit_time = trade['exit_time']
    
    # Get bars between entry and exit
    mask = (df_m5.index > entry_time) & (df_m5.index <= exit_time)
    trade_bars = df_m5[mask].copy()
    
    if len(trade_bars) > 0:
        entry_price = trade['entry_price']
        full_tp = trade['exit_price']
        
        # Calculate partial TP levels
        if trade['side'] == 'BUY':
            distance = full_tp - entry_price
            tp1 = entry_price + (distance * 0.25)
            tp2 = entry_price + (distance * 0.50)
            tp3 = entry_price + (distance * 0.75)
            
            if trade_bars['high'].max() >= tp1:
                winner_tp1_count += 1
            if trade_bars['high'].max() >= tp2:
                winner_tp2_count += 1
            if trade_bars['high'].max() >= tp3:
                winner_tp3_count += 1
        else:  # SELL
            distance = entry_price - full_tp
            tp1 = entry_price - (distance * 0.25)
            tp2 = entry_price - (distance * 0.50)
            tp3 = entry_price - (distance * 0.75)
            
            if trade_bars['low'].min() <= tp1:
                winner_tp1_count += 1
            if trade_bars['low'].min() <= tp2:
                winner_tp2_count += 1
            if trade_bars['low'].min() <= tp3:
                winner_tp3_count += 1

print(f"\n🔄 COUNTER-TREND ANALYSIS (WINNERS):")
print(f"   Counter-Trend Trades: {winner_counter_trend_count} ({winner_counter_trend_count/len(winners)*100:.1f}%)")
print(f"   With-Trend Trades: {winner_with_trend_count} ({winner_with_trend_count/len(winners)*100:.1f}%)")

if winner_with_trend_count > 0 and winner_counter_trend_count > 0:
    ratio = winner_with_trend_count / winner_counter_trend_count
    print(f"\n   💡 With-trend winners are {ratio:.2f}× more common than counter-trend")

print(f"\n🎯 PARTIAL TP PROGRESSION (WINNERS):")
print(f"   Hit TP1 (25%): {winner_tp1_count} ({winner_tp1_count/len(winners)*100:.1f}%)")
print(f"   Hit TP2 (50%): {winner_tp2_count} ({winner_tp2_count/len(winners)*100:.1f}%)")
print(f"   Hit TP3 (75%): {winner_tp3_count} ({winner_tp3_count/len(winners)*100:.1f}%)")
print(f"   Hit Full TP (100%): {len(winners)} (100.0%)")

print(f"\n   💡 Partial TP Impact on Winners:")
if winner_tp1_count < len(winners):
    print(f"      {len(winners) - winner_tp1_count} trades ({(len(winners)-winner_tp1_count)/len(winners)*100:.1f}%) went STRAIGHT to TP without hitting TP1")
    print(f"      These 'quick wins' would give up 75% profit if using partial TP at TP1")

# Analyze losing trades with 1H context
print(f"\n{'='*80}")
print(f"📉 LOSING TRADES: 1H TREND & SENTIMENT ANALYSIS")
print(f"{'='*80}")

print(f"\nAnalyzing {len(losers)} losing trades...")

# Add context to each losing trade
losers_with_context = []
partial_tp_results = {'tp1_hit': 0, 'tp2_hit': 0, 'tp3_hit': 0, 'none_hit': 0}

for idx, trade in losers.iterrows():
    h1_trend, h1_change, momentum = calculate_1h_trend(df_m5, trade['entry_time'])
    rsi, atr, price_vs_sma = calculate_sentiment_indicators(df_m5, trade['entry_time'])
    partial_tp = analyze_partial_tp_potential(df_m5, trade)
    
    # Check if trading against 1H trend
    counter_trend = None
    if h1_trend and trade['side']:
        if trade['side'] == 'BUY' and h1_trend == 'DOWN':
            counter_trend = True
        elif trade['side'] == 'SELL' and h1_trend == 'UP':
            counter_trend = True
        else:
            counter_trend = False
    
    losers_with_context.append({
        'entry_time': trade['entry_time'],
        'side': trade['side'],
        'pnl': trade['pnl'],
        'h1_trend': h1_trend,
        'h1_change_pct': h1_change,
        'momentum': momentum,
        'counter_trend': counter_trend,
        'rsi': rsi,
        'atr': atr,
        'price_vs_sma': price_vs_sma,
        'partial_tp': partial_tp
    })
    
    # Count partial TP hits
    if partial_tp:
        if partial_tp['tp1_hit']:
            partial_tp_results['tp1_hit'] += 1
        if partial_tp['tp2_hit']:
            partial_tp_results['tp2_hit'] += 1
        if partial_tp['tp3_hit']:
            partial_tp_results['tp3_hit'] += 1
        if not any([partial_tp['tp1_hit'], partial_tp['tp2_hit'], partial_tp['tp3_hit']]):
            partial_tp_results['none_hit'] += 1

df_losers_context = pd.DataFrame(losers_with_context)

# Analyze counter-trend trading
print(f"\n🔄 COUNTER-TREND ANALYSIS:")
counter_trend_losses = df_losers_context[df_losers_context['counter_trend'] == True]
with_trend_losses = df_losers_context[df_losers_context['counter_trend'] == False]

print(f"   Counter-Trend Trades: {len(counter_trend_losses)} ({len(counter_trend_losses)/len(df_losers_context)*100:.1f}%)")
print(f"   With-Trend Trades: {len(with_trend_losses)} ({len(with_trend_losses)/len(df_losers_context)*100:.1f}%)")

if len(counter_trend_losses) > 0:
    print(f"\n   💡 Counter-trend trades are {len(counter_trend_losses)/len(with_trend_losses):.2f}× more common")
    print(f"      Filtering counter-trend would eliminate {len(counter_trend_losses)} losses")

# Analyze by 1H trend
print(f"\n📈 LOSSES BY 1H TREND:")
trend_counts = df_losers_context['h1_trend'].value_counts()
for trend, count in trend_counts.items():
    pct = (count / len(df_losers_context)) * 100
    print(f"   {trend}: {count} trades ({pct:.1f}%)")

# Analyze RSI context
print(f"\n📊 RSI CONTEXT (at entry):")
df_with_rsi = df_losers_context[df_losers_context['rsi'].notna()]
if len(df_with_rsi) > 0:
    avg_rsi = df_with_rsi['rsi'].mean()
    overbought = len(df_with_rsi[df_with_rsi['rsi'] > 70])
    oversold = len(df_with_rsi[df_with_rsi['rsi'] < 30])
    neutral = len(df_with_rsi[(df_with_rsi['rsi'] >= 30) & (df_with_rsi['rsi'] <= 70)])
    
    print(f"   Average RSI: {avg_rsi:.1f}")
    print(f"   Overbought (>70): {overbought} ({overbought/len(df_with_rsi)*100:.1f}%)")
    print(f"   Oversold (<30): {oversold} ({oversold/len(df_with_rsi)*100:.1f}%)")
    print(f"   Neutral (30-70): {neutral} ({neutral/len(df_with_rsi)*100:.1f}%)")

# Partial TP Analysis
print(f"\n{'='*80}")
print(f"🎯 PARTIAL TP ANALYSIS (TP1=25%, TP2=50%, TP3=75%)")
print(f"{'='*80}")

total_analyzed = sum(partial_tp_results.values())
print(f"\nAnalyzed {total_analyzed} losing trades:")
print(f"   TP1 hit (25%): {partial_tp_results['tp1_hit']} ({partial_tp_results['tp1_hit']/total_analyzed*100:.1f}%)")
print(f"   TP2 hit (50%): {partial_tp_results['tp2_hit']} ({partial_tp_results['tp2_hit']/total_analyzed*100:.1f}%)")
print(f"   TP3 hit (75%): {partial_tp_results['tp3_hit']} ({partial_tp_results['tp3_hit']/total_analyzed*100:.1f}%)")
print(f"   None hit: {partial_tp_results['none_hit']} ({partial_tp_results['none_hit']/total_analyzed*100:.1f}%)")

# Calculate potential P&L with partial TPs
current_loss = losers['pnl'].sum()
tp_distance = abs(losers['take_profit'].iloc[0] - losers['entry_price'].iloc[0])

# Scenario: Close 50% at TP1, 50% at TP2 (or SL)
tp1_profit_per_trade = tp_distance * 0.25 * 0.5  # 50% of position at 25% profit
potential_improvement = partial_tp_results['tp1_hit'] * tp1_profit_per_trade

print(f"\n💡 PARTIAL TP STRATEGY IMPACT:")
print(f"   Current loss from these trades: ${current_loss:.2f}")
print(f"   If using TP1 (25%) for 50% position: ${-current_loss + potential_improvement:.2f}")
print(f"   Potential improvement: ${potential_improvement:.2f}")

# Recommendations
print(f"\n{'='*80}")
print(f"💡 RECOMMENDATIONS TO REDUCE LOSSES")
print(f"{'='*80}")

print(f"\n1️⃣  FILTER COUNTER-TREND ENTRIES (1H timeframe):")
if len(counter_trend_losses) > 0:
    loser_counter_pct = len(counter_trend_losses) / len(df_losers_context) * 100
    winner_counter_pct = winner_counter_trend_count / len(winners) * 100
    
    print(f"   • LOSERS: {len(counter_trend_losses)} counter-trend ({loser_counter_pct:.1f}%)")
    print(f"   • WINNERS: {winner_counter_trend_count} counter-trend ({winner_counter_pct:.1f}%)")
    
    if winner_counter_pct < loser_counter_pct - 10:
        print(f"   ✅ Counter-trend filtering WOULD HELP:")
        print(f"      - Eliminates {len(counter_trend_losses)} losses (${-len(counter_trend_losses) * 146.50:.2f})")
        print(f"      - Only sacrifices {winner_counter_trend_count} wins (${winner_counter_trend_count * 493.50:.2f})")
        net_benefit = (winner_counter_trend_count * 493.50) - (len(counter_trend_losses) * 146.50)
        print(f"      - NET IMPACT: ${net_benefit:.2f}")
    else:
        print(f"   ❌ Counter-trend filtering NOT RECOMMENDED:")
        print(f"      - Winners ({winner_counter_pct:.1f}%) and losers ({loser_counter_pct:.1f}%) both counter-trend at similar rates")
        print(f"      - Filtering would not improve win rate")

print(f"\n2️⃣  IMPLEMENT PARTIAL TP STRATEGY:")
if partial_tp_results['tp1_hit'] > 100:
    print(f"   • LOSERS: {partial_tp_results['tp1_hit']} hit TP1 before stopping out")
    print(f"   • WINNERS: {winner_tp1_count}/{len(winners)} ({winner_tp1_count/len(winners)*100:.1f}%) hit TP1")
    
    straight_to_tp = len(winners) - winner_tp1_count
    if straight_to_tp > 0:
        print(f"   ⚠️  TRADE-OFF: {straight_to_tp} winners ({straight_to_tp/len(winners)*100:.1f}%) went STRAIGHT to TP")
        print(f"      - These would give up 75% profit if taking partial at TP1")
    
    print(f"\n   💡 RECOMMENDATION:")
    print(f"      - Close 30-40% at TP1 (25% of target) to lock partial profit")
    print(f"      - Let remaining 60-70% run to full TP")
    print(f"      - Balances: Locking gains vs letting winners run")
    print(f"      - Potential loss reduction: ${potential_improvement:.2f}")

print(f"\n3️⃣  RSI FILTER:")
if len(df_with_rsi) > 0 and (overbought > 50 or oversold > 50):
    print(f"   • Avoid entries when RSI extreme (>70 or <30)")
    print(f"   • Would filter {overbought + oversold} trades")

print(f"\n4️⃣  WIDER STOPS TO REDUCE WHIPSAWS:")
print(f"   • Test 0.75-0.9× ATR stops (vs current 0.7×)")
print(f"   • May reduce premature stop-outs")
print(f"   • Trade-off: Lower R:R ratio but potentially higher win rate")

print(f"\n{'='*80}")
