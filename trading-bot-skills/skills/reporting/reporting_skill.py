"""
Reporting Skill - Generates performance analytics and reports

Creates detailed performance reports from backtest or live trading results.
Includes metrics, trade statistics, and visualization data.
"""

import sys
import os
from pathlib import Path
# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional
import json

from skills.base_skill import Skill, Context


class ReportingSkill(Skill):
    """
    Reporting Skill - Generates performance analytics and reports
    
    Features:
    - Performance summary (P&L, win rate, Sharpe ratio)
    - Trade statistics (avg win, avg loss, profit factor)
    - Equity curve data for charting
    - Drawdown analysis
    - Trade distribution analysis
    - Export to JSON, CSV, HTML
    
    Example Usage:
        # After running backtest
        config = {'reporting': {'output_dir': 'reports/'}}
        reporting = ReportingSkill(config)
        
        # Generate report from backtest results
        context.backtest_results = backtest_skill.get_results()
        report = reporting.execute(context)
        
        # Save report
        reporting.save_report(report, 'GOLD_M5_report')
    """
    
    def __init__(self, config: dict):
        super().__init__(config)
        
        # Reporting configuration
        report_config = config.get('reporting', {})
        self.output_dir = report_config.get('output_dir', 'reports/')
        
        # Create output directory
        os.makedirs(self.output_dir, exist_ok=True)
        
        print(f"📊 Reporting Skill initialized")
        print(f"   Output Directory: {self.output_dir}")
    
    def validate_config(self) -> bool:
        """Validate reporting configuration"""
        return True
    
    def execute(self, context: Context) -> Dict:
        """
        Generate performance report from trading results.
        
        Args:
            context: Trading context with backtest_results or live metrics
        
        Returns:
            Dictionary with comprehensive performance report
        """
        # Get results from context (could be backtest or live trading)
        results = getattr(context, 'backtest_results', None)
        
        if not results:
            # No results available, create empty report
            return self._create_empty_report()
        
        # Generate comprehensive report
        report = {
            'timestamp': datetime.now().isoformat(),
            'summary': self._generate_summary(results),
            'statistics': self._generate_statistics(results),
            'equity_curve': self._generate_equity_curve(results),
            'drawdown_analysis': self._analyze_drawdown(results),
            'trade_distribution': self._analyze_trade_distribution(results),
            'monthly_performance': self._analyze_monthly_performance(results)
        }
        
        return report
    
    def _create_empty_report(self) -> Dict:
        """Create empty report structure"""
        return {
            'timestamp': datetime.now().isoformat(),
            'summary': {},
            'statistics': {},
            'equity_curve': [],
            'drawdown_analysis': {},
            'trade_distribution': {},
            'monthly_performance': []
        }
    
    def _generate_summary(self, results: Dict) -> Dict:
        """Generate performance summary"""
        return {
            'initial_capital': results.get('initial_capital', 0),
            'final_capital': results.get('final_capital', 0),
            'total_pnl': results.get('total_pnl', 0),
            'total_return_pct': results.get('total_return_pct', 0),
            'avg_margin_per_trade': results.get('avg_margin_per_trade', 0),
            'return_on_margin_pct': results.get('return_on_margin_pct', 0),
            'total_trades': results.get('total_trades', 0),
            'win_rate': results.get('win_rate', 0),
            'sharpe_ratio': results.get('sharpe_ratio', 0),
            'profit_factor': results.get('profit_factor', 0),
            'max_drawdown': results.get('max_drawdown', 0),
            'max_drawdown_pct': results.get('max_drawdown_pct', 0),
            'expectancy_per_trade': results.get('expectancy_per_trade', 0)
        }
    
    def _generate_statistics(self, results: Dict) -> Dict:
        """Generate detailed statistics"""
        trades = results.get('trades', [])
        
        if not trades:
            return {}
        
        # Convert to DataFrame for easier analysis
        df = pd.DataFrame(trades)
        
        # Calculate statistics
        wins = df[df['pnl'] > 0]
        losses = df[df['pnl'] < 0]
        
        stats = {
            'winning_trades': len(wins),
            'losing_trades': len(losses),
            'avg_win': wins['pnl'].mean() if len(wins) > 0 else 0,
            'avg_loss': losses['pnl'].mean() if len(losses) > 0 else 0,
            'max_win': wins['pnl'].max() if len(wins) > 0 else 0,
            'max_loss': losses['pnl'].min() if len(losses) > 0 else 0,
            'avg_win_pct': wins['pnl_pct'].mean() if len(wins) > 0 else 0,
            'avg_loss_pct': losses['pnl_pct'].mean() if len(losses) > 0 else 0,
            'largest_win_streak': self._calculate_max_streak(df, True),
            'longest_loss_streak': self._calculate_max_streak(df, False),
            'avg_trade_duration': self._calculate_avg_duration(df)
        }
        
        return stats
    
    def _calculate_max_streak(self, df: pd.DataFrame, winning: bool) -> int:
        """Calculate maximum winning or losing streak"""
        if df.empty:
            return 0
        
        streak = 0
        max_streak = 0
        
        for pnl in df['pnl']:
            if (winning and pnl > 0) or (not winning and pnl < 0):
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0
        
        return max_streak
    
    def _calculate_avg_duration(self, df: pd.DataFrame) -> float:
        """Calculate average trade duration in hours"""
        if df.empty or 'entry_time' not in df.columns or 'exit_time' not in df.columns:
            return 0
        
        df['entry_time'] = pd.to_datetime(df['entry_time'])
        df['exit_time'] = pd.to_datetime(df['exit_time'])
        df['duration'] = (df['exit_time'] - df['entry_time']).dt.total_seconds() / 3600
        
        return df['duration'].mean()
    
    def _generate_equity_curve(self, results: Dict) -> List[Dict]:
        """Generate equity curve data for charting"""
        trades = results.get('trades', [])
        
        if not trades:
            return []
        
        initial_capital = results.get('initial_capital', 10000)
        equity = initial_capital
        equity_curve = [{'timestamp': None, 'equity': initial_capital}]
        
        for trade in trades:
            equity += trade.get('pnl', 0)
            equity_curve.append({
                'timestamp': trade.get('exit_time'),
                'equity': equity,
                'pnl': trade.get('pnl', 0)
            })
        
        return equity_curve
    
    def _analyze_drawdown(self, results: Dict) -> Dict:
        """Analyze drawdown patterns"""
        trades = results.get('trades', [])
        
        if not trades:
            return {}
        
        # Calculate drawdown series
        equity_curve = self._generate_equity_curve(results)
        equities = [e['equity'] for e in equity_curve]
        
        max_equity = equities[0]
        max_drawdown = 0
        max_drawdown_pct = 0
        current_drawdown = 0
        
        drawdowns = []
        
        for equity in equities:
            if equity > max_equity:
                max_equity = equity
            
            current_drawdown = max_equity - equity
            current_drawdown_pct = (current_drawdown / max_equity * 100) if max_equity > 0 else 0
            
            drawdowns.append(current_drawdown)
            
            if current_drawdown > max_drawdown:
                max_drawdown = current_drawdown
                max_drawdown_pct = current_drawdown_pct
        
        return {
            'max_drawdown': max_drawdown,
            'max_drawdown_pct': max_drawdown_pct,
            'avg_drawdown': np.mean(drawdowns),
            'drawdown_series': drawdowns
        }
    
    def _analyze_trade_distribution(self, results: Dict) -> Dict:
        """Analyze trade distribution by hour, day, direction"""
        trades = results.get('trades', [])
        
        if not trades:
            return {}
        
        df = pd.DataFrame(trades)
        df['entry_time'] = pd.to_datetime(df['entry_time'])
        
        # By hour
        df['hour'] = df['entry_time'].dt.hour
        by_hour = df.groupby('hour')['pnl'].agg(['count', 'sum', 'mean']).to_dict('index')
        
        # By day of week
        df['day_of_week'] = df['entry_time'].dt.dayofweek
        by_day = df.groupby('day_of_week')['pnl'].agg(['count', 'sum', 'mean']).to_dict('index')
        
        # By direction
        by_direction = df.groupby('side')['pnl'].agg(['count', 'sum', 'mean']).to_dict('index')
        
        # By exit reason
        by_exit_reason = df.groupby('exit_reason')['pnl'].agg(['count', 'sum', 'mean']).to_dict('index')
        
        return {
            'by_hour': by_hour,
            'by_day': by_day,
            'by_direction': by_direction,
            'by_exit_reason': by_exit_reason
        }
    
    def _analyze_monthly_performance(self, results: Dict) -> List[Dict]:
        """Analyze monthly performance"""
        trades = results.get('trades', [])

        if not trades:
            return []
        
        df = pd.DataFrame(trades)
        df['exit_time'] = pd.to_datetime(df['exit_time'])
        df['year_month'] = df['exit_time'].dt.to_period('M')

        monthly = df.groupby('year_month').agg({
            'pnl': ['sum', 'count', 'mean'],
        }).reset_index()
        monthly.columns = ['month', 'total_pnl', 'trades', 'avg_pnl']
        monthly['month'] = monthly['month'].astype(str)

        # Monthly max drawdown: worst peak-to-trough on the running equity within each month
        initial_capital = results.get('initial_capital', 10000.0)
        df_sorted = df.sort_values('exit_time').copy()
        df_sorted['cumulative_pnl'] = df_sorted['pnl'].cumsum() + initial_capital

        def _month_drawdown(group):
            eq = group['cumulative_pnl'].values
            peak = eq[0]
            max_dd = 0.0
            for v in eq:
                if v > peak:
                    peak = v
                dd = peak - v
                if dd > max_dd:
                    max_dd = dd
            return max_dd

        dd_by_month = df_sorted.groupby(df_sorted['exit_time'].dt.to_period('M')).apply(_month_drawdown)
        dd_by_month.index = dd_by_month.index.astype(str)
        monthly['max_drawdown'] = monthly['month'].map(dd_by_month).fillna(0)

        return monthly.to_dict('records')
    
    def save_report(self, report: Dict, filename: str = 'report'):
        """
        Save report to JSON file.
        
        Args:
            report: Report dictionary
            filename: Base filename (without extension)
        """
        filepath = os.path.join(self.output_dir, f"{filename}.json")
        
        with open(filepath, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        print(f"📄 Report saved: {filepath}")
    
    def save_trades_csv(self, results: Dict, filename: str = 'trades'):
        """
        Save trades to CSV file.
        
        Args:
            results: Backtest results with trades list
            filename: Base filename (without extension)
        """
        trades = results.get('trades', [])
        
        if not trades:
            print("⚠️ No trades to save")
            return
        
        df = pd.DataFrame(trades)
        filepath = os.path.join(self.output_dir, f"{filename}.csv")
        df.to_csv(filepath, index=False)
        
        print(f"📄 Trades saved: {filepath}")
    
    def generate_html_report(self, report: Dict, filename: str = 'report'):
        """
        Generate HTML report (simple version).
        
        Args:
            report: Report dictionary
            filename: Base filename (without .html extension)
        """
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Trading Bot Performance Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; }}
        h1 {{ color: #333; }}
        h2 {{ color: #666; margin-top: 30px; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
        th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
        th {{ background-color: #4CAF50; color: white; }}
        .metric {{ padding: 10px; margin: 10px 0; background: #f9f9f9; border-left: 4px solid #4CAF50; }}
        .positive {{ color: green; }}
        .negative {{ color: red; }}
    </style>
</head>
<body>
    <h1>Trading Bot Performance Report</h1>
    <p><strong>Generated:</strong> {report['timestamp']}</p>
    
    <h2>Performance Summary</h2>
    <div class="metric">
        <strong>Initial Capital:</strong> ${report['summary'].get('initial_capital', 0):,.2f}<br>
        <strong>Final Capital:</strong> ${report['summary'].get('final_capital', 0):,.2f}<br>
        <strong>Total P&L:</strong> <span class="{'positive' if report['summary'].get('total_pnl', 0) > 0 else 'negative'}">${report['summary'].get('total_pnl', 0):,.2f}</span><br>
        <strong>Return on Capital:</strong> <span class="{'positive' if report['summary'].get('total_return_pct', 0) > 0 else 'negative'}">{report['summary'].get('total_return_pct', 0):.2f}%</span><br>
        <strong>Avg Margin / Trade:</strong> ${report['summary'].get('avg_margin_per_trade', 0):,.2f}<br>
        <strong>Return on Margin:</strong> <span class="{'positive' if report['summary'].get('return_on_margin_pct', 0) > 0 else 'negative'}">{report['summary'].get('return_on_margin_pct', 0):.2f}%</span>
    </div>
    
    <div class="metric">
        <strong>Total Trades:</strong> {report['summary'].get('total_trades', 0)}<br>
        <strong>Win Rate:</strong> {report['summary'].get('win_rate', 0):.1f}%<br>
        <strong>Profit Factor:</strong> {report['summary'].get('profit_factor', 0):.2f}<br>
        <strong>Sharpe Ratio:</strong> {report['summary'].get('sharpe_ratio', 0):.2f}
    </div>
    
    <div class="metric">
        <strong>Max Drawdown:</strong> <span class="negative">${report['summary'].get('max_drawdown', 0):,.2f} ({report['summary'].get('max_drawdown_pct', 0):.2f}%)</span><br>
        <strong>Expectancy per Trade:</strong> ${report['summary'].get('expectancy_per_trade', 0):.2f}
    </div>
    
    <h2>Statistics</h2>
    <table>
        <tr>
            <th>Metric</th>
            <th>Value</th>
        </tr>
        """
        
        for key, value in report.get('statistics', {}).items():
            html += f"<tr><td>{key.replace('_', ' ').title()}</td><td>{value:.2f}</td></tr>"
        
        html += """
    </table>
</body>
</html>
        """
        
        filepath = os.path.join(self.output_dir, f"{filename}.html")
        with open(filepath, 'w') as f:
            f.write(html)
        
        print(f"📄 HTML report saved: {filepath}")

    def generate_excel_report(self, report: Dict, results: Dict, filename: str = 'backtest_analysis'):
        """
        Generate Excel workbook with multiple sheets:
        - Summary: key performance metrics
        - Statistics: detailed trade stats
        - Trades: full trade log
        - Equity Curve: equity over time
        - Monthly Performance: month-by-month breakdown
        """
        import xlsxwriter

        filepath = os.path.join(self.output_dir, f"{filename}.xlsx")
        workbook = xlsxwriter.Workbook(filepath)

        # ── Formats ──────────────────────────────────────────────────────────
        hdr = workbook.add_format({'bold': True, 'bg_color': '#4CAF50', 'font_color': 'white', 'border': 1})
        lbl = workbook.add_format({'bold': True, 'bg_color': '#F0F0F0', 'border': 1})
        num = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
        pct = workbook.add_format({'num_format': '0.00%', 'border': 1})
        pos = workbook.add_format({'num_format': '#,##0.00', 'font_color': '#006400', 'border': 1})
        neg = workbook.add_format({'num_format': '#,##0.00', 'font_color': '#8B0000', 'border': 1})
        plain = workbook.add_format({'border': 1})
        date_fmt = workbook.add_format({'num_format': 'yyyy-mm-dd hh:mm', 'border': 1})

        summary = report.get('summary', {})
        stats = report.get('statistics', {})

        # ── Sheet 1: Summary ─────────────────────────────────────────────────
        ws = workbook.add_worksheet('Summary')
        ws.set_column('A:A', 30)
        ws.set_column('B:B', 20)
        row = 0
        ws.write(row, 0, 'Trading Bot Backtest — Performance Summary', workbook.add_format({'bold': True, 'font_size': 14}))
        row += 2
        items = [
            ('Initial Capital',         summary.get('initial_capital', 0),          num),
            ('Final Capital',           summary.get('final_capital', 0),             num),
            ('Total P&L',               summary.get('total_pnl', 0),                 pos if summary.get('total_pnl', 0) >= 0 else neg),
            ('Return on Capital (%)',   summary.get('total_return_pct', 0) / 100,    pct),
            ('Avg Margin / Trade ($)',  summary.get('avg_margin_per_trade', 0),      num),
            ('Return on Margin (%)',    summary.get('return_on_margin_pct', 0) / 100, pct),
            ('Total Trades',            summary.get('total_trades', 0),              plain),
            ('Win Rate (%)',            summary.get('win_rate', 0) / 100,            pct),
            ('Profit Factor',           summary.get('profit_factor', 0),             num),
            ('Sharpe Ratio',            summary.get('sharpe_ratio', 0),              num),
            ('Max Drawdown ($)',        summary.get('max_drawdown', 0),              neg),
            ('Max Drawdown (%)',        summary.get('max_drawdown_pct', 0) / 100,    pct),
            ('Expectancy / Trade',      summary.get('expectancy_per_trade', 0),      num),
        ]
        for label, value, fmt in items:
            ws.write(row, 0, label, lbl)
            ws.write(row, 1, value, fmt)
            row += 1

        # ── Sheet 2: Statistics ──────────────────────────────────────────────
        ws2 = workbook.add_worksheet('Statistics')
        ws2.set_column('A:A', 30)
        ws2.set_column('B:B', 20)
        ws2.write(0, 0, 'Metric', hdr)
        ws2.write(0, 1, 'Value', hdr)
        for r, (k, v) in enumerate(stats.items(), start=1):
            ws2.write(r, 0, k.replace('_', ' ').title(), lbl)
            ws2.write(r, 1, v, num)

        # ── Sheet 3: Trades ──────────────────────────────────────────────────
        trades = results.get('trades', [])
        if trades:
            ws3 = workbook.add_worksheet('Trades')
            df_trades = pd.DataFrame(trades)
            cols = list(df_trades.columns)
            for c, col in enumerate(cols):
                ws3.write(0, c, col, hdr)
                ws3.set_column(c, c, 20)
            for r, row_data in enumerate(df_trades.itertuples(index=False), start=1):
                for c, val in enumerate(row_data):
                    if c < len(cols) and ('time' in cols[c] or 'date' in cols[c]):
                        ws3.write(r, c, str(val), plain)
                    elif isinstance(val, float):
                        ws3.write(r, c, val, num)
                    else:
                        ws3.write(r, c, val, plain)

        # ── Sheet 4: Equity Curve ────────────────────────────────────────────
        equity_data = report.get('equity_curve', [])
        if equity_data:
            ws4 = workbook.add_worksheet('Equity Curve')
            ws4.write(0, 0, 'Trade #', hdr)
            ws4.write(0, 1, 'Equity ($)', hdr)
            ws4.write(0, 2, 'P&L', hdr)
            ws4.set_column('A:C', 15)
            for r, pt in enumerate(equity_data, start=1):
                ws4.write(r, 0, r, plain)
                ws4.write(r, 1, pt.get('equity', 0), num)
                pnl_val = pt.get('pnl', 0)
                ws4.write(r, 2, pnl_val, pos if pnl_val >= 0 else neg)
            # Embed a chart
            chart = workbook.add_chart({'type': 'line'})
            chart.add_series({
                'name': 'Equity',
                'categories': ['Equity Curve', 1, 0, len(equity_data), 0],
                'values':     ['Equity Curve', 1, 1, len(equity_data), 1],
                'line': {'color': '#4CAF50', 'width': 1.5},
            })
            chart.set_title({'name': 'Equity Curve'})
            chart.set_x_axis({'name': 'Trade #'})
            chart.set_y_axis({'name': 'Equity ($)'})
            chart.set_size({'width': 720, 'height': 360})
            ws4.insert_chart('E2', chart)

        # ── Sheet 5: Monthly Performance ─────────────────────────────────────
        monthly = report.get('monthly_performance', [])
        if monthly:
            ws5 = workbook.add_worksheet('Monthly')
            headers = ['Month', 'Total P&L', 'Trades', 'Avg P&L', 'Max Drawdown ($)']
            for c, h in enumerate(headers):
                ws5.write(0, c, h, hdr)
            ws5.set_column('A:E', 18)
            for r, m in enumerate(monthly, start=1):
                ws5.write(r, 0, str(m.get('month', '')), plain)
                pnl_val = m.get('total_pnl', 0)
                ws5.write(r, 1, pnl_val, pos if pnl_val >= 0 else neg)
                ws5.write(r, 2, m.get('trades', 0), plain)
                ws5.write(r, 3, m.get('avg_pnl', 0), num)
                ws5.write(r, 4, m.get('max_drawdown', 0), neg)

        workbook.close()
        print(f"📊 Excel report saved: {filepath}")


# Example usage
if __name__ == "__main__":
    print("="*70)
    print("Reporting Skill - Example Usage")
    print("="*70)
    
    # Mock backtest results
    mock_results = {
        'initial_capital': 10000,
        'final_capital': 12500,
        'total_pnl': 2500,
        'total_return_pct': 25.0,
        'total_trades': 50,
        'winning_trades': 30,
        'losing_trades': 20,
        'win_rate': 60.0,
        'avg_win': 150.0,
        'avg_loss': -75.0,
        'profit_factor': 2.0,
        'max_drawdown': 500,
        'max_drawdown_pct': 4.0,
        'sharpe_ratio': 1.5,
        'expectancy_per_trade': 50.0,
        'trades': [
            {
                'entry_time': '2024-01-01 10:00:00',
                'entry_price': 1900.0,
                'side': 'BUY',
                'size': 1.0,
                'stop_loss': 1880.0,
                'take_profit': 1940.0,
                'exit_time': '2024-01-01 10:30:00',
                'exit_price': 1940.0,
                'exit_reason': 'TP_HIT',
                'pnl': 40.0,
                'pnl_pct': 2.1
            },
            {
                'entry_time': '2024-01-01 11:00:00',
                'entry_price': 1950.0,
                'side': 'SELL',
                'size': 1.0,
                'stop_loss': 1970.0,
                'take_profit': 1910.0,
                'exit_time': '2024-01-01 11:20:00',
                'exit_price': 1970.0,
                'exit_reason': 'SL_HIT',
                'pnl': -20.0,
                'pnl_pct': -1.0
            }
        ]
    }
    
    # Create skill
    config = {'reporting': {'output_dir': 'test_reports/'}}
    reporting = ReportingSkill(config)
    
    # Generate report
    context = Context(timestamp=datetime.now())
    context.backtest_results = mock_results
    report = reporting.execute(context)
    
    # Save report
    reporting.save_report(report, 'example_report')
    reporting.save_trades_csv(mock_results, 'example_trades')
    reporting.generate_html_report(report, 'example_report')
    
    print("\n" + "="*70)
    print("REPORT SUMMARY")
    print("="*70)
    print(f"Total P&L: ${report['summary']['total_pnl']:,.2f}")
    print(f"Win Rate: {report['summary']['win_rate']:.1f}%")
    print(f"Sharpe Ratio: {report['summary']['sharpe_ratio']:.2f}")
    print(f"Max Drawdown: ${report['summary']['max_drawdown']:,.2f}")
    print("="*70)
