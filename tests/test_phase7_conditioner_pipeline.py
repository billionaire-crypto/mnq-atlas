"""Integrated ten-arm Phase 7 conditioner pipeline tests."""

from __future__ import annotations

import pytest

from mnq_lab import SpineError
from mnq_lab.conditioners.arms import ARM_CONFIGS
from mnq_lab.conditioners.pipeline import SCALE_SOURCE_ARMS, build_conditioner_pipeline
from mnq_lab.conditioners.status import AssignmentStatus, ThresholdStatus
from tests.phase7_pipeline_fixtures import synthetic_pipeline


@pytest.fixture(scope="module")
def built():
    return synthetic_pipeline(123)


def test_pipeline_emits_exact_fixed_arm_order_without_factorial_expansion(built):
    sessions, _, _, pipeline = built
    arm_ids = tuple(config.arm_id for config in ARM_CONFIGS)
    assert tuple(pipeline.seasonal_profiles) == SCALE_SOURCE_ARMS
    assert tuple(pipeline.vol_rel_tables) == SCALE_SOURCE_ARMS
    assert tuple(pipeline.threshold_tables) == arm_ids
    assert tuple(pipeline.assignment_tables) == arm_ids
    assert tuple(pipeline.migration_summaries) == arm_ids[1:]
    assert tuple(pipeline.undefined_fractions) == arm_ids
    assert len(pipeline.assignment_tables) == 10
    assert all(
        len(table.rows) == len(sessions)
        for table in pipeline.assignment_tables.values()
    )


def test_first_threshold_and_assignment_follow_sixty_prior_defined_vol_sessions(built):
    sessions, _, _, pipeline = built
    primary_thresholds = pipeline.threshold_tables[
        "primary_ewma78_permissive_expanding"
    ]
    primary_assignments = pipeline.assignment_tables[
        "primary_ewma78_permissive_expanding"
    ]
    assert (
        primary_thresholds.lookup(sessions[119], "open").threshold_status
        is ThresholdStatus.INSUFFICIENT_THRESHOLD_HISTORY
    )
    first = primary_thresholds.lookup(sessions[120], "open")
    assert first.qualifying_prior_sessions == 60
    assert first.threshold_valid
    assignment_by_session = {row.session_id: row for row in primary_assignments.rows}
    assert assignment_by_session[sessions[119]].assignment_status is AssignmentStatus.WARMUP
    assert assignment_by_session[sessions[120]].assignment_status is AssignmentStatus.OK


def test_rolling_arm_uses_exact_latest_sixty_and_shifted_arms_keep_frozen_probabilities(built):
    sessions, _, _, pipeline = built
    rolling = pipeline.threshold_tables["threshold_rolling60"].lookup(
        sessions[-1], "open"
    )
    expanding = pipeline.threshold_tables[
        "primary_ewma78_permissive_expanding"
    ].lookup(sessions[-1], "open")
    assert rolling.qualifying_prior_sessions == 60
    assert expanding.qualifying_prior_sessions == 62
    dependency_sessions = {session for session, _ in rolling.dependency_keys}
    assert min(dependency_sessions) > min(
        session for session, _ in expanding.dependency_keys
    )
    assert pipeline.threshold_tables["threshold_shift_m05"].lookup(
        sessions[-1], "open"
    ).lower_probability == 1.0 / 3.0 - 0.05
    assert pipeline.threshold_tables["threshold_shift_p05"].lookup(
        sessions[-1], "open"
    ).upper_probability == 2.0 / 3.0 + 0.05


def test_migration_and_strict_permissive_undefined_diagnostics_are_mandatory(built):
    _, _, _, pipeline = built
    strict = pipeline.migration_summaries["coverage_strict"]
    mad = pipeline.migration_summaries["mad78"]
    assert len(strict.cells) == len(mad.cells) == 16
    assert sum(cell.count for cell in strict.cells) == 123
    assert "coverage_strict" in pipeline.undefined_fractions
    assert "primary_ewma78_permissive_expanding" in pipeline.undefined_fractions


def test_pipeline_rejects_missing_or_reordered_scale_arm_inputs(built):
    sessions, tables, calendar, _ = built
    missing = dict(tables)
    missing.pop("mad78")
    with pytest.raises(SpineError, match="exact order"):
        build_conditioner_pipeline(
            missing,
            sessions,
            frozenset(sessions),
            calendar,
        )
    reordered = {key: tables[key] for key in reversed(tuple(tables))}
    with pytest.raises(SpineError, match="exact order"):
        build_conditioner_pipeline(
            reordered, sessions, frozenset(sessions), calendar
        )

    shortened = dict(tables)
    shortened["coverage_strict"] = type(tables["coverage_strict"])(
        "coverage_strict", tables["coverage_strict"].rows[:-1]
    )
    with pytest.raises(SpineError, match="anchor supports differ"):
        build_conditioner_pipeline(
            shortened, sessions, frozenset(sessions), calendar
        )

    with pytest.raises(SpineError, match="current sessions differ"):
        build_conditioner_pipeline(
            tables, sessions[:-1], frozenset(sessions), calendar
        )
