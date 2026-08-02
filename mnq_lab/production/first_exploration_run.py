"""One fixed mechanical shakedown: Phase 7, then Unit O, never Phase 8.

The public entry point accepts no paths or corpus choices.  Tests exercise the
private composition helpers with synthetic ``BarStore`` objects; the public run
resolves the one canonical exploration input and one derived-artifact root.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import tracemalloc
from typing import Any, Mapping

import numpy as np

from mnq_lab import SpineError
from mnq_lab.conditioners.arms import ARM_CONFIGS
from mnq_lab.conditioners.artifacts import (
    ANCHOR_SCALE_SCHEMA,
    build_phase7_artifact_bundle,
    write_phase7_artifacts,
)
from mnq_lab.conditioners.calendar import (
    CALENDAR_SHA256,
    CalendarTable,
    completed_session_ids,
    load_accepted_calendar,
)
from mnq_lab.conditioners.pipeline import (
    PRIMARY_ARM,
    SCALE_SOURCE_ARMS,
    Phase7ConditionerPipeline,
    build_conditioner_pipeline,
)
from mnq_lab.conditioners.scales.ewma import EwmaScaleSeries, ewma_rms
from mnq_lab.conditioners.scales.mad import MadScaleSeries, rolling_mad
from mnq_lab.conditioners.scales.returns import (
    CoverageRule,
    ReturnInputs,
    ReturnSeries,
    construct_returns,
    missing_anchor_status,
)
from mnq_lab.conditioners.seasonal import (
    ScaleAnchorTable,
    scale_anchor_row,
)
from mnq_lab.conditioners.state_validity import (
    NON_OK_STATUS_ORDER,
    ArmStateDiagnostic,
    StateAnchorDiagnostic,
    build_state_validity_panel,
)
from mnq_lab.conditioners.status import (
    AnchorStatus,
    AssignmentStatus,
    EwmaStatus,
    MadStatus,
    ResetReason,
    ReturnMissingReason,
    ReturnStatus,
    SeasonalStatus,
    ThresholdStatus,
    VolRelStatus,
)
from mnq_lab.constants import CONSTANTS_PATH, REPO_ROOT, SPEC_PATH
from mnq_lab.outcomes.artifacts import write_outcome_artifact
from mnq_lab.outcomes.completion import (
    ESTIMAND_FULLY_LABELED,
    ESTIMAND_OBSERVED,
    anchor_outcome_completion,
    completion_by_year,
)
from mnq_lab.outcomes.excursions import OutcomeTable, build_outcome_table
from mnq_lab.spine.exploration import ExplorationBars, validate_exploration_store
from mnq_lab.spine.seal import Corpus, assert_exploration_safe, store_path
from mnq_lab.spine.store import BarStore, environment_fingerprint
from mnq_lab.spine.timemodel import TimeModel


RUN_SCHEMA_VERSION = "phase7-unit-o-mechanical-shakedown-v1"
RUN_MANIFEST_NAME = "run_manifest.json"
CANONICAL_STORE_ROOT = store_path(REPO_ROOT / "data", Corpus.EXPLORATION, "5m")
OUTPUT_ROOT = (
    REPO_ROOT
    / "data"
    / Corpus.EXPLORATION.dirname
    / "derived"
    / "phase7-unit-o-first-run-v1"
)
STAGING_ROOT = OUTPUT_ROOT.with_name(f".{OUTPUT_ROOT.name}.staging")

_OUTCOME_PREREGISTRATION = REPO_ROOT / "docs" / "OUTCOME_LAYER_PREREGISTRATION.md"
_PHASE8_PREREGISTRATION = REPO_ROOT / "docs" / "PHASE8_PREREGISTRATION.md"
_PHASE7_PREREGISTRATION = REPO_ROOT / "docs" / "PHASE7_PREREGISTRATION.md"
_PROTECTED_INPUTS = {
    "REV6_FROZEN_SPEC.md": (
        SPEC_PATH,
        "70dae16c8b12fe26d38a7bfdabf0202066fe7149f790d0d2942279d9c3b8ff50",
    ),
    "analysis_constants_v1.yaml": (
        CONSTANTS_PATH,
        "1c95aa595c30c48b853303291a7dbaabceaf5b7331bca565a30863e8dcf138d4",
    ),
    "docs/PHASE7_PREREGISTRATION.md": (
        _PHASE7_PREREGISTRATION,
        "eeb97cb7e6ccd17a0ccd676de3cf7424f511fc773bacd62ff9e9f88aa404a930",
    ),
    "docs/OUTCOME_LAYER_PREREGISTRATION.md": (
        _OUTCOME_PREREGISTRATION,
        "4b5bc97fdfd4b0219c69e6a8adf76f18072091a9389700191d3ddcd10f8207c8",
    ),
    "docs/PHASE8_PREREGISTRATION.md": (
        _PHASE8_PREREGISTRATION,
        "d07174ed0acc9e60ab6b255f4b33fc08141969c64e04f66e1e08c0aca98b4680",
    ),
}


def _gate(
    gate: str,
    classification: str,
    cause_class: str,
    meaning: str,
    failing_input: str,
) -> dict[str, str]:
    return {
        "gate": gate,
        "classification": classification,
        "cause_class": cause_class,
        "meaning": meaning,
        "failing_input": failing_input,
    }


# Fixed before the first real run.  Closed statuses are diagnostics unless the
# contract explicitly describes corruption; structural/provenance gates halt.
GATE_CLASSIFICATION = (
    _gate("return.bar_absent", "EXPECTED_DIAGNOSTIC", "missing_bars", "declared anchor label is absent", "remove the 10:00 anchor bar"),
    _gate("return.insufficient_components", "EXPECTED_DIAGNOSTIC", "missing_bars", "strict coverage rejects a partial bar", "set observed components to three"),
    _gate("return.spacing_break_scheduled", "EXPECTED_DIAGNOSTIC", "timestamps", "session or weekend break resets state", "place the next bar after the maintenance halt"),
    _gate("return.spacing_break_unscheduled", "EXPECTED_DIAGNOSTIC", "missing_bars", "an unexpected five-minute interval is absent", "remove an interior Globex bar"),
    _gate("return.symbol_change", "EXPECTED_DIAGNOSTIC", "roll_mapping", "a decoded-symbol change resets state", "change symbol code at a contract boundary"),
    _gate("reset.roll_reset", "EXPECTED_DIAGNOSTIC", "roll_mapping", "the first post-roll bar cannot bridge contracts", "set rollover true on the current bar"),
    _gate("reset.gap_reset", "EXPECTED_DIAGNOSTIC", "timestamps", "the first post-gap bar starts a new segment", "insert a non-five-minute spacing"),
    _gate("ewma.warmup", "EXPECTED_DIAGNOSTIC", "timestamps", "fewer than 78 contiguous returns are available", "supply only 77 contiguous returns"),
    _gate("mad.warmup", "EXPECTED_DIAGNOSTIC", "timestamps", "the exact 78-return MAD window is unavailable", "supply only 77 contiguous returns"),
    _gate("mad.zero_scale", "EXPECTED_DIAGNOSTIC", "aggregation", "the admitted MAD window is constant", "supply 78 equal returns"),
    _gate("seasonal.warmup", "EXPECTED_DIAGNOSTIC", "timestamps", "fewer than 60 qualifying prior sessions exist", "supply 59 qualifying prior sessions"),
    _gate("seasonal.fallback_unavailable", "EXPECTED_DIAGNOSTIC", "missing_bars", "the prior phase has no defined scale fallback", "remove every defined scale in the prior phase"),
    _gate("seasonal.calendar_classification_missing", "FATAL", "source_revision", "an in-range session lacks its accepted calendar row", "delete one in-range calendar row"),
    _gate("vol_rel.zero_scale", "EXPECTED_DIAGNOSTIC", "aggregation", "the seasonal denominator is exactly zero", "supply a zero seasonal profile"),
    _gate("vol_rel.upstream_undefined", "EXPECTED_DIAGNOSTIC", "missing_bars", "scale or seasonal input is unavailable", "make the current scale undefined"),
    _gate("threshold.insufficient_history", "EXPECTED_DIAGNOSTIC", "timestamps", "fewer than 60 qualifying prior sessions exist", "supply 59 qualifying sessions"),
    _gate("threshold.degenerate_boundaries", "EXPECTED_DIAGNOSTIC", "aggregation", "lower and upper frozen quantiles coincide", "supply tied prior vol_rel values"),
    _gate("assignment.warmup", "EXPECTED_DIAGNOSTIC", "timestamps", "defined current vol_rel lacks prior thresholds", "request assignment on the 60th qualifying session"),
    _gate("assignment.upstream_undefined", "EXPECTED_DIAGNOSTIC", "missing_bars", "current vol_rel is unavailable", "remove the current anchor bar"),
    _gate("store.hash_or_manifest", "FATAL", "source_revision", "sealed source bytes differ from their manifest", "flip one source-column byte"),
    _gate("store.timestamp_order", "FATAL", "timestamps", "timestamps are not strictly increasing", "swap two adjacent labels"),
    _gate("store.duplicate_timestamp", "FATAL", "duplicates", "two rows share one UTC label", "duplicate one timestamp"),
    _gate("store.ohlc_or_components", "FATAL", "aggregation", "bar aggregation invariants are corrupt", "set high below close"),
    _gate("phase7.anchor_or_arm_support", "FATAL", "timestamps", "grid or arm supports differ", "drop one arm's 10:00 anchor row"),
    _gate("phase7.impossible_status", "FATAL", "aggregation", "a closed status combination is inconsistent", "pair an ok return with gap_reset"),
    _gate("artifact.protected_input", "FATAL", "source_revision", "a frozen or preregistered input changed", "change one frozen-input digest"),
    _gate("artifact.row_count", "FATAL", "aggregation", "an emitted table differs from declared cardinality", "add one to the expected anchor row count"),
    _gate("artifact.column_hash", "FATAL", "source_revision", "a written column no longer matches its manifest", "flip one written column byte"),
    _gate("artifact.missing_manifest", "FATAL", "source_revision", "a staged layer is incomplete", "remove the layer manifest"),
    _gate("artifact.nonempty_root", "FATAL", "source_revision", "the immutable run target is already occupied", "place a file in the staging root"),
    _gate("artifact.canonical_store_target", "FATAL", "source_revision", "an output target could overwrite the source store", "point output at the canonical store root"),
)


@dataclass(frozen=True)
class Phase7Product:
    grid_rows: int
    scale_tables: Mapping[str, ScaleAnchorTable]
    pipeline: Phase7ConditionerPipeline
    bundle: Any
    completion_frame: Any
    completion_diagnostic: dict[str, Any]
    phase7_status_counts: dict[str, dict[str, int]]
    row_counts: dict[str, int]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            indent=2,
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise SpineError(f"shakedown JSON is not strict and finite: {exc}") from exc
    return (encoded + "\n").encode("utf-8")


def _validate_output_root(
    root: Path,
    *,
    canonical_store_root: Path = CANONICAL_STORE_ROOT,
) -> Path:
    resolved = assert_exploration_safe(Path(root)).resolve()
    canonical = assert_exploration_safe(Path(canonical_store_root)).resolve()
    if resolved == canonical or resolved in canonical.parents:
        raise SpineError("shakedown output root may not equal or contain the canonical exploration store")
    return resolved


def _require_absent(root: Path, label: str) -> None:
    if Path(root).exists():
        raise SpineError(f"{label} must be absent before the immutable shakedown run")


def _return_inputs(bars: ExplorationBars) -> ReturnInputs:
    return ReturnInputs(
        ts_event_ns=np.asarray(bars.column("ts_event_ns")),
        session_id=np.asarray(bars.column("session_id")),
        symbol_code=np.asarray(bars.column("symbol_code")),
        close_ticks=np.asarray(bars.column("close_ticks")),
        expected_1m_components=np.asarray(bars.column("expected_1m_components")),
        observed_1m_components=np.asarray(bars.column("observed_1m_components")),
        rollover=np.asarray(bars.column("rollover")),
    )


def _session_quality(
    bars: ExplorationBars,
    calendar: CalendarTable,
    time_model: TimeModel,
) -> dict[int, str]:
    flags = time_model.session_flags(
        bars.column("session_id"), bars.column("ts_event_ns")
    )
    output: dict[int, str] = {}
    for row in flags.itertuples(index=False):
        session_id = int(row.session_id)
        calendar_row = calendar.lookup(session_id)
        anomalous = bool(
            row.observed_no_rth_bars
            or row.observed_rth_ended_early
            or row.observed_mid_rth_gap
        )
        output[session_id] = (
            "unresolved_truncated_session"
            if calendar_row is not None
            and calendar_row.session_class == "regular"
            and anomalous
            else "ok"
        )
    return output


def _selected_strings(
    values: list[str],
    indices: np.ndarray,
    present: np.ndarray,
    default: str,
) -> np.ndarray:
    selected = np.full(present.size, default, dtype=object)
    selected[present] = np.asarray(values, dtype=object)[indices[present]]
    return selected


def _closed_counts(values: Any, vocabulary: tuple[str, ...]) -> dict[str, int]:
    array = np.asarray(values)
    return {name: int(np.sum(array == name)) for name in vocabulary}


def _source_arm(arm_id: str) -> str:
    return PRIMARY_ARM if arm_id.startswith("threshold_") else arm_id


def _anchor_products(
    bars: ExplorationBars,
    calendar: CalendarTable,
    time_model: TimeModel,
) -> tuple[
    dict[str, ScaleAnchorTable],
    dict[str, np.ndarray],
    dict[str, dict[str, np.ndarray]],
    Any,
]:
    inputs = _return_inputs(bars)
    permissive = construct_returns(inputs, CoverageRule.PERMISSIVE)
    strict = construct_returns(inputs, CoverageRule.STRICT)
    estimators: dict[str, tuple[ReturnSeries, EwmaScaleSeries | MadScaleSeries, str]] = {
        PRIMARY_ARM: (permissive, ewma_rms(permissive, 78), "ewma"),
        "coverage_strict": (strict, ewma_rms(strict, 78), "ewma"),
        "ewma39": (permissive, ewma_rms(permissive, 39), "ewma"),
        "ewma156": (permissive, ewma_rms(permissive, 156), "ewma"),
        "mad78": (permissive, rolling_mad(permissive), "mad"),
    }
    grid = time_model.anchor_grid(
        bars.column("session_id"), bars.column("ts_event_ns")
    )
    labels = np.asarray(bars.column("ts_event_ns"), dtype=np.int64)
    anchor_labels = grid["anchor_label_ns"].to_numpy(dtype=np.int64)
    indices = np.searchsorted(labels, anchor_labels)
    clipped = np.minimum(indices, labels.size - 1)
    present = (indices < labels.size) & (labels[clipped] == anchor_labels)
    if not np.array_equal(
        present,
        grid["status"].to_numpy(dtype=object) == AnchorStatus.OK.value,
    ):
        raise SpineError("Phase 7 exact anchor resolver differs from the declared grid")

    grid_rows = len(grid)
    total_rows = len(SCALE_SOURCE_ARMS) * grid_rows
    anchor_columns = {
        name: np.empty(total_rows, dtype=np.dtype(dtype))
        for name, dtype in ANCHOR_SCALE_SCHEMA
    }
    quality = _session_quality(bars, calendar, time_model)
    tables: dict[str, ScaleAnchorTable] = {}
    runtime: dict[str, dict[str, np.ndarray]] = {}

    session_values = grid["session_id"].to_numpy(dtype=np.int32)
    tau_values = grid["tau_ns"].to_numpy(dtype=np.int64)
    bucket_values = np.asarray(
        [f"{value // 60:02d}:{value % 60:02d}" for value in grid["tau_ct_minute"]],
        dtype="U5",
    )
    phase_values = grid["phase"].to_numpy(dtype=str)
    missing_status = missing_anchor_status()

    for arm_position, arm_id in enumerate(SCALE_SOURCE_ARMS):
        returns, estimator, stage = estimators[arm_id]
        block = slice(arm_position * grid_rows, (arm_position + 1) * grid_rows)
        return_status = _selected_strings(
            [status.return_status.value for status in returns.statuses],
            clipped,
            present,
            missing_status.return_status.value,
        )
        return_reason = _selected_strings(
            [
                "" if status.return_missing_reason is None else status.return_missing_reason.value
                for status in returns.statuses
            ],
            clipped,
            present,
            missing_status.return_missing_reason.value,
        )
        reset_reason = _selected_strings(
            [status.reset_reason.value for status in returns.statuses],
            clipped,
            present,
            missing_status.reset_reason.value,
        )
        scheduled = np.zeros(grid_rows, dtype=bool)
        scheduled[present] = np.asarray(
            [status.scheduled_break for status in returns.statuses], dtype=bool
        )[clipped[present]]
        estimator_status = _selected_strings(
            [status.value for status in estimator.statuses],
            clipped,
            present,
            EwmaStatus.WARMUP.value if stage == "ewma" else MadStatus.WARMUP.value,
        )
        scale_values = np.zeros(grid_rows, dtype=np.float64)
        scale_valid = np.zeros(grid_rows, dtype=bool)
        counts = np.zeros(grid_rows, dtype=np.int32)
        scale_values[present] = estimator.values[clipped[present]]
        scale_valid[present] = estimator.valid[clipped[present]]
        counts[present] = estimator.contiguous_return_count[clipped[present]]
        symbols = np.full(grid_rows, -1, dtype=np.int32)
        observed = np.zeros(grid_rows, dtype=np.int8)
        coverage = np.zeros(grid_rows, dtype=np.float64)
        symbols[present] = bars.column("symbol_code")[clipped[present]].astype(np.int32)
        observed[present] = bars.column("observed_1m_components")[clipped[present]]
        coverage[present] = bars.column("component_coverage_rate")[clipped[present]]
        anchor_status = np.where(
            present, AnchorStatus.OK.value, AnchorStatus.ANCHOR_BAR_MISSING.value
        )

        block_values = {
            "arm_id": np.full(grid_rows, arm_id, dtype="U64"),
            "session_id": session_values,
            "ts_event_ns": anchor_labels,
            "tau_ns": tau_values,
            "observation_bucket_ct": bucket_values,
            "session_phase": phase_values,
            "symbol_code": symbols,
            "observed_1m_components": observed,
            "component_coverage_rate": coverage,
            "anchor_status": anchor_status,
            "return_status": return_status,
            "return_missing_reason": return_reason,
            "reset_reason": reset_reason,
            "scheduled_break": scheduled,
            "contiguous_return_count": counts,
            "scale_value": scale_values,
            "scale_valid": scale_valid,
            "ewma_status": estimator_status if stage == "ewma" else np.full(grid_rows, ""),
            "mad_status": estimator_status if stage == "mad" else np.full(grid_rows, ""),
        }
        for name, _ in ANCHOR_SCALE_SCHEMA:
            anchor_columns[name][block] = block_values[name]

        rows = tuple(
            scale_anchor_row(
                arm_id=arm_id,
                session_id=int(session_values[position]),
                ts_event_ns=int(anchor_labels[position]),
                scale_stage=stage,
                scale_value=float(scale_values[position]),
                scale_valid=bool(scale_valid[position]),
                data_quality_status=quality[int(session_values[position])],
            )
            for position in range(grid_rows)
        )
        tables[arm_id] = ScaleAnchorTable(arm_id, rows)
        runtime[arm_id] = {
            "anchor_status": np.asarray(anchor_status, dtype=object),
            "return_status": np.asarray(return_status, dtype=object),
            "return_missing_reason": np.asarray(return_reason, dtype=object),
            "reset_reason": np.asarray(reset_reason, dtype=object),
            "scheduled_break": scheduled,
            "estimator_status": np.asarray(estimator_status, dtype=object),
            "stage": np.full(grid_rows, stage, dtype=object),
        }
    return tables, anchor_columns, runtime, grid


def _state_diagnostics(
    pipeline: Phase7ConditionerPipeline,
    runtime: dict[str, dict[str, np.ndarray]],
    completion_frame: Any,
) -> tuple[tuple[StateAnchorDiagnostic, ...], tuple[ArmStateDiagnostic, ...]]:
    diagnostics = tuple(
        StateAnchorDiagnostic(
            session_id=int(row.session_id),
            tau_ns=int(row.tau_ns),
            observed_1m_components=int(row.observed_1m_components),
            outcome_complete_h15=bool(
                getattr(row, f"outcome_eligible_{ESTIMAND_FULLY_LABELED}_h15")
            ),
            outcome_complete_h30=bool(
                getattr(row, f"outcome_eligible_{ESTIMAND_FULLY_LABELED}_h30")
            ),
            outcome_complete_h60=bool(
                getattr(row, f"outcome_eligible_{ESTIMAND_FULLY_LABELED}_h60")
            ),
        )
        for row in completion_frame.itertuples(index=False)
    )

    arm_diagnostics: list[ArmStateDiagnostic] = []
    for config in ARM_CONFIGS:
        arm_id = config.arm_id
        source = _source_arm(arm_id)
        source_runtime = runtime[source]
        profiles = pipeline.seasonal_profiles[source].rows
        vol_rows = pipeline.vol_rel_tables[source].rows
        assignments = pipeline.assignment_tables[arm_id].rows
        if not (len(profiles) == len(vol_rows) == len(assignments)):
            raise SpineError("Phase 7 diagnostic stages have differing anchor support")
        for position, (profile, vol_row, assignment) in enumerate(
            zip(profiles, vol_rows, assignments, strict=True)
        ):
            non_ok: set[str] = set()
            if source_runtime["anchor_status"][position] != AnchorStatus.OK.value:
                non_ok.add("anchor_bar_missing")
            if source_runtime["return_status"][position] != ReturnStatus.OK.value:
                non_ok.add("missing_return")
            reset = str(source_runtime["reset_reason"][position])
            if reset == ResetReason.ROLL_RESET.value:
                non_ok.add("roll_reset")
            elif reset == ResetReason.GAP_RESET.value:
                non_ok.add("gap_reset")
            stage = str(source_runtime["stage"][position])
            estimator_status = str(source_runtime["estimator_status"][position])
            if stage == "ewma" and estimator_status == EwmaStatus.WARMUP.value:
                non_ok.add("ewma_warmup")
            elif stage == "mad" and estimator_status == MadStatus.WARMUP.value:
                non_ok.add("mad_warmup")
            elif stage == "mad" and estimator_status == MadStatus.ZERO_SCALE.value:
                non_ok.add("mad_zero_scale")
            seasonal_map = {
                SeasonalStatus.WARMUP: "seasonal_warmup",
                SeasonalStatus.SEASONAL_FALLBACK_UNAVAILABLE: "seasonal_fallback_unavailable",
                SeasonalStatus.CALENDAR_CLASSIFICATION_MISSING: "calendar_classification_missing",
            }
            if profile.seasonal_status in seasonal_map:
                non_ok.add(seasonal_map[profile.seasonal_status])
            if vol_row.vol_rel_status is VolRelStatus.ZERO_SCALE:
                non_ok.add("vol_rel_zero_scale")
            elif vol_row.vol_rel_status is VolRelStatus.UPSTREAM_UNDEFINED:
                non_ok.add("vol_rel_upstream_undefined")
            threshold = pipeline.threshold_tables[arm_id].lookup(
                assignment.session_id, assignment.session_phase
            )
            if threshold.threshold_status is ThresholdStatus.INSUFFICIENT_THRESHOLD_HISTORY:
                non_ok.add("insufficient_threshold_history")
            elif threshold.threshold_status is ThresholdStatus.DEGENERATE_BOUNDARIES:
                non_ok.add("degenerate_boundaries")
            if assignment.assignment_status is AssignmentStatus.WARMUP:
                non_ok.add("assignment_warmup")
            elif assignment.assignment_status is AssignmentStatus.UPSTREAM_UNDEFINED:
                non_ok.add("assignment_upstream_undefined")
            if assignment.category_code == -1:
                non_ok.add("assignment_undefined")
            ordered = tuple(name for name in NON_OK_STATUS_ORDER if name in non_ok)
            arm_diagnostics.append(
                ArmStateDiagnostic(
                    arm_id=arm_id,
                    session_id=assignment.session_id,
                    tau_ns=assignment.tau_ns,
                    reset_before=bool(
                        reset != ResetReason.NONE.value
                        or source_runtime["anchor_status"][position]
                        != AnchorStatus.OK.value
                    ),
                    non_ok_stage_statuses=ordered,
                )
            )
    return diagnostics, tuple(arm_diagnostics)


def _completion_diagnostic(
    completion_frame: Any,
    time_model: TimeModel,
) -> dict[str, Any]:
    frame = completion_by_year(completion_frame, time_model)
    source_sessions = completion_frame["session_id"].to_numpy(dtype=np.int32)
    source_years = source_sessions.astype(np.int64) // 10_000
    first_year = int(source_years.min())
    last_year = int(source_years.max())
    rows: list[dict[str, Any]] = []
    for row in frame.itertuples(index=False):
        year = int(row.year)
        sessions = np.unique(source_sessions[source_years == year])
        if year == first_year == last_year:
            boundary = "partial_start_and_end_year"
        elif year == first_year:
            boundary = "partial_start_year"
        elif year == last_year:
            boundary = "partial_end_year"
        else:
            boundary = "full_in_scope_year"
        records = row._asdict()
        records["year"] = year
        records["horizon_minutes"] = int(records["horizon_minutes"])
        records["weight_ess"] = None
        records["weight_ess_status"] = "not_computed_until_phase_4"
        records["first_source_session"] = int(sessions.min()) if sessions.size else None
        records["last_source_session"] = int(sessions.max()) if sessions.size else None
        records["source_session_count"] = int(sessions.size)
        records["boundary_year_status"] = boundary
        if boundary == "partial_start_year":
            records["boundary_reason"] = "corpus begins at the first source session"
        elif boundary == "partial_end_year":
            records["boundary_reason"] = "corpus ends at the exploration seal boundary"
        elif boundary == "partial_start_and_end_year":
            records["boundary_reason"] = "fixture or corpus begins and ends within one calendar year"
        else:
            records["boundary_reason"] = "complete in-scope calendar year"
        for name, value in tuple(records.items()):
            if isinstance(value, (np.integer,)):
                records[name] = int(value)
            elif isinstance(value, (np.floating, float)):
                records[name] = None if not np.isfinite(value) else float(value)
        rows.append(records)

    concentration: list[dict[str, Any]] = []
    for horizon in time_model.horizons_minutes:
        horizon_rows = [row for row in rows if row["horizon_minutes"] == horizon]
        for estimand in (ESTIMAND_FULLY_LABELED, ESTIMAND_OBSERVED):
            field = f"n_complete_{estimand}"
            support_years = [row["year"] for row in horizon_rows if row[field] > 0]
            concentration.append(
                {
                    "estimand": estimand,
                    "horizon_minutes": int(horizon),
                    "complete_support_years": support_years,
                    "complete_confinement_to_single_year": bool(
                        first_year != last_year and len(support_years) == 1
                    ),
                    "numeric_concentration_threshold_applied": False,
                }
            )
    return {
        "schema_version": "d21-completion-by-year-v1",
        "admissibility": "NON-ADMISSIBLE DIAGNOSTIC ARTIFACTS",
        "source_year_first": first_year,
        "source_year_last": last_year,
        "rows": rows,
        "year_concentration": concentration,
    }


def _phase7_status_counts(
    anchor_columns: Mapping[str, np.ndarray],
    pipeline: Phase7ConditionerPipeline,
) -> dict[str, dict[str, int]]:
    seasonal = [row.seasonal_status.value for table in pipeline.seasonal_profiles.values() for row in table.rows]
    vol_rel = [row.vol_rel_status.value for table in pipeline.vol_rel_tables.values() for row in table.rows]
    thresholds = [row.threshold_status.value for table in pipeline.threshold_tables.values() for row in table.rows]
    assignments = [row.assignment_status.value for table in pipeline.assignment_tables.values() for row in table.rows]
    quality = [row.data_quality_status for table in pipeline.assignment_tables.values() for row in table.rows]
    return {
        "anchor_status": _closed_counts(anchor_columns["anchor_status"], tuple(value.value for value in AnchorStatus)),
        "return_status": _closed_counts(anchor_columns["return_status"], tuple(value.value for value in ReturnStatus)),
        "return_missing_reason": _closed_counts(anchor_columns["return_missing_reason"], tuple(value.value for value in ReturnMissingReason)),
        "reset_reason": _closed_counts(anchor_columns["reset_reason"], tuple(value.value for value in ResetReason)),
        "ewma_status": _closed_counts(anchor_columns["ewma_status"], tuple(value.value for value in EwmaStatus)),
        "mad_status": _closed_counts(anchor_columns["mad_status"], tuple(value.value for value in MadStatus)),
        "seasonal_status": _closed_counts(seasonal, tuple(value.value for value in SeasonalStatus)),
        "vol_rel_status": _closed_counts(vol_rel, tuple(value.value for value in VolRelStatus)),
        "threshold_status": _closed_counts(thresholds, tuple(value.value for value in ThresholdStatus)),
        "assignment_status": _closed_counts(assignments, tuple(value.value for value in AssignmentStatus)),
        "data_quality_status": _closed_counts(quality, tuple(dict.fromkeys(quality))),
        "scheduled_break": {"true": int(np.sum(anchor_columns["scheduled_break"])), "false": int(np.sum(~anchor_columns["scheduled_break"]))},
    }


def _build_phase7_product(
    store: BarStore,
    bars: ExplorationBars,
    calendar: CalendarTable,
) -> Phase7Product:
    if not isinstance(store, BarStore) or not isinstance(bars, ExplorationBars):
        raise SpineError("Phase 7 shakedown requires one validated BarStore")
    time_model = TimeModel.from_constants()
    tables, anchor_columns, runtime, grid = _anchor_products(bars, calendar, time_model)
    current_sessions = tuple(
        int(value) for value in np.unique(grid["session_id"].to_numpy(dtype=np.int32))
    )
    completed = completed_session_ids(bars, calendar)
    pipeline = build_conditioner_pipeline(tables, current_sessions, completed, calendar)
    completion_frame = anchor_outcome_completion(
        time_model,
        np.asarray(bars.column("session_id")),
        np.asarray(bars.column("ts_event_ns")),
        np.asarray(bars.column("observed_1m_components")),
        np.asarray(bars.column("expected_1m_components")),
    )
    labels = np.asarray(bars.column("ts_event_ns"), dtype=np.int64)
    anchor_labels = completion_frame["anchor_label_ns"].to_numpy(dtype=np.int64)
    anchor_indices = np.searchsorted(labels, anchor_labels)
    clipped = np.minimum(anchor_indices, labels.size - 1)
    anchor_present = (anchor_indices < labels.size) & (labels[clipped] == anchor_labels)
    anchor_components = np.zeros(len(completion_frame), dtype=np.int8)
    anchor_components[anchor_present] = bars.column("observed_1m_components")[
        clipped[anchor_present]
    ]
    completion_frame["observed_1m_components"] = anchor_components
    diagnostics, arm_diagnostics = _state_diagnostics(
        pipeline, runtime, completion_frame
    )
    panel = build_state_validity_panel(pipeline, diagnostics, arm_diagnostics)
    bundle = build_phase7_artifact_bundle(anchor_columns, pipeline, panel)
    row_counts = {
        "declared_grid": int(len(grid)),
        **{name: table.row_count for name, table in bundle.tables.items()},
    }
    return Phase7Product(
        grid_rows=int(len(grid)),
        scale_tables=tables,
        pipeline=pipeline,
        bundle=bundle,
        completion_frame=completion_frame,
        completion_diagnostic=_completion_diagnostic(completion_frame, time_model),
        phase7_status_counts=_phase7_status_counts(anchor_columns, pipeline),
        row_counts=row_counts,
    )


def _load_canonical_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SpineError(f"missing manifest: {path}")
    payload = path.read_bytes()
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpineError(f"invalid manifest {path}: {exc}") from exc
    if not isinstance(value, dict) or payload != _canonical_json_bytes(value):
        raise SpineError(f"manifest is not canonical strict JSON: {path}")
    return value


def _verify_column_records(
    root: Path,
    columns: Mapping[str, Any],
    expected_rows: int,
) -> None:
    for name, record in columns.items():
        if int(record.get("rows", -1)) != expected_rows:
            raise SpineError(f"artifact row count mismatch for {name}")
        path = root / str(record.get("file", ""))
        if not path.is_file():
            raise SpineError(f"artifact column is missing: {path}")
        if path.stat().st_size != int(record.get("bytes", -1)):
            raise SpineError(f"artifact byte count mismatch for {name}")
        if _sha256_file(path) != record.get("sha256"):
            raise SpineError(f"artifact column hash mismatch for {name}")
        array = np.load(path, mmap_mode="r", allow_pickle=False)
        if str(array.dtype) != record.get("dtype") or len(array) != expected_rows:
            raise SpineError(f"artifact dtype or row count mismatch for {name}")


def _expected_pin(name: str) -> str:
    path, expected = _PROTECTED_INPUTS[name]
    actual = _sha256_file(path)
    if actual != expected:
        raise SpineError(f"protected frozen input changed before shakedown: {name}")
    return expected


def _validate_phase7_tree(
    root: Path,
    expected_phase7_rows: Mapping[str, int],
) -> dict[str, Any]:
    manifest = _load_canonical_manifest(root / "manifest.json")
    frozen = manifest.get("frozen_inputs", {})
    expected_frozen = {
        "REV6_FROZEN_SPEC.md": _expected_pin("REV6_FROZEN_SPEC.md"),
        "analysis_constants_v1.yaml": _expected_pin("analysis_constants_v1.yaml"),
        "docs/PHASE7_PREREGISTRATION.md": _expected_pin("docs/PHASE7_PREREGISTRATION.md"),
        "accepted_calendar": CALENDAR_SHA256,
    }
    if frozen != expected_frozen:
        raise SpineError("Phase 7 artifact frozen input binding differs")
    tables = manifest.get("tables")
    if not isinstance(tables, dict) or set(tables) != set(expected_phase7_rows) - {"declared_grid"}:
        raise SpineError("Phase 7 artifact table manifest is incomplete")
    for name, expected_rows in expected_phase7_rows.items():
        if name == "declared_grid":
            continue
        table = tables[name]
        if int(table.get("row_count", -1)) != expected_rows:
            raise SpineError(f"Phase 7 artifact row count mismatch for {name}")
        column_order = table.get("column_order")
        columns = table.get("columns")
        if not isinstance(columns, dict) or set(columns) != set(column_order):
            raise SpineError(f"Phase 7 artifact column manifest is incomplete for {name}")
        _verify_column_records(root, columns, expected_rows)
    return manifest


def _validate_artifact_tree(
    stage_root: Path,
    *,
    expected_source_manifest_sha256: str,
    expected_phase7_rows: Mapping[str, int],
    expected_outcome_rows: int,
) -> dict[str, str]:
    phase7_root = Path(stage_root) / "phase7"
    unit_root = Path(stage_root) / "unit_o"
    phase7_manifest = _validate_phase7_tree(phase7_root, expected_phase7_rows)
    unit_manifest = _load_canonical_manifest(unit_root / "manifest.json")
    if unit_manifest.get("input_store_manifest_sha256") != expected_source_manifest_sha256:
        raise SpineError("Unit O source store manifest binding differs")
    expected_unit_frozen = {
        "REV6_FROZEN_SPEC.md": _expected_pin("REV6_FROZEN_SPEC.md"),
        "analysis_constants_v1.yaml": _expected_pin("analysis_constants_v1.yaml"),
        "docs/OUTCOME_LAYER_PREREGISTRATION.md": _expected_pin("docs/OUTCOME_LAYER_PREREGISTRATION.md"),
        "docs/PHASE8_PREREGISTRATION.md": _expected_pin("docs/PHASE8_PREREGISTRATION.md"),
    }
    if unit_manifest.get("frozen_inputs") != expected_unit_frozen:
        raise SpineError("Unit O artifact frozen input binding differs")
    if int(unit_manifest.get("row_count", -1)) != expected_outcome_rows:
        raise SpineError("Unit O artifact row count mismatch")
    columns = unit_manifest.get("columns")
    if not isinstance(columns, dict) or set(columns) != set(unit_manifest.get("column_order", ())):
        raise SpineError("Unit O artifact column manifest is incomplete")
    _verify_column_records(unit_root, columns, expected_outcome_rows)
    diagnostic = _load_canonical_manifest(Path(stage_root) / "diagnostics" / "completion_by_year.json")
    if diagnostic.get("admissibility") != "NON-ADMISSIBLE DIAGNOSTIC ARTIFACTS":
        raise SpineError("completion diagnostic lacks the non-admissible label")
    return {
        "phase7_manifest_sha256": _sha256_file(phase7_root / "manifest.json"),
        "unit_o_manifest_sha256": _sha256_file(unit_root / "manifest.json"),
        "completion_diagnostic_sha256": _sha256_file(
            Path(stage_root) / "diagnostics" / "completion_by_year.json"
        ),
        "phase7_manifest_schema": str(phase7_manifest.get("artifact_schema_version")),
    }


def _begin_stage(
    stage_root: Path,
    store: BarStore,
    product: Phase7Product,
    *,
    environment: Mapping[str, Any],
) -> dict[str, Any]:
    _require_absent(stage_root, "shakedown staging root")
    stage_root.mkdir(parents=True)
    write_phase7_artifacts(
        stage_root / "phase7",
        product.bundle,
        source_build_id=str(store.manifest["build_id"]),
        environment=environment,
    )
    diagnostic_root = stage_root / "diagnostics"
    diagnostic_root.mkdir()
    (diagnostic_root / "completion_by_year.json").write_bytes(
        _canonical_json_bytes(product.completion_diagnostic)
    )
    return {
        "completion_diagnostic_rows": len(product.completion_diagnostic["rows"]),
    }


def _complete_stage(
    stage_root: Path,
    store: BarStore,
    outcomes: OutcomeTable,
    *,
    environment: Mapping[str, Any],
) -> None:
    if (stage_root / RUN_MANIFEST_NAME).exists():
        raise SpineError("final run manifest appeared before Unit O completed")
    write_outcome_artifact(
        stage_root / "unit_o",
        outcomes,
        source_store=store,
        environment=environment,
    )


def _stage_artifacts(
    stage_root: Path,
    store: BarStore | None,
    product: Phase7Product | None,
    outcomes: OutcomeTable | None,
    *,
    environment: Mapping[str, Any],
) -> dict[str, Any]:
    _require_absent(stage_root, "shakedown staging root")
    if not isinstance(store, BarStore) or not isinstance(product, Phase7Product) or not isinstance(outcomes, OutcomeTable):
        raise SpineError("staging requires validated Phase 7 and Unit O products")
    staged = _begin_stage(stage_root, store, product, environment=environment)
    _complete_stage(stage_root, store, outcomes, environment=environment)
    return staged


def _validate_run_manifest(manifest: Mapping[str, Any], *, expected_year_rows: int) -> None:
    if manifest.get("admissibility") != "NON-ADMISSIBLE DIAGNOSTIC ARTIFACTS":
        raise SpineError("run manifest lacks the non-admissible label")
    if manifest.get("execution_order") != ["phase7", "unit_o"]:
        raise SpineError("run manifest execution order differs from Phase 7 then Unit O")
    if manifest.get("phase8_executed") is not False:
        raise SpineError("run manifest indicates Phase 8 execution")
    if manifest.get("outcome_values_inspected") is not False:
        raise SpineError("run manifest indicates outcome-value inspection")
    if int(manifest.get("year_diagnostic_rows", -1)) != expected_year_rows:
        raise SpineError("run manifest year diagnostic row count differs")
    if manifest.get("gate_classification") != list(GATE_CLASSIFICATION):
        raise SpineError("run manifest gate classification differs from the pre-run table")
    environment = manifest.get("environment_fingerprint")
    if not isinstance(environment, dict) or not environment.get("commit") or environment.get("dirty") is not False:
        raise SpineError("shakedown must execute at one clean committed code state")
    row_counts = manifest.get("row_counts")
    if not isinstance(row_counts, dict) or not row_counts or any(
        type(value) is not int or value <= 0 for value in row_counts.values()
    ):
        raise SpineError("run manifest row counts are missing or invalid")
    if type(manifest.get("peak_memory_bytes")) is not int or manifest["peak_memory_bytes"] <= 0:
        raise SpineError("run manifest peak memory is invalid")
    timings = manifest.get("stage_seconds")
    if not isinstance(timings, dict) or not timings or any(
        not isinstance(value, (int, float)) or value < 0 for value in timings.values()
    ):
        raise SpineError("run manifest stage timings are invalid")
    for key in (
        "source_store_manifest_sha256",
        "completion_diagnostic_sha256",
    ):
        value = manifest.get(key)
        if not isinstance(value, str) or len(value) != 64:
            raise SpineError(f"run manifest {key} is invalid")
    hashes = manifest.get("artifact_manifest_sha256")
    if not isinstance(hashes, dict) or set(hashes) != {"phase7", "unit_o"} or any(
        not isinstance(value, str) or len(value) != 64 for value in hashes.values()
    ):
        raise SpineError("run manifest artifact hashes are incomplete")


def _finalize_staged_run(
    stage_root: Path,
    final_root: Path,
    *,
    store: BarStore,
    product: Phase7Product,
    outcome_row_count: int,
    staged: Mapping[str, Any],
    stage_seconds: Mapping[str, float],
    peak_memory_bytes: int,
    environment: Mapping[str, Any],
) -> dict[str, Any]:
    _require_absent(final_root, "shakedown final root")
    if (stage_root / RUN_MANIFEST_NAME).exists():
        raise SpineError("run manifest must be the last staged file")
    source_manifest_sha = _sha256_file(store.root / "manifest.json")
    verified = _validate_artifact_tree(
        stage_root,
        expected_source_manifest_sha256=source_manifest_sha,
        expected_phase7_rows=product.row_counts,
        expected_outcome_rows=outcome_row_count,
    )
    unit_manifest = _load_canonical_manifest(stage_root / "unit_o" / "manifest.json")
    row_counts = dict(product.row_counts)
    row_counts["unit_o"] = int(outcome_row_count)
    manifest = {
        "schema_version": RUN_SCHEMA_VERSION,
        "admissibility": "NON-ADMISSIBLE DIAGNOSTIC ARTIFACTS",
        "claim_boundary": "mechanical pipeline shakedown only; not a scientific result",
        "execution_order": ["phase7", "unit_o"],
        "phase8_executed": False,
        "outcome_values_inspected": False,
        "source_store_build_id": str(store.manifest["build_id"]),
        "source_store_manifest_sha256": source_manifest_sha,
        "source_store_row_count": int(store.n_rows),
        "source_trade_date_first": int(store.manifest["trade_date_first"]),
        "source_trade_date_last": int(store.manifest["trade_date_last"]),
        "row_counts": row_counts,
        "year_diagnostic_rows": int(staged["completion_diagnostic_rows"]),
        "phase7_status_counts": product.phase7_status_counts,
        "unit_o_status_counts": unit_manifest["status_counts"],
        "artifact_manifest_sha256": {
            "phase7": verified["phase7_manifest_sha256"],
            "unit_o": verified["unit_o_manifest_sha256"],
        },
        "completion_diagnostic_sha256": verified["completion_diagnostic_sha256"],
        "gate_classification": list(GATE_CLASSIFICATION),
        "stage_seconds": {name: float(value) for name, value in stage_seconds.items()},
        "peak_memory_bytes": int(peak_memory_bytes),
        "environment_fingerprint": dict(environment),
    }
    _validate_run_manifest(
        manifest,
        expected_year_rows=len(product.completion_diagnostic["rows"]),
    )
    manifest_path = stage_root / RUN_MANIFEST_NAME
    manifest_path.write_bytes(_canonical_json_bytes(manifest))
    if _load_canonical_manifest(manifest_path) != manifest:
        raise SpineError("final run manifest failed its byte-level reread")
    stage_root.replace(final_root)
    return manifest


def _peak_process_memory_bytes() -> int:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class _Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("page_fault_count", wintypes.DWORD),
                ("peak_working_set_size", ctypes.c_size_t),
                ("working_set_size", ctypes.c_size_t),
                ("quota_peak_paged_pool_usage", ctypes.c_size_t),
                ("quota_paged_pool_usage", ctypes.c_size_t),
                ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
                ("quota_non_paged_pool_usage", ctypes.c_size_t),
                ("pagefile_usage", ctypes.c_size_t),
                ("peak_pagefile_usage", ctypes.c_size_t),
            ]

        counters = _Counters()
        counters.cb = ctypes.sizeof(counters)
        process = ctypes.windll.kernel32.GetCurrentProcess()
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            process, ctypes.byref(counters), counters.cb
        )
        if not ok:
            raise SpineError("cannot read process peak working-set memory")
        return int(counters.peak_working_set_size)
    import resource

    maximum = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return maximum * (1024 if sys.platform != "darwin" else 1)


def run_shakedown() -> dict[str, Any]:
    """Execute the one authorized exploration-only mechanical shakedown."""
    output_root = _validate_output_root(OUTPUT_ROOT)
    staging_root = _validate_output_root(STAGING_ROOT)
    _require_absent(output_root, "shakedown final root")
    _require_absent(staging_root, "shakedown staging root")
    environment = environment_fingerprint(REPO_ROOT)
    if not environment.get("commit") or environment.get("dirty") is not False:
        raise SpineError("shakedown requires a clean committed worktree")

    tracemalloc.start()
    started = time.perf_counter()
    timings: dict[str, float] = {}

    mark = time.perf_counter()
    source_root = assert_exploration_safe(CANONICAL_STORE_ROOT)
    store = BarStore.open(source_root)
    store.verify_hashes()
    bars = validate_exploration_store(store)
    calendar = load_accepted_calendar()
    timings["source_validation"] = time.perf_counter() - mark

    mark = time.perf_counter()
    product = _build_phase7_product(store, bars, calendar)
    timings["phase7_compute"] = time.perf_counter() - mark

    mark = time.perf_counter()
    staged = _begin_stage(staging_root, store, product, environment=environment)
    _validate_phase7_tree(staging_root / "phase7", product.row_counts)
    timings["phase7_write_and_verify"] = time.perf_counter() - mark

    mark = time.perf_counter()
    outcomes = build_outcome_table(store)
    timings["unit_o_compute"] = time.perf_counter() - mark

    mark = time.perf_counter()
    _complete_stage(staging_root, store, outcomes, environment=environment)
    _validate_artifact_tree(
        staging_root,
        expected_source_manifest_sha256=_sha256_file(store.root / "manifest.json"),
        expected_phase7_rows=product.row_counts,
        expected_outcome_rows=outcomes.row_count,
    )
    timings["unit_o_write_and_full_verify"] = time.perf_counter() - mark
    timings["total"] = time.perf_counter() - started
    _, traced_peak = tracemalloc.get_traced_memory()
    peak_memory = max(int(traced_peak), _peak_process_memory_bytes())
    tracemalloc.stop()

    return _finalize_staged_run(
        staging_root,
        output_root,
        store=store,
        product=product,
        outcome_row_count=outcomes.row_count,
        staged=staged,
        stage_seconds=timings,
        peak_memory_bytes=peak_memory,
        environment=environment,
    )


def main() -> None:
    if sys.argv[1:]:
        raise SpineError("the fixed shakedown entry point accepts no arguments")
    manifest = run_shakedown()
    summary = {
        "admissibility": manifest["admissibility"],
        "output_root": OUTPUT_ROOT.relative_to(REPO_ROOT).as_posix(),
        "row_counts": manifest["row_counts"],
        "stage_seconds": manifest["stage_seconds"],
        "peak_memory_bytes": manifest["peak_memory_bytes"],
        "outcome_values_inspected": False,
        "phase8_executed": False,
    }
    print(_canonical_json_bytes(summary).decode("utf-8"), end="")


if __name__ == "__main__":
    main()


__all__ = [
    "GATE_CLASSIFICATION",
    "OUTPUT_ROOT",
    "RUN_MANIFEST_NAME",
    "run_shakedown",
]
