import pandas as pd

# Load results
df = pd.read_csv('data/optimization/2026-03-07/run_20260307_233341/GOLD_M5_all_strategies_20260307_233341.csv')

print("="*80)
print("PHASE 2 RESULTS - BUG FIX VERIFICATION")
print("="*80)
print(f"Total strategies: {len(df)}")

# ADX filter impact
print("\n" + "="*80)
print("ADX FILTER IMPACT ON TRADE COUNT")
print("="*80)
adx_stats = df.groupby('use_adx_filter')['total_trades'].agg(['min', 'max', 'mean', 'count'])
print(adx_stats)

adx_false = df[df['use_adx_filter'] == False]['total_trades'].mean()
adx_true = df[df['use_adx_filter'] == True]['total_trades'].mean()
diff = adx_false - adx_true
print(f"\nADX False mean: {adx_false:.1f} trades")
print(f"ADX True mean: {adx_true:.1f} trades")
print(f"Difference: {diff:.1f} trades ({abs(diff)/adx_false*100:.1f}% {'reduction' if diff > 0 else 'increase'})")

if abs(diff) < 0.5:
    print("❌ BUG STILL EXISTS - No effect!")
else:
    print("✅ BUG FIXED - ADX filter working!")

# Top 10
print("\n" + "="*80)
print("TOP 10 STRATEGIES")
print("="*80)
cols = ['return_pct', 'total_trades', 'win_rate', 'st_mult',
        'use_adx_filter', 'adx_threshold', 'use_bb_position_sizing', 
        'use_dynamic_tp_sl', 'dynamic_sl_atr_mult', 'dynamic_tp_atr_mult']
print(df.nlargest(10, 'return_pct')[cols].to_string(index=False))

# Dynamic TP/SL impact
print("\n" + "="*80)
print("DYNAMIC TP/SL IMPACT")
print("="*80)
dynamic_stats = df.groupby('use_dynamic_tp_sl').agg({
    'return_pct': ['mean', 'max', 'count'],
    'win_rate': 'mean'
}).round(2)
print(dynamic_stats)

# BB Position Sizing impact
print("\n" + "="*80)
print("BB POSITION SIZING IMPACT")
print("="*80)
bb_stats = df.groupby('use_bb_position_sizing').agg({
    'return_pct': ['mean', 'max', 'count'],
    'win_rate': 'mean'
}).round(2)
print(bb_stats)

# Best dynamic TP/SL combo
print("\n" + "="*80)
print("BEST DYNAMIC TP/SL MULTIPLIER COMBINATIONS")
print("="*80)
dynamic_combos = df[df['use_dynamic_tp_sl'] == True].groupby(['dynamic_sl_atr_mult', 'dynamic_tp_atr_mult']).agg({
    'return_pct': ['mean', 'max', 'count']
}).round(2)
print(dynamic_combos)
