"""Immutable Phase 8 table stores and deterministic resumable checkpoints."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np

from mnq_lab import SpineError

PHASE8_ARTIFACT_SCHEMA_VERSION = "phase8-results-v1"
PHASE8_ARM_SCHEMA_VERSION = "phase8-frozen-arms-v1"
PHASE8_TABLE_ORDER = (
    "contrasts",
    "intervals",
    "day_type_descriptives",
    "interactions",
)


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class Phase8Table:
    name: str
    columns: tuple[tuple[str, np.ndarray], ...]

    def __post_init__(self) -> None:
        if self.name not in PHASE8_TABLE_ORDER:
            raise SpineError(f"undeclared Phase 8 output table: {self.name!r}")
        if not isinstance(self.columns, tuple) or not self.columns:
            raise SpineError("Phase 8 table columns must be a nonempty tuple")
        names = tuple(name for name, _ in self.columns)
        if len(set(names)) != len(names):
            raise SpineError("Phase 8 table contains a duplicate column")
        sizes: set[int] = set()
        for name, values in self.columns:
            if not isinstance(name, str) or not name:
                raise SpineError("Phase 8 column names must be nonempty strings")
            array = np.asarray(values)
            if array.ndim != 1 or array.dtype.kind == "O":
                raise SpineError("Phase 8 columns must be one-dimensional non-object arrays")
            sizes.add(array.size)
        if len(sizes) != 1:
            raise SpineError("Phase 8 table columns must have equal row counts")
        for index, name in enumerate(names):
            if name == "n_anchors" and names[index : index + 3] != (
                "n_anchors", "n_sessions", "weight_ess"
            ):
                raise SpineError(
                    "n_anchors must be immediately accompanied by n_sessions and weight_ess"
                )
            if name == "baseline_n_anchors" and names[index : index + 3] != (
                "baseline_n_anchors", "baseline_n_sessions", "baseline_weight_ess"
            ):
                raise SpineError(
                    "baseline_n_anchors must be immediately accompanied by "
                    "baseline_n_sessions and baseline_weight_ess"
                )

    @property
    def row_count(self) -> int:
        return int(np.asarray(self.columns[0][1]).size)


@dataclass(frozen=True)
class CheckpointIdentity:
    code_commit: str
    input_manifest_sha256: tuple[tuple[str, str], ...]
    workers: int
    process_start_method: str
    bootstrap_contract_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.code_commit, str) or len(self.code_commit) != 40:
            raise SpineError("checkpoint code commit must be a full SHA-1")
        if not isinstance(self.input_manifest_sha256, tuple) or not self.input_manifest_sha256:
            raise SpineError("checkpoint input manifest hashes must be a nonempty tuple")
        if isinstance(self.workers, bool) or not isinstance(self.workers, int) or self.workers <= 0:
            raise SpineError("checkpoint worker count must be a positive integer")
        if self.process_start_method not in {"spawn", "fork"}:
            raise SpineError("checkpoint process start method is invalid")
        if len(self.bootstrap_contract_sha256) != 64:
            raise SpineError("checkpoint bootstrap contract hash must be SHA-256")


class CheckpointStore:
    """Append-only operational chunks bound to one complete run identity."""

    def __init__(self, root: Path, identity: CheckpointIdentity):
        self.root = Path(root)
        self.identity = identity
        identity_path = self.root / "identity.json"
        payload = canonical_json_bytes(asdict(identity))
        if identity_path.exists():
            if identity_path.read_bytes() != payload:
                raise SpineError("checkpoint identity differs from the requested resume")
        else:
            self.root.mkdir(parents=True, exist_ok=True)
            identity_path.write_bytes(payload)

    def has_chunk(self, index: int) -> bool:
        return (self.root / f"chunk-{index:06d}" / "manifest.json").is_file()

    def write_chunk(self, index: int, columns: Mapping[str, np.ndarray]) -> None:
        final = self.root / f"chunk-{index:06d}"
        if final.exists():
            raise SpineError(f"checkpoint chunk {index} already exists")
        staging = self.root / f".chunk-{index:06d}.staging"
        if staging.exists():
            raise SpineError(f"an incomplete checkpoint chunk {index} staging directory exists")
        staging.mkdir()
        manifest_columns: dict[str, Any] = {}
        row_count: int | None = None
        for position, (name, raw) in enumerate(columns.items()):
            array = np.ascontiguousarray(np.asarray(raw))
            if array.ndim != 1 or array.dtype.kind == "O":
                raise SpineError("checkpoint columns must be one-dimensional non-object arrays")
            row_count = array.size if row_count is None else row_count
            if array.size != row_count:
                raise SpineError("checkpoint columns have unequal row counts")
            filename = f"{position:02d}_{name}.npy"
            path = staging / filename
            np.save(path, array, allow_pickle=False)
            manifest_columns[name] = {
                "file": filename,
                "dtype": str(array.dtype),
                "rows": int(array.size),
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        manifest = {
            "chunk_index": index,
            "column_order": list(columns),
            "row_count": 0 if row_count is None else row_count,
            "columns": manifest_columns,
        }
        (staging / "manifest.json").write_bytes(canonical_json_bytes(manifest))
        staging.replace(final)

    def read_chunk(self, index: int) -> dict[str, np.ndarray]:
        root = self.root / f"chunk-{index:06d}"
        manifest_path = root / "manifest.json"
        if not manifest_path.is_file():
            raise SpineError(f"checkpoint chunk {index} is incomplete")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.read_bytes() != canonical_json_bytes(manifest):
            raise SpineError(f"checkpoint chunk {index} manifest is not canonical")
        result: dict[str, np.ndarray] = {}
        for name in manifest["column_order"]:
            record = manifest["columns"][name]
            path = root / record["file"]
            if _sha256_file(path) != record["sha256"]:
                raise SpineError(f"checkpoint chunk {index} column hash differs")
            result[name] = np.load(path, allow_pickle=False)
        return result

    def has_plan_matrices(self) -> bool:
        return (self.root / "plans" / "manifest.json").is_file()

    def write_plan_matrices(self, bundle: Any) -> None:
        from mnq_lab.phase8.uncertainty import _JointPlanMatrices

        if not isinstance(bundle, _JointPlanMatrices):
            raise SpineError("checkpoint plans have the wrong type")
        final = self.root / "plans"
        if final.exists():
            raise SpineError("checkpoint plan matrices already exist")
        staging = self.root / ".plans.staging"
        if staging.exists():
            raise SpineError("an incomplete checkpoint plan staging directory exists")
        staging.mkdir()
        records = []
        for index, matrix in enumerate(bundle.matrices):
            path = staging / f"{index:02d}_session_multiplicities.npy"
            np.save(path, np.ascontiguousarray(matrix), allow_pickle=False)
            records.append({
                "file": path.name,
                "dtype": str(matrix.dtype),
                "shape": list(matrix.shape),
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            })
        manifest = {
            "group_digest": bundle.group_digest,
            "bootstrap_contract": asdict(bundle.contract),
            "matrices": records,
        }
        (staging / "manifest.json").write_bytes(canonical_json_bytes(manifest))
        staging.replace(final)

    def read_plan_matrices(self, contract: Any) -> Any:
        from mnq_lab.phase8.uncertainty import BootstrapContract, _JointPlanMatrices

        if not isinstance(contract, BootstrapContract):
            raise SpineError("checkpoint plan read requires BootstrapContract")
        root = self.root / "plans"
        manifest_path = root / "manifest.json"
        if not manifest_path.is_file():
            raise SpineError("checkpoint plan matrices are incomplete")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.read_bytes() != canonical_json_bytes(manifest):
            raise SpineError("checkpoint plan manifest is not canonical")
        if canonical_json_bytes(manifest["bootstrap_contract"]) != canonical_json_bytes(asdict(contract)):
            raise SpineError("checkpoint plan contract differs from the current contract")
        matrices = []
        for record in manifest["matrices"]:
            path = root / record["file"]
            if path.stat().st_size != record["bytes"] or _sha256_file(path) != record["sha256"]:
                raise SpineError("checkpoint plan matrix hash differs")
            matrix = np.load(path, mmap_mode="r", allow_pickle=False)
            if str(matrix.dtype) != record["dtype"] or list(matrix.shape) != record["shape"]:
                raise SpineError("checkpoint plan matrix schema differs")
            matrix.setflags(write=False)
            matrices.append(matrix)
        return _JointPlanMatrices(
            str(manifest["group_digest"]), contract, tuple(matrices)
        )


def write_phase8_artifacts(
    root: Path,
    tables: Iterable[Phase8Table],
    *,
    provenance: Mapping[str, Any],
    operating: Mapping[str, Any],
    limitations: tuple[str, ...],
) -> dict[str, Any]:
    root = Path(root)
    if root.exists() and any(root.iterdir()):
        raise SpineError("Phase 8 artifact output directory must be absent or empty")
    if root.exists():
        root.rmdir()
    staging = root.with_name(root.name + ".staging")
    if staging.exists():
        raise SpineError("an incomplete Phase 8 artifact staging directory exists")
    staging.mkdir(parents=True, exist_ok=False)
    table_tuple = tuple(tables)
    if tuple(table.name for table in table_tuple) != PHASE8_TABLE_ORDER:
        raise SpineError("Phase 8 tables differ from the immutable table order")
    table_manifests: dict[str, Any] = {}
    for table in table_tuple:
        table_root = staging / table.name
        table_root.mkdir()
        records: dict[str, Any] = {}
        for position, (name, raw) in enumerate(table.columns):
            array = np.ascontiguousarray(np.asarray(raw))
            filename = f"{position:02d}_{name}.npy"
            path = table_root / filename
            np.save(path, array, allow_pickle=False)
            records[name] = {
                "file": filename,
                "dtype": str(array.dtype),
                "rows": table.row_count,
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        statuses = dict(table.columns).get("status")
        status_counts = {}
        if statuses is not None:
            for value in statuses:
                label = str(value)
                status_counts[label] = status_counts.get(label, 0) + 1
        table_manifests[table.name] = {
            "column_order": [name for name, _ in table.columns],
            "row_count": table.row_count,
            "status_counts": status_counts,
            "columns": records,
        }
    manifest = {
        "artifact_schema_version": PHASE8_ARTIFACT_SCHEMA_VERSION,
        "arm_schema_version": PHASE8_ARM_SCHEMA_VERSION,
        "table_order": list(PHASE8_TABLE_ORDER),
        "tables": table_manifests,
        "provenance": dict(provenance),
        "operating": dict(operating),
        "limitations": list(limitations),
        "byte_identity_scope": "matching complete environment fingerprint only",
        "cross_environment_reproduction": "semantic within declared policies",
    }
    (staging / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    staging.replace(root)
    return manifest


__all__ = [
    "CheckpointIdentity", "CheckpointStore", "PHASE8_TABLE_ORDER", "Phase8Table",
    "canonical_json_bytes", "write_phase8_artifacts",
]
