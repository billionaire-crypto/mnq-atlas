"""Phase 5 whole-group stationary-resample plan properties."""

from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.constants import CONSTANTS_PATH, load_bootstrap_constants
from mnq_lab.core.bootstrap import (
    StationaryGroupResamplePlan,
    stationary_group_resample,
)


def _generator(seed=0):
    return np.random.Generator(np.random.PCG64(seed))


class _DuckRNG:
    def integers(self, high):
        return 0

    def random(self):
        return 0.5


def test_bootstrap_constants_load_exactly_and_drive_the_primary_plan():
    bootstrap = load_bootstrap_constants()
    assert bootstrap == {
        "scheme": "whole_session_stationary",
        "mean_block_sessions_primary": 5,
        "block_sensitivity": [1, 5, 10, 20],
        "truncate_partial_session": False,
    }

    plan = stationary_group_resample(
        ["a", "b", "c"],
        bootstrap["mean_block_sessions_primary"],
        _generator(),
    )
    assert plan.mean_block_groups == float(
        bootstrap["mean_block_sessions_primary"]
    )


@pytest.mark.parametrize(
    ("name", "old", "new", "message"),
    [
        (
            "missing",
            "  mean_block_sessions_primary: 5\n",
            "",
            "exactly the keys",
        ),
        (
            "extra",
            "  truncate_partial_session: false\n",
            "  truncate_partial_session: false\n  unregistered: 999\n",
            "exactly the keys",
        ),
        (
            "scheme",
            "  scheme: whole_session_stationary\n",
            "  scheme: row_bootstrap\n",
            "incompatible",
        ),
        (
            "bool_primary",
            "  mean_block_sessions_primary: 5\n",
            "  mean_block_sessions_primary: true\n",
            "non-bool",
        ),
        (
            "zero_primary",
            "  mean_block_sessions_primary: 5\n",
            "  mean_block_sessions_primary: 0\n",
            ">= 1",
        ),
        (
            "empty_sensitivity",
            "  block_sensitivity: [1, 5, 10, 20]\n",
            "  block_sensitivity: []\n",
            "non-empty",
        ),
        (
            "invalid_sensitivity",
            "  block_sensitivity: [1, 5, 10, 20]\n",
            "  block_sensitivity: [1, false, 10, 20]\n",
            "non-bool",
        ),
        (
            "true_sensitivity",
            "  block_sensitivity: [1, 5, 10, 20]\n",
            "  block_sensitivity: [1, true, 10, 20]\n",
            "non-bool",
        ),
        (
            "zero_sensitivity",
            "  block_sensitivity: [1, 5, 10, 20]\n",
            "  block_sensitivity: [1, 0, 10, 20]\n",
            ">= 1",
        ),
        (
            "nonfinite_sensitivity",
            "  block_sensitivity: [1, 5, 10, 20]\n",
            "  block_sensitivity: [1, .nan, 10, 20]\n",
            "finite",
        ),
        (
            "primary_absent",
            "  block_sensitivity: [1, 5, 10, 20]\n",
            "  block_sensitivity: [1, 10, 20]\n",
            "must occur",
        ),
        (
            "truncate",
            "  truncate_partial_session: false\n",
            "  truncate_partial_session: true\n",
            "must be false",
        ),
    ],
)
def test_bootstrap_constant_loader_fails_closed(
    tmp_path, name, old, new, message
):
    frozen = CONSTANTS_PATH.read_text(encoding="utf-8")
    assert old in frozen
    path = tmp_path / f"{name}.yaml"
    path.write_text(frozen.replace(old, new), encoding="utf-8")

    with pytest.raises(SpineError, match=message):
        load_bootstrap_constants(path)


def test_plan_draws_exactly_the_original_group_count_with_exact_multiplicities():
    plan = stationary_group_resample(
        ["a", "a", "b", "c", "c", "d"],
        5,
        _generator(),
    )

    assert plan.group_count == 4
    assert len(plan.selected_positions) == 4
    assert len(plan.multiplicities) == 4
    assert sum(plan.multiplicities) == 4
    assert plan.multiplicities == tuple(
        int(value)
        for value in np.bincount(plan.selected_positions, minlength=4)
    )
    assert all(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0
        for value in plan.multiplicities
    )


def test_unequal_group_sizes_are_selected_whole_without_a_row_target():
    group_ids = np.array(
        [
            "a",
            *(["b"] * 5),
            *(["c"] * 2),
            *(["d"] * 7),
        ]
    )
    plan = stationary_group_resample(group_ids, 5, _generator(0))
    original_regions = tuple(
        np.flatnonzero(group_ids == label)
        for label in plan.ordered_group_labels
    )
    selected_regions = tuple(
        original_regions[position] for position in plan.selected_positions
    )

    assert plan.selected_positions == (3, 0, 2, 0)
    assert tuple(len(region) for region in selected_regions) == (7, 1, 2, 1)
    assert sum(len(region) for region in selected_regions) == 11
    assert sum(len(region) for region in selected_regions) != len(group_ids)
    for position, region in zip(plan.selected_positions, selected_regions):
        assert np.array_equal(region, original_regions[position])


def _defective_row_target_slice(regions, selected_positions, row_target):
    concatenated = np.concatenate(
        [regions[position] for position in selected_positions]
    )
    return concatenated[:row_target]


def test_planted_row_target_final_group_slice_is_detectably_incomplete():
    regions = (
        np.array([0, 1]),
        np.array([2, 3, 4]),
        np.array([5, 6, 7, 8, 9]),
    )
    defective = _defective_row_target_slice(
        regions,
        selected_positions=(2, 1, 2),
        row_target=10,
    )

    final_selected_rows = defective[8:]
    assert np.array_equal(final_selected_rows, np.array([5, 6]))
    assert not np.array_equal(final_selected_rows, regions[2]), (
        "the planted row-target fixture no longer slices its final group"
    )

    plan = stationary_group_resample(
        ["a", "a", "b", "b", "b", "c", "c", "c", "c", "c"],
        5,
        _generator(0),
    )
    assert len(plan.selected_positions) == plan.group_count == 3
    assert not hasattr(plan, "selected_rows")
    assert not hasattr(plan, "row_target")


def test_seed_zero_discriminates_continuation_wrap_and_restart_probability():
    plan = stationary_group_resample(
        ["a", "b", "c", "d"],
        5,
        _generator(0),
    )

    assert plan.restart_probability == 0.2
    assert plan.selected_positions == (3, 0, 2, 0)
    assert plan.block_start_flags == (True, False, True, True)
    assert plan.multiplicities == (2, 0, 1, 1)
    assert plan.restart_count == 2

    first_transition_uniform = 0.2697867137638703
    assert 0.2 <= first_transition_uniform < 0.8, (
        "the fixture no longer distinguishes p=1/L from p=1-1/L"
    )
    assert plan.selected_positions[:2] == (3, 0), (
        "continuation no longer discriminates circular wrap from forced restart"
    )


def test_l_one_consumes_uniform_then_restarts_at_every_transition():
    plan = stationary_group_resample(
        ["a", "b", "c", "d"],
        1,
        _generator(0),
    )

    assert plan.restart_probability == 1.0
    assert plan.selected_positions == (3, 2, 0, 0)
    assert plan.block_start_flags == (True, True, True, True)
    assert plan.restart_count == 3


def test_rng_state_matches_the_exact_ratified_consumption_order():
    actual_rng = _generator(0)
    plan = stationary_group_resample(
        ["a", "b", "c", "d"],
        5,
        actual_rng,
    )

    control_rng = _generator(0)
    position = int(control_rng.integers(4))
    expected_positions = [position]
    expected_flags = [True]
    for _ in range(3):
        restart = bool(control_rng.random() < 0.2)
        if restart:
            position = int(control_rng.integers(4))
        else:
            position = (position + 1) % 4
        expected_positions.append(position)
        expected_flags.append(restart)

    assert plan.selected_positions == tuple(expected_positions)
    assert plan.block_start_flags == tuple(expected_flags)
    assert actual_rng.bit_generator.state == control_rng.bit_generator.state


def test_single_group_consumes_only_the_initial_bounded_integer_call():
    actual_rng = _generator(91)
    plan = stationary_group_resample(["only", "only"], 5, actual_rng)

    control_rng = _generator(91)
    assert int(control_rng.integers(1)) == 0

    assert plan.selected_positions == (0,)
    assert plan.multiplicities == (1,)
    assert plan.block_start_flags == (True,)
    assert plan.restart_count == 0
    assert actual_rng.bit_generator.state == control_rng.bit_generator.state


def test_same_initial_generator_state_reproduces_plan_and_final_state():
    first_rng = _generator(20260729)
    second_rng = _generator(20260729)

    first = stationary_group_resample(["a", "b", "c", "d"], 10, first_rng)
    second = stationary_group_resample(
        ["a", "b", "c", "d"], 10, second_rng
    )

    assert first == second
    assert first_rng.bit_generator.state == second_rng.bit_generator.state


def test_inputs_are_not_mutated():
    group_ids = np.array(["a", "a", "b", "c"], dtype="<U1")
    before = group_ids.tobytes()
    dtype = group_ids.dtype

    stationary_group_resample(group_ids, 5, _generator())

    assert group_ids.tobytes() == before
    assert group_ids.dtype == dtype


def test_plan_and_all_sequence_fields_are_immutable():
    plan = stationary_group_resample(["a", "b", "c"], 5, _generator())

    assert isinstance(plan.ordered_group_labels, tuple)
    assert isinstance(plan.selected_positions, tuple)
    assert isinstance(plan.multiplicities, tuple)
    assert isinstance(plan.block_start_flags, tuple)
    with pytest.raises(FrozenInstanceError):
        plan.restart_count = 99
    with pytest.raises(TypeError):
        plan.selected_positions[0] = 1


def test_restart_metadata_distinguishes_restart_from_same_continuation_target():
    plan = StationaryGroupResamplePlan(
        ordered_group_labels=("a", "b", "c"),
        group_count=3,
        mean_block_groups=5.0,
        restart_probability=0.2,
        selected_positions=(0, 1, 2),
        multiplicities=(1, 1, 1),
        block_start_flags=(True, False, True),
        restart_count=1,
    )

    assert plan.selected_positions[1:] == (1, 2)
    assert plan.selected_positions[2] == (
        plan.selected_positions[1] + 1
    ) % plan.group_count
    assert plan.block_start_flags[1:] == (False, True)
    assert plan.restart_count == 1


def test_production_records_restarts_that_land_on_continuation_targets():
    plan = stationary_group_resample(
        ["a", "b", "c", "d"],
        1,
        _generator(1),
    )

    assert plan.selected_positions == (1, 2, 3, 3)
    assert plan.block_start_flags == (True, True, True, True)
    assert plan.multiplicities == (0, 1, 1, 2)
    assert plan.restart_count == 3
    assert plan.selected_positions[1] == (
        plan.selected_positions[0] + 1
    ) % plan.group_count
    assert plan.selected_positions[2] == (
        plan.selected_positions[1] + 1
    ) % plan.group_count


def test_noncontiguous_group_reappearance_fails_closed():
    with pytest.raises(SpineError, match="contiguous"):
        stationary_group_resample(
            ["a", "a", "b", "a"],
            5,
            _generator(),
        )


@pytest.mark.parametrize(
    "group_ids",
    [
        [],
        [["a"]],
        [True, "a"],
        [None],
        [np.nan],
        [np.inf],
        [1 + 0j],
        [{"not": "a scalar label"}],
    ],
)
def test_malformed_group_labels_fail_closed(group_ids):
    with pytest.raises(SpineError):
        stationary_group_resample(group_ids, 5, _generator())


@pytest.mark.parametrize(
    "mean_block_groups",
    [0, -1, True, np.bool_(False), np.nan, np.inf, -np.inf, "5", 1 + 0j],
)
def test_invalid_mean_block_lengths_fail_closed(mean_block_groups):
    with pytest.raises(SpineError, match="mean_block_groups"):
        stationary_group_resample(
            ["a", "b"],
            mean_block_groups,
            _generator(),
        )


@pytest.mark.parametrize(
    "rng",
    [
        None,
        20260729,
        np.random.RandomState(0),
        _DuckRNG(),
        object(),
    ],
)
def test_invalid_rng_inputs_fail_closed(rng):
    with pytest.raises(SpineError, match="Generator"):
        stationary_group_resample(["a", "b"], 5, rng)


@pytest.mark.parametrize(
    "mutation",
    [
        {
            "group_count": 0,
        },
        {
            "selected_positions": [0, 1, 1],
        },
        {
            "selected_positions": (0, 1),
        },
        {
            "block_start_flags": (True,),
            "restart_count": 0,
        },
        {
            "ordered_group_labels": ("a", "a", "c"),
        },
        {
            "restart_probability": 0.25,
        },
        {
            "selected_positions": (0, 1, -1),
            "multiplicities": (1, 1, 1),
        },
        {
            "selected_positions": (0, 1, 3),
            "multiplicities": (1, 1, 1),
        },
        {
            "selected_positions": (0, 1, 1),
            "multiplicities": (1, 1, 1),
        },
        {
            "selected_positions": (0, 1, 1),
            "multiplicities": (1, 2, 0),
            "block_start_flags": (False, False, True),
        },
        {
            "selected_positions": (0, 1, 1),
            "multiplicities": (1, 2, 0),
            "restart_count": 0,
        },
        {
            "selected_positions": (0, 1, 1),
            "multiplicities": (True, 2, 0),
        },
        {
            "selected_positions": (0, 1, 1),
            "multiplicities": (2, 2, -1),
        },
        {
            "selected_positions": (0, 1, 1),
            "multiplicities": (1, 2, 0),
            "block_start_flags": (True, False, np.bool_(True)),
        },
        {
            "selected_positions": (0, 1, 1),
            "multiplicities": (1, 2, 0),
            "restart_count": True,
        },
    ],
)
def test_manual_plan_invariant_mutations_fail_closed(mutation):
    fields = {
        "ordered_group_labels": ("a", "b", "c"),
        "group_count": 3,
        "mean_block_groups": 5.0,
        "restart_probability": 0.2,
        "selected_positions": (0, 1, 1),
        "multiplicities": (1, 2, 0),
        "block_start_flags": (True, False, True),
        "restart_count": 1,
    }
    fields.update(copy.deepcopy(mutation))

    with pytest.raises(SpineError):
        StationaryGroupResamplePlan(**fields)
