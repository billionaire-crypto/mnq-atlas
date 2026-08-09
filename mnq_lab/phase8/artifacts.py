"""Immutable Phase 8 table stores and deterministic resumable checkpoints."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, is_dataclass
import hashlib
import importlib
import json
import os
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
CONTRAST_COLUMNS = (
    "row_id", "arm_id", "outcome_name", "path_estimand", "support_kind",
    "horizon_minutes", "statistic", "contrast_name", "population_estimand",
    "contrast_weighting", "target_phase", "target_vol_tercile",
    "target_quantile_ticks", "target_quantile_valid", "baseline_quantile_ticks",
    "baseline_quantile_valid", "contrast_ticks", "contrast_valid",
    "n_anchors", "n_sessions", "weight_ess", "baseline_n_anchors",
    "baseline_n_sessions", "baseline_weight_ess", "completion_target",
    "completion_baseline", "completion_imbalance", "unsupported_target_mass",
    "quarter_unsupported_target_mass", "max_single_anchor_weight_share",
    "weight_cv", "status", "status_flags", "migration_diagnostics",
)
INTERVAL_COLUMNS = (
    "row_id", "point_row_id", "mean_block_sessions", "draws", "confidence_level",
    "ci_lower_ticks", "ci_upper_ticks", "interval_valid", "rng_root_entropy",
    "rng_child_spawn_key", "historical_mixture_disclosure",
    "conditioner_uncertainty_disclosure", "weight_ess_disclosure",
)
DAY_TYPE_COLUMNS = (
    "row_id", "arm_id", "day_type", "outcome_name", "path_estimand",
    "support_kind", "horizon_minutes", "statistic", "quantile_ticks",
    "quantile_valid", "n_anchors", "n_sessions", "weight_ess",
    "completion", "status", "status_flags",
)
INTERACTION_COLUMNS = (
    "row_id", "arm_id", "outcome_name", "path_estimand", "support_kind",
    "horizon_minutes", "population_estimand", "statistic", "phase",
    "vol_rel_tercile", "reference_phase", "reference_vol_tercile",
    "interaction_ticks", "interaction_valid", "common_n_sessions",
    "cell_anchor_counts", "cell_session_counts", "cell_weight_ess",
    "completion_diagnostics", "status", "status_flags", "panel_label",
)
PHASE8_TABLE_SCHEMAS = {
    "contrasts": CONTRAST_COLUMNS,
    "intervals": INTERVAL_COLUMNS,
    "day_type_descriptives": DAY_TYPE_COLUMNS,
    "interactions": INTERACTION_COLUMNS,
}
_INTEGER_COLUMNS = {
    "horizon_minutes", "target_quantile_ticks", "baseline_quantile_ticks",
    "contrast_ticks", "n_anchors", "n_sessions", "baseline_n_anchors",
    "baseline_n_sessions", "quantile_ticks", "interaction_ticks",
    "common_n_sessions", "mean_block_sessions", "draws", "ci_lower_ticks",
    "ci_upper_ticks",
}
_FLOAT_COLUMNS = {
    "weight_ess", "baseline_weight_ess", "completion_target",
    "completion_baseline", "completion_imbalance", "unsupported_target_mass",
    "quarter_unsupported_target_mass", "max_single_anchor_weight_share",
    "weight_cv", "confidence_level",
}
_BOOLEAN_COLUMNS = {
    name for schema in PHASE8_TABLE_SCHEMAS.values()
    for name in schema if name.endswith("_valid")
}


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
        if names != PHASE8_TABLE_SCHEMAS[self.name]:
            raise SpineError(
                f"Phase 8 {self.name} columns differ from the immutable schema"
            )
        sizes: set[int] = set()
        for name, values in self.columns:
            if not isinstance(name, str) or not name:
                raise SpineError("Phase 8 column names must be nonempty strings")
            array = np.asarray(values)
            if array.ndim != 1 or array.dtype.kind == "O":
                raise SpineError("Phase 8 columns must be one-dimensional non-object arrays")
            if name in _INTEGER_COLUMNS and array.dtype.kind not in {"i", "u"}:
                raise SpineError(f"Phase 8 integer column {name!r} has the wrong dtype")
            if name in _FLOAT_COLUMNS and array.dtype.kind != "f":
                raise SpineError(f"Phase 8 float column {name!r} has the wrong dtype")
            if name in _BOOLEAN_COLUMNS and array.dtype.kind != "b":
                raise SpineError(f"Phase 8 validity column {name!r} has the wrong dtype")
            if (
                name not in _INTEGER_COLUMNS | _FLOAT_COLUMNS | _BOOLEAN_COLUMNS
                and array.dtype.kind != "U"
            ):
                raise SpineError(f"Phase 8 label column {name!r} has the wrong dtype")
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
    stage1_workers: int
    bootstrap_workers: int
    process_start_method: str
    bootstrap_contract_sha256: str
    phase8_output_version: str
    producing_code_sha256: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.code_commit, str) or len(self.code_commit) != 40:
            raise SpineError("checkpoint code commit must be a full SHA-1")
        if not isinstance(self.input_manifest_sha256, tuple) or not self.input_manifest_sha256:
            raise SpineError("checkpoint input manifest hashes must be a nonempty tuple")
        for name, value in (
            ("stage1", self.stage1_workers),
            ("bootstrap", self.bootstrap_workers),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise SpineError(f"checkpoint {name} worker count must be a positive integer")
        if self.process_start_method not in {"spawn", "fork"}:
            raise SpineError("checkpoint process start method is invalid")
        if len(self.bootstrap_contract_sha256) != 64:
            raise SpineError("checkpoint bootstrap contract hash must be SHA-256")
        if not isinstance(self.phase8_output_version, str) or not self.phase8_output_version:
            raise SpineError("checkpoint Phase 8 output version is absent")
        if not isinstance(self.producing_code_sha256, tuple) or not self.producing_code_sha256:
            raise SpineError("checkpoint producing-code hashes are absent")
        for name, digest in (*self.input_manifest_sha256, *self.producing_code_sha256):
            if not isinstance(name, str) or not name or not isinstance(digest, str) or len(digest) != 64:
                raise SpineError("checkpoint identity contains an invalid SHA-256 record")


def _checkpoint_tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.is_dir():
        raise SpineError(f"checkpoint unit is not a directory: {root.name}")
    paths = sorted((path for path in root.rglob("*") if path.is_file()), key=lambda p: p.as_posix())
    if not paths:
        raise SpineError(f"checkpoint unit is empty: {root.name}")
    for path in paths:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(path.stat().st_size.to_bytes(8, "big"))
        digest.update(bytes.fromhex(_sha256_file(path)))
    return digest.hexdigest()


def _durably_flush_directory(root: Path) -> None:
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
        with path.open("r+b") as handle:
            os.fsync(handle.fileno())
    if os.name != "nt" and hasattr(os, "O_DIRECTORY"):
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _durably_flush_parent(path: Path) -> None:
    if os.name != "nt" and hasattr(os, "O_DIRECTORY"):
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _encode_checkpoint_value(
    value: Any,
    root: Path,
    arrays: list[dict[str, Any]],
) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, np.generic):
        return _encode_checkpoint_value(value.item(), root, arrays)
    if isinstance(value, np.ndarray):
        if value.dtype.kind == "O":
            raise SpineError("Stage 1 checkpoint arrays may not use object dtype")
        array = np.ascontiguousarray(value)
        filename = f"array-{len(arrays):06d}.npy"
        path = root / filename
        np.save(path, array, allow_pickle=False)
        record = {
            "file": filename,
            "dtype": str(array.dtype),
            "shape": list(array.shape),
            "bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        arrays.append(record)
        return {"__phase8_type__": "array", "index": len(arrays) - 1}
    if isinstance(value, tuple):
        return {
            "__phase8_type__": "tuple",
            "items": [_encode_checkpoint_value(item, root, arrays) for item in value],
        }
    if isinstance(value, list):
        return {
            "__phase8_type__": "list",
            "items": [_encode_checkpoint_value(item, root, arrays) for item in value],
        }
    if isinstance(value, frozenset):
        return {
            "__phase8_type__": "frozenset",
            "items": [
                _encode_checkpoint_value(item, root, arrays)
                for item in sorted(value, key=repr)
            ],
        }
    if isinstance(value, Mapping):
        return {
            "__phase8_type__": "mapping",
            "items": [
                [
                    _encode_checkpoint_value(key, root, arrays),
                    _encode_checkpoint_value(item, root, arrays),
                ]
                for key, item in value.items()
            ],
        }
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "__phase8_type__": "dataclass",
            "module": type(value).__module__,
            "qualname": type(value).__qualname__,
            "fields": [
                [field.name, _encode_checkpoint_value(getattr(value, field.name), root, arrays)]
                for field in fields(value)
            ],
        }
    raise SpineError(f"unsupported Stage 1 checkpoint value type: {type(value).__name__}")


def _decode_checkpoint_value(value: Any, root: Path, arrays: list[dict[str, Any]]) -> Any:
    if not isinstance(value, dict) or "__phase8_type__" not in value:
        return value
    kind = value["__phase8_type__"]
    if kind == "array":
        try:
            record = arrays[int(value["index"])]
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise SpineError("Stage 1 checkpoint array reference is invalid") from exc
        path = root / record["file"]
        if (
            not path.is_file()
            or path.stat().st_size != record["bytes"]
            or _sha256_file(path) != record["sha256"]
        ):
            raise SpineError("Stage 1 checkpoint array hash differs")
        array = np.load(path, mmap_mode="r", allow_pickle=False)
        if str(array.dtype) != record["dtype"] or list(array.shape) != record["shape"]:
            raise SpineError("Stage 1 checkpoint array schema differs")
        array.setflags(write=False)
        return array
    if kind in {"tuple", "list", "frozenset"}:
        items = [_decode_checkpoint_value(item, root, arrays) for item in value["items"]]
        return tuple(items) if kind == "tuple" else (list(items) if kind == "list" else frozenset(items))
    if kind == "mapping":
        return {
            _decode_checkpoint_value(key, root, arrays): _decode_checkpoint_value(item, root, arrays)
            for key, item in value["items"]
        }
    if kind == "dataclass":
        module_name = value.get("module")
        if not isinstance(module_name, str) or not module_name.startswith("mnq_lab."):
            raise SpineError("Stage 1 checkpoint dataclass module is not permitted")
        target: Any = importlib.import_module(module_name)
        for component in str(value.get("qualname", "")).split("."):
            if not component or component == "<locals>":
                raise SpineError("Stage 1 checkpoint dataclass name is invalid")
            target = getattr(target, component)
        if not is_dataclass(target):
            raise SpineError("Stage 1 checkpoint target is not a dataclass")
        kwargs = {
            str(name): _decode_checkpoint_value(item, root, arrays)
            for name, item in value["fields"]
        }
        return target(**kwargs)
    raise SpineError(f"unknown Stage 1 checkpoint type tag: {kind!r}")


class CheckpointStore:
    """Append-only operational units bound to one complete run identity."""

    def __init__(
        self,
        root: Path,
        identity: CheckpointIdentity,
        *,
        mirror_root: Path | None = None,
    ):
        self.root = Path(root)
        self.mirror_root = None if mirror_root is None else Path(mirror_root)
        self.identity = identity
        self.reused_stage1_units: list[str] = []
        self.new_stage1_units: list[str] = []
        self.reused_plans = False
        self.new_plans = False
        self.reused_chunks: list[int] = []
        self.new_chunks: list[int] = []
        for candidate in self._roots(mirror_first=False):
            self._open_or_create_root(candidate)
        self._validate_root_inventory()

    def _roots(self, *, mirror_first: bool) -> tuple[Path, ...]:
        roots = (self.root,) if self.mirror_root is None else (self.root, self.mirror_root)
        return tuple(reversed(roots)) if mirror_first else roots

    def _open_or_create_root(self, root: Path) -> None:
        payload = canonical_json_bytes(asdict(self.identity))
        identity_path = root / "identity.json"
        identity_staging = root.with_name(f".{root.name}.identity.staging")
        if identity_staging.exists():
            raise SpineError("an incomplete checkpoint identity staging directory exists")
        if root.exists():
            if not root.is_dir() or not identity_path.is_file():
                raise SpineError("checkpoint root is incomplete")
            if identity_path.read_bytes() != payload:
                raise SpineError("checkpoint identity differs from the requested resume")
            return
        identity_staging.mkdir(parents=True, exist_ok=False)
        (identity_staging / "identity.json").write_bytes(payload)
        _durably_flush_directory(identity_staging)
        identity_staging.replace(root)
        _durably_flush_parent(root)

    def _validate_root_inventory(self) -> None:
        for root in self._roots(mirror_first=False):
            for path in root.iterdir():
                name = path.name
                if name == "identity.json":
                    continue
                if name.startswith(".") and name.endswith(".staging"):
                    raise SpineError(f"incomplete checkpoint staging evidence exists: {name}")
                allowed = (
                    name == "plans"
                    or name == "stage1-final"
                    or (name.startswith("stage1-partition-") and name[17:].isdigit())
                    or (name.startswith("chunk-") and name[6:].isdigit())
                )
                if not allowed:
                    raise SpineError(f"unexpected checkpoint entry: {name}")

    def _select_unit(self, relative: str) -> Path | None:
        found = [root / relative for root in self._roots(mirror_first=False) if (root / relative).exists()]
        if not found:
            return None
        for path in found:
            if not path.is_dir() or not (path / "manifest.json").is_file():
                raise SpineError(f"checkpoint unit is incomplete: {relative}")
        if len(found) == 2 and _checkpoint_tree_digest(found[0]) != _checkpoint_tree_digest(found[1]):
            raise SpineError(f"local and external checkpoint units differ: {relative}")
        return found[0]

    def _write_unit(self, relative: str, writer: Any) -> None:
        if self._select_unit(relative) is not None:
            raise SpineError(f"checkpoint unit already exists: {relative}")
        for root in self._roots(mirror_first=True):
            final = root / relative
            staging = root / f".{relative}.staging"
            if staging.exists():
                raise SpineError(f"incomplete checkpoint staging evidence exists: {staging.name}")
            staging.mkdir()
            writer(staging)
            if not (staging / "manifest.json").is_file():
                raise SpineError("checkpoint writer omitted its canonical manifest")
            _durably_flush_directory(staging)
            staging.replace(final)
            _durably_flush_parent(final)

    def has_chunk(self, index: int) -> bool:
        return self._select_unit(f"chunk-{index:06d}") is not None

    def write_chunk(self, index: int, columns: Mapping[str, np.ndarray]) -> None:
        def writer(staging: Path) -> None:
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
                    "file": filename, "dtype": str(array.dtype),
                    "rows": int(array.size), "bytes": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            manifest = {
                "schema_version": "phase8-bootstrap-chunk-v2",
                "chunk_index": index, "column_order": list(columns),
                "row_count": 0 if row_count is None else row_count,
                "columns": manifest_columns,
            }
            (staging / "manifest.json").write_bytes(canonical_json_bytes(manifest))
        self._write_unit(f"chunk-{index:06d}", writer)
        self.new_chunks.append(index)

    def read_chunk(self, index: int) -> dict[str, np.ndarray]:
        root = self._select_unit(f"chunk-{index:06d}")
        if root is None:
            raise SpineError(f"checkpoint chunk {index} is missing")
        manifest_path = root / "manifest.json"
        if not manifest_path.is_file():
            raise SpineError(f"checkpoint chunk {index} is incomplete")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.read_bytes() != canonical_json_bytes(manifest):
            raise SpineError(f"checkpoint chunk {index} manifest is not canonical")
        result: dict[str, np.ndarray] = {}
        if manifest.get("chunk_index") != index:
            raise SpineError(f"checkpoint chunk {index} identity differs")
        column_order = manifest.get("column_order")
        columns = manifest.get("columns")
        if (
            not isinstance(column_order, list)
            or len(column_order) != len(set(column_order))
            or not isinstance(columns, dict)
            or set(column_order) != set(columns)
        ):
            raise SpineError(f"checkpoint chunk {index} schema is invalid")
        expected_files = {"manifest.json"}
        for name in column_order:
            record = columns[name]
            path = root / record["file"]
            expected_files.add(record["file"])
            if not path.is_file() or path.stat().st_size != record["bytes"] or _sha256_file(path) != record["sha256"]:
                raise SpineError(f"checkpoint chunk {index} column hash differs")
            array = np.load(path, allow_pickle=False)
            if (
                array.ndim != 1 or str(array.dtype) != record["dtype"]
                or int(array.size) != record["rows"]
                or int(array.size) != manifest.get("row_count")
            ):
                raise SpineError(f"checkpoint chunk {index} column schema differs")
            result[name] = array
        actual_files = {path.name for path in root.iterdir() if path.is_file()}
        if actual_files != expected_files:
            raise SpineError(f"checkpoint chunk {index} contains an unexpected file")
        if index not in self.reused_chunks and index not in self.new_chunks:
            self.reused_chunks.append(index)
        return result

    def validate_chunk_inventory(self, expected_indices: Iterable[int]) -> None:
        expected = {f"chunk-{int(index):06d}" for index in expected_indices}
        for root in self._roots(mirror_first=False):
            actual = {path.name for path in root.iterdir() if path.name.startswith("chunk-")}
            unexpected = actual - expected
            if unexpected:
                raise SpineError(f"unexpected or duplicate bootstrap chunk: {sorted(unexpected)[0]}")

    def has_plan_matrices(self) -> bool:
        return self._select_unit("plans") is not None

    def write_plan_matrices(self, bundle: Any) -> None:
        from mnq_lab.phase8.uncertainty import _JointPlanMatrices

        if not isinstance(bundle, _JointPlanMatrices):
            raise SpineError("checkpoint plans have the wrong type")
        def writer(staging: Path) -> None:
            records = []
            for index, matrix in enumerate(bundle.matrices):
                path = staging / f"{index:02d}_session_multiplicities.npy"
                np.save(path, np.ascontiguousarray(matrix), allow_pickle=False)
                records.append({
                    "file": path.name, "dtype": str(matrix.dtype),
                    "shape": list(matrix.shape), "bytes": path.stat().st_size,
                    "sha256": _sha256_file(path),
                })
            manifest = {
                "schema_version": "phase8-bootstrap-plans-v2",
                "group_digest": bundle.group_digest,
                "bootstrap_contract": asdict(bundle.contract), "matrices": records,
            }
            (staging / "manifest.json").write_bytes(canonical_json_bytes(manifest))
        self._write_unit("plans", writer)
        self.new_plans = True

    def read_plan_matrices(self, contract: Any) -> Any:
        from mnq_lab.phase8.uncertainty import BootstrapContract, _JointPlanMatrices

        if not isinstance(contract, BootstrapContract):
            raise SpineError("checkpoint plan read requires BootstrapContract")
        root = self._select_unit("plans")
        if root is None:
            raise SpineError("checkpoint plan matrices are missing")
        manifest_path = root / "manifest.json"
        if not manifest_path.is_file():
            raise SpineError("checkpoint plan matrices are incomplete")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.read_bytes() != canonical_json_bytes(manifest):
            raise SpineError("checkpoint plan manifest is not canonical")
        if canonical_json_bytes(manifest["bootstrap_contract"]) != canonical_json_bytes(asdict(contract)):
            raise SpineError("checkpoint plan contract differs from the current contract")
        if (
            not isinstance(manifest.get("matrices"), list)
            or len(manifest["matrices"]) != len(contract.block_lengths)
            or len({record.get("file") for record in manifest["matrices"]})
            != len(manifest["matrices"])
        ):
            raise SpineError("checkpoint plan matrix inventory differs")
        matrices = []
        expected_files = {"manifest.json"}
        for record in manifest["matrices"]:
            path = root / record["file"]
            expected_files.add(record["file"])
            if path.stat().st_size != record["bytes"] or _sha256_file(path) != record["sha256"]:
                raise SpineError("checkpoint plan matrix hash differs")
            matrix = np.load(path, mmap_mode="r", allow_pickle=False)
            if str(matrix.dtype) != record["dtype"] or list(matrix.shape) != record["shape"]:
                raise SpineError("checkpoint plan matrix schema differs")
            matrix.setflags(write=False)
            matrices.append(matrix)
        if {path.name for path in root.iterdir() if path.is_file()} != expected_files:
            raise SpineError("checkpoint plans contain an unexpected file")
        if not self.new_plans:
            self.reused_plans = True
        return _JointPlanMatrices(
            str(manifest["group_digest"]), contract, tuple(matrices)
        )

    def has_stage1_unit(self, name: str) -> bool:
        if name != "final" and not (name.startswith("partition-") and name[10:].isdigit()):
            raise SpineError("Stage 1 checkpoint unit name is invalid")
        relative = "stage1-final" if name == "final" else f"stage1-{name}"
        return self._select_unit(relative) is not None

    def write_stage1_unit(
        self,
        name: str,
        value: Any,
        *,
        declared_indices: tuple[int, ...],
        declared_identity_sha256: str,
        row_ids: tuple[str, ...],
    ) -> None:
        relative = "stage1-final" if name == "final" else f"stage1-{name}"
        if len(declared_identity_sha256) != 64:
            raise SpineError("Stage 1 declared identity hash is invalid")
        def writer(staging: Path) -> None:
            arrays: list[dict[str, Any]] = []
            encoded = _encode_checkpoint_value(value, staging, arrays)
            metadata = {"value": encoded}
            metadata_path = staging / "metadata.json"
            metadata_path.write_bytes(canonical_json_bytes(metadata))
            manifest = {
                "schema_version": "phase8-stage1-unit-v1",
                "unit_name": name,
                "declared_indices": list(declared_indices),
                "declared_identity_sha256": declared_identity_sha256,
                "row_order": list(row_ids),
                "metadata": {
                    "file": metadata_path.name,
                    "bytes": metadata_path.stat().st_size,
                    "sha256": _sha256_file(metadata_path),
                },
                "arrays": arrays,
            }
            (staging / "manifest.json").write_bytes(canonical_json_bytes(manifest))
        self._write_unit(relative, writer)
        self.new_stage1_units.append(name)

    def read_stage1_unit(
        self,
        name: str,
        *,
        declared_indices: tuple[int, ...],
        declared_identity_sha256: str,
        row_ids: tuple[str, ...] | None = None,
    ) -> Any:
        relative = "stage1-final" if name == "final" else f"stage1-{name}"
        root = self._select_unit(relative)
        if root is None:
            raise SpineError(f"Stage 1 checkpoint unit is missing: {name}")
        manifest_path = root / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SpineError("Stage 1 checkpoint manifest is unreadable") from exc
        if manifest_path.read_bytes() != canonical_json_bytes(manifest):
            raise SpineError("Stage 1 checkpoint manifest is not canonical")
        if (
            manifest.get("schema_version") != "phase8-stage1-unit-v1"
            or manifest.get("unit_name") != name
            or manifest.get("declared_indices") != list(declared_indices)
            or manifest.get("declared_identity_sha256") != declared_identity_sha256
            or (row_ids is not None and manifest.get("row_order") != list(row_ids))
        ):
            raise SpineError("Stage 1 checkpoint identity differs")
        metadata_record = manifest.get("metadata", {})
        metadata_path = root / str(metadata_record.get("file", ""))
        if (
            not metadata_path.is_file()
            or metadata_path.stat().st_size != metadata_record.get("bytes")
            or _sha256_file(metadata_path) != metadata_record.get("sha256")
        ):
            raise SpineError("Stage 1 checkpoint metadata hash differs")
        expected_files = {"manifest.json", metadata_path.name}
        for record in manifest.get("arrays", []):
            expected_files.add(record["file"])
        if {path.name for path in root.iterdir() if path.is_file()} != expected_files:
            raise SpineError("Stage 1 checkpoint contains an unexpected file")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        value = _decode_checkpoint_value(metadata["value"], root, manifest["arrays"])
        if name not in self.new_stage1_units and name not in self.reused_stage1_units:
            self.reused_stage1_units.append(name)
        return value


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
    "CONTRAST_COLUMNS", "DAY_TYPE_COLUMNS", "INTERACTION_COLUMNS",
    "INTERVAL_COLUMNS", "CheckpointIdentity", "CheckpointStore",
    "PHASE8_TABLE_ORDER", "PHASE8_TABLE_SCHEMAS", "Phase8Table",
    "canonical_json_bytes", "write_phase8_artifacts",
]
