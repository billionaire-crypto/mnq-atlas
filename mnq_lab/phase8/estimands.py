"""Phase 8 population-estimand weight constructors."""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Real
from typing import Any, Hashable

import numpy as np

from mnq_lab import SpineError
from mnq_lab.core.weights import session_equal_weights, weight_ess
from mnq_lab.phase8.contrasts import (
    CellKey,
    contrast_support,
    support_masks,
)

ESTIMAND_NAMES = (
    "prospective_cell",
    "common_session_paired",
    "standardized_shared_population",
)

_COMPARATIVE_WEIGHTINGS = (
    "natural_prevalence_contrast",
    "equal_phase_contrast",
)

__all__ = [
    "ESTIMAND_NAMES",
    "CellWeightDiagnostics",
    "ConditionWeights",
    "EstimandWeights",
    "build_estimand_weights",
]


@dataclass(frozen=True)
class CellWeightDiagnostics:
    cell: CellKey
    assigned_mass: float
    n_anchors: int
    n_sessions: int
    weight_ess: float | None
    quarter_target_masses: tuple[tuple[str, float], ...]
    unsupported_target_mass: float


@dataclass(frozen=True)
class ConditionWeights:
    weights: np.ndarray
    session_keys: tuple[Hashable, ...]
    n_anchors: int
    n_sessions: int
    weight_ess: float | None
    cells: tuple[CellWeightDiagnostics, ...]
    quarter_target_masses: tuple[tuple[str, float], ...]
    unsupported_target_mass: float


@dataclass(frozen=True)
class EstimandWeights:
    estimand_name: str
    contrast_name: str
    contrast_weighting: str
    target_cell: CellKey
    target: ConditionWeights
    baseline: ConditionWeights | None
    retained_session_keys: tuple[Hashable, ...]


def _one_dimensional(values: Any, name: str) -> np.ndarray:
    try:
        array = np.asarray(values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpineError(f"{name} cannot be converted to an array: {exc}") from exc
    if array.ndim != 1:
        raise SpineError(f"{name} must be one-dimensional, got ndim={array.ndim}")
    return array


def _bool_vector(values: Any, name: str) -> np.ndarray:
    array = _one_dimensional(values, name)
    if array.dtype.kind != "b":
        raise SpineError(f"{name} must be a one-dimensional bool array")
    return array.astype(np.bool_, copy=False)


def _session_labels(values: Any) -> tuple[Hashable, ...]:
    array = _one_dimensional(values, "session_ids")
    labels: list[Hashable] = []
    for row_index, raw_label in enumerate(np.asarray(array, dtype=object)):
        label = raw_label.item() if isinstance(raw_label, np.generic) else raw_label
        if isinstance(label, (bool, np.bool_)) or label is None:
            raise SpineError(
                f"session_ids contains an invalid label at index {row_index}"
            )
        if isinstance(label, Real):
            try:
                finite = np.isfinite(float(label))
            except (TypeError, ValueError, OverflowError):
                finite = False
            if not finite:
                raise SpineError(
                    f"session_ids contains a non-finite label at index {row_index}"
                )
        elif not isinstance(label, (str, bytes)):
            raise SpineError(
                "session_ids labels must be finite real numbers, strings, or bytes"
            )
        try:
            hash(label)
        except TypeError as exc:
            raise SpineError(
                f"session_ids contains an unhashable label at index {row_index}"
            ) from exc
        labels.append(label)
    return tuple(labels)


def _quarter_labels(values: Any) -> tuple[str, ...]:
    array = _one_dimensional(values, "calendar_quarters")
    labels: list[str] = []
    for row_index, raw_label in enumerate(np.asarray(array, dtype=object)):
        label = raw_label.item() if isinstance(raw_label, np.generic) else raw_label
        if (
            not isinstance(label, str)
            or len(label) != 6
            or not label[:4].isdigit()
            or label[4] != "Q"
            or label[5] not in "1234"
        ):
            raise SpineError(
                f"calendar_quarters contains an invalid year-quarter at index {row_index}: "
                f"{label!r}"
            )
        labels.append(label)
    return tuple(labels)


def _ordered_unique(values: tuple[Hashable, ...]) -> tuple[Hashable, ...]:
    seen: set[Hashable] = set()
    result: list[Hashable] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def _keys_under_mask(
    session_ids: tuple[Hashable, ...], mask: np.ndarray
) -> tuple[Hashable, ...]:
    return _ordered_unique(
        tuple(session_id for session_id, keep in zip(session_ids, mask) if keep)
    )


def _mask_for_keys(
    session_ids: tuple[Hashable, ...], keys: tuple[Hashable, ...]
) -> np.ndarray:
    key_set = set(keys)
    return np.fromiter(
        (session_id in key_set for session_id in session_ids),
        dtype=np.bool_,
        count=len(session_ids),
    )


def _cell_mask(
    phases: np.ndarray, states: np.ndarray, cell: CellKey
) -> np.ndarray:
    return (phases == cell.phase) & (states == cell.volatility_state)


def _readonly_weights(weights: np.ndarray) -> np.ndarray:
    result = np.asarray(weights, dtype=np.float64).copy()
    result.setflags(write=False)
    return result


def _validate_session_metadata(
    session_ids: tuple[Hashable, ...],
    quarters: tuple[str, ...],
    ordinary_full_length: np.ndarray,
) -> None:
    by_session: dict[Hashable, tuple[str, bool]] = {}
    for row_index, (session_id, quarter, ordinary) in enumerate(
        zip(session_ids, quarters, ordinary_full_length)
    ):
        metadata = (quarter, bool(ordinary))
        previous = by_session.get(session_id)
        if previous is None:
            by_session[session_id] = metadata
        elif previous != metadata:
            raise SpineError(
                "calendar quarter and ordinary-full-length status must be "
                f"constant within session; mismatch at index {row_index}"
            )


def _quarter_target_masses(
    session_ids: tuple[Hashable, ...],
    quarters: tuple[str, ...],
    target_population_mask: np.ndarray,
) -> tuple[tuple[str, float], ...]:
    target_sessions = _keys_under_mask(session_ids, target_population_mask)
    if not target_sessions:
        raise SpineError(
            "standardized_shared_population requires at least one eligible "
            "ordinary full-length target-population session"
        )
    target_set = set(target_sessions)
    session_quarters: dict[Hashable, str] = {}
    quarter_order: list[str] = []
    quarter_counts: dict[str, int] = {}
    for session_id, quarter in zip(session_ids, quarters):
        if session_id not in target_set or session_id in session_quarters:
            continue
        session_quarters[session_id] = quarter
        if quarter not in quarter_counts:
            quarter_order.append(quarter)
            quarter_counts[quarter] = 0
        quarter_counts[quarter] += 1
    denominator = len(target_sessions)
    return tuple(
        (quarter, quarter_counts[quarter] / denominator)
        for quarter in quarter_order
    )


def _assigned_cell_masses(
    cells: tuple[CellKey, ...],
    cell_masks: tuple[np.ndarray, ...],
    contrast_weighting: str,
) -> tuple[float, ...]:
    if len(cells) == 1:
        return (1.0,)
    if contrast_weighting == "equal_phase_contrast":
        mass = 1.0 / len(cells)
        return tuple(mass for _ in cells)
    counts = tuple(int(np.count_nonzero(mask)) for mask in cell_masks)
    denominator = sum(counts)
    if denominator == 0:
        return tuple(0.0 for _ in cells)
    return tuple(count / denominator for count in counts)


def _base_cell_weights(
    session_ids: tuple[Hashable, ...],
    quarters: tuple[str, ...],
    cell_mask: np.ndarray,
    quarter_masses: tuple[tuple[str, float], ...],
) -> tuple[np.ndarray, float]:
    weights = np.zeros(len(session_ids), dtype=np.float64)
    if not quarter_masses:
        if bool(np.any(cell_mask)):
            selected, _ = session_equal_weights(
                tuple(
                    session_id
                    for session_id, keep in zip(session_ids, cell_mask)
                    if keep
                )
            )
            weights[cell_mask] = selected
        return weights, 0.0

    unsupported_mass = 0.0
    quarter_array = np.asarray(quarters, dtype=object)
    for quarter, target_mass in quarter_masses:
        quarter_mask = cell_mask & (quarter_array == quarter)
        if not bool(np.any(quarter_mask)):
            unsupported_mass += target_mass
            continue
        selected, _ = session_equal_weights(
            tuple(
                session_id
                for session_id, keep in zip(session_ids, quarter_mask)
                if keep
            )
        )
        weights[quarter_mask] = selected * target_mass
    return weights, unsupported_mass


def _condition_weights(
    *,
    session_ids: tuple[Hashable, ...],
    quarters: tuple[str, ...],
    phases: np.ndarray,
    states: np.ndarray,
    eligibility: np.ndarray,
    cells: tuple[CellKey, ...],
    contrast_weighting: str,
    quarter_masses: tuple[tuple[str, float], ...],
) -> ConditionWeights:
    masks = tuple(
        eligibility & _cell_mask(phases, states, cell) for cell in cells
    )
    assigned_masses = _assigned_cell_masses(
        cells, masks, contrast_weighting
    )
    combined = np.zeros(len(session_ids), dtype=np.float64)
    diagnostics: list[CellWeightDiagnostics] = []
    aggregate_unsupported_mass = 0.0

    for cell, mask, assigned_mass in zip(cells, masks, assigned_masses):
        base_weights, unsupported_mass = _base_cell_weights(
            session_ids, quarters, mask, quarter_masses
        )
        scaled = base_weights * assigned_mass
        combined += scaled
        positive = scaled > 0.0
        cell_sessions = _keys_under_mask(session_ids, mask)
        cell_ess = weight_ess(scaled[positive]) if bool(np.any(positive)) else None
        diagnostics.append(
            CellWeightDiagnostics(
                cell=cell,
                assigned_mass=float(assigned_mass),
                n_anchors=int(np.count_nonzero(mask)),
                n_sessions=len(cell_sessions),
                weight_ess=cell_ess,
                quarter_target_masses=quarter_masses,
                unsupported_target_mass=float(unsupported_mass),
            )
        )
        aggregate_unsupported_mass += assigned_mass * unsupported_mass

    union_mask = np.zeros(len(session_ids), dtype=np.bool_)
    for mask in masks:
        union_mask |= mask
    positive_combined = combined > 0.0
    overall_ess = (
        weight_ess(combined[positive_combined])
        if bool(np.any(positive_combined))
        else None
    )
    session_keys = _keys_under_mask(session_ids, union_mask)
    return ConditionWeights(
        weights=_readonly_weights(combined),
        session_keys=session_keys,
        n_anchors=int(np.count_nonzero(union_mask)),
        n_sessions=len(session_keys),
        weight_ess=overall_ess,
        cells=tuple(diagnostics),
        quarter_target_masses=quarter_masses,
        unsupported_target_mass=float(aggregate_unsupported_mass),
    )


def build_estimand_weights(
    *,
    estimand_name: Any,
    session_ids: Any,
    calendar_quarters: Any,
    session_phases: Any,
    volatility_states: Any,
    outcome_eligible: Any,
    ordinary_full_length: Any,
    target: CellKey,
    contrast_name: Any,
    contrast_weighting: Any,
) -> EstimandWeights:
    """Build full-row Phase 8 weights and immutable support diagnostics."""
    if not isinstance(estimand_name, str) or estimand_name not in ESTIMAND_NAMES:
        raise SpineError(f"undeclared Phase 8 estimand: {estimand_name!r}")

    labels = _session_labels(session_ids)
    quarters = _quarter_labels(calendar_quarters)
    phases = _one_dimensional(session_phases, "session_phases")
    states = _one_dimensional(volatility_states, "volatility_states")
    eligible = _bool_vector(outcome_eligible, "outcome_eligible")
    ordinary = _bool_vector(ordinary_full_length, "ordinary_full_length")
    lengths = {
        len(labels), len(quarters), phases.size, states.size, eligible.size, ordinary.size
    }
    if len(lengths) != 1:
        raise SpineError("all estimand input vectors must have equal row length")
    support = contrast_support(target, contrast_name)
    masks = support_masks(phases, states, target, contrast_name)
    _validate_session_metadata(labels, quarters, ordinary)

    if support.baseline_cells:
        if contrast_weighting not in _COMPARATIVE_WEIGHTINGS:
            raise SpineError(
                "comparative Phase 8 contrasts require a declared contrast weighting"
            )
    elif contrast_weighting != "not_applicable":
        raise SpineError(
            "absolute_distribution requires contrast_weighting='not_applicable'"
        )
    weighting = str(contrast_weighting)

    retained_sessions: tuple[Hashable, ...] = ()
    quarter_masses: tuple[tuple[str, float], ...] = ()
    condition_eligibility = eligible.copy()

    if estimand_name == "common_session_paired":
        target_sessions = _keys_under_mask(labels, eligible & masks.target)
        if support.baseline_cells:
            baseline_sessions = set(
                _keys_under_mask(labels, eligible & masks.baseline)
            )
            retained_sessions = tuple(
                session_id
                for session_id in target_sessions
                if session_id in baseline_sessions
            )
        else:
            retained_sessions = target_sessions
        condition_eligibility &= _mask_for_keys(labels, retained_sessions)
    elif estimand_name == "standardized_shared_population":
        condition_eligibility &= ordinary
        quarter_masses = _quarter_target_masses(
            labels, quarters, condition_eligibility
        )

    target_weights = _condition_weights(
        session_ids=labels,
        quarters=quarters,
        phases=phases,
        states=states,
        eligibility=condition_eligibility,
        cells=support.target_cells,
        contrast_weighting=weighting,
        quarter_masses=quarter_masses,
    )
    baseline_weights = None
    if support.baseline_cells:
        baseline_weights = _condition_weights(
            session_ids=labels,
            quarters=quarters,
            phases=phases,
            states=states,
            eligibility=condition_eligibility,
            cells=support.baseline_cells,
            contrast_weighting=weighting,
            quarter_masses=quarter_masses,
        )

    return EstimandWeights(
        estimand_name=estimand_name,
        contrast_name=str(contrast_name),
        contrast_weighting=weighting,
        target_cell=target,
        target=target_weights,
        baseline=baseline_weights,
        retained_session_keys=retained_sessions,
    )
