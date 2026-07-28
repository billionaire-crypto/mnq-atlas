"""Gate 3: authoritative symbol classification.

Spec §5.1 gate 3: "Symbol classification, not a percentage. Every retained symbol matches
the outright MNQ pattern; every rejected symbol matches an explicit spread pattern; exact
counts recorded in the manifest and re-versioned on a new source. The classifier is
authoritative."

Spec §14 struck the earlier rule "assert ~1.6% spread rows". Do not reintroduce a
percentage check.

The spread pattern below was derived by enumerating every distinct symbol in the source
(2026-07-28): 87 symbols = 32 outrights + 55 spreads, exhaustively, with no residue. Each
of the 55 spreads is two valid outright legs joined by a hyphen. See
docs/DISCREPANCIES.md D3 for the measured table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mnq_lab import SpineError

__all__ = [
    "OUTRIGHT_PATTERN",
    "SPREAD_PATTERN",
    "SymbolClassification",
    "classify_symbols",
]

# prepare_databento_mnq.py:31, unchanged — the retained-symbol rule.
OUTRIGHT_PATTERN = re.compile(r"^MNQ([HMUZ])(\d{1,2})$")

# The rejected-symbol rule: two outright legs joined by a hyphen.
SPREAD_PATTERN = re.compile(r"^MNQ([HMUZ])(\d{1,2})-MNQ([HMUZ])(\d{1,2})$")


def _is_outright(symbol: str) -> bool:
    return OUTRIGHT_PATTERN.fullmatch(symbol) is not None


def _is_spread(symbol: str) -> bool:
    return SPREAD_PATTERN.fullmatch(symbol) is not None


@dataclass(frozen=True)
class SymbolClassification:
    """Exhaustive partition of the source's distinct symbols."""

    retained: dict[str, int] = field(default_factory=dict)
    rejected: dict[str, int] = field(default_factory=dict)

    @property
    def retained_symbol_count(self) -> int:
        return len(self.retained)

    @property
    def rejected_symbol_count(self) -> int:
        return len(self.rejected)

    @property
    def retained_rows(self) -> int:
        return sum(self.retained.values())

    @property
    def rejected_rows(self) -> int:
        return sum(self.rejected.values())

    def to_manifest(self) -> dict[str, object]:
        """Exact counts for the manifest (spec §5.1 gate 3 requires exactness)."""
        return {
            "outright_pattern": OUTRIGHT_PATTERN.pattern,
            "spread_pattern": SPREAD_PATTERN.pattern,
            "retained_symbol_count": self.retained_symbol_count,
            "rejected_spread_symbol_count": self.rejected_symbol_count,
            "distinct_symbol_count": (
                self.retained_symbol_count + self.rejected_symbol_count
            ),
            "retained_rows": self.retained_rows,
            "rejected_spread_rows": self.rejected_rows,
            "retained_symbols": dict(sorted(self.retained.items())),
            "rejected_spread_symbols": dict(sorted(self.rejected.items())),
        }


def classify_symbols(symbol_counts: dict[str, int]) -> SymbolClassification:
    """Partition symbols into retained outrights and rejected calendar spreads.

    Fails closed on any symbol matching neither rule, and on any symbol matching both.
    A new vendor drop introducing an unrecognised naming convention therefore halts the
    build instead of silently discarding rows.
    """
    retained: dict[str, int] = {}
    rejected: dict[str, int] = {}
    unclassified: list[str] = []
    ambiguous: list[str] = []

    for symbol, count in symbol_counts.items():
        name = str(symbol)
        outright, spread = _is_outright(name), _is_spread(name)
        if outright and spread:
            ambiguous.append(name)
        elif outright:
            retained[name] = int(count)
        elif spread:
            rejected[name] = int(count)
        else:
            unclassified.append(name)

    if ambiguous:
        raise SpineError(
            "symbols match both the outright and spread rules, so the classifier is "
            f"not a partition: {sorted(ambiguous)[:10]}"
        )
    if unclassified:
        raise SpineError(
            f"{len(unclassified)} symbol(s) match neither the outright rule "
            f"{OUTRIGHT_PATTERN.pattern!r} nor the spread rule "
            f"{SPREAD_PATTERN.pattern!r}: {sorted(unclassified)[:10]}. "
            "The classifier is authoritative (spec §5.1 gate 3) — extend it "
            "deliberately and re-version the manifest; do not widen it to pass."
        )
    if not retained:
        raise SpineError("no outright MNQ symbols were found in the source")

    return SymbolClassification(retained=retained, rejected=rejected)
