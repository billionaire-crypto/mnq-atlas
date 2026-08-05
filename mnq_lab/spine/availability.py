"""Canonical per-session structural availability of an outcome window.

The D32 defect: ``TimeModel.outcome_window_fits_rth`` compares ``tau + horizon``
against a single global ``time.rth_end_ct`` of 15:00 CT and takes no session
argument, so a scheduled early close, a session with no scheduled RTH, a
registered interruption and a genuinely missing bar all collapse onto one fixed
boundary. A structurally unavailable timestamp was then charged against
completion as missing data.

This module decides availability from the accepted calendar instead. It lives in
``spine`` because ``outcomes`` must not import ``conditioners``.

Contract:

- exclusion is tested BEFORE any schedule arithmetic (D33);
- the outcome window is half-open ``[tau, tau + horizon)``;
- available requires ``tau + horizon <= scheduled close``, equality AVAILABLE,
  which reproduces the v1 rule exactly on a full 15:00 session;
- an interruption ``[start, end)`` blocks the window iff the half-open intervals
  intersect, so a window ending exactly at ``start`` and one beginning exactly at
  ``end`` both remain available;
- wall-clock semantics are preserved: trading time is never compressed across an
  interruption and no later bar is substituted for a missing scheduled timestamp;
- there is no fallback close, no inference from observed bars, no mutable global
  calendar and no per-row filesystem access.

Everything fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType
from typing import Iterable

from mnq_lab import SpineError
from mnq_lab.constants import load_constants
from mnq_lab.spine.accepted_calendar import (
    CALENDAR_SHA256,
    CALENDAR_VERSION,
    CalendarRow,
    load_accepted_calendar,
)

__all__ = [
    "AVAILABILITY_CONTRACT_VERSION",
    "CANONICAL_TIMEZONE",
    "EXCLUSION_REASONS",
    "INTERRUPTION_REASONS",
    "SCHEDULED_RTH_STATUSES",
    "UNAVAILABILITY_REASONS",
    "AvailabilityDecision",
    "SessionExclusion",
    "SessionSchedule",
    "SessionScheduleTable",
    "StructuralInterruption",
    "build_session_schedule_table",
    "load_session_schedule_table",
    "outcome_window_structurally_available",
]

AVAILABILITY_CONTRACT_VERSION = "session-availability-v1"
CANONICAL_TIMEZONE = "America/Chicago"

SCHEDULED_RTH_STATUSES = (
    "full_rth",
    "shortened_rth",
    "no_scheduled_rth",
    "full_exchange_holiday",
)
INTERRUPTION_REASONS = ("registered_interruption",)
EXCLUSION_REASONS = ("excluded_unresolved_official_interruption",)

REASON_NOT_APPLICABLE = "not_applicable"
REASON_SCHEDULED_CLOSE = "scheduled_close"
REASON_NO_SCHEDULED_RTH = "no_scheduled_rth"
REASON_REGISTERED_INTERRUPTION = "registered_interruption"

# Canonical order: available first, then the structural reasons in the order the
# decision function evaluates them.
UNAVAILABILITY_REASONS = (
    REASON_NOT_APPLICABLE,
    REASON_NO_SCHEDULED_RTH,
    REASON_SCHEDULED_CLOSE,
    REASON_REGISTERED_INTERRUPTION,
)

_NO_RTH_STATUSES = frozenset({"no_scheduled_rth", "full_exchange_holiday"})


def _require_int(value, name: str) -> int:
    if type(value) is not int:
        raise SpineError(f"{name} must be a built-in int, got {type(value).__name__}")
    return value


def _require_minute(value, name: str) -> int:
    minute = _require_int(value, name)
    if not 0 <= minute <= 1440:
        raise SpineError(f"{name} must be a minute of day in [0, 1440], got {minute}")
    return minute


def _parse_ct_minute(text: str, name: str) -> int:
    if not isinstance(text, str) or len(text) != 5 or text[2] != ":":
        raise SpineError(f"{name} must be 'HH:MM', got {text!r}")
    try:
        hour, minute = int(text[:2]), int(text[3:])
    except ValueError as exc:
        raise SpineError(f"{name} is not a valid clock time: {text!r}") from exc
    if not (0 <= hour <= 24 and 0 <= minute < 60):
        raise SpineError(f"{name} is out of range: {text!r}")
    return hour * 60 + minute


@dataclass(frozen=True)
class StructuralInterruption:
    """A registered temporary halt, with authoritative boundaries.

    Half-open ``[start_ct_minute, end_ct_minute)``. Empty and reversed intervals
    are rejected: an interruption with no duration is not evidence of anything.
    """

    start_ct_minute: int
    end_ct_minute: int
    reason: str
    source_id: str

    def __post_init__(self) -> None:
        start = _require_minute(self.start_ct_minute, "start_ct_minute")
        end = _require_minute(self.end_ct_minute, "end_ct_minute")
        if end <= start:
            raise SpineError(
                f"interruption must satisfy start < end, got [{start}, {end})"
            )
        if self.reason not in INTERRUPTION_REASONS:
            raise SpineError(f"undeclared interruption reason {self.reason!r}")
        if not isinstance(self.source_id, str) or not self.source_id:
            raise SpineError("interruption source_id must be a nonempty string")


@dataclass(frozen=True)
class SessionExclusion:
    """A whole session removed from the population (D33).

    Used when an official interruption is established but its exact CME/MNQ
    boundaries are not. The session leaves the population entirely rather than
    being classified intraday on unsourced timestamps.
    """

    session_id: int
    reason: str
    source_id: str
    recorded_by_ruling: str

    def __post_init__(self) -> None:
        _require_int(self.session_id, "session_id")
        if self.reason not in EXCLUSION_REASONS:
            raise SpineError(f"undeclared exclusion reason {self.reason!r}")
        for name in ("source_id", "recorded_by_ruling"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise SpineError(f"exclusion {name} must be a nonempty string")


@dataclass(frozen=True)
class SessionSchedule:
    """One session's structural availability, as scheduled -- never as observed."""

    session_id: int
    scheduled_rth_open_ct: int | None
    scheduled_rth_close_ct: int | None
    scheduled_rth_status: str
    structural_interruptions: tuple[StructuralInterruption, ...]
    timezone: str
    calendar_version: str
    calendar_sha256: str
    interruption_source_id: str | None

    def __post_init__(self) -> None:
        _require_int(self.session_id, "session_id")
        if self.timezone != CANONICAL_TIMEZONE:
            raise SpineError(
                f"session schedule timezone must be {CANONICAL_TIMEZONE!r}, "
                f"got {self.timezone!r}"
            )
        if self.scheduled_rth_status not in SCHEDULED_RTH_STATUSES:
            raise SpineError(
                f"undeclared scheduled_rth_status {self.scheduled_rth_status!r}"
            )
        if not isinstance(self.structural_interruptions, tuple):
            raise SpineError("structural_interruptions must be a tuple")

        has_rth = self.scheduled_rth_status not in _NO_RTH_STATUSES
        if has_rth:
            open_ct = _require_minute(self.scheduled_rth_open_ct, "scheduled_rth_open_ct")
            close_ct = _require_minute(self.scheduled_rth_close_ct, "scheduled_rth_close_ct")
            if open_ct >= close_ct:
                raise SpineError(
                    f"session {self.session_id}: open must precede close, "
                    f"got {open_ct} >= {close_ct}"
                )
        else:
            if self.scheduled_rth_open_ct is not None or self.scheduled_rth_close_ct is not None:
                raise SpineError(
                    f"session {self.session_id}: {self.scheduled_rth_status} must carry "
                    "no RTH open or close"
                )
            if self.structural_interruptions:
                raise SpineError(
                    f"session {self.session_id}: a session with no scheduled RTH cannot "
                    "carry an interruption"
                )
            open_ct = close_ct = None

        previous_end: int | None = None
        for item in self.structural_interruptions:
            if not isinstance(item, StructuralInterruption):
                raise SpineError("structural_interruptions must hold StructuralInterruption")
            if item.start_ct_minute < open_ct or item.end_ct_minute > close_ct:
                raise SpineError(
                    f"session {self.session_id}: interruption "
                    f"[{item.start_ct_minute}, {item.end_ct_minute}) lies outside the "
                    f"scheduled session [{open_ct}, {close_ct}]"
                )
            if previous_end is not None and item.start_ct_minute < previous_end:
                # Covers both non-canonical ordering and overlap. No silent sort
                # and no canonical merge: either would invent a boundary.
                raise SpineError(
                    f"session {self.session_id}: interruptions must be strictly "
                    "ascending and non-overlapping"
                )
            previous_end = item.end_ct_minute

        for name in ("calendar_version", "calendar_sha256"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise SpineError(f"session schedule {name} must be a nonempty string")
        if self.interruption_source_id is not None and (
            not isinstance(self.interruption_source_id, str)
            or not self.interruption_source_id
        ):
            raise SpineError("interruption_source_id must be None or a nonempty string")

    @property
    def has_scheduled_rth(self) -> bool:
        return self.scheduled_rth_status not in _NO_RTH_STATUSES


@dataclass(frozen=True)
class AvailabilityDecision:
    """Immutable verdict. ``reason`` is ``not_applicable`` iff ``available``."""

    available: bool
    reason: str

    def __post_init__(self) -> None:
        if type(self.available) is not bool:
            raise SpineError("availability must be a built-in bool")
        if self.reason not in UNAVAILABILITY_REASONS:
            raise SpineError(f"undeclared availability reason {self.reason!r}")
        if (self.reason == REASON_NOT_APPLICABLE) is not self.available:
            raise SpineError(
                "reason must be not_applicable exactly when the window is available"
            )


@dataclass(frozen=True)
class SessionScheduleTable:
    """Immutable schedule set plus the exclusion registry. Loaded once."""

    schedules: MappingProxyType
    exclusions: MappingProxyType

    def lookup(self, session_id: int) -> SessionSchedule:
        _require_int(session_id, "session_id")
        schedule = self.schedules.get(session_id)
        if schedule is None:
            raise SpineError(f"session {session_id} is absent from the session schedule")
        return schedule

    def is_excluded(self, session_id: int) -> bool:
        _require_int(session_id, "session_id")
        return session_id in self.exclusions

    def exclusion(self, session_id: int) -> SessionExclusion:
        _require_int(session_id, "session_id")
        record = self.exclusions.get(session_id)
        if record is None:
            raise SpineError(f"session {session_id} carries no exclusion record")
        return record

    @property
    def session_ids(self) -> tuple[int, ...]:
        """Canonical structural ordering: ascending session identity."""
        return tuple(sorted(self.schedules))

    @property
    def excluded_session_ids(self) -> tuple[int, ...]:
        return tuple(sorted(self.exclusions))


def build_session_schedule_table(
    schedules: Iterable[SessionSchedule],
    *,
    exclusions: Iterable[SessionExclusion] = (),
) -> SessionScheduleTable:
    """Assemble the canonical table. Duplicates and unknown sessions fail closed."""
    by_session: dict[int, SessionSchedule] = {}
    for schedule in schedules:
        if not isinstance(schedule, SessionSchedule):
            raise SpineError("session schedule table requires SessionSchedule records")
        if schedule.session_id in by_session:
            raise SpineError(f"duplicate session schedule for {schedule.session_id}")
        by_session[schedule.session_id] = schedule
    if not by_session:
        raise SpineError("session schedule table must be nonempty")

    excluded: dict[int, SessionExclusion] = {}
    for record in exclusions:
        if not isinstance(record, SessionExclusion):
            raise SpineError("exclusion registry requires SessionExclusion records")
        if record.session_id in excluded:
            raise SpineError(f"duplicate exclusion record for {record.session_id}")
        if record.session_id not in by_session:
            raise SpineError(
                f"exclusion references session {record.session_id}, which is absent "
                "from the accepted calendar"
            )
        excluded[record.session_id] = record

    return SessionScheduleTable(
        schedules=MappingProxyType(dict(sorted(by_session.items()))),
        exclusions=MappingProxyType(dict(sorted(excluded.items()))),
    )


def _schedule_from_calendar_row(row: CalendarRow) -> SessionSchedule:
    if row.scheduled_rth_status in _NO_RTH_STATUSES:
        open_ct = close_ct = None
    else:
        open_ct = _parse_ct_minute(row.scheduled_rth_open_ct, "scheduled_rth_open_ct")
        close_ct = _parse_ct_minute(row.scheduled_rth_close_ct, "scheduled_rth_close_ct")
    return SessionSchedule(
        session_id=row.trade_date,
        scheduled_rth_open_ct=open_ct,
        scheduled_rth_close_ct=close_ct,
        scheduled_rth_status=row.scheduled_rth_status,
        structural_interruptions=(),
        timezone=CANONICAL_TIMEZONE,
        calendar_version=CALENDAR_VERSION,
        calendar_sha256=CALENDAR_SHA256,
        interruption_source_id=None,
    )


@lru_cache(maxsize=1)
def load_session_schedule_table() -> SessionScheduleTable:
    """Build the canonical table from the byte-pinned accepted calendar.

    Accepts no caller path and no override. No interruption record is registered:
    none has authoritative boundaries (D33). Exclusions are supplied by the
    versioned registry once it exists; until then the table carries none, and an
    excluded session therefore cannot be silently assumed.
    """
    calendar = load_accepted_calendar()
    return build_session_schedule_table(
        _schedule_from_calendar_row(row) for row in calendar.rows
    )


@lru_cache(maxsize=1)
def _declared_horizons() -> tuple[int, ...]:
    horizons = load_constants().get("horizons_minutes")
    if not isinstance(horizons, list) or not horizons:
        raise SpineError("horizons_minutes must be a nonempty list")
    return tuple(int(value) for value in horizons)


def outcome_window_structurally_available(
    *,
    session_id: int,
    tau_ct_minute: int,
    horizon_minutes: int,
    schedule_table: SessionScheduleTable,
) -> AvailabilityDecision:
    """Whether every timestamp the horizon requires is structurally observable.

    Takes no bars and no store: availability is a property of the schedule, never
    of what was observed. Inferring a close from absent data is the prohibited
    move this signature makes impossible.
    """
    if not isinstance(schedule_table, SessionScheduleTable):
        raise SpineError("a canonical SessionScheduleTable is required")
    _require_int(session_id, "session_id")
    tau = _require_minute(tau_ct_minute, "tau_ct_minute")
    horizon = _require_int(horizon_minutes, "horizon_minutes")
    if horizon not in _declared_horizons():
        raise SpineError(
            f"horizon {horizon} is not a declared horizon "
            f"{list(_declared_horizons())} (analysis_constants_v1.yaml)"
        )

    # 1. Exclusion precedes every schedule test (D33). An excluded session has no
    #    admissible window at all, so this fails closed rather than returning a
    #    reason: no anchor from it may enter the population.
    if schedule_table.is_excluded(session_id):
        record = schedule_table.exclusion(session_id)
        raise SpineError(
            f"session {session_id} is excluded from the population "
            f"({record.reason}, {record.recorded_by_ruling}); no outcome window "
            "may be evaluated for it"
        )

    schedule = schedule_table.lookup(session_id)

    # 2. No scheduled RTH: no window is structurally available. Never invent a close.
    if not schedule.has_scheduled_rth:
        return AvailabilityDecision(False, REASON_NO_SCHEDULED_RTH)

    window_end = tau + horizon

    # 3. The window must lie inside the scheduled session. `<= close` with
    #    equality available reproduces the v1 rule exactly when close is 15:00.
    if tau < schedule.scheduled_rth_open_ct or window_end > schedule.scheduled_rth_close_ct:
        return AvailabilityDecision(False, REASON_SCHEDULED_CLOSE)

    # 4. Half-open intersection with any registered interruption.
    for item in schedule.structural_interruptions:
        if tau < item.end_ct_minute and item.start_ct_minute < window_end:
            return AvailabilityDecision(False, REASON_REGISTERED_INTERRUPTION)

    return AvailabilityDecision(True, REASON_NOT_APPLICABLE)
