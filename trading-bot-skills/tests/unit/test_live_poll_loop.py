"""
Unit tests — orchestrator/main.py, the live position-tracking loop.

`_poll_positions` is the live bot's entire close-detection path and it has the
worst track record in the codebase: its previous version recorded `pnl=0.0` on
365 trades and left three risk breakers inert for roughly three months
(CLAUDE.md gotcha 22). It never runs in backtest, so nothing covered it.

These tests drive the real coroutine against a scripted fake CapitalAPIClient
and a recording fake orchestrator, asserting on the calls it makes. The loop is
infinite, so each test runs it as a cancellable task and cancels once the
expected effect has been observed.

The single most important assertion here is that an unknown P&L stays None and
is never coerced to 0.0 — `is_loss = pnl < 0` scores a 0.0 trade as a win, and
`_register_daily_pnl(0.0)` keeps the daily-loss limit pinned at zero. That
coercion is the regression.
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from orchestrator.main import (
    TIMEFRAME_TO_RESOLUTION,
    WARMUP_MULTIPLIER,
    _poll_positions,
    classify_activity,
    derive_close_reason,
    load_config,
    register_skills,
)


# ──────────────────────────────────────────────────────────────────────────
# Fakes
# ──────────────────────────────────────────────────────────────────────────

def position(deal_id='D1', epic='US100', direction='BUY', level=29526.9,
             size=1.0, stop=29476.9, limit=29676.9, upl=0.0,
             created='2026-10-21T13:00:00'):
    """A /positions row, in the broker's nested shape."""
    return {
        'market': {'epic': epic},
        'position': {
            'dealId': deal_id, 'direction': direction, 'level': level,
            'size': size, 'stopLevel': stop, 'profitLevel': limit,
            'upl': upl, 'createdDateUTC': created,
        },
    }


def open_act(deal_id='D1', epic='US100', direction='BUY', level=29526.9):
    return {'epic': epic, 'dealId': deal_id, 'source': 'USER',
            'type': 'POSITION', 'status': 'ACCEPTED',
            'details': {'size': 1.0, 'direction': direction, 'level': level,
                        'stopLevel': 29476.9, 'profitLevel': 29676.9}}


def close_act(deal_id='D1', epic='US100', source='SL', level=29476.9,
              open_price=29526.9, direction='SELL'):
    """`openPrice` present marks a close; `direction` is the CLOSING side."""
    return {'epic': epic, 'dealId': deal_id, 'source': source,
            'type': 'POSITION', 'status': 'ACCEPTED',
            'details': {'size': 1.0, 'direction': direction, 'level': level,
                        'stopLevel': 29476.9, 'profitLevel': 29676.9,
                        'openPrice': open_price}}


class FakeCapital:
    """
    Scripted CapitalAPIClient. `activity_script` / `positions_script` are
    consumed one entry per call; the last entry repeats once exhausted so the
    loop can keep polling.
    """

    def __init__(self, activity_script=None, positions_script=None,
                 realised_pnl=None, raises_on_activity=0):
        self.activity_script = list(activity_script or [[]])
        self.positions_script = list(positions_script or [[]])
        self.realised_pnl = realised_pnl
        self.activity_calls = 0
        self.positions_calls = 0
        self.pnl_calls = []
        self.raises_on_activity = raises_on_activity
        self.activity_kwargs = []

    @staticmethod
    def _at(script, counter):
        return script[min(counter, len(script) - 1)]

    def get_activity(self, last_period_seconds=None, epic=None, **kw):
        self.activity_kwargs.append({'last_period_seconds': last_period_seconds,
                                     'epic': epic})
        n = self.activity_calls
        self.activity_calls += 1
        if n < self.raises_on_activity:
            raise RuntimeError('activity 503')
        return self._at(self.activity_script, n)

    def get_open_positions(self):
        n = self.positions_calls
        self.positions_calls += 1
        return self._at(self.positions_script, n)

    def get_realised_pnl(self, deal_id, **kw):
        self.pnl_calls.append(deal_id)
        return self.realised_pnl


class FakeStorage:
    def __init__(self):
        self.saved = []

    async def save_open_position(self, **kw):
        self.saved.append(kw)


class FakeRisk:
    def __init__(self):
        self.has_open_position = False
        self.open_position_deal_id = None
        self.open_position_direction = None


class FakeOrchestrator:
    def __init__(self, with_storage=True, with_risk=True):
        self.skills = {}
        if with_storage:
            self.skills['storage'] = FakeStorage()
        if with_risk:
            self.skills['risk'] = FakeRisk()
        self.closes = []

    async def on_position_closed(self, **kw):
        self.closes.append(kw)


class FakeStopManager:
    def __init__(self):
        self.forgotten = []
        self.synced = []

    def forget(self, deal_id):
        self.forgotten.append(deal_id)

    def sync_positions(self, known):
        self.synced.append(dict(known))


async def run_poll(capital, orch, epic='US100', interval=0.01,
                   stop_manager=None, until=None, max_wait=2.0):
    """
    Run `_poll_positions` as a task until `until()` is true (or `max_wait`
    elapses), then cancel it and re-raise the cancellation.
    """
    task = asyncio.create_task(
        _poll_positions(capital, orch, epic, interval=interval,
                        stop_manager=stop_manager))
    loop = asyncio.get_event_loop()
    deadline = loop.time() + max_wait
    try:
        while loop.time() < deadline:
            await asyncio.sleep(min(interval, 0.05))
            if until is None or until():
                break
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.fixture
def fast_clock(monkeypatch):
    """
    Replace asyncio.sleep with an immediate yield so the loop's 10s poll and
    60s reconcile cadence run instantly.

    `reconcile_every = max(1, 60 // interval)` still depends on the interval
    VALUE, so a test picks the interval for the cadence it wants (interval=61
    gives 60//61 == 0 -> reconcile on every cycle) and this fixture removes the
    wall-clock cost. Returns the real sleep so the waiter can still yield.
    """
    real = asyncio.sleep

    async def instant(_delay=0):
        await real(0)

    monkeypatch.setattr(asyncio, 'sleep', instant)
    return real


async def run_poll_fast(real_sleep, capital, orch, epic='US100', interval=61,
                        stop_manager=None, until=None, max_iters=4000):
    """run_poll, but driven by yield count instead of wall clock."""
    task = asyncio.create_task(
        _poll_positions(capital, orch, epic, interval=interval,
                        stop_manager=stop_manager))
    try:
        for _ in range(max_iters):
            await real_sleep(0)
            if until is None or until():
                break
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


# ──────────────────────────────────────────────────────────────────────────
# Startup seeding
# ──────────────────────────────────────────────────────────────────────────

class TestStartupSeeding:

    @pytest.mark.asyncio
    async def test_existing_positions_are_seeded_and_persisted(self):
        cap = FakeCapital(positions_script=[[position('D1'), position('D2')]])
        orch = FakeOrchestrator()
        await run_poll(cap, orch, until=lambda: cap.activity_calls >= 1)
        assert {s['deal_id'] for s in orch.skills['storage'].saved} == {'D1', 'D2'}

    @pytest.mark.asyncio
    async def test_seeded_positions_do_not_refire_as_opens(self):
        """The seed marks each deal `:POSITION_OPENED` processed."""
        cap = FakeCapital(positions_script=[[position('D1')]],
                          activity_script=[[open_act('D1')]])
        orch = FakeOrchestrator()
        await run_poll(cap, orch, until=lambda: cap.activity_calls >= 3)
        assert len(orch.skills['storage'].saved) == 1

    @pytest.mark.asyncio
    async def test_broker_open_timestamp_is_passed_through(self):
        """
        Without it save_open_position falls back to now() on every reconcile and
        every recorded hold time collapses to seconds.
        """
        cap = FakeCapital(
            positions_script=[[position('D1', created='2026-10-21T09:15:00')]])
        orch = FakeOrchestrator()
        await run_poll(cap, orch, until=lambda: cap.activity_calls >= 1)
        assert orch.skills['storage'].saved[0]['opened_at'] == '2026-10-21T09:15:00'

    @pytest.mark.asyncio
    async def test_other_epics_are_ignored(self):
        cap = FakeCapital(positions_script=[[position('D1', epic='GOLD'),
                                             position('D2', epic='US100')]])
        orch = FakeOrchestrator()
        await run_poll(cap, orch, epic='US100',
                       until=lambda: cap.activity_calls >= 1)
        assert [s['deal_id'] for s in orch.skills['storage'].saved] == ['D2']

    @pytest.mark.asyncio
    async def test_epic_match_is_case_insensitive(self):
        cap = FakeCapital(positions_script=[[position('D1', epic='us100')]])
        orch = FakeOrchestrator()
        await run_poll(cap, orch, epic='US100',
                       until=lambda: cap.activity_calls >= 1)
        assert len(orch.skills['storage'].saved) == 1

    @pytest.mark.asyncio
    async def test_positions_without_deal_id_are_skipped(self):
        bad = position('D1')
        bad['position']['dealId'] = None
        cap = FakeCapital(positions_script=[[bad]])
        orch = FakeOrchestrator()
        await run_poll(cap, orch, until=lambda: cap.activity_calls >= 1)
        assert orch.skills['storage'].saved == []

    @pytest.mark.asyncio
    async def test_a_failing_initial_fetch_does_not_abort_the_loop(self):
        class Boom(FakeCapital):
            def get_open_positions(self):
                self.positions_calls += 1
                raise RuntimeError('500 on /positions')

        cap = Boom(activity_script=[[]])
        orch = FakeOrchestrator()
        await run_poll(cap, orch, until=lambda: cap.activity_calls >= 2)
        assert cap.activity_calls >= 2, "loop must still be polling"

    @pytest.mark.asyncio
    async def test_missing_storage_skill_is_tolerated(self):
        cap = FakeCapital(positions_script=[[position('D1')]])
        orch = FakeOrchestrator(with_storage=False)
        await run_poll(cap, orch, until=lambda: cap.activity_calls >= 1)
        assert cap.activity_calls >= 1

    @pytest.mark.asyncio
    async def test_a_storage_failure_is_swallowed(self):
        class BadStorage:
            async def save_open_position(self, **kw):
                raise RuntimeError('db locked')

        cap = FakeCapital(positions_script=[[position('D1')]])
        orch = FakeOrchestrator()
        orch.skills['storage'] = BadStorage()
        await run_poll(cap, orch, until=lambda: cap.activity_calls >= 2)
        assert cap.activity_calls >= 2

    @pytest.mark.asyncio
    async def test_stop_manager_is_seeded_with_known_positions(self):
        cap = FakeCapital(positions_script=[[position('D1')]])
        orch = FakeOrchestrator()
        sm = FakeStopManager()
        await run_poll(cap, orch, stop_manager=sm,
                       until=lambda: cap.activity_calls >= 1)
        assert sm.synced and 'D1' in sm.synced[0]


# ──────────────────────────────────────────────────────────────────────────
# Activity poll — opens
# ──────────────────────────────────────────────────────────────────────────

class TestActivityPollOpens:

    @pytest.mark.asyncio
    async def test_a_new_open_is_tracked_and_persisted(self):
        cap = FakeCapital(activity_script=[[open_act('D9', direction='SELL')]])
        orch = FakeOrchestrator()
        await run_poll(cap, orch, until=lambda: bool(orch.skills['storage'].saved))
        saved = orch.skills['storage'].saved[0]
        assert saved['deal_id'] == 'D9'
        assert saved['direction'] == 'SELL'

    @pytest.mark.asyncio
    async def test_an_open_is_not_announced_twice(self):
        """The `processed` set guards the overlapping lookback window."""
        cap = FakeCapital(activity_script=[[open_act('D9')]])   # repeats forever
        orch = FakeOrchestrator()
        await run_poll(cap, orch, until=lambda: cap.activity_calls >= 4)
        assert len(orch.skills['storage'].saved) == 1

    @pytest.mark.asyncio
    async def test_activity_for_another_epic_is_ignored(self):
        cap = FakeCapital(activity_script=[[open_act('D9', epic='GOLD')]])
        orch = FakeOrchestrator()
        await run_poll(cap, orch, epic='US100',
                       until=lambda: cap.activity_calls >= 3)
        assert orch.skills['storage'].saved == []

    @pytest.mark.asyncio
    async def test_unparseable_activity_is_skipped(self):
        """classify_activity returns None without a dealId."""
        bad = open_act('D9')
        bad['dealId'] = ''
        cap = FakeCapital(activity_script=[[bad]])
        orch = FakeOrchestrator()
        await run_poll(cap, orch, until=lambda: cap.activity_calls >= 3)
        assert orch.skills['storage'].saved == []

    @pytest.mark.asyncio
    async def test_the_lookback_is_three_times_the_interval(self):
        cap = FakeCapital()
        orch = FakeOrchestrator()
        await run_poll(cap, orch, interval=1, until=lambda: cap.activity_calls >= 1,
                       max_wait=4.0)
        assert cap.activity_kwargs[0]['last_period_seconds'] == 3
        assert cap.activity_kwargs[0]['epic'] == 'US100'


# ──────────────────────────────────────────────────────────────────────────
# Activity poll — closes
# ──────────────────────────────────────────────────────────────────────────

class TestActivityPollCloses:

    @pytest.mark.asyncio
    async def test_a_close_fires_on_position_closed_with_the_right_reason(self):
        cap = FakeCapital(positions_script=[[position('D1')]],
                          activity_script=[[close_act('D1', source='SL')]],
                          realised_pnl=-45.0)
        orch = FakeOrchestrator()
        await run_poll(cap, orch, until=lambda: bool(orch.closes))
        c = orch.closes[0]
        assert c['deal_id'] == 'D1'
        assert c['close_reason'] == 'SL_HIT'
        assert c['pnl'] == -45.0

    @pytest.mark.asyncio
    async def test_a_tp_close_is_labelled_tp_hit(self):
        cap = FakeCapital(positions_script=[[position('D1')]],
                          activity_script=[[close_act('D1', source='TP')]],
                          realised_pnl=150.0)
        orch = FakeOrchestrator()
        await run_poll(cap, orch, until=lambda: bool(orch.closes))
        assert orch.closes[0]['close_reason'] == 'TP_HIT'

    @pytest.mark.asyncio
    async def test_a_user_close_is_labelled_signal(self):
        cap = FakeCapital(positions_script=[[position('D1')]],
                          activity_script=[[close_act('D1', source='USER')]],
                          realised_pnl=3.0)
        orch = FakeOrchestrator()
        await run_poll(cap, orch, until=lambda: bool(orch.closes))
        assert orch.closes[0]['close_reason'] == 'SIGNAL'

    @pytest.mark.asyncio
    async def test_the_position_direction_not_the_closing_side_is_recorded(self):
        """
        A BUY position closes with `details.direction: SELL`. The recorded
        direction must be the position's own side, taken from `known`.
        """
        cap = FakeCapital(positions_script=[[position('D1', direction='BUY')]],
                          activity_script=[[close_act('D1', direction='SELL')]],
                          realised_pnl=-10.0)
        orch = FakeOrchestrator()
        await run_poll(cap, orch, until=lambda: bool(orch.closes))
        assert orch.closes[0]['direction'] == 'BUY'

    @pytest.mark.asyncio
    async def test_entry_price_and_size_come_from_the_tracked_position(self):
        cap = FakeCapital(
            positions_script=[[position('D1', level=29526.9, size=2.0)]],
            activity_script=[[close_act('D1', level=29476.9)]],
            realised_pnl=-100.0)
        orch = FakeOrchestrator()
        await run_poll(cap, orch, until=lambda: bool(orch.closes))
        c = orch.closes[0]
        assert c['entry_price'] == 29526.9
        assert c['close_price'] == 29476.9
        assert c['size'] == 2.0

    @pytest.mark.asyncio
    async def test_realised_pnl_is_queried_once_per_close(self):
        cap = FakeCapital(positions_script=[[position('D1')]],
                          activity_script=[[close_act('D1')]],
                          realised_pnl=-45.0)
        orch = FakeOrchestrator()
        await run_poll(cap, orch, until=lambda: cap.activity_calls >= 4)
        assert cap.pnl_calls == ['D1'], "the processed set must stop a re-query"

    @pytest.mark.asyncio
    async def test_a_close_is_not_double_fired(self):
        cap = FakeCapital(positions_script=[[position('D1')]],
                          activity_script=[[close_act('D1')]],
                          realised_pnl=-45.0)
        orch = FakeOrchestrator()
        await run_poll(cap, orch, until=lambda: cap.activity_calls >= 4)
        assert len(orch.closes) == 1

    @pytest.mark.asyncio
    async def test_stop_manager_forgets_a_closed_deal(self):
        cap = FakeCapital(positions_script=[[position('D1')]],
                          activity_script=[[close_act('D1')]],
                          realised_pnl=-45.0)
        orch = FakeOrchestrator()
        sm = FakeStopManager()
        await run_poll(cap, orch, stop_manager=sm, until=lambda: bool(orch.closes))
        assert sm.forgotten == ['D1']

    @pytest.mark.asyncio
    async def test_an_open_then_a_close_in_sequence(self):
        cap = FakeCapital(
            activity_script=[[open_act('D5')], [close_act('D5', source='TP')]],
            realised_pnl=150.0)
        orch = FakeOrchestrator()
        await run_poll(cap, orch, until=lambda: bool(orch.closes))
        assert [s['deal_id'] for s in orch.skills['storage'].saved] == ['D5']
        assert orch.closes[0]['close_reason'] == 'TP_HIT'
        assert orch.closes[0]['entry_price'] == 29526.9


# ──────────────────────────────────────────────────────────────────────────
# Unknown P&L — THE regression
# ──────────────────────────────────────────────────────────────────────────

class TestUnknownPnlIsNeverZero:
    """
    CLAUDE.md gotcha 22. `pnl=None` means "the broker told us nothing" and must
    stay None all the way to on_position_closed. Coercing it to 0.0 makes
    `is_loss = pnl < 0` score the trade a win (so the consecutive-loss breaker
    can never trip) and leaves `_register_daily_pnl` permanently at zero (so the
    daily-loss limit can never trip).
    """

    @pytest.mark.asyncio
    async def test_no_realised_pnl_and_no_prices_records_none(self, fast_clock):
        """
        The REST-reconcile shape, which is how EVERY close was detected while
        get_activity was broken: _handle_close(deal_id, 0.0, '') — no close
        level, no size, no broker figure. There is nothing to estimate from, so
        the P&L must be recorded as unknown.
        """
        cap = FakeCapital(positions_script=[[position('D1')], []],
                          activity_script=[[]], realised_pnl=None)
        orch = FakeOrchestrator()
        await run_poll_fast(fast_clock, cap, orch, until=lambda: bool(orch.closes))
        assert orch.closes, "the reconcile must detect the missed close"
        assert orch.closes[0]['pnl'] is None, "unknown P&L must not become 0.0"

    @pytest.mark.asyncio
    async def test_a_genuine_broker_zero_is_preserved(self):
        """A real break-even trade is 0.0 and must not be replaced by an estimate."""
        cap = FakeCapital(positions_script=[[position('D1')]],
                          activity_script=[[close_act('D1', source='USER')]],
                          realised_pnl=0.0)
        orch = FakeOrchestrator()
        await run_poll(cap, orch, until=lambda: bool(orch.closes))
        assert orch.closes[0]['pnl'] == 0.0

    @pytest.mark.asyncio
    async def test_pnl_is_estimated_from_prices_only_when_unknown(self):
        """entry 29526.9, close 29476.9, BUY, size 1 -> -50.0."""
        cap = FakeCapital(
            positions_script=[[position('D1', direction='BUY', size=1.0)]],
            activity_script=[[close_act('D1', level=29476.9)]],
            realised_pnl=None)
        orch = FakeOrchestrator()
        await run_poll(cap, orch, until=lambda: bool(orch.closes))
        assert orch.closes[0]['pnl'] == pytest.approx(-50.0)

    @pytest.mark.asyncio
    async def test_a_sell_estimate_has_the_opposite_sign(self):
        cap = FakeCapital(
            positions_script=[[position('D1', direction='SELL', size=1.0)]],
            activity_script=[[close_act('D1', level=29476.9)]],
            realised_pnl=None)
        orch = FakeOrchestrator()
        await run_poll(cap, orch, until=lambda: bool(orch.closes))
        assert orch.closes[0]['pnl'] == pytest.approx(50.0)

    @pytest.mark.asyncio
    async def test_the_broker_figure_wins_over_the_price_estimate(self):
        """
        The transactions figure is net of spread and fees, so it is
        authoritative even where an arithmetic estimate is possible.
        """
        cap = FakeCapital(
            positions_script=[[position('D1', direction='BUY', size=1.0)]],
            activity_script=[[close_act('D1', level=29476.9)]],
            realised_pnl=-52.0)
        orch = FakeOrchestrator()
        await run_poll(cap, orch, until=lambda: bool(orch.closes))
        assert orch.closes[0]['pnl'] == -52.0

    @pytest.mark.asyncio
    async def test_a_failing_pnl_lookup_does_not_kill_the_loop(self):
        class NoPnl(FakeCapital):
            def get_realised_pnl(self, deal_id, **kw):
                self.pnl_calls.append(deal_id)
                raise RuntimeError('transactions 400')

        cap = NoPnl(positions_script=[[position('D1')]],
                    activity_script=[[close_act('D1')]])
        orch = FakeOrchestrator()
        await run_poll(cap, orch, until=lambda: cap.activity_calls >= 4)
        assert cap.activity_calls >= 4


# ──────────────────────────────────────────────────────────────────────────
# 60s REST reconcile
# ──────────────────────────────────────────────────────────────────────────

class TestRestReconcile:

    @pytest.mark.asyncio
    async def test_a_close_the_activity_poll_missed_is_detected(self, fast_clock):
        cap = FakeCapital(positions_script=[[position('D1')], []],
                          activity_script=[[]], realised_pnl=None)
        orch = FakeOrchestrator()
        await run_poll_fast(fast_clock, cap, orch, until=lambda: bool(orch.closes))
        assert orch.closes[0]['deal_id'] == 'D1'
        assert orch.closes[0]['close_reason'] == 'SIGNAL'

    @pytest.mark.asyncio
    async def test_the_reconcile_close_is_not_refired(self, fast_clock):
        cap = FakeCapital(positions_script=[[position('D1')], []],
                          activity_script=[[]])
        orch = FakeOrchestrator()
        await run_poll_fast(fast_clock, cap, orch,
                            until=lambda: cap.positions_calls >= 5)
        assert len(orch.closes) == 1

    @pytest.mark.asyncio
    async def test_an_untracked_broker_position_is_adopted(self, fast_clock):
        cap = FakeCapital(positions_script=[[], [position('D7', direction='SELL')]],
                          activity_script=[[]])
        orch = FakeOrchestrator()
        await run_poll_fast(fast_clock, cap, orch,
                            until=lambda: bool(orch.skills['storage'].saved))
        assert orch.skills['storage'].saved[0]['deal_id'] == 'D7'

    @pytest.mark.asyncio
    async def test_adopting_a_position_syncs_the_risk_gate(self, fast_clock):
        """Otherwise the bot would stack a second position on top of it."""
        cap = FakeCapital(positions_script=[[], [position('D7', direction='SELL')]],
                          activity_script=[[]])
        orch = FakeOrchestrator()
        risk = orch.skills['risk']
        await run_poll_fast(fast_clock, cap, orch,
                            until=lambda: risk.has_open_position)
        assert risk.has_open_position is True
        assert risk.open_position_deal_id == 'D7'
        assert risk.open_position_direction == 'SELL'

    @pytest.mark.asyncio
    async def test_unrealised_pnl_is_refreshed_for_a_known_position(self, fast_clock):
        cap = FakeCapital(
            positions_script=[[position('D1', upl=0.0)],
                              [position('D1', upl=-12.5)]],
            activity_script=[[]])
        orch = FakeOrchestrator()
        await run_poll_fast(fast_clock, cap, orch,
                            until=lambda: len(orch.skills['storage'].saved) >= 2)
        assert orch.skills['storage'].saved[-1]['upl'] == -12.5

    @pytest.mark.asyncio
    async def test_a_reconcile_failure_does_not_kill_the_loop(self, fast_clock):
        class Flaky(FakeCapital):
            def get_open_positions(self):
                n = self.positions_calls
                self.positions_calls += 1
                if n > 0:
                    raise RuntimeError('500 on /positions')
                return []

        cap = Flaky(activity_script=[[]])
        orch = FakeOrchestrator()
        await run_poll_fast(fast_clock, cap, orch,
                            until=lambda: cap.positions_calls >= 3)
        assert cap.positions_calls >= 3

    @pytest.mark.asyncio
    async def test_reconcile_runs_every_third_cycle_at_the_live_interval(self, fast_clock):
        """
        reconcile_every = max(1, 60 // interval). The live bot runs interval=10,
        so a reconcile lands every 6th poll — roughly 60s, as documented.
        At interval=20 it is every 3rd.
        """
        cap = FakeCapital(activity_script=[[]])
        orch = FakeOrchestrator()
        await run_poll_fast(fast_clock, cap, orch, interval=20,
                            until=lambda: cap.activity_calls >= 3)
        # 1 startup fetch + 1 reconcile on the 3rd cycle
        assert cap.positions_calls == 2


# ──────────────────────────────────────────────────────────────────────────
# Loop resilience
# ──────────────────────────────────────────────────────────────────────────

class TestLoopResilience:

    @pytest.mark.asyncio
    async def test_a_transient_activity_error_does_not_kill_the_loop(self):
        cap = FakeCapital(activity_script=[[], [open_act('D3')]],
                          raises_on_activity=2)
        orch = FakeOrchestrator()
        await run_poll(cap, orch, until=lambda: bool(orch.skills['storage'].saved))
        assert cap.activity_calls > 2
        assert orch.skills['storage'].saved[0]['deal_id'] == 'D3'

    @pytest.mark.asyncio
    async def test_cancellation_propagates(self):
        """The task must end as CancelledError, not swallow it."""
        cap = FakeCapital()
        orch = FakeOrchestrator()
        task = asyncio.create_task(_poll_positions(cap, orch, 'US100', interval=0.01))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_stop_manager_is_resynced_every_cycle(self):
        cap = FakeCapital(positions_script=[[position('D1')]])
        orch = FakeOrchestrator()
        sm = FakeStopManager()
        await run_poll(cap, orch, stop_manager=sm, until=lambda: len(sm.synced) >= 3)
        assert len(sm.synced) >= 3

    @pytest.mark.asyncio
    async def test_no_stop_manager_is_fine(self):
        cap = FakeCapital(positions_script=[[position('D1')]],
                          activity_script=[[close_act('D1')]],
                          realised_pnl=-45.0)
        orch = FakeOrchestrator()
        await run_poll(cap, orch, stop_manager=None, until=lambda: bool(orch.closes))
        assert len(orch.closes) == 1

    @pytest.mark.asyncio
    async def test_missing_risk_skill_is_tolerated(self, fast_clock):
        cap = FakeCapital(positions_script=[[], [position('D7')]],
                          activity_script=[[]])
        orch = FakeOrchestrator(with_risk=False)
        await run_poll_fast(fast_clock, cap, orch,
                            until=lambda: bool(orch.skills['storage'].saved))
        assert orch.skills['storage'].saved[0]['deal_id'] == 'D7'


# ──────────────────────────────────────────────────────────────────────────
# Module-level helpers
# ──────────────────────────────────────────────────────────────────────────

class TestLoadConfig:

    def test_env_placeholders_are_expanded(self, tmp_path, monkeypatch):
        monkeypatch.setenv('TEST_EPIC_NAME', 'US100')
        p = tmp_path / 'c.yaml'
        p.write_text('execution:\n  epic: ${TEST_EPIC_NAME}\n')
        assert load_config(str(p))['execution']['epic'] == 'US100'

    def test_an_unset_placeholder_is_left_verbatim(self, tmp_path, monkeypatch):
        monkeypatch.delenv('TEST_MISSING_VAR', raising=False)
        p = tmp_path / 'c.yaml'
        p.write_text('a: ${TEST_MISSING_VAR}\n')
        assert load_config(str(p))['a'] == '${TEST_MISSING_VAR}'

    def test_an_empty_env_var_is_treated_as_unset(self, tmp_path, monkeypatch):
        monkeypatch.setenv('TEST_EMPTY_VAR', '')
        p = tmp_path / 'c.yaml'
        p.write_text('a: ${TEST_EMPTY_VAR}\n')
        assert load_config(str(p))['a'] == '${TEST_EMPTY_VAR}'

    def test_several_placeholders_on_one_line(self, tmp_path, monkeypatch):
        monkeypatch.setenv('TEST_A', 'x')
        monkeypatch.setenv('TEST_B', 'y')
        p = tmp_path / 'c.yaml'
        p.write_text('a: ${TEST_A}-${TEST_B}\n')
        assert load_config(str(p))['a'] == 'x-y'

    def test_nested_structure_survives(self, tmp_path):
        p = tmp_path / 'c.yaml'
        p.write_text('risk:\n  sl_pips: 15\n  skip_hours: [0, 1]\n')
        cfg = load_config(str(p))
        assert cfg['risk']['sl_pips'] == 15
        assert cfg['risk']['skip_hours'] == [0, 1]


class TestRegisterSkills:

    class Orch:
        def __init__(self):
            self.skills = {}

        def register_skill(self, name, skill):
            self.skills[name] = skill

    def _base(self, **over):
        cfg = {
            'market_data': {'enabled': False},
            'analysis': {'enabled': False},
            'risk': {'enabled': False},
            'execution': {'enabled': False},
            'storage': {'enabled': False},
            'monitoring': {'enabled': False},
            'alerting': {'enabled': False},
            'reporting': {'enabled': False},
            'backtesting': {'enabled': False},
        }
        cfg.update(over)
        return cfg

    def test_bot_id_is_injected_into_monitoring_and_storage(self):
        cfg = self._base()
        register_skills(self.Orch(), cfg, mode='live', bot_id='gold_m5_bot')
        assert cfg['monitoring']['bot_id'] == 'gold_m5_bot'
        assert cfg['storage']['bot_id'] == 'gold_m5_bot'

    def test_epic_is_copied_into_storage_config(self):
        cfg = self._base(execution={'enabled': False, 'epic': 'US100'})
        register_skills(self.Orch(), cfg, mode='live')
        assert cfg['storage']['epic'] == 'US100'

    def test_epic_falls_back_to_market_data(self):
        cfg = self._base(market_data={'enabled': False, 'epic': 'GOLD'})
        register_skills(self.Orch(), cfg, mode='live')
        assert cfg['storage']['epic'] == 'GOLD'

    def test_risk_pips_propagate_into_analysis_sl_tp(self):
        """
        CLAUDE.md gotcha 1: `risk` is the single source of truth and
        analysis.sl_tp is overwritten at load time.
        """
        cfg = self._base(
            risk={'enabled': False, 'pip_size': 1.0,
                  'stop_loss_pips': 15, 'take_profit_pips': 45},
            analysis={'enabled': False,
                      'sl_tp': {'stop_loss_pips': 999, 'method': 'fixed'}})
        register_skills(self.Orch(), cfg, mode='live')
        sl_tp = cfg['analysis']['sl_tp']
        assert sl_tp['stop_loss_pips'] == 15
        assert sl_tp['take_profit_pips'] == 45
        assert sl_tp['pip_size'] == 1.0
        assert sl_tp['method'] == 'fixed'      # untouched keys survive

    def test_root_position_size_propagates_to_risk_and_execution(self):
        """
        CLAUDE.md gotcha 26: without this, execution_skill's own 0.5 default
        wins and the bot trades a fraction of the intended size.
        """
        cfg = self._base(position_size=10)
        register_skills(self.Orch(), cfg, mode='live')
        assert cfg['risk']['position_size'] == 10
        assert cfg['execution']['position_size'] == 10

    def test_an_explicit_section_size_is_not_overridden_by_the_root(self):
        cfg = self._base(position_size=10,
                         execution={'enabled': False, 'position_size': 1})
        register_skills(self.Orch(), cfg, mode='live')
        assert cfg['execution']['position_size'] == 1

    def test_no_root_position_size_leaves_sections_alone(self):
        cfg = self._base()
        register_skills(self.Orch(), cfg, mode='live')
        assert 'position_size' not in cfg.get('execution', {})

    def test_everything_disabled_registers_nothing(self):
        orch = self.Orch()
        register_skills(orch, self._base(), mode='live')
        assert orch.skills == {}

    def test_backtesting_is_only_registered_in_backtest_mode(self):
        orch = self.Orch()
        register_skills(orch, self._base(backtesting={'enabled': True}), mode='live')
        assert 'backtesting' not in orch.skills


class TestModuleConstants:

    def test_warmup_multiplier_is_three(self):
        """buffer_size is max_indicator_period x this (CLAUDE.md gotcha 2)."""
        assert WARMUP_MULTIPLIER == 3

    @pytest.mark.parametrize('tf,res', [
        ('M1', 'MINUTE'), ('M5', 'MINUTE_5'), ('M15', 'MINUTE_15'),
        ('M30', 'MINUTE_30'), ('H1', 'HOUR'), ('H4', 'HOUR_4'), ('D1', 'DAY'),
    ])
    def test_timeframe_maps_to_capital_resolution(self, tf, res):
        assert TIMEFRAME_TO_RESOLUTION[tf] == res


class TestHelpersStillExported:
    """Both are covered in depth in test_live_close_and_risk.py."""

    def test_classify_activity_is_importable_and_works(self):
        assert classify_activity(close_act('D1'))['is_close'] is True

    def test_derive_close_reason_is_importable_and_works(self):
        assert derive_close_reason(source='SL') == 'SL_HIT'
