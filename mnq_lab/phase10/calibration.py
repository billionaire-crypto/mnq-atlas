"""Predeclared calibration-summary gate; no randomized generator lives here.

Fixed synthetic summaries exercise this module without spending one-shot entropy.
Generating randomized controls, evaluating corpus permutations, or counting their
formal outcomes is separately authorized evidence work and is intentionally absent.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from numbers import Integral, Real
from typing import Any

import numpy as np

from mnq_lab import SpineError

NULL_REPLICATIONS = 300
NOMINAL_ALPHA = 0.05
NULL_EVENT_BAND = (8, 23)
EFFECT_ORDER = ("weak", "medium", "strong")


@dataclass(frozen=True)
class EffectSummary:
    name: str
    replications: int
    events: int
    mean_localization_overlap: float


@dataclass(frozen=True)
class CalibrationDecision:
    accepted: bool
    checks: tuple[tuple[str, bool], ...]


def _count(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
        raise SpineError(f"{name} must be a nonnegative integer")
    return int(value)


def _wilson(events: int, replications: int) -> tuple[float, float]:
    proportion = events / replications
    z = 1.959963984540054
    denominator = 1.0 + (z * z) / replications
    center = (proportion + (z * z) / (2.0 * replications)) / denominator
    spread = (
        z
        * sqrt(
            (proportion * (1.0 - proportion) / replications)
            + (z * z) / (4.0 * replications * replications)
        )
        / denominator
    )
    return center - spread, center + spread


def _positive_slope(values: tuple[float, float, float]) -> bool:
    x = np.asarray((0.0, 1.0, 2.0), dtype=np.float64)
    y = np.asarray(values, dtype=np.float64)
    centered_x = x - float(np.mean(x))
    centered_y = y - float(np.mean(y))
    slope = float(np.sum(centered_x * centered_y) / np.sum(centered_x * centered_x))
    return slope > 0.0


def evaluate_calibration_summary(
    null_events: Any,
    effects: Any,
) -> CalibrationDecision:
    """Apply the preregistered loose criteria to supplied summary values."""
    null_count = _count(null_events, "null_events")
    if null_count > NULL_REPLICATIONS:
        raise SpineError("null event count exceeds its fixed replication count")
    try:
        supplied = tuple(effects)
    except TypeError as exc:
        raise SpineError("effects must be a finite sequence") from exc
    if len(supplied) != 3 or any(not isinstance(item, EffectSummary) for item in supplied):
        raise SpineError("effects must contain exactly three EffectSummary values")
    if tuple(item.name for item in supplied) != EFFECT_ORDER:
        raise SpineError("effect summaries differ from the fixed order")
    fractions: list[float] = []
    intervals: list[tuple[float, float]] = []
    overlaps: list[float] = []
    for item in supplied:
        replications = _count(item.replications, "effect replications")
        events = _count(item.events, "effect events")
        if replications != NULL_REPLICATIONS or events > replications:
            raise SpineError("effect summary replication contract differs")
        if isinstance(item.mean_localization_overlap, bool) or not isinstance(
            item.mean_localization_overlap, Real
        ):
            raise SpineError("localization overlap must be one finite real value")
        overlap = float(item.mean_localization_overlap)
        if not np.isfinite(overlap) or not 0.0 <= overlap <= 1.0:
            raise SpineError("localization overlap must be inside [0,1]")
        fractions.append(events / replications)
        intervals.append(_wilson(events, replications))
        overlaps.append(overlap)
    checks = (
        ("null_binomial_band", NULL_EVENT_BAND[0] <= null_count <= NULL_EVENT_BAND[1]),
        ("power_positive_overall_trend", _positive_slope(tuple(fractions))),
        (
            "power_intervals_consistent",
            intervals[1][1] >= intervals[0][0]
            and intervals[2][1] >= intervals[1][0],
        ),
        ("strong_clearly_above_weak", intervals[2][0] > intervals[0][1]),
        ("localization_positive_overall_trend", _positive_slope(tuple(overlaps))),
        ("strong_localization_above_weak", overlaps[2] > overlaps[0]),
    )
    return CalibrationDecision(all(passed for _, passed in checks), checks)
