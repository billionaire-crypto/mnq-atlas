"""Deterministic tests for the Phase 5 percentile-interval boundary."""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.core import bootstrap as bootstrap_module
from mnq_lab.core.bootstrap import percentile_interval


def test_95_percent_interval_uses_the_25th_and_975th_ordered_draws():
    replicates = np.arange(1, 1_000, dtype=np.float64)

    interval = percentile_interval(replicates, 0.95)

    assert interval == (25.0, 975.0)
    assert isinstance(interval, tuple)
    assert interval[0] in replicates
    assert interval[1] in replicates
    assert np.count_nonzero(replicates < interval[0]) == 24
    assert np.count_nonzero(replicates > interval[1]) == 24


def test_default_linear_percentiles_are_detectably_different():
    replicates = np.arange(1, 1_000, dtype=np.float64)

    actual = percentile_interval(replicates, 0.95)
    linear = tuple(np.quantile(replicates, [0.025, 0.975], method="linear"))

    assert actual == (25.0, 975.0)
    assert linear == pytest.approx((25.95, 974.05))
    assert actual != linear


def test_literal_unit_weights_are_discriminated_from_one_over_draw_count():
    replicates = np.arange(1, 1_000, dtype=np.float64)
    confidence_level = 0.995995995995996

    actual = percentile_interval(replicates, confidence_level)

    assert actual == (3.0, 997.0)


def test_interval_delegates_to_phase4_with_literal_float64_unit_weights(
    monkeypatch,
):
    captured = {}

    def phase4_spy(values, weights, quantiles):
        captured["values"] = values
        captured["weights"] = weights
        captured["quantiles"] = quantiles
        return np.array([-12.5, 34.5], dtype=np.float64)

    monkeypatch.setattr(
        bootstrap_module,
        "weighted_quantiles",
        phase4_spy,
    )
    replicates = np.arange(999, dtype=np.float64)

    interval = percentile_interval(replicates, 0.95)

    assert interval == (-12.5, 34.5)
    assert np.array_equal(captured["values"], replicates)
    assert captured["weights"].dtype == np.float64
    assert np.array_equal(captured["weights"], np.ones(999, dtype=np.float64))
    assert captured["quantiles"] == pytest.approx((0.025, 0.975))


def test_replicate_order_does_not_change_interval_endpoints():
    replicates = np.arange(1, 1_000, dtype=np.float64)
    permuted = replicates[
        np.random.Generator(np.random.PCG64(20260729)).permutation(
            replicates.size
        )
    ]

    assert percentile_interval(permuted, 0.95) == percentile_interval(
        replicates, 0.95
    )


def test_more_than_the_generic_minimum_draw_count_is_admitted():
    replicates = np.arange(1, 1_001, dtype=np.float64)

    assert percentile_interval(replicates, 0.95) == (26.0, 975.0)


def test_interval_does_not_mutate_or_alias_replicate_statistics():
    replicates = np.random.Generator(np.random.PCG64(91)).permutation(
        np.linspace(-5.0, 5.0, 999, dtype=np.float64)
    )
    before = replicates.tobytes()
    dtype = replicates.dtype

    assert not np.array_equal(replicates, np.sort(replicates))
    interval = percentile_interval(replicates, 0.95)

    assert replicates.tobytes() == before
    assert replicates.dtype == dtype
    assert isinstance(interval[0], float)
    assert isinstance(interval[1], float)


def test_nonfinite_replicate_is_not_filtered_or_denominator_reduced():
    replicates = np.arange(1_000, dtype=np.float64)
    replicates[417] = np.nan

    with pytest.raises(SpineError, match=r"index 417"):
        percentile_interval(replicates, 0.95)


@pytest.mark.parametrize(
    ("replicates", "message"),
    [
        (np.arange(998, dtype=np.float64), "at least 999"),
        ([], "at least 999"),
        (np.ones((999, 1)), "replicate statistic at index 0"),
        ([False, *np.ones(998)], "index 0"),
        ([*np.ones(511), np.inf, *np.ones(487)], "index 511"),
        ([*np.ones(317), 1 + 0j, *np.ones(681)], "index 317"),
        (
            np.array([*np.ones(999)], dtype=object),
            "replicate statistic at index 0",
        ),
        (
            np.array([2**53 + 1, *([1] * 998)], dtype=np.int64),
            "replicate statistic at index 0",
        ),
    ],
)
def test_invalid_or_missing_replicate_statistics_fail_closed(
    replicates, message
):
    with pytest.raises(SpineError, match=message):
        percentile_interval(replicates, 0.95)


@pytest.mark.parametrize(
    "confidence_level",
    [
        0.0,
        1.0,
        -0.1,
        1.1,
        True,
        np.bool_(False),
        np.nan,
        np.inf,
        -np.inf,
        None,
        "0.95",
        0.95 + 0j,
    ],
)
def test_invalid_confidence_levels_fail_closed(confidence_level):
    with pytest.raises(SpineError, match="confidence_level"):
        percentile_interval(np.ones(999), confidence_level)


def test_confidence_level_has_no_default():
    parameter = inspect.signature(percentile_interval).parameters[
        "confidence_level"
    ]

    assert parameter.default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        percentile_interval(np.ones(999))
