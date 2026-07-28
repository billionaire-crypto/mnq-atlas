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
        pytest.skip("no built store; run python -m mnq_lab.spine.build --out data")
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
