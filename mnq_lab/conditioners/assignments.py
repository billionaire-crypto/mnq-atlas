"""Phase 7 relative volatility, thresholds, assignments, and migration."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from mnq_lab import SpineError
from mnq_lab.conditioners.arms import ArmConfig
from mnq_lab.conditioners.calendar import CalendarTable
from mnq_lab.conditioners.seasonal import (
    ScaleAnchorTable,
    SeasonalProfileTable,
)
from mnq_lab.conditioners.status import (
    AssignmentStatus,
    ThresholdStatus,
    UpstreamStage,
    VolRelStatus,
)
from mnq_lab.core.weights import weighted_quantile
from mnq_lab.spine.timemodel import TimeModel

__all__ = [
    "AssignmentRow",
    "AssignmentTable",
    "MigrationCell",
    "MigrationSummary",
    "ThresholdRow",
    "ThresholdTable",
    "UndefinedFractionRow",
    "VolRelRow",
    "VolRelTable",
    "assignment_undefined_fractions",
    "build_assignments",
    "build_thresholds",
    "build_vol_rel",
    "cell_migration",
]

CATEGORY_ORDER = (-1, 0, 1, 2)
CATEGORY_NAMES = {-1: "undefined", 0: "low", 1: "mid", 2: "high"}
THRESHOLD_WARMUP_SESSIONS = 60
PHASE_ORDER = tuple(TimeModel.from_constants().phase_names)


@dataclass(frozen=True)
class VolRelRow:
    source_arm_id: str
    session_id: int
    ts_event_ns: int
    tau_ns: int
    observation_bucket_ct: str
    session_phase: str
    scale_value: float
    scale_valid: bool
    seasonal_profile: float
    seasonal_valid: bool
    vol_rel: float
    vol_rel_valid: bool
    vol_rel_status: VolRelStatus
    upstream_stage: UpstreamStage | None
    data_quality_status: str


@dataclass(frozen=True)
class VolRelTable:
    source_arm_id: str
    rows: tuple[VolRelRow, ...]

    def __post_init__(self) -> None:
        if not self.rows:
            raise SpineError("vol_rel table must be nonempty")
        keys = [(row.session_id, row.tau_ns) for row in self.rows]
        if keys != sorted(keys) or len(set(keys)) != len(keys):
            raise SpineError("vol_rel rows must be unique and ordered")
        if any(row.source_arm_id != self.source_arm_id for row in self.rows):
            raise SpineError("vol_rel table mixes source arms")
        for row in self.rows:
            if not isinstance(row.vol_rel_status, VolRelStatus):
                raise SpineError("vol_rel status is outside the closed vocabulary")
            if row.upstream_stage is not None and not isinstance(
                row.upstream_stage, UpstreamStage
            ):
                raise SpineError("vol_rel upstream stage is outside the closed vocabulary")
            for name in ("scale_value", "seasonal_profile", "vol_rel"):
                value = getattr(row, name)
                if not isinstance(value, float) or not np.isfinite(value) or value < 0.0:
                    raise SpineError(f"vol_rel {name} must be finite and nonnegative")
            if not np.isfinite(row.vol_rel) or row.vol_rel < 0.0:
                raise SpineError("stored vol_rel must be finite and nonnegative")
            if (row.vol_rel_status is VolRelStatus.OK) != row.vol_rel_valid:
                raise SpineError("vol_rel status and validity disagree")
            if not row.vol_rel_valid and row.vol_rel != 0.0:
                raise SpineError("undefined vol_rel rows must store numeric zero")
            if row.vol_rel_status is VolRelStatus.UPSTREAM_UNDEFINED:
                if row.upstream_stage is None:
                    raise SpineError("upstream-undefined vol_rel requires its source stage")
                if row.upstream_stage in {UpstreamStage.EWMA, UpstreamStage.MAD}:
                    if row.scale_valid:
                        raise SpineError("scale-stage undefined vol_rel has a defined scale")
                elif not row.scale_valid or row.seasonal_valid:
                    raise SpineError("seasonal-stage undefined vol_rel has inconsistent operands")
            elif row.upstream_stage is not None:
                raise SpineError("upstream stage is reserved for upstream-undefined vol_rel")
            if row.vol_rel_status is VolRelStatus.ZERO_SCALE:
                if not row.scale_valid or not row.seasonal_valid or row.seasonal_profile != 0.0:
                    raise SpineError("zero-scale vol_rel requires defined operands and zero profile")
            if row.vol_rel_status is VolRelStatus.OK and (
                not row.scale_valid or not row.seasonal_valid or row.seasonal_profile == 0.0
            ):
                raise SpineError("defined vol_rel requires two defined operands and positive profile")
        object.__setattr__(
            self,
            "_by_key",
            MappingProxyType({(row.session_id, row.tau_ns): row for row in self.rows}),
        )


def build_vol_rel(
    scales: ScaleAnchorTable, profiles: SeasonalProfileTable
) -> VolRelTable:
    if scales.arm_id != profiles.arm_id:
        raise SpineError("vol_rel scale/profile arm identifiers differ")
    output: list[VolRelRow] = []
    for scale in scales.rows:
        profile = profiles.lookup(scale.session_id, scale.observation_bucket_ct)
        status: VolRelStatus
        upstream: UpstreamStage | None = None
        valid = False
        value = 0.0
        if not scale.scale_valid:
            status = VolRelStatus.UPSTREAM_UNDEFINED
            upstream = UpstreamStage.EWMA if scale.scale_stage == "ewma" else UpstreamStage.MAD
        elif not profile.seasonal_valid:
            status = VolRelStatus.UPSTREAM_UNDEFINED
            upstream = UpstreamStage.SEASONAL
        elif profile.seasonal_profile == 0.0:
            status = VolRelStatus.ZERO_SCALE
        else:
            value = float(
                np.float64(scale.scale_value) / np.float64(profile.seasonal_profile)
            )
            if not np.isfinite(value) or value < 0.0:
                raise SpineError("vol_rel division produced corruption")
            if value == 0.0:
                value = 0.0
            valid = True
            status = VolRelStatus.OK
        output.append(
            VolRelRow(
                scales.arm_id,
                scale.session_id,
                scale.ts_event_ns,
                scale.tau_ns,
                scale.observation_bucket_ct,
                scale.session_phase,
                scale.scale_value,
                scale.scale_valid,
                profile.seasonal_profile,
                profile.seasonal_valid,
                value,
                valid,
                status,
                upstream,
                scale.data_quality_status,
            )
        )
    return VolRelTable(scales.arm_id, tuple(output))


@dataclass(frozen=True)
class ThresholdRow:
    arm_id: str
    session_id: int
    session_phase: str
    history_kind: str
    qualifying_prior_sessions: int
    lower_probability: float
    upper_probability: float
    lower_threshold: float
    upper_threshold: float
    threshold_valid: bool
    threshold_status: ThresholdStatus
    dependency_keys: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class ThresholdTable:
    arm_id: str
    rows: tuple[ThresholdRow, ...]

    def __post_init__(self) -> None:
        if not self.rows:
            raise SpineError("threshold table must be nonempty")
        keys = [
            (row.session_id, PHASE_ORDER.index(row.session_phase)) for row in self.rows
        ]
        if keys != sorted(keys) or len(set(keys)) != len(keys):
            raise SpineError("threshold rows must be unique and canonically ordered")
        for row in self.rows:
            if row.arm_id != self.arm_id:
                raise SpineError("threshold table mixes arm identifiers")
            if row.session_phase not in PHASE_ORDER:
                raise SpineError("threshold phase is outside the frozen vocabulary")
            if row.history_kind not in {"expanding", "rolling60"}:
                raise SpineError("threshold history kind is outside the closed vocabulary")
            if not isinstance(row.threshold_status, ThresholdStatus):
                raise SpineError("threshold status is outside the closed vocabulary")
            if type(row.qualifying_prior_sessions) is not int or row.qualifying_prior_sessions < 0:
                raise SpineError("threshold qualifying-session count is invalid")
            if row.history_kind == "rolling60" and row.qualifying_prior_sessions > 60:
                raise SpineError("rolling threshold contains more than sixty sessions")
            if not (
                isinstance(row.lower_probability, float)
                and isinstance(row.upper_probability, float)
                and np.isfinite(row.lower_probability)
                and np.isfinite(row.upper_probability)
                and 0.0 < row.lower_probability < row.upper_probability < 1.0
            ):
                raise SpineError("threshold probabilities are not strictly ordered")
            if not (
                isinstance(row.lower_threshold, float)
                and isinstance(row.upper_threshold, float)
                and np.isfinite(row.lower_threshold)
                and np.isfinite(row.upper_threshold)
                and row.lower_threshold >= 0.0
                and row.upper_threshold >= 0.0
            ):
                raise SpineError("threshold boundaries must be finite and nonnegative")
            if row.lower_threshold > row.upper_threshold:
                raise SpineError("lower threshold exceeds upper threshold")
            if row.threshold_valid != (
                row.threshold_status
                in {ThresholdStatus.OK, ThresholdStatus.DEGENERATE_BOUNDARIES}
            ):
                raise SpineError("threshold status and validity disagree")
            if not row.threshold_valid and (
                row.lower_threshold != 0.0 or row.upper_threshold != 0.0
            ):
                raise SpineError("undefined thresholds must store numeric zero")
            if row.threshold_status is ThresholdStatus.DEGENERATE_BOUNDARIES:
                if row.lower_threshold != row.upper_threshold:
                    raise SpineError("degenerate threshold status requires equal boundaries")
            elif row.threshold_status is ThresholdStatus.OK and (
                row.lower_threshold == row.upper_threshold
            ):
                raise SpineError("equal boundaries require degenerate threshold status")
            if row.dependency_keys != tuple(sorted(set(row.dependency_keys))):
                raise SpineError("threshold dependency keys must be unique and ordered")
            if any(session >= row.session_id for session, _ in row.dependency_keys):
                raise SpineError("threshold dependency includes current or future session")
            if len({session for session, _ in row.dependency_keys}) != row.qualifying_prior_sessions:
                raise SpineError("threshold dependencies and qualifying-session count disagree")
        object.__setattr__(
            self,
            "_by_key",
            MappingProxyType(
                {(row.session_id, row.session_phase): row for row in self.rows}
            ),
        )

    def lookup(self, session_id: int, phase: str) -> ThresholdRow:
        try:
            return self._by_key[(session_id, phase)]
        except KeyError as exc:
            raise SpineError(f"threshold key is absent: {(session_id, phase)!r}") from exc


def build_thresholds(
    config: ArmConfig,
    vol_rel: VolRelTable,
    current_sessions: tuple[int, ...],
    completed_sessions: frozenset[int],
    calendar: CalendarTable,
) -> ThresholdTable:
    if not isinstance(config, ArmConfig) or not isinstance(vol_rel, VolRelTable):
        raise SpineError("threshold builder requires an arm config and vol_rel table")
    if (
        not current_sessions
        or tuple(sorted(current_sessions)) != current_sessions
        or len(set(current_sessions)) != len(current_sessions)
    ):
        raise SpineError("threshold current_sessions must be unique and ascending")
    by_session_phase: dict[tuple[int, str], list[VolRelRow]] = {}
    for row in vol_rel.rows:
        if row.vol_rel_valid:
            by_session_phase.setdefault((row.session_id, row.session_phase), []).append(row)

    output: list[ThresholdRow] = []
    for current in current_sessions:
        for phase in PHASE_ORDER:
            eligible_sessions = []
            for prior in sorted(completed_sessions):
                if prior >= current:
                    break
                calendar_row = calendar.lookup(prior)
                if calendar_row is None or not calendar_row.seasonal_reference_eligible:
                    continue
                if by_session_phase.get((prior, phase)):
                    eligible_sessions.append(prior)
            selected = (
                eligible_sessions[-60:]
                if config.history_kind == "rolling60"
                else eligible_sessions
            )
            dependency_keys = tuple(
                (row.session_id, row.tau_ns)
                for prior in selected
                for row in by_session_phase[(prior, phase)]
            )
            if len(eligible_sessions) < THRESHOLD_WARMUP_SESSIONS:
                output.append(
                    ThresholdRow(
                        config.arm_id,
                        current,
                        phase,
                        config.history_kind,
                        len(selected),
                        config.lower_probability,
                        config.upper_probability,
                        0.0,
                        0.0,
                        False,
                        ThresholdStatus.INSUFFICIENT_THRESHOLD_HISTORY,
                        dependency_keys,
                    )
                )
                continue
            values: list[float] = []
            weights: list[float] = []
            for prior in selected:
                rows = by_session_phase[(prior, phase)]
                mass = float(np.float64(1.0) / np.float64(len(rows)))
                values.extend(row.vol_rel for row in rows)
                weights.extend(mass for _ in rows)
            value_array = np.asarray(values, dtype=np.float64)
            weight_array = np.asarray(weights, dtype=np.float64)
            lower = weighted_quantile(
                value_array, weight_array, config.lower_probability
            )
            upper = weighted_quantile(
                value_array, weight_array, config.upper_probability
            )
            if not np.isfinite(lower) or not np.isfinite(upper) or lower > upper:
                raise SpineError("threshold computation produced corrupt boundaries")
            status = (
                ThresholdStatus.DEGENERATE_BOUNDARIES
                if lower == upper
                else ThresholdStatus.OK
            )
            output.append(
                ThresholdRow(
                    config.arm_id,
                    current,
                    phase,
                    config.history_kind,
                    len(selected),
                    config.lower_probability,
                    config.upper_probability,
                    float(lower),
                    float(upper),
                    True,
                    status,
                    dependency_keys,
                )
            )
    return ThresholdTable(config.arm_id, tuple(output))


@dataclass(frozen=True)
class AssignmentRow:
    arm_id: str
    session_id: int
    ts_event_ns: int
    tau_ns: int
    observation_bucket_ct: str
    session_phase: str
    scale_value: float
    scale_valid: bool
    seasonal_profile: float
    seasonal_valid: bool
    vol_rel: float
    vol_rel_valid: bool
    vol_rel_status: VolRelStatus
    upstream_stage: UpstreamStage | None
    lower_threshold: float
    upper_threshold: float
    threshold_status: ThresholdStatus
    category_code: int
    category_name: str
    assignment_status: AssignmentStatus
    calendar_session_class: str
    holiday_adjacent: bool
    data_quality_status: str


@dataclass(frozen=True)
class AssignmentTable:
    arm_id: str
    rows: tuple[AssignmentRow, ...]

    def __post_init__(self) -> None:
        if not self.rows:
            raise SpineError("assignment table must be nonempty")
        keys = [(row.session_id, row.tau_ns) for row in self.rows]
        if keys != sorted(keys) or len(set(keys)) != len(keys):
            raise SpineError("assignment rows must be unique and ordered")
        for row in self.rows:
            if row.arm_id != self.arm_id:
                raise SpineError("assignment table mixes arm identifiers")
            if not isinstance(row.vol_rel_status, VolRelStatus):
                raise SpineError("assignment vol_rel status is outside the closed vocabulary")
            if row.upstream_stage is not None and not isinstance(
                row.upstream_stage, UpstreamStage
            ):
                raise SpineError("assignment upstream stage is outside the closed vocabulary")
            if not isinstance(row.threshold_status, ThresholdStatus):
                raise SpineError("assignment threshold status is outside the closed vocabulary")
            if not isinstance(row.assignment_status, AssignmentStatus):
                raise SpineError("assignment status is outside the closed vocabulary")
            if row.calendar_session_class not in {
                "regular",
                "scheduled_early_close",
                "full_exchange_holiday",
                "unscheduled_closure",
                "calendar_classification_missing",
            }:
                raise SpineError("assignment calendar class is outside the closed vocabulary")
            if type(row.holiday_adjacent) is not bool:
                raise SpineError("assignment holiday_adjacent must be bool")
            for name in (
                "scale_value",
                "seasonal_profile",
                "vol_rel",
                "lower_threshold",
                "upper_threshold",
            ):
                value = getattr(row, name)
                if not isinstance(value, float) or not np.isfinite(value) or value < 0.0:
                    raise SpineError(f"assignment {name} must be finite and nonnegative")
            if type(row.category_code) is not int or row.category_code not in CATEGORY_ORDER:
                raise SpineError("assignment category code is outside the closed encoding")
            if row.category_name != CATEGORY_NAMES[row.category_code]:
                raise SpineError("assignment category name/code disagree")
            if (row.assignment_status is AssignmentStatus.OK) != (
                row.category_code != -1
            ):
                raise SpineError("assignment status and category disagree")
            if row.vol_rel_valid != (row.vol_rel_status is VolRelStatus.OK):
                raise SpineError("assignment vol_rel status and validity disagree")
            if row.vol_rel_status is VolRelStatus.UPSTREAM_UNDEFINED:
                if row.upstream_stage is None:
                    raise SpineError("assignment upstream-undefined vol_rel lacks its stage")
            elif row.upstream_stage is not None:
                raise SpineError("assignment upstream stage is present without upstream failure")
            if row.assignment_status is AssignmentStatus.UPSTREAM_UNDEFINED:
                if row.vol_rel_valid or row.vol_rel_status is VolRelStatus.OK:
                    raise SpineError("upstream-undefined assignment has defined vol_rel")
            elif row.assignment_status is AssignmentStatus.WARMUP:
                if not row.vol_rel_valid or row.threshold_status is not ThresholdStatus.INSUFFICIENT_THRESHOLD_HISTORY:
                    raise SpineError("warmup assignment requires defined vol_rel and threshold warmup")
            elif not row.vol_rel_valid or row.threshold_status not in {
                ThresholdStatus.OK,
                ThresholdStatus.DEGENERATE_BOUNDARIES,
            }:
                raise SpineError("defined assignment requires defined vol_rel and thresholds")
        object.__setattr__(
            self,
            "_by_key",
            MappingProxyType({(row.session_id, row.tau_ns): row for row in self.rows}),
        )


def build_assignments(
    config: ArmConfig,
    vol_rel: VolRelTable,
    thresholds: ThresholdTable,
    calendar: CalendarTable,
) -> AssignmentTable:
    if thresholds.arm_id != config.arm_id:
        raise SpineError("assignment threshold arm differs from config")
    output: list[AssignmentRow] = []
    for row in vol_rel.rows:
        threshold = thresholds.lookup(row.session_id, row.session_phase)
        calendar_row = calendar.lookup(row.session_id)
        calendar_class = (
            "calendar_classification_missing"
            if calendar_row is None
            else calendar_row.session_class
        )
        holiday_adjacent = False if calendar_row is None else calendar_row.holiday_adjacent
        category = -1
        if not row.vol_rel_valid:
            assignment_status = AssignmentStatus.UPSTREAM_UNDEFINED
        elif not threshold.threshold_valid:
            assignment_status = AssignmentStatus.WARMUP
        else:
            if row.vol_rel <= threshold.lower_threshold:
                category = 0
            elif row.vol_rel <= threshold.upper_threshold:
                category = 1
            else:
                category = 2
            assignment_status = AssignmentStatus.OK
        output.append(
            AssignmentRow(
                config.arm_id,
                row.session_id,
                row.ts_event_ns,
                row.tau_ns,
                row.observation_bucket_ct,
                row.session_phase,
                row.scale_value,
                row.scale_valid,
                row.seasonal_profile,
                row.seasonal_valid,
                row.vol_rel,
                row.vol_rel_valid,
                row.vol_rel_status,
                row.upstream_stage,
                threshold.lower_threshold,
                threshold.upper_threshold,
                threshold.threshold_status,
                category,
                CATEGORY_NAMES[category],
                assignment_status,
                calendar_class,
                holiday_adjacent,
                row.data_quality_status,
            )
        )
    return AssignmentTable(config.arm_id, tuple(output))


@dataclass(frozen=True)
class MigrationCell:
    primary_code: int
    alternative_code: int
    count: int

    def __post_init__(self) -> None:
        if type(self.primary_code) is not int or self.primary_code not in CATEGORY_ORDER:
            raise SpineError("migration primary code is outside the closed encoding")
        if type(self.alternative_code) is not int or self.alternative_code not in CATEGORY_ORDER:
            raise SpineError("migration alternative code is outside the closed encoding")
        if type(self.count) is not int or self.count < 0:
            raise SpineError("migration count must be a nonnegative built-in int")


@dataclass(frozen=True)
class MigrationSummary:
    primary_arm_id: str
    alternative_arm_id: str
    cells: tuple[MigrationCell, ...]
    common_defined: int
    changed_defined: int
    changed_fraction: float
    primary_defined_alternative_undefined: int
    primary_undefined_alternative_defined: int

    def __post_init__(self) -> None:
        expected_pairs = tuple(
            (left, right) for left in CATEGORY_ORDER for right in CATEGORY_ORDER
        )
        actual_pairs = tuple(
            (cell.primary_code, cell.alternative_code) for cell in self.cells
        )
        if actual_pairs != expected_pairs:
            raise SpineError("migration cells must emit the complete canonical 4x4 grid")
        for name in (
            "common_defined",
            "changed_defined",
            "primary_defined_alternative_undefined",
            "primary_undefined_alternative_defined",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise SpineError(f"migration {name} must be a nonnegative built-in int")
        if self.changed_defined > self.common_defined:
            raise SpineError("migration changed count exceeds common-defined support")
        derived_common = sum(
            cell.count
            for cell in self.cells
            if cell.primary_code != -1 and cell.alternative_code != -1
        )
        derived_changed = sum(
            cell.count
            for cell in self.cells
            if cell.primary_code != -1
            and cell.alternative_code != -1
            and cell.primary_code != cell.alternative_code
        )
        derived_primary_only = sum(
            cell.count
            for cell in self.cells
            if cell.primary_code != -1 and cell.alternative_code == -1
        )
        derived_alternative_only = sum(
            cell.count
            for cell in self.cells
            if cell.primary_code == -1 and cell.alternative_code != -1
        )
        if (
            derived_common != self.common_defined
            or derived_changed != self.changed_defined
            or derived_primary_only != self.primary_defined_alternative_undefined
            or derived_alternative_only != self.primary_undefined_alternative_defined
        ):
            raise SpineError("migration summary counts differ from the 4x4 cells")
        expected_fraction = (
            0.0
            if self.common_defined == 0
            else float(
                np.float64(self.changed_defined) / np.float64(self.common_defined)
            )
        )
        if self.changed_fraction != expected_fraction:
            raise SpineError("migration changed fraction differs from its counts")


def cell_migration(
    primary: AssignmentTable, alternative: AssignmentTable
) -> MigrationSummary:
    primary_keys = set(primary._by_key)
    alternative_keys = set(alternative._by_key)
    if primary_keys != alternative_keys:
        raise SpineError("migration assignment supports differ")
    counts = {(left, right): 0 for left in CATEGORY_ORDER for right in CATEGORY_ORDER}
    common = changed = primary_only = alternative_only = 0
    for key in sorted(primary_keys):
        left = primary._by_key[key].category_code
        right = alternative._by_key[key].category_code
        counts[(left, right)] += 1
        if left != -1 and right != -1:
            common += 1
            changed += int(left != right)
        elif left != -1:
            primary_only += 1
        elif right != -1:
            alternative_only += 1
    fraction = 0.0 if common == 0 else float(np.float64(changed) / np.float64(common))
    cells = tuple(
        MigrationCell(left, right, counts[(left, right)])
        for left in CATEGORY_ORDER
        for right in CATEGORY_ORDER
    )
    return MigrationSummary(
        primary.arm_id,
        alternative.arm_id,
        cells,
        common,
        changed,
        fraction,
        primary_only,
        alternative_only,
    )


@dataclass(frozen=True)
class UndefinedFractionRow:
    arm_id: str
    year: int
    session_phase: str
    undefined_count: int
    total_count: int
    undefined_fraction: float

    def __post_init__(self) -> None:
        if self.session_phase not in PHASE_ORDER:
            raise SpineError("undefined-fraction phase is outside the frozen vocabulary")
        if type(self.year) is not int or not 1900 <= self.year <= 2200:
            raise SpineError("undefined-fraction year is invalid")
        if (
            type(self.undefined_count) is not int
            or type(self.total_count) is not int
            or not 0 <= self.undefined_count <= self.total_count
            or self.total_count == 0
        ):
            raise SpineError("undefined-fraction counts are invalid")
        expected = float(
            np.float64(self.undefined_count) / np.float64(self.total_count)
        )
        if self.undefined_fraction != expected:
            raise SpineError("undefined fraction differs from its counts")


def assignment_undefined_fractions(
    assignments: AssignmentTable,
) -> tuple[UndefinedFractionRow, ...]:
    year_phase_groups: dict[tuple[int, str], list[AssignmentRow]] = {}
    for row in assignments.rows:
        year_phase_groups.setdefault(
            (row.session_id // 10_000, row.session_phase), []
        ).append(row)
    output = []
    for (year, phase) in sorted(
        year_phase_groups, key=lambda key: (key[0], PHASE_ORDER.index(key[1]))
    ):
        rows = year_phase_groups[(year, phase)]
        undefined = sum(row.category_code == -1 for row in rows)
        output.append(
            UndefinedFractionRow(
                assignments.arm_id,
                year,
                phase,
                undefined,
                len(rows),
                float(np.float64(undefined) / np.float64(len(rows))),
            )
        )
    return tuple(output)
