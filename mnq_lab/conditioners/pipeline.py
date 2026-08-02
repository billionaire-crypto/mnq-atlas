"""Deterministic assembly of all ten frozen Phase 7 conditioner arms."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from mnq_lab import SpineError
from mnq_lab.conditioners.arms import ARM_CONFIGS
from mnq_lab.conditioners.assignments import (
    AssignmentTable,
    MigrationSummary,
    ThresholdTable,
    UndefinedFractionRow,
    VolRelTable,
    assignment_undefined_fractions,
    build_assignments,
    build_thresholds,
    build_vol_rel,
    cell_migration,
)
from mnq_lab.conditioners.calendar import CalendarTable
from mnq_lab.conditioners.seasonal import (
    ScaleAnchorTable,
    SeasonalProfileTable,
    build_seasonal_profiles,
)

__all__ = ["SCALE_SOURCE_ARMS", "Phase7ConditionerPipeline", "build_conditioner_pipeline"]

PRIMARY_ARM = "primary_ewma78_permissive_expanding"
SCALE_SOURCE_ARMS = (
    PRIMARY_ARM,
    "coverage_strict",
    "ewma39",
    "ewma156",
    "mad78",
)


def _source_arm(arm_id: str) -> str:
    return PRIMARY_ARM if arm_id.startswith("threshold_") else arm_id


@dataclass(frozen=True)
class Phase7ConditionerPipeline:
    seasonal_profiles: MappingProxyType
    vol_rel_tables: MappingProxyType
    threshold_tables: MappingProxyType
    assignment_tables: MappingProxyType
    migration_summaries: MappingProxyType
    undefined_fractions: MappingProxyType

    def __post_init__(self) -> None:
        arm_ids = tuple(config.arm_id for config in ARM_CONFIGS)
        if tuple(self.seasonal_profiles) != SCALE_SOURCE_ARMS:
            raise SpineError("pipeline seasonal source-arm order differs from contract")
        if tuple(self.vol_rel_tables) != SCALE_SOURCE_ARMS:
            raise SpineError("pipeline vol_rel source-arm order differs from contract")
        if tuple(self.threshold_tables) != arm_ids:
            raise SpineError("pipeline threshold arm order differs from contract")
        if tuple(self.assignment_tables) != arm_ids:
            raise SpineError("pipeline assignment arm order differs from contract")
        if tuple(self.migration_summaries) != arm_ids[1:]:
            raise SpineError("pipeline migration order differs from contract")
        if tuple(self.undefined_fractions) != arm_ids:
            raise SpineError("pipeline undefined-fraction order differs from contract")
        for arm_id in SCALE_SOURCE_ARMS:
            if not isinstance(self.seasonal_profiles[arm_id], SeasonalProfileTable):
                raise SpineError("pipeline seasonal value is not a validated table")
            if not isinstance(self.vol_rel_tables[arm_id], VolRelTable):
                raise SpineError("pipeline vol_rel value is not a validated table")
        for arm_id in arm_ids:
            if self.threshold_tables[arm_id].arm_id != arm_id:
                raise SpineError("pipeline threshold key and embedded arm differ")
            if self.assignment_tables[arm_id].arm_id != arm_id:
                raise SpineError("pipeline assignment key and embedded arm differ")
            if any(row.arm_id != arm_id for row in self.undefined_fractions[arm_id]):
                raise SpineError("pipeline undefined-fraction key and rows differ")
        for arm_id in arm_ids[1:]:
            summary = self.migration_summaries[arm_id]
            if (
                summary.primary_arm_id != PRIMARY_ARM
                or summary.alternative_arm_id != arm_id
            ):
                raise SpineError("pipeline migration key and embedded arms differ")


def build_conditioner_pipeline(
    scale_tables: dict[str, ScaleAnchorTable],
    current_sessions: tuple[int, ...],
    completed_sessions: frozenset[int],
    calendar: CalendarTable,
) -> Phase7ConditionerPipeline:
    if tuple(scale_tables) != SCALE_SOURCE_ARMS:
        raise SpineError(
            f"scale tables must use exact order {SCALE_SOURCE_ARMS}, got {tuple(scale_tables)}"
        )
    reference_keys = tuple(
        (row.session_id, row.tau_ns)
        for row in scale_tables[PRIMARY_ARM].rows
    )
    reference_sessions = tuple(dict.fromkeys(session for session, _ in reference_keys))
    if current_sessions != reference_sessions:
        raise SpineError("current sessions differ from the declared anchor support")
    for source_arm in SCALE_SOURCE_ARMS:
        table = scale_tables[source_arm]
        keys = tuple((row.session_id, row.tau_ns) for row in table.rows)
        if keys != reference_keys:
            raise SpineError("scale-arm anchor supports differ")
        expected_stage = "mad" if source_arm == "mad78" else "ewma"
        if any(row.scale_stage != expected_stage for row in table.rows):
            raise SpineError("scale-arm estimator stage differs from its frozen arm")
    profiles: dict[str, SeasonalProfileTable] = {}
    vol_tables: dict[str, VolRelTable] = {}
    for source_arm in SCALE_SOURCE_ARMS:
        table = scale_tables[source_arm]
        if table.arm_id != source_arm:
            raise SpineError("scale table key and embedded arm_id differ")
        profiles[source_arm] = build_seasonal_profiles(
            table, current_sessions, completed_sessions, calendar
        )
        vol_tables[source_arm] = build_vol_rel(table, profiles[source_arm])

    thresholds: dict[str, ThresholdTable] = {}
    assignments: dict[str, AssignmentTable] = {}
    for config in ARM_CONFIGS:
        source_arm = _source_arm(config.arm_id)
        thresholds[config.arm_id] = build_thresholds(
            config,
            vol_tables[source_arm],
            current_sessions,
            completed_sessions,
            calendar,
        )
        assignments[config.arm_id] = build_assignments(
            config,
            vol_tables[source_arm],
            thresholds[config.arm_id],
            calendar,
        )

    primary = assignments[PRIMARY_ARM]
    migrations: dict[str, MigrationSummary] = {}
    for config in ARM_CONFIGS[1:]:
        migrations[config.arm_id] = cell_migration(
            primary, assignments[config.arm_id]
        )
    undefined = {
        config.arm_id: assignment_undefined_fractions(assignments[config.arm_id])
        for config in ARM_CONFIGS
    }
    return Phase7ConditionerPipeline(
        MappingProxyType(profiles),
        MappingProxyType(vol_tables),
        MappingProxyType(thresholds),
        MappingProxyType(assignments),
        MappingProxyType(migrations),
        MappingProxyType(undefined),
    )
