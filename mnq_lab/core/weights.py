"""Market-free weighted statistics.

Frozen spec §7.2 defines a discrete inverse CDF over real-valued nonnegative
weights. The executable binary64 accumulation contract was independently
ratified before this module was created and is recorded in ``docs/PHASE4.md``.

This module knows only numeric values and weights. It does not import or name
market data, outcomes, conditioners, studies, reports, or the freeze ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral, Real
from typing import Any, Hashable

import numpy as np

from mnq_lab import SpineError

__all__ = [
    "GroupWeightDiagnostics",
    "PreparedWeightedQuantileValues",
    "WeightDiagnostics",
    "anchor_equal_weights",
    "prepare_weighted_quantile_values",
    "session_equal_weights",
    "weight_ess",
    "weighted_quantile",
    "weighted_quantile_prepared",
    "weighted_quantiles",
    "weighted_quantiles_prepared",
    "weighted_quantiles_prepared_batch_fast",
    "weighted_quantiles_prepared_fast",
]

_MAX_EXACT_BINARY64_INTEGER = 2**53
_REAL_DTYPE_KINDS = frozenset({"i", "u", "f"})


@dataclass(frozen=True)
class WeightDiagnostics:
    """Generic diagnostics shared by every weight construction."""

    row_count: int
    weight_ess: float


@dataclass(frozen=True)
class GroupWeightDiagnostics(WeightDiagnostics):
    """Diagnostics proving how mass is distributed across opaque groups."""

    contributing_group_count: int
    group_total_mass: tuple[tuple[Hashable, float], ...]
    max_group_mass_fraction: float


@dataclass(frozen=True)
class PreparedWeightedQuantileValues:
    """Replicate-invariant stable value ordering for exact weighted quantiles."""

    order: np.ndarray
    group_starts: np.ndarray
    support: np.ndarray
    source_size: int

    def __post_init__(self) -> None:
        order = np.asarray(self.order)
        starts = np.asarray(self.group_starts)
        support = np.asarray(self.support)
        if (
            isinstance(self.source_size, bool)
            or not isinstance(self.source_size, Integral)
            or self.source_size <= 0
        ):
            raise SpineError("prepared quantile source_size must be positive")
        size = int(self.source_size)
        if (
            order.ndim != 1
            or order.dtype.kind not in {"i", "u"}
            or order.size != size
            or not np.array_equal(np.sort(order), np.arange(size))
        ):
            raise SpineError("prepared quantile order must be one full permutation")
        if (
            starts.ndim != 1
            or starts.dtype.kind not in {"i", "u"}
            or starts.size == 0
            or int(starts[0]) != 0
            or bool(np.any(starts[1:] <= starts[:-1]))
            or int(starts[-1]) >= size
        ):
            raise SpineError("prepared quantile group starts are invalid")
        if (
            support.ndim != 1
            or support.dtype != np.dtype("float64")
            or support.size != starts.size
            or not bool(np.isfinite(support).all())
            or bool(np.any(support[1:] <= support[:-1]))
        ):
            raise SpineError("prepared quantile support must be finite and increasing")
        order_copy = order.astype(np.intp, copy=True)
        starts_copy = starts.astype(np.intp, copy=True)
        support_copy = support.astype(np.float64, copy=True)
        order_copy.setflags(write=False)
        starts_copy.setflags(write=False)
        support_copy.setflags(write=False)
        object.__setattr__(self, "order", order_copy)
        object.__setattr__(self, "group_starts", starts_copy)
        object.__setattr__(self, "support", support_copy)
        object.__setattr__(self, "source_size", size)


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


def prepare_weighted_quantile_values(values: Any) -> PreparedWeightedQuantileValues:
    """Prepare only the stable value ordering shared by repeated weight vectors."""
    value_array = _as_real_float64_vector(values, "values")
    order = np.argsort(value_array, kind="mergesort")
    ordered_values = value_array[order]
    group_starts = np.flatnonzero(
        np.r_[True, ordered_values[1:] != ordered_values[:-1]]
    )
    support = ordered_values[group_starts]
    return PreparedWeightedQuantileValues(
        order=order,
        group_starts=group_starts,
        support=support,
        source_size=value_array.size,
    )


def _prepared_positive_support_cdf(
    prepared: PreparedWeightedQuantileValues,
    weights: Any,
) -> tuple[np.ndarray, np.ndarray]:
    if not isinstance(prepared, PreparedWeightedQuantileValues):
        raise SpineError(
            "prepared values must come from prepare_weighted_quantile_values"
        )
    weight_array = _as_real_float64_vector(weights, "weights")
    if weight_array.size != prepared.source_size:
        raise SpineError(
            "values and weights must have equal length; "
            f"got {prepared.source_size} and {weight_array.size}"
        )
    if bool(np.any(weight_array < 0.0)):
        bad = int(np.flatnonzero(weight_array < 0.0)[0])
        raise SpineError(f"weights contains a negative value at index {bad}")

    ordered_weights = weight_array[prepared.order]
    group_ends = np.r_[prepared.group_starts[1:], prepared.source_size]
    masses = np.empty(prepared.group_starts.size, dtype=np.float64)
    for index, (start, end) in enumerate(
        zip(prepared.group_starts, group_ends, strict=True)
    ):
        canonical_weights = np.sort(
            ordered_weights[int(start) : int(end)], kind="mergesort"
        )
        masses[index] = np.cumsum(canonical_weights, dtype=np.float64)[-1]

    positive = masses > 0.0
    support = prepared.support[positive]
    masses = masses[positive]
    if support.size == 0:
        raise SpineError("weights must have strictly positive total mass")
    cumulative = np.cumsum(masses, dtype=np.float64)
    total = cumulative[-1]
    if not np.isfinite(total):
        raise SpineError("canonical binary64 weight accumulation is non-finite")
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


def weighted_quantiles_prepared(
    prepared: PreparedWeightedQuantileValues,
    weights: Any,
    quantiles: Any,
) -> np.ndarray:
    """Evaluate exact inverse-CDF quantiles using one prepared value ordering."""
    probabilities = _as_quantile_vector(quantiles)
    support, cumulative = _prepared_positive_support_cdf(prepared, weights)
    total = cumulative[-1]
    thresholds = probabilities * total
    indices = np.searchsorted(cumulative, thresholds, side="left")
    if bool(np.any(indices >= support.size)):
        raise SpineError(
            "weighted inverse-CDF selection escaped the positive-mass support"
        )
    return support[indices].astype(np.float64, copy=False)


def weighted_quantiles_prepared_fast(
    prepared: PreparedWeightedQuantileValues,
    weights: Any,
    quantiles: Any,
) -> np.ndarray:
    """Exact prepared quantiles with singleton value groups handled in bulk."""
    probabilities = _as_quantile_vector(quantiles)
    if not isinstance(prepared, PreparedWeightedQuantileValues):
        raise SpineError(
            "prepared values must come from prepare_weighted_quantile_values"
        )
    weight_array = _as_real_float64_vector(weights, "weights")
    if weight_array.size != prepared.source_size:
        raise SpineError(
            "values and weights must have equal length; "
            f"got {prepared.source_size} and {weight_array.size}"
        )
    if bool(np.any(weight_array < 0.0)):
        bad = int(np.flatnonzero(weight_array < 0.0)[0])
        raise SpineError(f"weights contains a negative value at index {bad}")

    ordered_weights = weight_array[prepared.order]
    group_ends = np.r_[prepared.group_starts[1:], prepared.source_size]
    group_lengths = group_ends - prepared.group_starts
    masses = np.empty(prepared.group_starts.size, dtype=np.float64)
    singletons = group_lengths == 1
    masses[singletons] = ordered_weights[prepared.group_starts[singletons]]
    for index in np.flatnonzero(~singletons):
        start = int(prepared.group_starts[index])
        end = int(group_ends[index])
        canonical_weights = np.sort(
            ordered_weights[start:end], kind="mergesort"
        )
        masses[index] = np.cumsum(canonical_weights, dtype=np.float64)[-1]

    positive = masses > 0.0
    support = prepared.support[positive]
    masses = masses[positive]
    if support.size == 0:
        raise SpineError("weights must have strictly positive total mass")
    cumulative = np.cumsum(masses, dtype=np.float64)
    total = cumulative[-1]
    if not np.isfinite(total):
        raise SpineError("canonical binary64 weight accumulation is non-finite")
    if not total > 0.0:
        raise SpineError("weights must have strictly positive total mass")
    thresholds = probabilities * total
    indices = np.searchsorted(cumulative, thresholds, side="left")
    if bool(np.any(indices >= support.size)):
        raise SpineError(
            "weighted inverse-CDF selection escaped the positive-mass support"
        )
    return support[indices].astype(np.float64, copy=False)


def weighted_quantiles_prepared_batch_fast(
    prepared: PreparedWeightedQuantileValues,
    weights: Any,
    quantiles: Any,
) -> np.ndarray:
    """Evaluate many replicate weight rows with exact per-row accumulation."""
    probabilities = _as_quantile_vector(quantiles)
    if not isinstance(prepared, PreparedWeightedQuantileValues):
        raise SpineError(
            "prepared values must come from prepare_weighted_quantile_values"
        )
    _reject_embedded_bools(weights, "weights")
    try:
        raw_weights = np.asarray(weights)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpineError(f"weights cannot be converted to a numeric array: {exc}") from exc
    if raw_weights.ndim != 2 or raw_weights.shape[0] == 0:
        raise SpineError("batched weights must be a nonempty two-dimensional array")
    if raw_weights.shape[1] != prepared.source_size:
        raise SpineError(
            "values and weights must have equal length; "
            f"got {prepared.source_size} and {raw_weights.shape[1]}"
        )
    if raw_weights.dtype.kind not in _REAL_DTYPE_KINDS:
        raise SpineError("weights must have a real integer or floating dtype")
    if raw_weights.dtype.kind == "u" and bool(
        np.any(raw_weights > _MAX_EXACT_BINARY64_INTEGER)
    ):
        raise SpineError("weights contains an integer greater than 2**53")
    if raw_weights.dtype.kind == "i" and bool(
        np.any(raw_weights < -_MAX_EXACT_BINARY64_INTEGER)
        or np.any(raw_weights > _MAX_EXACT_BINARY64_INTEGER)
    ):
        raise SpineError("weights contains an integer outside [-2**53, 2**53]")
    weight_matrix = raw_weights.astype(np.float64, copy=False)
    if not bool(np.isfinite(weight_matrix).all()):
        raise SpineError("weights contains a non-finite value")
    if bool(np.any(weight_matrix < 0.0)):
        raise SpineError("weights contains a negative value")

    ordered_weights = weight_matrix[:, prepared.order]
    group_ends = np.r_[prepared.group_starts[1:], prepared.source_size]
    group_lengths = group_ends - prepared.group_starts
    masses = np.empty(
        (weight_matrix.shape[0], prepared.group_starts.size),
        dtype=np.float64,
    )
    singletons = group_lengths == 1
    masses[:, singletons] = ordered_weights[
        :, prepared.group_starts[singletons]
    ]
    for index in np.flatnonzero(~singletons):
        start = int(prepared.group_starts[index])
        end = int(group_ends[index])
        canonical_weights = np.sort(
            ordered_weights[:, start:end], axis=1, kind="mergesort"
        )
        masses[:, index] = np.cumsum(
            canonical_weights, axis=1, dtype=np.float64
        )[:, -1]

    output = np.empty(
        (weight_matrix.shape[0], probabilities.size), dtype=np.float64
    )
    for row_index, row_masses in enumerate(masses):
        positive = row_masses > 0.0
        support = prepared.support[positive]
        if support.size == 0:
            raise SpineError("weights must have strictly positive total mass")
        cumulative = np.cumsum(row_masses[positive], dtype=np.float64)
        total = cumulative[-1]
        if not np.isfinite(total):
            raise SpineError("canonical binary64 weight accumulation is non-finite")
        if not total > 0.0:
            raise SpineError("weights must have strictly positive total mass")
        thresholds = probabilities * total
        indices = np.searchsorted(cumulative, thresholds, side="left")
        if bool(np.any(indices >= support.size)):
            raise SpineError(
                "weighted inverse-CDF selection escaped the positive-mass support"
            )
        output[row_index] = support[indices]
    return output


def weighted_quantile(values: Any, weights: Any, q: Any) -> float:
    """Return one discrete weighted inverse-CDF observed support value."""
    probability = _as_quantile_scalar(q)
    result = weighted_quantiles(values, weights, [probability])
    return float(result[0])


def weighted_quantile_prepared(
    prepared: PreparedWeightedQuantileValues,
    weights: Any,
    q: Any,
) -> float:
    """Return one exact quantile while reusing a prepared value ordering."""
    probability = _as_quantile_scalar(q)
    result = weighted_quantiles_prepared(prepared, weights, [probability])
    return float(result[0])


def _validated_concentration_weights(weights: Any) -> np.ndarray:
    array = _as_real_float64_vector(weights, "weights")
    if bool(np.any(array < 0.0)):
        bad = int(np.flatnonzero(array < 0.0)[0])
        raise SpineError(f"weights contains a negative value at index {bad}")
    if not bool(np.any(array > 0.0)):
        raise SpineError("weights must have strictly positive total mass")
    return array


def weight_ess(weights: Any) -> float:
    """Return the frozen weight-concentration formula ``(Σw)² / Σ(w²)``."""
    array = _validated_concentration_weights(weights)
    with np.errstate(over="ignore", invalid="ignore"):
        total = np.sum(array, dtype=np.float64)
        squared_total = np.sum(np.square(array), dtype=np.float64)
        result = (total * total) / squared_total
    if not np.isfinite(total) or not total > 0.0:
        raise SpineError(
            "binary64 weight accumulation must be finite and strictly positive"
        )
    if not np.isfinite(squared_total) or not squared_total > 0.0:
        raise SpineError(
            "binary64 squared-weight accumulation must be finite and positive"
        )
    if not np.isfinite(result):
        raise SpineError("weight_ess is non-finite under the frozen formula")
    return float(result)


def _try_integer_labels(values: Any) -> tuple[Hashable, ...] | None:
    """Vectorized validation fast path for a homogeneous non-bool integer array.

    Returns the validated label tuple, or ``None`` if the fast path does not
    apply (any non-integer, mixed, or object-dtype input), in which case the
    caller must fall back to the exact per-element validator. Integers are
    always finite and always hashable, so no per-element check is needed once
    numpy has already unified every element into one concrete integer dtype
    without falling back to ``object`` -- that unification is itself the
    proof every element was an unambiguous integer.
    """
    try:
        probe = np.asarray(values)
    except (TypeError, ValueError, OverflowError):
        return None
    if probe.ndim != 1 or probe.size == 0 or probe.dtype.kind not in ("i", "u"):
        return None
    return tuple(probe.tolist())


def _factorize_first_occurrence(
    labels: tuple[Hashable, ...],
) -> tuple[np.ndarray, list[int], list[Hashable]] | None:
    """Vectorized group-index assignment in first-occurrence order.

    Returns ``(inverse, counts, unique_labels)`` matching exactly what the
    dict-based per-element loop below produces, or ``None`` if ``labels`` is
    not a single concrete numpy dtype (mixed/object content), in which case
    the caller must fall back to that loop. Uses ``np.unique`` and then
    remaps its sorted group order to first-occurrence order via a stable
    argsort on each group's first index, so the group numbering is identical
    to the dict-insertion order regardless of the sort key ``np.unique`` used.
    """
    # Integer dtypes ONLY. numpy silently coerces mixed input to a common
    # dtype -- ``(1, "1")`` becomes two equal strings -- which would merge two
    # groups the dict loop keeps distinct. Any non-integer or mixed label set
    # falls back to that loop, so this can never change grouping semantics.
    probe = np.asarray(labels)
    if probe.ndim != 1 or probe.dtype.kind not in ("i", "u"):
        return None
    uniq_sorted, first_index, inverse_sorted, counts_sorted = np.unique(
        probe, return_index=True, return_inverse=True, return_counts=True
    )
    order = np.argsort(first_index, kind="stable")
    rank = np.empty_like(order)
    rank[order] = np.arange(len(order))
    inverse = rank[inverse_sorted].astype(np.intp, copy=False)
    counts = counts_sorted[order].tolist()
    unique_labels = [labels[i] for i in first_index[order]]
    return inverse, counts, unique_labels


def _as_opaque_group_labels(group_ids: Any) -> tuple[Hashable, ...]:
    fast = _try_integer_labels(group_ids)
    if fast is not None:
        return fast
    try:
        array = np.asarray(group_ids, dtype=object)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpineError(
            f"group_ids cannot be converted to a one-dimensional array: {exc}"
        ) from exc
    if array.ndim != 1:
        raise SpineError(
            f"group_ids must be one-dimensional, got ndim={array.ndim}"
        )
    if array.size == 0:
        raise SpineError("group_ids must contain at least one label")

    labels: list[Hashable] = []
    for index, raw_label in enumerate(array):
        label = raw_label.item() if isinstance(raw_label, np.generic) else raw_label
        if isinstance(label, bool) or label is None:
            raise SpineError(
                f"group_ids contains an invalid label at index {index}: {label!r}"
            )
        if isinstance(label, Real):
            try:
                numeric_label = float(label)
            except (TypeError, ValueError, OverflowError) as exc:
                raise SpineError(
                    f"group_ids contains an invalid numeric label at index {index}"
                ) from exc
            if not np.isfinite(numeric_label):
                raise SpineError(
                    f"group_ids contains a non-finite label at index {index}"
                )
        elif not isinstance(label, (str, bytes)):
            raise SpineError(
                "group_ids labels must be finite real numbers, strings, or bytes; "
                f"index {index} is {type(label).__name__}"
            )
        try:
            hash(label)
        except TypeError as exc:
            raise SpineError(
                f"group_ids contains an unhashable label at index {index}"
            ) from exc
        labels.append(label)
    return tuple(labels)


def session_equal_weights(
    group_ids: Any,
) -> tuple[np.ndarray, GroupWeightDiagnostics]:
    """Give equal mass to opaque groups, then equal mass within each group.

    ``group_ids`` are generic labels only. They carry no calendar, exchange, or
    market meaning. Output weights align with the caller's original row order.
    """
    labels = _as_opaque_group_labels(group_ids)
    fast = _factorize_first_occurrence(labels)
    if fast is not None:
        inverse, counts, unique_labels = fast
    else:
        group_index: dict[Hashable, int] = {}
        unique_labels = []
        counts = []
        inverse = np.empty(len(labels), dtype=np.intp)
        for row_index, label in enumerate(labels):
            index = group_index.get(label)
            if index is None:
                index = len(unique_labels)
                group_index[label] = index
                unique_labels.append(label)
                counts.append(0)
            counts[index] += 1
            inverse[row_index] = index

    group_count = len(counts)
    counts_array = np.asarray(counts, dtype=np.float64)
    per_group_weight = 1.0 / (group_count * counts_array)
    weights = per_group_weight[inverse]

    # Sum each group's rows in the same ascending row order the original
    # weights[inverse == index] mask-extraction would visit them in, so
    # np.sum's pairwise-summation algorithm sees the identical sub-array and
    # produces a bit-identical result -- not just a numerically close one.
    sort_order = np.argsort(inverse, kind="stable")
    group_boundaries = np.cumsum(np.asarray(counts, dtype=np.intp))[:-1]
    group_row_runs = np.split(sort_order, group_boundaries)
    group_masses = np.array(
        [np.sum(weights[run], dtype=np.float64) for run in group_row_runs],
        dtype=np.float64,
    )
    total_group_mass = np.sum(group_masses, dtype=np.float64)
    if not np.isfinite(total_group_mass) or not total_group_mass > 0.0:
        raise SpineError("constructed group weights have invalid total mass")
    max_group_mass_fraction = float(
        np.max(group_masses) / total_group_mass
    )
    diagnostics = GroupWeightDiagnostics(
        row_count=len(labels),
        weight_ess=weight_ess(weights),
        contributing_group_count=group_count,
        group_total_mass=tuple(
            (label, float(mass))
            for label, mass in zip(unique_labels, group_masses)
        ),
        max_group_mass_fraction=max_group_mass_fraction,
    )
    return weights, diagnostics


def anchor_equal_weights(n: Any) -> tuple[np.ndarray, WeightDiagnostics]:
    """Give each of ``n`` generic rows equal mass."""
    if isinstance(n, (bool, np.bool_)) or not isinstance(n, Integral):
        raise SpineError(f"n must be a positive non-bool integer, got {n!r}")
    row_count = int(n)
    if row_count <= 0:
        raise SpineError(f"n must be strictly positive, got {row_count}")
    try:
        weights = np.full(
            row_count, 1.0 / row_count, dtype=np.float64
        )
    except (MemoryError, ValueError, OverflowError) as exc:
        raise SpineError(
            f"cannot construct {row_count} equal weights: {exc}"
        ) from exc
    diagnostics = WeightDiagnostics(
        row_count=row_count,
        weight_ess=weight_ess(weights),
    )
    return weights, diagnostics
