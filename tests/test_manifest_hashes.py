"""The manifest records everything Phase 1 requires, and its hashes are live.

Deliverable 5: build id, source sha256, per-column sha256, row counts, dtypes, tick
size, timezone rules, session rules, roll list, exact retained-symbol count, exact
rejected-spread-symbol count, environment fingerprint.

The manifest carries no wall-clock timestamp, so two builds from the same source in the
same environment produce identical bytes (spec §13 test 17: artifact determinism when
the fingerprint matches).
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.constants import CONSTANTS_PATH, SPEC_PATH
from mnq_lab.spine.store import BarStore, write_store
from mnq_lab.spine.vendored import sha256_file

REQUIRED_TOP_LEVEL = [
    "build_id",
    "pipeline_version",
    "corpus",
    "frequency",
    "source",
    "frozen_files",
    "tick_size",
    "timezone_rules",
    "session_rules",
    "rolls",
    "roll_count",
    "symbol_classification",
    "symbols",
    "row_count",
    "columns",
    "environment",
]


@pytest.mark.parametrize("key", REQUIRED_TOP_LEVEL)
def test_manifest_carries_required_field(exploration_5m, key):
    assert key in exploration_5m.manifest, f"manifest is missing {key!r}"


def test_source_hash_is_recorded_and_correct(exploration_5m):
    source = exploration_5m.manifest["source"]
    assert len(source["sha256"]) == 64
    assert source["rows"] == 3_665_228
    # The vendor's own manifest independently records the same digest.
    assert source["sha256"] == (
        "7af016ba7a2fda53d6663b22991ed628386f011eecff6c4e8ba1e9f5ccbab834"
    )


def test_frozen_file_hashes_match_the_files_on_disk(exploration_5m):
    frozen = exploration_5m.manifest["frozen_files"]
    assert frozen["REV6_FROZEN_SPEC.md"] == sha256_file(SPEC_PATH)
    assert frozen["analysis_constants_v1.yaml"] == sha256_file(CONSTANTS_PATH)


def test_every_column_has_a_dtype_row_count_and_live_hash(exploration_5m):
    for name, spec in exploration_5m.manifest["columns"].items():
        assert spec["dtype"], name
        assert spec["rows"] == exploration_5m.manifest["row_count"], name
        assert len(spec["sha256"]) == 64, name
        assert sha256_file(exploration_5m.root / spec["file"]) == spec["sha256"], name


def test_tick_and_timezone_and_session_rules_are_recorded(exploration_5m):
    manifest = exploration_5m.manifest
    assert manifest["tick_size"] == 0.25
    assert manifest["timezone_rules"]["storage_tz"] == "UTC"
    assert manifest["timezone_rules"]["storage_unit"] == "UTC nanoseconds"
    assert manifest["timezone_rules"]["session_tz"] == "America/Chicago"
    assert manifest["timezone_rules"]["bar_label"] == "open"
    assert manifest["session_rules"]["maintenance_break_ct"] == ["16:00", "17:00"]
    assert manifest["session_rules"]["rth_ct"] == ["08:30", "15:00"]
    assert manifest["session_rules"]["globex_session"] == "17:00 CT -> 16:00 CT next day"


def test_roll_list_and_exact_symbol_counts_are_recorded(exploration_5m):
    manifest = exploration_5m.manifest
    assert manifest["roll_count"] == 28
    assert len(manifest["rolls"]) == 28
    classification = manifest["symbol_classification"]
    assert classification["retained_symbol_count"] == 32
    assert classification["rejected_spread_symbol_count"] == 55


def test_environment_fingerprint_is_recorded(exploration_5m):
    environment = exploration_5m.manifest["environment"]
    for key in ("python", "numpy", "pandas", "platform", "pipeline_version", "vcs"):
        assert key in environment, key
    # D1: the spec says to record vcs "none"; this workspace is a real git repo.
    assert environment["vcs"] == "git"
    assert len(environment["commit"]) == 40


def test_manifest_has_no_wall_clock_time(exploration_5m):
    """A build timestamp would break artifact determinism on every rebuild."""
    blob = json.dumps(exploration_5m.manifest).lower()
    for token in ("built_at", "build_time", "generated_at", "timestamp_utc"):
        assert token not in blob, f"manifest carries a wall-clock field: {token}"


def test_out_of_session_rows_are_recorded_as_evidence(exploration_5m):
    """D4: the single excluded row is retained, not merely counted."""
    rows = exploration_5m.manifest["out_of_session_source_rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["ts_event_ct"].startswith("2020-03-31T16:59:00")
    assert row["symbol"] == "MNQM0"


def test_hash_verification_is_live_on_the_real_store(exploration_5m):
    exploration_5m.verify_hashes()


def test_negative_case_verification_fails_on_a_tampered_copy(tmp_path, exploration_5m):
    """Copy the real store, alter one value, and confirm the hash catches it."""
    import shutil

    copy = tmp_path / "copy"
    shutil.copytree(exploration_5m.root, copy)
    BarStore.open(copy).verify_hashes()  # sanity: the copy is clean

    volume = np.load(copy / "volume.npy")
    volume[0] += 1
    np.save(copy / "volume.npy", volume)

    with pytest.raises(SpineError, match="sha256 mismatch"):
        BarStore.open(copy).verify_hashes()


def test_negative_case_dtype_drift_is_detected(tmp_path):
    columns = {
        "ts_event_ns": np.arange(8, dtype=np.int64),
        "open_ticks": np.arange(8, dtype=np.int32),
    }
    write_store(tmp_path / "bars", columns, metadata={"build_id": "t"})
    manifest_path = tmp_path / "bars" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["columns"]["open_ticks"]["dtype"] = "int64"
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(SpineError, match="dtype"):
        BarStore.open(tmp_path / "bars")


def test_negative_case_row_count_drift_is_detected(tmp_path):
    columns = {"ts_event_ns": np.arange(8, dtype=np.int64)}
    write_store(tmp_path / "bars", columns, metadata={"build_id": "t"})
    manifest_path = tmp_path / "bars" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["row_count"] = 7
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(SpineError, match="rows, manifest says"):
        BarStore.open(tmp_path / "bars")
