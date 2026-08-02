"""Independent rolling lower-median MAD scale for Phase 7."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from mnq_lab import SpineError
from mnq_lab.conditioners.scales.median import lower_median
from mnq_lab.conditioners.scales.returns import (
    BAR_NS,
    CoverageRule,
    ReturnInputs,
    ReturnSeries,
    construct_returns,
)
from mnq_lab.conditioners.status import MadStatus, ReturnStatus

__all__ = [
    "MAD_FACTOR",
    "MAD_WINDOW_RETURNS",
    "MadScaleSeries",
    "calendar_isolation_probe",
    "mad_declared_mask",
    "rolling_mad",
]

MAD_WINDOW_RETURNS = 78
MAD_FACTOR = np.float64(1.4826)


def _readonly(array: np.ndarray) -> np.ndarray:
    result = np.array(array, copy=True)
    result.setflags(write=False)
    return result


def mad_declared_mask(size: int, segment_start: int, anchor: int) -> np.ndarray:
    """Return the production declaration for exactly 78 contiguous returns."""
    if type(size) is not int or type(segment_start) is not int or type(anchor) is not int:
        raise SpineError("MAD mask bounds must be built-in integers")
    first = anchor - MAD_WINDOW_RETURNS
    if not 0 <= segment_start <= first <= anchor < size:
        raise SpineError("MAD requires exactly 79 bars in one contiguous segment")
    mask = np.zeros(size, dtype=np.bool_)
    mask[first : anchor + 1] = True
    mask.setflags(write=False)
    return mask


@dataclass(frozen=True)
class MadScaleSeries:
    values: np.ndarray
    valid: np.ndarray
    contiguous_return_count: np.ndarray
    statuses: tuple[MadStatus, ...]
    segment_start: np.ndarray
    metadata: MappingProxyType

    def __post_init__(self) -> None:
        values = np.asarray(self.values)
        valid = np.asarray(self.valid)
        counts = np.asarray(self.contiguous_return_count)
        starts = np.asarray(self.segment_start)
        if values.dtype != np.dtype("float64") or valid.dtype != np.dtype("bool"):
            raise SpineError("MAD value/valid dtypes must be float64/bool")
        if counts.dtype != np.dtype("int32") or starts.dtype != np.dtype("int64"):
            raise SpineError("MAD count/start dtypes must be int32/int64")
        if values.ndim != 1 or not (
            values.shape == valid.shape == counts.shape == starts.shape
        ):
            raise SpineError("MAD outputs must be aligned one-dimensional arrays")
        if len(self.statuses) != values.size or not all(
            isinstance(status, MadStatus) for status in self.statuses
        ):
            raise SpineError("MAD statuses must align and use the closed vocabulary")
        if not bool(np.isfinite(values).all()) or bool(np.any(values < 0.0)):
            raise SpineError("MAD stored values must be finite and nonnegative")
        if not bool(np.all(counts >= 0)):
            raise SpineError("MAD contiguous-return counts must be nonnegative")
        if any(
            (status is MadStatus.OK) != bool(valid[index])
            for index, status in enumerate(self.statuses)
        ):
            raise SpineError("MAD status and validity disagree")
        object.__setattr__(self, "values", _readonly(values))
        object.__setattr__(self, "valid", _readonly(valid))
        object.__setattr__(self, "contiguous_return_count", _readonly(counts))
        object.__setattr__(self, "segment_start", _readonly(starts))

    def declared_mask(self, anchor: int) -> np.ndarray:
        if type(anchor) is not int or not 0 <= anchor < self.values.size:
            raise SpineError("MAD anchor is outside output support")
        if not self.valid[anchor]:
            raise SpineError("MAD has no admitted declared mask for undefined output")
        return mad_declared_mask(
            int(self.values.size), int(self.segment_start[anchor]), anchor
        )


def rolling_mad(returns: ReturnSeries) -> MadScaleSeries:
    """Compute the 78-return median-centered lower-median MAD scale."""
    if not isinstance(returns, ReturnSeries):
        raise SpineError("returns must be a ReturnSeries")
    size = returns.values.size
    values = np.zeros(size, dtype=np.float64)
    valid = np.zeros(size, dtype=np.bool_)
    counts = np.zeros(size, dtype=np.int32)
    statuses: list[MadStatus] = []
    contiguous_values: list[np.float64] = []

    for index in range(size):
        if returns.statuses[index].return_status is not ReturnStatus.OK:
            contiguous_values.clear()
            statuses.append(MadStatus.WARMUP)
            continue
        contiguous_values.append(np.float64(returns.values[index]))
        count = len(contiguous_values)
        counts[index] = count
        if count < MAD_WINDOW_RETURNS:
            statuses.append(MadStatus.WARMUP)
            continue
        window = np.asarray(contiguous_values[-MAD_WINDOW_RETURNS:], dtype=np.float64)
        center = np.float64(lower_median(window))
        deviations = np.abs(window - center).astype(np.float64, copy=False)
        unscaled = np.float64(lower_median(deviations))
        scale = np.float64(MAD_FACTOR * unscaled)
        if not np.isfinite(scale) or scale < np.float64(0.0):
            raise SpineError(f"MAD scale is invalid at index {index}")
        if scale == np.float64(0.0):
            statuses.append(MadStatus.ZERO_SCALE)
            continue
        values[index] = scale
        valid[index] = True
        statuses.append(MadStatus.OK)

    metadata = MappingProxyType(
        {
            "estimator": "rolling_lower_median_mad",
            "window_returns": MAD_WINDOW_RETURNS,
            "median_method": "inverted_cdf",
            "factor": float(MAD_FACTOR),
            "dtype": "float64",
            "atol": 0.0,
            "rtol": 1e-12,
            "semantic_mask_version": "phase7-bars-v1",
        }
    )
    return MadScaleSeries(
        values,
        valid,
        counts,
        tuple(statuses),
        returns.segment_start,
        metadata,
    )


def calendar_isolation_probe() -> float:
    """Execute a real defined MAD output for the dynamic A5 gate."""
    size = MAD_WINDOW_RETURNS + 1
    inputs = ReturnInputs(
        ts_event_ns=np.arange(size, dtype=np.int64) * np.int64(BAR_NS),
        session_id=np.full(size, 20200102, dtype=np.int32),
        symbol_code=np.zeros(size, dtype=np.int16),
        close_ticks=(10_000 + np.arange(size, dtype=np.int32) ** 2),
        expected_1m_components=np.full(size, 5, dtype=np.int8),
        observed_1m_components=np.full(size, 5, dtype=np.int8),
        rollover=np.zeros(size, dtype=np.bool_),
    )
    returns = construct_returns(inputs, CoverageRule.PERMISSIVE)
    output = rolling_mad(returns)
    if not output.valid[-1]:
        raise SpineError("MAD A5 probe failed to reach a defined output")
    return float(output.values[-1])
