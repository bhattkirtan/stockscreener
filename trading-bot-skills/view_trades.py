#!/usr/bin/env python3
"""
Trade Viewer — interactive Dash app to explore backtest results.

Usage:
    python view_trades.py                              # auto-picks latest run
    python view_trades.py --instrument GOLD            # latest GOLD run
    python view_trades.py --run results/GOLD/20260405_091641_st14_x1.5
    python view_trades.py --run results/ETHUSD/20260405_094943_st14_x1.5

Then open http://localhost:8050 in your browser.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import dash
from dash import dcc, html, Input, Output, callback_context
import yaml

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description='Backtest trade viewer')
    p.add_argument('--run',         help='Path to a specific run directory')
    p.add_argument('--instrument',  default=None, help='Instrument name (picks latest run)')
    p.add_argument('--port',        type=int, default=8050)
    p.add_argument('--host',        default='127.0.0.1', help='Bind host (use 0.0.0.0 in Docker)')
    p.add_argument('--results-dir', default=None, help='Override results directory (default: ./results)')
    return p.parse_args()


_RESULTS_DIR_OVERRIDE: Path | None = None  # set by main() via --results-dir

def find_latest_run(instrument=None):
    results_dir = _RESULTS_DIR_OVERRIDE or (Path(__file__).parent / 'results')
    if instrument:
        dirs = sorted((results_dir / instrument.upper()).iterdir())
    else:
        dirs = sorted(p for inst in results_dir.iterdir() if inst.is_dir()
                      for p in inst.iterdir())
    dirs = [d for d in dirs if d.is_dir() and (d / 'trades.csv').exists()]
    if not dirs:
        raise FileNotFoundError(f'No runs found under {results_dir}')
    return dirs[-1]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_run(run_dir: Path):
    trades = pd.read_csv(run_dir / 'trades.csv', parse_dates=['entry_time', 'exit_time'])
    import json
    with open(run_dir / 'report.json') as f:
        report = json.load(f)
    summary = report.get('summary', report)
    equity  = pd.DataFrame(report.get('equity_curve', []))
    if not equity.empty:
        equity['timestamp'] = pd.to_datetime(equity['timestamp'])
    return trades, summary, equity


def load_price_data(run_dir: Path, trades: pd.DataFrame):
    """
    Find and load the price CSV. Tries:
    1. instrument config data_path (relative to run_dir)
    2. Walks up to find any matching CSV in cloud-function/data/
    """
    # Guess instrument from run_dir path: results/<INSTRUMENT>/...
    instrument = run_dir.parent.name  # e.g. GOLD

    # Try instrument yaml for data_path
    yaml_path = Path(__file__).parent / 'config' / 'instruments' / f'{instrument}.yaml'
    data_path = None
    if yaml_path.exists():
        with open(yaml_path) as f:
            cfg = yaml.safe_load(f)
        rel = cfg.get('backtest', {}).get('data_path')
        if rel:
            data_path = (Path(__file__).parent / rel).resolve()

    if data_path is None or not data_path.exists():
        # Fallback: scan cloud-function/data/
        data_dir = Path(__file__).parent.parent / 'cloud-function' / 'data'
        candidates = sorted(data_dir.glob(f'{instrument}_M5_*.csv'))
        if candidates:
            data_path = candidates[-1]

    if data_path is None or not data_path.exists():
        return None

    # Only load the date range we need (+/- 1 day buffer)
    start = trades['entry_time'].min() - pd.Timedelta(days=1)
    end   = trades['exit_time'].max()  + pd.Timedelta(days=1)

    df = pd.read_csv(data_path, parse_dates=['timestamp'])
    df = df[(df['timestamp'] >= start) & (df['timestamp'] <= end)].reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# Chart builder
# ---------------------------------------------------------------------------

COLOR_WIN  = '#26a69a'   # teal
COLOR_LOSS = '#ef5350'   # red
COLOR_BUY  = '#1976d2'   # blue entry marker
COLOR_SELL = '#f57c00'   # orange entry marker


def build_chart(price_df, trades, selected_idx=None, window_hours=24):
    """
    Build the main candlestick + trade overlay figure.
    If selected_idx is set, zoom to that trade ± window_hours.
    """
    if price_df is None or price_df.empty:
        fig = go.Figure()
        fig.add_annotation(text='Price data not available', xref='paper', yref='paper',
                           x=0.5, y=0.5, showarrow=False, font=dict(size=18))
        return fig

    if selected_idx is not None and selected_idx < len(trades):
        t = trades.iloc[selected_idx]
        center = t['entry_time']
        x0 = center - pd.Timedelta(hours=window_hours)
        x1 = t['exit_time'] + pd.Timedelta(hours=window_hours)
        mask = (price_df['timestamp'] >= x0) & (price_df['timestamp'] <= x1)
        plot_df = price_df[mask]
        trade_mask = (trades['entry_time'] >= x0) & (trades['exit_time'] <= x1)
        plot_trades = trades[trade_mask]
    else:
        plot_df = price_df
        plot_trades = trades

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.75, 0.25],
                        vertical_spacing=0.03)

    # Candlesticks
    fig.add_trace(go.Candlestick(
        x=plot_df['timestamp'],
        open=plot_df['open'], high=plot_df['high'],
        low=plot_df['low'],  close=plot_df['close'],
        name='Price',
        increasing_line_color='#26a69a',
        decreasing_line_color='#ef5350',
        showlegend=False,
    ), row=1, col=1)

    # Trade overlays
    for i, (_, t) in enumerate(plot_trades.iterrows()):
        win   = t['pnl'] >= 0
        color = COLOR_WIN if win else COLOR_LOSS
        is_selected = (selected_idx is not None and
                       trades.index.get_loc(t.name) == selected_idx
                       if hasattr(t, 'name') else False)
        lw = 3 if is_selected else 1.5

        # Entry → exit line
        fig.add_shape(type='line',
                      x0=t['entry_time'], y0=t['entry_price'],
                      x1=t['exit_time'],  y1=t['exit_price'],
                      line=dict(color=color, width=lw),
                      row=1, col=1)

        # SL line (dashed red)
        fig.add_shape(type='line',
                      x0=t['entry_time'], y0=t['stop_loss'],
                      x1=t['exit_time'],  y1=t['stop_loss'],
                      line=dict(color='#ef5350', width=1, dash='dot'),
                      row=1, col=1)

        # TP line (dashed green)
        fig.add_shape(type='line',
                      x0=t['entry_time'], y0=t['take_profit'],
                      x1=t['exit_time'],  y1=t['take_profit'],
                      line=dict(color='#26a69a', width=1, dash='dot'),
                      row=1, col=1)

    # Entry markers (scatter for hover)
    buys  = plot_trades[plot_trades['side'] == 'BUY']
    sells = plot_trades[plot_trades['side'] == 'SELL']

    def _hover(df):
        return [
            f"#{i}<br>{r['side']} {r['size']} @ {r['entry_price']:.2f}<br>"
            f"Exit: {r['exit_price']:.2f} ({r['exit_reason']})<br>"
            f"PnL: ${r['pnl']:+.2f} | Hold: {int((r['exit_time']-r['entry_time']).total_seconds()//60)}m"
            for i, (_, r) in enumerate(df.iterrows())
        ]

    fig.add_trace(go.Scatter(
        x=buys['entry_time'], y=buys['entry_price'],
        mode='markers', name='BUY',
        marker=dict(symbol='triangle-up', size=8, color=COLOR_BUY),
        hovertext=_hover(buys), hoverinfo='text',
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=sells['entry_time'], y=sells['entry_price'],
        mode='markers', name='SELL',
        marker=dict(symbol='triangle-down', size=8, color=COLOR_SELL),
        hovertext=_hover(sells), hoverinfo='text',
    ), row=1, col=1)

    # Volume bars
    if 'volume' in plot_df.columns:
        vol_colors = ['#26a69a' if c >= o else '#ef5350'
                      for c, o in zip(plot_df['close'], plot_df['open'])]
        fig.add_trace(go.Bar(
            x=plot_df['timestamp'], y=plot_df['volume'],
            name='Volume', marker_color=vol_colors, showlegend=False,
        ), row=2, col=1)

    fig.update_layout(
        template='plotly_dark',
        xaxis_rangeslider_visible=False,
        height=700,
        margin=dict(l=50, r=20, t=30, b=20),
        legend=dict(orientation='h', y=1.02),
        paper_bgcolor='#1a1a2e',
        plot_bgcolor='#16213e',
    )
    fig.update_xaxes(gridcolor='#2a2a4a')
    fig.update_yaxes(gridcolor='#2a2a4a')
    return fig


def build_equity_chart(equity_df, trades):
    """Equity curve with trade P&L distribution."""
    fig = make_subplots(rows=1, cols=2,
                        column_widths=[0.7, 0.3],
                        subplot_titles=['Equity Curve', 'P&L Distribution'])

    if not equity_df.empty:
        fig.add_trace(go.Scatter(
            x=equity_df['timestamp'], y=equity_df['equity'],
            mode='lines', name='Equity',
            line=dict(color='#7c4dff', width=2),
            fill='tozeroy', fillcolor='rgba(124,77,255,0.1)',
        ), row=1, col=1)

    # P&L histogram
    wins   = trades[trades['pnl'] >= 0]['pnl']
    losses = trades[trades['pnl'] <  0]['pnl']
    fig.add_trace(go.Histogram(x=wins,   name='Win',  marker_color=COLOR_WIN,  opacity=0.8), row=1, col=2)
    fig.add_trace(go.Histogram(x=losses, name='Loss', marker_color=COLOR_LOSS, opacity=0.8), row=1, col=2)

    fig.update_layout(
        template='plotly_dark', height=300, barmode='overlay',
        margin=dict(l=50, r=20, t=40, b=20),
        paper_bgcolor='#1a1a2e', plot_bgcolor='#16213e',
        showlegend=True,
    )
    return fig


# ---------------------------------------------------------------------------
# Dash app
# ---------------------------------------------------------------------------

def build_app(run_dir: Path):
    trades, summary, equity = load_run(run_dir)
    price_df = load_price_data(run_dir, trades)

    instrument = run_dir.parent.name
    run_label  = run_dir.name

    app = dash.Dash(__name__, title=f'Trade Viewer — {instrument}')

    # Trade table data for the list
    table_rows = []
    for i, r in trades.iterrows():
        hold_min = int((r['exit_time'] - r['entry_time']).total_seconds() // 60)
        table_rows.append({
            'idx': i,
            'label': f"#{i}  {r['side']:<4}  {r['entry_time'].strftime('%m-%d %H:%M')}  "
                     f"{'▲' if r['pnl']>=0 else '▼'}  ${r['pnl']:+.0f}  {r['exit_reason'][:8]}  {hold_min}m",
            'pnl': r['pnl'],
        })

    def stat_card(label, value, color='#e0e0e0'):
        return html.Div([
            html.Div(label, style={'fontSize': '11px', 'color': '#888', 'marginBottom': '2px'}),
            html.Div(value, style={'fontSize': '18px', 'fontWeight': 'bold', 'color': color}),
        ], style={'background': '#1e1e3a', 'borderRadius': '8px', 'padding': '10px 14px',
                  'minWidth': '130px', 'flex': '1'})

    ret_color   = COLOR_WIN  if summary.get('total_return_pct', 0) > 0 else COLOR_LOSS
    dd_color    = '#ff9800'
    sharpe_color = COLOR_WIN if summary.get('sharpe_ratio', 0) > 1 else '#ff9800'

    stats_bar = html.Div([
        stat_card('Return',        f"{summary.get('total_return_pct', 0):,.1f}%",   ret_color),
        stat_card('Total PnL',     f"${summary.get('total_pnl', 0):,.0f}",          ret_color),
        stat_card('Trades',        f"{summary.get('total_trades', 0):,}"),
        stat_card('Win Rate',      f"{summary.get('win_rate', 0):.1f}%"),
        stat_card('Sharpe',        f"{summary.get('sharpe_ratio', 0):.2f}",         sharpe_color),
        stat_card('Max DD',        f"{summary.get('max_drawdown_pct', 0):.1f}%",    dd_color),
        stat_card('Profit Factor', f"{summary.get('profit_factor', 0):.2f}"),
        stat_card('Expectancy',    f"${summary.get('expectancy_per_trade', 0):.2f}"),
    ], style={'display': 'flex', 'gap': '8px', 'flexWrap': 'wrap', 'marginBottom': '12px'})

    # Trade list items
    def trade_item(row):
        color = COLOR_WIN if row['pnl'] >= 0 else COLOR_LOSS
        return html.Div(row['label'], id={'type': 'trade-item', 'index': row['idx']},
                        n_clicks=0,
                        style={
                            'padding': '5px 8px',
                            'cursor': 'pointer',
                            'borderLeft': f'3px solid {color}',
                            'marginBottom': '2px',
                            'fontSize': '11px',
                            'fontFamily': 'monospace',
                            'borderRadius': '3px',
                            'background': '#1e1e3a',
                            'color': '#ccc',
                        })

    app.layout = html.Div([
        # Header
        html.Div([
            html.H2(f'Trade Viewer  ·  {instrument}  ·  {run_label}',
                    style={'margin': '0', 'color': '#e0e0e0', 'fontSize': '16px'}),
        ], style={'background': '#0d0d1a', 'padding': '10px 16px',
                  'borderBottom': '1px solid #2a2a4a'}),

        html.Div([
            # Left panel — trade list
            html.Div([
                html.Div('TRADES', style={'fontSize': '10px', 'color': '#888',
                                          'letterSpacing': '1px', 'marginBottom': '6px'}),
                html.Div([
                    dcc.Input(id='search-box', type='text', placeholder='Filter…',
                              debounce=True,
                              style={'width': '100%', 'background': '#1e1e3a', 'color': '#ccc',
                                     'border': '1px solid #2a2a4a', 'borderRadius': '4px',
                                     'padding': '4px 8px', 'marginBottom': '6px',
                                     'boxSizing': 'border-box'}),
                ]),
                html.Div(
                    [trade_item(r) for r in table_rows],
                    id='trade-list',
                    style={'overflowY': 'auto', 'height': 'calc(100vh - 220px)'},
                ),
            ], style={'width': '230px', 'minWidth': '230px', 'padding': '12px',
                      'background': '#12122a', 'borderRight': '1px solid #2a2a4a',
                      'display': 'flex', 'flexDirection': 'column'}),

            # Right panel — charts
            html.Div([
                stats_bar,
                dcc.Tabs(id='tabs', value='chart', children=[
                    dcc.Tab(label='Price & Trades', value='chart',
                            style={'color': '#888'}, selected_style={'color': '#fff'}),
                    dcc.Tab(label='Equity Curve',   value='equity',
                            style={'color': '#888'}, selected_style={'color': '#fff'}),
                ], style={'marginBottom': '8px'}),
                html.Div(id='chart-container'),
                dcc.Store(id='selected-trade', data=None),
                dcc.Store(id='all-trades', data=table_rows),
            ], style={'flex': '1', 'padding': '12px', 'overflowY': 'auto'}),

        ], style={'display': 'flex', 'height': 'calc(100vh - 42px)', 'overflow': 'hidden'}),

    ], style={'fontFamily': 'Inter, sans-serif', 'background': '#0d0d1a',
              'height': '100vh', 'overflow': 'hidden'})

    # -----------------------------------------------------------------------
    # Callbacks
    # -----------------------------------------------------------------------

    @app.callback(
        Output('selected-trade', 'data'),
        Input({'type': 'trade-item', 'index': dash.ALL}, 'n_clicks'),
        prevent_initial_call=True,
    )
    def select_trade(n_clicks_list):
        ctx = callback_context
        if not ctx.triggered:
            return None
        triggered_id = ctx.triggered[0]['prop_id']
        import json as _json
        idx = _json.loads(triggered_id.split('.')[0])['index']
        return idx

    @app.callback(
        Output('chart-container', 'children'),
        Input('tabs', 'value'),
        Input('selected-trade', 'data'),
    )
    def update_chart(tab, selected_idx):
        if tab == 'equity':
            fig = build_equity_chart(equity, trades)
            return dcc.Graph(figure=fig, config={'displayModeBar': False})
        else:
            fig = build_chart(price_df, trades, selected_idx=selected_idx, window_hours=12)
            return dcc.Graph(figure=fig, config={'displayModeBar': True,
                                                  'modeBarButtonsToRemove': ['lasso2d', 'select2d']})

    @app.callback(
        Output('trade-list', 'children'),
        Input('search-box', 'value'),
        Input('all-trades', 'data'),
    )
    def filter_trades(query, rows):
        if query:
            q = query.lower()
            rows = [r for r in rows if q in r['label'].lower()]
        return [trade_item(r) for r in rows]

    return app


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    args = parse_args()

    global _RESULTS_DIR_OVERRIDE
    if args.results_dir:
        _RESULTS_DIR_OVERRIDE = Path(args.results_dir)

    if args.run:
        run_dir = Path(args.run)
        if not run_dir.is_absolute():
            run_dir = Path(__file__).parent / run_dir
    else:
        run_dir = find_latest_run(args.instrument)

    print(f'Loading run: {run_dir}')
    app = build_app(run_dir)
    print(f'\n  Open http://{args.host}:{args.port} in your browser\n')
    app.run(debug=False, host=args.host, port=args.port)
