"""Identity-preserving proof for seasonal dependency-tuple sharing."""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from mnq_lab.conditioners import seasonal
from mnq_lab.conditioners.calendar import (
    CALENDAR_VERSION,
    SCHEMA_VERSION,
    CalendarRow,
    CalendarTable,
)
from mnq_lab.conditioners.scales.median import lower_median

CT = ZoneInfo("America/Chicago")
ARM_ID = "primary_ewma78_permissive_expanding"
IDENTITY_SESSION_COUNT = 20


def _weekdays(count: int) -> tuple[date, ...]:
    output: list[date] = []
    current = date(2020, 1, 2)
    while len(output) < count:
        if current.weekday() < 5:
            output.append(current)
        current += timedelta(days=1)
    return tuple(output)


def _session_id(value: date) -> int:
    return value.year * 10_000 + value.month * 100 + value.day


def _full_density_fixture(
    session_count: int,
) -> tuple[tuple[int, ...], CalendarTable, seasonal.ScaleAnchorTable]:
    days = _weekdays(session_count)
    sessions = tuple(_session_id(value) for value in days)
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
                f"seasonal-sharing-fixture:{session}",
                "synthetic-calendar",
                "test",
                CALENDAR_VERSION,
                SCHEMA_VERSION,
            )
            for session in sessions
        )
    )
    rows: list[seasonal.ScaleAnchorRow] = []
    for session_index, (value, session) in enumerate(zip(days, sessions, strict=True)):
        for bucket_index, bucket in enumerate(seasonal.RTH_BUCKETS):
            hour, minute = (int(part) for part in bucket.split(":"))
            tau = datetime.combine(value, time(hour, minute), tzinfo=CT)
            valid = (session_index + bucket_index) % 17 != 0
            rows.append(
                seasonal.scale_anchor_row(
                    arm_id=ARM_ID,
                    session_id=session,
                    ts_event_ns=int(
                        (tau - timedelta(minutes=5)).timestamp() * 1_000_000_000
                    ),
                    scale_stage="ewma",
                    scale_value=(
                        float(1 + session_index * 78 + bucket_index) / 16.0
                        if valid
                        else 0.0
                    ),
                    scale_valid=valid,
                )
            )
    return sessions, calendar, seasonal.ScaleAnchorTable(ARM_ID, tuple(rows))


def _build_pre_fix_reference(
    scales: seasonal.ScaleAnchorTable,
    current_sessions: tuple[int, ...],
    completed_sessions: frozenset[int],
    calendar: CalendarTable,
) -> seasonal.SeasonalProfileTable:
    """Exact pre-fix algorithm, retaining one equal tuple per bucket row."""
    by_session_phase: dict[tuple[int, str], list[seasonal.ScaleAnchorRow]] = {}
    by_session_bucket: dict[tuple[int, str], seasonal.ScaleAnchorRow] = {}
    for row in scales.rows:
        by_session_phase.setdefault((row.session_id, row.session_phase), []).append(row)
        by_session_bucket[(row.session_id, row.observation_bucket_ct)] = row

    output: list[seasonal.SeasonalProfileRow] = []
    ordered_completed = tuple(sorted(completed_sessions))
    for current_session in current_sessions:
        current_calendar = calendar.lookup(current_session)
        phase_context: dict[
            str, tuple[list[int], list[float], list[tuple[int, str]]]
        ] = {}
        if current_calendar is not None:
            for phase in seasonal._time_model().phase_names:
                prior_sessions: list[int] = []
                phase_medians: list[float] = []
                phase_dependency_keys: list[tuple[int, str]] = []
                for prior in ordered_completed:
                    if prior >= current_session:
                        break
                    prior_calendar = calendar.lookup(prior)
                    if (
                        prior_calendar is None
                        or not prior_calendar.seasonal_reference_eligible
                    ):
                        continue
                    phase_rows = [
                        row
                        for row in by_session_phase.get((prior, phase), ())
                        if row.scale_valid
                    ]
                    if not phase_rows:
                        continue
                    prior_sessions.append(prior)
                    phase_medians.append(
                        float(
                            lower_median(
                                np.asarray(
                                    [row.scale_value for row in phase_rows],
                                    dtype=np.float64,
                                )
                            )
                        )
                    )
                    phase_dependency_keys.extend(
                        (row.session_id, row.observation_bucket_ct)
                        for row in phase_rows
                    )
                phase_context[phase] = (
                    prior_sessions,
                    phase_medians,
                    phase_dependency_keys,
                )
        for bucket in seasonal.RTH_BUCKETS:
            phase = seasonal._phase_for_bucket(bucket)
            if current_calendar is None:
                output.append(
                    seasonal.SeasonalProfileRow(
                        scales.arm_id,
                        current_session,
                        bucket,
                        phase,
                        0,
                        0,
                        0.0,
                        False,
                        0.0,
                        False,
                        0.0,
                        0.0,
                        False,
                        seasonal.SeasonalStatus.CALENDAR_CLASSIFICATION_MISSING,
                        seasonal.CALENDAR_VERSION,
                        seasonal.CALENDAR_SHA256,
                        (),
                    )
                )
                continue

            prior_sessions, phase_medians, phase_dependency_keys = phase_context[phase]
            bucket_rows = [
                by_session_bucket[(prior, bucket)]
                for prior in prior_sessions
                if (prior, bucket) in by_session_bucket
                and by_session_bucket[(prior, bucket)].scale_valid
            ]
            bucket_values = tuple(row.scale_value for row in bucket_rows)
            calculated = seasonal._profile_value(
                bucket_values,
                tuple(phase_medians),
                len(prior_sessions),
            )
            dependencies = tuple(sorted(set(phase_dependency_keys)))
            output.append(
                seasonal.SeasonalProfileRow(
                    scales.arm_id,
                    current_session,
                    bucket,
                    phase,
                    len(prior_sessions),
                    len(bucket_rows),
                    calculated[0],
                    calculated[1],
                    calculated[2],
                    calculated[3],
                    calculated[4],
                    calculated[5],
                    calculated[6],
                    calculated[7],
                    seasonal.CALENDAR_VERSION,
                    seasonal.CALENDAR_SHA256,
                    dependencies,
                )
            )
    return seasonal.SeasonalProfileTable(scales.arm_id, tuple(output))


def _assert_complete_table_equal(
    expected: seasonal.SeasonalProfileTable,
    actual: seasonal.SeasonalProfileTable,
) -> None:
    assert expected.arm_id == actual.arm_id
    assert len(expected.rows) == len(actual.rows)
    for row_index, (expected_row, actual_row) in enumerate(
        zip(expected.rows, actual.rows, strict=True)
    ):
        for field in fields(seasonal.SeasonalProfileRow):
            assert getattr(expected_row, field.name) == getattr(actual_row, field.name), (
                f"row {row_index} field {field.name} differs"
            )


@pytest.fixture(scope="module")
def _identity_tables() -> tuple[
    tuple[int, ...], seasonal.SeasonalProfileTable, seasonal.SeasonalProfileTable
]:
    sessions, calendar, scales = _full_density_fixture(IDENTITY_SESSION_COUNT)
    completed = frozenset(sessions)
    reference = _build_pre_fix_reference(scales, sessions, completed, calendar)
    actual = seasonal.build_seasonal_profiles(scales, sessions, completed, calendar)
    return sessions, reference, actual


def test_shared_dependencies_preserve_every_pre_fix_row_field_and_oracle_can_fail(
    _identity_tables: tuple[
        tuple[int, ...], seasonal.SeasonalProfileTable, seasonal.SeasonalProfileTable
    ],
) -> None:
    _, reference, actual = _identity_tables
    assert len(actual.rows) == IDENTITY_SESSION_COUNT * len(seasonal.RTH_BUCKETS) == 1_560
    _assert_complete_table_equal(reference, actual)

    source = next(row for row in reference.rows if row.dependency_keys)
    first_session, first_bucket = source.dependency_keys[0]
    perturbed_dependencies = tuple(
        sorted(
            ((first_session, "08:31") if key == (first_session, first_bucket) else key)
            for key in source.dependency_keys
        )
    )
    perturbed_row = replace(source, dependency_keys=perturbed_dependencies)
    perturbed_rows = tuple(
        perturbed_row if row is source else row for row in reference.rows
    )
    perturbed = seasonal.SeasonalProfileTable(reference.arm_id, perturbed_rows)
    with pytest.raises(AssertionError, match="dependency_keys"):
        _assert_complete_table_equal(perturbed, actual)


def test_all_buckets_within_each_session_phase_share_one_dependency_tuple_object(
    _identity_tables: tuple[
        tuple[int, ...], seasonal.SeasonalProfileTable, seasonal.SeasonalProfileTable
    ],
) -> None:
    sessions, _, actual = _identity_tables
    final_rows = [row for row in actual.rows if row.session_id == sessions[-1]]
    for phase in seasonal._time_model().phase_names:
        phase_rows = [row for row in final_rows if row.session_phase == phase]
        assert len(phase_rows) > 1
        assert phase_rows[0].dependency_keys
        assert all(
            row.dependency_keys is phase_rows[0].dependency_keys for row in phase_rows[1:]
        )
