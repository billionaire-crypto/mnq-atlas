"""D31/D32 structural-denominator controls for Phase 8 completion."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.phase8.production import (
    ArmFrame,
    ProductionInputs,
    _structural_completion_eligibility,
)


def _case(*, support_sessions: np.ndarray | None = None) -> tuple[ProductionInputs, ArmFrame]:
    sessions = np.asarray([20200102, 20200103], dtype=np.int32)
    support = sessions if support_sessions is None else support_sessions
    unit = {
        "estimand": np.asarray(["path", "path", "path", "path"]),
        "session_id": np.concatenate((sessions, support)),
        "ts_event_ns": np.asarray([1, 2, 1, 2], dtype=np.int64),
        "horizon_minutes": np.asarray([15, 15, 60, 60], dtype=np.int16),
        "window_fits_rth": np.asarray([True, False, False, True]),
        "outcome_valid": np.ones(4, dtype=np.bool_),
        "common_support": np.ones(4, dtype=np.bool_),
    }
    arm = ArmFrame(
        arm_id="arm",
        sessions=sessions,
        timestamps=np.asarray([1, 2], dtype=np.int64),
        phases=np.asarray(["open", "open"]),
        states=np.asarray(["state", "state"]),
        active=np.ones(2, dtype=np.bool_),
        session_class=np.asarray(["regular", "regular"]),
        data_quality=np.asarray(["ok", "ok"]),
        holiday_adjacent=np.zeros(2, dtype=np.bool_),
        category_code=np.zeros(2, dtype=np.int16),
    )
    inputs = ProductionInputs(
        root=Path("."), unit=unit, arms={"arm": arm},
        run_manifest={}, unit_manifest={}, phase7_manifest={},
        input_manifest_sha256=(),
    )
    return inputs, arm


def test_horizon_specific_denominator_requires_named_window_to_fit():
    inputs, arm = _case()
    result = _structural_completion_eligibility(
        {}, inputs, arm=arm, path_estimand="path",
        support_kind="horizon_specific", horizon_minutes=15,
    )
    np.testing.assert_array_equal(result, [True, False])
    # Negative control: arm.active alone would incorrectly retain row two.
    assert not np.array_equal(result, arm.active)


def test_common_support_denominator_uses_aligned_sixty_minute_fit():
    inputs, arm = _case()
    result = _structural_completion_eligibility(
        {}, inputs, arm=arm, path_estimand="path",
        support_kind="common_support", horizon_minutes=15,
    )
    np.testing.assert_array_equal(result, [False, True])
    # Negative control: the named 15-minute fit is the opposite mask.
    assert not np.array_equal(result, inputs.unit["window_fits_rth"][:2])


def test_common_support_denominator_rejects_misaligned_sixty_minute_keys():
    inputs, arm = _case(
        support_sessions=np.asarray([20200102, 20200104], dtype=np.int32)
    )
    with pytest.raises(SpineError, match="60-minute structural-support keys differ"):
        _structural_completion_eligibility(
            {}, inputs, arm=arm, path_estimand="path",
            support_kind="common_support", horizon_minutes=15,
        )


def test_structural_denominator_rejects_unknown_support_kind():
    inputs, arm = _case()
    with pytest.raises(SpineError, match="unknown support kind"):
        _structural_completion_eligibility(
            {}, inputs, arm=arm, path_estimand="path",
            support_kind="invented", horizon_minutes=15,
        )
