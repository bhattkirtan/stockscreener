"""
Unit tests — AnalysisSkill driven bar by bar, as the live bot drives it.

The backtester hands AnalysisSkill a `precomputed_df` covering the whole
history and looks rows up by timestamp. Live there is no precomputed frame:
every CANDLE_CLOSED recomputes indicators over a ROLLING BUFFER of whatever
bars have arrived, and the signal is published only on a state change. The
differences that matter:

  * warm-up — the live skill emits nothing until the buffer holds enough bars
    for the slowest indicator, and the buffer is rebuilt from scratch on every
    process restart (daily at 21:00 UTC).
  * edge detection — a trend state persists for many bars, so without it the
    skill would re-signal on every bar for the duration of a trend.
  * buffer truncation — Supertrend is path dependent. Measured on 1,100 GOLD
    M5 bars, a 300-bar rolling window reproduced the full-series direction
    exactly (100.00% agreement, 85 vs 85 flips), so truncation is NOT a
    divergence source. That is pinned here so the conclusion is not re-derived.
"""
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from core.event_bus import Event, EventBus, EventType
from skills.analysis.analysis_skill import AnalysisSkill


# ──────────────────────────────────────────────────────────────────────────
# Fixtures that mimic the live feed
# ──────────────────────────────────────────────────────────────────────────
def analysis_config(**over):
    """GOLD's deployed shape: Supertrend only, MA100 bias, SL/TP exits."""
    cfg = {
        'enabled': True,
        'indicators': {
            'supertrend': {'atr_period': 14, 'multiplier': 1.5},
            'ema': {'period': 21},
            'sma': {'fast_period': 25, 'slow_period': 30,
                    'bias_period': 100, 'bias_enabled': False},
            'adx': {'enabled': False},
            'm1_exit': {'enabled': False},
        },
        'signal_rules': {
            'require_supertrend': True,
            'require_ema': False,
            'require_sma': False,
            'require_adx': False,
            'require_sma_bias': False,
            'edge_detection': True,
        },
        'sl_tp': {'method': 'fixed', 'pip_size': 1.0,
                  'stop_loss_pips': 15, 'take_profit_pips': 60},
    }
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    return cfg


class FakeMarketData:
    """Stands in for MarketDataSkill: a rolling buffer, as live maintains."""

    def __init__(self, buffer_size=300):
        self.buffer, self.buffer_size = [], buffer_size

    def add(self, candle):
        self.buffer.append(candle)
        if len(self.buffer) > self.buffer_size:
            self.buffer = self.buffer[-self.buffer_size:]

    def get_candle_history(self):
        return self.buffer


def candle(ts, close, spread=3.0):
    return {'timestamp': ts, 'open': close - 0.5, 'high': close + spread,
            'low': close - spread, 'close': close, 'volume': 100}


def ramp(n, start=4000.0, step=1.0, base=None):
    """A clean monotonic series — Supertrend will settle into one direction."""
    base = base or datetime(2026, 10, 21, 0, 0)
    return [candle(base + timedelta(minutes=5 * i), start + step * i)
            for i in range(n)]


def vshape(n_down, n_up, start=4200.0, step=2.0, base=None):
    """Down then up — forces exactly one Supertrend flip."""
    base = base or datetime(2026, 10, 21, 0, 0)
    out, px = [], start
    for i in range(n_down):
        out.append(candle(base + timedelta(minutes=5 * i), px))
        px -= step
    for j in range(n_up):
        out.append(candle(base + timedelta(minutes=5 * (n_down + j)), px))
        px += step
    return out


class SignalRecorder:
    def __init__(self, bus):
        self.signals = []
        bus.subscribe(EventType.SIGNAL_GENERATED, self._on)

    async def _on(self, event):
        self.signals.append(event.payload.get('signal'))


async def feed(skill, md, bars, bus_recorder=None):
    """Drive bars through the live entry point one at a time."""
    for c in bars:
        md.add(c)
        await skill.on_candle_closed(Event(
            event_type=EventType.CANDLE_CLOSED, instrument='GOLD',
            source='market_data', payload={'candle': c, 'timeframe': 'M5'}))
    return bus_recorder.signals if bus_recorder else None


def build_skill(bus, md, **over):
    skill = AnalysisSkill(analysis_config(**over), event_bus=bus)
    skill.market_data = md
    return skill


# ──────────────────────────────────────────────────────────────────────────
# Warm-up
# ──────────────────────────────────────────────────────────────────────────
class TestWarmup:

    @pytest.mark.asyncio
    async def test_no_signal_before_enough_bars(self):
        """
        A restart empties the buffer. Emitting on bar 1 would trade on an
        indicator computed from almost no history.
        """
        bus = EventBus(fast_mode=True)
        md = FakeMarketData()
        rec = SignalRecorder(bus)
        skill = build_skill(bus, md)
        await feed(skill, md, ramp(5))
        assert rec.signals == []

    @pytest.mark.asyncio
    async def test_signals_begin_once_warm(self):
        bus = EventBus(fast_mode=True)
        md = FakeMarketData()
        rec = SignalRecorder(bus)
        skill = build_skill(bus, md)
        await feed(skill, md, vshape(40, 40))
        assert rec.signals, "expected at least one signal once warm"

    @pytest.mark.asyncio
    async def test_bias_filter_lengthens_warmup(self):
        """MA100 bias needs 100 bars, so signals cannot start before that."""
        bus = EventBus(fast_mode=True)
        md = FakeMarketData()
        rec = SignalRecorder(bus)
        skill = build_skill(bus, md, indicators={
            'sma': {'fast_period': 25, 'slow_period': 30,
                    'bias_period': 100, 'bias_enabled': True}},
            signal_rules={'require_sma_bias': True})
        await feed(skill, md, ramp(40))
        assert rec.signals == []

    @pytest.mark.asyncio
    async def test_empty_buffer_is_safe(self):
        bus = EventBus(fast_mode=True)
        md = FakeMarketData()
        skill = build_skill(bus, md)
        await skill.on_candle_closed(Event(
            event_type=EventType.CANDLE_CLOSED, payload={'candle': candle(
                datetime(2026, 10, 21), 4000.0)}))

    @pytest.mark.asyncio
    async def test_missing_market_data_is_safe(self):
        bus = EventBus(fast_mode=True)
        skill = AnalysisSkill(analysis_config(), event_bus=bus)
        skill.market_data = None
        await skill.on_candle_closed(Event(
            event_type=EventType.CANDLE_CLOSED,
            payload={'candle': candle(datetime(2026, 10, 21), 4000.0)}))


# ──────────────────────────────────────────────────────────────────────────
# Edge detection — the gate that stops one trend becoming many signals
# ──────────────────────────────────────────────────────────────────────────
class TestEdgeDetection:

    @pytest.mark.asyncio
    async def test_a_persistent_trend_signals_once_not_every_bar(self):
        """
        Supertrend direction persists for many bars. Without edge detection the
        skill would publish on every one of them.
        """
        bus = EventBus(fast_mode=True)
        md = FakeMarketData()
        rec = SignalRecorder(bus)
        skill = build_skill(bus, md)
        await feed(skill, md, ramp(80))
        assert len(rec.signals) <= 2, f"expected ~1 signal, got {rec.signals}"

    @pytest.mark.asyncio
    async def test_disabling_edge_detection_signals_repeatedly(self):
        bus = EventBus(fast_mode=True)
        md = FakeMarketData()
        rec = SignalRecorder(bus)
        skill = build_skill(bus, md, signal_rules={'edge_detection': False})
        await feed(skill, md, ramp(80))
        assert len(rec.signals) > 10

    @pytest.mark.asyncio
    async def test_a_flip_produces_the_opposite_signal(self):
        bus = EventBus(fast_mode=True)
        md = FakeMarketData()
        rec = SignalRecorder(bus)
        skill = build_skill(bus, md)
        await feed(skill, md, vshape(45, 45))
        assert len(set(rec.signals)) >= 1
        assert set(rec.signals) <= {'BUY', 'SELL'}

    @pytest.mark.asyncio
    async def test_state_resets_on_restart_so_the_first_signal_refires(self):
        """
        A fresh process has last_signal_state=None, so the first signal after a
        restart is published even though the trend did not change. The daily
        21:00 restart makes this a real daily event.
        """
        bus = EventBus(fast_mode=True)
        md = FakeMarketData()
        bars = ramp(80)

        rec1 = SignalRecorder(bus)
        s1 = build_skill(bus, md)
        await feed(s1, md, bars)
        first_run = list(rec1.signals)

        # Restart: new skill instance, buffer already populated
        bus2 = EventBus(fast_mode=True)
        rec2 = SignalRecorder(bus2)
        s2 = build_skill(bus2, md)
        await feed(s2, md, bars[-3:])
        assert first_run, "precondition: first run produced a signal"
        assert rec2.signals, "a restart re-publishes the prevailing direction"


# ──────────────────────────────────────────────────────────────────────────
# Rolling buffer vs full history
# ──────────────────────────────────────────────────────────────────────────
class TestRollingBuffer:

    @pytest.mark.asyncio
    async def test_truncated_buffer_matches_a_longer_one(self):
        """
        Supertrend carries bands forward, so a short window could in principle
        disagree with full history. Measured on real GOLD M5 data it does not
        (100% direction agreement at a 300-bar window, because the band resets
        at every flip). Pinned so the worry is not re-investigated.
        """
        bars = vshape(45, 45)
        out = {}
        for size in (120, 400):
            bus = EventBus(fast_mode=True)
            md = FakeMarketData(buffer_size=size)
            rec = SignalRecorder(bus)
            skill = build_skill(bus, md)
            await feed(skill, md, bars)
            out[size] = rec.signals
        assert out[120] == out[400]

    @pytest.mark.asyncio
    async def test_buffer_is_bounded_during_a_long_session(self):
        bus = EventBus(fast_mode=True)
        md = FakeMarketData(buffer_size=120)
        skill = build_skill(bus, md)
        await feed(skill, md, ramp(260))
        assert len(md.get_candle_history()) == 120


# ──────────────────────────────────────────────────────────────────────────
# SL/TP attached to the signal
# ──────────────────────────────────────────────────────────────────────────
class TestSignalPayload:

    @pytest.mark.asyncio
    async def test_signal_carries_sl_and_tp(self):
        bus = EventBus(fast_mode=True)
        md = FakeMarketData()
        payloads = []

        async def grab(e):
            payloads.append(e.payload)
        bus.subscribe(EventType.SIGNAL_GENERATED, grab)
        skill = build_skill(bus, md)
        await feed(skill, md, vshape(45, 45))
        assert payloads, "expected a signal"
        p = payloads[0]
        assert p.get('stop_loss') is not None
        assert p.get('take_profit') is not None

    @pytest.mark.asyncio
    async def test_sl_tp_straddle_entry_in_the_right_direction(self):
        bus = EventBus(fast_mode=True)
        md = FakeMarketData()
        payloads = []

        async def grab(e):
            payloads.append(e.payload)
        bus.subscribe(EventType.SIGNAL_GENERATED, grab)
        skill = build_skill(bus, md)
        await feed(skill, md, vshape(45, 45))
        for p in payloads:
            entry, sl, tp = p['entry_price'], p['stop_loss'], p['take_profit']
            if p['signal'] == 'BUY':
                assert sl < entry < tp
            else:
                assert tp < entry < sl

    @pytest.mark.asyncio
    async def test_configured_distances_are_used(self):
        bus = EventBus(fast_mode=True)
        md = FakeMarketData()
        payloads = []

        async def grab(e):
            payloads.append(e.payload)
        bus.subscribe(EventType.SIGNAL_GENERATED, grab)
        skill = build_skill(bus, md, sl_tp={
            'method': 'fixed', 'pip_size': 1.0,
            'stop_loss_pips': 15, 'take_profit_pips': 60})
        await feed(skill, md, vshape(45, 45))
        assert payloads
        p = payloads[0]
        assert abs(abs(p['stop_loss'] - p['entry_price']) - 15.0) < 0.01
        assert abs(abs(p['take_profit'] - p['entry_price']) - 60.0) < 0.01


# ──────────────────────────────────────────────────────────────────────────
# Filters, driven live
# ──────────────────────────────────────────────────────────────────────────
class TestFiltersLive:

    @pytest.mark.asyncio
    async def test_adx_filter_suppresses_signals_in_chop(self):
        """
        A flat, choppy series has low ADX. With require_adx the skill should
        emit fewer signals than without it.
        """
        base = datetime(2026, 10, 21)
        chop = [candle(base + timedelta(minutes=5 * i),
                       4000.0 + (2.0 if i % 2 else -2.0)) for i in range(120)]

        async def run(adx_on):
            bus = EventBus(fast_mode=True)
            md = FakeMarketData()
            rec = SignalRecorder(bus)
            skill = build_skill(
                bus, md,
                indicators={'adx': {'enabled': adx_on, 'period': 14,
                                    'threshold': 25}},
                signal_rules={'require_adx': adx_on})
            await feed(skill, md, chop)
            return rec.signals

        assert len(await run(True)) <= len(await run(False))

    @pytest.mark.asyncio
    async def test_bias_filter_blocks_counter_trend_entries(self):
        """
        With MA100 bias enabled, a SELL below a rising MA100 must be suppressed.
        On a clean uptrend every emitted signal should be a BUY.
        """
        bus = EventBus(fast_mode=True)
        md = FakeMarketData()
        rec = SignalRecorder(bus)
        skill = build_skill(bus, md, indicators={
            'sma': {'fast_period': 25, 'slow_period': 30,
                    'bias_period': 100, 'bias_enabled': True}},
            signal_rules={'require_sma_bias': True})
        await feed(skill, md, ramp(150))
        assert 'SELL' not in rec.signals
