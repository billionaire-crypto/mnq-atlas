"""Synthetic, store-free Phase 7 pipeline fixtures shared by contract tests."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from mnq_lab.conditioners.calendar import (
    CALENDAR_VERSION,
    SCHEMA_VERSION,
    CalendarRow,
    CalendarTable,
)
from mnq_lab.conditioners.pipeline import SCALE_SOURCE_ARMS, build_conditioner_pipeline
from mnq_lab.conditioners.seasonal import ScaleAnchorTable, scale_anchor_row

CT = ZoneInfo("America/Chicago")


def weekday_dates(count: int) -> tuple[date, ...]:
    output = []
    current = date(2020, 1, 2)
    while len(output) < count:
        if current.weekday() < 5:
            output.append(current)
        current += timedelta(days=1)
    return tuple(output)


def session_id(value: date) -> int:
    return value.year * 10_000 + value.month * 100 + value.day


def synthetic_pipeline(session_count: int):
    days = weekday_dates(session_count)
    sessions = tuple(session_id(value) for value in days)
    calendar = CalendarTable(
        tuple(
            CalendarRow(
                session,
                "CME_GLOBEX_EQUITY_INDEX_FUTURES",
                "regular",
                "full_rth",
                "08:30",
                "15:00",
                "17:00",
                "16:00",
                False,
                f"fixture:{session}",
                "fixture",
                "test",
                CALENDAR_VERSION,
                SCHEMA_VERSION,
            )
            for session in sessions
        )
    )
    tables = {}
    for arm_offset, arm_id in enumerate(SCALE_SOURCE_ARMS):
        rows = []
        for index, (value, session) in enumerate(zip(days, sessions)):
            tau = datetime.combine(value, time(8, 30), tzinfo=CT)
            ts_event_ns = int(
                (tau - timedelta(minutes=5)).timestamp() * 1_000_000_000
            )
            valid = not (arm_id == "coverage_strict" and index in {20, 70})
            scale = (
                (
                    0.25 + 0.01 * arm_offset + 0.01 * (index % 2)
                    if index >= 123
                    else 1.0
                    + 0.007 * index
                    + 0.03 * arm_offset
                    + 0.02 * (index % 5)
                )
                if valid
                else 0.0
            )
            rows.append(
                scale_anchor_row(
                    arm_id=arm_id,
                    session_id=session,
                    ts_event_ns=ts_event_ns,
                    scale_stage="mad" if arm_id == "mad78" else "ewma",
                    scale_value=scale,
                    scale_valid=valid,
                )
            )
        tables[arm_id] = ScaleAnchorTable(arm_id, tuple(rows))
    pipeline = build_conditioner_pipeline(
        tables,
        sessions,
        frozenset(sessions),
        calendar,
    )
    return sessions, tables, calendar, pipeline
