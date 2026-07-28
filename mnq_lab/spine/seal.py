"""Corpus tiers and the locked-store guard.

Spec §11:

    Exploration          2019-05-05 -> 2023-03-29   free use
    Locked confirmation  2023-03-30 -> 2026-03-29   post-preregistration only
    Forward vintages     after freeze               the only untouched evidence

    "Physically separate `data/exploration/` and `data/locked_confirmation/`; the
    exploration runtime does not import or mmap the locked store. `Corpus.EXPLORATION`
    is truncated at `seal_boundary - max_horizon_bars` so rows are absent from the
    object, not merely flagged."

The tier bounds are stated in §11 prose rather than in `analysis_constants_v1.yaml`.
`SEAL_BOUNDARY_TRADE_DATE` below is tied to the YAML by
`tests/test_spec_consistency.py`, which asserts it equals
`completion.source_population.years[1]` — so a change to one without the other fails.

The split is on **CME trade date**, not UTC date: the two §11 bounds are contiguous
calendar days, and only the trade-date reading makes the tiers adjacent and
non-overlapping (docs/DISCREPANCIES.md D6).
"""

from __future__ import annotations

import enum
from pathlib import Path

from mnq_lab import SpineError

__all__ = [
    "SEAL_BOUNDARY_TRADE_DATE",
    "LOCKED_STORE_DIRNAME",
    "EXPLORATION_STORE_DIRNAME",
    "Corpus",
    "store_path",
    "assert_exploration_safe",
]

# Last trade date belonging to the exploration tier (spec §11).
SEAL_BOUNDARY_TRADE_DATE = "2023-03-29"

EXPLORATION_STORE_DIRNAME = "exploration"
LOCKED_STORE_DIRNAME = "locked_confirmation"


class Corpus(enum.Enum):
    EXPLORATION = "exploration"
    LOCKED_CONFIRMATION = "locked_confirmation"

    @property
    def dirname(self) -> str:
        return self.value

    @property
    def is_locked(self) -> bool:
        return self is Corpus.LOCKED_CONFIRMATION


def store_path(root: Path | str, corpus: Corpus, frequency: str) -> Path:
    """`<root>/<tier>/bars_<frequency>`, e.g. `data/exploration/bars_5m`."""
    if frequency not in {"1m", "5m"}:
        raise SpineError(f"unknown bar frequency {frequency!r}")
    return Path(root) / corpus.dirname / f"bars_{frequency}"


def assert_exploration_safe(path: Path | str) -> Path:
    """Refuse a path inside the locked store.

    Call this from anything that opens a store on behalf of exploratory analysis. It is
    friction, not structure (spec §11) — a determined caller can bypass it. The actual
    protections are preregistration, the ledger, access control, and human discipline.
    `tests/test_seal_guard.py` additionally scans the package by AST so no exploratory
    module can even name the locked directory.
    """
    resolved = Path(path).resolve()
    if LOCKED_STORE_DIRNAME in resolved.parts:
        raise SpineError(
            f"refusing to open {resolved} from the exploration runtime: it is inside "
            f"the locked confirmation store. Spec §16.4.1 — the locked tier is "
            "post-preregistration only and is already contaminated by prior "
            "Kronos/LoRA work."
        )
    return resolved
