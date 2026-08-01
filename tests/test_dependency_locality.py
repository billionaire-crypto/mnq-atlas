"""Frozen spec §13 test 6 — generic dependency-locality infrastructure.

The fixtures are synthetic and market-free.  Dependency membership is declared
on irregular event-time coordinates; positional offsets are deliberately wrong
on the planted negative cases.  Every positive mechanism below has a negative
case that proves the corresponding guard can fail.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.core.causality import conditioner_input_mask
from mnq_lab.core.dependency import (
    DependencyCase,
    OutputComparison,
    OutputKind,
    run_dependency_locality,
)


def _readonly(values, dtype=None):
    array = np.asarray(values, dtype=dtype)
    array.setflags(write=False)
    return array


def _case(
    invoke,
    *,
    coordinates=None,
    allowed=None,
    inputs=None,
    comparison=None,
    name="synthetic",
):
    if coordinates is None:
        coordinates = _readonly([10, 20, 100, 101, 500, 900], np.int64)
    if allowed is None:
        allowed = _readonly([True, True, False, False, True, False], np.bool_)
    if inputs is None:
        inputs = {"x": _readonly([2, 3, 11, 13, 5, 17], np.int64)}
    if comparison is None:
        comparison = OutputComparison(OutputKind.INTEGER)
    return DependencyCase(
        name=name,
        coordinates_ns=coordinates,
        allowed_dependency_mask=allowed,
        inputs=inputs,
        invoke=invoke,
        comparison=comparison,
    )


def test_locality_mutates_every_forbidden_region_non_vacuously():
    allowed = np.asarray([True, True, False, False, True, False])

    case = _case(
        lambda call: np.asarray(
            np.sum(call.values["x"][allowed]), dtype=np.int64
        )
    )
    report = run_dependency_locality(case)

    assert report.case_name == "synthetic"
    assert report.forbidden_region_count == 2
    assert report.forbidden_region_sizes == (2, 1)
    assert report.changed_value_counts == (2, 1)
    assert report.test_seed == 0

    with pytest.raises(FrozenInstanceError):
        report.test_seed = 1


def test_event_time_boundary_is_inclusive_and_positional_future_read_is_caught():
    tau = np.int64(1_000)
    coordinates = _readonly([100, tau, tau + 1, tau + 10_000], np.int64)
    allowed = conditioner_input_mask(coordinates, tau)
    allowed.setflags(write=False)
    assert allowed.tolist() == [True, True, False, False]

    values = {"x": _readonly([2, 3, 101, 103], np.int64)}
    causal = _case(
        lambda call: np.asarray(np.sum(call.values["x"][:2]), dtype=np.int64),
        coordinates=coordinates,
        allowed=allowed,
        inputs=values,
        name="event_time",
    )
    assert run_dependency_locality(causal).forbidden_region_sizes == (2,)

    positional_future_read = _case(
        lambda call: np.asarray(np.sum(call.values["x"][-2:]), dtype=np.int64),
        coordinates=coordinates,
        allowed=allowed,
        inputs=values,
        name="positional_future_read",
    )
    with pytest.raises(SpineError, match="out-of-window.*changed output"):
        run_dependency_locality(positional_future_read)


def test_planted_one_row_future_read_is_caught_exactly():
    case = _case(
        lambda call: np.asarray(call.values["x"][2], dtype=np.int64),
        name="one_row_future_read",
    )
    with pytest.raises(SpineError, match="region 0.*changed output"):
        run_dependency_locality(case)


def test_boolean_output_is_exact_and_future_read_is_caught():
    inputs = {"flag": _readonly([True, False, True, False, True, False], np.bool_)}
    case = _case(
        lambda call: np.asarray(call.values["flag"][5], dtype=np.bool_),
        inputs=inputs,
        comparison=OutputComparison(OutputKind.BOOLEAN),
        name="boolean_future_read",
    )
    with pytest.raises(SpineError, match="changed output"):
        run_dependency_locality(case)


def test_float_locality_uses_the_declared_formula_and_can_fail():
    inputs = {"x": _readonly([2.0, 3.0, 11.0, 13.0, 5.0, 17.0], np.float64)}
    within = _case(
        lambda call: np.asarray(1.0 + 1e-8 * call.values["x"][2], dtype=np.float64),
        inputs=inputs,
        comparison=OutputComparison(OutputKind.FLOAT, atol=1e-6, rtol=0.0),
        name="float_within_tolerance",
    )
    run_dependency_locality(within)

    beyond = _case(
        lambda call: np.asarray(call.values["x"][2], dtype=np.float64),
        inputs=inputs,
        comparison=OutputComparison(OutputKind.FLOAT, atol=1e-12, rtol=0.0),
        name="float_beyond_tolerance",
    )
    with pytest.raises(SpineError, match="floating comparison"):
        run_dependency_locality(beyond)


@pytest.mark.parametrize("mutation", ["shape", "dtype"])
def test_changed_output_shape_or_dtype_fails_closed(mutation):
    baseline_future = 11

    def malformed(call):
        if int(call.values["x"][2]) == baseline_future:
            return np.asarray([7], dtype=np.int64)
        if mutation == "shape":
            return np.asarray([7, 7], dtype=np.int64)
        return np.asarray([7], dtype=np.int32)

    with pytest.raises(SpineError, match=mutation):
        run_dependency_locality(_case(malformed, name=f"changed_{mutation}"))


@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_nonfinite_float_output_fails_closed(value):
    case = _case(
        lambda call: np.asarray(value, dtype=np.float64),
        comparison=OutputComparison(OutputKind.FLOAT),
        name="nonfinite_output",
    )
    with pytest.raises(SpineError, match="non-finite"):
        run_dependency_locality(case)


def test_hidden_nondeterminism_is_caught_by_repeated_identical_calls():
    calls = 0

    def hidden_counter(call):
        nonlocal calls
        calls += 1
        return np.asarray(calls, dtype=np.int64)

    with pytest.raises(SpineError, match="nondeterministic"):
        run_dependency_locality(_case(hidden_counter, name="hidden_counter"))


def test_callable_cannot_mutate_supplied_inputs():
    def mutates_input(call):
        call.values["x"][0] = 999
        return np.asarray(0, dtype=np.int64)

    with pytest.raises(SpineError, match="read-only|callable raised"):
        run_dependency_locality(_case(mutates_input, name="mutates_input"))


def test_case_owns_immutable_nonaliased_inputs():
    coordinates = _readonly([10, 20, 30], np.int64)
    allowed = _readonly([True, False, True], np.bool_)
    values = _readonly([1, 2, 3], np.int64)
    case = _case(
        lambda call: np.asarray(call.values["x"][0], dtype=np.int64),
        coordinates=coordinates,
        allowed=allowed,
        inputs={"x": values},
    )

    assert not case.coordinates_ns.flags.writeable
    assert not case.allowed_dependency_mask.flags.writeable
    assert not case.inputs["x"].flags.writeable
    assert not np.shares_memory(case.coordinates_ns, coordinates)
    assert not np.shares_memory(case.allowed_dependency_mask, allowed)
    assert not np.shares_memory(case.inputs["x"], values)
    with pytest.raises(TypeError):
        case.inputs["new"] = values


@pytest.mark.parametrize(
    ("coordinates", "allowed", "message"),
    [
        (_readonly([], np.int64), _readonly([], np.bool_), "non-empty"),
        (
            _readonly([[1, 2], [3, 4]], np.int64),
            _readonly([True, False], np.bool_),
            "one-dimensional",
        ),
        (_readonly([1, 2], np.int32), _readonly([True, False]), "int64"),
        (_readonly([2, 1], np.int64), _readonly([True, False]), "increasing"),
        (_readonly([1, 2], np.int64), _readonly([[True, False]]), "one-dimensional"),
        (_readonly([1, 2], np.int64), _readonly([1, 0], np.int64), "boolean"),
        (_readonly([1, 2, 3], np.int64), _readonly([True, False]), "length"),
        (_readonly([1, 2], np.int64), _readonly([True, True]), "out-of-window"),
        (_readonly([1, 2], np.int64), _readonly([False, False]), "in-window"),
    ],
)
def test_malformed_dependency_windows_fail_closed(coordinates, allowed, message):
    with pytest.raises(SpineError, match=message):
        _case(
            lambda call: np.asarray(0, dtype=np.int64),
            coordinates=coordinates,
            allowed=allowed,
            inputs={"x": _readonly(np.arange(coordinates.size), np.int64)},
        )


@pytest.mark.parametrize("which", ["coordinates", "mask"])
def test_mutable_dependency_coordinates_and_masks_fail_closed(which):
    coordinates = np.asarray([1, 2], dtype=np.int64)
    allowed = np.asarray([True, False], dtype=np.bool_)
    if which == "coordinates":
        allowed.setflags(write=False)
    else:
        coordinates.setflags(write=False)

    with pytest.raises(SpineError, match="immutable"):
        _case(
            lambda call: np.asarray(0, dtype=np.int64),
            coordinates=coordinates,
            allowed=allowed,
            inputs={"x": _readonly([1, 2], np.int64)},
        )


@pytest.mark.parametrize(
    ("inputs", "message"),
    [
        ({}, "non-empty"),
        ({"x": np.asarray([1, 2], dtype=np.int64)}, "immutable"),
        ({"x": _readonly([1], np.int64)}, "length"),
        ({"x": _readonly([[1, 2]], np.int64)}, "one-dimensional"),
        ({"x": _readonly([1, object()], object)}, "dtype"),
        ({"x": _readonly([1.0, np.nan], np.float64)}, "non-finite"),
        ({"x": _readonly([1 + 0j, 2 + 0j], np.complex128)}, "dtype"),
    ],
)
def test_malformed_baseline_inputs_fail_closed(inputs, message):
    with pytest.raises(SpineError, match=message):
        _case(
            lambda call: np.asarray(0, dtype=np.int64),
            coordinates=_readonly([1, 2], np.int64),
            allowed=_readonly([True, False], np.bool_),
            inputs=inputs,
        )


@pytest.mark.parametrize(
    ("policy", "message"),
    [
        (lambda: OutputComparison("integer"), "OutputKind"),
        (lambda: OutputComparison(OutputKind.INTEGER, atol=1.0), "exact"),
        (lambda: OutputComparison(OutputKind.BOOLEAN, rtol=1.0), "exact"),
        (lambda: OutputComparison(OutputKind.FLOAT, atol=-1.0), "nonnegative"),
        (lambda: OutputComparison(OutputKind.FLOAT, atol=np.nan), "finite"),
        (lambda: OutputComparison(OutputKind.FLOAT, rtol=np.inf), "finite"),
        (lambda: OutputComparison(OutputKind.FLOAT, atol=True), "non-bool"),
    ],
)
def test_malformed_comparison_policies_fail_closed(policy, message):
    with pytest.raises(SpineError, match=message):
        policy()


def test_callable_exception_fails_closed_with_case_context():
    def broken(call):
        raise RuntimeError("planted failure")

    with pytest.raises(SpineError, match="synthetic.*planted failure"):
        run_dependency_locality(_case(broken))
