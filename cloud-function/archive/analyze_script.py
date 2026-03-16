import pandas as pd
import json

BASE = 'data/optimization/2026-03-16/run_20260316_070905'
df = pd.read_csv(f'{BASE}/GOLD_M5_all_strategies_20260316_070905.csv')

# --- deduplicate (same combo appears twice due to train/test) ---
df = df.drop_duplicates(subset=['strategy_name']).copy()

# ── TOP 10 OVERVIEW ──────────────────────────────────────────────
top = df.nlargest(10, 'return_pct')[['strategy_name','return_pct','sharpe_ratio','win_rate','profit_factor','max_drawdown_pct','total_trades','avg_win','avg_loss','st_mult','sma_fast','sma_slow','tp_sl']]
print("═"*90)
print("TOP 10 BY RETURN")
print("═"*90)
print(top.to_string(index=False))

# ── TOP 10 BY SHARPE ─────────────────────────────────────────────
top_sharpe = df.nlargest(10, 'sharpe_ratio')[['strategy_name','return_pct','sharpe_ratio','win_rate','profit_factor','max_drawdown_pct','total_trades','st_mult','sma_fast','sma_slow','tp_sl']]
print("\n" + "═"*90)
print("TOP 10 BY SHARPE (risk-adjusted)")
print("═"*90)
print(top_sharpe.to_string(index=False))

# ── TRADE EXIT ANALYSIS from rank01 orders ───────────────────────
print("\n" + "═"*90)
print("TRADE EXIT ANALYSIS — Rank #1 (rank01_ST1.5_SMA25-30_BB2.0_PIP0.50_F15-20)")
print("═"*90)
orders = pd.read_csv(f'{BASE}/rank01_ST1.5_SMA25-30_BB2.0_PIP0.50_F15-20/orders.csv')
print("Columns:", list(orders.columns))
print(orders.head(3).to_string())

if 'exit_reason' in orders.columns or 'reason' in orders.columns:
    col = 'exit_reason' if 'exit_reason' in orders.columns else 'reason'
    print("\nExit reason breakdown:")
    print(orders[col].value_counts().to_string())

# holding period
if 'entry_time' in orders.columns and 'exit_time' in orders.columns:
    orders['entry_time'] = pd.to_datetime(orders['entry_time'])
    orders['exit_time']  = pd.to_datetime(orders['exit_time'])
    orders['hold_hours'] = (orders['exit_time'] - orders['entry_time']).dt.total_seconds() / 3600
    print(f"\nHolding period (hours):")
    print(f"  Mean:   {orders['hold_hours'].mean():.1f}h")
    print(f"  Median: {orders['hold_hours'].median():.1f}h")
    print(f"  Min:    {orders['hold_hours'].min():.1f}h")
    print(f"  Max:    {orders['hold_hours'].max():.1f}h")
    print(f"  <1h:    {(orders['hold_hours']<1).sum()} trades  ({(orders['hold_hours']<1).mean()*100:.0f}%)")
    print(f"  1-4h:   {((orders['hold_hours']>=1)&(orders['hold_hours']<4)).sum()} trades  ({((orders['hold_hours']>=1)&(orders['hold_hours']<4)).mean()*100:.0f}%)")
    print(f"  4-24h:  {((orders['hold_hours']>=4)&(orders['hold_hours']<24)).sum()} trades  ({((orders['hold_hours']>=4)&(orders['hold_hours']<24)).mean()*100:.0f}%)")
    print(f"  >24h:   {(orders['hold_hours']>=24).sum()} trades  ({(orders['hold_hours']>=24).mean()*100:.0f}%)")

# ── PARAMETER PATTERNS in top 20% ────────────────────────────────
print("\n" + "═"*90)
print("PARAMETER PATTERNS IN TOP 20% OF STRATEGIES")
print("═"*90)
threshold = df['return_pct'].quantile(0.80)
top20 = df[df['return_pct'] >= threshold]
print(f"Top 20% threshold: {threshold:.1f}% return  ({len(top20)} strategies)")
print(f"\nSupertrend multiplier distribution:")
print(top20['st_mult'].value_counts().sort_index().to_string())
print(f"\nSMA fast/slow pairs:")
print(top20.groupby(['sma_fast','sma_slow']).size().sort_values(ascending=False).head(8).to_string())
print(f"\nTP/SL strategy:")
print(top20['tp_sl'].value_counts().head(8).to_string())

# ── FIXED vs ATR SUMMARY ─────────────────────────────────────────
print("\n" + "═"*90)
print("FIXED vs ATR COMPARISON")
print("═"*90)
df['tp_type'] = df['tp_sl'].apply(lambda x: 'ATR' if str(x).startswith('ATR') else 'Fixed')
for ttype, grp in df.groupby('tp_type'):
    print(f"\n{ttype}:  n={len(grp)}  mean_return={grp['return_pct'].mean():.1f}%  "
          f"best={grp['return_pct'].max():.1f}%  "
          f"mean_sharpe={grp['sharpe_ratio'].mean():.3f}  "
          f"mean_win_rate={grp['win_rate'].mean():.1f}%")
