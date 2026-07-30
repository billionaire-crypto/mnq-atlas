"""Deterministic coherence tests for Phase 5 bootstrap replicate generation."""

from __future__ import annotations

import copy
import inspect
from types import SimpleNamespace

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.core import bootstrap as bootstrap_module
from mnq_lab.core import weights as weights_module
from mnq_lab.core.bootstrap import (
    StationaryGroupResamplePlan,
    bootstrap_weighted_quantile_replicates,
    stationary_group_resample,
)
from mnq_lab.core.weights import anchor_equal_weights


def _generator(seed=0):
    return np.random.Generator(np.random.PCG64(seed))


def _all_ones_plan(labels):
    group_count = len(labels)
    return StationaryGroupResamplePlan(
        ordered_group_labels=tuple(labels),
        group_count=group_count,
        mean_block_groups=5.0,
        restart_probability=0.2,
        selected_positions=tuple(range(group_count)),
        multiplicities=(1,) * group_count,
        block_start_flags=(True,) + (False,) * (group_count - 1),
        restart_count=0,
    )


def test_one_plan_per_replicate_serves_two_aligned_value_and_mask_paths():
    group_ids = np.repeat(np.array(["a", "b", "c", "d"]), 2)
    first_values = np.array([0, 1, 10, 11, 20, 21, 30, 31], dtype=np.float64)
    second_values = first_values + 100.0
    first_mask = np.tile(np.array([True, False]), 4)
    second_mask = ~first_mask
    baseline, _ = anchor_equal_weights(group_ids.size)
    actual_rng = _generator(44)
    groups_before = group_ids.tobytes()
    baseline_before = baseline.tobytes()
    first_before = first_values.tobytes()
    second_before = second_values.tobytes()
    first_mask_before = first_mask.tobytes()
    second_mask_before = second_mask.tobytes()

    replicates = bootstrap_weighted_quantile_replicates(
        group_ids,
        baseline,
        (first_values, second_values),
        (first_mask, second_mask),
        (0.5, 0.5),
        999,
        5,
        actual_rng,
    )

    control_rng = _generator(44)
    for _ in range(999):
        stationary_group_resample(group_ids, 5, control_rng)

    assert replicates.shape == (2, 999)
    assert replicates.dtype == np.float64
    assert np.array_equal(replicates[1] - replicates[0], np.full(999, 101.0))
    assert actual_rng.bit_generator.state == control_rng.bit_generator.state
    assert group_ids.tobytes() == groups_before
    assert baseline.tobytes() == baseline_before
    assert first_values.tobytes() == first_before
    assert second_values.tobytes() == second_before
    assert first_mask.tobytes() == first_mask_before
    assert second_mask.tobytes() == second_mask_before


def test_one_global_plan_and_composition_precede_every_request_mask(
    monkeypatch,
):
    group_ids = np.array(["a", "b", "c", "d"])
    baseline, _ = anchor_equal_weights(group_ids.size)
    seen_group_vectors = []
    recorded_compositions = []
    plan_calls = 0
    composition_calls = 0
    phase4_calls = 0
    original_apply = bootstrap_module.apply_group_multiplicities
    original_phase4 = bootstrap_module.weighted_quantiles
    original_phase4_scalar = weights_module.weighted_quantile
    plan = _all_ones_plan(("a", "b", "c", "d"))
    request_values = (
        np.array([0.0, 1.0, 2.0, 3.0]),
        np.array([10.0, 11.0, 12.0, 13.0]),
    )
    request_masks = (
        np.ones(4, dtype=bool),
        np.array([True, False, True, False]),
    )

    def plan_spy(supplied_group_ids, mean_block_groups, rng):
        nonlocal plan_calls
        plan_calls += 1
        seen_group_vectors.append(tuple(supplied_group_ids))
        return plan

    def composition_spy(supplied_group_ids, supplied_weights, supplied_plan):
        nonlocal composition_calls
        composition_calls += 1
        composed = original_apply(
            supplied_group_ids,
            supplied_weights,
            supplied_plan,
        )
        recorded_compositions.append(composed.copy())
        return composed

    def assert_untampered_phase4_inputs(values, weights):
        nonlocal phase4_calls
        replicate_index, request_index = divmod(phase4_calls, 2)
        expected_values = request_values[request_index][
            request_masks[request_index]
        ]
        expected_weights = recorded_compositions[replicate_index][
            request_masks[request_index]
        ]
        supplied_values = np.asarray(values)
        supplied_weights = np.asarray(weights)

        assert supplied_values.dtype == expected_values.dtype
        assert supplied_values.tobytes() == expected_values.tobytes()
        assert supplied_weights.dtype == expected_weights.dtype
        assert supplied_weights.tobytes() == expected_weights.tobytes()
        phase4_calls += 1

    def phase4_spy(values, weights, quantiles):
        assert_untampered_phase4_inputs(values, weights)
        return original_phase4(values, weights, quantiles)

    def phase4_scalar_spy(values, weights, quantile):
        assert_untampered_phase4_inputs(values, weights)
        return original_phase4_scalar(values, weights, quantile)

    monkeypatch.setattr(
        bootstrap_module,
        "stationary_group_resample",
        plan_spy,
    )
    monkeypatch.setattr(
        bootstrap_module,
        "apply_group_multiplicities",
        composition_spy,
    )
    monkeypatch.setattr(
        bootstrap_module,
        "weighted_quantiles",
        phase4_spy,
    )
    monkeypatch.setattr(
        bootstrap_module,
        "weighted_quantile",
        phase4_scalar_spy,
        raising=False,
    )

    replicates = bootstrap_weighted_quantile_replicates(
        group_ids,
        baseline,
        request_values,
        request_masks,
        (0.5, 0.5),
        1_000,
        5,
        _generator(0),
    )

    assert replicates.shape == (2, 1_000)
    assert plan_calls == 1_000
    assert composition_calls == 1_000
    assert len(recorded_compositions) == 1_000
    assert phase4_calls == 2_000
    assert set(seen_group_vectors) == {("a", "b", "c", "d")}


def test_zero_mass_request_fails_at_the_exact_later_replicate_without_retry():
    group_ids = np.array(["a", "b", "c", "d"])
    baseline, _ = anchor_equal_weights(group_ids.size)
    only_b = np.array([False, True, False, False])

    with pytest.raises(
        SpineError,
        match=r"replicate 7, request 0.*positive total",
    ):
        bootstrap_weighted_quantile_replicates(
            group_ids,
            baseline,
            (np.arange(4, dtype=np.float64),),
            (only_b,),
            (0.5,),
            999,
            5,
            _generator(2),
        )


def test_failure_identifies_the_second_request_after_the_shared_plan():
    group_ids = np.array(["a", "b", "c", "d"])
    baseline, _ = anchor_equal_weights(group_ids.size)

    with pytest.raises(
        SpineError,
        match=r"replicate 0, request 1.*positive total",
    ):
        bootstrap_weighted_quantile_replicates(
            group_ids,
            baseline,
            (
                np.arange(4, dtype=np.float64),
                np.arange(10, 14, dtype=np.float64),
            ),
            (
                np.ones(4, dtype=bool),
                np.array([False, True, False, False]),
            ),
            (0.5, 0.5),
            999,
            5,
            _generator(0),
        )


def test_nonfinite_eligible_value_fails_even_when_its_plan_weight_is_zero():
    group_ids = np.array(["a", "b", "c", "d"])
    baseline, _ = anchor_equal_weights(group_ids.size)

    with pytest.raises(
        SpineError,
        match=r"replicate 0, request 0.*non-finite value at index 1",
    ):
        bootstrap_weighted_quantile_replicates(
            group_ids,
            baseline,
            (np.array([0.0, np.nan, 2.0, 3.0]),),
            (np.ones(4, dtype=bool),),
            (0.5,),
            999,
            5,
            _generator(0),
        )


@pytest.mark.parametrize(
    ("draws", "message"),
    [
        (998, "draws"),
        (0, "draws"),
        (-1, "draws"),
        (999.0, "draws"),
        (True, "draws"),
        (np.bool_(False), "draws"),
        ("999", "draws"),
    ],
)
def test_invalid_draw_counts_fail_before_rng_consumption(draws, message):
    rng = _generator(81)
    state = copy.deepcopy(rng.bit_generator.state)

    with pytest.raises(SpineError, match=message):
        bootstrap_weighted_quantile_replicates(
            ["a"],
            [1.0],
            (np.array([1.0]),),
            (np.array([True]),),
            (0.5,),
            draws,
            5,
            rng,
        )

    assert rng.bit_generator.state == state


@pytest.mark.parametrize(
    "rng",
    [
        None,
        20260729,
        np.random.RandomState(0),
        SimpleNamespace(integers=lambda high: 0, random=lambda: 0.5),
        object(),
    ],
)
def test_invalid_rng_inputs_fail_closed(rng):
    with pytest.raises(SpineError, match="Generator"):
        bootstrap_weighted_quantile_replicates(
            ["a"],
            [1.0],
            (np.array([1.0]),),
            (np.array([True]),),
            (0.5,),
            999,
            5,
            rng,
        )


@pytest.mark.parametrize(
    ("value_arrays", "eligibility_masks", "quantiles", "message"),
    [
        ((), (), (), "at least one"),
        ((np.ones(2),), (np.ones(2, dtype=bool),), (), "equal request"),
        ((np.ones(2),), (), (0.5,), "equal request"),
        ((np.ones(1),), (np.ones(2, dtype=bool),), (0.5,), "row length"),
        ((np.ones(2),), (np.ones(1, dtype=bool),), (0.5,), "bool array"),
        ((np.ones(2),), (np.ones(2, dtype=np.int8),), (0.5,), "bool array"),
        ((np.ones((2, 1)),), (np.ones(2, dtype=bool),), (0.5,), "values"),
    ],
)
def test_malformed_aligned_request_sequences_fail_before_rng_consumption(
    value_arrays,
    eligibility_masks,
    quantiles,
    message,
):
    rng = _generator(82)
    state = copy.deepcopy(rng.bit_generator.state)

    with pytest.raises(SpineError, match=message):
        bootstrap_weighted_quantile_replicates(
            ["a", "b"],
            [0.5, 0.5],
            value_arrays,
            eligibility_masks,
            quantiles,
            999,
            5,
            rng,
        )

    assert rng.bit_generator.state == state


def test_empty_mask_fails_closed_at_replicate_zero():
    with pytest.raises(
        SpineError,
        match=r"replicate 0, request 0.*at least one",
    ):
        bootstrap_weighted_quantile_replicates(
            ["a", "b"],
            [0.5, 0.5],
            (np.array([1.0, 2.0]),),
            (np.array([False, False]),),
            (0.5,),
            999,
            5,
            _generator(0),
        )


@pytest.mark.parametrize(
    "quantile",
    [0.0, -0.1, 1.1, True, np.nan, np.inf, None, 0.5 + 0j],
)
def test_invalid_request_quantiles_fail_closed_with_replicate_index(
    quantile,
):
    with pytest.raises(
        SpineError,
        match=r"replicate 0, request 0",
    ):
        bootstrap_weighted_quantile_replicates(
            ["a", "b"],
            [0.5, 0.5],
            (np.array([1.0, 2.0]),),
            (np.array([True, True]),),
            (quantile,),
            999,
            5,
            _generator(0),
        )


def test_all_public_orchestration_inputs_are_explicit():
    signature = inspect.signature(bootstrap_weighted_quantile_replicates)

    assert all(
        parameter.default is inspect.Parameter.empty
        for parameter in signature.parameters.values()
    )
