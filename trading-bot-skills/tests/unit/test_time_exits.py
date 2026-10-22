"""
Unit tests — time-based flattening (CLAUDE.md gotcha 19).

Nothing in the live bot force-closed a position before this. `time_based_exits`
in the YAML is read only by `production_orchestrator.py`, which the live bot
does not run, and `guaranteedStop` is false on every position — so a weekend
gap was uncapped. The confirmed cost is a US100 SELL opened Fri 2026-07-31
20:00:07 UTC with a 28320.1 stop that closed on the Sunday reopen at 28441.7,
121.6 pts past the stop, realised -$153 against an intended -$50.

Three things are pinned here, and the second is the one that makes the fix real
rather than cosmetic:

  1. the clock logic itself, including the `hour >= close_hour` form that makes
     a naive global EOD unusable for US100;
  2. that entries are refused after the flatten moment — otherwise the next
     signal re-opens the position the flatten just closed, and it rides the gap
     anyway (the -$153 position was opened at 20:00, inside its own session);
  3. that the poll loop asks the broker to close and books NOTHING itself, so
     an unknown P&L is never invented as 0.0 (gotchas 22 and 49).
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import orchestrator.main as live_main
from core.time_exits import TimeBasedFlatten, _as_utc
from orchestrator.main import _poll_positions
from skills.risk.risk_skill import RiskSkill

from test_live_poll_loop import FakeCapital, FakeOrchestrator, position

# Real instrument sessions, so the config traps under test are the live ones.
US100_SKIP = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 21, 22, 23]  # trades 13-20
GOLD_SKIP = [0, 1, 2, 3, 4, 5, 6, 7]                                  # trades 08-23

FRI = datetime(2026, 7, 31, tzinfo=timezone.utc)   # the day of the -$153 trade
THU = datetime(2026, 7, 30, tzinfo=timezone.utc)
SAT = datetime(2026, 8, 1, tzinfo=timezone.utc)


def at(day, hour, minute=0):
    return day.replace(hour=hour, minute=minute)


def friday_only(**over):
    cfg = {'enabled': True, 'friday_enabled': True,
           'friday_hour': 20, 'friday_minute': 45}
    cfg.update(over)
    return TimeBasedFlatten(cfg)


# ══════════════════════════════════════════════════════════════════════════
# Part A — the clock
# ══════════════════════════════════════════════════════════════════════════

class TestDisabledByDefault:
    """Deploying this must change nothing until an instrument opts in."""

    @pytest.mark.parametrize('cfg', [None, {}, {'enabled': False},
                                     {'friday_enabled': True, 'friday_hour': 20}])
    def test_never_flattens(self, cfg):
        f = TimeBasedFlatten(cfg)
        assert f.should_flatten(at(FRI, 23))[0] is False
        assert f.blocks_entry(at(FRI, 23))[0] is False
        assert f.flatten_moment(at(FRI, 23)) is None

    def test_enabled_alone_does_nothing(self):
        """`enabled: true` with no time set must not flatten at midnight."""
        f = TimeBasedFlatten({'enabled': True})
        assert f.should_flatten(at(FRI, 0))[0] is False
        assert f.should_flatten(at(FRI, 23, 59))[0] is False

    def test_max_hold_requires_enabled(self):
        f = TimeBasedFlatten({'max_hold_hours': 1})
        assert f.position_exceeded_hold(at(FRI, 10), at(FRI, 20))[0] is False


class TestFridayFlatten:
    def test_before_at_after(self):
        f = friday_only()
        assert f.should_flatten(at(FRI, 20, 44))[0] is False
        assert f.should_flatten(at(FRI, 20, 45))[0] is True   # inclusive
        assert f.should_flatten(at(FRI, 20, 46))[0] is True

    def test_other_weekdays_untouched(self):
        """Friday-only is the minimal fix: it must not alter Mon-Thu at all."""
        f = friday_only()
        for day in range(26, 31):           # Sun 26 Jul .. Thu 30 Jul 2026
            d = datetime(2026, 7, day, 23, 59, tzinfo=timezone.utc)
            if d.weekday() == 4:
                continue
            assert f.should_flatten(d)[0] is False, d
            assert f.blocks_entry(d)[0] is False, d

    def test_saturday_not_blocked_by_fridays_rule(self):
        assert friday_only().should_flatten(at(SAT, 2))[0] is False

    def test_the_minus_153_position_would_have_been_flattened(self):
        """
        SELL opened Fri 2026-07-31 20:00:07 UTC, carried to the Sunday reopen.
        A 20:45 Friday flatten closes it ~45 min after it opened, on the Friday.
        """
        opened = datetime(2026, 7, 31, 20, 0, 7, tzinfo=timezone.utc)
        f = friday_only()
        assert f.should_flatten(opened)[0] is False              # still open at entry
        assert f.should_flatten(opened + timedelta(minutes=45))[0] is True

    def test_reason_names_the_moment(self):
        due, why = friday_only().should_flatten(at(FRI, 21))
        assert due and 'Friday flatten' in why and '20:45' in why


class TestDailyFlatten:
    def test_applies_every_day(self):
        f = TimeBasedFlatten({'enabled': True, 'daily_enabled': True, 'daily_hour': 16})
        assert f.should_flatten(at(THU, 15, 59))[0] is False
        assert f.should_flatten(at(THU, 16))[0] is True
        assert f.should_flatten(at(FRI, 16))[0] is True

    def test_friday_overrides_daily(self):
        f = TimeBasedFlatten({'enabled': True,
                              'daily_enabled': True, 'daily_hour': 16,
                              'friday_enabled': True, 'friday_hour': 20, 'friday_minute': 45})
        assert f.should_flatten(at(THU, 16))[0] is True          # daily on Thursday
        assert f.should_flatten(at(FRI, 16))[0] is False         # Friday waits for 20:45
        assert f.should_flatten(at(FRI, 20, 45))[0] is True

    def test_not_the_hour_ge_close_hour_form(self):
        """
        production_orchestrator uses `current_time.hour >= close_hour`, which is
        true for every later hour of every day. The regression that form causes
        on US100: a position opened at 17:00 is flattened the instant it opens.
        Here 16:00 is a moment on the day, so 15:59 is still open.
        """
        f = TimeBasedFlatten({'enabled': True, 'daily_enabled': True,
                              'daily_hour': 16, 'daily_minute': 30})
        assert f.should_flatten(at(THU, 16, 0))[0] is False      # hour matches, minute does not
        assert f.should_flatten(at(THU, 16, 30))[0] is True


class TestTimezoneHandling:
    def test_naive_is_read_as_utc(self):
        f = friday_only()
        assert f.should_flatten(datetime(2026, 7, 31, 20, 50))[0] is True
        assert f.should_flatten(datetime(2026, 7, 31, 20, 40))[0] is False

    def test_non_utc_is_converted_not_truncated(self):
        """
        22:30 in UTC+2 is 20:30 UTC — before a 20:45 flatten. Reading the local
        hour instead of converting is the production_orchestrator bug
        (`datetime.now()` against a UTC config hour).
        """
        plus2 = timezone(timedelta(hours=2))
        assert friday_only().should_flatten(datetime(2026, 7, 31, 22, 30, tzinfo=plus2))[0] is False
        assert friday_only().should_flatten(datetime(2026, 7, 31, 22, 50, tzinfo=plus2))[0] is True

    def test_pandas_timestamp_accepted(self):
        pd = pytest.importorskip('pandas')
        assert friday_only().should_flatten(pd.Timestamp('2026-07-31 20:50'))[0] is True

    @pytest.mark.parametrize('raw,expect_hour', [
        ('2026-07-31T20:00:07', 20),
        ('2026-07-31T20:00:07.123', 20),
        ('2026-07-31T20:00:07Z', 20),
        ('2026-07-31 20:00:07', 20),
    ])
    def test_broker_timestamp_strings(self, raw, expect_hour):
        """createdDateUTC arrives in several shapes; all must parse."""
        parsed = _as_utc(raw)
        assert parsed is not None and parsed.hour == expect_hour

    @pytest.mark.parametrize('junk', [None, '', '   ', 'not-a-date', 42, object()])
    def test_unreadable_values_are_none_not_a_guess(self, junk):
        assert _as_utc(junk) is None


class TestMaxHold:
    def test_disabled_at_zero(self):
        f = friday_only(max_hold_hours=0)
        assert f.position_exceeded_hold(at(FRI, 1), at(FRI, 23))[0] is False

    def test_triggers_at_the_boundary(self):
        f = friday_only(max_hold_hours=4)
        opened = at(THU, 10)
        assert f.position_exceeded_hold(opened, at(THU, 13, 59))[0] is False
        assert f.position_exceeded_hold(opened, at(THU, 14))[0] is True

    def test_unknown_open_time_never_closes(self):
        """A position whose age cannot be read must not be closed on a guess."""
        f = friday_only(max_hold_hours=1)
        for bad in (None, '', 'garbage'):
            assert f.position_exceeded_hold(bad, at(FRI, 23))[0] is False

    def test_independent_of_the_flatten_clock(self):
        """max_hold applies on days that have no flatten time at all."""
        f = TimeBasedFlatten({'enabled': True, 'max_hold_hours': 2})
        assert f.should_flatten(at(THU, 23))[0] is False
        assert f.position_exceeded_hold(at(THU, 10), at(THU, 13))[0] is True


class TestEntryBlocking:
    def test_blocks_after_the_moment(self):
        f = friday_only()
        assert f.blocks_entry(at(FRI, 20, 44))[0] is False
        assert f.blocks_entry(at(FRI, 20, 45))[0] is True

    def test_opt_out_leaves_entries_open(self):
        f = friday_only(block_entries_after_flatten=False)
        assert f.should_flatten(at(FRI, 21))[0] is True          # still flattens
        assert f.blocks_entry(at(FRI, 21))[0] is False           # but re-entry allowed


class TestValidation:
    def test_sound_config_is_silent(self):
        assert friday_only().validate(US100_SKIP) == []

    def test_catches_the_us100_trap(self):
        """
        The naive fix prompt 2 warns about: a global eod_hour 16 against a
        13:00-20:59 session. Hours 17-20 are still entry-allowed.
        """
        f = TimeBasedFlatten({'enabled': True, 'daily_enabled': True, 'daily_hour': 16})
        problems = f.validate(US100_SKIP)
        assert len(problems) == 1
        assert '17-20' in problems[0]

    def test_churn_is_named_when_blocking_is_off(self):
        f = TimeBasedFlatten({'enabled': True, 'daily_enabled': True,
                              'daily_hour': 16, 'block_entries_after_flatten': False})
        assert 'churn' in f.validate(US100_SKIP)[0]

    def test_catches_golds_documented_eod_inconsistency(self):
        """GOLD's strategy says EOD 16:00 but skip_hours only blocks 00-07."""
        f = TimeBasedFlatten({'enabled': True, 'daily_enabled': True, 'daily_hour': 16})
        assert '17-23' in f.validate(GOLD_SKIP)[0]

    def test_enabled_with_no_time(self):
        assert 'nothing will ever be flattened' in TimeBasedFlatten({'enabled': True}).validate([])[0]

    @pytest.mark.parametrize('hour', [-1, 24, 99])
    def test_out_of_range_hour(self, hour):
        f = TimeBasedFlatten({'enabled': True, 'friday_enabled': True, 'friday_hour': hour})
        assert any('outside 0-23' in p for p in f.validate([]))

    def test_disabled_never_complains(self):
        assert TimeBasedFlatten({'daily_enabled': True, 'daily_hour': 16}).validate(US100_SKIP) == []

    def test_log_validation_warns(self, caplog):
        import logging
        f = TimeBasedFlatten({'enabled': True, 'daily_enabled': True, 'daily_hour': 16})
        with caplog.at_level(logging.WARNING):
            problems = f.log_validation(US100_SKIP, epic='US100')
        assert problems and 'US100' in caplog.text


class TestDescribe:
    def test_disabled(self):
        assert 'DISABLED' in TimeBasedFlatten({}).describe()

    def test_friday_and_blocking_shown(self):
        d = friday_only().describe()
        assert 'Friday 20:45' in d and 'entries blocked after' in d

    def test_blocking_off_is_visible(self):
        assert 'entries NOT blocked' in friday_only(block_entries_after_flatten=False).describe()


# ══════════════════════════════════════════════════════════════════════════
# Part B — the RiskSkill gate (the half that makes the flatten real)
# ══════════════════════════════════════════════════════════════════════════

def risk_with(time_exits=None, **over):
    cfg = {
        'skip_hours': US100_SKIP,
        'startup_flip_gate': False,
        'trading_hours': {'enabled': False},
        'sl_cooldown_minutes': 0,
        'tp_cooldown_minutes': 0,
    }
    cfg.update(over)
    if time_exits is not None:
        cfg['time_exits'] = time_exits
    return RiskSkill(cfg)


FRIDAY_CFG = {'enabled': True, 'friday_enabled': True,
              'friday_hour': 20, 'friday_minute': 45}


class TestRiskGate:
    def test_entry_allowed_before_the_flatten(self):
        allowed, reason = risk_with(FRIDAY_CFG)._evaluate_entry_gates('BUY', at(FRI, 20, 30))
        assert allowed, reason

    def test_entry_refused_after_the_flatten(self):
        """
        This is the gap-closing assertion: at 20:50 on a Friday the session is
        still open (hour 20 is allowed) but the flatten has run, so re-entry
        must be refused. Without it the -$153 position simply re-opens.
        """
        allowed, reason = risk_with(FRIDAY_CFG)._evaluate_entry_gates('BUY', at(FRI, 20, 50))
        assert not allowed
        assert 'Flatten window' in reason

    def test_unconfigured_risk_skill_is_unchanged(self):
        """Every instrument without `time_exits` must behave exactly as before."""
        allowed, reason = risk_with(None)._evaluate_entry_gates('BUY', at(FRI, 20, 50))
        assert allowed, reason

    def test_other_weekdays_unaffected(self):
        allowed, _ = risk_with(FRIDAY_CFG)._evaluate_entry_gates('BUY', at(THU, 20, 50))
        assert allowed

    def test_skip_hours_still_wins_first(self):
        """The cheaper gate stays ahead of it; the reason must name skip-hours."""
        allowed, reason = risk_with(FRIDAY_CFG)._evaluate_entry_gates('BUY', at(FRI, 22))
        assert not allowed and 'Skip hour' in reason

    def test_gate_is_shared_with_the_poll_loop_object(self):
        """
        Not a behaviour test — an identity one. main.py pulls this very object
        off the risk skill, which is what makes it impossible to configure the
        flatten moment and the entry block inconsistently.
        """
        risk = risk_with(FRIDAY_CFG)
        assert risk.time_exits.flatten_moment(at(FRI, 12)) == at(FRI, 20, 45)


# ══════════════════════════════════════════════════════════════════════════
# Part C — the poll loop actually closing positions
# ══════════════════════════════════════════════════════════════════════════

class FakeExecution:
    def __init__(self, results=None):
        self.closed = []
        self.results = list(results or [])

    async def close_position(self, deal_id):
        self.closed.append(deal_id)
        if self.results:
            return self.results.pop(0)
        return True


class FakeExecutionRaises:
    def __init__(self):
        self.closed = []

    async def close_position(self, deal_id):
        self.closed.append(deal_id)
        raise RuntimeError('broker 500')


@pytest.fixture
def frozen(monkeypatch):
    """Freeze `datetime.now(tz)` inside main.py's poll loop."""
    holder = {'now': at(FRI, 20, 50)}

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return holder['now']

    monkeypatch.setattr(live_main, 'datetime', Frozen)
    return holder


@pytest.fixture
def instant_sleep(monkeypatch):
    real = asyncio.sleep

    async def nap(_d=0):
        await real(0)

    monkeypatch.setattr(live_main.asyncio, 'sleep', nap)
    return real


async def run_until(capital, orch, flatten, until, epic='US100',
                    interval=61, max_wait=2.0):
    """interval=61 makes `60 // interval == 0`, so reconcile runs every cycle."""
    task = asyncio.create_task(
        _poll_positions(capital, orch, epic, interval=interval, flatten=flatten))
    loop = asyncio.get_event_loop()
    deadline = loop.time() + max_wait
    try:
        while loop.time() < deadline:
            await asyncio.sleep(0)
            if until():
                break
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def orch_with_execution(execution):
    orch = FakeOrchestrator()
    orch.skills['execution'] = execution
    return orch


@pytest.mark.asyncio
class TestPollLoopFlatten:

    async def test_closes_the_open_position_after_the_moment(self, frozen, instant_sleep):
        ex = FakeExecution()
        orch = orch_with_execution(ex)
        cap = FakeCapital(positions_script=[[position(deal_id='D1')]])
        await run_until(cap, orch, friday_only(), lambda: bool(ex.closed))
        assert ex.closed == ['D1']

    async def test_does_nothing_before_the_moment(self, frozen, instant_sleep):
        frozen['now'] = at(FRI, 20, 30)
        ex = FakeExecution()
        orch = orch_with_execution(ex)
        cap = FakeCapital(positions_script=[[position(deal_id='D1')]])
        await run_until(cap, orch, friday_only(),
                        lambda: cap.positions_calls > 3, max_wait=0.5)
        assert ex.closed == []

    async def test_disabled_flatten_never_closes(self, frozen, instant_sleep):
        ex = FakeExecution()
        orch = orch_with_execution(ex)
        cap = FakeCapital(positions_script=[[position(deal_id='D1')]])
        await run_until(cap, orch, TimeBasedFlatten({}),
                        lambda: cap.positions_calls > 3, max_wait=0.5)
        assert ex.closed == []

    async def test_asks_once_not_every_poll(self, frozen, instant_sleep):
        """
        A close takes a few polls to confirm. Re-sending it every 10s would
        spam the broker with duplicate closes.
        """
        ex = FakeExecution()
        orch = orch_with_execution(ex)
        cap = FakeCapital(positions_script=[[position(deal_id='D1')]])
        await run_until(cap, orch, friday_only(),
                        lambda: cap.positions_calls > 5, max_wait=1.0)
        assert ex.closed == ['D1']

    async def test_refused_close_is_retried(self, frozen, instant_sleep):
        """
        A refused close must not be recorded as done — the position is still
        live and still exposed to the gap.
        """
        ex = FakeExecution(results=[False, True])
        orch = orch_with_execution(ex)
        cap = FakeCapital(positions_script=[[position(deal_id='D1')]])
        await run_until(cap, orch, friday_only(), lambda: len(ex.closed) >= 2)
        assert ex.closed == ['D1', 'D1']

    async def test_raising_close_is_retried_and_does_not_kill_the_loop(
            self, frozen, instant_sleep):
        ex = FakeExecutionRaises()
        orch = orch_with_execution(ex)
        cap = FakeCapital(positions_script=[[position(deal_id='D1')]])
        await run_until(cap, orch, friday_only(), lambda: len(ex.closed) >= 2)
        assert len(ex.closed) >= 2

    async def test_books_nothing_itself(self, frozen, instant_sleep):
        """
        The flatten must NOT call on_position_closed. Booking here would have to
        invent a P&L, and 0.0 scores as a win and leaves the daily-loss
        accumulator at zero (gotchas 22, 49). The next activity poll books the
        close with the real figure from get_realised_pnl.
        """
        ex = FakeExecution()
        orch = orch_with_execution(ex)
        cap = FakeCapital(positions_script=[[position(deal_id='D1')]])
        await run_until(cap, orch, friday_only(), lambda: bool(ex.closed))
        assert orch.closes == []

    async def test_flattens_every_open_position(self, frozen, instant_sleep):
        ex = FakeExecution()
        orch = orch_with_execution(ex)
        cap = FakeCapital(positions_script=[[position(deal_id='D1'),
                                             position(deal_id='D2')]])
        await run_until(cap, orch, friday_only(), lambda: len(ex.closed) >= 2)
        assert sorted(ex.closed) == ['D1', 'D2']

    async def test_max_hold_closes_outside_any_flatten_window(self, frozen, instant_sleep):
        """Thursday, no flatten time — but the position is 5h old."""
        frozen['now'] = at(THU, 18)
        ex = FakeExecution()
        orch = orch_with_execution(ex)
        cap = FakeCapital(positions_script=[
            [position(deal_id='D1', created='2026-07-30T13:00:00')]])
        flatten = TimeBasedFlatten({'enabled': True, 'max_hold_hours': 4})
        await run_until(cap, orch, flatten, lambda: bool(ex.closed))
        assert ex.closed == ['D1']

    async def test_young_position_survives_max_hold(self, frozen, instant_sleep):
        frozen['now'] = at(THU, 14)
        ex = FakeExecution()
        orch = orch_with_execution(ex)
        cap = FakeCapital(positions_script=[
            [position(deal_id='D1', created='2026-07-30T13:00:00')]])
        flatten = TimeBasedFlatten({'enabled': True, 'max_hold_hours': 4})
        await run_until(cap, orch, flatten,
                        lambda: cap.positions_calls > 3, max_wait=0.5)
        assert ex.closed == []

    async def test_missing_execution_skill_does_not_crash(self, frozen, instant_sleep):
        orch = FakeOrchestrator()          # no execution skill registered
        cap = FakeCapital(positions_script=[[position(deal_id='D1')]])
        await run_until(cap, orch, friday_only(),
                        lambda: cap.positions_calls > 3, max_wait=0.5)
        assert orch.closes == []

    async def test_defaults_to_the_risk_skills_object(self, frozen, instant_sleep):
        """
        With no `flatten=` passed, the loop must pick up the risk skill's
        instance — this is the production wiring.
        """
        ex = FakeExecution()
        orch = orch_with_execution(ex)
        orch.skills['risk'] = risk_with(FRIDAY_CFG)
        cap = FakeCapital(positions_script=[[position(deal_id='D1')]])
        task = asyncio.create_task(
            _poll_positions(cap, orch, 'US100', interval=61))
        loop = asyncio.get_event_loop()
        deadline = loop.time() + 2.0
        try:
            while loop.time() < deadline and not ex.closed:
                await asyncio.sleep(0)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert ex.closed == ['D1']


# ══════════════════════════════════════════════════════════════════════════
# Part D — error paths. The validator is the safety net for the config traps,
# so its own branches are worth pinning.
# ══════════════════════════════════════════════════════════════════════════

class TestErrorPaths:
    def test_unreadable_now_never_flattens(self):
        due, why = friday_only().should_flatten('not-a-date')
        assert due is False and 'unreadable' in why

    def test_unreadable_now_never_blocks_entries(self):
        assert friday_only().blocks_entry('not-a-date')[0] is False

    def test_flatten_moment_of_junk_is_none(self):
        assert friday_only().flatten_moment('garbage') is None

    def test_to_pydatetime_that_raises_is_not_a_crash(self):
        class Hostile:
            def to_pydatetime(self):
                raise ValueError('nope')
        assert _as_utc(Hostile()) is None
        assert friday_only().should_flatten(Hostile())[0] is False

    def test_enabled_hour_unset_is_reported(self):
        f = TimeBasedFlatten({'enabled': True, 'friday_enabled': True})
        assert any('friday_hour is unset' in p for p in f.validate([]))

    def test_minute_out_of_range_is_reported(self):
        f = TimeBasedFlatten({'enabled': True, 'friday_enabled': True,
                              'friday_hour': 20, 'friday_minute': 99})
        assert any('outside 0-59' in p for p in f.validate([]))

    def test_describe_covers_daily_and_max_hold(self):
        d = TimeBasedFlatten({'enabled': True, 'daily_enabled': True,
                              'daily_hour': 16, 'daily_minute': 30,
                              'max_hold_hours': 6}).describe()
        assert 'daily 16:30' in d and 'max hold 6h' in d

    def test_describe_enabled_without_a_time(self):
        assert 'no time set' in TimeBasedFlatten({'enabled': True}).describe()
