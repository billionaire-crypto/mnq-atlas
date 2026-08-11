"""Immutable Phase 9 ``.npy`` column stores with memory-mapped reads."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np

from mnq_lab import SpineError
from mnq_lab.constants import REPO_ROOT
from mnq_lab.phase9.prevalence import (
    EPISODE_LENGTH_COLUMNS,
    EVENT_COLUMNS,
    SUMMARY_COLUMNS,
    PrevalenceTable,
)

PHASE9_ARTIFACT_SCHEMA_VERSION = "phase9-prevalence-v2"
PHASE9_TABLE_ORDER = ("summary", "episode_lengths", "events")
PHASE9_TABLE_SCHEMAS = {
    "summary": SUMMARY_COLUMNS,
    "episode_lengths": EPISODE_LENGTH_COLUMNS,
    "events": EVENT_COLUMNS,
}

__all__ = [
    "PHASE9_ARTIFACT_SCHEMA_VERSION",
    "PHASE9_TABLE_ORDER",
    "PHASE9_TABLE_SCHEMAS",
    "load_phase9_artifacts",
    "write_phase9_artifacts",
]


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_output_root(root: Path) -> Path:
    candidate = root.resolve()
    repository_store = (REPO_ROOT / "data").resolve()
    if candidate == repository_store or repository_store in candidate.parents:
        raise SpineError("Phase 9 implementation serializer may not write under data/")
    if candidate.exists():
        raise SpineError("Phase 9 artifact root must be absent")
    return candidate


def write_phase9_artifacts(
    root: Path,
    tables: Iterable[PrevalenceTable],
    *,
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    """Write exactly the three declared tables; this is not a corpus runner."""

    destination = _assert_output_root(Path(root))
    table_values = tuple(tables)
    if tuple(table.name for table in table_values) != PHASE9_TABLE_ORDER:
        raise SpineError("Phase 9 tables differ from the declared order")
    if any(not isinstance(table, PrevalenceTable) for table in table_values):
        raise SpineError("Phase 9 writer received an invalid table")

    destination.mkdir(parents=True, exist_ok=False)
    table_manifest: dict[str, Any] = {}
    for table in table_values:
        table_root = destination / table.name
        table_root.mkdir()
        column_manifest: dict[str, Any] = {}
        for position, (name, raw) in enumerate(table.columns):
            values = np.ascontiguousarray(np.asarray(raw))
            filename = f"{position:02d}_{name}.npy"
            path = table_root / filename
            np.save(path, values, allow_pickle=False)
            column_manifest[name] = {
                "file": filename,
                "dtype": str(values.dtype),
                "rows": int(values.size),
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        table_manifest[table.name] = {
            "column_order": list(PHASE9_TABLE_SCHEMAS[table.name]),
            "row_count": table.row_count,
            "columns": column_manifest,
        }
    manifest = {
        "schema_version": PHASE9_ARTIFACT_SCHEMA_VERSION,
        "table_order": list(PHASE9_TABLE_ORDER),
        "tables": table_manifest,
        "provenance": dict(provenance),
    }
    (destination / "manifest.json").write_bytes(_canonical_json_bytes(manifest))
    return manifest


def load_phase9_artifacts(root: Path) -> tuple[PrevalenceTable, ...]:
    """Validate and open every array with ``mmap_mode='r'``."""

    source = Path(root)
    manifest_path = source / "manifest.json"
    if not manifest_path.is_file():
        raise SpineError("Phase 9 artifact manifest is missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SpineError(f"Phase 9 artifact manifest is unreadable: {exc}") from exc
    if manifest_path.read_bytes() != _canonical_json_bytes(manifest):
        raise SpineError("Phase 9 artifact manifest is not canonical")
    if manifest.get("schema_version") != PHASE9_ARTIFACT_SCHEMA_VERSION:
        raise SpineError("Phase 9 artifact schema version differs")
    if tuple(manifest.get("table_order", ())) != PHASE9_TABLE_ORDER:
        raise SpineError("Phase 9 artifact table order differs")
    if set(manifest.get("tables", {})) != set(PHASE9_TABLE_ORDER):
        raise SpineError("Phase 9 artifact table inventory differs")

    expected_root_entries = {"manifest.json", *PHASE9_TABLE_ORDER}
    if {path.name for path in source.iterdir()} != expected_root_entries:
        raise SpineError("Phase 9 artifact root contains an unexpected entry")

    output: list[PrevalenceTable] = []
    for table_name in PHASE9_TABLE_ORDER:
        record = manifest["tables"][table_name]
        schema = PHASE9_TABLE_SCHEMAS[table_name]
        if tuple(record.get("column_order", ())) != schema:
            raise SpineError(f"Phase 9 {table_name} column order differs")
        if set(record.get("columns", {})) != set(schema):
            raise SpineError(f"Phase 9 {table_name} column inventory differs")
        table_root = source / table_name
        expected_files: set[str] = set()
        columns: list[tuple[str, np.ndarray]] = []
        for name in schema:
            column_record = record["columns"][name]
            filename = column_record.get("file")
            if not isinstance(filename, str) or Path(filename).name != filename:
                raise SpineError(f"Phase 9 {table_name} column path is invalid")
            expected_files.add(filename)
            path = table_root / filename
            if (
                not path.is_file()
                or path.stat().st_size != column_record.get("bytes")
                or _sha256_file(path) != column_record.get("sha256")
            ):
                raise SpineError(f"Phase 9 {table_name} column hash differs")
            values = np.load(path, mmap_mode="r", allow_pickle=False)
            if (
                values.ndim != 1
                or str(values.dtype) != column_record.get("dtype")
                or int(values.size) != column_record.get("rows")
                or int(values.size) != record.get("row_count")
            ):
                raise SpineError(f"Phase 9 {table_name} column schema differs")
            values.setflags(write=False)
            columns.append((name, values))
        if not table_root.is_dir() or {
            path.name for path in table_root.iterdir()
        } != expected_files:
            raise SpineError(f"Phase 9 {table_name} contains an unexpected entry")
        output.append(PrevalenceTable(table_name, tuple(columns)))
    return tuple(output)
