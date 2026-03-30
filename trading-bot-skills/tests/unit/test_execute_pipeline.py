"""
Unit Tests — execute(context) Pipeline Methods

Tests the sequential orchestrator path (execute()) for each skill,
which is separate from the event-driven path (on_signal_generated etc.)
These methods are what actually runs in live trading.
"""

import pytest
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from skills.base_skill import Context
from skills.analysis import AnalysisSkill
from skills.risk import RiskSkill
from skills.execution import ExecutionSkill


# ── Fixtures ──────────────────────────────────────────────────────────────────

ANALYSIS_CONFIG = {
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
        'require_ema': True,
        'require_sma': True,
        'require_h1_bb': False,
        'require_daily_bias': False,
        'edge_detection': True,
    },
    'sl_tp': {'method': 'fixed', 'stop_loss_pips': 20, 'take_profit_pips': 60},
}

RISK_CONFIG = {
    'trading_hours': {'enabled': False},
    'sl_cooldown_minutes': 15,
    'tp_cooldown_minutes': 5,
    'skip_hours': [],
    'position_size_pct': 2.0,
}

EXECUTION_CONFIG = {
    'sl_pips': 20,
    'tp_pips': 60,
    'mock_mode': True,
}


def _make_candle(close: float = 2650.0, ts: str = None) -> dict:
    ts = ts or datetime.now().isoformat()
    return {
        'timestamp': ts,
        'open':  close - 0.1,
        'high':  close + 0.2,
        'low':   close - 0.2,
        'close': close,
        'volume': 100,
    }


def _make_candle_list(n: int, base: float = 2650.0, step: float = 0.1) -> list:
    base_time = datetime(2026, 1, 1)
    return [
        {
            'timestamp': (base_time + timedelta(minutes=5 * i)).isoformat(),
            'open':  base + i * step - 0.05,
            'high':  base + i * step + 0.2,
            'low':   base + i * step - 0.2,
            'close': base + i * step,
            'volume': 100,
        }
        for i in range(n)
    ]


# ── AnalysisSkill.execute() ───────────────────────────────────────────────────

class TestAnalysisSkillExecute:

    def test_returns_context_unchanged_when_no_market_data_skill(self):
        """execute() must return context untouched if market_data is not injected."""
        skill = AnalysisSkill(ANALYSIS_CONFIG, market_data_skill=None)
        ctx = Context(signal=None)
        import asyncio
        result = asyncio.run(skill.execute(ctx))
        assert result.signal is None

    def test_returns_context_unchanged_when_insufficient_candles(self):
        """execute() must return early if buffer has fewer bars than min_bars."""
        md = MagicMock()
        md.get_candle_history.return_value = _make_candle_list(5)  # way below min_bars (~40)

        skill = AnalysisSkill(ANALYSIS_CONFIG, market_data_skill=md)
        ctx = Context()
        import asyncio
        result = asyncio.run(skill.execute(ctx))
        assert result.signal is None

    def test_sets_signal_and_pricing_fields_on_sufficient_data(self):
        """With enough candles, execute() must populate signal + SL/TP on context."""
        md = MagicMock()
        md.get_candle_history.return_value = _make_candle_list(80, step=0.5)

        skill = AnalysisSkill(ANALYSIS_CONFIG, market_data_skill=md)
        ctx = Context()
        import asyncio
        result = asyncio.run(skill.execute(ctx))

        # If a signal fires, SL/TP/entry must all be set
        if result.signal is not None:
            assert result.signal in ('BUY', 'SELL')
            assert result.entry_price is not None and result.entry_price > 0
            assert result.stop_loss   is not None
            assert result.take_profit is not None

    def test_edge_detection_suppresses_repeat_signal(self):
        """Same signal on back-to-back execute() calls must be suppressed."""
        md = MagicMock()
        md.get_candle_history.return_value = _make_candle_list(80, step=0.5)

        skill = AnalysisSkill(ANALYSIS_CONFIG, market_data_skill=md)
        import asyncio

        ctx1 = Context()
        ctx1 = asyncio.run(skill.execute(ctx1))
        first_signal = ctx1.signal

        # Same data — edge detection must suppress
        ctx2 = Context()
        ctx2 = asyncio.run(skill.execute(ctx2))

        if first_signal is not None:
            assert ctx2.signal is None, \
                "Edge detection must suppress identical back-to-back signal"


# ── AnalysisSkill MTF data loading ────────────────────────────────────────────

class TestAnalysisSkillMTF:

    def test_load_h1_history_sets_df_h1(self):
        """load_h1_history() must build df_h1 with h1_bb_middle column."""
        import pandas as pd
        skill = AnalysisSkill(ANALYSIS_CONFIG)
        candles = _make_candle_list(60, step=0.5)
        skill.load_h1_history(candles)

        assert skill.df_h1 is not None
        assert len(skill.df_h1) == 60
        assert 'h1_bb_middle' in skill.df_h1.columns
        assert 'h1_bb_upper'  in skill.df_h1.columns
        assert 'h1_bb_lower'  in skill.df_h1.columns
        assert 'close'        in skill.df_h1.columns

    def test_load_h1_history_empty_list_is_safe(self):
        """load_h1_history([]) must not raise or set df_h1."""
        skill = AnalysisSkill(ANALYSIS_CONFIG)
        skill.load_h1_history([])
        assert skill.df_h1 is None

    def test_update_h1_candle_appends_and_recomputes(self):
        """update_h1_candle() must append the row and recompute BB."""
        import pandas as pd
        skill = AnalysisSkill(ANALYSIS_CONFIG)
        skill.load_h1_history(_make_candle_list(60, step=0.5))

        original_len = len(skill.df_h1)
        new_candle = _make_candle(close=2660.0, ts='2026-01-01T05:00:00')
        skill.update_h1_candle(new_candle)

        assert len(skill.df_h1) == original_len + 1
        # BB must still be computed on the updated frame
        assert 'h1_bb_middle' in skill.df_h1.columns
        assert not skill.df_h1['h1_bb_middle'].isna().all()

    def test_update_h1_candle_deduplicates_same_timestamp(self):
        """Sending the same H1 candle twice must not add a duplicate row."""
        skill = AnalysisSkill(ANALYSIS_CONFIG)
        skill.load_h1_history(_make_candle_list(60, step=0.5))
        original_len = len(skill.df_h1)

        candle = _make_candle(close=2660.0, ts='2026-01-01T05:00:00')
        skill.update_h1_candle(candle)
        skill.update_h1_candle(candle)  # same timestamp

        assert len(skill.df_h1) == original_len + 1

    def test_update_h1_candle_noop_when_df_h1_is_none(self):
        """update_h1_candle() must not crash when called before load_h1_history."""
        skill = AnalysisSkill(ANALYSIS_CONFIG)
        skill.update_h1_candle(_make_candle())  # df_h1 is None — must be safe

    def test_load_daily_history_sets_df_daily(self):
        """load_daily_history() must build df_daily with daily_sma column."""
        skill = AnalysisSkill(ANALYSIS_CONFIG)
        candles = _make_candle_list(30, step=1.0)
        skill.load_daily_history(candles)

        assert skill.df_daily is not None
        assert len(skill.df_daily) == 30
        assert 'daily_sma' in skill.df_daily.columns

    def test_load_daily_history_empty_list_is_safe(self):
        """load_daily_history([]) must not raise or set df_daily."""
        skill = AnalysisSkill(ANALYSIS_CONFIG)
        skill.load_daily_history([])
        assert skill.df_daily is None

    def test_h1_bb_gate_blocks_buy_below_midline(self):
        """H1 BB gate must block BUY when H1 close is below midline."""
        import pandas as pd
        skill = AnalysisSkill({
            **ANALYSIS_CONFIG,
            'signal_rules': {
                **ANALYSIS_CONFIG['signal_rules'],
                'require_h1_bb': True,
            },
        })

        candles = _make_candle_list(60, base=2650.0, step=0.0)
        skill.load_h1_history(candles)

        # Force close well below midline
        skill.df_h1['close'] = 2600.0
        skill.df_h1['h1_bb_middle'] = 2650.0

        ts = pd.Timestamp('2026-01-01T01:00:00', tz='UTC')
        ok, reason = skill._check_mtf_confluence(ts, 'BUY')
        assert ok is False
        assert reason == 'h1_below_midline_long'

    def test_h1_bb_gate_allows_buy_above_midline(self):
        """H1 BB gate must allow BUY when H1 close is above midline."""
        import pandas as pd
        skill = AnalysisSkill({
            **ANALYSIS_CONFIG,
            'signal_rules': {
                **ANALYSIS_CONFIG['signal_rules'],
                'require_h1_bb': True,
            },
        })
        candles = _make_candle_list(60, base=2650.0, step=0.0)
        skill.load_h1_history(candles)

        skill.df_h1['close'] = 2700.0
        skill.df_h1['h1_bb_middle'] = 2650.0

        ts = pd.Timestamp('2026-01-01T01:00:00', tz='UTC')
        ok, reason = skill._check_mtf_confluence(ts, 'BUY')
        assert ok is True


# ── RiskSkill.execute() ───────────────────────────────────────────────────────

class TestRiskSkillExecute:

    @pytest.mark.asyncio
    async def test_no_signal_passes_through(self):
        """execute() with no signal must return context untouched."""
        skill = RiskSkill(RISK_CONFIG)
        ctx = Context(current_candle=_make_candle())
        result = await skill.execute(ctx)
        assert result.is_allowed is False  # default
        assert result.signal is None

    @pytest.mark.asyncio
    async def test_has_open_position_blocks_any_signal(self):
        """execute() must block BUY and SELL when has_open_position=True."""
        skill = RiskSkill(RISK_CONFIG)
        skill.has_open_position = True

        for direction in ('BUY', 'SELL'):
            ctx = Context(
                current_candle=_make_candle(),
                signal=direction,
            )
            result = await skill.execute(ctx)
            assert result.is_allowed is False
            assert 'Max positions' in result.risk_reason

    @pytest.mark.asyncio
    async def test_skip_hours_blocks_signal(self):
        """execute() must block signal during configured skip hours."""
        from datetime import timezone
        now_utc = datetime.now(timezone.utc)
        config = {**RISK_CONFIG, 'skip_hours': [now_utc.hour]}
        skill = RiskSkill(config)

        ctx = Context(
            current_candle={'timestamp': now_utc.isoformat(), 'close': 2650.0},
            signal='BUY',
        )
        result = await skill.execute(ctx)
        assert result.is_allowed is False
        assert 'Skip hour' in result.risk_reason

    @pytest.mark.asyncio
    async def test_clean_state_allows_signal(self):
        """execute() must allow signal with no open position, no cooldown."""
        skill = RiskSkill(RISK_CONFIG)
        ctx = Context(
            current_candle=_make_candle(),
            signal='BUY',
        )
        result = await skill.execute(ctx)
        assert result.is_allowed is True
        assert result.position_size > 0

    @pytest.mark.asyncio
    async def test_sl_cooldown_blocks_via_execute(self):
        """After SL hit, execute() must block same-direction signal."""
        skill = RiskSkill(RISK_CONFIG)
        skill.on_position_closed(
            direction='BUY', close_reason='SL_HIT',
            entry_price=2650.0, close_price=2630.0,
        )
        ctx = Context(
            current_candle=_make_candle(),
            signal='BUY',
        )
        result = await skill.execute(ctx)
        assert result.is_allowed is False
        assert 'SL cooldown' in result.risk_reason

    @pytest.mark.asyncio
    async def test_tp_cooldown_blocks_via_execute(self):
        """After TP hit, execute() must block same-direction signal."""
        skill = RiskSkill(RISK_CONFIG)
        skill.on_position_closed(
            direction='SELL', close_reason='TP_HIT',
            entry_price=2650.0, close_price=2670.0,
        )
        ctx = Context(
            current_candle=_make_candle(),
            signal='SELL',
        )
        result = await skill.execute(ctx)
        assert result.is_allowed is False
        assert 'TP cooldown' in result.risk_reason

    @pytest.mark.asyncio
    async def test_cooldown_allows_opposite_direction_via_execute(self):
        """After SL hit on BUY, execute() must allow SELL signal."""
        skill = RiskSkill(RISK_CONFIG)
        skill.on_position_closed(
            direction='BUY', close_reason='SL_HIT',
            entry_price=2650.0, close_price=2630.0,
        )
        ctx = Context(
            current_candle=_make_candle(),
            signal='SELL',
        )
        result = await skill.execute(ctx)
        assert result.is_allowed is True


# ── ExecutionSkill.execute() ──────────────────────────────────────────────────

class TestExecutionSkillExecute:

    @pytest.mark.asyncio
    async def test_sets_deal_id_and_current_position(self):
        """execute() must set both deal_id and current_position on context."""
        skill = ExecutionSkill(EXECUTION_CONFIG)
        ctx = Context(
            signal='BUY',
            is_allowed=True,
            position_size=0.5,
            entry_price=2650.0,
            stop_loss=2649.80,
            take_profit=2650.60,
        )
        result = await skill.execute(ctx)

        assert result.deal_id is not None
        assert result.current_position is not None
        assert result.current_position['direction']   == 'BUY'
        assert result.current_position['entry_price'] == 2650.0
        assert result.current_position['stop_loss']   == 2649.80
        assert result.current_position['take_profit'] == 2650.60
        assert result.current_position['size']        == 0.5
        assert 'deal_id'    in result.current_position
        assert 'opened_at'  in result.current_position

    @pytest.mark.asyncio
    async def test_skips_when_not_allowed(self):
        """execute() must not place order when is_allowed=False."""
        skill = ExecutionSkill(EXECUTION_CONFIG)
        ctx = Context(signal='BUY', is_allowed=False)
        result = await skill.execute(ctx)
        assert result.deal_id is None
        assert result.current_position is None

    @pytest.mark.asyncio
    async def test_skips_when_no_signal(self):
        """execute() must not place order when signal is None."""
        skill = ExecutionSkill(EXECUTION_CONFIG)
        ctx = Context(signal=None, is_allowed=True)
        result = await skill.execute(ctx)
        assert result.deal_id is None

    @pytest.mark.asyncio
    async def test_falls_back_to_skill_position_size(self):
        """execute() must use skill.position_size when context.position_size=0."""
        skill = ExecutionSkill({**EXECUTION_CONFIG, 'position_size': 1.0})
        ctx = Context(
            signal='SELL',
            is_allowed=True,
            position_size=0.0,  # not set by risk
            entry_price=2650.0,
            stop_loss=2650.20,
            take_profit=2649.40,
        )
        result = await skill.execute(ctx)
        assert result.current_position is not None
        assert result.current_position['size'] == 1.0

    @pytest.mark.asyncio
    async def test_mock_mode_generates_unique_deal_ids(self):
        """Mock mode must generate unique deal_id per execution."""
        import asyncio as aio
        skill = ExecutionSkill(EXECUTION_CONFIG)

        ids = set()
        for _ in range(3):
            ctx = Context(
                signal='BUY', is_allowed=True,
                position_size=0.5, entry_price=2650.0,
                stop_loss=2649.80, take_profit=2650.60,
            )
            result = await skill.execute(ctx)
            await aio.sleep(0.01)  # ensure timestamp differs
            ids.add(result.deal_id)

        assert len(ids) == 3, "Each execution must produce a unique deal_id"
