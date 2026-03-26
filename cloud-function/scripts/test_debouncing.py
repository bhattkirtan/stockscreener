#!/usr/bin/env python3
"""
Test signal debouncing logic to prevent duplicate trades after SL/TP.
Compares strategy performance with and without debouncing.
"""

import sys
import os
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.strategy import SupertrendVWAPStrategy
from src.core.backtester import IntraCandleBacktester, BacktestConfig


def load_data():
    """Load GOLD M5 data for backtesting."""
    data_path = Path(__file__).parent.parent / 'data' / 'gold_m5_2024.csv'
    
    if not data_path.exists():
        # Try alternative path
        data_path = Path(__file__).parent.parent / 'data' / 'GOLD_M5_2024-01-01_2024-12-31.csv'
    
    if not data_path.exists():
        print(f"❌ Data file not found: {data_path}")
        sys.exit(1)
    
    print(f"📂 Loading data from: {data_path}")
    df = pd.read_csv(data_path)
    
    # Ensure timestamp column
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.set_index('timestamp')
    elif 'time' in df.columns:
        df['timestamp'] = pd.to_datetime(df['time'])
        df = df.set_index('timestamp')
    
    # Ensure OHLC columns
    for col in ['open', 'high', 'low', 'close']:
        if col not in df.columns:
            print(f"❌ Missing required column: {col}")
            sys.exit(1)
    
    print(f"✅ Loaded {len(df)} candles")
    print(f"   Date range: {df.index[0]} to {df.index[-1]}")
    
    return df


def simulate_debounced_backtest(df: pd.DataFrame, sl_cooldown_minutes: int = 15, tp_cooldown_minutes: int = 5):
    """
    Simulate backtest with debouncing logic.
    This mimics the exact logic from trading_bot.py.
    """
    
    # Best strategy params: ST2.0 SMA25/30 BB2.0 Fixed 20/40
    strategy = SupertrendVWAPStrategy(
        supertrend_period=7,
        supertrend_multiplier=2.0,
        sma_fast=25,
        sma_slow=30,
        ema_period=25,
        bb_period=20,
        bb_std=2.0,
        sl_pips=20.0,
        tp_pips=40.0,
        pip_value=1.0,
        use_rsi_filter=False,
        use_atr_volatility_filter=False,
        use_session_filter=False,
        use_heikin_ashi=False
    )
    
    # Calculate indicators
    df_with_indicators = strategy.calculate_indicators(df.copy())
    
    # Simulate trading with debouncing
    current_position = None
    last_closed_position = None
    last_signal_state = None
    trades = []
    
    for i in range(1, len(df_with_indicators)):
        row = df_with_indicators.iloc[i]
        prev_row = df_with_indicators.iloc[i-1]
        
        # Skip if indicators not ready
        if pd.isna(row['supertrend']) or pd.isna(row['sma_fast']) or pd.isna(row['sma_slow']):
            continue
        
        close = row['close']
        supertrend_dir = row['direction']
        sma_fast = row['sma_fast']
        sma_slow = row['sma_slow']
        ema = row['ema']
        timestamp = row.name
        
        # Check if in position
        if current_position is not None:
            # Check for exit signal
            if current_position['direction'] == 'BUY' and supertrend_dir == -1:
                # Close LONG on bearish signal
                close_reason = 'SIGNAL'
                trades.append({
                    'entry_time': current_position['entry_time'],
                    'exit_time': timestamp,
                    'direction': current_position['direction'],
                    'entry_price': current_position['entry_price'],
                    'exit_price': close,
                    'sl': current_position['sl'],
                    'tp': current_position['tp'],
                    'close_reason': close_reason,
                    'pnl': close - current_position['entry_price']
                })
                last_closed_position = {
                    'direction': current_position['direction'],
                    'close_time': timestamp,
                    'close_reason': close_reason
                }
                current_position = None
                
            elif current_position['direction'] == 'SELL' and supertrend_dir == 1:
                # Close SHORT on bullish signal
                close_reason = 'SIGNAL'
                trades.append({
                    'entry_time': current_position['entry_time'],
                    'exit_time': timestamp,
                    'direction': current_position['direction'],
                    'entry_price': current_position['entry_price'],
                    'exit_price': close,
                    'sl': current_position['sl'],
                    'tp': current_position['tp'],
                    'close_reason': close_reason,
                    'pnl': current_position['entry_price'] - close
                })
                last_closed_position = {
                    'direction': current_position['direction'],
                    'close_time': timestamp,
                    'close_reason': close_reason
                }
                current_position = None
            
            # Check SL/TP hits
            elif current_position['direction'] == 'BUY':
                if close <= current_position['sl']:
                    # SL hit
                    close_reason = 'SL_HIT'
                    trades.append({
                        'entry_time': current_position['entry_time'],
                        'exit_time': timestamp,
                        'direction': current_position['direction'],
                        'entry_price': current_position['entry_price'],
                        'exit_price': current_position['sl'],
                        'sl': current_position['sl'],
                        'tp': current_position['tp'],
                        'close_reason': close_reason,
                        'pnl': current_position['sl'] - current_position['entry_price']
                    })
                    last_closed_position = {
                        'direction': current_position['direction'],
                        'close_time': timestamp,
                        'close_reason': close_reason
                    }
                    current_position = None
                elif close >= current_position['tp']:
                    # TP hit
                    close_reason = 'TP_HIT'
                    trades.append({
                        'entry_time': current_position['entry_time'],
                        'exit_time': timestamp,
                        'direction': current_position['direction'],
                        'entry_price': current_position['entry_price'],
                        'exit_price': current_position['tp'],
                        'sl': current_position['sl'],
                        'tp': current_position['tp'],
                        'close_reason': close_reason,
                        'pnl': current_position['tp'] - current_position['entry_price']
                    })
                    last_closed_position = {
                        'direction': current_position['direction'],
                        'close_time': timestamp,
                        'close_reason': close_reason
                    }
                    current_position = None
                    
            elif current_position['direction'] == 'SELL':
                if close >= current_position['sl']:
                    # SL hit
                    close_reason = 'SL_HIT'
                    trades.append({
                        'entry_time': current_position['entry_time'],
                        'exit_time': timestamp,
                        'direction': current_position['direction'],
                        'entry_price': current_position['entry_price'],
                        'exit_price': current_position['sl'],
                        'sl': current_position['sl'],
                        'tp': current_position['tp'],
                        'close_reason': close_reason,
                        'pnl': current_position['entry_price'] - current_position['sl']
                    })
                    last_closed_position = {
                        'direction': current_position['direction'],
                        'close_time': timestamp,
                        'close_reason': close_reason
                    }
                    current_position = None
                elif close <= current_position['tp']:
                    # TP hit
                    close_reason = 'TP_HIT'
                    trades.append({
                        'entry_time': current_position['entry_time'],
                        'exit_time': timestamp,
                        'direction': current_position['direction'],
                        'entry_price': current_position['entry_price'],
                        'exit_price': current_position['tp'],
                        'sl': current_position['sl'],
                        'tp': current_position['tp'],
                        'close_reason': close_reason,
                        'pnl': current_position['entry_price'] - current_position['tp']
                    })
                    last_closed_position = {
                        'direction': current_position['direction'],
                        'close_time': timestamp,
                        'close_reason': close_reason
                    }
                    current_position = None
            
            continue
        
        # Determine current signal state
        current_signal = None
        if supertrend_dir == 1 and close > ema and sma_fast > sma_slow:
            current_signal = 'BUY'
        elif supertrend_dir == -1 and close < ema and sma_fast < sma_slow:
            current_signal = 'SELL'
        
        # Signal edge detection: only trade NEW signals
        if current_signal == last_signal_state:
            # Signal was already active - skip
            continue
        
        # Cooldown check: after SL/TP hit, wait before re-entering same direction
        if last_closed_position and current_signal:
            last_direction = last_closed_position['direction']
            last_close_time = last_closed_position['close_time']
            last_close_reason = last_closed_position['close_reason']
            
            if current_signal == last_direction:
                minutes_since_close = (timestamp - last_close_time).total_seconds() / 60
                
                # Apply cooldown
                if last_close_reason == 'SL_HIT' and minutes_since_close < sl_cooldown_minutes:
                    last_signal_state = current_signal
                    continue
                elif last_close_reason == 'TP_HIT' and minutes_since_close < tp_cooldown_minutes:
                    last_signal_state = current_signal
                    continue
        
        # Check for crossovers
        sma_fast_prev = prev_row['sma_fast']
        sma_slow_prev = prev_row['sma_slow']
        golden_cross = (sma_fast > sma_slow) and (sma_fast_prev <= sma_slow_prev)
        death_cross = (sma_fast < sma_slow) and (sma_fast_prev >= sma_slow_prev)
        
        # BUY Signal
        if supertrend_dir == 1 and close > ema and (golden_cross or sma_fast > sma_slow):
            stop_loss = close - 20.0  # 20 pips
            take_profit = close + 40.0  # 40 pips
            current_position = {
                'direction': 'BUY',
                'entry_time': timestamp,
                'entry_price': close,
                'sl': stop_loss,
                'tp': take_profit
            }
            last_signal_state = 'BUY'
            
        # SELL Signal
        elif supertrend_dir == -1 and close < ema and (death_cross or sma_fast < sma_slow):
            stop_loss = close + 20.0  # 20 pips
            take_profit = close - 40.0  # 40 pips
            current_position = {
                'direction': 'SELL',
                'entry_time': timestamp,
                'entry_price': close,
                'sl': stop_loss,
                'tp': take_profit
            }
            last_signal_state = 'SELL'
        else:
            # No signal
            last_signal_state = None
    
    return pd.DataFrame(trades)


def main():
    print("=" * 110)
    print(" SIGNAL DEBOUNCING BACKTEST")
    print("=" * 110)
    print("\nTesting strategy performance WITH cooldown after SL/TP hits")
    print("This prevents duplicate trades when SL hit but market conditions unchanged.\n")
    
    # Load data
    df = load_data()
    
    # Run backtest with debouncing
    print("\n🔬 Running backtest with debouncing (SL cooldown: 15min, TP cooldown: 5min)...")
    trades_df = simulate_debounced_backtest(df, sl_cooldown_minutes=15, tp_cooldown_minutes=5)
    
    if len(trades_df) == 0:
        print("❌ No trades generated")
        return
    
    # Calculate statistics
    total_trades = len(trades_df)
    winning_trades = len(trades_df[trades_df['pnl'] > 0])
    losing_trades = len(trades_df[trades_df['pnl'] < 0])
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    
    total_pnl = trades_df['pnl'].sum()
    avg_win = trades_df[trades_df['pnl'] > 0]['pnl'].mean() if winning_trades > 0 else 0
    avg_loss = trades_df[trades_df['pnl'] < 0]['pnl'].mean() if losing_trades > 0 else 0
    
    # Close reason breakdown
    sl_hits = len(trades_df[trades_df['close_reason'] == 'SL_HIT'])
    tp_hits = len(trades_df[trades_df['close_reason'] == 'TP_HIT'])
    signal_exits = len(trades_df[trades_df['close_reason'] == 'SIGNAL'])
    
    print("\n" + "=" * 110)
    print(" BACKTEST RESULTS WITH DEBOUNCING")
    print("=" * 110)
    print(f"Total Trades:      {total_trades}")
    print(f"Winning Trades:    {winning_trades} ({win_rate:.1f}%)")
    print(f"Losing Trades:     {losing_trades}")
    print(f"")
    print(f"Total P&L:         {total_pnl:,.2f} pips")
    print(f"Average Win:       {avg_win:.2f} pips")
    print(f"Average Loss:      {avg_loss:.2f} pips")
    print(f"")
    print(f"Close Reasons:")
    print(f"  SL Hits:         {sl_hits} ({sl_hits/total_trades*100:.1f}%)")
    print(f"  TP Hits:         {tp_hits} ({tp_hits/total_trades*100:.1f}%)")
    print(f"  Signal Exits:    {signal_exits} ({signal_exits/total_trades*100:.1f}%)")
    print("=" * 110)
    
    # Show sample of trades around SL hits
    print("\n📊 Sample trades showing SL hits followed by cooldown:")
    sl_hit_trades = trades_df[trades_df['close_reason'] == 'SL_HIT'].head(5)
    
    for idx, trade in sl_hit_trades.iterrows():
        print(f"\n  Trade #{idx}: {trade['direction']} @ {trade['entry_price']:.2f}")
        print(f"    Entry:  {trade['entry_time']}")
        print(f"    Exit:   {trade['exit_time']} (SL HIT)")
        print(f"    P&L:    {trade['pnl']:.2f} pips")
        
        # Check if next trade was delayed
        next_trades = trades_df[trades_df['entry_time'] > trade['exit_time']].head(3)
        if len(next_trades) > 0:
            next_same_direction = next_trades[next_trades['direction'] == trade['direction']]
            if len(next_same_direction) > 0:
                next_trade = next_same_direction.iloc[0]
                delay_minutes = (next_trade['entry_time'] - trade['exit_time']).total_seconds() / 60
                print(f"    Next {trade['direction']}: {delay_minutes:.1f} minutes later {'✅ (cooldown applied)' if delay_minutes >= 15 else '⚠️ (too soon!)'}")
    
    print("\n✅ Backtest complete!\n")


if __name__ == '__main__':
    main()
