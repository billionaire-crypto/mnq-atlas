"""Executable return, coverage-arm, and continuity contract for Phase 7."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.conditioners.scales.returns import (
    BAR_NS,
    CoverageRule,
    ReturnInputs,
    calendar_isolation_probe,
    construct_returns,
    missing_anchor_status,
)
from mnq_lab.conditioners.status import (
    AnchorStatus,
    ResetReason,
    ReturnMissingReason,
    ReturnStatus,
)

CT = ZoneInfo("America/Chicago")


def _ct_ns(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=CT).timestamp() * 1_000_000_000)


def _inputs(
    *,
    timestamps: list[int] | None = None,
    sessions: list[int] | None = None,
    symbols: list[int] | None = None,
    closes: list[int] | None = None,
    observed: list[int] | None = None,
    rollover: list[bool] | None = None,
) -> ReturnInputs:
    supplied = (timestamps, sessions, symbols, closes, observed, rollover)
    size = next((len(values) for values in supplied if values is not None), 4)
    timestamps = timestamps or [index * BAR_NS for index in range(size)]
    sessions = sessions or [20200102] * size
    symbols = symbols or [0] * size
    closes = closes or [100 + index for index in range(size)]
    observed = observed or [5] * size
    rollover = rollover or [False] * size
    return ReturnInputs(
        ts_event_ns=np.asarray(timestamps, dtype=np.int64),
        session_id=np.asarray(sessions, dtype=np.int32),
        symbol_code=np.asarray(symbols, dtype=np.int16),
        close_ticks=np.asarray(closes, dtype=np.int32),
        expected_1m_components=np.full(size, 5, dtype=np.int8),
        observed_1m_components=np.asarray(observed, dtype=np.int8),
        rollover=np.asarray(rollover, dtype=np.bool_),
    )


def test_close_to_close_return_includes_the_current_anchor_and_is_binary64():
    inputs = _inputs(closes=[100, 125, 80, 160])
    before = inputs.close_ticks.copy()
    result = construct_returns(inputs, CoverageRule.PERMISSIVE)

    expected = np.asarray(
        [0.0, np.log(np.float64(125) / np.float64(100)),
         np.log(np.float64(80) / np.float64(125)),
         np.log(np.float64(160) / np.float64(80))],
        dtype=np.float64,
    )
    assert np.array_equal(result.valid, [False, True, True, True])
    assert np.array_equal(result.values, expected)
    assert result.values[3] == np.log(np.float64(160) / np.float64(80))
    assert np.array_equal(inputs.close_ticks, before)
    assert not result.values.flags.writeable
    assert calendar_isolation_probe() == np.log(np.float64(101) / np.float64(100))

    # A one-row lookahead mutation would change the anchor value and is killed.
    forbidden = np.log(np.float64(160) / np.float64(80))
    assert forbidden != result.values[2]


def test_permissive_and_strict_component_coverage_are_both_emitted_without_selection():
    inputs = _inputs(observed=[5, 4, 5, 5])
    permissive = construct_returns(inputs, CoverageRule.PERMISSIVE)
    strict = construct_returns(inputs, CoverageRule.STRICT)

    assert permissive.valid.tolist() == [False, True, True, True]
    assert strict.valid.tolist() == [False, False, False, True]
    assert strict.statuses[1].return_missing_reason is ReturnMissingReason.INSUFFICIENT_COMPONENTS
    assert strict.statuses[2].return_missing_reason is ReturnMissingReason.SPACING_BREAK
    assert strict.segment_start.tolist() == [0, 1, 2, 2]
    assert permissive.metadata["coverage_rule"] == "permissive"
    assert strict.metadata["coverage_rule"] == "strict"

    # The forbidden bridge over the partial bar produces a value strict must omit.
    bridged = np.log(np.float64(inputs.close_ticks[2]) / np.float64(inputs.close_ticks[0]))
    assert strict.valid[2] is np.False_
    assert bridged != 0.0


def test_extending_the_corpus_cannot_change_any_existing_return():
    full = _inputs(closes=[100, 101, 103, 107])
    prefix = _inputs(closes=[100, 101, 103])
    full_result = construct_returns(full, CoverageRule.PERMISSIVE)
    prefix_result = construct_returns(prefix, CoverageRule.PERMISSIVE)
    assert np.array_equal(full_result.values[:3], prefix_result.values)
    assert np.array_equal(full_result.valid[:3], prefix_result.valid)
    assert full_result.statuses[:3] == prefix_result.statuses

    corpus_normalized = full_result.values / np.sum(np.abs(full_result.values))
    prefix_normalized = prefix_result.values / np.sum(np.abs(prefix_result.values))
    assert not np.array_equal(corpus_normalized[:3], prefix_normalized)


@pytest.mark.parametrize(
    ("timestamps", "sessions"),
    [
        (
            [_ct_ns("2020-01-02T15:55:00"), _ct_ns("2020-01-02T17:00:00")],
            [20200102, 20200103],
        ),
        (
            [_ct_ns("2020-01-03T15:55:00"), _ct_ns("2020-01-05T17:00:00")],
            [20200103, 20200106],
        ),
    ],
)
def test_maintenance_and_weekend_breaks_are_scheduled_zero_memory_resets(
    timestamps, sessions
):
    result = construct_returns(
        _inputs(timestamps=timestamps, sessions=sessions, closes=[100, 150]),
        CoverageRule.PERMISSIVE,
    )
    boundary = result.statuses[1]
    assert not result.valid[1]
    assert boundary.return_missing_reason is ReturnMissingReason.SPACING_BREAK
    assert boundary.reset_reason is ResetReason.GAP_RESET
    assert boundary.scheduled_break is True
    assert result.segment_start[1] == 1

    bridging_mutant = np.log(np.float64(150) / np.float64(100))
    assert bridging_mutant != result.values[1]


def test_anomalous_gap_is_not_mislabeled_as_a_scheduled_break():
    result = construct_returns(
        _inputs(
            timestamps=[_ct_ns("2020-01-02T10:00:00"), _ct_ns("2020-01-02T10:10:00")],
            closes=[100, 120],
        ),
        CoverageRule.PERMISSIVE,
    )
    assert result.statuses[1].return_missing_reason is ReturnMissingReason.SPACING_BREAK
    assert result.statuses[1].scheduled_break is False
    assert result.segment_start[1] == 1


def test_roll_identity_beats_spacing_and_carries_no_return():
    result = construct_returns(
        _inputs(
            timestamps=[0, 2 * BAR_NS, 3 * BAR_NS],
            symbols=[0, 1, 1],
            closes=[100, 200, 220],
            rollover=[False, True, False],
        ),
        CoverageRule.PERMISSIVE,
    )
    boundary = result.statuses[1]
    assert boundary.return_missing_reason is ReturnMissingReason.SYMBOL_CHANGE
    assert boundary.reset_reason is ResetReason.ROLL_RESET
    assert boundary.scheduled_break is False
    assert not result.valid[1]
    assert result.valid[2]
    assert result.values[2] == np.log(np.float64(220) / np.float64(200))

    carried_mutant = np.log(np.float64(200) / np.float64(100))
    assert carried_mutant != result.values[1]


def test_missing_declared_anchor_has_an_explicit_status_row_identity():
    status = missing_anchor_status()
    assert status.anchor_status is AnchorStatus.ANCHOR_BAR_MISSING
    assert status.return_status is ReturnStatus.MISSING_RETURN
    assert status.return_missing_reason is ReturnMissingReason.BAR_ABSENT
    assert status.reset_reason is ResetReason.GAP_RESET


@pytest.mark.parametrize(
    "mutation",
    [
        {"ts_event_ns": np.asarray([0, 0], dtype=np.int64)},
        {"close_ticks": np.asarray([100, 0], dtype=np.int32)},
        {"expected_1m_components": np.asarray([5, 4], dtype=np.int8)},
        {"observed_1m_components": np.asarray([5, 0], dtype=np.int8)},
        {"symbol_code": np.asarray([0, 0], dtype=np.int32)},
        {"rollover": np.asarray([0, 0], dtype=np.int8)},
    ],
)
def test_return_inputs_fail_closed_on_corrupt_structure(mutation):
    base = _inputs(timestamps=[0, BAR_NS])
    with pytest.raises(SpineError):
        replace(base, **mutation)


def test_return_constructor_rejects_unregistered_coverage_values():
    with pytest.raises(SpineError, match="CoverageRule"):
        construct_returns(_inputs(), "permissive")
