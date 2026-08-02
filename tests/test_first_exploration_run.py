"""Mechanical shakedown orchestration: adapters, isolation, and staging gates."""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.conditioners.calendar import (
    CALENDAR_VERSION,
    SCHEMA_VERSION,
    CalendarRow,
    CalendarTable,
)
from mnq_lab.conditioners.pipeline import SCALE_SOURCE_ARMS
from mnq_lab.outcomes.excursions import build_outcome_table
from mnq_lab.production.first_exploration_run import (
    GATE_CLASSIFICATION,
    OUTPUT_ROOT,
    RUN_MANIFEST_NAME,
    _build_phase7_product,
    _canonical_json_bytes,
    _finalize_staged_run,
    _stage_artifacts,
    _validate_artifact_tree,
    _validate_output_root,
    _validate_run_manifest,
    run_shakedown,
)
from mnq_lab.spine.exploration import validate_exploration_store
from mnq_lab.spine.store import environment_fingerprint
from tests.unit_o_fixtures import (
    in_memory_store,
    synthetic_outcome_columns,
    write_synthetic_store,
)


def _calendar(*session_ids: int) -> CalendarTable:
    return CalendarTable(
        tuple(
            CalendarRow(
                trade_date=session_id,
                market="CME_GLOBEX_EQUITY_INDEX_FUTURES",
                session_class="regular",
                scheduled_rth_status="full_rth",
                scheduled_rth_open_ct="08:30",
                scheduled_rth_close_ct="15:00",
                raw_exchange_open_ct="17:00",
                raw_exchange_close_ct="16:00",
                holiday_adjacent=False,
                source_event_id=f"fixture:{session_id}",
                source_label="synthetic shakedown fixture",
                source_as_of="2026-08-02",
                calendar_version=CALENDAR_VERSION,
                schema_version=SCHEMA_VERSION,
            )
            for session_id in session_ids
        )
    )


def _product(tmp_path: Path, *, missing: tuple[str, ...] = ()):
    columns = synthetic_outcome_columns(missing=missing)
    store = in_memory_store(tmp_path / "exploration" / "bars_5m", columns)
    bars = validate_exploration_store(store)
    return store, _build_phase7_product(store, bars, _calendar(20210615))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_public_entry_point_has_no_override_and_fixed_output_root():
    assert tuple(inspect.signature(run_shakedown).parameters) == ()
    assert OUTPUT_ROOT.as_posix().endswith(
        "data/exploration/derived/phase7-unit-o-first-run-v1"
    )


def test_output_guard_rejects_the_canonical_store_and_its_parent(tmp_path):
    canonical = tmp_path / "data" / "exploration" / "bars_5m"
    canonical.mkdir(parents=True)

    with pytest.raises(SpineError, match="canonical exploration store"):
        _validate_output_root(canonical, canonical_store_root=canonical)
    with pytest.raises(SpineError, match="canonical exploration store"):
        _validate_output_root(canonical.parent, canonical_store_root=canonical)

    allowed = canonical.parent / "derived" / "phase7-unit-o-first-run-v1"
    assert _validate_output_root(allowed, canonical_store_root=canonical) == allowed.resolve()


def test_gate_classification_is_closed_and_every_rule_has_a_failing_input():
    allowed = {"EXPECTED_DIAGNOSTIC", "FATAL"}
    causes = {
        "roll_mapping",
        "missing_bars",
        "timestamps",
        "aggregation",
        "duplicates",
        "source_revision",
    }
    names = [row["gate"] for row in GATE_CLASSIFICATION]
    assert names == list(dict.fromkeys(names))
    assert all(row["classification"] in allowed for row in GATE_CLASSIFICATION)
    assert all(row["cause_class"] in causes for row in GATE_CLASSIFICATION)
    assert all(row["failing_input"] for row in GATE_CLASSIFICATION)
    assert any(row["classification"] == "EXPECTED_DIAGNOSTIC" for row in GATE_CLASSIFICATION)
    assert any(row["classification"] == "FATAL" for row in GATE_CLASSIFICATION)


def test_adapter_emits_full_grid_for_every_scale_arm(tmp_path):
    _, product = _product(tmp_path)
    grid_rows = 78

    assert product.grid_rows == grid_rows
    assert tuple(product.scale_tables) == SCALE_SOURCE_ARMS
    assert all(len(table.rows) == grid_rows for table in product.scale_tables.values())
    assert product.bundle.tables["anchor_scales"].row_count == 5 * grid_rows
    assert product.bundle.tables["seasonal_profiles"].row_count == 5 * grid_rows
    assert product.bundle.tables["assignments"].row_count == 10 * grid_rows
    assert product.bundle.tables["thresholds"].row_count == 10 * 5


def test_missing_anchor_is_retained_and_cannot_become_a_scale(tmp_path):
    _, product = _product(tmp_path, missing=("10:00",))
    table = product.bundle.tables["anchor_scales"]
    tau_ns = np.asarray(table.columns["tau_ns"])
    statuses = np.asarray(table.columns["anchor_status"])
    valid = np.asarray(table.columns["scale_valid"])
    missing = statuses == "anchor_bar_missing"

    assert int(missing.sum()) == len(SCALE_SOURCE_ARMS)
    assert len(np.unique(tau_ns[missing])) == 1
    assert not bool(np.any(valid[missing]))


def test_partial_regular_session_gets_a_data_quality_flag_without_reclassification(tmp_path):
    _, product = _product(tmp_path, missing=("10:00",))
    assignments = product.bundle.tables["assignments"].columns

    assert set(np.asarray(assignments["calendar_session_class"])) == {"regular"}
    assert set(np.asarray(assignments["data_quality_status"])) == {
        "unresolved_truncated_session"
    }


def test_staging_refuses_nonempty_root_and_missing_manifest(tmp_path):
    nonempty = tmp_path / "nonempty"
    nonempty.mkdir()
    (nonempty / "evidence.txt").write_text("occupied", encoding="utf-8")
    with pytest.raises(SpineError, match="absent"):
        _stage_artifacts(nonempty, None, None, None, environment={})

    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    with pytest.raises(SpineError, match="missing manifest"):
        _validate_artifact_tree(
            incomplete,
            expected_source_manifest_sha256="0" * 64,
            expected_phase7_rows={},
            expected_outcome_rows=1,
        )


def test_staged_artifacts_reverify_hashes_rows_source_and_frozen_inputs(tmp_path):
    columns = synthetic_outcome_columns()
    store = write_synthetic_store(tmp_path / "source", columns)
    bars = validate_exploration_store(store)
    product = _build_phase7_product(store, bars, _calendar(20210615))
    outcomes = build_outcome_table(store)
    stage = tmp_path / "stage"
    environment = environment_fingerprint(Path(__file__).resolve().parents[1])

    staged = _stage_artifacts(stage, store, product, outcomes, environment=environment)
    validation = _validate_artifact_tree(
        stage,
        expected_source_manifest_sha256=_sha256(store.root / "manifest.json"),
        expected_phase7_rows=product.row_counts,
        expected_outcome_rows=outcomes.row_count,
    )

    assert validation["phase7_manifest_sha256"] == _sha256(stage / "phase7/manifest.json")
    assert validation["unit_o_manifest_sha256"] == _sha256(stage / "unit_o/manifest.json")
    assert staged["completion_diagnostic_rows"] == 3


@pytest.mark.parametrize(
    "mutation, message",
    [
        ("hash", "hash"),
        ("rows", "row count"),
        ("source", "source store"),
        ("frozen", "frozen input"),
    ],
)
def test_staging_validator_kills_each_declared_mutation(tmp_path, mutation, message):
    columns = synthetic_outcome_columns()
    store = write_synthetic_store(tmp_path / "source", columns)
    bars = validate_exploration_store(store)
    product = _build_phase7_product(store, bars, _calendar(20210615))
    outcomes = build_outcome_table(store)
    stage = tmp_path / "stage"
    _stage_artifacts(stage, store, product, outcomes, environment={"commit": "fixture", "dirty": False})
    source_sha = _sha256(store.root / "manifest.json")
    expected_rows = dict(product.row_counts)

    if mutation == "hash":
        column = next((stage / "phase7").rglob("*.npy"))
        payload = bytearray(column.read_bytes())
        payload[-1] ^= 1
        column.write_bytes(payload)
    elif mutation == "rows":
        expected_rows["anchor_scales"] += 1
    elif mutation == "source":
        source_sha = "f" * 64
    else:
        manifest_path = stage / "phase7/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["frozen_inputs"]["REV6_FROZEN_SPEC.md"] = "f" * 64
        manifest_path.write_bytes(_canonical_json_bytes(manifest))

    with pytest.raises(SpineError, match=message):
        _validate_artifact_tree(
            stage,
            expected_source_manifest_sha256=source_sha,
            expected_phase7_rows=expected_rows,
            expected_outcome_rows=outcomes.row_count,
        )


def test_final_manifest_is_last_and_labels_outputs_non_admissible(tmp_path):
    columns = synthetic_outcome_columns()
    store = write_synthetic_store(tmp_path / "source", columns)
    bars = validate_exploration_store(store)
    product = _build_phase7_product(store, bars, _calendar(20210615))
    outcomes = build_outcome_table(store)
    stage = tmp_path / "stage"
    final = tmp_path / "final"
    staged = _stage_artifacts(stage, store, product, outcomes, environment={"commit": "fixture", "dirty": False})

    assert not (stage / RUN_MANIFEST_NAME).exists()
    run_manifest = _finalize_staged_run(
        stage,
        final,
        store=store,
        product=product,
        outcome_row_count=outcomes.row_count,
        staged=staged,
        stage_seconds={"phase7": 1.0, "unit_o": 1.0, "total": 2.0},
        peak_memory_bytes=123,
        environment={"commit": "fixture", "dirty": False},
    )

    assert not stage.exists()
    assert (final / RUN_MANIFEST_NAME).is_file()
    assert run_manifest["admissibility"] == "NON-ADMISSIBLE DIAGNOSTIC ARTIFACTS"
    assert run_manifest["phase8_executed"] is False
    assert run_manifest["outcome_values_inspected"] is False


def test_run_manifest_validator_rejects_reversed_order_and_missing_year(tmp_path):
    _, product = _product(tmp_path)
    base = {
        "admissibility": "NON-ADMISSIBLE DIAGNOSTIC ARTIFACTS",
        "execution_order": ["phase7", "unit_o"],
        "phase8_executed": False,
        "outcome_values_inspected": False,
        "row_counts": product.row_counts,
        "year_diagnostic_rows": 3,
        "source_store_manifest_sha256": "0" * 64,
        "artifact_manifest_sha256": {"phase7": "1" * 64, "unit_o": "2" * 64},
        "completion_diagnostic_sha256": "3" * 64,
        "gate_classification": list(GATE_CLASSIFICATION),
        "stage_seconds": {"phase7": 1.0, "unit_o": 1.0, "total": 2.0},
        "peak_memory_bytes": 1,
        "environment_fingerprint": {"commit": "fixture", "dirty": False},
    }
    _validate_run_manifest(base, expected_year_rows=3)

    reversed_order = dict(base, execution_order=["unit_o", "phase7"])
    with pytest.raises(SpineError, match="execution order"):
        _validate_run_manifest(reversed_order, expected_year_rows=3)
    with pytest.raises(SpineError, match="year diagnostic"):
        _validate_run_manifest(base, expected_year_rows=6)
