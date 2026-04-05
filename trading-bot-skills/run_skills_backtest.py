#!/usr/bin/env python3
"""
Skills-Based Backtest Runner
Uses the ACTUAL skills architecture (not script shortcuts)

SKILLS WIRED:
1. MarketDataSkill - Provides candle history
2. AnalysisSkill - Generates signals (THIS IS WHERE SIGNALS ARE CREATED!)
3. RiskSkill - Validates signals, checks cooldowns
4. BacktestingSkill - Simulates execution

ADD NEW STRATEGIES:
Edit skills/analysis/analysis_skill.py:
- Line 200: _generate_signal() method
- Add your strategy logic
- Enable/disable via config (trading_config.yaml)
"""
import sys
import os
import copy
import argparse
from pathlib import Path
import pandas as pd
import yaml
import asyncio
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from skills.market_data import MarketDataSkill
from skills.analysis import AnalysisSkill
from skills.risk import RiskSkill
from skills.backtesting import BacktestingSkill
from skills.reporting import ReportingSkill
from skills.base_skill import Context
from core.event_bus import EventBus, EventType


def load_config(instrument: str = None) -> dict:
    """Load base config, optionally deep-merged with an instrument override."""
    base_path = Path(__file__).parent / 'config' / 'trading_config.yaml'
    with open(base_path, 'r') as f:
        config = yaml.safe_load(f)

    if instrument:
        inst_path = Path(__file__).parent / 'config' / 'instruments' / f'{instrument.upper()}.yaml'
        if not inst_path.exists():
            raise FileNotFoundError(f"No instrument config found: {inst_path}")
        with open(inst_path, 'r') as f:
            inst_config = yaml.safe_load(f)
        config = _deep_merge(config, inst_config)

    # Single source of truth: risk pip values → analysis.sl_tp
    _propagate_risk_to_sl_tp(config)
    return config


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = copy.deepcopy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _propagate_risk_to_sl_tp(config: dict) -> None:
    """
    Single source of truth for pip/SL/TP: copy from risk → analysis.sl_tp.

    Instrument yamls only need to set risk.pip_size / stop_loss_pips /
    take_profit_pips. AnalysisSkill (which only sees the analysis section)
    will pick them up via analysis.sl_tp without any duplication.
    """
    risk = config.get('risk', {})
    sl_tp = config.setdefault('analysis', {}).setdefault('sl_tp', {})
    for key in ('pip_size', 'stop_loss_pips', 'take_profit_pips'):
        if key in risk:
            sl_tp[key] = risk[key]


def _ensure_data(data_path: str, config: dict) -> None:
    """
    If data_path does not exist, download it via fetch_data.py.

    Derives --epic and --bars from the instrument config and filename
    so no manual intervention is needed.
    """
    if Path(data_path).exists():
        return

    print(f"⚠️  Data file not found: {data_path}")
    print(f"⬇️  Auto-downloading...")

    # Resolve epic from instrument config (e.g. GOLD, EURUSD, US100)
    epic = config.get('market_data', {}).get('instrument', 'GOLD')

    # Parse bar count from filename (e.g. GOLD_M5_215000bars.csv → 215000)
    stem = Path(data_path).stem          # 'GOLD_M5_215000bars'
    bars = 150000                        # safe default
    for part in stem.split('_'):
        if part.endswith('bars') and part[:-4].isdigit():
            bars = int(part[:-4])
            break

    # Timeframe from filename (e.g. GOLD_M5_... → M5)
    timeframe = 'M5'
    parts = stem.split('_')
    if len(parts) >= 2 and parts[1].upper().startswith('M'):
        timeframe = parts[1].upper()

    fetch_script = Path(__file__).parent / 'fetch_data.py'
    cmd = [
        sys.executable, str(fetch_script),
        '--epic',      epic,
        '--timeframe', timeframe,
        '--bars',      str(bars),
        '--output',    data_path,
    ]

    print(f"   Command: {' '.join(cmd)}")
    import subprocess
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"Data download failed for {epic} {timeframe} {bars} bars.\n"
            f"Check your API credentials in .env and try manually:\n"
            f"  python3 fetch_data.py --epic {epic} --timeframe {timeframe} --bars {bars}"
        )
    print(f"✅ Download complete: {data_path}")


def load_historical_data(data_path: str) -> pd.DataFrame:
    """Load historical candle data"""
    print(f"📊 Loading data from {data_path}...")
    df = pd.read_csv(data_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    print(f"✅ Loaded {len(df):,} candles")
    print(f"   Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    return df


def resample_ohlcv(df: pd.DataFrame, target_minutes: int) -> pd.DataFrame:
    """Resample M5 data to a higher timeframe (e.g. M10, M15, M30) in-memory."""
    df = df.set_index('timestamp').sort_index()
    rule = f'{target_minutes}min'
    agg = {
        'open':  'first',
        'high':  'max',
        'low':   'min',
        'close': 'last',
    }
    if 'volume' in df.columns:
        agg['volume'] = 'sum'
    resampled = df.resample(rule, label='left', closed='left').agg(agg).dropna()
    resampled = resampled.reset_index()  # timestamp back as column
    print(f"   Resampled M5 → M{target_minutes}: {len(resampled):,} candles")
    return resampled


async def run_skills_backtest(df: pd.DataFrame, config: dict, shuffle_signals: bool = False, run_id: str = None, buy_only: bool = False):
    """
    Run backtest using actual skills (not shortcuts!)
    
    This simulates the real bot flow:
    1. Candle arrives -> MarketDataSkill buffers it
    2. MarketDataSkill -> AnalysisSkill calculates indicators
    3. AnalysisSkill -> Generates signal (THIS IS WHERE SIGNALS COME FROM!)
    4. Signal -> RiskSkill validates (cooldown, position limits)
    5. Approved Signal -> BacktestingSkill executes (simulated trade)
    """
    print("\n🔄 Running backtest with ACTUAL SKILLS...")
    print("=" * 60)
    
    # Initialize Event Bus (fast_mode skips history tracking for 150k candle performance)
    event_bus = EventBus(fast_mode=True)
    
    # Initialize Skills (same order as live bot)
    print("\n🔧 Initializing skills...")
    
    # 1. Market Data Skill - manages candle buffer
    market_data = MarketDataSkill(config.get('market_data', {}), event_bus)
    print(f"   ✅ MarketDataSkill (buffer: {market_data.buffer_size} candles)")
    
    # 2. Analysis Skill - THIS IS WHERE SIGNALS ARE GENERATED!
    analysis = AnalysisSkill(config.get('analysis', {}), event_bus, market_data)
    print(f"   ✅ AnalysisSkill")
    print(f"      - Supertrend: ATR({analysis.st_period}) x {analysis.st_multiplier}")
    print(f"      - EMA: {analysis.ema_period}")
    print(f"      - SMA: {analysis.sma_fast_period}/{analysis.sma_slow_period}")
    print(f"      - SL/TP method: {analysis.sl_tp_config.get('method', 'atr')}")
    
    # 3. Risk Skill - validates signals
    risk = RiskSkill(config.get('risk', {}), event_bus)
    print(f"   ✅ RiskSkill (cooldowns: SL={risk.sl_cooldown_minutes}min, TP={risk.tp_cooldown_minutes}min)")
    
    # 4. Backtesting Skill - simulates execution
    backtesting = BacktestingSkill(config, event_bus)
    print(f"   ✅ BacktestingSkill (capital: ${backtesting.initial_capital:,.0f}, SL/TP: {backtesting.stop_loss_pips}/{backtesting.take_profit_pips}p)")

    # 5. Reporting Skill - generates performance report
    # Output dir: <results_root>/<epic>/<run_id>/
    epic = config.get('market_data', {}).get('instrument', 'backtest').upper()
    _results_root = Path(os.getenv('RESULTS_DIR', str(Path(__file__).parent / 'results')))
    out_dir = str(_results_root / epic / (run_id or 'default'))
    config.setdefault('reporting', {})['output_dir'] = out_dir
    reporting = ReportingSkill(config)
    print(f"   ✅ ReportingSkill (output: {reporting.output_dir})")
    
    # Register event handlers (connect skills to event bus)
    event_bus.subscribe(EventType.CANDLE_CLOSED, analysis.on_candle_closed)
    event_bus.subscribe(EventType.SIGNAL_GENERATED, risk.on_signal_generated)
    
    # Mutable cell so on_risk_approved can read the current candle's open price.
    # Cloud-function closes reverse positions at candle['open'], not candle['close'].
    _current_candle_open = [0.0]
    # Mutable cell so on_risk_approved knows the candle's actual timestamp.
    # RISK_APPROVED event doesn't carry timestamp in its payload; without this the
    # Context falls back to datetime.now() and all entry_times would be today.
    _current_candle_timestamp = [None]

    if shuffle_signals:
        import random
        print("\n🔀 SHUFFLE MODE — signal directions are randomised")
        print("   Real edge should collapse P&L to ~$0. High P&L = R:R artefact.")

    # Handler for risk-approved signals -> execute in backtest
    async def on_risk_approved(event):
        """When risk approves signal, execute simulated trade"""
        signal    = event.payload.get('signal')
        if shuffle_signals and signal in ('BUY', 'SELL'):
            signal = random.choice(['BUY', 'SELL'])
            # Null out SL/TP so backtesting_skill recomputes them for the shuffled direction.
            # Keeping the original SL/TP would invert them (e.g. a SELL with a BUY's SL
            # below entry causes an instant win on the very next candle — not a real result).
            trade_sl = None
            trade_tp = None
        else:
            trade_sl = event.payload.get('stop_loss')
            trade_tp = event.payload.get('take_profit')
        price     = event.payload.get('entry_price')
        # Prefer payload timestamp; fall back to current-candle cell (set each iteration)
        timestamp = event.payload.get('timestamp') or _current_candle_timestamp[0]
        # Close opposite-direction positions at candle['open'] — mirrors cloud-function
        # which calls: self.close_position(trade, timestamp, candle['open'], 'Reverse Signal')
        if signal and price:
            reverse_price = _current_candle_open[0] if _current_candle_open[0] else price
            closed = backtesting.close_reverse_positions(signal, reverse_price, timestamp)
            # Notify risk of closed trades so cooldown tracking uses candle timestamps
            for t in closed:
                risk.has_open_position = False
                risk.on_position_closed(
                    direction=t.side.value,
                    close_reason='Reverse Signal',
                    entry_price=t.entry_price,
                    close_price=t.exit_price,
                    close_time=timestamp
                )
        context = Context(
            timestamp=timestamp,
            current_candle=event.payload.get('candle', {}),
            signal=signal,
            entry_price=price,
            stop_loss=trade_sl,
            take_profit=trade_tp
        )
        # buy_only: allow reverse-exits but block new SELL entries
        if buy_only and signal == 'SELL':
            entered = False
        else:
            entered = backtesting.execute(context)
        if entered:
            risk.has_open_position = True
    
    event_bus.subscribe(EventType.RISK_APPROVED, on_risk_approved)

    # ----------------------------------------------------------------
    # Pre-compute ALL indicators once on the full DataFrame (O(n) not O(n²))
    # ----------------------------------------------------------------
    print("\n⚡ Pre-computing indicators on full dataset...")
    from skills.analysis.analysis_skill import _to_dataframe
    full_df = df.copy()
    full_df = full_df.set_index('timestamp') if 'timestamp' in full_df.columns else full_df
    full_df.index = pd.to_datetime(full_df.index)
    full_df = analysis._compute_indicators(full_df)
    analysis.precomputed_df = full_df
    print(f"   ✅ Done — {len(full_df):,} rows with indicators")

    # Build higher-timeframe frames for MTF confluence (lookahead-safe .asof() lookups)
    need_htf = (analysis.require_h1_bb or analysis.require_mtf_bb or
                analysis.require_daily_bias or analysis.block_ranging_days)
    if need_htf:
        from core.indicators import calculate_bollinger_bands, calculate_sma
        print("   📊 Building higher-timeframe frames for MTF confluence...")

        if analysis.require_h1_bb or analysis.require_mtf_bb:
            df_h1 = resample_ohlcv(df, 60).set_index('timestamp').sort_index()
            df_h1.index = pd.to_datetime(df_h1.index)
            bb_u, bb_m, bb_l = calculate_bollinger_bands(
                df_h1['close'], analysis.mtf_h1_bb_period, analysis.mtf_h1_bb_std)
            df_h1['h1_bb_upper']  = bb_u
            df_h1['h1_bb_middle'] = bb_m
            df_h1['h1_bb_lower']  = bb_l
            analysis.df_h1 = df_h1
            print(f"   ✅ H1: {len(df_h1):,} bars | BB({analysis.mtf_h1_bb_period},{analysis.mtf_h1_bb_std})")

        if analysis.require_mtf_bb:
            df_4h = resample_ohlcv(df, 240).set_index('timestamp').sort_index()
            df_4h.index = pd.to_datetime(df_4h.index)
            bb_u, bb_m, bb_l = calculate_bollinger_bands(
                df_4h['close'], analysis.mtf_h4_bb_period, analysis.mtf_h4_bb_std)
            df_4h['h4_bb_upper']  = bb_u
            df_4h['h4_bb_middle'] = bb_m
            df_4h['h4_bb_lower']  = bb_l
            analysis.df_4h = df_4h
            print(f"   ✅ 4h: {len(df_4h):,} bars | BB({analysis.mtf_h4_bb_period},{analysis.mtf_h4_bb_std})")

        if analysis.require_daily_bias or analysis.block_ranging_days or analysis.require_mtf_bb:
            df_daily = resample_ohlcv(df, 1440).set_index('timestamp').sort_index()
            df_daily.index = pd.to_datetime(df_daily.index)
            df_daily['daily_sma'] = calculate_sma(df_daily['close'], analysis.mtf_daily_sma)
            if analysis.require_mtf_bb:
                bb_u, bb_m, bb_l = calculate_bollinger_bands(
                    df_daily['close'], analysis.mtf_daily_bb_period, analysis.mtf_daily_bb_std)
                df_daily['daily_bb_upper']  = bb_u
                df_daily['daily_bb_middle'] = bb_m
                df_daily['daily_bb_lower']  = bb_l
            analysis.df_daily = df_daily
            print(f"   ✅ Daily: {len(df_daily):,} bars | BB({analysis.mtf_daily_bb_period},{analysis.mtf_daily_bb_std})")

    print("\n" + "=" * 60)
    print("🎯 Processing candles through skills pipeline...")
    print("=" * 60)

    # Track progress
    total_candles = len(df)
    # Derive warmup from the slowest indicator period + a safety buffer.
    # This ensures all indicators have a full rolling window before signals fire.
    warmup_bars = max(
        analysis.sma_slow_period,
        analysis.bb_period,
        analysis.st_period,
        getattr(analysis, 'macd_slow', 26) + getattr(analysis, 'macd_signal_period', 9),
        getattr(analysis, 'rsi_period', 14),
    ) + 10  # +10 bar buffer for indicator stabilisation

    # Feed candles through skills pipeline
    for idx in range(total_candles):
        candle = df.iloc[idx].to_dict()
        timestamp = candle['timestamp']

        # Skip warmup period
        if idx < warmup_bars:
            continue

        # Track open price and timestamp so on_risk_approved can reference the candle
        _current_candle_open[0] = candle['open']
        _current_candle_timestamp[0] = timestamp

        # 1. Check SL/TP hits using intracandle HIGH/LOW — must run BEFORE signal
        #    processing so that SL/TP takes priority over reverse-signal exits on
        #    candles where both conditions are triggered.  This matches cloud-function
        #    behaviour (SL/TP checked first against high/low, then signal at close).
        context = Context(timestamp=timestamp, current_candle=candle)
        sl_tp_closed = backtesting.check_exits(context)
        # Notify risk of SL/TP closures so cooldown tracking uses candle timestamps
        for t in sl_tp_closed:
            risk.has_open_position = False
            risk.on_position_closed(
                direction=t.side.value,
                close_reason=t.exit_reason,  # 'SL_HIT' or 'TP_HIT'
                entry_price=t.entry_price,
                close_price=t.exit_price,
                close_time=timestamp
            )

        # 2. Publish CANDLE_CLOSED — triggers analysis → signal → reverse exit + new trade
        from core.event_bus import Event, EventType as ET
        await event_bus.publish(Event(
            event_type=ET.CANDLE_CLOSED,
            instrument=config.get('market_data', {}).get('instrument', 'GOLD'),
            source='backtest',
            payload={'candle': candle, 'timeframe': 'M5'}
        ))
        
        # Progress indicator
        if (idx + 1) % 10000 == 0:
            pct = (idx + 1) / total_candles * 100
            print(f"   Progress: {idx + 1:,}/{total_candles:,} ({pct:.1f}%) - Capital: ${backtesting.capital:,.2f}")
    
    # Close any remaining positions at end of data.
    # First check SL/TP on the final candle (they may have been hit),
    # then force-close survivors at close price.
    if backtesting.open_positions:
        last_candle = df.iloc[-1].to_dict()
        last_ts = last_candle['timestamp']
        context = Context(timestamp=last_ts, current_candle=last_candle)
        sl_tp_closed = backtesting.check_exits(context)
        for t in sl_tp_closed:
            risk.on_position_closed(
                direction=t.side.value,
                close_reason=t.exit_reason,
                entry_price=t.entry_price,
                close_price=t.exit_price,
                close_time=last_ts,
            )
        # Force-close anything still open
        for trade in backtesting.open_positions[:]:
            backtesting._close_position(
                trade,
                exit_price=last_candle['close'],
                exit_reason='End of Data',
                exit_time=last_ts,
            )
            backtesting.open_positions.remove(trade)
    
    print("\n" + "=" * 60)
    print("✅ Backtest complete!")
    print("=" * 60)
    
    results = backtesting.get_results()

    # Generate report via ReportingSkill
    context = Context(timestamp=datetime.now())
    context.backtest_results = results
    report = reporting.execute(context)
    reporting.save_report(report, 'report')
    reporting.save_trades_csv(results, 'trades')
    reporting.generate_html_report(report, 'report')
    reporting.generate_excel_report(report, results, 'analysis')

    # MTF rejection diagnostics
    if analysis.mtf_rejections:
        total_r = sum(analysis.mtf_rejections.values())
        print(f"\n📊 MTF Filter Rejections: {total_r:,} signals blocked")
        for reason, cnt in sorted(analysis.mtf_rejections.items(), key=lambda x: -x[1]):
            print(f"   {reason}: {cnt:,} ({cnt / total_r * 100:.1f}%)")

    # ── M1 Exit Validation ────────────────────────────────────────────────────
    _run_m1_validation(results, config, out_dir)

    return results


def _run_m1_validation(results: dict, config: dict, out_dir: str) -> None:
    """
    Optional post-backtest step: re-check every SL/TP exit against M1 candles.
    Skipped silently if disabled in config or M1 data file not found.
    """
    val_cfg = config.get('m1_validation', {})
    if not val_cfg.get('enabled', False):
        return

    # Allow instrument yaml to override m1_data_path (e.g. EURUSD has its own M1 file)
    m1_path = val_cfg.get('data_path', '')
    if not m1_path:
        return

    # Resolve relative paths from the project root (same dir as run_skills_backtest.py)
    m1_path = str(Path(__file__).parent / m1_path)
    if not Path(m1_path).exists():
        print(f"\n⚠️  M1 validation skipped — file not found: {m1_path}")
        print(f"   Generate it with: python3 subset_m1_data.py --from YYYY-MM-DD --to YYYY-MM-DD")
        return

    trades = results.get('trades', [])
    if not trades:
        return

    print(f"\n🔍 Running M1 exit validation ({len(trades):,} trades)...")

    try:
        import pandas as pd
        from validate_exits import load_m1, recheck_exit, print_summary

        tz_offset = val_cfg.get('tz_offset_hours', 0)
        pip_size  = config.get('risk', {}).get('pip_size', 1.0)

        m1 = load_m1(m1_path, tz_offset_hours=tz_offset)

        trades_df = pd.DataFrame(trades)
        # Ensure timestamp columns are parsed
        for col in ('entry_time', 'exit_time'):
            if col in trades_df.columns:
                trades_df[col] = pd.to_datetime(trades_df[col])

        val_rows = []
        for _, trade in trades_df.iterrows():
            val_rows.append(recheck_exit(trade, m1, pip_size=pip_size))
        val_df = pd.DataFrame(val_rows)

        # Save validation CSV alongside trades
        out_path = Path(out_dir) / 'exit_validation.csv'
        pd.concat([trades_df, val_df], axis=1).to_csv(out_path, index=False)

        print_summary(trades_df, val_df)
        print(f"💾 Validation saved: {out_path}")

    except Exception as e:
        print(f"\n⚠️  M1 validation failed: {e}")
        import traceback
        traceback.print_exc()


def print_results(results: dict):
    """Print backtest results"""
    print("\n" + "=" * 60)
    print("BACKTEST RESULTS (Skills-Based)")
    print("=" * 60)
    
    print(f"\n📊 Trade Statistics:")
    print(f"   Total Trades: {results.get('total_trades', 0):,}")
    print(f"   Winning Trades: {results.get('winning_trades', 0):,}")
    print(f"   Losing Trades: {results.get('losing_trades', 0):,}")
    print(f"   Win Rate: {results.get('win_rate', 0):.1f}%")
    
    print(f"\n💰 P&L:")
    print(f"   Initial Capital: ${results.get('initial_capital', 0):,.2f}")
    print(f"   Final Capital: ${results.get('final_capital', 0):,.2f}")
    print(f"   Total P&L: ${results.get('total_pnl', 0):,.2f}")
    print(f"   Return: {results.get('total_return_pct', 0):.2f}%")
    print(f"   Average Trade: ${results.get('expectancy_per_trade', 0):.2f}")
    print(f"   Average Winner: ${results.get('avg_win', 0):.2f}")
    print(f"   Average Loser: ${results.get('avg_loss', 0):.2f}")
    
    print(f"\n📉 Risk Metrics:")
    print(f"   Max Drawdown: ${results.get('max_drawdown', 0):,.2f}")
    print(f"   Sharpe Ratio: {results.get('sharpe_ratio', 0):.2f}")
    
    print(f"\n🎯 Strategy Analysis:")
    print(f"   Strategy: {results.get('strategy', 'supertrend_vwap')}")
    print(f"   Timeframe: {results.get('timeframe', 'M5')}")
    
    print("\n" + "=" * 60)
    print("\n💡 WHERE SIGNALS ARE CREATED:")
    print("   File: skills/analysis/analysis_skill.py")
    print("   Method: _generate_signal() (line 200)")
    print("   Logic: Uses core/signal_engine.py (shared with live bot)")
    print("\n💡 TO ADD NEW STRATEGIES:")
    print("   1. Edit skills/analysis/analysis_skill.py")
    print("   2. Add new indicator calculations (e.g., _calculate_rsi)")
    print("   3. Modify _generate_signal() to use new indicators")
    print("   4. Add config options in trading_config.yaml")
    print("   5. Enable/disable via config.analysis.strategy")
    print("\n" + "=" * 60)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Skills-Based Backtest Runner')
    parser.add_argument(
        '--instrument', default=None,
        help='Instrument to run (e.g. GOLD, US100, EURUSD). Loads config/instruments/<INSTRUMENT>.yaml as override.'
    )
    parser.add_argument('--sl',   type=float, default=None, help='Override stop_loss_pips (e.g. --sl 25)')
    parser.add_argument('--tp',   type=float, default=None, help='Override take_profit_pips (e.g. --tp 100)')
    parser.add_argument('--size', type=float, default=None, help='Override position size / units (e.g. --size 1)')
    parser.add_argument('--bars', type=int,   default=None,
                        help='Number of M5 bars to backtest (e.g. --bars 215000). '
                             'Resolves the data file automatically and downloads if missing.')
    parser.add_argument('--shuffle-signals', action='store_true', default=False,
                        help='Randomise signal direction (BUY/SELL) before execution. '
                             'If P&L stays high under shuffle, edge comes from R:R ratio '
                             'not signal quality. A real edge should collapse to ~0.')
    parser.add_argument('--no-ema', action='store_true', default=False,
                        help='Disable EMA filter (require_ema: false). Test if EMA adds edge.')
    parser.add_argument('--no-sma', action='store_true', default=False,
                        help='Disable SMA filter (require_sma: false). Test if SMA adds edge.')
    parser.add_argument('--min-hold', type=int, default=None,
                        help='Min minutes to hold before reverse-signal exit allowed (e.g. --min-hold 120).')
    parser.add_argument('--skip-hours', type=str, default=None,
                        help='Comma-separated UTC hours to skip new entries (e.g. --skip-hours 18,19,20,21,22,23).')
    parser.add_argument('--buy-only', action='store_true', default=False,
                        help='Only take BUY signals, ignore SELL signals.')
    parser.add_argument('--st-period', type=int, default=None,
                        help='Override Supertrend ATR period (e.g. --st-period 10).')
    parser.add_argument('--st-mult', type=float, default=None,
                        help='Override Supertrend multiplier (e.g. --st-mult 3.0).')
    parser.add_argument('--results-dir', default=None,
                        help='Root directory for results (default: ./results). '
                             'Use /data/results inside Docker.')
    parser.add_argument('--run-id', default=None,
                        help='Optional run id override (used by API job runner).')
    args = parser.parse_args()

    print("🧪 SKILLS-BASED BACKTEST")
    print("=" * 60)
    print("Using ACTUAL skills (not shortcuts!)")
    print("=" * 60)
    
    # Load config (base + optional instrument override)
    config = load_config(args.instrument)

    # Apply CLI overrides (--sl / --tp / --size override YAML config)
    if args.sl is not None:
        config.setdefault('analysis', {}).setdefault('sl_tp', {})['stop_loss_pips'] = args.sl
        config.setdefault('risk', {})['stop_loss_pips'] = args.sl
    if args.tp is not None:
        config.setdefault('analysis', {}).setdefault('sl_tp', {})['take_profit_pips'] = args.tp
        config.setdefault('risk', {})['take_profit_pips'] = args.tp
    if args.size is not None:
        config.setdefault('backtesting', {})['position_size'] = args.size
        config.setdefault('backtest', {})['position_size'] = args.size
    if args.no_ema:
        config.setdefault('analysis', {}).setdefault('signal_rules', {})['require_ema'] = False
    if args.no_sma:
        config.setdefault('analysis', {}).setdefault('signal_rules', {})['require_sma'] = False
    if args.min_hold is not None:
        config.setdefault('backtesting_filters', {})['min_hold_minutes'] = args.min_hold
    if args.skip_hours is not None:
        hours = [int(h.strip()) for h in args.skip_hours.split(',')]
        config.setdefault('risk', {})['skip_hours'] = hours
    if args.buy_only:
        config.setdefault('analysis', {}).setdefault('signal_rules', {})['buy_only'] = True
    if args.st_period is not None:
        config.setdefault('analysis', {}).setdefault('indicators', {}).setdefault('supertrend', {})['atr_period'] = args.st_period
    if args.st_mult is not None:
        config.setdefault('analysis', {}).setdefault('indicators', {}).setdefault('supertrend', {})['multiplier'] = args.st_mult

    print("\n✅ Configuration loaded")
    if args.instrument:
        print(f"   Instrument override: {args.instrument.upper()}")
    if args.sl or args.tp or args.size:
        print(f"   CLI overrides: SL={args.sl or '(config)'} TP={args.tp or '(config)'} size={args.size or '(config)'}")
    if args.no_ema:
        print(f"   EMA filter: DISABLED")
    if args.no_sma:
        print(f"   SMA filter: DISABLED")
    if args.min_hold is not None:
        print(f"   Min hold: {args.min_hold}min before reverse-signal exit")
    if args.skip_hours is not None:
        print(f"   Skip hours (UTC): {args.skip_hours}")
    if args.buy_only:
        print(f"   Direction: BUY only")
    if args.st_period is not None or args.st_mult is not None:
        print(f"   Supertrend: ATR={args.st_period or '(config)'} mult={args.st_mult or '(config)'}")
    print(f"   Strategy: {config.get('analysis', {}).get('strategy', 'supertrend_vwap')}")
    print(f"   Instrument: {config.get('market_data', {}).get('instrument', 'GOLD')}")
    tf = config.get('market_data', {}).get('resample_to') or config.get('market_data', {}).get('timeframe', 'M5')
    sl = config.get('analysis', {}).get('sl_tp', {}).get('stop_loss_pips', '?')
    tp = config.get('analysis', {}).get('sl_tp', {}).get('take_profit_pips', '?')
    size = config.get('backtest', {}).get('position_size') or config.get('backtesting', {}).get('position_size', 1)
    print(f"   Timeframe: {tf} | SL: {sl} pts | TP: {tp} pts | Size: {size} unit(s)")
    
    # Resolve data path
    # --bars overrides the config file path: builds INSTRUMENT_TIMEFRAME_BARSbars.csv
    if args.bars is not None:
        instrument = config.get('market_data', {}).get('instrument', 'GOLD').upper()
        timeframe  = (config.get('market_data', {}).get('resample_to')
                      or config.get('market_data', {}).get('timeframe', 'M5')).upper()
        data_dir   = Path(__file__).parent.parent / 'cloud-function' / 'data'
        data_path  = str(data_dir / f'{instrument}_{timeframe}_{args.bars}bars.csv')
        config.setdefault('backtest', {})['data_path'] = data_path
        print(f"   Bars override: {args.bars:,} → {data_path}")
    else:
        data_path = config.get('backtest', {}).get('data_path', '../cloud-function/data/GOLD_M5_150000bars.csv')

    _ensure_data(data_path, config)
    df = load_historical_data(data_path)

    # Optionally resample to a higher timeframe (no extra download needed)
    resample_to = config.get('market_data', {}).get('resample_to', None)
    if resample_to and str(resample_to).upper() != 'M5':
        minutes = int(str(resample_to).upper().replace('M', ''))
        print(f"\n🔀 Resampling M5 → {resample_to.upper()}...")
        df = resample_ohlcv(df, minutes)
    
    # Apply --results-dir CLI override (takes priority over RESULTS_DIR env var)
    if args.results_dir:
        os.environ['RESULTS_DIR'] = args.results_dir

    # Build run_id: timestamp + active flags so each run is uniquely named
    if args.run_id:
        run_id = args.run_id
    else:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        flags = []
        if args.no_ema:          flags.append('noEMA')
        if args.no_sma:          flags.append('noSMA')
        if args.shuffle_signals: flags.append('shuffle')
        if args.st_period:       flags.append(f'st{args.st_period}')
        if args.st_mult:         flags.append(f'x{args.st_mult}')
        if args.min_hold:        flags.append(f'hold{args.min_hold}m')
        if args.skip_hours:      flags.append(f'skip{args.skip_hours.replace(",","-")}h')
        if args.buy_only:        flags.append('buyOnly')
        if args.sl:              flags.append(f'sl{int(args.sl)}')
        if args.tp:              flags.append(f'tp{int(args.tp)}')
        if args.size:            flags.append(f'sz{args.size}')
        run_id = '_'.join([ts] + flags) if flags else ts

    # Run backtest using skills
    results = asyncio.run(run_skills_backtest(df, config, shuffle_signals=args.shuffle_signals, run_id=run_id, buy_only=args.buy_only))
    
    # Print results
    print_results(results)
    
    # Reports already saved by ReportingSkill inside run_skills_backtest()
    prefix = config.get('backtest', {}).get('report_prefix', 'backtest')
    
    instrument = config.get('market_data', {}).get('instrument', 'backtest').upper()
    print("\n✅ Backtest complete!")
    print(f"\n📁 Results saved in: results/{instrument}/{run_id}/")
    print(f"   - report.json")
    print(f"   - report.html")
    print(f"   - trades.csv")
    print(f"   - analysis.xlsx")
    print("\n📚 NEXT STEPS:")
    print("   1. Open reports/backtest_report.html in browser")
    print("   2. Review trades in: reports/backtest_trades_skills.csv")
    print("   3. Add new strategies in: skills/analysis/analysis_skill.py")
    print("   4. Configure strategies in: config/trading_config.yaml")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⏸️  Backtest interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
