"""Frozen spec §13 test 6 — generic dependency-locality infrastructure.

The fixtures are synthetic and market-free.  Dependency membership is declared
on irregular event-time coordinates; positional offsets are deliberately wrong
on the planted negative cases.  Every positive mechanism below has a negative
case that proves the corresponding guard can fail.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import gc

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.core.causality import conditioner_input_mask
from mnq_lab.core.dependency import (
    DependencyCheck,
    DependencyCheckError,
    DependencyCase,
    DependencyFailure,
    DeterministicWitness,
    OutputComparison,
    OutputKind,
    run_dependency_locality,
    run_deterministic_witness,
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
    assert report.changed_value_counts == (8, 4)
    assert report.mutation_trial_count == 8
    assert report.test_seed == 0

    with pytest.raises(FrozenInstanceError):
        report.test_seed = 1


def test_each_named_input_is_mutated_in_a_separate_trial():
    allowed = np.asarray([True, True, False, False, True, False])
    inputs = {
        "x": _readonly([2, 3, 11, 13, 5, 17], np.int64),
        "companion": _readonly([19, 23, 29, 31, 37, 41], np.int64),
    }
    causal = _case(
        lambda call: np.asarray(
            np.sum(call.values["x"][allowed])
            + np.sum(call.values["companion"][allowed]),
            dtype=np.int64,
        ),
        inputs=inputs,
        name="two_inputs",
    )
    report = run_dependency_locality(causal)
    assert report.mutation_trial_count == 16
    assert report.changed_value_counts == (16, 8)

    companion_future_read = _case(
        lambda call: np.asarray(call.values["companion"][2], dtype=np.int64),
        inputs=inputs,
        name="companion_future_read",
    )
    with pytest.raises(SpineError, match="input 'companion'.*changed output"):
        run_dependency_locality(companion_future_read)


@pytest.mark.parametrize(
    ("values", "dtype"),
    [
        ([1, -128, 2, 127], np.int8),
        ([1, 0, 2, 255], np.uint8),
        ([1.0, -np.finfo(np.float32).max, 2.0, 0.0], np.float32),
        ([True, False, False, True], np.bool_),
    ],
)
def test_mutation_schedule_changes_dtype_boundaries_without_noop(values, dtype):
    case = _case(
        lambda call: np.asarray(1, dtype=np.int64),
        coordinates=_readonly([1, 2, 3, 4], np.int64),
        allowed=_readonly([True, False, True, False], np.bool_),
        inputs={"x": _readonly(values, dtype)},
        name=f"boundary_{np.dtype(dtype).name}",
    )
    report = run_dependency_locality(case)
    assert report.forbidden_region_sizes == (1, 1)
    assert all(count >= 1 for count in report.changed_value_counts)
    assert sum(report.changed_value_counts) == report.mutation_trial_count


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


def test_locality_comparison_failure_has_machine_readable_identity():
    case = _case(
        lambda call: np.asarray(call.values["x"][2], dtype=np.int64),
        name="structured_locality_failure",
    )

    with pytest.raises(DependencyCheckError) as caught:
        run_dependency_locality(case)

    assert caught.value.check is DependencyCheck.LOCALITY
    assert caught.value.failure is DependencyFailure.EXACT_COMPARISON_MISMATCH


def test_shape_failure_cannot_claim_output_comparison_identity():
    def changes_shape(call):
        if int(call.values["x"][2]) == 11:
            return np.asarray([7], dtype=np.int64)
        return np.asarray([7, 7], dtype=np.int64)

    with pytest.raises(DependencyCheckError) as caught:
        run_dependency_locality(
            _case(changes_shape, name="comparison failed in caller name")
        )

    assert caught.value.check is DependencyCheck.LOCALITY
    assert caught.value.failure is DependencyFailure.SHAPE_MISMATCH


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


def test_tick_output_is_bit_exact_and_future_read_is_caught():
    case = _case(
        lambda call: np.asarray(call.values["x"][3], dtype=np.int32),
        comparison=OutputComparison(OutputKind.TICKS),
        name="tick_future_read",
    )
    with pytest.raises(SpineError, match="exact comparison"):
        run_dependency_locality(case)


def test_float_locality_uses_the_declared_formula_and_can_fail():
    inputs = {"x": _readonly([2.0, 3.0, 11.0, 13.0, 5.0, 17.0], np.float64)}
    within = _case(
        lambda call: np.asarray(
            1.0 + 1e-8 * np.tanh(call.values["x"][2]), dtype=np.float64
        ),
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


@pytest.mark.parametrize(
    "output",
    [None, np.asarray([], dtype=np.int64)],
)
def test_missing_or_empty_output_fails_closed(output):
    case = _case(lambda call: output, name="missing_output")
    with pytest.raises(SpineError, match="output.*(dtype|non-empty)"):
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


def test_callable_cannot_mutate_dependency_coordinates():
    def mutates_coordinates(call):
        call.coordinates_ns[0] = 999
        return np.asarray(0, dtype=np.int64)

    with pytest.raises(SpineError, match="read-only|callable raised"):
        run_dependency_locality(
            _case(mutates_coordinates, name="mutates_coordinates")
        )


def test_case_owns_immutable_nonaliased_inputs():
    coordinates = _readonly([10, 20, 30], np.int64)
    allowed = _readonly([True, False, True], np.bool_)
    values = _readonly([1, 2, 3], np.int64)
    source_inputs = {"x": values}
    case = _case(
        lambda call: np.asarray(call.values["x"][0], dtype=np.int64),
        coordinates=coordinates,
        allowed=allowed,
        inputs=source_inputs,
    )
    source_inputs.clear()

    assert not case.coordinates_ns.flags.writeable
    assert not case.allowed_dependency_mask.flags.writeable
    assert not case.inputs["x"].flags.writeable
    assert not np.shares_memory(case.coordinates_ns, coordinates)
    assert not np.shares_memory(case.allowed_dependency_mask, allowed)
    assert not np.shares_memory(case.inputs["x"], values)
    with pytest.raises(TypeError):
        case.inputs["new"] = values


def test_dependency_execution_refuses_case_input_mapping_content_rewrite():
    holder = {}
    replacement = _readonly([101, 103, 107, 109, 113, 127], np.int64)

    def rewrites_declared_inputs(call):
        backing = next(
            referent
            for referent in gc.get_referents(holder["case"].inputs)
            if isinstance(referent, dict)
        )
        backing["x"] = replacement
        return np.asarray(1, dtype=np.int64)

    case = _case(rewrites_declared_inputs, name="rewrites_declared_inputs")
    holder["case"] = case

    with pytest.raises(SpineError, match="inputs.*content"):
        run_dependency_locality(case)


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


def _witness(
    changed_inputs,
    expected_baseline,
    expected_changed,
    *,
    affected_output_index=(),
    name="deterministic_change",
):
    return DeterministicWitness(
        name=name,
        changed_inputs=changed_inputs,
        expected_baseline=expected_baseline,
        expected_changed=expected_changed,
        affected_output_index=affected_output_index,
    )


def test_dependency_case_has_no_writable_instance_dict():
    case = _case(lambda call: np.asarray(call.values["x"][0], dtype=np.int64))

    with pytest.raises(AttributeError):
        case.__dict__["invoke"] = lambda call: np.asarray(0, dtype=np.int64)


def test_deterministic_witness_has_no_writable_instance_dict():
    witness = _witness(
        {"x": _readonly([7, 3, 11, 13, 5, 17], np.int64)},
        _readonly(10, np.int64),
        _readonly(15, np.int64),
    )

    with pytest.raises(AttributeError):
        witness.__dict__["expected_changed"] = _readonly(10, np.int64)


def test_integer_witness_asserts_independent_baseline_and_changed_responses():
    allowed = np.asarray([True, True, False, False, True, False])
    case = _case(
        lambda call: np.asarray(
            np.sum(call.values["x"][allowed]), dtype=np.int64
        ),
        name="integer_sum",
    )
    witness = _witness(
        {"x": _readonly([7, 3, 11, 13, 5, 17], np.int64)},
        _readonly(10, np.int64),
        _readonly(15, np.int64),
    )

    report = run_deterministic_witness(case, witness)
    assert report.case_name == "integer_sum"
    assert report.witness_name == "deterministic_change"
    assert report.changed_input_count == 1
    assert report.affected_output_index == ()
    with pytest.raises(FrozenInstanceError):
        report.changed_input_count = 2


def test_median_witness_moves_the_order_statistic_not_a_noncentral_value():
    allowed = np.asarray([True, True, False, False, True, False])
    case = _case(
        lambda call: np.asarray(
            np.median(call.values["x"][allowed]), dtype=np.int64
        ),
        name="median",
    )
    central = _witness(
        {"x": _readonly([2, 9, 11, 13, 5, 17], np.int64)},
        _readonly(3, np.int64),
        _readonly(5, np.int64),
        name="central_median_change",
    )
    assert run_deterministic_witness(case, central).changed_input_count == 1

    noncentral = _witness(
        {"x": _readonly([-100, 3, 11, 13, 5, 17], np.int64)},
        _readonly(3, np.int64),
        _readonly(3, np.int64),
        name="noncentral_median_change",
    )
    with pytest.raises(SpineError, match="vacuous.*affected output"):
        run_deterministic_witness(case, noncentral)


def test_category_witness_crosses_its_threshold_exactly():
    case = _case(
        lambda call: np.asarray(call.values["x"][0] >= 5, dtype=np.int8),
        comparison=OutputComparison(OutputKind.INTEGER),
        name="category",
    )
    witness = _witness(
        {"x": _readonly([7, 3, 11, 13, 5, 17], np.int64)},
        _readonly(0, np.int8),
        _readonly(1, np.int8),
    )
    run_deterministic_witness(case, witness)


def test_boolean_mask_witness_flips_the_required_element():
    inputs = {"x": _readonly([2, 3, 11, 13, 5, 17], np.int64)}
    case = _case(
        lambda call: np.asarray(
            [call.values["x"][0] >= 5, call.values["x"][1] >= 5],
            dtype=np.bool_,
        ),
        inputs=inputs,
        comparison=OutputComparison(OutputKind.BOOLEAN),
        name="mask",
    )
    witness = _witness(
        {"x": _readonly([7, 3, 11, 13, 5, 17], np.int64)},
        _readonly([False, False], np.bool_),
        _readonly([True, False], np.bool_),
        affected_output_index=(0,),
    )
    run_deterministic_witness(case, witness)


def test_wrong_expected_baseline_and_changed_values_each_fail():
    allowed = np.asarray([True, True, False, False, True, False])
    case = _case(
        lambda call: np.asarray(np.sum(call.values["x"][allowed]), dtype=np.int64),
        name="independent_expectations",
    )
    changed = {"x": _readonly([7, 3, 11, 13, 5, 17], np.int64)}

    wrong_baseline = _witness(
        changed,
        _readonly(9, np.int64),
        _readonly(15, np.int64),
    )
    with pytest.raises(SpineError, match="witness baseline.*exact comparison"):
        run_deterministic_witness(case, wrong_baseline)

    wrong_changed = _witness(
        changed,
        _readonly(10, np.int64),
        _readonly(14, np.int64),
    )
    with pytest.raises(SpineError, match="witness changed.*exact comparison"):
        run_deterministic_witness(case, wrong_changed)


def test_insensitive_and_wrong_direction_callables_are_killed():
    changed = {"x": _readonly([7, 3, 11, 13, 5, 17], np.int64)}
    witness = _witness(
        changed,
        _readonly(10, np.int64),
        _readonly(15, np.int64),
    )
    insensitive = _case(
        lambda call: np.asarray(10, dtype=np.int64),
        name="insensitive",
    )
    with pytest.raises(SpineError, match="witness changed.*exact comparison"):
        run_deterministic_witness(insensitive, witness)

    allowed = np.asarray([True, True, False, False, True, False])
    wrong_direction = _case(
        lambda call: np.asarray(
            20 - np.sum(call.values["x"][allowed]), dtype=np.int64
        ),
        name="wrong_direction",
    )
    with pytest.raises(SpineError, match="witness changed.*exact comparison"):
        run_deterministic_witness(wrong_direction, witness)


def test_valid_float_witness_asserts_both_disjoint_responses():
    inputs = {"x": _readonly([0.0, 3.0, 11.0, 13.0, 5.0, 17.0], np.float64)}
    case = _case(
        lambda call: np.asarray(call.values["x"][0], dtype=np.float64),
        inputs=inputs,
        comparison=OutputComparison(OutputKind.FLOAT, atol=0.01, rtol=0.05),
        name="float_response",
    )
    witness = _witness(
        {"x": _readonly([1.0, 3.0, 11.0, 13.0, 5.0, 17.0], np.float64)},
        _readonly(0.0, np.float64),
        _readonly(1.0, np.float64),
    )
    run_deterministic_witness(case, witness)


def test_one_band_float_witness_is_rejected_as_vacuous():
    case = _case(
        lambda call: np.asarray(0.008, dtype=np.float64),
        inputs={"x": _readonly([0.0, 3.0, 11.0, 13.0, 5.0, 17.0], np.float64)},
        comparison=OutputComparison(OutputKind.FLOAT, atol=0.01, rtol=0.0),
        name="g1_counterexample",
    )
    witness = _witness(
        {"x": _readonly([0.015, 3.0, 11.0, 13.0, 5.0, 17.0], np.float64)},
        _readonly(0.0, np.float64),
        _readonly(0.015, np.float64),
    )
    with pytest.raises(SpineError, match="disjoint.*comparison bands"):
        run_deterministic_witness(case, witness)


def test_constant_float_callable_fails_when_witness_bands_are_disjoint():
    case = _case(
        lambda call: np.asarray(0.008, dtype=np.float64),
        inputs={"x": _readonly([0.0, 3.0, 11.0, 13.0, 5.0, 17.0], np.float64)},
        comparison=OutputComparison(OutputKind.FLOAT, atol=0.01, rtol=0.0),
        name="constant_float",
    )
    witness = _witness(
        {"x": _readonly([0.03, 3.0, 11.0, 13.0, 5.0, 17.0], np.float64)},
        _readonly(0.0, np.float64),
        _readonly(0.03, np.float64),
    )
    with pytest.raises(SpineError, match="witness changed.*floating comparison"):
        run_deterministic_witness(case, witness)


def test_witness_may_change_only_declared_in_window_values():
    future_change = _witness(
        {"x": _readonly([2, 3, 99, 13, 5, 17], np.int64)},
        _readonly(2, np.int64),
        _readonly(2, np.int64),
    )
    with pytest.raises(SpineError, match="out-of-window input"):
        run_deterministic_witness(
            _case(lambda call: np.asarray(call.values["x"][0], dtype=np.int64)),
            future_change,
        )


def test_witness_with_no_actual_input_change_fails_closed():
    unchanged = _witness(
        {"x": _readonly([2, 3, 11, 13, 5, 17], np.int64)},
        _readonly(2, np.int64),
        _readonly(3, np.int64),
    )
    with pytest.raises(SpineError, match="at least one in-window input"):
        run_deterministic_witness(
            _case(lambda call: np.asarray(call.values["x"][0], dtype=np.int64)),
            unchanged,
        )


@pytest.mark.parametrize(
    ("changed_inputs", "message"),
    [
        ({}, "same names"),
        ({"y": _readonly([2, 3, 11, 13, 5, 17], np.int64)}, "same names"),
        ({"x": _readonly([7, 3], np.int64)}, "shape"),
        ({"x": _readonly([7, 3, 11, 13, 5, 17], np.int32)}, "dtype"),
    ],
)
def test_malformed_witness_inputs_fail_closed(changed_inputs, message):
    witness = _witness(
        changed_inputs,
        _readonly(2, np.int64),
        _readonly(7, np.int64),
    )
    with pytest.raises(SpineError, match=message):
        run_deterministic_witness(
            _case(lambda call: np.asarray(call.values["x"][0], dtype=np.int64)),
            witness,
        )


@pytest.mark.parametrize(
    ("expected_baseline", "expected_changed", "index", "message"),
    [
        (_readonly(2, np.int64), _readonly(7, np.int32), (), "dtype"),
        (_readonly([2], np.int64), _readonly([7], np.int64), (), "index"),
        (_readonly([2], np.int64), _readonly([7], np.int64), (1,), "bounds"),
        (_readonly([2], np.int64), _readonly([7], np.int64), (True,), "integers"),
    ],
)
def test_malformed_expected_outputs_and_affected_index_fail_closed(
    expected_baseline, expected_changed, index, message
):
    witness = _witness(
        {"x": _readonly([7, 3, 11, 13, 5, 17], np.int64)},
        expected_baseline,
        expected_changed,
        affected_output_index=index,
    )
    with pytest.raises(SpineError, match=message):
        run_deterministic_witness(
            _case(lambda call: np.asarray(call.values["x"][0], dtype=np.int64)),
            witness,
        )


@pytest.mark.parametrize("mutable_part", ["input", "baseline", "changed"])
def test_mutable_witness_arrays_fail_at_declaration(mutable_part):
    changed_inputs = {"x": _readonly([7, 3, 11, 13, 5, 17], np.int64)}
    expected_baseline = _readonly(2, np.int64)
    expected_changed = _readonly(7, np.int64)
    if mutable_part == "input":
        changed_inputs = {"x": np.asarray([7, 3, 11, 13, 5, 17], dtype=np.int64)}
    elif mutable_part == "baseline":
        expected_baseline = np.asarray(2, dtype=np.int64)
    else:
        expected_changed = np.asarray(7, dtype=np.int64)

    with pytest.raises(SpineError, match="immutable"):
        _witness(changed_inputs, expected_baseline, expected_changed)


def test_witness_owns_immutable_nonaliased_arrays_and_mapping():
    changed = _readonly([7, 3, 11, 13, 5, 17], np.int64)
    baseline = _readonly(2, np.int64)
    expected = _readonly(7, np.int64)
    source_inputs = {"x": changed}
    witness = _witness(source_inputs, baseline, expected)
    source_inputs.clear()

    assert not np.shares_memory(witness.changed_inputs["x"], changed)
    assert not np.shares_memory(witness.expected_baseline, baseline)
    assert not np.shares_memory(witness.expected_changed, expected)
    assert not witness.changed_inputs["x"].flags.writeable
    assert not witness.expected_baseline.flags.writeable
    assert not witness.expected_changed.flags.writeable
    with pytest.raises(TypeError):
        witness.changed_inputs["new"] = changed
