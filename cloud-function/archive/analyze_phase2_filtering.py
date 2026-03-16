#!/usr/bin/env python3
"""Analyze if Phase 2 features actually filter entries (change trade count)"""
import pandas as pd
import os

os.chdir('/Users/kirtanbhatt/code/stockScreener/cloud-function')
df = pd.read_csv('data/optimization/latest/GOLD_M5_all_strategies_20260307_195537.csv')

print('='*80)
print('PHASE 2 ENTRY FILTERING ANALYSIS')
print('='*80)

# Focus on one base config to isolate Phase 2 effects
base_config = df[(df['st_mult']==2.5) & (df['use_rsi_filter']==True) & 
                  (df['use_session_filter']==False) & (df['enable_eod_blackout']==True)]

print(f'\nBase config (ST 2.5, RSI=T, Session=F, EOD=T, TP 4x): {len(base_config)} strategies')
print(f'Trade count range: {base_config["total_trades"].min()} - {base_config["total_trades"].max()}')
print(f'Return range: {base_config["return_pct"].min():.2f}% - {base_config["return_pct"].max():.2f}%')

print('\n' + '='*80)
print('Does ADX filter change trade count?')
print('='*80)
for adx in [True, False]:
    subset = base_config[base_config['use_adx_filter']==adx]
    trades = subset['total_trades'].unique()
    returns = subset['return_pct'].unique()
    print(f'ADX={adx}: {len(subset)} strategies')
    print(f'  Trades: {trades}')
    print(f'  Returns: {[f"{r:.2f}" for r in returns]}')

print('\n' + '='*80)
print('Does BB sizing change returns (same trades, different position sizes)?')
print('='*80)
for bb in [True, False]:
    subset = base_config[base_config['use_bb_position_sizing']==bb]
    trades = subset['total_trades'].unique()
    returns = subset['return_pct'].unique()
    print(f'BB sizing={bb}: {len(subset)} strategies')
    print(f'  Trades: {trades}')
    print(f'  Returns: {[f"{r:.2f}" for r in returns]}')

print('\n' + '='*80)
print('Does Dynamic TP/SL change returns (same entries, different exits)?')
print('='*80)
for dyn in [True, False]:
    subset = base_config[base_config['use_dynamic_tp_sl']==dyn]
    trades = subset['total_trades'].unique()
    returns = subset['return_pct'].unique()
    print(f'Dynamic TP/SL={dyn}: {len(subset)} strategies')
    print(f'  Trades: {trades}')
    print(f'  Returns: {[f"{r:.2f}" for r in returns]}')

print('\n' + '='*80)
print('CONCLUSION:')
print('='*80)
print('If all Phase 2 variations show SAME trades and SAME returns:')
print('  → Phase 2 features are NOT affecting entry or exit decisions')
print('  → Bug: Features defined but not applied')
print('\nIf trades differ but returns same:')
print('  → Entry filtering works, but all filtered trades happen to have same aggregate P&L')
print('\nIf both trades and returns differ:')
print('  → Phase 2 features working correctly ✓')

print('\n' + '='*80)
print('Trade count distribution across ALL 576 strategies:')
print('='*80)
print(df['total_trades'].value_counts().sort_index().head(20))
