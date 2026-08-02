"""Fail-closed tests for the sole Phase 7 exploration-data adapter."""

from __future__ import annotations

import ast
import inspect
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.spine import exploration
from mnq_lab.spine.exploration import open_exploration_bars, validate_exploration_store
from mnq_lab.spine.store import BarStore, PIPELINE_VERSION

CT = ZoneInfo("America/Chicago")


def _ct_ns(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=CT).timestamp() * 1_000_000_000)


def _synthetic_store() -> BarStore:
    timestamps = np.asarray(
        [_ct_ns("2020-01-01T17:00:00"), _ct_ns("2020-01-01T17:05:00")],
        dtype=np.int64,
    )
    columns = {
        "ts_event_ns": timestamps,
        "session_id": np.asarray([20200102, 20200102], dtype=np.int32),
        "symbol_code": np.asarray([0, 0], dtype=np.int16),
        "open_ticks": np.asarray([100, 102], dtype=np.int32),
        "high_ticks": np.asarray([105, 106], dtype=np.int32),
        "low_ticks": np.asarray([99, 101], dtype=np.int32),
        "close_ticks": np.asarray([102, 104], dtype=np.int32),
        "volume": np.asarray([0, 7], dtype=np.int64),
        "expected_1m_components": np.asarray([5, 5], dtype=np.int8),
        "observed_1m_components": np.asarray([5, 3], dtype=np.int8),
        "component_coverage_rate": np.asarray([1.0, 0.6], dtype=np.float64),
        "rollover": np.asarray([False, False], dtype=np.bool_),
    }
    manifest = {
        "corpus": "exploration",
        "frequency": "5m",
        "bar_seconds": 300,
        "program_id": "mnq-atlas-001",
        "pipeline_version": PIPELINE_VERSION,
        "build_id": "synthetic-phase7",
        "row_count": 2,
        "trade_date_first": 20200102,
        "trade_date_last": 20200102,
        "symbols": ["MNQH0"],
        "columns": {
            name: {"dtype": str(array.dtype), "file": f"{name}.npy", "rows": 2}
            for name, array in columns.items()
        },
    }
    return BarStore(Path("synthetic-not-opened"), manifest, columns)


def _mutate_store(
    store: BarStore,
    *,
    manifest: dict | None = None,
    column: tuple[str, np.ndarray] | None = None,
) -> BarStore:
    changed_manifest = dict(store.manifest)
    if manifest:
        changed_manifest.update(manifest)
    changed_columns = dict(store._columns)
    if column:
        changed_columns[column[0]] = column[1]
    return BarStore(store.root, changed_manifest, changed_columns)


def test_adapter_has_one_zero_argument_exploration_only_entry_point():
    assert list(inspect.signature(open_exploration_bars).parameters) == []
    source = inspect.getsource(exploration)
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not any(name.startswith("mnq_lab.studies") for name in imported)
    assert not any(name.startswith("mnq_lab.report") for name in imported)
    assert "Corpus.EXPLORATION" in source

    # A tier/path switch would enlarge the public signature and fail this guard.
    def forbidden_switch(*, corpus, path):
        return corpus, path

    assert list(inspect.signature(forbidden_switch).parameters) == ["corpus", "path"]
    assert inspect.signature(forbidden_switch) != inspect.signature(open_exploration_bars)


def test_synthetic_store_validates_without_opening_any_store():
    validated = validate_exploration_store(_synthetic_store())
    assert validated.build_id == "synthetic-phase7"
    assert validated.symbols == ("MNQH0",)
    assert validated.n_rows == 2
    assert validated.column("component_coverage_rate").tolist() == [1.0, 0.6]
    assert not validated.column("close_ticks").flags.writeable
    with pytest.raises(ValueError):
        validated.column("close_ticks")[0] = 1
    with pytest.raises(SpineError, match="unknown exploration column"):
        validated.column("unknown")


def test_canonical_exploration_store_passes_hash_and_schema_validation():
    validated = open_exploration_bars()
    assert validated.n_rows == 274_847
    assert validated.build_id == "0ad7843647f17258"
    assert validated.column("ts_event_ns").dtype == np.dtype("int64")
    assert validated.column("rollover").dtype == np.dtype("bool")


@pytest.mark.parametrize(
    ("manifest_mutation", "column_mutation", "match"),
    [
        ({"corpus": "not-exploration"}, None, "corpus"),
        ({"frequency": "1m"}, None, "frequency"),
        ({"bar_seconds": 60}, None, "bar_seconds"),
        ({"row_count": 0}, None, "date range is empty"),
        (None, ("ts_event_ns", np.asarray([1, 1], dtype=np.int64)), "strictly increasing"),
        (None, ("session_id", np.asarray([20200103, 20200103], dtype=np.int32)), "first trade date"),
        (None, ("symbol_code", np.asarray([0, 1], dtype=np.int16)), "symbol_code"),
        (None, ("high_ticks", np.asarray([98, 106], dtype=np.int32)), "OHLC consistency"),
        (None, ("low_ticks", np.asarray([101, 101], dtype=np.int32)), "OHLC consistency"),
        (None, ("volume", np.asarray([0, -1], dtype=np.int64)), "nonnegative"),
        (None, ("expected_1m_components", np.asarray([5, 4], dtype=np.int8)), "equal five"),
        (None, ("observed_1m_components", np.asarray([5, 6], dtype=np.int8)), "outside"),
        (None, ("component_coverage_rate", np.asarray([1.0, 0.8], dtype=np.float64)), "differs"),
        (None, ("close_ticks", np.asarray([102, 104], dtype=np.int64)), "dtype"),
    ],
)
def test_adapter_rejects_each_named_corruption(manifest_mutation, column_mutation, match):
    corrupted = _mutate_store(
        _synthetic_store(), manifest=manifest_mutation, column=column_mutation
    )
    with pytest.raises(SpineError, match=match):
        validate_exploration_store(corrupted)


def test_adapter_rejects_missing_required_field_before_computation():
    store = _synthetic_store()
    manifest = dict(store.manifest)
    column_specs = dict(manifest["columns"])
    del column_specs["volume"]
    manifest["columns"] = column_specs
    missing = replace(store, manifest=manifest)
    with pytest.raises(SpineError, match="missing columns.*volume"):
        validate_exploration_store(missing)
