#!/usr/bin/env python3
"""
🚀 Flexible Trading Bot Launcher

Supports multiple timeframes and instruments.
Usage:
    python3 launch_bot.py --epic GOLD --timeframe M15
    python3 launch_bot.py --epic GOLD --timeframe M5
    python3 launch_bot.py --epic ETHEREUM --timeframe M5
"""

import argparse
import sys
import os
import subprocess
from typing import Dict

# Bot configurations for different timeframes
BOT_CONFIGS: Dict[str, dict] = {
    'M5': {
        'description': '5-minute candles (faster signals, needs 20 bars ~100min)',
        'min_bars': 20,
        'wait_time_hours': 1.7,
        'strategy': {
            'supertrend_period': 7,
            'supertrend_multiplier': 2.0,
            'sma_fast': 10,
            'sma_slow': 21,
            'bb_period': 20,
            'sl_atr_mult': 0.7,
            'tp_atr_mult': 2.5
        }
    },
    'M15': {
        'description': '15-minute candles (proven strategy, needs 60 bars ~15h)',
        'min_bars': 60,
        'wait_time_hours': 15,
        'strategy': {
            'supertrend_period': 7,
            'supertrend_multiplier': 2.0,
            'sma_fast': 21,
            'sma_slow': 50,
            'bb_period': 20,
            'sl_atr_mult': 0.7,
            'tp_atr_mult': 2.5
        }
    }
}

INSTRUMENTS = {
    'GOLD': {'name': 'Gold', 'pip_value': 1.0},
    'ETHEREUM': {'name': 'Ethereum', 'pip_value': 1.0},
    'BITCOIN': {'name': 'Bitcoin', 'pip_value': 1.0},
    'US500': {'name': 'S&P 500', 'pip_value': 1.0},
    'EURUSD': {'name': 'EUR/USD', 'pip_value': 0.0001},
}


def main():
    parser = argparse.ArgumentParser(description='Launch trading bot with specified configuration')
    parser.add_argument('--epic', type=str, default='GOLD', choices=INSTRUMENTS.keys(),
                        help='Instrument to trade (default: GOLD)')
    parser.add_argument('--timeframe', type=str, default='M15', choices=BOT_CONFIGS.keys(),
                        help='Timeframe (default: M15)')
    parser.add_argument('--mode', type=str, default='screen', choices=['screen', 'direct', 'nohup'],
                        help='Launch mode (default: screen)')
    parser.add_argument('--env', type=str, default='demo', choices=['demo', 'live'],
                        help='Trading environment (default: demo)')
    
    args = parser.parse_args()
    
    # Get configuration
    config = BOT_CONFIGS[args.timeframe]
    instrument = INSTRUMENTS[args.epic]
    
    # Print configuration
    print("=" * 80)
    print(f"🤖 TRADING BOT LAUNCHER")
    print("=" * 80)
    print(f"📊 Instrument: {args.epic} ({instrument['name']})")
    print(f"⏰ Timeframe: {args.timeframe} - {config['description']}")
    print(f"📈 Min bars needed: {config['min_bars']} (~{config['wait_time_hours']:.1f} hours)")
    print(f"🌍 Environment: {args.env.upper()}")
    print(f"🚀 Launch mode: {args.mode}")
    print("=" * 80)
    
    # Set environment variables
    env = os.environ.copy()
    env['TRADING_ENVIRONMENT'] = args.env
    env['BOT_EPIC'] = args.epic
    env['BOT_TIMEFRAME'] = args.timeframe
    env['BOT_MIN_BARS'] = str(config['min_bars'])
    
    # Build command
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    if args.timeframe == 'M5':
        bot_script = os.path.join(script_dir, 'trading_bot_m5.py')
    else:  # M15
        bot_script = os.path.join(script_dir, 'trading_bot.py')
    
    # Check if bot script exists
    if not os.path.exists(bot_script):
        print(f"❌ Error: Bot script not found: {bot_script}")
        sys.exit(1)
    
    # Launch based on mode
    if args.mode == 'screen':
        session_name = f"trading_{args.epic}_{args.timeframe}"
        cmd = ['screen', '-dmS', session_name, 'python3', bot_script]
        print(f"\n📺 Starting in Screen session: {session_name}")
        print(f"   Attach with: screen -r {session_name}")
        print(f"   Detach with: Ctrl+A, D")
        
    elif args.mode == 'nohup':
        log_file = f"logs/bot_{args.epic}_{args.timeframe}.log"
        os.makedirs('logs', exist_ok=True)
        cmd = f"nohup python3 {bot_script} > {log_file} 2>&1 &"
        print(f"\n📝 Starting in background, logs: {log_file}")
        print(f"   Monitor with: tail -f {log_file}")
        
    else:  # direct
        cmd = ['python3', bot_script]
        print(f"\n▶️  Starting directly (foreground)")
        print(f"   Stop with: Ctrl+C")
    
    # Execute
    try:
        if args.mode == 'nohup':
            subprocess.run(cmd, shell=True, env=env, check=True)
        else:
            subprocess.run(cmd, env=env, check=True)
        
        print("\n✅ Bot started successfully!")
        
        if args.mode == 'screen':
            print(f"\n💡 Quick commands:")
            print(f"   • Monitor: ./scripts/monitor_bot.sh")
            print(f"   • Attach: screen -r {session_name}")
            print(f"   • Stop: screen -S {session_name} -X quit")
        
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Error starting bot: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n⛔ Launch cancelled")
        sys.exit(0)


if __name__ == '__main__':
    main()
