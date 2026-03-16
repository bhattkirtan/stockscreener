import pandas as pd
import sys

# Check which file to analyze
file_path = sys.argv[1] if len(sys.argv) > 1 else 'hybrid_optimization_results.csv'

df = pd.read_csv(file_path)

# Handle different CSV formats
if 'params' in df.columns:
    # Hybrid optimization format
    df['params_dict'] = df['params'].apply(eval)
    df['st_period'] = df['params_dict'].apply(lambda x: x['supertrend_period'])
    df['st_mult'] = df['params_dict'].apply(lambda x: x['supertrend_multiplier'])
    df['sl_mult'] = df['params_dict'].apply(lambda x: x.get('atr_sl_multiplier', 0.7))
    df['tp_mult'] = df['params_dict'].apply(lambda x: x.get('atr_tp_multiplier', 2.5))
    df['rr_ratio'] = df['tp_mult'] / df['sl_mult']
    df['return'] = df['total_return']
    df['trades'] = df['trades']
else:
    # SuperTrend optimization format
    df['st_period'] = df['st_period']
    df['st_mult'] = df['st_mult']
    df['return'] = df['return_pct']
    df['trades'] = df['total_trades']
    df['win_rate'] = df['win_rate']
    df['sharpe'] = df['sharpe_ratio']
    df['max_dd'] = df['max_drawdown_pct']
    df['profit_factor'] = df['profit_factor']

print('='*80)
print('📊 PARAMETER IMPACT ANALYSIS')
print('='*80)

print('\n1️⃣ SUPERTREND PERIOD (avg return by period):')
period_stats = df.groupby('st_period')['return'].agg(['mean', 'std', 'min', 'max', 'count']).round(2)
print(period_stats)

print('\n2️⃣ SUPERTREND MULTIPLIER (avg return by multiplier):')
mult_stats = df.groupby('st_mult')['return'].agg(['mean', 'std', 'min', 'max', 'count']).round(2)
print(mult_stats)

if 'sl_mult' in df.columns:
    print('\n3️⃣ STOP LOSS multiplier (avg return by SL):')
    sl_stats = df.groupby('sl_mult')['return'].agg(['mean', 'std', 'min', 'max', 'count']).round(2)
    print(sl_stats)

    print('\n4️⃣ TAKE PROFIT multiplier (avg return by TP):')
    tp_stats = df.groupby('tp_mult')['return'].agg(['mean', 'std', 'min', 'max', 'count']).round(2)
    print(tp_stats)

    print('\n5️⃣ RISK:REWARD RATIO (avg return by R:R):')
    rr_stats = df.groupby(df['rr_ratio'].round(1)).agg({
        'return': 'mean',
        'trades': 'mean'
    }).round(2)
    print(rr_stats)

if 'tp_sl' in df.columns:
    print('\n3️⃣ TP:SL STRATEGY (avg return by strategy):')
    tpsl_stats = df.groupby('tp_sl')['return'].agg(['mean', 'std', 'min', 'max', 'count']).round(2)
    print(tpsl_stats)

print('\n6️⃣ TOP 10 vs BOTTOM 10 CHARACTERISTICS:')
top10 = df.nlargest(10, 'return')
bottom10 = df.nsmallest(10, 'return')

print('\nTOP 10 AVERAGE:')
print(f'  Period: {top10["st_period"].mean():.1f}')
print(f'  Mult: {top10["st_mult"].mean():.2f}')
if 'sl_mult' in df.columns:
    print(f'  SL: {top10["sl_mult"].mean():.2f}x ATR')
    print(f'  TP: {top10["tp_mult"].mean():.2f}x ATR')
    print(f'  R:R: {top10["rr_ratio"].mean():.1f}')
if 'win_rate' in df.columns:
    print(f'  WinRate: {top10["win_rate"].mean():.1f}%')
print(f'  Trades: {top10["trades"].mean():.0f}')
print(f'  Return: {top10["return"].mean():.1f}%')
if 'sharpe' in df.columns:
    print(f'  Sharpe: {top10["sharpe"].mean():.3f}')
if 'max_dd' in df.columns:
    print(f'  MaxDD: {top10["max_dd"].mean():.2f}')

print('\nBOTTOM 10 AVERAGE:')
print(f'  Period: {bottom10["st_period"].mean():.1f}')
print(f'  Mult: {bottom10["st_mult"].mean():.2f}')
if 'sl_mult' in df.columns:
    print(f'  SL: {bottom10["sl_mult"].mean():.2f}x ATR')
    print(f'  TP: {bottom10["tp_mult"].mean():.2f}x ATR')
    print(f'  R:R: {bottom10["rr_ratio"].mean():.1f}')
if 'win_rate' in df.columns:
    print(f'  WinRate: {bottom10["win_rate"].mean():.1f}%')
print(f'  Trades: {bottom10["trades"].mean():.0f}')
print(f'  Return: {bottom10["return"].mean():.1f}%')
if 'sharpe' in df.columns:
    print(f'  Sharpe: {bottom10["sharpe"].mean():.3f}')
if 'max_dd' in df.columns:
    print(f'  MaxDD: {bottom10["max_dd"].mean():.2f}')

print('\n7️⃣ BEST PARAMETER COMBINATIONS (individual):')
best_period = df.groupby('st_period')['return'].mean().idxmax()
best_mult = df.groupby('st_mult')['return'].mean().idxmax()
print(f'Best Period: {best_period} (avg {df[df["st_period"]==best_period]["return"].mean():.1f}%)')
print(f'Best Mult: {best_mult} (avg {df[df["st_mult"]==best_mult]["return"].mean():.1f}%)')
if 'sl_mult' in df.columns:
    best_sl = df.groupby('sl_mult')['return'].mean().idxmax()
    best_tp = df.groupby('tp_mult')['return'].mean().idxmax()
    print(f'Best SL: {best_sl} (avg {df[df["sl_mult"]==best_sl]["return"].mean():.1f}%)')
    print(f'Best TP: {best_tp} (avg {df[df["tp_mult"]==best_tp]["return"].mean():.1f}%)')

print('\n8️⃣ CONSISTENCY CHECK - All configs with best ST params:')
best_st_configs = df[(df['st_period']==best_period) & (df['st_mult']==best_mult)]
if 'sl_mult' in df.columns:
    for sl in [0.5, 0.7, 0.9]:
        subset = best_st_configs[best_st_configs['sl_mult']==sl]
        if len(subset) > 0:
            print(f'\n  With SL={sl}x:')
            for _, row in subset.sort_values('return', ascending=False).iterrows():
                print(f'    TP={row["tp_mult"]}: Return={row["return"]:.1f}%, WR={row.get("win_rate", 0):.1f}%, Trades={int(row["trades"])}')
else:
    print(f'\nTop configs with Period={best_period}, Mult={best_mult}:')
    top_best = best_st_configs.nlargest(10, 'return')
    for _, row in top_best.iterrows():
        if 'strategy_name' in row:
            print(f'  {row["strategy_name"]}: {row["return"]:.1f}% return, {int(row["trades"])} trades')
        else:
            print(f'  Return={row["return"]:.1f}%, Trades={int(row["trades"])}')

print('\n9️⃣ POTENTIAL CONCERNS:')
concerns = []

high_dd = df[df['max_dd'] > 1.0]
if len(high_dd) > 0:
    concerns.append(f'⚠️  {len(high_dd)}/81 configs have MaxDD > 100% (account wipeout risk)')
    
low_trades = df[df['trades'] < 80]
if len(low_trades) > 0:
    concerns.append(f'⚠️  {len(low_trades)}/81 configs have <80 trades (lower statistical confidence)')

low_wr = df[df['win_rate'] < 20]
if len(low_wr) > 0:
    concerns.append(f'⚠️  {len(low_wr)}/81 configs have WinRate <20% (psychologically difficult)')

best_return = df['total_return'].max()
second_best = df['total_return'].nlargest(2).iloc[1]
gap = (best_return - second_best) / second_best * 100
if gap > 10:
    concerns.append(f'⚠️  Best config is {gap:.1f}% better than 2nd (potential overfitting)')

negative_configs = len(df[df['total_return'] < 0])
if negative_configs > 0:
    concerns.append(f'⚠️  {negative_configs}/81 configs are LOSING money')

if concerns:
    for concern in concerns:
        print(concern)
else:
    print('✅ No major concerns found')

print('\n🔟 KEY INSIGHTS:')
print(f'• Best single param: Period={best_period}, Mult={best_mult} (faster trend detection)')
print(f'• Best R:R ratio: {df.groupby(df["rr_ratio"].round(1))["total_return"].mean().idxmax():.1f}:1')
print(f'• SL=0.5 avg: {df[df["sl_mult"]==0.5]["total_return"].mean():.1f}% vs SL=0.9 avg: {df[df["sl_mult"]==0.9]["total_return"].mean():.1f}%')
print(f'• Performance range: {df["total_return"].min():.1f}% to {df["total_return"].max():.1f}% ({df["total_return"].max() - df["total_return"].min():.1f}% spread)')
print(f'• Win rate range: {df["win_rate"].min():.1f}% to {df["win_rate"].max():.1f}%')

print('\n' + '='*80)
