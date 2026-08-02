"""Integrated real-callable Phase 7 registry admission gate."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.conditioners.admission import (
    PHASE7_ADMISSION_SPECS,
    admission_suite,
    assert_semantic_mask_equal,
    build_phase7_registry,
)
from mnq_lab.conditioners.arms import ARM_CONFIGS
from mnq_lab.conditioners.registry import (
    ConditionerClass,
    ConditionerRegistry,
    register_causal_conditioner,
)
from tests.phase7_contract_oracles import composite_row_mask


def test_exact_real_callable_inventory_enters_causal_registry_atomically():
    registry = build_phase7_registry()
    descriptors = registry.entries()
    assert len(descriptors) == 35
    assert tuple(item.identifier for item in descriptors) == tuple(
        spec.identifier for spec in PHASE7_ADMISSION_SPECS
    )
    assert all(item.classification is ConditionerClass.CAUSAL for item in descriptors)
    assert all(item.locality_case_count == 1 for item in descriptors)
    assert all(item.witness_count == 1 for item in descriptors)
    assert all(item.negative_control_count == 2 for item in descriptors)
    assert len({id(item.conditioner) for item in descriptors}) == 35
    assert [item.metadata["arm_order"] for item in descriptors[-10:]] == list(range(10))


def test_registration_metadata_is_complete_immutable_and_never_selective():
    registry = build_phase7_registry()
    required = {
        "stage",
        "arm_id",
        "arm_order",
        "estimator_kind",
        "halflife",
        "mad_window",
        "coverage_rule",
        "warmup",
        "bucket_timezone",
        "calendar_version",
        "calendar_sha256",
        "threshold_history",
        "lower_probability",
        "upper_probability",
        "semantic_mask_version",
        "output_kind",
        "atol",
        "rtol",
        "sensitivity_factor",
        "sensitivity_value",
    }
    for descriptor in registry.entries():
        assert set(descriptor.metadata) == required
        assert descriptor.metadata["bucket_timezone"] == "America/Chicago"
        assert "best" not in descriptor.metadata.values()
        with pytest.raises(TypeError):
            descriptor.metadata["selected"] = True


def test_every_declared_mask_equals_an_independent_contract_oracle():
    required_indices = {
        "scale": tuple(range(1, 80)),
        "seasonal_profile": (0, 1, 2, 3, 4),
        "vol_rel": (0, 1, 2, 3, 4, 5),
        "thresholds": (0, 1, 2, 3, 4),
        "assignment": (0, 1, 2, 3, 4, 5),
    }
    for spec in PHASE7_ADMISSION_SPECS:
        size = spec.declared_mask.size
        expected = composite_row_mask(size, required_indices[spec.stage])
        # The test oracle is structurally independent and then checked by the
        # production admission assertion as a second direction.
        assert np.array_equal(spec.declared_mask, expected)
        assert_semantic_mask_equal(spec.stage, spec.declared_mask)

        leading = np.array(spec.declared_mask, copy=True)
        false_before = np.flatnonzero(~leading & (np.arange(size) < np.flatnonzero(leading)[0]))
        if false_before.size:
            leading[int(false_before[-1])] = True
            with pytest.raises(SpineError, match="semantic mask"):
                assert_semantic_mask_equal(spec.stage, leading)
        trailing = np.array(spec.declared_mask, copy=True)
        false_after = np.flatnonzero(~trailing & (np.arange(size) > np.flatnonzero(trailing)[-1]))
        assert false_after.size
        trailing[int(false_after[0])] = True
        with pytest.raises(SpineError, match="semantic mask"):
            assert_semantic_mask_equal(spec.stage, trailing)


def test_caller_cannot_borrow_another_real_callable_evidence():
    original = PHASE7_ADMISSION_SPECS[0]
    borrower = PHASE7_ADMISSION_SPECS[1]
    case, witness, controls = admission_suite(original)
    registry = ConditionerRegistry()
    with pytest.raises(SpineError, match="exact conditioner callable"):
        register_causal_conditioner(
            registry,
            "mnq.phase7.scale.borrowed.v1",
            borrower.invoke,
            metadata={"stage": "scale"},
            locality_cases=(case,),
            witness_checks=(witness,),
            negative_controls=controls,
        )
    assert registry.entries() == ()


def test_unknown_or_duplicate_phase7_identity_fails_closed():
    assert len(PHASE7_ADMISSION_SPECS) == 5 + 5 + 5 + 10 + 10
    assert tuple(config.order for config in ARM_CONFIGS) == tuple(range(10))
    duplicate = replace(
        PHASE7_ADMISSION_SPECS[1],
        config=PHASE7_ADMISSION_SPECS[0].config,
    )
    assert duplicate.identifier == PHASE7_ADMISSION_SPECS[0].identifier
    registry = build_phase7_registry()
    case, witness, controls = admission_suite(duplicate)
    with pytest.raises(SpineError, match="duplicate conditioner identifier"):
        register_causal_conditioner(
            registry,
            duplicate.identifier,
            duplicate.invoke,
            metadata={"stage": duplicate.stage},
            locality_cases=(case,),
            witness_checks=(witness,),
            negative_controls=controls,
        )
