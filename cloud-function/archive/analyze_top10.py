#!/usr/bin/env python3
"""Analyze top 10 configurations to identify expansion opportunities"""
import pandas as pd
import os

# Change to script directory
os.chdir('/Users/kirtanbhatt/code/stockScreener/cloud-function')

df = pd.read_csv('data/optimization/2026-03-08/run_20260308_155631/GOLD_M5_all_strategies_20260308_155631.csv')
df_sorted = df.sort_values('test_return_pct', ascending=False)

print('🏆 TOP 10 BY TEST PERFORMANCE (Out-of-Sample)')
print('=' * 80)

for i, row in df_sorted.head(10).iterrows():
    rank = df_sorted.index.get_loc(i) + 1
    print(f'\nRank {rank}: {row["return_pct"]:.2f}% train, {row["test_return_pct"]:.2f}% test')
    print(f'  ST: {row["st_mult"]}, SMA: {row["sma_fast"]}/{row["sma_slow"]}')
    print(f'  TP/SL: {row["tp_sl"]}')
    print(f'  RSI: {row["use_rsi_filter"]}, ATR Vol: {row["use_atr_volatility_filter"]}')
    print(f'  Session: {row["use_session_filter"]} ({row["trading_sessions"]}), EOD: {row["enable_eod_blackout"]}')

print('\n' + '=' * 80)
print('\nParameter frequency in top 10:')
print(f'  ST multiplier: {df_sorted.head(10)["st_mult"].value_counts().to_dict()}')
print(f'  SMA fast: {df_sorted.head(10)["sma_fast"].value_counts().to_dict()}')
print(f'  SMA slow: {df_sorted.head(10)["sma_slow"].value_counts().to_dict()}')
print(f'  TP/SL strategy: {df_sorted.head(10)["tp_sl"].value_counts().to_dict()}')

print('\n' + '=' * 80)
print('RECOMMENDATION: Should we also test:')
print('  - Different SL multipliers? (if variation exists in top 10)')
print('  - Different ST multipliers? (if variation exists in top 10)')
print('  - Different SMA combinations? (if variation exists in top 10)')
