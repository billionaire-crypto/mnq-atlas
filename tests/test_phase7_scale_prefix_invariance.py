"""Prefix invariance for the calendar-independent Phase 7 scale layer."""

from __future__ import annotations

import numpy as np

from mnq_lab.conditioners.scales.ewma import ewma_rms
from mnq_lab.conditioners.scales.mad import rolling_mad
from mnq_lab.conditioners.scales.returns import (
    BAR_NS,
    CoverageRule,
    ReturnInputs,
    construct_returns,
)


def _inputs(size: int) -> ReturnInputs:
    index = np.arange(size, dtype=np.int32)
    observed = np.full(size, 5, dtype=np.int8)
    observed[35] = 4
    return ReturnInputs(
        ts_event_ns=np.arange(size, dtype=np.int64) * np.int64(BAR_NS),
        session_id=np.full(size, 20200102, dtype=np.int32),
        symbol_code=np.zeros(size, dtype=np.int16),
        close_ticks=(30_000 + index * index + (index % 11) * 5).astype(np.int32),
        expected_1m_components=np.full(size, 5, dtype=np.int8),
        observed_1m_components=observed,
        rollover=np.zeros(size, dtype=np.bool_),
    )


def _prefix(inputs: ReturnInputs, size: int) -> ReturnInputs:
    return ReturnInputs(
        ts_event_ns=inputs.ts_event_ns[:size].copy(),
        session_id=inputs.session_id[:size].copy(),
        symbol_code=inputs.symbol_code[:size].copy(),
        close_ticks=inputs.close_ticks[:size].copy(),
        expected_1m_components=inputs.expected_1m_components[:size].copy(),
        observed_1m_components=inputs.observed_1m_components[:size].copy(),
        rollover=inputs.rollover[:size].copy(),
    )


def test_every_bar_scale_is_bit_identical_before_corpus_extension():
    prefix_size = 180
    full_inputs = _inputs(220)
    prefix_inputs = _prefix(full_inputs, prefix_size)
    for coverage in (CoverageRule.PERMISSIVE, CoverageRule.STRICT):
        full_returns = construct_returns(full_inputs, coverage)
        prefix_returns = construct_returns(prefix_inputs, coverage)
        for halflife in (39, 78, 156):
            full = ewma_rms(full_returns, halflife)
            prefix = ewma_rms(prefix_returns, halflife)
            assert np.array_equal(full.values[:prefix_size], prefix.values)
            assert np.array_equal(full.valid[:prefix_size], prefix.valid)
            assert np.array_equal(
                full.contiguous_return_count[:prefix_size],
                prefix.contiguous_return_count,
            )
            assert full.statuses[:prefix_size] == prefix.statuses
        full_mad = rolling_mad(full_returns)
        prefix_mad = rolling_mad(prefix_returns)
        assert np.array_equal(full_mad.values[:prefix_size], prefix_mad.values)
        assert np.array_equal(full_mad.valid[:prefix_size], prefix_mad.valid)
        assert np.array_equal(
            full_mad.contiguous_return_count[:prefix_size],
            prefix_mad.contiguous_return_count,
        )
        assert full_mad.statuses[:prefix_size] == prefix_mad.statuses


def test_corpus_wide_scale_normalizer_is_a_discriminating_negative_control():
    prefix_size = 180
    full_inputs = _inputs(220)
    prefix_inputs = _prefix(full_inputs, prefix_size)
    full = ewma_rms(
        construct_returns(full_inputs, CoverageRule.PERMISSIVE), 78
    )
    prefix = ewma_rms(
        construct_returns(prefix_inputs, CoverageRule.PERMISSIVE), 78
    )
    full_denominator = np.sum(full.values[full.valid], dtype=np.float64)
    prefix_denominator = np.sum(prefix.values[prefix.valid], dtype=np.float64)
    assert full_denominator != prefix_denominator
    full_mutant = full.values[:prefix_size] / full_denominator
    prefix_mutant = prefix.values / prefix_denominator
    compared = full.valid[:prefix_size] & prefix.valid
    assert bool(np.any(compared)), "negative control is vacuous without defined scales"
    assert not np.array_equal(full_mutant[compared], prefix_mutant[compared])
