"""Relative-volatility, session-equal threshold, assignment, and migration tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.conditioners.arms import ARM_CONFIGS, arm_config
from mnq_lab.conditioners.assignments import (
    AssignmentRow,
    AssignmentStatus,
    AssignmentTable,
    ThresholdRow,
    ThresholdStatus,
    ThresholdTable,
    UpstreamStage,
    VolRelRow,
    VolRelStatus,
    VolRelTable,
    assignment_undefined_fractions,
    build_assignments,
    build_thresholds,
    build_vol_rel,
    cell_migration,
)
from mnq_lab.conditioners.calendar import (
    CALENDAR_SHA256,
    CALENDAR_VERSION,
    SCHEMA_VERSION,
    CalendarRow,
    CalendarTable,
)
from mnq_lab.conditioners.seasonal import (
    ScaleAnchorTable,
    SeasonalProfileRow,
    SeasonalProfileTable,
    SeasonalStatus,
    scale_anchor_row,
)


def _calendar_row(session: int) -> CalendarRow:
    return CalendarRow(
        session,
        "CME_GLOBEX_EQUITY_INDEX_FUTURES",
        "regular",
        "full_rth",
        "08:30",
        "15:00",
        "17:00",
        "16:00",
        False,
        f"synthetic:{session}",
        "synthetic",
        "test",
        CALENDAR_VERSION,
        SCHEMA_VERSION,
    )


def _calendar(sessions: tuple[int, ...]) -> CalendarTable:
    return CalendarTable(tuple(_calendar_row(session) for session in sessions))


def _vol_row(session: int, tau: int, value: float, phase: str = "open") -> VolRelRow:
    return VolRelRow(
        "primary_ewma78_permissive_expanding",
        session,
        tau - 300_000_000_000,
        tau,
        "08:30",
        phase,
        value,
        True,
        1.0,
        True,
        value,
        True,
        VolRelStatus.OK,
        None,
        "ok",
    )


def _threshold_fixture(prior_count: int = 60):
    sessions = tuple(20200101 + index for index in range(prior_count + 1))
    rows = []
    for index, session in enumerate(sessions[:-1]):
        count = 6 if index < 20 else 1
        value = 0.0 if index < 20 else 10.0
        for anchor in range(count):
            rows.append(_vol_row(session, session * 10_000 + anchor, value))
    current = sessions[-1]
    rows.append(_vol_row(current, current * 10_000, 999.0))
    return sessions, _calendar(sessions), VolRelTable(
        "primary_ewma78_permissive_expanding", tuple(rows)
    )


def test_arm_inventory_is_exactly_the_ten_frozen_ofat_arms():
    assert [config.order for config in ARM_CONFIGS] == list(range(10))
    assert [config.arm_id for config in ARM_CONFIGS] == [
        "primary_ewma78_permissive_expanding",
        "coverage_strict",
        "ewma39",
        "ewma156",
        "mad78",
        "threshold_rolling60",
        "threshold_shift_m05",
        "threshold_shift_m02",
        "threshold_shift_p02",
        "threshold_shift_p05",
    ]
    assert arm_config("mad78").scale_kind == "mad"
    with pytest.raises(SpineError, match="unknown Phase 7 arm_id"):
        arm_config("best_measured_arm")


def test_vol_rel_propagates_upstream_statuses_and_handles_zero_exactly():
    session = 20200102
    base_ts = int(
        datetime(2020, 1, 2, 8, 25, tzinfo=ZoneInfo("America/Chicago")).timestamp()
        * 1_000_000_000
    )
    scales = ScaleAnchorTable(
        "x",
        tuple(
            scale_anchor_row(
                arm_id="x",
                session_id=session,
                ts_event_ns=base_ts + index * 300_000_000_000,
                scale_stage="ewma",
                scale_value=value,
                scale_valid=valid,
            )
            for index, (value, valid) in enumerate(
                ((2.0, True), (0.0, True), (0.0, False), (2.0, True))
            )
        ),
    )
    profiles = []
    for index, scale in enumerate(scales.rows):
        profile_value = (4.0, 4.0, 4.0, 0.0)[index]
        # Keep the profile defined at index 2 so scale-stage precedence is
        # discriminated from a coincident seasonal failure.
        profile_valid = True
        profiles.append(
            SeasonalProfileRow(
                "x",
                session,
                scale.observation_bucket_ct,
                scale.session_phase,
                60,
                60,
                profile_value,
                profile_valid,
                profile_value,
                profile_valid,
                1.0,
                profile_value,
                profile_valid,
                SeasonalStatus.OK if profile_valid else SeasonalStatus.WARMUP,
                CALENDAR_VERSION,
                CALENDAR_SHA256,
                (),
            )
        )
    result = build_vol_rel(scales, SeasonalProfileTable("x", tuple(profiles)))
    assert result.rows[0].vol_rel == 0.5
    assert result.rows[0].vol_rel_status is VolRelStatus.OK
    assert result.rows[1].vol_rel == 0.0 and result.rows[1].vol_rel_valid
    assert not np.signbit(result.rows[1].vol_rel)
    assert result.rows[2].vol_rel_status is VolRelStatus.UPSTREAM_UNDEFINED
    assert result.rows[2].upstream_stage is UpstreamStage.EWMA
    assert result.rows[3].vol_rel_status is VolRelStatus.ZERO_SCALE
    assert not result.rows[3].vol_rel_valid


def test_thresholds_use_strictly_prior_session_equal_mass_not_anchor_equal_mass():
    sessions, calendar, vol_rel = _threshold_fixture()
    current = sessions[-1]
    table = build_thresholds(
        arm_config("primary_ewma78_permissive_expanding"),
        vol_rel,
        (current,),
        frozenset(sessions[:-1]),
        calendar,
    )
    row = table.lookup(current, "open")
    assert row.qualifying_prior_sessions == 60
    assert row.lower_threshold == 0.0
    assert row.upper_threshold == 10.0
    assert row.threshold_status is ThresholdStatus.OK
    assert all(session < current for session, _ in row.dependency_keys)

    values = np.asarray([item.vol_rel for item in vol_rel.rows if item.session_id < current])
    anchor_equal_upper = float(np.sort(values)[int(np.ceil((2.0 / 3.0) * len(values))) - 1])
    assert anchor_equal_upper == 0.0
    assert anchor_equal_upper != row.upper_threshold


def test_threshold_warmup_rolling_window_shifts_and_degenerate_ties():
    sessions, calendar, vol_rel = _threshold_fixture(59)
    current = sessions[-1]
    warmup = build_thresholds(
        arm_config("primary_ewma78_permissive_expanding"),
        vol_rel,
        (current,),
        frozenset(sessions[:-1]),
        calendar,
    ).lookup(current, "open")
    assert warmup.threshold_status is ThresholdStatus.INSUFFICIENT_THRESHOLD_HISTORY
    assert not warmup.threshold_valid

    assert arm_config("threshold_shift_m05").lower_probability == 1.0 / 3.0 - 0.05
    assert arm_config("threshold_shift_p05").upper_probability == 2.0 / 3.0 + 0.05

    tied_sessions = tuple(20210101 + index for index in range(61))
    tied_rows = tuple(
        _vol_row(session, session * 10_000, 1.0) for session in tied_sessions
    )
    tied = build_thresholds(
        arm_config("primary_ewma78_permissive_expanding"),
        VolRelTable("primary_ewma78_permissive_expanding", tied_rows),
        (tied_sessions[-1],),
        frozenset(tied_sessions[:-1]),
        _calendar(tied_sessions),
    ).lookup(tied_sessions[-1], "open")
    assert tied.lower_threshold == tied.upper_threshold == 1.0
    assert tied.threshold_status is ThresholdStatus.DEGENERATE_BOUNDARIES


def test_assignments_use_frozen_tie_boundaries_and_emit_every_category():
    session = 20200102
    rows = tuple(
        _vol_row(session, session * 10_000 + index, value)
        for index, value in enumerate((1.0, 2.0, 3.0))
    )
    thresholds = ThresholdTable(
        "primary_ewma78_permissive_expanding",
        tuple(
            ThresholdRow(
                "primary_ewma78_permissive_expanding",
                session,
                phase,
                "expanding",
                60,
                1.0 / 3.0,
                2.0 / 3.0,
                1.0,
                2.0,
                True,
                ThresholdStatus.OK,
                tuple((20190000 + index, index) for index in range(60)),
            )
            for phase in ("open", "morning", "midday", "afternoon", "close")
        ),
    )
    assignments = build_assignments(
        arm_config("primary_ewma78_permissive_expanding"),
        VolRelTable("primary_ewma78_permissive_expanding", rows),
        thresholds,
        _calendar((session,)),
    )
    assert [row.category_code for row in assignments.rows] == [0, 1, 2]
    assert [row.category_name for row in assignments.rows] == ["low", "mid", "high"]

    reversed_mutant = [2 if value <= 1.0 else 0 for value in (1.0, 2.0, 3.0)]
    assert reversed_mutant != [row.category_code for row in assignments.rows]


def test_cell_migration_and_undefined_fractions_are_descriptive_and_ordered():
    session = 20200102
    base = AssignmentRow(
        "primary",
        session,
        1,
        301,
        "08:30",
        "open",
        1.0,
        True,
        1.0,
        True,
        1.0,
        True,
        VolRelStatus.OK,
        None,
        1.0,
        2.0,
        ThresholdStatus.OK,
        0,
        "low",
        AssignmentStatus.OK,
        "regular",
        False,
        "ok",
    )
    primary = AssignmentTable(
        "primary",
        (
            base,
            replace(base, ts_event_ns=2, tau_ns=302, category_code=1, category_name="mid"),
            replace(
                base,
                ts_event_ns=3,
                tau_ns=303,
                vol_rel=0.0,
                vol_rel_valid=False,
                vol_rel_status=VolRelStatus.UPSTREAM_UNDEFINED,
                upstream_stage=UpstreamStage.SEASONAL,
                category_code=-1,
                category_name="undefined",
                assignment_status=AssignmentStatus.UPSTREAM_UNDEFINED,
            ),
        ),
    )
    alternative = AssignmentTable(
        "alternative",
        (
            replace(base, arm_id="alternative", category_code=1, category_name="mid"),
            replace(base, arm_id="alternative", ts_event_ns=2, tau_ns=302, category_code=1, category_name="mid"),
            replace(base, arm_id="alternative", ts_event_ns=3, tau_ns=303, category_code=2, category_name="high"),
        ),
    )
    migration = cell_migration(primary, alternative)
    assert len(migration.cells) == 16
    assert migration.common_defined == 2
    assert migration.changed_defined == 1
    assert migration.changed_fraction == 0.5
    assert migration.primary_undefined_alternative_defined == 1
    assert sum(cell.count for cell in migration.cells) == 3

    fractions = assignment_undefined_fractions(primary)
    assert len(fractions) == 1
    assert fractions[0].undefined_count == 1
    assert fractions[0].total_count == 3
    assert fractions[0].undefined_fraction == 1.0 / 3.0

    with pytest.raises(SpineError, match="supports differ"):
        cell_migration(primary, AssignmentTable("alternative", alternative.rows[:-1]))


def test_output_schemas_halt_on_incoherent_statuses_and_dependency_windows():
    sessions, calendar, vol_rel = _threshold_fixture()
    current = sessions[-1]
    with pytest.raises(SpineError, match="reserved for upstream-undefined"):
        VolRelTable(
            vol_rel.source_arm_id,
            (replace(vol_rel.rows[0], upstream_stage=UpstreamStage.SEASONAL),)
            + vol_rel.rows[1:],
        )

    thresholds = build_thresholds(
        arm_config("primary_ewma78_permissive_expanding"),
        vol_rel,
        (current,),
        frozenset(sessions[:-1]),
        calendar,
    )
    first = thresholds.rows[0]
    with pytest.raises(SpineError, match="current or future"):
        ThresholdTable(
            thresholds.arm_id,
            (replace(first, dependency_keys=first.dependency_keys + ((current, 1),)),)
            + thresholds.rows[1:],
        )

    current_vol_rel = VolRelTable(
        vol_rel.source_arm_id,
        tuple(row for row in vol_rel.rows if row.session_id == current),
    )
    assignment = build_assignments(
        arm_config("primary_ewma78_permissive_expanding"),
        current_vol_rel,
        thresholds,
        calendar,
    )
    with pytest.raises(SpineError, match="closed encoding"):
        AssignmentTable(
            assignment.arm_id,
            (replace(assignment.rows[0], category_code=True),) + assignment.rows[1:],
        )
