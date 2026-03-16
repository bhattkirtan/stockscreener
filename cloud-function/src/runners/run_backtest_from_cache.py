#!/usr/bin/env python3
"""
Run backtest using ONLY cached data (no API calls)
Exports results as JSON for dashboard UI
"""

import os
import sys
import pandas as pd
import json
from datetime import datetime
import logging

from src.core.strategy import SupertrendVWAPStrategy
from src.core.backtester import BacktestConfig, IntraCandleBacktester
from src.data.gcs_cache import ensure_csv_from_gcs

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def load_cached_data(epic, resolution, max_bars):
    """Load from cache (downloads from GCS if needed)"""
    try:
        cache_file = ensure_csv_from_gcs(epic, resolution, max_bars)
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        
        # Trim to requested max_bars (take most recent bars)
        if max_bars and len(df) > max_bars:
            logger.info(f"📊 Trimming {len(df)} bars to requested {max_bars} bars (using latest data)")
            df = df.iloc[-max_bars:]
        
        logger.info(f"✅ Loaded {len(df)} bars from {cache_file}")
        return df
    except FileNotFoundError as e:
        logger.error(f"❌ Cache not found: {e}")
        logger.info("💡 Ensure CSV files are uploaded to GCS bucket data/ folder")
        return None
    except Exception as e:
        logger.error(f"❌ Failed to load data: {e}")
        return None


def export_results(results, epic, resolution, initial_capital, base_dir='data/backtest_results'):
    """Export to JSON for dashboard with date-based organization"""
    # Create date-based folder structure
    today = datetime.now()
    date_folder = today.strftime('%Y-%m-%d')
    output_dir = os.path.join(base_dir, date_folder)
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate filename with timestamp
    timestamp_str = today.strftime('%H%M%S')
    filename = os.path.join(output_dir, f"{epic}_{resolution}_{timestamp_str}.json")
    
    output = {
        'instrument': epic,
        'timeframe': resolution,
        'timestamp': today.isoformat(),
        'performance': {
            'initial_capital': initial_capital,
            'final_capital': results['final_capital'],
            'total_pnl': results['total_pnl'],
            'total_return_pct': results['return_pct'],
        },
        'trades': {
            'total': results['total_trades'],
            'wins': results['winning_trades'],
            'losses': results['losing_trades'],
            'win_rate': results['win_rate'],
        },
        'pnl': {
            'avg_win': results['avg_win'],
            'avg_loss': results['avg_loss'],
            'profit_factor': results['profit_factor'],
        },
        'risk': {
            'max_drawdown': results['max_drawdown'],
            'max_drawdown_pct': results['max_drawdown_pct'],
            'sharpe_ratio': results['sharpe_ratio'],
        },
        'trades_sample': [
            {
                **trade,
                'entry_time': trade['entry_time'].isoformat() if hasattr(trade.get('entry_time'), 'isoformat') else str(trade.get('entry_time')),
                'exit_time': trade['exit_time'].isoformat() if hasattr(trade.get('exit_time'), 'isoformat') else str(trade.get('exit_time'))
            }
            for trade in results.get('trades', [])[:10]
        ]  # First 10 trades with timestamps converted
    }
    
    with open(filename, 'w') as f:
        json.dump(output, f, indent=2)
    
    # Also create a 'latest' symlink for easy access
    latest_file = os.path.join(base_dir, f"{epic}_{resolution}_latest.json")
    try:
        if os.path.exists(latest_file):
            os.remove(latest_file)
        # Copy instead of symlink for Windows compatibility
        import shutil
        shutil.copy2(filename, latest_file)
        logger.info(f"💾 Exported to {filename}")
        logger.info(f"📌 Latest result: {latest_file}")
    except Exception as e:
        logger.warning(f"Could not create latest file: {e}")
        logger.info(f"💾 Exported to {filename}")
    
    return output, filename


if __name__ == '__main__':
    print("\n" + "="*70)
    print("🎯 Backtest Runner - Using Cached Data Only")
    print("="*70 + "\n")
    
    # Config
    EPIC = 'GOLD'
    RESOLUTION = 'M5'  # 5-minute timeframe
    MAX_BARS = 5000
    INITIAL_CAPITAL = 10000.0
    
    try:
        # Load cached data
        logger.info(f"Loading {EPIC} {RESOLUTION} data from cache...")
        df = load_cached_data(EPIC, RESOLUTION, MAX_BARS)
        
        if df is None:
            sys.exit(1)
        
        logger.info(f"   Date range: {df.index[0]} to {df.index[-1]}")
        logger.info(f"   Duration: {(df.index[-1] - df.index[0]).days} days\n")
        
        # Initialize strategy with optimized parameters
        logger.info("Initializing strategy...")
        strategy = SupertrendVWAPStrategy(
            # Using default optimized parameters:
            # supertrend_multiplier=2.5 (more sensitive)
            # rsi: 35/65 (easier to trigger)
            # bb_std: 1.8 (tighter bands)
            sl_pips=20.0,
            tp_pips=40.0,
            pip_value=0.01  # Gold
        )
        
        # Calculate indicators
        logger.info("Calculating indicators...")
        df_with_indicators = strategy.calculate_indicators(df)
        
        # Generate signals
        logger.info("Generating signals...")
        signals = strategy.generate_signals(df_with_indicators)
        
        buy_signals = (signals['signal'] == 1).sum()
        sell_signals = (signals['signal'] == -1).sum()
        logger.info(f"   Buy signals: {buy_signals}")
        logger.info(f"   Sell signals: {sell_signals}")
        logger.info(f"   Total signals: {buy_signals + sell_signals}\n")
        
        # Configure backtest
        config = BacktestConfig(
            initial_capital=INITIAL_CAPITAL,
            spread_pips=2.0,  # Gold typical
            slippage_pips=0.5,
            pip_value=0.01,
            default_position_size=1.0,
            max_positions=1
        )
        
        # Run backtest (SIMULATION ONLY - NO REAL ORDERS)
        logger.info(f"Running backtest (initial capital: ${INITIAL_CAPITAL:,.2f})...")
        backtester = IntraCandleBacktester(config)
        results = backtester.run(df_with_indicators, signals)
        
        # Display results
        print("\n" + "="*70)
        print("📊 BACKTEST RESULTS")
        print("="*70)
        
        print(f"\n💵 Performance:")
        print(f"   Initial: ${INITIAL_CAPITAL:,.2f}")
        print(f"   Final: ${results['final_capital']:,.2f}")
        print(f"   P&L: ${results['total_pnl']:,.2f} ({results['return_pct']:.2f}%)")
        
        print(f"\n📈 Trades:")
        print(f"   Total: {results['total_trades']}")
        print(f"   Wins: {results['winning_trades']} ({results['win_rate']:.1f}%)")
        print(f"   Losses: {results['losing_trades']}")
        
        print(f"\n📊 Risk:")
        print(f"   Max Drawdown: {results['max_drawdown_pct']:.2f}%")
        print(f"   Sharpe Ratio: {results['sharpe_ratio']:.2f}")
        print(f"   Profit Factor: {results['profit_factor']:.2f}")
        
        # Export for dashboard
        print(f"\n💾 Exporting results...")
        output, result_file = export_results(results, EPIC, RESOLUTION, INITIAL_CAPITAL)
        
        print("\n" + "="*70)
        print("✅ Backtest Complete!")
        print("="*70)
        print(f"\n📄 Results saved to: {result_file}")
        print(f"📌 Latest result: data/backtest_results/{EPIC}_{RESOLUTION}_latest.json")
        print("💡 Use the latest JSON file in your dashboard UI\n")
        
    except Exception as e:
        print(f"\n❌ Error: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
