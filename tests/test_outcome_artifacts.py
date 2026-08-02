"""Deterministic Unit O table and manifest writer tests."""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.constants import REPO_ROOT
from mnq_lab.outcomes.artifacts import write_outcome_artifact
from mnq_lab.outcomes.excursions import (
    OUTCOME_SCHEMA,
    OUTCOME_STATUSES,
    STATUS_OK,
    build_outcome_table,
    validate_outcome_table,
)
from tests.unit_o_fixtures import synthetic_outcome_columns, write_synthetic_store

EXPECTED_SCHEMA = (
    "estimand",
    "session_id",
    "ts_event_ns",
    "tau_ns",
    "observation_time_ct",
    "session_phase",
    "horizon_minutes",
    "anchor_symbol_code",
    "anchor_close_ticks",
    "anchor_close_valid",
    "n_required_bars",
    "n_present_bars",
    "n_fully_labeled_bars",
    "window_fits_rth",
    "common_support",
    "outcome_status",
    "path_timestamp_missing",
    "path_session_mismatch",
    "path_symbol_mismatch",
    "insufficient_components",
    "downward_excursion_ticks",
    "upward_excursion_ticks",
    "signed_downward_extreme_ticks",
    "signed_upward_extreme_ticks",
    "outcome_valid",
)
ENVIRONMENT = {
    "vcs": "git",
    "commit": "a" * 40,
    "branch": "synthetic",
    "dirty": False,
    "python": "3.test",
    "numpy": "test",
    "pandas": "test",
    "platform": "test",
    "machine": "test",
    "pipeline_version": "spine-1.0.0",
}


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact_bytes(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_outcome_table_schema_dtypes_and_immutable_columns_are_exact(tmp_path):
    store = write_synthetic_store(tmp_path / "data", synthetic_outcome_columns())
    table = build_outcome_table(store)
    assert OUTCOME_SCHEMA == EXPECTED_SCHEMA
    assert tuple(table.columns) == EXPECTED_SCHEMA
    assert table.row_count == 2 * 78 * 3
    assert table.column("session_id").dtype == np.dtype("int32")
    assert table.column("ts_event_ns").dtype == np.dtype("int64")
    assert table.column("anchor_close_ticks").dtype == np.dtype("int32")
    assert table.column("outcome_valid").dtype == np.dtype("bool")
    assert table.column("estimand").dtype.kind == "U"
    assert all(not values.flags.writeable for values in table.columns.values())
    validate_outcome_table(table)


def test_invalid_rows_have_false_validity_and_no_semantic_numeric_payload(tmp_path):
    columns = synthetic_outcome_columns(missing=("08:40",))
    store = write_synthetic_store(tmp_path / "data", columns)
    table = build_outcome_table(store)
    invalid = table.column("outcome_status") != STATUS_OK
    assert invalid.any()
    assert not table.column("outcome_valid")[invalid].any()
    for name in (
        "downward_excursion_ticks",
        "upward_excursion_ticks",
        "signed_downward_extreme_ticks",
        "signed_upward_extreme_ticks",
    ):
        assert np.all(table.column(name)[invalid] == 0)


def test_writer_is_byte_deterministic_and_manifest_is_canonical(tmp_path):
    store = write_synthetic_store(tmp_path / "data", synthetic_outcome_columns())
    table = build_outcome_table(store)
    first = tmp_path / "first"
    second = tmp_path / "second"
    manifest_a = write_outcome_artifact(
        first, table, source_store=store, environment=ENVIRONMENT
    )
    manifest_b = write_outcome_artifact(
        second, table, source_store=store, environment=ENVIRONMENT
    )
    assert manifest_a == manifest_b
    assert _artifact_bytes(first) == _artifact_bytes(second)
    payload = (first / "manifest.json").read_bytes()
    assert payload.endswith(b"\n") and not payload.endswith(b"\n\n")
    assert payload == (
        json.dumps(json.loads(payload), sort_keys=True, indent=2, ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def test_manifest_binds_every_column_and_all_frozen_inputs(tmp_path):
    store = write_synthetic_store(tmp_path / "data", synthetic_outcome_columns())
    table = build_outcome_table(store)
    root = tmp_path / "artifact"
    manifest = write_outcome_artifact(
        root, table, source_store=store, environment=ENVIRONMENT
    )
    assert manifest["artifact_schema_version"] == "unit-o-outcomes-v1"
    assert manifest["base_commit"] == "289977aaaf836c76788035670d099740dfaa05f7"
    assert manifest["code_commit"] == ENVIRONMENT["commit"]
    assert manifest["dirty_worktree"] is False
    assert manifest["row_count"] == table.row_count
    assert manifest["column_order"] == list(EXPECTED_SCHEMA)
    assert sum(manifest["status_counts"].values()) == table.row_count
    assert list(manifest["status_counts"]) == list(OUTCOME_STATUSES)
    assert manifest["horizons_minutes"] == [15, 30, 60]
    assert manifest["estimands"] == [
        "fully_labeled_1m_grid",
        "observed_bar_path",
    ]
    assert manifest["semantic_comparison_policy"] == {
        "bar_rows": "numpy.array_equal",
        "component_rows": "numpy.array_equal",
        "outcomes": "exact int32 ticks",
    }
    protected = {
        "REV6_FROZEN_SPEC.md": "70dae16c8b12fe26d38a7bfdabf0202066fe7149f790d0d2942279d9c3b8ff50",
        "analysis_constants_v1.yaml": "1c95aa595c30c48b853303291a7dbaabceaf5b7331bca565a30863e8dcf138d4",
        "docs/OUTCOME_LAYER_PREREGISTRATION.md": "4b5bc97fdfd4b0219c69e6a8adf76f18072091a9389700191d3ddcd10f8207c8",
        "docs/PHASE8_PREREGISTRATION.md": "d07174ed0acc9e60ab6b255f4b33fc08141969c64e04f66e1e08c0aca98b4680",
    }
    assert manifest["frozen_inputs"] | protected == manifest["frozen_inputs"]
    for relative, digest in protected.items():
        assert manifest["frozen_inputs"][relative] == digest
        assert _sha256(REPO_ROOT / relative) == digest
    assert manifest["input_store_manifest_sha256"] == _sha256(
        store.root / "manifest.json"
    )
    for position, name in enumerate(EXPECTED_SCHEMA):
        record = manifest["columns"][name]
        path = root / record["file"]
        assert record["file"] == f"{position:02d}_{name}.npy"
        assert record["dtype"] == str(table.column(name).dtype)
        assert record["bytes"] == path.stat().st_size
        assert record["sha256"] == _sha256(path)


def test_writer_refuses_overwrite_invalid_table_and_mutated_preregistration(
    tmp_path, monkeypatch
):
    store = write_synthetic_store(tmp_path / "data", synthetic_outcome_columns())
    table = build_outcome_table(store)
    root = tmp_path / "artifact"
    root.mkdir()
    (root / "occupied").write_text("x", encoding="ascii")
    with pytest.raises(SpineError, match="absent or empty"):
        write_outcome_artifact(root, table, source_store=store, environment=ENVIRONMENT)

    columns = table.mutable_copy()
    columns["outcome_status"][0] = "unknown_status"
    invalid = table.from_columns(columns)
    with pytest.raises(SpineError, match="status"):
        write_outcome_artifact(
            tmp_path / "invalid", invalid, source_store=store, environment=ENVIRONMENT
        )

    from mnq_lab.outcomes import artifacts

    monkeypatch.setattr(
        artifacts,
        "_sha256_file",
        lambda path: "0" * 64
        if path.name == "OUTCOME_LAYER_PREREGISTRATION.md"
        else _sha256(path),
    )
    with pytest.raises(SpineError, match="preregistration"):
        artifacts.write_outcome_artifact(
            tmp_path / "mutated", table, source_store=store, environment=ENVIRONMENT
        )
