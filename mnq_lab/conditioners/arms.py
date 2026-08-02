"""Immutable Phase 7 one-factor-at-a-time conditioner arm inventory."""

from __future__ import annotations

from dataclasses import dataclass

from mnq_lab import SpineError

__all__ = ["ARM_CONFIGS", "ArmConfig", "arm_config"]


@dataclass(frozen=True)
class ArmConfig:
    order: int
    arm_id: str
    scale_kind: str
    coverage: str
    halflife: int | None
    history_kind: str
    lower_probability: float
    upper_probability: float

    def __post_init__(self) -> None:
        if self.scale_kind not in {"ewma", "mad"}:
            raise SpineError("arm scale_kind must be ewma or mad")
        if self.coverage not in {"permissive", "strict"}:
            raise SpineError("arm coverage must be permissive or strict")
        if self.history_kind not in {"expanding", "rolling60"}:
            raise SpineError("arm history_kind must be expanding or rolling60")
        if not 0.0 < self.lower_probability < self.upper_probability < 1.0:
            raise SpineError("arm probabilities must be strictly ordered inside (0,1)")


_ONE_THIRD = 1.0 / 3.0
_TWO_THIRDS = 2.0 / 3.0

ARM_CONFIGS = (
    ArmConfig(0, "primary_ewma78_permissive_expanding", "ewma", "permissive", 78, "expanding", _ONE_THIRD, _TWO_THIRDS),
    ArmConfig(1, "coverage_strict", "ewma", "strict", 78, "expanding", _ONE_THIRD, _TWO_THIRDS),
    ArmConfig(2, "ewma39", "ewma", "permissive", 39, "expanding", _ONE_THIRD, _TWO_THIRDS),
    ArmConfig(3, "ewma156", "ewma", "permissive", 156, "expanding", _ONE_THIRD, _TWO_THIRDS),
    ArmConfig(4, "mad78", "mad", "permissive", None, "expanding", _ONE_THIRD, _TWO_THIRDS),
    ArmConfig(5, "threshold_rolling60", "ewma", "permissive", 78, "rolling60", _ONE_THIRD, _TWO_THIRDS),
    ArmConfig(6, "threshold_shift_m05", "ewma", "permissive", 78, "expanding", _ONE_THIRD - 0.05, _TWO_THIRDS - 0.05),
    ArmConfig(7, "threshold_shift_m02", "ewma", "permissive", 78, "expanding", _ONE_THIRD - 0.02, _TWO_THIRDS - 0.02),
    ArmConfig(8, "threshold_shift_p02", "ewma", "permissive", 78, "expanding", _ONE_THIRD + 0.02, _TWO_THIRDS + 0.02),
    ArmConfig(9, "threshold_shift_p05", "ewma", "permissive", 78, "expanding", _ONE_THIRD + 0.05, _TWO_THIRDS + 0.05),
)

_BY_ID = {config.arm_id: config for config in ARM_CONFIGS}


def arm_config(arm_id: str) -> ArmConfig:
    try:
        return _BY_ID[arm_id]
    except KeyError as exc:
        raise SpineError(f"unknown Phase 7 arm_id {arm_id!r}") from exc
