"""Exact-identity witnesses for the D27 prepared-order experiment."""

from __future__ import annotations

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.core import weights as weights_module
from mnq_lab.core.weights import (
    prepare_weighted_quantile_values,
    weighted_quantile,
    weighted_quantile_prepared,
    weighted_quantiles,
    weighted_quantiles_prepared,
)
from mnq_lab.phase8.contrasts import (
    prepare_weighted_quantile_ticks,
    weighted_quantile_ticks,
)


def test_prepared_quantiles_match_a_fixed_randomized_oracle_with_ties_and_zeros():
    rng = np.random.Generator(np.random.PCG64(20260803))
    values = rng.integers(-7, 8, size=257, dtype=np.int32)
    prepared = prepare_weighted_quantile_values(values)
    probabilities = np.asarray([0.01, 0.25, 0.50, 0.75, 0.90, 1.0])

    for replicate in range(40):
        weights = rng.random(257)
        weights[(np.arange(257) + replicate) % 7 == 0] = 0.0
        expected = weighted_quantiles(values, weights, probabilities)
        actual = weighted_quantiles_prepared(prepared, weights, probabilities)
        assert np.array_equal(actual, expected)


@pytest.mark.parametrize(
    ("weights", "probabilities", "expected"),
    (
        pytest.param(
            [0.5, 0.0, 0.5, 0.0],
            [0.5, 0.5000000000000001, 1.0],
            [0.0, 2.0, 2.0],
            id="zero-mass-groups-between-positive-support",
        ),
        pytest.param(
            [0.0, 0.0, 3.0, 0.0],
            [0.01, 0.5, 1.0],
            [2.0, 2.0, 2.0],
            id="single-positive-support-cell",
        ),
        pytest.param(
            [2.0**-52, 1.0, 2.0**-53, 0.0],
            [0.5, 1.0],
            [0.0, 2.0],
            id="tied-value-binary64-accumulation-order",
        ),
    ),
)
def test_prepared_support_preserves_positive_filtering_and_left_inverse_cdf(
    weights, probabilities, expected
):
    values = np.asarray([0, 0, 2, 3], dtype=np.int32)
    prepared = prepare_weighted_quantile_values(values)

    actual = weighted_quantiles_prepared(prepared, weights, probabilities)
    assert np.array_equal(actual, np.asarray(expected, dtype=np.float64))
    assert np.array_equal(actual, weighted_quantiles(values, weights, probabilities))


def test_prepared_phase8_ticks_are_exactly_identical_for_every_frozen_statistic():
    values = np.asarray(
        [np.iinfo(np.int32).min, -5, -5, 0, 7, 7, np.iinfo(np.int32).max],
        dtype=np.int32,
    )
    weights = np.asarray([0.0, 0.2, 0.3, 0.0, 0.1, 0.4, 0.0])
    prepared = prepare_weighted_quantile_ticks(values)

    for statistic in ("q50", "q75", "q90"):
        assert weighted_quantile_ticks(prepared, weights, statistic) == (
            weighted_quantile_ticks(values, weights, statistic)
        )


def test_value_order_is_prepared_once_and_not_resorted_for_new_weights(monkeypatch):
    values = np.asarray([9, 1, 9, 4, 1], dtype=np.int32)
    calls = 0
    original = weights_module.np.argsort

    def argsort_spy(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(weights_module.np, "argsort", argsort_spy)
    prepared = prepare_weighted_quantile_values(values)
    assert calls == 1

    first = weighted_quantile_prepared(prepared, [1, 0, 1, 0, 1], 0.5)
    second = weighted_quantile_prepared(prepared, [0, 1, 0, 1, 0], 0.5)
    assert calls == 1
    assert first == weighted_quantile(values, [1, 0, 1, 0, 1], 0.5)
    assert second == weighted_quantile(values, [0, 1, 0, 1, 0], 0.5)


def test_prepared_quantile_rejects_changed_length_and_zero_total_mass():
    prepared = prepare_weighted_quantile_values(np.asarray([1, 2, 3]))
    with pytest.raises(SpineError, match="equal length"):
        weighted_quantile_prepared(prepared, [1.0, 1.0], 0.5)
    with pytest.raises(SpineError, match="strictly positive total mass"):
        weighted_quantile_prepared(prepared, [0.0, 0.0, 0.0], 0.5)


def test_prepared_tick_contract_cannot_bypass_signed_int32_validation():
    with pytest.raises(SpineError, match="signed integer ticks"):
        prepare_weighted_quantile_ticks(np.asarray([1.0, 2.0]))
    with pytest.raises(SpineError, match="int32 storage range"):
        prepare_weighted_quantile_ticks(
            np.asarray([np.iinfo(np.int32).max + 1], dtype=np.int64)
        )
