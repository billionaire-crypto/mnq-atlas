"""Exact-key, read-only adapter from exploration artifacts to Phase 9 input."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from mnq_lab import SpineError
from mnq_lab.conditioners.arms import ARM_CONFIGS
from mnq_lab.conditioners.pipeline import PRIMARY_ARM, SCALE_SOURCE_ARMS
from mnq_lab.constants import REPO_ROOT
from mnq_lab.outcomes.completion import anchor_outcome_completion
from mnq_lab.outcomes.excursions import ESTIMAND_ORDER, OUTCOME_SCHEMA
from mnq_lab.phase9.prevalence import ELIGIBILITY_COLUMNS, HORIZONS, PrevalenceInput
from mnq_lab.spine.availability import load_session_schedule_table
from mnq_lab.spine.store import BarStore
from mnq_lab.spine.timemodel import TimeModel

ASSIGNMENT_INPUT_COLUMNS = (
    "arm_id",
    "session_id",
    "ts_event_ns",
    "tau_ns",
    "observation_bucket_ct",
    "session_phase",
    "category_code",
    "assignment_status",
)
ANCHOR_KEY_COLUMNS = ("session_id", "tau_ns")
RESET_SOURCE_ARM = PRIMARY_ARM

__all__ = [
    "ANCHOR_KEY_COLUMNS",
    "ASSIGNMENT_INPUT_COLUMNS",
    "RESET_SOURCE_ARM",
    "CorpusAdapterResult",
    "JoinReconciliation",
    "adapt_prevalence_input",
    "load_exploration_prevalence_input",
]


@dataclass(frozen=True)
class JoinReconciliation:
    """Exact row and key counts recorded by the adapter."""

    anchor_count: int
    arm_count: int
    assignment_rows: int
    reset_rows: int
    completion_rows: int
    matched_anchor_rows: int
    broadcast_rows: int
    reset_source_arm: str
    unused_reset_disagreement_count: int = 0


@dataclass(frozen=True)
class CorpusAdapterResult:
    source: PrevalenceInput
    reconciliation: JoinReconciliation


def _column(columns: Mapping[str, Any], name: str) -> np.ndarray:
    if name not in columns:
        raise SpineError(f"Phase 9 adapter source is missing column {name!r}")
    values = np.asarray(columns[name])
    if values.ndim != 1 or values.dtype.kind == "O":
        raise SpineError(f"Phase 9 adapter column {name!r} is not a 1-D array")
    return values


def _aligned(columns: Mapping[str, Any], names: tuple[str, ...], label: str) -> dict[str, np.ndarray]:
    output = {name: _column(columns, name) for name in names}
    sizes = {int(values.size) for values in output.values()}
    if len(sizes) != 1:
        raise SpineError(f"Phase 9 {label} columns have unequal row counts")
    return output


def _first_key_mismatch(
    left_session: np.ndarray,
    left_tau: np.ndarray,
    right_session: np.ndarray,
    right_tau: np.ndarray,
    *,
    left_label: str,
    right_label: str,
) -> None:
    if left_session.size != right_session.size:
        common = min(int(left_session.size), int(right_session.size))
    else:
        common = int(left_session.size)
    mismatch = np.flatnonzero(
        (left_session[:common] != right_session[:common])
        | (left_tau[:common] != right_tau[:common])
    )
    if mismatch.size:
        position = int(mismatch[0])
        raise SpineError(
            "Phase 9 exact-key join mismatch at position "
            f"{position}: {left_label}=({int(left_session[position])}, "
            f"{int(left_tau[position])}), {right_label}="
            f"({int(right_session[position])}, {int(right_tau[position])}); "
            "cause class timestamps/source_revision"
        )
    if left_session.size != right_session.size:
        first_extra_session = (
            int(left_session[common]) if left_session.size > common else int(right_session[common])
        )
        raise SpineError(
            "Phase 9 exact-key join row-count mismatch: "
            f"{left_label}={left_session.size}, {right_label}={right_session.size}; "
            f"first mismatching session {first_extra_session}; cause class missing_bars/source_revision"
        )


def _assert_unique_keys(session_id: np.ndarray, tau_ns: np.ndarray, label: str) -> None:
    if session_id.size < 2:
        return
    duplicate = np.flatnonzero(
        (session_id[1:] == session_id[:-1]) & (tau_ns[1:] == tau_ns[:-1])
    )
    if duplicate.size:
        position = int(duplicate[0] + 1)
        raise SpineError(
            f"Phase 9 {label} has duplicate exact key at position {position}, "
            f"session {int(session_id[position])}; cause class duplicates"
        )
    noncanonical = np.flatnonzero(
        (session_id[1:] < session_id[:-1])
        | (
            (session_id[1:] == session_id[:-1])
            & (tau_ns[1:] < tau_ns[:-1])
        )
    )
    if noncanonical.size:
        position = int(noncanonical[0] + 1)
        raise SpineError(
            f"Phase 9 {label} key order changes at position {position}, "
            f"session {int(session_id[position])}; cause class timestamps/source_revision"
        )


def adapt_prevalence_input(
    assignments: Mapping[str, Any],
    reset_columns: Mapping[str, Any],
    completion_columns: Mapping[str, Any],
    *,
    declared_arm_ids: tuple[str, ...] | None = None,
    reset_source_arm: str = RESET_SOURCE_ARM,
    unused_reset_disagreement_count: int = 0,
) -> CorpusAdapterResult:
    """Broadcast exact anchor columns across declared arm blocks, or fail closed."""

    arms = (
        tuple(config.arm_id for config in ARM_CONFIGS)
        if declared_arm_ids is None
        else tuple(declared_arm_ids)
    )
    if not arms or len(arms) != len(set(arms)):
        raise SpineError("Phase 9 adapter arm inventory is empty or duplicated")
    assignment = _aligned(assignments, ASSIGNMENT_INPUT_COLUMNS, "assignment")
    reset = _aligned(
        reset_columns,
        ("session_id", "ts_event_ns", "tau_ns", "reset_reason"),
        "reset",
    )
    completion = _aligned(
        completion_columns,
        ("session_id", "ts_event_ns", "tau_ns", "state_anchor", *ELIGIBILITY_COLUMNS),
        "completion",
    )
    anchor_count = int(reset["session_id"].size)
    if anchor_count == 0:
        raise SpineError("Phase 9 adapter requires nonempty anchor sources")
    _assert_unique_keys(reset["session_id"], reset["tau_ns"], "reset source")
    _assert_unique_keys(completion["session_id"], completion["tau_ns"], "completion source")
    _first_key_mismatch(
        reset["session_id"], reset["tau_ns"],
        completion["session_id"], completion["tau_ns"],
        left_label="reset", right_label="completion",
    )
    if not np.array_equal(reset["ts_event_ns"], completion["ts_event_ns"]):
        raise SpineError(
            "Phase 9 reset and completion bar-label timestamps differ; "
            "cause class timestamps"
        )

    expected_assignment_rows = anchor_count * len(arms)
    if int(assignment["arm_id"].size) != expected_assignment_rows:
        raise SpineError(
            "Phase 9 assignment row count does not equal exact anchors x arms: "
            f"{assignment['arm_id'].size} != {anchor_count} x {len(arms)}; "
            "cause class missing_bars/source_revision"
        )
    for arm_position, arm in enumerate(arms):
        start = arm_position * anchor_count
        stop = start + anchor_count
        observed_arms = assignment["arm_id"][start:stop]
        if not np.all(observed_arms == arm):
            mismatch = int(np.flatnonzero(observed_arms != arm)[0]) + start
            raise SpineError(
                f"Phase 9 assignment arm/order mismatch at position {mismatch}; "
                "cause class source_revision"
            )
        _first_key_mismatch(
            assignment["session_id"][start:stop], assignment["tau_ns"][start:stop],
            completion["session_id"], completion["tau_ns"],
            left_label=f"assignment[{arm}]", right_label="completion",
        )
        if not np.array_equal(
            assignment["ts_event_ns"][start:stop],
            completion["ts_event_ns"],
        ):
            raise SpineError(
                f"Phase 9 timestamp identity differs for arm {arm!r}; cause class timestamps"
            )

    repeated_reset = np.tile(reset["reset_reason"], len(arms))
    repeated_state = np.tile(completion["state_anchor"], len(arms))
    repeated_eligibility = tuple(
        (name, np.tile(completion[name], len(arms))) for name in ELIGIBILITY_COLUMNS
    )
    broadcast_rows = int(assignment["arm_id"].size)
    if any(values.size != broadcast_rows for _, values in repeated_eligibility):
        raise SpineError("Phase 9 eligibility broadcast row count differs")
    source = PrevalenceInput(
        arm_id=assignment["arm_id"],
        session_id=assignment["session_id"],
        ts_event_ns=assignment["ts_event_ns"],
        tau_ns=assignment["tau_ns"],
        observation_bucket_ct=assignment["observation_bucket_ct"],
        session_phase=assignment["session_phase"],
        category_code=assignment["category_code"],
        assignment_status=assignment["assignment_status"],
        reset_reason=repeated_reset,
        state_anchor=repeated_state,
        eligibility_columns=repeated_eligibility,
    )
    return CorpusAdapterResult(
        source=source,
        reconciliation=JoinReconciliation(
            anchor_count=anchor_count,
            arm_count=len(arms),
            assignment_rows=broadcast_rows,
            reset_rows=anchor_count,
            completion_rows=anchor_count,
            matched_anchor_rows=anchor_count,
            broadcast_rows=broadcast_rows,
            reset_source_arm=reset_source_arm,
            unused_reset_disagreement_count=int(unused_reset_disagreement_count),
        ),
    )


def _canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SpineError(f"Phase 9 {label} manifest is unreadable: {exc}") from exc
    if raw != _canonical_json_bytes(value):
        raise SpineError(f"Phase 9 {label} manifest is not canonical")
    return value


def _read_artifact_column(root: Path, record: Mapping[str, Any], name: str) -> np.ndarray:
    columns = record.get("columns")
    if not isinstance(columns, dict) or name not in columns:
        raise SpineError(f"Phase 9 corpus artifact is missing column {name!r}")
    column = columns[name]
    relative = column.get("file")
    if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise SpineError(f"Phase 9 corpus column path for {name!r} is invalid")
    path = root / relative
    if not path.is_file() or path.stat().st_size != column.get("bytes"):
        raise SpineError(f"Phase 9 corpus column {name!r} size differs")
    if _sha256_file(path) != column.get("sha256"):
        raise SpineError(f"Phase 9 corpus column {name!r} hash differs")
    values = np.load(path, mmap_mode="r", allow_pickle=False)
    if values.ndim != 1 or str(values.dtype) != column.get("dtype") or int(values.size) != column.get("rows"):
        raise SpineError(f"Phase 9 corpus column {name!r} schema differs")
    return values


def _completion_frame_columns(frame: Any) -> dict[str, np.ndarray]:
    required = (
        "session_id",
        "anchor_label_ns",
        "tau_ns",
        "state_anchor",
        *ELIGIBILITY_COLUMNS,
    )
    missing = tuple(name for name in required if name not in frame.columns)
    if missing:
        raise SpineError(
            f"Phase 9 completion frame is missing declared columns: {missing}"
        )
    return {
        "session_id": frame["session_id"].to_numpy(dtype=np.int32),
        "ts_event_ns": frame["anchor_label_ns"].to_numpy(dtype=np.int64),
        "tau_ns": frame["tau_ns"].to_numpy(dtype=np.int64),
        "state_anchor": frame["state_anchor"].to_numpy(dtype=np.bool_),
        **{
            name: frame[name].to_numpy(dtype=np.bool_)
            for name in ELIGIBILITY_COLUMNS
        },
    }


def load_exploration_prevalence_input(root: Path) -> CorpusAdapterResult:
    """Read the version-bound exploration artifacts without writing or matching loosely."""

    source_root = Path(root).resolve()
    exploration_root = (REPO_ROOT / "data" / "exploration").resolve()
    if source_root == exploration_root or exploration_root not in source_root.parents:
        raise SpineError("Phase 9 corpus adapter may read only within data/exploration")
    run_manifest = _read_manifest(source_root / "run_manifest.json", "run")
    if tuple(run_manifest.get("execution_order", ())) != ("phase7", "unit_o"):
        raise SpineError("Phase 9 corpus sources do not share the declared pipeline execution")
    phase7_root = source_root / "phase7"
    outcome_root = source_root / "unit_o"
    phase7_path = phase7_root / "manifest.json"
    outcome_path = outcome_root / "manifest.json"
    expected_hashes = run_manifest.get("artifact_manifest_sha256", {})
    if _sha256_file(phase7_path) != expected_hashes.get("phase7") or _sha256_file(outcome_path) != expected_hashes.get("unit_o"):
        raise SpineError("Phase 9 corpus sources bridge pipeline versions")
    phase7 = _read_manifest(phase7_path, "Phase 7")
    outcome = _read_manifest(outcome_path, "Unit O")
    if tuple(phase7.get("arm_order", ())) != tuple(config.arm_id for config in ARM_CONFIGS):
        raise SpineError("Phase 9 assignment arm inventory differs from ARM_CONFIGS")
    if tuple(outcome.get("column_order", ())) != OUTCOME_SCHEMA:
        raise SpineError("Phase 9 Unit O column order differs")
    if tuple(outcome.get("estimands", ())) != ESTIMAND_ORDER or tuple(outcome.get("horizons_minutes", ())) != HORIZONS:
        raise SpineError("Phase 9 Unit O estimand/horizon declarations differ")

    assignment_record = phase7.get("tables", {}).get("assignments", {})
    assignment = {
        name: _read_artifact_column(phase7_root, assignment_record, name)
        for name in ASSIGNMENT_INPUT_COLUMNS
    }
    reset_record = phase7.get("tables", {}).get("anchor_scales", {})
    reset_all = {
        name: _read_artifact_column(phase7_root, reset_record, name)
        for name in ("arm_id", "session_id", "ts_event_ns", "tau_ns", "reset_reason")
    }
    reset_total = int(reset_all["arm_id"].size)
    if reset_total % len(SCALE_SOURCE_ARMS):
        raise SpineError("Phase 9 reset source rows do not divide into declared arm blocks")
    anchor_count = reset_total // len(SCALE_SOURCE_ARMS)
    primary_slice = slice(0, anchor_count)
    if not np.all(reset_all["arm_id"][primary_slice] == RESET_SOURCE_ARM):
        raise SpineError("Phase 9 primary reset source block differs")
    reset = {name: values[primary_slice] for name, values in reset_all.items() if name != "arm_id"}
    unused_reset_disagreements = 0
    for position, arm in enumerate(SCALE_SOURCE_ARMS):
        block = slice(position * anchor_count, (position + 1) * anchor_count)
        if not np.all(reset_all["arm_id"][block] == arm):
            raise SpineError(f"Phase 9 reset source arm block differs for {arm!r}")
        _first_key_mismatch(
            reset_all["session_id"][block], reset_all["tau_ns"][block],
            reset["session_id"], reset["tau_ns"],
            left_label=f"reset[{arm}]", right_label=f"reset[{RESET_SOURCE_ARM}]",
        )
        if arm != RESET_SOURCE_ARM:
            unused_reset_disagreements += int(np.count_nonzero(reset_all["reset_reason"][block] != reset["reset_reason"]))

    store_root = (REPO_ROOT / "data" / "exploration" / "bars_5m").resolve()
    store_manifest_path = store_root / "manifest.json"
    if (
        _sha256_file(store_manifest_path)
        != run_manifest.get("source_store_manifest_sha256")
    ):
        raise SpineError("Phase 9 completion source bridges pipeline versions")
    store = BarStore.open(store_root)
    if (
        str(store.manifest.get("build_id"))
        != str(run_manifest.get("source_store_build_id"))
        or int(store.n_rows) != int(run_manifest.get("source_store_row_count", -1))
    ):
        raise SpineError("Phase 9 completion source identity differs")
    store.verify_hashes()
    completion_frame = anchor_outcome_completion(
        TimeModel.from_constants(),
        np.asarray(store.column("session_id")),
        np.asarray(store.column("ts_event_ns")),
        np.asarray(store.column("observed_1m_components")),
        np.asarray(store.column("expected_1m_components")),
    )
    excluded_sessions = np.asarray(
        load_session_schedule_table().excluded_session_ids, dtype=np.int32
    )
    if excluded_sessions.size:
        keep = ~np.isin(
            completion_frame["session_id"].to_numpy(dtype=np.int32),
            excluded_sessions,
        )
        completion_frame = completion_frame.loc[keep].reset_index(drop=True)
    completion = _completion_frame_columns(completion_frame)
    return adapt_prevalence_input(
        assignment,
        reset,
        completion,
        reset_source_arm=RESET_SOURCE_ARM,
        unused_reset_disagreement_count=unused_reset_disagreements,
    )
