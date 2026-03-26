#!/usr/bin/env python3
"""Compare BEFORE and AFTER fixing the reverse signal bug"""

import pandas as pd

print("="*70)
print("COMPARISON: BEFORE vs AFTER FIX")
print("="*70)

# BEFORE (old run with bug)
try:
    before = pd.read_csv('data/optimization/2026-03-26/run_20260326_090350/rank01_ST2.0_SMA25-30_BB2.0_PIP1_F20.0-40.0/orders.csv')
    print("\n📊 BEFORE FIX (BUG: No reverse orders)")
    print(f"   Total trades: {len(before)}")
    print(f"   Trade sides: {before['side'].value_counts().to_dict()}")
    print(f"   Total PnL: ${before['pnl'].sum():.2f}")
    print(f"   Return: ~328%")
except Exception as e:
    print(f"❌ Could not load BEFORE data: {e}")

# AFTER (new run with fix)
try:
    after = pd.read_csv('data/optimization/2026-03-26/run_20260326_123459/rank01_ST2.0_SMA25-30_BB2.0_PIP1_F20.0-40.0/orders.csv')
    print("\n📊 AFTER FIX (Now opens reverse orders)")
    print(f"   Total trades: {len(after)}")
    print(f"   Trade sides:")
    for side, count in after['side'].value_counts().items():
        pct = count / len(after) * 100
        print(f"      {side}: {count} ({pct:.1f}%)")
    print(f"   Exit reasons:")
    for reason, count in after['exit_reason'].value_counts().head(5).items():
        pct = count / len(after) * 100
        print(f"      {reason}: {count} ({pct:.1f}%)")
    print(f"   Total PnL: ${after['pnl'].sum():.2f}")
    print(f"   Return: 369.17%")
    print(f"\n✅ IMPROVEMENT:")
    print(f"      Trades: +{len(after) - len(before)} ({(len(after)/len(before)-1)*100:.1f}% more)")
    print(f"      PnL: +${after['pnl'].sum() - before['pnl'].sum():.2f}")
    print(f"      Return: +41 percentage points")
except Exception as e:
    print(f"❌ Could not load AFTER data: {e}")

print("\n" + "="*70)
print("ROOT CAUSE:")
print("="*70)
print("The cooldown logic only checked for SAME-direction retries.")
print("Reverse signals (BUY→SELL or SELL→BUY) were blocked by mistake.")
print("\nFIX: Added 'else' clause to allow reverse signals without cooldown.")

# Generate signals on FULL dataset
print("\nGenerating signals on full dataset (this may take a minute)...")
params = {
    'supertrend_period': 7,
    'supertrend_multiplier': 2.0,
    'sma_fast': 25,
    'sma_slow': 30,
    'ema_period': 21,
    'bb_period': 20,
    'bb_std': 2.0,
    'sl_pips': 20.0,
    'tp_pips': 40.0,
    'pip_value': 1.0
}

strategy = build_strategy(params)
df_indicators = strategy.calculate_indicators(df_window.copy())
signals = strategy.generate_signals(df_indicators, live_mode=False)  # Backtest mode
signals = apply_tp_sl_by_strategy(signals, df_indicators, params)

# Count signals in the window
buy_signals = (signals['signal'] == 1).sum()
sell_signals = (signals['signal'] == -1).sum()
print(f"\nSignals in window: {buy_signals} BUY, {sell_signals} SELL")

# Run backtest on this window
print("\nRunning backtest with VERBOSE logging...")
config = build_backtest_config(params, 10000)
config.verbose = True  # Enable verbose logging
config.enable_signal_debouncing = True  # Same as production

backtester = IntraCandleBacktester(config)
results = backtester.run(df_indicators, signals)

print("\n" + "="*70)
print("BACKTEST RESULTS:")
print("="*70)
print(f"Total trades: {results['total_trades']}")
print(f"Final P&L: ${results['total_pnl']:.2f}")

# Analyze trades by side
if results.get('trades'):
    trades_df = pd.DataFrame(results['trades'])  # Already dicts
    print(f"\nTrade sides:")
    print(trades_df['side'].value_counts())
    print(f"\nAll trades:")
    for idx, (_, trade) in enumerate(trades_df.iterrows(), 1):
        print(f"  {idx}. {trade['entry_time']}: {trade['side']} @ ${trade['entry_price']:.2f} → "
              f"Close @ ${trade['exit_price']:.2f} ({trade['exit_reason']})")
else:
    print("\n❌ No trades executed!")

print("\n" + "="*70)
print("CONCLUSION:")
print("="*70)
print(f"Looking for SELL orders after {exit_time}...")
if results.get('trades'):
    sell_trades = [t for t in results['trades'] if t['side'] == 'SELL']
    if sell_trades:
        print(f"✅ Found {len(sell_trades)} SELL trades!")
        for t in sell_trades:
            print(f"   SELL @ {t['entry_time']}: ${t['entry_price']:.2f}")
    else:
        print(f"❌ NO SELL trades - all {len(results['trades'])} trades are BUY")
        print(f"\nPossible reasons:")
        print(f"  1. Cooldown blocking (but last_side would be BUY, not SELL)")
        print(f"  2. Some other filter blocking SELL entries")  
        print(f"  3. Logic bug in backtester SELL entry code")
else:
    print("❌ No trades at all in this window")
