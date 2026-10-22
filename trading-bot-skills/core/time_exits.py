"""
Time-based position flattening for the LIVE path.

Why this module exists
----------------------
Nothing in the live bot ever force-closed a position. ``time_based_exits``
(``eod_hour`` / ``eod_enabled``) in the YAML is read only by
``orchestrator/production_orchestrator.py``, which the live bot does not run
(CLAUDE.md gotcha 19). The live path is ``bot_control_api.py`` →
``orchestrator/main.py`` → ``TradingOrchestrator``, and its only exits are
SL / TP / tick-exit. ``guaranteedStop`` is false on every position, so a
weekend gap was uncapped:

    US100 dealId 00384627-...-000083765fd6, SELL 1 @ 28288.7 opened
    Fri 2026-07-31 20:00:07 UTC with a stop at 28320.1, closed Sun
    2026-08-02 22:00:10 UTC at 28441.7 on the reopen gap — 121.6 pts
    *past* the stop, realised -$153 against an intended -$50.

Why a new config key instead of reusing ``time_based_exits``
------------------------------------------------------------
The base config carries ``eod_hour: 16`` with ``eod_enabled: true``. Honouring
that in the live path would flatten every US100 position from 17:00 onward —
US100's entire allowed session is 13:00-20:59 UTC, so it would open and
immediately re-flatten all afternoon. GOLD has the same problem for a different
reason: its ``skip_hours`` is only ``[0..7]``, so it may enter at 17:00-23:00,
well after the documented 16:00 EOD.

So this reads ``risk.time_exits`` and is **OFF unless a config explicitly turns
it on**. Deploying it changes nothing until an instrument opts in.
``time_based_exits`` stays dead; do not wire it in.

Both halves are required
------------------------
Flattening alone does not cap the gap. If entries are still allowed after the
flatten moment, the next signal re-opens a position and carries it over the
weekend regardless — the US100 loss above was opened at 20:00 on the Friday,
inside its own allowed session. So:

  * :meth:`should_flatten` drives the close in ``main.py``'s poll loop, and
  * :meth:`blocks_entry` is a gate in ``RiskSkill._evaluate_entry_gates``.

Both read the same moment, so they cannot drift apart.

Not simulated by the backtester
-------------------------------
``run_skills_backtest.py`` models SL/TP exits only. Enabling a flatten makes
live diverge from backtest by exactly the trades the flatten touches.
"""
from datetime import datetime, time, timedelta, timezone
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

FRIDAY = 4


def _as_utc(value) -> Optional[datetime]:
    """
    Coerce a datetime-ish value to an aware UTC datetime.

    Accepts datetime, pandas.Timestamp, and the broker's ISO strings
    (``createdDateUTC`` arrives as e.g. ``2026-07-31T20:00:07.123``, sometimes
    with a trailing ``Z``). A naive value is assumed to already be UTC — every
    clock in this system is UTC, and guessing local time here is how the
    production orchestrator's ``datetime.now()`` ended up comparing a local
    hour against a UTC config hour.

    Returns None when the value cannot be read as a time, so callers can treat
    "unknown" as "do not act" rather than acting on a wrong number.
    """
    if value is None:
        return None

    # pandas.Timestamp and anything else offering .to_pydatetime()
    to_py = getattr(value, 'to_pydatetime', None)
    if callable(to_py):
        try:
            value = to_py()
        except Exception:
            return None

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.endswith('Z'):
            raw = raw[:-1] + '+00:00'
        try:
            value = datetime.fromisoformat(raw)
        except ValueError:
            # Capital.com also emits "YYYY-MM-DDTHH:MM:SS.mmm" variants that
            # fromisoformat handles, and occasionally a space separator.
            try:
                value = datetime.fromisoformat(raw.replace(' ', 'T'))
            except ValueError:
                return None

    if not isinstance(value, datetime):
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class TimeBasedFlatten:
    """
    Decides when an open position must be force-closed on the clock, and when
    entries must stop so the flatten is not immediately undone.

    Config (``risk.time_exits``) — every switch defaults OFF::

        risk:
          time_exits:
            enabled: true              # master switch; nothing happens without it
            friday_enabled: true       # weekend-gap cap (the confirmed loss)
            friday_hour: 20            # UTC
            friday_minute: 45
            daily_enabled: false       # every-day flatten (a strategy change)
            daily_hour: 16
            daily_minute: 0
            max_hold_hours: 0          # 0 = disabled
            block_entries_after_flatten: true

    All times are UTC. ``friday_*`` overrides ``daily_*`` on Fridays; if only
    ``friday_enabled`` is set, the other four weekdays are untouched.
    """

    def __init__(self, config: Optional[Dict] = None):
        cfg = config or {}
        self.enabled = bool(cfg.get('enabled', False))

        self.daily_enabled = bool(cfg.get('daily_enabled', False))
        self.daily_hour = cfg.get('daily_hour')
        self.daily_minute = int(cfg.get('daily_minute') or 0)

        self.friday_enabled = bool(cfg.get('friday_enabled', False))
        self.friday_hour = cfg.get('friday_hour')
        self.friday_minute = int(cfg.get('friday_minute') or 0)

        self.max_hold_hours = float(cfg.get('max_hold_hours') or 0)
        self.block_entries_after_flatten = bool(
            cfg.get('block_entries_after_flatten', True)
        )

    # ── internals ────────────────────────────────────────────────────────────

    def _time_for_day(self, now: datetime) -> Optional[Tuple[time, str]]:
        """The flatten clock-time that applies on ``now``'s weekday, if any."""
        if now.weekday() == FRIDAY and self.friday_enabled and self.friday_hour is not None:
            return time(int(self.friday_hour), self.friday_minute), 'Friday flatten'
        if self.daily_enabled and self.daily_hour is not None:
            return time(int(self.daily_hour), self.daily_minute), 'EOD flatten'
        return None

    def flatten_moment(self, now) -> Optional[datetime]:
        """
        The exact UTC instant on ``now``'s calendar day at which positions must
        be flat, or None if no flatten applies to that day.
        """
        if not self.enabled:
            return None
        now = _as_utc(now)
        if now is None:
            return None
        resolved = self._time_for_day(now)
        if resolved is None:
            return None
        clock, _ = resolved
        return now.replace(
            hour=clock.hour, minute=clock.minute,
            second=0, microsecond=0,
        )

    # ── decisions ────────────────────────────────────────────────────────────

    def should_flatten(self, now) -> Tuple[bool, str]:
        """
        True once the day's flatten moment has passed.

        Deliberately a ">=" against a moment on the *same day* rather than the
        production orchestrator's ``hour >= close_hour``: that form is true for
        every later hour of every day, which is what makes a 16:00 setting
        close US100 positions all afternoon.
        """
        now_utc = _as_utc(now)
        if now_utc is None:
            return False, 'unreadable timestamp'
        moment = self.flatten_moment(now_utc)
        if moment is None:
            return False, 'no flatten configured for this day'
        if now_utc < moment:
            return False, f'before flatten at {moment:%H:%M} UTC'
        label = self._time_for_day(now_utc)[1]
        return True, f'{label} {moment:%H:%M} UTC'

    def blocks_entry(self, now) -> Tuple[bool, str]:
        """
        True when a new entry must be refused because the day's flatten moment
        has passed. Without this the flatten is cosmetic — the next signal
        re-opens the position it just closed.
        """
        if not self.block_entries_after_flatten:
            return False, ''
        due, reason = self.should_flatten(now)
        if not due:
            return False, ''
        return True, f'past {reason}'

    def position_exceeded_hold(self, opened_at, now) -> Tuple[bool, str]:
        """
        True when a single position has been open longer than
        ``max_hold_hours``. Independent of the flatten clock.

        An unreadable or missing ``opened_at`` returns False: a position whose
        age is unknown must not be closed on a guess.
        """
        if not self.enabled or self.max_hold_hours <= 0:
            return False, ''
        opened = _as_utc(opened_at)
        now_utc = _as_utc(now)
        if opened is None or now_utc is None:
            return False, ''
        held = now_utc - opened
        if held < timedelta(hours=self.max_hold_hours):
            return False, ''
        hours = held.total_seconds() / 3600
        return True, f'max hold {hours:.1f}h >= {self.max_hold_hours:g}h'

    # ── configuration sanity ─────────────────────────────────────────────────

    def validate(self, skip_hours: Optional[List[int]] = None) -> List[str]:
        """
        Report configurations that would misbehave, given the instrument's
        ``skip_hours``. Returns human-readable problems, empty when sound.

        The check that matters: a flatten time with allowed entry hours still
        after it. With ``block_entries_after_flatten`` off that is a churn loop
        (open → flatten → open → flatten); with it on it silently truncates the
        trading session, which is a strategy change the operator should make
        deliberately rather than discover.
        """
        if not self.enabled:
            return []

        problems: List[str] = []

        if not self.daily_enabled and not self.friday_enabled:
            problems.append(
                "time_exits.enabled is true but neither daily_enabled nor "
                "friday_enabled is set — nothing will ever be flattened"
            )

        for label, on, hour, minute in (
            ('daily', self.daily_enabled, self.daily_hour, self.daily_minute),
            ('friday', self.friday_enabled, self.friday_hour, self.friday_minute),
        ):
            if not on:
                continue
            if hour is None:
                problems.append(f"time_exits.{label}_enabled is true but {label}_hour is unset")
                continue
            if not 0 <= int(hour) <= 23:
                problems.append(f"time_exits.{label}_hour={hour} is outside 0-23")
            if not 0 <= minute <= 59:
                problems.append(f"time_exits.{label}_minute={minute} is outside 0-59")

        allowed = [h for h in range(24) if h not in set(skip_hours or [])]

        for label, on, hour in (
            ('daily', self.daily_enabled, self.daily_hour),
            ('friday', self.friday_enabled, self.friday_hour),
        ):
            if not on or hour is None or not 0 <= int(hour) <= 23:
                continue
            after = [h for h in allowed if h > int(hour)]
            if not after:
                continue
            when = ' on Fridays' if label == 'friday' else ''
            if self.block_entries_after_flatten:
                problems.append(
                    f"time_exits.{label}_hour={int(hour):02d} truncates the session"
                    f"{when}: hours {after[0]:02d}-{after[-1]:02d} UTC are allowed by "
                    f"skip_hours but entries will be blocked after the flatten"
                )
            else:
                problems.append(
                    f"time_exits.{label}_hour={int(hour):02d} will churn{when}: hours "
                    f"{after[0]:02d}-{after[-1]:02d} UTC still allow entries and "
                    f"block_entries_after_flatten is false, so positions will be "
                    f"re-opened and re-flattened"
                )

        return problems

    def log_validation(self, skip_hours: Optional[List[int]] = None, epic: str = '') -> List[str]:
        """Run :meth:`validate` and log each problem at WARNING. Returns them."""
        problems = self.validate(skip_hours)
        for p in problems:
            logger.warning(f"⚠️ [{epic or 'time_exits'}] {p}")
        return problems

    def describe(self) -> str:
        """One-line summary for the startup log."""
        if not self.enabled:
            return 'time-based flatten: DISABLED'
        parts = []
        if self.friday_enabled and self.friday_hour is not None:
            parts.append(f"Friday {int(self.friday_hour):02d}:{self.friday_minute:02d}")
        if self.daily_enabled and self.daily_hour is not None:
            parts.append(f"daily {int(self.daily_hour):02d}:{self.daily_minute:02d}")
        if self.max_hold_hours > 0:
            parts.append(f"max hold {self.max_hold_hours:g}h")
        if not parts:
            return 'time-based flatten: enabled but no time set'
        gate = 'entries blocked after' if self.block_entries_after_flatten else 'entries NOT blocked'
        return f"time-based flatten: {', '.join(parts)} UTC ({gate})"
