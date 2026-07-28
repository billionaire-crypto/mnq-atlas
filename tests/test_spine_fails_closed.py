"""Every declared failure mode halts the build (spec §13 test 18, §16.4.3).

    "Fail closed. Every gate in §5.1 halts the build. Do not add a fallback path, do not
    'handle' the discrepancy, do not proceed with a warning."

Each test here pairs a poisoned input with a positive control on the same code path, so
"it raised" is never confused with "it raises on everything".
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.constants import load_constants, load_spine_constants
from mnq_lab.core.units import to_quanta
from mnq_lab.spine.gates import gate_five_minute_equality, gate_roll_list_equality
from mnq_lab.spine.source import scan_source
from tests.conftest import SourceBuilder, session_grid

TIMES = ["17:00", "08:30", "15:55"]
SESSIONS = ["2021-06-08", "2021-06-09", "2021-06-10"]


def _clean_source(path: Path) -> Path:
    builder = SourceBuilder()
    for trade_date in SESSIONS:
        builder.add_minutes(
            session_grid(trade_date, TIMES), "MNQM1", volume=100, open_=12_000.0
        )
    return builder.write(path)


def _poison(path: Path, find: str, replace: str) -> Path:
    text = path.read_text(encoding="utf-8")
    assert find in text, f"fixture does not contain {find!r}; the poison would be inert"
    path.write_text(text.replace(find, replace, 1), encoding="utf-8")
    return path


# --- positive control ---------------------------------------------------------------

def test_a_clean_source_scans_without_error(tmp_path):
    """The control. Without it, every assertion below could pass on broken plumbing."""
    result = scan_source(_clean_source(tmp_path / "clean.csv"), 10_000, verbose=False)
    assert result.report["source_rows"] == len(SESSIONS) * len(TIMES)
    assert result.classification.retained_symbol_count == 1


# --- source validation --------------------------------------------------------------

def test_negative_volume_halts(tmp_path):
    path = _poison(_clean_source(tmp_path / "s.csv"), ",100,MNQM1", ",-5,MNQM1")
    with pytest.raises(SpineError, match="negative volume"):
        scan_source(path, 10_000, verbose=False)


def test_ohlc_invariant_violation_halts(tmp_path):
    # high below open
    path = _poison(
        _clean_source(tmp_path / "s.csv"),
        "12000.000000000,12001.000000000",
        "12000.000000000,11000.000000000",
    )
    with pytest.raises(SpineError, match="OHLC invariant"):
        scan_source(path, 10_000, verbose=False)


def test_null_value_halts(tmp_path):
    path = _poison(_clean_source(tmp_path / "s.csv"), "12000.000000000,", ",")
    with pytest.raises(SpineError, match="null source values|OHLC invariant"):
        scan_source(path, 10_000, verbose=False)


def test_backward_timestamps_halt(tmp_path):
    path = _clean_source(tmp_path / "s.csv")
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[1], lines[-1] = lines[-1], lines[1]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(SpineError, match="moves backward"):
        scan_source(path, 10_000, verbose=False)


def test_unclassifiable_symbol_halts(tmp_path):
    path = _poison(_clean_source(tmp_path / "s.csv"), "MNQM1", "ESM1")
    with pytest.raises(SpineError, match="match neither"):
        scan_source(path, 10_000, verbose=False)


def test_missing_source_halts(tmp_path):
    with pytest.raises(SpineError, match="source CSV not found"):
        scan_source(tmp_path / "absent.csv", 10_000, verbose=False)


def test_wrong_schema_halts(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    with pytest.raises(SpineError, match="source schema"):
        scan_source(path, 10_000, verbose=False)


# --- tick exactness -----------------------------------------------------------------

def test_price_off_the_tick_grid_halts():
    """A price that is not a multiple of 0.25 must halt, never round."""
    with pytest.raises(SpineError, match="not an exact multiple"):
        to_quanta(np.array([12_000.0, 12_000.10]), 0.25, name="close")


def test_tick_conversion_accepts_exact_prices():
    np.testing.assert_array_equal(
        to_quanta(np.array([12_000.0, 12_000.25, -1.5]), 0.25), [48_000, 48_001, -6]
    )


def test_non_finite_price_halts():
    with pytest.raises(SpineError, match="non-finite"):
        to_quanta(np.array([12_000.0, np.nan]), 0.25)


def test_out_of_int32_range_halts():
    with pytest.raises(SpineError, match="outside int32"):
        to_quanta(np.array([1e12]), 0.25)


# --- constants ----------------------------------------------------------------------

def test_missing_constants_file_halts(tmp_path):
    with pytest.raises(SpineError, match="refuses to run without it"):
        load_spine_constants(tmp_path / "absent.yaml")


def test_absent_constant_halts_with_no_default(tmp_path):
    path = tmp_path / "partial.yaml"
    path.write_text("time:\n  tick_size: 0.25\n", encoding="utf-8")
    constants = load_constants(path)
    assert constants.get("time", "tick_size") == 0.25
    with pytest.raises(SpineError, match="no default is permitted"):
        constants.get("time", "rth_start_ct")


def _yaml_with(session_tz="America/Chicago", break_ct="['16:00','17:00']", bar_label="open"):
    return (
        "spec_version: 6\nprogram_id: x\nhorizons_minutes: [15]\n"
        "time:\n  storage_tz: UTC\n"
        f"  session_tz: {session_tz}\n"
        f"  bar_label: {bar_label}\n  tick_size: 0.25\n  rth_start_ct: '08:30'\n"
        f"  rth_end_ct: '15:00'\n  maintenance_break_ct: {break_ct}\n"
    )


def test_yaml_session_tz_divergence_halts(tmp_path):
    """Audit M2: the vendored runtime implements America/Chicago; a YAML declaring a
    different session timezone must refuse to build, not build under one rule while
    the manifest documents another."""
    path = tmp_path / "london.yaml"
    path.write_text(_yaml_with(session_tz="Europe/London"), encoding="utf-8")
    with pytest.raises(SpineError, match="vendored session runtime"):
        load_spine_constants(path)


def test_yaml_maintenance_break_divergence_halts(tmp_path):
    """Audit M2, second half: the mask hardcodes [16:00, 17:00) CT."""
    path = tmp_path / "shifted.yaml"
    path.write_text(_yaml_with(break_ct="['15:00','16:00']"), encoding="utf-8")
    with pytest.raises(SpineError, match="vendored session mask"):
        load_spine_constants(path)


def test_yaml_matching_the_vendored_rules_loads(tmp_path):
    """Positive control for the two checks above."""
    path = tmp_path / "good.yaml"
    path.write_text(_yaml_with(), encoding="utf-8")
    constants = load_spine_constants(path)
    assert constants.session_tz == "America/Chicago"
    assert constants.maintenance_break_ct == ("16:00", "17:00")


def test_missing_real_store_fails_rather_than_skips(tmp_path, monkeypatch):
    """Audit H2: a clean checkout must not get a green suite with the gates unrun."""
    import tests.conftest as conftest_module
    from mnq_lab.spine.seal import Corpus

    monkeypatch.setattr(conftest_module, "REAL_STORE_ROOT", tmp_path / "no_data")
    with pytest.raises(pytest.fail.Exception, match="fail closed rather than skip"):
        conftest_module._require_real_store(Corpus.EXPLORATION, "5m")


def test_wrong_bar_label_halts(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        "spec_version: 6\nprogram_id: x\nhorizons_minutes: [15]\n"
        "time:\n  storage_tz: UTC\n  session_tz: America/Chicago\n"
        "  bar_label: close\n  tick_size: 0.25\n  rth_start_ct: '08:30'\n"
        "  rth_end_ct: '15:00'\n  maintenance_break_ct: ['16:00','17:00']\n",
        encoding="utf-8",
    )
    with pytest.raises(SpineError, match="bar OPEN"):
        load_spine_constants(path)


# --- gates --------------------------------------------------------------------------

def _fixture_rolls():
    from mnq_lab.spine.gates import ROLL_FIXTURE_PATH

    return json.loads(ROLL_FIXTURE_PATH.read_text(encoding="utf-8"))["rolls"]


def test_gate_1_passes_on_the_fixture_itself():
    assert gate_roll_list_equality(_fixture_rolls())["roll_count"] == 28


def test_gate_1_halts_on_a_missing_roll():
    with pytest.raises(SpineError, match="GATE 1 FAILED"):
        gate_roll_list_equality(_fixture_rolls()[:-1])


def test_gate_1_halts_on_a_changed_field():
    rolls = [dict(roll) for roll in _fixture_rolls()]
    rolls[5]["effective_trade_date"] = "1999-01-01"
    with pytest.raises(SpineError, match="GATE 1 FAILED at roll 5"):
        gate_roll_list_equality(rolls)


def test_gate_1_halts_on_a_reordered_list():
    rolls = [dict(roll) for roll in _fixture_rolls()]
    rolls[0], rolls[1] = rolls[1], rolls[0]
    with pytest.raises(SpineError, match="GATE 1 FAILED"):
        gate_roll_list_equality(rolls)


def test_gate_1_halts_when_the_fixture_is_absent(tmp_path):
    """A missing oracle must halt, never silently pass."""
    with pytest.raises(SpineError, match="cannot be skipped"):
        gate_roll_list_equality(_fixture_rolls(), tmp_path / "absent.json")


def test_gate_2_halts_when_the_reference_is_absent(locked_5m, tmp_path):
    with pytest.raises(SpineError, match="cannot be skipped"):
        gate_five_minute_equality(locked_5m, tmp_path / "absent.csv")


def test_gate_2_halts_on_a_truncated_reference(locked_5m, tmp_path):
    """Row-count drift must be caught before any value comparison."""
    from mnq_lab.spine.gates import REFERENCE_5M_CSV

    lines = REFERENCE_5M_CSV.read_text(encoding="utf-8").splitlines()
    truncated = tmp_path / "short.csv"
    truncated.write_text("\n".join(lines[:-10]) + "\n", encoding="utf-8")
    with pytest.raises(SpineError, match="GATE 2 FAILED.*rows"):
        gate_five_minute_equality(locked_5m, truncated)


def test_gate_2_halts_on_a_single_altered_price(locked_5m, tmp_path):
    """One changed tick anywhere in 211,968 rows must fail the gate."""
    from mnq_lab.spine.gates import REFERENCE_5M_CSV

    lines = REFERENCE_5M_CSV.read_text(encoding="utf-8").splitlines()
    middle = len(lines) // 2
    fields = lines[middle].split(",")
    fields[1] = f"{float(fields[1]) + 0.25:.2f}"  # shift open by exactly one tick
    lines[middle] = ",".join(fields)
    altered = tmp_path / "altered.csv"
    altered.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(SpineError, match="GATE 2 FAILED: column 'open_ticks'"):
        gate_five_minute_equality(locked_5m, altered)


def test_gate_2_passes_on_the_real_reference(locked_5m):
    report = gate_five_minute_equality(locked_5m)
    assert report["rows_compared"] == 211_968
