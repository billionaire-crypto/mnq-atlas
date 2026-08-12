"""Test 12: signed rook regions, missing breaks, and mutation witnesses."""

from __future__ import annotations

import numpy as np
import pytest

from mnq_lab.phase10.surface import coherence_statistic, shared_standardization


def _yearly(z):
    years = np.repeat(z[np.newaxis, :, :, :], 4, axis=0)
    valid = np.ones(years.shape, dtype=np.bool_)
    return years, valid


def _assert_signed_regions(result):
    positive = [region for region in result.regions if region.sign == "positive"]
    negative = [region for region in result.regions if region.sign == "negative"]
    assert positive and negative
    assert all(
        not (set(left.cells) & set(right.cells))
        for left in positive
        for right in negative
    )


def test_surface_detects_positive_and_negative_without_merging_signs():
    z = np.zeros((2, 5, 3), dtype=np.float64)
    valid = np.ones(z.shape, dtype=np.bool_)
    z[0, 0, 0] = 2.0
    z[0, 0, 1] = 1.5
    z[0, 1, 1] = -1.7
    z[0, 2, 1] = -2.1
    years, year_valid = _yearly(z)
    result = coherence_statistic(z, valid, years, year_valid)
    _assert_signed_regions(result)
    assert {region.sign for region in result.regions} == {"positive", "negative"}


def test_surface_negative_magnitude_merge_fails_the_positive_assertion():
    z = np.zeros((2, 5, 3), dtype=np.float64)
    valid = np.ones(z.shape, dtype=np.bool_)
    z[0, 0, 0] = 2.0
    z[0, 0, 1] = -2.0
    years, year_valid = _yearly(z)
    valid_result = coherence_statistic(z, valid, years, year_valid)
    _assert_signed_regions(valid_result)

    magnitude_mutant = np.square(z)
    mutant_years, mutant_year_valid = _yearly(magnitude_mutant)
    mutant_result = coherence_statistic(
        magnitude_mutant, valid, mutant_years, mutant_year_valid
    )
    with pytest.raises(AssertionError):
        _assert_signed_regions(mutant_result)


def _assert_diagonal_separate(result):
    positive = [region for region in result.regions if region.sign == "positive"]
    assert len(positive) == 2
    assert all(len(region.cells) == 1 for region in positive)


def test_surface_uses_rook_not_diagonal_connectivity():
    z = np.zeros((1, 5, 3), dtype=np.float64)
    valid = np.ones(z.shape, dtype=np.bool_)
    z[0, 0, 0] = 2.0
    z[0, 1, 1] = 2.0
    years, year_valid = _yearly(z)
    _assert_diagonal_separate(coherence_statistic(z, valid, years, year_valid))


def test_surface_missing_cell_breaks_adjacency():
    z = np.zeros((1, 5, 3), dtype=np.float64)
    valid = np.ones(z.shape, dtype=np.bool_)
    z[0, 0, :] = 2.0
    valid[0, 0, 1] = False
    years, year_valid = _yearly(z)
    result = coherence_statistic(z, valid, years, year_valid)
    positive = [region for region in result.regions if region.sign == "positive"]
    assert len(positive) == 2
    assert all(len(region.cells) == 1 for region in positive)


def _assert_invalid_standardization_is_not_zero(result):
    assert not bool(result.observed_valid[0, 0, 1])
    assert np.isnan(result.observed_z[0, 0, 1])


def test_surface_missing_standardization_remains_nonfinite():
    observed = np.ones((1, 5, 3), dtype=np.float64)
    observed_valid = np.ones(observed.shape, dtype=np.bool_)
    observed_valid[0, 0, 1] = False
    null = np.stack((observed, observed * 2.0, observed * 3.0))
    null_valid = np.ones(null.shape, dtype=np.bool_)
    result = shared_standardization(observed, observed_valid, null, null_valid)
    _assert_invalid_standardization_is_not_zero(result)


def test_surface_negative_zero_fill_fails_the_positive_assertion():
    observed = np.ones((1, 5, 3), dtype=np.float64)
    observed_valid = np.ones(observed.shape, dtype=np.bool_)
    observed_valid[0, 0, 1] = False
    null = np.stack((observed, observed * 2.0, observed * 3.0))
    null_valid = np.ones(null.shape, dtype=np.bool_)
    result = shared_standardization(observed, observed_valid, null, null_valid)
    result.observed_z[0, 0, 1] = 0.0
    with pytest.raises(AssertionError):
        _assert_invalid_standardization_is_not_zero(result)


def _assert_pooled_standardization(function):
    observed = np.zeros((1, 5, 3), dtype=np.float64)
    observed[0, 0, 0] = 10.0
    observed_valid = np.ones(observed.shape, dtype=np.bool_)
    observed_valid[0, 0, 1] = False
    null = np.stack(
        (
            np.zeros(observed.shape, dtype=np.float64),
            np.full(observed.shape, 2.0, dtype=np.float64),
        )
    )
    null_valid = np.ones(null.shape, dtype=np.bool_)
    result = function(observed, observed_valid, null, null_valid)
    pooled_scale = float(np.std((10.0, 0.0, 2.0), ddof=1))
    null_only_scale = float(np.std((0.0, 2.0), ddof=1))
    assert result.scales[0, 0, 0] == pooled_scale
    assert result.observed_z[0, 0, 0] == 10.0 / pooled_scale
    assert result.null_z[1, 0, 0, 0] == 2.0 / pooled_scale
    assert result.scales[0, 0, 1] == null_only_scale


def test_surface_standardization_pools_observed_and_null_values():
    _assert_pooled_standardization(shared_standardization)


def test_surface_negative_null_only_scale_fails_the_positive_assertion():
    def null_only_mutant(observed, observed_valid, null, null_valid):
        result = shared_standardization(
            observed, observed_valid, null, null_valid
        )
        scale = float(np.std(null[:, 0, 0, 0], ddof=1))
        result.scales[0, 0, 0] = scale
        result.observed_z[0, 0, 0] = observed[0, 0, 0] / scale
        result.null_z[:, 0, 0, 0] = null[:, 0, 0, 0] / scale
        return result

    with pytest.raises(AssertionError):
        _assert_pooled_standardization(null_only_mutant)
