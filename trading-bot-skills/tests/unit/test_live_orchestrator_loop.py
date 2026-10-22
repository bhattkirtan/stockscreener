"""
Unit tests — orchestrator/trading_orchestrator.py, the live trading loop.

`TradingOrchestrator.on_candle` is the pipeline the live bot actually runs:
`bot_control_api` spawns `orchestrator/main.py`, which builds this orchestrator
and hands it every WebSocket M5 candle. main.py's own tests stop at that call
boundary, so this module sat at 15% (99 of 116 statements uncovered) — the
largest untested surface left in the repo, and it owns three paths with a
history of costing money quietly:

  * `warming_up`, which must suppress signals and orders while historical bars
    are replayed into the buffer (`main.py:608-621`). If it leaks, the bot
    trades its own warm-up — every bar of it, at market.

  * the reverse-signal close (modified 2026-10-22, previously untested). The
    only thing standing between a rejected close and an accumulating stack of
    positions is the abort branch; and the 1.5s settle sleep is the only reason
    Capital.com accepts the replacement order at all.

  * `on_position_closed`, which threads realised P&L into the three risk
    breakers. This is the path CLAUDE.md gotcha 22 broke for ~3 months: P&L
    recorded as 0.0 on 365 trades, so the SL/TP cooldowns never fired, the
    consecutive-loss breaker scored every trade a win, and the daily-loss limit
    stayed pinned at zero. `pnl=None` means "broker figure unavailable" and
    must stay None; a genuine broker 0.0 must survive as 0.0.

Every skill the orchestrator touches is just an object with `execute` plus a
couple of handler methods, so the whole pipeline is driveable with fakes — no
network, no broker. The fakes record what they are handed; the assertions are
about which skills ran, in what order, and with which arguments. Script lists
are consumed one entry per call with the last entry repeating, the same
convention as `FakeCapital` in test_live_poll_loop.py.
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from orchestrator.trading_orchestrator import TradingOrchestrator
from skills.base_skill import Context


# ──────────────────────────────────────────────────────────────────────────
# Fakes
# ──────────────────────────────────────────────────────────────────────────

def candle(close=4100.0, ts='2026-10-21T10:00:00'):
    """The dict shape main.py's WebSocket callback builds (main.py:674)."""
    return {'timestamp': ts, 'open': close, 'high': close + 2,
            'low': close - 2, 'close': close, 'volume': 0}


def _script_next(seq):
    """Consume one entry; the last entry repeats once exhausted."""
    if not seq:
        return None
    return seq.pop(0) if len(seq) > 1 else seq[0]


class FakeSkill:
    """
    A skill as the orchestrator sees one: `validate_config()` + `execute()`.
    Records every context handed to it on `self.seen`, and appends to a shared
    `log` so tests can assert pipeline ORDER, not just participation.
    """

    def __init__(self, valid=True, raises=None, returns_none=False):
        self.config = {}
        self.name = type(self).__name__
        self.label = type(self).__name__
        self.log = None
        self.valid = valid
        self.raises = raises
        self.returns_none = returns_none
        self.seen = []

    def validate_config(self):
        return self.valid

    def _note(self, what):
        if self.log is not None:
            self.log.append(f'{self.label}.{what}')

    async def execute(self, context):
        self.seen.append(context)
        self._note('execute')
        if self.raises is not None:
            raise self.raises
        self._apply(context)
        # A skill that forgets to return the context hands the orchestrator
        # None — see TestErrorContainment.
        return None if self.returns_none else context

    def _apply(self, context):
        pass

    @property
    def ran(self):
        return len(self.seen)


class FakeMarketData(FakeSkill):
    def _apply(self, context):
        context.candle_history.append(context.current_candle)


class FakeAnalysis(FakeSkill):
    def __init__(self, signals=None, **kw):
        super().__init__(**kw)
        self.signals = list(signals) if signals else []

    def _apply(self, context):
        context.signal = _script_next(self.signals)


class FakeRisk(FakeSkill):
    """
    The orchestrator reads three position attributes off the risk skill and
    writes them back after a fill, and calls `on_position_closed`
    SYNCHRONOUSLY — the real `RiskSkill.on_position_closed` is a plain `def`
    (risk_skill.py:576), not a coroutine.
    """

    def __init__(self, allow=True, has_open_position=False, deal_id=None,
                 direction=None, reason='', **kw):
        super().__init__(**kw)
        self.allow = allow if isinstance(allow, list) else [allow]
        self.has_open_position = has_open_position
        self.open_position_deal_id = deal_id
        self.open_position_direction = direction
        self.reason = reason
        self.closed = []            # on_position_closed kwargs, in order

    def _apply(self, context):
        context.is_allowed = bool(_script_next(self.allow))
        context.risk_reason = self.reason

    def on_position_closed(self, **kw):
        self._note('on_position_closed')
        self.closed.append(kw)


class FakeExecution(FakeSkill):
    def __init__(self, deal_ids=None, close_results=None, close_raises=None, **kw):
        super().__init__(**kw)
        self.deal_ids = list(deal_ids) if deal_ids is not None else ['D-NEW']
        self.close_results = list(close_results) if close_results is not None else [True]
        self.close_raises = close_raises
        self.closed = []            # deal_ids passed to close_position

    def _apply(self, context):
        context.deal_id = _script_next(self.deal_ids)

    async def close_position(self, deal_id):
        self.closed.append(deal_id)
        self._note('close_position')
        if self.close_raises is not None:
            raise self.close_raises
        return _script_next(self.close_results)


class FakeStorage(FakeSkill):
    def __init__(self, close_raises=None, **kw):
        super().__init__(**kw)
        self.close_raises = close_raises
        self.closed = []

    async def close_position(self, deal_id, close_price, close_reason, pnl=0.0,
                             direction=None, entry_price=0.0, size=0.0):
        # Record BEFORE any raise so a swallowed failure is still observable.
        self.closed.append(dict(deal_id=deal_id, close_price=close_price,
                                close_reason=close_reason, pnl=pnl,
                                direction=direction, entry_price=entry_price,
                                size=size))
        self._note('close_position')
        if self.close_raises is not None:
            raise self.close_raises


class FakeMonitoring(FakeSkill):
    """
    The orchestrator branches on `asyncio.iscoroutinefunction` before calling
    `on_position_closed`, so both an async and a sync handler must work. The
    real MonitoringSkill handler is async (monitoring_skill.py:128).
    """

    def __init__(self, sync_handler=False, **kw):
        super().__init__(**kw)
        self.events = []
        if sync_handler:
            self.on_position_closed = self._sync_handler

    async def on_position_closed(self, event):
        self._note('on_position_closed')
        self.events.append(event.payload)

    def _sync_handler(self, event):
        self._note('on_position_closed_sync')
        self.events.append(event.payload)


class FakeAlerting(FakeSkill):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.alerts = []

    async def send_trade_closed_alert(self, **kw):
        self._note('send_trade_closed_alert')
        self.alerts.append(kw)


# ──────────────────────────────────────────────────────────────────────────
# Harness
# ──────────────────────────────────────────────────────────────────────────

def build(config=None, **skills):
    """An orchestrator with the named fake skills registered and log-wired."""
    orch = TradingOrchestrator(config if config is not None else {})
    orch.call_log = []
    for name, skill in skills.items():
        skill.label = name
        skill.log = orch.call_log
        orch.register_skill(name, skill)
    return orch


def pipeline(config=None, signals=('BUY',), **overrides):
    """The full 7-skill live pipeline, any member replaceable."""
    skills = {
        'market_data': FakeMarketData(),
        'analysis': FakeAnalysis(signals=list(signals)),
        'risk': FakeRisk(),
        'execution': FakeExecution(),
        'storage': FakeStorage(),
        'monitoring': FakeMonitoring(),
        'alerting': FakeAlerting(),
    }
    skills.update(overrides)
    return build(config, **skills)


REVERSE_ON = {'risk': {'reverse_signal_exit': True}}


@pytest.fixture
def fast_clock(monkeypatch):
    """
    Replace `asyncio.sleep` with an immediate yield that RECORDS its delay, so
    the reverse-close settle wait costs nothing and is still assertable. The
    orchestrator does `import asyncio` at module scope and resolves
    `asyncio.sleep` at call time, so patching the module attribute reaches it.
    """
    real = asyncio.sleep
    delays = []

    async def instant(delay=0):
        delays.append(delay)
        await real(0)

    monkeypatch.setattr(asyncio, 'sleep', instant)
    return delays


# ──────────────────────────────────────────────────────────────────────────
# Registration / lifecycle
# ──────────────────────────────────────────────────────────────────────────

class TestRegistration:

    def test_registered_skill_is_retrievable(self):
        skill = FakeRisk()
        orch = build({}, risk=skill)
        assert orch.get_skill('risk') is skill
        assert list(orch.skills) == ['risk']

    def test_a_skill_failing_validate_config_is_refused(self):
        """A bad config must fail loudly at wiring time, not at the first bar."""
        orch = TradingOrchestrator({})
        with pytest.raises(ValueError, match='Invalid configuration for skill: risk'):
            orch.register_skill('risk', FakeRisk(valid=False))
        assert 'risk' not in orch.skills

    def test_unknown_skill_is_none_not_an_error(self):
        assert TradingOrchestrator({}).get_skill('nope') is None

    def test_fresh_orchestrator_state(self):
        orch = TradingOrchestrator({'risk': {}})
        assert orch.running is False
        assert orch.warming_up is False
        assert orch.total_signals == 0
        assert orch.total_trades == 0
        assert orch.start_time is None


class TestLifecycle:

    @pytest.mark.asyncio
    async def test_start_then_stop(self, capsys):
        orch = pipeline()
        await orch.start()
        assert orch.running is True and orch.start_time is not None
        await orch.stop()
        assert orch.running is False
        out = capsys.readouterr().out
        assert 'Orchestrator started' in out
        assert 'Total signals: 0' in out and 'Total trades: 0' in out

    @pytest.mark.asyncio
    async def test_stop_reports_the_counters_the_session_accumulated(self, capsys):
        orch = pipeline()
        await orch.start()
        await orch.on_candle(candle())
        await orch.stop()
        out = capsys.readouterr().out
        assert 'Total signals: 1' in out and 'Total trades: 1' in out

    @pytest.mark.asyncio
    async def test_stop_without_start_does_not_raise(self, capsys):
        """
        `stop()` subtracts `self.start_time`, which is None until `start()`
        runs. A shutdown path that raises masks whatever caused the shutdown,
        so the runtime falls back to 0.0 instead.
        """
        orch = TradingOrchestrator({})
        await orch.stop()
        assert orch.running is False
        assert 'Runtime: 0.0 minutes' in capsys.readouterr().out


# ──────────────────────────────────────────────────────────────────────────
# Warm-up suppression
# ──────────────────────────────────────────────────────────────────────────

class TestWarmUp:
    """
    main.py sets `warming_up = True` around the historical replay
    (main.py:608-621) and clears it in a `finally`. Every bar of ~300 is fed
    through `on_candle`. If the flag leaks, the bot opens a position on each
    replayed bar — at market, on stale prices.
    """

    @pytest.mark.asyncio
    async def test_warm_up_buffers_the_candle_and_stops(self):
        orch = pipeline()
        orch.warming_up = True
        await orch.on_candle(candle())
        assert orch.skills['market_data'].ran == 1, 'the buffer must still fill'
        assert orch.call_log == ['market_data.execute']

    @pytest.mark.asyncio
    async def test_warm_up_places_no_orders_even_with_a_signal_on_every_bar(self):
        """The replay is ~300 bars; a leak is 300 market orders, not one."""
        orch = pipeline(signals=['BUY', 'SELL'] * 10)
        orch.warming_up = True
        for i in range(20):
            await orch.on_candle(candle(close=4100.0 + i))
        assert orch.skills['market_data'].ran == 20
        assert orch.skills['analysis'].ran == 0
        assert orch.skills['execution'].ran == 0
        assert orch.total_signals == 0
        assert orch.total_trades == 0

    @pytest.mark.asyncio
    async def test_clearing_the_flag_resumes_the_full_pipeline(self):
        """The flag is read per candle, so replay-then-live works on one instance."""
        orch = pipeline(signals=['BUY'])
        orch.warming_up = True
        await orch.on_candle(candle())
        orch.warming_up = False
        await orch.on_candle(candle(close=4105.0))
        assert orch.total_trades == 1
        assert orch.skills['market_data'].ran == 2

    @pytest.mark.asyncio
    async def test_warm_up_with_no_market_data_skill_is_harmless(self):
        orch = build({}, analysis=FakeAnalysis(signals=['BUY']))
        orch.warming_up = True
        await orch.on_candle(candle())
        assert orch.skills['analysis'].ran == 0


# ──────────────────────────────────────────────────────────────────────────
# The happy path and its ordering
# ──────────────────────────────────────────────────────────────────────────

class TestFullPipeline:

    @pytest.mark.asyncio
    async def test_all_seven_stages_run_in_order(self):
        orch = pipeline()
        await orch.on_candle(candle())
        assert orch.call_log == [
            'market_data.execute',
            'analysis.execute',
            'risk.execute',
            'execution.execute',
            'storage.execute',
            'monitoring.execute',
            'alerting.execute',
        ]

    @pytest.mark.asyncio
    async def test_a_fill_updates_the_counters_and_the_risk_position_flags(self):
        """
        The risk skill's open-position gate reads these three attributes, so a
        fill that does not write them back lets the next bar stack a second
        position on the same instrument.
        """
        orch = pipeline(signals=['SELL'], execution=FakeExecution(deal_ids=['D-77']))
        await orch.on_candle(candle())
        risk = orch.skills['risk']
        assert orch.total_signals == 1 and orch.total_trades == 1
        assert risk.has_open_position is True
        assert risk.open_position_deal_id == 'D-77'
        assert risk.open_position_direction == 'SELL'

    @pytest.mark.asyncio
    async def test_the_candle_reaches_market_data_as_the_context_payload(self):
        orch = pipeline()
        bar = candle(close=4123.5)
        await orch.on_candle(bar)
        assert orch.skills['market_data'].seen[0].current_candle is bar

    @pytest.mark.asyncio
    async def test_one_context_is_threaded_through_every_stage(self):
        """Each stage returns the context it was given; a new one would lose the signal."""
        orch = pipeline()
        await orch.on_candle(candle())
        contexts = [orch.skills[n].seen[0] for n in
                    ('market_data', 'analysis', 'risk', 'execution', 'storage')]
        assert all(c is contexts[0] for c in contexts)

    @pytest.mark.asyncio
    async def test_a_sequence_of_bars_accumulates_trades(self):
        orch = pipeline(signals=['BUY', 'SELL', 'BUY'],
                        execution=FakeExecution(deal_ids=['D1', 'D2', 'D3']))
        for i in range(3):
            await orch.on_candle(candle(close=4100.0 + i))
        assert orch.total_signals == 3 and orch.total_trades == 3
        assert orch.skills['risk'].open_position_deal_id == 'D3'

    @pytest.mark.asyncio
    async def test_a_bar_with_no_signal_reaches_analysis_and_stops(self):
        """No signal must mean no risk call and no order — `is_allowed` defaults False."""
        orch = pipeline(signals=[None])
        await orch.on_candle(candle())
        assert orch.skills['analysis'].ran == 1
        assert orch.skills['risk'].ran == 0
        assert orch.skills['execution'].ran == 0
        assert orch.total_signals == 0
        # Monitoring still runs on a quiet bar — it is the metrics heartbeat.
        assert orch.skills['monitoring'].ran == 1
        assert orch.skills['storage'].ran == 0
        assert orch.skills['alerting'].ran == 0

    @pytest.mark.asyncio
    async def test_pipeline_runs_with_only_market_data_registered(self):
        orch = build({}, market_data=FakeMarketData())
        await orch.on_candle(candle())
        assert orch.skills['market_data'].ran == 1

    @pytest.mark.asyncio
    async def test_pipeline_with_no_skills_at_all_is_a_no_op(self):
        orch = TradingOrchestrator({})
        await orch.on_candle(candle())
        assert orch.total_signals == 0 and orch.total_trades == 0


# ──────────────────────────────────────────────────────────────────────────
# Gates must short-circuit
# ──────────────────────────────────────────────────────────────────────────

class TestGateShortCircuit:

    @pytest.mark.asyncio
    async def test_a_blocked_signal_calls_nothing_downstream(self):
        orch = pipeline(risk=FakeRisk(allow=False, reason='Cooldown active'))
        await orch.on_candle(candle())
        assert orch.call_log == ['market_data.execute', 'analysis.execute', 'risk.execute']
        assert orch.skills['execution'].ran == 0
        assert orch.skills['storage'].ran == 0
        assert orch.skills['alerting'].ran == 0
        assert orch.total_trades == 0

    @pytest.mark.asyncio
    async def test_a_blocked_signal_still_counts_as_a_signal(self):
        """`total_signals` is signal generation; `total_trades` is what got through."""
        orch = pipeline(risk=FakeRisk(allow=False))
        await orch.on_candle(candle())
        assert orch.total_signals == 1 and orch.total_trades == 0

    @pytest.mark.asyncio
    async def test_a_blocked_signal_skips_the_monitoring_heartbeat(self):
        """
        The block path `return`s before stage 6, so monitoring does NOT run on a
        blocked bar — unlike a no-signal bar, where it does. Pinned because the
        asymmetry is surprising, not because it is desirable.
        """
        orch = pipeline(risk=FakeRisk(allow=False))
        await orch.on_candle(candle())
        assert orch.skills['monitoring'].ran == 0

    @pytest.mark.asyncio
    async def test_the_block_reason_is_the_one_risk_set(self):
        orch = pipeline(risk=FakeRisk(allow=False, reason='Daily loss limit hit'))
        await orch.on_candle(candle())
        assert orch.skills['risk'].seen[0].risk_reason == 'Daily loss limit hit'

    @pytest.mark.asyncio
    async def test_blocking_one_bar_does_not_block_the_next(self):
        orch = pipeline(signals=['BUY', 'BUY'], risk=FakeRisk(allow=[False, True]))
        await orch.on_candle(candle())
        await orch.on_candle(candle(close=4101.0))
        assert orch.total_trades == 1

    @pytest.mark.asyncio
    async def test_no_risk_skill_means_no_order_at_all(self):
        """
        `Context.is_allowed` defaults to False, so an unregistered risk skill
        fails closed: a signal is generated and nothing is ever placed.
        """
        orch = build({}, market_data=FakeMarketData(),
                     analysis=FakeAnalysis(signals=['BUY']),
                     execution=FakeExecution())
        await orch.on_candle(candle())
        assert orch.total_signals == 1
        assert orch.skills['execution'].ran == 0


class TestBrokerRejectsTheEntry:

    @pytest.mark.asyncio
    async def test_no_deal_id_means_no_trade_and_no_position_flags(self):
        """
        An order the broker drops must leave the bot flat. Setting the risk
        flags here would block every later signal against a position that does
        not exist.
        """
        orch = pipeline(execution=FakeExecution(deal_ids=[None]))
        await orch.on_candle(candle())
        risk = orch.skills['risk']
        assert orch.total_trades == 0
        assert risk.has_open_position is False
        assert risk.open_position_deal_id is None
        assert risk.open_position_direction is None

    @pytest.mark.asyncio
    async def test_no_deal_id_skips_storage_and_alerting_but_not_monitoring(self):
        orch = pipeline(execution=FakeExecution(deal_ids=[None]))
        await orch.on_candle(candle())
        assert orch.skills['storage'].ran == 0
        assert orch.skills['alerting'].ran == 0
        assert orch.skills['monitoring'].ran == 1

    @pytest.mark.asyncio
    async def test_a_rejected_entry_does_not_stop_the_next_bar(self):
        orch = pipeline(signals=['BUY', 'BUY'],
                        execution=FakeExecution(deal_ids=[None, 'D2']))
        await orch.on_candle(candle())
        await orch.on_candle(candle(close=4101.0))
        assert orch.total_trades == 1
        assert orch.skills['risk'].open_position_deal_id == 'D2'


# ──────────────────────────────────────────────────────────────────────────
# Reverse-signal close
# ──────────────────────────────────────────────────────────────────────────

class TestReverseSignalClose:
    """
    Stage 3a. Fires only when `risk.reverse_signal_exit` is true — all six
    deployed YAMLs set it false (CLAUDE.md gotcha 41), so this is latent in
    live today and reachable the moment one is flipped.
    """

    @pytest.mark.asyncio
    async def test_opposite_signal_closes_the_open_position_first(self, fast_clock):
        orch = pipeline(REVERSE_ON, signals=['SELL'],
                        risk=FakeRisk(has_open_position=True, deal_id='D-OLD',
                                      direction='BUY'))
        await orch.on_candle(candle())
        assert orch.skills['execution'].closed == ['D-OLD']
        assert orch.call_log.index('execution.close_position') \
            < orch.call_log.index('execution.execute')

    @pytest.mark.asyncio
    async def test_the_close_is_booked_as_a_reverse_signal_exit(self, fast_clock):
        orch = pipeline(REVERSE_ON, signals=['SELL'],
                        risk=FakeRisk(has_open_position=True, deal_id='D-OLD',
                                      direction='BUY'))
        await orch.on_candle(candle(close=4150.0))
        booked = orch.skills['risk'].closed[0]
        assert booked['direction'] == 'BUY', 'the CLOSED position, not the new signal'
        assert booked['close_reason'] == 'Reverse Signal'
        assert booked['close_price'] == 4150.0
        assert orch.skills['storage'].closed[0]['deal_id'] == 'D-OLD'

    @pytest.mark.asyncio
    async def test_the_new_entry_opens_after_the_close(self, fast_clock):
        orch = pipeline(REVERSE_ON, signals=['SELL'],
                        risk=FakeRisk(has_open_position=True, deal_id='D-OLD',
                                      direction='BUY'),
                        execution=FakeExecution(deal_ids=['D-NEW']))
        await orch.on_candle(candle())
        risk = orch.skills['risk']
        assert orch.total_trades == 1
        assert risk.open_position_deal_id == 'D-NEW'
        assert risk.open_position_direction == 'SELL'

    @pytest.mark.asyncio
    async def test_the_settle_wait_is_15s_and_happens_between_close_and_entry(self, fast_clock):
        """
        Capital.com rejects (DELETES) a new order that arrives while the close
        on the same instrument is still processing. The wait is the only thing
        preventing that, so its presence is behaviour, not an implementation
        detail.
        """
        orch = pipeline(REVERSE_ON, signals=['SELL'],
                        risk=FakeRisk(has_open_position=True, deal_id='D-OLD',
                                      direction='BUY'))
        await orch.on_candle(candle())
        assert fast_clock == [1.5]

    # ── the abort branch ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_a_rejected_close_aborts_the_new_entry(self, fast_clock):
        """
        THE position-accumulation guard. If the broker refuses the close, the
        old position may still be live; opening the new one would leave two
        open on the same instrument in opposite directions.
        """
        orch = pipeline(REVERSE_ON, signals=['SELL'],
                        risk=FakeRisk(has_open_position=True, deal_id='D-OLD',
                                      direction='BUY'),
                        execution=FakeExecution(close_results=[False]))
        await orch.on_candle(candle())
        execution = orch.skills['execution']
        assert execution.closed == ['D-OLD'], 'the close was attempted'
        assert execution.ran == 0, 'but NO new order was placed'
        assert orch.total_trades == 0

    @pytest.mark.asyncio
    async def test_a_rejected_close_skips_the_settle_wait_and_all_later_stages(self, fast_clock):
        orch = pipeline(REVERSE_ON, signals=['SELL'],
                        risk=FakeRisk(has_open_position=True, deal_id='D-OLD',
                                      direction='BUY'),
                        execution=FakeExecution(close_results=[False]))
        await orch.on_candle(candle())
        assert fast_clock == [], 'nothing to settle — the abort returns first'
        assert orch.skills['risk'].ran == 0, 'risk.execute is downstream of the abort'
        assert orch.skills['monitoring'].ran == 0
        assert orch.skills['alerting'].ran == 0

    @pytest.mark.asyncio
    async def test_a_rejected_close_keeps_the_risk_position_flags(self, fast_clock):
        """
        The other half of the accumulation guard. The close result is checked
        BEFORE anything is booked, because `on_position_closed` clears the
        open-position flags — so booking a refused close would leave the bot
        believing it is flat while the broker still holds the position, and the
        next bar's open-position gate would not block. Aborting this bar while
        clearing the flags would defeat the abort.
        """
        orch = pipeline(REVERSE_ON, signals=['SELL'],
                        risk=FakeRisk(has_open_position=True, deal_id='D-OLD',
                                      direction='BUY'),
                        execution=FakeExecution(close_results=[False]))
        await orch.on_candle(candle())
        risk = orch.skills['risk']
        assert risk.has_open_position is True
        assert risk.open_position_deal_id == 'D-OLD'
        assert risk.open_position_direction == 'BUY'
        assert risk.closed == [], 'a refused close must not be booked as a trade'
        assert orch.skills['storage'].closed == []

    @pytest.mark.asyncio
    async def test_a_rejected_close_does_not_wedge_the_loop(self, fast_clock):
        orch = pipeline(REVERSE_ON, signals=['SELL', 'SELL'],
                        risk=FakeRisk(has_open_position=True, deal_id='D-OLD',
                                      direction='BUY'),
                        execution=FakeExecution(close_results=[False, True],
                                                deal_ids=['D-NEW']))
        await orch.on_candle(candle())
        assert orch.total_trades == 0
        # The flags survive the abort, so bar 2 retries the reverse close —
        # which succeeds this time, and the entry follows.
        await orch.on_candle(candle(close=4101.0))
        assert orch.skills['execution'].closed == ['D-OLD', 'D-OLD']
        assert orch.total_trades == 1

    # ── cases that must NOT trigger a close ───────────────────────────────

    @pytest.mark.asyncio
    async def test_reverse_exit_defaults_off_so_no_close_is_attempted(self, fast_clock):
        """
        The default is False and must stay False — it was inconsistent across
        entry points until 2026-10-22 (gotcha 41). An empty config must not
        close positions.
        """
        orch = pipeline({}, signals=['SELL'],
                        risk=FakeRisk(has_open_position=True, deal_id='D-OLD',
                                      direction='BUY'))
        await orch.on_candle(candle())
        assert orch.skills['execution'].closed == []
        assert fast_clock == []

    @pytest.mark.asyncio
    async def test_reverse_exit_explicitly_false_attempts_no_close(self, fast_clock):
        orch = pipeline({'risk': {'reverse_signal_exit': False}}, signals=['SELL'],
                        risk=FakeRisk(has_open_position=True, deal_id='D-OLD',
                                      direction='BUY'))
        await orch.on_candle(candle())
        assert orch.skills['execution'].closed == []

    @pytest.mark.asyncio
    async def test_a_same_direction_signal_does_not_close(self, fast_clock):
        orch = pipeline(REVERSE_ON, signals=['BUY'],
                        risk=FakeRisk(has_open_position=True, deal_id='D-OLD',
                                      direction='BUY'))
        await orch.on_candle(candle())
        assert orch.skills['execution'].closed == []

    @pytest.mark.asyncio
    async def test_a_flat_account_does_not_close(self, fast_clock):
        orch = pipeline(REVERSE_ON, signals=['SELL'], risk=FakeRisk())
        await orch.on_candle(candle())
        assert orch.skills['execution'].closed == []
        assert orch.total_trades == 1

    @pytest.mark.asyncio
    async def test_an_open_position_with_no_recorded_direction_does_not_close(self, fast_clock):
        """Direction None means the position is not reconciled yet — nothing to reverse."""
        orch = pipeline(REVERSE_ON, signals=['SELL'],
                        risk=FakeRisk(has_open_position=True, deal_id='D-OLD',
                                      direction=None))
        await orch.on_candle(candle())
        assert orch.skills['execution'].closed == []

    @pytest.mark.asyncio
    async def test_no_signal_never_reaches_the_reverse_branch(self, fast_clock):
        orch = pipeline(REVERSE_ON, signals=[None],
                        risk=FakeRisk(has_open_position=True, deal_id='D-OLD',
                                      direction='BUY'))
        await orch.on_candle(candle())
        assert orch.skills['execution'].closed == []

    # ── degenerate wiring ─────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_an_open_position_with_no_deal_id_books_the_close_and_continues(self, fast_clock):
        """
        No deal id means no broker call is possible, so the close is treated as
        succeeded and the new entry proceeds; the booking uses 'unknown'.
        """
        orch = pipeline(REVERSE_ON, signals=['SELL'],
                        risk=FakeRisk(has_open_position=True, deal_id=None,
                                      direction='BUY'))
        await orch.on_candle(candle())
        assert orch.skills['execution'].closed == []
        assert orch.skills['storage'].closed[0]['deal_id'] == 'unknown'
        assert fast_clock == [1.5]
        assert orch.total_trades == 1

    @pytest.mark.asyncio
    async def test_no_execution_skill_books_the_close_without_a_broker_call(self, fast_clock):
        orch = build(REVERSE_ON,
                     market_data=FakeMarketData(),
                     analysis=FakeAnalysis(signals=['SELL']),
                     risk=FakeRisk(has_open_position=True, deal_id='D-OLD',
                                   direction='BUY'),
                     storage=FakeStorage())
        await orch.on_candle(candle())
        assert orch.skills['risk'].closed[0]['close_reason'] == 'Reverse Signal'
        assert fast_clock == [1.5]

    @pytest.mark.asyncio
    async def test_a_reverse_close_that_is_then_blocked_by_risk_opens_nothing(self, fast_clock):
        """Closing is stage 3a; the gates still get the final say on re-entry."""
        orch = pipeline(REVERSE_ON, signals=['SELL'],
                        risk=FakeRisk(has_open_position=True, deal_id='D-OLD',
                                      direction='BUY', allow=False,
                                      reason='Skip hour'))
        await orch.on_candle(candle())
        assert orch.skills['execution'].closed == ['D-OLD']
        assert orch.skills['execution'].ran == 0
        assert orch.total_trades == 0


class TestReverseCloseDoesNotInventPnl:
    """
    The reverse path used to hardcode `pnl=0.0` and `entry_price=0.0`, which is
    gotcha 22's regression in miniature: the breakers compute
    `is_loss = pnl < 0`, so 0.0 scored every reverse exit as a WIN and
    contributed nothing to the daily-loss accumulator. Verified against the
    real RiskSkill: four consecutive losing reverse exits left
    `consecutive_losses` at 0 and `_daily_realized_pnl` at 0.0.

    The orchestrator genuinely does not know either figure — it has no broker
    client, and the risk skill tracks only deal id and direction — so it now
    reports both as None ("unknown") and the breakers skip the trade. The real
    numbers arrive moments later from main.py's `_poll_positions`, which sees
    the same close in the activity feed and resolves P&L via
    `get_realised_pnl(deal_id)`.
    """

    @pytest.mark.asyncio
    async def test_the_reverse_close_reports_pnl_as_unknown(self, fast_clock):
        orch = pipeline(REVERSE_ON, signals=['SELL'],
                        risk=FakeRisk(has_open_position=True, deal_id='D-OLD',
                                      direction='BUY'))
        await orch.on_candle(candle(close=4150.0))
        booked = orch.skills['risk'].closed[0]
        assert booked['pnl'] is None, 'must not be 0.0 — that scores as a win'
        assert booked['entry_price'] is None, (
            'must not be 0.0 either, or the price-distance fallback computes '
            '(close - 0.0) and scores a phantom win instead')

    @pytest.mark.asyncio
    async def test_the_real_risk_skill_skips_rather_than_scoring_a_win(self, fast_clock):
        """
        End to end against the REAL RiskSkill with both breakers armed: four
        consecutive losing reverse exits must leave the consecutive-loss
        counter untouched rather than registering four wins.
        """
        from skills.risk.risk_skill import RiskSkill
        risk = RiskSkill({'sl_cooldown_minutes': 30, 'tp_cooldown_minutes': 5,
                          'position_size_pct': 2.0, 'max_consecutive_losses': 4,
                          'max_daily_loss_usd': 150})
        orch = build(REVERSE_ON,
                     market_data=FakeMarketData(),
                     analysis=FakeAnalysis(signals=['SELL']),
                     risk=risk,
                     execution=FakeExecution(deal_ids=['D-NEW']))
        for i in range(4):
            risk.has_open_position = True
            risk.open_position_deal_id = f'D{i}'
            risk.open_position_direction = 'BUY'
            await orch.on_candle(candle(close=3000.0))

        assert risk.consecutive_losses == 0, 'no phantom wins, no phantom losses'
        assert risk.loss_circuit_until is None
        assert risk._daily_realized_pnl == 0.0
        assert risk._daily_halt_date is None
        # And the breaker still works when a real figure IS supplied.
        for _ in range(4):
            risk.on_position_closed(direction='BUY', close_reason='SL_HIT', pnl=-50.0)
        assert risk.consecutive_losses == 4
        assert risk.loss_circuit_until is not None

    @pytest.mark.asyncio
    async def test_the_close_price_is_still_reported(self, fast_clock):
        """The candle close is the one figure the orchestrator does know."""
        orch = pipeline(REVERSE_ON, signals=['SELL'],
                        risk=FakeRisk(has_open_position=True, deal_id='D-OLD',
                                      direction='BUY'))
        await orch.on_candle(candle(close=4150.0))
        assert orch.skills['risk'].closed[0]['close_price'] == 4150.0
        assert orch.skills['storage'].closed[0]['close_price'] == 4150.0


# ──────────────────────────────────────────────────────────────────────────
# Error containment
# ──────────────────────────────────────────────────────────────────────────

class TestErrorContainment:
    """
    `on_candle` is the WebSocket candle callback. A raise that escapes is caught
    one layer up in `CapitalWebSocketClient._handle_message`
    (capital_websocket.py:209), so the socket survives — but the bar is lost
    with only a log line, which is how a broken pipeline stays invisible.
    """

    @pytest.mark.asyncio
    async def test_a_raising_skill_does_not_propagate(self, capsys):
        orch = pipeline(analysis=FakeAnalysis(raises=RuntimeError('indicator blew up')))
        await orch.on_candle(candle())
        assert 'Error in orchestrator: indicator blew up' in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_a_raising_skill_does_not_kill_the_loop(self):
        """The next bar must still be processed end to end."""
        analysis = FakeAnalysis(signals=['BUY', 'BUY'],
                                raises=RuntimeError('transient'))
        orch = pipeline(signals=['BUY', 'BUY'], analysis=analysis)
        await orch.on_candle(candle())
        assert orch.total_trades == 0
        analysis.raises = None
        await orch.on_candle(candle(close=4101.0))
        assert orch.total_trades == 1

    @pytest.mark.asyncio
    async def test_a_raise_in_market_data_stops_the_bar_before_analysis(self, capsys):
        orch = pipeline(market_data=FakeMarketData(raises=RuntimeError('ws gap')))
        await orch.on_candle(candle())
        assert orch.skills['analysis'].ran == 0
        assert 'ws gap' in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_a_raise_in_execution_leaves_the_position_flags_untouched(self, capsys):
        """A failed order must not be recorded as an open position."""
        orch = pipeline(execution=FakeExecution(raises=RuntimeError('broker 500')))
        await orch.on_candle(candle())
        assert orch.total_trades == 0
        assert orch.skills['risk'].has_open_position is False
        assert 'broker 500' in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_a_raise_in_close_position_is_contained(self, fast_clock, capsys):
        orch = pipeline(REVERSE_ON, signals=['SELL'],
                        risk=FakeRisk(has_open_position=True, deal_id='D-OLD',
                                      direction='BUY'),
                        execution=FakeExecution(close_raises=RuntimeError('close 500')))
        await orch.on_candle(candle())
        assert orch.total_trades == 0
        assert 'close 500' in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_a_raise_in_a_late_stage_keeps_the_trade_counted(self, capsys):
        """The order was placed; an alerting failure must not unwind that fact."""
        orch = pipeline(alerting=FakeAlerting(raises=RuntimeError('telegram down')))
        await orch.on_candle(candle())
        assert orch.total_trades == 1
        assert orch.skills['risk'].open_position_deal_id == 'D-NEW'
        assert 'telegram down' in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_a_skill_returning_none_is_contained_and_named(self, caplog):
        """
        A skill whose `execute` forgets to return the context used to rebind
        `context` to None. The next attribute access raised, and then the
        handler's own `context.errors.append(...)` raised AttributeError on
        None — the except block defeated itself and the exception escaped
        `on_candle`. `_run_skill` now carries the previous context forward and
        names the offending skill at ERROR level.
        """
        orch = pipeline(market_data=FakeMarketData(returns_none=True))
        with caplog.at_level('ERROR'):
            await orch.on_candle(candle())      # must not raise
        assert "Skill 'market_data' returned None" in caplog.text
        assert 'FakeMarketData' in caplog.text, 'the offending class is named'

    @pytest.mark.asyncio
    async def test_a_skill_returning_none_does_not_lose_the_bar(self):
        """The pipeline continues on the carried-forward context, so the bar still trades."""
        orch = pipeline(market_data=FakeMarketData(returns_none=True))
        await orch.on_candle(candle())
        assert orch.total_signals == 1
        assert orch.total_trades == 1

    @pytest.mark.asyncio
    async def test_a_none_returning_skill_mid_pipeline_keeps_its_work(self, caplog):
        """
        Why carrying the previous context forward is safe rather than lossy:
        skills mutate the context IN PLACE, so `return context` is redundant
        with the mutation. The risk skill's `is_allowed` decision survives even
        though it returned None, and the bar completes normally.
        """
        orch = pipeline(risk=FakeRisk(returns_none=True))
        with caplog.at_level('ERROR'):
            await orch.on_candle(candle())
        assert "Skill 'risk' returned None" in caplog.text
        assert orch.total_trades == 1, 'the gate decision was not lost'

    @pytest.mark.asyncio
    async def test_a_none_returning_risk_skill_that_blocks_still_blocks(self):
        """The same, for the decision that matters more: a block is not lost."""
        orch = pipeline(risk=FakeRisk(allow=False, returns_none=True))
        await orch.on_candle(candle())
        assert orch.total_trades == 0
        assert orch.skills['execution'].ran == 0

    @pytest.mark.asyncio
    async def test_the_failed_bar_is_logged_at_error_with_a_traceback(self, caplog):
        """
        A caught bare Exception must be logged at ERROR (project convention),
        and the traceback is the diagnostic that was missing — the old handler
        only printed the message.
        """
        orch = pipeline(analysis=FakeAnalysis(raises=RuntimeError('boom')))
        with caplog.at_level('ERROR'):
            await orch.on_candle(candle())
        rec = [r for r in caplog.records if 'on_candle' in r.message]
        assert rec and rec[0].levelname == 'ERROR'
        assert rec[0].exc_info is not None, 'no traceback attached'

    @pytest.mark.asyncio
    async def test_the_error_record_is_appended_to_a_discarded_context(self, capsys):
        """
        The handler appends to the local `context`, which goes out of scope
        immediately — `print` is the only durable trace. Documented because it
        looks like error accounting and is not.
        """
        orch = pipeline(analysis=FakeAnalysis(raises=RuntimeError('boom')))
        await orch.on_candle(candle())
        ctx = orch.skills['market_data'].seen[0]
        assert len(ctx.errors) == 1
        assert ctx.errors[0]['location'] == 'orchestrator.on_candle'
        assert ctx.errors[0]['error'] == 'boom'


# ──────────────────────────────────────────────────────────────────────────
# on_position_closed — the P&L threading path
# ──────────────────────────────────────────────────────────────────────────

class TestOnPositionClosedPnl:
    """
    The single most important assertions in this file. `pnl=None` means the
    broker figure is unavailable and MUST stay None: the breakers read
    `is_loss = pnl < 0`, so a coerced 0.0 scores a loss as a win, and
    `_register_daily_pnl(0.0)` keeps the daily-loss limit at zero. A genuine
    broker 0.0 (a real break-even trade) must survive as 0.0 — the two are not
    interchangeable.
    """

    @pytest.mark.asyncio
    async def test_unknown_pnl_stays_none_through_every_consumer(self):
        orch = pipeline()
        await orch.on_position_closed('D1', 'BUY', 'SL_HIT', pnl=None,
                                      entry_price=4100.0, close_price=4085.0, size=10.0)
        assert orch.skills['risk'].closed[0]['pnl'] is None
        assert orch.skills['storage'].closed[0]['pnl'] is None
        assert orch.skills['monitoring'].events[0]['realized_pnl'] is None
        assert orch.skills['alerting'].alerts[0]['pnl'] is None

    @pytest.mark.asyncio
    async def test_unknown_pnl_prints_as_unknown_not_as_a_number(self, capsys):
        orch = pipeline()
        await orch.on_position_closed('D1', 'BUY', 'SL_HIT', pnl=None)
        out = capsys.readouterr().out
        assert 'P&L: unknown' in out
        assert '$0.00' not in out

    @pytest.mark.asyncio
    async def test_a_genuine_broker_zero_is_preserved_as_zero(self):
        orch = pipeline()
        await orch.on_position_closed('D1', 'BUY', 'TP_HIT', pnl=0.0)
        booked = orch.skills['risk'].closed[0]
        assert booked['pnl'] == 0.0 and booked['pnl'] is not None

    @pytest.mark.asyncio
    async def test_a_real_loss_is_threaded_with_its_sign(self):
        orch = pipeline()
        await orch.on_position_closed('D1', 'SELL', 'SL_HIT', pnl=-52.70)
        assert orch.skills['risk'].closed[0]['pnl'] == -52.70
        assert orch.skills['monitoring'].events[0]['realized_pnl'] == -52.70

    @pytest.mark.asyncio
    async def test_a_real_win_is_threaded(self, capsys):
        orch = pipeline()
        await orch.on_position_closed('D1', 'BUY', 'TP_HIT', pnl=150.0)
        assert orch.skills['risk'].closed[0]['pnl'] == 150.0
        assert 'P&L: $150.00' in capsys.readouterr().out


class TestOnPositionClosedThreading:

    @pytest.mark.asyncio
    async def test_the_risk_position_flags_are_cleared(self):
        """Not clearing these leaves every later signal blocked against a ghost."""
        risk = FakeRisk(has_open_position=True, deal_id='D1', direction='BUY')
        orch = pipeline(risk=risk)
        await orch.on_position_closed('D1', 'BUY', 'SL_HIT', pnl=-15.0)
        assert risk.has_open_position is False
        assert risk.open_position_deal_id is None
        assert risk.open_position_direction is None

    @pytest.mark.asyncio
    async def test_every_field_reaches_the_risk_breakers(self):
        orch = pipeline()
        await orch.on_position_closed('D1', 'SELL', 'TP_HIT', pnl=45.0,
                                      entry_price=4100.0, close_price=4055.0, size=10.0)
        assert orch.skills['risk'].closed[0] == {
            'direction': 'SELL', 'close_reason': 'TP_HIT',
            'entry_price': 4100.0, 'close_price': 4055.0, 'pnl': 45.0,
        }

    @pytest.mark.asyncio
    async def test_storage_receives_the_size_for_the_trade_history_record(self):
        """`size` exists only for the trade_history row (gotcha 13)."""
        orch = pipeline()
        await orch.on_position_closed('D-77', 'BUY', 'SL_HIT', pnl=-15.0,
                                      entry_price=4100.0, close_price=4085.0, size=10.0)
        assert orch.skills['storage'].closed[0] == {
            'deal_id': 'D-77', 'close_price': 4085.0, 'close_reason': 'SL_HIT',
            'pnl': -15.0, 'direction': 'BUY', 'entry_price': 4100.0, 'size': 10.0,
        }

    @pytest.mark.asyncio
    async def test_monitoring_gets_the_payload_shape_it_reads(self):
        """MonitoringSkill reads deal_id / realized_pnl / close_reason."""
        orch = pipeline()
        await orch.on_position_closed('D1', 'BUY', 'TP_HIT', pnl=45.0)
        assert orch.skills['monitoring'].events[0] == {
            'deal_id': 'D1', 'realized_pnl': 45.0, 'close_reason': 'TP_HIT',
        }

    @pytest.mark.asyncio
    async def test_a_sync_monitoring_handler_is_called_without_await(self):
        orch = pipeline(monitoring=FakeMonitoring(sync_handler=True))
        await orch.on_position_closed('D1', 'BUY', 'TP_HIT', pnl=45.0)
        assert orch.skills['monitoring'].events[0]['deal_id'] == 'D1'
        assert 'monitoring.on_position_closed_sync' in orch.call_log

    @pytest.mark.asyncio
    async def test_alerting_gets_the_full_closed_trade(self):
        orch = pipeline()
        await orch.on_position_closed('D1', 'BUY', 'SL_HIT', pnl=-15.0,
                                      entry_price=4100.0, close_price=4085.0)
        assert orch.skills['alerting'].alerts[0] == {
            'direction': 'BUY', 'entry_price': 4100.0, 'close_price': 4085.0,
            'close_reason': 'SL_HIT', 'pnl': -15.0,
        }

    @pytest.mark.asyncio
    async def test_the_default_prices_and_size_are_zero(self):
        orch = pipeline()
        await orch.on_position_closed('D1', 'BUY', 'SIGNAL', pnl=-10.0)
        assert orch.skills['storage'].closed[0]['entry_price'] == 0.0
        assert orch.skills['storage'].closed[0]['size'] == 0.0

    @pytest.mark.asyncio
    async def test_the_consumers_run_in_order(self):
        orch = pipeline()
        await orch.on_position_closed('D1', 'BUY', 'SL_HIT', pnl=-15.0)
        assert orch.call_log == [
            'risk.on_position_closed',
            'storage.close_position',
            'monitoring.on_position_closed',
            'alerting.send_trade_closed_alert',
        ]


class TestOnPositionClosedOnlyClearsItsOwnDeal:
    """
    A close event can arrive for a deal that is no longer the tracked one. The
    reverse path guarantees it: it closes D-OLD and opens D-NEW 1.5s later, and
    then main.py's `_poll_positions` books that SAME close from the activity
    feed ~10s afterwards (its `processed` set is a closure local to the poll
    loop — the orchestrator's own close never registers in it, so the close is
    booked twice). The second booking used to wipe D-NEW's flags
    unconditionally, so the open-position gate saw a flat account and the next
    signal stacked a second position.
    """

    @pytest.mark.asyncio
    async def test_a_close_for_a_different_deal_keeps_the_flags(self, caplog):
        risk = FakeRisk(has_open_position=True, deal_id='D-NEW', direction='SELL')
        orch = pipeline(risk=risk)
        with caplog.at_level('WARNING'):
            await orch.on_position_closed('D-OLD', 'BUY', 'SIGNAL', pnl=-87.40)
        assert risk.has_open_position is True
        assert risk.open_position_deal_id == 'D-NEW'
        assert risk.open_position_direction == 'SELL'
        assert 'tracked position is D-NEW' in caplog.text

    @pytest.mark.asyncio
    async def test_the_stale_close_is_still_booked_with_its_real_pnl(self):
        """
        Only the position FLAGS are protected. The trade itself is real and
        must still reach the breakers, storage and the alert — this is the
        booking that carries the true P&L.
        """
        risk = FakeRisk(has_open_position=True, deal_id='D-NEW', direction='SELL')
        orch = pipeline(risk=risk)
        await orch.on_position_closed('D-OLD', 'BUY', 'SIGNAL', pnl=-87.40)
        assert risk.closed[0]['pnl'] == -87.40
        assert orch.skills['storage'].closed[0]['deal_id'] == 'D-OLD'
        assert orch.skills['alerting'].alerts[0]['pnl'] == -87.40

    @pytest.mark.asyncio
    async def test_a_close_for_the_tracked_deal_clears_the_flags(self):
        risk = FakeRisk(has_open_position=True, deal_id='D1', direction='BUY')
        orch = pipeline(risk=risk)
        await orch.on_position_closed('D1', 'BUY', 'SL_HIT', pnl=-15.0)
        assert risk.has_open_position is False
        assert risk.open_position_deal_id is None

    @pytest.mark.asyncio
    async def test_an_untracked_deal_id_still_clears(self):
        """
        `open_position_deal_id` is None when a position is open but not yet
        reconciled. Refusing to clear there would wedge the gate permanently,
        so an unknown tracked id clears.
        """
        risk = FakeRisk(has_open_position=True, deal_id=None, direction='BUY')
        orch = pipeline(risk=risk)
        await orch.on_position_closed('D-WHATEVER', 'BUY', 'SL_HIT', pnl=-15.0)
        assert risk.has_open_position is False

    @pytest.mark.asyncio
    async def test_the_full_double_booking_sequence_leaves_the_new_position_guarded(self, fast_clock):
        """
        The whole race, end to end: reverse close D-OLD -> open D-NEW -> the
        poll loop books D-OLD's close again with the real figure. D-NEW must
        still be visible to the open-position gate afterwards.
        """
        orch = pipeline(REVERSE_ON, signals=['SELL'],
                        risk=FakeRisk(has_open_position=True, deal_id='D-OLD',
                                      direction='BUY'),
                        execution=FakeExecution(deal_ids=['D-NEW']))
        await orch.on_candle(candle())
        risk = orch.skills['risk']
        assert risk.open_position_deal_id == 'D-NEW'

        # ~10s later: the activity poll books the same close, now with real P&L.
        await orch.on_position_closed('D-OLD', 'BUY', 'SIGNAL', pnl=-87.40)
        assert risk.has_open_position is True, 'D-NEW must stay guarded'
        assert risk.open_position_deal_id == 'D-NEW'
        # Both bookings happened; only the second carries a usable P&L.
        assert [c['pnl'] for c in risk.closed] == [None, -87.40]


class TestOnPositionClosedResilience:

    @pytest.mark.asyncio
    async def test_a_storage_failure_does_not_stop_the_breakers_or_the_alert(self, capsys):
        """
        Firestore/SQLite is the least important consumer here — the risk
        breakers are the ones that must see the loss.
        """
        orch = pipeline(storage=FakeStorage(close_raises=RuntimeError('firestore 503')))
        await orch.on_position_closed('D1', 'BUY', 'SL_HIT', pnl=-15.0)
        assert orch.skills['risk'].closed[0]['pnl'] == -15.0
        assert orch.skills['monitoring'].events
        assert orch.skills['alerting'].alerts
        assert 'Storage close failed: firestore 503' in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_it_runs_with_no_skills_registered(self, capsys):
        await TradingOrchestrator({}).on_position_closed('D1', 'BUY', 'SL_HIT', pnl=-15.0)
        assert 'Position closed: D1' in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_it_runs_with_only_a_risk_skill(self):
        risk = FakeRisk(has_open_position=True, deal_id='D1', direction='BUY')
        orch = build({}, risk=risk)
        await orch.on_position_closed('D1', 'BUY', 'SL_HIT', pnl=-15.0)
        assert risk.has_open_position is False and risk.closed

    @pytest.mark.asyncio
    async def test_a_monitoring_failure_propagates(self):
        """
        Only the storage call is wrapped. A monitoring raise escapes, and from
        the reverse-close path that means the new entry is skipped by the
        outer handler rather than by the abort branch. Documented, not endorsed.
        """
        orch = pipeline(monitoring=FakeMonitoring(raises=RuntimeError('metrics')))
        orch.skills['monitoring'].on_position_closed = None
        with pytest.raises(TypeError):
            await orch.on_position_closed('D1', 'BUY', 'SL_HIT', pnl=-15.0)

    @pytest.mark.asyncio
    async def test_closing_twice_is_tolerated(self):
        """The activity poll and the 60s REST reconcile can both report one close."""
        orch = pipeline()
        await orch.on_position_closed('D1', 'BUY', 'SL_HIT', pnl=-15.0)
        await orch.on_position_closed('D1', 'BUY', 'SL_HIT', pnl=-15.0)
        assert len(orch.skills['risk'].closed) == 2
        assert len(orch.skills['storage'].closed) == 2
