"""
Unit Tests — execute(context) Pipeline Methods

Tests the sequential orchestrator path (execute()) for each skill,
which is separate from the event-driven path (on_signal_generated etc.)
These methods are what actually runs in live trading.
"""

import pandas as pd
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
    # Startup-flip suppression is the first gate in the chain and mutates state,
    # so it would short-circuit every test below. Disabled here; covered in
    # test_live_close_and_risk.py::TestStartupFlipSuppression.
    'startup_flip_gate': False,
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

    # ------------------------------------------------------------------
    # H1 Bollinger gate
    #
    # This gate treats BB lines as PRICE WALLS, not as a trend filter:
    #   BUY  is blocked when H1 price sits near the UPPER band (resistance above)
    #   SELL is blocked when H1 price sits near the LOWER band (support below)
    # band_pct = (close - lower) / (upper - lower), thresholds 0.75 / 0.25.
    #
    # The previous tests here asserted the opposite ("block BUY below midline")
    # and set an `h1_bb_middle` column the gate never reads, so they tested a
    # gate that does not exist. The companion "allows" test passed only
    # vacuously: with a flat price series the bands are degenerate
    # (band_width == 0) and the gate short-circuits.
    # ------------------------------------------------------------------

    def _h1_skill(self):
        return AnalysisSkill({
            **ANALYSIS_CONFIG,
            'signal_rules': {
                **ANALYSIS_CONFIG['signal_rules'],
                'require_h1_bb': True,
            },
        })

    def _load_h1_bands(self, skill, close, lower=2600.0, upper=2700.0):
        """
        Load H1 history then force an explicit, non-degenerate band.

        Two mechanics matter here and both bit the previous version of these
        tests:

        1. `load_h1_history` does NOT resample — it indexes whatever candles it
           is handed. 60 M5 candles become 60 "H1" rows at 5-minute spacing.
        2. The gate looks the row up with `DataFrame.asof`, which returns the
           last row with NO NaN in ANY column. `h1_bb_middle` is NaN for the
           first `h1_bb_period` (20) rows, so any lookup landing in the warm-up
           returns an all-NaN row and the gate silently no-ops. The returned
           timestamp is therefore chosen past the warm-up, and every band column
           is set explicitly.
        """
        skill.load_h1_history(_make_candle_list(60, base=2650.0, step=0.0))
        skill.df_h1['h1_bb_lower'] = lower
        skill.df_h1['h1_bb_upper'] = upper
        skill.df_h1['h1_bb_middle'] = (lower + upper) / 2
        skill.df_h1['close'] = close
        # index is 5-min spaced from 2026-01-01T00:00; -1h must land past row 20
        return pd.Timestamp('2026-01-01T03:00:00', tz='UTC')

    def test_h1_bb_gate_noops_during_band_warmup(self):
        """
        Pins mechanic (2) above: a lookup inside the BB warm-up window yields an
        all-NaN asof row, so the gate must allow rather than block.
        """
        skill = self._h1_skill()
        skill.load_h1_history(_make_candle_list(60, base=2650.0, step=0.0))
        skill.df_h1['h1_bb_lower'] = 2600.0
        skill.df_h1['h1_bb_upper'] = 2700.0
        skill.df_h1['close'] = 2690.0          # would block if the row resolved
        early = pd.Timestamp('2026-01-01T01:00:00', tz='UTC')
        assert skill._check_mtf_confluence(early, 'BUY')[0] is True

    def test_h1_bb_gate_blocks_buy_near_upper_band(self):
        """band_pct 0.90 > 0.75 -> resistance overhead -> BUY blocked."""
        skill = self._h1_skill()
        ts = self._load_h1_bands(skill, close=2690.0)
        ok, reason = skill._check_mtf_confluence(ts, 'BUY')
        assert ok is False
        assert reason == 'h1_near_upper_resistance'

    def test_h1_bb_gate_blocks_sell_near_lower_band(self):
        """band_pct 0.10 < 0.25 -> support below -> SELL blocked."""
        skill = self._h1_skill()
        ts = self._load_h1_bands(skill, close=2610.0)
        ok, reason = skill._check_mtf_confluence(ts, 'SELL')
        assert ok is False
        assert reason == 'h1_near_lower_support'

    def test_h1_bb_gate_allows_buy_near_lower_band(self):
        """A BUY with room overhead is exactly what this gate is for."""
        skill = self._h1_skill()
        ts = self._load_h1_bands(skill, close=2610.0)
        assert skill._check_mtf_confluence(ts, 'BUY')[0] is True

    def test_h1_bb_gate_allows_sell_near_upper_band(self):
        skill = self._h1_skill()
        ts = self._load_h1_bands(skill, close=2690.0)
        assert skill._check_mtf_confluence(ts, 'SELL')[0] is True

    def test_h1_bb_gate_allows_both_directions_mid_band(self):
        skill = self._h1_skill()
        ts = self._load_h1_bands(skill, close=2650.0)
        assert skill._check_mtf_confluence(ts, 'BUY')[0] is True
        assert skill._check_mtf_confluence(ts, 'SELL')[0] is True

    def test_h1_bb_gate_does_not_block_on_degenerate_band(self):
        """upper == lower (flat series) must not block — band_width guard."""
        skill = self._h1_skill()
        ts = self._load_h1_bands(skill, close=2650.0, lower=2650.0, upper=2650.0)
        assert skill._check_mtf_confluence(ts, 'BUY')[0] is True
        assert skill._check_mtf_confluence(ts, 'SELL')[0] is True

    def test_h1_bb_gate_is_off_when_not_required(self):
        """With require_h1_bb False the gate must not run at all."""
        skill = AnalysisSkill(ANALYSIS_CONFIG)
        ts = self._load_h1_bands(skill, close=2690.0)
        assert skill._check_mtf_confluence(ts, 'BUY')[0] is True


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
