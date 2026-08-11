"""Phase 9 prevalence measurement on horizon-invariant state support.

This module consumes Phase 7 assignments and the support columns already emitted
by :func:`mnq_lab.outcomes.completion.anchor_outcome_completion`.  It does not
derive outcome availability, execute over a corpus, or write an artifact.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np

from mnq_lab import SpineError
from mnq_lab.conditioners.arms import ARM_CONFIGS
from mnq_lab.conditioners.assignments import CATEGORY_NAMES, PHASE_ORDER
from mnq_lab.conditioners.status import AssignmentStatus, ResetReason
from mnq_lab.outcomes.completion import ESTIMAND_FULLY_LABELED, ESTIMAND_OBSERVED
from mnq_lab.spine.timemodel import BAR_NS, TimeModel

HORIZONS = (15, 30, 60)
ESTIMANDS = (ESTIMAND_FULLY_LABELED, ESTIMAND_OBSERVED)
DECLARED_ARM_IDS = tuple(config.arm_id for config in ARM_CONFIGS)
DECLARED_CATEGORIES = tuple(
    (code, CATEGORY_NAMES[code]) for code in (0, 1, 2)
)
ELIGIBILITY_COLUMNS = tuple(
    f"outcome_eligible_{estimand}_h{horizon}"
    for estimand in ESTIMANDS
    for horizon in HORIZONS
)

STATUS_OK = "ok"
STATUS_EMPTY_STATE = "empty_state"
STATUS_NO_STATE_SUPPORT = "unsupported_no_state_anchor_support"
STATUS_NO_ARM_ROWS = "unsupported_no_arm_rows"
WEIGHT_ESS_STATUS = "not_computed_in_phase9"

SUMMARY_COLUMNS = (
    "arm_id",
    "category_code",
    "category_name",
    "status",
    "state_anchors",
    "n_anchors",
    "n_sessions",
    "weight_ess",
    "weight_ess_status",
    *ELIGIBILITY_COLUMNS,
    "bar_occupancy",
    "bar_occupancy_valid",
    "episodes",
    "session_presence",
    "entry_transitions",
    "exit_transitions",
)
EPISODE_LENGTH_COLUMNS = (
    "arm_id",
    "category_code",
    "category_name",
    "episode_ordinal",
    "episode_length",
    "status",
)

_ASSIGNMENT_VALUES = frozenset(status.value for status in AssignmentStatus)
_RESET_VALUES = frozenset(reason.value for reason in ResetReason)

__all__ = [
    "DECLARED_ARM_IDS",
    "DECLARED_CATEGORIES",
    "ELIGIBILITY_COLUMNS",
    "EPISODE_LENGTH_COLUMNS",
    "ESTIMANDS",
    "HORIZONS",
    "SUMMARY_COLUMNS",
    "PrevalenceInput",
    "PrevalenceResult",
    "PrevalenceTable",
    "anchor_observation_keys",
    "measure_prevalence",
    "state_anchor_counts_by_horizon",
    "validate_horizon_support",
]


@dataclass(frozen=True)
class PrevalenceInput:
    """Aligned assignment and completion columns; no field is recomputed here."""

    arm_id: np.ndarray
    session_id: np.ndarray
    ts_event_ns: np.ndarray
    tau_ns: np.ndarray
    observation_bucket_ct: np.ndarray
    session_phase: np.ndarray
    category_code: np.ndarray
    assignment_status: np.ndarray
    reset_reason: np.ndarray
    state_anchor: np.ndarray
    eligibility_columns: tuple[tuple[str, np.ndarray], ...]


@dataclass(frozen=True)
class PrevalenceTable:
    name: str
    columns: tuple[tuple[str, np.ndarray], ...]

    def __post_init__(self) -> None:
        schemas = {
            "summary": SUMMARY_COLUMNS,
            "episode_lengths": EPISODE_LENGTH_COLUMNS,
        }
        if self.name not in schemas:
            raise SpineError(f"undeclared Phase 9 output table: {self.name!r}")
        names = tuple(name for name, _ in self.columns)
        if names != schemas[self.name]:
            raise SpineError(f"Phase 9 {self.name} columns differ from the schema")
        sizes: set[int] = set()
        for name, raw in self.columns:
            values = np.asarray(raw)
            if values.ndim != 1 or values.dtype.kind == "O":
                raise SpineError(
                    "Phase 9 columns must be one-dimensional non-object arrays"
                )
            sizes.add(int(values.size))
            if name in {
                "category_code",
                "state_anchors",
                "n_anchors",
                "n_sessions",
                *ELIGIBILITY_COLUMNS,
                "episodes",
                "session_presence",
                "entry_transitions",
                "exit_transitions",
                "episode_ordinal",
                "episode_length",
            } and values.dtype.kind not in {"i", "u"}:
                raise SpineError(f"Phase 9 integer column {name!r} has wrong dtype")
            if name in {"weight_ess", "bar_occupancy"} and values.dtype.kind != "f":
                raise SpineError(f"Phase 9 float column {name!r} has wrong dtype")
            if name == "bar_occupancy_valid" and values.dtype.kind != "b":
                raise SpineError("Phase 9 bar_occupancy_valid must be bool")
            if name not in {
                "category_code",
                "state_anchors",
                "n_anchors",
                "n_sessions",
                *ELIGIBILITY_COLUMNS,
                "episodes",
                "session_presence",
                "entry_transitions",
                "exit_transitions",
                "episode_ordinal",
                "episode_length",
                "weight_ess",
                "bar_occupancy",
                "bar_occupancy_valid",
            } and values.dtype.kind != "U":
                raise SpineError(f"Phase 9 label column {name!r} has wrong dtype")
        if len(sizes) != 1:
            raise SpineError("Phase 9 table columns must have equal row counts")
        for index, name in enumerate(names):
            if name == "n_anchors" and names[index : index + 3] != (
                "n_anchors",
                "n_sessions",
                "weight_ess",
            ):
                raise SpineError(
                    "n_anchors must be immediately accompanied by n_sessions and weight_ess"
                )

    @property
    def row_count(self) -> int:
        return int(np.asarray(self.columns[0][1]).size)

    def column(self, name: str) -> np.ndarray:
        for candidate, values in self.columns:
            if candidate == name:
                return values
        raise SpineError(f"Phase 9 table has no column {name!r}")


@dataclass(frozen=True)
class PrevalenceResult:
    summary: PrevalenceTable
    episode_lengths: PrevalenceTable

    def __post_init__(self) -> None:
        if self.summary.name != "summary" or self.episode_lengths.name != "episode_lengths":
            raise SpineError("Phase 9 result tables are mislabelled")


def _one_dimensional(raw: Any, name: str) -> np.ndarray:
    try:
        values = np.asarray(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpineError(f"{name} cannot be converted to an array: {exc}") from exc
    if values.ndim != 1 or values.dtype.kind == "O":
        raise SpineError(f"{name} must be a one-dimensional non-object array")
    return values


def anchor_observation_keys(
    ts_event_ns: np.ndarray, *, time_model: TimeModel | None = None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return tau, CT HH:MM bucket, and phase, all keyed from the bar close."""

    labels = _one_dimensional(ts_event_ns, "ts_event_ns")
    if labels.dtype != np.int64:
        raise SpineError("ts_event_ns must be int64 UTC nanoseconds")
    model = TimeModel.from_constants() if time_model is None else time_model
    tau = model.observation_times_ns(labels)
    minutes = model.ct_minute_of_day(tau)
    buckets = np.asarray(
        [f"{int(minute) // 60:02d}:{int(minute) % 60:02d}" for minute in minutes],
        dtype="U5",
    )
    phases = np.asarray(model.phase_of(minutes), dtype="U16")
    return tau, buckets, phases


def state_anchor_counts_by_horizon(
    state_anchor: np.ndarray, category_mask: np.ndarray
) -> tuple[tuple[int, int], ...]:
    """Repeat the one state-support count across horizons without future masks."""

    state = _one_dimensional(state_anchor, "state_anchor")
    category = _one_dimensional(category_mask, "category_mask")
    if state.dtype.kind != "b" or category.dtype.kind != "b" or state.shape != category.shape:
        raise SpineError("state_anchor and category_mask must be aligned bool vectors")
    count = int(np.count_nonzero(state & category))
    return tuple((horizon, count) for horizon in HORIZONS)


def validate_horizon_support(
    state_counts: Iterable[tuple[int, int]],
    eligible_counts: Iterable[tuple[str, Iterable[tuple[int, int]]]],
    *,
    require_strict_decrease: bool = False,
) -> None:
    """Fail closed on horizon-dependent prevalence or expanding eligibility."""

    state = tuple((int(horizon), int(count)) for horizon, count in state_counts)
    if tuple(horizon for horizon, _ in state) != HORIZONS:
        raise SpineError("state support horizons differ from the declared order")
    if len({count for _, count in state}) != 1:
        raise SpineError("state-anchor prevalence depends on outcome horizon")

    any_strict = False
    estimand_rows = tuple(eligible_counts)
    if tuple(name for name, _ in estimand_rows) != ESTIMANDS:
        raise SpineError("eligibility estimands differ from the declared order")
    for estimand, raw_counts in estimand_rows:
        counts = tuple((int(horizon), int(count)) for horizon, count in raw_counts)
        if tuple(horizon for horizon, _ in counts) != HORIZONS:
            raise SpineError(f"{estimand} horizons differ from the declared order")
        values = tuple(count for _, count in counts)
        if any(left < right for left, right in zip(values, values[1:])):
            raise SpineError(f"{estimand} outcome eligibility increases with horizon")
        any_strict = any_strict or any(
            left > right for left, right in zip(values, values[1:])
        )
    if require_strict_decrease and not any_strict:
        raise SpineError("fixture has no strict outcome-eligibility decrease")


def _declared_inventory(
    declared_arm_ids: Iterable[str], declared_categories: Iterable[tuple[int, str]]
) -> tuple[tuple[str, ...], tuple[tuple[int, str], ...]]:
    arms = tuple(declared_arm_ids)
    categories = tuple(declared_categories)
    if not arms or len(set(arms)) != len(arms) or any(
        not isinstance(arm, str) or not arm for arm in arms
    ):
        raise SpineError("declared arm identifiers must be unique nonempty strings")
    if not categories or len({code for code, _ in categories}) != len(categories):
        raise SpineError("declared categories must have unique codes")
    for code, name in categories:
        if type(code) is not int or code not in {0, 1, 2}:
            raise SpineError("declared category code is outside the closed encoding")
        if name != CATEGORY_NAMES[code]:
            raise SpineError("declared category name/code disagree")
    return arms, categories


def _validated_input(
    source: PrevalenceInput, declared_arm_ids: tuple[str, ...]
) -> dict[str, np.ndarray]:
    if not isinstance(source, PrevalenceInput):
        raise SpineError("Phase 9 input must be PrevalenceInput")
    raw_columns = {
        "arm_id": source.arm_id,
        "session_id": source.session_id,
        "ts_event_ns": source.ts_event_ns,
        "tau_ns": source.tau_ns,
        "observation_bucket_ct": source.observation_bucket_ct,
        "session_phase": source.session_phase,
        "category_code": source.category_code,
        "assignment_status": source.assignment_status,
        "reset_reason": source.reset_reason,
        "state_anchor": source.state_anchor,
    }
    columns = {name: _one_dimensional(raw, name) for name, raw in raw_columns.items()}
    sizes = {int(values.size) for values in columns.values()}
    if len(sizes) != 1:
        raise SpineError("Phase 9 input columns must have equal row counts")
    row_count = next(iter(sizes))

    if columns["arm_id"].dtype.kind != "U":
        raise SpineError("arm_id must be a unicode array")
    if columns["session_id"].dtype.kind not in {"i", "u"}:
        raise SpineError("session_id must be an integer array")
    if columns["ts_event_ns"].dtype != np.int64 or columns["tau_ns"].dtype != np.int64:
        raise SpineError("timestamps must be int64 UTC nanoseconds")
    if columns["observation_bucket_ct"].dtype.kind != "U":
        raise SpineError("observation_bucket_ct must be a unicode array")
    if columns["session_phase"].dtype.kind != "U":
        raise SpineError("session_phase must be a unicode array")
    if columns["category_code"].dtype.kind not in {"i", "u"}:
        raise SpineError("category_code must be an integer array")
    if columns["assignment_status"].dtype.kind != "U":
        raise SpineError("assignment_status must be a unicode array")
    if columns["reset_reason"].dtype.kind != "U":
        raise SpineError("reset_reason must be a unicode array")
    if columns["state_anchor"].dtype.kind != "b":
        raise SpineError("state_anchor must be a bool array")

    eligibility = tuple(source.eligibility_columns)
    if tuple(name for name, _ in eligibility) != ELIGIBILITY_COLUMNS:
        raise SpineError("outcome-eligibility columns differ from the declared schema")
    for name, raw in eligibility:
        values = _one_dimensional(raw, name)
        if values.dtype.kind != "b" or values.size != row_count:
            raise SpineError(f"{name} must be an aligned bool vector")
        columns[name] = values

    arm_values = columns["arm_id"]
    unknown_arms = set(arm_values.tolist()) - set(declared_arm_ids)
    if unknown_arms:
        raise SpineError(f"input contains an undeclared arm: {min(unknown_arms)!r}")
    arm_positions = {arm: index for index, arm in enumerate(declared_arm_ids)}
    observed_positions = np.asarray(
        [arm_positions[str(arm)] for arm in arm_values], dtype=np.int64
    )
    if observed_positions.size > 1 and np.any(np.diff(observed_positions) < 0):
        raise SpineError("input arm blocks differ from declared order")

    for arm in declared_arm_ids:
        mask = arm_values == arm
        labels = columns["ts_event_ns"][mask]
        if labels.size > 1 and np.any(np.diff(labels) <= 0):
            raise SpineError(f"timestamps for arm {arm!r} are not strictly chronological")

    codes = columns["category_code"]
    if np.any(~np.isin(codes, (-1, 0, 1, 2))):
        raise SpineError("category_code is outside the closed encoding")
    statuses = columns["assignment_status"]
    if set(statuses.tolist()) - _ASSIGNMENT_VALUES:
        raise SpineError("assignment_status is outside the closed vocabulary")
    if np.any((statuses == AssignmentStatus.OK.value) != (codes >= 0)):
        raise SpineError("assignment status and category disagree")
    resets = columns["reset_reason"]
    if set(resets.tolist()) - _RESET_VALUES:
        raise SpineError("reset_reason is outside the closed vocabulary")
    if set(columns["session_phase"].tolist()) - set(PHASE_ORDER):
        raise SpineError("session_phase is outside the closed vocabulary")

    expected_tau, expected_buckets, expected_phases = anchor_observation_keys(
        columns["ts_event_ns"]
    )
    if not np.array_equal(columns["tau_ns"], expected_tau):
        raise SpineError("tau_ns is not the bar-open timestamp plus BAR_NS")
    if not np.array_equal(columns["observation_bucket_ct"], expected_buckets):
        raise SpineError("time-of-day bucket is not keyed on anchor observation time")
    if not np.array_equal(columns["session_phase"], expected_phases):
        raise SpineError("session phase is not keyed on anchor observation time")

    state = columns["state_anchor"]
    for name in ELIGIBILITY_COLUMNS:
        if np.any(columns[name] & ~state):
            raise SpineError(f"{name} includes a row outside state_anchor support")
    for estimand in ESTIMANDS:
        prior = columns[f"outcome_eligible_{estimand}_h{HORIZONS[0]}"]
        for horizon in HORIZONS[1:]:
            current = columns[f"outcome_eligible_{estimand}_h{horizon}"]
            if np.any(current & ~prior):
                raise SpineError(f"{estimand} row eligibility increases with horizon")
            prior = current
    return columns


def _episode_measurements(
    columns: dict[str, np.ndarray], arm_mask: np.ndarray, category_codes: tuple[int, ...]
) -> tuple[dict[int, tuple[int, ...]], dict[int, int], dict[int, int]]:
    positions = np.flatnonzero(arm_mask)
    lengths: dict[int, list[int]] = {code: [] for code in category_codes}
    entries = {code: 0 for code in category_codes}
    exits = {code: 0 for code in category_codes}
    active_code: int | None = None
    active_length = 0
    previous_position: int | None = None

    def close_active() -> None:
        nonlocal active_code, active_length
        if active_code is not None:
            lengths[active_code].append(active_length)
        active_code = None
        active_length = 0

    for position_value in positions:
        position = int(position_value)
        defined = bool(
            columns["state_anchor"][position]
            and columns["assignment_status"][position] == AssignmentStatus.OK.value
        )
        edge = False
        if previous_position is not None:
            previous_defined = bool(
                columns["state_anchor"][previous_position]
                and columns["assignment_status"][previous_position]
                == AssignmentStatus.OK.value
            )
            gap_reset = bool(
                columns["reset_reason"][position] == ResetReason.GAP_RESET.value
            )
            roll_reset = bool(
                columns["reset_reason"][position] == ResetReason.ROLL_RESET.value
            )
            edge = bool(
                defined
                and previous_defined
                and columns["session_id"][previous_position]
                == columns["session_id"][position]
                and columns["tau_ns"][position]
                == columns["tau_ns"][previous_position] + int(BAR_NS)
                and not gap_reset
                and not roll_reset
            )

        if not defined:
            close_active()
        else:
            code = int(columns["category_code"][position])
            if edge and active_code == code:
                active_length += 1
            else:
                if edge:
                    previous_code = int(columns["category_code"][previous_position])
                    if previous_code != code:
                        if previous_code in exits:
                            exits[previous_code] += 1
                        if code in entries:
                            entries[code] += 1
                close_active()
                active_code = code
                active_length = 1
        previous_position = position
    close_active()
    return (
        {code: tuple(values) for code, values in lengths.items()},
        entries,
        exits,
    )


def _table_from_records(
    name: str, schema: tuple[str, ...], records: list[dict[str, Any]]
) -> PrevalenceTable:
    integer_columns = {
        "category_code",
        "state_anchors",
        "n_anchors",
        "n_sessions",
        *ELIGIBILITY_COLUMNS,
        "episodes",
        "session_presence",
        "entry_transitions",
        "exit_transitions",
        "episode_ordinal",
        "episode_length",
    }
    float_columns = {"weight_ess", "bar_occupancy"}
    bool_columns = {"bar_occupancy_valid"}
    columns: list[tuple[str, np.ndarray]] = []
    for column in schema:
        raw = [record[column] for record in records]
        if column in integer_columns:
            values = np.asarray(raw, dtype=np.int64)
        elif column in float_columns:
            values = np.asarray(raw, dtype=np.float64)
        elif column in bool_columns:
            values = np.asarray(raw, dtype=np.bool_)
        else:
            values = np.asarray(raw, dtype="U64")
        columns.append((column, values))
    return PrevalenceTable(name, tuple(columns))


def measure_prevalence(
    source: PrevalenceInput,
    *,
    declared_arm_ids: Iterable[str] = DECLARED_ARM_IDS,
    declared_categories: Iterable[tuple[int, str]] = DECLARED_CATEGORIES,
) -> PrevalenceResult:
    """Measure every declared arm-category cell without a corpus execution path."""

    arms, categories = _declared_inventory(declared_arm_ids, declared_categories)
    columns = _validated_input(source, arms)
    category_codes = tuple(code for code, _ in categories)
    summary_records: list[dict[str, Any]] = []
    length_records: list[dict[str, Any]] = []

    for arm in arms:
        arm_mask = columns["arm_id"] == arm
        arm_rows = int(np.count_nonzero(arm_mask))
        state_mask = arm_mask & columns["state_anchor"]
        n_anchors = int(np.count_nonzero(state_mask))
        n_sessions = int(np.unique(columns["session_id"][state_mask]).size)
        lengths, entries, exits = _episode_measurements(
            columns, arm_mask, category_codes
        )

        for category_code, category_name in categories:
            category_mask = (
                arm_mask
                & columns["state_anchor"]
                & (columns["assignment_status"] == AssignmentStatus.OK.value)
                & (columns["category_code"] == category_code)
            )
            state_counts = state_anchor_counts_by_horizon(
                columns["state_anchor"][arm_mask],
                category_mask[arm_mask],
            )
            eligible_counts = tuple(
                (
                    estimand,
                    tuple(
                        (
                            horizon,
                            int(
                                np.count_nonzero(
                                    category_mask
                                    & columns[
                                        f"outcome_eligible_{estimand}_h{horizon}"
                                    ]
                                )
                            ),
                        )
                        for horizon in HORIZONS
                    ),
                )
                for estimand in ESTIMANDS
            )
            validate_horizon_support(state_counts, eligible_counts)
            state_count = state_counts[0][1]
            if arm_rows == 0:
                status = STATUS_NO_ARM_ROWS
            elif n_anchors == 0:
                status = STATUS_NO_STATE_SUPPORT
            elif state_count == 0:
                status = STATUS_EMPTY_STATE
            else:
                status = STATUS_OK

            record: dict[str, Any] = {
                "arm_id": arm,
                "category_code": category_code,
                "category_name": category_name,
                "status": status,
                "state_anchors": state_count,
                "n_anchors": n_anchors,
                "n_sessions": n_sessions,
                "weight_ess": float("nan"),
                "weight_ess_status": WEIGHT_ESS_STATUS,
                "bar_occupancy": (
                    float(np.float64(state_count) / np.float64(n_anchors))
                    if n_anchors
                    else float("nan")
                ),
                "bar_occupancy_valid": bool(n_anchors),
                "episodes": len(lengths[category_code]),
                "session_presence": int(
                    np.unique(columns["session_id"][category_mask]).size
                ),
                "entry_transitions": entries[category_code],
                "exit_transitions": exits[category_code],
            }
            for estimand, counts in eligible_counts:
                for horizon, count in counts:
                    record[f"outcome_eligible_{estimand}_h{horizon}"] = count
            summary_records.append(record)

            episode_lengths = lengths[category_code]
            if episode_lengths:
                for ordinal, episode_length in enumerate(episode_lengths):
                    length_records.append(
                        {
                            "arm_id": arm,
                            "category_code": category_code,
                            "category_name": category_name,
                            "episode_ordinal": ordinal,
                            "episode_length": episode_length,
                            "status": STATUS_OK,
                        }
                    )
            else:
                length_records.append(
                    {
                        "arm_id": arm,
                        "category_code": category_code,
                        "category_name": category_name,
                        "episode_ordinal": -1,
                        "episode_length": 0,
                        "status": status,
                    }
                )

    return PrevalenceResult(
        summary=_table_from_records("summary", SUMMARY_COLUMNS, summary_records),
        episode_lengths=_table_from_records(
            "episode_lengths", EPISODE_LENGTH_COLUMNS, length_records
        ),
    )
