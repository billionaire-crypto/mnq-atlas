"""Frozen §13 item-18 roll-reset file: zero memory across every reset."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np

from mnq_lab.conditioners.scales.ewma import ewma_alpha, ewma_rms
from mnq_lab.conditioners.scales.mad import rolling_mad
from mnq_lab.conditioners.scales.returns import (
    BAR_NS,
    CoverageRule,
    ReturnInputs,
    construct_returns,
)
from mnq_lab.conditioners.status import (
    EwmaStatus,
    MadStatus,
    ResetReason,
    ReturnMissingReason,
)

CT = ZoneInfo("America/Chicago")
BOUNDARY = 85
SIZE = 170


def _ct_ns(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=CT).timestamp() * 1_000_000_000)


def _inputs(
    timestamps: np.ndarray,
    sessions: np.ndarray,
    symbols: np.ndarray,
    rollover: np.ndarray,
) -> ReturnInputs:
    index = np.arange(SIZE, dtype=np.int32)
    closes = 25_000 + index * index + (index % 7) * 3
    return ReturnInputs(
        ts_event_ns=timestamps,
        session_id=sessions,
        symbol_code=symbols,
        close_ticks=closes.astype(np.int32),
        expected_1m_components=np.full(SIZE, 5, dtype=np.int8),
        observed_1m_components=np.full(SIZE, 5, dtype=np.int8),
        rollover=rollover,
    )


def _slice(inputs: ReturnInputs, start: int) -> ReturnInputs:
    return ReturnInputs(
        ts_event_ns=inputs.ts_event_ns[start:].copy(),
        session_id=inputs.session_id[start:].copy(),
        symbol_code=inputs.symbol_code[start:].copy(),
        close_ticks=inputs.close_ticks[start:].copy(),
        expected_1m_components=inputs.expected_1m_components[start:].copy(),
        observed_1m_components=inputs.observed_1m_components[start:].copy(),
        rollover=inputs.rollover[start:].copy(),
    )


def _assert_zero_memory(
    inputs: ReturnInputs,
    reason: ReturnMissingReason,
    reset: ResetReason,
    scheduled: bool,
) -> None:
    actual_returns = construct_returns(inputs, CoverageRule.PERMISSIVE)
    standalone_returns = construct_returns(
        _slice(inputs, BOUNDARY), CoverageRule.PERMISSIVE
    )
    boundary = actual_returns.statuses[BOUNDARY]
    assert boundary.return_missing_reason is reason
    assert boundary.reset_reason is reset
    assert boundary.scheduled_break is scheduled
    assert not actual_returns.valid[BOUNDARY]

    for halflife in (39, 78, 156):
        actual = ewma_rms(actual_returns, halflife)
        standalone = ewma_rms(standalone_returns, halflife)
        assert np.array_equal(actual.values[BOUNDARY:], standalone.values)
        assert np.array_equal(actual.valid[BOUNDARY:], standalone.valid)
        assert np.array_equal(
            actual.contiguous_return_count[BOUNDARY:],
            standalone.contiguous_return_count,
        )
        assert actual.statuses[BOUNDARY:] == standalone.statuses
        assert not bool(np.any(actual.valid[BOUNDARY : BOUNDARY + 78]))
        assert actual.valid[BOUNDARY + 78]
        assert actual.statuses[BOUNDARY] is EwmaStatus.WARMUP

    actual_mad = rolling_mad(actual_returns)
    standalone_mad = rolling_mad(standalone_returns)
    assert np.array_equal(actual_mad.values[BOUNDARY:], standalone_mad.values)
    assert np.array_equal(actual_mad.valid[BOUNDARY:], standalone_mad.valid)
    assert np.array_equal(
        actual_mad.contiguous_return_count[BOUNDARY:],
        standalone_mad.contiguous_return_count,
    )
    assert actual_mad.statuses[BOUNDARY:] == standalone_mad.statuses
    assert not bool(np.any(actual_mad.valid[BOUNDARY : BOUNDARY + 78]))
    assert actual_mad.valid[BOUNDARY + 78]
    assert actual_mad.statuses[BOUNDARY] is MadStatus.WARMUP


def _bridging_ewma_validity_and_values(returns, halflife: int):
    decay = np.float64(1.0) - ewma_alpha(halflife)
    numerator = np.float64(0.0)
    denominator = np.float64(0.0)
    count = 0
    values = np.zeros(returns.values.size, dtype=np.float64)
    valid = np.zeros(returns.values.size, dtype=np.bool_)
    for index in range(returns.values.size):
        if not returns.valid[index]:
            continue  # Deliberate defect: state is carried across the reset.
        value = np.float64(returns.values[index])
        numerator = np.float64(decay * numerator + value * value)
        denominator = np.float64(decay * denominator + np.float64(1.0))
        count += 1
        if count >= 78:
            values[index] = np.sqrt(np.float64(numerator / denominator))
            valid[index] = True
    return values, valid


def test_roll_reset_is_from_scratch_bit_identical_and_bridge_mutant_fails():
    timestamps = np.arange(SIZE, dtype=np.int64) * np.int64(BAR_NS)
    sessions = np.full(SIZE, 20200102, dtype=np.int32)
    symbols = np.zeros(SIZE, dtype=np.int16)
    symbols[BOUNDARY:] = 1
    rollover = np.zeros(SIZE, dtype=np.bool_)
    rollover[BOUNDARY] = True
    inputs = _inputs(timestamps, sessions, symbols, rollover)
    _assert_zero_memory(
        inputs,
        ReturnMissingReason.SYMBOL_CHANGE,
        ResetReason.ROLL_RESET,
        False,
    )

    returns = construct_returns(inputs, CoverageRule.PERMISSIVE)
    correct = ewma_rms(returns, 78)
    mutant_values, mutant_valid = _bridging_ewma_validity_and_values(returns, 78)
    assert mutant_valid[BOUNDARY + 1]
    assert not correct.valid[BOUNDARY + 1]
    assert mutant_values[BOUNDARY + 78] != correct.values[BOUNDARY + 78]


def test_anomalous_gap_has_the_same_zero_memory_scale_reset():
    timestamps = np.arange(SIZE, dtype=np.int64) * np.int64(BAR_NS)
    timestamps[BOUNDARY:] += np.int64(BAR_NS)
    sessions = np.full(SIZE, 20200102, dtype=np.int32)
    symbols = np.zeros(SIZE, dtype=np.int16)
    rollover = np.zeros(SIZE, dtype=np.bool_)
    _assert_zero_memory(
        _inputs(timestamps, sessions, symbols, rollover),
        ReturnMissingReason.SPACING_BREAK,
        ResetReason.GAP_RESET,
        False,
    )


def test_maintenance_halt_has_the_same_zero_memory_scale_reset():
    first_start = _ct_ns("2020-01-02T08:55:00")
    second_start = _ct_ns("2020-01-02T17:00:00")
    timestamps = np.concatenate(
        (
            first_start + np.arange(BOUNDARY, dtype=np.int64) * np.int64(BAR_NS),
            second_start
            + np.arange(SIZE - BOUNDARY, dtype=np.int64) * np.int64(BAR_NS),
        )
    )
    sessions = np.concatenate(
        (
            np.full(BOUNDARY, 20200102, dtype=np.int32),
            np.full(SIZE - BOUNDARY, 20200103, dtype=np.int32),
        )
    )
    symbols = np.zeros(SIZE, dtype=np.int16)
    rollover = np.zeros(SIZE, dtype=np.bool_)
    _assert_zero_memory(
        _inputs(timestamps, sessions, symbols, rollover),
        ReturnMissingReason.SPACING_BREAK,
        ResetReason.GAP_RESET,
        True,
    )
