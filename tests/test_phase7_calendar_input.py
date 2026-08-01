"""Acceptance gate for the immutable Phase 7 CME equity-index calendar input.

This module validates a reference input only.  It contains no conditioner,
seasonal-profile, threshold, assignment, or other Phase 7 production logic.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import pkgutil
import subprocess
import sys
from collections import Counter
from copy import deepcopy
from datetime import date, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from mnq_lab import SpineError
from mnq_lab.ledger.calendar_entries.validator import (
    load_calendar_entry,
    validate_calendar_entry_artifacts,
)


REPO = Path(__file__).resolve().parents[1]
INPUT = REPO / "mnq_lab/spine/calendar_inputs/cme_equity_index_v1"
TABLE = INPUT / "cme_equity_index_sessions_20190506_20230329_v1.json"
MANIFEST = INPUT / "cme_equity_index_sessions_20190506_20230329_v1.manifest.json"
ACCEPTANCE = INPUT / "cme_equity_index_sessions_20190506_20230329_v1.acceptance.json"
RAW = INPUT / "raw_source_provenance"
INDEX = RAW / "pandas_market_calendars_v5.4.0.source_index.json"
LOCK = RAW / "extraction_environment.lock.json"
TOOL = REPO / "tools/build_phase7_calendar_v1.py"
STORE = REPO / "data/exploration/bars_5m"
CT = ZoneInfo("America/Chicago")

EXPECTED_ARTIFACTS = {
    TABLE: (447_577, "b86e112c16112bf11a6a548ca8b3f21d28a08f90442b4dde84098f9d3f6eb069"),
    MANIFEST: (5_844, "bdd923a534152ef88bd9db874e60e08c757b85dae729b397ae78351a3e3d7a1d"),
    ACCEPTANCE: (24_039, "f63e58854e4c5427271140be4452ebb7169a39f665927641f0b63bea3d0df64d"),
    TOOL: (39_158, "937abff993d3e5a5d43282ae12b895ca0e1a99328082e1438687f6972a306db6"),
    REPO / "docs/DISCREPANCIES.md": (
        49_015,
        "68325d575bd5a480fa23c11cc22dc5b1b1ecfbd0f7714cca007721e8f63df1c7",
    ),
}
EXPECTED_COLUMNS = [
    "trade_date",
    "market",
    "session_class",
    "scheduled_rth_status",
    "scheduled_rth_open_ct",
    "scheduled_rth_close_ct",
    "raw_exchange_open_ct",
    "raw_exchange_close_ct",
    "holiday_adjacent",
    "source_event_id",
    "source_label",
    "source_as_of",
    "calendar_version",
    "schema_version",
]
KNOWN_DISCREPANCIES = {20200228: "10:00", 20200630: "09:15"}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical(value) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()


def _document() -> dict:
    return json.loads(TABLE.read_text(encoding="utf-8"))


def _rows() -> list[dict]:
    document = _document()
    return [dict(zip(document["columns"], values, strict=True)) for values in document["rows"]]


def _load_tool():
    name = "_mnq_phase7_calendar_builder_test"
    spec = importlib.util.spec_from_file_location(name, TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


def _observed_sessions() -> dict[int, tuple[str, str | None]]:
    store_manifest = json.loads((STORE / "manifest.json").read_text(encoding="utf-8"))
    assert store_manifest["corpus"] == "exploration"
    assert store_manifest["frequency"] == "5m"
    assert store_manifest["bar_seconds"] == 300
    assert store_manifest["row_count"] == 274_847
    for column in ("session_id", "ts_event_ns"):
        record = store_manifest["columns"][column]
        assert _sha256(STORE / record["file"]) == record["sha256"]

    session_ids = np.load(STORE / "session_id.npy", mmap_mode="r")
    timestamps = np.load(STORE / "ts_event_ns.npy", mmap_mode="r")
    assert session_ids.dtype == np.dtype("int32")
    assert timestamps.dtype == np.dtype("int64")
    assert session_ids.shape == timestamps.shape == (274_847,)
    assert np.all(timestamps[1:] > timestamps[:-1])

    in_scope = (session_ids >= 20190506) & (session_ids <= 20230329)
    scoped_ids = np.asarray(session_ids[in_scope], dtype=np.int32)
    scoped_ts = np.asarray(timestamps[in_scope], dtype=np.int64)
    ends = pd.to_datetime(scoped_ts + 300_000_000_000, unit="ns", utc=True).tz_convert(CT)
    observed: dict[int, tuple[str, str | None]] = {}
    for session_id in np.unique(scoped_ids):
        session_ends = ends[scoped_ids == session_id]
        rth = session_ends[
            (session_ends.time >= time(8, 30)) & (session_ends.time <= time(15, 0))
        ]
        observed[int(session_id)] = (
            session_ends[-1].strftime("%H:%M"),
            None if len(rth) == 0 else rth[-1].strftime("%H:%M"),
        )
    return observed


def test_calendar_ledger_precedes_and_binds_committed_artifacts():
    entry = validate_calendar_entry_artifacts()
    assert entry == load_calendar_entry()
    assert entry["phase7_production_authorized"] is False
    assert entry["no_affected_result_has_run"] is True
    assert entry["source_provenance"]["complete_python_file_count"] == 47

    base = "4100abadad1d8212b8c98ad7382e1019a1afbe96"
    ledger_commit = "b5377a3"
    artifact_commit = "f0bde87"
    for older, newer in ((base, ledger_commit), (ledger_commit, artifact_commit)):
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", older, newer],
            cwd=REPO,
            check=False,
        )
        assert result.returncode == 0, f"required commit order failed: {older} -> {newer}"


def test_calendar_artifact_hashes_and_json_are_canonical():
    for path, (expected_bytes, expected_hash) in EXPECTED_ARTIFACTS.items():
        payload = path.read_bytes()
        assert len(payload) == expected_bytes, path
        assert _sha256_bytes(payload) == expected_hash, path
    for path in (TABLE, MANIFEST, ACCEPTANCE, INDEX, LOCK):
        payload = path.read_bytes()
        assert payload == _canonical(json.loads(payload.decode("utf-8"))), path


def test_calendar_table_schema_support_and_total_mapping():
    document = _document()
    assert list(document) == ["calendar_version", "columns", "rows", "schema_version"]
    assert document["columns"] == EXPECTED_COLUMNS
    rows = _rows()
    assert len(rows) == 1018
    dates = [row["trade_date"] for row in rows]
    expected_dates = []
    cursor = date(2019, 5, 5)
    while cursor <= date(2023, 3, 29):
        if cursor.weekday() < 5:
            expected_dates.append(int(cursor.strftime("%Y%m%d")))
        cursor += timedelta(days=1)
    assert dates == expected_dates
    assert len(set(dates)) == len(dates)
    assert all(type(row["trade_date"]) is int for row in rows)
    assert all(type(row["holiday_adjacent"]) is bool for row in rows)
    assert all(type(row[field]) is str for row in rows for field in EXPECTED_COLUMNS if field not in {"trade_date", "holiday_adjacent"})
    assert Counter(row["session_class"] for row in rows) == {
        "regular": 976,
        "scheduled_early_close": 33,
        "full_exchange_holiday": 9,
    }
    assert Counter(row["scheduled_rth_status"] for row in rows) == {
        "full_rth": 976,
        "shortened_rth": 32,
        "no_scheduled_rth": 1,
        "full_exchange_holiday": 9,
    }
    tool = _load_tool()
    tool.validate_table(deepcopy(rows))
    assert tool.map_rth("scheduled_early_close", "15:30") == ("full_rth", "08:30", "15:00")


def test_holiday_adjacent_is_independently_reconstructed():
    rows = _rows()
    active = [i for i, row in enumerate(rows) if row["session_class"] != "full_exchange_holiday"]
    expected: set[int] = set()
    for index, row in enumerate(rows):
        if row["session_class"] not in {"full_exchange_holiday", "scheduled_early_close"}:
            continue
        before = [candidate for candidate in active if candidate < index]
        after = [candidate for candidate in active if candidate > index]
        if before:
            expected.add(before[-1])
        if after:
            expected.add(after[0])
    actual = {i for i, row in enumerate(rows) if row["holiday_adjacent"]}
    assert actual == expected
    assert len(actual) == 82
    assert not any(rows[i]["session_class"] == "full_exchange_holiday" for i in actual)


def test_a3_a6_observational_partition_is_complete_and_disjoint():
    rows = _rows()
    observed = _observed_sessions()
    regular_matches: set[int] = set()
    timed_early: set[int] = set()
    structural: set[int] = set()
    closures: set[int] = set()
    discrepancies: set[int] = set()
    for row in rows:
        trade_date = row["trade_date"]
        actual = observed.get(trade_date)
        if row["session_class"] == "regular":
            assert actual is not None
            if actual[0] == "16:00":
                regular_matches.add(trade_date)
            else:
                assert KNOWN_DISCREPANCIES.get(trade_date) == actual[0]
                discrepancies.add(trade_date)
        elif row["session_class"] == "scheduled_early_close":
            assert actual is not None
            assert actual[0] == row["raw_exchange_close_ct"]
            if row["scheduled_rth_status"] == "no_scheduled_rth":
                assert actual[1] is None
                structural.add(trade_date)
            else:
                assert actual[1] == row["scheduled_rth_close_ct"]
                timed_early.add(trade_date)
        elif row["session_class"] == "full_exchange_holiday":
            assert actual is None
            closures.add(trade_date)
        else:
            pytest.fail(f"unmapped session class {row['session_class']}")
    groups = [regular_matches, timed_early, structural, closures, discrepancies]
    assert [len(group) for group in groups] == [974, 32, 1, 9, 2]
    assert set.union(*groups) == {row["trade_date"] for row in rows}
    assert sum(map(len, groups)) == len(set.union(*groups)) == 1018
    assert discrepancies == set(KNOWN_DISCREPANCIES)
    assert structural == {20210402}
    assert len(observed) == 1009


def test_a3_a6_mutations_are_killed_for_the_intended_reason():
    tool = _load_tool()
    rows = _rows()
    observed_raw = _observed_sessions()
    observed = {
        key: tool.ObservedSession(key, final, rth)
        for key, (final, rth) in observed_raw.items()
    }
    tool.validate_against_observations(rows, observed)
    results = tool.execute_negative_battery(rows, observed)
    names = {result["mutation"]: result["status"] for result in results}
    assert names == {
        "a2_missing_date": "killed",
        "a3a_regular_final_end_1555": "killed",
        "a3a_early_close_1215_to_1200": "killed",
        "a3b_remove_registered_discrepancy": "killed",
        "a6_false_full_closure": "killed",
        "a7_raw_regular_close_1500": "killed",
        "a7_raw_regular_close_1700": "killed",
        "a7_early_close_at_1600": "killed",
        "a7_unknown_class": "killed",
        "a7_early_close_1530_total_mapping": "classified",
        "a7_wrong_timezone": "killed",
        "a7_wrong_raw_open": "killed",
        "a7_same_day_open": "killed",
        "a7_non_equity_product": "killed",
        "a7_generic_calendar": "killed",
    }


def test_a1_complete_source_tree_is_hash_bound_and_inert():
    index_raw = INDEX.read_bytes()
    assert len(index_raw) == 18_370
    assert _sha256_bytes(index_raw) == "bc6934832e2a9934bf485504ad844ed64948d83292c88a012cef9cef493a92a6"
    index = json.loads(index_raw)
    assert index["complete_package_python_file_count"] == 47
    assert index["stored_files_are_inert"] is True
    assert index["stored_suffix"] == ".py.txt"
    records = index["files"]
    assert len(records) == 47
    assert [record["original_path"] for record in records] == sorted(record["original_path"] for record in records)
    material = b""
    for record in records:
        path = INPUT / record["stored_path"]
        payload = path.read_bytes()
        assert len(payload) == record["bytes"]
        assert _sha256_bytes(payload) == record["sha256"]
        assert path.name.endswith(".py.txt")
        assert not path.name.startswith("test_")
        material += f"{record['original_path']}\0{record['bytes']}\0{record['sha256']}\n".encode()
    assert _sha256_bytes(material) == index["tree_sha256"]
    assert index["tree_sha256"] == "253ca03bc5ba4956a930d47d167843469c4440a0514961599cc3ee0d376890ee"
    assert not list(RAW.rglob("*.py"))
    assert not list(RAW.rglob("test_*.py"))

    corrupted = bytearray((INPUT / records[0]["stored_path"]).read_bytes())
    corrupted.append(0)
    assert len(corrupted) != records[0]["bytes"]
    assert _sha256_bytes(corrupted) != records[0]["sha256"]


def test_retained_tree_has_no_importable_or_collectable_modules():
    assert list(pkgutil.walk_packages([str(INPUT)])) == []
    module_name = (
        "mnq_lab.spine.calendar_inputs.cme_equity_index_v1.raw_source_provenance."
        "pandas_market_calendars.calendars.cme_globex_equities"
    )
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module_name)
    discovery_names = {path.name for path in RAW.rglob("*") if path.is_file() and (path.name.startswith("test_") or path.name.endswith("_test.py"))}
    assert discovery_names == set()


def test_source_identity_dependency_lock_and_phase3_ledger_are_preserved():
    assert (RAW / "git_HEAD.txt").read_text(encoding="utf-8").strip() == "275890784073a3a3a347e4f05f4dc986456e6a75"
    packed_refs = (RAW / "git_packed_refs.txt").read_text(encoding="utf-8")
    assert "275890784073a3a3a347e4f05f4dc986456e6a75 refs/tags/v5.4.0" in packed_refs
    pyproject = (RAW / "pyproject.toml.txt").read_text(encoding="utf-8")
    assert 'name = "pandas_market_calendars"' in pyproject
    assert 'version = "5.4.0"' in pyproject
    assert 'license = { text = "MIT" }' in pyproject
    lock_raw = LOCK.read_bytes()
    assert len(lock_raw) == 1_064
    assert _sha256_bytes(lock_raw) == "68707c623e0a89df75474eba00de587ac5462dd666c9ce138e327166875d3676"
    lock = json.loads(lock_raw)
    assert lock["pandas_market_calendars"] == "5.4.0"
    assert lock["numpy"] == "2.5.1" and lock["pandas"] == "3.0.5"

    phase3_entries = list((REPO / "mnq_lab/ledger/entries").glob("*.json"))
    assert len(phase3_entries) == 1
    assert phase3_entries[0].name == "2026-07-28-phase3-s00-completion-thresholds.json"
    assert _sha256(phase3_entries[0]) == "55c313c55f791c4744108891d8889f7b17ccd94233408d550d948c45e6696558"


def test_builder_import_is_side_effect_free_without_extraction_dependency(tmp_path, monkeypatch):
    before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}
    assert "pandas_market_calendars" not in sys.modules
    monkeypatch.chdir(tmp_path)
    module = _load_tool()
    assert "pandas_market_calendars" not in sys.modules
    assert module.np is None and module.pd is None
    assert not hasattr(module, "mcal")
    assert {path.relative_to(tmp_path) for path in tmp_path.rglob("*")} == before


@pytest.mark.parametrize(
    ("session_class", "raw_close", "message"),
    [
        ("regular", "15:00", "regular raw exchange close"),
        ("regular", "17:00", "regular raw exchange close"),
        ("scheduled_early_close", "16:00", "inconsistent"),
        ("cash_equity", "16:00", "unmapped session class"),
    ],
)
def test_a7_rth_mapping_mutations_fail_narrowly(session_class, raw_close, message):
    tool = _load_tool()
    with pytest.raises(tool.CandidateError, match=message):
        tool.map_rth(session_class, raw_close)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("timezone", "America/New_York", "timezone"),
        ("raw_open", "18:00", "raw exchange open"),
        ("open_on_prior_calendar_day", False, "prior calendar day"),
        ("market", "CME_GLOBEX_INTEREST_RATE_FUTURES", "product group"),
        ("calendar_name", "CME Globex", "CME Globex Equities"),
    ],
)
def test_a7_source_mechanics_mutations_fail_narrowly(field, value, message):
    tool = _load_tool()
    arguments = {
        "calendar_name": "CME Globex Equities",
        "timezone": "America/Chicago",
        "market": "CME_GLOBEX_EQUITY_INDEX_FUTURES",
        "raw_open": "17:00",
        "raw_close": "16:00",
        "open_on_prior_calendar_day": True,
        "session_class": "regular",
    }
    arguments[field] = value
    with pytest.raises(tool.CandidateError, match=message):
        tool.validate_source_mechanics(**arguments)


def test_negative_calendar_ledger_hash_mutation_fails(tmp_path):
    entry = deepcopy(load_calendar_entry())
    entry["canonical_table"]["sha256"] = "0" * 64
    with pytest.raises(SpineError, match="SHA-256 differs"):
        validate_calendar_entry_artifacts(entry)


@pytest.mark.xfail(
    strict=True,
    reason="U11 A5: mandatory calendar import-isolation gate awaits real Phase 7 scale modules",
)
def test_a5_calendar_import_isolation():
    """Must become a discriminating passing test when dependent modules exist."""
    pytest.fail("a5_calendar_import_isolation is pending; removal without conversion is forbidden")
