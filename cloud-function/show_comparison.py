import pandas as pd

df = pd.read_csv('data/optimization/2026-03-17/run_20260317_133552/GOLD_M5_all_strategies_20260317_133552.csv')

blocked = df[df['enable_event_blocking'] == True].set_index('_winner_rank')
no_block = df[df['enable_event_blocking'] == False].set_index('_winner_rank')

print(f"{'Rank':<6} {'Strategy':<38} {'No-Block':>10} {'Blocked':>10} {'Delta':>8} {'DD(nb)':>8} {'DD(b)':>8} {'Win'}")
print("-" * 112)

improved = 0
declined = 0
neutral = 0

for rank in sorted(no_block.index):
    nb = no_block.loc[rank]
    if rank not in blocked.index:
        continue
    bl = blocked.loc[rank]

    nb_ret = float(nb['return_pct'])
    bl_ret = float(bl['return_pct'])
    delta = bl_ret - nb_ret
    nb_dd = float(nb['max_drawdown_pct'])
    bl_dd = float(bl['max_drawdown_pct'])

    strat = str(nb.get('strategy_name', f'rank{rank:03d}'))
    strat_short = strat.replace('_BB2.0_PIP1', '').replace('rank0', 'r').replace('rank', 'r')
    strat_short = strat_short[:38]

    if delta > 0.5:
        win = "\u2705"
        improved += 1
    elif delta < -0.5:
        win = "\u274c"
        declined += 1
    else:
        win = "~"
        neutral += 1

    print(f"{rank:<6} {strat_short:<38} {nb_ret:>10.1f}% {bl_ret:>10.1f}% {delta:>+8.1f}% {nb_dd:>8.1f}% {bl_dd:>8.1f}% {win}")

print("-" * 112)
print(f"Improved: {improved}  Declined: {declined}  Neutral: {neutral}")
print(f"Best with blocking: rank {blocked['return_pct'].idxmax()}: {blocked['return_pct'].max():.1f}%")
print(f"Best no blocking:   rank {no_block['return_pct'].idxmax()}: {no_block['return_pct'].max():.1f}%")

all_deltas = blocked['return_pct'].values - no_block.reindex(blocked.index)['return_pct'].values
import numpy as np
print(f"\nAvg delta (blocking - no blocking): {float(np.nanmean(all_deltas)):+.2f}%")
print(f"Max gain from blocking:  {float(np.nanmax(all_deltas)):+.2f}%")
print(f"Max loss from blocking:  {float(np.nanmin(all_deltas)):+.2f}%")
