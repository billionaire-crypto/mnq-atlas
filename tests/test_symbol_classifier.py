"""Gate 3: the symbol classifier is authoritative (spec §5.1 gate 3).

Spec §14 struck "assert ~1.6% spread rows". Nothing here checks a proportion.

The measured partition of the real source (docs/DISCREPANCIES.md D3) is 87 distinct
symbols = 32 outrights + 55 calendar spreads, exhaustively.
"""

from __future__ import annotations

import pytest

from mnq_lab import SpineError
from mnq_lab.spine.gates import gate_symbol_classification
from mnq_lab.spine.symbols import (
    OUTRIGHT_PATTERN,
    SPREAD_PATTERN,
    classify_symbols,
)

OUTRIGHTS = ["MNQH0", "MNQM1", "MNQU2", "MNQZ3", "MNQM9", "MNQH24"]
SPREADS = ["MNQH0-MNQM0", "MNQU5-MNQZ5", "MNQZ5-MNQH6", "MNQM9-MNQU9"]


@pytest.mark.parametrize("symbol", OUTRIGHTS)
def test_outrights_are_retained(symbol):
    result = classify_symbols({symbol: 1})
    assert symbol in result.retained
    assert not result.rejected


@pytest.mark.parametrize("symbol", SPREADS)
def test_spreads_are_rejected(symbol):
    # One outright must be present: a source with no retained symbol at all is itself a
    # fail-closed condition, asserted separately below.
    result = classify_symbols({symbol: 1, "MNQH0": 1})
    assert symbol in result.rejected
    assert set(result.retained) == {"MNQH0"}


def test_partition_is_exhaustive_and_counts_are_exact():
    counts = {**{s: 10 for s in OUTRIGHTS}, **{s: 3 for s in SPREADS}}
    result = classify_symbols(counts)
    assert result.retained_symbol_count == len(OUTRIGHTS)
    assert result.rejected_symbol_count == len(SPREADS)
    assert result.retained_rows + result.rejected_rows == sum(counts.values())


@pytest.mark.parametrize(
    "symbol",
    [
        "ESH4",  # a different product
        "MNQ",  # no month/year
        "MNQA1",  # not a quarterly month code
        "MNQH0-",  # truncated spread
        "MNQH0-ESM0",  # mixed-product spread
        "MNQH0-MNQM0-MNQU0",  # three legs
        "mnqh0",  # wrong case
        "MNQH0 ",  # trailing space
        "MNQM9\n",  # trailing newline: `$` would accept this, `fullmatch` must not
    ],
)
def test_negative_case_unknown_symbols_fail_closed(symbol):
    """A symbol matching neither rule must halt the build, not be silently dropped."""
    with pytest.raises(SpineError, match="match neither"):
        classify_symbols({symbol: 1})


def test_negative_case_empty_source_fails_closed():
    with pytest.raises(SpineError):
        classify_symbols({})
    with pytest.raises(SpineError, match="no outright"):
        classify_symbols({"MNQH0-MNQM0": 5})


def test_patterns_are_anchored_both_ends():
    """`str.match` is a prefix match; the classifier must use full matching."""
    assert OUTRIGHT_PATTERN.match("MNQH0junk") is None
    assert SPREAD_PATTERN.match("MNQH0-MNQM0junk") is None
    assert OUTRIGHT_PATTERN.fullmatch("MNQM9\n") is None


# --- gate 3 over a manifest ---------------------------------------------------------


def _manifest(retained, rejected, source_rows=None):
    total = sum(retained.values()) + sum(rejected.values())
    return {
        "symbol_classification": {
            "retained_symbols": retained,
            "rejected_spread_symbols": rejected,
            "retained_symbol_count": len(retained),
            "rejected_spread_symbol_count": len(rejected),
            "distinct_symbol_count": len(retained) + len(rejected),
            "retained_rows": sum(retained.values()),
            "rejected_spread_rows": sum(rejected.values()),
        },
        "source": {"rows": total if source_rows is None else source_rows},
    }


def test_gate_passes_on_a_consistent_manifest():
    report = gate_symbol_classification(
        _manifest({"MNQH0": 10}, {"MNQH0-MNQM0": 2})
    )
    assert report["status"] == "pass"
    assert report["distinct_symbol_count"] == 2


def test_negative_case_gate_catches_a_non_exhaustive_partition():
    """Rows unaccounted for must fail — this is the silent-data-loss detector."""
    with pytest.raises(SpineError, match="not exhaustive"):
        gate_symbol_classification(
            _manifest({"MNQH0": 10}, {"MNQH0-MNQM0": 2}, source_rows=99)
        )


def test_negative_case_gate_catches_a_miscounted_manifest():
    manifest = _manifest({"MNQH0": 10}, {"MNQH0-MNQM0": 2})
    manifest["symbol_classification"]["retained_symbol_count"] = 7
    with pytest.raises(SpineError, match="retained_symbol_count"):
        gate_symbol_classification(manifest)


def test_negative_case_gate_catches_a_spread_smuggled_into_retained():
    with pytest.raises(SpineError, match="do not match the outright rule"):
        gate_symbol_classification(_manifest({"MNQH0-MNQM0": 10}, {}))


def test_real_manifest_partition(locked_5m):
    """The measured partition of the actual source (D3)."""
    report = gate_symbol_classification(locked_5m.manifest)
    assert report["retained_symbol_count"] == 32
    assert report["rejected_spread_symbol_count"] == 55
    assert report["distinct_symbol_count"] == 87
    assert report["retained_rows"] == 3_607_321
    assert report["rejected_spread_rows"] == 57_907
    assert report["retained_rows"] + report["rejected_spread_rows"] == 3_665_228
