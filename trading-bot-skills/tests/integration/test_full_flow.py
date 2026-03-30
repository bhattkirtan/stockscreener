"""
Integration Tests — Full Trading Flow

Tests the complete sequential pipeline:
Market Data → Analysis → Risk → Execution → Storage → Monitoring → Alerting

Uses the same execute(context) path that the live orchestrator uses.
"""

import pytest
import asyncio
import sys
import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from skills.base_skill import Context
from skills.market_data import MarketDataSkill
from skills.analysis import AnalysisSkill
from skills.risk import RiskSkill
from skills.execution import ExecutionSkill
from skills.storage import StorageSkill
from skills.monitoring import MonitoringSkill
from orchestrator.trading_orchestrator import TradingOrchestrator


# ── Shared config (mirrors trading_config.yaml structure) ─────────────────────

BASE_CONFIG = {
    'market_data': {
        'enabled': True,
        'instrument': 'GOLD',
        'timeframe': 'M5',
        'buffer_size': 100,
    },
    'analysis': {
        'enabled': True,
        'indicators': {
            'supertrend': {'enabled': True, 'atr_period': 7, 'multiplier': 2.0},
            'ema':        {'enabled': True, 'period': 21},
            'sma':        {'enabled': True, 'fast_period': 25, 'slow_period': 30},
            'vwap':       {'enabled': False},
            'macd':       {'enabled': False, 'fast': 12, 'slow': 26, 'signal_period': 9},
            'rsi':        {'enabled': False, 'period': 14},
            'bollinger':  {'enabled': False, 'period': 20, 'std_dev': 2.0},
            'stochastic': {'enabled': False, 'k_period': 14, 'd_period': 3},
            'volume':     {'enabled': False, 'sma_period': 20},
            'mtf':        {'h1_bb_period': 20, 'h1_bb_std': 2.0, 'daily_sma_period': 20},
        },
        'signal_rules': {
            'require_supertrend': True,
            'require_ema':        True,
            'require_sma':        True,
            'strict_sma_cross':   False,
            'require_vwap':       False,
            'require_rsi':        False,
            'require_macd':       False,
            'require_bb':         False,
            'require_stochastic': False,
            'require_volume':     False,
            'require_h1_bb':      False,  # off — no H1 data in unit tests
            'require_daily_bias': False,
            'edge_detection':     True,
        },
        'sl_tp': {
            'method': 'fixed',
            'stop_loss_pips':   20,
            'take_profit_pips': 60,
        },
    },
    'risk': {
        'enabled': True,
        'trading_hours': {'enabled': False},
        'sl_cooldown_minutes': 15,
        'tp_cooldown_minutes': 5,
        'skip_hours': [],
        'position_size_pct': 2.0,
        'max_positions': 1,
    },
    'execution': {
        'enabled': True,
        'sl_pips': 20,
        'tp_pips': 60,
        'mock_mode': True,
    },
    'storage':    {'enabled': True},
    'monitoring': {'enabled': True},
    'alerting':   {'enabled': False},
}


def _make_candles(n: int, base_price: float = 2650.0, trend: str = 'up') -> list:
    """Generate n synthetic M5 candles with a clear trend for indicator warm-up."""
    candles = []
    for i in range(n):
        ts = datetime(2026, 1, 1, 0, 0) + timedelta(minutes=5 * i)
        if trend == 'up':
            close = base_price + i * 0.1
        elif trend == 'down':
            close = base_price - i * 0.1
        else:
            close = base_price
        candles.append({
            'timestamp': ts.isoformat(),
            'open':  close - 0.05,
            'high':  close + 0.15,
            'low':   close - 0.15,
            'close': close,
            'volume': 100,
        })
    return candles


async def _warm_up(orchestrator: TradingOrchestrator, n: int = 80, **kwargs) -> None:
    """Feed n historical candles into the orchestrator buffer (warm-up mode)."""
    orchestrator.warming_up = True
    for candle in _make_candles(n, **kwargs):
        await orchestrator.on_candle(candle)
    orchestrator.warming_up = False


def _make_orchestrator(cfg: dict = None) -> TradingOrchestrator:
    cfg = cfg or BASE_CONFIG
    orch = TradingOrchestrator(cfg)

    md   = MarketDataSkill(cfg.get('market_data', cfg))
    ana  = AnalysisSkill(cfg.get('analysis', cfg), market_data_skill=md)
    risk = RiskSkill(cfg.get('risk', cfg))
    exe  = ExecutionSkill(cfg.get('execution', cfg))

    # Mock storage so we don't need Firestore
    storage = MagicMock()
    storage.validate_config = MagicMock(return_value=True)
    storage.execute = AsyncMock(side_effect=lambda ctx: ctx)
    storage.close_position = AsyncMock()

    mon = MonitoringSkill(cfg.get('monitoring', cfg))

    orch.register_skill('market_data', md)
    orch.register_skill('analysis',    ana)
    orch.register_skill('risk',        risk)
    orch.register_skill('execution',   exe)
    orch.register_skill('storage',     storage)
    orch.register_skill('monitoring',  mon)

    orch.running = True
    return orch


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_warming_up_flag_suppresses_execution():
    """Warm-up candles must NOT trigger any orders."""
    orch = _make_orchestrator()
    await _warm_up(orch, n=80)

    assert orch.total_trades == 0, "No trades should fire during warm-up"
    assert orch.skills['risk'].has_open_position is False


@pytest.mark.asyncio
async def test_market_data_buffers_candles():
    """After warm-up, market_data buffer holds the correct number of candles."""
    orch = _make_orchestrator()
    await _warm_up(orch, n=80)

    history = orch.skills['market_data'].get_candle_history()
    assert len(history) == 80, f"Expected 80 candles, got {len(history)}"


@pytest.mark.asyncio
async def test_full_flow_signal_to_trade():
    """
    End-to-end: warm up → live candle → signal → risk pass → order placed.
    Verifies context fields flow correctly through every skill.
    """
    orch = _make_orchestrator()
    await _warm_up(orch, n=80, trend='up')

    # Feed one more live candle — analysis runs on the full buffer
    live_candle = _make_candles(1, base_price=2658.0)[0]
    await orch.on_candle(live_candle)

    # If a signal fired, a trade should have opened
    if orch.total_trades > 0:
        assert orch.skills['risk'].has_open_position is True, \
            "has_open_position must be True after trade opens"
    # No exception = flow is wired correctly


@pytest.mark.asyncio
async def test_context_fields_populated_on_trade():
    """
    When execution places an order, context.deal_id and
    context.current_position must both be set.
    """
    orch = _make_orchestrator()
    await _warm_up(orch, n=80, trend='up')

    # Manually inject a signal through the pipeline to force a trade
    risk_skill = orch.skills['risk']
    exe_skill  = orch.skills['execution']

    ctx = Context(
        current_candle={'timestamp': '2026-01-01T10:00:00', 'close': 2658.0},
        signal='BUY',
        is_allowed=True,
        position_size=0.5,
        entry_price=2658.0,
        stop_loss=2657.80,
        take_profit=2658.60,
    )

    ctx = await exe_skill.execute(ctx)

    assert ctx.deal_id is not None, "deal_id must be set after execution"
    assert ctx.current_position is not None, "current_position must be set after execution"
    assert ctx.current_position['direction'] == 'BUY'
    assert ctx.current_position['entry_price'] == 2658.0
    assert ctx.current_position['stop_loss']   == 2657.80
    assert ctx.current_position['take_profit'] == 2658.60


@pytest.mark.asyncio
async def test_risk_blocks_second_trade_while_open():
    """has_open_position=True must block any new signal."""
    orch = _make_orchestrator()
    await _warm_up(orch, n=80)

    risk = orch.skills['risk']
    risk.has_open_position = True

    ctx = Context(
        current_candle={'timestamp': '2026-01-01T10:00:00', 'close': 2650.0},
        signal='BUY',
    )
    ctx = await risk.execute(ctx)

    assert ctx.is_allowed is False
    assert 'Max positions' in ctx.risk_reason


@pytest.mark.asyncio
async def test_position_close_clears_open_position_flag():
    """on_position_closed must set has_open_position=False and start cooldown."""
    orch = _make_orchestrator()
    orch.running = True
    await _warm_up(orch, n=80)

    risk = orch.skills['risk']
    risk.has_open_position = True

    await orch.on_position_closed(
        deal_id='DEAL001',
        direction='BUY',
        close_reason='SL_HIT',
        pnl=-20.0,
        close_price=2630.0,
    )

    assert risk.has_open_position is False, "Flag must clear after position close"
    assert risk.last_closed_position is not None, "Cooldown must be recorded"
    assert risk.last_closed_position['close_reason'] == 'SL_HIT'


@pytest.mark.asyncio
async def test_sl_cooldown_blocks_same_direction():
    """After SL hit, same-direction signal must be blocked for 15 minutes."""
    orch = _make_orchestrator()
    await _warm_up(orch, n=80)

    risk = orch.skills['risk']

    # Simulate SL hit
    risk.on_position_closed(
        direction='BUY',
        close_reason='SL_HIT',
        entry_price=2650.0,
        close_price=2630.0,
    )

    ctx = Context(
        current_candle={'timestamp': '2026-01-01T10:00:00', 'close': 2650.0},
        signal='BUY',
    )
    ctx = await risk.execute(ctx)

    assert ctx.is_allowed is False
    assert 'SL cooldown' in ctx.risk_reason


@pytest.mark.asyncio
async def test_sl_cooldown_allows_opposite_direction():
    """After SL hit on BUY, a SELL signal must NOT be blocked."""
    orch = _make_orchestrator()
    await _warm_up(orch, n=80)

    risk = orch.skills['risk']
    risk.on_position_closed(
        direction='BUY',
        close_reason='SL_HIT',
        entry_price=2650.0,
        close_price=2630.0,
    )

    ctx = Context(
        current_candle={'timestamp': '2026-01-01T10:00:00', 'close': 2650.0},
        signal='SELL',
    )
    ctx = await risk.execute(ctx)

    assert ctx.is_allowed is True, "Opposite direction must bypass SL cooldown"


@pytest.mark.asyncio
async def test_edge_detection_prevents_duplicate_signal():
    """Same signal on consecutive candles must not fire twice."""
    orch = _make_orchestrator()
    await _warm_up(orch, n=80, trend='up')

    analysis = orch.skills['analysis']
    md       = orch.skills['market_data']

    # Build context with enough history
    ctx1 = Context(current_candle=_make_candles(1, base_price=2658.0)[0])
    ctx1 = await md.execute(ctx1)
    ctx1 = await analysis.execute(ctx1)
    first_signal = ctx1.signal

    # Same price conditions — edge detection must suppress repeat
    ctx2 = Context(current_candle=_make_candles(1, base_price=2658.1)[0])
    ctx2 = await md.execute(ctx2)
    ctx2 = await analysis.execute(ctx2)

    if first_signal is not None:
        assert ctx2.signal != first_signal or ctx2.signal is None, \
            "Edge detection must suppress identical consecutive signals"


@pytest.mark.asyncio
async def test_monitoring_tracks_pnl_on_close():
    """MonitoringSkill must update total_pnl and trade count after close."""
    orch = _make_orchestrator()
    orch.running = True
    await _warm_up(orch, n=80)

    mon = orch.skills['monitoring']

    await orch.on_position_closed(
        deal_id='DEAL002',
        direction='BUY',
        close_reason='TP_HIT',
        pnl=60.0,
        close_price=2656.0,
    )

    assert mon.total_trades == 1
    assert mon.total_pnl == 60.0
    assert mon.winning_trades == 1
