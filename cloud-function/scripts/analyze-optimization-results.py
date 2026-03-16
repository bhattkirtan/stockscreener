#!/usr/bin/env python3
"""
Comprehensive Optimization Results Analyzer
Analyzes trade frequency, profitability, durations, and strategy characteristics.
Includes clustering analysis and out-of-sample validation.

AVAILABLE MODES:
  overview      - Trade distribution + top strategies overview
  trades        - Top strategies by trade count
  returns       - Top strategies by profitability
  balanced      - Strategies with good trades & performance
  duration      - Detailed trade duration analysis for specific strategy
  compare       - Side-by-side comparison of multiple strategies
  intraday      - Analyze intraday feature performance
  top20         - Detailed tabular view of top N strategies
  explain       - Explain duplicate performance groups
  risk          - Risk-adjusted comparison (return/drawdown/Sharpe)
  cluster       - Cluster analysis to find stable parameter regions
  validate      - Out-of-sample validation analysis (train vs test)
  rank1         - Detailed metrics for rank #1 strategy
  overnight     - Analyze overnight trades & prevention potential
  trade-counts  - Comprehensive trade count distribution
  losing-trades - Analyze losing trades from best strategy to identify patterns
  orders        - Analyze losing trades directly from orders.csv file
  hold-time     - Scan ALL strategies, rank by shortest loss/hold duration
  costs         - Spread/slippage costs, order value, leverage & position sizing
  verify        - Re-calculate every trade P&L from raw prices and flag any mismatches

EXAMPLES:
  python analyze-optimization-results.py --mode rank1
  python analyze-optimization-results.py --mode hold-time
  python analyze-optimization-results.py --mode hold-time --date 2026-03-14 --top-n 30
  python analyze-optimization-results.py --mode orders --orders-file data/optimization/2026-03-14/run_XXX/rank01_XXX/orders.csv
"""
import pandas as pd
import numpy as np
import argparse
from pathlib import Path
from datetime import datetime

try:
    from sklearn.cluster import KMeans, DBSCAN
    from sklearn.preprocessing import StandardScaler
    CLUSTERING_AVAILABLE = True
except ImportError:
    CLUSTERING_AVAILABLE = False
    print("⚠️  Warning: sklearn not installed. Clustering analysis disabled.")
    print("   Install with: pip install scikit-learn")

class OptimizationAnalyzer:
    """Unified tool for analyzing optimization results"""
    
    def __init__(self, results_dir: str = "data/optimization"):
        self.results_dir = Path(results_dir)
        self.df = None
        self.csv_file = None
        
    def load_latest_results(self, date: str = None):
        """Load most recent optimization results"""
        if date:
            search_dir = self.results_dir / date
        else:
            # Use latest symlink if available
            latest_dir = self.results_dir / 'latest'
            if latest_dir.exists():
                search_dir = latest_dir
            else:
                # Find most recent date folder
                date_folders = [d for d in self.results_dir.iterdir() if d.is_dir() and d.name != 'latest']
                if not date_folders:
                    print("❌ No optimization results found")
                    return False
                search_dir = max(date_folders, key=lambda x: x.stat().st_mtime)
        
        # Find CSV file (search in subdirectories too)
        csv_files = list(search_dir.glob("**/GOLD_M5_all_strategies*.csv"))
        if not csv_files:
            print(f"❌ No results CSV found in {search_dir}")
            return False
        
        self.csv_file = max(csv_files, key=lambda x: x.stat().st_mtime)
        self.df = pd.read_csv(self.csv_file)
        
        print(f"✅ Loaded: {self.csv_file.name}")
        print(f"   Total strategies: {len(self.df)}")
        print(f"   Location: {search_dir}\n")
        return True
    
    def show_trade_distribution(self):
        """Display distribution of trade counts"""
        print("="*80)
        print("📊 TRADE COUNT DISTRIBUTION")
        print("="*80)
        
        print(f"\n1-2 trades:   {len(self.df[self.df['total_trades'] <= 2]):4d} strategies")
        print(f"3-5 trades:   {len(self.df[(self.df['total_trades'] >= 3) & (self.df['total_trades'] <= 5)]):4d} strategies")
        print(f"6-10 trades:  {len(self.df[(self.df['total_trades'] >= 6) & (self.df['total_trades'] <= 10)]):4d} strategies")
        print(f"11-20 trades: {len(self.df[(self.df['total_trades'] >= 11) & (self.df['total_trades'] <= 20)]):4d} strategies")
        print(f"21-50 trades: {len(self.df[(self.df['total_trades'] >= 21) & (self.df['total_trades'] <= 50)]):4d} strategies")
        print(f"50+ trades:   {len(self.df[self.df['total_trades'] > 50]):4d} strategies")
        
        print(f"\n📈 Statistics:")
        print(f"   Average:  {self.df['total_trades'].mean():.1f} trades")
        print(f"   Median:   {self.df['total_trades'].median():.0f} trades")
        print(f"   Min:      {self.df['total_trades'].min():.0f} trades")
        print(f"   Max:      {self.df['total_trades'].max():.0f} trades")
    
    def show_top_by_trades(self, n: int = 10, min_pf: float = None):
        """Show strategies with most trades"""
        print("\n" + "="*80)
        print(f"📊 TOP {n} STRATEGIES BY TRADE COUNT")
        if min_pf:
            print(f"   (Filtered: Profit Factor >= {min_pf})")
        print("="*80 + "\n")
        
        df_filtered = self.df.copy()
        if min_pf:
            df_filtered = df_filtered[df_filtered['profit_factor'] >= min_pf]
        
        df_sorted = df_filtered.sort_values('total_trades', ascending=False).head(n)
        
        for i, (idx, row) in enumerate(df_sorted.iterrows(), 1):
            status = "✅ PROFITABLE" if row['return_pct'] > 0 else "❌ LOSING"
            print(f"{i:2d}. {row['strategy_name']}")
            print(f"    Trades: {int(row['total_trades'])} | Return: {row['return_pct']:>7.2f}% | "
                  f"PF: {row['profit_factor']:>5.2f} | WinRate: {row['win_rate']:>5.1f}% | {status}")
            print(f"    Sharpe: {row['sharpe_ratio']:>5.2f} | MaxDD: {row['max_drawdown_pct']:>6.2f}% | "
                  f"Signals: {int(row['total_signals'])}")
            print()
    
    def show_top_by_return(self, n: int = 10, min_trades: int = None):
        """Show most profitable strategies"""
        print("\n" + "="*80)
        print(f"💰 TOP {n} STRATEGIES BY RETURN")
        if min_trades:
            print(f"   (Filtered: Minimum {min_trades} trades)")
        print("="*80 + "\n")
        
        df_filtered = self.df.copy()
        if min_trades:
            df_filtered = df_filtered[df_filtered['total_trades'] >= min_trades]
        
        df_sorted = df_filtered.sort_values('return_pct', ascending=False).head(n)
        
        for i, (idx, row) in enumerate(df_sorted.iterrows(), 1):
            print(f"{i:2d}. {row['strategy_name']}")
            print(f"    Return: {row['return_pct']:>7.2f}% | Trades: {int(row['total_trades'])} | "
                  f"PF: {row['profit_factor']:>5.2f} | WinRate: {row['win_rate']:>5.1f}%")
            print(f"    Sharpe: {row['sharpe_ratio']:>5.2f} | MaxDD: {row['max_drawdown_pct']:>6.2f}%")
            print()
    
    def show_balanced_strategies(self, min_trades: int = 10, min_pf: float = 2.0, n: int = 20):
        """Find best balanced strategies: good trades + good performance"""
        print("\n" + "="*80)
        print(f"⚖️  BALANCED STRATEGIES (Trades >= {min_trades}, PF >= {min_pf})")
        print("="*80 + "\n")
        
        df_filtered = self.df[
            (self.df['total_trades'] >= min_trades) & 
            (self.df['profit_factor'] >= min_pf)
        ].sort_values('profit_factor', ascending=False).head(n)
        
        if len(df_filtered) == 0:
            print(f"❌ No strategies found with {min_trades}+ trades and PF >= {min_pf}")
            print(f"\n💡 Try lowering criteria:")
            
            # Show what's available
            for trades in [8, 6, 4]:
                count = len(self.df[(self.df['total_trades'] >= trades) & (self.df['profit_factor'] >= min_pf)])
                if count > 0:
                    print(f"   {trades}+ trades & PF >= {min_pf}: {count} strategies")
            return
        
        print(f"Found {len(df_filtered)} strategies:\n")
        
        for i, (idx, row) in enumerate(df_filtered.iterrows(), 1):
            print(f"{i:2d}. {row['strategy_name']}")
            print(f"    Trades: {int(row['total_trades'])} | Return: {row['return_pct']:>7.2f}% | "
                  f"PF: {row['profit_factor']:>5.2f} | WinRate: {row['win_rate']:>5.1f}%")
            print(f"    TP/SL: {row['tp_sl']} | Sharpe: {row['sharpe_ratio']:>5.2f}")
            print()
    
    def analyze_strategy_durations(self, strategy_name: str):
        """Analyze trade durations for a specific strategy"""
        # Find strategy folder
        date_folder = self.csv_file.parent
        strategy_folders = list(date_folder.glob(f"*{strategy_name}*"))
        
        if not strategy_folders:
            print(f"❌ Strategy folder not found for: {strategy_name}")
            return
        
        strategy_dir = strategy_folders[0]
        orders_file = strategy_dir / "orders.csv"
        
        if not orders_file.exists():
            print(f"❌ No orders.csv found in {strategy_dir}")
            return
        
        df_orders = pd.read_csv(orders_file, parse_dates=['entry_time', 'exit_time'])
        
        print("="*80)
        print(f"⏱️  TRADE DURATION ANALYSIS: {strategy_name}")
        print("="*80)
        
        print(f"\n📋 Summary:")
        print(f"   Total Trades: {len(df_orders)}")
        print(f"   Total P&L: ${df_orders['pnl'].sum():,.2f}")
        print(f"   Win Rate: {100*len(df_orders[df_orders['pnl'] > 0])/len(df_orders):.1f}%\n")
        
        durations_days = []
        intraday_count = 0
        
        print("="*80)
        print("TRADE DETAILS")
        print("="*80)
        
        for i, trade in df_orders.iterrows():
            entry = trade['entry_time']
            exit = trade['exit_time']
            duration = exit - entry
            duration_days = duration.total_seconds() / 86400
            duration_hours = duration.total_seconds() / 3600
            durations_days.append(duration_days)
            
            is_intraday = duration_days < 1
            if is_intraday:
                intraday_count += 1
            
            pnl_symbol = "✅" if trade['pnl'] > 0 else "❌"
            intraday_marker = "✓" if is_intraday else "⚠️"
            
            print(f"\n{pnl_symbol} Trade {i+1}: {trade['side']} @ {trade['entry_price']:.2f} → {trade['exit_price']:.2f}")
            print(f"   {entry.strftime('%b %d %H:%M')} → {exit.strftime('%b %d %H:%M')} ({trade['exit_reason']})")
            print(f"   Duration: {duration_days:.1f}d ({duration_hours:.1f}h) {intraday_marker} | P&L: ${trade['pnl']:,.2f}")
        
        # Summary
        avg_days = sum(durations_days) / len(durations_days)
        min_hours = min(durations_days) * 24
        max_days = max(durations_days)
        
        print("\n" + "="*80)
        print("📊 DURATION SUMMARY")
        print("="*80)
        print(f"\n   Average Hold: {avg_days:.1f} days ({avg_days*24:.1f} hours)")
        print(f"   Shortest: {min_hours:.1f} hours")
        print(f"   Longest: {max_days:.1f} days ({max_days*24:.1f} hours)")
        print(f"   Intraday (< 24h): {intraday_count}/{len(df_orders)} ({100*intraday_count/len(df_orders):.0f}%)")
        
        # Profitability
        pf = abs(df_orders[df_orders['pnl'] > 0]['pnl'].sum() / df_orders[df_orders['pnl'] < 0]['pnl'].sum()) if len(df_orders[df_orders['pnl'] < 0]) > 0 else 999
        print(f"\n   Total P&L: ${df_orders['pnl'].sum():,.2f}")
        print(f"   Profit Factor: {pf:.2f}")
        print(f"   Win Rate: {100*len(df_orders[df_orders['pnl'] > 0])/len(df_orders):.1f}%")
    
    def compare_strategies(self, strategy_names: list):
        """Compare multiple strategies side by side"""
        print("="*80)
        print("🔄 STRATEGY COMPARISON")
        print("="*80 + "\n")
        
        for name in strategy_names:
            row = self.df[self.df['strategy_name'].str.contains(name, case=False)]
            if len(row) == 0:
                print(f"❌ Strategy not found: {name}\n")
                continue
            
            row = row.iloc[0]
            print(f"📊 {row['strategy_name']}")
            print(f"   Return: {row['return_pct']:>7.2f}% | Trades: {int(row['total_trades']):>3d} | "
                  f"PF: {row['profit_factor']:>5.2f} | WR: {row['win_rate']:>5.1f}%")
            print(f"   Sharpe: {row['sharpe_ratio']:>5.2f} | MaxDD: {row['max_drawdown_pct']:>6.2f}% | "
                  f"Signals: {int(row['total_signals'])}")
            print()
    
    def has_intraday_features(self):
        """Check if results include intraday feature columns"""
        required_cols = ['enable_time_exit', 'enable_eod_close', 'enable_eod_blackout', 'enable_partial_exit']
        return all(col in self.df.columns for col in required_cols)
    
    def show_top_strategies(self, top_n: int = 20):
        """Display top N strategies in detailed tabular format"""
        print("\n" + "="*120)
        print(f"🏆 TOP {top_n} STRATEGIES - DETAILED COMPARISON")
        print("="*120)
        print(f"Data Period: {self.csv_file.parent.name} | Initial Capital: $10,000")
        print("="*120)
        
        df_top = self.df.head(top_n)
        
        # Performance table
        print("\n1️⃣  PERFORMANCE METRICS")
        print("-"*120)
        print(f"{'Rank':<5} {'Strategy':<38} {'Return':<10} {'Final $':<12} {'Trades':<8} {'Win%':<8} {'PF':<7} {'Sharpe':<8} {'MaxDD%'}")
        print("-"*120)
        
        for idx, row in df_top.iterrows():
            final_value = 10000 + row['total_pnl']
            strategy_name = row['strategy_name'].replace('rank', 'R').replace('_ST', ' ST').replace('_SMA', ' ').replace('_BB', ' BB').replace('_PIP1_', ' ')
            print(f"{idx+1:<5} {strategy_name:<38} {row['return_pct']:>7.2f}%  ${final_value:>10,.0f}  {int(row['total_trades']):>6}  {row['win_rate']:>6.2f}%  {row['profit_factor']:>6.2f}  {row['sharpe_ratio']:>6.2f}  {row['max_drawdown_pct']:>6.2f}%")
        
        print("-"*120)
        
        # Parameters table (if intraday features exist)
        if self.has_intraday_features():
            print("\n2️⃣  STRATEGY PARAMETERS")
            print("-"*120)
            print(f"{'Rank':<5} {'ST':<7} {'SMA':<10} {'BB':<7} {'TP/SL':<18} {'TimeExit':<12} {'EODClose':<12} {'EODBlock':<12} {'PartExit'}")
            print("-"*120)
            
            for idx, row in df_top.iterrows():
                sma_combo = f"{int(row['sma_fast'])}/{int(row['sma_slow'])}"
                te = 'Yes' if row['enable_time_exit'] else 'No'
                ec = 'Yes' if row['enable_eod_close'] else 'No'
                eb = 'Yes' if row['enable_eod_blackout'] else 'No'
                pe = 'Yes' if row['enable_partial_exit'] else 'No'
                print(f"{idx+1:<5} {row['st_mult']:<7.1f} {sma_combo:<10} {row['bb_std']:<7.1f} {row['tp_sl']:<18} {te:<12} {ec:<12} {eb:<12} {pe}")
            
            print("-"*120)
        
        # Summary statistics
        print("\n3️⃣  SUMMARY STATISTICS")
        print("-"*120)
        print(f"{'Metric':<35} {'Value':<20}    {'Metric':<35} {'Value':<20}")
        print("-"*120)
        print(f"{'Average Return':<35} {df_top['return_pct'].mean():>7.2f}%        {'Average Sharpe Ratio':<35} {df_top['sharpe_ratio'].mean():>7.2f}")
        print(f"{'Median Return':<35} {df_top['return_pct'].median():>7.2f}%        {'Average Win Rate':<35} {df_top['win_rate'].mean():>7.2f}%")
        print(f"{'Best Return':<35} {df_top['return_pct'].max():>7.2f}%        {'Average Trades':<35} {df_top['total_trades'].mean():>7.0f}")
        print(f"{'Average Final Value':<35} ${(10000 + df_top['total_pnl'].mean()):>10,.0f}    {'Average Max Drawdown':<35} {df_top['max_drawdown_pct'].mean():>7.2f}%")
        print("-"*120)
        
        # Feature distribution (if available)
        if self.has_intraday_features():
            print("\n4️⃣  FEATURE DISTRIBUTION IN TOP", top_n)
            print("-"*120)
            print(f"{'Feature':<40} {'Count':<15} {'Percentage':<15}")
            print("-"*120)
            atr_count = (df_top['tp_sl'].str.contains('ATR', na=False)).sum()
            print(f"{'Using ATR (vs Fixed pips)':<40} {atr_count}/{len(df_top):<12} {atr_count/len(df_top)*100:>6.0f}%")
            print(f"{'EOD Blackout Enabled':<40} {df_top['enable_eod_blackout'].sum()}/{len(df_top):<12} {df_top['enable_eod_blackout'].sum()/len(df_top)*100:>6.0f}%")
            print(f"{'Partial Exit Enabled':<40} {df_top['enable_partial_exit'].sum()}/{len(df_top):<12} {df_top['enable_partial_exit'].sum()/len(df_top)*100:>6.0f}%")
            print(f"{'Time Exit Enabled':<40} {df_top['enable_time_exit'].sum()}/{len(df_top):<12} {df_top['enable_time_exit'].sum()/len(df_top)*100:>6.0f}%")
            print(f"{'EOD Close Enabled':<40} {df_top['enable_eod_close'].sum()}/{len(df_top):<12} {df_top['enable_eod_close'].sum()/len(df_top)*100:>6.0f}%")
            print()
            st25_count = (df_top['st_mult'] == 2.5).sum()
            print(f"{'Supertrend 2.5 (vs 3.0)':<40} {st25_count}/{len(df_top):<12} {st25_count/len(df_top)*100:>6.0f}%")
            if 'sma_fast' in df_top.columns and 'sma_slow' in df_top.columns:
                sma_count = ((df_top['sma_fast'] == 15) & (df_top['sma_slow'] == 50)).sum()
                print(f"{'SMA 15/50 combination':<40} {sma_count}/{len(df_top):<12} {sma_count/len(df_top)*100:>6.0f}%")
            print("-"*120)
        
        print(f"\n💾 Full results: {self.csv_file}")
        print("="*120 + "\n")
    
    def explain_duplicates(self, top_n: int = 20):
        """Explain why strategies have identical performance"""
        print("\n" + "="*100)
        print(f"🔍 DUPLICATE PERFORMANCE ANALYSIS - TOP {top_n}")
        print("="*100)
        
        df_top = self.df.head(top_n)
        
        # Show unique performance groups
        unique_returns = sorted(df_top['return_pct'].unique(), reverse=True)
        print(f"\nTotal unique performance levels: {len(unique_returns)} (out of {top_n} strategies)\n")
        
        # Detailed comparison of first duplicate group
        first_return = unique_returns[0]
        first_group = df_top[df_top['return_pct'] == first_return]
        
        if len(first_group) > 1:
            print("Example: First" + f" {len(first_group)} strategies with {first_return:.2f}% return:\n")
            print(f"{'Rank':<6} {'BB':<8} {'PartExit':<10} {'Return':<10} {'Trades':<8} {'Win%':<8}")
            print("-"*70)
            
            for idx, row in first_group.iterrows():
                bb = row.get('bb_std', 'N/A')
                pe = 'Yes' if self.has_intraday_features() and row.get('enable_partial_exit', False) else 'No'
                print(f"{idx+1:<6} {bb:<8} {pe:<10} {row['return_pct']:.2f}%    {int(row['total_trades']):<8} {row['win_rate']:.2f}%")
            
            print("-"*70)
            print("\n💡 KEY INSIGHT:")
            print("   These strategies have IDENTICAL performance because:")
            print("   1. Core indicators are the SAME (ST, SMA, TP/SL strategy)")
            print("   2. Small parameter variations (BB std, Partial Exit) didn't change signals")
            print("   3. They entered and exited the EXACT SAME trades\n")
        
        # Group all by unique performance
        print("="*100)
        print("📊 ALL UNIQUE PERFORMANCE GROUPS:")
        print("="*100 + "\n")
        
        for i, ret in enumerate(unique_returns, 1):
            matching = df_top[df_top['return_pct'] == ret]
            count = len(matching)
            ranks = matching.index.tolist()
            rank_str = f"{ranks[0]+1}-{ranks[-1]+1}" if len(ranks) > 1 else f"{ranks[0]+1}"
            
            sample = matching.iloc[0]
            
            # Build config description
            st = f"ST{sample['st_mult']}"
            sma = f"SMA{int(sample['sma_fast'])}/{int(sample['sma_slow'])}" if 'sma_fast' in sample else 'N/A'
            tp_sl = sample.get('tp_sl', 'N/A')
            
            features = []
            if self.has_intraday_features():
                if sample.get('enable_eod_blackout', False):
                    features.append('EOD Blackout')
                if sample.get('enable_time_exit', False):
                    features.append('Time Exit')
                if sample.get('enable_partial_exit', False):
                    features.append('Partial Exit')
            feature_str = ', '.join(features) if features else 'No features'
            
            print(f"Group {i}: {ret:.2f}% return")
            print(f"   Ranks: {rank_str} ({count} variation{'s' if count > 1 else ''})")
            print(f"   Config: {st}, {sma}, {tp_sl}")
            print(f"   Features: {feature_str}")
            
            # Show key metrics
            print(f"   Metrics: {int(sample['total_trades'])} trades, {sample['win_rate']:.1f}% WR, "
                  f"Sharpe {sample['sharpe_ratio']:.2f}, DD {sample['max_drawdown_pct']:.2f}%\n")
        
        print("="*100)
        print(f"\n✅ CONCLUSION: {len(unique_returns)} truly different strategies, "
              f"but {top_n} parameter variations")
        print("   Small param changes (BB std, Partial Exit) often produce identical results")
        print("   → Focus on the {len(unique_returns)} unique performance groups for decision-making\n")
    
    def compare_risk_adjusted(self, top_n: int = 20):
        """Compare strategies by risk-adjusted metrics"""
        print("\n" + "="*120)
        print(f"⚖️  RISK-ADJUSTED COMPARISON - TOP {top_n} BY RETURN")
        print("="*120 + "\n")
        
        df_top = self.df.head(top_n)
        
        # Sort by different metrics
        by_sharpe = df_top.sort_values('sharpe_ratio', ascending=False).head(5)
        by_drawdown = df_top.sort_values('max_drawdown_pct', ascending=True).head(5)
        by_return = df_top.head(5)
        
        print("🏆 TOP 5 BY ABSOLUTE RETURN:")
        print("-"*120)
        print(f"{'Rank':<5} {'Strategy':<45} {'Return':<10} {'DD%':<8} {'Sharpe':<8} {'Trades'}")
        print("-"*120)
        for idx, row in by_return.iterrows():
            strategy_short = row['strategy_name'].replace('rank', 'R').replace('_ST', ' ST').replace('_SMA', ' ').replace('_BB', ' BB').replace('_PIP1_', ' ')[:43]
            print(f"{idx+1:<5} {strategy_short:<45} {row['return_pct']:>7.2f}%  {row['max_drawdown_pct']:>6.2f}%  {row['sharpe_ratio']:>6.2f}  {int(row['total_trades'])}")
        
        print("\n📉 TOP 5 BY LOWEST DRAWDOWN (Best Risk):")
        print("-"*120)
        print(f"{'Rank':<5} {'Strategy':<45} {'Return':<10} {'DD%':<8} {'Sharpe':<8} {'Trades'}")
        print("-"*120)
        for original_idx in by_drawdown.index:
            row = by_drawdown.loc[original_idx]
            strategy_short = row['strategy_name'].replace('rank', 'R').replace('_ST', ' ST').replace('_SMA', ' ').replace('_BB', ' BB').replace('_PIP1_', ' ')[:43]
            print(f"{original_idx+1:<5} {strategy_short:<45} {row['return_pct']:>7.2f}%  {row['max_drawdown_pct']:>6.2f}%  {row['sharpe_ratio']:>6.2f}  {int(row['total_trades'])}")
        
        print("\n📊 TOP 5 BY SHARPE RATIO (Best Risk-Adjusted):")
        print("-"*120)
        print(f"{'Rank':<5} {'Strategy':<45} {'Return':<10} {'DD%':<8} {'Sharpe':<8} {'Trades'}")
        print("-"*120)
        for original_idx in by_sharpe.index:
            row = by_sharpe.loc[original_idx]
            strategy_short = row['strategy_name'].replace('rank', 'R').replace('_ST', ' ST').replace('_SMA', ' ').replace('_BB', ' BB').replace('_PIP1_', ' ')[:43]
            print(f"{original_idx+1:<5} {strategy_short:<45} {row['return_pct']:>7.2f}%  {row['max_drawdown_pct']:>6.2f}%  {row['sharpe_ratio']:>6.2f}  {int(row['total_trades'])}")
        
        print("\n" + "="*120)
        print("💡 RECOMMENDATION GUIDE:")
        print("-"*120)
        print("  • Maximum Returns: Choose from 'Top by Return' (accept higher drawdown)")
        print("  • Conservative: Choose from 'Lowest Drawdown' (smoother equity curve)")
        print("  • Balanced: Choose from 'Top Sharpe Ratio' (best return per unit risk)")
        print("="*120 + "\n")
    
    def cluster_strategies(self, n_clusters: int = 5, top_n: int = 100):
        """
        Cluster strategies by parameter similarity to identify stable groups.
        Uses KMeans clustering on normalized parameters.
        
        Args:
            n_clusters: Number of clusters to create
            top_n: Only cluster top N strategies (faster, more relevant)
        """
        if not CLUSTERING_AVAILABLE:
            print("❌ Clustering requires scikit-learn")
            print("   Install with: pip install scikit-learn")
            return
        
        print("\n" + "="*100)
        print(f"🔬 STRATEGY CLUSTERING ANALYSIS (Top {top_n} strategies, {n_clusters} clusters)")
        print("="*100)
        print("\n📊 Purpose: Identify stable parameter regions vs isolated peaks")
        print("   - Dense clusters = robust parameter combinations (GOOD)")
        print("   - Isolated strategies = lucky combinations, may not generalize (RISKY)")
        print("="*100)
        
        # Get top N strategies
        df_top = self.df.head(top_n).copy()
        
        # Select numerical parameters for clustering
        param_cols = ['st_mult', 'sma_fast', 'sma_slow', 'bb_std', 'pip_value']
        
        # Extract feature matrix
        X = df_top[param_cols].values
        
        # Standardize features
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        
        # Perform KMeans clustering
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        df_top['cluster'] = kmeans.fit_predict(X_scaled)
        
        # Analyze each cluster
        print(f"\n📦 CLUSTER ANALYSIS:")
        print("-" * 100)
        
        for cluster_id in range(n_clusters):
            cluster_df = df_top[df_top['cluster'] == cluster_id]
            cluster_size = len(cluster_df)

            if cluster_size == 0:
                continue
            
            # Get cluster statistics
            avg_return = cluster_df['return_pct'].mean()
            std_return = cluster_df['return_pct'].std()
            avg_sharpe = cluster_df['sharpe_ratio'].mean()
            avg_dd = cluster_df['max_drawdown_pct'].mean()
            avg_trades = cluster_df['total_trades'].mean()
            
            # Get centroid parameters (closest strategy to cluster center)
            centroid = cluster_df.iloc[0]
            
            print(f"\n🔹 CLUSTER {cluster_id + 1} ({cluster_size} strategies, {cluster_size/top_n*100:.1f}%):")
            print(f"   Performance: {avg_return:.1f}% ± {std_return:.1f}% return | "
                  f"Sharpe: {avg_sharpe:.2f} | DD: {avg_dd:.1f}% | Trades: {avg_trades:.0f}")
            print(f"   Centroid: ST{centroid['st_mult']:.1f} | "
                  f"SMA {int(centroid['sma_fast'])}-{int(centroid['sma_slow'])} | "
                  f"BB{centroid['bb_std']:.1f} | {centroid['tp_sl']}")
            
            # Show best in cluster
            best_in_cluster = cluster_df.nlargest(3, 'return_pct')
            print(f"   Top 3 in cluster:")
            for i, (idx, row) in enumerate(best_in_cluster.iterrows(), 1):
                rank = idx + 1
                print(f"      {i}. Rank #{rank:3d}: {row['return_pct']:6.1f}% | "
                      f"Sharpe {row['sharpe_ratio']:.2f} | DD {row['max_drawdown_pct']:.1f}%")
        
        # Identify best cluster
        cluster_performance = df_top.groupby('cluster').agg({
            'return_pct': ['mean', 'std', 'count'],
            'sharpe_ratio': 'mean',
            'max_drawdown_pct': 'mean'
        })
        
        best_cluster = cluster_performance['return_pct']['mean'].idxmax()
        best_cluster_df = df_top[df_top['cluster'] == best_cluster]
        
        print(f"\n⭐ RECOMMENDED CLUSTER: #{best_cluster + 1}")
        print(f"   - Best-performing group on average")
        print(f"   - Contains {len(best_cluster_df)} strategies")
        print(f"   - Avg performance: {best_cluster_df['return_pct'].mean():.1f}% ± {best_cluster_df['return_pct'].std():.1f}%")
        print(f"   - More reliable than isolated peaks")
        
        print("\n💡 ACTIONABLE INSIGHTS:")
        print(f"   1. Choose from cluster #{best_cluster + 1} (most stable parameter region)")
        print(f"   2. Small clusters (<5% of total) = risky lucky combinations")
        print(f"   3. Large clusters with low std = robust parameter ranges")
        print(f"   4. If rank #1 is in small cluster, consider cluster centroid instead")
        print("=" * 100)
    
    def validate_out_of_sample(self, top_n: int = 20, max_degradation: float = 20.0):
        """
        Analyze out-of-sample validation results.
        Shows train vs test performance and identifies overfitting.
        
        Args:
            top_n: Number of top strategies to analyze
            max_degradation: Flag strategies with degradation > this threshold (%)
        """
        # Check if validation columns exist
        has_validation = 'test_return_pct' in self.df.columns
        
        print("\n" + "="*100)
        print(f"📊 OUT-OF-SAMPLE VALIDATION ANALYSIS")
        print("="*100)
        
        if not has_validation:
            print("\n❌ NO VALIDATION DATA FOUND")
            print("   Your optimization was run without train/test split.")
            print("\n💡 To enable validation:")
            print("   python -m src.optimization.optimize_strategy --validation-split 0.3")
            print("      (0.3 = 30% test set, 70% train set)")
            print("\n   ⚠️  Without validation, you cannot assess overfitting risk!")
            print("=" * 100)
            return
        
        print(f"\n✅ VALIDATION ENABLED - Analyzing top {top_n} strategies")
        print("=" * 100)
        
        # Get top strategies
        df_top = self.df.head(top_n).copy()
        
        # Show detailed metrics for #1 strategy
        if len(df_top) > 0:
            best = df_top.iloc[0]
            
            print(f"\n{'='*100}")
            print(f"🏆 RANK #1 STRATEGY - DETAILED METRICS")
            print(f"{'='*100}")
            print(f"\n📋 Configuration:")
            print(f"   Strategy: {best['tp_sl']}")
            print(f"   SuperTrend: {best['st_mult']:.1f}x multiplier")
            print(f"   SMA: {int(best['sma_fast'])}-{int(best['sma_slow'])}")
            print(f"   Bollinger: {best['bb_std']:.1f} std")
            
            # Training metrics
            train_capital = 10000  # Default initial capital
            train_profit = best['total_pnl']
            train_final = train_capital + train_profit
            train_dd_dollars = train_capital * (best['max_drawdown_pct'] / 100)
            
            print(f"\n📊 TRAINING SET (Conservative Estimate):")
            print(f"   Return:        {best['return_pct']:>8.2f}%")
            print(f"   Profit:        ${train_profit:>10,.2f}")
            print(f"   Final Capital: ${train_final:>10,.2f}")
            print(f"   Max Drawdown:  {best['max_drawdown_pct']:>8.2f}% (${train_dd_dollars:,.2f})")
            print(f"   Sharpe Ratio:  {best['sharpe_ratio']:>8.3f}")
            print(f"   Win Rate:      {best['win_rate']:>8.2f}%")
            print(f"   Profit Factor: {best['profit_factor']:>8.2f}")
            print(f"   Total Trades:  {int(best['total_trades']):>8d}")
            if best['total_trades'] > 0:
                print(f"   Avg Win:       ${best['avg_win']:>10,.2f}")
                print(f"   Avg Loss:      ${best['avg_loss']:>10,.2f}")
            
            # Test metrics
            test_profit = best['test_total_pnl']
            test_final = train_capital + test_profit
            test_dd_dollars = train_capital * (best['test_max_drawdown_pct'] / 100)
            
            print(f"\n📊 TEST SET (Out-of-Sample Performance):")
            print(f"   Return:        {best['test_return_pct']:>8.2f}%")
            print(f"   Profit:        ${test_profit:>10,.2f}")
            print(f"   Final Capital: ${test_final:>10,.2f}")
            print(f"   Max Drawdown:  {best['test_max_drawdown_pct']:>8.2f}% (${test_dd_dollars:,.2f})")
            print(f"   Sharpe Ratio:  {best['test_sharpe_ratio']:>8.3f}")
            print(f"   Win Rate:      {best.get('test_win_rate', 0):>8.2f}%")
            print(f"   Profit Factor: {best.get('test_profit_factor', 0):>8.2f}")
            print(f"   Total Trades:  {int(best['test_total_trades']):>8d}")
            
            # Validation status
            degradation = best['oos_degradation_pct']
            print(f"\n🎯 VALIDATION STATUS:")
            print(f"   OOS Degradation: {degradation:+.2f}%")
            
            if degradation < -50:
                print(f"   ✅ TEST OUTPERFORMED TRAIN significantly!")
                print(f"      → Test period had better market conditions")
                print(f"      → Strategy adapts well to different conditions")
                print(f"      → NOT overfit - can trust for production")
            elif abs(degradation) < 10:
                print(f"   ✅ EXCELLENT - Very consistent train/test performance")
                print(f"      → Strategy is stable and robust")
            elif abs(degradation) < 20:
                print(f"   ✅ GOOD - Acceptable degradation level")
                print(f"      → Strategy generalizes reasonably well")
            else:
                print(f"   ⚠️  WARNING - Significant performance drop on test set")
                print(f"      → May be overfit to training data")
                print(f"      → Use with caution in production")
            
            # Production recommendation
            print(f"\n💼 PRODUCTION RECOMMENDATION:")
            print(f"   Risk/Reward:   {best['return_pct']/best['max_drawdown_pct']:.2f}x (train)")
            print(f"   Expected:      {best['return_pct']:.2f}% return on {best['max_drawdown_pct']:.2f}% max drawdown")
            print(f"   Trade Freq:    ~{int(best['total_trades'])} trades per training period")
            
            if degradation < 0:
                print(f"\n   💡 Conservative Estimate: Use TRAIN metrics ({best['return_pct']:.1f}% return)")
                print(f"   💡 Optimistic Scenario: Test shows potential for {best['test_return_pct']:.1f}% in trending markets")
            else:
                print(f"\n   💡 Use TRAIN metrics for production expectations")
            
            print(f"{'='*100}\n")
        
        # Calculate additional metrics
        df_top['sharpe_degradation'] = df_top.apply(
            lambda row: ((row.get('test_sharpe_ratio', 0) - row['sharpe_ratio']) / abs(row['sharpe_ratio']) * 100) 
            if row['sharpe_ratio'] != 0 else 0,
            axis=1
        )
        
        # Flag overfit strategies (positive degradation = test worse than train)
        df_top['overfit_flag'] = df_top['oos_degradation_pct'] > max_degradation
        overfit_count = df_top['overfit_flag'].sum()
        
        print(f"\n⚠️  OVERFITTING DETECTION:")
        print(f"   Strategies with >{max_degradation}% performance DROP: {overfit_count}/{top_n}")
        print(f"   (Degradation = Test performs worse than Train)")
        
        if overfit_count > 0:
            print(f"\n   🚨 OVERFIT STRATEGIES (avoid for live trading):")
            overfit_df = df_top[df_top['overfit_flag']].nlargest(5, 'oos_degradation_pct')
            for i, (idx, row) in enumerate(overfit_df.iterrows(), 1):
                rank = idx + 1
                print(f"      {i}. Rank #{rank:3d}: Train {row['return_pct']:6.1f}% → Test {row['test_return_pct']:6.1f}% "
                      f"({row['oos_degradation_pct']:+.1f}% degradation = TEST WORSE)")
        else:
            print(f"\n   ✅ NO SIGNIFICANT OVERFITTING DETECTED!")
            print(f"      All top strategies generalize well to test set")
        
        # Show best validated strategies
        print(f"\n✅ BEST VALIDATED STRATEGIES (test performance):")
        print("-" * 100)
        
        # Sort by test performance (actual out-of-sample results)
        df_validated = df_top.sort_values('test_return_pct', ascending=False).head(10)
        
        for i, (idx, row) in enumerate(df_validated.iterrows(), 1):
            rank = idx + 1
            degradation_symbol = "✅" if abs(row['oos_degradation_pct']) < 10 else "⚠️"
            
            print(f"{i:2d}. Rank #{rank:3d} {degradation_symbol}")
            print(f"    TRAIN: {row['return_pct']:6.1f}% | Sharpe {row['sharpe_ratio']:.2f} | "
                  f"DD {row['max_drawdown_pct']:.1f}% | {int(row['total_trades'])} trades")
            print(f"    TEST:  {row['test_return_pct']:6.1f}% | Sharpe {row['test_sharpe_ratio']:.2f} | "
                  f"DD {row['test_max_drawdown_pct']:.1f}% | {int(row['test_total_trades'])} trades")
            print(f"    Degradation: {row['oos_degradation_pct']:+.1f}% return, {row['sharpe_degradation']:+.1f}% Sharpe")
            print(f"    {row['tp_sl']:15s} | ST: {row['st_mult']:.1f} | SMA: {int(row['sma_fast'])}-{int(row['sma_slow'])}")
            print()
        
        # Summary statistics
        avg_degradation = df_top['oos_degradation_pct'].mean()
        median_degradation = df_top['oos_degradation_pct'].median()
        
        print(f"\n📈 VALIDATION SUMMARY:")
        print(f"   Average degradation: {avg_degradation:+.1f}%")
        print(f"   Median degradation: {median_degradation:+.1f}%")
        print(f"   Overfit strategies: {overfit_count}/{top_n} ({overfit_count/top_n*100:.0f}%)")
        
        print("\n💡 INTERPRETATION:")
        if avg_degradation < -20:
            print("   🎯 TEST OUTPERFORMED TRAIN significantly")
            print("      → Test period had better conditions OR strategy adapts well")
            print("      → Not overfit - use TRAIN metrics for conservative estimate")
        elif avg_degradation < 0:
            print("   ✅ TEST BETTER THAN TRAIN - Strategy adapts well!")
            print("      → Not overfit, can trust for production")
        elif avg_degradation < 10:
            print("   ✅ LOW degradation - strategies generalize well")
        elif avg_degradation < 20:
            print("   ⚠️  MODERATE degradation - some overfitting present")
        else:
            print("   🚨 HIGH degradation - significant overfitting detected!")
            print("      Consider: longer data window, fewer parameters, or different grid")
        
        print("\n💡 ACTIONABLE INSIGHTS:")
        print("   1. Sort by TEST performance (not train) for live deployment")
        print("   2. Avoid strategies with >20% degradation")
        print("   3. Prefer strategies with consistent train/test Sharpe ratios")
        print("   4. Low test trade count may indicate the strategy stopped working")
        print("=" * 100)
    
    def show_rank1_detailed(self):
        """Show detailed metrics for rank #1 strategy"""
        if len(self.df) == 0:
            print("❌ No strategies found")
            return
        
        rank1 = self.df.iloc[0]
        has_validation = 'test_return_pct' in self.df.columns
        
        print('=' * 80)
        print('🏆 RANK #1 STRATEGY - COMPLETE METRICS')
        print('=' * 80)
        print()
        print(f'📋 Strategy: {rank1["strategy_name"]}')
        print()
        print('📊 PERFORMANCE:')
        print(f'   Return:        {rank1["return_pct"]:.2f}%')
        print(f'   Profit:        ${rank1["total_pnl"]:.2f}')
        print(f'   Sharpe Ratio:  {rank1["sharpe_ratio"]:.3f}')
        print(f'   Max Drawdown:  {rank1["max_drawdown_pct"]:.2f}%')
        print(f'   Win Rate:      {rank1["win_rate"]:.2f}%')
        print(f'   Profit Factor: {rank1["profit_factor"]:.2f}')
        print(f'   Total Trades:  {int(rank1["total_trades"])}')
        print(f'   Avg Win:       {rank1.get("avg_win", 0):.2f} pips')
        print(f'   Avg Loss:      {rank1.get("avg_loss", 0):.2f} pips')
        
        if has_validation:
            print()
            print('📊 TEST SET (30% of data):')
            print(f'   Return:        {rank1["test_return_pct"]:.2f}%')
            print(f'   Profit:        ${rank1["test_total_pnl"]:.2f}')
            print(f'   Sharpe Ratio:  {rank1["test_sharpe_ratio"]:.3f}')
            print(f'   Max Drawdown:  {rank1["test_max_drawdown_pct"]:.2f}%')
            print(f'   Win Rate:      {rank1.get("test_win_rate", 0):.2f}%')
            print(f'   Profit Factor: {rank1.get("test_profit_factor", 0):.2f}')
            print(f'   Total Trades:  {int(rank1["test_total_trades"])}')
            print()
            print('📈 VALIDATION METRICS:')
            print(f'   Degradation:   {rank1["oos_degradation_pct"]:.2f}%')
            if rank1['oos_degradation_pct'] < 0:
                print('   ✅ TEST OUTPERFORMED TRAIN (negative degradation = good!)')
            else:
                status = "✅ Good" if rank1["oos_degradation_pct"] < 20 else "⚠️ Review"
                print(f'   Status: {status}')
        
        print()
        print('💰 CAPITAL GROWTH:')
        train_capital_final = 10000 + rank1["total_pnl"]
        print(f'   $10,000 → ${train_capital_final:,.2f}  ({rank1["return_pct"]:.1f}%)')
        print()
        print(f'   Risk/Reward Ratio:   {rank1["return_pct"] / rank1["max_drawdown_pct"]:.2f}x')
        print('=' * 80)

        # ── Load orders.csv for exit + holding time analysis ──────────────
        date_folder = self.csv_file.parent
        rank1_name = rank1['strategy_name']
        strategy_folders = list(date_folder.glob(f"*{rank1_name}*"))
        orders_path = None
        if strategy_folders:
            for candidate in ['orders_train.csv', 'orders.csv']:
                p = strategy_folders[0] / candidate
                if p.exists():
                    orders_path = p
                    break

        if orders_path:
            o = pd.read_csv(orders_path)
            o['entry_time'] = pd.to_datetime(o['entry_time'])
            o['exit_time']  = pd.to_datetime(o['exit_time'])
            o['hold_mins']  = (o['exit_time'] - o['entry_time']).dt.total_seconds() / 60
            winners = o[o['pnl'] > 0]
            losers  = o[o['pnl'] < 0]

            print()
            print('⏱️  HOLDING TIME DISTRIBUTION')
            print('-' * 50)
            def fmt(n, total):
                return f"{n:5d}  ({n/total*100:.0f}%)"
            t = len(o)
            print(f"  Mean   : {o['hold_mins'].mean():.0f} min  ({o['hold_mins'].mean()/60:.1f}h)")
            print(f"  Median : {o['hold_mins'].median():.0f} min  ({o['hold_mins'].median()/60:.1f}h)")
            print(f"  <30min : {fmt((o['hold_mins']<30).sum(), t)}")
            print(f"  30-60m : {fmt(((o['hold_mins']>=30)&(o['hold_mins']<60)).sum(), t)}")
            print(f"  1-4h   : {fmt(((o['hold_mins']>=60)&(o['hold_mins']<240)).sum(), t)}")
            print(f"  4-24h  : {fmt(((o['hold_mins']>=240)&(o['hold_mins']<1440)).sum(), t)}")
            print(f"  >24h   : {fmt((o['hold_mins']>=1440).sum(), t)}")
            print()
            print(f"  Winners avg hold : {winners['hold_mins'].mean():.0f} min ({winners['hold_mins'].mean()/60:.1f}h)")
            print(f"  Losers  avg hold : {losers['hold_mins'].mean():.0f} min ({losers['hold_mins'].mean()/60:.1f}h)")

            print()
            print('🚪 EXIT REASON BREAKDOWN')
            print('-' * 50)
            reason_col = 'exit_reason' if 'exit_reason' in o.columns else 'exit_type'
            if reason_col in o.columns:
                for reason, cnt in o[reason_col].value_counts().items():
                    sub = o[o[reason_col] == reason]
                    pct = cnt / t * 100
                    avg_pnl = sub['pnl'].mean()
                    print(f"  {reason:<22} {cnt:5d} ({pct:.0f}%)  avg P&L: {avg_pnl:+.1f} pips")
            print()
            print('🚪 EXIT REASON — WINNERS')
            print('-' * 50)
            if reason_col in winners.columns:
                for reason, cnt in winners[reason_col].value_counts().items():
                    print(f"  {reason:<22} {cnt:5d} ({cnt/len(winners)*100:.0f}%)")
            print()
            print('🚪 EXIT REASON — LOSERS')
            print('-' * 50)
            if reason_col in losers.columns:
                for reason, cnt in losers[reason_col].value_counts().items():
                    print(f"  {reason:<22} {cnt:5d} ({cnt/len(losers)*100:.0f}%)")
        else:
            print("\n⚠️  orders.csv not found — skipping trade-level analysis")
        print('=' * 80)
    
    def analyze_overnight_prevention(self, strategy_name: str = None):
        """Analyze overnight trades and prevention potential"""
        # Find strategy folder
        date_folder = self.csv_file.parent
        
        if strategy_name:
            strategy_folders = list(date_folder.glob(f"*{strategy_name}*"))
            if not strategy_folders:
                print(f"❌ Strategy folder not found for: {strategy_name}")
                return
            strategy_dirs = [strategy_folders[0]]
        else:
            # Use rank #1 strategy
            rank1_name = self.df.iloc[0]['strategy_name']
            strategy_folders = list(date_folder.glob(f"*{rank1_name}*"))
            if not strategy_folders:
                print(f"❌ Strategy folder not found for rank #1: {rank1_name}")
                return
            strategy_dirs = [strategy_folders[0]]
        
        for strategy_dir in strategy_dirs:
            orders_file = strategy_dir / "orders_train.csv"
            if not orders_file.exists():
                orders_file = strategy_dir / "orders.csv"
            
            if not orders_file.exists():
                print(f"❌ No orders file found in {strategy_dir}")
                continue
            
            # Read orders
            df = pd.read_csv(orders_file)
            df['entry_time'] = pd.to_datetime(df['entry_time'])
            df['exit_time'] = pd.to_datetime(df['exit_time'])
            
            # Calculate holding time in hours
            df['holding_hours'] = (df['exit_time'] - df['entry_time']).dt.total_seconds() / 3600
            
            # Check if closed same day
            df['same_day'] = df['entry_time'].dt.date == df['exit_time'].dt.date
            
            # Get overnight trades
            overnight = df[~df['same_day']].copy()
            
            if len(overnight) == 0:
                print(f"\n✅ NO OVERNIGHT TRADES found in {strategy_dir.name}")
                print(f"   All {len(df)} trades closed same day!")
                continue
            
            # Extract time components
            overnight['entry_hour'] = overnight['entry_time'].dt.hour
            overnight['entry_day'] = overnight['entry_time'].dt.day_name()
            overnight['exit_day'] = overnight['exit_time'].dt.day_name()
            
            # Check if weekend-crossing
            overnight['crosses_weekend'] = (
                ((overnight['entry_day'] == 'Friday') & (overnight['exit_day'] != 'Friday')) |
                ((overnight['entry_day'] == 'Saturday') | (overnight['entry_day'] == 'Sunday'))
            )
            
            # Categorize by entry time
            overnight['late_entry'] = overnight['entry_hour'] >= 15  # After 3 PM
            overnight['eod_blackout_zone'] = overnight['entry_hour'] >= 15
            
            # Could features have prevented it?
            overnight['prevented_by_blackout'] = overnight['eod_blackout_zone']
            overnight['prevented_by_eod_close'] = ~overnight['crosses_weekend']
            
            print("\n" + "="*100)
            print(f"🌙 OVERNIGHT TRADE ANALYSIS - {strategy_dir.name}")
            print("="*100)
            print()
            
            print(f"Total Overnight Trades: {len(overnight)}/{len(df)} ({len(overnight)/len(df)*100:.1f}%)")
            print()
            
            print("📅 DAY ANALYSIS:")
            print("-" * 100)
            print(f"Weekend-Crossing Trades:    {overnight['crosses_weekend'].sum():3d} ({overnight['crosses_weekend'].sum()/len(overnight)*100:.1f}%)")
            print(f"Weekday Overnight Trades:   {(~overnight['crosses_weekend']).sum():3d} ({(~overnight['crosses_weekend']).sum()/len(overnight)*100:.1f}%)")
            print()
            
            print("⏰ ENTRY TIME ANALYSIS:")
            print("-" * 100)
            print(f"Late Entries (>= 3 PM):     {overnight['late_entry'].sum():3d} ({overnight['late_entry'].sum()/len(overnight)*100:.1f}%)")
            print(f"Early/Mid-Day Entries:      {(~overnight['late_entry']).sum():3d} ({(~overnight['late_entry']).sum()/len(overnight)*100:.1f}%)")
            print()
            
            print("🛡️ PREVENTION POTENTIAL:")
            print("-" * 100)
            print(f"Preventable by EOD Blackout (no entry after 3 PM): {overnight['prevented_by_blackout'].sum():3d}/{len(overnight)} ({overnight['prevented_by_blackout'].sum()/len(overnight)*100:.1f}%)")
            print(f"Preventable by EOD Close (force close at 4 PM):    {overnight['prevented_by_eod_close'].sum():3d}/{len(overnight)} ({overnight['prevented_by_eod_close'].sum()/len(overnight)*100:.1f}%)")
            print()
            
            print("💡 RECOMMENDATIONS:")
            prevented_pct = overnight['prevented_by_blackout'].sum() / len(overnight) * 100
            if prevented_pct > 50:
                print(f"   ✅ EOD Blackout would prevent {prevented_pct:.0f}% of overnight trades")
            print(f"   ✅ EOD Close feature could prevent {overnight['prevented_by_eod_close'].sum()/len(overnight)*100:.0f}% of weekday overnight trades")
            print("="*100)
    
    def analyze_trade_counts_all(self):
        """Comprehensive trade count analysis across all strategies"""
        print("\n" + "="*80)
        print("📊 COMPREHENSIVE TRADE COUNT ANALYSIS")
        print("="*80 + "\n")
        
        # Distribution
        print("1️⃣  TRADE COUNT DISTRIBUTION:")
        print("-" * 80)
        distribution = [
            ("1-2 trades", self.df['total_trades'] <= 2),
            ("3-5 trades", (self.df['total_trades'] >= 3) & (self.df['total_trades'] <= 5)),
            ("6-10 trades", (self.df['total_trades'] >= 6) & (self.df['total_trades'] <= 10)),
            ("11-20 trades", (self.df['total_trades'] >= 11) & (self.df['total_trades'] <= 20)),
            ("21-50 trades", (self.df['total_trades'] >= 21) & (self.df['total_trades'] <= 50)),
            ("50+ trades", self.df['total_trades'] > 50),
        ]
        
        for label, mask in distribution:
            count = mask.sum()
            pct = count / len(self.df) * 100
            avg_return = self.df[mask]['return_pct'].mean() if count > 0 else 0
            print(f"{label:<15} {count:>5} strategies ({pct:>5.1f}%) | Avg Return: {avg_return:>7.2f}%")
        
        print()
        print("2️⃣  STATISTICS:")
        print("-" * 80)
        print(f"Average:  {self.df['total_trades'].mean():>7.1f} trades")
        print(f"Median:   {self.df['total_trades'].median():>7.0f} trades")
        print(f"Min:      {self.df['total_trades'].min():>7.0f} trades")
        print(f"Max:      {self.df['total_trades'].max():>7.0f} trades")
        print(f"Std Dev:  {self.df['total_trades'].std():>7.1f} trades")
        
        print()
        print("3️⃣  PROFITABILITY BY TRADE COUNT:")
        print("-" * 80)
        for label, mask in distribution:
            subset = self.df[mask]
            if len(subset) > 0:
                profitable = (subset['return_pct'] > 0).sum()
                print(f"{label:<15} {profitable}/{len(subset)} profitable ({profitable/len(subset)*100:>5.1f}%)")
        
        print("="*80)
    
    def analyze_intraday_features(self, top_n: int = 5):
        """Analyze performance by intraday feature combinations"""
        if not self.has_intraday_features():
            print("❌ Results do not contain intraday feature columns")
            print("   Run optimization with --mode intraday to test time-based features\n")
            return
        
        print("="*80)
        print("🕒 INTRADAY FEATURE ANALYSIS")
        print("="*80 + "\n")
        
        # Overall statistics
        print("📊 OVERALL STATISTICS:")
        print("-" * 80)
        print(f"Total Strategies Tested:              {len(self.df):5d}")
        print(f"Baseline (no intraday):               {(~self.df['enable_time_exit'] & ~self.df['enable_eod_close'] & ~self.df['enable_eod_blackout'] & ~self.df['enable_partial_exit']).sum():5d} "
              f"({(~self.df['enable_time_exit'] & ~self.df['enable_eod_close'] & ~self.df['enable_eod_blackout'] & ~self.df['enable_partial_exit']).sum()/len(self.df)*100:.1f}%)")
        print(f"With Time Exit:                       {self.df['enable_time_exit'].sum():5d} ({self.df['enable_time_exit'].sum()/len(self.df)*100:.1f}%)")
        print(f"With EOD Close:                       {self.df['enable_eod_close'].sum():5d} ({self.df['enable_eod_close'].sum()/len(self.df)*100:.1f}%)")
        print(f"With EOD Blackout:                    {self.df['enable_eod_blackout'].sum():5d} ({self.df['enable_eod_blackout'].sum()/len(self.df)*100:.1f}%)")
        print(f"With Partial Exit:                    {self.df['enable_partial_exit'].sum():5d} ({self.df['enable_partial_exit'].sum()/len(self.df)*100:.1f}%)")
        full_intraday = (self.df['enable_eod_blackout'] & self.df['enable_eod_close']).sum()
        print(f"Full Intraday (EOD blackout + close): {full_intraday:5d} ({full_intraday/len(self.df)*100:.1f}%)")
        print()
        
        # Feature combination performance
        print("📈 PERFORMANCE BY FEATURE COMBINATION:")
        print("-" * 80)
        
        scenarios = [
            ('Baseline (all OFF)', 
             ~self.df['enable_time_exit'] & ~self.df['enable_eod_close'] & ~self.df['enable_eod_blackout'] & ~self.df['enable_partial_exit']),
            ('Time Exit ONLY', 
             self.df['enable_time_exit'] & ~self.df['enable_eod_close'] & ~self.df['enable_eod_blackout'] & ~self.df['enable_partial_exit']),
            ('EOD Close ONLY', 
             ~self.df['enable_time_exit'] & self.df['enable_eod_close'] & ~self.df['enable_eod_blackout'] & ~self.df['enable_partial_exit']),
            ('EOD Blackout ONLY', 
             ~self.df['enable_time_exit'] & ~self.df['enable_eod_close'] & self.df['enable_eod_blackout'] & ~self.df['enable_partial_exit']),
            ('Time + EOD Close', 
             self.df['enable_time_exit'] & self.df['enable_eod_close'] & ~self.df['enable_eod_blackout'] & ~self.df['enable_partial_exit']),
            ('Time + Blackout', 
             self.df['enable_time_exit'] & ~self.df['enable_eod_close'] & self.df['enable_eod_blackout'] & ~self.df['enable_partial_exit']),
            ('EOD Close + Blackout', 
             ~self.df['enable_time_exit'] & self.df['enable_eod_close'] & self.df['enable_eod_blackout'] & ~self.df['enable_partial_exit']),
            ('Full Intraday (3 features)', 
             self.df['enable_time_exit'] & self.df['enable_eod_close'] & self.df['enable_eod_blackout'] & ~self.df['enable_partial_exit']),
        ]
        
        for name, mask in scenarios:
            subset = self.df[mask]
            if len(subset) > 0:
                best_return = subset['return_pct'].max()
                avg_return = subset['return_pct'].mean()
                best_sharpe = subset['sharpe_ratio'].max()
                avg_trades = subset['total_trades'].mean()
                print(f"{name:30s} Count:{len(subset):3d}  Best:{best_return:6.2f}%  Avg:{avg_return:6.2f}%  "
                      f"Sharpe:{best_sharpe:5.3f}  Trades:{avg_trades:5.0f}")
            else:
                print(f"{name:30s} No strategies")
        
        print()
        
        # Top strategies by category
        print(f"🏆 TOP {top_n} BY CATEGORY:")
        print("-" * 80)
        
        # Best baseline
        baseline = self.df[~self.df['enable_time_exit'] & ~self.df['enable_eod_close'] & 
                          ~self.df['enable_eod_blackout'] & ~self.df['enable_partial_exit']].head(top_n)
        if len(baseline) > 0:
            print(f"\n🔵 Baseline (No Features) - Top Strategy:")
            row = baseline.iloc[0]
            print(f"   {row['strategy_name']}")
            print(f"   Return: {row['return_pct']:>7.2f}% | Sharpe: {row['sharpe_ratio']:>5.2f} | "
                  f"WR: {row['win_rate']:>5.1f}% | DD: {row['max_drawdown_pct']:>6.2f}% | Trades: {int(row['total_trades'])}")
        
        # Best time exit only
        time_only = self.df[self.df['enable_time_exit'] & ~self.df['enable_eod_close'] & 
                           ~self.df['enable_eod_blackout'] & ~self.df['enable_partial_exit']].head(top_n)
        if len(time_only) > 0:
            print(f"\n🟢 Time Exit Only (4h max) - Top Strategy:")
            row = time_only.iloc[0]
            print(f"   {row['strategy_name']}")
            print(f"   Return: {row['return_pct']:>7.2f}% | Sharpe: {row['sharpe_ratio']:>5.2f} | "
                  f"WR: {row['win_rate']:>5.1f}% | DD: {row['max_drawdown_pct']:>6.2f}% | Trades: {int(row['total_trades'])}")
        
        # Best full intraday
        full_intra = self.df[self.df['enable_eod_blackout'] & self.df['enable_eod_close']].head(top_n)
        if len(full_intra) > 0:
            print(f"\n🟡 Full Intraday (EOD Blackout + Close) - Top Strategy:")
            row = full_intra.iloc[0]
            print(f"   {row['strategy_name']}")
            print(f"   Return: {row['return_pct']:>7.2f}% | Sharpe: {row['sharpe_ratio']:>5.2f} | "
                  f"WR: {row['win_rate']:>5.1f}% | DD: {row['max_drawdown_pct']:>6.2f}% | Trades: {int(row['total_trades'])}")
        
        print()
        
        # Head-to-head comparison
        if len(baseline) > 0 and len(full_intra) > 0:
            print("="*80)
            print("⚖️  HEAD-TO-HEAD: Best Baseline vs Best Full Intraday")
            print("="*80 + "\n")
            
            b_row = baseline.iloc[0]
            f_row = full_intra.iloc[0]
            
            print(f"{'Metric':<25s} {'Baseline':>12s} {'Full Intraday':>15s} {'Difference':>15s}")
            print("-" * 80)
            
            metrics = [
                ('Return %', 'return_pct', '%'),
                ('Sharpe Ratio', 'sharpe_ratio', ''),
                ('Win Rate %', 'win_rate', '%'),
                ('Max Drawdown %', 'max_drawdown_pct', '%'),
                ('Total Trades', 'total_trades', ''),
                ('Profit Factor', 'profit_factor', ''),
            ]
            
            for label, col, suffix in metrics:
                b_val = b_row[col]
                f_val = f_row[col]
                diff = f_val - b_val
                
                if col == 'max_drawdown_pct':
                    indicator = "✅" if diff < 0 else "❌"
                else:
                    indicator = "✅" if diff > 0 else "❌"
                
                print(f"{label:<25s} {b_val:>11.2f}{suffix:1s} {f_val:>14.2f}{suffix:1s} {indicator} {diff:>+13.2f}{suffix:1s}")
            
            print()
            print("💡 INTERPRETATION:")
            print("-" * 80)
            
            return_diff = f_row['return_pct'] - b_row['return_pct']
            
            if return_diff >= -5:
                print(f"✅ Full Intraday trades only {abs(return_diff):.1f}% less for ZERO overnight risk")
                print(f"   → Excellent risk-adjusted choice!")
            elif return_diff >= -15:
                print(f"⚠️  Full Intraday costs {abs(return_diff):.1f}% return but eliminates overnight risk")
                print(f"   → Consider if avoiding gaps is worth {abs(return_diff):.1f}% return")
            else:
                print(f"❌ Full Intraday costs {abs(return_diff):.1f}% return - significant penalty")
                print(f"   → Time Exit ONLY might be better balance")
            
            print()
            print("🎯 RECOMMENDATION:")
            print(f"   Best strategy DEPENDS on your risk tolerance:")
            print(f"   • Maximum returns: Use Baseline ({b_row['return_pct']:.1f}%, ~95% intraday naturally)")
            if len(time_only) > 0:
                print(f"   • Balanced approach: Use Time Exit Only ({time_only.iloc[0]['return_pct']:.1f}%, 4h max hold)")
            print(f"   • Zero overnight risk: Use Full Intraday ({f_row['return_pct']:.1f}%, 99%+ same-day)")
            print()
    
    def analyze_losing_trades(self, strategy_name: str = None, data_file: str = None):
        """Analyze losing trades from best strategy to identify patterns and avoidance strategies"""
        import sys
        sys.path.append('.')
        
        from src.core.strategy import SupertrendVWAPStrategy
        from src.backtesting.backtester import Backtester
        
        print("="*80)
        print("🔍 LOSING TRADES ANALYSIS")
        print("="*80)
        
        # Get strategy to analyze
        if strategy_name:
            strategy_row = self.df[self.df['strategy_name'].str.contains(strategy_name, case=False)]
            if len(strategy_row) == 0:
                print(f"❌ Strategy not found: {strategy_name}")
                return
            strategy_row = strategy_row.iloc[0]
        else:
            # Use best strategy (rank 1)
            strategy_row = self.df.iloc[0]
        
        print(f"\n📊 Analyzing: {strategy_row['strategy_name']}")
        print(f"   Return: {strategy_row['return_pct']:.2f}% | Win Rate: {strategy_row['win_rate']:.1f}% | Trades: {int(strategy_row['total_trades'])}")
        
        # Parse configuration from strategy name
        config = self._parse_strategy_config(strategy_row)
        
        print(f"\n🎯 Configuration:")
        print(f"   SuperTrend: Period={config.get('supertrend_period', 'N/A')}, Mult={config.get('supertrend_multiplier', 'N/A')}")
        print(f"   TP/SL: {config.get('tp_pips', 'N/A')} pips / {config.get('sl_pips', 'N/A')} pips")
        print(f"   Zones: {'ON' if config.get('enable_zone_filter', False) else 'OFF'}")
        print(f"   Events: {'ON' if config.get('enable_event_blocking', False) else 'OFF'}")
        
        # Load data
        if not data_file:
            data_file = 'data/GOLD_M5_3000bars.csv'
        
        print(f"\n📁 Loading data: {data_file}")
        try:
            df = pd.read_csv(data_file)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.sort_values('timestamp').reset_index(drop=True)
            print(f"   ✅ Loaded {len(df)} bars from {df.timestamp.min()} to {df.timestamp.max()}")
        except FileNotFoundError:
            print(f"❌ Data file not found: {data_file}")
            return
        
        # Initialize strategy
        strategy = SupertrendVWAPStrategy(
            supertrend_period=config.get('supertrend_period', 10),
            supertrend_multiplier=config.get('supertrend_multiplier', 1.5),
            sma_fast=config.get('sma_fast', 20),
            sma_slow=config.get('sma_slow', 50)
        )
        
        # Run backtest
        print("\n⚙️  Running backtest...")
        backtester = Backtester(initial_capital=10000)
        results = backtester.run(df, strategy, config)
        
        print("\n" + "="*80)
        print("📈 BACKTEST RESULTS")
        print("="*80)
        print(f"Total Return:     {results['total_return']:.2f}%")
        print(f"Win Rate:         {results['win_rate']:.1f}%")
        print(f"Total Trades:     {results['trades']}")
        print(f"Winners:          {results['winners']}")
        print(f"Losers:           {results['losers']}")
        print(f"Sharpe Ratio:     {results['sharpe']:.2f}")
        print(f"Max Drawdown:     {results['max_dd']:.2f}%")
        print(f"Profit Factor:    {results['profit_factor']:.2f}")
        
        # Analyze trades
        if not results.get('trade_details'):
            print("\n⚠️  No trade details available")
            return
        
        trades_df = pd.DataFrame(results['trade_details'])
        losing_trades = trades_df[trades_df['pnl'] < 0].copy()
        winning_trades = trades_df[trades_df['pnl'] > 0].copy()
        
        print("\n" + "="*80)
        print("📉 LOSING TRADES BREAKDOWN")
        print("="*80)
        print(f"\nTotal Losers:     {len(losing_trades)}")
        print(f"Total Winners:    {len(winning_trades)}")
        
        if len(losing_trades) == 0:
            print("\n🎉 NO LOSING TRADES! Perfect strategy!")
            return
        
        print(f"Avg Loss:         {losing_trades['pnl'].mean():.2f} pips")
        print(f"Max Loss:         {losing_trades['pnl'].min():.2f} pips")
        print(f"Total Loss:       {losing_trades['pnl'].sum():.2f} pips")
        
        if len(winning_trades) > 0:
            print(f"\nAvg Win:          {winning_trades['pnl'].mean():.2f} pips")
            print(f"Max Win:          {winning_trades['pnl'].max():.2f} pips")
            print(f"Total Win:        {winning_trades['pnl'].sum():.2f} pips")
        
        # Detailed losing trade analysis
        print("\n" + "="*80)
        print("🔬 LOSING TRADES DETAIL")
        print("="*80)
        
        for idx, trade in losing_trades.iterrows():
            print(f"\n❌ Trade #{idx+1}:")
            print(f"   Time:          {trade['entry_time']}")
            print(f"   Direction:     {trade['direction'].upper()}")
            print(f"   Entry:         {trade['entry_price']:.2f}")
            print(f"   Exit:          {trade['exit_price']:.2f}")
            print(f"   Exit Type:     {trade['exit_type']}")
            print(f"   P&L:           {trade['pnl']:.2f} pips ({trade['pnl']/abs(trade['pnl']) * 100:.1f}% of SL)")
            print(f"   Duration:      {trade['duration_bars']} bars")
            
            # Calculate adverse move
            if trade['direction'] == 'long':
                adverse_move = trade['entry_price'] - trade['exit_price']
            else:
                adverse_move = trade['exit_price'] - trade['entry_price']
            print(f"   Adverse Move:  {adverse_move:.2f} pips")
        
        # Pattern analysis
        print("\n" + "="*80)
        print("🔍 LOSS PATTERN ANALYSIS")
        print("="*80)
        
        # Exit type distribution
        print(f"\n1️⃣  Exit Type Distribution (Losers):")
        exit_counts = losing_trades['exit_type'].value_counts()
        for exit_type, count in exit_counts.items():
            pct = 100 * count / len(losing_trades)
            avg_loss = losing_trades[losing_trades['exit_type'] == exit_type]['pnl'].mean()
            print(f"   {exit_type:15s}: {count:2d} trades ({pct:5.1f}%) | Avg loss: {avg_loss:.2f} pips")
        
        # Direction bias
        print(f"\n2️⃣  Direction Analysis:")
        long_losers = losing_trades[losing_trades['direction'] == 'long']
        short_losers = losing_trades[losing_trades['direction'] == 'short']
        print(f"   Long losses:   {len(long_losers):2d} trades | Avg: {long_losers['pnl'].mean():.2f} pips" if len(long_losers) > 0 else "   Long losses:    0 trades")
        print(f"   Short losses:  {len(short_losers):2d} trades | Avg: {short_losers['pnl'].mean():.2f} pips" if len(short_losers) > 0 else "   Short losses:   0 trades")
        
        # Duration analysis
        print(f"\n3️⃣  Duration Analysis:")
        print(f"   Avg loss duration:  {losing_trades['duration_bars'].mean():.1f} bars")
        print(f"   Min loss duration:  {losing_trades['duration_bars'].min():.0f} bars")
        print(f"   Max loss duration:  {losing_trades['duration_bars'].max():.0f} bars")
        
        if len(winning_trades) > 0:
            print(f"   Avg win duration:   {winning_trades['duration_bars'].mean():.1f} bars")
            duration_diff = winning_trades['duration_bars'].mean() - losing_trades['duration_bars'].mean()
            print(f"   Duration diff:      {duration_diff:+.1f} bars (winners vs losers)")
        
        # Recommendations
        print("\n" + "="*80)
        print("💡 RECOMMENDATIONS TO AVOID LOSSES")
        print("="*80)
        
        recommendations = []
        
        # Check if all losses are stop losses
        sl_losses = losing_trades[losing_trades['exit_type'] == 'stop_loss']
        if len(sl_losses) == len(losing_trades):
            recommendations.append(("✅ All losses hit stop loss", 
                                   "Stop loss is working correctly. Current SL optimal."))
        elif len(sl_losses) > len(losing_trades) * 0.8:
            recommendations.append(("⚠️  Most losses are stop losses", 
                                   "Consider slightly wider SL or trend filter to avoid whipsaws."))
        
        # Check for reversal exits
        reversal_losses = losing_trades[losing_trades['exit_type'].str.contains('reversal', case=False, na=False)]
        if len(reversal_losses) > 0:
            recommendations.append((f"⚠️  {len(reversal_losses)} reversal exits", 
                                   "SuperTrend reversed while in trade. Consider trend strength filter."))
        
        # Check duration patterns
        if len(losing_trades) > 0 and len(winning_trades) > 0:
            if losing_trades['duration_bars'].mean() < winning_trades['duration_bars'].mean() * 0.5:
                recommendations.append(("💡 Losers exit much faster", 
                                       "Consider minimum hold time filter to avoid noise trades."))
        
        # Check direction bias
        if len(long_losers) > 2 * len(short_losers) or len(short_losers) > 2 * len(long_losers):
            bias = "long" if len(long_losers) > len(short_losers) else "short"
            recommendations.append((f"⚠️  Strong {bias} loss bias", 
                                   f"Consider disabling {bias} trades or adding {bias}-specific filters."))
        
        # Loss size analysis
        avg_loss_pct = abs(losing_trades['pnl'].mean() / config.get('sl_pips', 5) * 100)
        if avg_loss_pct > 90:
            recommendations.append(("✅ Losses close to full SL", 
                                   "Stop loss placement is good. Losses are expected size."))
        elif avg_loss_pct < 50:
            recommendations.append(("💡 Losses smaller than SL", 
                                   "Some early exits preventing larger losses. Consider tighter SL."))
        
        # Print recommendations
        if recommendations:
            for i, (finding, suggestion) in enumerate(recommendations, 1):
                print(f"\n{i}. {finding}")
                print(f"   → {suggestion}")
        else:
            print("\n✅ No obvious patterns detected. Strategy appears well-balanced.")
        
        # Final summary
        print("\n" + "="*80)
        print("📊 SUMMARY")
        print("="*80)
        
        total_loss = abs(losing_trades['pnl'].sum())
        total_win = winning_trades['pnl'].sum() if len(winning_trades) > 0 else 0
        
        print(f"\nIf we eliminated ALL losing trades:")
        print(f"   Current return:     {results['total_return']:.2f}%")
        print(f"   Without losers:     {results['total_return'] + (total_loss / 10000 * 100):.2f}%")
        print(f"   Potential gain:     {total_loss / 10000 * 100:.2f}%")
        print(f"   Win rate would be:  100.0%")
        
        print(f"\n💡 Realistic Goal: Avoid 50% of losing trades")
        half_losses_avoided = total_loss * 0.5 / 10000 * 100
        print(f"   Return improvement:  +{half_losses_avoided:.2f}%")
        print(f"   New estimated return: {results['total_return'] + half_losses_avoided:.2f}%")
        print(f"   New win rate:        {((len(winning_trades) + len(losing_trades) * 0.5) / len(trades_df)) * 100:.1f}%")
        
        print()
    
    def _parse_strategy_config(self, row):
        """Parse strategy configuration from results row"""
        config = {
            'supertrend_period': int(row.get('st_period', 10)),
            'supertrend_multiplier': float(row.get('st_mult', 1.5)),
            'sma_fast': 20,
            'sma_slow': 50,
            'tp_sl_strategy': 'fixed',
            'enable_zone_filter': False,
            'enable_event_blocking': False,
        }
        
        # Parse TP/SL from row
        tp_sl_str = str(row.get('tp_sl', '30.0:5.0'))
        if ':' in tp_sl_str:
            parts = tp_sl_str.split(':')
            config['tp_pips'] = float(parts[0])
            config['sl_pips'] = float(parts[1])
        else:
            config['tp_pips'] = 30.0
            config['sl_pips'] = 5.0
        
        # Check for zone/event features
        if 'enable_zone_filter' in row:
            config['enable_zone_filter'] = bool(row['enable_zone_filter'])
        if 'enable_event_blocking' in row:
            config['enable_event_blocking'] = bool(row['enable_event_blocking'])
        
        return config
    
    def analyze_hold_times(self, date: str = None, top_n: int = 20):
        """Scan ALL strategy orders.csv files and rank by shortest hold time"""
        import pandas as pd
        import os
        
        print("="*80)
        print("⚡ HOLD TIME ANALYSIS - ALL STRATEGIES")
        print("="*80)
        
        # Find run directory
        if date:
            run_parent = self.results_dir / date
        else:
            # Find most recent date folder
            date_folders = [d for d in self.results_dir.iterdir() if d.is_dir() and d.name not in ('latest',) and d.name.startswith('2')]
            if not date_folders:
                print("❌ No optimization results found")
                return
            run_parent = max(date_folders, key=lambda x: x.stat().st_mtime)
        
        # Find run folder inside date folder
        run_folders = [d for d in run_parent.iterdir() if d.is_dir() and d.name.startswith('run_')]
        if not run_folders:
            print(f"❌ No run folder found in {run_parent}")
            return
        run_folder = max(run_folders, key=lambda x: x.stat().st_mtime)
        
        print(f"\n📂 Scanning: {run_folder}\n")
        
        # Find all rank folders with orders.csv
        results = []
        rank_folders = sorted([d for d in run_folder.iterdir() if d.is_dir() and d.name.startswith('rank')])
        
        print(f"🔍 Found {len(rank_folders)} strategy folders...")
        
        for rank_dir in rank_folders:
            orders_file = rank_dir / 'orders.csv'
            if not orders_file.exists():
                continue
            
            try:
                orders = pd.read_csv(orders_file)
                if len(orders) == 0:
                    continue
                
                # Normalize
                orders['entry_time'] = pd.to_datetime(orders['entry_time'])
                orders['exit_time'] = pd.to_datetime(orders['exit_time'])
                orders['duration_bars'] = (orders['exit_time'] - orders['entry_time']).dt.total_seconds() / 300
                
                wins = orders[orders['pnl'] > 0]
                losses = orders[orders['pnl'] < 0]
                
                # Extract rank number and strategy name
                folder_name = rank_dir.name
                rank_num = int(folder_name.split('_')[0].replace('rank', ''))
                strategy_name = '_'.join(folder_name.split('_')[1:])
                
                results.append({
                    'rank': rank_num,
                    'strategy': strategy_name,
                    'total_trades': len(orders),
                    'win_rate': len(wins) / len(orders) * 100,
                    'total_pnl': orders['pnl'].sum(),
                    'avg_duration_bars': orders['duration_bars'].mean(),
                    'avg_duration_hours': orders['duration_bars'].mean() / 12,
                    'avg_win_bars': wins['duration_bars'].mean() if len(wins) > 0 else 0,
                    'avg_win_hours': wins['duration_bars'].mean() / 12 if len(wins) > 0 else 0,
                    'avg_loss_bars': losses['duration_bars'].mean() if len(losses) > 0 else 0,
                    'avg_loss_hours': losses['duration_bars'].mean() / 12 if len(losses) > 0 else 0,
                    'avg_win_pnl': wins['pnl'].mean() if len(wins) > 0 else 0,
                    'avg_loss_pnl': losses['pnl'].mean() if len(losses) > 0 else 0,
                    'n_losses': len(losses),
                    'n_wins': len(wins),
                })
            except Exception as e:
                continue
        
        if not results:
            print("❌ No orders.csv files found or readable")
            return
        
        df_results = pd.DataFrame(results)
        
        # Sort by average loss duration (shortest first)
        df_results = df_results.sort_values('avg_loss_hours')
        
        print(f"\n{'='*80}")
        print(f"🏆 TOP {top_n} STRATEGIES BY SHORTEST LOSS HOLD TIME")
        print(f"{'='*80}")
        print(f"{'Rank':<6} {'Strategy':<45} {'Trades':>6} {'WR%':>6} {'P&L':>10} {'Loss Hold':>10} {'Win Hold':>10} {'AvgLoss':>9}")
        print('-'*80)
        
        for _, row in df_results.head(top_n).iterrows():
            print(f"#{row['rank']:<5} {row['strategy']:<45} {int(row['total_trades']):>6} {row['win_rate']:>5.1f}% {row['total_pnl']:>10.0f} {row['avg_loss_hours']:>8.1f}h  {row['avg_win_hours']:>8.1f}h  {row['avg_loss_pnl']:>9.0f}")
        
        # Also show top by OVERALL shortest hold time
        df_by_overall = df_results.sort_values('avg_duration_hours')
        print(f"\n{'='*80}")
        print(f"⚡ TOP {top_n} BY SHORTEST OVERALL HOLD TIME (ALL TRADES)")
        print(f"{'='*80}")
        print(f"{'Rank':<6} {'Strategy':<45} {'Trades':>6} {'WR%':>6} {'P&L':>10} {'Avg Hold':>9} {'Loss Hold':>9} {'Win Hold':>9}")
        print('-'*80)
        
        for _, row in df_by_overall.head(top_n).iterrows():
            print(f"#{row['rank']:<5} {row['strategy']:<45} {int(row['total_trades']):>6} {row['win_rate']:>5.1f}% {row['total_pnl']:>10.0f} {row['avg_duration_hours']:>7.1f}h  {row['avg_loss_hours']:>7.1f}h  {row['avg_win_hours']:>7.1f}h")

        # Summary stats
        print(f"\n{'='*80}")
        print(f"📊 DISTRIBUTION ACROSS ALL {len(df_results)} STRATEGIES:")
        print(f"{'='*80}")
        print(f"  Loss Hold Time:  Min={df_results['avg_loss_hours'].min():.1f}h  Median={df_results['avg_loss_hours'].median():.1f}h  Max={df_results['avg_loss_hours'].max():.1f}h")
        print(f"  Win Hold Time:   Min={df_results['avg_win_hours'].min():.1f}h  Median={df_results['avg_win_hours'].median():.1f}h  Max={df_results['avg_win_hours'].max():.1f}h")
        print(f"  Overall Hold:    Min={df_results['avg_duration_hours'].min():.1f}h  Median={df_results['avg_duration_hours'].median():.1f}h  Max={df_results['avg_duration_hours'].max():.1f}h")
        
        # Highlight best balanced strategy (short hold + good return)
        print(f"\n{'='*80}")
        print(f"💎 BEST BALANCED: SHORT LOSS HOLD + POSITIVE RETURN")
        print(f"{'='*80}")
        positive = df_results[df_results['total_pnl'] > 0].sort_values('avg_loss_hours')
        print(f"{'Rank':<6} {'Strategy':<45} {'Trades':>6} {'WR%':>6} {'P&L':>10} {'Loss Hold':>10} {'Win Hold':>10}")
        print('-'*80)
        for _, row in positive.head(10).iterrows():
            print(f"#{row['rank']:<5} {row['strategy']:<45} {int(row['total_trades']):>6} {row['win_rate']:>5.1f}% {row['total_pnl']:>10.0f} {row['avg_loss_hours']:>8.1f}h  {row['avg_win_hours']:>8.1f}h")
        print()

    def verify_trades(self):
        """Re-derive every trade P&L from entry/exit prices and flag mismatches vs recorded values."""
        import json

        print("="*80)
        print("🔬 TRADE VERIFICATION — P&L RE-CALCULATION")
        print("="*80)

        if self.csv_file is None:
            print("❌ No results loaded.")
            return

        # Auto-locate rank-1 orders.csv
        rank1_dirs = sorted(self.csv_file.parent.glob("rank01_*"))
        if not rank1_dirs:
            print("❌ rank01 folder not found")
            return
        orders_file = rank1_dirs[0] / "orders.csv"
        summary_file = rank1_dirs[0] / "summary.json"

        df = pd.read_csv(orders_file, parse_dates=["entry_time", "exit_time"])
        with open(summary_file) as f:
            s = json.load(f)
        initial_capital = s["capital"]["initial_capital"]

        print(f"\n📂 Strategy : {rank1_dirs[0].name}")
        print(f"📊 Trades   : {len(df)}")
        print(f"💰 Capital  : ${initial_capital:,.2f}\n")

        # ── Re-derive P&L using same formula as backtester.calculate_pnl() ──────
        def recalc_pnl(row):
            if row['side'].upper() in ('BUY', 'LONG'):
                pts = row['exit_price'] - row['entry_price']
            else:
                pts = row['entry_price'] - row['exit_price']
            pts -= (row['spread_cost'] + row['slippage_cost'])
            return round(pts * row['size'], 8)

        df['pnl_recalc'] = df.apply(recalc_pnl, axis=1)
        df['pnl_diff']   = (df['pnl_recalc'] - df['pnl']).abs()
        TOLERANCE = 1e-4
        mismatches = df[df['pnl_diff'] > TOLERANCE]

        print(f"{'='*60}")
        print("✅ P&L FORMULA VERIFICATION")
        print(f"{'='*60}")
        if mismatches.empty:
            print(f"  All {len(df)} trades match ✅  (tolerance ${TOLERANCE})")
        else:
            print(f"  ❌ {len(mismatches)} mismatches found (threshold ${TOLERANCE}):")
            print(mismatches[['entry_time','side','entry_price','exit_price',
                               'size','spread_cost','slippage_cost',
                               'pnl','pnl_recalc','pnl_diff']].head(10).to_string(index=False))

        # ── SL/TP placement check ─────────────────────────────────────────────
        print(f"\n{'='*60}")
        print("✅ SL / TP PLACEMENT CHECK")
        print(f"{'='*60}")
        sl_valid = df.apply(lambda r:
            (r['side'].upper() in ('BUY','LONG')  and r['stop_loss']  < r['entry_price']) or
            (r['side'].upper() in ('SELL','SHORT') and r['stop_loss']  > r['entry_price']),
            axis=1)
        tp_valid = df.apply(lambda r:
            (r['side'].upper() in ('BUY','LONG')  and r['take_profit'] > r['entry_price']) or
            (r['side'].upper() in ('SELL','SHORT') and r['take_profit'] < r['entry_price']),
            axis=1)
        print(f"  SL correctly placed : {sl_valid.sum():>5}/{len(df)}  ({'✅' if sl_valid.all() else '❌ ' + str((~sl_valid).sum()) + ' wrong'})")
        print(f"  TP correctly placed : {tp_valid.sum():>5}/{len(df)}  ({'✅' if tp_valid.all() else '❌ ' + str((~tp_valid).sum()) + ' wrong'})")

        if not sl_valid.all():
            print("\n  Bad SL examples:")
            print(df[~sl_valid][['entry_time','side','entry_price','stop_loss']].head(5).to_string(index=False))
        if not tp_valid.all():
            print("\n  Bad TP examples:")
            print(df[~tp_valid][['entry_time','side','entry_price','take_profit']].head(5).to_string(index=False))

        # ── Stop-loss distance consistency ───────────────────────────────────
        print(f"\n{'='*60}")
        print("✅ SL / TP DISTANCE CONSISTENCY")
        print(f"{'='*60}")
        df['sl_dist'] = (df['entry_price'] - df['stop_loss']).abs()
        df['tp_dist'] = (df['take_profit'] - df['entry_price']).abs()
        df['rr']      = df['tp_dist'] / df['sl_dist']
        print(f"  SL distance  min/mean/max : {df['sl_dist'].min():.2f} / {df['sl_dist'].mean():.2f} / {df['sl_dist'].max():.2f}")
        print(f"  TP distance  min/mean/max : {df['tp_dist'].min():.2f} / {df['tp_dist'].mean():.2f} / {df['tp_dist'].max():.2f}")
        print(f"  R:R ratio    min/mean/max : {df['rr'].min():.2f} / {df['rr'].mean():.2f} / {df['rr'].max():.2f}")

        # ── Equity curve cross-check ──────────────────────────────────────────
        print(f"\n{'='*60}")
        print("✅ EQUITY CURVE CROSS-CHECK")
        print(f"{'='*60}")
        recalc_final = initial_capital + df['pnl_recalc'].sum()
        recorded_final = s['train']['capital']['final_capital']
        print(f"  Recorded final capital  : ${recorded_final:>12,.2f}")
        print(f"  Re-calculated final cap : ${recalc_final:>12,.2f}")
        diff = abs(recalc_final - recorded_final)
        print(f"  Difference              : ${diff:>12,.6f}  {'✅' if diff < 0.01 else '❌ MISMATCH'}")

        # ── Sample of 5 trades with full math shown ───────────────────────────
        print(f"\n{'='*60}")
        print("🔎 SAMPLE — 5 TRADES WITH FULL MATH")
        print(f"{'='*60}")
        for _, r in df.head(5).iterrows():
            direction = 'LONG' if r['side'].upper() in ('BUY','LONG') else 'SHORT'
            pts = (r['exit_price'] - r['entry_price']) if direction == 'LONG' else (r['entry_price'] - r['exit_price'])
            costs = r['spread_cost'] + r['slippage_cost']
            net_pts = pts - costs
            calc_pnl = net_pts * r['size']
            print(f"  [{r['entry_time']}] {direction}")
            print(f"    Entry={r['entry_price']:.2f}  Exit={r['exit_price']:.2f}  Size={r['size']}")
            print(f"    Price move={pts:+.2f}  Costs={costs:.2f}  Net pts={net_pts:+.2f}")
            print(f"    P&L = {net_pts:+.4f} × {r['size']} = ${calc_pnl:+.2f}  (recorded: ${r['pnl']:+.2f})  {'✅' if abs(calc_pnl - r['pnl']) < TOLERANCE else '❌'}")
            print(f"    SL={r['stop_loss']:.2f}  TP={r['take_profit']:.2f}  Exit: {r['exit_reason']}")
            print()

    def analyze_trade_costs(self, date: str = None):
        """Analyse spread/slippage costs, order value, leverage and position sizing for rank-1 strategy."""
        import json

        print("="*80)
        print("💸 TRADE COST & POSITION SIZING ANALYSIS")
        print("="*80)

        # Find rank-1 orders.csv
        if self.csv_file is None:
            print("❌ No results loaded. Run with --date first.")
            return
        base_dir = self.csv_file.parent

        rank1_dirs = sorted(base_dir.glob("rank01_*"))
        if not rank1_dirs:
            print("❌ Could not find rank01 folder under", base_dir)
            return
        rank1_dir = rank1_dirs[0]
        orders_file = rank1_dir / "orders.csv"
        summary_file = rank1_dir / "summary.json"

        if not orders_file.exists():
            print(f"❌ orders.csv not found: {orders_file}")
            return

        df = pd.read_csv(orders_file, parse_dates=["entry_time", "exit_time"])
        with open(summary_file) as f:
            s = json.load(f)

        initial_capital = s["capital"]["initial_capital"]
        final_capital   = s["train"]["capital"]["final_capital"]
        total_pnl       = s["train"]["capital"]["total_pnl"]
        return_pct      = s["train"]["capital"]["return_pct"]

        # ── Capital summary ───────────────────────────────────────────────────
        print(f"\n{'='*60}")
        print("💰 CAPITAL SUMMARY")
        print(f"{'='*60}")
        print(f"  Initial capital :  ${initial_capital:>12,.2f}")
        print(f"  Final capital   :  ${final_capital:>12,.2f}")
        print(f"  Total P&L       :  ${total_pnl:>12,.2f}")
        print(f"  Return          :  {return_pct:.2f}%")

        # ── Spread / slippage breakdown ───────────────────────────────────────
        print(f"\n{'='*60}")
        print("📊 SPREAD & SLIPPAGE COSTS")
        print(f"{'='*60}")
        spread_per_trade   = df["spread_cost"].unique()
        slippage_per_trade = df["slippage_cost"].unique()
        total_spread   = df["spread_cost"].sum()
        total_slippage = df["slippage_cost"].sum()
        total_costs    = total_spread + total_slippage
        print(f"  Spread per trade  : {spread_per_trade}")
        print(f"  Slippage per trade: {slippage_per_trade}")
        print(f"  Total spread paid : ${total_spread:>10,.2f}")
        print(f"  Total slippage    : ${total_slippage:>10,.2f}")
        print(f"  Total tx costs    : ${total_costs:>10,.2f}")
        print(f"  Costs as % of P&L : {total_costs / abs(total_pnl) * 100:.1f}%  (gross P&L would be ${total_pnl + total_costs:,.2f})")
        print(f"  Cost per trade avg: ${total_costs / len(df):.4f}")

        # ── Order / position sizing ───────────────────────────────────────────
        print(f"\n{'='*60}")
        print("📦 ORDER SIZE & LEVERAGE")
        print(f"{'='*60}")
        lots_values = sorted(df["size"].unique())
        print(f"  Lot sizes used    : {lots_values}")
        print(f"  Order value min   : ${df['order_value_usd'].min():>12,.2f}")
        print(f"  Order value max   : ${df['order_value_usd'].max():>12,.2f}")
        print(f"  Order value mean  : ${df['order_value_usd'].mean():>12,.2f}")

        # Leverage = order_value / running capital
        df = df.copy()
        df["running_capital"] = df["pnl"].cumsum().shift(1).fillna(0) + initial_capital
        df["leverage"] = df["order_value_usd"] / df["running_capital"]
        df["order_pct"]  = df["leverage"] * 100

        print(f"  Avg leverage      : {df['leverage'].mean():.1f}x  (order_value / equity)")
        print(f"  Max leverage      : {df['leverage'].max():.1f}x")
        print(f"  Min leverage      : {df['leverage'].min():.1f}x")
        print(f"  Avg order as % cap: {df['order_pct'].mean():.1f}%")

        # ── First 5 trades walkthrough ────────────────────────────────────────
        print(f"\n{'='*60}")
        print("🔎 FIRST 5 TRADES — FULL BREAKDOWN")
        print(f"{'='*60}")
        cols = ["entry_time", "side", "size", "entry_price", "order_value_usd",
                "running_capital", "leverage", "spread_cost", "slippage_cost", "pnl", "exit_reason"]
        print(df[cols].head(5).to_string(index=False))

        # ── Are costs realistic? ───────────────────────────────────────────────
        print(f"\n{'='*60}")
        print("✅ COST SANITY CHECK")
        print(f"{'='*60}")
        spread_val = df["spread_cost"].iloc[0]
        if spread_val == 0.5:
            print(f"  Spread = $0.50/trade  ✅  (matches Capital.com ~0.5 USD for GOLD M5)")
        elif spread_val < 1.0:
            print(f"  Spread = ${spread_val}/trade  ⚠️  Lower than typical broker — verify")
        else:
            print(f"  Spread = ${spread_val}/trade  ❌  Higher than expected — check spread config")

        gross_pnl = total_pnl + total_costs
        cost_drag = total_costs / gross_pnl * 100 if gross_pnl != 0 else 0
        print(f"  Gross P&L (before costs): ${gross_pnl:,.2f}")
        print(f"  Net   P&L (after costs) : ${total_pnl:,.2f}")
        print(f"  Cost drag on gross P&L  : {cost_drag:.1f}%")
        print()

    def analyze_orders_csv(self, orders_file: str):
        """Analyze losing trades directly from an orders.csv file"""
        import pandas as pd
        
        print("="*80)
        print("🔍 ORDERS FILE ANALYSIS - LOSING TRADES")
        print("="*80)
        
        # Load orders
        print(f"\n📂 Loading: {orders_file}")
        try:
            orders_df = pd.read_csv(orders_file)
        except Exception as e:
            print(f"❌ Failed to load orders file: {e}")
            return
        
        # Parse timestamp if available
        if 'entry_time' in orders_df.columns:
            orders_df['entry_time'] = pd.to_datetime(orders_df['entry_time'])
        if 'exit_time' in orders_df.columns:
            orders_df['exit_time'] = pd.to_datetime(orders_df['exit_time'])
        
        # Normalize side/direction column
        if 'side' in orders_df.columns:
            orders_df['direction'] = orders_df['side'].str.lower().replace({'buy': 'long', 'sell': 'short'})
        elif 'direction' not in orders_df.columns:
            orders_df['direction'] = 'unknown'
        
        # Normalize exit_reason/exit_type column
        if 'exit_reason' in orders_df.columns and 'exit_type' not in orders_df.columns:
            orders_df['exit_type'] = orders_df['exit_reason']
        
        # Calculate duration_bars if not present (approximate based on time difference, assume 5-minute bars)
        if 'duration_bars' not in orders_df.columns and 'entry_time' in orders_df.columns and 'exit_time' in orders_df.columns:
            orders_df['duration_bars'] = (orders_df['exit_time'] - orders_df['entry_time']).dt.total_seconds() / 300  # 5 min = 300 sec
        
        print(f"✅ Loaded {len(orders_df)} orders\n")
        
        # Calculate metrics
        wins = orders_df[orders_df['pnl'] > 0]
        losses = orders_df[orders_df['pnl'] < 0]
        breakeven = orders_df[orders_df['pnl'] == 0]
        
        total_pnl = orders_df['pnl'].sum()
        win_rate = len(wins) / len(orders_df) * 100 if len(orders_df) > 0 else 0
        avg_win = wins['pnl'].mean() if len(wins) > 0 else 0
        avg_loss = losses['pnl'].mean() if len(losses) > 0 else 0
        
        # Overall statistics
        print("📊 OVERALL STATISTICS")
        print("="*80)
        print(f"Total Trades:        {len(orders_df)}")
        print(f"Winning Trades:      {len(wins)} ({len(wins)/len(orders_df)*100:.1f}%)")
        print(f"Losing Trades:       {len(losses)} ({len(losses)/len(orders_df)*100:.1f}%)")
        print(f"Breakeven Trades:    {len(breakeven)} ({len(breakeven)/len(orders_df)*100:.1f}%)")
        print(f"\nTotal P&L:           {total_pnl:.2f} pips")
        print(f"Win Rate:            {win_rate:.1f}%")
        print(f"Average Win:         {avg_win:.2f} pips")
        print(f"Average Loss:        {avg_loss:.2f} pips")
        if avg_loss != 0:
            print(f"Win/Loss Ratio:      {abs(avg_win/avg_loss):.2f}:1")
        
        # Analyze losing trades
        if len(losses) == 0:
            print("\n✅ No losing trades found! Perfect strategy!")
            return
        
        print(f"\n\n{'='*80}")
        print(f"❌ DETAILED LOSING TRADES ANALYSIS ({len(losses)} trades)")
        print("="*80)
        
        # Individual losing trades
        print(f"\n📋 All Losing Trades:")
        print("-"*80)
        for idx, trade in losses.iterrows():
            print(f"\nTrade #{idx + 1}:")
            if 'entry_time' in trade:
                print(f"   Entry:  {trade['entry_time']} @ {trade['entry_price']:.2f} ({trade['direction'].upper()})")
            else:
                print(f"   Entry:  {trade['entry_price']:.2f} ({trade['direction'].upper()})")
            if 'exit_time' in trade:
                print(f"   Exit:   {trade['exit_time']} @ {trade['exit_price']:.2f}")
            else:
                print(f"   Exit:   {trade['exit_price']:.2f}")
            print(f"   P&L:    {trade['pnl']:.2f} pips")
            print(f"   Type:   {trade.get('exit_type', 'unknown')}")
            if 'duration_bars' in trade:
                print(f"   Duration: {trade['duration_bars']} bars")
        
        # Pattern analysis
        print(f"\n\n{'='*80}")
        print("🔍 LOSS PATTERN ANALYSIS")
        print("="*80)
        
        # 1. Exit type distribution
        if 'exit_type' in losses.columns:
            print(f"\n1️⃣  Exit Type Distribution:")
            exit_counts = losses['exit_type'].value_counts()
            for exit_type, count in exit_counts.items():
                pct = 100 * count / len(losses)
                type_losses = losses[losses['exit_type'] == exit_type]
                avg_loss_type = type_losses['pnl'].mean()
                total_impact = type_losses['pnl'].sum()
                print(f"   {exit_type:20s}: {count:2d} trades ({pct:5.1f}%) | Avg: {avg_loss_type:7.2f} pips | Total: {total_impact:7.2f} pips")
        
        # 2. Direction analysis
        print(f"\n2️⃣  Direction Analysis:")
        long_losses = losses[losses['direction'] == 'long']
        short_losses = losses[losses['direction'] == 'short']
        
        if len(long_losses) > 0:
            print(f"   LONG losses:   {len(long_losses):2d} trades | Avg: {long_losses['pnl'].mean():7.2f} pips | Total: {long_losses['pnl'].sum():7.2f} pips")
        else:
            print(f"   LONG losses:    0 trades")
        
        if len(short_losses) > 0:
            print(f"   SHORT losses:  {len(short_losses):2d} trades | Avg: {short_losses['pnl'].mean():7.2f} pips | Total: {short_losses['pnl'].sum():7.2f} pips")
        else:
            print(f"   SHORT losses:   0 trades")
        
        # 3. Duration analysis
        if 'duration_bars' in losses.columns:
            print(f"\n3️⃣  Duration Analysis:")
            print(f"   Avg loss duration:  {losses['duration_bars'].mean():.1f} bars")
            print(f"   Min loss duration:  {losses['duration_bars'].min():.0f} bars")
            print(f"   Max loss duration:  {losses['duration_bars'].max():.0f} bars")
            
            if len(wins) > 0 and 'duration_bars' in wins.columns:
                print(f"   Avg win duration:   {wins['duration_bars'].mean():.1f} bars")
                duration_diff = wins['duration_bars'].mean() - losses['duration_bars'].mean()
                print(f"   Duration diff:      {duration_diff:+.1f} bars (wins vs losses)")
        
        # 4. Time pattern analysis
        if 'entry_time' in losses.columns:
            print(f"\n4️⃣  Time Pattern Analysis:")
            losses['hour'] = losses['entry_time'].dt.hour
            hour_counts = losses['hour'].value_counts().sort_index()
            print(f"   Losses by hour:")
            for hour, count in hour_counts.items():
                pct = count / len(losses) * 100
                print(f"      {hour:02d}:00 - {count} trades ({pct:.1f}%)")
        
        # Recommendations
        print(f"\n\n{'='*80}")
        print("💡 RECOMMENDATIONS TO AVOID LOSSES")
        print("="*80)
        
        recommendations = []
        
        # Exit type recommendations
        if 'exit_type' in losses.columns:
            stop_loss_exits = losses[losses['exit_type'] == 'stop_loss']
            reversal_exits = losses[losses['exit_type'] == 'reversal']
            
            if len(stop_loss_exits) > len(losses) * 0.7:
                recommendations.append((
                    "⚠️  70%+ losses from stop_loss hits",
                    "Consider: 1) Wider stop loss, 2) Better entry timing, 3) Trend filter"
                ))
            
            if len(reversal_exits) > len(losses) * 0.5:
                recommendations.append((
                    "💡 50%+ losses from reversals",
                    "Consider: 1) Trailing stops, 2) Partial profit taking, 3) Momentum filter"
                ))
        
        # Direction bias recommendations
        if len(long_losses) > 2 * len(short_losses):
            recommendations.append((
                f"⚠️  Strong LONG bias in losses ({len(long_losses)} long vs {len(short_losses)} short)",
                "Consider: 1) Disable long trades temporarily, 2) Add long-specific filters, 3) Check for uptrend bias"
            ))
        elif len(short_losses) > 2 * len(long_losses):
            recommendations.append((
                f"⚠️  Strong SHORT bias in losses ({len(short_losses)} short vs {len(long_losses)} long)",
                "Consider: 1) Disable short trades temporarily, 2) Add short-specific filters, 3) Check for downtrend bias"
            ))
        
        # Duration recommendations
        if 'duration_bars' in losses.columns and len(wins) > 0 and 'duration_bars' in wins.columns:
            if losses['duration_bars'].mean() < wins['duration_bars'].mean() * 0.5:
                recommendations.append((
                    "💡 Losers exit much faster than winners",
                    "Consider: Minimum hold time filter to avoid noise/whipsaw trades"
                ))
            elif losses['duration_bars'].mean() > wins['duration_bars'].mean() * 1.5:
                recommendations.append((
                    "⚠️  Losers hold longer than winners",
                    "Consider: Earlier exit signals or time-based stops"
                ))
        
        # Time pattern recommendations
        if 'entry_time' in losses.columns and len(losses) >= 3:
            worst_hours = losses['hour'].value_counts().head(2)
            for hour, count in worst_hours.items():
                if count >= len(losses) * 0.3:  # 30%+ of losses in one hour
                    recommendations.append((
                        f"🕐 {count} losses ({count/len(losses)*100:.0f}%) occur at {hour:02d}:00 hour",
                        f"Consider: Blacklist trading during {hour:02d}:00-{hour+1:02d}:00 window"
                    ))
        
        # Print recommendations
        if recommendations:
            for i, (finding, suggestion) in enumerate(recommendations, 1):
                print(f"\n{i}. {finding}")
                print(f"   → {suggestion}")
        else:
            print("\n✅ No obvious patterns detected. Strategy appears well-balanced.")
        
        # Impact analysis
        print(f"\n\n{'='*80}")
        print("📊 IMPACT ANALYSIS")
        print("="*80)
        
        total_loss_pips = abs(losses['pnl'].sum())
        current_pnl = total_pnl
        
        print(f"\n💰 If we eliminated ALL losing trades:")
        print(f"   Current P&L:        {current_pnl:.2f} pips")
        print(f"   Without losers:     {current_pnl + total_loss_pips:.2f} pips")
        print(f"   Potential gain:     +{total_loss_pips:.2f} pips")
        print(f"   Win rate would be:  100.0%")
        
        print(f"\n🎯 Realistic Goal: Avoid 50% of losing trades")
        half_avoided = total_loss_pips * 0.5
        new_pnl = current_pnl + half_avoided
        new_win_rate = (len(wins) + len(losses) * 0.5) / len(orders_df) * 100
        print(f"   P&L improvement:    +{half_avoided:.2f} pips")
        print(f"   New estimated P&L:  {new_pnl:.2f} pips")
        print(f"   New win rate:       {new_win_rate:.1f}%")
        
        print()


def main():
    parser = argparse.ArgumentParser(description='Comprehensive Optimization Results Analysis')
    parser.add_argument('--date', help='Optimization date folder (e.g., 2026-03-05)')
    parser.add_argument('--mode', default='overview', 
                       choices=['overview', 'trades', 'returns', 'balanced', 'duration', 'compare', 
                               'intraday', 'top20', 'explain', 'risk', 'cluster', 'validate',
                               'rank1', 'overnight', 'trade-counts', 'losing-trades', 'orders', 'hold-time', 'costs', 'verify'],
                       help='Analysis mode')
    parser.add_argument('--min-trades', type=int, help='Minimum trades filter')
    parser.add_argument('--min-pf', type=float, help='Minimum profit factor filter')
    parser.add_argument('--top-n', type=int, default=10, help='Number of top results to show')
    parser.add_argument('--strategy', help='Strategy name for duration/overnight/losing-trades analysis')
    parser.add_argument('--strategies', nargs='+', help='Multiple strategies for comparison')
    parser.add_argument('--n-clusters', type=int, default=5, help='Number of clusters for clustering analysis')
    parser.add_argument('--data-file', help='Data file for losing-trades analysis (default: data/GOLD_M5_3000bars.csv)')
    parser.add_argument('--orders-file', help='Path to orders.csv file for orders mode analysis')
    
    args = parser.parse_args()
    
    print("\n" + "="*80)
    print("📊 OPTIMIZATION RESULTS ANALYZER")
    print("="*80 + "\n")
    
    # Handle orders mode separately (doesn't need optimization results)
    if args.mode == 'orders':
        if not args.orders_file:
            print("❌ Error: --orders-file is required for 'orders' mode")
            print("   Example: python analyze-optimization-results.py --mode orders --orders-file data/optimization/2026-03-14/run_XXX/rank01_XXX/orders.csv")
            sys.exit(1)
        analyzer = OptimizationAnalyzer()
        analyzer.analyze_orders_csv(args.orders_file)
        print("\n" + "="*80)
        print("✅ ANALYSIS COMPLETE")
        print("="*80 + "\n")
        return
    
    # For all other modes, load optimization results
    analyzer = OptimizationAnalyzer()
    
    if not analyzer.load_latest_results(args.date):
        return
    
    # Execute requested analysis
    if args.mode == 'overview':
        analyzer.show_trade_distribution()
        analyzer.show_top_by_return(args.top_n, min_trades=3)
        analyzer.show_top_by_trades(args.top_n, min_pf=1.0)
    
    elif args.mode == 'trades':
        analyzer.show_top_by_trades(args.top_n, min_pf=args.min_pf)
    
    elif args.mode == 'returns':
        analyzer.show_top_by_return(args.top_n, min_trades=args.min_trades)
    
    elif args.mode == 'balanced':
        min_trades = args.min_trades or 10
        min_pf = args.min_pf or 2.0
        analyzer.show_balanced_strategies(min_trades, min_pf, args.top_n)
    
    elif args.mode == 'duration':
        if not args.strategy:
            print("❌ --strategy required for duration analysis")
            return
        analyzer.analyze_strategy_durations(args.strategy)
    
    elif args.mode == 'compare':
        if not args.strategies:
            print("❌ --strategies required for comparison")
            return
        analyzer.compare_strategies(args.strategies)
    
    elif args.mode == 'intraday':
        analyzer.analyze_intraday_features(args.top_n)
    
    elif args.mode == 'top20':
        analyzer.show_top_strategies(args.top_n)
    
    elif args.mode == 'explain':
        analyzer.explain_duplicates(args.top_n)
    
    elif args.mode == 'risk':
        analyzer.compare_risk_adjusted(args.top_n)
    
    elif args.mode == 'cluster':
        analyzer.cluster_strategies(n_clusters=args.n_clusters, top_n=args.top_n)
    
    elif args.mode == 'validate':
        analyzer.validate_out_of_sample(top_n=args.top_n)
    
    elif args.mode == 'rank1':
        analyzer.show_rank1_detailed()
    
    elif args.mode == 'overnight':
        analyzer.analyze_overnight_prevention(strategy_name=args.strategy)
    
    elif args.mode == 'trade-counts':
        analyzer.analyze_trade_counts_all()
    
    elif args.mode == 'losing-trades':
        analyzer.analyze_losing_trades(strategy_name=args.strategy, data_file=args.data_file)
    
    elif args.mode == 'hold-time':
        analyzer.analyze_hold_times(date=args.date, top_n=args.top_n)

    elif args.mode == 'costs':
        analyzer.analyze_trade_costs(date=args.date)

    elif args.mode == 'verify':
        analyzer.verify_trades()

    print("\n" + "="*80)
    print("✅ ANALYSIS COMPLETE")
    print("="*80 + "\n")


if __name__ == '__main__':
    main()
