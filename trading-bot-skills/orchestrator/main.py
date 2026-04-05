"""
Trading Bot Main Entry Point

Modes:
  live      — real Capital.com account, real money
  demo      — Capital.com demo account, paper trading
  backtest  — historical CSV data (uses run_skills_backtest.py instead)

Environment variables (or set in config YAML under capital_com:):
  CAPITAL_API_KEY
  CAPITAL_USERNAME
  CAPITAL_PASSWORD
  CAPITAL_ENVIRONMENT   (demo | live)
  GCP_PROJECT_ID        (for Firestore log streaming)
"""
import asyncio
import argparse
import logging
import sys
import os
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from orchestrator.trading_orchestrator import TradingOrchestrator
from skills.risk.risk_skill import RiskSkill
from skills.market_data import MarketDataSkill
from skills.analysis import AnalysisSkill
from skills.execution import ExecutionSkill
from skills.storage import StorageSkill
from skills.monitoring import MonitoringSkill
from skills.alerting import AlertingSkill
from skills.backtesting import BacktestingSkill
from skills.reporting import ReportingSkill
import yaml

logger = logging.getLogger(__name__)

# Map YAML timeframe names → Capital.com resolution strings
TIMEFRAME_TO_RESOLUTION = {
    'M1': 'MINUTE',
    'M5': 'MINUTE_5',
    'M15': 'MINUTE_15',
    'M30': 'MINUTE_30',
    'H1': 'HOUR',
    'H4': 'HOUR_4',
    'D1': 'DAY',
}

# Safety multiplier applied to all indicator periods when calculating warm-up bar counts.
# 3× ensures the rolling window is fully populated and indicator values are stable.
WARMUP_MULTIPLIER = 3


def load_config(config_path: str) -> dict:
    import re

    with open(config_path, 'r') as f:
        raw = f.read()

    # Expand ${VAR} placeholders from environment
    def _expand(match):
        value = os.getenv(match.group(1), '')
        return value if value else match.group(0)  # leave unexpanded if not set

    expanded = re.sub(r'\$\{([^}]+)\}', _expand, raw)
    return yaml.safe_load(expanded)


def setup_logging(config: dict, bot_id: str, run_id: str) -> None:
    """
    Configure root logger.
    If storage is enabled, attach FirestoreLogHandler so all INFO+
    logs stream to the bot_logs collection in SQLite in real-time.
    """
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)-8s %(name)s — %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        stream=sys.stdout,
    )

    if not config.get('storage', {}).get('enabled', True):
        return

    try:
        from clients.log_publisher import LogPublisher, FirestoreLogHandler
        publisher = LogPublisher(bot_id=bot_id, run_id=run_id)
        handler = FirestoreLogHandler(publisher, level=logging.INFO)
        handler.setFormatter(logging.Formatter('%(asctime)s %(name)s %(message)s'))
        logging.getLogger().addHandler(handler)
        publisher.start_batch_writer()

        # Keep a reference so we can stop it on shutdown
        logging.getLogger().firestore_log_publisher = publisher
        logger.info("✅ SQLite log streaming enabled")
    except Exception as e:
        logger.warning(f"⚠️ Log streaming setup failed: {e}")


def register_skills(orchestrator: TradingOrchestrator, config: dict, mode: str) -> None:
    """Register all enabled skills with the orchestrator."""

    # Single source of truth: propagate risk pip/SL/TP into analysis.sl_tp
    # so AnalysisSkill reads the same values without duplication in YAML.
    _risk = config.get('risk', {})
    _sl_tp = config.setdefault('analysis', {}).setdefault('sl_tp', {})
    for _key in ('pip_size', 'stop_loss_pips', 'take_profit_pips'):
        if _key in _risk:
            _sl_tp[_key] = _risk[_key]

    market_data_skill = None
    if config.get('market_data', {}).get('enabled', True):
        market_data_skill = MarketDataSkill(config.get('market_data', config))
        orchestrator.register_skill('market_data', market_data_skill)

    if config.get('analysis', {}).get('enabled', True):
        orchestrator.register_skill('analysis', AnalysisSkill(
            config.get('analysis', config), market_data_skill=market_data_skill
        ))

    if config.get('risk', {}).get('enabled', True):
        orchestrator.register_skill('risk', RiskSkill(config.get('risk', config)))

    if config.get('execution', {}).get('enabled', True):
        orchestrator.register_skill('execution', ExecutionSkill(config.get('execution', config)))

    if config.get('storage', {}).get('enabled', True):
        orchestrator.register_skill('storage', StorageSkill(config.get('storage', config)))

    if config.get('monitoring', {}).get('enabled', True):
        orchestrator.register_skill('monitoring', MonitoringSkill(config.get('monitoring', config)))

    if config.get('alerting', {}).get('enabled', True):
        orchestrator.register_skill('alerting', AlertingSkill(config.get('alerting', config)))

    if mode == 'backtest' and config.get('backtesting', {}).get('enabled', True):
        orchestrator.register_skill('backtesting', BacktestingSkill(config))

    if config.get('reporting', {}).get('enabled', True):
        orchestrator.register_skill('reporting', ReportingSkill(config))

    logger.info(f"✅ Registered {len(orchestrator.skills)} skills")


async def run_live_mode(config: dict, orchestrator: TradingOrchestrator, environment: str) -> None:
    """
    Live / demo trading loop:
      1. Authenticate with Capital.com
      2. Prefetch historical candles to warm up indicators
      3. Connect WebSocket and stream live candles
      4. Auto-reconnect on drop (exponential backoff, max 60 s)
    """
    from clients.capital_api import CapitalAPIClient
    from clients.capital_websocket import CapitalWebSocketClient

    exec_cfg = config.get('execution', {})
    timeframe = config.get('market_data', {}).get('timeframe', 'M5')
    resolution = TIMEFRAME_TO_RESOLUTION.get(timeframe, 'MINUTE_5')
    epic = exec_cfg.get('epic') or config.get('market_data', {}).get('epic', 'CS.D.CFDGOLD.CFD.IP')

    # ── 1. Authenticate ───────────────────────────────────────────────────────
    logger.info(f"🔐 Authenticating with Capital.com ({environment.upper()})...")
    capital = CapitalAPIClient(
        username=exec_cfg.get('identifier'),   # config uses 'identifier' not 'username'
        password=exec_cfg.get('password'),
        api_key=exec_cfg.get('api_key'),
        environment=environment,
    )
    tokens = capital.get_tokens()
    logger.info("✅ Authentication successful")

    # Wire Capital client + epic into ExecutionSkill
    if 'execution' in orchestrator.skills:
        skill = orchestrator.skills['execution']
        if not getattr(skill, 'rest_client', None):
            skill.rest_client = capital
            skill.mock_mode = False
            logger.info("✅ Wired Capital.com client into ExecutionSkill")
        skill.epic = epic  # ensure skill uses the same epic resolved above

    # ── Restore state: check for positions left open from a previous session ────
    try:
        open_positions = capital.get_open_positions()
        if open_positions:
            logger.warning(
                f"⚠️ Found {len(open_positions)} open position(s) from previous session — "
                "blocking new entries until they close"
            )
            if 'risk' in orchestrator.skills:
                orchestrator.skills['risk'].has_open_position = True
        else:
            logger.info("✅ No open positions — starting clean")
    except Exception as e:
        logger.warning(f"⚠️ Could not check open positions on startup: {e} — assuming none open")

    # ── 2. Calculate warm-up bar counts from configured indicator periods ──────
    # All counts are derived at runtime so changing any period in the YAML
    # automatically adjusts how many candles are fetched — no code change needed.
    m5_warmup = 300  # safe fallback
    h1_warmup  = 0
    daily_warmup = 0

    if 'analysis' in orchestrator.skills:
        a = orchestrator.skills['analysis']

        # M5: largest period across all enabled indicators × WARMUP_MULTIPLIER
        # macd_slow + macd_signal_period covers the longest MACD lookback
        m5_min_bars = max(
            a.sma_slow_period,
            a.bb_period,
            a.st_period,
            a.macd_slow + a.macd_signal_period,
            a.rsi_period,
            a.stoch_k_period,
        )
        m5_warmup = min(m5_min_bars * WARMUP_MULTIPLIER, 1000)  # Capital.com max = 1000

        # H1 BB: bb_period × WARMUP_MULTIPLIER
        if a.require_h1_bb:
            h1_warmup = min(a.mtf_h1_bb_period * WARMUP_MULTIPLIER, 1000)

        # Daily SMA: sma_period × WARMUP_MULTIPLIER
        if a.require_daily_bias:
            daily_warmup = min(a.mtf_daily_sma * WARMUP_MULTIPLIER, 1000)

        logger.info(
            f"📐 Warm-up bars — M5: {m5_warmup}  H1: {h1_warmup}  Daily: {daily_warmup}"
        )

    # Keep market_data buffer large enough to hold all warm-up candles
    if 'market_data' in orchestrator.skills:
        orchestrator.skills['market_data'].buffer_size = m5_warmup

    # ── 2b. M5 warm-up (buffers candles only — no signals/orders) ────────────
    orchestrator.warming_up = True
    try:
        logger.info(f"📥 Fetching {m5_warmup} {resolution} candles for M5 warm-up...")
        candles = capital.get_historical_prices(
            epic=epic, resolution=resolution, max_bars=m5_warmup,
        )
        logger.info(f"📊 Replaying {len(candles)} candles into buffer...")
        for candle in candles:
            await orchestrator.on_candle(candle)
        logger.info(f"✅ M5 warm-up complete — {len(candles)} candles buffered")
    except Exception as e:
        logger.warning(f"⚠️ M5 prefetch failed: {e} — continuing without warm-up")
    finally:
        orchestrator.warming_up = False

    # ── 2c. Higher-timeframe data (MTF confluence) ────────────────────────────
    if 'analysis' in orchestrator.skills:
        analysis_skill = orchestrator.skills['analysis']

        if h1_warmup > 0:
            logger.info(f"📥 Fetching {h1_warmup} H1 candles for H1 BB (period={analysis_skill.mtf_h1_bb_period})...")
            try:
                h1_candles = capital.get_historical_prices(
                    epic=epic, resolution='HOUR', max_bars=h1_warmup,
                )
                analysis_skill.load_h1_history(h1_candles)
            except Exception as e:
                logger.warning(f"⚠️ H1 fetch failed: {e} — H1 BB gate will be skipped")

        if daily_warmup > 0:
            logger.info(f"📥 Fetching {daily_warmup} Daily candles for Daily SMA (period={analysis_skill.mtf_daily_sma})...")
            try:
                daily_candles = capital.get_historical_prices(
                    epic=epic, resolution='DAY', max_bars=daily_warmup,
                )
                analysis_skill.load_daily_history(daily_candles)
            except Exception as e:
                logger.warning(f"⚠️ Daily fetch failed: {e} — Daily SMA gate will be skipped")

    logger.info("🟢 Warm-up done — live signal generation enabled")

    # ── 3. WebSocket loop with auto-reconnect ─────────────────────────────────
    max_retries = 10
    retry = 0

    while orchestrator.running and retry < max_retries:
        try:
            logger.info(f"🌐 Connecting to Capital.com WebSocket (attempt {retry + 1})...")

            # Refresh tokens before each connect attempt
            tokens = capital.get_tokens()
            ws = CapitalWebSocketClient(
                cst=tokens['CST'],
                security_token=tokens['X-SECURITY-TOKEN'],
            )

            # M5 candle callback → main trading pipeline
            async def on_candle(candle_data: dict) -> None:
                candle = {
                    'timestamp': candle_data['time'].isoformat() if candle_data.get('time') else '',
                    'open':  candle_data.get('open', 0),
                    'high':  candle_data.get('high', 0),
                    'low':   candle_data.get('low', 0),
                    'close': candle_data.get('close', 0),
                    'volume': 0,
                }
                await orchestrator.on_candle(candle)

            # H1 candle callback → update H1 BB on analysis skill
            async def on_h1_candle(candle_data: dict) -> None:
                if 'analysis' in orchestrator.skills:
                    candle = {
                        'timestamp': candle_data['time'].isoformat() if candle_data.get('time') else '',
                        'open':  candle_data.get('open', 0),
                        'high':  candle_data.get('high', 0),
                        'low':   candle_data.get('low', 0),
                        'close': candle_data.get('close', 0),
                    }
                    orchestrator.skills['analysis'].update_h1_candle(candle)
                    logger.debug(f"📊 H1 BB updated: close={candle['close']}")

            # Position update callback: SL/TP/manual close → orchestrator
            async def on_position_update(update: dict) -> None:
                await orchestrator.on_position_closed(
                    deal_id=update['deal_id'],
                    direction=update['direction'],
                    close_reason=update['close_reason'],
                    pnl=update['pnl'],
                    close_price=update['close_price'],
                )

            ws.on_candle = on_candle
            ws.on_h1_candle = on_h1_candle
            ws.on_position_update = on_position_update

            await ws.connect()
            await ws.subscribe_ohlc([epic], resolution=resolution)
            if 'analysis' in orchestrator.skills and orchestrator.skills['analysis'].require_h1_bb:
                await ws.subscribe_ohlc([epic], resolution='HOUR')
            await ws.subscribe_trades()
            logger.info(f"✅ Streaming {resolution} + H1 candles + trade events for {epic}")

            retry = 0  # Reset backoff on successful connect
            await ws.run()  # Blocks until disconnect

        except asyncio.CancelledError:
            logger.info("⏸️ WebSocket task cancelled — shutting down")
            break

        except Exception as e:
            retry += 1
            if retry >= max_retries:
                logger.error(f"❌ WebSocket failed {max_retries} times — giving up")
                break

            delay = min(2 ** retry, 60)
            logger.error(f"❌ WebSocket error (attempt {retry}): {e}. Reconnecting in {delay}s...")
            await asyncio.sleep(delay)

    logger.info("🛑 WebSocket loop exited")


async def main() -> None:
    parser = argparse.ArgumentParser(description='Trading Bot — Skill-Based Architecture')
    parser.add_argument(
        '--config',
        default='config/trading_config.yaml',
        help='Path to configuration YAML',
    )
    parser.add_argument(
        '--mode',
        choices=['live', 'demo', 'backtest'],
        default='demo',
        help='live = real money | demo = paper trading | backtest = historical data',
    )
    args = parser.parse_args()

    config = load_config(args.config)

    # Bot identity for logging / Firestore
    bot_name = config.get('bot', {}).get('name', 'gold_m5_bot')
    bot_id = bot_name.lower().replace(' ', '_')
    run_id = datetime.now().strftime('%Y%m%d_%H%M%S')

    # ── Logging setup ─────────────────────────────────────────────────────────
    setup_logging(config, bot_id=bot_id, run_id=run_id)

    logger.info(f"{'='*60}")
    logger.info(f"  {bot_name}")
    logger.info(f"  Mode: {args.mode.upper()}  |  Run: {run_id}")
    logger.info(f"{'='*60}")

    # ── Orchestrator + skills ─────────────────────────────────────────────────
    orchestrator = TradingOrchestrator(config)
    register_skills(orchestrator, config, mode=args.mode)
    await orchestrator.start()

    # ── Mode dispatch ─────────────────────────────────────────────────────────
    try:
        if args.mode == 'backtest':
            logger.info("ℹ️  For backtesting use: python run_skills_backtest.py")

        elif args.mode in ('live', 'demo'):
            environment = 'live' if args.mode == 'live' else 'demo'
            if args.mode == 'live':
                logger.warning("⚠️  LIVE MODE — real money trades will be placed")

            await run_live_mode(config, orchestrator, environment)

    except KeyboardInterrupt:
        logger.info("\n⏸️  Keyboard interrupt — shutting down...")

    finally:
        await orchestrator.stop()

        # Flush any remaining Firestore logs
        publisher = getattr(logging.getLogger(), 'firestore_log_publisher', None)
        if publisher:
            publisher.stop_batch_writer()

        logger.info("✅ Bot stopped")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1)
