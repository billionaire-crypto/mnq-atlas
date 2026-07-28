"""All four fail-closed gates, end to end against the real build (spec §5.1).

Individual gate failure modes are exercised in `test_spine_fails_closed.py`,
`test_symbol_classifier.py` and `test_roll_causality.py`. This file asserts the runner
composes them and that a real build passes every one.
"""

from __future__ import annotations

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.constants import REPO_ROOT
from mnq_lab.spine.gates import gate_roll_causality, run_all_gates

STORE_ROOT = REPO_ROOT / "data"


@pytest.fixture(scope="module")
def gate_report():
    if not (STORE_ROOT / "exploration" / "bars_5m" / "manifest.json").is_file():
        # Fail, never skip: a green suite with the gates unexecuted certifies nothing
        # (audit H2; spec §16.4.3).
        pytest.fail(
            f"Phase 1 acceptance requires built stores under {STORE_ROOT}; run "
            "python -m mnq_lab.spine.build --out data",
            pytrace=False,
        )
    return run_all_gates(STORE_ROOT)


def test_all_four_gates_pass(gate_report):
    assert gate_report["status"] == "pass"
    assert [gate["gate"] for gate in gate_report["gates"]] == [
        "roll_list_equality",
        "five_minute_equality",
        "symbol_classification",
        "roll_causality",
    ]
    assert all(gate["status"] == "pass" for gate in gate_report["gates"])


def test_gate_1_matched_the_28_roll_fixture(gate_report):
    gate = gate_report["gates"][0]
    assert gate["roll_count"] == 28
    assert gate["first_effective"] == "2019-06-18"
    assert gate["last_effective"] == "2026-03-18"


def test_gate_2_compared_every_reference_row(gate_report):
    gate = gate_report["gates"][1]
    assert gate["rows_compared"] == 211_968
    # Every column the reference carries, including the derived rollover flag (D7).
    assert set(gate["columns_compared"]) == {
        "ts_event_ns",
        "open_ticks",
        "high_ticks",
        "low_ticks",
        "close_ticks",
        "volume",
        "symbol",
        "rollover",
    }


def test_gate_3_partition_is_exact(gate_report):
    gate = gate_report["gates"][2]
    assert (gate["retained_symbol_count"], gate["rejected_spread_symbol_count"]) == (
        32,
        55,
    )
    assert gate["distinct_symbol_count"] == 87


def test_gate_4_checked_every_session(gate_report):
    gate = gate_report["gates"][3]
    assert gate["sessions_checked"] > 900  # ~985 exploration sessions per spec §11
    assert gate["rolls_checked"] == 28


def test_gate_4_report_shows_the_selector_fixture_ran(gate_report):
    """Audit H1: the CLI gate must execute the decisive fixture, not observe shapes."""
    fixture = gate_report["gates"][3]["selector_fixture"]
    assert fixture["leaky_selector_detected"] is True
    diverged = fixture["divergence_reached_next_session"]
    assert diverged[0] != diverged[1], "fixture was inert; the causality check is vacuous"


def test_negative_case_gate_4_catches_a_same_day_selector(
    exploration_5m, monkeypatch
):
    """Audit H1's exact attack: a selector using session d's own volume.

    Swap the real selector for a leaky one inside the gates module and confirm the CLI
    gate now fails — previously it returned pass because it never ran the selector.
    """
    from mnq_lab.spine import gates as gates_module
    from mnq_lab.spine.rolls import RollMap

    def leaky_map(daily_volume, first_year_by_symbol):
        by_day = {}
        for (trade_date, symbol), volume in daily_volume.items():
            by_day.setdefault(trade_date, {})[symbol] = volume
        active = {
            trade_date: max(day, key=lambda symbol: day[symbol])
            for trade_date, day in by_day.items()
        }
        return RollMap(active=active, rolls=[], expiries={})

    monkeypatch.setattr(
        gates_module, "build_causal_active_contract_map", leaky_map
    )
    with pytest.raises(SpineError, match="GATE 4 FAILED"):
        gates_module.gate_roll_causality(exploration_5m, exploration_5m.manifest)


def test_negative_case_gate_4_catches_an_inert_fixture(exploration_5m, monkeypatch):
    """A selector that ignores volume entirely makes the fixture inert; the gate's
    self-check must refuse to certify causality on evidence that cannot discriminate."""
    from mnq_lab.spine import gates as gates_module
    from mnq_lab.spine.rolls import RollMap

    def constant_map(daily_volume, first_year_by_symbol):
        sessions = sorted({trade_date for trade_date, _ in daily_volume})
        return RollMap(
            active={trade_date: "MNQM1" for trade_date in sessions},
            rolls=[],
            expiries={},
        )

    monkeypatch.setattr(
        gates_module, "build_causal_active_contract_map", constant_map
    )
    with pytest.raises(SpineError, match="fixture inert"):
        gates_module.gate_roll_causality(exploration_5m, exploration_5m.manifest)


def test_negative_case_gate_3_catches_a_false_distinct_count(exploration_5m):
    """Audit M1's exact attack: distinct_symbol_count = 999 previously passed."""
    from mnq_lab.spine.gates import gate_symbol_classification

    manifest = json_roundtrip(exploration_5m.manifest)
    manifest["symbol_classification"]["distinct_symbol_count"] = 999
    with pytest.raises(SpineError, match="distinct_symbol_count is 999"):
        gate_symbol_classification(manifest)


def test_negative_case_gate_3_catches_row_totals_disagreeing_with_the_lists(
    exploration_5m,
):
    """Audit M1: per-symbol lists must sum to the recorded row totals."""
    from mnq_lab.spine.gates import gate_symbol_classification

    manifest = json_roundtrip(exploration_5m.manifest)
    block = manifest["symbol_classification"]
    first_symbol = next(iter(block["retained_symbols"]))
    block["retained_symbols"][first_symbol] += 1  # lists no longer sum to the total
    with pytest.raises(SpineError, match="per-symbol counts sum"):
        gate_symbol_classification(manifest)


def test_gate_3_report_confirms_source_verification_ran(gate_report):
    """The CLI runner must verify per-symbol counts against the source, not lists only."""
    assert gate_report["gates"][2]["per_symbol_counts_verified_against_source"] is True


def test_negative_case_gate_3_catches_per_symbol_counts_altered_with_same_total(
    exploration_5m,
):
    """Audit M1's residual attack: shift counts between symbols, preserving every
    aggregate. List-consistency passes by construction; only the source rescan can
    catch it — so it must."""
    from pathlib import Path

    from mnq_lab.spine.gates import gate_symbol_classification

    manifest = json_roundtrip(exploration_5m.manifest)
    block = manifest["symbol_classification"]
    symbols = list(block["retained_symbols"])
    block["retained_symbols"][symbols[0]] += 7
    block["retained_symbols"][symbols[1]] -= 7

    # Sanity: the manifest-only checks cannot see this (documented limitation)...
    assert gate_symbol_classification(manifest)["status"] == "pass"
    # ...and the source rescan does.
    source = Path(manifest["source"]["path"])
    with pytest.raises(SpineError, match="per-symbol counts disagree with the source"):
        gate_symbol_classification(manifest, source)


def test_negative_case_gate_3_fails_when_the_source_is_absent(exploration_5m, tmp_path):
    """An unverifiable gate does not pass (spec §16.4.3)."""
    from mnq_lab.spine.gates import gate_symbol_classification

    manifest = json_roundtrip(exploration_5m.manifest)
    with pytest.raises(SpineError, match="cannot be verified"):
        gate_symbol_classification(manifest, tmp_path / "gone.csv")


def _tiny_source_and_manifest(tmp_path, recorded_sha):
    """A minimal source CSV plus a manifest whose counts match it exactly."""
    source = tmp_path / "tiny.csv"
    source.write_text(
        "symbol\nMNQH0\nMNQH0\nMNQH0-MNQM0\n", encoding="utf-8", newline=""
    )
    manifest = {
        "symbol_classification": {
            "retained_symbols": {"MNQH0": 2},
            "rejected_spread_symbols": {"MNQH0-MNQM0": 1},
            "retained_symbol_count": 1,
            "rejected_spread_symbol_count": 1,
            "distinct_symbol_count": 2,
            "retained_rows": 2,
            "rejected_spread_rows": 1,
        },
        "source": {"rows": 3, "sha256": recorded_sha},
    }
    return source, manifest


def test_negative_case_gate_3_rejects_a_count_equivalent_source_forgery(tmp_path):
    """Re-audit L2's exact attack: a hash-different file reproducing every recorded
    count must not earn source_verified. Count agreement with an unauthenticated file
    verifies nothing."""
    from mnq_lab.spine.gates import gate_symbol_classification

    source, manifest = _tiny_source_and_manifest(tmp_path, recorded_sha="0" * 64)
    with pytest.raises(SpineError, match="sha256.*not the file"):
        gate_symbol_classification(manifest, source)


def test_gate_3_authenticated_source_passes_with_both_flags(tmp_path):
    """Positive control: correct hash + correct counts -> both verifications recorded."""
    from mnq_lab.spine.gates import gate_symbol_classification
    from mnq_lab.spine.vendored import sha256_file

    source, manifest = _tiny_source_and_manifest(tmp_path, recorded_sha="")
    manifest["source"]["sha256"] = sha256_file(source)
    report = gate_symbol_classification(manifest, source)
    assert report["source_sha256_verified"] is True
    assert report["per_symbol_counts_verified_against_source"] is True


def test_gate_3_hash_check_precedes_count_comparison(tmp_path):
    """A wrong hash must fail even when counts would also disagree — source revision
    is the diagnosis, not count drift (gate-diagnosis skill: check the sha first)."""
    from mnq_lab.spine.gates import gate_symbol_classification

    source, manifest = _tiny_source_and_manifest(tmp_path, recorded_sha="0" * 64)
    manifest["symbol_classification"]["retained_symbols"]["MNQH0"] = 99
    manifest["symbol_classification"]["retained_rows"] = 99
    manifest["source"]["rows"] = 100
    with pytest.raises(SpineError, match="sha256"):
        gate_symbol_classification(manifest, source)


def json_roundtrip(manifest):
    """Deep copy via JSON so mutations cannot leak into the mmap'd manifest."""
    import json

    return json.loads(json.dumps(manifest))


def test_negative_case_gate_4_detects_an_intrasession_contract_change(exploration_5m):
    """Plant a second contract inside one session; the gate must halt."""

    class _Tampered:
        def __init__(self, store):
            self._store = store
            codes = np.asarray(store["symbol_code"]).copy()
            codes[len(codes) // 2] = codes[len(codes) // 2] + 1
            self._codes = codes

        def __getitem__(self, name):
            return self._codes if name == "symbol_code" else self._store[name]

    with pytest.raises(SpineError, match="GATE 4 FAILED"):
        gate_roll_causality(_Tampered(exploration_5m), exploration_5m.manifest)


def test_negative_case_gate_4_detects_a_same_session_effective_roll(exploration_5m):
    """A roll effective on its own trigger session must halt."""
    manifest = dict(exploration_5m.manifest)
    rolls = [dict(roll) for roll in manifest["rolls"]]
    rolls[0]["effective_trade_date"] = rolls[0]["trigger_trade_date"]
    manifest["rolls"] = rolls

    with pytest.raises(SpineError, match="not strictly after its trigger"):
        gate_roll_causality(exploration_5m, manifest)


def test_gates_verify_store_hashes_before_comparing(gate_report):
    """run_all_gates calls verify_hashes; a tampered store cannot reach a comparison."""
    from mnq_lab.spine.seal import Corpus, store_path
    from mnq_lab.spine.store import BarStore

    BarStore.open(store_path(STORE_ROOT, Corpus.EXPLORATION, "5m")).verify_hashes()
    BarStore.open(store_path(STORE_ROOT, Corpus.LOCKED_CONFIRMATION, "5m")).verify_hashes()
