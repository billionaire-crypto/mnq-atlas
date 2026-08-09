"""Real-input adapter and complete Phase 8 Step 7 inventory computation.

This module contains no configurable corpus path.  It receives manifests only
from :mod:`mnq_lab.phase8.runner` after ratification and builds every declared
row in literal inventory order.  Point rows are computed before interval
requests, so a non-``ok`` row can never enter the bootstrap.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Hashable, Mapping

import numpy as np

from mnq_lab import SpineError
from mnq_lab.conditioners.calendar import CALENDAR_SHA256, CALENDAR_VERSION
from mnq_lab.constants import CONSTANTS_PATH, REPO_ROOT, SPEC_PATH
from mnq_lab.phase8.artifacts import (
    CONTRAST_COLUMNS, DAY_TYPE_COLUMNS, INTERACTION_COLUMNS, INTERVAL_COLUMNS,
    Phase8Table,
)
from mnq_lab.phase8.contrasts import (
    OUTCOME_NAMES, SESSION_PHASES, VOLATILITY_STATES, CellKey,
    contrast_support, degenerate_baseline, support_masks, weighted_quantile_ticks,
)
from mnq_lab.phase8.day_types import DAY_TYPES, declared_day_type_rows, evaluate_day_type_distribution
from mnq_lab.phase8.diagnostics import (
    PositivityStratumInput, anchor_support_failure, completion_diagnostics,
    positivity_diagnostics, status_decision,
)
from mnq_lab.phase8.estimands import build_estimand_weights
from mnq_lab.phase8.interactions import (
    DESCRIPTIVE_ONLY_LABEL, build_four_cell_support, declared_interaction_rows,
    evaluate_interaction,
)
from mnq_lab.phase8.inventory import (
    ALTERNATIVE_ARM_IDS, PRIMARY_ARM_ID, ResultRowSpec, declared_result_rows,
)
from mnq_lab.phase8 import progress as _progress
from mnq_lab.phase8.preflight import BootstrapTermKey, TermSupportRecord, build_term_support_record
from mnq_lab.phase8.uncertainty import (
    BootstrapIntervalRequest, BootstrapQuantileTerm, bootstrap_contract,
)

_INT32 = np.iinfo(np.int32)
COMMON_SUPPORT_HORIZON_MINUTES = 60

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _row_id(kind: str, values: tuple[Any, ...]) -> str:
    payload = json.dumps((kind, values), separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _json(value: Any) -> str:
    def default(item: Any) -> Any:
        if isinstance(item, CellKey):
            return [item.phase, item.volatility_state]
        if isinstance(item, np.generic):
            return item.item()
        if hasattr(item, "__dict__"):
            return item.__dict__
        return str(item)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=default)


def _year_quarter(session_ids: np.ndarray) -> np.ndarray:
    years = session_ids.astype(np.int64) // 10_000
    months = (session_ids.astype(np.int64) // 100) % 100
    quarters = ((months - 1) // 3) + 1
    return np.char.add(np.char.add(years.astype("<U4"), "Q"), quarters.astype("<U1"))


def _read_column(root: Path, table_root: str, manifest: Mapping[str, Any], name: str) -> np.ndarray:
    record = manifest["columns"][name]
    path = root / table_root / record["file"]
    array = np.load(path, mmap_mode="r", allow_pickle=False)
    if str(array.dtype) != record["dtype"] or array.size != int(record["rows"]):
        raise SpineError(f"Phase 8 input column {name!r} differs from its manifest")
    return array


@dataclass(frozen=True)
class ArmFrame:
    arm_id: str
    sessions: np.ndarray
    timestamps: np.ndarray
    phases: np.ndarray
    states: np.ndarray
    active: np.ndarray
    session_class: np.ndarray
    data_quality: np.ndarray
    holiday_adjacent: np.ndarray
    category_code: np.ndarray


@dataclass(frozen=True)
class ProductionInputs:
    root: Path
    unit: Mapping[str, np.ndarray]
    arms: Mapping[str, ArmFrame]
    run_manifest: Mapping[str, Any]
    unit_manifest: Mapping[str, Any]
    phase7_manifest: Mapping[str, Any]
    input_manifest_sha256: tuple[tuple[str, str], ...]


def open_production_inputs(
    root: Path,
    *,
    run_manifest: Mapping[str, Any],
    unit_manifest: Mapping[str, Any],
    phase7_manifest: Mapping[str, Any],
    input_manifest_sha256: tuple[tuple[str, str], ...],
) -> ProductionInputs:
    """Open arrays only after the caller has passed ratification."""
    unit_names = (
        "estimand", "session_id", "ts_event_ns", "horizon_minutes",
        "window_fits_rth", "common_support", "outcome_valid", *OUTCOME_NAMES,
    )
    unit = {name: _read_column(root, "unit_o", unit_manifest, name) for name in unit_names}
    assignment = phase7_manifest["tables"]["assignments"]
    columns = {
        name: _read_column(root, "phase7", assignment, name)
        for name in (
            "arm_id", "session_id", "ts_event_ns", "session_phase", "category_name",
            "assignment_status", "calendar_session_class", "data_quality_status",
            "holiday_adjacent", "category_code",
        )
    }
    arms: dict[str, ArmFrame] = {}
    for arm_id in (PRIMARY_ARM_ID, *ALTERNATIVE_ARM_IDS):
        mask = columns["arm_id"] == arm_id
        states = np.asarray(columns["category_name"][mask]).copy()
        active = np.asarray(columns["assignment_status"][mask] == "ok", dtype=np.bool_)
        states[~active] = VOLATILITY_STATES[0]
        arms[arm_id] = ArmFrame(
            arm_id, np.asarray(columns["session_id"][mask]),
            np.asarray(columns["ts_event_ns"][mask]),
            np.asarray(columns["session_phase"][mask]), states, active,
            np.asarray(columns["calendar_session_class"][mask]),
            np.asarray(columns["data_quality_status"][mask]),
            np.asarray(columns["holiday_adjacent"][mask]),
            np.asarray(columns["category_code"][mask]),
        )
    return ProductionInputs(
        Path(root), unit, arms, run_manifest, unit_manifest, phase7_manifest,
        input_manifest_sha256,
    )


@dataclass(frozen=True)
class ProductionComputation:
    contrast_table: Phase8Table
    day_type_table: Phase8Table
    interaction_table: Phase8Table
    group_ids: np.ndarray
    term_recipes: tuple["BootstrapTermRecipe", ...]
    requests: tuple[Any, ...]
    census: tuple[TermSupportRecord, ...]

    def materialize_terms(self, term_ids: set[Hashable]) -> tuple[BootstrapQuantileTerm, ...]:
        selected = tuple(recipe for recipe in self.term_recipes if recipe.term_id in term_ids)
        if {recipe.term_id for recipe in selected} != term_ids:
            raise SpineError("interval chunk names an undeclared compact term")
        return tuple(recipe.materialize(self.group_ids.size) for recipe in selected)

    @property
    def distinct_term_count(self) -> int:
        return len({recipe.support_digest for recipe in self.term_recipes})


@dataclass(frozen=True)
class BootstrapTermRecipe:
    term_id: Hashable
    support_digest: str
    eligible_rows: np.ndarray
    eligible_values: np.ndarray
    eligible_weights: np.ndarray
    statistic: str

    def materialize(self, frame_size: int) -> BootstrapQuantileTerm:
        values = np.zeros(frame_size, dtype=np.int32)
        mask = np.zeros(frame_size, dtype=np.bool_)
        weights = np.zeros(frame_size, dtype=np.float64)
        values[self.eligible_rows] = self.eligible_values
        mask[self.eligible_rows] = True
        weights[self.eligible_rows] = self.eligible_weights
        return BootstrapQuantileTerm(
            self.term_id, values, mask, weights, self.statistic
        )


class _TermRegistry:
    def __init__(self) -> None:
        self._payloads: dict[str, list[tuple[np.ndarray, np.ndarray, np.ndarray]]] = {}
        self._recipe_by_key: dict[tuple[str, int, str], BootstrapTermRecipe] = {}
        self._recipes: list[BootstrapTermRecipe] = []

    def register(self, values: np.ndarray, weights: np.ndarray, statistic: str) -> Hashable:
        rows = np.flatnonzero(weights > 0.0).astype(np.int32, copy=False)
        if rows.size == 0:
            raise SpineError("an ok point row cannot register an empty bootstrap term")
        local_values = np.asarray(values[rows], dtype=np.int32)
        local_weights = np.asarray(weights[rows], dtype=np.float64)
        return self.register_payload(rows, local_values, local_weights, statistic)

    def register_payload(
        self,
        rows: np.ndarray,
        local_values: np.ndarray,
        local_weights: np.ndarray,
        statistic: str,
    ) -> Hashable:
        """Assign a term identifier from an already-compacted payload.

        This is the ONLY place a term identifier is minted. ``payload_index``
        disambiguates a digest collision by position within that digest's
        bucket, so it is meaningful only relative to the registry that
        assigned it. A worker registry cannot mint a globally valid
        identifier: two workers would each assign index 0 to different
        payloads under the same digest and produce one identifier for two
        distinct terms. Workers therefore return opaque local handles and
        the parent registers every payload here, in declared order.
        """
        if rows.size == 0:
            raise SpineError("an ok point row cannot register an empty bootstrap term")
        digest = hashlib.sha256()
        for array in (rows, local_values, local_weights):
            digest.update(str(array.dtype).encode("ascii"))
            digest.update(np.asarray(array.shape, dtype=np.int64).tobytes())
            digest.update(array.tobytes(order="C"))
        hexdigest = digest.hexdigest()
        bucket = self._payloads.setdefault(hexdigest, [])
        payload_index = None
        for index, payload in enumerate(bucket):
            known_rows, known_values, known_weights = payload
            if (
                np.array_equal(rows, known_rows)
                and np.array_equal(local_values, known_values)
                and np.array_equal(local_weights, known_weights)
            ):
                payload_index = index
                rows, local_values, local_weights = known_rows, known_values, known_weights
                break
        if payload_index is None:
            payload_index = len(bucket)
            rows = rows.copy(); local_values = local_values.copy(); local_weights = local_weights.copy()
            for array in (rows, local_values, local_weights):
                array.setflags(write=False)
            bucket.append((rows, local_values, local_weights))
        key = (hexdigest, payload_index, statistic)
        existing = self._recipe_by_key.get(key)
        if existing is not None:
            return existing.term_id
        term_id = ("compact", hexdigest, payload_index, statistic)
        recipe = BootstrapTermRecipe(
            term_id, f"{hexdigest}:{payload_index}", rows, local_values,
            local_weights, statistic,
        )
        self._recipe_by_key[key] = recipe
        self._recipes.append(recipe)
        return term_id

    @property
    def recipes(self) -> tuple[BootstrapTermRecipe, ...]:
        return tuple(self._recipes)


def _cell_tuple(cell: CellKey) -> tuple[str, str]:
    return cell.phase, cell.volatility_state


def _spec_key(spec: ResultRowSpec) -> tuple[Any, ...]:
    return (
        spec.arm_id, spec.outcome_name, spec.path_estimand, spec.support_kind,
        spec.horizon_minutes, spec.statistic, spec.contrast_name,
        spec.population_estimand, spec.contrast_weighting, *_cell_tuple(spec.target_cell),
    )


def _migration(primary: ArmFrame, alternative: ArmFrame) -> str:
    if not np.array_equal(primary.sessions, alternative.sessions) or not np.array_equal(primary.timestamps, alternative.timestamps):
        raise SpineError("Phase 7 migration supports differ")
    left = primary.category_code
    right = alternative.category_code
    common = (left != -1) & (right != -1)
    changed = common & (left != right)
    return _json({
        "alternative_arm_id": alternative.arm_id,
        "common_defined": int(np.count_nonzero(common)),
        "changed_defined": int(np.count_nonzero(changed)),
        "changed_fraction": 0.0 if not bool(np.any(common)) else float(np.count_nonzero(changed) / np.count_nonzero(common)),
        "primary_defined_alternative_undefined": int(np.count_nonzero((left != -1) & (right == -1))),
        "primary_undefined_alternative_defined": int(np.count_nonzero((left == -1) & (right != -1))),
    })


def _table_from_rows(name: str, columns: tuple[str, ...], rows: list[dict[str, Any]]) -> Phase8Table:
    integer_columns = {
        "horizon_minutes", "target_quantile_ticks", "baseline_quantile_ticks",
        "contrast_ticks", "n_anchors", "n_sessions", "baseline_n_anchors",
        "baseline_n_sessions", "quantile_ticks", "interaction_ticks",
        "common_n_sessions", "mean_block_sessions", "draws", "ci_lower_ticks",
        "ci_upper_ticks",
    }
    bool_columns = {
        "target_quantile_valid", "baseline_quantile_valid", "contrast_valid",
        "quantile_valid", "interaction_valid", "interval_valid",
    }
    float_columns = {
        "weight_ess", "baseline_weight_ess", "completion_target",
        "completion_baseline", "completion_imbalance", "unsupported_target_mass",
        "quarter_unsupported_target_mass", "max_single_anchor_weight_share",
        "weight_cv", "confidence_level",
    }
    arrays = []
    for column in columns:
        values = [row[column] for row in rows]
        if column in integer_columns:
            array = np.asarray([0 if value is None else value for value in values], dtype=np.int64)
        elif column in bool_columns:
            array = np.asarray(values, dtype=np.bool_)
        elif column in float_columns:
            array = np.asarray([np.nan if value is None else value for value in values], dtype=np.float64)
        else:
            array = np.asarray(["" if value is None else str(value) for value in values])
        arrays.append((column, array))
    return Phase8Table(name, tuple(arrays))


def _slice(inputs: ProductionInputs, path_estimand: str, horizon: int) -> tuple[np.ndarray, ...]:
    unit = inputs.unit
    mask = (unit["estimand"] == path_estimand) & (unit["horizon_minutes"] == horizon)
    sessions = np.asarray(unit["session_id"][mask])
    timestamps = np.asarray(unit["ts_event_ns"][mask])
    return (
        mask, sessions, timestamps,
        np.asarray(unit["outcome_valid"][mask], dtype=np.bool_),
        np.asarray(unit["common_support"][mask], dtype=np.bool_),
        np.asarray(unit["window_fits_rth"][mask], dtype=np.bool_),
    )


@dataclass(frozen=True)
class _CensusEntry:
    identity: str
    key: BootstrapTermKey
    support_sessions: tuple[Hashable, ...]
    status: str


@dataclass(frozen=True)
class _ContrastEntry:
    index: int
    row: dict[str, Any]
    census: tuple[_CensusEntry, ...]
    request: tuple[Any, ...] | None


@dataclass(frozen=True)
class _ContrastPartition:
    entries: tuple[_ContrastEntry, ...]
    # Opaque worker-local handle -> raw compact payload. A handle is NOT a
    # term identifier and is meaningless outside its own partition; only the
    # parent's single registry mints identifiers.
    payloads: Mapping[Hashable, tuple[np.ndarray, np.ndarray, np.ndarray, str]]


@dataclass(frozen=True)
class _MergedContrastPartitions:
    """Parent-owned, declared-order result of merging worker partitions."""

    rows: tuple[dict[str, Any], ...]
    registry: "_TermRegistry"
    requests: tuple[BootstrapIntervalRequest, ...]
    census: tuple[TermSupportRecord, ...]
    census_identities: frozenset[str]


def _census_identity(
    key: BootstrapTermKey,
    weights_for_identity: np.ndarray,
    status: str,
    outcome_name: str,
    empty_axis_key: tuple[Any, ...],
) -> str:
    digest = hashlib.sha256()
    positive = np.flatnonzero(weights_for_identity > 0.0)
    digest.update(key.family.encode("ascii"))
    digest.update(key.term_role.encode("utf-8"))
    digest.update(outcome_name.encode("ascii"))
    digest.update(status.encode("ascii"))
    digest.update(positive.tobytes())
    digest.update(np.asarray(weights_for_identity[positive], dtype=np.float64).tobytes())
    if positive.size == 0:
        digest.update(repr(empty_axis_key).encode("utf-8"))
    return digest.hexdigest()


def _contrast_partition(
    inputs: ProductionInputs,
    indexed_specs: tuple[tuple[int, ResultRowSpec], ...],
    migrations: Mapping[str, str],
    progress: Any = None,
) -> _ContrastPartition:
    """Compute contrast rows for a subset of declared specs with no shared state.

    The arithmetic is identical to the serial loop. Term registration is local
    to this partition and census de-duplication is deferred to the caller, so
    partitions can be merged in declared order to reproduce the serial output
    byte for byte. The caller must preserve declared order when merging.
    """
    # Local registry ONLY to de-duplicate identical payloads inside this
    # partition and shrink what is shipped back. Its identifiers are opaque
    # handles; see _TermRegistry.register_payload for why they cannot be
    # used globally.
    local_handles = _TermRegistry()
    entries: list[_ContrastEntry] = []
    slice_cache: dict[tuple[str, int], tuple[np.ndarray, ...]] = {}
    weight_cache: dict[tuple[Any, ...], Any] = {}
    diagnostic_cache: dict[tuple[Any, ...], tuple[Any, Any, Any]] = {}
    value_cache: dict[tuple[str, str, int], np.ndarray] = {}
    active_cache_scope: tuple[Any, ...] | None = None

    for position, (index, spec) in enumerate(indexed_specs, start=1):
        cache_scope = (
            spec.arm_id, spec.outcome_name, spec.path_estimand,
            spec.support_kind, spec.horizon_minutes,
        )
        if cache_scope != active_cache_scope:
            weight_cache.clear()
            diagnostic_cache.clear()
            active_cache_scope = cache_scope
        slice_key = (spec.path_estimand, spec.horizon_minutes)
        if slice_key not in slice_cache:
            slice_cache[slice_key] = _slice(inputs, *slice_key)
        unit_mask, sessions, timestamps, valid, common, _window_fits = slice_cache[slice_key]
        arm = inputs.arms[spec.arm_id]
        if not np.array_equal(sessions, arm.sessions) or not np.array_equal(timestamps, arm.timestamps):
            raise SpineError("Unit O and Phase 7 assignment keys differ")
        completed = valid if spec.support_kind == "horizon_specific" else (valid & common)
        structurally_eligible = _structural_completion_eligibility(
            slice_cache, inputs, arm=arm, path_estimand=spec.path_estimand,
            support_kind=spec.support_kind, horizon_minutes=spec.horizon_minutes,
        )
        eligible = completed & arm.active
        ordinary = (arm.session_class == "regular") & (arm.data_quality == "ok")
        quarters = _year_quarter(sessions)
        cache_key = (
            spec.arm_id, spec.path_estimand, spec.support_kind, spec.horizon_minutes,
            spec.contrast_name, spec.population_estimand, spec.contrast_weighting,
            spec.target_cell,
        )
        if cache_key not in weight_cache:
            weight_cache[cache_key] = build_estimand_weights(
                estimand_name=spec.population_estimand, session_ids=sessions,
                calendar_quarters=quarters, session_phases=arm.phases,
                volatility_states=arm.states, outcome_eligible=eligible,
                ordinary_full_length=ordinary, target=spec.target_cell,
                contrast_name=spec.contrast_name,
                contrast_weighting=spec.contrast_weighting,
            )
        weights = weight_cache[cache_key]
        if cache_key not in diagnostic_cache:
            masks = support_masks(arm.phases, arm.states, spec.target_cell, spec.contrast_name)
            completion = completion_diagnostics(
                horizon_minutes=spec.horizon_minutes, session_ids=sessions,
                calendar_years=sessions.astype(np.int64) // 10_000,
                structurally_eligible=structurally_eligible, completed=completed,
                target_mask=masks.target, target_weights=weights.target.weights,
                baseline_mask=None if weights.baseline is None else masks.baseline,
                baseline_weights=None if weights.baseline is None else weights.baseline.weights,
            )
            positivity = None
            if weights.baseline is not None:
                baseline_cells = contrast_support(spec.target_cell, spec.contrast_name).baseline_cells
                baseline_by_cell = {item.cell: item for item in weights.baseline.cells}
                strata = tuple(
                    PositivityStratumInput(
                        stratum=cell,
                        target_weights=np.asarray([baseline_by_cell[cell].assigned_mass], dtype=np.float64),
                        baseline_session_ids=tuple(sessions[
                            eligible & (arm.phases == cell.phase) & (arm.states == cell.volatility_state)
                        ]),
                    )
                    for cell in baseline_cells
                )
                positivity = positivity_diagnostics(
                    strata=strata, target=spec.target_cell,
                    contrast_name=spec.contrast_name,
                    population_estimand=spec.population_estimand,
                    quarter_unsupported_target_mass=weights.baseline.unsupported_target_mass
                    if spec.population_estimand == "standardized_shared_population" else 0.0,
                )
            degenerate = False
            if weights.baseline is not None and weights.target.n_anchors and weights.baseline.n_anchors:
                target_rows = np.flatnonzero(weights.target.weights > 0.0)
                baseline_rows = np.flatnonzero(weights.baseline.weights > 0.0)
                degenerate = degenerate_baseline(
                    tuple(target_rows), weights.target.weights[target_rows],
                    tuple(baseline_rows), weights.baseline.weights[baseline_rows],
                )
            anchors_failed = anchor_support_failure(
                target_n_anchors=weights.target.n_anchors,
                target_n_sessions=weights.target.n_sessions,
                baseline_n_anchors=None if weights.baseline is None else weights.baseline.n_anchors,
                baseline_n_sessions=None if weights.baseline is None else weights.baseline.n_sessions,
                has_baseline=weights.baseline is not None,
            )
            decision = status_decision(
                degenerate_baseline=degenerate,
                insufficient_anchors=anchors_failed,
                insufficient_completion=completion.insufficient_completion,
                insufficient_overlap=False if positivity is None else positivity.insufficient_overlap,
            )
            diagnostic_cache[cache_key] = (completion, positivity, decision)
        completion, positivity, decision = diagnostic_cache[cache_key]
        value_key = (spec.outcome_name, spec.path_estimand, spec.horizon_minutes)
        if value_key not in value_cache:
            values = np.asarray(inputs.unit[spec.outcome_name][unit_mask], dtype=np.int32)
            values.setflags(write=False)
            value_cache[value_key] = values
        values = value_cache[value_key]
        target_tick = baseline_tick = contrast_tick = None
        if decision.status == "ok":
            target_tick = weighted_quantile_ticks(
                values[weights.target.weights > 0.0],
                weights.target.weights[weights.target.weights > 0.0], spec.statistic,
            )
            if weights.baseline is not None:
                baseline_tick = weighted_quantile_ticks(
                    values[weights.baseline.weights > 0.0],
                    weights.baseline.weights[weights.baseline.weights > 0.0], spec.statistic,
                )
                contrast_tick = int(np.int64(target_tick) - np.int64(baseline_tick))
        rid = _row_id("contrast", _spec_key(spec))
        target_term_id = baseline_term_id = None
        census_entries: list[_CensusEntry] = []
        for role, condition in (("target", weights.target), ("baseline", weights.baseline)):
            if condition is None:
                continue
            support_sessions = tuple(sessions[condition.weights > 0.0])
            census_key = BootstrapTermKey("contrast", _spec_key(spec), role)
            census_entries.append(_CensusEntry(
                _census_identity(
                    census_key, condition.weights, decision.status, spec.outcome_name,
                    _spec_key(spec)[:5] + _spec_key(spec)[6:],
                ),
                census_key, support_sessions, decision.status,
            ))
        request = None
        if decision.status == "ok":
            target_term_id = local_handles.register(values, weights.target.weights, spec.statistic)
            if weights.baseline is not None:
                baseline_term_id = local_handles.register(values, weights.baseline.weights, spec.statistic)
            request = (rid, target_term_id, baseline_term_id, decision)
        max_share = weight_cv = unsupported = quarter_unsupported = None
        if positivity is not None:
            shares = [item.max_single_anchor_weight_share for item in positivity.strata if item.max_single_anchor_weight_share is not None]
            cvs = [item.weight_cv for item in positivity.strata if item.weight_cv is not None]
            max_share = max(shares) if shares else None
            weight_cv = max(cvs) if cvs else None
            unsupported = positivity.unsupported_target_mass
            quarter_unsupported = positivity.quarter_unsupported_target_mass
        entries.append(_ContrastEntry(index, {
            "row_id": rid, "arm_id": spec.arm_id, "outcome_name": spec.outcome_name,
            "path_estimand": spec.path_estimand, "support_kind": spec.support_kind,
            "horizon_minutes": spec.horizon_minutes, "statistic": spec.statistic,
            "contrast_name": spec.contrast_name, "population_estimand": spec.population_estimand,
            "contrast_weighting": spec.contrast_weighting, "target_phase": spec.target_cell.phase,
            "target_vol_tercile": spec.target_cell.volatility_state,
            "target_quantile_ticks": target_tick, "target_quantile_valid": target_tick is not None,
            "baseline_quantile_ticks": baseline_tick, "baseline_quantile_valid": baseline_tick is not None,
            "contrast_ticks": target_tick if weights.baseline is None else contrast_tick,
            "contrast_valid": target_tick is not None if weights.baseline is None else contrast_tick is not None,
            "n_anchors": weights.target.n_anchors, "n_sessions": weights.target.n_sessions,
            "weight_ess": weights.target.weight_ess,
            "baseline_n_anchors": None if weights.baseline is None else weights.baseline.n_anchors,
            "baseline_n_sessions": None if weights.baseline is None else weights.baseline.n_sessions,
            "baseline_weight_ess": None if weights.baseline is None else weights.baseline.weight_ess,
            "completion_target": completion.target.completion_rate,
            "completion_baseline": None if completion.baseline is None else completion.baseline.completion_rate,
            "completion_imbalance": completion.completion_imbalance,
            "unsupported_target_mass": unsupported,
            "quarter_unsupported_target_mass": quarter_unsupported,
            "max_single_anchor_weight_share": max_share, "weight_cv": weight_cv,
            "status": decision.status, "status_flags": _json(decision.status_flags),
            "migration_diagnostics": "" if spec.arm_id == PRIMARY_ARM_ID else migrations[spec.arm_id],
        }, tuple(census_entries), request))
        if progress is not None:
            progress.advance(position)
    return _ContrastPartition(tuple(entries), {
        recipe.term_id: (
            recipe.eligible_rows, recipe.eligible_values,
            recipe.eligible_weights, recipe.statistic,
        )
        for recipe in local_handles.recipes
    })


def _partition_indexed_specs(
    indexed_specs: tuple[tuple[int, ResultRowSpec], ...], partition_count: int,
) -> tuple[tuple[tuple[int, ResultRowSpec], ...], ...]:
    """Split declared specs into partitions without splitting a weight cache key.

    Specs sharing a cache key share one ``build_estimand_weights`` result, so a
    key split across partitions would recompute it. Keys are NOT contiguous in
    declared order -- 5,130 distinct keys are scattered across 29,430 positions
    -- so partitioning must group by key rather than by position. Declared
    order is carried on each spec's index and restored by the caller.
    """
    groups: dict[tuple[Any, ...], list[tuple[int, ResultRowSpec]]] = {}
    for index, spec in indexed_specs:
        key = (
            spec.arm_id, spec.outcome_name, spec.path_estimand, spec.support_kind,
            spec.horizon_minutes, spec.contrast_name, spec.population_estimand,
            spec.contrast_weighting, spec.target_cell,
        )
        groups.setdefault(key, []).append((index, spec))
    ordered_groups = sorted(groups.values(), key=lambda group: group[0][0])
    if partition_count <= 1 or len(ordered_groups) <= 1:
        return (tuple(indexed_specs),)
    buckets: list[list[tuple[int, ResultRowSpec]]] = [
        [] for _ in range(min(partition_count, len(ordered_groups)))
    ]
    # Longest group first into the currently smallest bucket: the largest unit
    # sets the wall clock, so it must not be scheduled last.
    #
    # Groups are appended WHOLE and are deliberately NOT re-sorted by declared
    # index afterwards. weight_cache and diagnostic_cache clear whenever
    # cache_scope changes, so a bucket resorted into declared order would
    # interleave scopes and recompute weights the serial sweep computes once.
    # Intra-partition order cannot affect any output value: every spec carries
    # its declared index, and the parent merges strictly by that index before
    # its single registry mints global identifiers. Worker-local identifiers
    # are opaque handles only. Keeping a group contiguous is therefore free
    # correctness-wise and materially cheaper.
    for group in sorted(ordered_groups, key=len, reverse=True):
        smallest = min(buckets, key=len)
        smallest.extend(group)
    return tuple(tuple(bucket) for bucket in buckets if bucket)


PHASE8_STAGE1_WORKERS_ENV = "MNQ_PHASE8_STAGE1_WORKERS"


def _contrast_worker_count() -> int:
    """Resolve stage 1 worker count.

    Defaults to serial. Parallelism is opt-in through the environment so no
    existing caller, test or fixture silently changes execution mode, and so
    the single-core path stays available as the identity oracle. ``0`` or a
    negative value means every available core.
    """
    raw = os.environ.get(PHASE8_STAGE1_WORKERS_ENV)
    if raw is None or not raw.strip():
        return 1
    try:
        requested = int(raw)
    except ValueError as exc:
        raise SpineError(
            f"{PHASE8_STAGE1_WORKERS_ENV} must be an integer, got {raw!r}"
        ) from exc
    if requested <= 0:
        return max(1, os.cpu_count() or 1)
    return requested


def _run_contrast_partitions(
    inputs: ProductionInputs,
    partitions: tuple[tuple[tuple[int, ResultRowSpec], ...], ...],
    progress: Any,
) -> list[_ContrastPartition]:
    """Run contrast partitions in worker processes and collect their results.

    Results are returned in completion order; the caller restores declared
    order from each entry's index, so completion order cannot affect output.
    """
    import multiprocessing

    # Use an explicit start-method context, matching the existing bootstrap
    # executor in uncertainty.py rather than relying on the interpreter
    # default: spawn on Windows, fork on POSIX. Under spawn, each child
    # re-imports the entry module, so any caller must guard its entry point
    # with ``if __name__ == "__main__"`` or the pool cannot start.
    context = multiprocessing.get_context(
        "spawn" if os.name == "nt" else "fork"
    )
    # Each worker owns one complete cache-preserving partition and can retain
    # tens of GiB in its Python allocator after returning that partition.  A
    # persistent executor therefore keeps the worker heap resident while the
    # same payload accumulates in the parent.  ``maxtasksperchild=1`` makes the
    # operating lifetime match the scientific work unit: once the one
    # partition has been serialized, that process exits and releases its
    # private heap.  This changes no partition, row, payload, or merge order.
    pool = context.Pool(
        processes=len(partitions),
        initializer=_worker_initializer,
        initargs=(
            str(inputs.root), inputs.run_manifest, inputs.unit_manifest,
            inputs.phase7_manifest, inputs.input_manifest_sha256,
        ),
        maxtasksperchild=1,
    )
    results: list[_ContrastPartition] = []
    completed_specs = 0
    try:
        completed = pool.imap_unordered(
            _worker_contrast_partition, partitions, chunksize=1
        )
        pool.close()
        for result in completed:
            results.append(result)
            completed_specs += len(result.entries)
            if progress is not None:
                progress.advance(completed_specs)
        pool.join()
    except BaseException:
        pool.terminate()
        pool.join()
        raise
    return results


_WORKER_STATE: dict[str, Any] = {}


def _worker_initializer(
    root: str,
    run_manifest: Mapping[str, Any],
    unit_manifest: Mapping[str, Any],
    phase7_manifest: Mapping[str, Any],
    input_manifest_sha256: tuple[tuple[str, str], ...],
) -> None:
    """Open the ratified inputs once per worker.

    ``ProductionInputs`` holds memory-mapped arrays that cannot be pickled, so
    each worker opens its own from the same ratified root. This is spawn-safe
    on Windows as well as fork-safe on Linux.
    """
    inputs = open_production_inputs(
        Path(root), run_manifest=run_manifest, unit_manifest=unit_manifest,
        phase7_manifest=phase7_manifest, input_manifest_sha256=input_manifest_sha256,
    )
    primary = inputs.arms[PRIMARY_ARM_ID]
    _WORKER_STATE["inputs"] = inputs
    _WORKER_STATE["migrations"] = {
        arm: _migration(primary, inputs.arms[arm]) for arm in ALTERNATIVE_ARM_IDS
    }


def _worker_contrast_partition(
    indexed_specs: tuple[tuple[int, ResultRowSpec], ...],
) -> _ContrastPartition:
    return _contrast_partition(
        _WORKER_STATE["inputs"], indexed_specs, _WORKER_STATE["migrations"],
    )


def _merge_contrast_partitions(
    results: tuple[_ContrastPartition, ...],
) -> _MergedContrastPartitions:
    """Merge opaque worker handles through one parent-owned term registry.

    Completion order and worker-local mapping order are deliberately ignored.
    Every identifier is minted centrally while entries are visited in declared
    structural order. A worker handle is scoped to its partition and cannot
    reach an output request.
    """
    registry = _TermRegistry()
    rows: list[dict[str, Any]] = []
    requests: list[BootstrapIntervalRequest] = []
    census: list[TermSupportRecord] = []
    census_seen: set[str] = set()
    handle_to_global: dict[tuple[int, Hashable], Hashable] = {}
    payload_by_handle = {
        (part_index, handle): payload
        for part_index, part in enumerate(results)
        for handle, payload in part.payloads.items()
    }
    entry_partition = {
        id(entry): part_index
        for part_index, part in enumerate(results)
        for entry in part.entries
    }
    entries = sorted(
        (entry for part in results for entry in part.entries),
        key=lambda item: item.index,
    )
    if len({entry.index for entry in entries}) != len(entries):
        raise SpineError("contrast partitions contain a duplicate declared index")
    for entry in entries:
        rows.append(entry.row)
        for census_entry in entry.census:
            if census_entry.identity not in census_seen:
                census_seen.add(census_entry.identity)
                census.append(build_term_support_record(
                    key=census_entry.key,
                    session_ids=census_entry.support_sessions,
                    status=census_entry.status,
                ))
        if entry.request is None:
            continue
        rid, target_handle, baseline_handle, decision = entry.request
        global_ids: list[Hashable | None] = []
        for handle in (target_handle, baseline_handle):
            if handle is None:
                global_ids.append(None)
                continue
            scoped = (entry_partition[id(entry)], handle)
            if scoped not in payload_by_handle:
                raise SpineError("contrast partition request has no term payload")
            resolved = handle_to_global.get(scoped)
            if resolved is None:
                resolved = registry.register_payload(*payload_by_handle[scoped])
                handle_to_global[scoped] = resolved
            global_ids.append(resolved)
        requests.append(BootstrapIntervalRequest(
            rid, global_ids[0], global_ids[1], decision,
        ))
    return _MergedContrastPartitions(
        tuple(rows), registry, tuple(requests), tuple(census),
        frozenset(census_seen),
    )


def _cached_slice(
    cache: dict[tuple[str, int], tuple[np.ndarray, ...]],
    inputs: ProductionInputs,
    key: tuple[str, int],
) -> tuple[np.ndarray, ...]:
    """Return an input slice, rebuilding a worker-local cache miss."""
    cached = cache.get(key)
    if cached is None:
        cached = _slice(inputs, *key)
        cache[key] = cached
    return cached


def _structural_completion_eligibility(
    cache: dict[tuple[str, int], tuple[np.ndarray, ...]],
    inputs: ProductionInputs,
    *,
    arm: ArmFrame,
    path_estimand: str,
    support_kind: str,
    horizon_minutes: int,
) -> np.ndarray:
    """Return D31/D32's structural completion denominator.

    Unit O v2 stores ``window_fits_rth`` after resolving every anchor against
    the explicit session schedule table. Horizon-specific rows use the named
    horizon. Common-support rows deliberately use the aligned 60-minute row,
    which is the contract's longest common window.
    """
    current = _cached_slice(cache, inputs, (path_estimand, horizon_minutes))
    _, sessions, timestamps, _, _, named_window_fits = current
    if not np.array_equal(sessions, arm.sessions) or not np.array_equal(
        timestamps, arm.timestamps
    ):
        raise SpineError("Unit O and Phase 7 assignment keys differ")

    if support_kind == "horizon_specific":
        structural_fit = named_window_fits
    elif support_kind == "common_support":
        support = _cached_slice(
            cache, inputs, (path_estimand, COMMON_SUPPORT_HORIZON_MINUTES)
        )
        _, support_sessions, support_timestamps, _, _, structural_fit = support
        if not np.array_equal(sessions, support_sessions) or not np.array_equal(
            timestamps, support_timestamps
        ):
            raise SpineError("60-minute structural-support keys differ from named horizon")
    else:
        raise SpineError(f"unknown support kind {support_kind!r}")

    structural_fit = np.asarray(structural_fit, dtype=np.bool_)
    if structural_fit.shape != arm.active.shape:
        raise SpineError("structural-fit mask and Phase 7 activity shape differ")
    return np.asarray(arm.active, dtype=np.bool_) & structural_fit


def build_production_computation(inputs: ProductionInputs) -> ProductionComputation:
    """Compute all point inventories and construct only status-ok interval requests."""
    declared = declared_result_rows()
    contrast_rows: list[dict[str, Any]] = []
    day_rows: list[dict[str, Any]] = []
    interaction_rows: list[dict[str, Any]] = []
    registry = _TermRegistry()
    requests: list[Any] = []
    census: list[TermSupportRecord] = []
    census_seen: set[str] = set()
    primary = inputs.arms[PRIMARY_ARM_ID]
    migrations = {arm: _migration(primary, inputs.arms[arm]) for arm in ALTERNATIVE_ARM_IDS}
    cells = tuple(CellKey(phase, state) for phase in SESSION_PHASES for state in VOLATILITY_STATES)
    slice_cache: dict[tuple[str, int], tuple[np.ndarray, ...]] = {}
    weight_cache: dict[tuple[Any, ...], Any] = {}
    diagnostic_cache: dict[tuple[Any, ...], tuple[Any, Any, Any]] = {}
    value_cache: dict[tuple[str, str, int], np.ndarray] = {}
    active_cache_scope: tuple[Any, ...] | None = None

    def add_census(
        key: BootstrapTermKey,
        support_sessions: tuple[Hashable, ...],
        weights_for_identity: np.ndarray,
        status: str,
        outcome_name: str,
        empty_axis_key: tuple[Any, ...],
    ) -> None:
        digest = hashlib.sha256()
        positive = np.flatnonzero(weights_for_identity > 0.0)
        digest.update(key.family.encode("ascii"))
        digest.update(key.term_role.encode("utf-8"))
        digest.update(outcome_name.encode("ascii"))
        digest.update(status.encode("ascii"))
        digest.update(positive.tobytes())
        digest.update(np.asarray(weights_for_identity[positive], dtype=np.float64).tobytes())
        if positive.size == 0:
            digest.update(repr(empty_axis_key).encode("utf-8"))
        identity = digest.hexdigest()
        if identity not in census_seen:
            census_seen.add(identity)
            census.append(build_term_support_record(
                key=key, session_ids=support_sessions, status=status
            ))

    sink = _progress.get_sink()
    contrast_progress = sink.phase(_progress.PHASE_CONTRASTS, len(declared))
    indexed_specs = tuple(enumerate(declared))
    partitions = _partition_indexed_specs(indexed_specs, _contrast_worker_count())
    if len(partitions) <= 1:
        results = [_contrast_partition(inputs, indexed_specs, migrations, contrast_progress)]
    else:
        results = _run_contrast_partitions(inputs, partitions, contrast_progress)

    merged = _merge_contrast_partitions(tuple(results))
    contrast_rows = list(merged.rows)
    registry = merged.registry
    requests = list(merged.requests)
    census = list(merged.census)
    census_seen = set(merged.census_identities)

    # Day-type inventory, primary arm only.
    _day_type_specs = tuple(declared_day_type_rows())
    day_progress = sink.phase(_progress.PHASE_DAY_TYPES, len(_day_type_specs))
    for _day_position, spec in enumerate(_day_type_specs, start=1):
        unit_mask, sessions, timestamps, valid, common, _window_fits = _cached_slice(
            slice_cache, inputs, (spec.path_estimand, spec.horizon_minutes)
        )
        completed = valid if spec.support_kind == "horizon_specific" else (valid & common)
        structurally_eligible = _structural_completion_eligibility(
            slice_cache, inputs, arm=primary, path_estimand=spec.path_estimand,
            support_kind=spec.support_kind, horizon_minutes=spec.horizon_minutes,
        )
        day_types = np.full(sessions.size, "regular", dtype="<U21")
        day_types[primary.holiday_adjacent] = "holiday_adjacent"
        day_types[primary.session_class == "scheduled_early_close"] = "scheduled_early_close"
        values = np.asarray(inputs.unit[spec.outcome_name][unit_mask], dtype=np.int32)
        result = evaluate_day_type_distribution(
            values=values, session_ids=sessions,
            calendar_years=sessions.astype(np.int64) // 10_000,
            structurally_eligible=structurally_eligible, completed=completed,
            day_types=day_types, target_day_type=spec.day_type,
            horizon_minutes=spec.horizon_minutes, statistic=spec.statistic,
        )
        key = (
            spec.arm_id, spec.day_type, spec.outcome_name, spec.path_estimand,
            spec.support_kind, spec.horizon_minutes, spec.statistic,
        )
        rid = _row_id("day_type", key)
        add_census(
            BootstrapTermKey("day_type", key, "target"),
            tuple(sessions[result.support.weights > 0.0]), result.support.weights,
            result.status, spec.outcome_name,
            key[:-1],
        )
        if result.status == "ok":
            term_id = registry.register(values, result.support.weights, spec.statistic)
            requests.append(BootstrapIntervalRequest(rid, term_id, None, status_decision(
                degenerate_baseline=False, insufficient_anchors=False,
                insufficient_completion=False, insufficient_overlap=False,
            )))
        day_rows.append({
            "row_id": rid, "arm_id": spec.arm_id, "day_type": spec.day_type,
            "outcome_name": spec.outcome_name, "path_estimand": spec.path_estimand,
            "support_kind": spec.support_kind, "horizon_minutes": spec.horizon_minutes,
            "statistic": spec.statistic, "quantile_ticks": result.quantile_ticks,
            "quantile_valid": result.quantile_valid, "n_anchors": result.n_anchors,
            "n_sessions": result.n_sessions, "weight_ess": result.weight_ess,
            "completion": _json(result.completion), "status": result.status,
            "status_flags": _json(result.status_flags),
        })
        day_progress.advance(_day_position)

    # Interaction inventory. Degenerate cells are emitted without building support.
    _interaction_specs = tuple(declared_interaction_rows())
    interaction_progress = sink.phase(_progress.PHASE_INTERACTIONS, len(_interaction_specs))
    for _interaction_position, spec in enumerate(_interaction_specs, start=1):
        unit_mask, sessions, timestamps, valid, common, _window_fits = _cached_slice(
            slice_cache, inputs, (spec.path_estimand, spec.horizon_minutes)
        )
        completed = valid if spec.support_kind == "horizon_specific" else (valid & common)
        structurally_eligible = _structural_completion_eligibility(
            slice_cache, inputs, arm=primary, path_estimand=spec.path_estimand,
            support_kind=spec.support_kind, horizon_minutes=spec.horizon_minutes,
        )
        values = np.asarray(inputs.unit[spec.outcome_name][unit_mask], dtype=np.int32)
        key = (
            spec.arm_id, spec.outcome_name, spec.path_estimand, spec.support_kind,
            spec.horizon_minutes, spec.population_estimand, spec.statistic,
            *_cell_tuple(spec.target_cell),
        )
        rid = _row_id("interaction", key)
        if spec.structurally_degenerate:
            interaction_rows.append({
                "row_id": rid, "arm_id": spec.arm_id, "outcome_name": spec.outcome_name,
                "path_estimand": spec.path_estimand, "support_kind": spec.support_kind,
                "horizon_minutes": spec.horizon_minutes,
                "population_estimand": spec.population_estimand, "statistic": spec.statistic,
                "phase": spec.target_cell.phase, "vol_rel_tercile": spec.target_cell.volatility_state,
                "reference_phase": "midday", "reference_vol_tercile": "mid",
                "interaction_ticks": None, "interaction_valid": False,
                "common_n_sessions": None, "cell_anchor_counts": "[]",
                "cell_session_counts": "[]", "cell_weight_ess": "[]",
                "completion_diagnostics": "[]", "status": "degenerate_baseline",
                "status_flags": _json(("degenerate_baseline",)),
                "panel_label": DESCRIPTIVE_ONLY_LABEL,
            })
            interaction_progress.advance(_interaction_position)
            continue
        support = build_four_cell_support(
            sessions, primary.phases, primary.states, completed & primary.active,
            spec.target_cell,
        )
        completion_passes = {}
        for term in support.terms:
            completion_passes[term.cell] = not completion_diagnostics(
                horizon_minutes=spec.horizon_minutes, session_ids=sessions,
                calendar_years=sessions.astype(np.int64) // 10_000,
                structurally_eligible=structurally_eligible, completed=completed,
                target_mask=(primary.phases == term.cell.phase) & (primary.states == term.cell.volatility_state),
                target_weights=term.weights,
            ).insufficient_completion
        evaluation = evaluate_interaction(values, support, completion_passes, spec.statistic)
        for term in support.terms:
            add_census(
                BootstrapTermKey("interaction", key, f"{term.cell.phase}:{term.cell.volatility_state}"),
                tuple(sessions[term.weights > 0.0]), term.weights,
                evaluation.status, spec.outcome_name,
                key[:6] + key[7:],
            )
        if evaluation.status == "ok":
            term_ids = tuple(
                registry.register(values, term.weights, spec.statistic)
                for term in support.terms
            )
            from mnq_lab.phase8.uncertainty import BootstrapInteractionRequest
            requests.append(BootstrapInteractionRequest(rid, term_ids, "ok"))
        interaction_rows.append({
            "row_id": rid, "arm_id": spec.arm_id, "outcome_name": spec.outcome_name,
            "path_estimand": spec.path_estimand, "support_kind": spec.support_kind,
            "horizon_minutes": spec.horizon_minutes,
            "population_estimand": spec.population_estimand, "statistic": spec.statistic,
            "phase": spec.target_cell.phase, "vol_rel_tercile": spec.target_cell.volatility_state,
            "reference_phase": "midday", "reference_vol_tercile": "mid",
            "interaction_ticks": evaluation.interaction_ticks,
            "interaction_valid": evaluation.interaction_valid,
            "common_n_sessions": support.n_common_sessions,
            "cell_anchor_counts": _json(tuple((term.cell, term.n_anchors) for term in support.terms)),
            "cell_session_counts": _json(tuple((term.cell, term.n_sessions) for term in support.terms)),
            "cell_weight_ess": _json(tuple((term.cell, term.weight_ess) for term in support.terms)),
            "completion_diagnostics": _json(evaluation.completion_passes),
            "status": evaluation.status, "status_flags": _json(evaluation.status_flags),
            "panel_label": DESCRIPTIVE_ONLY_LABEL,
        })
        interaction_progress.advance(_interaction_position)

    if len(contrast_rows) != 29_430 or len(day_rows) != 216 or len(interaction_rows) != 720:
        raise SpineError("Phase 8 point inventory differs from the complete declared counts")
    group_ids = np.asarray(primary.sessions)
    return ProductionComputation(
        _table_from_rows("contrasts", CONTRAST_COLUMNS, contrast_rows),
        _table_from_rows("day_type_descriptives", DAY_TYPE_COLUMNS, day_rows),
        _table_from_rows("interactions", INTERACTION_COLUMNS, interaction_rows),
        group_ids, registry.recipes, tuple(requests), tuple(census),
    )


def interval_table_from_rows(rows: list[dict[str, Any]]) -> Phase8Table:
    return _table_from_rows("intervals", INTERVAL_COLUMNS, rows)


def production_provenance(inputs: ProductionInputs, environment: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "frozen_spec_sha256": _sha(SPEC_PATH),
        "analysis_constants_sha256": _sha(CONSTANTS_PATH),
        "outcome_preregistration_sha256": _sha(REPO_ROOT / "docs/OUTCOME_LAYER_PREREGISTRATION.md"),
        "phase8_preregistration_sha256": _sha(REPO_ROOT / "docs/PHASE8_PREREGISTRATION.md"),
        "unit_o_input_manifest_sha256": dict(inputs.input_manifest_sha256)["unit_o"],
        "phase7_input_manifest_sha256": dict(inputs.input_manifest_sha256)["phase7"],
        "run_input_manifest_sha256": dict(inputs.input_manifest_sha256)["run"],
        "accepted_calendar_version": CALENDAR_VERSION,
        "accepted_calendar_sha256": CALENDAR_SHA256,
        "corpus_seal": inputs.run_manifest.get("source_store_manifest_sha256"),
        "code_commit": environment.get("commit"),
        "dirty_worktree": environment.get("dirty"),
        "environment_fingerprint": dict(environment),
        "bootstrap_contract": bootstrap_contract().__dict__,
    }


__all__ = [
    "CONTRAST_COLUMNS", "DAY_TYPE_COLUMNS", "INTERACTION_COLUMNS", "INTERVAL_COLUMNS",
    "ProductionComputation", "ProductionInputs", "build_production_computation",
    "interval_table_from_rows", "open_production_inputs", "production_provenance",
]
