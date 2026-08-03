"""Completion, positivity, and total status diagnostics for Phase 8."""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral, Real
from pathlib import Path
from typing import Any, Hashable

import numpy as np

from mnq_lab import SpineError
from mnq_lab.constants import load_completion_thresholds, load_constants
from mnq_lab.core.weights import session_equal_weights, weight_ess
from mnq_lab.phase8.contrasts import CellKey, contrast_support
from mnq_lab.phase8.estimands import ESTIMAND_NAMES

STATUS_PRECEDENCE = (
    "degenerate_baseline",
    "insufficient_anchors",
    "insufficient_completion",
    "insufficient_overlap",
)

_POSITIVITY_KEYS = (
    "min_baseline_anchors_per_stratum",
    "min_contributing_sessions",
    "max_single_anchor_weight_share",
    "max_weight_cv",
    "max_unsupported_target_mass",
)

_POSITIVITY_BREACH_ORDER = (
    "insufficient_baseline_anchors",
    "insufficient_contributing_sessions",
    "invalid_session_equal_support",
    "invalid_target_weight_support",
    "single_anchor_weight_share_above_maximum",
    "weight_cv_above_maximum",
    "unsupported_target_mass_above_maximum",
    "quarter_unsupported_target_mass_above_maximum",
)

__all__ = [
    "STATUS_PRECEDENCE",
    "CompletionDiagnostics",
    "CompletionSideDiagnostics",
    "CompletionYearDiagnostics",
    "PositivityDiagnostics",
    "PositivityStratumDiagnostics",
    "PositivityStratumInput",
    "PositivityThresholds",
    "ResultValidity",
    "StatusDecision",
    "anchor_support_failure",
    "completion_diagnostics",
    "positivity_diagnostics",
    "resolve_status",
    "status_decision",
    "validate_result_validity",
]


@dataclass(frozen=True)
class CompletionYearDiagnostics:
    year: int
    n_anchors: int
    n_sessions: int
    weight_ess: float | None
    n_complete: int
    completion_rate: float | None


@dataclass(frozen=True)
class CompletionSideDiagnostics:
    n_anchors: int
    n_sessions: int
    weight_ess: float | None
    n_complete: int
    completion_rate: float | None
    by_year: tuple[CompletionYearDiagnostics, ...]
    accepted_years: tuple[int, ...]
    single_year_concentration: bool


@dataclass(frozen=True)
class CompletionDiagnostics:
    horizon_minutes: int
    threshold: float
    max_imbalance: float
    source_population_years: tuple[int, ...]
    target: CompletionSideDiagnostics
    baseline: CompletionSideDiagnostics | None
    completion_imbalance: float | None
    breaches: tuple[str, ...]
    insufficient_completion: bool


@dataclass(frozen=True)
class PositivityThresholds:
    min_baseline_anchors_per_stratum: int
    min_contributing_sessions: int
    max_single_anchor_weight_share: float
    max_weight_cv: float
    max_unsupported_target_mass: float


@dataclass(frozen=True)
class PositivityStratumInput:
    stratum: CellKey
    target_weights: np.ndarray
    baseline_session_ids: tuple[Hashable, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.stratum, CellKey):
            raise SpineError("positivity stratum must be a declared CellKey")
        weights = _nonnegative_weights(self.target_weights, "target_weights")
        weights.setflags(write=False)
        object.__setattr__(self, "target_weights", weights)
        if not isinstance(self.baseline_session_ids, tuple):
            raise SpineError("baseline_session_ids must be an immutable tuple")
        _validated_session_labels(self.baseline_session_ids, "baseline_session_ids")


@dataclass(frozen=True)
class PositivityStratumDiagnostics:
    stratum: CellKey
    target_weight_mass: float
    n_anchors: int
    n_sessions: int
    weight_ess: float | None
    max_single_anchor_weight_share: float | None
    weight_cv: float | None
    baseline_support_shortage: bool


@dataclass(frozen=True)
class PositivityDiagnostics:
    thresholds: PositivityThresholds
    strata: tuple[PositivityStratumDiagnostics, ...]
    unsupported_target_mass: float | None
    quarter_unsupported_target_mass: float
    breaches: tuple[str, ...]
    insufficient_overlap: bool


@dataclass(frozen=True)
class StatusDecision:
    status: str
    status_flags: tuple[str, ...]
    failure_states: tuple[bool, bool, bool, bool]


@dataclass(frozen=True)
class ResultValidity:
    point_ticks: int | None
    point_valid: bool
    interval_valid: bool


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


def _nonnegative_weights(values: Any, name: str) -> np.ndarray:
    array = _one_dimensional(values, name)
    object_view = np.asarray(values, dtype=object)
    if any(isinstance(item, (bool, np.bool_)) for item in object_view.flat):
        raise SpineError(f"{name} must contain finite nonnegative real weights")
    if array.dtype.kind not in {"i", "u", "f"}:
        raise SpineError(f"{name} must contain finite nonnegative real weights")
    converted = array.astype(np.float64, copy=True)
    if not bool(np.isfinite(converted).all()) or bool(np.any(converted < 0.0)):
        raise SpineError(f"{name} must contain finite nonnegative real weights")
    return converted


def _validated_session_labels(values: Any, name: str) -> tuple[Hashable, ...]:
    try:
        labels = tuple(values)
    except TypeError as exc:
        raise SpineError(f"{name} must be a finite sequence") from exc
    validated: list[Hashable] = []
    for index, raw in enumerate(labels):
        label = raw.item() if isinstance(raw, np.generic) else raw
        if isinstance(label, (bool, np.bool_)) or label is None:
            raise SpineError(f"{name} contains an invalid label at index {index}")
        if isinstance(label, Real):
            try:
                finite = np.isfinite(float(label))
            except (TypeError, ValueError, OverflowError):
                finite = False
            if not finite:
                raise SpineError(f"{name} contains a non-finite label at index {index}")
        elif not isinstance(label, (str, bytes)):
            raise SpineError(
                f"{name} labels must be finite real numbers, strings, or bytes"
            )
        try:
            hash(label)
        except TypeError as exc:
            raise SpineError(f"{name} contains an unhashable label at index {index}") from exc
        validated.append(label)
    return tuple(validated)


def _ordered_unique(values: Any) -> tuple[Any, ...]:
    seen: set[Any] = set()
    result: list[Any] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def _weight_ess_or_none(weights: np.ndarray) -> float | None:
    positive = weights > 0.0
    return weight_ess(weights[positive]) if bool(np.any(positive)) else None


def _completion_contract(
    path: Path | None,
) -> tuple[dict[int, float], float]:
    thresholds = load_completion_thresholds(path)
    raw = load_constants(path).get("completion", "max_imbalance_absolute")
    if isinstance(raw, bool) or not isinstance(raw, Real):
        raise SpineError("completion.max_imbalance_absolute must be numeric")
    maximum = float(raw)
    if not np.isfinite(maximum) or not 0.0 <= maximum <= 1.0:
        raise SpineError(
            "completion.max_imbalance_absolute must be finite and inside [0,1]"
        )
    return thresholds, maximum


def _completion_side(
    *,
    labels: tuple[Hashable, ...],
    years: np.ndarray,
    source_years: tuple[int, ...],
    mask: np.ndarray,
    completed: np.ndarray,
    weights: np.ndarray,
) -> CompletionSideDiagnostics:
    session_keys = _ordered_unique(
        label for label, keep in zip(labels, mask) if keep
    )
    n_anchors = int(np.count_nonzero(mask))
    n_complete = int(np.count_nonzero(mask & completed))
    rate = None if n_anchors == 0 else n_complete / n_anchors
    by_year: list[CompletionYearDiagnostics] = []
    for year in source_years:
        year_mask = mask & (years == year)
        year_sessions = _ordered_unique(
            label for label, keep in zip(labels, year_mask) if keep
        )
        year_anchors = int(np.count_nonzero(year_mask))
        year_complete = int(np.count_nonzero(year_mask & completed))
        by_year.append(
            CompletionYearDiagnostics(
                year=year,
                n_anchors=year_anchors,
                n_sessions=len(year_sessions),
                weight_ess=_weight_ess_or_none(weights[year_mask]),
                n_complete=year_complete,
                completion_rate=(
                    None if year_anchors == 0 else year_complete / year_anchors
                ),
            )
        )
    accepted_years = _ordered_unique(int(year) for year in years[mask & completed])
    concentrated = len(source_years) > 1 and len(accepted_years) == 1
    return CompletionSideDiagnostics(
        n_anchors=n_anchors,
        n_sessions=len(session_keys),
        weight_ess=_weight_ess_or_none(weights[mask]),
        n_complete=n_complete,
        completion_rate=rate,
        by_year=tuple(by_year),
        accepted_years=accepted_years,
        single_year_concentration=concentrated,
    )


def completion_diagnostics(
    *,
    horizon_minutes: Any,
    session_ids: Any,
    calendar_years: Any,
    structurally_eligible: Any,
    completed: Any,
    target_mask: Any,
    target_weights: Any,
    baseline_mask: Any | None = None,
    baseline_weights: Any | None = None,
    constants_path: Path | None = None,
) -> CompletionDiagnostics:
    """Evaluate completion without changing any left-hand-side assignment."""
    thresholds, max_imbalance = _completion_contract(constants_path)
    if isinstance(horizon_minutes, (bool, np.bool_)) or not isinstance(
        horizon_minutes, Integral
    ):
        raise SpineError("horizon_minutes must be one of the frozen horizons")
    horizon = int(horizon_minutes)
    if horizon not in thresholds:
        raise SpineError(f"undeclared Phase 8 horizon: {horizon}")

    labels = _validated_session_labels(
        _one_dimensional(session_ids, "session_ids"), "session_ids"
    )
    years_array = _one_dimensional(calendar_years, "calendar_years")
    if years_array.dtype.kind not in {"i", "u"}:
        raise SpineError("calendar_years must contain integer years")
    years = years_array.astype(np.int64, copy=False)
    structural = _bool_vector(structurally_eligible, "structurally_eligible")
    completion = _bool_vector(completed, "completed")
    target = _bool_vector(target_mask, "target_mask")
    target_weight_array = _nonnegative_weights(target_weights, "target_weights")
    lengths = {
        len(labels), years.size, structural.size, completion.size,
        target.size, target_weight_array.size,
    }
    if len(lengths) != 1:
        raise SpineError("all completion input vectors must have equal row length")

    source_years = tuple(
        int(year) for year in _ordered_unique(years[structural].tolist())
    )
    target_support = structural & target
    target_diagnostics = _completion_side(
        labels=labels,
        years=years,
        source_years=source_years,
        mask=target_support,
        completed=completion,
        weights=target_weight_array,
    )

    if (baseline_mask is None) != (baseline_weights is None):
        raise SpineError("baseline completion mask and weights must be supplied together")
    baseline_diagnostics = None
    if baseline_mask is not None:
        baseline = _bool_vector(baseline_mask, "baseline_mask")
        baseline_weight_array = _nonnegative_weights(
            baseline_weights, "baseline_weights"
        )
        if baseline.size != len(labels) or baseline_weight_array.size != len(labels):
            raise SpineError("all completion input vectors must have equal row length")
        baseline_diagnostics = _completion_side(
            labels=labels,
            years=years,
            source_years=source_years,
            mask=structural & baseline,
            completed=completion,
            weights=baseline_weight_array,
        )

    threshold = thresholds[horizon]
    imbalance = None
    breaches: list[str] = []
    if (
        target_diagnostics.completion_rate is None
        or target_diagnostics.completion_rate < threshold
    ):
        breaches.append("target_below_completion_minimum")
    if baseline_diagnostics is not None:
        if (
            baseline_diagnostics.completion_rate is None
            or baseline_diagnostics.completion_rate < threshold
        ):
            breaches.append("baseline_below_completion_minimum")
        if (
            target_diagnostics.completion_rate is not None
            and baseline_diagnostics.completion_rate is not None
        ):
            imbalance = abs(
                target_diagnostics.completion_rate
                - baseline_diagnostics.completion_rate
            )
            if imbalance > max_imbalance:
                breaches.append("completion_imbalance_above_maximum")
    if target_diagnostics.single_year_concentration:
        breaches.append("target_accepted_support_confined_to_one_year")
    if (
        baseline_diagnostics is not None
        and baseline_diagnostics.single_year_concentration
    ):
        breaches.append("baseline_accepted_support_confined_to_one_year")
    return CompletionDiagnostics(
        horizon_minutes=horizon,
        threshold=threshold,
        max_imbalance=max_imbalance,
        source_population_years=source_years,
        target=target_diagnostics,
        baseline=baseline_diagnostics,
        completion_imbalance=imbalance,
        breaches=tuple(breaches),
        insufficient_completion=bool(breaches),
    )


def _positivity_thresholds(path: Path | None) -> PositivityThresholds:
    positivity = load_constants(path).get("positivity")
    if not isinstance(positivity, dict) or tuple(positivity) != _POSITIVITY_KEYS:
        actual = tuple(positivity) if isinstance(positivity, dict) else ()
        raise SpineError(
            f"positivity must contain exactly the keys {_POSITIVITY_KEYS}; found {actual}"
        )
    minimums: list[int] = []
    for key in _POSITIVITY_KEYS[:2]:
        value = positivity[key]
        if isinstance(value, bool) or not isinstance(value, Integral) or value <= 0:
            raise SpineError(f"positivity.{key} must be a positive integer")
        minimums.append(int(value))
    maximums: list[float] = []
    for key in _POSITIVITY_KEYS[2:]:
        value = positivity[key]
        if isinstance(value, bool) or not isinstance(value, Real):
            raise SpineError(f"positivity.{key} must be a finite nonnegative real")
        numeric = float(value)
        if not np.isfinite(numeric) or numeric < 0.0:
            raise SpineError(f"positivity.{key} must be a finite nonnegative real")
        maximums.append(numeric)
    return PositivityThresholds(*minimums, *maximums)


def positivity_diagnostics(
    *,
    strata: Any,
    target: CellKey,
    contrast_name: Any,
    population_estimand: Any,
    quarter_unsupported_target_mass: Any = 0.0,
    constants_path: Path | None = None,
) -> PositivityDiagnostics:
    """Evaluate exact phase-volatility strata with session-equal weights."""
    thresholds = _positivity_thresholds(constants_path)
    if population_estimand not in ESTIMAND_NAMES:
        raise SpineError(f"undeclared Phase 8 estimand: {population_estimand!r}")
    try:
        inputs = tuple(strata)
    except TypeError as exc:
        raise SpineError("strata must be a finite sequence") from exc
    if not inputs or any(not isinstance(item, PositivityStratumInput) for item in inputs):
        raise SpineError("strata must contain PositivityStratumInput values")
    keys = tuple(item.stratum for item in inputs)
    declared = contrast_support(target, contrast_name).baseline_cells
    if not declared:
        raise SpineError("positivity baseline support is not applicable to absolute_distribution")
    if keys != declared:
        raise SpineError(
            "positivity strata must exactly equal the declared comparison support "
            "in structural order"
        )

    if isinstance(quarter_unsupported_target_mass, (bool, np.bool_)) or not isinstance(
        quarter_unsupported_target_mass, Real
    ):
        raise SpineError("quarter_unsupported_target_mass must be inside [0,1]")
    quarter_mass = float(quarter_unsupported_target_mass)
    if not np.isfinite(quarter_mass) or not 0.0 <= quarter_mass <= 1.0:
        raise SpineError("quarter_unsupported_target_mass must be inside [0,1]")
    if population_estimand != "standardized_shared_population" and quarter_mass != 0.0:
        raise SpineError(
            "quarter unsupported mass applies only to standardized_shared_population"
        )

    diagnostics: list[PositivityStratumDiagnostics] = []
    breach_set: set[str] = set()
    unsupported_mass_numerator = 0.0
    total_target_mass = 0.0
    for item in inputs:
        target_mass = float(np.sum(item.target_weights, dtype=np.float64))
        if not np.isfinite(target_mass):
            raise SpineError("target stratum weight mass is non-finite")
        total_target_mass += target_mass
        n_anchors = len(item.baseline_session_ids)
        session_keys = _ordered_unique(item.baseline_session_ids)
        n_sessions = len(session_keys)
        shortage = (
            n_anchors < thresholds.min_baseline_anchors_per_stratum
            or n_sessions < thresholds.min_contributing_sessions
        )
        if n_anchors < thresholds.min_baseline_anchors_per_stratum:
            breach_set.add("insufficient_baseline_anchors")
        if n_sessions < thresholds.min_contributing_sessions:
            breach_set.add("insufficient_contributing_sessions")
        if shortage:
            unsupported_mass_numerator += target_mass

        ess = maximum_share = cv = None
        if n_anchors == 0:
            breach_set.add("invalid_session_equal_support")
        else:
            session_weights, session_diagnostics = session_equal_weights(
                item.baseline_session_ids
            )
            positive = session_weights[session_weights > 0.0]
            if positive.size == 0 or not float(np.mean(positive)) > 0.0:
                breach_set.add("invalid_session_equal_support")
            else:
                ess = session_diagnostics.weight_ess
                maximum_share = float(np.max(positive))
                cv = float(
                    np.std(positive, ddof=0, dtype=np.float64)
                    / np.mean(positive, dtype=np.float64)
                )
                if maximum_share > thresholds.max_single_anchor_weight_share:
                    breach_set.add("single_anchor_weight_share_above_maximum")
                if cv > thresholds.max_weight_cv:
                    breach_set.add("weight_cv_above_maximum")
        diagnostics.append(
            PositivityStratumDiagnostics(
                stratum=item.stratum,
                target_weight_mass=target_mass,
                n_anchors=n_anchors,
                n_sessions=n_sessions,
                weight_ess=ess,
                max_single_anchor_weight_share=maximum_share,
                weight_cv=cv,
                baseline_support_shortage=shortage,
            )
        )

    unsupported_mass = None
    if total_target_mass > 0.0:
        unsupported_mass = unsupported_mass_numerator / total_target_mass
        if unsupported_mass > thresholds.max_unsupported_target_mass:
            breach_set.add("unsupported_target_mass_above_maximum")
    else:
        breach_set.add("invalid_target_weight_support")
    if (
        population_estimand == "standardized_shared_population"
        and quarter_mass > thresholds.max_unsupported_target_mass
    ):
        breach_set.add("quarter_unsupported_target_mass_above_maximum")
    breaches = tuple(name for name in _POSITIVITY_BREACH_ORDER if name in breach_set)
    return PositivityDiagnostics(
        thresholds=thresholds,
        strata=tuple(diagnostics),
        unsupported_target_mass=unsupported_mass,
        quarter_unsupported_target_mass=quarter_mass,
        breaches=breaches,
        insufficient_overlap=bool(breaches),
    )


def anchor_support_failure(
    *,
    target_n_anchors: Any,
    target_n_sessions: Any,
    baseline_n_anchors: Any,
    baseline_n_sessions: Any,
    has_baseline: Any,
    constants_path: Path | None = None,
) -> bool:
    """Apply the top-level anchor rule; baseline is inapplicable for absolutes."""
    threshold = _positivity_thresholds(
        constants_path
    ).min_baseline_anchors_per_stratum
    if type(has_baseline) is not bool:
        raise SpineError("has_baseline must be bool")

    def invalid_count(value: Any, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
            raise SpineError(f"{name} must be a nonnegative integer")
        return int(value)

    target_anchors = invalid_count(target_n_anchors, "target_n_anchors")
    target_sessions = invalid_count(target_n_sessions, "target_n_sessions")
    failed = target_anchors < threshold or target_sessions == 0
    if not has_baseline:
        if baseline_n_anchors is not None or baseline_n_sessions is not None:
            raise SpineError("absolute support must not supply baseline counts")
        return failed
    baseline_anchors = invalid_count(baseline_n_anchors, "baseline_n_anchors")
    baseline_sessions = invalid_count(baseline_n_sessions, "baseline_n_sessions")
    return failed or baseline_anchors < threshold or baseline_sessions == 0


def resolve_status(status_flags: Any) -> StatusDecision:
    try:
        flags = tuple(status_flags)
    except TypeError as exc:
        raise SpineError("status_flags must be an immutable canonical sequence") from exc
    if any(flag not in STATUS_PRECEDENCE for flag in flags):
        raise SpineError("status_flags contains an unknown flag")
    if len(set(flags)) != len(flags):
        raise SpineError("status_flags contains a duplicate flag")
    canonical = tuple(flag for flag in STATUS_PRECEDENCE if flag in flags)
    if flags != canonical:
        raise SpineError("status_flags differs from frozen status precedence")
    states = tuple(flag in flags for flag in STATUS_PRECEDENCE)
    return StatusDecision(
        status=flags[0] if flags else "ok",
        status_flags=flags,
        failure_states=states,
    )


def status_decision(
    *,
    degenerate_baseline: Any,
    insufficient_anchors: Any,
    insufficient_completion: Any,
    insufficient_overlap: Any,
) -> StatusDecision:
    states = (
        degenerate_baseline,
        insufficient_anchors,
        insufficient_completion,
        insufficient_overlap,
    )
    if any(type(value) is not bool for value in states):
        raise SpineError("status failure states must be built-in bool values")
    return resolve_status(
        tuple(
            name for name, failed in zip(STATUS_PRECEDENCE, states) if failed
        )
    )


def _validated_decision(decision: StatusDecision) -> StatusDecision:
    if not isinstance(decision, StatusDecision):
        raise SpineError("result status must be a StatusDecision")
    if (
        not isinstance(decision.failure_states, tuple)
        or len(decision.failure_states) != len(STATUS_PRECEDENCE)
        or any(type(value) is not bool for value in decision.failure_states)
    ):
        raise SpineError("status failure_states are invalid")
    expected_flags = tuple(
        name
        for name, failed in zip(STATUS_PRECEDENCE, decision.failure_states)
        if failed
    )
    resolved = resolve_status(decision.status_flags)
    if decision.status_flags != expected_flags or decision.status != resolved.status:
        raise SpineError("status_flags hides or misorders a recorded failure")
    return decision


def validate_result_validity(
    decision: StatusDecision,
    *,
    point_ticks: Any,
    point_valid: Any,
    interval_valid: Any,
) -> ResultValidity:
    """Reject valid numeric output on any non-ok result row."""
    checked = _validated_decision(decision)
    if type(point_valid) is not bool or type(interval_valid) is not bool:
        raise SpineError("point_valid and interval_valid must be built-in bool values")
    if checked.status != "ok":
        if point_ticks is not None or point_valid or interval_valid:
            raise SpineError("non-ok row must have null point and false validity flags")
        return ResultValidity(None, False, False)
    if point_valid:
        if isinstance(point_ticks, bool) or not isinstance(point_ticks, Integral):
            raise SpineError("a valid point must be an exact integer tick")
        point = int(point_ticks)
    else:
        if point_ticks is not None:
            raise SpineError("an invalid point must be null")
        point = None
    return ResultValidity(point, point_valid, interval_valid)
