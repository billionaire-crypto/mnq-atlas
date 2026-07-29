"""Phase 4 weight concentration and generic weight construction."""

from __future__ import annotations

import inspect
import math

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.core.weights import (
    GroupWeightDiagnostics,
    WeightDiagnostics,
    anchor_equal_weights,
    session_equal_weights,
    weight_ess,
    weighted_quantile,
)

REL_TOLERANCE = 1e-12


def _group_masses(diagnostics):
    return dict(diagnostics.group_total_mass)


def test_weight_ess_is_the_exact_frozen_formula_on_hand_computed_weights():
    weights = np.array([1.0, 2.0, 3.0])

    assert weight_ess(weights) == (6.0**2) / (1.0 + 4.0 + 9.0)
    assert weight_ess(weights) != float(np.sum(weights))
    assert weight_ess(weights) != 1.0 / np.sum(weights**2)


def test_equal_dyadic_weights_give_the_positive_weight_count_exactly():
    assert weight_ess(np.full(7, 0.25)) == 7.0


def test_equal_nondyadic_weights_use_the_declared_floating_tolerance():
    assert weight_ess(np.full(7, 0.1)) == pytest.approx(
        7.0, rel=REL_TOLERANCE
    )


def test_one_positive_weight_gives_one_and_zeros_are_algebraically_ignored():
    assert weight_ess([0.0, 3.0, 0.0]) == 1.0
    assert weight_ess([1.0, 2.0]) == weight_ess([0.0, 1.0, 0.0, 2.0])


def test_weight_ess_positive_rescaling_is_semantically_invariant():
    weights = np.array([0.1, 0.2, 0.7])

    assert weight_ess(weights * 3.7) == pytest.approx(
        weight_ess(weights), rel=REL_TOLERANCE
    )


def test_weight_ess_does_not_mutate_float64_input():
    weights = np.array([0.1, 0.2, 0.7], dtype=np.float64)
    before = weights.tobytes()
    dtype = weights.dtype

    weight_ess(weights)

    assert weights.tobytes() == before
    assert weights.dtype == dtype


def test_concentrated_weights_lower_weight_ess():
    equal = weight_ess([0.25, 0.25, 0.25, 0.25])
    concentrated = weight_ess([0.97, 0.01, 0.01, 0.01])

    assert equal == 4.0
    assert concentrated < equal


def test_weight_ess_naming_and_diagnostic_fields_are_honest():
    assert weight_ess.__name__ == "weight_ess"
    assert "effective sample size" not in inspect.getdoc(weight_ess).lower()
    assert set(WeightDiagnostics.__dataclass_fields__) == {
        "row_count",
        "weight_ess",
    }
    assert "weight_ess" in GroupWeightDiagnostics.__dataclass_fields__


@pytest.mark.parametrize(
    ("weights", "message"),
    [
        ([], "at least one"),
        ([[1.0]], "one-dimensional"),
        ([1.0, -1.0], "negative"),
        ([0.0, 0.0], "positive total"),
        ([True, 1.0], "bool"),
        ([1.0, np.nan], "non-finite"),
        ([1.0, np.inf], "non-finite"),
        (np.array([1.0], dtype=object), "real integer or floating"),
        ([2**53 + 1], r"2\*\*53"),
    ],
)
def test_weight_ess_malformed_inputs_fail_closed(weights, message):
    with pytest.raises(SpineError, match=message):
        weight_ess(weights)


def test_unbalanced_session_equal_and_anchor_equal_quantiles_differ():
    group_ids = np.array(["small", *(["large"] * 7)])
    values = np.array([0.0, *([10.0] * 7)])
    session_weights, diagnostics = session_equal_weights(group_ids)
    anchor_weights, anchor_diagnostics = anchor_equal_weights(len(group_ids))

    assert session_weights[0] == 0.5
    assert np.all(session_weights[1:] == 1.0 / 14.0)
    assert np.all(anchor_weights == 1.0 / 8.0)
    assert weighted_quantile(values, session_weights, 0.25) == 0.0
    assert weighted_quantile(values, anchor_weights, 0.25) == 10.0
    assert diagnostics.contributing_group_count == 2
    assert diagnostics.row_count == anchor_diagnostics.row_count == 8


def test_equal_size_groups_have_bit_equal_session_mass():
    group_ids = np.array(["a", "a", "b", "b", "c", "c"])
    _, diagnostics = session_equal_weights(group_ids)
    masses = list(_group_masses(diagnostics).values())

    assert masses[0] == masses[1] == masses[2]


def test_unbalanced_session_mass_uses_declared_tolerance_and_kills_anchor_mutation():
    group_ids = np.array(["small", *(["large"] * 7)])
    session_weights, diagnostics = session_equal_weights(group_ids)
    anchor_weights, _ = anchor_equal_weights(len(group_ids))
    session_masses = _group_masses(diagnostics)
    anchor_small_mass = float(np.sum(anchor_weights[group_ids == "small"]))
    anchor_large_mass = float(np.sum(anchor_weights[group_ids == "large"]))

    assert session_masses["small"] == pytest.approx(
        0.5, rel=REL_TOLERANCE
    )
    assert session_masses["large"] == pytest.approx(
        0.5, rel=REL_TOLERANCE
    )
    assert not math.isclose(
        anchor_small_mass, 0.5, rel_tol=REL_TOLERANCE, abs_tol=0.0
    )
    assert not math.isclose(
        anchor_large_mass, 0.5, rel_tol=REL_TOLERANCE, abs_tol=0.0
    )
    assert session_weights[0] != anchor_weights[0]


def test_within_each_group_rows_receive_equal_mass():
    group_ids = np.array(["b", "a", "b", "c", "c", "c"])
    weights, _ = session_equal_weights(group_ids)

    for label in ("a", "b", "c"):
        assert np.unique(weights[group_ids == label]).size == 1


def test_only_present_groups_contribute_and_labels_are_opaque():
    group_ids = np.array([101, 101, 303, 303, 303])
    _, diagnostics = session_equal_weights(group_ids)

    assert diagnostics.contributing_group_count == 2
    assert [label for label, _ in diagnostics.group_total_mass] == [101, 303]


def test_duplicating_one_group_preserves_its_session_mass_but_changes_anchor_mass():
    base_groups = np.array(["a", "b", "b", "b"])
    duplicated_groups = np.array(["a", *(["b"] * 6)])
    _, base_session = session_equal_weights(base_groups)
    _, duplicated_session = session_equal_weights(duplicated_groups)
    base_anchor_weights, _ = anchor_equal_weights(len(base_groups))
    duplicated_anchor_weights, _ = anchor_equal_weights(len(duplicated_groups))

    assert _group_masses(base_session)["b"] == pytest.approx(
        _group_masses(duplicated_session)["b"], rel=REL_TOLERANCE
    )
    base_anchor_mass = float(
        np.sum(base_anchor_weights[base_groups == "b"])
    )
    duplicated_anchor_mass = float(
        np.sum(duplicated_anchor_weights[duplicated_groups == "b"])
    )
    assert duplicated_anchor_mass > base_anchor_mass


def test_session_weights_align_with_noncanonical_input_row_order():
    group_ids = np.array(["b", "a", "b", "c", "c", "c"])
    weights, diagnostics = session_equal_weights(group_ids)

    assert np.array_equal(
        weights,
        np.array([1 / 6, 1 / 3, 1 / 6, 1 / 9, 1 / 9, 1 / 9]),
    )
    assert diagnostics.contributing_group_count == 3


def test_group_ids_are_not_mutated():
    group_ids = np.array(["b", "a", "b", "c"], dtype="<U1")
    before = group_ids.tobytes()
    dtype = group_ids.dtype

    session_equal_weights(group_ids)

    assert group_ids.tobytes() == before
    assert group_ids.dtype == dtype


def test_max_group_mass_fraction_uses_group_totals_not_anchor_maximum():
    group_ids = np.array([*(["a"] * 2), *(["b"] * 3), *(["c"] * 5)])
    weights, diagnostics = session_equal_weights(group_ids)

    assert diagnostics.max_group_mass_fraction == pytest.approx(
        1 / 3, rel=REL_TOLERANCE
    )
    assert np.max(weights) == 1 / 6
    assert diagnostics.max_group_mass_fraction != np.max(weights)


def test_anchor_equal_weights_and_diagnostics():
    weights, diagnostics = anchor_equal_weights(8)

    assert weights.dtype == np.float64
    assert np.all(weights == 1 / 8)
    assert diagnostics == WeightDiagnostics(row_count=8, weight_ess=8.0)


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
def test_malformed_group_identifiers_fail_closed(group_ids):
    with pytest.raises(SpineError):
        session_equal_weights(group_ids)


@pytest.mark.parametrize("n", [0, -1, 1.5, True, "2", None])
def test_malformed_anchor_counts_fail_closed(n):
    with pytest.raises(SpineError):
        anchor_equal_weights(n)
