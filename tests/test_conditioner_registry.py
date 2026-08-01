"""Phase 6 conditioner-registry lifecycle and classification tests.

Only synthetic callables appear here.  Real conditioners remain Phase 7.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import inspect
import math

import pytest

from mnq_lab import SpineError
from mnq_lab.conditioners.registry import (
    DESCRIPTIVE_LABEL,
    ConditionerClass,
    ConditionerRegistry,
    register_descriptive_conditioner,
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
