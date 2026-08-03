"""Complete structural result-row inventory for Phase 8 point estimates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from mnq_lab import SpineError
from mnq_lab.conditioners.arms import ARM_CONFIGS
from mnq_lab.conditioners.assignments import MigrationSummary
from mnq_lab.phase8.contrasts import (
    CONTRAST_NAMES,
    OUTCOME_NAMES,
    SESSION_PHASES,
    STATISTICS,
    VOLATILITY_STATES,
    CellKey,
)
from mnq_lab.phase8.diagnostics import StatusDecision, resolve_status
from mnq_lab.phase8.estimands import ESTIMAND_NAMES

PRIMARY_ARM_ID = "primary_ewma78_permissive_expanding"
ALTERNATIVE_ARM_IDS = (
    "coverage_strict",
    "ewma39",
    "ewma156",
    "mad78",
    "threshold_rolling60",
    "threshold_shift_m05",
    "threshold_shift_m02",
    "threshold_shift_p02",
    "threshold_shift_p05",
)
PATH_ESTIMANDS = ("fully_labeled_1m_grid", "observed_bar_path")
SUPPORT_KINDS = ("horizon_specific", "common_support")
HORIZONS_MINUTES = (15, 30, 60)
CONTRAST_WEIGHTINGS = (
    "equal_phase_contrast",
    "natural_prevalence_contrast",
)

__all__ = [
    "ALTERNATIVE_ARM_IDS",
    "CONTRAST_WEIGHTINGS",
    "HORIZONS_MINUTES",
    "PATH_ESTIMANDS",
    "PRIMARY_ARM_ID",
    "SUPPORT_KINDS",
    "Phase8StatusRow",
    "ResultRowSpec",
    "assemble_status_rows",
    "declared_result_rows",
]


@dataclass(frozen=True)
class ResultRowSpec:
    arm_id: str
    outcome_name: str
    path_estimand: str
    support_kind: str
    horizon_minutes: int
    statistic: str
    contrast_name: str
    population_estimand: str
    contrast_weighting: str
    target_cell: CellKey
    migration_diagnostic_arm_id: str | None

    def __post_init__(self) -> None:
        arm_ids = (PRIMARY_ARM_ID, *ALTERNATIVE_ARM_IDS)
        if self.arm_id not in arm_ids:
            raise SpineError("result row arm is outside the frozen inventory")
        if self.outcome_name not in OUTCOME_NAMES:
            raise SpineError("result row outcome is outside the frozen inventory")
        if self.path_estimand not in PATH_ESTIMANDS:
            raise SpineError("result row path estimand is outside the frozen inventory")
        if self.support_kind not in SUPPORT_KINDS:
            raise SpineError("result row support kind is outside the frozen inventory")
        if self.horizon_minutes not in HORIZONS_MINUTES:
            raise SpineError("result row horizon is outside the frozen inventory")
        if self.statistic not in {name for name, _ in STATISTICS}:
            raise SpineError("result row statistic is outside the frozen inventory")
        if self.contrast_name not in CONTRAST_NAMES:
            raise SpineError("result row contrast is outside the frozen inventory")
        if self.population_estimand not in ESTIMAND_NAMES:
            raise SpineError("result row population estimand is outside the inventory")
        expected_weightings = (
            ("not_applicable",)
            if self.contrast_name == "absolute_distribution"
            else CONTRAST_WEIGHTINGS
        )
        if self.contrast_weighting not in expected_weightings:
            raise SpineError("result row contrast weighting is outside the inventory")
        if not isinstance(self.target_cell, CellKey):
            raise SpineError("result row target must be a declared CellKey")
        expected_migration = None if self.arm_id == PRIMARY_ARM_ID else self.arm_id
        if self.migration_diagnostic_arm_id != expected_migration:
            raise SpineError("survival row is missing its Phase 7 migration diagnostic key")


@dataclass(frozen=True)
class Phase8StatusRow:
    spec: ResultRowSpec
    status: StatusDecision
    migration_diagnostics: MigrationSummary | None


def _cells() -> tuple[CellKey, ...]:
    return tuple(
        CellKey(phase, state)
        for phase in SESSION_PHASES
        for state in VOLATILITY_STATES
    )


def _weightings(contrast_name: str) -> tuple[str, ...]:
    if contrast_name == "absolute_distribution":
        return ("not_applicable",)
    if contrast_name in CONTRAST_NAMES[1:]:
        return CONTRAST_WEIGHTINGS
    raise SpineError(f"unhandled declared contrast in row inventory: {contrast_name!r}")


def _validate_phase7_arm_binding() -> None:
    actual = tuple(config.arm_id for config in ARM_CONFIGS)
    expected = (PRIMARY_ARM_ID, *ALTERNATIVE_ARM_IDS)
    if actual != expected:
        raise SpineError("Phase 8 arm inventory diverges from Phase 7 arm order")


def declared_result_rows() -> tuple[ResultRowSpec, ...]:
    """Return every declared point-row key in literal structural order."""
    _validate_phase7_arm_binding()
    cells = _cells()
    rows: list[ResultRowSpec] = []
    for outcome_name in OUTCOME_NAMES:
        for path_estimand in PATH_ESTIMANDS:
            for support_kind in SUPPORT_KINDS:
                for horizon in HORIZONS_MINUTES:
                    for statistic, _ in STATISTICS:
                        for contrast_name in CONTRAST_NAMES:
                            for population_estimand in ESTIMAND_NAMES:
                                for contrast_weighting in _weightings(contrast_name):
                                    for target_cell in cells:
                                        rows.append(
                                            ResultRowSpec(
                                                PRIMARY_ARM_ID,
                                                outcome_name,
                                                path_estimand,
                                                support_kind,
                                                horizon,
                                                statistic,
                                                contrast_name,
                                                population_estimand,
                                                contrast_weighting,
                                                target_cell,
                                                None,
                                            )
                                        )
    for arm_id in ALTERNATIVE_ARM_IDS:
        for contrast_weighting in CONTRAST_WEIGHTINGS:
            for target_cell in cells:
                rows.append(
                    ResultRowSpec(
                        arm_id,
                        "downward_excursion_ticks",
                        "fully_labeled_1m_grid",
                        "horizon_specific",
                        30,
                        "q90",
                        "vol_effect_given_phase",
                        "prospective_cell",
                        contrast_weighting,
                        target_cell,
                        arm_id,
                    )
                )
    return tuple(rows)


def assemble_status_rows(
    declared: Any,
    status_by_spec: Mapping[ResultRowSpec, StatusDecision],
    *,
    migration_by_arm: Mapping[str, MigrationSummary] | None = None,
) -> tuple[Phase8StatusRow, ...]:
    """Require exactly one validated status for every declared result cell."""
    if not isinstance(declared, tuple) or any(
        not isinstance(spec, ResultRowSpec) for spec in declared
    ):
        raise SpineError("declared result cells must be an immutable spec tuple")
    if len(set(declared)) != len(declared):
        raise SpineError("declared result cells contain a duplicate")
    if not isinstance(status_by_spec, Mapping):
        raise SpineError("status_by_spec must be a mapping")
    migrations = {} if migration_by_arm is None else migration_by_arm
    if not isinstance(migrations, Mapping):
        raise SpineError("migration_by_arm must be a mapping")
    for spec in declared:
        if spec not in status_by_spec:
            raise SpineError(f"missing declared result cell: {spec!r}")
    extras = tuple(spec for spec in status_by_spec if spec not in set(declared))
    if extras:
        raise SpineError(f"status rows contain an undeclared result cell: {extras[0]!r}")
    output: list[Phase8StatusRow] = []
    for spec in declared:
        decision = status_by_spec[spec]
        if not isinstance(decision, StatusDecision):
            raise SpineError("every declared result cell requires a StatusDecision")
        resolved = resolve_status(decision.status_flags)
        if (
            resolved.status != decision.status
            or resolved.failure_states != decision.failure_states
        ):
            raise SpineError("declared result cell carries an inconsistent status")
        migration = None
        if spec.migration_diagnostic_arm_id is not None:
            migration = migrations.get(spec.migration_diagnostic_arm_id)
            if migration is None:
                raise SpineError(
                    "missing Phase 7 migration diagnostic for survival row "
                    f"{spec.migration_diagnostic_arm_id!r}"
                )
            if not isinstance(migration, MigrationSummary):
                raise SpineError("survival-row migration diagnostic has the wrong type")
            if (
                migration.primary_arm_id != PRIMARY_ARM_ID
                or migration.alternative_arm_id != spec.arm_id
            ):
                raise SpineError("survival-row migration diagnostic arm keys differ")
        output.append(Phase8StatusRow(spec, decision, migration))
    return tuple(output)
