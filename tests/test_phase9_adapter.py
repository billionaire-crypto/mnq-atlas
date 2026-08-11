"""Exact-key witnesses for the read-only Phase 9 corpus adapter."""

from __future__ import annotations

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
