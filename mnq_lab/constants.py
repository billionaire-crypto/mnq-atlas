"""Frozen-constant loader.

Spec §12: "S01A refuses to run if any constant is absent. No defaults, no inline
literals." This module is the only place `analysis_constants_v1.yaml` is read, and it
never supplies a default for a missing key.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from mnq_lab import SpineError

REPO_ROOT = Path(__file__).resolve().parent.parent
CONSTANTS_PATH = REPO_ROOT / "analysis_constants_v1.yaml"
SPEC_PATH = REPO_ROOT / "REV6_FROZEN_SPEC.md"

_MISSING = object()


class Constants:
    """Read-only view over the frozen constants, with fail-closed lookup."""

    def __init__(self, data: dict[str, Any], source: Path) -> None:
        self._data = data
        self.source = source

    def get(self, *path: str) -> Any:
        """Return a nested constant. Raises rather than defaulting (spec §12)."""
        node: Any = self._data
        for index, key in enumerate(path):
            if not isinstance(node, dict):
                raise SpineError(
                    f"constant path {'.'.join(path)} is not a mapping at "
                    f"{'.'.join(path[:index]) or '<root>'} in {self.source}"
                )
            node = node.get(key, _MISSING)
            if node is _MISSING:
                raise SpineError(
                    f"required constant {'.'.join(path)} is absent from "
                    f"{self.source}; no default is permitted (spec §12)"
                )
        return node

    def as_dict(self) -> dict[str, Any]:
        return self._data


def _normalise_yaml_keys(node: Any) -> Any:
    """Restore the *written* spelling of keys YAML resolves to non-strings.

    `analysis_constants_v1.yaml` contains, under §12 `inference:`, a key written as
    `null:`. YAML resolves an unquoted `null` to the null value, so `safe_load` returns
    a mapping whose key is Python `None` — meaning `constants["inference"]["null"]`
    raises `KeyError` while the file plainly reads `null:`.

    The frozen file is **not** edited to work around this (§16.4.2 and the frozen-file
    rule); the key is restored to the string it was written as, here, at load time. See
    docs/DISCREPANCIES.md D8. `tests/test_spec_consistency.py` asserts both that the raw
    YAML still has the `None` key and that the normalised lookup works, so this
    accommodation cannot silently stop matching the file.
    """
    if isinstance(node, dict):
        return {
            ("null" if key is None else key): _normalise_yaml_keys(value)
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_normalise_yaml_keys(item) for item in node]
    return node


def load_constants(path: Path | None = None) -> Constants:
    resolved = Path(path) if path is not None else CONSTANTS_PATH
    if not resolved.is_file():
        raise SpineError(
            f"analysis_constants_v1.yaml not found at {resolved}. The lab refuses to "
            "run without it; do not invent defaults (spec §12, §16.4.2)."
        )
    parsed = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise SpineError(f"{resolved} did not parse to a mapping")
    return Constants(_normalise_yaml_keys(parsed), resolved)


# --- Spine-relevant constants, resolved once and named -----------------------------

class SpineConstants:
    """The subset of frozen constants the Phase 1 spine needs (spec §4, §11)."""

    def __init__(self, constants: Constants) -> None:
        self.spec_version = constants.get("spec_version")
        self.program_id = constants.get("program_id")
        self.storage_tz = constants.get("time", "storage_tz")
        self.session_tz = constants.get("time", "session_tz")
        self.bar_label = constants.get("time", "bar_label")
        self.tick_size = float(constants.get("time", "tick_size"))
        self.rth_start_ct = constants.get("time", "rth_start_ct")
        self.rth_end_ct = constants.get("time", "rth_end_ct")
        self.maintenance_break_ct = tuple(
            constants.get("time", "maintenance_break_ct")
        )
        self.horizons_minutes = list(constants.get("horizons_minutes"))

        if self.bar_label != "open":
            raise SpineError(
                f"time.bar_label is {self.bar_label!r}; the spine is written against "
                "ts_event = bar OPEN (spec §4, finding E)"
            )
        if self.storage_tz != "UTC":
            raise SpineError(f"time.storage_tz must be UTC, got {self.storage_tz!r}")
        if self.tick_size <= 0:
            raise SpineError(f"time.tick_size must be positive, got {self.tick_size}")


def load_spine_constants(path: Path | None = None) -> SpineConstants:
    return SpineConstants(load_constants(path))
