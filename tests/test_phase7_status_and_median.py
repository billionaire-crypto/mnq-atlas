"""Contract-first tests for the Phase 7 status and median foundation."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.conditioners.scales.median import (
    calendar_isolation_probe,
    lower_median,
)
from mnq_lab.conditioners.status import (
    AnchorStatus,
    AssignmentStatus,
    ConditionerStatuses,
    EwmaStatus,
    MadStatus,
    ResetReason,
    ReturnMissingReason,
    ReturnStatus,
    SeasonalStatus,
    ThresholdStatus,
    UpstreamStage,
    VolRelStatus,
)


def _values(enum_type) -> set[str]:
    return {member.value for member in enum_type}


def _ok() -> ConditionerStatuses:
    return ConditionerStatuses(
        anchor_status=AnchorStatus.OK,
        return_status=ReturnStatus.OK,
        return_missing_reason=None,
        reset_reason=ResetReason.NONE,
        scheduled_break=False,
    )


def test_status_vocabularies_are_exactly_the_preregistered_closed_sets():
    assert _values(AnchorStatus) == {"ok", "anchor_bar_missing"}
    assert _values(ReturnStatus) == {"ok", "missing_return"}
    assert _values(ReturnMissingReason) == {
        "bar_absent",
        "insufficient_components",
        "spacing_break",
        "symbol_change",
    }
    assert _values(ResetReason) == {"none", "roll_reset", "gap_reset"}
    assert _values(EwmaStatus) == {"ok", "warmup"}
    assert _values(MadStatus) == {"ok", "warmup", "zero_scale"}
    assert _values(SeasonalStatus) == {
        "ok",
        "warmup",
        "seasonal_fallback_unavailable",
        "calendar_classification_missing",
    }
    assert _values(VolRelStatus) == {"ok", "zero_scale", "upstream_undefined"}
    assert _values(ThresholdStatus) == {
        "ok",
        "insufficient_threshold_history",
        "degenerate_boundaries",
    }
    assert _values(AssignmentStatus) == {"ok", "warmup", "upstream_undefined"}

    with pytest.raises(ValueError, match="not-a-status"):
        ReturnStatus("not-a-status")


def test_status_companions_form_total_fail_closed_combinations():
    assert _ok().return_status is ReturnStatus.OK
    absent = ConditionerStatuses(
        anchor_status=AnchorStatus.ANCHOR_BAR_MISSING,
        return_status=ReturnStatus.MISSING_RETURN,
        return_missing_reason=ReturnMissingReason.BAR_ABSENT,
        reset_reason=ResetReason.GAP_RESET,
        scheduled_break=False,
    )
    assert absent.anchor_status is AnchorStatus.ANCHOR_BAR_MISSING
    scheduled = ConditionerStatuses(
        anchor_status=AnchorStatus.OK,
        return_status=ReturnStatus.MISSING_RETURN,
        return_missing_reason=ReturnMissingReason.SPACING_BREAK,
        reset_reason=ResetReason.GAP_RESET,
        scheduled_break=True,
    )
    assert scheduled.scheduled_break is True
    propagated = replace(
        _ok(),
        vol_rel_status=VolRelStatus.UPSTREAM_UNDEFINED,
        upstream_stage=UpstreamStage.SEASONAL,
    )
    assert propagated.upstream_stage is UpstreamStage.SEASONAL

    invalid = (
        {"return_status": ReturnStatus.OK, "return_missing_reason": ReturnMissingReason.SPACING_BREAK},
        {"return_status": ReturnStatus.MISSING_RETURN, "return_missing_reason": None},
        {"return_status": ReturnStatus.MISSING_RETURN, "return_missing_reason": ReturnMissingReason.SYMBOL_CHANGE, "reset_reason": ResetReason.GAP_RESET},
        {"return_status": ReturnStatus.MISSING_RETURN, "return_missing_reason": ReturnMissingReason.SPACING_BREAK, "reset_reason": ResetReason.ROLL_RESET},
        {"anchor_status": AnchorStatus.OK, "return_status": ReturnStatus.MISSING_RETURN, "return_missing_reason": ReturnMissingReason.BAR_ABSENT, "reset_reason": ResetReason.GAP_RESET},
        {"scheduled_break": True},
        {"vol_rel_status": VolRelStatus.UPSTREAM_UNDEFINED},
        {"vol_rel_status": VolRelStatus.OK, "upstream_stage": UpstreamStage.EWMA},
        {"anchor_status": "ok"},
    )
    for mutation in invalid:
        with pytest.raises(SpineError):
            replace(_ok(), **mutation)


def test_lower_median_uses_frozen_inverted_cdf_without_mutation():
    even = np.asarray([100.0, 4.0, 1.0, 3.0], dtype=np.float64)
    before = even.copy()
    assert lower_median(even) == 3.0
    assert np.array_equal(even, before)
    assert lower_median(np.asarray([9, 1, 5], dtype=np.int32)) == 5.0
    assert calendar_isolation_probe() == 2.0

    # The forbidden averaged-median mutation is discriminating on this fixture.
    assert float(np.median(even)) == 3.5
    assert float(np.median(even)) != lower_median(even)


@pytest.mark.parametrize(
    "bad",
    [
        np.asarray([], dtype=np.float64),
        np.asarray([[1.0]], dtype=np.float64),
        np.asarray([True, False], dtype=np.bool_),
        np.asarray([1.0, np.nan], dtype=np.float64),
        np.asarray([1.0, np.inf], dtype=np.float64),
        np.asarray(["1", "2"], dtype="U1"),
    ],
)
def test_lower_median_rejects_inputs_that_cannot_define_a_scale(bad):
    with pytest.raises(SpineError):
        lower_median(bad)
