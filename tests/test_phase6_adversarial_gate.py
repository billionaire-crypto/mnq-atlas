"""Phase 6 Stage E integrated adversarial admission gate.

All callables, arrays, coordinates, witnesses, and mutations are synthetic.
Nothing in this module reads market data or implements a real conditioner.
"""

from __future__ import annotations

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.conditioners.registry import (
    DESCRIPTIVE_LABEL,
    ConditionerClass,
    ConditionerRegistry,
    NegativeControl,
    NegativeControlFailure,
    WitnessCheck,
    register_causal_conditioner,
    register_descriptive_conditioner,
)
from mnq_lab.core.dependency import (
    DependencyCase,
    DeterministicWitness,
    OutputComparison,
    OutputKind,
    run_dependency_locality,
)


def _readonly(values, dtype):
    array = np.asarray(values, dtype=dtype)
    array.setflags(write=False)
    return array


def _coordinates():
    return _readonly([10, 20, 100, 101, 500, 900], np.int64)


def _allowed():
    return _readonly([True, True, False, False, True, False], np.bool_)


def _exact_inputs():
    return {"x": _readonly([2, 3, 11, 13, 5, 17], np.int64)}


def _float_inputs():
    return {"x": _readonly([2.0, 4.0, 11.0, 13.0, 8.0, 17.0], np.float64)}


def _case(name, invoke, inputs, comparison):
    return DependencyCase(
        name=name,
        coordinates_ns=_coordinates(),
        allowed_dependency_mask=_allowed(),
        inputs=inputs,
        invoke=invoke,
        comparison=comparison,
    )


def _exact_sum(call):
    x = call.values["x"]
    return np.asarray(x[0] + x[1] + x[4], dtype=np.int64)


def _float_linear(call):
    x = call.values["x"]
    return np.asarray(x[0] + 0.5 * x[1], dtype=np.float64)


def _exact_witness(*, expected_changed=15, name="exact_sum_changes"):
    return DeterministicWitness(
        name=name,
        changed_inputs={"x": _readonly([7, 3, 11, 13, 5, 17], np.int64)},
        expected_baseline=_readonly(10, np.int64),
        expected_changed=_readonly(expected_changed, np.int64),
        affected_output_index=(),
    )


def _float_witness(*, expected_changed=8.0, name="float_linear_changes"):
    return DeterministicWitness(
        name=name,
        changed_inputs={
            "x": _readonly([6.0, 4.0, 11.0, 13.0, 8.0, 17.0], np.float64)
        },
        expected_baseline=_readonly(4.0, np.float64),
        expected_changed=_readonly(expected_changed, np.float64),
        affected_output_index=(),
    )


def _exact_controls(primary_case):
    def forbidden_read(call):
        return np.asarray(call.values["x"][2], dtype=np.int64)

    locality = NegativeControl(
        name="exact_forbidden_read",
        failure=NegativeControlFailure.LOCALITY_OUTPUT_CHANGE,
        case=_case(
            "exact_forbidden_read",
            forbidden_read,
            _exact_inputs(),
            OutputComparison(OutputKind.INTEGER),
        ),
    )
    witness = NegativeControl(
        name="exact_wrong_expected_change",
        failure=NegativeControlFailure.WITNESS_CHANGED_OUTPUT,
        case=primary_case,
        witness=_exact_witness(
            expected_changed=14, name="exact_wrong_expected_change"
        ),
    )
    return locality, witness


def _float_controls(primary_case):
    comparison = OutputComparison(OutputKind.FLOAT, atol=1e-12, rtol=1e-12)

    def forbidden_read(call):
        return np.asarray(call.values["x"][2], dtype=np.float64)

    locality = NegativeControl(
        name="float_forbidden_read",
        failure=NegativeControlFailure.LOCALITY_OUTPUT_CHANGE,
        case=_case(
            "float_forbidden_read",
            forbidden_read,
            _float_inputs(),
            comparison,
        ),
    )
    witness = NegativeControl(
        name="float_wrong_expected_change",
        failure=NegativeControlFailure.WITNESS_CHANGED_OUTPUT,
        case=primary_case,
        witness=_float_witness(
            expected_changed=7.0, name="float_wrong_expected_change"
        ),
    )
    return locality, witness


def _admit_exact(registry, conditioner=_exact_sum, identifier="gate.exact"):
    primary = _case(
        "integrated_exact",
        conditioner,
        _exact_inputs(),
        OutputComparison(OutputKind.INTEGER),
    )
    return register_causal_conditioner(
        registry,
        identifier,
        conditioner,
        metadata={"fixture": "independently specified exact gate"},
        locality_cases=(primary,),
        witness_checks=(WitnessCheck(primary, _exact_witness()),),
        negative_controls=_exact_controls(primary),
    )


def _admit_float(registry, conditioner=_float_linear, identifier="gate.float"):
    primary = _case(
        "integrated_float",
        conditioner,
        _float_inputs(),
        OutputComparison(OutputKind.FLOAT, atol=1e-12, rtol=1e-12),
    )
    return register_causal_conditioner(
        registry,
        identifier,
        conditioner,
        metadata={"fixture": "independently specified floating gate"},
        locality_cases=(primary,),
        witness_checks=(WitnessCheck(primary, _float_witness()),),
        negative_controls=_float_controls(primary),
    )


def test_integrated_exact_gate_admits_only_after_both_nonvacuous_halves():
    registry = ConditionerRegistry()

    descriptor = _admit_exact(registry)

    assert descriptor.classification is ConditionerClass.CAUSAL
    assert descriptor.locality_case_count == 1
    assert descriptor.witness_count == 1
    assert descriptor.negative_control_count == 2
    assert descriptor.comparison_policies[0].kind is OutputKind.INTEGER
    assert registry.is_confirmation_eligible(descriptor.identifier)


@pytest.mark.parametrize("mutation", ["future_read", "insensitive", "wrong_direction"])
def test_integrated_exact_gate_kills_named_causal_mutations(mutation):
    if mutation == "future_read":
        def mutant(call):
            return np.asarray(call.values["x"][2], dtype=np.int64)
    elif mutation == "insensitive":
        def mutant(call):
            return np.asarray(10, dtype=np.int64)
    else:
        def mutant(call):
            x = call.values["x"]
            return np.asarray(20 - (x[0] + x[1] + x[4]), dtype=np.int64)

    registry = ConditionerRegistry()
    with pytest.raises(SpineError):
        _admit_exact(registry, mutant, identifier=f"gate.exact.{mutation}")
    assert registry.entries() == ()


def test_integrated_float_gate_executes_declared_tolerance_and_disjoint_witness():
    registry = ConditionerRegistry()

    descriptor = _admit_float(registry)

    policy = descriptor.comparison_policies[0]
    assert policy.kind is OutputKind.FLOAT
    assert policy.atol == 1e-12
    assert policy.rtol == 1e-12
    assert registry.is_confirmation_eligible(descriptor.identifier)


@pytest.mark.parametrize("mutation", ["future_read", "insensitive", "wrong_direction"])
def test_integrated_float_gate_kills_named_causal_mutations(mutation):
    if mutation == "future_read":
        def mutant(call):
            return np.asarray(call.values["x"][2], dtype=np.float64)
    elif mutation == "insensitive":
        def mutant(call):
            return np.asarray(4.0, dtype=np.float64)
    else:
        def mutant(call):
            x = call.values["x"]
            return np.asarray(8.0 - (x[0] + 0.5 * x[1]), dtype=np.float64)

    registry = ConditionerRegistry()
    with pytest.raises(SpineError):
        _admit_float(registry, mutant, identifier=f"gate.float.{mutation}")
    assert registry.entries() == ()


def test_integrated_descriptive_route_is_permanently_ineligible():
    registry = ConditionerRegistry()
    descriptor = register_descriptive_conditioner(
        registry,
        "gate.descriptive",
        _exact_sum,
        metadata={"fixture": "synthetic descriptive control"},
    )

    assert descriptor.label == DESCRIPTIVE_LABEL
    assert not registry.is_confirmation_eligible(descriptor.identifier)
    with pytest.raises(SpineError, match="callable object.*already registered"):
        _admit_exact(registry, _exact_sum, identifier="gate.descriptive.alias")


def test_landmark_integer_mutation_kills_far_threshold_dependency():
    def far_threshold(call):
        return np.asarray(call.values["x"][2] > -1_000_000_000, dtype=np.bool_)

    case = _case(
        "far_integer_threshold",
        far_threshold,
        _exact_inputs(),
        OutputComparison(OutputKind.BOOLEAN),
    )
    with pytest.raises(SpineError, match="out-of-window.*comparison failed"):
        run_dependency_locality(case)


def test_landmark_float_mutation_kills_far_threshold_dependency():
    def far_threshold(call):
        return np.asarray(call.values["x"][2] > 1e300, dtype=np.bool_)

    case = _case(
        "far_float_threshold",
        far_threshold,
        _float_inputs(),
        OutputComparison(OutputKind.BOOLEAN),
    )
    with pytest.raises(SpineError, match="out-of-window.*comparison failed"):
        run_dependency_locality(case)
