"""Phase 6 conditioner-registry lifecycle and classification tests.

Only synthetic callables appear here.  Real conditioners remain Phase 7.
"""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
import gc
import inspect
import math
from pathlib import Path
import re

import pytest
import numpy as np

from mnq_lab import SpineError
import mnq_lab.conditioners.registry as registry_module
from mnq_lab.conditioners.registry import (
    CAUSAL_LABEL,
    DESCRIPTIVE_LABEL,
    ConditionerClass,
    ConditionerDescriptor,
    ConditionerRegistry,
    NegativeControl,
    NegativeControlFailure,
    WitnessCheck,
    register_causal_conditioner,
    register_descriptive_conditioner,
)
from mnq_lab.core.dependency import (
    DependencyCheck,
    DependencyCheckError,
    DependencyCase,
    DependencyFailure,
    DeterministicWitness,
    LocalityReport,
    OutputComparison,
    OutputKind,
    run_dependency_locality,
)


def _first(call):
    return call.values["x"][0]


def test_descriptive_registration_has_exact_permanent_label_and_is_ineligible():
    registry = ConditionerRegistry()

    descriptor = register_descriptive_conditioner(
        registry,
        "synthetic.descriptive.first",
        _first,
        metadata={"purpose": "synthetic fixture"},
    )

    assert descriptor.identifier == "synthetic.descriptive.first"
    assert descriptor.conditioner is _first
    assert descriptor.classification is ConditionerClass.DESCRIPTIVE
    assert descriptor.label == "NONCAUSAL — NOT ELIGIBLE FOR CONFIRMATION"
    assert descriptor.label == DESCRIPTIVE_LABEL
    assert not registry.is_confirmation_eligible(descriptor.identifier)

    # Negative mutation: neither the descriptor nor the query accepts an
    # eligibility override that could turn descriptive evidence into causal.
    with pytest.raises(FrozenInstanceError):
        descriptor.label = "CAUSAL"
    with pytest.raises(TypeError):
        registry.is_confirmation_eligible(
            descriptor.identifier, eligible=True
        )


def test_duplicate_identifier_always_fails_and_preserves_original_entry():
    registry = ConditionerRegistry()
    original = register_descriptive_conditioner(
        registry,
        "synthetic.duplicate",
        _first,
        metadata={"version": 1},
    )

    with pytest.raises(SpineError, match="duplicate conditioner identifier"):
        register_descriptive_conditioner(
            registry,
            "synthetic.duplicate",
            _first,
            metadata={"version": 1},
        )
    with pytest.raises(SpineError, match="duplicate conditioner identifier"):
        register_descriptive_conditioner(
            registry,
            "synthetic.duplicate",
            lambda call: call.values["x"][0],
            metadata={"version": 2},
        )

    assert registry.entries() == (original,)
    assert registry.get("synthetic.duplicate") is original


def test_callable_alias_is_rejected_but_distinct_wrapper_has_distinct_identity():
    registry = ConditionerRegistry()
    first = register_descriptive_conditioner(
        registry,
        "synthetic.identity.original",
        _first,
        metadata={},
    )

    with pytest.raises(SpineError, match="callable object.*already registered"):
        register_descriptive_conditioner(
            registry,
            "synthetic.identity.alias",
            _first,
            metadata={},
        )

    def wrapper(call):
        return _first(call)

    second = register_descriptive_conditioner(
        registry,
        "synthetic.identity.wrapper",
        wrapper,
        metadata={},
    )
    assert registry.entries() == (first, second)


def test_metadata_and_retrieval_are_deeply_immutable_and_nonaliased():
    nested = {"owner": "tests", "details": {"revision": 1}, "tags": ("a", "b")}
    registry = ConditionerRegistry()
    descriptor = register_descriptive_conditioner(
        registry,
        "synthetic.metadata",
        _first,
        metadata=nested,
    )

    nested["owner"] = "mutated"
    nested["details"]["revision"] = 99
    assert descriptor.metadata["owner"] == "tests"
    assert descriptor.metadata["details"]["revision"] == 1
    assert descriptor.metadata["tags"] == ("a", "b")

    with pytest.raises(TypeError):
        descriptor.metadata["owner"] = "mutated"
    with pytest.raises(TypeError):
        descriptor.metadata["details"]["revision"] = 99
    with pytest.raises(FrozenInstanceError):
        descriptor.identifier = "synthetic.changed"
    assert registry.get("synthetic.metadata") is descriptor


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        ({1: "value"}, "metadata keys"),
        ({"": "value"}, "metadata keys"),
        ({"bad": [1, 2]}, "immutable metadata"),
        ({"bad": {1, 2}}, "immutable metadata"),
        ({"bad": object()}, "immutable metadata"),
        ({"bad": math.nan}, "finite"),
        ({"bad": math.inf}, "finite"),
    ],
)
def test_malformed_or_mutable_metadata_values_fail_closed(metadata, message):
    registry = ConditionerRegistry()
    with pytest.raises(SpineError, match=message):
        register_descriptive_conditioner(
            registry,
            "synthetic.bad_metadata",
            _first,
            metadata=metadata,
        )
    assert registry.entries() == ()


@pytest.mark.parametrize(
    ("identifier", "conditioner", "metadata", "message"),
    [
        ("", _first, {}, "identifier"),
        ("  ", _first, {}, "identifier"),
        (" padded", _first, {}, "identifier"),
        (1, _first, {}, "identifier"),
        ("synthetic.not_callable", 3, {}, "callable"),
        ("synthetic.not_mapping", _first, (), "metadata.*mapping"),
    ],
)
def test_malformed_registration_fails_without_insertion(
    identifier, conditioner, metadata, message
):
    registry = ConditionerRegistry()
    with pytest.raises(SpineError, match=message):
        register_descriptive_conditioner(
            registry, identifier, conditioner, metadata=metadata
        )
    assert registry.entries() == ()


def test_iteration_is_insertion_order_not_metadata_measurement_order():
    registry = ConditionerRegistry()
    callables = [
        lambda call: call.values["x"][0],
        lambda call: call.values["x"][0],
        lambda call: call.values["x"][0],
    ]
    identifiers = ["synthetic.z", "synthetic.a", "synthetic.m"]
    measured_values = [2, 99, -5]

    for identifier, conditioner, measured in zip(
        identifiers, callables, measured_values, strict=True
    ):
        register_descriptive_conditioner(
            registry,
            identifier,
            conditioner,
            metadata={"synthetic_measurement": measured},
        )

    assert tuple(entry.identifier for entry in registry.entries()) == tuple(
        identifiers
    )


def test_registry_has_no_overwrite_unregister_or_reclassification_surface():
    registry = ConditionerRegistry()
    public_names = {
        name
        for name, _ in inspect.getmembers(registry)
        if not name.startswith("_")
    }
    assert public_names == {"entries", "get", "is_confirmation_eligible"}
    assert not {
        "overwrite",
        "unregister",
        "remove",
        "downgrade",
        "reclassify",
        "insert",
    } & public_names

    with pytest.raises(SpineError, match="unknown conditioner identifier"):
        registry.get("synthetic.absent")
    with pytest.raises(SpineError, match="unknown conditioner identifier"):
        registry.is_confirmation_eligible("synthetic.absent")


def test_registry_rejects_subclassing_and_duck_typed_substitutes():
    with pytest.raises(TypeError, match="final"):
        class SubRegistry(ConditionerRegistry):
            pass

    class DuckRegistry:
        pass

    with pytest.raises(SpineError, match="ConditionerRegistry"):
        register_descriptive_conditioner(
            DuckRegistry(),
            "synthetic.duck_registry",
            _first,
            metadata={},
        )


def _readonly(values, dtype):
    array = np.asarray(values, dtype=dtype)
    array.setflags(write=False)
    return array


def _synthetic_sum(call):
    return np.asarray(
        call.values["x"][0] + call.values["x"][1] + call.values["x"][4],
        dtype=np.int64,
    )


def _case(
    invoke=_synthetic_sum,
    *,
    name="synthetic_sum",
    coordinates=None,
):
    return DependencyCase(
        name=name,
        coordinates_ns=_readonly(
            [10, 20, 30, 40, 50, 60]
            if coordinates is None
            else coordinates,
            np.int64,
        ),
        allowed_dependency_mask=_readonly(
            [True, True, False, False, True, False], np.bool_
        ),
        inputs={"x": _readonly([2, 3, 11, 13, 5, 17], np.int64)},
        invoke=invoke,
        comparison=OutputComparison(OutputKind.INTEGER),
    )


def _witness(*, expected_changed=15, name="sum_changes"):
    return DeterministicWitness(
        name=name,
        changed_inputs={"x": _readonly([7, 3, 11, 13, 5, 17], np.int64)},
        expected_baseline=_readonly(10, np.int64),
        expected_changed=_readonly(expected_changed, np.int64),
        affected_output_index=(),
    )


def _negative_controls(primary_case):
    def future_read(call):
        return np.asarray(call.values["x"][2], dtype=np.int64)

    locality_negative = NegativeControl(
        name="planted_future_read",
        failure=NegativeControlFailure.LOCALITY_OUTPUT_CHANGE,
        case=_case(future_read, name="planted_future_read"),
    )
    witness_negative = NegativeControl(
        name="planted_wrong_expected_change",
        failure=NegativeControlFailure.WITNESS_CHANGED_OUTPUT,
        case=primary_case,
        witness=_witness(
            expected_changed=14, name="planted_wrong_expected_change"
        ),
    )
    return locality_negative, witness_negative


def _register_causal(
    registry,
    conditioner=_synthetic_sum,
    *,
    identifier="synthetic.causal.sum",
    locality_cases=None,
    witness_checks=None,
    negative_controls=None,
    metadata=None,
):
    case = _case(conditioner)
    cases = (case,) if locality_cases is None else locality_cases
    checks = (
        (WitnessCheck(case, _witness()),)
        if witness_checks is None
        else witness_checks
    )
    controls = (
        _negative_controls(case)
        if negative_controls is None
        else negative_controls
    )
    return register_causal_conditioner(
        registry,
        identifier,
        conditioner,
        metadata={"purpose": "synthetic admission"}
        if metadata is None
        else metadata,
        locality_cases=cases,
        witness_checks=checks,
        negative_controls=controls,
    )


def test_causal_registration_executes_suite_then_exposes_empirical_admission():
    registry = ConditionerRegistry()

    descriptor = _register_causal(registry)

    assert descriptor.identifier == "synthetic.causal.sum"
    assert descriptor.conditioner is _synthetic_sum
    assert descriptor.classification is ConditionerClass.CAUSAL
    assert descriptor.label == CAUSAL_LABEL
    assert "EMPIRICAL" in descriptor.label
    assert "NOT PROOF" in descriptor.label
    assert registry.is_confirmation_eligible(descriptor.identifier)
    assert descriptor.locality_case_count == 1
    assert descriptor.witness_count == 1
    assert descriptor.negative_control_count == 2
    assert len(descriptor.comparison_policies) == 1
    policy = descriptor.comparison_policies[0]
    assert policy.case_name == "synthetic_sum"
    assert policy.kind is OutputKind.INTEGER
    assert policy.atol == 0.0
    assert policy.rtol == 0.0


@pytest.mark.parametrize(
    ("locality_cases", "witness_checks", "negative_controls", "message"),
    [
        ((), "default", "default", "locality case"),
        ("default", (), "default", "witness"),
        ("default", "default", (), "negative control"),
    ],
)
def test_missing_executable_evidence_prevents_causal_admission(
    locality_cases, witness_checks, negative_controls, message
):
    registry = ConditionerRegistry()
    kwargs = {}
    if locality_cases != "default":
        kwargs["locality_cases"] = locality_cases
    if witness_checks != "default":
        kwargs["witness_checks"] = witness_checks
    if negative_controls != "default":
        kwargs["negative_controls"] = negative_controls

    with pytest.raises(SpineError, match=message):
        _register_causal(registry, **kwargs)
    assert registry.entries() == ()


@pytest.mark.parametrize(
    "fake",
    [
        True,
        "passed",
        LocalityReport(
            case_name="forged",
            forbidden_region_count=1,
            forbidden_region_sizes=(1,),
            changed_value_counts=(1,),
            mutation_trial_count=1,
        ),
        object(),
    ],
)
def test_boolean_string_report_and_object_cannot_replace_executed_suite(fake):
    registry = ConditionerRegistry()
    with pytest.raises(SpineError, match="tuple.*DependencyCase"):
        _register_causal(registry, locality_cases=fake)
    assert registry.entries() == ()

    # Negative mutation: the only public admission function has no passed,
    # certificate, evidence, cached-result, or prior-result argument.
    with pytest.raises(TypeError):
        register_causal_conditioner(
            registry,
            "synthetic.forged",
            _synthetic_sum,
            metadata={},
            locality_cases=(),
            witness_checks=(),
            negative_controls=(),
            passed=True,
        )


def test_suite_must_execute_the_exact_callable_being_registered():
    registry = ConditionerRegistry()
    unrelated_case = _case(_synthetic_sum)

    def alias(call):
        return _synthetic_sum(call)

    with pytest.raises(SpineError, match="exact conditioner callable"):
        _register_causal(
            registry,
            alias,
            locality_cases=(unrelated_case,),
            witness_checks=(WitnessCheck(unrelated_case, _witness()),),
            negative_controls=_negative_controls(unrelated_case),
        )
    assert registry.entries() == ()


def test_witness_check_must_reference_a_declared_locality_case_object():
    registry = ConditionerRegistry()
    declared = _case()
    equal_but_distinct = _case()

    with pytest.raises(SpineError, match="declared locality case object"):
        _register_causal(
            registry,
            locality_cases=(declared,),
            witness_checks=(WitnessCheck(equal_but_distinct, _witness()),),
            negative_controls=_negative_controls(declared),
        )
    assert registry.entries() == ()


def test_failed_locality_case_leaves_registry_unchanged():
    registry = ConditionerRegistry()

    def future_read(call):
        return np.asarray(call.values["x"][2], dtype=np.int64)

    leaky = _case(future_read, name="registered_future_read")
    with pytest.raises(SpineError, match="out-of-window.*comparison failed"):
        _register_causal(
            registry,
            future_read,
            locality_cases=(leaky,),
            witness_checks=(WitnessCheck(leaky, _witness()),),
            negative_controls=_negative_controls(leaky),
        )
    assert registry.entries() == ()


def _f1_mask_widening_attack_suite(*, restore_honest_mask):
    holder = {}
    honest_mask = _readonly(
        [True, True, False, False, True, False], np.bool_
    )
    widened_mask = _readonly(
        [True, True, True, True, True, False], np.bool_
    )

    def widens_own_window(call):
        holder["case"].__dict__["allowed_dependency_mask"] = widened_mask
        return np.asarray(
            call.values["x"][0] + call.values["x"][2], dtype=np.int64
        )

    primary = _case(widens_own_window, name="self_widening_window")
    holder["case"] = primary
    witness = DeterministicWitness(
        name="self_widening_change",
        changed_inputs={
            "x": _readonly([7, 3, 11, 13, 5, 17], np.int64)
        },
        expected_baseline=_readonly(13, np.int64),
        expected_changed=_readonly(18, np.int64),
        affected_output_index=(),
    )

    def locality_negative(call):
        if restore_honest_mask:
            holder["case"].__dict__["allowed_dependency_mask"] = honest_mask
        return np.asarray(call.values["x"][2], dtype=np.int64)

    locality_control = NegativeControl(
        name="planted_future_read",
        failure=NegativeControlFailure.LOCALITY_OUTPUT_CHANGE,
        case=_case(locality_negative, name="planted_future_read"),
    )
    independent = _case(_synthetic_sum, name="independent_witness_control")
    witness_control = NegativeControl(
        name="planted_wrong_expected_change",
        failure=NegativeControlFailure.WITNESS_CHANGED_OUTPUT,
        case=independent,
        witness=_witness(
            expected_changed=14, name="planted_wrong_expected_change"
        ),
    )
    return primary, witness, (locality_control, witness_control), honest_mask


def test_causal_admission_refuses_mid_suite_dependency_mask_widening():
    registry = ConditionerRegistry()
    case, witness, controls, _ = _f1_mask_widening_attack_suite(
        restore_honest_mask=False
    )

    with pytest.raises(SpineError):
        _register_causal(
            registry,
            case.invoke,
            locality_cases=(case,),
            witness_checks=(WitnessCheck(case, witness),),
            negative_controls=controls,
        )
    assert registry.entries() == ()


def test_causal_admission_refuses_mask_widening_even_when_trace_is_erased():
    registry = ConditionerRegistry()
    case, witness, controls, honest_mask = _f1_mask_widening_attack_suite(
        restore_honest_mask=True
    )

    with pytest.raises(SpineError):
        _register_causal(
            registry,
            case.invoke,
            locality_cases=(case,),
            witness_checks=(WitnessCheck(case, witness),),
            negative_controls=controls,
        )
    assert np.array_equal(case.allowed_dependency_mask, honest_mask)
    assert registry.entries() == ()


def test_dependency_locality_refuses_bounded_comparison_widening():
    holder = {}
    widened = OutputComparison(OutputKind.FLOAT, atol=2.2)

    def bounded_future_read(call):
        object.__setattr__(holder["case"], "comparison", widened)
        values = call.values["x"]
        return np.asarray(
            values[0] + values[1] + values[4] + np.tanh(values[2]),
            dtype=np.float64,
        )

    case = DependencyCase(
        name="bounded_comparison_widening",
        coordinates_ns=_readonly([10, 20, 30, 40, 50, 60], np.int64),
        allowed_dependency_mask=_readonly(
            [True, True, False, False, True, False], np.bool_
        ),
        inputs={"x": _readonly([2, 3, 11, 13, 5, 17], np.float64)},
        invoke=bounded_future_read,
        comparison=OutputComparison(OutputKind.FLOAT),
    )
    holder["case"] = case
    with pytest.raises(SpineError, match="comparison"):
        run_dependency_locality(case)


def test_causal_admission_refuses_witness_input_mapping_content_rewrite():
    registry = ConditionerRegistry()
    holder = {}
    repaired_change = _readonly(
        [9991, 3, 11, 13, 5, 17], np.int64
    )

    def rewrites_declared_witness_inputs(call):
        backing = next(
            referent
            for referent in gc.get_referents(
                holder["witness"].changed_inputs
            )
            if isinstance(referent, dict)
        )
        backing["x"] = repaired_change
        return _synthetic_sum(call)

    case = _case(
        rewrites_declared_witness_inputs,
        name="rewrites_declared_witness_inputs",
    )
    witness = _witness(
        expected_changed=9999,
        name="wrong_expectation_repaired_by_mapping_rewrite",
    )
    holder["witness"] = witness

    with pytest.raises(SpineError, match="changed_inputs.*content"):
        _register_causal(
            registry,
            rewrites_declared_witness_inputs,
            locality_cases=(case,),
            witness_checks=(WitnessCheck(case, witness),),
            negative_controls=_negative_controls(case),
        )
    assert registry.entries() == ()


def test_failed_witness_leaves_registry_unchanged():
    registry = ConditionerRegistry()

    def insensitive(call):
        return np.asarray(10, dtype=np.int64)

    case = _case(insensitive, name="registered_insensitive")
    with pytest.raises(SpineError, match="witness changed.*comparison failed"):
        _register_causal(
            registry,
            insensitive,
            locality_cases=(case,),
            witness_checks=(WitnessCheck(case, _witness()),),
            negative_controls=_negative_controls(case),
        )
    assert registry.entries() == ()


def test_every_declared_locality_case_executes_before_atomic_insertion():
    registry = ConditionerRegistry()

    def second_case_leaks(call):
        if int(call.coordinates_ns[0]) == 100:
            return np.asarray(call.values["x"][2], dtype=np.int64)
        return _synthetic_sum(call)

    safe = _case(second_case_leaks, name="first_safe_case")
    leaky = _case(
        second_case_leaks,
        name="second_leaky_case",
        coordinates=[100, 110, 120, 130, 140, 150],
    )
    with pytest.raises(SpineError, match="second_leaky_case.*out-of-window"):
        _register_causal(
            registry,
            second_case_leaks,
            locality_cases=(safe, leaky),
            witness_checks=(WitnessCheck(safe, _witness()),),
            negative_controls=_negative_controls(safe),
        )
    assert registry.entries() == ()


def test_execution_refuses_cross_case_invoke_swap_before_locality():
    registry = ConditionerRegistry()
    holder = {}

    def substitute(call):
        return _synthetic_sum(call)

    def conditioner(call):
        if int(call.coordinates_ns[0]) == 10:
            object.__setattr__(holder["second"], "invoke", substitute)
        return _synthetic_sum(call)

    first = _case(conditioner, name="invoke_swap_first")
    second = _case(
        conditioner,
        name="invoke_swap_second",
        coordinates=[100, 110, 120, 130, 140, 150],
    )
    holder["second"] = second

    with pytest.raises(SpineError, match="exact conditioner.*execution"):
        _register_causal(
            registry,
            conditioner,
            locality_cases=(first, second),
            witness_checks=(WitnessCheck(first, _witness()),),
            negative_controls=_negative_controls(first),
        )
    assert registry.entries() == ()


def test_execution_refuses_cross_case_comparison_swap_before_locality():
    registry = ConditionerRegistry()
    holder = {}
    replacement = OutputComparison(OutputKind.INTEGER)

    def conditioner(call):
        if int(call.coordinates_ns[0]) == 10:
            object.__setattr__(holder["second"], "comparison", replacement)
        return _synthetic_sum(call)

    first = _case(conditioner, name="comparison_swap_first")
    second = _case(
        conditioner,
        name="comparison_swap_second",
        coordinates=[100, 110, 120, 130, 140, 150],
    )
    holder["second"] = second

    with pytest.raises(SpineError, match="comparison.*execution"):
        _register_causal(
            registry,
            conditioner,
            locality_cases=(first, second),
            witness_checks=(WitnessCheck(first, _witness()),),
            negative_controls=_negative_controls(first),
        )
    assert registry.entries() == ()


def test_every_declared_witness_executes_before_atomic_insertion():
    registry = ConditionerRegistry()

    def second_case_is_insensitive(call):
        if int(call.coordinates_ns[0]) == 100:
            return np.asarray(10, dtype=np.int64)
        return _synthetic_sum(call)

    first = _case(second_case_is_insensitive, name="first_witness_case")
    second = _case(
        second_case_is_insensitive,
        name="second_witness_case",
        coordinates=[100, 110, 120, 130, 140, 150],
    )
    checks = (
        WitnessCheck(first, _witness(name="first_witness")),
        WitnessCheck(second, _witness(name="second_witness")),
    )
    with pytest.raises(SpineError, match="witness changed.*comparison failed"):
        _register_causal(
            registry,
            second_case_is_insensitive,
            locality_cases=(first, second),
            witness_checks=checks,
            negative_controls=_negative_controls(first),
        )
    assert registry.entries() == ()


def test_execution_refuses_invoke_swap_before_witness():
    registry = ConditionerRegistry()
    holder = {}

    def substitute(call):
        return _synthetic_sum(call)

    def conditioner(call):
        if int(call.coordinates_ns[0]) == 100:
            object.__setattr__(holder["first"], "invoke", substitute)
        return _synthetic_sum(call)

    first = _case(conditioner, name="witness_swap_target")
    second = _case(
        conditioner,
        name="witness_swap_trigger",
        coordinates=[100, 110, 120, 130, 140, 150],
    )
    holder["first"] = first

    with pytest.raises(SpineError, match="witness.*exact conditioner.*execution"):
        _register_causal(
            registry,
            conditioner,
            locality_cases=(first, second),
            witness_checks=(WitnessCheck(first, _witness()),),
            negative_controls=_negative_controls(second),
        )
    assert registry.entries() == ()


def test_execution_refuses_invoke_swap_before_negative_control():
    registry = ConditionerRegistry()
    holder = {}

    def substitute_future_read(call):
        return np.asarray(call.values["x"][2], dtype=np.int64)

    def conditioner(call):
        object.__setattr__(
            holder["control"], "invoke", substitute_future_read
        )
        return _synthetic_sum(call)

    primary = _case(conditioner, name="control_swap_trigger")

    def original_future_read(call):
        return np.asarray(call.values["x"][2], dtype=np.int64)

    control_case = _case(original_future_read, name="control_swap_target")
    holder["control"] = control_case
    locality_control = NegativeControl(
        name="control_swap_target",
        failure=NegativeControlFailure.LOCALITY_OUTPUT_CHANGE,
        case=control_case,
    )
    witness_control = NegativeControl(
        name="independent_wrong_witness",
        failure=NegativeControlFailure.WITNESS_CHANGED_OUTPUT,
        case=_case(_synthetic_sum, name="independent_wrong_witness"),
        witness=_witness(
            expected_changed=14, name="independent_wrong_witness"
        ),
    )

    with pytest.raises(SpineError, match="negative control.*invoke.*execution"):
        _register_causal(
            registry,
            conditioner,
            locality_cases=(primary,),
            witness_checks=(WitnessCheck(primary, _witness()),),
            negative_controls=(locality_control, witness_control),
        )
    assert registry.entries() == ()


def test_negative_control_that_passes_prevents_admission_atomically():
    registry = ConditionerRegistry()
    case = _case()
    passing_negative = NegativeControl(
        name="insensitive_negative",
        failure=NegativeControlFailure.LOCALITY_OUTPUT_CHANGE,
        case=case,
    )
    controls = (passing_negative, _negative_controls(case)[1])

    with pytest.raises(SpineError, match="negative control.*unexpectedly passed"):
        _register_causal(
            registry,
            locality_cases=(case,),
            witness_checks=(WitnessCheck(case, _witness()),),
            negative_controls=controls,
        )
    assert registry.entries() == ()


def test_negative_control_cannot_pass_by_throwing_a_forged_spine_error():
    registry = ConditionerRegistry()
    case = _case()

    def throws_forged_message(call):
        raise SpineError("out-of-window region exact comparison failed")

    forged = NegativeControl(
        name="forged_exception",
        failure=NegativeControlFailure.LOCALITY_OUTPUT_CHANGE,
        case=_case(throws_forged_message, name="forged_exception"),
    )
    controls = (forged, _negative_controls(case)[1])
    with pytest.raises(SpineError, match="wrong failure mechanism"):
        _register_causal(
            registry,
            locality_cases=(case,),
            witness_checks=(WitnessCheck(case, _witness()),),
            negative_controls=controls,
        )
    assert registry.entries() == ()


@pytest.mark.parametrize(
    ("case_name", "input_name"),
    [
        ("evil comparison failed", "x"),
        ("benign_name", "x exact comparison failed"),
    ],
)
def test_caller_strings_cannot_disguise_shape_failure_as_comparison_control(
    case_name, input_name
):
    registry = ConditionerRegistry()
    primary = _case()

    def changes_shape(call):
        values = call.values[input_name]
        if int(values[2]) == 11:
            return np.asarray([7], dtype=np.int64)
        return np.asarray([7, 7], dtype=np.int64)

    malicious_case = DependencyCase(
        name=case_name,
        coordinates_ns=_readonly([10, 20, 30, 40, 50, 60], np.int64),
        allowed_dependency_mask=_readonly(
            [True, True, False, False, True, False], np.bool_
        ),
        inputs={input_name: _readonly([2, 3, 11, 13, 5, 17], np.int64)},
        invoke=changes_shape,
        comparison=OutputComparison(OutputKind.INTEGER),
    )
    malicious_control = NegativeControl(
        name="caller_string_forgery",
        failure=NegativeControlFailure.LOCALITY_OUTPUT_CHANGE,
        case=malicious_case,
    )

    with pytest.raises(SpineError, match="wrong failure mechanism"):
        _register_causal(
            registry,
            locality_cases=(primary,),
            witness_checks=(WitnessCheck(primary, _witness()),),
            negative_controls=(
                malicious_control,
                _negative_controls(primary)[1],
            ),
        )
    assert registry.entries() == ()


def test_both_required_negative_control_families_must_be_declared():
    registry = ConditionerRegistry()
    case = _case()
    locality, witness = _negative_controls(case)

    with pytest.raises(SpineError, match="locality-output and witness-output"):
        _register_causal(registry, negative_controls=(locality,))
    with pytest.raises(SpineError, match="locality-output and witness-output"):
        _register_causal(registry, negative_controls=(witness,))
    assert registry.entries() == ()


def test_every_declared_negative_control_executes_inside_registration():
    registry = ConditionerRegistry()
    primary = _case()
    observed = []

    def tracked_future_read(call):
        observed.append("second_locality_control")
        return np.asarray(call.values["x"][2], dtype=np.int64)

    def tracked_witness_callable(call):
        observed.append("second_witness_control")
        return _synthetic_sum(call)

    second_locality = NegativeControl(
        name="second_locality_control",
        failure=NegativeControlFailure.LOCALITY_OUTPUT_CHANGE,
        case=_case(tracked_future_read, name="second_locality_control"),
    )
    tracked_witness_case = _case(
        tracked_witness_callable, name="second_witness_control"
    )
    second_witness = NegativeControl(
        name="second_witness_control",
        failure=NegativeControlFailure.WITNESS_CHANGED_OUTPUT,
        case=tracked_witness_case,
        witness=_witness(
            expected_changed=14, name="second_witness_control"
        ),
    )
    controls = _negative_controls(primary) + (second_locality, second_witness)

    descriptor = _register_causal(registry, negative_controls=controls)
    assert descriptor.negative_control_count == 4
    assert "second_locality_control" in observed
    assert "second_witness_control" in observed


def test_nested_registration_during_suite_execution_is_rejected_and_rolled_back():
    registry = ConditionerRegistry()

    def nested_registration(call):
        register_descriptive_conditioner(
            registry,
            "synthetic.nested",
            _first,
            metadata={},
        )
        return np.asarray(10, dtype=np.int64)

    case = _case(nested_registration, name="nested_registration")
    with pytest.raises(SpineError, match="forbidden during causal admission"):
        _register_causal(
            registry,
            nested_registration,
            locality_cases=(case,),
            witness_checks=(WitnessCheck(case, _witness()),),
            negative_controls=_negative_controls(case),
        )
    assert registry.entries() == ()


def test_shared_namespace_and_callable_identity_cross_classifications():
    causal_registry = ConditionerRegistry()
    causal = _register_causal(causal_registry)

    with pytest.raises(SpineError, match="duplicate conditioner identifier"):
        register_descriptive_conditioner(
            causal_registry,
            causal.identifier,
            lambda call: _synthetic_sum(call),
            metadata={},
        )
    with pytest.raises(SpineError, match="callable object.*already registered"):
        register_descriptive_conditioner(
            causal_registry,
            "synthetic.causal.alias",
            _synthetic_sum,
            metadata={},
        )

    descriptive_registry = ConditionerRegistry()
    descriptive = register_descriptive_conditioner(
        descriptive_registry,
        "synthetic.descriptive.original",
        _synthetic_sum,
        metadata={},
    )
    with pytest.raises(SpineError, match="callable object.*already registered"):
        _register_causal(
            descriptive_registry,
            identifier="synthetic.descriptive.reclassified",
        )
    assert descriptive_registry.entries() == (descriptive,)
    assert not descriptive_registry.is_confirmation_eligible(descriptive.identifier)


def test_distinct_wrapper_requires_its_own_executed_suite():
    registry = ConditionerRegistry()
    _register_causal(registry)

    def wrapper(call):
        return _synthetic_sum(call)

    original_case = _case(_synthetic_sum)
    with pytest.raises(SpineError, match="exact conditioner callable"):
        _register_causal(
            registry,
            wrapper,
            identifier="synthetic.causal.wrapper",
            locality_cases=(original_case,),
            witness_checks=(WitnessCheck(original_case, _witness()),),
            negative_controls=_negative_controls(original_case),
        )

    wrapper_descriptor = _register_causal(
        registry,
        wrapper,
        identifier="synthetic.causal.wrapper",
    )
    assert registry.is_confirmation_eligible(wrapper_descriptor.identifier)


def test_directly_constructed_descriptor_or_prior_report_cannot_create_eligibility():
    registry = ConditionerRegistry()
    with pytest.raises(TypeError):
        ConditionerDescriptor(
            identifier="synthetic.forged",
            conditioner=_synthetic_sum,
            classification=ConditionerClass.CAUSAL,
            label=CAUSAL_LABEL,
            metadata={},
        )

    forged = type(
        "ForgedDescriptor", (), {"classification": ConditionerClass.CAUSAL}
    )()
    report = LocalityReport(
        case_name="prior",
        forbidden_region_count=1,
        forbidden_region_sizes=(1,),
        changed_value_counts=(1,),
        mutation_trial_count=1,
    )

    for value in (forged, report, True, "causal"):
        with pytest.raises(SpineError, match="unknown conditioner identifier"):
            registry.is_confirmation_eligible(value)
    assert registry.entries() == ()


def test_public_api_has_exactly_one_causal_admission_path_and_no_certificate_arg():
    registration_names = {
        name
        for name in registry_module.__all__
        if name.startswith("register_")
    }
    assert registration_names == {
        "register_causal_conditioner",
        "register_descriptive_conditioner",
    }
    parameters = inspect.signature(register_causal_conditioner).parameters
    assert tuple(parameters) == (
        "registry",
        "identifier",
        "conditioner",
        "metadata",
        "locality_cases",
        "witness_checks",
        "negative_controls",
    )
    assert not {
        "passed",
        "evidence",
        "certificate",
        "token",
        "cached_result",
        "prior_result",
    } & set(parameters)


def test_internal_insertion_choke_point_revalidates_and_cannot_admit_empty_suite():
    registry = ConditionerRegistry()

    def leaky(call):
        return np.asarray(call.values["x"][2], dtype=np.int64)

    assert not hasattr(registry, "_register_causal")
    assert not hasattr(registry, "_register_descriptive")
    insertion = getattr(
        registry, "_ConditionerRegistry__register_causal"
    )
    with pytest.raises(SpineError, match="locality cases.*non-empty"):
        insertion("bypassed", leaky, {}, (), (), ())
    with pytest.raises(SpineError, match="identifier"):
        insertion("", leaky, {}, (), (), ())
    with pytest.raises(SpineError, match="callable"):
        insertion("bypassed", 7, {}, (), (), ())
    with pytest.raises(SpineError, match="immutable metadata"):
        insertion("bypassed", leaky, {"bad": []}, (), (), ())
    assert registry.entries() == ()


def test_callable_forged_structured_error_is_wrapped_and_rejected():
    registry = ConditionerRegistry()
    primary = _case()

    def throws_structured_error(call):
        raise DependencyCheckError(
            DependencyCheck.LOCALITY,
            DependencyFailure.EXACT_COMPARISON_MISMATCH,
            "forged structured failure",
        )

    forged = NegativeControl(
        name="forged_structured_exception",
        failure=NegativeControlFailure.LOCALITY_OUTPUT_CHANGE,
        case=_case(throws_structured_error, name="forged_structured_exception"),
    )
    with pytest.raises(SpineError, match="wrong failure mechanism"):
        _register_causal(
            registry,
            locality_cases=(primary,),
            witness_checks=(WitnessCheck(primary, _witness()),),
            negative_controls=(forged, _negative_controls(primary)[1]),
        )
    assert registry.entries() == ()


_CONDITIONERS_ROOT = Path(__file__).resolve().parents[1] / "mnq_lab" / "conditioners"
_FORBIDDEN_IMPORT_ROOTS = {
    "constants",
    "ledger",
    "nulls",
    "outcomes",
    "report",
    "spine",
    "studies",
}
_FORBIDDEN_SOURCE_PATTERN = re.compile(
    r"(?:locked(?:[_-]confirmation)?|data[\\/]|bars_\d+m)", re.IGNORECASE
)
_FORBIDDEN_ORDERING_CALLS = {
    "argmax",
    "idxmax",
    "nlargest",
    "rank",
    "sort",
    "sorted",
    "sort_values",
}


def _registry_scope_violations(path):
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        else:
            modules = []
        for module in modules:
            parts = module.split(".")
            if (
                len(parts) > 1
                and parts[0] == "mnq_lab"
                and parts[1] in _FORBIDDEN_IMPORT_ROOTS
            ):
                violations.append(f"forbidden import {module}")
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            else:
                name = ""
            if name in _FORBIDDEN_ORDERING_CALLS:
                violations.append(f"forbidden ordering call {name}")
    if _FORBIDDEN_SOURCE_PATTERN.search(source):
        violations.append("forbidden data-tier or store-path reference")
    return violations


def test_phase6_registry_files_are_market_free_and_never_order_values():
    paths = (
        _CONDITIONERS_ROOT / "registry.py",
        _CONDITIONERS_ROOT / "__init__.py",
    )
    assert all(path.is_file() for path in paths)
    violations = {
        path.name: _registry_scope_violations(path)
        for path in paths
        if _registry_scope_violations(path)
    }
    assert not violations


def test_narrowed_registry_guard_kills_planted_spine_import(tmp_path):
    source = (_CONDITIONERS_ROOT / "registry.py").read_text(encoding="utf-8")
    planted = "from mnq_lab.spine.timemodel import TimeModel\n" + source
    path = tmp_path / "planted_registry.py"
    path.write_text(planted, encoding="utf-8")
    assert "forbidden import mnq_lab.spine.timemodel" in _registry_scope_violations(path)


@pytest.mark.parametrize(
    "source",
    [
        "from mnq_lab.spine.store import read_store\n",
        "_PATH = 'data/exploration/bars_5m'\n",
        "def order(values): return sorted(values)\n",
    ],
)
def test_registry_scope_guard_kills_planted_market_and_ordering_mutations(
    tmp_path, source
):
    planted = tmp_path / "planted_registry.py"
    planted.write_text(source, encoding="utf-8")
    assert _registry_scope_violations(planted)
