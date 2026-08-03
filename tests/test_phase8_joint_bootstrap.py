"""Independent synthetic witnesses for Phase 8 preregistration step 5."""

from __future__ import annotations

import copy
import inspect

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.core.bootstrap import StationaryGroupResamplePlan
from mnq_lab.phase8 import uncertainty as uncertainty_module
from mnq_lab.phase8.diagnostics import status_decision
from mnq_lab.phase8.uncertainty import (
    BLOCK_LENGTHS,
    CONFIDENCE_LEVEL,
    CONDITIONER_UNCERTAINTY_DISCLOSURE,
    DRAWS_PER_BLOCK_LENGTH,
    HISTORICAL_MIXTURE_DISCLOSURE,
    PRIMARY_BLOCK_LENGTH,
    ROOT_ENTROPY,
    WEIGHT_ESS_DISCLOSURE,
    BootstrapIntervalRequest,
    BootstrapQuantileTerm,
    bootstrap_contract,
    interval_conclusion_reversal,
    joint_bootstrap_intervals,
)


def _ok():
    return status_decision(
        degenerate_baseline=False,
        insufficient_anchors=False,
        insufficient_completion=False,
        insufficient_overlap=False,
    )


def _paired_fixture():
    group_ids = np.repeat(np.asarray([10, 11, 12], dtype=np.int64), 2)
    values = np.asarray([0, -10, 100, 90, 200, 190], dtype=np.int32)
    target_mask = np.asarray([True, False, True, False, True, False])
    baseline_mask = ~target_mask
    target_weights = np.where(target_mask, 1 / 3, 0.0)
    baseline_weights = np.where(baseline_mask, 1 / 3, 0.0)
    terms = (
        BootstrapQuantileTerm(
            "target",
            values,
            target_mask,
            target_weights,
            "q50",
        ),
        BootstrapQuantileTerm(
            "baseline",
            values,
            baseline_mask,
            baseline_weights,
            "q50",
        ),
    )
    requests = (
        BootstrapIntervalRequest("paired_contrast", "target", "baseline", _ok()),
        BootstrapIntervalRequest("target_level", "target", None, _ok()),
        BootstrapIntervalRequest("baseline_level", "baseline", None, _ok()),
    )
    return group_ids, terms, requests


def test_phase8_bootstrap_contract_is_exact_and_has_no_caller_rng_or_draw_count():
    assert ROOT_ENTROPY == (20260801, 8, 13, 1)
    assert BLOCK_LENGTHS == (1, 5, 10, 20)
    assert DRAWS_PER_BLOCK_LENGTH == 4_999
    assert CONFIDENCE_LEVEL == 0.95
    assert PRIMARY_BLOCK_LENGTH == 5

    contract = bootstrap_contract()
    assert contract.root_entropy == ROOT_ENTROPY
    assert contract.block_lengths == BLOCK_LENGTHS
    assert contract.draws_per_block_length == DRAWS_PER_BLOCK_LENGTH
    assert contract.confidence_level == CONFIDENCE_LEVEL
    assert contract.primary_block_length == PRIMARY_BLOCK_LENGTH
    assert contract.child_spawn_keys == ((0,), (1,), (2,), (3,))
    assert contract.bit_generator == "PCG64"
    assert contract.scheme == "whole_session_stationary"
    assert contract.truncate_partial_session is False
    assert contract.early_stopping is False

    parameters = inspect.signature(joint_bootstrap_intervals).parameters
    assert "draws" not in parameters
    assert "rng" not in parameters
    assert "block_lengths" not in parameters


def test_reordered_block_constants_fail_instead_of_selecting_a_sensitivity(tmp_path):
    constants = tmp_path / "reordered-blocks.yaml"
    constants.write_text(
        "bootstrap:\n"
        "  scheme: whole_session_stationary\n"
        "  mean_block_sessions_primary: 5\n"
        "  block_sensitivity: [1, 10, 5, 20]\n"
        "  truncate_partial_session: false\n",
        encoding="utf-8",
    )
    with pytest.raises(SpineError, match="Phase 8 block lengths"):
        bootstrap_contract(constants)


def test_one_global_plan_per_replicate_serves_all_terms_and_requests(monkeypatch):
    monkeypatch.setattr(uncertainty_module, "DRAWS_PER_BLOCK_LENGTH", 999)
    group_ids, terms, requests = _paired_fixture()
    snapshots = tuple(
        (term.values.tobytes(), term.eligibility_mask.tobytes(), term.weights.tobytes())
        for term in terms
    )
    plan_calls = 0
    composition_calls = 0
    quantile_calls = 0
    seen_group_vectors = set()
    first_rng_states = []
    original_plan = uncertainty_module.stationary_group_resample
    original_apply = uncertainty_module.apply_group_multiplicities
    original_quantile = uncertainty_module.weighted_quantile_ticks

    def plan_spy(supplied_groups, mean_block_groups, rng):
        nonlocal plan_calls
        if plan_calls % 999 == 0:
            first_rng_states.append(copy.deepcopy(rng.bit_generator.state))
        plan_calls += 1
        seen_group_vectors.add(tuple(supplied_groups))
        return original_plan(supplied_groups, mean_block_groups, rng)

    def apply_spy(supplied_groups, supplied_weights, plan):
        nonlocal composition_calls
        composition_calls += 1
        return original_apply(supplied_groups, supplied_weights, plan)

    def quantile_spy(values, weights, statistic):
        nonlocal quantile_calls
        quantile_calls += 1
        return original_quantile(values, weights, statistic)

    monkeypatch.setattr(uncertainty_module, "stationary_group_resample", plan_spy)
    monkeypatch.setattr(uncertainty_module, "apply_group_multiplicities", apply_spy)
    monkeypatch.setattr(uncertainty_module, "weighted_quantile_ticks", quantile_spy)

    result = joint_bootstrap_intervals(group_ids, terms, requests)

    assert plan_calls == 999 * 4
    assert composition_calls == 999 * 4
    assert quantile_calls == len(terms) * 999 * 4
    assert seen_group_vectors == {tuple(group_ids)}
    assert len(first_rng_states) == 4
    children = np.random.SeedSequence(ROOT_ENTROPY).spawn(4)
    expected_states = [
        np.random.Generator(np.random.PCG64(child)).bit_generator.state
        for child in children
    ]
    assert first_rng_states == expected_states
    assert tuple(
        (term.values.tobytes(), term.eligibility_mask.tobytes(), term.weights.tobytes())
        for term in terms
    ) == snapshots

    by_id = {item.request_id: item for item in result.requests}
    paired = by_id["paired_contrast"]
    assert tuple(row.mean_block_sessions for row in paired.intervals) == BLOCK_LENGTHS
    assert tuple(row.is_primary for row in paired.intervals) == (
        False,
        True,
        False,
        False,
    )
    assert all(
        (row.ci_lower_ticks, row.ci_upper_ticks) == (10, 10)
        for row in paired.intervals
    )
    assert not paired.block_5_10_reversal

    target = by_id["target_level"]
    baseline = by_id["baseline_level"]
    marginal_endpoint_mutants = tuple(
        (
            target_row.ci_lower_ticks - baseline_row.ci_upper_ticks,
            target_row.ci_upper_ticks - baseline_row.ci_lower_ticks,
        )
        for target_row, baseline_row in zip(
            target.intervals, baseline.intervals, strict=True
        )
    )
    assert any(mutant != (10, 10) for mutant in marginal_endpoint_mutants)

    for request_result in result.requests:
        for row in request_result.intervals:
            assert row.historical_mixture_disclosure == HISTORICAL_MIXTURE_DISCLOSURE
            assert (
                row.conditioner_uncertainty_disclosure
                == CONDITIONER_UNCERTAINTY_DISCLOSURE
            )
            assert row.weight_ess_disclosure == WEIGHT_ESS_DISCLOSURE


def test_zero_mass_term_halts_at_first_replicate_without_retry(monkeypatch):
    monkeypatch.setattr(uncertainty_module, "DRAWS_PER_BLOCK_LENGTH", 999)
    calls = 0
    plan = StationaryGroupResamplePlan(
        ordered_group_labels=(0, 1),
        group_count=2,
        mean_block_groups=1.0,
        restart_probability=1.0,
        selected_positions=(1, 1),
        multiplicities=(0, 2),
        block_start_flags=(True, True),
        restart_count=1,
    )

    def zero_support_plan(group_ids, mean_block_groups, rng):
        nonlocal calls
        calls += 1
        return plan

    monkeypatch.setattr(
        uncertainty_module, "stationary_group_resample", zero_support_plan
    )
    term = BootstrapQuantileTerm(
        "only_session_zero",
        np.asarray([5, 9], dtype=np.int32),
        np.asarray([True, False]),
        np.asarray([1.0, 0.0]),
        "q50",
    )
    request = BootstrapIntervalRequest(
        "absolute", "only_session_zero", None, _ok()
    )

    with pytest.raises(
        SpineError,
        match=r"block length 1, replicate 0, term 'only_session_zero'",
    ):
        joint_bootstrap_intervals(np.asarray([0, 1]), (term,), (request,))
    assert calls == 1


def test_non_ok_request_is_rejected_before_any_resample(monkeypatch):
    calls = 0

    def forbidden_plan(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("resampling must not begin")

    monkeypatch.setattr(
        uncertainty_module, "stationary_group_resample", forbidden_plan
    )
    term = BootstrapQuantileTerm(
        "term",
        np.asarray([1], dtype=np.int32),
        np.asarray([True]),
        np.asarray([1.0]),
        "q50",
    )
    invalid = status_decision(
        degenerate_baseline=False,
        insufficient_anchors=True,
        insufficient_completion=False,
        insufficient_overlap=False,
    )
    request = BootstrapIntervalRequest("row", "term", None, invalid)

    with pytest.raises(SpineError, match="only ok point rows"):
        joint_bootstrap_intervals(np.asarray([0]), (term,), (request,))
    assert calls == 0


def test_nonintegral_interval_endpoint_halts_instead_of_rounding(monkeypatch):
    monkeypatch.setattr(uncertainty_module, "DRAWS_PER_BLOCK_LENGTH", 999)
    group_ids, terms, requests = _paired_fixture()
    monkeypatch.setattr(
        uncertainty_module,
        "percentile_interval",
        lambda replicates, confidence_level: (1.5, 10.0),
    )

    with pytest.raises(SpineError, match="non-integral interval endpoint"):
        joint_bootstrap_intervals(group_ids, terms, requests[:1])


def test_block_5_10_reversal_is_descriptive_and_not_triggered_by_zero_overlap():
    assert interval_conclusion_reversal((1, 4), (-5, -1))
    assert interval_conclusion_reversal((-5, -1), (1, 4))
    assert not interval_conclusion_reversal((0, 4), (-5, -1))
    assert not interval_conclusion_reversal((1, 4), (-5, 0))
