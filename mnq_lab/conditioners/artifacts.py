"""Deterministic Phase 7 column-store artifacts.

This module serializes already-computed Phase 7 tables.  It never opens a
market store and it never computes a conditioner value.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

import numpy as np

from mnq_lab import SpineError
from mnq_lab.conditioners.admission import build_phase7_registry
from mnq_lab.conditioners.arms import ARM_CONFIGS
from mnq_lab.conditioners.calendar import CALENDAR_SHA256, CALENDAR_VERSION, SCHEMA_VERSION
from mnq_lab.conditioners.pipeline import Phase7ConditionerPipeline, SCALE_SOURCE_ARMS
from mnq_lab.conditioners.state_validity import METRIC_ORDER, StateValidityPanel
from mnq_lab.constants import CONSTANTS_PATH, REPO_ROOT, SPEC_PATH
from mnq_lab.spine.store import environment_fingerprint

__all__ = [
    "ANCHOR_SCALE_SCHEMA",
    "ASSIGNMENT_SCHEMA",
    "PHASE7_ARTIFACT_SCHEMA_VERSION",
    "SEASONAL_SCHEMA",
    "STATE_VALIDITY_SCHEMA",
    "THRESHOLD_SCHEMA",
    "ArtifactTable",
    "Phase7ArtifactBundle",
    "build_phase7_artifact_bundle",
    "write_phase7_artifacts",
]


PHASE7_ARTIFACT_SCHEMA_VERSION = "phase7-conditioner-artifacts-v1"
PREREGISTRATION_PATH = REPO_ROOT / "docs" / "PHASE7_PREREGISTRATION.md"
PREREGISTRATION_SHA256 = "eeb97cb7e6ccd17a0ccd676de3cf7424f511fc773bacd62ff9e9f88aa404a930"

ANCHOR_SCALE_SCHEMA = (
    ("arm_id", "U64"),
    ("session_id", "int32"),
    ("ts_event_ns", "int64"),
    ("tau_ns", "int64"),
    ("observation_bucket_ct", "U5"),
    ("session_phase", "U16"),
    ("symbol_code", "int32"),
    ("observed_1m_components", "int8"),
    ("component_coverage_rate", "float64"),
    ("anchor_status", "U24"),
    ("return_status", "U24"),
    ("return_missing_reason", "U32"),
    ("reset_reason", "U16"),
    ("scheduled_break", "bool"),
    ("contiguous_return_count", "int32"),
    ("scale_value", "float64"),
    ("ewma_status", "U16"),
    ("mad_status", "U16"),
)
SEASONAL_SCHEMA = (
    ("arm_id", "U64"),
    ("session_id", "int32"),
    ("observation_bucket_ct", "U5"),
    ("session_phase", "U16"),
    ("qualifying_prior_sessions", "int32"),
    ("bucket_n", "int32"),
    ("bucket_median", "float64"),
    ("bucket_median_valid", "bool"),
    ("phase_session_median", "float64"),
    ("phase_session_median_valid", "bool"),
    ("shrink_weight", "float64"),
    ("seasonal_profile", "float64"),
    ("seasonal_valid", "bool"),
    ("seasonal_status", "U40"),
    ("calendar_version", "U64"),
    ("calendar_sha256", "U64"),
)
THRESHOLD_SCHEMA = (
    ("arm_id", "U64"),
    ("session_id", "int32"),
    ("session_phase", "U16"),
    ("history_kind", "U16"),
    ("qualifying_prior_sessions", "int32"),
    ("lower_probability", "float64"),
    ("upper_probability", "float64"),
    ("lower_threshold", "float64"),
    ("upper_threshold", "float64"),
    ("threshold_valid", "bool"),
    ("threshold_status", "U40"),
)
ASSIGNMENT_SCHEMA = (
    ("arm_id", "U64"),
    ("session_id", "int32"),
    ("ts_event_ns", "int64"),
    ("tau_ns", "int64"),
    ("observation_bucket_ct", "U5"),
    ("session_phase", "U16"),
    ("scale_value", "float64"),
    ("scale_valid", "bool"),
    ("seasonal_profile", "float64"),
    ("seasonal_valid", "bool"),
    ("vol_rel", "float64"),
    ("vol_rel_valid", "bool"),
    ("vol_rel_status", "U32"),
    ("upstream_stage", "U32"),
    ("lower_threshold", "float64"),
    ("upper_threshold", "float64"),
    ("threshold_status", "U40"),
    ("category_code", "int8"),
    ("category_name", "U16"),
    ("assignment_status", "U32"),
    ("calendar_session_class", "U32"),
    ("holiday_adjacent", "bool"),
    ("data_quality_status", "U48"),
)
STATE_VALIDITY_SCHEMA = (
    ("metric", "U48"),
    ("arm_id", "U64"),
    ("session_phase", "U16"),
    ("detail", "U64"),
    ("comparison_arm_id", "U64"),
    ("category_code", "int8"),
    ("category_to_code", "int8"),
    ("session_id", "int32"),
    ("year", "int16"),
    ("horizon", "U32"),
    ("count", "int64"),
    ("denominator", "int64"),
    ("value", "float64"),
    ("value_valid", "bool"),
    ("status", "U64"),
)

_SCHEMAS = MappingProxyType(
    {
        "anchor_scales": ANCHOR_SCALE_SCHEMA,
        "seasonal_profiles": SEASONAL_SCHEMA,
        "thresholds": THRESHOLD_SCHEMA,
        "assignments": ASSIGNMENT_SCHEMA,
        "state_validity": STATE_VALIDITY_SCHEMA,
    }
)
_FORBIDDEN_ARTIFACT_KEYS = frozenset(
    {"contrast", "prevalence", "null", "vintage", "guard", "s01a", "report"}
)


def _canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
        "utf-8"
    )


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_array(values: Iterable[Any], dtype: str) -> np.ndarray:
    normalized = [value.value if isinstance(value, Enum) else value for value in values]
    normalized = ["" if value is None and dtype.startswith("U") else value for value in normalized]
    array = np.asarray(normalized, dtype=np.dtype(dtype))
    if array.ndim != 1:
        raise SpineError("Phase 7 artifact columns must be one-dimensional")
    if np.issubdtype(array.dtype, np.floating):
        if not np.isfinite(array).all():
            raise SpineError("Phase 7 artifacts may not store non-finite floats")
        array[array == 0.0] = 0.0
    array.setflags(write=False)
    return array


@dataclass(frozen=True)
class ArtifactTable:
    name: str
    columns: Mapping[str, np.ndarray]

    def __post_init__(self) -> None:
        if self.name not in _SCHEMAS:
            raise SpineError(f"unknown Phase 7 artifact table {self.name!r}")
        schema = _SCHEMAS[self.name]
        if tuple(self.columns) != tuple(name for name, _ in schema):
            raise SpineError(f"{self.name} columns differ from the frozen schema")
        lengths = {len(value) for value in self.columns.values()}
        if len(lengths) != 1 or not lengths or next(iter(lengths)) == 0:
            raise SpineError(f"{self.name} must contain aligned nonempty columns")
        for name, dtype in schema:
            value = self.columns[name]
            if not isinstance(value, np.ndarray) or value.ndim != 1:
                raise SpineError(f"{self.name}.{name} is not a one-dimensional array")
            if str(value.dtype) != str(np.dtype(dtype)):
                raise SpineError(f"{self.name}.{name} has dtype {value.dtype}, expected {dtype}")
            if value.flags.writeable:
                raise SpineError(f"{self.name}.{name} must be read-only")

    @property
    def row_count(self) -> int:
        return len(next(iter(self.columns.values())))


@dataclass(frozen=True)
class Phase7ArtifactBundle:
    tables: Mapping[str, ArtifactTable]

    def __post_init__(self) -> None:
        if any(name.lower() in _FORBIDDEN_ARTIFACT_KEYS for name in self.tables):
            raise SpineError("Phase 8-12 artifact key entered the Phase 7 bundle")
        if tuple(self.tables) != tuple(_SCHEMAS):
            raise SpineError("Phase 7 artifact bundle differs from the frozen table order")


def _table_from_records(name: str, records: Iterable[Any]) -> ArtifactTable:
    rows = tuple(records)
    schema = _SCHEMAS[name]
    columns = {
        field: _canonical_array((getattr(row, field) for row in rows), dtype)
        for field, dtype in schema
    }
    return ArtifactTable(name, MappingProxyType(columns))


def _anchor_table(columns: Mapping[str, Any]) -> ArtifactTable:
    schema = _SCHEMAS["anchor_scales"]
    if tuple(columns) != tuple(name for name, _ in schema):
        raise SpineError("anchor scale columns differ from the frozen schema")
    canonical = {
        name: _canonical_array(columns[name], dtype) for name, dtype in schema
    }
    return ArtifactTable("anchor_scales", MappingProxyType(canonical))


def build_phase7_artifact_bundle(
    anchor_scale_columns: Mapping[str, Any],
    pipeline: Phase7ConditionerPipeline,
    state_validity: StateValidityPanel,
) -> Phase7ArtifactBundle:
    if not isinstance(pipeline, Phase7ConditionerPipeline):
        raise SpineError("artifacts require a validated Phase 7 pipeline")
    if not isinstance(state_validity, StateValidityPanel):
        raise SpineError("artifacts require a validated state-validity panel")
    seasonal_rows = tuple(
        row for arm_id in SCALE_SOURCE_ARMS for row in pipeline.seasonal_profiles[arm_id].rows
    )
    threshold_rows = tuple(
        row for config in ARM_CONFIGS for row in pipeline.threshold_tables[config.arm_id].rows
    )
    assignment_rows = tuple(
        row for config in ARM_CONFIGS for row in pipeline.assignment_tables[config.arm_id].rows
    )
    tables = {
        "anchor_scales": _anchor_table(anchor_scale_columns),
        "seasonal_profiles": _table_from_records("seasonal_profiles", seasonal_rows),
        "thresholds": _table_from_records("thresholds", threshold_rows),
        "assignments": _table_from_records("assignments", assignment_rows),
        "state_validity": _table_from_records("state_validity", state_validity.rows),
    }
    return Phase7ArtifactBundle(MappingProxyType(tables))


def _comparison_policies() -> list[dict[str, Any]]:
    output = []
    for descriptor in build_phase7_registry().entries():
        output.append(
            {
                "identifier": descriptor.identifier,
                "policies": [
                    {
                        "case_name": policy.case_name,
                        "kind": policy.kind.value,
                        "atol": policy.atol,
                        "rtol": policy.rtol,
                    }
                    for policy in descriptor.comparison_policies
                ],
            }
        )
    return output


def _validate_calendar_identity(calendar_version: str | None, calendar_sha256: str | None) -> None:
    if calendar_version != CALENDAR_VERSION or calendar_sha256 != CALENDAR_SHA256:
        raise SpineError("seasonal-dependent Phase 7 artifacts require the accepted calendar")


def write_phase7_artifacts(
    root: Path,
    bundle: Phase7ArtifactBundle,
    *,
    source_build_id: str,
    calendar_version: str | None = CALENDAR_VERSION,
    calendar_sha256: str | None = CALENDAR_SHA256,
    environment: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write a complete deterministic Phase 7 artifact bundle."""
    if not isinstance(bundle, Phase7ArtifactBundle):
        raise SpineError("write_phase7_artifacts requires a validated bundle")
    if not isinstance(source_build_id, str) or not source_build_id:
        raise SpineError("source_build_id must be a nonempty string")
    _validate_calendar_identity(calendar_version, calendar_sha256)
    if _sha256_file(PREREGISTRATION_PATH) != PREREGISTRATION_SHA256:
        raise SpineError("Phase 7 preregistration bytes differ from the ratified pin")
    root = Path(root)
    if root.exists() and any(root.iterdir()):
        raise SpineError("Phase 7 artifact output directory must be absent or empty")
    root.mkdir(parents=True, exist_ok=True)

    table_manifest: dict[str, Any] = {}
    for table_name, table in bundle.tables.items():
        table_root = root / table_name
        table_root.mkdir()
        column_manifest: dict[str, Any] = {}
        for position, (column_name, array) in enumerate(table.columns.items()):
            filename = f"{position:02d}_{column_name}.npy"
            path = table_root / filename
            np.save(path, np.ascontiguousarray(array), allow_pickle=False)
            column_manifest[column_name] = {
                "file": f"{table_name}/{filename}",
                "dtype": str(array.dtype),
                "rows": table.row_count,
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        table_manifest[table_name] = {
            "column_order": list(table.columns),
            "row_count": table.row_count,
            "columns": column_manifest,
        }

    env = dict(environment) if environment is not None else environment_fingerprint(REPO_ROOT)
    manifest = {
        "artifact_schema_version": PHASE7_ARTIFACT_SCHEMA_VERSION,
        "source_build_id": source_build_id,
        "frozen_inputs": {
            "REV6_FROZEN_SPEC.md": _sha256_file(SPEC_PATH),
            "analysis_constants_v1.yaml": _sha256_file(CONSTANTS_PATH),
            "docs/PHASE7_PREREGISTRATION.md": PREREGISTRATION_SHA256,
            "accepted_calendar": calendar_sha256,
        },
        "calendar_version": calendar_version,
        "calendar_schema_version": SCHEMA_VERSION,
        "calendar_sha256": calendar_sha256,
        "code_commit": env.get("commit"),
        "dirty_worktree": env.get("dirty"),
        "environment_fingerprint": env,
        "arm_order": [config.arm_id for config in ARM_CONFIGS],
        "table_order": list(bundle.tables),
        "tables": table_manifest,
        "registry_comparison_policies": _comparison_policies(),
        "semantic_determinism": "exact discrete; float64 atol=0 rtol=1e-12",
        "byte_identity_scope": "matching complete environment fingerprint only",
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_bytes(_canonical_json_bytes(manifest))
    return manifest
