"""D31/D32 structural-denominator controls for Phase 8 completion."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.phase8 import production as production_module
from mnq_lab.phase8.production import (
    ArmFrame,
    ProductionInputs,
    _cached_structural_completion_eligibility,
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


def _cache_key_case() -> tuple[ProductionInputs, dict[str, ArmFrame]]:
    sessions = np.asarray([20200102, 20200103], dtype=np.int32)
    timestamps = np.asarray([1, 2], dtype=np.int64)
    records = (
        ("path-a", 15, (True, False)),
        ("path-a", 60, (False, True)),
        ("path-b", 15, (False, True)),
        ("path-b", 60, (True, False)),
    )
    unit = {
        "estimand": np.asarray([
            path for path, _horizon, _fit in records for _ in sessions
        ]),
        "session_id": np.concatenate(tuple(sessions for _ in records)),
        "ts_event_ns": np.concatenate(tuple(timestamps for _ in records)),
        "horizon_minutes": np.asarray([
            horizon for _path, horizon, _fit in records for _ in sessions
        ], dtype=np.int16),
        "window_fits_rth": np.asarray([
            value for _path, _horizon, fit in records for value in fit
        ], dtype=np.bool_),
        "outcome_valid": np.ones(8, dtype=np.bool_),
        "common_support": np.ones(8, dtype=np.bool_),
    }

    def arm(arm_id: str, active: tuple[bool, bool]) -> ArmFrame:
        return ArmFrame(
            arm_id=arm_id, sessions=sessions, timestamps=timestamps,
            phases=np.asarray(["open", "open"]),
            states=np.asarray(["state", "state"]),
            active=np.asarray(active, dtype=np.bool_),
            session_class=np.asarray(["regular", "regular"]),
            data_quality=np.asarray(["ok", "ok"]),
            holiday_adjacent=np.zeros(2, dtype=np.bool_),
            category_code=np.zeros(2, dtype=np.int16),
        )

    arms = {"arm-a": arm("arm-a", (True, True)), "arm-b": arm("arm-b", (False, True))}
    return ProductionInputs(
        root=Path("."), unit=unit, arms=arms,
        run_manifest={}, unit_manifest={}, phase7_manifest={},
        input_manifest_sha256=(),
    ), arms


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


@pytest.mark.parametrize(
    "mutation",
    ("arm_id", "path_estimand", "support_kind", "horizon_minutes"),
)
def test_structural_denominator_cache_key_uses_every_component(
    monkeypatch, mutation,
):
    inputs, arms = _cache_key_case()
    real = production_module._structural_completion_eligibility
    calls: list[tuple[str, str, str, int]] = []

    def counted(
        *args, arm, path_estimand, support_kind, horizon_minutes, **kwargs
    ):
        calls.append((arm.arm_id, path_estimand, support_kind, horizon_minutes))
        return real(
            *args, arm=arm, path_estimand=path_estimand,
            support_kind=support_kind, horizon_minutes=horizon_minutes, **kwargs,
        )

    monkeypatch.setattr(
        production_module, "_structural_completion_eligibility", counted
    )
    slices: dict[tuple[str, int], tuple[np.ndarray, ...]] = {}
    eligibility: dict[tuple[str, str, str, int], np.ndarray] = {}
    base = {
        "arm": arms["arm-a"], "path_estimand": "path-a",
        "support_kind": "horizon_specific", "horizon_minutes": 15,
    }
    first = _cached_structural_completion_eligibility(
        slices, eligibility, inputs, **base,
    )
    repeated = _cached_structural_completion_eligibility(
        slices, eligibility, inputs, **base,
    )
    changed = dict(base)
    changed.update({
        "arm_id": {"arm": arms["arm-b"]},
        "path_estimand": {"path_estimand": "path-b"},
        "support_kind": {"support_kind": "common_support"},
        "horizon_minutes": {"horizon_minutes": 60},
    }[mutation])
    mutated = _cached_structural_completion_eligibility(
        slices, eligibility, inputs, **changed,
    )

    assert repeated is first
    assert first.flags.writeable is False
    assert mutated.flags.writeable is False
    assert len(calls) == 2
    assert calls[0] != calls[1]
    np.testing.assert_array_equal(first, [True, False])
    assert not np.array_equal(first, mutated)
    # Negative control: a cache key missing the parameter under test aliases
    # these two detectably different masks.
    incomplete = tuple(
        value for index, value in enumerate(calls[0])
        if index != {
            "arm_id": 0, "path_estimand": 1,
            "support_kind": 2, "horizon_minutes": 3,
        }[mutation]
    )
    assert incomplete == tuple(
        value for index, value in enumerate(calls[1])
        if index != {
            "arm_id": 0, "path_estimand": 1,
            "support_kind": 2, "horizon_minutes": 3,
        }[mutation]
    )
    assert not np.array_equal(first, mutated)
