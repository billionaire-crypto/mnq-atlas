"""Identity-preserving proof for seasonal dependency-tuple sharing."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import date, datetime, time, timedelta
import hashlib
from pathlib import Path
import struct
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from mnq_lab.conditioners import seasonal
from mnq_lab.conditioners.arms import ArmConfig, arm_config
from mnq_lab.conditioners.assignments import (
    PHASE_ORDER,
    ThresholdRow,
    ThresholdTable,
    VolRelRow,
    VolRelTable,
    build_thresholds,
)
from mnq_lab.conditioners.calendar import (
    CALENDAR_VERSION,
    SCHEMA_VERSION,
    CalendarRow,
    CalendarTable,
)
from mnq_lab.conditioners.scales.median import lower_median
from mnq_lab.conditioners.status import ThresholdStatus, UpstreamStage, VolRelStatus
from mnq_lab.core.weights import weighted_quantile

CT = ZoneInfo("America/Chicago")
ARM_ID = "primary_ewma78_permissive_expanding"
ROLLING_ARM_ID = "threshold_rolling60"
IDENTITY_SESSION_COUNT = 70
PREREGISTRATION_BYTES = 21_026
PREREGISTRATION_SHA256 = (
    "759527ca33f13c9cefaf73124541ac300eab650ac72349753a1d4c95154944e1"
)
PREREGISTRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "DEPENDENCY_REPRESENTATION_PREREGISTRATION.md"
)


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

    def calendar_row(index: int, session: int) -> CalendarRow:
        if index == 4:
            session_class, status, rth_close, raw_close = (
                "scheduled_early_close",
                "shortened_rth",
                "12:00",
                "12:00",
            )
            rth_open, raw_open = "08:30", "17:00"
        elif index == 11:
            session_class = status = "full_exchange_holiday"
            rth_open = rth_close = raw_open = raw_close = ""
        else:
            session_class, status, rth_close, raw_close = (
                "regular",
                "full_rth",
                "15:00",
                "16:00",
            )
            rth_open, raw_open = "08:30", "17:00"
        return CalendarRow(
            session,
            "CME_GLOBEX_EQUITY_INDEX_FUTURES",
            session_class,
            status,
            rth_open,
            rth_close,
            raw_open,
            raw_close,
            False,
            f"dependency-oracle:{session}",
            "synthetic-calendar",
            "test",
            CALENDAR_VERSION,
            SCHEMA_VERSION,
        )

    calendar = CalendarTable(
        tuple(
            calendar_row(index, session) for index, session in enumerate(sessions)
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


def _vol_rel_fixture(scales: seasonal.ScaleAnchorTable) -> VolRelTable:
    rows: list[VolRelRow] = []
    for row in scales.rows:
        valid = row.scale_valid
        rows.append(
            VolRelRow(
                ARM_ID,
                row.session_id,
                row.ts_event_ns,
                row.tau_ns,
                row.observation_bucket_ct,
                row.session_phase,
                row.scale_value,
                row.scale_valid,
                1.0,
                True,
                row.scale_value if valid else 0.0,
                valid,
                VolRelStatus.OK if valid else VolRelStatus.UPSTREAM_UNDEFINED,
                None if valid else UpstreamStage.EWMA,
                row.data_quality_status,
            )
        )
    return VolRelTable(ARM_ID, tuple(rows))


def _build_threshold_reference(
    config: ArmConfig,
    vol_rel: VolRelTable,
    current_sessions: tuple[int, ...],
    completed_sessions: frozenset[int],
    calendar: CalendarTable,
) -> ThresholdTable:
    """Exact current threshold construction, independent of build_thresholds."""
    by_session_phase: dict[tuple[int, str], list[VolRelRow]] = {}
    for row in vol_rel.rows:
        if row.vol_rel_valid:
            by_session_phase.setdefault((row.session_id, row.session_phase), []).append(
                row
            )

    output: list[ThresholdRow] = []
    for current in current_sessions:
        for phase in PHASE_ORDER:
            eligible_sessions: list[int] = []
            for prior in sorted(completed_sessions):
                if prior >= current:
                    break
                calendar_row = calendar.lookup(prior)
                if (
                    calendar_row is None
                    or not calendar_row.seasonal_reference_eligible
                ):
                    continue
                if by_session_phase.get((prior, phase)):
                    eligible_sessions.append(prior)
            selected = (
                eligible_sessions[-60:]
                if config.history_kind == "rolling60"
                else eligible_sessions
            )
            dependency_keys = tuple(
                (row.session_id, row.tau_ns)
                for prior in selected
                for row in by_session_phase[(prior, phase)]
            )
            if len(eligible_sessions) < 60:
                output.append(
                    ThresholdRow(
                        config.arm_id,
                        current,
                        phase,
                        config.history_kind,
                        len(selected),
                        config.lower_probability,
                        config.upper_probability,
                        0.0,
                        0.0,
                        False,
                        ThresholdStatus.INSUFFICIENT_THRESHOLD_HISTORY,
                        dependency_keys,
                    )
                )
                continue
            values: list[float] = []
            weights: list[float] = []
            for prior in selected:
                rows = by_session_phase[(prior, phase)]
                mass = float(np.float64(1.0) / np.float64(len(rows)))
                values.extend(row.vol_rel for row in rows)
                weights.extend(mass for _ in rows)
            value_array = np.asarray(values, dtype=np.float64)
            weight_array = np.asarray(weights, dtype=np.float64)
            lower = weighted_quantile(
                value_array, weight_array, config.lower_probability
            )
            upper = weighted_quantile(
                value_array, weight_array, config.upper_probability
            )
            status = (
                ThresholdStatus.DEGENERATE_BOUNDARIES
                if lower == upper
                else ThresholdStatus.OK
            )
            output.append(
                ThresholdRow(
                    config.arm_id,
                    current,
                    phase,
                    config.history_kind,
                    len(selected),
                    config.lower_probability,
                    config.upper_probability,
                    float(lower),
                    float(upper),
                    True,
                    status,
                    dependency_keys,
                )
            )
    return ThresholdTable(config.arm_id, tuple(output))


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
            expected_value = getattr(expected_row, field.name)
            actual_value = getattr(actual_row, field.name)
            assert type(expected_value) is type(actual_value), (
                f"row {row_index} field {field.name} type differs"
            )
            if isinstance(expected_value, float):
                assert struct.pack(">d", expected_value) == struct.pack(">d", actual_value), (
                    f"row {row_index} field {field.name} differs"
                )
            else:
                assert expected_value == actual_value, (
                    f"row {row_index} field {field.name} differs"
                )


def _assert_complete_threshold_table_equal(
    expected: ThresholdTable,
    actual: ThresholdTable,
) -> None:
    assert expected.arm_id == actual.arm_id
    assert len(expected.rows) == len(actual.rows)
    for row_index, (expected_row, actual_row) in enumerate(
        zip(expected.rows, actual.rows, strict=True)
    ):
        for field in fields(ThresholdRow):
            expected_value = getattr(expected_row, field.name)
            actual_value = getattr(actual_row, field.name)
            assert type(expected_value) is type(actual_value), (
                f"row {row_index} field {field.name} type differs"
            )
            if isinstance(expected_value, float):
                assert struct.pack(">d", expected_value) == struct.pack(">d", actual_value), (
                    f"row {row_index} field {field.name} differs"
                )
            else:
                assert expected_value == actual_value, (
                    f"row {row_index} field {field.name} differs"
                )


@dataclass(frozen=True)
class _IdentityOracle:
    sessions: tuple[int, ...]
    seasonal_reference: seasonal.SeasonalProfileTable
    seasonal_actual: seasonal.SeasonalProfileTable
    threshold_reference: dict[str, ThresholdTable]
    threshold_actual: dict[str, ThresholdTable]


@pytest.fixture(scope="module")
def _identity_tables() -> _IdentityOracle:
    sessions, calendar, scales = _full_density_fixture(IDENTITY_SESSION_COUNT)
    completed = frozenset(sessions)
    seasonal_reference = _build_pre_fix_reference(
        scales, sessions, completed, calendar
    )
    seasonal_actual = seasonal.build_seasonal_profiles(
        scales, sessions, completed, calendar
    )
    vol_rel = _vol_rel_fixture(scales)
    configs = (arm_config(ARM_ID), arm_config(ROLLING_ARM_ID))
    threshold_reference = {
        config.arm_id: _build_threshold_reference(
            config, vol_rel, sessions, completed, calendar
        )
        for config in configs
    }
    threshold_actual = {
        config.arm_id: build_thresholds(
            config, vol_rel, sessions, completed, calendar
        )
        for config in configs
    }
    return _IdentityOracle(
        sessions,
        seasonal_reference,
        seasonal_actual,
        threshold_reference,
        threshold_actual,
    )


def test_shared_dependencies_preserve_every_pre_fix_row_field_and_oracle_can_fail(
    _identity_tables: _IdentityOracle,
) -> None:
    reference = _identity_tables.seasonal_reference
    actual = _identity_tables.seasonal_actual
    assert len(actual.rows) == IDENTITY_SESSION_COUNT * len(seasonal.RTH_BUCKETS) == 5_460
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
    _identity_tables: _IdentityOracle,
) -> None:
    sessions = _identity_tables.sessions
    actual = _identity_tables.seasonal_actual
    final_rows = [row for row in actual.rows if row.session_id == sessions[-1]]
    for phase in seasonal._time_model().phase_names:
        phase_rows = [row for row in final_rows if row.session_phase == phase]
        assert len(phase_rows) > 1
        assert phase_rows[0].dependency_keys
        assert all(
            row.dependency_keys is phase_rows[0].dependency_keys for row in phase_rows[1:]
        )


def test_threshold_legacy_oracle_covers_expanding_and_rolling60_at_full_density(
    _identity_tables: _IdentityOracle,
) -> None:
    expected_rows = IDENTITY_SESSION_COUNT * len(PHASE_ORDER)
    assert expected_rows == 350
    for arm_id in (ARM_ID, ROLLING_ARM_ID):
        reference = _identity_tables.threshold_reference[arm_id]
        actual = _identity_tables.threshold_actual[arm_id]
        assert len(reference.rows) == len(actual.rows) == expected_rows
        _assert_complete_threshold_table_equal(reference, actual)

    final_session = _identity_tables.sessions[-1]
    expanding = _identity_tables.threshold_actual[ARM_ID].lookup(
        final_session, PHASE_ORDER[0]
    )
    rolling = _identity_tables.threshold_actual[ROLLING_ARM_ID].lookup(
        final_session, PHASE_ORDER[0]
    )
    assert expanding.qualifying_prior_sessions == 67
    assert rolling.qualifying_prior_sessions == 60
    assert expanding.dependency_keys != rolling.dependency_keys


@pytest.mark.parametrize("arm_id", (ARM_ID, ROLLING_ARM_ID))
def test_threshold_legacy_oracle_rejects_one_structurally_valid_key_perturbation(
    _identity_tables: _IdentityOracle,
    arm_id: str,
) -> None:
    reference = _identity_tables.threshold_reference[arm_id]
    actual = _identity_tables.threshold_actual[arm_id]
    source = next(row for row in reference.rows if row.dependency_keys)
    first_session, first_tau = source.dependency_keys[0]
    perturbed_dependencies = tuple(
        sorted(
            ((first_session, first_tau + 1) if key == (first_session, first_tau) else key)
            for key in source.dependency_keys
        )
    )
    perturbed_row = replace(source, dependency_keys=perturbed_dependencies)
    perturbed = ThresholdTable(
        reference.arm_id,
        tuple(perturbed_row if row is source else row for row in reference.rows),
    )
    with pytest.raises(AssertionError, match="dependency_keys"):
        _assert_complete_threshold_table_equal(perturbed, actual)


def _assert_preregistration_pin(payload: bytes) -> None:
    assert len(payload) == PREREGISTRATION_BYTES
    assert hashlib.sha256(payload).hexdigest() == PREREGISTRATION_SHA256


def test_dependency_representation_preregistration_is_byte_pinned_and_guard_can_fail():
    payload = PREREGISTRATION_PATH.read_bytes()
    _assert_preregistration_pin(payload)

    with pytest.raises(AssertionError):
        _assert_preregistration_pin(payload[:-1])
    changed = bytearray(payload)
    changed[100] ^= 1
    with pytest.raises(AssertionError):
        _assert_preregistration_pin(bytes(changed))
