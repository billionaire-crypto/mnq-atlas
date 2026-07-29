"""Frozen-spec §13 test 7: market-free discrete weighted inverse CDF."""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.core.weights import weighted_quantile, weighted_quantiles


@pytest.mark.parametrize(
    "q", [0.01, 0.24, 0.25, 0.26, 0.5, 0.749, 0.75, 0.751, 1.0]
)
def test_rational_weights_match_the_repeated_inverted_cdf_oracle(q):
    values = np.array([-4, 0, 7, 12], dtype=np.int32)
    counts = np.array([1, 3, 2, 4], dtype=np.int64)
    repeated = np.repeat(values, counts)

    actual = weighted_quantile(values, counts, q)
    expected = np.quantile(repeated, q, method="inverted_cdf")

    assert actual == float(expected)


def test_heavy_ties_aggregate_to_observed_support_without_interpolation():
    values = np.array([0, 10, 10, 10, 20], dtype=np.int32)
    weights = np.array([1, 1, 2, 3, 1], dtype=np.int64)

    assert weighted_quantile(values, weights, 0.25) == 10.0
    assert weighted_quantile(values, weights, 0.50) == 10.0
    assert weighted_quantile(values, weights, 0.75) == 10.0
    assert weighted_quantile(values, weights, 0.90) == 20.0


def test_zero_weight_values_cannot_enter_or_change_positive_quantile_support():
    base_values = np.array([10.0, 20.0])
    base_weights = np.array([1.0, 1.0])
    augmented_values = np.array([-1e9, 10.0, 20.0, 1e9])
    augmented_weights = np.array([0.0, 1.0, 1.0, 0.0])

    for q in (0.01, 0.5, 1.0):
        assert weighted_quantile(
            augmented_values, augmented_weights, q
        ) == weighted_quantile(base_values, base_weights, q)
    assert weighted_quantile(augmented_values, augmented_weights, 1.0) == 20.0


def test_one_positive_weight_returns_its_value_at_every_admitted_probability():
    values = np.array([-100.0, 7.5, 100.0])
    weights = np.array([0.0, 2.0, 0.0])

    assert np.array_equal(
        weighted_quantiles(values, weights, [1e-12, 0.25, 0.5, 1.0]),
        np.array([7.5, 7.5, 7.5, 7.5]),
    )


def _naive_tie_order_quantile(values, weights, q):
    """Deliberately wrong mutation: tied weights retain caller row order."""
    order = np.argsort(values, kind="mergesort")
    ordered_values = values[order]
    ordered_weights = weights[order]
    starts = np.flatnonzero(
        np.r_[True, ordered_values[1:] != ordered_values[:-1]]
    )
    ends = np.r_[starts[1:], len(ordered_values)]
    masses = np.array(
        [
            np.cumsum(ordered_weights[start:end], dtype=np.float64)[-1]
            for start, end in zip(starts, ends)
        ]
    )
    cumulative = np.cumsum(masses, dtype=np.float64)
    index = np.searchsorted(cumulative, q * cumulative[-1], side="left")
    return float(ordered_values[starts][index])


def test_boundary_order_invariance_requires_canonical_fractional_tie_sums():
    values = np.array([10.0, 10.0, 10.0, 20.0, 30.0, 40.0])
    weights = np.array(
        [
            0.7915377469248704,
            0.25237183338002467,
            0.7436827587296093,
            0.6397215895039096,
            0.057559123366011766,
            0.07266497261138638,
        ]
    )
    q = 0.6989504444896484
    observed = set()
    naive_observed = set()

    for tied_permutation in itertools.permutations(range(3)):
        order = np.array([*tied_permutation, 3, 4, 5])
        observed.add(weighted_quantile(values[order], weights[order], q))
        naive_observed.add(
            _naive_tie_order_quantile(values[order], weights[order], q)
        )

    assert observed == {10.0}
    assert naive_observed == {10.0, 20.0}, (
        "the fixture no longer kills caller-order tie accumulation"
    )


def test_full_row_permutation_is_invariant_at_the_fractional_boundary():
    values = np.array([10.0, 10.0, 10.0, 20.0, 30.0, 40.0])
    weights = np.array(
        [
            0.7915377469248704,
            0.25237183338002467,
            0.7436827587296093,
            0.6397215895039096,
            0.057559123366011766,
            0.07266497261138638,
        ]
    )
    q = 0.6989504444896484
    rng = np.random.default_rng(20260729)

    expected = weighted_quantile(values, weights, q)
    for _ in range(100):
        order = rng.permutation(values.size)
        assert weighted_quantile(values[order], weights[order], q) == expected


def test_power_of_two_rescaling_is_exact_at_a_cdf_boundary():
    values = np.array([10.0, 20.0, 30.0])
    weights = np.array([1.0, 2.0, 1.0])
    q = 0.25
    expected = weighted_quantile(values, weights, q)

    for factor in (0.25, 0.5, 2.0, 4.0, 1024.0):
        assert weighted_quantile(values, weights * factor, q) == expected


def test_arbitrary_scale_boundary_limitation_is_real_and_not_tolerance_repaired():
    values = np.array([10.0, 20.0, 30.0])
    weights = np.array(
        [0.4757049720330856, 0.4375367624618729, 0.28309648450120006]
    )
    q = 0.39763418444680915
    factor = 76.87749167008357

    assert weighted_quantile(values, weights, q) == 10.0
    assert weighted_quantile(values, weights * factor, q) == 20.0


def test_exact_cdf_boundary_returns_the_current_support_point():
    values = np.array([10.0, 20.0, 30.0])
    weights = np.array([1.0, 2.0, 1.0])

    assert weighted_quantile(values, weights, 0.25) == 10.0
    assert weighted_quantile(values, weights, 0.75) == 20.0


def test_q_one_uses_final_cumulative_mass_not_an_independent_sum():
    values = np.arange(8, dtype=np.float64)
    weights = np.array(
        [
            0.40821833698859167,
            0.6243576679833042,
            0.274758043242749,
            0.0002738297704468762,
            0.7998100144321403,
            0.18255092071347034,
            0.4357736430374587,
            0.5287514588115207,
        ]
    )
    assert np.sum(weights) > np.cumsum(weights)[-1]
    assert weighted_quantile(values, weights, 1.0) == 7.0


def _division_form_quantile(values, weights, q):
    cumulative = np.cumsum(weights, dtype=np.float64)
    index = np.searchsorted(cumulative / cumulative[-1], q, side="left")
    return float(values[index])


def test_multiplication_form_boundary_kills_division_form_comparison():
    values = np.array([0.0, 1.0])
    weights = np.array(
        [
            float.fromhex("0x1.2e406a476e443p-9"),
            float.fromhex("0x1.111b1a8bf8dfep-7"),
        ]
    )
    q = float.fromhex("0x1.bbd6cdf73ddbep-3")

    assert weighted_quantile(values, weights, q) == 0.0
    assert _division_form_quantile(values, weights, q) == 1.0, (
        "the exact fixture no longer kills cumulative/total >= q"
    )


def _prenormalized_quantile(values, weights, q):
    normalized = weights / np.sum(weights)
    cumulative = np.cumsum(normalized, dtype=np.float64)
    index = np.searchsorted(cumulative, q * cumulative[-1], side="left")
    return float(values[index])


def test_binary64_boundary_kills_pre_normalization_by_total_mass():
    values = np.array([0.0, 1.0])
    weights = np.array(
        [
            float.fromhex("0x1.b8408469042adp+21"),
            float.fromhex("0x1.7e0662da5302fp+19"),
        ]
    )
    q = float.fromhex("0x1.a4ba9f98a6d54p-1")

    assert weighted_quantile(values, weights, q) == 0.0
    assert _prenormalized_quantile(values, weights, q) == 1.0, (
        "the exact fixture no longer kills weight pre-normalization"
    )


def test_multi_quantile_output_preserves_caller_order_and_duplicates():
    values = np.array([0.0, 10.0, 20.0, 30.0])
    weights = np.ones(4)
    quantiles = np.array([1.0, 0.25, 0.75, 0.25, 0.5])

    actual = weighted_quantiles(values, weights, quantiles)

    assert actual.dtype == np.float64
    assert np.array_equal(actual, np.array([30.0, 0.0, 20.0, 0.0, 10.0]))


def test_default_linear_interpolation_is_detectably_wrong():
    values = np.array([0.0, 1.0, 2.0, 3.0])
    weights = np.ones(4)

    actual = weighted_quantile(values, weights, 0.25)
    linear = np.quantile(values, 0.25, method="linear")

    assert actual == 0.0
    assert linear == 0.75
    assert actual != linear


@pytest.mark.parametrize(
    ("value_dtype", "weight_dtype", "quantile_dtype"),
    [
        (np.int32, np.float32, np.float32),
        (np.float64, np.float64, np.float64),
    ],
)
def test_calls_do_not_mutate_values_weights_quantiles_or_their_dtypes(
    value_dtype, weight_dtype, quantile_dtype
):
    values = np.array([30, 10, 20, 10], dtype=value_dtype)
    weights = np.array([0.5, 0.1, 0.3, 0.2], dtype=weight_dtype)
    quantiles = np.array([0.75, 0.25], dtype=quantile_dtype)
    values_before = values.tobytes()
    weights_before = weights.tobytes()
    quantiles_before = quantiles.tobytes()
    value_dtype = values.dtype
    weight_dtype = weights.dtype
    quantile_dtype = quantiles.dtype

    weighted_quantile(values, weights, 0.5)
    weighted_quantiles(values, weights, quantiles)

    assert values.tobytes() == values_before
    assert weights.tobytes() == weights_before
    assert quantiles.tobytes() == quantiles_before
    assert values.dtype == value_dtype
    assert weights.dtype == weight_dtype
    assert quantiles.dtype == quantile_dtype


@pytest.mark.parametrize(
    ("values", "weights", "message"),
    [
        ([], [], "at least one"),
        ([1.0], [1.0, 2.0], "equal length"),
        ([[1.0]], [[1.0]], "one-dimensional"),
        ([1.0, 2.0], [1.0, -1.0], "negative"),
        ([1.0, 2.0], [0.0, 0.0], "positive total"),
        ([True, False], [1.0, 1.0], "bool"),
        ([1.0, 2.0], [True, False], "bool"),
        ([True, 1], [1.0, 1.0], "bool"),
        ([1.0, 2.0], [True, 1], "bool"),
        ([[1.0], [2.0, 3.0]], [1.0, 1.0], "converted"),
        ([1.0, np.nan], [1.0, 1.0], "non-finite"),
        ([1.0, np.inf], [1.0, 0.0], "non-finite"),
        ([1.0, 2.0], [1.0, np.inf], "non-finite"),
        (np.array([1, 2], dtype=object), [1.0, 1.0], "real integer or floating"),
        (np.array([1 + 0j]), [1.0], "real integer or floating"),
        (np.array(["1"]), [1.0], "real integer or floating"),
        (np.array(["2026-07-29"], dtype="datetime64[D]"), [1.0], "real integer or floating"),
        (np.array([1], dtype="timedelta64[D]"), [1.0], "real integer or floating"),
        ([2**53 + 1], [1.0], "2\\*\\*53"),
        ([1.0], [2**53 + 1], "2\\*\\*53"),
    ],
)
def test_malformed_value_and_weight_inputs_fail_closed(values, weights, message):
    with pytest.raises(SpineError, match=message):
        weighted_quantile(values, weights, 0.5)


@pytest.mark.parametrize(
    "q", [0.0, -0.1, 1.1, np.nan, np.inf, -np.inf, True, None, 0.5 + 0j]
)
def test_invalid_scalar_probabilities_fail_closed(q):
    with pytest.raises(SpineError, match="0 < q <= 1"):
        weighted_quantile([1.0, 2.0], [1.0, 1.0], q)


@pytest.mark.parametrize(
    "quantiles",
    [
        [],
        [[0.5]],
        [0.0],
        [-0.1],
        [1.1],
        [np.nan],
        [np.inf],
        [True],
        [True, 0.5],
        np.array([0.5], dtype=object),
        np.array([0.5 + 0j]),
    ],
)
def test_invalid_multi_probabilities_fail_closed(quantiles):
    with pytest.raises(SpineError):
        weighted_quantiles([1.0, 2.0], [1.0, 1.0], quantiles)
