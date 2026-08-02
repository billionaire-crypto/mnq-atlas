"""Exercise frozen independent semantic masks against real scale estimators."""

from __future__ import annotations

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.conditioners.scales.ewma import ewma_rms
from mnq_lab.conditioners.scales.mad import rolling_mad
from mnq_lab.conditioners.scales.returns import (
    BAR_NS,
    CoverageRule,
    ReturnInputs,
    construct_returns,
)
from tests.phase7_contract_oracles import ewma_semantic_mask, mad_semantic_mask


def _inputs(
    closes: np.ndarray, timestamps: np.ndarray | None = None
) -> ReturnInputs:
    size = closes.size
    return ReturnInputs(
        ts_event_ns=(
            np.arange(size, dtype=np.int64) * np.int64(BAR_NS)
            if timestamps is None
            else np.asarray(timestamps, dtype=np.int64)
        ),
        session_id=np.full(size, 20200102, dtype=np.int32),
        symbol_code=np.zeros(size, dtype=np.int16),
        close_ticks=np.asarray(closes, dtype=np.int32),
        expected_1m_components=np.full(size, 5, dtype=np.int8),
        observed_1m_components=np.full(size, 5, dtype=np.int8),
        rollover=np.zeros(size, dtype=np.bool_),
    )


def _assert_exact_semantic_mask(declared: np.ndarray, expected: np.ndarray) -> None:
    if not np.array_equal(declared, expected):
        raise SpineError("declared mask differs from independent semantic mask")


def test_real_declared_masks_equal_independent_contract_oracles():
    size = 140
    anchor = 120
    closes = 10_000 + np.arange(size, dtype=np.int32) ** 2
    returns = construct_returns(_inputs(closes), CoverageRule.PERMISSIVE)
    ewmas = {halflife: ewma_rms(returns, halflife) for halflife in (39, 78, 156)}
    mad = rolling_mad(returns)
    expected_ewma = ewma_semantic_mask(size, 0, anchor)
    expected_mad = mad_semantic_mask(size, 0, anchor)

    for output in ewmas.values():
        _assert_exact_semantic_mask(output.declared_mask(anchor), expected_ewma)
    assert np.array_equal(
        ewmas[39].declared_mask(anchor), ewmas[156].declared_mask(anchor)
    )
    _assert_exact_semantic_mask(mad.declared_mask(anchor), expected_mad)

    timestamps = np.arange(size, dtype=np.int64) * np.int64(BAR_NS)
    timestamps[10:] += np.int64(BAR_NS)
    segmented_returns = construct_returns(
        _inputs(closes, timestamps), CoverageRule.PERMISSIVE
    )
    segmented_ewma = ewma_rms(segmented_returns, 78)
    segmented_expected = ewma_semantic_mask(size, 10, anchor)
    segmented_declared = segmented_ewma.declared_mask(anchor)
    _assert_exact_semantic_mask(segmented_declared, segmented_expected)

    widened_before_segment = segmented_declared.copy()
    widened_before_segment[9] = True
    widened_after_anchor = segmented_declared.copy()
    widened_after_anchor[anchor + 1] = True
    narrowed = expected_mad.copy()
    narrowed[np.flatnonzero(narrowed)[0]] = False
    widened_mad = expected_ewma.copy()
    for mutant, expected in (
        (widened_before_segment, segmented_expected),
        (widened_after_anchor, segmented_expected),
        (narrowed, expected_mad),
        (widened_mad, expected_mad),
    ):
        with pytest.raises(SpineError, match="declared mask differs"):
            _assert_exact_semantic_mask(mutant, expected)


def test_anchor_minus_79_mutation_changes_ewma_but_not_mad_bitwise():
    size = 140
    anchor = 120
    probe = anchor - 79
    baseline_closes = 20_000 + np.arange(size, dtype=np.int32) ** 2
    changed_closes = baseline_closes.copy()
    changed_closes[probe] += 17

    baseline_returns = construct_returns(
        _inputs(baseline_closes), CoverageRule.PERMISSIVE
    )
    changed_returns = construct_returns(
        _inputs(changed_closes), CoverageRule.PERMISSIVE
    )
    baseline_ewma = ewma_rms(baseline_returns, 78)
    changed_ewma = ewma_rms(changed_returns, 78)
    baseline_mad = rolling_mad(baseline_returns)
    changed_mad = rolling_mad(changed_returns)

    assert baseline_ewma.valid[anchor] and changed_ewma.valid[anchor]
    assert baseline_mad.valid[anchor] and changed_mad.valid[anchor]
    assert baseline_ewma.values[anchor] != changed_ewma.values[anchor]
    assert baseline_mad.values[anchor] == changed_mad.values[anchor]
    assert baseline_mad.values[anchor].tobytes() == changed_mad.values[anchor].tobytes()

    ewma_mask = baseline_ewma.declared_mask(anchor)
    mad_mask = baseline_mad.declared_mask(anchor)
    assert ewma_mask[probe]
    assert not mad_mask[probe]


def test_mad_has_no_admitted_mask_before_defined_output():
    closes = 10_000 + np.arange(50, dtype=np.int32) ** 2
    output = rolling_mad(
        construct_returns(_inputs(closes), CoverageRule.PERMISSIVE)
    )
    with pytest.raises(SpineError, match="undefined output"):
        output.declared_mask(49)
