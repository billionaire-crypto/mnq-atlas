"""Phase 5 plan composition with the signed-off Phase 4 weight path."""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.core.bootstrap import (
    StationaryGroupResamplePlan,
    apply_group_multiplicities,
    stationary_group_resample,
)
from mnq_lab.core.weights import (
    anchor_equal_weights,
    session_equal_weights,
    weighted_quantile,
)


def _generator(seed=0):
    return np.random.Generator(np.random.PCG64(seed))


def _manual_plan(labels, selected_positions):
    group_count = len(labels)
    multiplicities = tuple(
        int(value)
        for value in np.bincount(selected_positions, minlength=group_count)
    )
    flags = (True,) + tuple(
        position != (previous + 1) % group_count
        for previous, position in zip(
            selected_positions[:-1], selected_positions[1:]
        )
    )
    return StationaryGroupResamplePlan(
        ordered_group_labels=tuple(labels),
        group_count=group_count,
        mean_block_groups=5.0,
        restart_probability=0.2,
        selected_positions=tuple(selected_positions),
        multiplicities=multiplicities,
        block_start_flags=flags,
        restart_count=sum(flags[1:]),
    )


@pytest.mark.parametrize("baseline_factory", ["session", "anchor"])
def test_all_ones_multiplicities_preserve_baseline_bytes_and_point_estimate(
    baseline_factory,
):
    group_ids = np.array(["a", "b", "b", "b", "c", "c"])
    values = np.array([-4.0, 1.0, 7.0, 7.0, 20.0, 30.0])
    plan = _manual_plan(("a", "b", "c"), (0, 1, 2))
    if baseline_factory == "session":
        baseline, _ = session_equal_weights(group_ids)
    else:
        baseline, _ = anchor_equal_weights(group_ids.size)

    composed = apply_group_multiplicities(group_ids, baseline, plan)

    assert composed.dtype == baseline.dtype == np.dtype(np.float64)
    assert composed.tobytes() == baseline.tobytes()
    assert not np.shares_memory(composed, baseline)
    assert weighted_quantile(values, composed, 0.5) == weighted_quantile(
        values, baseline, 0.5
    )


def test_integer_multiplicities_match_a_repeated_whole_group_oracle():
    group_ids = np.array(["a", "b", "b", "b", "c", "c", "d", "d"])
    values = np.array([-8.0, -3.0, -1.0, 2.0, 7.0, 9.0, 20.0, 30.0])
    baseline, _ = anchor_equal_weights(group_ids.size)
    plan = _manual_plan(("a", "b", "c", "d"), (3, 0, 2, 0))

    composed = apply_group_multiplicities(group_ids, baseline, plan)
    expanded_values = np.concatenate(
        [
            values[group_ids == label]
            for label, multiplicity in zip(
                plan.ordered_group_labels, plan.multiplicities
            )
            for _ in range(multiplicity)
        ]
    )
    expanded_weights = np.concatenate(
        [
            baseline[group_ids == label]
            for label, multiplicity in zip(
                plan.ordered_group_labels, plan.multiplicities
            )
            for _ in range(multiplicity)
        ]
    )

    assert plan.multiplicities == (2, 0, 1, 1)
    assert np.array_equal(
        composed,
        np.array([0.25, 0.0, 0.0, 0.0, 0.125, 0.125, 0.125, 0.125]),
    )
    for probability in (0.25, 0.5, 0.75, 1.0):
        assert weighted_quantile(
            values, composed, probability
        ) == weighted_quantile(
            expanded_values, expanded_weights, probability
        )


def test_fractional_baseline_is_multiplied_without_pre_normalization():
    group_ids = np.array(["a", "a", "b", "c"])
    baseline = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float64)
    plan = _manual_plan(("a", "b", "c"), (0, 0, 0))

    composed = apply_group_multiplicities(group_ids, baseline, plan)
    expected = baseline * np.array([3.0, 3.0, 0.0, 0.0])

    assert np.array_equal(composed, expected)
    assert float(np.sum(composed)) == pytest.approx(0.9)
    assert not np.isclose(float(np.sum(composed)), 1.0)
    assert np.all(composed[group_ids != "a"] == 0.0)


def test_session_and_anchor_baselines_remain_distinct_after_composition():
    group_ids = np.array(["a", "b", "b", "b", "c", "c"])
    plan = _manual_plan(("a", "b", "c"), (0, 0, 2))
    session_baseline, _ = session_equal_weights(group_ids)
    anchor_baseline, _ = anchor_equal_weights(group_ids.size)

    session_composed = apply_group_multiplicities(
        group_ids, session_baseline, plan
    )
    anchor_composed = apply_group_multiplicities(
        group_ids, anchor_baseline, plan
    )

    assert not np.array_equal(session_composed, anchor_composed)
    assert session_composed[0] == pytest.approx(2.0 / 3.0)
    assert anchor_composed[0] == pytest.approx(1.0 / 3.0)
    assert np.all(session_composed[group_ids == "b"] == 0.0)
    assert np.all(anchor_composed[group_ids == "b"] == 0.0)


def test_one_global_plan_serves_two_aligned_paths_and_post_plan_masks():
    group_ids = np.array(
        ["a", "b", "b", "b", "c", "c", "d", "d", "d", "d"]
    )
    first_values = np.arange(group_ids.size, dtype=np.float64)
    second_values = np.arange(100, 100 + group_ids.size, dtype=np.float64)
    first_mask = np.isin(group_ids, ["a", "c", "d"])
    second_mask = np.array(
        [True, False, True, False, True, False, True, False, True, False]
    )
    baseline, _ = anchor_equal_weights(group_ids.size)
    plan = stationary_group_resample(group_ids, 5, _generator(0))

    composed = apply_group_multiplicities(group_ids, baseline, plan)
    first_statistic = weighted_quantile(
        first_values[first_mask], composed[first_mask], 0.5
    )
    second_statistic = weighted_quantile(
        second_values[second_mask], composed[second_mask], 0.5
    )

    assert plan.multiplicities == (2, 0, 1, 1)
    assert first_statistic == 5.0
    assert second_statistic == 104.0
    expected = baseline * np.repeat(plan.multiplicities, (1, 3, 2, 4))
    assert np.array_equal(composed[first_mask], expected[first_mask])
    assert np.array_equal(composed[second_mask], expected[second_mask])


def test_cell_support_varies_across_global_plans_without_prefiltering():
    group_ids = np.array(
        ["a", "b", "b", "b", "c", "c", "d", "d", "d", "d"]
    )
    cell_mask = np.isin(group_ids, ["a", "c", "d"])
    baseline, _ = anchor_equal_weights(group_ids.size)
    first_plan = stationary_group_resample(group_ids, 5, _generator(0))
    second_plan = stationary_group_resample(group_ids, 5, _generator(1))

    first = apply_group_multiplicities(group_ids, baseline, first_plan)
    second = apply_group_multiplicities(group_ids, baseline, second_plan)
    first_positive = cell_mask & (first > 0.0)
    second_positive = cell_mask & (second > 0.0)

    assert first_plan.multiplicities == (2, 0, 1, 1)
    assert second_plan.multiplicities == (0, 1, 2, 1)
    assert np.count_nonzero(first_positive) == 7
    assert np.count_nonzero(second_positive) == 6
    assert len(set(group_ids[first_positive])) == 3
    assert len(set(group_ids[second_positive])) == 2


def test_joint_fixture_kills_redrawing_for_each_aligned_path():
    group_ids = np.array(["a", "b", "c", "d"])
    redraw_rng = _generator(0)
    first = stationary_group_resample(group_ids, 5, redraw_rng)
    defective_second = stationary_group_resample(group_ids, 5, redraw_rng)

    assert first.multiplicities == (2, 0, 1, 1)
    assert defective_second.multiplicities != first.multiplicities
    assert "rng" not in inspect.signature(
        apply_group_multiplicities
    ).parameters


def test_joint_fixture_kills_resampling_inside_a_filtered_cell():
    group_ids = np.array(
        ["a", "b", "b", "b", "c", "c", "d", "d", "d", "d"]
    )
    cell_mask = np.isin(group_ids, ["a", "c", "d"])
    baseline, _ = anchor_equal_weights(group_ids.size)
    global_plan = stationary_group_resample(group_ids, 5, _generator(0))
    correct = apply_group_multiplicities(
        group_ids, baseline, global_plan
    )[cell_mask]

    filtered_groups = group_ids[cell_mask]
    filtered_baseline = baseline[cell_mask]
    defective_plan = stationary_group_resample(
        filtered_groups, 5, _generator(0)
    )
    defective = apply_group_multiplicities(
        filtered_groups, filtered_baseline, defective_plan
    )

    assert global_plan.group_count == 4
    assert defective_plan.group_count == 3
    assert not np.array_equal(correct, defective)


@pytest.mark.parametrize(
    "different_group_ids",
    [
        ["a", "a", "b", "different"],
        ["b", "b", "a", "c"],
    ],
    ids=["different-label", "reordered-same-labels"],
)
def test_plan_application_rejects_a_different_same_count_grouping(
    different_group_ids,
):
    plan = stationary_group_resample(
        ["a", "a", "b", "c"], 5, _generator(0)
    )

    with pytest.raises(SpineError, match="exactly match"):
        apply_group_multiplicities(
            different_group_ids,
            np.full(4, 0.25),
            plan,
        )


@pytest.mark.parametrize(
    ("group_ids", "baseline_weights", "message"),
    [
        (["a", "b"], [1.0], "equal length"),
        (["a", "b"], [[1.0, 1.0]], "one-dimensional"),
        (["a", "b"], [True, 1.0], "bool"),
        (["a", "b"], [-1.0, 2.0], "negative"),
        (["a", "b"], [0.0, 0.0], "positive total"),
        (["a", "b"], [np.nan, 1.0], "non-finite"),
        (["a", "b"], [np.inf, 1.0], "non-finite"),
        (["a", "b"], np.array([1.0, 2.0], dtype=object), "real integer"),
        (["a", "b"], [2**53 + 1, 1], r"2\*\*53"),
        (["a", "b", "a"], [1.0, 1.0, 1.0], "contiguous"),
    ],
)
def test_invalid_composition_inputs_fail_closed(
    group_ids, baseline_weights, message
):
    plan = _manual_plan(("a", "b"), (0, 1))

    with pytest.raises(SpineError, match=message):
        apply_group_multiplicities(group_ids, baseline_weights, plan)


@pytest.mark.parametrize(
    "plan",
    [
        None,
        {},
        object(),
        SimpleNamespace(
            ordered_group_labels=("a",),
            multiplicities=(1,),
        ),
    ],
)
def test_non_plan_inputs_fail_closed(plan):
    with pytest.raises(SpineError, match="StationaryGroupResamplePlan"):
        apply_group_multiplicities(["a"], [1.0], plan)


def test_composition_overflow_fails_closed():
    plan = _manual_plan(("a", "b"), (0, 0))

    with pytest.raises(SpineError, match="finite"):
        apply_group_multiplicities(
            ["a", "b"],
            [np.finfo(np.float64).max, 1.0],
            plan,
        )


def test_composition_does_not_mutate_or_alias_caller_arrays():
    group_ids = np.array(["a", "a", "b", "c"], dtype="<U1")
    baseline = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float64)
    plan = _manual_plan(("a", "b", "c"), (0, 0, 2))
    groups_before = group_ids.tobytes()
    baseline_before = baseline.tobytes()

    composed = apply_group_multiplicities(group_ids, baseline, plan)
    composed[0] = 99.0

    assert group_ids.tobytes() == groups_before
    assert baseline.tobytes() == baseline_before
    assert not np.shares_memory(composed, baseline)


def test_real_scale_shape_composes_once_without_rebuilding_baselines():
    group_count = 1_009
    rows_per_group = 78
    group_ids = np.repeat(np.arange(group_count), rows_per_group)
    baseline, _ = anchor_equal_weights(group_ids.size)
    plan = stationary_group_resample(group_ids, 5, _generator(20260729))

    composed = apply_group_multiplicities(group_ids, baseline, plan)

    assert group_ids.size == composed.size == 78_702
    assert composed.dtype == np.float64
    assert bool(np.isfinite(composed).all())
    assert np.count_nonzero(composed) <= composed.size
