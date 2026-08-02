"""Descriptive-only Phase 7 state-validity panel."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from mnq_lab import SpineError
from mnq_lab.conditioners.arms import ARM_CONFIGS
from mnq_lab.conditioners.assignments import (
    CATEGORY_ORDER,
    AssignmentRow,
    AssignmentStatus,
    AssignmentTable,
)
from mnq_lab.conditioners.pipeline import Phase7ConditionerPipeline
from mnq_lab.conditioners.scales.returns import BAR_NS
from mnq_lab.conditioners.scales.median import lower_median
from mnq_lab.spine.timemodel import TimeModel

__all__ = [
    "METRIC_ORDER",
    "NON_OK_STATUS_ORDER",
    "ArmStateDiagnostic",
    "StateAnchorDiagnostic",
    "StateValidityPanel",
    "StateValidityRow",
    "average_rank_spearman",
    "build_state_validity_panel",
]


METRIC_ORDER = (
    "category_frequency",
    "average_run_length",
    "transition_entropy",
    "cell_migration",
    "threshold_drift",
    "raw_volatility_correlation",
    "missingness_completion_correlation",
    "liquidity_era_correlation",
    "undefined_warmup_fraction",
)
PHASE_ORDER = tuple(TimeModel.from_constants().phase_names)
NON_OK_STATUS_ORDER = (
    "anchor_bar_missing",
    "missing_return",
    "roll_reset",
    "gap_reset",
    "ewma_warmup",
    "mad_warmup",
    "mad_zero_scale",
    "seasonal_warmup",
    "seasonal_fallback_unavailable",
    "calendar_classification_missing",
    "vol_rel_zero_scale",
    "vol_rel_upstream_undefined",
    "insufficient_threshold_history",
    "degenerate_boundaries",
    "assignment_warmup",
    "assignment_upstream_undefined",
    "assignment_undefined",
)
_DIAGNOSTIC_RHS_ORDER = (
    "component_coverage",
    "outcome_complete_h15",
    "outcome_complete_h30",
    "outcome_complete_h60",
)


@dataclass(frozen=True)
class StateAnchorDiagnostic:
    session_id: int
    tau_ns: int
    observed_1m_components: int
    outcome_complete_h15: bool
    outcome_complete_h30: bool
    outcome_complete_h60: bool

    def __post_init__(self) -> None:
        if type(self.session_id) is not int or type(self.tau_ns) is not int:
            raise SpineError("state diagnostic identities must be built-in integers")
        if type(self.observed_1m_components) is not int or not 0 <= self.observed_1m_components <= 5:
            raise SpineError("state diagnostic component count must be inside [0,5]")
        for name in (
            "outcome_complete_h15",
            "outcome_complete_h30",
            "outcome_complete_h60",
        ):
            if type(getattr(self, name)) is not bool:
                raise SpineError(f"state diagnostic {name} must be bool")


@dataclass(frozen=True)
class ArmStateDiagnostic:
    arm_id: str
    session_id: int
    tau_ns: int
    reset_before: bool
    non_ok_stage_statuses: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.arm_id not in {config.arm_id for config in ARM_CONFIGS}:
            raise SpineError("arm-state diagnostic arm is outside the fixed inventory")
        if type(self.session_id) is not int or type(self.tau_ns) is not int:
            raise SpineError("arm-state diagnostic identities must be built-in integers")
        if type(self.reset_before) is not bool:
            raise SpineError("arm-state diagnostic reset_before must be bool")
        if (
            not isinstance(self.non_ok_stage_statuses, tuple)
            or len(set(self.non_ok_stage_statuses)) != len(self.non_ok_stage_statuses)
            or any(status not in NON_OK_STATUS_ORDER for status in self.non_ok_stage_statuses)
        ):
            raise SpineError("arm-state diagnostic statuses are not a unique closed tuple")


@dataclass(frozen=True)
class StateValidityRow:
    metric: str
    arm_id: str
    session_phase: str
    detail: str
    comparison_arm_id: str
    category_code: int
    category_to_code: int
    session_id: int
    year: int
    horizon: str
    count: int
    denominator: int
    value: float
    value_valid: bool
    status: str

    def __post_init__(self) -> None:
        if self.metric not in METRIC_ORDER:
            raise SpineError("state-validity metric is outside the fixed order")
        if self.session_phase not in PHASE_ORDER:
            raise SpineError("state-validity phase is outside the frozen order")
        if type(self.category_code) is not int or self.category_code not in {-2, -1, 0, 1, 2}:
            raise SpineError("state-validity category code is invalid")
        if type(self.category_to_code) is not int or self.category_to_code not in {-2, -1, 0, 1, 2}:
            raise SpineError("state-validity destination category is invalid")
        for name in ("session_id", "year", "count", "denominator"):
            if type(getattr(self, name)) is not int:
                raise SpineError(f"state-validity {name} must be a built-in int")
        if self.count < 0 or self.denominator < 0:
            raise SpineError("state-validity counts cannot be negative")
        if not isinstance(self.value, float) or not np.isfinite(self.value):
            raise SpineError("state-validity stored value must be finite float64")
        if type(self.value_valid) is not bool:
            raise SpineError("state-validity value_valid must be bool")
        if not self.value_valid and self.value != 0.0:
            raise SpineError("undefined state-validity values must store zero")
        for name in ("arm_id", "detail", "comparison_arm_id", "horizon", "status"):
            if not isinstance(getattr(self, name), str):
                raise SpineError(f"state-validity {name} must be a string")


@dataclass(frozen=True)
class StateValidityPanel:
    rows: tuple[StateValidityRow, ...]

    def __post_init__(self) -> None:
        if not self.rows:
            raise SpineError("state-validity panel must be nonempty")
        ranks = [METRIC_ORDER.index(row.metric) for row in self.rows]
        if any(right < left for left, right in zip(ranks, ranks[1:])):
            raise SpineError("state-validity rows differ from fixed metric order")
        if any("score" in row.detail or "preferred" in row.detail for row in self.rows):
            raise SpineError("state-validity panel cannot emit scores or preferences")


def _average_ranks(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    order = np.argsort(values, kind="stable")
    ranks = np.empty(values.size, dtype=np.float64)
    start = 0
    while start < values.size:
        end = start + 1
        while end < values.size and values[order[end]] == values[order[start]]:
            end += 1
        rank = np.float64(np.float64(start + 1 + end) / np.float64(2.0))
        ranks[order[start:end]] = rank
        start = end
    return ranks


def average_rank_spearman(left, right) -> tuple[float, bool]:
    x = np.asarray(left, dtype=np.float64)
    y = np.asarray(right, dtype=np.float64)
    if x.ndim != 1 or y.ndim != 1 or x.size != y.size:
        raise SpineError("Spearman inputs must be aligned vectors")
    if x.size < 2 or not np.isfinite(x).all() or not np.isfinite(y).all():
        return 0.0, False
    rx = _average_ranks(x)
    ry = _average_ranks(y)
    dx = rx - np.mean(rx, dtype=np.float64)
    dy = ry - np.mean(ry, dtype=np.float64)
    denom = np.sqrt(np.sum(dx * dx, dtype=np.float64) * np.sum(dy * dy, dtype=np.float64))
    if denom == 0.0:
        return 0.0, False
    value = float(np.sum(dx * dy, dtype=np.float64) / denom)
    return value, bool(np.isfinite(value))


def _diagnostic_map(diagnostics: tuple[StateAnchorDiagnostic, ...]):
    keys = tuple((row.session_id, row.tau_ns) for row in diagnostics)
    if keys != tuple(dict.fromkeys(keys)):
        raise SpineError("state diagnostics must have unique ordered identities")
    return {(row.session_id, row.tau_ns): row for row in diagnostics}


def _runs_and_transitions(
    rows: tuple[AssignmentRow, ...],
    arm_diagnostic_by_key: dict,
) -> tuple[tuple[int, ...], np.ndarray]:
    runs: list[int] = []
    transitions = np.zeros((3, 3), dtype=np.int64)
    previous: AssignmentRow | None = None
    run_length = 0
    for row in rows:
        key = (row.session_id, row.tau_ns)
        diagnostic = arm_diagnostic_by_key[key]
        defined = row.assignment_status is AssignmentStatus.OK and row.category_code >= 0
        adjacent = (
            previous is not None
            and previous.assignment_status is AssignmentStatus.OK
            and previous.category_code >= 0
            and previous.session_id == row.session_id
            and previous.session_phase == row.session_phase
            and row.tau_ns == previous.tau_ns + int(BAR_NS)
            and not diagnostic.reset_before
        )
        if defined and adjacent:
            transitions[previous.category_code, row.category_code] += 1
            if row.category_code == previous.category_code:
                run_length += 1
            else:
                if run_length:
                    runs.append(run_length)
                run_length = 1
        elif defined:
            if run_length:
                runs.append(run_length)
            run_length = 1
        else:
            if run_length:
                runs.append(run_length)
            run_length = 0
        previous = row
    if run_length:
        runs.append(run_length)
    return tuple(runs), transitions


def _rhs(diagnostic: StateAnchorDiagnostic, name: str) -> float:
    if name == "component_coverage":
        return float(np.float64(diagnostic.observed_1m_components) / np.float64(5.0))
    return float(bool(getattr(diagnostic, name)))


def _row(
    metric: str,
    arm_id: str,
    phase: str,
    detail: str,
    *,
    comparison: str = "",
    category: int = -2,
    category_to: int = -2,
    session_id: int = 0,
    year: int = 0,
    horizon: str = "",
    count: int = 0,
    denominator: int = 0,
    value: float = 0.0,
    valid: bool = True,
    status: str = "ok",
) -> StateValidityRow:
    return StateValidityRow(
        metric,
        arm_id,
        phase,
        detail,
        comparison,
        category,
        category_to,
        session_id,
        year,
        horizon,
        count,
        denominator,
        float(value) if valid else 0.0,
        valid,
        status,
    )


def build_state_validity_panel(
    pipeline: Phase7ConditionerPipeline,
    diagnostics: tuple[StateAnchorDiagnostic, ...],
    arm_diagnostics: tuple[ArmStateDiagnostic, ...],
) -> StateValidityPanel:
    if not isinstance(pipeline, Phase7ConditionerPipeline):
        raise SpineError("state validity requires a validated Phase 7 pipeline")
    diagnostic_by_key = _diagnostic_map(diagnostics)
    primary = pipeline.assignment_tables["primary_ewma78_permissive_expanding"]
    expected_keys = tuple((row.session_id, row.tau_ns) for row in primary.rows)
    if tuple(diagnostic_by_key) != expected_keys:
        raise SpineError("state diagnostics differ from declared anchor support")
    arm_diagnostic_by_arm: dict[str, dict[tuple[int, int], ArmStateDiagnostic]] = {}
    position = 0
    for config in ARM_CONFIGS:
        table = pipeline.assignment_tables[config.arm_id]
        keys = tuple((row.session_id, row.tau_ns) for row in table.rows)
        count = len(keys)
        block = arm_diagnostics[position : position + count]
        position += count
        if tuple((row.session_id, row.tau_ns) for row in block) != keys or any(
            row.arm_id != config.arm_id for row in block
        ):
            raise SpineError("arm-state diagnostics differ from fixed arm/anchor support")
        arm_diagnostic_by_arm[config.arm_id] = {
            (row.session_id, row.tau_ns): row for row in block
        }
    if position != len(arm_diagnostics):
        raise SpineError("arm-state diagnostics contain trailing rows")
    output: list[StateValidityRow] = []

    # 1. Category and status frequency.
    for config in ARM_CONFIGS:
        table = pipeline.assignment_tables[config.arm_id]
        for phase in PHASE_ORDER:
            phase_rows = tuple(row for row in table.rows if row.session_phase == phase)
            denominator = len(phase_rows)
            for code in CATEGORY_ORDER:
                count = sum(row.category_code == code for row in phase_rows)
                value = 0.0 if denominator == 0 else count / denominator
                output.append(_row("category_frequency", config.arm_id, phase, f"category:{code}", category=code, count=count, denominator=denominator, value=value))
            for status in AssignmentStatus:
                count = sum(row.assignment_status is status for row in phase_rows)
                value = 0.0 if denominator == 0 else count / denominator
                output.append(_row("category_frequency", config.arm_id, phase, f"assignment_status:{status.value}", count=count, denominator=denominator, value=value))

    # 2. Runs.
    for config in ARM_CONFIGS:
        table = pipeline.assignment_tables[config.arm_id]
        for phase in PHASE_ORDER:
            phase_rows = tuple(row for row in table.rows if row.session_phase == phase)
            runs, _ = _runs_and_transitions(
                phase_rows, arm_diagnostic_by_arm[config.arm_id]
            )
            total = sum(runs)
            mean = 0.0 if not runs else total / len(runs)
            output.append(_row("average_run_length", config.arm_id, phase, "defined_category_episodes", count=len(runs), denominator=total, value=mean, valid=bool(runs), status="ok" if runs else "undefined_no_episodes"))

    # 3. Transition matrix and entropy.
    for config in ARM_CONFIGS:
        table = pipeline.assignment_tables[config.arm_id]
        for phase in PHASE_ORDER:
            phase_rows = tuple(row for row in table.rows if row.session_phase == phase)
            _, transitions = _runs_and_transitions(
                phase_rows, arm_diagnostic_by_arm[config.arm_id]
            )
            total = int(np.sum(transitions))
            for source in (0, 1, 2):
                row_total = int(np.sum(transitions[source]))
                for destination in (0, 1, 2):
                    count = int(transitions[source, destination])
                    probability = 0.0 if row_total == 0 else count / row_total
                    output.append(_row("transition_entropy", config.arm_id, phase, "transition_probability", category=source, category_to=destination, count=count, denominator=row_total, value=probability, valid=row_total > 0, status="ok" if row_total else "undefined_source_state"))
            entropy = 0.0
            if total:
                for source in (0, 1, 2):
                    row_total = int(np.sum(transitions[source]))
                    if not row_total:
                        continue
                    pi = np.float64(row_total) / np.float64(total)
                    conditional = 0.0
                    for count in transitions[source]:
                        if count:
                            probability = np.float64(count) / np.float64(row_total)
                            conditional -= float(probability * np.log2(probability))
                    entropy += float(pi * conditional)
            output.append(_row("transition_entropy", config.arm_id, phase, "conditional_entropy_bits", count=total, denominator=total, value=entropy, valid=total > 0, status="ok" if total else "undefined_no_transitions"))

    # 4. Primary-versus-OFAT migration by phase.
    primary_table = pipeline.assignment_tables["primary_ewma78_permissive_expanding"]
    for config in ARM_CONFIGS[1:]:
        alternative = pipeline.assignment_tables[config.arm_id]
        for phase in PHASE_ORDER:
            left = tuple(row for row in primary_table.rows if row.session_phase == phase)
            right = tuple(row for row in alternative.rows if row.session_phase == phase)
            if tuple((row.session_id, row.tau_ns) for row in left) != tuple((row.session_id, row.tau_ns) for row in right):
                raise SpineError("state-validity migration supports differ")
            counts = {(a, b): 0 for a in CATEGORY_ORDER for b in CATEGORY_ORDER}
            for a, b in zip(left, right, strict=True):
                counts[(a.category_code, b.category_code)] += 1
            common = sum(count for (a, b), count in counts.items() if a != -1 and b != -1)
            changed = sum(count for (a, b), count in counts.items() if a != -1 and b != -1 and a != b)
            for source in CATEGORY_ORDER:
                row_total = sum(counts[(source, destination)] for destination in CATEGORY_ORDER)
                for destination in CATEGORY_ORDER:
                    count = counts[(source, destination)]
                    fraction = 0.0 if row_total == 0 else count / row_total
                    output.append(_row("cell_migration", config.arm_id, phase, "row_fraction", comparison=config.arm_id, category=source, category_to=destination, count=count, denominator=row_total, value=fraction, valid=row_total > 0, status="ok" if row_total else "undefined_source_state"))
            output.append(_row("cell_migration", config.arm_id, phase, "common_defined_changed_fraction", comparison=config.arm_id, count=changed, denominator=common, value=0.0 if common == 0 else changed / common, valid=common > 0, status="ok" if common else "undefined_no_common_support"))
            primary_only = sum(count for (a, b), count in counts.items() if a != -1 and b == -1)
            alternative_only = sum(count for (a, b), count in counts.items() if a == -1 and b != -1)
            output.append(_row("cell_migration", config.arm_id, phase, "primary_defined_alternative_undefined", comparison=config.arm_id, count=primary_only, denominator=len(left), value=0.0 if not left else primary_only / len(left)))
            output.append(_row("cell_migration", config.arm_id, phase, "primary_undefined_alternative_defined", comparison=config.arm_id, count=alternative_only, denominator=len(left), value=0.0 if not left else alternative_only / len(left)))

    # 5. Complete threshold series, then fixed drift summary.
    for config in ARM_CONFIGS:
        table = pipeline.threshold_tables[config.arm_id]
        for phase in PHASE_ORDER:
            phase_rows = tuple(row for row in table.rows if row.session_phase == phase)
            for boundary in ("lower", "upper"):
                differences: list[float] = []
                previous = None
                for row in phase_rows:
                    value = row.lower_threshold if boundary == "lower" else row.upper_threshold
                    output.append(_row("threshold_drift", config.arm_id, phase, f"{boundary}_threshold_series", session_id=row.session_id, value=value, valid=row.threshold_valid, status=row.threshold_status.value))
                    if row.threshold_valid and previous is not None:
                        differences.append(abs(value - previous))
                    previous = value if row.threshold_valid else None
                valid = bool(differences)
                summary = 0.0 if not valid else float(lower_median(np.asarray(differences, dtype=np.float64)))
                output.append(_row("threshold_drift", config.arm_id, phase, f"{boundary}_median_absolute_consecutive_change", count=len(differences), denominator=len(differences), value=summary, valid=valid, status="ok" if valid else "undefined_no_consecutive_thresholds"))

    # 6. Construction diagnostic: raw scale versus assigned category.
    for config in ARM_CONFIGS:
        table = pipeline.assignment_tables[config.arm_id]
        for phase in PHASE_ORDER:
            phase_rows = tuple(row for row in table.rows if row.session_phase == phase and row.assignment_status is AssignmentStatus.OK and row.scale_valid)
            correlation, valid = average_rank_spearman([row.category_code for row in phase_rows], [row.scale_value for row in phase_rows])
            output.append(_row("raw_volatility_correlation", config.arm_id, phase, "spearman_average_ties", count=len(phase_rows), denominator=len(phase_rows), value=correlation, valid=valid, status="ok" if valid else "undefined_insufficient_or_constant"))

    # 7. Completion/missingness is RHS-only and never changes state support.
    for config in ARM_CONFIGS:
        table = pipeline.assignment_tables[config.arm_id]
        for phase in PHASE_ORDER:
            phase_rows = tuple(row for row in table.rows if row.session_phase == phase)
            defined_rows = tuple(row for row in phase_rows if row.assignment_status is AssignmentStatus.OK)
            for rhs_name in _DIAGNOSTIC_RHS_ORDER:
                rhs_values = [_rhs(diagnostic_by_key[(row.session_id, row.tau_ns)], rhs_name) for row in defined_rows]
                correlation, valid = average_rank_spearman([row.category_code for row in defined_rows], rhs_values)
                horizon = rhs_name.removeprefix("outcome_complete_") if rhs_name.startswith("outcome_complete_") else ""
                output.append(_row("missingness_completion_correlation", config.arm_id, phase, f"category_vs_{rhs_name}", horizon=horizon, count=len(defined_rows), denominator=len(defined_rows), value=correlation, valid=valid, status="ok" if valid else "undefined_insufficient_or_constant"))
                all_rhs = [_rhs(diagnostic_by_key[(row.session_id, row.tau_ns)], rhs_name) for row in phase_rows]
                definedness = [float(row.assignment_status is AssignmentStatus.OK) for row in phase_rows]
                defined_corr, defined_valid = average_rank_spearman(definedness, all_rhs)
                output.append(_row("missingness_completion_correlation", config.arm_id, phase, f"assignment_definedness_vs_{rhs_name}", horizon=horizon, count=len(phase_rows), denominator=len(phase_rows), value=defined_corr, valid=defined_valid, status="ok" if defined_valid else "undefined_insufficient_or_constant"))

    # 8. Mandatory explicit deferral.
    for config in ARM_CONFIGS:
        for phase in PHASE_ORDER:
            output.append(_row("liquidity_era_correlation", config.arm_id, phase, "deferred_missing_versioned_input", count=0, denominator=0, valid=False, status="deferred_missing_versioned_input"))

    # 9. Every non-ok stage status by arm, phase, and year.
    for config in ARM_CONFIGS:
        table = pipeline.assignment_tables[config.arm_id]
        years = tuple(dict.fromkeys(row.session_id // 10_000 for row in table.rows))
        for phase in PHASE_ORDER:
            for year in years:
                phase_rows = tuple(row for row in table.rows if row.session_phase == phase and row.session_id // 10_000 == year)
                denominator = len(phase_rows)
                for status in NON_OK_STATUS_ORDER:
                    count = 0
                    for row in phase_rows:
                        diagnostic = arm_diagnostic_by_arm[config.arm_id][
                            (row.session_id, row.tau_ns)
                        ]
                        if status == "assignment_undefined":
                            count += int(row.category_code == -1)
                        else:
                            count += int(status in diagnostic.non_ok_stage_statuses)
                    value = 0.0 if denominator == 0 else count / denominator
                    output.append(_row("undefined_warmup_fraction", config.arm_id, phase, status, year=year, count=count, denominator=denominator, value=value))

    return StateValidityPanel(tuple(output))
