"""Calendar-free lower-median utility for Phase 7 scale construction."""

from __future__ import annotations

from typing import Any

import numpy as np

from mnq_lab import SpineError
from mnq_lab.core.weights import weighted_quantile

__all__ = ["calendar_isolation_probe", "lower_median"]


def lower_median(values: Any) -> float:
    """Return the frozen inverted-CDF median as a binary64 scalar."""
    try:
        array = np.asarray(values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpineError(f"median values cannot be converted to an array: {exc}") from exc
    if array.ndim != 1 or array.size == 0:
        raise SpineError("median values must be a nonempty one-dimensional array")
    if array.dtype.kind not in "iuf" or array.dtype == np.bool_:
        raise SpineError(f"median values must be real numeric, got {array.dtype}")
    converted = array.astype(np.float64, copy=False)
    if not bool(np.isfinite(converted).all()):
        raise SpineError("median values must be finite")
    weights = np.ones(converted.size, dtype=np.float64)
    return weighted_quantile(converted, weights, 0.5)


def calendar_isolation_probe() -> float:
    """Execute the real median path for the dynamic A5 isolation gate."""
    return lower_median(np.asarray([1.0, 2.0, 100.0, 200.0], dtype=np.float64))
