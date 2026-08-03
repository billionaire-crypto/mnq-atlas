"""Joint-bootstrap witnesses for Phase 8 four-term interactions."""

from __future__ import annotations

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.phase8 import uncertainty as uncertainty_module
from mnq_lab.phase8.uncertainty import (
    BootstrapInteractionRequest,
    BootstrapIntervalRequest,
    BootstrapQuantileTerm,
    joint_bootstrap_intervals,
)


def _joint_interaction_fixture():
    group_ids = np.repeat(np.asarray([10, 11, 12], dtype=np.int64), 4)
    values_by_term = (
        (0, 100, 200),
        (-10, 90, 190),
        (5, 105, 205),
        (15, 115, 215),
    )
    term_ids = ("pv", "p_mid", "midday_v", "midday_mid")
    terms = []
    for offset, (term_id, values) in enumerate(
        zip(term_ids, values_by_term, strict=True)
    ):
        mask = np.zeros(group_ids.size, dtype=np.bool_)
        mask[offset::4] = True
        full_values = np.zeros(group_ids.size, dtype=np.int32)
        full_values[mask] = values
        terms.append(
            BootstrapQuantileTerm(
                term_id,
                full_values,
                mask,
                np.where(mask, 1 / 3, 0.0),
                "q50",
            )
        )
    requests = (
        BootstrapInteractionRequest("interaction", term_ids, "ok"),
        *(
            BootstrapIntervalRequest(f"level_{term_id}", term_id, None, _ok())
            for term_id in term_ids
        ),
    )
    return group_ids, tuple(terms), requests


def _ok():
    from mnq_lab.phase8.diagnostics import status_decision

    return status_decision(
        degenerate_baseline=False,
        insufficient_anchors=False,
        insufficient_completion=False,
        insufficient_overlap=False,
    )


def test_interaction_is_recomputed_inside_the_existing_joint_bootstrap(monkeypatch):
    monkeypatch.setattr(uncertainty_module, "DRAWS_PER_BLOCK_LENGTH", 999)
    group_ids, terms, requests = _joint_interaction_fixture()
    plan_calls = 0
    quantile_calls = 0
    original_plan = uncertainty_module.stationary_group_resample
    original_quantile = uncertainty_module.weighted_quantile_ticks

    def plan_spy(groups, block_length, rng):
        nonlocal plan_calls
        plan_calls += 1
        return original_plan(groups, block_length, rng)

    def quantile_spy(values, weights, statistic):
        nonlocal quantile_calls
        quantile_calls += 1
        return original_quantile(values, weights, statistic)

    monkeypatch.setattr(uncertainty_module, "stationary_group_resample", plan_spy)
    monkeypatch.setattr(uncertainty_module, "weighted_quantile_ticks", quantile_spy)
    result = joint_bootstrap_intervals(group_ids, terms, requests)

    assert plan_calls == 4 * 999
    assert quantile_calls == 4 * 4 * 999
    by_id = {request.request_id: request for request in result.requests}
    interaction = by_id["interaction"]
    assert all(
        (row.ci_lower_ticks, row.ci_upper_ticks) == (20, 20)
        for row in interaction.intervals
    )

    marginal_mutants = []
    for block_index in range(4):
        pv = by_id["level_pv"].intervals[block_index]
        p_mid = by_id["level_p_mid"].intervals[block_index]
        midday_v = by_id["level_midday_v"].intervals[block_index]
        midday_mid = by_id["level_midday_mid"].intervals[block_index]
        marginal_mutants.append(
            (
                pv.ci_lower_ticks
                - p_mid.ci_upper_ticks
                - midday_v.ci_upper_ticks
                + midday_mid.ci_lower_ticks,
                pv.ci_upper_ticks
                - p_mid.ci_lower_ticks
                - midday_v.ci_lower_ticks
                + midday_mid.ci_upper_ticks,
            )
        )
    assert any(interval != (20, 20) for interval in marginal_mutants)


def test_interaction_request_rejects_invalid_status_and_non_four_term_shape():
    with pytest.raises(SpineError, match="only ok interaction rows"):
        BootstrapInteractionRequest(
            "thin",
            ("pv", "p_mid", "midday_v", "midday_mid"),
            "insufficient_interaction_support",
        )
    with pytest.raises(SpineError, match="exactly four distinct"):
        BootstrapInteractionRequest(
            "pairwise_mutant",
            ("pv", "p_mid", "pv", "midday_mid"),
            "ok",
        )


def test_interaction_request_rejects_fewer_than_four_terms():
    with pytest.raises(SpineError, match="exactly four distinct"):
        BootstrapInteractionRequest(
            "three_term_mutant",
            ("pv", "p_mid", "midday_v"),
            "ok",
        )
