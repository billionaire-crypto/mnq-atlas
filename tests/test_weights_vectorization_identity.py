"""D30 vectorization of ``session_equal_weights`` is byte-identical.

D30 authorizes replacing the accidentally quadratic ``O(groups * n)`` mask
scans and the per-element validation loop in
``mnq_lab/core/weights.py:session_equal_weights`` with vectorized
equivalents. The acceptance gate is byte equality of every output field, not
numerical closeness: per D27, a plausible argument is not a proof.

Following the pattern D28 established for the prepared quantile ordering,
the pre-change algorithm is retained here verbatim as an independent
executable oracle. The production implementation is compared against it.

No single fixture detects every fault class, and this file proves that:

* The real production session ids are chronological, so sorted group order
  and first-occurrence group order coincide. Ordering faults are invisible
  there and are caught only by deliberately unsorted fixtures.
* numpy only switches ``np.sum`` to pairwise summation above a size
  threshold, so summation-order faults are invisible on small fixtures and
  are caught only by large ones.

``test_negative_control_*`` prove the comparison detects each fault class. A
check that cannot fail is worse than no check, because it manufactures
confidence.
"""

from __future__ import annotations

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.core.weights import (
    GroupWeightDiagnostics,
    _as_opaque_group_labels,
    session_equal_weights,
    weight_ess,
)


def _reference_factorize(labels):
    """The original dict-insertion-order group assignment, verbatim."""
    group_index: dict = {}
    unique_labels: list = []
    counts: list[int] = []
    inverse = np.empty(len(labels), dtype=np.intp)
    for row_index, label in enumerate(labels):
        index = group_index.get(label)
        if index is None:
            index = len(unique_labels)
            group_index[label] = index
            unique_labels.append(label)
            counts.append(0)
        counts[index] += 1
        inverse[row_index] = index
    return inverse, counts, unique_labels


def _reference_session_equal_weights(group_ids):
    """The pre-D30 implementation, retained as an executable oracle.

    Deliberately keeps the ``O(groups * n)`` mask scans. This is the
    behaviour the vectorized production code must reproduce bit for bit.
    """
    labels = _as_opaque_group_labels(group_ids)
    inverse, counts, unique_labels = _reference_factorize(labels)
    group_count = len(unique_labels)
    weights = np.empty(len(labels), dtype=np.float64)
    for index, count in enumerate(counts):
        weights[inverse == index] = 1.0 / (group_count * count)
    group_masses = np.array(
        [
            np.sum(weights[inverse == index], dtype=np.float64)
            for index in range(group_count)
        ],
        dtype=np.float64,
    )
    total_group_mass = np.sum(group_masses, dtype=np.float64)
    if not np.isfinite(total_group_mass) or not total_group_mass > 0.0:
        raise SpineError("constructed group weights have invalid total mass")
    diagnostics = GroupWeightDiagnostics(
        row_count=len(labels),
        weight_ess=weight_ess(weights),
        contributing_group_count=group_count,
        group_total_mass=tuple(
            (label, float(mass))
            for label, mass in zip(unique_labels, group_masses)
        ),
        max_group_mass_fraction=float(np.max(group_masses) / total_group_mass),
    )
    return weights, diagnostics


def _fields_identical(left, right) -> bool:
    weights_left, diagnostics_left = left
    weights_right, diagnostics_right = right
    return (
        weights_left.tobytes() == weights_right.tobytes()
        and diagnostics_left.row_count == diagnostics_right.row_count
        and diagnostics_left.weight_ess == diagnostics_right.weight_ess
        and diagnostics_left.contributing_group_count
        == diagnostics_right.contributing_group_count
        and diagnostics_left.group_total_mass == diagnostics_right.group_total_mass
        and diagnostics_left.max_group_mass_fraction
        == diagnostics_right.max_group_mass_fraction
    )


# Chronological ascending ids, shaped like the real ratified slice: enough
# rows PER GROUP that np.sum switches to pairwise summation and so diverges
# from sequential accumulation. This was determined empirically -- 6 rows per
# group does NOT diverge, 50 does, and the real slice averages ~156. Shrinking
# rows-per-group below ~50 would silently make the summation-order negative
# control vacuous.
_ROWS_PER_GROUP = 50
_GROUP_COUNT = 100
_CHRONOLOGICAL = tuple(
    int(20200101 + day)
    for day in range(_GROUP_COUNT)
    for _ in range(_ROWS_PER_GROUP)
)
# The same size and group structure but descending, so first-occurrence order
# and sorted order disagree on every group.
_DESCENDING = tuple(
    int(20200101 + day)
    for day in range(_GROUP_COUNT, 0, -1)
    for _ in range(_ROWS_PER_GROUP)
)

IDENTITY_FIXTURES = [
    pytest.param(_CHRONOLOGICAL, id="large-chronological-like-production"),
    pytest.param(_DESCENDING, id="large-descending-order-differs"),
    pytest.param(tuple(range(4000)), id="large-all-unique"),
    pytest.param((7,) * 4000, id="large-single-group"),
    pytest.param((5, 5, 5, 1, 1, 2, 2, 2, 2, 9, 5, 1), id="small-with-ties"),
    pytest.param((3, 1, 2), id="unique-unsorted"),
    pytest.param((10, 1, 10, 1, 10), id="interleaved-two-groups"),
    pytest.param(np.array([4, 4, 9, 1], dtype=np.int32), id="numpy-int32"),
    pytest.param(np.array([4, 4, 9, 1], dtype=np.uint16), id="numpy-uint16"),
    pytest.param(np.array([-3, -3, 7], dtype=np.int64), id="negative-ints"),
    pytest.param(("b", "a", "a", "c"), id="strings-fall-back"),
    pytest.param((1.5, 2.5, 1.5), id="floats-fall-back"),
    pytest.param((1, 2.5, 1), id="mixed-int-float-falls-back"),
    pytest.param((b"x", b"y", b"x"), id="bytes-fall-back"),
    pytest.param((1, "1"), id="int-and-str-one-must-not-merge"),
]


@pytest.mark.parametrize("group_ids", IDENTITY_FIXTURES)
def test_vectorized_weights_are_byte_identical_to_the_original(group_ids):
    assert _fields_identical(
        session_equal_weights(group_ids),
        _reference_session_equal_weights(group_ids),
    )


def test_int_and_string_one_are_not_merged_into_a_single_group():
    """numpy coerces ``(1, "1")`` to two equal strings; grouping must not."""
    _, diagnostics = session_equal_weights((1, "1"))
    assert diagnostics.contributing_group_count == 2


REJECT_FIXTURES = [
    pytest.param([], id="empty-list"),
    pytest.param([["a"]], id="two-dimensional"),
    pytest.param([True, "a"], id="bool-label"),
    pytest.param([None], id="none-label"),
    pytest.param([np.nan], id="nan-label"),
    pytest.param([np.inf], id="inf-label"),
    pytest.param([1 + 0j], id="complex-label"),
    pytest.param([{"not": "a scalar label"}], id="unhashable-label"),
    pytest.param(np.array([[1, 2], [3, 4]]), id="two-dimensional-int-array"),
    pytest.param(np.array([], dtype=np.int64), id="empty-int-array"),
    pytest.param(np.array([True, False]), id="bool-array"),
]


@pytest.mark.parametrize("group_ids", REJECT_FIXTURES)
def test_rejection_messages_are_unchanged(group_ids):
    with pytest.raises(SpineError) as production:
        session_equal_weights(group_ids)
    with pytest.raises(SpineError) as oracle:
        _reference_session_equal_weights(group_ids)
    assert str(production.value) == str(oracle.value)


# --------------------------------------------------------------------------
# Negative control. Each mutant is a real fault class. Every one must be
# detected by at least one fixture, otherwise the identity assertions above
# are vacuous.
# --------------------------------------------------------------------------


def _mutant_one_ulp(group_ids):
    weights, diagnostics = _reference_session_equal_weights(group_ids)
    perturbed = weights.copy()
    perturbed[0] = np.nextafter(perturbed[0], np.inf)
    return perturbed, diagnostics


def _mutant_summation_order(group_ids):
    """Correct values, accumulated sequentially instead of pairwise."""
    labels = _as_opaque_group_labels(group_ids)
    inverse, counts, unique_labels = _reference_factorize(labels)
    group_count = len(counts)
    weights = (1.0 / (group_count * np.asarray(counts, dtype=np.float64)))[inverse]
    masses = np.bincount(inverse, weights=weights, minlength=group_count)
    total = np.sum(masses, dtype=np.float64)
    return weights, GroupWeightDiagnostics(
        row_count=len(labels),
        weight_ess=weight_ess(weights),
        contributing_group_count=group_count,
        group_total_mass=tuple(
            (label, float(mass)) for label, mass in zip(unique_labels, masses)
        ),
        max_group_mass_fraction=float(np.max(masses) / total),
    )


def _mutant_group_order(group_ids):
    """Correct values, groups reported sorted instead of first-seen."""
    weights, diagnostics = _reference_session_equal_weights(group_ids)
    return weights, GroupWeightDiagnostics(
        row_count=diagnostics.row_count,
        weight_ess=diagnostics.weight_ess,
        contributing_group_count=diagnostics.contributing_group_count,
        group_total_mass=tuple(sorted(diagnostics.group_total_mass)),
        max_group_mass_fraction=diagnostics.max_group_mass_fraction,
    )


@pytest.mark.parametrize(
    ("mutant", "detecting_fixture"),
    [
        # A one-ULP weight error is caught everywhere.
        pytest.param(_mutant_one_ulp, _CHRONOLOGICAL, id="one-ulp-weight"),
        # Summation order needs a fixture large enough for pairwise summation.
        pytest.param(
            _mutant_summation_order, _CHRONOLOGICAL, id="summation-order-large"
        ),
        # Group order needs a fixture whose sorted order differs from
        # first-occurrence order. The chronological one cannot detect this.
        pytest.param(_mutant_group_order, _DESCENDING, id="group-order-descending"),
    ],
)
def test_negative_control_each_fault_class_is_detected(mutant, detecting_fixture):
    assert not _fields_identical(
        mutant(detecting_fixture),
        _reference_session_equal_weights(detecting_fixture),
    )


def test_negative_control_chronological_data_cannot_detect_group_ordering():
    """Documents why the descending fixture exists and must not be deleted.

    Real session ids are chronological, so a group-ordering fault is
    invisible on production-shaped data. Removing the descending fixture
    would silently make the ordering assertion vacuous.
    """
    assert _fields_identical(
        _mutant_group_order(_CHRONOLOGICAL),
        _reference_session_equal_weights(_CHRONOLOGICAL),
    )


def test_negative_control_small_data_cannot_detect_summation_order():
    """Documents why a large fixture is required for the summation check."""
    small = (5, 5, 1, 2, 2, 2, 9)
    assert _fields_identical(
        _mutant_summation_order(small),
        _reference_session_equal_weights(small),
    )
