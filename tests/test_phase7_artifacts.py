"""Deterministic Phase 7 artifact and manifest contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.conditioners.artifacts import (
    ANCHOR_SCALE_SCHEMA,
    PHASE7_ARTIFACT_SCHEMA_VERSION,
    build_phase7_artifact_bundle,
    write_phase7_artifacts,
)
from mnq_lab.conditioners.calendar import CALENDAR_SHA256, CALENDAR_VERSION
from mnq_lab.conditioners.state_validity import (
    METRIC_ORDER,
    StateValidityPanel,
    StateValidityRow,
)
from tests.phase7_pipeline_fixtures import synthetic_pipeline


def _anchor_columns():
    values = {
        "arm_id": ["primary_ewma78_permissive_expanding"],
        "session_id": [20200102],
        "ts_event_ns": [1_000_000_000],
        "tau_ns": [301_000_000_000],
        "observation_bucket_ct": ["08:30"],
        "session_phase": ["open"],
        "symbol_code": [0],
        "observed_1m_components": [5],
        "component_coverage_rate": [1.0],
        "anchor_status": ["ok"],
        "return_status": ["ok"],
        "return_missing_reason": [""],
        "reset_reason": ["none"],
        "scheduled_break": [False],
        "contiguous_return_count": [78],
        "scale_value": [-0.0],
        "scale_valid": [True],
        "ewma_status": ["ok"],
        "mad_status": [""],
    }
    assert tuple(values) == tuple(name for name, _ in ANCHOR_SCALE_SCHEMA)
    return values


def _panel():
    rows = []
    for metric in METRIC_ORDER:
        rows.append(
            StateValidityRow(
                metric,
                "primary_ewma78_permissive_expanding",
                "open",
                "fixture",
                "",
                -2,
                -2,
                0,
                0,
                "",
                0,
                1,
                0.0,
                metric != "liquidity_era_correlation",
                "deferred_missing_versioned_input"
                if metric == "liquidity_era_correlation"
                else "ok",
            )
        )
    return StateValidityPanel(tuple(rows))


@pytest.fixture(scope="module")
def bundle():
    _, _, _, pipeline = synthetic_pipeline(65)
    return build_phase7_artifact_bundle(_anchor_columns(), pipeline, _panel())


def _files(root: Path):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _environment():
    return {
        "python": "fixture",
        "numpy": np.__version__,
        "pandas": "fixture",
        "platform": "fixture",
        "machine": "fixture",
        "pipeline_version": "fixture",
        "vcs": "git",
        "commit": "a" * 40,
        "branch": "phase-7-conditioners",
        "dirty": False,
    }


def test_same_fingerprint_builds_are_byte_identical(tmp_path, bundle):
    left = tmp_path / "left"
    right = tmp_path / "right"
    write_phase7_artifacts(left, bundle, source_build_id="fixture", environment=_environment())
    write_phase7_artifacts(right, bundle, source_build_id="fixture", environment=_environment())
    assert _files(left)
    assert _files(left) == _files(right)


def test_manifest_binds_every_column_and_required_identity(tmp_path, bundle):
    root = tmp_path / "artifact"
    manifest = write_phase7_artifacts(
        root, bundle, source_build_id="fixture", environment=_environment()
    )
    raw = (root / "manifest.json").read_bytes()
    assert raw.endswith(b"\n") and b"\r" not in raw
    assert json.loads(raw) == manifest
    assert manifest["artifact_schema_version"] == PHASE7_ARTIFACT_SCHEMA_VERSION
    assert manifest["arm_schema_version"] == "phase7-ofat-arms-v1"
    assert tuple(manifest["table_schema_versions"]) == tuple(bundle.tables)
    assert manifest["calendar_version"] == CALENDAR_VERSION
    assert manifest["calendar_sha256"] == CALENDAR_SHA256
    assert manifest["code_commit"] == "a" * 40
    assert manifest["dirty_worktree"] is False
    assert len(manifest["registry_comparison_policies"]) == 35
    for table in manifest["tables"].values():
        assert table["column_order"]
        for spec in table["columns"].values():
            path = root / spec["file"]
            payload = path.read_bytes()
            assert spec["bytes"] == len(payload)
            assert spec["sha256"] == hashlib.sha256(payload).hexdigest()
            assert len(np.load(path, allow_pickle=False)) == spec["rows"]


def test_negative_zero_is_canonicalized(tmp_path, bundle):
    root = tmp_path / "artifact"
    write_phase7_artifacts(root, bundle, source_build_id="fixture", environment=_environment())
    value = np.load(root / "anchor_scales" / "15_scale_value.npy", allow_pickle=False)[0]
    assert value == 0.0
    assert not np.signbit(value)


@pytest.mark.parametrize(
    ("version", "digest"),
    [(None, CALENDAR_SHA256), (CALENDAR_VERSION, None), ("wrong", CALENDAR_SHA256)],
)
def test_calendar_identity_fails_before_any_write(tmp_path, bundle, version, digest):
    root = tmp_path / "artifact"
    with pytest.raises(SpineError, match="accepted calendar"):
        write_phase7_artifacts(
            root,
            bundle,
            source_build_id="fixture",
            calendar_version=version,
            calendar_sha256=digest,
            environment=_environment(),
        )
    assert not root.exists()


def test_schema_rejects_a_phase8_artifact_key(bundle):
    tables = dict(bundle.tables)
    tables["contrast_results"] = tables["assignments"]
    from mnq_lab.conditioners.artifacts import Phase7ArtifactBundle

    with pytest.raises(SpineError, match="Phase 8-12 artifact key"):
        Phase7ArtifactBundle(tables)


def test_nonempty_output_directory_is_rejected(tmp_path, bundle):
    root = tmp_path / "artifact"
    root.mkdir()
    (root / "stale").write_text("stale", encoding="ascii")
    with pytest.raises(SpineError, match="absent or empty"):
        write_phase7_artifacts(root, bundle, source_build_id="fixture", environment=_environment())
