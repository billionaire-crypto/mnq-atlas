"""Output-identity witnesses for the Phase 8 bootstrap performance engine."""

from __future__ import annotations

import numpy as np
import pytest

from mnq_lab.phase8 import uncertainty as uncertainty_module
from mnq_lab.phase8.diagnostics import status_decision
from mnq_lab.phase8.uncertainty import (
    BootstrapInteractionRequest,
    BootstrapIntervalRequest,
    BootstrapQuantileTerm,
    distinct_bootstrap_evaluations,
    joint_bootstrap_intervals,
    joint_bootstrap_intervals_oracle,
)


def _ok():
    return status_decision(
        degenerate_baseline=False,
        insufficient_anchors=False,
        insufficient_completion=False,
        insufficient_overlap=False,
    )


def _identity_fixture():
    groups = np.repeat(np.arange(6, dtype=np.int32), 5)
    base = np.asarray([-4, -4, 0, 9, 9] * 6, dtype=np.int32)
    all_rows = np.ones(30, dtype=np.bool_)
    weights = np.asarray(
        [1e-12, 1e-6, 1.0, 1e6, 1e7] * 6,
        dtype=np.float64,
    )
    weights /= weights.sum()
    terms = [
        BootstrapQuantileTerm(f"shared-{stat}", base, all_rows, weights, stat)
        for stat in ("q50", "q75", "q90")
    ]
    for index, offset in enumerate((0, 3, 7, 11)):
        mask = np.zeros(30, dtype=np.bool_)
        mask[index::5] = True
        local_weights = np.zeros(30, dtype=np.float64)
        local_weights[mask] = 1.0 / 6.0
        terms.append(
            BootstrapQuantileTerm(
                f"interaction-{index}",
                base + np.int32(offset),
                mask,
                local_weights,
                "q90",
            )
        )
    requests = (
        BootstrapIntervalRequest("level-q50", "shared-q50", None, _ok()),
        BootstrapIntervalRequest("level-q75", "shared-q75", None, _ok()),
        BootstrapIntervalRequest(
            "q90-minus-q50", "shared-q90", "shared-q50", _ok()
        ),
        BootstrapInteractionRequest(
            "four-term-interaction",
            tuple(f"interaction-{index}" for index in range(4)),
            "ok",
        ),
    )
    return groups, tuple(terms), requests


def test_optimized_engine_is_exactly_equal_to_untouched_end_to_end_oracle(monkeypatch):
    monkeypatch.setattr(uncertainty_module, "DRAWS_PER_BLOCK_LENGTH", 999)
    groups, terms, requests = _identity_fixture()

    oracle = joint_bootstrap_intervals_oracle(groups, terms, requests)
    optimized = joint_bootstrap_intervals(groups, terms, requests)
    assert optimized == oracle


def test_production_sized_process_path_is_exactly_equal_to_untouched_oracle(
    monkeypatch,
):
    monkeypatch.setattr(uncertainty_module, "DRAWS_PER_BLOCK_LENGTH", 999)
    groups = np.repeat(np.arange(6, dtype=np.int32), 700)
    values = np.tile(np.arange(700, dtype=np.int32), 6)
    masks = []
    terms = []
    requests = []
    for term_index, offset in enumerate((0, 1)):
        mask = np.zeros(groups.size, dtype=np.bool_)
        mask[offset::700] = True
        weights = np.zeros(groups.size, dtype=np.float64)
        weights[mask] = 1.0 / 6.0
        term_id = f"process-path-{term_index}"
        terms.append(
            BootstrapQuantileTerm(
                term_id,
                values + np.int32(offset),
                mask,
                weights,
                "q90",
            )
        )
        requests.append(
            BootstrapIntervalRequest(
                f"process-request-{term_index}", term_id, None, _ok()
            )
        )
        masks.append(mask)
    assert groups.size > 4_096
    assert all(np.count_nonzero(mask) == 6 for mask in masks)

    oracle = joint_bootstrap_intervals_oracle(
        groups, tuple(terms), tuple(requests)
    )
    optimized = joint_bootstrap_intervals(
        groups, tuple(terms), tuple(requests)
    )
    assert optimized == oracle


def test_three_statistics_collapse_to_one_distinct_support_evaluation():
    groups, terms, _ = _identity_fixture()
    del groups
    assert distinct_bootstrap_evaluations(terms[:3]) == 1
    assert distinct_bootstrap_evaluations(terms) == 5


def test_distinct_evaluations_ignore_values_outside_the_declared_support():
    mask = np.asarray([True, False, True, False], dtype=np.bool_)
    weights = np.asarray([0.5, 0.0, 0.5, 0.0])
    first = BootstrapQuantileTerm(
        "outside-first",
        np.asarray([1, -2_000_000_000, 9, 2_000_000_000], dtype=np.int32),
        mask,
        weights,
        "q50",
    )
    second = BootstrapQuantileTerm(
        "outside-second",
        np.asarray([1, 777, 9, -888], dtype=np.int32),
        mask,
        weights,
        "q90",
    )
    assert distinct_bootstrap_evaluations((first, second)) == 1


def test_optimized_engine_passes_only_eligible_rows_to_quantile_evaluation(
    monkeypatch,
):
    monkeypatch.setattr(uncertainty_module, "DRAWS_PER_BLOCK_LENGTH", 999)
    groups = np.repeat(np.arange(2), 50)
    mask = np.zeros(100, dtype=np.bool_)
    mask[[0, 50]] = True
    weights = np.zeros(100)
    weights[mask] = 0.5
    term = BootstrapQuantileTerm(
        "two-eligible-rows",
        np.arange(100, dtype=np.int32),
        mask,
        weights,
        "q50",
    )
    request = BootstrapIntervalRequest("level", term.term_id, None, _ok())
    seen_sizes = set()
    original = uncertainty_module.weighted_quantile_ticks

    def quantile_spy(prepared, supplied_weights, statistic):
        seen_sizes.add(prepared.prepared.source_size)
        assert len(supplied_weights) == 2
        return original(prepared, supplied_weights, statistic)

    monkeypatch.setattr(uncertainty_module, "weighted_quantile_ticks", quantile_spy)
    joint_bootstrap_intervals(groups, (term,), (request,))
    assert seen_sizes == {2}


def test_frozen_draw_count_is_19996_independent_of_term_and_request_count(monkeypatch):
    groups = np.asarray([0, 1], dtype=np.int32)
    mask = np.ones(2, dtype=np.bool_)
    weights = np.asarray([0.5, 0.5])
    terms = tuple(
        BootstrapQuantileTerm(
            f"term-{stat}",
            np.asarray([1, 2], dtype=np.int32),
            mask,
            weights,
            stat,
        )
        for stat in ("q50", "q75", "q90")
    )
    requests = tuple(
        BootstrapIntervalRequest(f"request-{index}", term.term_id, None, _ok())
        for index, term in enumerate(terms)
    )
    calls = 0
    original = uncertainty_module.stationary_group_resample

    def plan_spy(group_ids, block_length, rng):
        nonlocal calls
        calls += 1
        return original(group_ids, block_length, rng)

    monkeypatch.setattr(uncertainty_module, "stationary_group_resample", plan_spy)
    joint_bootstrap_intervals(groups, terms, requests)
    assert calls == 4 * 4_999 == 19_996
