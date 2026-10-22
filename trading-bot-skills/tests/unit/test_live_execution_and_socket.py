"""
Unit tests — ExecutionSkill and CapitalWebSocketClient.

Both sit entirely on the live path. The backtester simulates fills in
BacktestingSkill and never touches either, so between them they held ~157 + 119
statements at 45% / 41% coverage.

Two things here are load-bearing beyond mere coverage:

  * `ExecutionSkill.position_size` defaults to **0.5** (execution_skill.py:51).
    GOLD and ETHUSD define `position_size` only under `backtesting:`, so that
    default won and GOLD traded 0.5 contracts against an intended 10 — risk per
    trade $7.50 instead of $150 (CLAUDE.md gotcha 26). The resolution order is
    pinned below so the fix is verifiable and the default cannot drift.

  * A Capital.com order can be "placed" and still fail: the broker answers
    `status: DELETED`/`REJECTED`, or hands back a zero-prefixed dealId. Treating
    either as a fill leaves the bot believing it holds a position it does not.
"""
import asyncio
import json
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from clients.capital_websocket import WS_URL, CapitalWebSocketClient
from core.event_bus import Event, EventBus, EventType
from skills.base_skill import Context, SkillExecutionError
from skills.execution.execution_skill import ExecutionSkill


# ──────────────────────────────────────────────────────────────────────────
# Fake REST client
# ──────────────────────────────────────────────────────────────────────────

class FakeRest:
    """
    Stands in for CapitalAPIClient. `confirm` is the confirmation body the
    broker returns; `place_raises` / `confirm_raises` inject failures.
    """

    def __init__(self, confirm=None, place_raises=None, confirm_raises=None,
                 close_raises=None, positions=None):
        self.confirm_body = confirm if confirm is not None else {
            'status': 'OPEN', 'dealId': 'REAL-DEAL-1', 'level': 29530.5}
        self.place_raises = place_raises
        self.confirm_raises = confirm_raises
        self.close_raises = close_raises
        self.positions = positions if positions is not None else []
        self.orders = []
        self.confirms = []
        self.closes = []
        self.positions_calls = 0

    def place_order(self, **kw):
        self.orders.append(kw)
        if self.place_raises:
            raise self.place_raises
        return {'dealReference': 'REF-1'}

    def confirm_order(self, deal_reference):
        self.confirms.append(deal_reference)
        if self.confirm_raises:
            raise self.confirm_raises
        return self.confirm_body

    def close_position(self, deal_id=None):
        self.closes.append(deal_id)
        if self.close_raises:
            raise self.close_raises
        return {'status': 'CLOSED'}

    def get_open_positions(self):
        self.positions_calls += 1
        return self.positions


def live_skill(rest=None, bus=None, **cfg):
    """An ExecutionSkill wired to a fake broker (mock_mode off)."""
    base = {'epic': 'US100', 'sl_pips': 50, 'tp_pips': 150,
            'position_size': 1.0, 'mock_mode': False}
    base.update(cfg)
    skill = ExecutionSkill(base, event_bus=bus)
    skill.rest_client = rest if rest is not None else FakeRest()
    return skill


def approved_event(signal='BUY', size=1.0, entry=29500.0,
                   sl=29450.0, tp=29650.0, instrument='US100'):
    return Event(
        event_type=EventType.RISK_APPROVED, instrument=instrument,
        source='risk',
        payload={'signal': signal, 'position_size': size, 'entry_price': entry,
                 'stop_loss': sl, 'take_profit': tp})


class Orders:
    def __init__(self, bus):
        self.filled, self.rejected = [], []
        bus.subscribe(EventType.ORDER_FILLED, self._fill)
        bus.subscribe(EventType.ORDER_REJECTED, self._reject)

    async def _fill(self, e):
        self.filled.append(e.payload)

    async def _reject(self, e):
        self.rejected.append(e.payload)


# ──────────────────────────────────────────────────────────────────────────
# Size resolution — CLAUDE.md gotcha 26
# ──────────────────────────────────────────────────────────────────────────

class TestPositionSizeResolution:
    """
    The 0.5 default is the whole bug. These pin where size comes from and in
    what order, so the fix (propagating a root-level `position_size` into the
    execution section) is checkable and the default cannot silently change.
    """

    def test_the_default_is_still_point_five(self):
        """
        Not an endorsement — a tripwire. If this ever changes, every instrument
        that relies on the propagation silently changes risk per trade.
        """
        assert ExecutionSkill({}).position_size == 0.5

    def test_an_explicit_execution_size_is_used(self):
        assert ExecutionSkill({'position_size': 10}).position_size == 10

    def test_a_size_under_backtesting_does_not_reach_execution(self):
        """
        Exactly the GOLD shape: `backtesting.position_size: 10` with nothing
        under execution, so the 0.5 default wins and live trades 1/20th size.
        """
        skill = ExecutionSkill({'backtesting': {'position_size': 10}})
        assert skill.position_size == 0.5

    @pytest.mark.asyncio
    async def test_the_context_size_overrides_the_configured_one(self):
        rest = FakeRest()
        skill = live_skill(rest, position_size=0.5)
        ctx = Context(signal='BUY', is_allowed=True, entry_price=29500.0,
                      position_size=7.0, stop_loss=29450.0, take_profit=29650.0)
        await skill.execute(ctx)
        assert rest.orders[0]['size'] == 7.0

    @pytest.mark.asyncio
    async def test_the_configured_size_is_the_fallback(self):
        rest = FakeRest()
        skill = live_skill(rest, position_size=3.0)
        ctx = Context(signal='BUY', is_allowed=True, entry_price=29500.0,
                      position_size=None, stop_loss=29450.0, take_profit=29650.0)
        await skill.execute(ctx)
        assert rest.orders[0]['size'] == 3.0

    @pytest.mark.asyncio
    async def test_a_zero_context_size_falls_back_rather_than_ordering_zero(self):
        rest = FakeRest()
        skill = live_skill(rest, position_size=2.0)
        ctx = Context(signal='BUY', is_allowed=True, entry_price=29500.0,
                      position_size=0, stop_loss=29450.0, take_profit=29650.0)
        await skill.execute(ctx)
        assert rest.orders[0]['size'] == 2.0


# ──────────────────────────────────────────────────────────────────────────
# Order placement
# ──────────────────────────────────────────────────────────────────────────

class TestOrderPlacement:

    @pytest.mark.asyncio
    async def test_a_market_order_carries_epic_direction_size_and_levels(self):
        rest = FakeRest()
        skill = live_skill(rest)
        ctx = Context(signal='SELL', is_allowed=True, entry_price=29500.0,
                      position_size=1.0, stop_loss=29550.0, take_profit=29350.0)
        await skill.execute(ctx)
        o = rest.orders[0]
        assert o['epic'] == 'US100'
        assert o['direction'] == 'SELL'
        assert o['size'] == 1.0
        assert o['stop_level'] == 29550.0
        assert o['profit_level'] == 29350.0

    @pytest.mark.asyncio
    async def test_guaranteed_stop_is_not_requested(self):
        """
        CLAUDE.md gotcha 19 — every live position carries
        `guaranteedStop: false`, so a weekend gap is uncapped. Pinned as the
        current, deliberate behaviour.
        """
        rest = FakeRest()
        await live_skill(rest).execute(
            Context(signal='BUY', is_allowed=True, entry_price=29500.0,
                    position_size=1.0, stop_loss=29450.0, take_profit=29650.0))
        assert rest.orders[0]['guaranteed_stop'] is False

    @pytest.mark.asyncio
    async def test_the_order_is_confirmed_and_the_real_deal_id_is_used(self):
        """
        place_order returns only a dealReference; the real dealId and fill price
        come from the confirmation. Using the reference as the id would break
        every later join against /history/activity.
        """
        rest = FakeRest(confirm={'status': 'OPEN', 'dealId': 'REAL-1',
                                 'level': 29533.3})
        skill = live_skill(rest)
        ctx = Context(signal='BUY', is_allowed=True, entry_price=29500.0,
                      position_size=1.0, stop_loss=29450.0, take_profit=29650.0)
        await skill.execute(ctx)
        assert rest.confirms == ['REF-1']
        assert ctx.deal_id == 'REAL-1'
        assert ctx.current_position['entry_price'] == 29533.3

    @pytest.mark.asyncio
    async def test_the_confirmed_fill_price_not_the_signal_price_is_recorded(self):
        """
        CLAUDE.md gotcha 20: SL/TP are computed off the signal bar's close while
        the broker fills at market seconds later, so the two differ.
        """
        rest = FakeRest(confirm={'status': 'OPEN', 'dealId': 'D', 'level': 29288.7})
        skill = live_skill(rest)
        ctx = Context(signal='BUY', is_allowed=True, entry_price=29270.1,
                      position_size=1.0, stop_loss=29220.1, take_profit=29420.1)
        await skill.execute(ctx)
        assert ctx.current_position['entry_price'] == 29288.7

    @pytest.mark.asyncio
    async def test_a_missing_confirmation_level_falls_back_to_the_signal_price(self):
        rest = FakeRest(confirm={'status': 'OPEN', 'dealId': 'D'})
        skill = live_skill(rest)
        ctx = Context(signal='BUY', is_allowed=True, entry_price=29500.0,
                      position_size=1.0, stop_loss=29450.0, take_profit=29650.0)
        await skill.execute(ctx)
        assert ctx.current_position['entry_price'] == 29500.0

    @pytest.mark.asyncio
    async def test_a_missing_deal_id_falls_back_to_the_reference(self):
        rest = FakeRest(confirm={'status': 'OPEN', 'level': 29500.0})
        skill = live_skill(rest)
        ctx = Context(signal='BUY', is_allowed=True, entry_price=29500.0,
                      position_size=1.0, stop_loss=29450.0, take_profit=29650.0)
        await skill.execute(ctx)
        assert ctx.deal_id == 'REF-1'

    @pytest.mark.asyncio
    async def test_the_tracked_position_carries_everything_storage_needs(self):
        skill = live_skill()
        ctx = Context(signal='BUY', is_allowed=True, entry_price=29500.0,
                      position_size=2.0, stop_loss=29450.0, take_profit=29650.0)
        await skill.execute(ctx)
        p = ctx.current_position
        assert p['direction'] == 'BUY'
        assert p['size'] == 2.0
        assert p['stop_loss'] == 29450.0
        assert p['take_profit'] == 29650.0
        assert p['opened_at']

    @pytest.mark.asyncio
    async def test_a_disallowed_context_places_nothing(self):
        rest = FakeRest()
        skill = live_skill(rest)
        ctx = Context(signal='BUY', is_allowed=False, entry_price=29500.0)
        await skill.execute(ctx)
        assert rest.orders == []
        assert ctx.deal_id is None

    @pytest.mark.asyncio
    async def test_a_context_without_a_signal_places_nothing(self):
        rest = FakeRest()
        skill = live_skill(rest)
        await skill.execute(Context(signal=None, is_allowed=True))
        assert rest.orders == []


class TestBrokerRejection:
    """
    A placed order is not a filled order. Each of these shapes means "no
    position exists" and must return None.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize('status', ['DELETED', 'REJECTED'])
    async def test_a_rejected_status_is_not_a_fill(self, status):
        rest = FakeRest(confirm={'status': status, 'dealId': 'D1',
                                 'reason': 'INSUFFICIENT_FUNDS'})
        skill = live_skill(rest)
        ctx = Context(signal='BUY', is_allowed=True, entry_price=29500.0,
                      position_size=1.0, stop_loss=29450.0, take_profit=29650.0)
        await skill.execute(ctx)
        assert ctx.deal_id is None
        assert ctx.current_position is None

    @pytest.mark.asyncio
    async def test_a_zero_prefixed_deal_id_is_not_a_fill(self):
        """The broker's other way of saying no."""
        rest = FakeRest(confirm={'status': 'OPEN', 'level': 29500.0,
                                 'dealId': '00000000-0000-0000-abc'})
        skill = live_skill(rest)
        ctx = Context(signal='BUY', is_allowed=True, entry_price=29500.0,
                      position_size=1.0, stop_loss=29450.0, take_profit=29650.0)
        await skill.execute(ctx)
        assert ctx.deal_id is None

    @pytest.mark.asyncio
    async def test_a_place_failure_returns_no_fill(self):
        rest = FakeRest(place_raises=RuntimeError('400 margin'))
        skill = live_skill(rest)
        ctx = Context(signal='BUY', is_allowed=True, entry_price=29500.0,
                      position_size=1.0, stop_loss=29450.0, take_profit=29650.0)
        await skill.execute(ctx)
        assert ctx.deal_id is None

    @pytest.mark.asyncio
    async def test_a_confirm_failure_returns_no_fill(self):
        rest = FakeRest(confirm_raises=RuntimeError('timeout'))
        skill = live_skill(rest)
        ctx = Context(signal='BUY', is_allowed=True, entry_price=29500.0,
                      position_size=1.0, stop_loss=29450.0, take_profit=29650.0)
        await skill.execute(ctx)
        assert ctx.deal_id is None


class TestMockMode:

    @pytest.mark.asyncio
    async def test_mock_mode_fills_without_touching_the_broker(self):
        rest = FakeRest()
        skill = ExecutionSkill({'epic': 'US100', 'mock_mode': True})
        skill.rest_client = rest
        ctx = Context(signal='BUY', is_allowed=True, entry_price=29500.0,
                      position_size=1.0, stop_loss=29450.0, take_profit=29650.0)
        await skill.execute(ctx)
        assert rest.orders == []
        assert ctx.deal_id.startswith('DEAL')

    @pytest.mark.asyncio
    async def test_no_rest_client_also_falls_back_to_a_mock_fill(self):
        skill = ExecutionSkill({'epic': 'US100', 'mock_mode': False})
        assert skill.rest_client is None
        ctx = Context(signal='BUY', is_allowed=True, entry_price=29500.0,
                      position_size=1.0, stop_loss=29450.0, take_profit=29650.0)
        await skill.execute(ctx)
        assert ctx.deal_id is not None

    @pytest.mark.asyncio
    async def test_the_mock_fill_uses_the_requested_entry_price(self):
        skill = ExecutionSkill({'epic': 'US100', 'mock_mode': True})
        ctx = Context(signal='BUY', is_allowed=True, entry_price=29500.0,
                      position_size=1.0, stop_loss=29450.0, take_profit=29650.0)
        await skill.execute(ctx)
        assert ctx.current_position['entry_price'] == 29500.0


# ──────────────────────────────────────────────────────────────────────────
# The RISK_APPROVED event path
# ──────────────────────────────────────────────────────────────────────────

class TestRiskApprovedPath:

    @pytest.mark.asyncio
    async def test_an_approved_signal_publishes_order_filled(self):
        bus = EventBus(fast_mode=True)
        out = Orders(bus)
        skill = live_skill(bus=bus)
        await skill.on_risk_approved(approved_event())
        assert len(out.filled) == 1
        assert out.filled[0]['direction'] == 'BUY'
        assert out.filled[0]['deal_id'] == 'REAL-DEAL-1'

    @pytest.mark.asyncio
    async def test_transaction_costs_ride_along_on_the_fill(self):
        """So live P&L can be reconciled against the backtest cost model."""
        bus = EventBus(fast_mode=True)
        out = Orders(bus)
        skill = live_skill(bus=bus)
        await skill.on_risk_approved(approved_event())
        assert 'spread_cost' in out.filled[0]
        assert 'slippage_cost' in out.filled[0]

    @pytest.mark.asyncio
    @pytest.mark.parametrize('bad', ['NONE', '', None, 'HOLD'])
    async def test_a_non_directional_signal_is_dropped(self, bad):
        bus = EventBus(fast_mode=True)
        out = Orders(bus)
        rest = FakeRest()
        skill = live_skill(rest, bus=bus)
        await skill.on_risk_approved(approved_event(signal=bad))
        assert rest.orders == []
        assert out.filled == [] and out.rejected == []

    @pytest.mark.asyncio
    async def test_a_broker_failure_publishes_order_rejected(self):
        bus = EventBus(fast_mode=True)
        out = Orders(bus)

        class Boom(FakeRest):
            def place_order(self, **kw):
                raise RuntimeError('503 broker down')

        skill = live_skill(Boom(), bus=bus)
        # _place_order_api swallows and returns None, so the fill carries no id
        await skill.on_risk_approved(approved_event())
        assert out.rejected or out.filled, "the event path must resolve one way"

    @pytest.mark.asyncio
    async def test_costs_are_cached_for_the_fill_event(self):
        skill = live_skill()
        await skill.on_risk_approved(approved_event())
        assert skill._last_transaction_costs is not None

    @pytest.mark.asyncio
    async def test_no_event_bus_is_tolerated(self):
        skill = live_skill(bus=None)
        await skill.on_risk_approved(approved_event())    # must not raise


class TestIdempotency:
    """
    Duplicate suppression: the activity poll and the REST reconcile can both
    see the same signal, so a repeat must not place a second order.
    """

    class FakeIdem:
        def __init__(self, duplicate=False):
            self.duplicate = duplicate
            self.submissions, self.fills, self.rejections = [], [], []

        def is_duplicate(self, key):
            return self.duplicate

        def get_cached_result(self, key):
            return {'deal_id': 'CACHED-1'}

        def register_submission(self, order):
            self.submissions.append(order)

        def register_fill(self, key, deal_id):
            self.fills.append((key, deal_id))

        def register_rejection(self, key, reason):
            self.rejections.append((key, reason))

    @pytest.mark.asyncio
    async def test_a_fresh_order_is_registered_then_filled(self):
        idem = self.FakeIdem(duplicate=False)
        rest = FakeRest()
        skill = ExecutionSkill({'epic': 'US100', 'mock_mode': False},
                               idempotency_manager=idem)
        skill.rest_client = rest
        await skill.on_risk_approved(approved_event())
        assert len(idem.submissions) == 1
        assert len(idem.fills) == 1
        assert len(rest.orders) == 1

    @pytest.mark.asyncio
    async def test_a_duplicate_places_no_second_order(self):
        idem = self.FakeIdem(duplicate=True)
        rest = FakeRest()
        skill = ExecutionSkill({'epic': 'US100', 'mock_mode': False},
                               idempotency_manager=idem)
        skill.rest_client = rest
        await skill.on_risk_approved(approved_event())
        assert rest.orders == [], "a duplicate must never reach the broker"
        assert idem.submissions == []

    @pytest.mark.asyncio
    async def test_the_retry_policy_is_used_when_supplied(self):
        class Retry:
            def __init__(self):
                self.calls = 0

            async def execute_with_retry(self, fn, *args):
                self.calls += 1
                return await fn(*args)

        retry = Retry()
        rest = FakeRest()
        skill = ExecutionSkill({'epic': 'US100', 'mock_mode': False},
                               retry_policy=retry)
        skill.rest_client = rest
        await skill.on_risk_approved(approved_event())
        assert retry.calls == 1
        assert len(rest.orders) == 1


# ──────────────────────────────────────────────────────────────────────────
# Closing positions, including the stale-deal-id fallback
# ──────────────────────────────────────────────────────────────────────────

class TestClosePosition:

    @pytest.mark.asyncio
    async def test_a_normal_close_calls_the_broker(self):
        rest = FakeRest()
        assert await live_skill(rest).close_position('D1') is True
        assert rest.closes == ['D1']

    @pytest.mark.asyncio
    async def test_mock_mode_reports_success_without_calling_out(self):
        rest = FakeRest()
        skill = ExecutionSkill({'epic': 'US100', 'mock_mode': True})
        skill.rest_client = rest
        assert await skill.close_position('D1') is True
        assert rest.closes == []

    @pytest.mark.asyncio
    async def test_a_non_404_failure_reports_failure(self):
        """
        The caller aborts a reverse entry on a failed close, so reporting False
        here is what stops positions accumulating.
        """
        rest = FakeRest(close_raises=RuntimeError('500 server error'))
        assert await live_skill(rest).close_position('D1') is False

    @pytest.mark.asyncio
    async def test_a_404_closes_whatever_is_actually_open(self):
        """
        A stale deal_id after a restart: the position exists under a new id, so
        the fallback finds the real one and closes that instead.
        """
        calls = []

        class Stale(FakeRest):
            def close_position(self, deal_id=None):
                calls.append(deal_id)
                if deal_id == 'STALE':
                    raise RuntimeError('404 not found')
                return {'status': 'CLOSED'}

        rest = Stale(positions=[{'market': {'epic': 'US100'},
                                 'position': {'dealId': 'REAL-9'}}])
        assert await live_skill(rest).close_position('STALE') is True
        assert calls == ['STALE', 'REAL-9']

    @pytest.mark.asyncio
    async def test_a_404_with_nothing_open_counts_as_already_closed(self):
        rest = FakeRest(close_raises=RuntimeError('404 not found'), positions=[])
        assert await live_skill(rest).close_position('D1') is True

    @pytest.mark.asyncio
    async def test_the_fallback_only_considers_this_instrument(self):
        class Stale(FakeRest):
            def close_position(self, deal_id=None):
                self.closes.append(deal_id)
                if deal_id == 'STALE':
                    raise RuntimeError('404 not found')
                return {}

        rest = Stale(positions=[{'market': {'epic': 'GOLD'},
                                 'position': {'dealId': 'OTHER'}}])
        # only a GOLD position exists, so for US100 there is nothing to close
        assert await live_skill(rest).close_position('STALE') is True
        assert 'OTHER' not in rest.closes

    @pytest.mark.asyncio
    async def test_a_position_without_a_deal_id_reports_failure(self):
        class Stale(FakeRest):
            def close_position(self, deal_id=None):
                raise RuntimeError('404 not found')

        rest = Stale(positions=[{'market': {'epic': 'US100'}, 'position': {}}])
        assert await live_skill(rest).close_position('STALE') is False

    @pytest.mark.asyncio
    async def test_a_failing_fallback_reports_failure(self):
        class Stale(FakeRest):
            def close_position(self, deal_id=None):
                raise RuntimeError('404 not found')

            def get_open_positions(self):
                raise RuntimeError('500 on /positions')

        assert await live_skill(Stale()).close_position('STALE') is False


class TestValidateConfig:

    def test_a_valid_config_passes(self):
        assert ExecutionSkill({'sl_pips': 50, 'tp_pips': 150,
                               'position_size': 1}).validate_config() is True

    @pytest.mark.parametrize('bad', [
        {'sl_pips': 0, 'tp_pips': 150, 'position_size': 1},
        {'sl_pips': 50, 'tp_pips': 0, 'position_size': 1},
        {'sl_pips': -1, 'tp_pips': 150, 'position_size': 1},
    ])
    def test_non_positive_pips_are_rejected(self, bad):
        with pytest.raises(SkillExecutionError):
            ExecutionSkill(bad).validate_config()

    def test_a_non_positive_size_is_rejected(self):
        with pytest.raises(SkillExecutionError):
            ExecutionSkill({'sl_pips': 50, 'tp_pips': 150,
                            'position_size': 0}).validate_config()


# ──────────────────────────────────────────────────────────────────────────
# CapitalWebSocketClient
# ──────────────────────────────────────────────────────────────────────────

class FakeSocket:
    """
    A minimal websockets-style connection: `incoming` is replayed by async
    iteration, `sent` records every frame, and `raise_on_iter` injects a drop.
    """

    def __init__(self, incoming=None, raise_on_iter=None):
        self.incoming = list(incoming or [])
        self.sent = []
        self.closed = 0
        self.raise_on_iter = raise_on_iter

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    async def close(self):
        self.closed += 1

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for m in self.incoming:
            yield m
        if self.raise_on_iter:
            raise self.raise_on_iter


def ws_client(sock=None, **kw):
    c = CapitalWebSocketClient('cst-1', 'sec-1', **kw)
    if sock is not None:
        c.ws = sock
        c.running = True
    return c


def ohlc_msg(epic='US100', resolution='MINUTE_5', price_type='ask',
             o=29500.0, h=29510.0, l=29490.0, c=29505.0, t=1792000000000):
    return json.dumps({'destination': 'ohlc.event',
                       'payload': {'epic': epic, 'resolution': resolution,
                                   'priceType': price_type, 'o': o, 'h': h,
                                   'l': l, 'c': c, 't': t}})


def quote_msg(epic='US100', bid=29499.0, ofr=29501.0, ts=1792000000000):
    return json.dumps({'destination': 'quote',
                       'payload': {'epic': epic, 'bid': bid, 'ofr': ofr,
                                   'timestamp': ts}})


class TestWebSocketConnect:

    def test_the_streaming_url_is_shared_by_demo_and_live(self):
        assert WS_URL.startswith('wss://')
        assert ws_client().ws_url == WS_URL

    def test_tokens_are_stored_for_every_subsequent_frame(self):
        c = ws_client()
        assert c.cst == 'cst-1' and c.security_token == 'sec-1'

    def test_it_starts_disconnected(self):
        c = ws_client()
        assert c.ws is None and c.running is False

    @pytest.mark.asyncio
    async def test_connect_opens_the_socket_and_starts_the_keepalive(self, monkeypatch):
        import clients.capital_websocket as mod
        sock = FakeSocket()

        async def fake_connect(url, **kw):
            assert kw['ping_interval'] is None, \
                "the client sends its own pings, so the library's must be off"
            return sock

        monkeypatch.setattr(mod.websockets, 'connect', fake_connect)
        c = ws_client(ping_interval=0.01)
        await c.connect()
        try:
            assert c.ws is sock
            assert c.running is True
            assert c.keepalive_task is not None
        finally:
            await c.close()

    @pytest.mark.asyncio
    async def test_a_connect_failure_propagates(self, monkeypatch):
        import clients.capital_websocket as mod

        async def boom(url, **kw):
            raise OSError('dns failure')

        monkeypatch.setattr(mod.websockets, 'connect', boom)
        with pytest.raises(OSError):
            await ws_client().connect()

    @pytest.mark.asyncio
    async def test_close_stops_the_keepalive_and_the_socket(self, monkeypatch):
        import clients.capital_websocket as mod
        sock = FakeSocket()
        monkeypatch.setattr(mod.websockets, 'connect',
                            lambda url, **kw: _coro(sock))
        c = ws_client(ping_interval=0.01)
        await c.connect()
        await c.close()
        assert c.running is False
        assert sock.closed == 1
        assert c.keepalive_task.cancelled() or c.keepalive_task.done()

    @pytest.mark.asyncio
    async def test_close_is_safe_without_a_connection(self):
        await ws_client().close()


async def _coro(value):
    return value


class TestSubscriptions:

    @pytest.mark.asyncio
    async def test_quote_subscription_frame(self):
        sock = FakeSocket()
        await ws_client(sock).subscribe_quotes(['US100'])
        f = sock.sent[0]
        assert f['destination'] == 'marketData.subscribe'
        assert f['payload']['epics'] == ['US100']
        assert f['cst'] == 'cst-1' and f['securityToken'] == 'sec-1'

    @pytest.mark.asyncio
    async def test_ohlc_subscription_frame(self):
        sock = FakeSocket()
        await ws_client(sock).subscribe_ohlc(['US100'], resolution='MINUTE_5')
        f = sock.sent[0]
        assert f['destination'] == 'OHLCMarketData.subscribe'
        assert f['payload']['resolutions'] == ['MINUTE_5']
        assert f['payload']['type'] == 'classic'

    @pytest.mark.asyncio
    async def test_the_resolution_and_bar_type_are_configurable(self):
        sock = FakeSocket()
        await ws_client(sock).subscribe_ohlc(['GOLD'], resolution='HOUR',
                                             bar_type='heikin_ashi')
        assert sock.sent[0]['payload']['resolutions'] == ['HOUR']
        assert sock.sent[0]['payload']['type'] == 'heikin_ashi'

    @pytest.mark.asyncio
    async def test_sending_without_a_connection_does_not_raise(self):
        c = ws_client()
        await c.subscribe_quotes(['US100'])     # ws is None — warns, no crash


class TestKeepalive:

    @pytest.mark.asyncio
    async def test_a_ping_is_sent_every_interval(self):
        sock = FakeSocket()
        c = ws_client(sock, ping_interval=0.01)
        task = asyncio.create_task(c._keepalive())
        await asyncio.sleep(0.06)
        c.running = False
        task.cancel()
        with __import__('contextlib').suppress(asyncio.CancelledError):
            await task
        pings = [f for f in sock.sent if f['destination'] == 'ping']
        assert pings, "the 10-minute idle timeout needs these"
        assert pings[0]['cst'] == 'cst-1'

    @pytest.mark.asyncio
    async def test_the_loop_exits_once_running_goes_false(self):
        sock = FakeSocket()
        c = ws_client(sock, ping_interval=0.01)
        c.running = False
        await asyncio.wait_for(c._keepalive(), timeout=1)

    @pytest.mark.asyncio
    async def test_a_send_failure_ends_the_keepalive_rather_than_spinning(self):
        class BadSocket(FakeSocket):
            async def send(self, raw):
                raise RuntimeError('socket gone')

        c = ws_client(BadSocket(), ping_interval=0.01)
        await asyncio.wait_for(c._keepalive(), timeout=2)


class TestMessageDispatch:

    @pytest.mark.asyncio
    async def test_a_quote_message_reaches_the_quote_handler(self):
        got = []
        c = ws_client(FakeSocket())
        c.on_quote = lambda q: _append(got, q)
        await c._handle_message(quote_msg())
        assert got[0]['epic'] == 'US100'
        assert got[0]['mid'] == pytest.approx(29500.0)
        assert got[0]['spread'] == pytest.approx(2.0)

    @pytest.mark.asyncio
    async def test_an_ohlc_message_reaches_the_candle_handler(self):
        got = []
        c = ws_client(FakeSocket())
        c.on_candle = lambda x: _append(got, x)
        await c._handle_message(ohlc_msg())
        assert got[0]['close'] == 29505.0

    @pytest.mark.asyncio
    async def test_a_ping_ack_is_ignored(self):
        c = ws_client(FakeSocket())
        await c._handle_message(json.dumps({'destination': 'ping'}))

    @pytest.mark.asyncio
    async def test_an_unknown_destination_is_logged_not_fatal(self):
        c = ws_client(FakeSocket())
        await c._handle_message(json.dumps(
            {'destination': 'marketData.subscribe', 'status': 'OK'}))

    @pytest.mark.asyncio
    async def test_malformed_json_does_not_raise(self):
        await ws_client(FakeSocket())._handle_message('{not json')

    @pytest.mark.asyncio
    async def test_a_failing_callback_does_not_escape(self):
        """One bad handler must not take down the stream."""
        async def boom(_):
            raise RuntimeError('handler bug')

        c = ws_client(FakeSocket())
        c.on_candle = boom
        await c._handle_message(ohlc_msg())      # swallowed by _handle_message

    @pytest.mark.asyncio
    async def test_a_message_with_no_payload_is_tolerated(self):
        c = ws_client(FakeSocket())
        await c._handle_message(json.dumps({'destination': 'quote'}))


async def _append(target, value):
    target.append(value)


class TestRunLoop:

    @pytest.mark.asyncio
    async def test_every_queued_message_is_processed(self):
        got = []
        sock = FakeSocket(incoming=[ohlc_msg(c=1.0), ohlc_msg(c=2.0),
                                    ohlc_msg(c=3.0)])
        c = ws_client(sock)
        c.on_candle = lambda x: _append(got, x)
        await c.run()
        assert [g['close'] for g in got] == [1.0, 2.0, 3.0]

    @pytest.mark.asyncio
    async def test_the_socket_is_closed_when_the_loop_ends(self):
        sock = FakeSocket(incoming=[])
        c = ws_client(sock)
        await c.run()
        assert sock.closed == 1, "run() must clean up in its finally block"

    @pytest.mark.asyncio
    async def test_a_dropped_connection_is_raised_so_the_caller_reconnects(self):
        sock = FakeSocket(incoming=[ohlc_msg()],
                          raise_on_iter=ConnectionResetError('dropped'))
        c = ws_client(sock)
        with pytest.raises(ConnectionResetError):
            await c.run()
        assert sock.closed == 1

    @pytest.mark.asyncio
    async def test_cancellation_is_swallowed_and_the_socket_closed(self):
        class Hanging(FakeSocket):
            async def _gen(self):
                raise asyncio.CancelledError()
                yield  # pragma: no cover

        sock = Hanging()
        c = ws_client(sock)
        await c.run()      # CancelledError is caught, not re-raised
        assert sock.closed == 1


class TestOhlcRouting:
    """
    Capital.com sends a BID and an ASK candle per bar. Only ASK/OFR is acted on
    — that is the price paid to buy, consistent with the SL/TP levels — so a bar
    must not be processed twice.
    """

    @pytest.mark.asyncio
    async def test_a_bid_candle_is_skipped(self):
        got = []
        c = ws_client(FakeSocket())
        c.on_candle = lambda x: _append(got, x)
        await c._handle_message(ohlc_msg(price_type='bid'))
        assert got == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize('pt', ['ask', 'ASK', 'ofr', 'OFR'])
    async def test_ask_and_ofr_candles_are_processed(self, pt):
        got = []
        c = ws_client(FakeSocket())
        c.on_candle = lambda x: _append(got, x)
        await c._handle_message(ohlc_msg(price_type=pt))
        assert len(got) == 1

    @pytest.mark.asyncio
    async def test_an_hour_candle_routes_to_the_h1_handler(self):
        m5, h1 = [], []
        c = ws_client(FakeSocket())
        c.on_candle = lambda x: _append(m5, x)
        c.on_h1_candle = lambda x: _append(h1, x)
        await c._handle_message(ohlc_msg(resolution='HOUR'))
        assert len(h1) == 1 and m5 == []

    @pytest.mark.asyncio
    async def test_an_hour_candle_falls_back_to_on_candle_without_an_h1_handler(self):
        m5 = []
        c = ws_client(FakeSocket())
        c.on_candle = lambda x: _append(m5, x)
        await c._handle_message(ohlc_msg(resolution='HOUR'))
        assert len(m5) == 1

    @pytest.mark.asyncio
    async def test_the_latest_candle_is_cached_even_for_a_bid(self):
        c = ws_client(FakeSocket())
        await c._handle_message(ohlc_msg(price_type='bid', c=1.0))
        assert c.get_latest_candle('US100')['close'] == 1.0

    @pytest.mark.asyncio
    async def test_the_timestamp_is_converted_from_milliseconds(self):
        got = []
        c = ws_client(FakeSocket())
        c.on_candle = lambda x: _append(got, x)
        await c._handle_message(ohlc_msg(t=1792000000000))
        assert got[0]['time'] == datetime.fromtimestamp(1792000000000 / 1000)

    @pytest.mark.asyncio
    async def test_a_candle_without_a_timestamp_has_no_time(self):
        got = []
        c = ws_client(FakeSocket())
        c.on_candle = lambda x: _append(got, x)
        await c._handle_message(json.dumps(
            {'destination': 'ohlc.event',
             'payload': {'epic': 'US100', 'resolution': 'MINUTE_5',
                         'priceType': 'ask', 'o': 1, 'h': 2, 'l': 0, 'c': 1.5}}))
        assert got[0]['time'] is None


class TestQuoteHandling:

    @pytest.mark.asyncio
    async def test_the_mid_is_the_average_of_bid_and_offer(self):
        c = ws_client(FakeSocket())
        await c._handle_message(quote_msg(bid=100.0, ofr=102.0))
        q = c.get_latest_quote('US100')
        assert q['mid'] == 101.0 and q['spread'] == 2.0

    @pytest.mark.asyncio
    async def test_a_missing_side_leaves_mid_and_spread_unknown(self):
        c = ws_client(FakeSocket())
        await c._handle_message(json.dumps(
            {'destination': 'quote', 'payload': {'epic': 'US100', 'bid': 100.0}}))
        q = c.get_latest_quote('US100')
        assert q['mid'] is None and q['spread'] is None

    @pytest.mark.asyncio
    async def test_the_quote_cache_is_updated_without_a_handler(self):
        c = ws_client(FakeSocket())
        await c._handle_message(quote_msg(bid=1.0, ofr=3.0))
        assert c.get_latest_quote('US100')['mid'] == 2.0

    def test_an_unknown_epic_has_no_cached_data(self):
        c = ws_client()
        assert c.get_latest_quote('NOPE') is None
        assert c.get_latest_candle('NOPE') is None
