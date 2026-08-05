"""Deterministic immutable column-store writer for Unit O outcome tables."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from mnq_lab import SpineError
from mnq_lab.constants import CONSTANTS_PATH, REPO_ROOT, SPEC_PATH
from mnq_lab.outcomes.excursions import (
    ESTIMAND_ORDER,
    OUTCOME_SCHEMA,
    OUTCOME_STATUSES,
    OutcomeTable,
    validate_outcome_table,
)
from mnq_lab.spine.exploration import validate_exploration_store
from mnq_lab.spine.seal import LOCKED_STORE_DIRNAME, assert_exploration_safe
from mnq_lab.spine.store import BarStore, environment_fingerprint
from mnq_lab.spine.timemodel import assert_store_bar_seconds

# D32/D35: the outcome schema gained structural_unavailability_reason and
# renamed a status, so it is a new schema and carries a new identifier.
ARTIFACT_SCHEMA_VERSION = "unit-o-outcomes-v2"
BASE_COMMIT = "289977aaaf836c76788035670d099740dfaa05f7"
OUTCOME_PREREGISTRATION = REPO_ROOT / "docs" / "OUTCOME_LAYER_PREREGISTRATION.md"
PHASE8_PREREGISTRATION = REPO_ROOT / "docs" / "PHASE8_PREREGISTRATION.md"
_PROTECTED_INPUTS = {
    SPEC_PATH: "70dae16c8b12fe26d38a7bfdabf0202066fe7149f790d0d2942279d9c3b8ff50",
    CONSTANTS_PATH: "1c95aa595c30c48b853303291a7dbaabceaf5b7331bca565a30863e8dcf138d4",
    OUTCOME_PREREGISTRATION: "4b5bc97fdfd4b0219c69e6a8adf76f18072091a9389700191d3ddcd10f8207c8",
    PHASE8_PREREGISTRATION: "d07174ed0acc9e60ab6b255f4b33fc08141969c64e04f66e1e08c0aca98b4680",
}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    ).encode("utf-8")


def _contains_forbidden_tier_name(value: Any) -> bool:
    if isinstance(value, str):
        return LOCKED_STORE_DIRNAME in value
    if isinstance(value, Mapping):
        return any(
            _contains_forbidden_tier_name(key)
            or _contains_forbidden_tier_name(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_tier_name(item) for item in value)
    return False


def _verify_protected_inputs() -> dict[str, str]:
    recorded: dict[str, str] = {}
    for path, expected in _PROTECTED_INPUTS.items():
        actual = _sha256_file(path)
        if actual != expected:
            kind = "preregistration" if "PREREGISTRATION" in path.name else "frozen input"
            raise SpineError(
                f"Unit O {kind} {path.name} differs from its ratified raw-byte pin"
            )
        recorded[path.relative_to(REPO_ROOT).as_posix()] = actual
    return recorded


def write_outcome_artifact(
    root: Path,
    table: OutcomeTable,
    *,
    source_store: BarStore,
    environment: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write a validated Unit O table and canonical manifest exactly once."""
    if not isinstance(source_store, BarStore):
        raise SpineError("Unit O artifact writer requires its source BarStore")
    assert_exploration_safe(source_store.root)
    assert_store_bar_seconds(source_store.manifest)
    validate_exploration_store(source_store)
    validate_outcome_table(table)

    env = (
        dict(environment)
        if environment is not None
        else environment_fingerprint(REPO_ROOT)
    )
    if _contains_forbidden_tier_name(env) or _contains_forbidden_tier_name(
        source_store.manifest
    ):
        raise SpineError("Unit O artifact metadata contains a forbidden tier name")
    frozen_inputs = _verify_protected_inputs()
    manifest_path = source_store.root / "manifest.json"
    if not manifest_path.is_file():
        raise SpineError("Unit O source store has no raw manifest to fingerprint")

    root = Path(root)
    if root.exists() and any(root.iterdir()):
        raise SpineError("Unit O artifact output directory must be absent or empty")
    root.mkdir(parents=True, exist_ok=True)

    column_manifest: dict[str, dict[str, Any]] = {}
    for position, name in enumerate(OUTCOME_SCHEMA):
        array = table.column(name)
        filename = f"{position:02d}_{name}.npy"
        path = root / filename
        np.save(path, np.ascontiguousarray(array), allow_pickle=False)
        column_manifest[name] = {
            "file": filename,
            "dtype": str(array.dtype),
            "rows": table.row_count,
            "bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }

    status_values = table.column("outcome_status")
    status_counts = {
        status: int(np.sum(status_values == status)) for status in OUTCOME_STATUSES
    }
    code_paths = (
        REPO_ROOT / "mnq_lab" / "outcomes" / "excursions.py",
        Path(__file__).resolve(),
    )
    code_hashes = {
        path.relative_to(REPO_ROOT).as_posix(): _sha256_file(path) for path in code_paths
    }
    manifest = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "base_commit": BASE_COMMIT,
        "code_commit": env.get("commit"),
        "dirty_worktree": env.get("dirty"),
        "environment_fingerprint": env,
        "frozen_inputs": frozen_inputs,
        "input_store_build_id": source_store.manifest["build_id"],
        "input_store_manifest_sha256": _sha256_file(manifest_path),
        "code_sha256": code_hashes,
        "row_count": table.row_count,
        "column_order": list(OUTCOME_SCHEMA),
        "columns": column_manifest,
        "status_counts": status_counts,
        "horizons_minutes": [15, 30, 60],
        "estimands": list(ESTIMAND_ORDER),
        "semantic_comparison_policy": {
            "bar_rows": "numpy.array_equal",
            "component_rows": "numpy.array_equal",
            "outcomes": "exact int32 ticks",
        },
        "byte_identity_scope": "matching complete environment fingerprint only",
        "corpus_scope": "exploration",
    }
    if _contains_forbidden_tier_name(manifest):
        raise SpineError("Unit O artifact manifest contains a forbidden tier name")
    (root / "manifest.json").write_bytes(_canonical_json_bytes(manifest))
    return manifest


__all__ = ["ARTIFACT_SCHEMA_VERSION", "write_outcome_artifact"]
