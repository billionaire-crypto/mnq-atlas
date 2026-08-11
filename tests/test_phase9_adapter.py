"""Exact-key witnesses for the read-only Phase 9 corpus adapter."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from mnq_lab import SpineError
from mnq_lab.conditioners.status import AssignmentStatus, ResetReason
from mnq_lab.phase9 import (
    DECLARED_ARM_IDS,
    ELIGIBILITY_COLUMNS,
    adapt_prevalence_input,
    anchor_observation_keys,
    measure_prevalence,
)
from mnq_lab.phase9.adapter import (
    _completion_frame_columns,
    _exclude_completion_sessions,
)


def _sources():
    arms = DECLARED_ARM_IDS[:2]
    labels = (
        pd.DatetimeIndex(
            ["2021-06-07 08:30", "2021-06-07 08:35"],
            tz="America/Chicago",
        )
        .tz_convert("UTC")
        .to_numpy(dtype="datetime64[ns]")
        .astype(np.int64)
    )
    tau, buckets, phases = anchor_observation_keys(labels)
    sessions = np.asarray([20210607, 20210607], dtype=np.int32)
    assignment = {
        "arm_id": np.repeat(np.asarray(arms, dtype="U64"), 2),
        "session_id": np.tile(sessions, 2),
        "ts_event_ns": np.tile(labels, 2),
        "tau_ns": np.tile(tau, 2),
        "observation_bucket_ct": np.tile(buckets, 2),
        "session_phase": np.tile(phases, 2),
        "category_code": np.asarray([0, 1, 2, 1], dtype=np.int8),
        "assignment_status": np.full(4, AssignmentStatus.OK.value, dtype="U32"),
    }
    reset = {
        "session_id": sessions,
        "ts_event_ns": labels,
        "tau_ns": tau,
        "reset_reason": np.asarray(
            [ResetReason.NONE.value, ResetReason.GAP_RESET.value], dtype="U16"
        ),
    }
    completion = {
        "session_id": sessions,
        "ts_event_ns": labels,
        "tau_ns": tau,
        "state_anchor": np.asarray([True, True], dtype=np.bool_),
    }
    for position, name in enumerate(ELIGIBILITY_COLUMNS):
        completion[name] = np.asarray(
            [True, position % 3 == 0], dtype=np.bool_
        )
    return arms, assignment, reset, completion


def test_exact_adapter_broadcasts_anchor_sources_without_reordering():
    arms, assignment, reset, completion = _sources()
    adapted = adapt_prevalence_input(
        assignment, reset, completion, declared_arm_ids=arms
    )
    counts = adapted.reconciliation
    assert counts.anchor_count == 2
    assert counts.arm_count == 2
    assert counts.assignment_rows == 4
    assert counts.reset_rows == 2
    assert counts.completion_rows == 2
    assert counts.matched_anchor_rows == 2
    assert counts.broadcast_rows == 4
    assert counts.excluded_session_count == 0
    assert counts.excluded_completion_rows == 0
    np.testing.assert_array_equal(adapted.source.arm_id, assignment["arm_id"])
    np.testing.assert_array_equal(
        adapted.source.reset_reason,
        np.tile(reset["reset_reason"], 2),
    )
    np.testing.assert_array_equal(
        adapted.source.state_anchor,
        np.tile(completion["state_anchor"], 2),
    )
    for name, values in adapted.source.eligibility_columns:
        np.testing.assert_array_equal(values, np.tile(completion[name], 2))
    result = measure_prevalence(adapted.source, declared_arm_ids=arms)
    assert result.summary.row_count == len(arms) * 3
    assert result.events is not None and result.events.row_count == 4


def test_exact_adapter_rejects_five_minute_tolerance_match():
    arms, assignment, reset, completion = _sources()
    completion["tau_ns"] = completion["tau_ns"].copy()
    completion["tau_ns"][1] += 300_000_000_000
    with pytest.raises(SpineError, match="exact-key join mismatch"):
        adapt_prevalence_input(
            assignment, reset, completion, declared_arm_ids=arms
        )


@pytest.mark.parametrize("source_name", ("reset", "completion"))
def test_exact_adapter_rejects_unmatched_rows_in_either_anchor_source(source_name):
    arms, assignment, reset, completion = _sources()
    target = reset if source_name == "reset" else completion
    for name in tuple(target):
        target[name] = target[name][:-1]
    with pytest.raises(SpineError, match="row-count mismatch"):
        adapt_prevalence_input(
            assignment, reset, completion, declared_arm_ids=arms
        )


def test_exact_adapter_rejects_assignment_key_mismatch_without_drop_or_fill():
    arms, assignment, reset, completion = _sources()
    assignment["tau_ns"] = assignment["tau_ns"].copy()
    assignment["tau_ns"][2] += 1
    with pytest.raises(SpineError, match=r"assignment\[.*exact-key join mismatch|exact-key join mismatch"):
        adapt_prevalence_input(
            assignment, reset, completion, declared_arm_ids=arms
        )


def test_exact_adapter_rejects_duplicate_anchor_keys():
    arms, assignment, reset, completion = _sources()
    for target in (reset, completion):
        target["session_id"] = target["session_id"].copy()
        target["tau_ns"] = target["tau_ns"].copy()
        target["ts_event_ns"] = target["ts_event_ns"].copy()
    reset["tau_ns"][1] = reset["tau_ns"][0]
    reset["ts_event_ns"][1] = reset["ts_event_ns"][0]
    with pytest.raises(SpineError, match="duplicate exact key"):
        adapt_prevalence_input(
            assignment, reset, completion, declared_arm_ids=arms
        )


def test_exact_adapter_rejects_arm_block_order_change():
    arms, assignment, reset, completion = _sources()
    assignment["arm_id"] = assignment["arm_id"].copy()
    assignment["arm_id"][0] = arms[1]
    with pytest.raises(SpineError, match="arm/order mismatch"):
        adapt_prevalence_input(
            assignment, reset, completion, declared_arm_ids=arms
        )


def test_completion_frame_bar_label_maps_to_ts_event_ns():
    _, _, _, completion = _sources()
    frame_columns = {
        "session_id": completion["session_id"],
        "anchor_label_ns": completion["ts_event_ns"],
        "tau_ns": completion["tau_ns"],
        "state_anchor": completion["state_anchor"],
        **{name: completion[name] for name in ELIGIBILITY_COLUMNS},
    }
    frame = pd.DataFrame(frame_columns)
    converted = _completion_frame_columns(frame)
    np.testing.assert_array_equal(
        converted["ts_event_ns"], frame_columns["anchor_label_ns"]
    )
    assert "anchor_label_ns" not in converted


def _completion_frame_fixture_with_prior_session():
    _, _, _, completion = _sources()
    prior_session = np.asarray([20210606, 20210606], dtype=np.int32)
    prior_tau = completion["tau_ns"] - np.int64(86_400_000_000_000)
    frame_columns = {
        "session_id": np.concatenate((prior_session, completion["session_id"])),
        "anchor_label_ns": np.concatenate(
            (prior_tau - np.int64(300_000_000_000), completion["ts_event_ns"])
        ),
        "tau_ns": np.concatenate((prior_tau, completion["tau_ns"])),
        "state_anchor": np.concatenate(
            (np.ones(2, dtype=np.bool_), completion["state_anchor"])
        ),
        **{
            name: np.concatenate((np.ones(2, dtype=np.bool_), completion[name]))
            for name in ELIGIBILITY_COLUMNS
        },
    }
    return pd.DataFrame(frame_columns)


def _assert_exclusion_counts(reconciliation, expected_sessions, expected_rows):
    assert reconciliation.excluded_session_count == expected_sessions
    assert reconciliation.excluded_completion_rows == expected_rows


def test_excluded_session_reconciliation_reports_nonzero_and_zero_counts():
    arms, assignment, reset, _ = _sources()
    frame = _completion_frame_fixture_with_prior_session()
    filtered, session_count, row_count = _exclude_completion_sessions(
        frame, (20210606,)
    )
    assert set(filtered["session_id"]) == {20210607}
    adapted = adapt_prevalence_input(
        assignment,
        reset,
        _completion_frame_columns(filtered),
        declared_arm_ids=arms,
        excluded_session_count=session_count,
        excluded_completion_rows=row_count,
    )
    _assert_exclusion_counts(adapted.reconciliation, 1, 2)

    unchanged, no_session_count, no_row_count = _exclude_completion_sessions(
        filtered, ()
    )
    no_exclusions = adapt_prevalence_input(
        assignment,
        reset,
        _completion_frame_columns(unchanged),
        declared_arm_ids=arms,
        excluded_session_count=no_session_count,
        excluded_completion_rows=no_row_count,
    )
    _assert_exclusion_counts(no_exclusions.reconciliation, 0, 0)


def test_excluded_session_counter_negative_always_zero_mutant_is_rejected():
    arms, assignment, reset, _ = _sources()
    frame = _completion_frame_fixture_with_prior_session()
    filtered, session_count, row_count = _exclude_completion_sessions(
        frame, (20210606,)
    )
    adapted = adapt_prevalence_input(
        assignment,
        reset,
        _completion_frame_columns(filtered),
        declared_arm_ids=arms,
        excluded_session_count=session_count,
        excluded_completion_rows=row_count,
    )
    always_zero = replace(
        adapted.reconciliation,
        excluded_session_count=0,
        excluded_completion_rows=0,
    )
    with pytest.raises(AssertionError):
        _assert_exclusion_counts(always_zero, 1, 2)
