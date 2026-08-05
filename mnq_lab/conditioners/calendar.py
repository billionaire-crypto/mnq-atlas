"""Accepted immutable CME equity-index calendar consumer for Phase 7.

The calendar records, their validation and the byte-pinned loader now live in
``mnq_lab.spine.accepted_calendar`` so that the outcome layer can reach them
without importing ``conditioners`` (D32/D33 Stage 3). This module re-exports them
unchanged and keeps the Phase-7-specific helpers that need exploration bars.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import numpy as np

from mnq_lab import SpineError
from mnq_lab.spine.accepted_calendar import (
    CALENDAR_SHA256,
    CALENDAR_VERSION,
    SCHEMA_VERSION,
    CalendarRow,
    CalendarTable,
    load_accepted_calendar,
)
from mnq_lab.spine.exploration import ExplorationBars

__all__ = [
    "CALENDAR_SHA256",
    "CALENDAR_VERSION",
    "SCHEMA_VERSION",
    "CalendarRow",
    "CalendarTable",
    "completed_session_ids",
    "load_accepted_calendar",
]

_CT = ZoneInfo("America/Chicago")
_BAR_NS = 300_000_000_000


def _calendar_close_ns(row: CalendarRow) -> int:
    if not row.raw_exchange_close_ct:
        raise SpineError("active calendar row lacks a raw exchange close")
    text = str(row.trade_date)
    day = datetime.strptime(text, "%Y%m%d").date()
    hour, minute = (int(part) for part in row.raw_exchange_close_ct.split(":"))
    close = datetime.combine(day, time(hour, minute), tzinfo=_CT)
    return int(close.timestamp() * 1_000_000_000)


def completed_session_ids(
    bars: ExplorationBars, calendar: CalendarTable
) -> frozenset[int]:
    """Return sessions whose scheduled Globex interval ended by the seal.

    The boundary is the end of the final physically present exploration bar.
    Observed shortening and per-session row counts never participate.
    """
    if not isinstance(bars, ExplorationBars) or not isinstance(calendar, CalendarTable):
        raise SpineError("completed-session qualification requires exploration bars and calendar")
    timestamps = bars.column("ts_event_ns")
    sessions = bars.column("session_id")
    if timestamps.size == 0:
        raise SpineError("completed-session qualification requires nonempty bars")
    truncation_boundary_ns = int(timestamps[-1]) + _BAR_NS
    completed: set[int] = set()
    for value in np.unique(sessions):
        session_id = int(value)
        row = calendar.lookup(session_id)
        if row is None or not row.seasonal_reference_eligible:
            continue
        if _calendar_close_ns(row) <= truncation_boundary_ns:
            completed.add(session_id)
    return frozenset(completed)
