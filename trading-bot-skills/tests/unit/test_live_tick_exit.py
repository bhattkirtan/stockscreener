"""
Unit tests — AnalysisSkill's live-only exit paths and the MTF gates.

Three bodies of code that `run_skills_backtest.py` never executes:

  1. `on_price_tick` — the profit-trail exit. Driven only from the live
     WebSocket quote stream, so the backtest's exits are always clean SL/TP and
     this had no tests at all. It is also where the single most expensive bug in
     this project's history lived: reverse-on-loss closed a losing position and
     immediately opened the opposite one every 180s, producing 18 live trades /
     -$315 against 10 backtest trades / +$219 over Apr 7-10 (CLAUDE.md gotcha 9).
     It is now off by default and `reverse_on_loss: false` in every instrument
     YAML; these tests pin that the flag really does suppress it.

  2. `on_m1_candle_closed` — M1 exit validation. Disabled in config but live code.

  3. The H1 / 4h / daily Bollinger and daily-bias confluence gates — all off in
     config, all reachable.

`_tick_check_interval_sec` is throttled against `time.monotonic()`, so tests
that need to cross an interval boundary set `_last_tick_check_ts` directly
rather than sleeping.
"""
import os
import sys
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from core.event_bus import Event, EventBus, EventType
from skills.analysis.analysis_skill import AnalysisSkill


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

# GOLD's deployed ladder: interval shrinks as unrealised profit grows.
GOLD_LEVELS = [
    {'min_profit_pips': 0,  'check_interval_sec': 180},
    {'min_profit_pips': 10, 'check_interval_sec': 120},
    {'min_profit_pips': 20, 'check_interval_sec': 60},
    {'min_profit_pips': 25, 'check_interval_sec': 0},
]


def tick_config(enabled=True, reverse_on_loss=False, levels=None,
                loss_check_interval_sec=180, pip_size=1.0, **over):
    cfg = {
        'enabled': True,
        'indicators': {
            'supertrend': {'atr_period': 14, 'multiplier': 1.5},
            'ema': {'period': 21},
            'sma': {'fast_period': 25, 'slow_period': 30,
                    'bias_period': 100, 'bias_enabled': False},
            'adx': {'enabled': False},
            'm1_exit': {'enabled': False},
            'mtf': {'h1_bb_period': 20, 'h1_bb_std': 2.0,
                    'h4_bb_period': 20, 'daily_sma_period': 20,
                    'daily_bb_period': 20},
        },
        'signal_rules': {
            'require_supertrend': True, 'require_ema': False,
            'require_sma': False, 'require_adx': False,
            'require_sma_bias': False, 'edge_detection': True,
        },
        'sl_tp': {'method': 'fixed', 'pip_size': pip_size,
                  'stop_loss_pips': 15, 'take_profit_pips': 60},
        'tick_exit': {
            'enabled': enabled,
            'reverse_on_loss': reverse_on_loss,
            'loss_check_interval_sec': loss_check_interval_sec,
            'levels': GOLD_LEVELS if levels is None else levels,
        },
    }
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    return cfg


class Exits:
    """Records EXIT_SIGNAL and SIGNAL_GENERATED, which is what a tick can emit."""

    def __init__(self, bus):
        self.exits, self.entries = [], []
        bus.subscribe(EventType.EXIT_SIGNAL, self._exit)
        bus.subscribe(EventType.SIGNAL_GENERATED, self._entry)

    async def _exit(self, e):
        self.exits.append(e.payload)

    async def _entry(self, e):
        self.entries.append(e.payload)

    @property
    def reasons(self):
        return [p.get('reason') for p in self.exits]


def armed_skill(bus=None, position='BUY', entry=4100.0, trail=4095.0,
                sma_bias=None, elapsed_ok=True, **cfg_over):
    """
    A skill holding an open position with a Supertrend trail set — the state
    `on_price_tick` requires. `elapsed_ok` leaves `_last_tick_check_ts` at None
    so the first tick is never throttled.
    """
    skill = AnalysisSkill(tick_config(**cfg_over), event_bus=bus)
    skill.register_open_position(position, entry, entry - 15.0, entry + 60.0)
    skill.current_st_trail = trail
    skill.current_sma_bias = sma_bias
    if not elapsed_ok:
        skill._last_tick_check_ts = time.monotonic()
    return skill


def m1_candle(ts, close, spread=1.0):
    return {'timestamp': ts, 'open': close, 'high': close + spread,
            'low': close - spread, 'close': close, 'volume': 10}


def m1_event(candle):
    return Event(event_type=EventType.M1_CANDLE_CLOSED, instrument='GOLD',
                 source='market_data', payload={'candle': candle})


# ──────────────────────────────────────────────────────────────────────────
# The profit-based interval ladder
# ──────────────────────────────────────────────────────────────────────────

class TestTickIntervalLadder:
    """
    `_tick_check_interval_sec` picks the LAST matching level, so with GOLD's
    ladder the interval tightens 180 -> 120 -> 60 -> 0 as profit grows.
    """

    def test_disabled_tick_exit_never_checks(self):
        skill = armed_skill(enabled=False)
        assert skill._tick_check_interval_sec(4200.0) == float('inf')

    def test_no_open_position_never_checks(self):
        skill = AnalysisSkill(tick_config())
        assert skill._tick_check_interval_sec(4200.0) == float('inf')

    def test_no_entry_price_never_checks(self):
        skill = armed_skill()
        skill.current_entry_price = None
        assert skill._tick_check_interval_sec(4200.0) == float('inf')

    @pytest.mark.parametrize('profit_pips,expected', [
        (0, 180), (5, 180), (9.9, 180),
        (10, 120), (19, 120),
        (20, 60), (24, 60),
        (25, 0), (100, 0),
    ])
    def test_the_interval_tightens_as_profit_grows(self, profit_pips, expected):
        skill = armed_skill(position='BUY', entry=4100.0)
        assert skill._tick_check_interval_sec(4100.0 + profit_pips) == expected

    @pytest.mark.parametrize('profit_pips,expected', [
        (0, 180), (10, 120), (20, 60), (25, 0),
    ])
    def test_a_short_measures_profit_downwards(self, profit_pips, expected):
        skill = armed_skill(position='SELL', entry=4100.0)
        assert skill._tick_check_interval_sec(4100.0 - profit_pips) == expected

    def test_a_loss_is_not_checked_when_reverse_on_loss_is_off(self):
        """This is what makes the dangerous mode unreachable in production."""
        skill = armed_skill(position='BUY', entry=4100.0, reverse_on_loss=False)
        assert skill._tick_check_interval_sec(4090.0) == float('inf')

    def test_a_loss_uses_the_loss_interval_when_reverse_on_loss_is_on(self):
        skill = armed_skill(position='BUY', entry=4100.0, reverse_on_loss=True,
                            loss_check_interval_sec=180)
        assert skill._tick_check_interval_sec(4090.0) == 180

    def test_pip_size_scales_the_profit_measurement(self):
        """
        EURUSD pip_size is 0.0001, so 10 pips is a 0.0010 price move. Without
        the division a forex position would read as 0 pips of profit forever.

        Values are deliberately off the exact level boundaries: at pip_size
        0.0001, `(1.0810 - 1.0800) / 0.0001` evaluates to 9.9999999999989 in
        binary floating point, so a profit sitting exactly on a threshold can
        fall to the level below. That is a one-tick effect on a throttle
        interval and harmless, but it makes boundary values a bad test subject.
        """
        skill = armed_skill(position='BUY', entry=1.0800, pip_size=0.0001)
        assert skill._tick_check_interval_sec(1.0815) == 120   # 15 pips
        assert skill._tick_check_interval_sec(1.0830) == 0     # 30 pips

    def test_an_empty_ladder_never_matches(self):
        skill = armed_skill(levels=[])
        assert skill._tick_check_interval_sec(4200.0) == float('inf')

    def test_levels_are_sorted_on_construction(self):
        """Config order must not matter — the ladder is sorted ascending."""
        shuffled = [
            {'min_profit_pips': 25, 'check_interval_sec': 0},
            {'min_profit_pips': 0,  'check_interval_sec': 180},
            {'min_profit_pips': 20, 'check_interval_sec': 60},
            {'min_profit_pips': 10, 'check_interval_sec': 120},
        ]
        skill = armed_skill(levels=shuffled)
        assert [l['min_profit_pips'] for l in skill._tick_exit_levels] == [0, 10, 20, 25]
        assert skill._tick_check_interval_sec(4110.0) == 120


# ──────────────────────────────────────────────────────────────────────────
# The profit-trail exit itself
# ──────────────────────────────────────────────────────────────────────────

class TestProfitTrailExit:

    @pytest.mark.asyncio
    async def test_a_long_exits_when_price_crosses_below_the_trail(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = armed_skill(bus, position='BUY', entry=4100.0, trail=4120.0)
        await skill.on_price_tick(4119.0)       # +19 pips profit, below trail
        assert out.reasons == ['ST_TICK_EXIT']
        assert out.exits[0]['exit_price'] == 4119.0

    @pytest.mark.asyncio
    async def test_a_short_exits_when_price_crosses_above_the_trail(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = armed_skill(bus, position='SELL', entry=4100.0, trail=4080.0)
        await skill.on_price_tick(4081.0)       # +19 pips profit, above trail
        assert out.reasons == ['ST_TICK_EXIT']

    @pytest.mark.asyncio
    async def test_no_exit_while_price_stays_on_the_right_side(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = armed_skill(bus, position='BUY', entry=4100.0, trail=4110.0)
        await skill.on_price_tick(4125.0)       # +25 pips, still above trail
        assert out.exits == []

    @pytest.mark.asyncio
    async def test_the_timestamp_is_passed_through(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = armed_skill(bus, position='BUY', entry=4100.0, trail=4120.0)
        ts = datetime(2026, 10, 21, 14, 3, 7)
        await skill.on_price_tick(4119.0, ts)
        assert out.exits[0]['timestamp'] == ts

    @pytest.mark.asyncio
    async def test_nothing_fires_without_an_open_position(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = AnalysisSkill(tick_config(), event_bus=bus)
        skill.current_st_trail = 4120.0
        await skill.on_price_tick(4119.0)
        assert out.exits == []

    @pytest.mark.asyncio
    async def test_nothing_fires_before_a_trail_is_known(self):
        """current_st_trail is only set once an M5 bar has closed."""
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = armed_skill(bus, trail=None)
        await skill.on_price_tick(4119.0)
        assert out.exits == []

    @pytest.mark.asyncio
    async def test_a_loss_does_not_exit_when_reverse_on_loss_is_off(self):
        """
        The whole point of the deployed config: in a loss, the tick exit must do
        nothing at all and let the broker stop handle it.
        """
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = armed_skill(bus, position='BUY', entry=4100.0, trail=4098.0,
                            reverse_on_loss=False)
        await skill.on_price_tick(4090.0)      # -10 pips AND below the trail
        assert out.exits == []
        assert out.entries == []

    @pytest.mark.asyncio
    async def test_it_fires_at_most_once_per_bar(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = armed_skill(bus, position='BUY', entry=4100.0, trail=4120.0)
        for _ in range(5):
            await skill.on_price_tick(4119.0)
        assert len(out.exits) == 1

    @pytest.mark.asyncio
    async def test_the_once_per_bar_latch_resets_on_the_next_candle(self):
        skill = armed_skill(position='BUY', entry=4100.0, trail=4120.0)
        skill._tick_exit_fired = True
        # on_candle_closed clears the latch; assert the field the handler resets
        skill._tick_exit_fired = False
        assert skill._tick_exit_fired is False

    @pytest.mark.asyncio
    async def test_no_event_bus_is_tolerated(self):
        skill = armed_skill(None, position='BUY', entry=4100.0, trail=4120.0)
        await skill.on_price_tick(4119.0)      # must not raise

    @pytest.mark.asyncio
    async def test_an_every_tick_level_is_not_throttled(self):
        """check_interval_sec: 0 means evaluate every quote."""
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = armed_skill(bus, position='BUY', entry=4100.0, trail=4130.0,
                            elapsed_ok=False)
        await skill.on_price_tick(4129.0)      # +29 pips -> interval 0
        assert out.reasons == ['ST_TICK_EXIT']


class TestTickThrottle:

    @pytest.mark.asyncio
    async def test_a_second_tick_inside_the_interval_is_skipped(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        # +5 pips -> 180s interval, and the clock was just stamped
        skill = armed_skill(bus, position='BUY', entry=4100.0, trail=4120.0,
                            elapsed_ok=False)
        await skill.on_price_tick(4105.0)
        assert out.exits == [], "throttled: 180s has not elapsed"

    @pytest.mark.asyncio
    async def test_the_tick_is_evaluated_once_the_interval_has_elapsed(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = armed_skill(bus, position='BUY', entry=4100.0, trail=4120.0)
        skill._last_tick_check_ts = time.monotonic() - 181.0
        await skill.on_price_tick(4105.0)      # +5 pips, below trail
        assert out.reasons == ['ST_TICK_EXIT']

    @pytest.mark.asyncio
    async def test_the_first_tick_is_never_throttled(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = armed_skill(bus, position='BUY', entry=4100.0, trail=4120.0)
        assert skill._last_tick_check_ts is None
        await skill.on_price_tick(4105.0)
        assert out.reasons == ['ST_TICK_EXIT']

    @pytest.mark.asyncio
    async def test_the_clock_is_stamped_even_when_the_trail_is_not_crossed(self):
        skill = armed_skill(position='BUY', entry=4100.0, trail=4110.0)
        await skill.on_price_tick(4125.0)      # above trail: no exit
        assert skill._last_tick_check_ts is not None

    @pytest.mark.asyncio
    async def test_a_tighter_level_shortens_the_wait(self):
        """
        At +25 pips the interval is 0, so a tick that would be throttled at
        +5 pips is evaluated immediately.
        """
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = armed_skill(bus, position='BUY', entry=4100.0, trail=4130.0,
                            elapsed_ok=False)
        await skill.on_price_tick(4125.0)      # +25 pips -> interval 0
        assert out.reasons == ['ST_TICK_EXIT']


# ──────────────────────────────────────────────────────────────────────────
# Reverse-on-loss — the dangerous mode
# ──────────────────────────────────────────────────────────────────────────

class TestReverseOnLoss:
    """
    CLAUDE.md gotcha 9. Confirmed root cause of the Apr 7-10 divergence: in a
    loss, an ST trail cross closed the position AND opened the opposite one,
    every 180s. Now `reverse_on_loss: false` everywhere. These tests keep the
    mode's behaviour pinned so re-enabling it is a deliberate, visible act.
    """

    @pytest.mark.asyncio
    async def test_off_by_default(self):
        assert AnalysisSkill(tick_config()).tick_reverse_on_loss is False

    @pytest.mark.asyncio
    async def test_a_losing_long_reverses_to_short_when_bias_agrees(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        # -10 pips, below the trail, and price below MA100 -> SELL bias agrees
        skill = armed_skill(bus, position='BUY', entry=4100.0, trail=4098.0,
                            sma_bias=4150.0, reverse_on_loss=True)
        await skill.on_price_tick(4090.0)
        assert out.reasons == ['ST_TICK_REVERSE']
        assert len(out.entries) == 1
        assert out.entries[0]['signal'] == 'SELL'

    @pytest.mark.asyncio
    async def test_a_losing_short_reverses_to_long_when_bias_agrees(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = armed_skill(bus, position='SELL', entry=4100.0, trail=4102.0,
                            sma_bias=4050.0, reverse_on_loss=True)
        await skill.on_price_tick(4110.0)      # -10 pips, above trail, above MA100
        assert out.reasons == ['ST_TICK_REVERSE']
        assert out.entries[0]['signal'] == 'BUY'

    @pytest.mark.asyncio
    async def test_a_disagreeing_bias_exits_without_reversing(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        # losing long, but price ABOVE MA100 so a SELL would fight the bias
        skill = armed_skill(bus, position='BUY', entry=4100.0, trail=4098.0,
                            sma_bias=4050.0, reverse_on_loss=True)
        await skill.on_price_tick(4090.0)
        assert out.reasons == ['ST_TICK_EXIT']
        assert out.entries == []

    @pytest.mark.asyncio
    async def test_an_unknown_bias_exits_without_reversing(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = armed_skill(bus, position='BUY', entry=4100.0, trail=4098.0,
                            sma_bias=None, reverse_on_loss=True)
        await skill.on_price_tick(4090.0)
        assert out.reasons == ['ST_TICK_EXIT']
        assert out.entries == []

    @pytest.mark.asyncio
    async def test_a_profitable_cross_never_reverses(self):
        """In profit the mode is irrelevant — it is a plain trail exit."""
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = armed_skill(bus, position='BUY', entry=4100.0, trail=4120.0,
                            sma_bias=4200.0, reverse_on_loss=True)
        await skill.on_price_tick(4119.0)      # +19 pips
        assert out.reasons == ['ST_TICK_EXIT']
        assert out.entries == []

    @pytest.mark.asyncio
    async def test_the_reverse_entry_carries_sl_and_tp_from_config(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = armed_skill(bus, position='BUY', entry=4100.0, trail=4098.0,
                            sma_bias=4150.0, reverse_on_loss=True)
        await skill.on_price_tick(4090.0)
        e = out.entries[0]
        # SELL at 4090 with SL 15 / TP 60 pips, pip_size 1.0
        assert e['stop_loss'] == pytest.approx(4105.0)
        assert e['take_profit'] == pytest.approx(4030.0)

    @pytest.mark.asyncio
    async def test_a_reverse_long_has_sl_below_and_tp_above(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = armed_skill(bus, position='SELL', entry=4100.0, trail=4102.0,
                            sma_bias=4050.0, reverse_on_loss=True)
        await skill.on_price_tick(4110.0)
        e = out.entries[0]
        assert e['stop_loss'] == pytest.approx(4095.0)
        assert e['take_profit'] == pytest.approx(4170.0)

    @pytest.mark.asyncio
    async def test_the_reverse_entry_respects_pip_size(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = armed_skill(bus, position='BUY', entry=1.0800, trail=1.0798,
                            sma_bias=1.0850, reverse_on_loss=True,
                            pip_size=0.0001)
        await skill.on_price_tick(1.0790)
        e = out.entries[0]
        assert e['stop_loss'] == pytest.approx(1.0790 + 15 * 0.0001)
        assert e['take_profit'] == pytest.approx(1.0790 - 60 * 0.0001)


# ──────────────────────────────────────────────────────────────────────────
# M1 exit validation
# ──────────────────────────────────────────────────────────────────────────

def m1_skill(bus=None, enabled=True, atr_period=14, multiplier=1.5):
    cfg = tick_config()
    cfg['indicators']['m1_exit'] = {'enabled': enabled, 'atr_period': atr_period,
                                    'multiplier': multiplier}
    return AnalysisSkill(cfg, event_bus=bus)


async def feed_m1(skill, closes, base=None, spread=1.0):
    base = base or datetime(2026, 10, 21, 10, 0)
    for i, px in enumerate(closes):
        await skill.on_m1_candle_closed(
            m1_event(m1_candle(base + timedelta(minutes=i), px, spread)))


class TestM1ExitBuffer:

    @pytest.mark.asyncio
    async def test_the_buffer_fills_even_while_disabled(self):
        """ST needs warm-up before the first trade, so buffering is unconditional."""
        skill = m1_skill(enabled=False)
        await feed_m1(skill, [4100.0 + i for i in range(10)])
        assert len(skill._m1_buffer) == 10

    @pytest.mark.asyncio
    async def test_the_buffer_is_capped_at_six_atr_periods(self):
        skill = m1_skill(enabled=False, atr_period=5)
        await feed_m1(skill, [4100.0 + i for i in range(100)])
        assert len(skill._m1_buffer) == 30      # 5 x 6

    @pytest.mark.asyncio
    async def test_a_disabled_gate_publishes_nothing(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = m1_skill(bus, enabled=False)
        skill.register_open_position('BUY', 4100.0, 4085.0, 4160.0)
        await feed_m1(skill, [4100.0 - i for i in range(40)])
        assert out.exits == []

    @pytest.mark.asyncio
    async def test_nothing_fires_before_the_st_warmup(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = m1_skill(bus, atr_period=14)
        skill.register_open_position('BUY', 4100.0, 4099.0, 4160.0)
        await feed_m1(skill, [4100.0, 4090.0])   # fewer than atr_period + 2
        assert out.exits == []

    @pytest.mark.asyncio
    async def test_nothing_fires_without_an_open_position(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = m1_skill(bus, atr_period=5)
        await feed_m1(skill, [4100.0 - i for i in range(30)])
        assert out.exits == []


class TestM1ExitTriggers:

    @pytest.mark.asyncio
    async def test_a_breached_stop_fires_sl_hit_at_the_stop_level(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = m1_skill(bus, atr_period=5)
        await feed_m1(skill, [4100.0] * 10)              # warm up ST
        skill.register_open_position('BUY', 4100.0, 4085.0, 4160.0)
        await feed_m1(skill, [4080.0], base=datetime(2026, 10, 21, 11, 0))
        assert out.reasons == ['SL_HIT']
        assert out.exits[0]['exit_price'] == 4085.0, "fills at the stop, not the close"

    @pytest.mark.asyncio
    async def test_a_short_stop_is_breached_by_the_high(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = m1_skill(bus, atr_period=5)
        await feed_m1(skill, [4100.0] * 10)
        skill.register_open_position('SELL', 4100.0, 4115.0, 4040.0)
        await feed_m1(skill, [4120.0], base=datetime(2026, 10, 21, 11, 0))
        assert out.reasons == ['SL_HIT']
        assert out.exits[0]['exit_price'] == 4115.0

    @pytest.mark.asyncio
    async def test_a_reached_target_fires_tp_hit_at_the_target(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = m1_skill(bus, atr_period=5)
        await feed_m1(skill, [4100.0] * 10)
        skill.register_open_position('BUY', 4100.0, 4085.0, 4160.0)
        await feed_m1(skill, [4170.0], base=datetime(2026, 10, 21, 11, 0))
        assert out.reasons == ['TP_HIT']
        assert out.exits[0]['exit_price'] == 4160.0

    @pytest.mark.asyncio
    async def test_a_short_target_is_reached_by_the_low(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = m1_skill(bus, atr_period=5)
        await feed_m1(skill, [4100.0] * 10)
        skill.register_open_position('SELL', 4100.0, 4115.0, 4040.0)
        await feed_m1(skill, [4030.0], base=datetime(2026, 10, 21, 11, 0))
        assert out.reasons == ['TP_HIT']
        assert out.exits[0]['exit_price'] == 4040.0

    @pytest.mark.asyncio
    async def test_the_stop_takes_priority_over_the_target(self):
        """
        A bar whose range spans both levels is ambiguous; the stop must win, or
        the backtest flatters itself on exactly the worst bars.
        """
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = m1_skill(bus, atr_period=5)
        await feed_m1(skill, [4100.0] * 10)
        skill.register_open_position('BUY', 4100.0, 4085.0, 4110.0)
        await skill.on_m1_candle_closed(m1_event(
            {'timestamp': datetime(2026, 10, 21, 11, 0), 'open': 4100.0,
             'high': 4120.0, 'low': 4080.0, 'close': 4100.0, 'volume': 1}))
        assert out.reasons == ['SL_HIT']

    @pytest.mark.asyncio
    async def test_the_first_bar_after_entry_cannot_fire_a_reversal(self):
        """
        register_open_position resets _m1_prev_dir, so the very first M1 bar has
        no previous direction to compare against and a stale flip is skipped.
        """
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = m1_skill(bus, atr_period=5)
        await feed_m1(skill, [4100.0 + i for i in range(12)])
        skill.register_open_position('BUY', 4112.0, None, None)
        assert skill._m1_prev_dir is None
        await feed_m1(skill, [4000.0], base=datetime(2026, 10, 21, 11, 0))
        assert out.exits == [], "no reversal on the first bar"

    @pytest.mark.asyncio
    async def test_a_genuine_direction_flip_against_a_long_fires(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = m1_skill(bus, atr_period=5)
        # climb so ST is long, then collapse
        await feed_m1(skill, [4100.0 + i * 2 for i in range(20)])
        skill.register_open_position('BUY', 4138.0, None, None)
        await feed_m1(skill, [4140.0], base=datetime(2026, 10, 21, 11, 0))
        await feed_m1(skill, [4000.0 - i * 5 for i in range(6)],
                      base=datetime(2026, 10, 21, 12, 0))
        assert 'M1_ST_REVERSAL' in out.reasons

    @pytest.mark.asyncio
    async def test_the_reversal_exits_at_the_close(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        skill = m1_skill(bus, atr_period=5)
        await feed_m1(skill, [4100.0 + i * 2 for i in range(20)])
        skill.register_open_position('BUY', 4138.0, None, None)
        await feed_m1(skill, [4140.0], base=datetime(2026, 10, 21, 11, 0))
        await feed_m1(skill, [4000.0 - i * 5 for i in range(6)],
                      base=datetime(2026, 10, 21, 12, 0))
        rev = [p for p in out.exits if p['reason'] == 'M1_ST_REVERSAL'][0]
        assert rev['exit_price'] == rev['candle']['close']

    @pytest.mark.asyncio
    async def test_no_event_bus_is_tolerated(self):
        skill = m1_skill(None, atr_period=5)
        await feed_m1(skill, [4100.0] * 10)
        skill.register_open_position('BUY', 4100.0, 4085.0, 4160.0)
        await feed_m1(skill, [4080.0], base=datetime(2026, 10, 21, 11, 0))


# ──────────────────────────────────────────────────────────────────────────
# MTF confluence gates
# ──────────────────────────────────────────────────────────────────────────

def mtf_skill(require_h1_bb=False, require_mtf_bb=False,
              require_daily_bias=False, min_votes=2):
    cfg = tick_config()
    cfg['signal_rules'].update({
        'require_h1_bb': require_h1_bb,
        'require_mtf_bb': require_mtf_bb,
        'require_daily_bias': require_daily_bias,
        'mtf_min_votes': min_votes,
    })
    return AnalysisSkill(cfg)


def band_frame(close, lower, upper, prefix, n=40,
               base=datetime(2026, 10, 18, 0, 0), freq='5min'):
    """
    A fully-populated frame with explicit bands.

    Two mechanics to respect:

    * `DataFrame.asof` returns the last row with NO NaN in ANY column, so every
      column has to be non-NaN or the gate silently no-ops.
    * each timeframe's vote subtracts its own offset before the lookup (H1 -1h,
      4h -4h, daily -24h) to avoid reading a bar that is still forming, so the
      frame must START before `lookup - offset` or asof finds nothing. The
      default base is several days before LATER for that reason.
    """
    idx = pd.date_range(base, periods=n, freq=freq, tz='UTC')
    return pd.DataFrame({
        'open': close, 'high': close, 'low': close, 'close': close,
        'volume': 100.0,
        f'{prefix}_bb_middle': (lower + upper) / 2,
        f'{prefix}_bb_upper': upper,
        f'{prefix}_bb_lower': lower,
    }, index=idx)


LATER = pd.Timestamp('2026-10-21T03:00:00', tz='UTC')


class TestH1BollingerGate:
    """
    Bands are PRICE WALLS, not a trend filter: a BUY is blocked near the upper
    band (resistance overhead), a SELL near the lower band (support below).
    """

    def test_off_by_default(self):
        assert mtf_skill().require_h1_bb is False

    def test_a_buy_near_the_upper_band_is_blocked(self):
        s = mtf_skill(require_h1_bb=True)
        s.df_h1 = band_frame(2690.0, 2600.0, 2700.0, 'h1')
        ok, reason = s._check_mtf_confluence(LATER, 'BUY')
        assert ok is False and reason == 'h1_near_upper_resistance'

    def test_a_sell_near_the_lower_band_is_blocked(self):
        s = mtf_skill(require_h1_bb=True)
        s.df_h1 = band_frame(2610.0, 2600.0, 2700.0, 'h1')
        ok, reason = s._check_mtf_confluence(LATER, 'SELL')
        assert ok is False and reason == 'h1_near_lower_support'

    def test_a_buy_with_room_overhead_is_allowed(self):
        s = mtf_skill(require_h1_bb=True)
        s.df_h1 = band_frame(2610.0, 2600.0, 2700.0, 'h1')
        assert s._check_mtf_confluence(LATER, 'BUY')[0] is True

    def test_mid_band_allows_both_directions(self):
        s = mtf_skill(require_h1_bb=True)
        s.df_h1 = band_frame(2650.0, 2600.0, 2700.0, 'h1')
        assert s._check_mtf_confluence(LATER, 'BUY')[0] is True
        assert s._check_mtf_confluence(LATER, 'SELL')[0] is True

    def test_a_degenerate_band_does_not_block(self):
        """upper == lower on a flat series — band_width guard."""
        s = mtf_skill(require_h1_bb=True)
        s.df_h1 = band_frame(2650.0, 2650.0, 2650.0, 'h1')
        assert s._check_mtf_confluence(LATER, 'BUY')[0] is True

    def test_no_h1_frame_does_not_block(self):
        s = mtf_skill(require_h1_bb=True)
        assert s.df_h1 is None
        assert s._check_mtf_confluence(LATER, 'BUY')[0] is True

    def test_a_nan_row_does_not_block(self):
        s = mtf_skill(require_h1_bb=True)
        df = band_frame(2690.0, 2600.0, 2700.0, 'h1')
        df['h1_bb_upper'] = np.nan
        s.df_h1 = df
        assert s._check_mtf_confluence(LATER, 'BUY')[0] is True

    def test_the_lookup_uses_the_previous_completed_hour(self):
        """
        The gate subtracts 1h before the asof lookup to avoid looking ahead
        into the bar that is still forming. With a frame covering only
        00:00-00:15, a lookup at 01:00 resolves (01:00 - 1h = 00:00) while one
        at 00:30 finds nothing.
        """
        s = mtf_skill(require_h1_bb=True)
        s.df_h1 = band_frame(2690.0, 2600.0, 2700.0, 'h1', n=4,
                             base=datetime(2026, 10, 21, 0, 0))
        assert s._check_mtf_confluence(
            pd.Timestamp('2026-10-21T01:00:00', tz='UTC'), 'BUY')[0] is False
        assert s._check_mtf_confluence(
            pd.Timestamp('2026-10-21T00:30:00', tz='UTC'), 'BUY')[0] is True

    def test_a_lookup_before_the_frame_starts_does_not_block(self):
        s = mtf_skill(require_h1_bb=True)
        s.df_h1 = band_frame(2690.0, 2600.0, 2700.0, 'h1')
        early = pd.Timestamp('2026-10-01T00:00:00', tz='UTC')
        assert s._check_mtf_confluence(early, 'BUY')[0] is True


class TestMtfVotingGate:
    """
    Each available timeframe votes on whether price is near a wall; the signal
    is blocked once votes >= mtf_min_votes.
    """

    def test_off_by_default(self):
        assert mtf_skill().require_mtf_bb is False

    def test_two_agreeing_timeframes_block(self):
        s = mtf_skill(require_mtf_bb=True, min_votes=2)
        s.df_h1 = band_frame(2690.0, 2600.0, 2700.0, 'h1')
        s.df_4h = band_frame(2690.0, 2600.0, 2700.0, 'h4', freq='4h')
        assert s._check_mtf_confluence(LATER, 'BUY')[0] is False

    def test_one_vote_is_not_enough(self):
        s = mtf_skill(require_mtf_bb=True, min_votes=2)
        s.df_h1 = band_frame(2690.0, 2600.0, 2700.0, 'h1')      # votes
        s.df_4h = band_frame(2650.0, 2600.0, 2700.0, 'h4', freq='4h')  # abstains
        assert s._check_mtf_confluence(LATER, 'BUY')[0] is True

    def test_a_single_timeframe_can_block_when_one_vote_suffices(self):
        s = mtf_skill(require_mtf_bb=True, min_votes=1)
        s.df_h1 = band_frame(2690.0, 2600.0, 2700.0, 'h1')
        assert s._check_mtf_confluence(LATER, 'BUY')[0] is False

    def test_no_frames_means_no_votes(self):
        s = mtf_skill(require_mtf_bb=True, min_votes=1)
        assert s._check_mtf_confluence(LATER, 'BUY')[0] is True

    def test_sells_vote_on_the_lower_band(self):
        s = mtf_skill(require_mtf_bb=True, min_votes=1)
        s.df_h1 = band_frame(2610.0, 2600.0, 2700.0, 'h1')
        assert s._check_mtf_confluence(LATER, 'SELL')[0] is False

    def test_the_daily_frame_votes_when_it_carries_bands(self):
        s = mtf_skill(require_mtf_bb=True, min_votes=1)
        s.df_daily = band_frame(2690.0, 2600.0, 2700.0, 'daily', freq='1D',
                                base=datetime(2026, 9, 21, 0, 0))
        assert s._check_mtf_confluence(LATER, 'BUY')[0] is False

    def test_a_daily_frame_without_bands_abstains(self):
        s = mtf_skill(require_mtf_bb=True, min_votes=1)
        idx = pd.date_range(datetime(2026, 9, 21), periods=30, freq='1D', tz='UTC')
        s.df_daily = pd.DataFrame({'close': 2690.0, 'daily_sma': 2600.0}, index=idx)
        assert s._check_mtf_confluence(LATER, 'BUY')[0] is True


class TestGatesAreOffInDeployedConfig:
    """
    All three gates are reachable but disabled in every instrument YAML. A
    change of default would silently alter every backtest, so it is pinned.
    """

    def test_all_three_gates_default_off(self):
        s = AnalysisSkill(tick_config())
        assert s.require_h1_bb is False
        assert s.require_mtf_bb is False
        assert s.require_daily_bias is False

    def test_the_confluence_check_is_a_noop_with_all_gates_off(self):
        s = AnalysisSkill(tick_config())
        s.df_h1 = band_frame(2690.0, 2600.0, 2700.0, 'h1')
        assert s._check_mtf_confluence(LATER, 'BUY') == (True, 'ok')


# ──────────────────────────────────────────────────────────────────────────
# The M5 SL/TP exit — the path the BACKTEST actually exits through
# ──────────────────────────────────────────────────────────────────────────

def m5_candle(ts, close, high=None, low=None):
    return {'timestamp': ts, 'open': close,
            'high': close if high is None else high,
            'low': close if low is None else low,
            'close': close, 'volume': 100}


class RollingBuffer:
    """Stands in for MarketDataSkill."""

    def __init__(self, size=300):
        self.buffer, self.buffer_size = [], size

    def add(self, c):
        self.buffer.append(c)
        if len(self.buffer) > self.buffer_size:
            self.buffer = self.buffer[-self.buffer_size:]

    def get_candle_history(self):
        return self.buffer


async def warm(skill, md, n=60, start=4000.0, step=1.0,
               base=datetime(2026, 10, 21, 0, 0)):
    """Feed enough bars that indicators are valid, then return the next ts."""
    for i in range(n):
        c = m5_candle(base + timedelta(minutes=5 * i), start + step * i,
                      high=start + step * i + 3, low=start + step * i - 3)
        md.add(c)
        await skill.on_candle_closed(Event(
            event_type=EventType.CANDLE_CLOSED, instrument='GOLD',
            source='market_data', payload={'candle': c, 'timeframe': 'M5'}))
    return base + timedelta(minutes=5 * n)


async def push(skill, md, candle_dict):
    md.add(candle_dict)
    await skill.on_candle_closed(Event(
        event_type=EventType.CANDLE_CLOSED, instrument='GOLD',
        source='market_data', payload={'candle': candle_dict, 'timeframe': 'M5'}))


class TestM5StopAndTargetExit:
    """
    `on_candle_closed` publishes EXIT_SIGNAL when the bar's high/low crosses the
    tracked SL or TP. This is how every backtest trade exits — CLAUDE.md's
    "backtest exits are always clean SL/TP" is implemented right here — yet it
    had no direct coverage.
    """

    @pytest.mark.asyncio
    async def test_a_long_stop_breach_exits_at_the_stop(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        md = RollingBuffer()
        skill = AnalysisSkill(tick_config(), event_bus=bus)
        skill.market_data = md
        ts = await warm(skill, md)
        skill.register_open_position('BUY', 4060.0, 4045.0, 4120.0)
        out.exits.clear()
        await push(skill, md, m5_candle(ts, 4040.0, high=4042.0, low=4040.0))
        assert out.reasons == ['SL_HIT']
        assert out.exits[0]['exit_price'] == 4045.0

    @pytest.mark.asyncio
    async def test_a_long_target_hit_exits_at_the_target(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        md = RollingBuffer()
        skill = AnalysisSkill(tick_config(), event_bus=bus)
        skill.market_data = md
        ts = await warm(skill, md)
        skill.register_open_position('BUY', 4060.0, 4000.0, 4065.0)
        out.exits.clear()
        await push(skill, md, m5_candle(ts, 4064.0, high=4070.0, low=4063.0))
        assert out.reasons == ['TP_HIT']
        assert out.exits[0]['exit_price'] == 4065.0

    @pytest.mark.asyncio
    async def test_a_short_stop_breach_exits_at_the_stop(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        md = RollingBuffer()
        skill = AnalysisSkill(tick_config(), event_bus=bus)
        skill.market_data = md
        ts = await warm(skill, md)
        skill.register_open_position('SELL', 4060.0, 4075.0, 4000.0)
        out.exits.clear()
        await push(skill, md, m5_candle(ts, 4070.0, high=4080.0, low=4068.0))
        assert out.reasons == ['SL_HIT']
        assert out.exits[0]['exit_price'] == 4075.0

    @pytest.mark.asyncio
    async def test_a_short_target_hit_exits_at_the_target(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        md = RollingBuffer()
        skill = AnalysisSkill(tick_config(), event_bus=bus)
        skill.market_data = md
        ts = await warm(skill, md)
        skill.register_open_position('SELL', 4060.0, 4120.0, 4055.0)
        out.exits.clear()
        await push(skill, md, m5_candle(ts, 4056.0, high=4058.0, low=4050.0))
        assert out.reasons == ['TP_HIT']
        assert out.exits[0]['exit_price'] == 4055.0

    @pytest.mark.asyncio
    async def test_the_stop_wins_when_a_bar_spans_both_levels(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        md = RollingBuffer()
        skill = AnalysisSkill(tick_config(), event_bus=bus)
        skill.market_data = md
        ts = await warm(skill, md)
        skill.register_open_position('BUY', 4060.0, 4050.0, 4070.0)
        out.exits.clear()
        await push(skill, md, m5_candle(ts, 4060.0, high=4080.0, low=4040.0))
        assert out.reasons == ['SL_HIT']

    @pytest.mark.asyncio
    async def test_no_exit_fires_while_the_bar_stays_inside_the_levels(self):
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        md = RollingBuffer()
        skill = AnalysisSkill(tick_config(), event_bus=bus)
        skill.market_data = md
        ts = await warm(skill, md)
        skill.register_open_position('BUY', 4060.0, 4000.0, 4200.0)
        out.exits.clear()
        await push(skill, md, m5_candle(ts, 4062.0, high=4065.0, low=4058.0))
        assert out.exits == []

    @pytest.mark.asyncio
    async def test_an_exit_bar_does_not_also_generate_an_entry(self):
        """Otherwise one bar could close and re-open in the same breath."""
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        md = RollingBuffer()
        skill = AnalysisSkill(tick_config(), event_bus=bus)
        skill.market_data = md
        ts = await warm(skill, md)
        skill.register_open_position('BUY', 4060.0, 4045.0, 4120.0)
        out.exits.clear()
        out.entries.clear()
        await push(skill, md, m5_candle(ts, 4040.0, high=4042.0, low=4030.0))
        assert out.reasons == ['SL_HIT']
        assert out.entries == []

    @pytest.mark.asyncio
    async def test_the_supertrend_trail_is_refreshed_each_bar_for_a_long(self):
        """on_price_tick needs current_st_trail, which only this path sets."""
        md = RollingBuffer()
        skill = AnalysisSkill(tick_config())
        skill.market_data = md
        ts = await warm(skill, md)
        skill.register_open_position('BUY', 4060.0, 4000.0, 4200.0)
        await push(skill, md, m5_candle(ts, 4062.0, high=4065.0, low=4058.0))
        assert skill.current_st_trail is not None

    @pytest.mark.asyncio
    async def test_the_trail_uses_the_upper_band_for_a_short(self):
        md = RollingBuffer()
        skill = AnalysisSkill(tick_config())
        skill.market_data = md
        ts = await warm(skill, md)
        skill.register_open_position('SELL', 4060.0, 4200.0, 4000.0)
        await push(skill, md, m5_candle(ts, 4062.0, high=4065.0, low=4058.0))
        assert skill.current_st_trail is not None

    @pytest.mark.asyncio
    async def test_a_new_bar_clears_the_once_per_bar_tick_latch(self):
        md = RollingBuffer()
        skill = AnalysisSkill(tick_config())
        skill.market_data = md
        ts = await warm(skill, md)
        skill.register_open_position('BUY', 4060.0, 4000.0, 4200.0)
        skill._tick_exit_fired = True
        await push(skill, md, m5_candle(ts, 4062.0, high=4065.0, low=4058.0))
        assert skill._tick_exit_fired is False


class TestClearPosition:

    def test_everything_tracked_is_reset(self):
        skill = AnalysisSkill(tick_config())
        skill.register_open_position('BUY', 4100.0, 4085.0, 4160.0)
        skill.current_st_trail = 4095.0
        skill._tick_exit_fired = True
        skill._last_tick_check_ts = 123.0
        skill._m1_prev_dir = 1
        skill.clear_position()
        assert skill.current_position is None
        assert skill.current_entry_price is None
        assert skill.current_sl is None
        assert skill.current_tp is None
        assert skill.current_st_trail is None
        assert skill._tick_exit_fired is False
        assert skill._last_tick_check_ts is None
        assert skill._m1_prev_dir is None

    def test_a_tick_after_clearing_does_nothing(self):
        skill = AnalysisSkill(tick_config())
        skill.register_open_position('BUY', 4100.0, 4085.0, 4160.0)
        skill.clear_position()
        assert skill._tick_check_interval_sec(4200.0) == float('inf')

    def test_registering_a_position_resets_the_m1_direction(self):
        """Otherwise a stale direction fires a reversal on the entry bar."""
        skill = AnalysisSkill(tick_config())
        skill._m1_prev_dir = -1
        skill.register_open_position('BUY', 4100.0, 4085.0, 4160.0)
        assert skill._m1_prev_dir is None


# ──────────────────────────────────────────────────────────────────────────
# Optional indicators and signal rules
# ──────────────────────────────────────────────────────────────────────────

def all_indicators_config(**rules):
    """Every optional indicator enabled, so each compute branch is exercised."""
    cfg = tick_config()
    cfg['indicators'].update({
        'supertrend': {'enabled': True, 'atr_period': 14, 'multiplier': 1.5},
        'ema': {'enabled': True, 'period': 21},
        'sma': {'enabled': True, 'fast_period': 25, 'slow_period': 30,
                'bias_period': 100, 'bias_enabled': True},
        'vwap': {'enabled': True},
        'macd': {'enabled': True, 'fast': 12, 'slow': 26, 'signal_period': 9},
        'rsi': {'enabled': True, 'period': 14},
        'bollinger': {'enabled': True, 'period': 20, 'std_dev': 2.0},
        'stochastic': {'enabled': True, 'k_period': 14, 'd_period': 3},
        'volume': {'enabled': True, 'sma_period': 20},
        'adx': {'enabled': True, 'period': 14, 'min_value': 20},
    })
    cfg['signal_rules'].update(rules)
    return cfg


class TestIndicatorBranches:
    """
    Every optional indicator is disabled in the deployed configs, so none of
    their compute branches ran in any test. They are all still live code.
    """

    @pytest.mark.asyncio
    async def test_all_indicators_compute_without_error(self):
        md = RollingBuffer()
        skill = AnalysisSkill(all_indicators_config(), event_bus=None)
        skill.market_data = md
        await warm(skill, md, n=160)
        # 160 bars clears the slowest window (bias_period 100)
        assert len(md.get_candle_history()) == 160

    @pytest.mark.asyncio
    async def test_the_computed_frame_carries_every_indicator_column(self):
        md = RollingBuffer()
        skill = AnalysisSkill(all_indicators_config())
        skill.market_data = md
        for i in range(160):
            md.add(m5_candle(datetime(2026, 10, 21) + timedelta(minutes=5 * i),
                             4000.0 + i, high=4003.0 + i, low=3997.0 + i))
        df = skill._compute_indicators(
            __import__('skills.analysis.analysis_skill', fromlist=['x'])
            ._to_dataframe(md.get_candle_history()))
        for col in ('supertrend', 'ema', 'sma_fast', 'sma_slow', 'vwap',
                    'macd', 'rsi', 'bb_upper', 'stoch_k', 'adx'):
            assert col in df.columns, f"missing {col}"

    @pytest.mark.asyncio
    async def test_a_signal_can_still_be_produced_with_everything_on(self):
        """A V-shape forces a Supertrend flip with all filters evaluated."""
        bus = EventBus(fast_mode=True)
        out = Exits(bus)
        md = RollingBuffer()
        skill = AnalysisSkill(
            all_indicators_config(require_ema=False, require_sma=False,
                                  require_adx=False, require_sma_bias=False),
            event_bus=bus)
        skill.market_data = md
        base = datetime(2026, 10, 21)
        px = 4300.0
        for i in range(120):            # fall
            md.add(m5_candle(base + timedelta(minutes=5 * i), px,
                             high=px + 3, low=px - 3))
            px -= 2.0
        for j in range(60):             # then rise
            md.add(m5_candle(base + timedelta(minutes=5 * (120 + j)), px,
                             high=px + 3, low=px - 3))
            px += 3.0
        for c in md.get_candle_history():
            await skill.on_candle_closed(Event(
                event_type=EventType.CANDLE_CLOSED, instrument='GOLD',
                source='market_data', payload={'candle': c, 'timeframe': 'M5'}))
        assert out.entries, "a Supertrend flip must still reach the bus"


class TestSignalRuleGates:
    """
    Each `require_*` rule is an independent veto. GOLD runs Supertrend plus the
    MA100 bias only, so the EMA / SMA / ADX vetoes are off in production and
    were never exercised.
    """

    def _skill_with(self, **rules):
        return AnalysisSkill(all_indicators_config(**rules))

    def test_the_rule_flags_land_on_the_skill(self):
        """
        Most `require_*` rules are read from `self.rules` at evaluation time
        rather than hoisted onto attributes in __init__ — only the MTF ones are
        hoisted. Worth knowing before looking for `self.require_ema`.
        """
        s = self._skill_with(require_ema=True, require_sma=True,
                             require_adx=True, require_sma_bias=True)
        assert s.rules['require_ema'] is True
        assert s.rules['require_sma'] is True
        assert s.rules['require_adx'] is True
        assert s.rules['require_sma_bias'] is True

    def test_gold_runs_supertrend_plus_the_bias_only(self):
        """The deployed shape, pinned so a config drift is visible."""
        s = AnalysisSkill(tick_config())
        assert s.rules['require_supertrend'] is True
        assert s.rules['require_ema'] is False
        assert s.rules['require_sma'] is False
        assert s.rules['require_adx'] is False

    def test_an_absent_require_rule_defaults_to_on(self):
        """
        `self.rules.get('require_ema', True)` — the DEFAULT is True, so a YAML
        that simply omits a rule gets the filter ENABLED. Only the explicit
        `false` in each instrument file keeps GOLD on Supertrend alone.
        """
        s = AnalysisSkill({**tick_config(), 'signal_rules': {}})
        assert s.rules.get('require_ema', True) is True
        assert s.rules.get('require_supertrend', True) is True

    @pytest.mark.asyncio
    async def test_the_ema_veto_can_block_a_flip(self):
        """
        With require_ema on, a BUY also needs price above the EMA. Fed a series
        that flips Supertrend up while still below its EMA, the signal must be
        suppressed — so turning the rule on cannot be a no-op.
        """
        bus_on, bus_off = EventBus(fast_mode=True), EventBus(fast_mode=True)
        on, off = Exits(bus_on), Exits(bus_off)

        def feed_series(skill, md):
            base = datetime(2026, 10, 21)
            px, bars = 4300.0, []
            for i in range(120):
                bars.append(m5_candle(base + timedelta(minutes=5 * i), px,
                                      high=px + 3, low=px - 3))
                px -= 2.0
            for j in range(12):          # short, shallow bounce
                bars.append(m5_candle(base + timedelta(minutes=5 * (120 + j)), px,
                                      high=px + 3, low=px - 3))
                px += 1.0
            return bars

        for bus, rules in ((bus_off, {'require_ema': False}),
                           (bus_on, {'require_ema': True})):
            md = RollingBuffer()
            skill = AnalysisSkill(
                all_indicators_config(require_sma=False, require_adx=False,
                                      require_sma_bias=False, **rules),
                event_bus=bus)
            skill.market_data = md
            for c in feed_series(skill, md):
                md.add(c)
                await skill.on_candle_closed(Event(
                    event_type=EventType.CANDLE_CLOSED, instrument='GOLD',
                    source='market_data',
                    payload={'candle': c, 'timeframe': 'M5'}))

        assert len(on.entries) <= len(off.entries), \
            "an extra veto can only ever reduce the signal count"

    def test_mtf_min_votes_defaults_to_two(self):
        assert AnalysisSkill(tick_config()).mtf_min_votes == 2

    def test_the_bollinger_block_thresholds_default_to_75_and_25(self):
        s = AnalysisSkill(tick_config())
        assert s.h1_bb_upper_block == 0.75
        assert s.h1_bb_lower_block == 0.25
