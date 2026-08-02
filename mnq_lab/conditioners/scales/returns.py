"""Causal five-minute close-to-close returns for Phase 7.

This module accepts arrays only.  It imports no calendar or store module and
accepts no filesystem path.  The current bar's return ends at its observation
time and is therefore available to a conditioner at that time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from mnq_lab import SpineError
from mnq_lab.conditioners.status import (
    AnchorStatus,
    ConditionerStatuses,
    ResetReason,
    ReturnMissingReason,
    ReturnStatus,
)

__all__ = [
    "CoverageRule",
    "ReturnInputs",
    "ReturnSeries",
    "calendar_isolation_probe",
    "construct_returns",
    "missing_anchor_status",
]

BAR_NS = 300_000_000_000
CT = ZoneInfo("America/Chicago")


class CoverageRule(str, Enum):
    PERMISSIVE = "permissive"
    STRICT = "strict"


def _readonly(array: np.ndarray) -> np.ndarray:
    result = np.array(array, copy=True)
    result.setflags(write=False)
    return result


def _require_vector(value: Any, name: str, dtype: np.dtype) -> np.ndarray:
    array = np.asarray(value)
    if array.ndim != 1 or array.size == 0:
        raise SpineError(f"{name} must be a nonempty one-dimensional array")
    if array.dtype != dtype:
        raise SpineError(f"{name} dtype must be {dtype}, got {array.dtype}")
    return array


@dataclass(frozen=True)
class ReturnInputs:
    ts_event_ns: np.ndarray
    session_id: np.ndarray
    symbol_code: np.ndarray
    close_ticks: np.ndarray
    expected_1m_components: np.ndarray
    observed_1m_components: np.ndarray
    rollover: np.ndarray

    def __post_init__(self) -> None:
        arrays = {
            "ts_event_ns": _require_vector(self.ts_event_ns, "ts_event_ns", np.dtype("int64")),
            "session_id": _require_vector(self.session_id, "session_id", np.dtype("int32")),
            "symbol_code": _require_vector(self.symbol_code, "symbol_code", np.dtype("int16")),
            "close_ticks": _require_vector(self.close_ticks, "close_ticks", np.dtype("int32")),
            "expected_1m_components": _require_vector(
                self.expected_1m_components,
                "expected_1m_components",
                np.dtype("int8"),
            ),
            "observed_1m_components": _require_vector(
                self.observed_1m_components,
                "observed_1m_components",
                np.dtype("int8"),
            ),
            "rollover": _require_vector(self.rollover, "rollover", np.dtype("bool")),
        }
        lengths = {array.size for array in arrays.values()}
        if len(lengths) != 1:
            raise SpineError("return input arrays must have identical length")
        if not bool(np.all(arrays["ts_event_ns"][1:] > arrays["ts_event_ns"][:-1])):
            raise SpineError("ts_event_ns must be strictly increasing and unique")
        if not bool(np.all(arrays["close_ticks"] > 0)):
            raise SpineError("close_ticks must be strictly positive")
        expected = arrays["expected_1m_components"]
        observed = arrays["observed_1m_components"]
        if not bool(np.all(expected == 5)):
            raise SpineError("expected_1m_components must equal five")
        if not bool(np.all((observed >= 1) & (observed <= expected))):
            raise SpineError("observed_1m_components must be in [1, expected]")
        for name, array in arrays.items():
            object.__setattr__(self, name, _readonly(array))


@dataclass(frozen=True)
class ReturnSeries:
    values: np.ndarray
    valid: np.ndarray
    segment_start: np.ndarray
    statuses: tuple[ConditionerStatuses, ...]
    metadata: MappingProxyType

    def __post_init__(self) -> None:
        values = np.asarray(self.values)
        valid = np.asarray(self.valid)
        starts = np.asarray(self.segment_start)
        if values.dtype != np.dtype("float64") or valid.dtype != np.dtype("bool"):
            raise SpineError("return values/valid dtypes must be float64/bool")
        if starts.dtype != np.dtype("int64"):
            raise SpineError("segment_start dtype must be int64")
        if values.ndim != 1 or values.shape != valid.shape or values.shape != starts.shape:
            raise SpineError("return result arrays must be aligned one-dimensional vectors")
        if len(self.statuses) != values.size:
            raise SpineError("return statuses must align with result arrays")
        if not bool(np.isfinite(values).all()):
            raise SpineError("stored return values must be finite")
        object.__setattr__(self, "values", _readonly(values))
        object.__setattr__(self, "valid", _readonly(valid))
        object.__setattr__(self, "segment_start", _readonly(starts))


def missing_anchor_status() -> ConditionerStatuses:
    return ConditionerStatuses(
        anchor_status=AnchorStatus.ANCHOR_BAR_MISSING,
        return_status=ReturnStatus.MISSING_RETURN,
        return_missing_reason=ReturnMissingReason.BAR_ABSENT,
        reset_reason=ResetReason.GAP_RESET,
        scheduled_break=False,
    )


def _scheduled_session_break(
    previous_ts_ns: int,
    current_ts_ns: int,
    previous_session: int,
    current_session: int,
) -> bool:
    if current_session == previous_session:
        return False
    previous = datetime.fromtimestamp(previous_ts_ns / 1_000_000_000, tz=UTC).astimezone(CT)
    current = datetime.fromtimestamp(current_ts_ns / 1_000_000_000, tz=UTC).astimezone(CT)
    previous_end = previous + timedelta(minutes=5)
    return previous_end.strftime("%H:%M") == "16:00" and current.strftime("%H:%M") == "17:00"


def _missing_status(
    reason: ReturnMissingReason,
    *,
    scheduled_break: bool = False,
) -> ConditionerStatuses:
    return ConditionerStatuses(
        anchor_status=AnchorStatus.OK,
        return_status=ReturnStatus.MISSING_RETURN,
        return_missing_reason=reason,
        reset_reason=(
            ResetReason.ROLL_RESET
            if reason is ReturnMissingReason.SYMBOL_CHANGE
            else ResetReason.GAP_RESET
        ),
        scheduled_break=scheduled_break,
    )


def construct_returns(inputs: ReturnInputs, coverage: CoverageRule) -> ReturnSeries:
    """Build one causal return row per present input bar."""
    if not isinstance(inputs, ReturnInputs):
        raise SpineError("inputs must be ReturnInputs")
    if not isinstance(coverage, CoverageRule):
        raise SpineError("coverage must be a CoverageRule")

    size = inputs.ts_event_ns.size
    values = np.zeros(size, dtype=np.float64)
    valid = np.zeros(size, dtype=np.bool_)
    segment_start = np.zeros(size, dtype=np.int64)
    statuses: list[ConditionerStatuses] = []
    current_start = 0
    previous_usable = False

    for index in range(size):
        complete = int(inputs.observed_1m_components[index]) == 5
        usable = coverage is CoverageRule.PERMISSIVE or complete
        if not usable:
            current_start = index + 1
            segment_start[index] = index
            statuses.append(
                _missing_status(ReturnMissingReason.INSUFFICIENT_COMPONENTS)
            )
            previous_usable = False
            continue

        if index == 0:
            current_start = 0
            segment_start[index] = current_start
            statuses.append(_missing_status(ReturnMissingReason.SPACING_BREAK))
            previous_usable = True
            continue

        symbol_changed = (
            bool(inputs.rollover[index])
            or int(inputs.symbol_code[index]) != int(inputs.symbol_code[index - 1])
        )
        spacing = int(inputs.ts_event_ns[index] - inputs.ts_event_ns[index - 1])
        session_changed = int(inputs.session_id[index]) != int(inputs.session_id[index - 1])

        if symbol_changed:
            current_start = index
            segment_start[index] = current_start
            statuses.append(_missing_status(ReturnMissingReason.SYMBOL_CHANGE))
        elif not previous_usable or spacing != BAR_NS or session_changed:
            current_start = index
            segment_start[index] = current_start
            scheduled = _scheduled_session_break(
                int(inputs.ts_event_ns[index - 1]),
                int(inputs.ts_event_ns[index]),
                int(inputs.session_id[index - 1]),
                int(inputs.session_id[index]),
            )
            statuses.append(
                _missing_status(
                    ReturnMissingReason.SPACING_BREAK,
                    scheduled_break=scheduled,
                )
            )
        else:
            ratio = np.float64(inputs.close_ticks[index]) / np.float64(
                inputs.close_ticks[index - 1]
            )
            result = np.log(ratio)
            if not np.isfinite(result):
                raise SpineError(f"return at index {index} is non-finite")
            values[index] = np.float64(result)
            valid[index] = True
            segment_start[index] = current_start
            statuses.append(
                ConditionerStatuses(
                    anchor_status=AnchorStatus.OK,
                    return_status=ReturnStatus.OK,
                    return_missing_reason=None,
                    reset_reason=ResetReason.NONE,
                    scheduled_break=False,
                )
            )
        previous_usable = True

    metadata = MappingProxyType(
        {
            "coverage_rule": coverage.value,
            "return_definition": "log(float64(close_t)/float64(close_t_minus_1))",
            "bar_ns": BAR_NS,
        }
    )
    return ReturnSeries(values, valid, segment_start, tuple(statuses), metadata)


def calendar_isolation_probe() -> float:
    """Execute the real return path for the dynamic A5 isolation gate."""
    inputs = ReturnInputs(
        ts_event_ns=np.asarray([0, BAR_NS], dtype=np.int64),
        session_id=np.asarray([20200102, 20200102], dtype=np.int32),
        symbol_code=np.asarray([0, 0], dtype=np.int16),
        close_ticks=np.asarray([100, 101], dtype=np.int32),
        expected_1m_components=np.asarray([5, 5], dtype=np.int8),
        observed_1m_components=np.asarray([5, 5], dtype=np.int8),
        rollover=np.asarray([False, False], dtype=np.bool_),
    )
    return float(construct_returns(inputs, CoverageRule.PERMISSIVE).values[1])
