"""Bias-adjusted causal EWMA RMS estimators for Phase 7."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from mnq_lab import SpineError
from mnq_lab.conditioners.scales.returns import (
    BAR_NS,
    CoverageRule,
    ReturnInputs,
    ReturnSeries,
    construct_returns,
)
from mnq_lab.conditioners.status import EwmaStatus, ReturnStatus

__all__ = [
    "EWMA_HALFLIVES",
    "EWMA_WARMUP_RETURNS",
    "EwmaScaleSeries",
    "calendar_isolation_probe",
    "ewma_alpha",
    "ewma_declared_mask",
    "ewma_rms",
]

EWMA_HALFLIVES = (39, 78, 156)
EWMA_WARMUP_RETURNS = 78


def _readonly(array: np.ndarray) -> np.ndarray:
    result = np.array(array, copy=True)
    result.setflags(write=False)
    return result


def ewma_alpha(halflife: int) -> np.float64:
    """Return ``1 - 0.5**(1/h)`` in the frozen stable binary64 form."""
    if type(halflife) is not int or halflife not in EWMA_HALFLIVES:
        raise SpineError(f"halflife must be one of {EWMA_HALFLIVES}")
    exponent = np.float64(np.log(np.float64(0.5)) / np.float64(halflife))
    alpha = np.float64(-np.expm1(exponent))
    if not np.isfinite(alpha) or not np.float64(0.0) < alpha < np.float64(1.0):
        raise SpineError("EWMA alpha is outside (0, 1)")
    return alpha


def ewma_declared_mask(
    size: int, segment_start: int, anchor: int
) -> np.ndarray:
    """Return the production declaration for the exact bar-indexed window."""
    if type(size) is not int or type(segment_start) is not int or type(anchor) is not int:
        raise SpineError("EWMA mask bounds must be built-in integers")
    if not 0 <= segment_start <= anchor < size:
        raise SpineError("invalid EWMA declared-mask bounds")
    mask = np.zeros(size, dtype=np.bool_)
    mask[segment_start : anchor + 1] = True
    mask.setflags(write=False)
    return mask


@dataclass(frozen=True)
class EwmaScaleSeries:
    values: np.ndarray
    valid: np.ndarray
    contiguous_return_count: np.ndarray
    statuses: tuple[EwmaStatus, ...]
    segment_start: np.ndarray
    metadata: MappingProxyType

    def __post_init__(self) -> None:
        values = np.asarray(self.values)
        valid = np.asarray(self.valid)
        counts = np.asarray(self.contiguous_return_count)
        starts = np.asarray(self.segment_start)
        if values.dtype != np.dtype("float64"):
            raise SpineError("EWMA values dtype must be float64")
        if valid.dtype != np.dtype("bool"):
            raise SpineError("EWMA valid dtype must be bool")
        if counts.dtype != np.dtype("int32") or starts.dtype != np.dtype("int64"):
            raise SpineError("EWMA count/start dtypes must be int32/int64")
        if values.ndim != 1 or not (
            values.shape == valid.shape == counts.shape == starts.shape
        ):
            raise SpineError("EWMA outputs must be aligned one-dimensional arrays")
        if len(self.statuses) != values.size or not all(
            isinstance(status, EwmaStatus) for status in self.statuses
        ):
            raise SpineError("EWMA statuses must align and use the closed vocabulary")
        if not bool(np.isfinite(values).all()) or bool(np.any(values < 0.0)):
            raise SpineError("EWMA stored values must be finite and nonnegative")
        if not bool(np.all(counts >= 0)):
            raise SpineError("EWMA contiguous-return counts must be nonnegative")
        if any(
            (status is EwmaStatus.OK) != bool(valid[index])
            for index, status in enumerate(self.statuses)
        ):
            raise SpineError("EWMA status and validity disagree")
        object.__setattr__(self, "values", _readonly(values))
        object.__setattr__(self, "valid", _readonly(valid))
        object.__setattr__(self, "contiguous_return_count", _readonly(counts))
        object.__setattr__(self, "segment_start", _readonly(starts))

    def declared_mask(self, anchor: int) -> np.ndarray:
        if type(anchor) is not int or not 0 <= anchor < self.values.size:
            raise SpineError("EWMA anchor is outside output support")
        return ewma_declared_mask(
            int(self.values.size), int(self.segment_start[anchor]), anchor
        )


def ewma_rms(returns: ReturnSeries, halflife: int) -> EwmaScaleSeries:
    """Compute the causal bias-adjusted EWMA RMS in written binary64 order."""
    if not isinstance(returns, ReturnSeries):
        raise SpineError("returns must be a ReturnSeries")
    alpha = ewma_alpha(halflife)
    decay = np.float64(np.float64(1.0) - alpha)
    size = returns.values.size
    values = np.zeros(size, dtype=np.float64)
    valid = np.zeros(size, dtype=np.bool_)
    counts = np.zeros(size, dtype=np.int32)
    statuses: list[EwmaStatus] = []
    numerator = np.float64(0.0)
    denominator = np.float64(0.0)
    count = 0

    for index in range(size):
        returned = returns.statuses[index].return_status
        if returned is not ReturnStatus.OK:
            numerator = np.float64(0.0)
            denominator = np.float64(0.0)
            count = 0
            statuses.append(EwmaStatus.WARMUP)
            continue

        value = np.float64(returns.values[index])
        squared = np.float64(value * value)
        numerator = np.float64(np.float64(decay * numerator) + squared)
        denominator = np.float64(
            np.float64(decay * denominator) + np.float64(1.0)
        )
        count += 1
        counts[index] = count
        if count < EWMA_WARMUP_RETURNS:
            statuses.append(EwmaStatus.WARMUP)
            continue
        variance = np.float64(numerator / denominator)
        if not np.isfinite(variance) or variance < np.float64(0.0):
            raise SpineError(f"EWMA variance is invalid at index {index}")
        scale = np.float64(np.sqrt(variance))
        if not np.isfinite(scale) or scale < np.float64(0.0):
            raise SpineError(f"EWMA scale is invalid at index {index}")
        if scale == np.float64(0.0):
            scale = np.float64(0.0)
        values[index] = scale
        valid[index] = True
        statuses.append(EwmaStatus.OK)

    metadata = MappingProxyType(
        {
            "estimator": "bias_adjusted_ewma_rms",
            "halflife_bars": halflife,
            "alpha": float(alpha),
            "decay": float(decay),
            "warmup_returns": EWMA_WARMUP_RETURNS,
            "dtype": "float64",
            "atol": 0.0,
            "rtol": 1e-12,
            "semantic_mask_version": "phase7-bars-v1",
        }
    )
    return EwmaScaleSeries(
        values,
        valid,
        counts,
        tuple(statuses),
        returns.segment_start,
        metadata,
    )


def calendar_isolation_probe() -> float:
    """Execute a real defined EWMA output for the dynamic A5 gate."""
    size = EWMA_WARMUP_RETURNS + 1
    inputs = ReturnInputs(
        ts_event_ns=np.arange(size, dtype=np.int64) * np.int64(BAR_NS),
        session_id=np.full(size, 20200102, dtype=np.int32),
        symbol_code=np.zeros(size, dtype=np.int16),
        close_ticks=np.arange(10_000, 10_000 + size, dtype=np.int32),
        expected_1m_components=np.full(size, 5, dtype=np.int8),
        observed_1m_components=np.full(size, 5, dtype=np.int8),
        rollover=np.zeros(size, dtype=np.bool_),
    )
    returns = construct_returns(inputs, CoverageRule.PERMISSIVE)
    output = ewma_rms(returns, 78)
    if not output.valid[-1]:
        raise SpineError("EWMA A5 probe failed to reach a defined output")
    return float(output.values[-1])
