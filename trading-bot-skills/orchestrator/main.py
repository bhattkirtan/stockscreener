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

# How many historical candles to prefetch for indicator warm-up
WARMUP_CANDLES = 300


def load_config(config_path: str) -> dict:
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def setup_logging(config: dict, bot_id: str, run_id: str) -> None:
    """
    Configure root logger.
    If Firestore storage is enabled, attach FirestoreLogHandler so all INFO+
    logs stream to the bot_logs collection in real-time.
    """
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)-8s %(name)s — %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        stream=sys.stdout,
    )

    if not config.get('storage', {}).get('enabled', True):
        return

    project_id = (
        config.get('firestore', {}).get('project_id')
        or os.getenv('GCP_PROJECT_ID')
        or os.getenv('FIRESTORE_PROJECT_ID')
    )
    if not project_id:
        logger.warning("⚠️ GCP_PROJECT_ID not set — Firestore log streaming disabled")
        return

    try:
        from clients.log_publisher import LogPublisher, FirestoreLogHandler
        publisher = LogPublisher(bot_id=bot_id, run_id=run_id, project_id=project_id)
        handler = FirestoreLogHandler(publisher, level=logging.INFO)
        handler.setFormatter(logging.Formatter('%(asctime)s %(name)s %(message)s'))
        logging.getLogger().addHandler(handler)
        publisher.start_batch_writer()

        # Keep a reference so we can stop it on shutdown
        logging.getLogger().firestore_log_publisher = publisher
        logger.info("✅ Firestore log streaming enabled")
    except Exception as e:
        logger.warning(f"⚠️ Firestore log streaming setup failed: {e}")


def register_skills(orchestrator: TradingOrchestrator, config: dict, mode: str) -> None:
    """Register all enabled skills with the orchestrator."""

    if config.get('market_data', {}).get('enabled', True):
        orchestrator.register_skill('market_data', MarketDataSkill(config))

    if config.get('analysis', {}).get('enabled', True):
        orchestrator.register_skill('analysis', AnalysisSkill(config))

    if config.get('risk', {}).get('enabled', True):
        orchestrator.register_skill('risk', RiskSkill(config))

    if config.get('execution', {}).get('enabled', True):
        orchestrator.register_skill('execution', ExecutionSkill(config))

    if config.get('storage', {}).get('enabled', True):
        orchestrator.register_skill('storage', StorageSkill(config))

    if config.get('monitoring', {}).get('enabled', True):
        orchestrator.register_skill('monitoring', MonitoringSkill(config))

    if config.get('alerting', {}).get('enabled', True):
        orchestrator.register_skill('alerting', AlertingSkill(config))

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

    # Also wire the Capital client into ExecutionSkill if it doesn't have one yet
    if 'execution' in orchestrator.skills:
        skill = orchestrator.skills['execution']
        if not getattr(skill, 'rest_client', None):
            skill.rest_client = capital
            skill.mock_mode = False
            logger.info("✅ Wired Capital.com client into ExecutionSkill")

    # ── 2. Warm up indicators with historical candles ─────────────────────────
    logger.info(f"📥 Prefetching {WARMUP_CANDLES} {resolution} candles for warm-up...")
    try:
        candles = capital.get_historical_prices(
            epic=epic,
            resolution=resolution,
            max_bars=WARMUP_CANDLES,
        )
        logger.info(f"📊 Replaying {len(candles)} historical candles...")
        for candle in candles:
            await orchestrator.on_candle(candle)
        logger.info("✅ Indicator warm-up complete")
    except Exception as e:
        logger.warning(f"⚠️ Historical prefetch failed: {e} — continuing without warm-up")

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

            # Candle callback: adapt WS format → orchestrator.on_candle format
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

            ws.on_candle = on_candle

            await ws.connect()
            await ws.subscribe_ohlc([epic], resolution=resolution)
            logger.info(f"✅ Streaming {resolution} candles for {epic}")

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
