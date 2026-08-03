"""Synthetic-only Step 7 checkpoint and immutable artifact witnesses."""

from __future__ import annotations

import json

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.phase8.artifacts import (
    PHASE8_TABLE_ORDER,
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


def _identity(*, workers=2):
    return CheckpointIdentity(
        code_commit="a" * 40,
        input_manifest_sha256=(
            ("phase7", "b" * 64),
            ("unit_o", "c" * 64),
        ),
        workers=workers,
        process_start_method="spawn",
        bootstrap_contract_sha256="d" * 64,
    )


def _tables():
    return tuple(
        Phase8Table(
            name=name,
            columns=(
                ("row_id", np.asarray([f"{name}:0", f"{name}:1"])),
                ("n_anchors", np.asarray([30, 31], dtype=np.int64)),
                ("n_sessions", np.asarray([20, 21], dtype=np.int64)),
                ("weight_ess", np.asarray([20.0, 21.0], dtype=np.float64)),
                ("status", np.asarray(["ok", "insufficient_overlap"])),
            ),
        )
        for name in PHASE8_TABLE_ORDER
    )


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
        assert table["column_order"][1:4] == [
            "n_anchors",
            "n_sessions",
            "weight_ess",
        ]
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

