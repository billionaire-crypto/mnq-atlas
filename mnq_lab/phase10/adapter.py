"""Exact-key, read-only adapter for the frozen Phase 10 formal population."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from mnq_lab import SpineError
from mnq_lab.conditioners.pipeline import PRIMARY_ARM
from mnq_lab.phase10.contract import (
    PERMUTATION_SESSIONS,
    PRIMARY_HORIZON_MINUTES,
    PRIMARY_OUTCOME,
    PRIMARY_PATH_ESTIMAND,
    artifact_metadata,
)
from mnq_lab.phase8.production import _year_quarter
from mnq_lab.phase9.adapter import (
    _assert_unique_keys,
    _first_key_mismatch,
    _read_artifact_column,
    _read_manifest,
    load_exploration_prevalence_input,
)
from mnq_lab.phase9.prevalence import anchor_observation_keys


@dataclass(frozen=True)
class FormalJoinReconciliation:
    verified_anchor_rows: int
    verified_arm_rows: int
    schedule_excluded_sessions: int
    schedule_excluded_rows: int
    active_sessions: int
    regular_full_rth_sessions: int
    holiday_adjacent_sessions_removed: int
    truncated_sessions_removed: int
    formal_sessions: int
    formal_rows: int
    anchors_per_session: int


@dataclass(frozen=True)
class FormalCorpus:
    session_ids: np.ndarray
    calendar_quarters: np.ndarray
    calendar_years: np.ndarray
    observation_grid: np.ndarray
    phase_grid: np.ndarray
    ts_event_ns: np.ndarray
    state_codes: np.ndarray
    state_valid: np.ndarray
    downward_excursion_ticks: np.ndarray
    outcome_valid: np.ndarray
    window_fits_rth: np.ndarray
    reconciliation: FormalJoinReconciliation
    metadata: dict[str, Any]


def _readonly(values: Any, dtype: Any | None = None) -> np.ndarray:
    result = np.array(values, dtype=dtype, copy=True)
    result.setflags(write=False)
    return result


def _reshape_exact_sessions(
    sessions: np.ndarray,
    columns: tuple[np.ndarray, ...],
) -> tuple[np.ndarray, tuple[np.ndarray, ...], int]:
    boundaries = np.flatnonzero(sessions[1:] != sessions[:-1]) + 1
    starts = np.concatenate((np.asarray([0], dtype=np.intp), boundaries))
    stops = np.concatenate((boundaries, np.asarray([sessions.size], dtype=np.intp)))
    counts = stops - starts
    if counts.size == 0 or not bool(np.all(counts == counts[0])):
        first = 0 if counts.size == 0 else int(np.flatnonzero(counts != counts[0])[0])
        raise SpineError(
            "Phase 10 formal grid has unequal session length at block "
            f"{first}; cause class missing_bars/timestamps"
        )
    width = int(counts[0])
    session_keys = sessions[starts]
    if len(set(session_keys.tolist())) != session_keys.size:
        raise SpineError("Phase 10 session rows are not one contiguous block")
    reshaped = tuple(np.asarray(column).reshape(session_keys.size, width) for column in columns)
    return session_keys, reshaped, width


def load_formal_corpus(root: Path) -> FormalCorpus:
    """Load only the session-aware v2 exploration corpus and freeze 900 sessions."""
    source_root = Path(root).resolve()
    verified = load_exploration_prevalence_input(source_root)
    source = verified.source
    primary_mask = np.asarray(source.arm_id == PRIMARY_ARM)
    if int(np.count_nonzero(primary_mask)) != verified.reconciliation.anchor_count:
        raise SpineError("Phase 10 primary arm row count differs from Phase 9")
    primary_session = np.asarray(source.session_id[primary_mask])
    primary_ts = np.asarray(source.ts_event_ns[primary_mask])
    primary_tau = np.asarray(source.tau_ns[primary_mask])
    primary_bucket = np.asarray(source.observation_bucket_ct[primary_mask])
    primary_phase = np.asarray(source.session_phase[primary_mask])
    primary_code = np.asarray(source.category_code[primary_mask])
    primary_status = np.asarray(source.assignment_status[primary_mask])
    _assert_unique_keys(primary_session, primary_tau, "Phase 10 primary assignment")
    expected_tau, expected_bucket, expected_phase = anchor_observation_keys(primary_ts)
    if not np.array_equal(primary_tau, expected_tau):
        raise SpineError(
            "Phase 10 observation time is not bar open plus one bar; "
            "cause class timestamps"
        )
    if not np.array_equal(primary_bucket, expected_bucket) or not np.array_equal(
        primary_phase, expected_phase
    ):
        raise SpineError(
            "Phase 10 stored canonical observation grid differs from its tau keys; "
            "cause class timestamps"
        )

    phase7_root = source_root / "phase7"
    unit_root = source_root / "unit_o"
    phase7 = _read_manifest(phase7_root / "manifest.json", "Phase 7")
    unit = _read_manifest(unit_root / "manifest.json", "Unit O")
    assignment_record = phase7.get("tables", {}).get("assignments", {})
    assignment_arm = _read_artifact_column(
        phase7_root, assignment_record, "arm_id"
    )
    direct_primary = assignment_arm == PRIMARY_ARM
    extra = {
        name: _read_artifact_column(phase7_root, assignment_record, name)[direct_primary]
        for name in (
            "session_id",
            "tau_ns",
            "calendar_session_class",
            "holiday_adjacent",
            "data_quality_status",
        )
    }
    _first_key_mismatch(
        primary_session,
        primary_tau,
        extra["session_id"],
        extra["tau_ns"],
        left_label="Phase9-verified primary",
        right_label="Phase10 population metadata",
    )

    unit_columns = {
        name: _read_artifact_column(unit_root, unit, name)
        for name in (
            "estimand",
            "horizon_minutes",
            "session_id",
            "ts_event_ns",
            "tau_ns",
            "session_phase",
            PRIMARY_OUTCOME,
            "outcome_valid",
            "window_fits_rth",
        )
    }
    unit_mask = (
        (unit_columns["estimand"] == PRIMARY_PATH_ESTIMAND)
        & (unit_columns["horizon_minutes"] == PRIMARY_HORIZON_MINUTES)
    )
    unit_slice = {name: values[unit_mask] for name, values in unit_columns.items()}
    _assert_unique_keys(
        unit_slice["session_id"], unit_slice["tau_ns"], "Phase 10 Unit O slice"
    )
    _first_key_mismatch(
        primary_session,
        primary_tau,
        unit_slice["session_id"],
        unit_slice["tau_ns"],
        left_label="Phase9-verified primary",
        right_label="Phase10 Unit O",
    )
    if not np.array_equal(primary_ts, unit_slice["ts_event_ns"]):
        raise SpineError("Phase 10 bar-label timestamps differ; cause class timestamps")
    if not np.array_equal(primary_phase, unit_slice["session_phase"]):
        raise SpineError("Phase 10 imported phase labels differ; cause class timestamps")

    session_class = np.asarray(extra["calendar_session_class"])
    holiday_adjacent = np.asarray(extra["holiday_adjacent"], dtype=np.bool_)
    data_quality = np.asarray(extra["data_quality_status"])
    regular = session_class == "regular"
    nonadjacent = ~holiday_adjacent
    resolved = data_quality == "ok"
    keep = regular & nonadjacent & resolved
    active_sessions = int(np.unique(primary_session).size)
    regular_sessions = int(np.unique(primary_session[regular]).size)
    removed_adjacent = int(np.unique(primary_session[regular & holiday_adjacent]).size)
    removed_truncated = int(
        np.unique(primary_session[regular & nonadjacent & ~resolved]).size
    )

    filtered_session = primary_session[keep]
    aligned = (
        primary_bucket[keep],
        primary_phase[keep],
        primary_ts[keep],
        primary_code[keep],
        primary_status[keep] == "ok",
        unit_slice[PRIMARY_OUTCOME][keep],
        unit_slice["outcome_valid"][keep],
        unit_slice["window_fits_rth"][keep],
    )
    session_keys, matrices, width = _reshape_exact_sessions(filtered_session, aligned)
    (
        bucket_matrix,
        phase_matrix,
        ts_matrix,
        code_matrix,
        state_valid_matrix,
        outcome_matrix,
        outcome_valid_matrix,
        window_matrix,
    ) = matrices
    if session_keys.size != PERMUTATION_SESSIONS:
        raise SpineError(
            "Phase 10 realized formal population differs: "
            f"{session_keys.size} != {PERMUTATION_SESSIONS}; cause class source_revision"
        )
    if width != 78:
        raise SpineError(
            f"Phase 10 canonical observation grid has {width} anchors, expected 78"
        )
    if not bool(np.all(bucket_matrix == bucket_matrix[0])):
        mismatch = np.argwhere(bucket_matrix != bucket_matrix[0])[0]
        raise SpineError(
            "Phase 10 canonical observation-time grid differs at session block "
            f"{int(mismatch[0])}, position {int(mismatch[1])}; cause class timestamps"
        )
    if not bool(np.all(phase_matrix == phase_matrix[0])):
        mismatch = np.argwhere(phase_matrix != phase_matrix[0])[0]
        raise SpineError(
            "Phase 10 imported phase grid differs at session block "
            f"{int(mismatch[0])}, position {int(mismatch[1])}; cause class timestamps"
        )
    quarters_by_row = _year_quarter(filtered_session)
    quarter_matrix = quarters_by_row.reshape(session_keys.size, width)
    if not bool(np.all(quarter_matrix == quarter_matrix[:, :1])):
        raise SpineError("Phase 10 a session crosses calendar-quarter strata")
    reconciliation = FormalJoinReconciliation(
        verified_anchor_rows=verified.reconciliation.anchor_count,
        verified_arm_rows=verified.reconciliation.assignment_rows,
        schedule_excluded_sessions=verified.reconciliation.excluded_session_count,
        schedule_excluded_rows=verified.reconciliation.excluded_completion_rows,
        active_sessions=active_sessions,
        regular_full_rth_sessions=regular_sessions,
        holiday_adjacent_sessions_removed=removed_adjacent,
        truncated_sessions_removed=removed_truncated,
        formal_sessions=int(session_keys.size),
        formal_rows=int(filtered_session.size),
        anchors_per_session=width,
    )
    if reconciliation != FormalJoinReconciliation(
        78_390,
        783_900,
        4,
        312,
        1_005,
        972,
        70,
        2,
        900,
        70_200,
        78,
    ):
        raise SpineError("Phase 10 population reconciliation differs from preregistration")
    return FormalCorpus(
        session_ids=_readonly(session_keys, np.int32),
        calendar_quarters=_readonly(quarter_matrix[:, 0]),
        calendar_years=_readonly(session_keys.astype(np.int64) // 10_000),
        observation_grid=_readonly(bucket_matrix[0]),
        phase_grid=_readonly(phase_matrix[0]),
        ts_event_ns=_readonly(ts_matrix, np.int64),
        state_codes=_readonly(code_matrix, np.int8),
        state_valid=_readonly(state_valid_matrix, np.bool_),
        downward_excursion_ticks=_readonly(outcome_matrix, np.int32),
        outcome_valid=_readonly(outcome_valid_matrix, np.bool_),
        window_fits_rth=_readonly(window_matrix, np.bool_),
        reconciliation=reconciliation,
        metadata=artifact_metadata(),
    )
