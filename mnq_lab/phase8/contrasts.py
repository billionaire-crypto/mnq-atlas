"""Frozen Phase 8 axes, named supports, and raw-tick comparisons."""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Real
from typing import Any, Hashable

import numpy as np

from mnq_lab import SpineError
from mnq_lab.core.weights import (
    PreparedWeightedQuantileValues,
    prepare_weighted_quantile_values,
    weighted_quantile,
    weighted_quantile_prepared,
)

OUTCOME_NAMES = (
    "downward_excursion_ticks",
    "upward_excursion_ticks",
)
STATISTICS = (("q50", 0.50), ("q75", 0.75), ("q90", 0.90))
SESSION_PHASES = ("open", "morning", "midday", "afternoon", "close")
VOLATILITY_STATES = ("low", "mid", "high")
CONTRAST_NAMES = (
    "absolute_distribution",
    "phase_effect_given_vol",
    "vol_effect_given_phase",
    "cell_vs_complement",
    "cell_vs_population",
)

_STATISTIC_PROBABILITIES = dict(STATISTICS)
_INT32_INFO = np.iinfo(np.int32)
_INT64_INFO = np.iinfo(np.int64)

__all__ = [
    "CONTRAST_NAMES",
    "OUTCOME_NAMES",
    "SESSION_PHASES",
    "STATISTICS",
    "VOLATILITY_STATES",
    "CellKey",
    "ContrastSupport",
    "SupportMasks",
    "TickContrast",
    "PreparedTickQuantileValues",
    "contrast_support",
    "degenerate_baseline",
    "statistic_probability",
    "prepare_weighted_quantile_ticks",
    "support_masks",
    "tick_contrast",
    "weighted_quantile_ticks",
]


def _validate_phase(phase: Any) -> str:
    if not isinstance(phase, str) or phase not in SESSION_PHASES:
        raise SpineError(f"undeclared Phase 8 session phase: {phase!r}")
    return phase


def _validate_volatility_state(volatility_state: Any) -> str:
    if (
        not isinstance(volatility_state, str)
        or volatility_state not in VOLATILITY_STATES
    ):
        raise SpineError(
            f"undeclared volatility state: {volatility_state!r}"
        )
    return volatility_state


def _validate_contrast_name(contrast_name: Any) -> str:
    if not isinstance(contrast_name, str) or contrast_name not in CONTRAST_NAMES:
        raise SpineError(f"undeclared Phase 8 contrast: {contrast_name!r}")
    return contrast_name


@dataclass(frozen=True, order=True)
class CellKey:
    """One structurally declared phase-volatility cell."""

    phase: str
    volatility_state: str

    def __post_init__(self) -> None:
        _validate_phase(self.phase)
        _validate_volatility_state(self.volatility_state)


@dataclass(frozen=True)
class ContrastSupport:
    target_cells: tuple[CellKey, ...]
    baseline_cells: tuple[CellKey, ...]


@dataclass(frozen=True)
class SupportMasks:
    target: np.ndarray
    baseline: np.ndarray


@dataclass(frozen=True)
class TickContrast:
    target_quantile_ticks: int
    baseline_quantile_ticks: int
    contrast_ticks: int


@dataclass(frozen=True)
class PreparedTickQuantileValues:
    """Signed-int32 tick values with one audited prepared value ordering."""

    prepared: PreparedWeightedQuantileValues

    def __post_init__(self) -> None:
        if not isinstance(self.prepared, PreparedWeightedQuantileValues):
            raise SpineError("prepared tick values require the audited core helper")


def statistic_probability(statistic: Any) -> float:
    """Return the preregistered probability for one literal statistic name."""
    if not isinstance(statistic, str) or statistic not in _STATISTIC_PROBABILITIES:
        raise SpineError(f"undeclared Phase 8 statistic: {statistic!r}")
    return _STATISTIC_PROBABILITIES[statistic]


def _all_cells() -> tuple[CellKey, ...]:
    return tuple(
        CellKey(phase, volatility_state)
        for phase in SESSION_PHASES
        for volatility_state in VOLATILITY_STATES
    )


def contrast_support(target: CellKey, contrast_name: Any) -> ContrastSupport:
    """Return exact declared target and baseline cells in structural order."""
    if not isinstance(target, CellKey):
        raise SpineError("target must be a declared Phase 8 CellKey")
    name = _validate_contrast_name(contrast_name)

    if name == "absolute_distribution":
        baseline_cells: tuple[CellKey, ...] = ()
    elif name == "phase_effect_given_vol":
        baseline_cells = tuple(
            CellKey(phase, target.volatility_state)
            for phase in SESSION_PHASES
            if phase != target.phase
        )
    elif name == "vol_effect_given_phase":
        baseline_cells = tuple(
            CellKey(target.phase, volatility_state)
            for volatility_state in VOLATILITY_STATES
            if volatility_state != target.volatility_state
        )
    elif name == "cell_vs_complement":
        baseline_cells = tuple(cell for cell in _all_cells() if cell != target)
    elif name == "cell_vs_population":
        baseline_cells = _all_cells()
    else:  # pragma: no cover - _validate_contrast_name makes this unreachable
        raise SpineError(f"unhandled declared Phase 8 contrast: {name!r}")
    return ContrastSupport(target_cells=(target,), baseline_cells=baseline_cells)


def _label_vector(values: Any, name: str) -> np.ndarray:
    try:
        array = np.asarray(values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpineError(f"{name} cannot be converted to an array: {exc}") from exc
    if array.ndim != 1:
        raise SpineError(f"{name} must be one-dimensional, got ndim={array.ndim}")
    return array


def _readonly_bool(values: np.ndarray) -> np.ndarray:
    result = np.asarray(values, dtype=np.bool_).copy()
    result.setflags(write=False)
    return result


def support_masks(
    session_phases: Any,
    volatility_states: Any,
    target: CellKey,
    contrast_name: Any,
) -> SupportMasks:
    """Build masks from exact declared labels without support repair."""
    support = contrast_support(target, contrast_name)
    phases = _label_vector(session_phases, "session_phases")
    states = _label_vector(volatility_states, "volatility_states")
    if phases.size != states.size:
        raise SpineError(
            "session_phases and volatility_states must have equal length; "
            f"got {phases.size} and {states.size}"
        )

    for row_index, phase in enumerate(phases):
        if not isinstance(phase, (str, np.str_)) or phase not in SESSION_PHASES:
            raise SpineError(
                f"undeclared Phase 8 session phase at index {row_index}: {phase!r}"
            )
    for row_index, state in enumerate(states):
        if (
            not isinstance(state, (str, np.str_))
            or state not in VOLATILITY_STATES
        ):
            raise SpineError(
                f"undeclared volatility state at index {row_index}: {state!r}"
            )

    target_mask = (phases == target.phase) & (
        states == target.volatility_state
    )
    baseline_mask = np.zeros(phases.size, dtype=np.bool_)
    for cell in support.baseline_cells:
        baseline_mask |= (phases == cell.phase) & (
            states == cell.volatility_state
        )
    return SupportMasks(
        target=_readonly_bool(target_mask),
        baseline=_readonly_bool(baseline_mask),
    )


def _signed_int32_tick_vector(values: Any) -> np.ndarray:
    try:
        array = np.asarray(values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpineError(f"ticks cannot be converted to an array: {exc}") from exc
    if array.ndim != 1 or array.dtype.kind != "i":
        raise SpineError(
            "tick values must be one-dimensional signed integer ticks"
        )
    if array.size == 0:
        raise SpineError("tick values must contain at least one signed integer tick")
    if bool(np.any(array < _INT32_INFO.min) or np.any(array > _INT32_INFO.max)):
        raise SpineError("signed integer ticks must remain within int32 storage range")
    return array


def prepare_weighted_quantile_ticks(values: Any) -> PreparedTickQuantileValues:
    """Validate signed int32 ticks and prepare their invariant value ordering."""
    ticks = _signed_int32_tick_vector(values)
    return PreparedTickQuantileValues(prepare_weighted_quantile_values(ticks))


def weighted_quantile_ticks(values: Any, weights: Any, statistic: Any) -> int:
    """Return one exact inverse-CDF tick without interpolation or rounding."""
    probability = statistic_probability(statistic)
    if isinstance(values, PreparedTickQuantileValues):
        raw = weighted_quantile_prepared(values.prepared, weights, probability)
    else:
        ticks = _signed_int32_tick_vector(values)
        raw = weighted_quantile(ticks, weights, probability)
    if isinstance(raw, (bool, np.bool_)) or not isinstance(raw, Real):
        raise SpineError("weighted quantile produced a non-integral tick quantile")
    numeric = float(raw)
    if not np.isfinite(numeric):
        raise SpineError("weighted quantile produced a non-finite tick quantile")
    if not numeric.is_integer():
        raise SpineError("weighted quantile produced a non-integral tick quantile")
    if numeric < _INT64_INFO.min or numeric > _INT64_INFO.max:
        raise SpineError("weighted quantile tick is outside int64 range")
    return int(numeric)


def tick_contrast(
    target_values: Any,
    target_weights: Any,
    baseline_values: Any,
    baseline_weights: Any,
    statistic: Any,
) -> TickContrast:
    """Subtract baseline from target after widening both exact ticks to int64."""
    target_tick = weighted_quantile_ticks(
        target_values, target_weights, statistic
    )
    baseline_tick = weighted_quantile_ticks(
        baseline_values, baseline_weights, statistic
    )
    widened_target = np.int64(target_tick)
    widened_baseline = np.int64(baseline_tick)
    difference = int(widened_target - widened_baseline)
    return TickContrast(
        target_quantile_ticks=target_tick,
        baseline_quantile_ticks=baseline_tick,
        contrast_ticks=difference,
    )


def _normalized_key_weights(
    keys: Any, weights: Any, side: str
) -> dict[Hashable, float]:
    try:
        key_tuple = tuple(keys)
    except TypeError as exc:
        raise SpineError(f"{side} support keys must be a finite sequence") from exc
    try:
        object_weights = np.asarray(weights, dtype=object)
        array = np.asarray(weights)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpineError(f"{side} weights cannot be converted to an array: {exc}") from exc
    if array.ndim != 1 or array.size != len(key_tuple) or array.size == 0:
        raise SpineError(
            f"{side} support keys and weights must be nonempty one-dimensional "
            "sequences of equal length"
        )
    if any(isinstance(value, (bool, np.bool_)) for value in object_weights.flat):
        raise SpineError(f"{side} weights must be finite nonnegative real values")
    if array.dtype.kind not in frozenset({"i", "u", "f"}):
        raise SpineError(f"{side} weights must be finite nonnegative real values")
    converted = array.astype(np.float64, copy=False)
    if not bool(np.isfinite(converted).all()) or bool(np.any(converted < 0.0)):
        raise SpineError(f"{side} weights must be finite nonnegative real values")
    total = np.sum(converted, dtype=np.float64)
    if not np.isfinite(total) or not total > 0.0:
        raise SpineError(f"{side} weights must have strictly positive total mass")

    result: dict[Hashable, float] = {}
    normalized = converted / total
    for index, key in enumerate(key_tuple):
        try:
            hash(key)
        except TypeError as exc:
            raise SpineError(f"{side} support key at index {index} is unhashable") from exc
        if key in result:
            raise SpineError(f"{side} support keys must be unique")
        result[key] = float(normalized[index])
    return result


def degenerate_baseline(
    target_keys: Any,
    target_weights: Any,
    baseline_keys: Any,
    baseline_weights: Any,
) -> bool:
    """Test exact key identity and exact normalized weights, independent of values."""
    target = _normalized_key_weights(target_keys, target_weights, "target")
    baseline = _normalized_key_weights(
        baseline_keys, baseline_weights, "baseline"
    )
    if target.keys() != baseline.keys():
        return False
    return all(target[key] == baseline[key] for key in target)
