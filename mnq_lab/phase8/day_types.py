"""Calendar-derived descriptive absolute distributions for Phase 8."""

from __future__ import annotations

from dataclasses import dataclass, field
from numbers import Integral
from typing import Any, Hashable

import numpy as np

from mnq_lab import SpineError
from mnq_lab.conditioners.calendar import CalendarRow
from mnq_lab.core.weights import session_equal_weights
from mnq_lab.phase8.contrasts import OUTCOME_NAMES, STATISTICS, weighted_quantile_ticks
from mnq_lab.phase8.diagnostics import (
    CompletionDiagnostics,
    anchor_support_failure,
    completion_diagnostics,
    resolve_status,
    status_decision,
)
from mnq_lab.phase8.inventory import (
    HORIZONS_MINUTES,
    PATH_ESTIMANDS,
    PRIMARY_ARM_ID,
    SUPPORT_KINDS,
)

DAY_TYPES = ("regular", "holiday_adjacent", "scheduled_early_close")
TRUNCATED_REGULAR_SESSIONS = (20200228, 20200630)
TRUNCATED_SESSION_STATUS = "unresolved_truncated_session"

_INT32 = np.iinfo(np.int32)

__all__ = [
    "DAY_TYPES",
    "TRUNCATED_REGULAR_SESSIONS",
    "TRUNCATED_SESSION_STATUS",
    "DayTypeDistribution",
    "DayTypeRowSpec",
    "DayTypeSupport",
    "classify_calendar_day_type",
    "declared_day_type_rows",
    "evaluate_day_type_distribution",
]


def _validate_day_type(value: Any, name: str = "day_type") -> str:
    if not isinstance(value, str) or value not in DAY_TYPES:
        raise SpineError(f"undeclared {name}: {value!r}")
    return value


def classify_calendar_day_type(
    calendar_row: CalendarRow,
    data_quality_status: Any,
) -> str | None:
    """Apply the accepted-calendar precedence without observed-duration input."""
    if not isinstance(calendar_row, CalendarRow):
        raise SpineError("day type requires one accepted CalendarRow")
    if not isinstance(data_quality_status, str) or not data_quality_status:
        raise SpineError("data_quality_status must be a nonempty string")

    is_truncated = calendar_row.trade_date in TRUNCATED_REGULAR_SESSIONS
    if is_truncated:
        if data_quality_status != TRUNCATED_SESSION_STATUS:
            raise SpineError(
                "the two truncated regular sessions require "
                "data_quality_status=unresolved_truncated_session"
            )
        if (
            calendar_row.session_class != "regular"
            or calendar_row.scheduled_rth_status != "full_rth"
        ):
            raise SpineError("a truncated regular session was reclassified")
    elif data_quality_status == TRUNCATED_SESSION_STATUS:
        raise SpineError(
            "unresolved_truncated_session is reserved for the two frozen sessions"
        )

    if calendar_row.session_class == "full_exchange_holiday":
        return None
    if calendar_row.session_class == "scheduled_early_close":
        if calendar_row.scheduled_rth_status not in {
            "shortened_rth",
            "no_scheduled_rth",
        }:
            raise SpineError("unknown active calendar combination for day type")
        return "scheduled_early_close"
    if (
        calendar_row.session_class == "regular"
        and calendar_row.scheduled_rth_status == "full_rth"
    ):
        return "holiday_adjacent" if calendar_row.holiday_adjacent else "regular"
    raise SpineError("unknown active calendar combination for day type")


@dataclass(frozen=True)
class DayTypeRowSpec:
    arm_id: str
    day_type: str
    outcome_name: str
    path_estimand: str
    support_kind: str
    horizon_minutes: int
    statistic: str

    def __post_init__(self) -> None:
        if self.arm_id != PRIMARY_ARM_ID:
            raise SpineError("day-type rows belong to the primary arm only")
        _validate_day_type(self.day_type)
        if self.outcome_name not in OUTCOME_NAMES:
            raise SpineError("day-type outcome is outside the frozen inventory")
        if self.path_estimand not in PATH_ESTIMANDS:
            raise SpineError("day-type path estimand is outside the frozen inventory")
        if self.support_kind not in SUPPORT_KINDS:
            raise SpineError("day-type support kind is outside the frozen inventory")
        if self.horizon_minutes not in HORIZONS_MINUTES:
            raise SpineError("day-type horizon is outside the frozen inventory")
        if self.statistic not in {name for name, _ in STATISTICS}:
            raise SpineError("day-type statistic is outside the frozen inventory")


@dataclass(frozen=True)
class DayTypeSupport:
    day_type: str
    eligibility_mask: np.ndarray = field(repr=False, compare=False)
    weights: np.ndarray = field(repr=False, compare=False)
    n_anchors: int
    n_sessions: int
    weight_ess: float | None

    def __post_init__(self) -> None:
        _validate_day_type(self.day_type)
        mask = np.asarray(self.eligibility_mask)
        weights = np.asarray(self.weights)
        if mask.ndim != 1 or mask.dtype.kind != "b":
            raise SpineError("day-type support mask must be one-dimensional bool")
        if weights.ndim != 1 or weights.dtype.kind != "f" or weights.size != mask.size:
            raise SpineError("day-type support weights must be aligned float weights")
        if not bool(np.isfinite(weights).all()) or bool(np.any(weights < 0.0)):
            raise SpineError("day-type support weights must be finite and nonnegative")
        if bool(np.any(weights[~mask] != 0.0)):
            raise SpineError("day-type support weights must be zero outside support")
        if isinstance(self.n_anchors, bool) or not isinstance(self.n_anchors, Integral):
            raise SpineError("day-type n_anchors must be a nonnegative integer")
        if isinstance(self.n_sessions, bool) or not isinstance(self.n_sessions, Integral):
            raise SpineError("day-type n_sessions must be a nonnegative integer")
        if int(self.n_anchors) != int(np.count_nonzero(mask)):
            raise SpineError("day type result evidence differs from its support")
        if int(self.n_anchors) == 0:
            if self.n_sessions != 0 or self.weight_ess is not None:
                raise SpineError("empty day-type support must not pretend to have evidence")
        else:
            if self.n_sessions <= 0 or self.weight_ess is None:
                raise SpineError("nonempty day-type support requires session and ESS evidence")
            if not np.isclose(np.sum(weights, dtype=np.float64), 1.0):
                raise SpineError("nonempty day-type support weights must have unit mass")
        mask_copy = mask.astype(np.bool_, copy=True)
        weight_copy = weights.astype(np.float64, copy=True)
        mask_copy.setflags(write=False)
        weight_copy.setflags(write=False)
        object.__setattr__(self, "eligibility_mask", mask_copy)
        object.__setattr__(self, "weights", weight_copy)
        object.__setattr__(self, "n_anchors", int(self.n_anchors))
        object.__setattr__(self, "n_sessions", int(self.n_sessions))


@dataclass(frozen=True)
class DayTypeDistribution:
    target_day_type: str
    statistic: str
    horizon_minutes: int
    quantile_ticks: int | None
    quantile_valid: bool
    n_anchors: int
    n_sessions: int
    weight_ess: float | None
    completion: CompletionDiagnostics
    status: str
    status_flags: tuple[str, ...]
    support: DayTypeSupport = field(repr=False, compare=True)

    def __post_init__(self) -> None:
        _validate_day_type(self.target_day_type, "target day_type")
        if self.statistic not in {name for name, _ in STATISTICS}:
            raise SpineError("day-type statistic is outside the frozen inventory")
        if self.horizon_minutes not in HORIZONS_MINUTES:
            raise SpineError("day-type horizon is outside the frozen inventory")
        if not isinstance(self.support, DayTypeSupport):
            raise SpineError("day type result evidence has the wrong support type")
        if (
            self.support.day_type != self.target_day_type
            or self.n_anchors != self.support.n_anchors
            or self.n_sessions != self.support.n_sessions
            or self.weight_ess != self.support.weight_ess
        ):
            raise SpineError("day type result evidence differs from its support")
        if not isinstance(self.completion, CompletionDiagnostics):
            raise SpineError("day type result evidence lacks completion diagnostics")
        if (
            self.completion.horizon_minutes != self.horizon_minutes
            or self.completion.baseline is not None
        ):
            raise SpineError("day type result evidence has mismatched completion scope")
        decision = resolve_status(self.status_flags)
        if decision.status != self.status:
            raise SpineError("day type result status differs from canonical precedence")
        if any(
            flag not in {"insufficient_anchors", "insufficient_completion"}
            for flag in self.status_flags
        ):
            raise SpineError("day type result carries an inapplicable status flag")
        if self.status == "ok":
            if (
                not self.quantile_valid
                or isinstance(self.quantile_ticks, bool)
                or not isinstance(self.quantile_ticks, Integral)
            ):
                raise SpineError("ok day type result requires one exact tick quantile")
        elif self.quantile_ticks is not None or self.quantile_valid:
            raise SpineError("invalid day type result must retain a null point")


def declared_day_type_rows() -> tuple[DayTypeRowSpec, ...]:
    """Return the complete primary-arm descriptive inventory in structural order."""
    return tuple(
        DayTypeRowSpec(
            PRIMARY_ARM_ID,
            day_type,
            outcome,
            path_estimand,
            support_kind,
            horizon,
            statistic,
        )
        for day_type in DAY_TYPES
        for outcome in OUTCOME_NAMES
        for path_estimand in PATH_ESTIMANDS
        for support_kind in SUPPORT_KINDS
        for horizon in HORIZONS_MINUTES
        for statistic, _ in STATISTICS
    )


def _one_dimensional(values: Any, name: str) -> np.ndarray:
    try:
        array = np.asarray(values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpineError(f"{name} cannot be converted to an array: {exc}") from exc
    if array.ndim != 1:
        raise SpineError(f"{name} must be one-dimensional")
    return array


def _bool_vector(values: Any, name: str) -> np.ndarray:
    array = _one_dimensional(values, name)
    if array.dtype.kind != "b":
        raise SpineError(f"{name} must be a one-dimensional bool array")
    return array.astype(np.bool_, copy=False)


def _tick_vector(values: Any) -> np.ndarray:
    array = _one_dimensional(values, "values")
    if array.dtype.kind != "i":
        raise SpineError("day-type values must be signed integer ticks")
    if bool(np.any(array < _INT32.min) or np.any(array > _INT32.max)):
        raise SpineError("day-type values must remain within int32 storage range")
    return array


def _day_type_vector(values: Any) -> np.ndarray:
    array = _one_dimensional(values, "day_types")
    for index, value in enumerate(array):
        if not isinstance(value, (str, np.str_)) or str(value) not in DAY_TYPES:
            raise SpineError(f"undeclared day_type at index {index}: {value!r}")
    return array


def _support(
    session_ids: np.ndarray,
    mask: np.ndarray,
    target_day_type: str,
) -> DayTypeSupport:
    weights = np.zeros(mask.size, dtype=np.float64)
    indices = np.flatnonzero(mask)
    if indices.size == 0:
        return DayTypeSupport(target_day_type, mask, weights, 0, 0, None)
    local_weights, diagnostics = session_equal_weights(session_ids[indices])
    weights[indices] = local_weights
    return DayTypeSupport(
        target_day_type,
        mask,
        weights,
        int(indices.size),
        diagnostics.contributing_group_count,
        diagnostics.weight_ess,
    )


def evaluate_day_type_distribution(
    *,
    values: Any,
    session_ids: Any,
    calendar_years: Any,
    structurally_eligible: Any,
    completed: Any,
    day_types: Any,
    target_day_type: Any,
    horizon_minutes: Any,
    statistic: Any,
) -> DayTypeDistribution:
    """Evaluate one declared absolute day-type level without repairing support."""
    target = _validate_day_type(target_day_type, "target day_type")
    ticks = _tick_vector(values)
    sessions = _one_dimensional(session_ids, "session_ids")
    years = _one_dimensional(calendar_years, "calendar_years")
    structural = _bool_vector(structurally_eligible, "structurally_eligible")
    complete = _bool_vector(completed, "completed")
    labels = _day_type_vector(day_types)
    if len({
        ticks.size,
        sessions.size,
        years.size,
        structural.size,
        complete.size,
        labels.size,
    }) != 1:
        raise SpineError("all day-type input vectors must have equal row length")
    target_mask = labels == target
    structural_target = structural & target_mask
    completion_support = _support(sessions, structural_target, target)
    completion = completion_diagnostics(
        horizon_minutes=horizon_minutes,
        session_ids=sessions,
        calendar_years=years,
        structurally_eligible=structural,
        completed=complete,
        target_mask=target_mask,
        target_weights=completion_support.weights,
    )
    point_support = _support(sessions, structural_target & complete, target)
    insufficient_anchors = anchor_support_failure(
        target_n_anchors=point_support.n_anchors,
        target_n_sessions=point_support.n_sessions,
        baseline_n_anchors=None,
        baseline_n_sessions=None,
        has_baseline=False,
    )
    decision = status_decision(
        degenerate_baseline=False,
        insufficient_anchors=insufficient_anchors,
        insufficient_completion=completion.insufficient_completion,
        insufficient_overlap=False,
    )
    quantile = None
    valid = False
    if decision.status == "ok":
        mask = point_support.eligibility_mask
        quantile = weighted_quantile_ticks(
            ticks[mask], point_support.weights[mask], statistic
        )
        valid = True
    return DayTypeDistribution(
        target_day_type=target,
        statistic=statistic,
        horizon_minutes=int(horizon_minutes),
        quantile_ticks=quantile,
        quantile_valid=valid,
        n_anchors=point_support.n_anchors,
        n_sessions=point_support.n_sessions,
        weight_ess=point_support.weight_ess,
        completion=completion,
        status=decision.status,
        status_flags=decision.status_flags,
        support=point_support,
    )
