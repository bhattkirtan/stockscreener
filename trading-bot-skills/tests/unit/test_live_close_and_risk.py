"""
Unit tests — live close detection and risk gating, as the live bot sees them.

Covers the two halves of the live loop the backtester never exercises:

  1. classify_activity / derive_close_reason — the /history/activity parser.
     Its previous version walked a `details['actions']` array that does not
     exist in the response, so no close was ever detected: P&L was recorded as
     0.0 on 365 trades, every exit was labelled 'SIGNAL', and the SL/TP
     cooldowns, daily-loss limit and consecutive-loss breaker all went inert.
     Payloads here are the real shapes captured from the live API on
     2026-10-21.

  2. RiskSkill gating driven as a SEQUENCE of events. In backtest the gates are
     evaluated against candle timestamps on clean data; live they are evaluated
     against wall clock and mutate state across calls (cooldown anchored to the
     previous close, daily P&L accumulated per UTC day). Order matters, so these
     drive several events through one skill instance rather than testing gates
     in isolation.
"""
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from core.event_bus import Event, EventBus, EventType
from orchestrator.main import classify_activity, derive_close_reason
from skills.base_skill import Context
from skills.risk.risk_skill import RiskSkill


# ──────────────────────────────────────────────────────────────────────────
# Real payloads captured from the live demo API
# ──────────────────────────────────────────────────────────────────────────
def close_activity(epic='US100', deal_id='D1', source='SL', level=29579.9,
                   open_price=29526.9, direction='BUY', size=1.0):
    """A close: `openPrice` present, `direction` is the CLOSING side."""
    return {'epic': epic, 'dealId': deal_id, 'source': source,
            'type': 'POSITION', 'status': 'ACCEPTED',
            'details': {'size': size, 'direction': direction, 'level': level,
                        'stopLevel': 29579.7, 'profitLevel': 29379.7,
                        'guaranteedStop': False, 'openPrice': open_price}}


def open_activity(epic='US100', deal_id='D1', direction='SELL', level=29526.9):
    """An open: no `openPrice`, `direction` is the position's own side."""
    return {'epic': epic, 'dealId': deal_id, 'source': 'USER',
            'type': 'POSITION', 'status': 'ACCEPTED',
            'details': {'size': 1.0, 'direction': direction, 'level': level,
                        'stopLevel': 29579.7, 'profitLevel': 29379.7}}


class TestCloseDiscrimination:

    def test_openprice_marks_a_close(self):
        assert classify_activity(close_activity())['is_close'] is True

    def test_absent_openprice_marks_an_open(self):
        assert classify_activity(open_activity())['is_close'] is False

    def test_no_deal_id_is_skipped(self):
        a = close_activity()
        a['dealId'] = ''
        assert classify_activity(a) is None

    def test_missing_details_is_tolerated(self):
        assert classify_activity({'dealId': 'D1'})['is_close'] is False

    def test_the_response_has_no_actions_array(self):
        """Guards the assumption the old parser got wrong."""
        assert 'actions' not in close_activity()['details']

    def test_the_response_has_no_profit_field(self):
        """P&L must come from /history/transactions, not from here."""
        assert 'profit' not in close_activity()['details']


class TestCloseDirectionFlip:
    """
    On a close, `details.direction` is the direction of the CLOSING trade — the
    opposite of the position. Using it directly mislabels every trade's side,
    which also inverts any price-derived P&L fallback.
    """

    def test_close_direction_is_flipped_to_the_position_side(self):
        assert classify_activity(close_activity(direction='BUY'))['direction'] == 'SELL'
        assert classify_activity(close_activity(direction='SELL'))['direction'] == 'BUY'

    def test_open_direction_is_not_flipped(self):
        assert classify_activity(open_activity(direction='SELL'))['direction'] == 'SELL'

    def test_open_and_close_of_one_position_agree(self):
        """The real captured pair: SELL opened, closed with direction BUY."""
        o = classify_activity(open_activity(direction='SELL'))
        c = classify_activity(close_activity(direction='BUY'))
        assert o['direction'] == c['direction'] == 'SELL'

    def test_direction_is_case_insensitive(self):
        assert classify_activity(close_activity(direction='buy'))['direction'] == 'SELL'

    def test_missing_direction_defaults_then_flips(self):
        a = close_activity()
        del a['details']['direction']
        assert classify_activity(a)['direction'] == 'SELL'   # default BUY, flipped


class TestExitReason:

    @pytest.mark.parametrize('source,expected', [
        ('SL', 'SL_HIT'), ('TP', 'TP_HIT'), ('USER', 'SIGNAL'),
        ('sl', 'SL_HIT'), ('tp', 'TP_HIT'), ('', 'SIGNAL'), (None, 'SIGNAL'),
    ])
    def test_source_is_authoritative(self, source, expected):
        assert derive_close_reason(source=source) == expected

    def test_source_wins_over_description(self):
        assert derive_close_reason(source='TP', description='stop loss') == 'TP_HIT'

    @pytest.mark.parametrize('desc,expected', [
        ('Stop loss triggered', 'SL_HIT'),
        ('Limit order filled', 'TP_HIT'),
        ('Take profit hit', 'TP_HIT'),
        ('closed by user', 'SIGNAL'),
    ])
    def test_description_is_the_fallback(self, desc, expected):
        assert derive_close_reason(source=None, description=desc) == expected

    def test_empty_description_yields_signal(self):
        """
        The regression: the REST reconcile passes description='', so every exit
        became 'SIGNAL' and _check_cooldown returned "no cooldown required".
        """
        assert derive_close_reason(source=None, description='') == 'SIGNAL'

    def test_reason_flows_through_the_parser(self):
        assert classify_activity(close_activity(source='TP'))['close_reason'] == 'TP_HIT'


class TestParsedNumerics:

    def test_levels_and_size_are_floats(self):
        p = classify_activity(close_activity(level=29579.9, open_price=29526.9))
        assert p['close_level'] == 29579.9
        assert p['entry_price'] == 29526.9
        assert p['size'] == 1.0

    def test_non_numeric_values_become_zero_not_crash(self):
        a = close_activity()
        a['details']['level'] = 'n/a'
        a['details']['size'] = None
        p = classify_activity(a)
        assert p['close_level'] == 0.0 and p['size'] == 0.0

    def test_profit_level_falls_back_to_limit_level(self):
        a = open_activity()
        del a['details']['profitLevel']
        a['details']['limitLevel'] = 123.0
        assert classify_activity(a)['profit_level'] == 123.0

    def test_a_full_day_of_mixed_events_parses(self):
        """11 opens + 11 closes, as a real session delivers them."""
        acts = []
        for i in range(11):
            acts.append(open_activity(deal_id=f'D{i}'))
            acts.append(close_activity(deal_id=f'D{i}', source='SL'))
        parsed = [classify_activity(a) for a in acts]
        assert all(p is not None for p in parsed)
        assert sum(p['is_close'] for p in parsed) == 11
        assert all(p['close_reason'] == 'SL_HIT' for p in parsed if p['is_close'])


# ──────────────────────────────────────────────────────────────────────────
# RiskSkill driven as a live sequence
# ──────────────────────────────────────────────────────────────────────────
def make_risk(bus=None, **over):
    cfg = {
        'enabled': True, 'position_size': 1.0, 'position_size_pct': 2.0,
        'max_position_size': 10.0, 'sl_cooldown_minutes': 30,
        'tp_cooldown_minutes': 10, 'initial_capital': 10000,
        'trading_hours': {'enabled': False},
    }
    cfg.update(over)
    return RiskSkill(cfg, event_bus=bus)


def live_context(signal='BUY', price=4100.0, ts=None):
    """
    The LIVE path. TradingOrchestrator.on_candle calls risk.execute(context)
    (trading_orchestrator.py:168), NOT on_signal_generated. The two have
    DIFFERENT gate sets — see TestGatePathAsymmetry — so a live-POV test must
    drive this one.
    """
    ts = ts or datetime(2026, 10, 21, 10, 0)
    return Context(
        current_candle={'timestamp': ts, 'open': price, 'high': price + 2,
                        'low': price - 2, 'close': price},
        signal=signal, entry_price=price,
        indicators={'current_price': price},
    )


async def arm(risk, first_signal='SELL', ts=None):
    """
    Walk a RiskSkill past its startup-flip suppression.

    The live path refuses to trade until the trend has flipped at least once
    since the process started, so that a restart does not enter mid-trend.
    Because bot_control_api restarts every bot daily at 21:00 UTC, this fires
    once per bot per day in production — and the backtest path has no
    equivalent, so it is a standing live/backtest divergence.
    """
    await risk.execute(live_context(signal=first_signal, ts=ts))


async def arm_events(risk, first_signal='SELL', ts=None):
    """
    Same as arm(), but driven through the EventBus path.

    Since the two gate chains were unified behind
    RiskSkill._evaluate_entry_gates, the event path applies the startup-flip
    gate too — so an event-path test whose subject is some *other* gate has to
    walk past it first, exactly as the context-path tests already did.
    """
    await risk.on_signal_generated(signal_event(signal=first_signal, ts=ts))


def signal_event(signal='BUY', price=4100.0, ts=None):
    return Event(event_type=EventType.SIGNAL_GENERATED, instrument='GOLD',
                 source='analysis',
                 payload={'signal': signal, 'entry_price': price,
                          'timestamp': ts or datetime(2026, 10, 21, 10, 0),
                          'indicators': {'current_price': price}})


class Outcomes:
    def __init__(self, bus):
        self.approved, self.rejected = [], []
        bus.subscribe(EventType.RISK_APPROVED, self._ok)
        bus.subscribe(EventType.RISK_REJECTED, self._no)

    async def _ok(self, e):
        self.approved.append(e)

    async def _no(self, e):
        self.rejected.append(e)


class TestRiskGatingLiveSequence:

    @pytest.mark.asyncio
    async def test_a_clean_signal_is_approved(self):
        bus = EventBus(fast_mode=True)
        out = Outcomes(bus)
        risk = make_risk(bus)
        await arm_events(risk)
        out.rejected.clear()          # the arming signal is itself rejected
        await risk.on_signal_generated(signal_event())
        assert len(out.approved) == 1 and out.rejected == []

    @pytest.mark.asyncio
    async def test_non_directional_signal_is_ignored(self):
        bus = EventBus(fast_mode=True)
        out = Outcomes(bus)
        risk = make_risk(bus)
        await risk.on_signal_generated(signal_event(signal='NONE'))
        assert out.approved == [] and out.rejected == []

    @pytest.mark.asyncio
    async def test_skip_hours_blocks_entry(self):
        bus = EventBus(fast_mode=True)
        out = Outcomes(bus)
        risk = make_risk(bus, skip_hours=[0, 1, 2, 3, 4, 5, 6, 7])
        await arm_events(risk, ts=datetime(2026, 10, 21, 10, 0))
        out.rejected.clear()
        await risk.on_signal_generated(
            signal_event(ts=datetime(2026, 10, 21, 3, 0)))
        assert out.approved == [] and len(out.rejected) == 1

    @pytest.mark.asyncio
    async def test_allowed_hour_passes_skip_filter(self):
        bus = EventBus(fast_mode=True)
        out = Outcomes(bus)
        risk = make_risk(bus, skip_hours=[0, 1, 2])
        await arm_events(risk, ts=datetime(2026, 10, 21, 10, 0))
        await risk.on_signal_generated(
            signal_event(ts=datetime(2026, 10, 21, 10, 0)))
        assert len(out.approved) == 1

    @pytest.mark.asyncio
    async def test_sl_cooldown_blocks_then_expires(self):
        """
        The live-only bug: because every close was labelled 'SIGNAL', this gate
        never fired in production. Driven as a sequence: close -> immediate
        re-signal (blocked) -> later re-signal (allowed).
        """
        bus = EventBus(fast_mode=True)
        out = Outcomes(bus)
        risk = make_risk(bus, sl_cooldown_minutes=30)
        t0 = datetime(2026, 10, 21, 10, 0)
        await arm_events(risk, ts=t0)
        out.rejected.clear()
        risk.on_position_closed(direction='BUY', close_reason='SL_HIT',
                                entry_price=4100.0, close_price=4085.0,
                                close_time=t0, pnl=-15.0)
        await risk.on_signal_generated(signal_event(ts=t0 + timedelta(minutes=5)))
        assert len(out.rejected) == 1, "within cooldown"
        await risk.on_signal_generated(signal_event(ts=t0 + timedelta(minutes=31)))
        assert len(out.approved) == 1, "after cooldown"

    @pytest.mark.asyncio
    async def test_signal_labelled_close_applies_no_cooldown(self):
        """Pins the consequence of the mislabelling, so a regression is visible."""
        bus = EventBus(fast_mode=True)
        out = Outcomes(bus)
        risk = make_risk(bus, sl_cooldown_minutes=30)
        t0 = datetime(2026, 10, 21, 10, 0)
        await arm_events(risk, ts=t0)
        risk.on_position_closed(direction='BUY', close_reason='SIGNAL',
                                entry_price=4100.0, close_price=4085.0,
                                close_time=t0, pnl=-15.0)
        await risk.on_signal_generated(signal_event(ts=t0 + timedelta(minutes=1)))
        assert len(out.approved) == 1, "SIGNAL closes bypass the cooldown"

    @pytest.mark.asyncio
    async def test_tp_cooldown_is_shorter_than_sl(self):
        bus = EventBus(fast_mode=True)
        out = Outcomes(bus)
        risk = make_risk(bus, sl_cooldown_minutes=30, tp_cooldown_minutes=10)
        t0 = datetime(2026, 10, 21, 10, 0)
        await arm_events(risk, ts=t0)
        out.rejected.clear()
        risk.on_position_closed(direction='BUY', close_reason='TP_HIT',
                                entry_price=4100.0, close_price=4160.0,
                                close_time=t0, pnl=60.0)
        await risk.on_signal_generated(signal_event(ts=t0 + timedelta(minutes=5)))
        assert len(out.rejected) == 1
        await risk.on_signal_generated(signal_event(ts=t0 + timedelta(minutes=11)))
        assert len(out.approved) == 1

    @pytest.mark.asyncio
    async def test_open_position_blocks_a_second_entry_on_the_live_path(self):
        """Only one position at a time — the gate the live path relies on."""
        risk = make_risk()
        await arm(risk)
        risk.has_open_position = True
        ctx = await risk.execute(live_context())
        assert ctx.is_allowed is False
        assert 'Max positions' in ctx.risk_reason

    @pytest.mark.asyncio
    async def test_flat_book_allows_entry_on_the_live_path(self):
        risk = make_risk()
        await arm(risk)
        ctx = await risk.execute(live_context())
        assert ctx.is_allowed is True
        assert ctx.position_size > 0


class TestStartupFlipSuppression:
    """
    Live-only behaviour with no backtest equivalent. On process start the first
    signal is recorded and suppressed; entries are enabled only once the trend
    flips. The daily 21:00 restart re-arms this for every bot every day.
    """

    @pytest.mark.asyncio
    async def test_first_signal_after_start_is_suppressed(self):
        risk = make_risk()
        ctx = await risk.execute(live_context(signal='BUY'))
        assert ctx.is_allowed is False
        assert 'Startup' in ctx.risk_reason

    @pytest.mark.asyncio
    async def test_same_direction_stays_suppressed(self):
        risk = make_risk()
        await risk.execute(live_context(signal='BUY'))
        ctx = await risk.execute(live_context(signal='BUY'))
        assert ctx.is_allowed is False
        assert 'Startup' in ctx.risk_reason

    @pytest.mark.asyncio
    async def test_a_flip_enables_entries(self):
        risk = make_risk()
        await risk.execute(live_context(signal='BUY'))
        ctx = await risk.execute(live_context(signal='SELL'))
        assert ctx.is_allowed is True

    @pytest.mark.asyncio
    async def test_suppression_does_not_return_after_the_flip(self):
        risk = make_risk(sl_cooldown_minutes=0)
        await risk.execute(live_context(signal='BUY'))
        await risk.execute(live_context(signal='SELL'))
        ctx = await risk.execute(live_context(signal='BUY'))
        assert ctx.is_allowed is True

    @pytest.mark.asyncio
    async def test_the_event_path_suppresses_the_first_signal_too(self):
        """
        Was a divergence: the backtest drives the event path, so it used to take
        the very first signal while live discarded it — one bar of divergence
        after every restart. Both paths now share
        RiskSkill._evaluate_entry_gates, so both suppress it.
        """
        bus = EventBus(fast_mode=True)
        out = Outcomes(bus)
        risk = make_risk(bus)
        await risk.on_signal_generated(signal_event(signal='BUY'))
        assert out.approved == [] and len(out.rejected) == 1
        assert 'Startup' in out.rejected[0].payload['reason']

    @pytest.mark.asyncio
    async def test_a_flip_enables_entries_on_the_event_path(self):
        bus = EventBus(fast_mode=True)
        out = Outcomes(bus)
        risk = make_risk(bus)
        await risk.on_signal_generated(signal_event(signal='BUY'))
        await risk.on_signal_generated(signal_event(signal='SELL'))
        assert len(out.approved) == 1

    @pytest.mark.asyncio
    async def test_the_gate_can_be_switched_off(self):
        """
        `startup_flip_gate: false` disables it on both paths — the escape hatch
        for a backtest that wants to measure the strategy without the restart
        artefact.
        """
        bus = EventBus(fast_mode=True)
        out = Outcomes(bus)
        risk = make_risk(bus, startup_flip_gate=False)
        await risk.on_signal_generated(signal_event(signal='BUY'))
        assert len(out.approved) == 1

    @pytest.mark.asyncio
    async def test_resuming_a_live_position_bypasses_the_gate(self):
        """_startup_flip_seen is set externally when a position is resumed."""
        risk = make_risk()
        risk._startup_flip_seen = True
        assert (await risk.execute(live_context(signal='BUY'))).is_allowed is True


class TestGatePathParity:
    """
    RiskSkill used to have TWO gate implementations enforcing DIFFERENT rules:

      execute(context)        — the sequential orchestrator the live bot runs.
                                Had: open-position, startup-flip, skip_hours,
                                loss circuit, daily loss, trading hours, cooldown.
      on_signal_generated(e)  — the EventBus path that run_skills_backtest.py
                                drives. Had: skip_hours, loss circuit, daily
                                loss, trading hours, cooldown, plus the circuit
                                breaker / session filter / news kill-switch.

    So the event path could stack positions, and the live path silently ignored
    the news kill-switch and session filter. Both now delegate to
    RiskSkill._evaluate_entry_gates, so the two cannot drift apart again. These
    tests assert each gate fires on BOTH paths.
    """

    @pytest.mark.asyncio
    async def test_context_path_blocks_when_a_position_is_open(self):
        risk = make_risk()
        await arm(risk)
        risk.has_open_position = True
        ctx = await risk.execute(live_context())
        assert ctx.is_allowed is False
        assert 'Max positions' in ctx.risk_reason

    @pytest.mark.asyncio
    async def test_event_path_also_blocks_when_a_position_is_open(self):
        bus = EventBus(fast_mode=True)
        out = Outcomes(bus)
        risk = make_risk(bus)
        await arm_events(risk)
        out.rejected.clear()
        risk.has_open_position = True
        await risk.on_signal_generated(signal_event())
        assert out.approved == [], "event path must not stack positions"
        assert 'Max positions' in out.rejected[0].payload['reason']

    @pytest.mark.asyncio
    async def test_reverse_exit_lets_an_opposite_signal_through(self):
        """
        With `reverse_signal_exit: true` an opposite-direction signal is an
        exit-and-reenter, not a stack: the caller closes the open position
        first (live before gating, backtest at the next bar's open), so the gate
        must allow it.
        """
        bus = EventBus(fast_mode=True)
        out = Outcomes(bus)
        risk = make_risk(bus, reverse_signal_exit=True, sl_cooldown_minutes=0)
        await arm_events(risk)
        out.rejected.clear()
        risk.has_open_position = True
        risk.open_position_direction = 'SELL'
        await risk.on_signal_generated(signal_event(signal='BUY'))
        assert len(out.approved) == 1

    @pytest.mark.asyncio
    async def test_reverse_exit_still_blocks_a_same_direction_stack(self):
        bus = EventBus(fast_mode=True)
        out = Outcomes(bus)
        risk = make_risk(bus, reverse_signal_exit=True, sl_cooldown_minutes=0)
        await arm_events(risk)
        out.rejected.clear()
        risk.has_open_position = True
        risk.open_position_direction = 'BUY'
        await risk.on_signal_generated(signal_event(signal='BUY'))
        assert out.approved == []
        assert 'Max positions' in out.rejected[0].payload['reason']

    @pytest.mark.asyncio
    async def test_reverse_exit_is_off_by_default(self):
        """
        Default False now matches trading_orchestrator.py and every deployed
        instrument YAML. run_skills_backtest.py used to default it to True, so
        an instrument omitting the key got reverse-exit ON in backtest and OFF
        in live.
        """
        assert make_risk().reverse_signal_exit is False

    @pytest.mark.asyncio
    async def test_both_paths_honour_skip_hours(self):
        risk_a = make_risk(skip_hours=[3])
        await arm(risk_a, ts=datetime(2026, 10, 21, 10, 0))
        ctx = await risk_a.execute(live_context(ts=datetime(2026, 10, 21, 3, 0)))
        assert ctx.is_allowed is False

        bus = EventBus(fast_mode=True)
        out = Outcomes(bus)
        risk_b = make_risk(bus, skip_hours=[3])
        await arm_events(risk_b, ts=datetime(2026, 10, 21, 10, 0))
        out.rejected.clear()
        await risk_b.on_signal_generated(
            signal_event(ts=datetime(2026, 10, 21, 3, 0)))
        assert len(out.rejected) == 1

    @pytest.mark.asyncio
    async def test_both_paths_honour_the_sl_cooldown(self):
        t0 = datetime(2026, 10, 21, 10, 0)
        risk_a = make_risk(sl_cooldown_minutes=30)
        await arm(risk_a, ts=t0)
        risk_a.on_position_closed(direction='BUY', close_reason='SL_HIT',
                                  close_time=t0, pnl=-15.0)
        ctx = await risk_a.execute(live_context(ts=t0 + timedelta(minutes=5)))
        assert ctx.is_allowed is False

        bus = EventBus(fast_mode=True)
        out = Outcomes(bus)
        risk_b = make_risk(bus, sl_cooldown_minutes=30)
        await arm_events(risk_b, ts=t0)
        out.rejected.clear()
        risk_b.on_position_closed(direction='BUY', close_reason='SL_HIT',
                                  close_time=t0, pnl=-15.0)
        await risk_b.on_signal_generated(signal_event(ts=t0 + timedelta(minutes=5)))
        assert len(out.rejected) == 1

    @pytest.mark.asyncio
    async def test_the_news_killswitch_now_reaches_the_live_path(self):
        """
        It used to be checked only on the event path, so the live bot ignored it
        entirely.
        """
        class Blocked:
            def is_trading_allowed(self):
                return False, 'high-impact event'

        risk = RiskSkill({'trading_hours': {'enabled': False},
                          'sl_cooldown_minutes': 0, 'initial_capital': 10000},
                         news_killswitch=Blocked())
        await arm(risk)
        ctx = await risk.execute(live_context())
        assert ctx.is_allowed is False
        assert 'News' in ctx.risk_reason

    @pytest.mark.asyncio
    async def test_the_session_filter_now_reaches_the_live_path(self):
        class Closed:
            def is_trading_allowed(self):
                return False, 'outside LONDON/NY'

        risk = RiskSkill({'trading_hours': {'enabled': False},
                          'sl_cooldown_minutes': 0, 'initial_capital': 10000},
                         session_filter=Closed())
        await arm(risk)
        ctx = await risk.execute(live_context())
        assert ctx.is_allowed is False
        assert 'Session' in ctx.risk_reason


class TestDailyLossLimitLiveSequence:

    @pytest.mark.asyncio
    async def test_limit_trips_after_cumulative_losses(self):
        """
        Requires REAL P&L at close. With the old code pnl was always 0.0, so the
        accumulator never moved and this gate could not trip.
        """
        bus = EventBus(fast_mode=True)
        out = Outcomes(bus)
        risk = make_risk(bus, max_daily_loss_usd=100, sl_cooldown_minutes=0)
        t0 = datetime(2026, 10, 21, 10, 0)
        await arm_events(risk, ts=t0)
        out.rejected.clear()
        for i in range(2):
            risk.on_position_closed(direction='BUY', close_reason='SL_HIT',
                                    close_time=t0 + timedelta(minutes=i),
                                    pnl=-60.0)
        await risk.on_signal_generated(signal_event(ts=t0 + timedelta(hours=1)))
        assert len(out.rejected) == 1, "daily loss limit should halt entries"

    @pytest.mark.asyncio
    async def test_zero_pnl_never_trips_the_limit(self):
        """Exactly the production failure: pnl=0.0 accumulates to nothing."""
        bus = EventBus(fast_mode=True)
        out = Outcomes(bus)
        risk = make_risk(bus, max_daily_loss_usd=100, sl_cooldown_minutes=0)
        t0 = datetime(2026, 10, 21, 10, 0)
        await arm_events(risk, ts=t0)
        for i in range(20):
            risk.on_position_closed(direction='BUY', close_reason='SIGNAL',
                                    close_time=t0 + timedelta(minutes=i), pnl=0.0)
        await risk.on_signal_generated(signal_event(ts=t0 + timedelta(hours=2)))
        assert len(out.approved) == 1, "zero P&L leaves the limit inert"

    @pytest.mark.asyncio
    async def test_limit_clears_at_utc_rollover(self):
        bus = EventBus(fast_mode=True)
        out = Outcomes(bus)
        risk = make_risk(bus, max_daily_loss_usd=100, sl_cooldown_minutes=0)
        t0 = datetime(2026, 10, 21, 10, 0)
        await arm_events(risk, ts=t0)
        out.rejected.clear()
        risk.on_position_closed(direction='BUY', close_reason='SL_HIT',
                                close_time=t0, pnl=-150.0)
        await risk.on_signal_generated(signal_event(ts=t0 + timedelta(hours=1)))
        assert len(out.rejected) == 1
        await risk.on_signal_generated(signal_event(ts=t0 + timedelta(days=1)))
        assert len(out.approved) == 1, "new UTC day clears the halt"

    @pytest.mark.asyncio
    async def test_disabled_by_default(self):
        bus = EventBus(fast_mode=True)
        out = Outcomes(bus)
        risk = make_risk(bus, sl_cooldown_minutes=0)
        t0 = datetime(2026, 10, 21, 10, 0)
        await arm_events(risk, ts=t0)
        risk.on_position_closed(direction='BUY', close_reason='SL_HIT',
                                close_time=t0, pnl=-5000.0)
        await risk.on_signal_generated(signal_event(ts=t0 + timedelta(hours=1)))
        assert len(out.approved) == 1


class TestConsecutiveLossBreaker:

    @pytest.mark.asyncio
    async def test_trips_after_n_losses_and_a_win_resets(self):
        bus = EventBus(fast_mode=True)
        out = Outcomes(bus)
        risk = make_risk(bus, max_consecutive_losses=3,
                         consecutive_loss_cooldown_minutes=120,
                         sl_cooldown_minutes=0)
        t0 = datetime(2026, 10, 21, 10, 0)
        await arm_events(risk, ts=t0)
        out.rejected.clear()
        for i in range(3):
            risk.on_position_closed(direction='BUY', close_reason='SL_HIT',
                                    close_time=t0 + timedelta(minutes=i), pnl=-15.0)
        await risk.on_signal_generated(signal_event(ts=t0 + timedelta(minutes=10)))
        assert len(out.rejected) == 1
        # A win resets the counter immediately
        risk.on_position_closed(direction='BUY', close_reason='TP_HIT',
                                close_time=t0 + timedelta(minutes=20), pnl=60.0)
        assert risk.consecutive_losses == 0

    @pytest.mark.asyncio
    async def test_zero_pnl_counts_as_a_win(self):
        """
        `is_loss = pnl < 0`, so the production pnl=0.0 scored every trade a win
        and the breaker could never trip.
        """
        bus = EventBus(fast_mode=True)
        risk = make_risk(bus, max_consecutive_losses=2, sl_cooldown_minutes=0)
        t0 = datetime(2026, 10, 21, 10, 0)
        for i in range(5):
            risk.on_position_closed(direction='BUY', close_reason='SIGNAL',
                                    close_time=t0 + timedelta(minutes=i), pnl=0.0)
        assert risk.consecutive_losses == 0

    @pytest.mark.asyncio
    async def test_disabled_by_default(self):
        bus = EventBus(fast_mode=True)
        out = Outcomes(bus)
        risk = make_risk(bus, sl_cooldown_minutes=0)
        t0 = datetime(2026, 10, 21, 10, 0)
        await arm_events(risk, ts=t0)
        for i in range(10):
            risk.on_position_closed(direction='BUY', close_reason='SL_HIT',
                                    close_time=t0 + timedelta(minutes=i), pnl=-15.0)
        await risk.on_signal_generated(signal_event(ts=t0 + timedelta(minutes=30)))
        assert len(out.approved) == 1
