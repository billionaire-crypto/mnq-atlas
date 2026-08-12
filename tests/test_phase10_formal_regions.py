"""The formal result retains observed region membership for later localization."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from mnq_lab.phase10 import engine
from mnq_lab.phase10.engine import NullSurfaceBatch
from mnq_lab.phase10.surface import SurfaceRegion


def _batch(region):
    return NullSurfaceBatch(
        observed=object(),
        null_contrasts=np.zeros((2, 1, 5, 3), dtype=np.int64),
        null_valid=np.ones((2, 1, 5, 3), dtype=np.bool_),
        null_yearly_contrasts=np.zeros((2, 1, 1, 5, 3), dtype=np.int64),
        null_yearly_valid=np.ones((2, 1, 1, 5, 3), dtype=np.bool_),
        observed_statistic=region.statistic,
        observed_regions=(region,),
        null_statistics=np.asarray([0.5, 1.0], dtype=np.float64),
    )


def _assert_region_retained(result, expected):
    assert result.observed_regions == (expected,)


def test_formal_result_retains_observed_region_membership(monkeypatch):
    region = SurfaceRegion(
        plane_index=1,
        sign="positive",
        cells=((1, 2), (2, 2), (3, 2)),
        mean_z=2.5,
        stability=0.75,
        statistic=3.247595264191645,
    )
    monkeypatch.setattr(
        engine,
        "evaluate_null_surfaces",
        lambda corpus, replications: _batch(region),
    )

    result = engine.run_formal_test(object(), replications=4999)

    _assert_region_retained(result, region)


def test_formal_region_negative_uses_the_positive_assertion(monkeypatch):
    region = SurfaceRegion(0, "negative", ((0, 0),), -2.0, 1.0, 2.0)
    monkeypatch.setattr(
        engine,
        "evaluate_null_surfaces",
        lambda corpus, replications: _batch(region),
    )
    result = engine.run_formal_test(object(), replications=4999)
    mutant = replace(result, observed_regions=())
    with pytest.raises(AssertionError):
        _assert_region_retained(mutant, region)
