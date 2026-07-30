"""Market-free whole-group stationary resampling.

Frozen spec §7.3 requires one coherent resample of ordered whole groups, with
the selected occurrence count equal to the original group count. This module
creates that immutable plan and composes its integer group multiplicities with
unchanged row-aligned baseline weights. Interval construction remains a
separate Phase 5 unit.
"""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Real
from typing import Any, Hashable

import numpy as np

from mnq_lab import SpineError
from mnq_lab.core.weights import (
    _as_opaque_group_labels,
    _validated_concentration_weights,
)

__all__ = [
    "StationaryGroupResamplePlan",
    "apply_group_multiplicities",
    "stationary_group_resample",
]


def _validated_mean_block_groups(mean_block_groups: Any) -> float:
    if isinstance(mean_block_groups, (bool, np.bool_)) or not isinstance(
        mean_block_groups, Real
    ):
        raise SpineError(
            "mean_block_groups must be a finite non-bool real scalar >= 1; "
            f"got {mean_block_groups!r}"
        )
    try:
        value = float(mean_block_groups)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpineError(
            "mean_block_groups must be a finite non-bool real scalar >= 1; "
            f"got {mean_block_groups!r}"
        ) from exc
    if not np.isfinite(value) or value < 1.0:
        raise SpineError(
            "mean_block_groups must be a finite non-bool real scalar >= 1; "
            f"got {mean_block_groups!r}"
        )
    return value


def _ordered_contiguous_group_labels(group_ids: Any) -> tuple[Hashable, ...]:
    labels = _as_opaque_group_labels(group_ids)
    ordered = [labels[0]]
    seen = {labels[0]}
    previous = labels[0]

    for row_index, label in enumerate(labels[1:], start=1):
        if label == previous:
            continue
        if label in seen:
            raise SpineError(
                "group_ids labels must occupy one contiguous row region; "
                f"label {label!r} reappears at index {row_index}"
            )
        ordered.append(label)
        seen.add(label)
        previous = label
    return tuple(ordered)


@dataclass(frozen=True)
class StationaryGroupResamplePlan:
    """Immutable whole-group stationary-resample plan."""

    ordered_group_labels: tuple[Hashable, ...]
    group_count: int
    mean_block_groups: float
    restart_probability: float
    selected_positions: tuple[int, ...]
    multiplicities: tuple[int, ...]
    block_start_flags: tuple[bool, ...]
    restart_count: int

    def __post_init__(self) -> None:
        if isinstance(self.group_count, bool) or not isinstance(
            self.group_count, int
        ):
            raise SpineError("plan group_count must be a positive integer")
        if self.group_count <= 0:
            raise SpineError("plan group_count must be a positive integer")

        sequence_fields = {
            "ordered_group_labels": self.ordered_group_labels,
            "selected_positions": self.selected_positions,
            "multiplicities": self.multiplicities,
            "block_start_flags": self.block_start_flags,
        }
        for name, sequence in sequence_fields.items():
            if not isinstance(sequence, tuple):
                raise SpineError(f"plan {name} must be an immutable tuple")
            if len(sequence) != self.group_count:
                raise SpineError(
                    f"plan {name} length must equal group_count "
                    f"{self.group_count}"
                )

        labels = _as_opaque_group_labels(self.ordered_group_labels)
        if len(set(labels)) != self.group_count:
            raise SpineError("plan ordered_group_labels must be unique")

        mean_block_groups = _validated_mean_block_groups(self.mean_block_groups)
        expected_probability = 1.0 / mean_block_groups
        if (
            isinstance(self.restart_probability, (bool, np.bool_))
            or not isinstance(self.restart_probability, Real)
            or float(self.restart_probability) != expected_probability
        ):
            raise SpineError(
                "plan restart_probability must equal 1 / mean_block_groups"
            )

        for position in self.selected_positions:
            if isinstance(position, bool) or not isinstance(position, int):
                raise SpineError("plan selected_positions must contain integers")
            if not 0 <= position < self.group_count:
                raise SpineError(
                    "plan selected_positions contains an out-of-range position"
                )

        for multiplicity in self.multiplicities:
            if isinstance(multiplicity, bool) or not isinstance(
                multiplicity, int
            ):
                raise SpineError("plan multiplicities must contain integers")
            if multiplicity < 0:
                raise SpineError("plan multiplicities must be nonnegative")
        if sum(self.multiplicities) != self.group_count:
            raise SpineError("plan multiplicities must sum to group_count")

        observed_multiplicities = tuple(
            int(value)
            for value in np.bincount(
                np.asarray(self.selected_positions, dtype=np.intp),
                minlength=self.group_count,
            )
        )
        if observed_multiplicities != self.multiplicities:
            raise SpineError(
                "plan multiplicities do not match selected_positions"
            )

        if any(type(flag) is not bool for flag in self.block_start_flags):
            raise SpineError("plan block_start_flags must contain bool values")
        if self.block_start_flags[0] is not True:
            raise SpineError("plan block_start_flags must start with True")

        expected_restart_count = sum(self.block_start_flags[1:])
        if isinstance(self.restart_count, bool) or not isinstance(
            self.restart_count, int
        ):
            raise SpineError("plan restart_count must be a nonnegative integer")
        if self.restart_count != expected_restart_count:
            raise SpineError(
                "plan restart_count must match block_start_flags after "
                "the initial occurrence"
            )


def stationary_group_resample(
    group_ids: Any,
    mean_block_groups: Any,
    rng: np.random.Generator,
) -> StationaryGroupResamplePlan:
    """Draw exactly one original group count in stationary whole-group blocks.

    The supplied ``Generator`` advances explicitly. The first RNG call is
    ``rng.integers(S)``. Each of the following ``S - 1`` transitions consumes
    one ``rng.random()`` and, only on restart, one ``rng.integers(S)``. No RNG
    call occurs after the final selected occurrence.
    """
    if not isinstance(rng, np.random.Generator):
        raise SpineError(
            "rng must be an explicitly supplied numpy.random.Generator"
        )

    ordered_labels = _ordered_contiguous_group_labels(group_ids)
    group_count = len(ordered_labels)
    mean = _validated_mean_block_groups(mean_block_groups)
    restart_probability = 1.0 / mean

    position = int(rng.integers(group_count))
    selected_positions = [position]
    block_start_flags = [True]

    for _ in range(group_count - 1):
        restart = bool(rng.random() < restart_probability)
        if restart:
            position = int(rng.integers(group_count))
        else:
            position = (position + 1) % group_count
        selected_positions.append(position)
        block_start_flags.append(restart)

    multiplicities = tuple(
        int(value)
        for value in np.bincount(
            np.asarray(selected_positions, dtype=np.intp),
            minlength=group_count,
        )
    )
    flags = tuple(block_start_flags)
    return StationaryGroupResamplePlan(
        ordered_group_labels=ordered_labels,
        group_count=group_count,
        mean_block_groups=mean,
        restart_probability=restart_probability,
        selected_positions=tuple(selected_positions),
        multiplicities=multiplicities,
        block_start_flags=flags,
        restart_count=sum(flags[1:]),
    )


def apply_group_multiplicities(
    group_ids: Any,
    baseline_weights: Any,
    plan: StationaryGroupResamplePlan,
) -> np.ndarray:
    """Compose one whole-group plan with unchanged row baseline weights.

    The returned float64 array remains aligned to the caller's rows. A group's
    integer plan multiplicity multiplies every baseline weight in that group.
    Nothing is normalized, expanded, filtered, or redrawn.
    """
    if not isinstance(plan, StationaryGroupResamplePlan):
        raise SpineError("plan must be a StationaryGroupResamplePlan")

    labels = _as_opaque_group_labels(group_ids)
    ordered_labels = _ordered_contiguous_group_labels(labels)
    if ordered_labels != plan.ordered_group_labels:
        raise SpineError(
            "group_ids ordered labels must exactly match the plan"
        )

    weights = _validated_concentration_weights(baseline_weights)
    if weights.size != len(labels):
        raise SpineError(
            "group_ids and baseline_weights must have equal length; "
            f"got {len(labels)} and {weights.size}"
        )

    if all(multiplicity == 1 for multiplicity in plan.multiplicities):
        return weights.copy()

    multiplicity_by_label = dict(
        zip(plan.ordered_group_labels, plan.multiplicities)
    )
    row_multiplicities = np.fromiter(
        (multiplicity_by_label[label] for label in labels),
        dtype=np.float64,
        count=len(labels),
    )
    with np.errstate(over="ignore", invalid="ignore"):
        composed = np.multiply(weights, row_multiplicities, dtype=np.float64)
    if not bool(np.isfinite(composed).all()):
        raise SpineError(
            "composed bootstrap weights must remain finite binary64 values"
        )
    return composed
