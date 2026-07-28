"""BarStore: `.npy` column store with a hashed manifest.

Spec §5: "Store format: `.npy` column store. `pyarrow` and `fastparquet` are both absent;
`to_parquet()` raises `ImportError`. One `.npy` per column plus `manifest.json` with
per-file sha256 ... Loads via `mmap_mode="r"`."

The manifest deliberately contains **no wall-clock timestamp**. Spec §13 test 17 requires
artifact determinism (identical bytes) whenever the environment fingerprint matches, and
a build time would break that on every rebuild. Provenance comes from `build_id`, the
source hash, and the git commit instead.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from mnq_lab import SpineError
from mnq_lab.spine.vendored import sha256_file

__all__ = ["PIPELINE_VERSION", "BarStore", "environment_fingerprint", "write_store"]

# Bump on any change to the meaning of a stored column. Two stores with different
# pipeline versions may never be compared or concatenated (spec §5.1: "Never bridge two
# data definitions").
PIPELINE_VERSION = "spine-1.0.0"

MANIFEST_NAME = "manifest.json"


# --- environment ------------------------------------------------------------------

def _git_fingerprint(repo_root: Path) -> dict[str, Any]:
    """Record the git state. Spec §16.2 asserts this is not a repo; it is (D1)."""
    def _run(*args: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", *args],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip() if out.returncode == 0 else None

    commit = _run("rev-parse", "HEAD")
    if commit is None:
        return {"vcs": "none"}
    status = _run("status", "--porcelain")
    return {
        "vcs": "git",
        "commit": commit,
        "branch": _run("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(status),
    }


def environment_fingerprint(repo_root: Path) -> dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "pipeline_version": PIPELINE_VERSION,
        **_git_fingerprint(repo_root),
    }


# --- store ------------------------------------------------------------------------

@dataclass(frozen=True)
class BarStore:
    """A read-only, memory-mapped column store."""

    root: Path
    manifest: dict[str, Any]
    _columns: dict[str, np.ndarray]

    @property
    def n_rows(self) -> int:
        return int(self.manifest["row_count"])

    @property
    def symbols(self) -> list[str]:
        return list(self.manifest["symbols"])

    @property
    def column_names(self) -> list[str]:
        return list(self.manifest["columns"].keys())

    def column(self, name: str) -> np.ndarray:
        if name not in self._columns:
            raise SpineError(
                f"column {name!r} is not in this store; available: "
                f"{sorted(self._columns)}"
            )
        return self._columns[name]

    def __getitem__(self, name: str) -> np.ndarray:
        return self.column(name)

    def symbol_series(self) -> np.ndarray:
        """Decode `symbol_code` back to symbol strings."""
        table = np.asarray(self.symbols, dtype=object)
        return table[self.column("symbol_code").astype(np.int64)]

    @classmethod
    def open(cls, root: Path | str) -> "BarStore":
        root = Path(root)
        manifest_path = root / MANIFEST_NAME
        if not manifest_path.is_file():
            raise SpineError(f"no {MANIFEST_NAME} in {root}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        columns: dict[str, np.ndarray] = {}
        for name, spec in manifest["columns"].items():
            path = root / spec["file"]
            if not path.is_file():
                raise SpineError(f"column file missing: {path}")
            array = np.load(path, mmap_mode="r")
            if str(array.dtype) != spec["dtype"]:
                raise SpineError(
                    f"column {name!r} has dtype {array.dtype}, manifest says "
                    f"{spec['dtype']}"
                )
            if len(array) != manifest["row_count"]:
                raise SpineError(
                    f"column {name!r} has {len(array)} rows, manifest says "
                    f"{manifest['row_count']}"
                )
            columns[name] = array
        return cls(root=root, manifest=manifest, _columns=columns)

    def verify_hashes(self) -> None:
        """Re-hash every column file and compare with the manifest. Fails closed."""
        for name, spec in self.manifest["columns"].items():
            digest = sha256_file(self.root / spec["file"])
            if digest != spec["sha256"]:
                raise SpineError(
                    f"column {name!r} sha256 mismatch in {self.root}: manifest "
                    f"{spec['sha256']}, file {digest}. The store has been modified "
                    "since it was built."
                )

    def to_frame(self) -> pd.DataFrame:
        """Materialise as a DataFrame. Copies out of the mmap; use for gates and tests."""
        return pd.DataFrame({name: np.asarray(col) for name, col in self._columns.items()})


def write_store(
    root: Path,
    columns: dict[str, np.ndarray],
    *,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Write one `.npy` per column plus a hashed manifest. Returns the manifest."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)

    if not columns:
        raise SpineError("refusing to write a store with no columns")
    lengths = {len(array) for array in columns.values()}
    if len(lengths) != 1:
        raise SpineError(
            f"columns have differing lengths: "
            f"{ {name: len(a) for name, a in columns.items()} }"
        )
    row_count = lengths.pop()
    if row_count == 0:
        raise SpineError("refusing to write an empty store")

    column_manifest: dict[str, Any] = {}
    for name in sorted(columns):
        array = np.ascontiguousarray(columns[name])
        filename = f"{name}.npy"
        path = root / filename
        # allow_pickle=False: a column store must never carry executable payloads.
        np.save(path, array, allow_pickle=False)
        column_manifest[name] = {
            "file": filename,
            "dtype": str(array.dtype),
            "rows": int(len(array)),
            "sha256": sha256_file(path),
        }

    manifest = {
        **metadata,
        "row_count": int(row_count),
        "columns": column_manifest,
    }
    manifest_path = root / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return manifest


def manifest_digest(manifest: dict[str, Any]) -> str:
    """Stable digest of a manifest's content, for cross-store comparison."""
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
