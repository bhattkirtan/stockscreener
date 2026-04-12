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
from contextlib import suppress
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


def register_skills(orchestrator: TradingOrchestrator, config: dict, mode: str, bot_id: str = None) -> None:
    """Register all enabled skills with the orchestrator."""
    # Inject bot_id into monitoring config so heartbeats are keyed by the correct bot
    if bot_id:
        config.setdefault('monitoring', {})['bot_id'] = bot_id

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


async def _poll_positions(
    capital,
    orchestrator: TradingOrchestrator,
    epic: str,
    interval: int = 10,
) -> None:
    """
    Track position lifecycle via REST activity polling.

    Capital.com WebSocket does not support position/trade events — only
    OHLC candles and quotes are available over the stream. Position close
    detection uses two REST mechanisms:

      1. Activity poll every `interval` seconds (default 10 s):
         GET /api/v1/history/activity — catches POSITION_OPENED and
         POSITION_CLOSED events quickly after they occur.

      2. Full positions reconciliation every 60 s:
         GET /api/v1/positions — source-of-truth fallback for any event
         the activity poll might have missed during a connectivity gap.
    """
    known: dict[str, dict] = {}
    # Tracks (deal_id, action_type) pairs already processed to prevent
    # double-firing when the activity lookback window overlaps polls.
    processed: set[str] = set()

    def _positions_for_epic(raw: list) -> list[tuple[str, dict]]:
        result = []
        for p in raw:
            market_epic = p.get('market', {}).get('epic', '')
            if market_epic.upper() != epic.upper():
                continue
            pos = p.get('position', p)
            deal_id = pos.get('dealId')
            if deal_id:
                result.append((deal_id, pos))
        return result

    async def _persist_open_position(deal_id: str, pos: dict, upl: float = 0.0) -> None:
        """Write/update a broker position in SQLite active_positions via StorageSkill."""
        if 'storage' not in orchestrator.skills:
            return
        try:
            await orchestrator.skills['storage'].save_open_position(
                deal_id=deal_id,
                epic=epic,
                direction=pos.get('direction', 'BUY'),
                level=float(pos.get('level') or pos.get('entry_price') or 0.0),
                size=float(pos.get('size') or 0.0),
                stop_level=pos.get('stopLevel') or pos.get('stop_loss'),
                profit_level=pos.get('profitLevel') or pos.get('limitLevel') or pos.get('take_profit'),
                upl=upl,
            )
        except Exception as e:
            logger.warning(f"⚠️ Failed to persist position {deal_id} to storage: {e}")

    async def _handle_close(deal_id: str, close_level: float, description: str, pnl: float = None) -> None:
        """Fire on_position_closed for a deal that just closed."""
        pos = known.pop(deal_id, None)
        direction = (pos.get('direction', 'BUY') if pos else 'BUY')
        entry = float(pos.get('level', 0.0) if pos else 0.0)
        size  = float(pos.get('size',  0.0) if pos else 0.0)

        # Derive close reason from activity description
        desc_upper = description.upper()
        if any(w in desc_upper for w in ('STOP', ' SL')):
            close_reason = 'SL_HIT'
        elif any(w in desc_upper for w in ('LIMIT', 'TAKE PROFIT', ' TP', 'PROFIT')):
            close_reason = 'TP_HIT'
        else:
            close_reason = 'SIGNAL'

        # Calculate P&L from entry/close if not supplied by caller
        if pnl is None:
            if entry and close_level and size:
                direction_mult = 1.0 if direction == 'BUY' else -1.0
                pnl = (close_level - entry) * direction_mult * size
            else:
                pnl = 0.0

        logger.info(f"🎯 Position closed via activity: {deal_id} reason={close_reason} @ {close_level} pnl={pnl:.2f}")
        await orchestrator.on_position_closed(
            deal_id=deal_id,
            direction=direction,
            close_reason=close_reason,
            pnl=pnl,
            entry_price=entry,
            close_price=close_level,
        )

    # ── Startup seed: pull existing open positions from REST ──────────────────
    try:
        for deal_id, pos in _positions_for_epic(capital.get_open_positions() or []):
            known[deal_id] = pos
            await _persist_open_position(deal_id, pos)
            # Mark as already-seen so the activity poll doesn't re-fire OPEN
            processed.add(f"{deal_id}:POSITION_OPENED")
        logger.info(f"📋 Tracking {len(known)} open position(s) for {epic}")
    except Exception as e:
        logger.warning(f"⚠️ Initial positions fetch failed: {e}")

    # ── Poll loop ─────────────────────────────────────────────────────────────
    reconcile_counter = 0
    reconcile_every = max(1, 60 // interval)  # every ~60 s

    try:
        while True:
            await asyncio.sleep(interval)

            # ── Primary: activity poll ────────────────────────────────────────
            try:
                # Look back 3× the interval to cover any gap between polls
                activities = capital.get_activity(
                    last_period_seconds=interval * 3,
                    epic=epic,
                )
                for activity in activities:
                    if activity.get('epic', '').upper() != epic.upper():
                        continue
                    details = activity.get('details', {})
                    description = activity.get('description', '')

                    for action in details.get('actions', []):
                        action_type = action.get('actionType', '')
                        deal_id = action.get('dealId') or activity.get('dealId', '')
                        if not deal_id:
                            continue
                        key = f"{deal_id}:{action_type}"
                        if key in processed:
                            continue
                        processed.add(key)

                        if action_type == 'POSITION_OPENED':
                            if deal_id not in known:
                                pos = {
                                    'dealId':      deal_id,
                                    'direction':   details.get('direction', 'BUY'),
                                    'level':       float(details.get('level') or 0.0),
                                    'size':        float(details.get('size') or 0.0),
                                    'stopLevel':   details.get('stopLevel'),
                                    'profitLevel': details.get('limitLevel'),
                                }
                                known[deal_id] = pos
                                await _persist_open_position(deal_id, pos)
                                logger.info(f"📈 New position tracked via activity: {deal_id}")

                        elif action_type in ('POSITION_CLOSED', 'POSITION_PARTIALLY_CLOSED'):
                            close_level = float(details.get('level') or 0.0)
                            activity_pnl = details.get('profit')
                            pnl = float(activity_pnl) if activity_pnl is not None else None
                            await _handle_close(deal_id, close_level, description, pnl=pnl)

            except Exception as e:
                logger.warning(f"⚠️ Activity poll error: {e}")

            # ── Fallback: full positions reconciliation every ~60 s ───────────
            reconcile_counter += 1
            if reconcile_counter >= reconcile_every:
                reconcile_counter = 0
                try:
                    raw_positions = capital.get_open_positions() or []
                    current: dict[str, dict] = {
                        deal_id: pos
                        for deal_id, pos in _positions_for_epic(raw_positions)
                    }
                    logger.debug(f"🔄 REST reconcile: {len(current)} open position(s) for {epic} (account total: {len(raw_positions)})")
                    # Positions gone from broker but still in known → missed close
                    for deal_id, pos in list(known.items()):
                        if deal_id not in current:
                            close_key = f"{deal_id}:POSITION_CLOSED"
                            if close_key not in processed:
                                processed.add(close_key)
                                logger.warning(f"📉 Position closed (REST fallback): {deal_id}")
                                await _handle_close(deal_id, 0.0, '')
                    # Positions at broker not in known → missed open (or update live P&L)
                    for deal_id, pos in current.items():
                        upl = float(pos.get('upl') or 0.0)
                        if deal_id not in known:
                            known[deal_id] = pos
                            await _persist_open_position(deal_id, pos, upl=upl)
                            logger.warning(f"📈 Position tracked (REST fallback): {deal_id}")
                            # Sync risk skill so it knows this position exists and blocks new entries
                            if 'risk' in orchestrator.skills:
                                risk = orchestrator.skills['risk']
                                if not risk.has_open_position:
                                    risk.has_open_position = True
                                    risk.open_position_deal_id = deal_id
                                    risk.open_position_direction = pos.get('direction', 'BUY')
                                    logger.warning(
                                        f"⚠️ Risk state synced from REST reconcile: "
                                        f"{deal_id} dir={risk.open_position_direction}"
                                    )
                        else:
                            # Update live P&L and current price in DB
                            known[deal_id] = pos
                            await _persist_open_position(deal_id, pos, upl=upl)
                except Exception as e:
                    logger.warning(f"⚠️ REST reconciliation error: {e}")

    except asyncio.CancelledError:
        raise


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
    market_cfg = config.get('market_data', {})
    epic = (
        exec_cfg.get('epic')
        or market_cfg.get('epic')
        or market_cfg.get('instrument')
    )
    if not epic:
        raise ValueError("No epic/instrument configured. Set market_data.instrument in your YAML or pass --instrument.")

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
        def _epic_positions(raw: list) -> list[dict]:
            return [p.get('position', p) for p in raw
                    if p.get('market', {}).get('epic', '').upper() == epic.upper()]

        all_positions = capital.get_open_positions() or []
        open_positions = _epic_positions(all_positions)
        if open_positions:
            if len(open_positions) > 1:
                logger.warning(
                    f"⚠️ Found {len(open_positions)} open {epic} position(s) from previous session — "
                    f"expected 1. Extra positions may need manual cleanup. "
                    f"Deal IDs: {[p.get('dealId') for p in open_positions]}"
                )
            else:
                logger.warning(
                    f"⚠️ Found {len(open_positions)} open position(s) for {epic} from previous session — "
                    "blocking new entries until they close"
                )
            if 'risk' in orchestrator.skills:
                risk = orchestrator.skills['risk']
                risk.has_open_position = True
                # Use the most recent position (last in list) as the canonical tracked deal.
                # All positions are seeded into _poll_positions.known for full reconciliation.
                pos = open_positions[-1]
                risk.open_position_deal_id = pos.get('dealId')
                risk.open_position_direction = pos.get('direction', 'BUY')
                logger.info(
                    f"📌 Tracking deal {risk.open_position_deal_id} dir={risk.open_position_direction} as canonical position"
                )
                # Startup flip gate: already in a live position — mark as satisfied
                # so normal entry logic resumes after this position closes
                risk._startup_flip_seen = True
        else:
            logger.info(f"✅ No open positions for {epic} — starting clean, waiting for first trend flip")
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

            # Live tick quote callback → Supertrend tick exit
            async def on_quote(quote_data: dict) -> None:
                mid = quote_data.get('mid')
                if mid and 'analysis' in orchestrator.skills:
                    ts = quote_data.get('time')
                    await orchestrator.skills['analysis'].on_price_tick(mid, ts)

            ws.on_candle = on_candle
            ws.on_h1_candle = on_h1_candle
            ws.on_quote = on_quote

            await ws.connect()
            await ws.subscribe_ohlc([epic], resolution=resolution)
            await ws.subscribe_quotes([epic])
            if 'analysis' in orchestrator.skills and orchestrator.skills['analysis'].require_h1_bb:
                await ws.subscribe_ohlc([epic], resolution='HOUR')
            logger.info(f"✅ Streaming {resolution} candles + live quotes for {epic}")

            # Start position tracker: activity poll (10 s) + REST reconciliation (60 s)
            poll_task = asyncio.create_task(
                _poll_positions(capital, orchestrator, epic, interval=10)
            )

            retry = 0  # Reset backoff on successful connect
            try:
                await ws.run()  # Blocks until disconnect
            finally:
                poll_task.cancel()
                with suppress(asyncio.CancelledError):
                    await poll_task

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
    parser.add_argument(
        '--instrument',
        default=None,
        help='Instrument override (e.g. GOLD, US100). Loads config/instruments/<INSTRUMENT>.yaml if available.',
    )
    parser.add_argument(
        '--timeframe',
        default=None,
        help='Timeframe override (e.g. M5, H1).',
    )
    parser.add_argument(
        '--bot-id',
        dest='bot_id',
        default=None,
        help='Explicit bot ID used for logging and status (e.g. gold_m5_bot). '
             'If not set, derived from config bot.name.',
    )
    parser.add_argument(
        '--quantity',
        type=float,
        default=None,
        help='Position size (contracts/lots) override. Overrides the instrument config value.',
    )
    args = parser.parse_args()

    config = load_config(args.config)

    # Apply CLI instrument/timeframe overrides
    if args.instrument:
        instr_upper = args.instrument.upper()
        config.setdefault('market_data', {})['instrument'] = instr_upper
        # Load instrument-specific config overlay if it exists
        inst_path = Path(__file__).parent.parent / 'config' / 'instruments' / f'{instr_upper}.yaml'
        if inst_path.exists():
            import yaml as _yaml
            with open(inst_path) as _f:
                inst_cfg = _yaml.safe_load(_f)
            # Deep-merge: instrument config values override base config
            for k, v in inst_cfg.items():
                if isinstance(v, dict) and isinstance(config.get(k), dict):
                    config[k].update(v)
                else:
                    config[k] = v
    if args.timeframe:
        config.setdefault('market_data', {})['timeframe'] = args.timeframe.upper()
    if args.quantity is not None:
        config.setdefault('execution', {})['position_size'] = args.quantity
        config.setdefault('risk', {})['position_size'] = args.quantity

    # Bot identity for logging / Firestore
    # Prefer explicit --bot-id CLI arg; fall back to deriving from config name
    if args.bot_id:
        bot_id = args.bot_id
        bot_name = bot_id
    else:
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
    register_skills(orchestrator, config, mode=args.mode, bot_id=bot_id)
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
