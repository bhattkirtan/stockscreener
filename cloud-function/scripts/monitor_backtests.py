#!/usr/bin/env python3
"""Monitor running backtest and optimization processes."""

import os
import time
import subprocess
from datetime import datetime


def check_process_running(search_term: str) -> tuple[bool, str]:
    """Check if a process is running.
    
    Args:
        search_term: Process search term
        
    Returns:
        (is_running, details)
    """
    try:
        result = subprocess.run(
            ['ps', 'aux'],
            capture_output=True,
            text=True
        )
        
        for line in result.stdout.split('\n'):
            if search_term in line and 'grep' not in line:
                return True, line.strip()
        
        return False, ""
    
    except Exception as e:
        return False, f"Error: {e}"


def check_file_exists(path: str) -> tuple[bool, str]:
    """Check if output file exists and get size.
    
    Args:
        path: File path
        
    Returns:
        (exists, size_info)
    """
    if os.path.exists(path):
        size_bytes = os.path.getsize(path)
        size_kb = size_bytes / 1024
        size_mb = size_kb / 1024
        
        if size_mb > 1:
            return True, f"{size_mb:.2f} MB"
        else:
            return True, f"{size_kb:.2f} KB"
    
    return False, "not created yet"


def tail_file(path: str, lines: int = 10) -> str:
    """Get last N lines of file.
    
    Args:
        path: File path
        lines: Number of lines
        
    Returns:
        Last lines or error message
    """
    if not os.path.exists(path):
        return "File not found"
    
    try:
        result = subprocess.run(
            ['tail', f'-{lines}', path],
            capture_output=True,
            text=True
        )
        return result.stdout
    except Exception as e:
        return f"Error reading file: {e}"


def main():
    """Main monitoring loop."""
    
    print("=" * 80)
    print("STRATEGY BACKTEST & OPTIMIZATION MONITOR")
    print("=" * 80)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Process names
    zone_process = "backtest_zone_strategy"
    opt_process = "run-local-optimization"
    
    # Output files
    zone_trades_file = "/Users/kirtanbhatt/code/stockScreener/cloud-function/zone_strategy_trades.csv"
    opt_results_dir = "/Users/kirtanbhatt/code/stockScreener/cloud-function/optimization_results"
    
    # Check zone strategy backtest
    print("📊 ZONE STRATEGY BACKTEST")
    print("-" * 80)
    
    zone_running, zone_details = check_process_running(zone_process)
    
    if zone_running:
        print("   Status: 🔄 RUNNING")
        print(f"   Process: {zone_details[:100]}")
    else:
        print("   Status: ⏹️  NOT RUNNING (may be completed or stopped)")
    
    zone_file_exists, zone_size = check_file_exists(zone_trades_file)
    
    if zone_file_exists:
        print(f"   Output: ✅ {zone_trades_file}")
        print(f"   Size: {zone_size}")
        
        # Count trades
        try:
            with open(zone_trades_file, 'r') as f:
                trade_count = len(f.readlines()) - 1  # Minus header
            print(f"   Trades: {trade_count}")
        except:
            pass
    else:
        print(f"   Output: ⏳ {zone_size}")
    
    print()
    
    # Check SuperTrend optimization
    print("🎯 SUPERTREND OPTIMIZATION")
    print("-" * 80)
    
    opt_running, opt_details = check_process_running(opt_process)
    
    if opt_running:
        print("   Status: 🔄 RUNNING")
        print(f"   Process: {opt_details[:100]}")
    else:
        print("   Status: ⏹️  NOT RUNNING")
    
    # Check for results
    if os.path.exists(opt_results_dir):
        files = os.listdir(opt_results_dir)
        csv_files = [f for f in files if f.endswith('.csv')]
        
        if csv_files:
            latest_file = max([os.path.join(opt_results_dir, f) for f in csv_files], 
                            key=os.path.getmtime)
            
            size_info = check_file_exists(latest_file)[1]
            print(f"   Latest: {os.path.basename(latest_file)} ({size_info})")
            
            # Try to get progress
            try:
                with open(latest_file, 'r') as f:
                    lines = f.readlines()
                    if len(lines) > 1:
                        completed = len(lines) - 1  # Minus header
                        print(f"   Progress: {completed} combinations tested")
            except:
                pass
    
    print()
    
    # System info
    print("💻 SYSTEM INFO")
    print("-" * 80)
    
    # CPU usage
    try:
        result = subprocess.run(['top', '-l', '1', '-n', '0'], 
                              capture_output=True, text=True)
        for line in result.stdout.split('\n')[:5]:
            if 'CPU' in line or 'PhysMem' in line:
                print(f"   {line.strip()}")
    except:
        pass
    
    print()
    print("=" * 80)
    print("\nPress Ctrl+C to exit monitor")
    print("\nTo check detailed logs:")
    print(f"  Zone:   No log file (console output only)")
    print(f"  Optimization: Check optimization_results/ directory")
    print()
    print("To stop processes:")
    print(f"  killall -9 python3")
    print()


if __name__ == "__main__":
    main()
