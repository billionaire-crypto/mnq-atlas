"""Integrated empirical registry admission for all real Phase 7 arms."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from types import MappingProxyType
from zoneinfo import ZoneInfo

import numpy as np

from mnq_lab import SpineError
from mnq_lab.conditioners.arms import ARM_CONFIGS, ArmConfig
from mnq_lab.conditioners.assignments import (
    VolRelRow,
    VolRelStatus,
    VolRelTable,
    build_assignments,
    build_thresholds,
    build_vol_rel,
)
from mnq_lab.conditioners.calendar import (
    CALENDAR_SHA256,
    CALENDAR_VERSION,
    SCHEMA_VERSION,
    CalendarRow,
    CalendarTable,
)
from mnq_lab.conditioners.pipeline import SCALE_SOURCE_ARMS
from mnq_lab.conditioners.registry import (
    ConditionerRegistry,
    NegativeControl,
    NegativeControlFailure,
    WitnessCheck,
    register_causal_conditioner,
)
from mnq_lab.conditioners.scales.ewma import ewma_rms
from mnq_lab.conditioners.scales.mad import rolling_mad
from mnq_lab.conditioners.scales.returns import (
    BAR_NS,
    CoverageRule,
    ReturnInputs,
    construct_returns,
)
from mnq_lab.conditioners.seasonal import (
    ScaleAnchorTable,
    SeasonalProfileRow,
    SeasonalProfileTable,
    SeasonalStatus,
    _profile_value,
    scale_anchor_row,
)
from mnq_lab.conditioners.semantic_masks import (
    ADMISSION_MASK_SIZES,
    semantic_mask_for_stage,
)
from mnq_lab.core.dependency import (
    DependencyCase,
    DependencyInputs,
    DeterministicWitness,
    OutputComparison,
    OutputKind,
)

__all__ = [
    "PHASE7_ADMISSION_SPECS",
    "Phase7AdmissionSpec",
    "admission_suite",
    "assert_semantic_mask_equal",
    "build_phase7_registry",
]


_CT = ZoneInfo("America/Chicago")
_FLOAT_POLICY = OutputComparison(OutputKind.FLOAT, atol=0.0, rtol=1e-12)
_INTEGER_POLICY = OutputComparison(OutputKind.INTEGER)
_BASE_FLOAT = np.asarray([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0], dtype=np.float64)
_BASE_CLOSES = np.asarray(
    10_000 + np.arange(82, dtype=np.int64) ** 2, dtype=np.int32
)
_SCALE_EXPECTED = {
    "primary_ewma78_permissive_expanding": (
        0.007279452800510302,
        0.007282684017977786,
    ),
    "coverage_strict": (0.007279452800510302, 0.007282684017977786),
    "ewma39": (0.007678095778571932, 0.007680845801713831),
    "ewma156": (0.007062095212655637, 0.007065556935241522),
    "mad78": (0.0032783389900971683, 0.003338746456796749),
}


def _readonly(values, dtype=None) -> np.ndarray:
    array = np.asarray(values, dtype=dtype)
    array.setflags(write=False)
    return array


def _weekdays(count: int) -> tuple[int, ...]:
    values: list[int] = []
    current = date(2020, 1, 2)
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current.year * 10_000 + current.month * 100 + current.day)
        current += timedelta(days=1)
    return tuple(values)


_SESSIONS = _weekdays(61)


def _calendar_row(session_id: int) -> CalendarRow:
    return CalendarRow(
        session_id,
        "CME_GLOBEX_EQUITY_INDEX_FUTURES",
        "regular",
        "full_rth",
        "08:30",
        "15:00",
        "17:00",
        "16:00",
        False,
        f"phase7-admission:{session_id}",
        "phase7-admission-fixture",
        "contract-v1",
        CALENDAR_VERSION,
        SCHEMA_VERSION,
    )


_CALENDAR = CalendarTable(tuple(_calendar_row(session) for session in _SESSIONS))


def _open_tau_ns(session_id: int) -> int:
    value = datetime.strptime(str(session_id), "%Y%m%d").date()
    tau = datetime.combine(value, time(8, 30), tzinfo=_CT)
    return int(tau.timestamp() * 1_000_000_000)


def _declared_mask(stage: str) -> np.ndarray:
    size = ADMISSION_MASK_SIZES[stage]
    mask = np.zeros(size, dtype=np.bool_)
    if stage == "scale":
        mask[1:80] = True
    elif stage in {"seasonal_profile", "thresholds"}:
        mask[0:5] = True
    elif stage in {"vol_rel", "assignment"}:
        mask[0:6] = True
    else:
        raise SpineError(f"unknown declared-mask stage {stage!r}")
    mask.setflags(write=False)
    return mask


def assert_semantic_mask_equal(stage: str, declared: np.ndarray) -> None:
    expected = semantic_mask_for_stage(stage)
    if not isinstance(declared, np.ndarray) or not np.array_equal(declared, expected):
        raise SpineError(
            f"declared {stage} mask differs from independent semantic mask"
        )


def _scale_callable(config: ArmConfig):
    coverage = CoverageRule.STRICT if config.coverage == "strict" else CoverageRule.PERMISSIVE

    def invoke(call: DependencyInputs) -> np.ndarray:
        closes = np.asarray(call.values["x"][1:80], dtype=np.int32)
        size = closes.size
        inputs = ReturnInputs(
            ts_event_ns=np.arange(size, dtype=np.int64) * np.int64(BAR_NS),
            session_id=np.full(size, 20200102, dtype=np.int32),
            symbol_code=np.zeros(size, dtype=np.int16),
            close_ticks=closes,
            expected_1m_components=np.full(size, 5, dtype=np.int8),
            observed_1m_components=np.full(size, 5, dtype=np.int8),
            rollover=np.zeros(size, dtype=np.bool_),
        )
        returns = construct_returns(inputs, coverage)
        output = (
            rolling_mad(returns)
            if config.scale_kind == "mad"
            else ewma_rms(returns, int(config.halflife))
        )
        if not output.valid[-1]:
            raise SpineError("admission scale witness did not reach defined output")
        return np.asarray(output.values[-1], dtype=np.float64)

    invoke.__name__ = f"admit_scale_{config.arm_id}"
    return invoke


def _profile_from_values(values: np.ndarray) -> tuple:
    return _profile_value(
        tuple(float(value) for value in values[:3]),
        tuple(float(value) for value in values[3:5]),
        60,
    )


def _seasonal_callable(arm_id: str):
    def invoke(call: DependencyInputs) -> np.ndarray:
        calculated = _profile_from_values(call.values["x"])
        if not calculated[6]:
            raise SpineError("admission seasonal profile is unexpectedly undefined")
        return np.asarray(calculated[5], dtype=np.float64)

    invoke.__name__ = f"admit_seasonal_{arm_id}"
    return invoke


def _scale_and_profile(values: np.ndarray, arm_id: str):
    tau = _open_tau_ns(_SESSIONS[-1])
    calculated = _profile_from_values(values)
    scales = ScaleAnchorTable(
        arm_id,
        (
            scale_anchor_row(
                arm_id=arm_id,
                session_id=_SESSIONS[-1],
                ts_event_ns=tau - int(BAR_NS),
                scale_stage="mad" if arm_id == "mad78" else "ewma",
                scale_value=float(values[5]),
                scale_valid=True,
            ),
        ),
    )
    profiles = SeasonalProfileTable(
        arm_id,
        (
            SeasonalProfileRow(
                arm_id,
                _SESSIONS[-1],
                "08:30",
                "open",
                60,
                3,
                float(calculated[0]),
                True,
                float(calculated[2]),
                True,
                float(calculated[4]),
                float(calculated[5]),
                True,
                SeasonalStatus.OK,
                CALENDAR_VERSION,
                CALENDAR_SHA256,
                tuple((_SESSIONS[index], "08:30") for index in range(5)),
            ),
        ),
    )
    return scales, profiles


def _vol_rel_callable(arm_id: str):
    def invoke(call: DependencyInputs) -> np.ndarray:
        scales, profiles = _scale_and_profile(call.values["x"], arm_id)
        result = build_vol_rel(scales, profiles).rows[0]
        if not result.vol_rel_valid:
            raise SpineError("admission vol_rel is unexpectedly undefined")
        return np.asarray(result.vol_rel, dtype=np.float64)

    invoke.__name__ = f"admit_vol_rel_{arm_id}"
    return invoke


def _vol_row(session_id: int, tau_ns: int, value: float, arm_id: str) -> VolRelRow:
    return VolRelRow(
        arm_id,
        session_id,
        tau_ns - int(BAR_NS),
        tau_ns,
        "08:30",
        "open",
        float(value),
        True,
        1.0,
        True,
        float(value),
        True,
        VolRelStatus.OK,
        None,
        "ok",
    )


def _threshold_inputs(values: np.ndarray, source_arm: str) -> VolRelTable:
    rows = tuple(
        _vol_row(
            session,
            _open_tau_ns(session),
            float(values[index % 5]),
            source_arm,
        )
        for index, session in enumerate(_SESSIONS[:60])
    )
    return VolRelTable(source_arm, rows)


def _source_arm(config: ArmConfig) -> str:
    return (
        "primary_ewma78_permissive_expanding"
        if config.arm_id.startswith("threshold_")
        else config.arm_id
    )


def _threshold_callable(config: ArmConfig):
    source_arm = _source_arm(config)

    def invoke(call: DependencyInputs) -> np.ndarray:
        history = _threshold_inputs(call.values["x"], source_arm)
        table = build_thresholds(
            config,
            history,
            (_SESSIONS[-1],),
            frozenset(_SESSIONS[:60]),
            _CALENDAR,
        )
        row = table.lookup(_SESSIONS[-1], "open")
        if not row.threshold_valid:
            raise SpineError("admission thresholds are unexpectedly undefined")
        return np.asarray(
            [row.lower_threshold, row.upper_threshold], dtype=np.float64
        )

    invoke.__name__ = f"admit_thresholds_{config.arm_id}"
    return invoke


def _assignment_callable(config: ArmConfig):
    source_arm = _source_arm(config)

    def invoke(call: DependencyInputs) -> np.ndarray:
        history = _threshold_inputs(call.values["x"], source_arm)
        thresholds = build_thresholds(
            config,
            history,
            (_SESSIONS[-1],),
            frozenset(_SESSIONS[:60]),
            _CALENDAR,
        )
        current_tau = _open_tau_ns(_SESSIONS[-1])
        current = VolRelTable(
            source_arm,
            (_vol_row(_SESSIONS[-1], current_tau, float(call.values["x"][5]), source_arm),),
        )
        row = build_assignments(config, current, thresholds, _CALENDAR).rows[0]
        return np.asarray(row.category_code, dtype=np.int64)

    invoke.__name__ = f"admit_assignment_{config.arm_id}"
    return invoke


@dataclass(frozen=True)
class Phase7AdmissionSpec:
    stage: str
    config: ArmConfig
    invoke: object
    declared_mask: np.ndarray
    comparison: OutputComparison
    expected_baseline: np.ndarray
    expected_changed: np.ndarray
    baseline_inputs: np.ndarray
    changed_inputs: np.ndarray

    @property
    def identifier(self) -> str:
        return f"mnq.phase7.{self.stage}.{self.config.arm_id}.v1"


def _threshold_expected(config: ArmConfig, multiplier: float) -> np.ndarray:
    # All five frozen probability pairs select the second and fourth order
    # statistics on the hand-built five-value witness.
    return _readonly([2.0 * multiplier, 4.0 * multiplier], np.float64)


def _specs() -> tuple[Phase7AdmissionSpec, ...]:
    by_id = {config.arm_id: config for config in ARM_CONFIGS}
    output: list[Phase7AdmissionSpec] = []
    for arm_id in SCALE_SOURCE_ARMS:
        config = by_id[arm_id]
        baseline, changed = _SCALE_EXPECTED[arm_id]
        changed_closes = _BASE_CLOSES.copy()
        changed_closes[40] += 17
        output.append(
            Phase7AdmissionSpec(
                "scale",
                config,
                _scale_callable(config),
                _declared_mask("scale"),
                _FLOAT_POLICY,
                _readonly(baseline, np.float64),
                _readonly(changed, np.float64),
                _readonly(_BASE_CLOSES, np.int32),
                _readonly(changed_closes, np.int32),
            )
        )
    for arm_id in SCALE_SOURCE_ARMS:
        config = by_id[arm_id]
        changed = _BASE_FLOAT.copy()
        changed[1] = 10.0
        output.append(
            Phase7AdmissionSpec(
                "seasonal_profile",
                config,
                _seasonal_callable(arm_id),
                _declared_mask("seasonal_profile"),
                _FLOAT_POLICY,
                _readonly(42.0 / 11.0, np.float64),
                _readonly(43.0 / 11.0, np.float64),
                _readonly(_BASE_FLOAT, np.float64),
                _readonly(changed, np.float64),
            )
        )
    for arm_id in SCALE_SOURCE_ARMS:
        config = by_id[arm_id]
        changed = _BASE_FLOAT.copy()
        changed[5] = 12.0
        output.append(
            Phase7AdmissionSpec(
                "vol_rel",
                config,
                _vol_rel_callable(arm_id),
                _declared_mask("vol_rel"),
                _FLOAT_POLICY,
                _readonly(11.0 / 7.0, np.float64),
                _readonly(22.0 / 7.0, np.float64),
                _readonly(_BASE_FLOAT, np.float64),
                _readonly(changed, np.float64),
            )
        )
    for config in ARM_CONFIGS:
        changed = _BASE_FLOAT.copy()
        changed[:5] *= 2.0
        output.append(
            Phase7AdmissionSpec(
                "thresholds",
                config,
                _threshold_callable(config),
                _declared_mask("thresholds"),
                _FLOAT_POLICY,
                _threshold_expected(config, 1.0),
                _threshold_expected(config, 2.0),
                _readonly(_BASE_FLOAT, np.float64),
                _readonly(changed, np.float64),
            )
        )
    for config in ARM_CONFIGS:
        changed = _BASE_FLOAT.copy()
        changed[5] = 0.5
        output.append(
            Phase7AdmissionSpec(
                "assignment",
                config,
                _assignment_callable(config),
                _declared_mask("assignment"),
                _INTEGER_POLICY,
                _readonly(2, np.int64),
                _readonly(0, np.int64),
                _readonly(_BASE_FLOAT, np.float64),
                _readonly(changed, np.float64),
            )
        )
    return tuple(output)


PHASE7_ADMISSION_SPECS = _specs()


def _future_read(kind: OutputKind):
    def invoke(call: DependencyInputs) -> np.ndarray:
        value = call.values["x"][-1]
        if kind is OutputKind.INTEGER:
            return np.asarray(int(value), dtype=np.int64)
        return np.asarray(float(value), dtype=np.float64)

    return invoke


def admission_suite(spec: Phase7AdmissionSpec):
    assert_semantic_mask_equal(spec.stage, spec.declared_mask)
    size = spec.baseline_inputs.size
    case = DependencyCase(
        name=spec.identifier,
        coordinates_ns=_readonly(np.arange(size, dtype=np.int64) + 1, np.int64),
        allowed_dependency_mask=_readonly(spec.declared_mask, np.bool_),
        inputs={"x": _readonly(spec.baseline_inputs, spec.baseline_inputs.dtype)},
        invoke=spec.invoke,
        comparison=spec.comparison,
    )
    witness = DeterministicWitness(
        name=f"{spec.identifier}.witness",
        changed_inputs={"x": _readonly(spec.changed_inputs, spec.changed_inputs.dtype)},
        expected_baseline=_readonly(spec.expected_baseline, spec.expected_baseline.dtype),
        expected_changed=_readonly(spec.expected_changed, spec.expected_changed.dtype),
        affected_output_index=(0,) if spec.expected_baseline.ndim else (),
    )
    locality_negative = NegativeControl(
        name=f"{spec.identifier}.future_read",
        failure=NegativeControlFailure.LOCALITY_OUTPUT_CHANGE,
        case=DependencyCase(
            name=f"{spec.identifier}.future_read",
            coordinates_ns=_readonly(np.arange(size, dtype=np.int64) + 1, np.int64),
            allowed_dependency_mask=_readonly(spec.declared_mask, np.bool_),
            inputs={"x": _readonly(spec.baseline_inputs, spec.baseline_inputs.dtype)},
            invoke=_future_read(spec.comparison.kind),
            comparison=spec.comparison,
        ),
    )
    wrong = np.array(spec.expected_changed, copy=True)
    wrong.flat[0] = (
        wrong.flat[0] + 1
        if spec.comparison.kind is OutputKind.INTEGER
        else wrong.flat[0] + max(1.0, abs(float(wrong.flat[0]))) * 1e-3
    )
    wrong.setflags(write=False)
    witness_negative = NegativeControl(
        name=f"{spec.identifier}.wrong_witness",
        failure=NegativeControlFailure.WITNESS_CHANGED_OUTPUT,
        case=case,
        witness=DeterministicWitness(
            name=f"{spec.identifier}.wrong_witness",
            changed_inputs={"x": _readonly(spec.changed_inputs, spec.changed_inputs.dtype)},
            expected_baseline=_readonly(spec.expected_baseline, spec.expected_baseline.dtype),
            expected_changed=wrong,
            affected_output_index=(0,) if spec.expected_baseline.ndim else (),
        ),
    )
    return case, WitnessCheck(case, witness), (locality_negative, witness_negative)


def _sensitivity(config: ArmConfig) -> tuple[str, str]:
    if config.arm_id == "primary_ewma78_permissive_expanding":
        return "reference", "primary"
    if config.arm_id == "coverage_strict":
        return "component_coverage", "strict"
    if config.arm_id in {"ewma39", "ewma156"}:
        return "ewma_halflife", str(config.halflife)
    if config.arm_id == "mad78":
        return "scale_estimator", "mad78"
    if config.arm_id == "threshold_rolling60":
        return "threshold_history", "rolling60"
    return "threshold_probability_shift", config.arm_id.rsplit("_", 1)[-1]


def _metadata(spec: Phase7AdmissionSpec) -> MappingProxyType:
    factor, value = _sensitivity(spec.config)
    return MappingProxyType(
        {
            "stage": spec.stage,
            "arm_id": spec.config.arm_id,
            "arm_order": spec.config.order,
            "estimator_kind": spec.config.scale_kind,
            "halflife": spec.config.halflife,
            "mad_window": 78 if spec.config.scale_kind == "mad" else None,
            "coverage_rule": spec.config.coverage,
            "warmup": 78 if spec.stage == "scale" else 60,
            "bucket_timezone": "America/Chicago",
            "calendar_version": None if spec.stage == "scale" else CALENDAR_VERSION,
            "calendar_sha256": None if spec.stage == "scale" else CALENDAR_SHA256,
            "threshold_history": spec.config.history_kind,
            "lower_probability": spec.config.lower_probability,
            "upper_probability": spec.config.upper_probability,
            "semantic_mask_version": "phase7-bars-and-rows-v1",
            "output_kind": spec.comparison.kind.value,
            "atol": spec.comparison.atol,
            "rtol": spec.comparison.rtol,
            "sensitivity_factor": factor,
            "sensitivity_value": value,
        }
    )


def build_phase7_registry() -> ConditionerRegistry:
    registry = ConditionerRegistry()
    for spec in PHASE7_ADMISSION_SPECS:
        case, witness, controls = admission_suite(spec)
        register_causal_conditioner(
            registry,
            spec.identifier,
            spec.invoke,
            metadata=_metadata(spec),
            locality_cases=(case,),
            witness_checks=(witness,),
            negative_controls=controls,
        )
    return registry
