"""Synthetic-only Step 7 checkpoint and immutable artifact witnesses."""

from __future__ import annotations

import json

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.phase8.artifacts import (
    PHASE8_TABLE_ORDER,
    PHASE8_TABLE_SCHEMAS,
    CheckpointIdentity,
    CheckpointStore,
    Phase8Table,
    write_phase8_artifacts,
)
from mnq_lab.phase8.runner import (
    AggregateMemoryGate,
    InventoryChunk,
    execute_checkpointed_chunks,
)
from mnq_lab.phase8 import uncertainty as uncertainty_module
from mnq_lab.phase8.diagnostics import status_decision
from mnq_lab.phase8.uncertainty import BootstrapIntervalRequest, BootstrapQuantileTerm


def _identity(*, workers=2, stage1_workers=2):
    return CheckpointIdentity(
        code_commit="a" * 40,
        input_manifest_sha256=(
            ("phase7", "b" * 64),
            ("unit_o", "c" * 64),
        ),
        stage1_workers=stage1_workers,
        bootstrap_workers=workers,
        process_start_method="spawn",
        bootstrap_contract_sha256="d" * 64,
        phase8_output_version="phase8-session-aware-v2",
        producing_code_sha256=(("runner.py", "e" * 64),),
    )


def _tables():
    integer = {
        "horizon_minutes", "target_quantile_ticks", "baseline_quantile_ticks",
        "contrast_ticks", "n_anchors", "n_sessions", "baseline_n_anchors",
        "baseline_n_sessions", "quantile_ticks", "interaction_ticks",
        "common_n_sessions", "mean_block_sessions", "draws", "ci_lower_ticks",
        "ci_upper_ticks",
    }
    floating = {
        "weight_ess", "baseline_weight_ess", "completion_target",
        "completion_baseline", "completion_imbalance", "unsupported_target_mass",
        "quarter_unsupported_target_mass", "max_single_anchor_weight_share",
        "weight_cv", "confidence_level",
    }
    boolean = {name for schema in PHASE8_TABLE_SCHEMAS.values() for name in schema if name.endswith("_valid")}
    tables = []
    for table_name in PHASE8_TABLE_ORDER:
        columns = []
        for column in PHASE8_TABLE_SCHEMAS[table_name]:
            if column in integer:
                values = np.asarray([30, 31], dtype=np.int64)
            elif column in floating:
                values = np.asarray([20.0, 21.0], dtype=np.float64)
            elif column in boolean:
                values = np.asarray([True, False], dtype=np.bool_)
            elif column == "status":
                values = np.asarray(["ok", "insufficient_overlap"])
            else:
                values = np.asarray([f"{table_name}:0", f"{table_name}:1"])
            columns.append((column, values))
        tables.append(Phase8Table(table_name, tuple(columns)))
    return tuple(tables)


def test_phase8_writer_is_canonical_hashed_and_refuses_overwrite(tmp_path):
    root = tmp_path / "phase8"
    manifest = write_phase8_artifacts(
        root,
        _tables(),
        provenance={"unit_o_manifest_sha256": "c" * 64},
        operating={"workers": 16, "aggregate_peak_memory_bytes": 1234},
        limitations=("literal limitation",),
    )

    payload = (root / "manifest.json").read_bytes()
    assert payload == (
        json.dumps(json.loads(payload), sort_keys=True, indent=2, ensure_ascii=True)
        + "\n"
    ).encode("utf-8")
    assert manifest["table_order"] == list(PHASE8_TABLE_ORDER)
    for table_name in PHASE8_TABLE_ORDER:
        table = manifest["tables"][table_name]
        assert table["column_order"] == list(PHASE8_TABLE_SCHEMAS[table_name])
        for record in table["columns"].values():
            path = root / table_name / record["file"]
            assert path.stat().st_size == record["bytes"]

    with pytest.raises(SpineError, match="absent or empty"):
        write_phase8_artifacts(
            root,
            _tables(),
            provenance={},
            operating={},
            limitations=(),
        )


def test_phase8_table_rejects_a_schema_that_drops_required_companions():
    with pytest.raises(SpineError, match="immutable schema"):
        Phase8Table(
            "contrasts",
            (("row_id", np.asarray(["schema-drop-mutant"])),),
        )


def test_checkpoint_resume_is_exact_and_mismatch_halts(tmp_path):
    chunks = tuple(
        InventoryChunk(index=index, row_ids=(f"row-{index}",)) for index in range(3)
    )

    def compute(chunk):
        return {"row_id": np.asarray(chunk.row_ids), "value": np.asarray([chunk.index])}

    clean = execute_checkpointed_chunks(
        chunks,
        checkpoint=CheckpointStore(tmp_path / "clean", _identity()),
        compute_chunk=compute,
    )
    interrupted_store = CheckpointStore(tmp_path / "resume", _identity())
    with pytest.raises(RuntimeError, match="named interruption"):
        execute_checkpointed_chunks(
            chunks,
            checkpoint=interrupted_store,
            compute_chunk=compute,
            interrupt_after_chunks=1,
        )
    resumed = execute_checkpointed_chunks(
        chunks,
        checkpoint=CheckpointStore(tmp_path / "resume", _identity()),
        compute_chunk=compute,
    )
    assert tuple(clean) == tuple(resumed)
    for key in clean:
        assert np.array_equal(clean[key], resumed[key])

    with pytest.raises(SpineError, match="checkpoint identity differs"):
        CheckpointStore(tmp_path / "resume", _identity(workers=3))


def test_checkpoint_union_rejects_missing_or_duplicate_declared_rows(tmp_path):
    duplicate = (
        InventoryChunk(0, ("same",)),
        InventoryChunk(1, ("same",)),
    )
    with pytest.raises(SpineError, match="duplicate declared row"):
        execute_checkpointed_chunks(
            duplicate,
            checkpoint=CheckpointStore(tmp_path / "duplicate", _identity()),
            compute_chunk=lambda chunk: {"row_id": np.asarray(chunk.row_ids)},
        )


def test_aggregate_memory_gate_measures_parent_plus_descendants():
    samples = iter((100, 400, 600))
    gate = AggregateMemoryGate(
        ceiling_bytes=500,
        launch_minimum_available_bytes=700,
        aggregate_sampler=lambda: next(samples),
        available_sampler=lambda: 700,
    )
    assert gate.preflight() == 700
    assert gate.sample() == 100
    assert gate.sample() == 400
    with pytest.raises(SpineError, match="aggregate Phase 8 memory"):
        gate.sample()
    assert gate.peak_bytes == 600


def test_launch_preflight_fails_before_any_chunk_computation(tmp_path):
    called = False

    def compute(_chunk):
        nonlocal called
        called = True
        return {"row_id": np.asarray(["must-not-run"])}

    gate = AggregateMemoryGate(
        ceiling_bytes=1_000,
        launch_minimum_available_bytes=700,
        aggregate_sampler=lambda: 100,
        available_sampler=lambda: 699,
    )
    with pytest.raises(SpineError, match="available memory preflight"):
        execute_checkpointed_chunks(
            (InventoryChunk(0, ("row",)),),
            checkpoint=CheckpointStore(tmp_path / "preflight", _identity()),
            compute_chunk=compute,
            memory_gate=gate,
        )
    assert called is False


def test_small_synthetic_pipeline_reaches_all_four_canonical_tables(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(uncertainty_module, "DRAWS_PER_BLOCK_LENGTH", 999)
    groups = np.repeat(np.arange(4, dtype=np.int32), 2)
    mask = np.ones(groups.size, dtype=np.bool_)
    weights = np.full(groups.size, 1 / groups.size)
    term = BootstrapQuantileTerm(
        "smoke-term", np.arange(groups.size, dtype=np.int32), mask, weights, "q50"
    )
    ok = status_decision(
        degenerate_baseline=False,
        insufficient_anchors=False,
        insufficient_completion=False,
        insufficient_overlap=False,
    )
    request = BootstrapIntervalRequest("smoke-point", term.term_id, None, ok)
    plans = uncertainty_module._prepare_joint_plan_matrices(groups, (term,))
    result = uncertainty_module._joint_bootstrap_intervals_with_plan_matrices(
        groups, (term,), (request,), plans
    )
    interval = result.requests[0].intervals[0]
    columns = []
    values = {
        "row_id": "smoke-point:1",
        "point_row_id": "smoke-point",
        "mean_block_sessions": interval.mean_block_sessions,
        "draws": interval.draws,
        "confidence_level": interval.confidence_level,
        "ci_lower_ticks": interval.ci_lower_ticks,
        "ci_upper_ticks": interval.ci_upper_ticks,
        "interval_valid": interval.interval_valid,
        "rng_root_entropy": str(interval.rng_root_entropy),
        "rng_child_spawn_key": str(interval.rng_child_spawn_key),
        "historical_mixture_disclosure": interval.historical_mixture_disclosure,
        "conditioner_uncertainty_disclosure": interval.conditioner_uncertainty_disclosure,
        "weight_ess_disclosure": interval.weight_ess_disclosure,
    }
    for name in PHASE8_TABLE_SCHEMAS["intervals"]:
        value = values[name]
        if name in {"mean_block_sessions", "draws", "ci_lower_ticks", "ci_upper_ticks"}:
            array = np.asarray([value], dtype=np.int64)
        elif name == "confidence_level":
            array = np.asarray([value], dtype=np.float64)
        elif name == "interval_valid":
            array = np.asarray([value], dtype=np.bool_)
        else:
            array = np.asarray([value])
        columns.append((name, array))
    tables = list(_tables())
    tables[1] = Phase8Table("intervals", tuple(columns))
    manifest = write_phase8_artifacts(
        tmp_path / "smoke-output",
        tuple(tables),
        provenance={"synthetic": True},
        operating={"workers": 1, "aggregate_peak_memory_bytes": 1},
        limitations=("synthetic smoke only",),
    )
    assert manifest["tables"]["intervals"]["row_count"] == 1
    assert tuple(manifest["tables"]) == PHASE8_TABLE_ORDER
