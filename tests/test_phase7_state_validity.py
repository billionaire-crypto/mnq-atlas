"""Descriptive state-validity panel and RHS isolation tests."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.conditioners.assignments import (
    AssignmentRow,
    AssignmentStatus,
    ThresholdStatus,
    VolRelStatus,
)
from mnq_lab.conditioners.state_validity import (
    ArmStateDiagnostic,
    METRIC_ORDER,
    NON_OK_STATUS_ORDER,
    StateAnchorDiagnostic,
    _runs_and_transitions,
    average_rank_spearman,
    build_state_validity_panel,
)
from tests.phase7_pipeline_fixtures import synthetic_pipeline


def _diagnostics(sessions, pipeline):
    output = []
    anchors = pipeline.assignment_tables[
        "primary_ewma78_permissive_expanding"
    ].rows
    for index, (session, anchor) in enumerate(zip(sessions, anchors, strict=True)):
        statuses = () if index >= 120 else ("assignment_warmup", "assignment_undefined")
        output.append(
            StateAnchorDiagnostic(
                session,
                anchor.tau_ns,
                4 if index % 3 == 0 else 5,
                index % 2 == 0,
                index % 3 != 0,
                index % 5 != 0,
            )
        )
    return tuple(output)


def _arm_diagnostics(pipeline):
    output = []
    for arm_id, table in pipeline.assignment_tables.items():
        for index, row in enumerate(table.rows):
            statuses = () if row.assignment_status is AssignmentStatus.OK else (
                "assignment_warmup"
                if row.assignment_status is AssignmentStatus.WARMUP
                else "assignment_upstream_undefined",
                "assignment_undefined",
            )
            output.append(
                ArmStateDiagnostic(
                    arm_id,
                    row.session_id,
                    row.tau_ns,
                    arm_id == "coverage_strict" and index in {20, 70},
                    statuses,
                )
            )
    return tuple(output)


def test_panel_emits_all_metrics_in_fixed_non_measurement_order():
    sessions, _, _, pipeline = synthetic_pipeline(123)
    panel = build_state_validity_panel(
        pipeline, _diagnostics(sessions, pipeline), _arm_diagnostics(pipeline)
    )
    seen = tuple(dict.fromkeys(row.metric for row in panel.rows))
    assert seen == METRIC_ORDER
    assert not any("score" in row.detail or "preferred" in row.detail for row in panel.rows)
    assert any(row.metric == "transition_entropy" and not row.value_valid for row in panel.rows)
    assert all(
        row.status == "deferred_missing_versioned_input"
        and row.count == 0
        and not row.value_valid
        for row in panel.rows
        if row.metric == "liquidity_era_correlation"
    )


def test_average_ranks_and_transition_entropy_mechanism_are_discriminating():
    correlation, valid = average_rank_spearman([0, 0, 1, 2], [1, 2, 2, 4])
    assert valid
    # Independent average-rank oracle: [1.5,1.5,3,4] and [1,2.5,2.5,4].
    assert correlation == pytest.approx(0.8333333333333334)
    assert not average_rank_spearman([1, 1], [0, 1])[1]

    base = AssignmentRow(
        "x", 20200102, 0, 300_000_000_000, "08:30", "open",
        1.0, True, 1.0, True, 1.0, True, VolRelStatus.OK, None,
        1.0, 2.0, ThresholdStatus.OK, 0, "low", AssignmentStatus.OK,
        "regular", False, "ok",
    )
    rows = (
        base,
        replace(base, ts_event_ns=300_000_000_000, tau_ns=600_000_000_000),
        replace(base, ts_event_ns=600_000_000_000, tau_ns=900_000_000_000, category_code=1, category_name="mid"),
        replace(base, ts_event_ns=900_000_000_000, tau_ns=1_200_000_000_000, category_code=1, category_name="mid"),
    )
    diagnostics = {
        (row.session_id, row.tau_ns): StateAnchorDiagnostic(
            row.session_id, row.tau_ns, 5, True, True, True,
        )
        for row in rows
    }
    arm_diagnostics = {
        key: ArmStateDiagnostic(
            "primary_ewma78_permissive_expanding",
            key[0],
            key[1],
            key[1] == 900_000_000_000,
            (),
        )
        for key in diagnostics
    }
    runs, transitions = _runs_and_transitions(rows, arm_diagnostics)
    assert runs == (2, 2)
    assert transitions.tolist() == [[1, 0, 0], [0, 1, 0], [0, 0, 0]]

    bridged = dict(arm_diagnostics)
    bridged[(20200102, 900_000_000_000)] = replace(
        arm_diagnostics[(20200102, 900_000_000_000)], reset_before=False
    )
    _, mutant = _runs_and_transitions(rows, bridged)
    assert mutant[0, 1] == 1


def test_completion_rhs_changes_panel_only_and_never_assignments():
    sessions, _, _, pipeline = synthetic_pipeline(123)
    original_assignments = tuple(
        table.rows for table in pipeline.assignment_tables.values()
    )
    diagnostics = _diagnostics(sessions, pipeline)
    changed = tuple(
        replace(row, outcome_complete_h60=not row.outcome_complete_h60)
        for row in diagnostics
    )
    arm_diagnostics = _arm_diagnostics(pipeline)
    first = build_state_validity_panel(pipeline, diagnostics, arm_diagnostics)
    second = build_state_validity_panel(pipeline, changed, arm_diagnostics)
    assert tuple(table.rows for table in pipeline.assignment_tables.values()) == original_assignments
    first_h60 = tuple(row for row in first.rows if row.horizon == "h60")
    second_h60 = tuple(row for row in second.rows if row.horizon == "h60")
    assert first_h60 != second_h60


def test_diagnostics_are_exact_support_and_status_vocabulary_is_closed():
    sessions, _, _, pipeline = synthetic_pipeline(123)
    diagnostics = _diagnostics(sessions, pipeline)
    with pytest.raises(SpineError, match="support"):
        build_state_validity_panel(
            pipeline, diagnostics[:-1], _arm_diagnostics(pipeline)
        )
    with pytest.raises(SpineError, match="statuses"):
        replace(
            _arm_diagnostics(pipeline)[0],
            non_ok_stage_statuses=("invented_state",),
        )
    assert "assignment_undefined" in NON_OK_STATUS_ORDER
