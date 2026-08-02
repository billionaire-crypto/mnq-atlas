"""Closed Phase 7 conditioner status vocabularies.

Missingness receives a status; structural corruption raises ``SpineError``.
This module is market-aware vocabulary only.  It performs no scale, calendar,
threshold, assignment, or outcome computation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from mnq_lab import SpineError

__all__ = [
    "AnchorStatus",
    "AssignmentStatus",
    "ConditionerStatuses",
    "EwmaStatus",
    "MadStatus",
    "ResetReason",
    "ReturnMissingReason",
    "ReturnStatus",
    "SeasonalStatus",
    "ThresholdStatus",
    "UpstreamStage",
    "VolRelStatus",
]


class _ClosedStatus(str, Enum):
    """String-valued enum whose members are the complete public vocabulary."""


class AnchorStatus(_ClosedStatus):
    OK = "ok"
    ANCHOR_BAR_MISSING = "anchor_bar_missing"


class ReturnStatus(_ClosedStatus):
    OK = "ok"
    MISSING_RETURN = "missing_return"


class ReturnMissingReason(_ClosedStatus):
    BAR_ABSENT = "bar_absent"
    INSUFFICIENT_COMPONENTS = "insufficient_components"
    SPACING_BREAK = "spacing_break"
    SYMBOL_CHANGE = "symbol_change"


class ResetReason(_ClosedStatus):
    NONE = "none"
    ROLL_RESET = "roll_reset"
    GAP_RESET = "gap_reset"


class EwmaStatus(_ClosedStatus):
    OK = "ok"
    WARMUP = "warmup"


class MadStatus(_ClosedStatus):
    OK = "ok"
    WARMUP = "warmup"
    ZERO_SCALE = "zero_scale"


class SeasonalStatus(_ClosedStatus):
    OK = "ok"
    WARMUP = "warmup"
    SEASONAL_FALLBACK_UNAVAILABLE = "seasonal_fallback_unavailable"
    CALENDAR_CLASSIFICATION_MISSING = "calendar_classification_missing"


class VolRelStatus(_ClosedStatus):
    OK = "ok"
    ZERO_SCALE = "zero_scale"
    UPSTREAM_UNDEFINED = "upstream_undefined"


class UpstreamStage(_ClosedStatus):
    EWMA = "ewma"
    MAD = "mad"
    SEASONAL = "seasonal"


class ThresholdStatus(_ClosedStatus):
    OK = "ok"
    INSUFFICIENT_THRESHOLD_HISTORY = "insufficient_threshold_history"
    DEGENERATE_BOUNDARIES = "degenerate_boundaries"


class AssignmentStatus(_ClosedStatus):
    OK = "ok"
    WARMUP = "warmup"
    UPSTREAM_UNDEFINED = "upstream_undefined"


def _member(value, enum_type: type[_ClosedStatus], field: str):
    if not isinstance(value, enum_type):
        raise SpineError(f"{field} must be a {enum_type.__name__}; got {value!r}")
    return value


def _optional_member(value, enum_type: type[_ClosedStatus], field: str):
    if value is not None:
        _member(value, enum_type, field)
    return value


@dataclass(frozen=True)
class ConditionerStatuses:
    """One total, validated combination of all Phase 7 stage statuses.

    Later stages may be ``None`` before they are evaluated.  Once supplied,
    their own closed-vocabulary and companion-field rules apply immediately.
    """

    anchor_status: AnchorStatus
    return_status: ReturnStatus
    return_missing_reason: ReturnMissingReason | None
    reset_reason: ResetReason
    scheduled_break: bool
    ewma_status: EwmaStatus | None = None
    mad_status: MadStatus | None = None
    seasonal_status: SeasonalStatus | None = None
    vol_rel_status: VolRelStatus | None = None
    upstream_stage: UpstreamStage | None = None
    threshold_status: ThresholdStatus | None = None
    assignment_status: AssignmentStatus | None = None

    def __post_init__(self) -> None:
        anchor = _member(self.anchor_status, AnchorStatus, "anchor_status")
        returned = _member(self.return_status, ReturnStatus, "return_status")
        reason = _optional_member(
            self.return_missing_reason,
            ReturnMissingReason,
            "return_missing_reason",
        )
        reset = _member(self.reset_reason, ResetReason, "reset_reason")
        if not isinstance(self.scheduled_break, bool):
            raise SpineError("scheduled_break must be bool")

        for field, enum_type in (
            ("ewma_status", EwmaStatus),
            ("mad_status", MadStatus),
            ("seasonal_status", SeasonalStatus),
            ("vol_rel_status", VolRelStatus),
            ("upstream_stage", UpstreamStage),
            ("threshold_status", ThresholdStatus),
            ("assignment_status", AssignmentStatus),
        ):
            _optional_member(getattr(self, field), enum_type, field)

        if returned is ReturnStatus.OK:
            if reason is not None or reset is not ResetReason.NONE:
                raise SpineError("ok return requires no missing reason and no reset")
            if self.scheduled_break:
                raise SpineError("ok return cannot be a scheduled break")
        else:
            if reason is None:
                raise SpineError("missing_return requires return_missing_reason")
            expected_reset = (
                ResetReason.ROLL_RESET
                if reason is ReturnMissingReason.SYMBOL_CHANGE
                else ResetReason.GAP_RESET
            )
            if reset is not expected_reset:
                raise SpineError(
                    f"{reason.value} requires reset_reason={expected_reset.value}"
                )

        if anchor is AnchorStatus.ANCHOR_BAR_MISSING:
            if (
                returned is not ReturnStatus.MISSING_RETURN
                or reason is not ReturnMissingReason.BAR_ABSENT
            ):
                raise SpineError(
                    "anchor_bar_missing requires missing_return/bar_absent"
                )
        elif reason is ReturnMissingReason.BAR_ABSENT:
            raise SpineError("bar_absent is reserved for anchor_bar_missing")

        if self.scheduled_break and not (
            reset is ResetReason.GAP_RESET
            and reason is ReturnMissingReason.SPACING_BREAK
        ):
            raise SpineError(
                "scheduled_break requires gap_reset with spacing_break"
            )

        if self.vol_rel_status is VolRelStatus.UPSTREAM_UNDEFINED:
            if self.upstream_stage is None:
                raise SpineError(
                    "vol_rel upstream_undefined requires upstream_stage"
                )
        elif self.upstream_stage is not None:
            raise SpineError(
                "upstream_stage is permitted only for vol_rel upstream_undefined"
            )

