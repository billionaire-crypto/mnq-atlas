"""Accepted-calendar and causal seasonal-profile contract tests."""

from __future__ import annotations

import inspect
from datetime import date, datetime, time, timedelta, timezone
from types import MappingProxyType
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.conditioners.calendar import (
    CALENDAR_SHA256,
    CALENDAR_VERSION,
    SCHEMA_VERSION,
    CalendarRow,
    CalendarTable,
    completed_session_ids,
    load_accepted_calendar,
)
from mnq_lab.conditioners.scales.returns import CoverageRule, ReturnInputs, construct_returns
from mnq_lab.conditioners.status import ResetReason, ReturnMissingReason
from mnq_lab.conditioners.seasonal import (
    RTH_BUCKETS,
    ScaleAnchorTable,
    SeasonalStatus,
    _profile_value,
    build_seasonal_profiles,
    scale_anchor_row,
)
from mnq_lab.spine.exploration import ExplorationBars

CT = ZoneInfo("America/Chicago")


def _calendar_row(trade_date: int, session_class: str = "regular") -> CalendarRow:
    if session_class == "full_exchange_holiday":
        status, rth_open, rth_close, raw_open, raw_close = (
            "full_exchange_holiday",
            "",
            "",
            "",
            "",
        )
    elif session_class == "scheduled_early_close":
        status, rth_open, rth_close, raw_open, raw_close = (
            "shortened_rth",
            "08:30",
            "12:00",
            "17:00",
            "12:00",
        )
    else:
        status, rth_open, rth_close, raw_open, raw_close = (
            "full_rth",
            "08:30",
            "15:00",
            "17:00",
            "16:00",
        )
    return CalendarRow(
        trade_date,
        "CME_GLOBEX_EQUITY_INDEX_FUTURES",
        session_class,
        status,
        rth_open,
        rth_close,
        raw_open,
        raw_close,
        False,
        f"synthetic:{trade_date}",
        "synthetic-calendar",
        "test",
        CALENDAR_VERSION,
        SCHEMA_VERSION,
    )


def _weekdays(count: int) -> tuple[date, ...]:
    values = []
    current = date(2020, 1, 2)
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current)
        current += timedelta(days=1)
    return tuple(values)


def _session_id(value: date) -> int:
    return value.year * 10_000 + value.month * 100 + value.day


def _ts_event_ns(value: date, tau_hhmm: str) -> int:
    hour, minute = (int(part) for part in tau_hhmm.split(":"))
    tau = datetime.combine(value, time(hour, minute), tzinfo=CT)
    return int((tau - timedelta(minutes=5)).timestamp() * 1_000_000_000)


def _seasonal_fixture():
    days = _weekdays(63)
    session_ids = tuple(_session_id(value) for value in days)
    classes = ("full_exchange_holiday", "scheduled_early_close") + ("regular",) * 61
    calendar = CalendarTable(
        tuple(_calendar_row(session, kind) for session, kind in zip(session_ids, classes))
    )
    rows = []
    for index, (value, session) in enumerate(zip(days, session_ids)):
        base = float(index + 1)
        rows.append(
            scale_anchor_row(
                arm_id="primary_ewma78_permissive_expanding",
                session_id=session,
                ts_event_ns=_ts_event_ns(value, "08:30"),
                scale_stage="ewma",
                scale_value=base,
                scale_valid=True,
            )
        )
        rows.append(
            scale_anchor_row(
                arm_id="primary_ewma78_permissive_expanding",
                session_id=session,
                ts_event_ns=_ts_event_ns(value, "08:35"),
                scale_stage="ewma",
                scale_value=base + 100.0 if index < 12 else 0.0,
                scale_valid=index < 12,
            )
        )
    table = ScaleAnchorTable("primary_ewma78_permissive_expanding", tuple(rows))
    return days, session_ids, calendar, table


def test_accepted_calendar_loader_is_zero_argument_byte_pinned_and_total():
    assert list(inspect.signature(load_accepted_calendar).parameters) == []
    calendar = load_accepted_calendar()
    assert len(calendar.rows) == 1018
    assert calendar.first_trade_date == 20190506
    assert calendar.last_trade_date == 20230329
    assert calendar.lookup(20210402).raw_exchange_close_ct == "08:15"
    assert calendar.lookup(20191225).session_class == "full_exchange_holiday"
    assert CALENDAR_SHA256 == "b86e112c16112bf11a6a548ca8b3f21d28a08f90442b4dde84098f9d3f6eb069"
    assert calendar.lookup(20180101) is None

    missing = CalendarTable((_calendar_row(20200102), _calendar_row(20200106)))
    with pytest.raises(SpineError, match="missing in-range"):
        missing.lookup(20200103)


def test_calendar_exclusion_is_external_and_unscheduled_rows_remain_flagged_eligible():
    regular = _calendar_row(20200102)
    early = _calendar_row(20200103, "scheduled_early_close")
    holiday = _calendar_row(20200106, "full_exchange_holiday")
    unscheduled = _calendar_row(20200107, "unscheduled_closure")
    assert regular.seasonal_reference_eligible
    assert not early.seasonal_reference_eligible
    assert not holiday.seasonal_reference_eligible
    assert unscheduled.seasonal_reference_eligible

    with pytest.raises(SpineError, match="unknown calendar session_class"):
        _calendar_row(20200108, "remembered_holiday")


def test_profiles_use_strictly_prior_regular_sessions_and_first_emit_on_61st_clock():
    _, sessions, calendar, scales = _seasonal_fixture()
    current = sessions[-1]
    completed = frozenset(sessions[:-1])
    profiles = build_seasonal_profiles(scales, (current,), completed, calendar)
    assert len(profiles.rows) == 78
    open_row = profiles.lookup(current, "08:30")
    assert open_row.qualifying_prior_sessions == 60
    assert open_row.bucket_n == 60
    assert open_row.seasonal_status is SeasonalStatus.OK
    assert open_row.seasonal_profile == open_row.bucket_median
    assert all(session < current for session, _ in open_row.dependency_keys)
    assert sessions[0] not in {session for session, _ in open_row.dependency_keys}
    assert sessions[1] not in {session for session, _ in open_row.dependency_keys}

    # Including the two calendar-excluded sessions would move the lower median.
    forbidden_values = np.arange(1.0, 63.0, dtype=np.float64)
    forbidden_median = float(np.sort(forbidden_values)[30])
    assert forbidden_median != open_row.bucket_median


def test_sparse_bucket_shrinks_and_absent_bucket_uses_phase_median():
    _, sessions, calendar, scales = _seasonal_fixture()
    current = sessions[-1]
    profiles = build_seasonal_profiles(
        scales, (current,), frozenset(sessions[:-1]), calendar
    )
    sparse = profiles.lookup(current, "08:35")
    assert sparse.qualifying_prior_sessions == 60
    assert sparse.bucket_n == 10  # first two valid rows are calendar-excluded
    assert sparse.shrink_weight == np.float64(10) / np.float64(40)
    expected = np.float64(
        np.float64(sparse.shrink_weight * sparse.bucket_median)
        + np.float64((1.0 - sparse.shrink_weight) * sparse.phase_session_median)
    )
    assert sparse.seasonal_profile == expected

    absent = profiles.lookup(current, "08:40")
    assert absent.bucket_n == 0
    assert not absent.bucket_median_valid
    assert absent.phase_session_median_valid
    assert absent.seasonal_profile == absent.phase_session_median


def test_warmup_and_unavailable_fallback_are_distinct_statuses():
    _, sessions, calendar, scales = _seasonal_fixture()
    before_60 = sessions[-2]
    profiles = build_seasonal_profiles(
        scales, (before_60,), frozenset(sessions[:-2]), calendar
    )
    assert profiles.lookup(before_60, "08:30").seasonal_status is SeasonalStatus.WARMUP
    assert not profiles.lookup(before_60, "08:30").seasonal_valid

    unavailable = _profile_value((), (), 60)
    assert unavailable[-1] is SeasonalStatus.SEASONAL_FALLBACK_UNAVAILABLE
    assert not unavailable[-2]


def test_bucket_identity_is_observation_time_and_stable_across_dst_weeks():
    before = date(2021, 3, 12)
    after = date(2021, 3, 15)
    rows = [
        scale_anchor_row(
            arm_id="x",
            session_id=_session_id(value),
            ts_event_ns=_ts_event_ns(value, "08:30"),
            scale_stage="ewma",
            scale_value=1.0,
            scale_valid=True,
        )
        for value in (before, after)
    ]
    assert [row.observation_bucket_ct for row in rows] == ["08:30", "08:30"]
    assert rows[0].ts_event_ns + 5 * 60 * 1_000_000_000 == rows[0].tau_ns
    assert "08:25" not in RTH_BUCKETS

    # The bar-label mutation would key the first anchor outside the frozen grid.
    with pytest.raises(SpineError, match="outside the RTH"):
        scale_anchor_row(
            arm_id="x",
            session_id=_session_id(before),
            ts_event_ns=_ts_event_ns(before, "08:25"),
            scale_stage="ewma",
            scale_value=1.0,
            scale_valid=True,
        )


def test_planted_intrasession_utc_offset_change_breaks_recursion():
    before = datetime(2021, 11, 7, 1, 55, tzinfo=timezone(timedelta(hours=-5)))
    after = datetime(2021, 11, 7, 2, 0, tzinfo=timezone(timedelta(hours=-6)))
    timestamps = np.asarray(
        [int(value.timestamp() * 1_000_000_000) for value in (before, after)],
        dtype=np.int64,
    )
    inputs = ReturnInputs(
        ts_event_ns=timestamps,
        session_id=np.asarray([20210315, 20210315], dtype=np.int32),
        symbol_code=np.asarray([0, 0], dtype=np.int16),
        close_ticks=np.asarray([100, 101], dtype=np.int32),
        expected_1m_components=np.asarray([5, 5], dtype=np.int8),
        observed_1m_components=np.asarray([5, 5], dtype=np.int8),
        rollover=np.asarray([False, False], dtype=np.bool_),
    )
    result = construct_returns(inputs, CoverageRule.PERMISSIVE)
    assert timestamps[1] - timestamps[0] != 300_000_000_000
    assert not result.valid[1]
    assert result.statuses[1].return_missing_reason is ReturnMissingReason.SPACING_BREAK
    assert result.statuses[1].reset_reason is ResetReason.GAP_RESET
    assert not result.statuses[1].scheduled_break


def test_completed_session_clock_uses_scheduled_end_not_observed_shortening():
    sessions = (20200102, 20200103)
    calendar = CalendarTable(tuple(_calendar_row(session) for session in sessions))
    # The first session is observed only through 10:00, but the corpus boundary
    # is after its scheduled close. It remains completed; the final session does
    # not because the boundary precedes its scheduled 16:00 close.
    timestamps = np.asarray(
        [
            _ts_event_ns(date(2020, 1, 2), "10:00"),
            _ts_event_ns(date(2020, 1, 3), "14:00"),
        ],
        dtype=np.int64,
    )
    columns = MappingProxyType(
        {
            "ts_event_ns": timestamps,
            "session_id": np.asarray(sessions, dtype=np.int32),
        }
    )
    bars = ExplorationBars("synthetic", ("MNQH0",), columns)
    assert completed_session_ids(bars, calendar) == frozenset({20200102})

    # A data-quality label is carried by scale rows but cannot relabel the
    # calendar or remove the completed regular session from the reference.
    row = scale_anchor_row(
        arm_id="x",
        session_id=20200102,
        ts_event_ns=_ts_event_ns(date(2020, 1, 2), "08:30"),
        scale_stage="ewma",
        scale_value=2.0,
        scale_valid=True,
        data_quality_status="unresolved_truncated_session",
    )
    table = ScaleAnchorTable("x", (row,))
    profile = build_seasonal_profiles(
        table,
        (20200103,),
        frozenset({20200102}),
        calendar,
    ).lookup(20200103, "08:30")
    assert profile.qualifying_prior_sessions == 1
    assert profile.seasonal_status is SeasonalStatus.WARMUP
    assert profile.dependency_keys == ((20200102, "08:30"),)
