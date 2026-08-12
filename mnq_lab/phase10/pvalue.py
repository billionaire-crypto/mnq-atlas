"""Frozen one-sided upper Monte Carlo p-value."""

from __future__ import annotations

from numbers import Real
from typing import Any

import numpy as np

from mnq_lab import SpineError


def permutation_pvalue(observed_statistic: Any, null_statistics: Any) -> float:
    """Return the exact plus-one estimate with ties in the numerator."""
    if isinstance(observed_statistic, (bool, np.bool_)) or not isinstance(
        observed_statistic, Real
    ):
        raise SpineError("observed statistic must be one finite real value")
    observed = float(observed_statistic)
    try:
        values = np.asarray(null_statistics)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpineError("null statistics cannot be converted") from exc
    if values.ndim != 1 or values.size == 0 or values.dtype.kind not in {"i", "u", "f"}:
        raise SpineError("null statistics must be one nonempty real vector")
    converted = values.astype(np.float64, copy=False)
    if not np.isfinite(observed) or not bool(np.isfinite(converted).all()):
        raise SpineError("permutation statistics must be finite")
    exceedances = int(np.count_nonzero(converted >= observed))
    return (1.0 + exceedances) / (int(converted.size) + 1.0)
