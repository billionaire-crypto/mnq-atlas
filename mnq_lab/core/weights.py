"""Market-free weighted statistics.

Frozen spec §7.2 defines a discrete inverse CDF over real-valued nonnegative
weights. The executable binary64 accumulation contract was independently
ratified before this module was created and is recorded in ``docs/PHASE4.md``.

This module knows only numeric values and weights. It does not import or name
market data, outcomes, conditioners, studies, reports, or the freeze ledger.
"""

from __future__ import annotations

from numbers import Real
from typing import Any

import numpy as np

from mnq_lab import SpineError

__all__ = ["weighted_quantile", "weighted_quantiles"]

_MAX_EXACT_BINARY64_INTEGER = 2**53
_REAL_DTYPE_KINDS = frozenset({"i", "u", "f"})


def _reject_embedded_bools(values: Any, name: str) -> None:
    """Reject bools before a heterogeneous array-like coerces them to 0/1."""
    try:
        object_view = np.asarray(values, dtype=object)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpineError(f"{name} cannot be converted to an array: {exc}") from exc
    if any(
        isinstance(item, (bool, np.bool_)) for item in object_view.flat
    ):
        raise SpineError(
            f"{name} contains a bool; implicit bool-to-number conversion is forbidden"
        )


def _as_real_float64_vector(values: Any, name: str) -> np.ndarray:
    """Validate a non-empty real numeric vector and convert it to binary64."""
    _reject_embedded_bools(values, name)
    try:
        array = np.asarray(values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpineError(
            f"{name} cannot be converted to a numeric array: {exc}"
        ) from exc
    if array.ndim != 1:
        raise SpineError(f"{name} must be one-dimensional, got ndim={array.ndim}")
    if array.size == 0:
        raise SpineError(f"{name} must contain at least one entry")
    if array.dtype.kind not in _REAL_DTYPE_KINDS:
        raise SpineError(
            f"{name} must have a real integer or floating dtype; "
            f"got {array.dtype}"
        )

    if array.dtype.kind == "u":
        if bool(np.any(array > _MAX_EXACT_BINARY64_INTEGER)):
            raise SpineError(
                f"{name} contains an integer greater than 2**53; binary64 "
                "could not preserve the supplied value exactly"
            )
    elif array.dtype.kind == "i":
        if bool(
            np.any(array < -_MAX_EXACT_BINARY64_INTEGER)
            or np.any(array > _MAX_EXACT_BINARY64_INTEGER)
        ):
            raise SpineError(
                f"{name} contains an integer outside [-2**53, 2**53]; "
                "binary64 could not preserve the supplied value exactly"
            )

    converted = array.astype(np.float64, copy=False)
    if not bool(np.isfinite(converted).all()):
        bad = int(np.flatnonzero(~np.isfinite(converted))[0])
        raise SpineError(f"{name} contains a non-finite value at index {bad}")
    return converted


def _as_quantile_vector(quantiles: Any) -> np.ndarray:
    _reject_embedded_bools(quantiles, "quantiles")
    try:
        array = np.asarray(quantiles)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpineError(
            f"quantiles cannot be converted to a numeric array: {exc}"
        ) from exc
    if array.ndim != 1:
        raise SpineError(
            f"quantiles must be one-dimensional, got ndim={array.ndim}"
        )
    if array.size == 0:
        raise SpineError("quantiles must contain at least one probability")
    if array.dtype.kind not in _REAL_DTYPE_KINDS:
        raise SpineError(
            "quantiles must have a real integer or floating dtype; "
            f"got {array.dtype}"
        )
    converted = array.astype(np.float64, copy=False)
    invalid = ~np.isfinite(converted) | (converted <= 0.0) | (converted > 1.0)
    if bool(invalid.any()):
        bad = int(np.flatnonzero(invalid)[0])
        raise SpineError(
            "quantiles must be finite, non-bool probabilities in 0 < q <= 1; "
            f"index {bad} is {converted[bad]!r}"
        )
    return converted


def _as_quantile_scalar(q: Any) -> float:
    if isinstance(q, (bool, np.bool_)) or not isinstance(q, Real):
        raise SpineError(
            f"q must be a finite, non-bool real scalar in 0 < q <= 1; got {q!r}"
        )
    try:
        probability = float(q)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpineError(
            f"q must be a finite, non-bool real scalar in 0 < q <= 1; got {q!r}"
        ) from exc
    if not np.isfinite(probability) or not 0.0 < probability <= 1.0:
        raise SpineError(
            "q must be a finite, non-bool real scalar in 0 < q <= 1; "
            f"got {q!r}"
        )
    return probability


def _positive_support_cdf(
    values: Any, weights: Any
) -> tuple[np.ndarray, np.ndarray]:
    """Return positive-mass support and its canonical cumulative mass.

    Accumulation order is part of the public numerical contract:

    1. stable mergesort by observed value;
    2. ascending mergesort of weights within each tied-value group;
    3. binary64 cumsum within groups and then across support points.

    Total mass is always the final returned cumulative value. It is never
    computed by an independent sum.
    """
    value_array = _as_real_float64_vector(values, "values")
    weight_array = _as_real_float64_vector(weights, "weights")
    if value_array.size != weight_array.size:
        raise SpineError(
            "values and weights must have equal length; "
            f"got {value_array.size} and {weight_array.size}"
        )
    if bool(np.any(weight_array < 0.0)):
        bad = int(np.flatnonzero(weight_array < 0.0)[0])
        raise SpineError(f"weights contains a negative value at index {bad}")

    order = np.argsort(value_array, kind="mergesort")
    ordered_values = value_array[order]
    ordered_weights = weight_array[order]

    group_starts = np.flatnonzero(
        np.r_[True, ordered_values[1:] != ordered_values[:-1]]
    )
    group_ends = np.r_[group_starts[1:], ordered_values.size]
    support = ordered_values[group_starts]
    masses = np.empty(group_starts.size, dtype=np.float64)

    for index, (start, end) in enumerate(zip(group_starts, group_ends)):
        canonical_weights = np.sort(
            ordered_weights[start:end], kind="mergesort"
        )
        masses[index] = np.cumsum(
            canonical_weights, dtype=np.float64
        )[-1]

    positive = masses > 0.0
    support = support[positive]
    masses = masses[positive]
    if support.size == 0:
        raise SpineError("weights must have strictly positive total mass")

    cumulative = np.cumsum(masses, dtype=np.float64)
    total = cumulative[-1]
    if not np.isfinite(total):
        raise SpineError(
            "canonical binary64 weight accumulation is non-finite"
        )
    if not total > 0.0:
        raise SpineError("weights must have strictly positive total mass")
    return support, cumulative


def weighted_quantiles(
    values: Any, weights: Any, quantiles: Any
) -> np.ndarray:
    """Return discrete weighted inverse-CDF values in caller quantile order.

    The returned float64 values are observed positive-mass support points. No
    interpolation, tolerance, pre-normalization, or input mutation occurs.
    Duplicate probabilities are permitted.
    """
    probabilities = _as_quantile_vector(quantiles)
    support, cumulative = _positive_support_cdf(values, weights)
    total = cumulative[-1]
    thresholds = probabilities * total
    indices = np.searchsorted(cumulative, thresholds, side="left")
    if bool(np.any(indices >= support.size)):
        raise SpineError(
            "weighted inverse-CDF selection escaped the positive-mass support"
        )
    return support[indices].astype(np.float64, copy=False)


def weighted_quantile(values: Any, weights: Any, q: Any) -> float:
    """Return one discrete weighted inverse-CDF observed support value."""
    probability = _as_quantile_scalar(q)
    result = weighted_quantiles(values, weights, [probability])
    return float(result[0])
