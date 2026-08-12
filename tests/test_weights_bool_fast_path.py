"""Bit-identity and fail-closed witnesses for the numeric ndarray bool guard.

The reference guard is the complete pre-optimization production implementation.
Both Phase 8 primitives and the Phase 10 fixed-seed surface batch are executed with
the reference and optimized guards. The heterogeneous-bool mutant proves that the
same invalid-input assertion used for production rejects a bypassed scan.
"""

from __future__ import annotations

from dataclasses import fields

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.core import weights as weights_module
from mnq_lab.core.weights import prepare_weighted_quantile_values
from mnq_lab.phase10.adapter import FormalCorpus, FormalJoinReconciliation
from mnq_lab.phase10.engine import NullSurfaceBatch, evaluate_null_surfaces
from mnq_lab.phase8.contrasts import (
    CellKey,
    SESSION_PHASES,
    VOLATILITY_STATES,
    contrast_support,
    prepare_weighted_quantile_ticks,
    support_masks,
    tick_contrast,
    weighted_quantiles_ticks_prepared_batch_fast,
)
from mnq_lab.phase8.diagnostics import status_decision


def _reference_reject_embedded_bools(values, name):
    """Verbatim guard from production before the numeric-ndarray fast path."""
    try:
        object_view = np.asarray(values, dtype=object)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpineError(f"{name} cannot be converted to an array: {exc}") from exc
    if any(isinstance(item, (bool, np.bool_)) for item in object_view.flat):
        raise SpineError(
            f"{name} contains a bool; implicit bool-to-number conversion is forbidden"
        )


def _snapshot_phase8():
    values = np.asarray([9, -3, 9, 4, 1, 4, 12, -3], dtype=np.int32)
    weights = np.asarray(
        [
            [0.0, 0.5, 0.1, 0.0, 0.4, 0.2, 0.7, 0.3],
            [1.0, 0.0, 0.0, 0.5, 0.0, 0.2, 0.1, 0.0],
        ],
        dtype=np.float64,
    )
    prepared = prepare_weighted_quantile_values(values)
    prepared_ticks = prepare_weighted_quantile_ticks(values)
    quantiles = weighted_quantiles_ticks_prepared_batch_fast(
        prepared_ticks, weights, ("q50", "q75", "q90")
    )
    contrast = tick_contrast(
        values,
        weights[0],
        values,
        weights[1],
        "q90",
    )
    phases = np.asarray(["morning", "morning", "midday", "midday"])
    states = np.asarray(["high", "low", "high", "mid"])
    target = CellKey("morning", "high")
    support = contrast_support(target, "vol_effect_given_phase")
    masks = support_masks(phases, states, target, "vol_effect_given_phase")
    decision = status_decision(
        degenerate_baseline=False,
        insufficient_anchors=False,
        insufficient_completion=False,
        insufficient_overlap=False,
    )
    return {
        "prepared_order": prepared.order.copy(),
        "prepared_starts": prepared.group_starts.copy(),
        "prepared_support": prepared.support.copy(),
        "quantiles": quantiles.copy(),
        "contrast": (
            contrast.target_quantile_ticks,
            contrast.baseline_quantile_ticks,
            contrast.contrast_ticks,
        ),
        "support": (
            tuple((cell.phase, cell.volatility_state) for cell in support.target_cells),
            tuple((cell.phase, cell.volatility_state) for cell in support.baseline_cells),
        ),
        "target_mask": masks.target.copy(),
        "baseline_mask": masks.baseline.copy(),
        "status": (decision.status, decision.status_flags, decision.failure_states),
    }


def _synthetic_phase10_corpus():
    session_count = 120
    width = 78
    sessions = np.arange(session_count, dtype=np.int32) + 20200101
    grid = np.asarray(
        [f"{8 + (30 + 5 * index) // 60:02d}:{(30 + 5 * index) % 60:02d}" for index in range(width)]
    )
    phase_grid = np.asarray(
        tuple(
            "open"
            if index < 6
            else "morning"
            if index < 24
            else "midday"
            if index < 48
            else "afternoon"
            if index < 72
            else "close"
            for index in range(width)
        )
    )
    session_axis = np.arange(session_count, dtype=np.int64)[:, np.newaxis]
    anchor_axis = np.arange(width, dtype=np.int64)[np.newaxis, :]
    state_codes = ((session_axis + anchor_axis) % 3).astype(np.int8)
    outcomes = ((17 * session_axis + 11 * anchor_axis) % 401).astype(np.int32)
    quarters = np.repeat(
        np.asarray(("2020Q1", "2020Q2", "2021Q1", "2021Q2")), 30
    )
    years = np.repeat(np.asarray((2020, 2020, 2021, 2021), dtype=np.int32), 30)
    reconciliation = FormalJoinReconciliation(
        verified_anchor_rows=session_count * width,
        verified_arm_rows=session_count * width,
        schedule_excluded_sessions=0,
        schedule_excluded_rows=0,
        active_sessions=session_count,
        regular_full_rth_sessions=session_count,
        holiday_adjacent_sessions_removed=0,
        truncated_sessions_removed=0,
        formal_sessions=session_count,
        formal_rows=session_count * width,
        anchors_per_session=width,
    )
    return FormalCorpus(
        session_ids=sessions,
        calendar_quarters=quarters,
        calendar_years=years,
        observation_grid=grid,
        phase_grid=phase_grid,
        ts_event_ns=np.arange(session_count * width, dtype=np.int64).reshape(
            session_count, width
        ),
        state_codes=state_codes,
        state_valid=np.ones((session_count, width), dtype=np.bool_),
        downward_excursion_ticks=outcomes,
        outcome_valid=np.ones((session_count, width), dtype=np.bool_),
        window_fits_rth=np.ones((session_count, width), dtype=np.bool_),
        reconciliation=reconciliation,
        metadata={"effective_null_strata": "calendar_quarter_only"},
    )


def _snapshot_phase10():
    batch = evaluate_null_surfaces(_synthetic_phase10_corpus(), replications=3)
    snapshot = {}
    for field in fields(NullSurfaceBatch):
        value = getattr(batch, field.name)
        if isinstance(value, np.ndarray):
            snapshot[field.name] = value.copy()
        elif hasattr(value, "__dataclass_fields__"):
            snapshot[field.name] = {
                nested.name: (
                    getattr(value, nested.name).copy()
                    if isinstance(getattr(value, nested.name), np.ndarray)
                    else getattr(value, nested.name)
                )
                for nested in fields(value)
            }
        else:
            snapshot[field.name] = value
    return snapshot


def _identical(left, right):
    if isinstance(left, np.ndarray) or isinstance(right, np.ndarray):
        try:
            return bool(np.array_equal(left, right, equal_nan=True))
        except TypeError:
            return bool(np.array_equal(left, right))
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _identical(left[key], right[key]) for key in left
        )
    if isinstance(left, (tuple, list)) and isinstance(right, (tuple, list)):
        return len(left) == len(right) and all(
            _identical(a, b) for a, b in zip(left, right, strict=True)
        )
    if isinstance(left, float) and isinstance(right, float):
        return (np.isnan(left) and np.isnan(right)) or left == right
    return left == right


def _with_guard(monkeypatch, guard, callable_):
    monkeypatch.setattr(weights_module, "_reject_embedded_bools", guard)
    return callable_()


def test_numeric_ndarray_fast_path_is_bit_identical_across_phase8(monkeypatch):
    production_guard = weights_module._reject_embedded_bools
    reference = _with_guard(
        monkeypatch, _reference_reject_embedded_bools, _snapshot_phase8
    )
    production = _with_guard(monkeypatch, production_guard, _snapshot_phase8)
    assert _identical(production, reference)


def test_numeric_ndarray_fast_path_is_bit_identical_across_phase10(monkeypatch):
    production_guard = weights_module._reject_embedded_bools
    reference = _with_guard(
        monkeypatch, _reference_reject_embedded_bools, _snapshot_phase10
    )
    production = _with_guard(monkeypatch, production_guard, _snapshot_phase10)
    assert _identical(production, reference)


INVALID_CASES = (
    pytest.param(True, id="bool-scalar"),
    pytest.param(np.asarray([True, False]), id="bool-array"),
    pytest.param(np.asarray([1, True], dtype=object), id="mixed-object-array"),
    pytest.param(np.asarray([1, 2], dtype=object), id="numeric-object-array"),
    pytest.param(np.asarray([2**53 + 1], dtype=np.int64), id="integer-upper-bound"),
    pytest.param(np.asarray([-(2**53) - 1], dtype=np.int64), id="integer-lower-bound"),
    pytest.param(np.asarray([1.0, np.nan]), id="nan"),
    pytest.param(np.asarray([1.0, np.inf]), id="infinity"),
)


def _outcome(function, values):
    try:
        result = function(values, "values")
    except Exception as exc:  # exact type and message are the asserted output
        return ("error", type(exc), str(exc))
    return ("value", np.asarray(result).copy())


def _assert_same_validation(function, values):
    expected = _outcome(
        lambda supplied, name: (
            _reference_reject_embedded_bools(supplied, name),
            weights_module._as_real_float64_vector(supplied, name),
        )[1],
        values,
    )
    actual = _outcome(function, values)
    assert _identical(actual, expected)


@pytest.mark.parametrize("values", INVALID_CASES)
def test_fast_path_preserves_exact_invalid_type_and_message(values):
    _assert_same_validation(weights_module._as_real_float64_vector, values)


def test_heterogeneous_bool_bypass_mutant_fails_the_positive_validation_assertion(
    monkeypatch,
):
    def bypass_embedded_bool_scan(values, name):
        return None

    monkeypatch.setattr(
        weights_module, "_reject_embedded_bools", bypass_embedded_bool_scan
    )
    with pytest.raises(AssertionError):
        _assert_same_validation(
            weights_module._as_real_float64_vector,
            np.asarray([1, True], dtype=object),
        )
