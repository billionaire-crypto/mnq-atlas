"""Fresh-process bounded memory probe for the ratified dependency gate."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time as datetime_time, timedelta
import gc
from itertools import chain
import json
from pathlib import Path
import sys
import tempfile
import time

import numpy as np

from mnq_lab.conditioners.assignments import build_thresholds
from mnq_lab.conditioners.arms import arm_config
from mnq_lab.conditioners.calendar import (
    CALENDAR_VERSION,
    SCHEMA_VERSION,
    CalendarRow,
    CalendarTable,
)
from mnq_lab.conditioners.dependencies import dependency_storage_stats
from mnq_lab.conditioners.pipeline import (
    SCALE_SOURCE_ARMS,
    build_conditioner_pipeline,
)
from mnq_lab.conditioners.seasonal import (
    ScaleAnchorTable,
    build_seasonal_profiles,
)
from mnq_lab.outcomes.excursions import build_outcome_table
from mnq_lab.production.first_exploration_run import (
    _begin_stage,
    _build_phase7_product,
    _complete_stage,
    _peak_process_memory_bytes,
    _sha256_file,
    _validate_artifact_tree,
    _validate_phase7_tree,
)
from mnq_lab.spine.exploration import validate_exploration_store
from tests.phase7_pipeline_fixtures import CT, session_id, weekday_dates
from tests.test_seasonal_dependency_retention import (
    ARM_ID,
    _full_density_fixture,
    _vol_rel_fixture,
)
from tests.unit_o_fixtures import (
    schedule_for_store,
    write_synthetic_store,
)


def _full_scale_tables(primary: ScaleAnchorTable) -> dict[str, ScaleAnchorTable]:
    tables: dict[str, ScaleAnchorTable] = {}
    for arm_id in SCALE_SOURCE_ARMS:
        stage = "mad" if arm_id == "mad78" else "ewma"
        tables[arm_id] = ScaleAnchorTable(
            arm_id,
            tuple(
                replace(row, arm_id=arm_id, scale_stage=stage)
                for row in primary.rows
            ),
        )
    return tables


def _full_run_store_and_calendar(root: Path, session_count: int):
    days = weekday_dates(session_count)
    labels: list[int] = []
    sessions: list[int] = []
    for value in days:
        current = datetime.combine(
            value - timedelta(days=1), datetime_time(17, 0), tzinfo=CT
        )
        end = datetime.combine(value, datetime_time(16, 0), tzinfo=CT)
        while current < end:
            labels.append(int(current.timestamp() * 1_000_000_000))
            sessions.append(session_id(value))
            current += timedelta(minutes=5)
    row_count = len(labels)
    center = 1_000 + np.arange(row_count, dtype=np.int32) % 200
    expected = np.full(row_count, 5, dtype=np.int8)
    columns = {
        "ts_event_ns": np.asarray(labels, dtype=np.int64),
        "session_id": np.asarray(sessions, dtype=np.int32),
        "symbol_code": np.zeros(row_count, dtype=np.int16),
        "open_ticks": center.copy(),
        "high_ticks": center + np.int32(2),
        "low_ticks": center - np.int32(2),
        "close_ticks": center.copy(),
        "volume": np.full(row_count, 10, dtype=np.int64),
        "expected_1m_components": expected,
        "observed_1m_components": expected.copy(),
        "component_coverage_rate": np.ones(row_count, dtype=np.float64),
        "rollover": np.zeros(row_count, dtype=bool),
    }
    store = write_synthetic_store(root / "source", columns)
    del columns
    gc.collect()
    calendar = CalendarTable(
        tuple(
            CalendarRow(
                session_id(value),
                "CME_GLOBEX_EQUITY_INDEX_FUTURES",
                "regular",
                "full_rth",
                "08:30",
                "15:00",
                "17:00",
                "16:00",
                False,
                f"full-memory-probe:{session_id(value)}",
                "synthetic-memory-probe",
                "test",
                CALENDAR_VERSION,
                SCHEMA_VERSION,
            )
            for value in days
        )
    )
    return store, calendar


def _run_full_shape(root: Path, session_count: int) -> dict[str, object]:
    environment = {
        "branch": "synthetic-memory-probe",
        "commit": "synthetic-memory-probe",
        "dirty": False,
        "machine": "bounded",
        "numpy": np.__version__,
        "pandas": "bounded",
        "pipeline_version": "spine-1.0.0",
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "vcs": "fixture",
    }
    store, calendar = _full_run_store_and_calendar(root, session_count)
    bars = validate_exploration_store(store)
    stage_seconds: dict[str, float] = {}

    mark = time.perf_counter()
    product = _build_phase7_product(store, bars, calendar)
    stage_seconds["phase7_compute"] = time.perf_counter() - mark
    rows = tuple(
        chain(
            *(table.rows for table in product.pipeline.seasonal_profiles.values()),
            *(table.rows for table in product.pipeline.threshold_tables.values()),
        )
    )
    stats = dependency_storage_stats(rows)
    private_expansions = sum(
        "dependency_keys" in getattr(row, "__dict__", {}) for row in rows
    )
    del rows

    mark = time.perf_counter()
    stage_root = root / "stage"
    _begin_stage(stage_root, store, product, environment=environment)
    _validate_phase7_tree(stage_root / "phase7", product.row_counts)
    stage_seconds["phase7_write_and_verify"] = time.perf_counter() - mark
    phase7_row_counts = dict(product.row_counts)
    live_row_counts = {
        "seasonal": phase7_row_counts["seasonal_profiles"],
        "threshold": phase7_row_counts["thresholds"],
        "assignment": phase7_row_counts["assignments"],
        "state_validity": phase7_row_counts["state_validity"],
    }
    del product, bars, calendar
    gc.collect()

    mark = time.perf_counter()
    outcomes = build_outcome_table(store, schedule_table=schedule_for_store(store))
    stage_seconds["unit_o_compute"] = time.perf_counter() - mark
    outcome_row_count = outcomes.row_count

    mark = time.perf_counter()
    _complete_stage(stage_root, store, outcomes, environment=environment)
    del outcomes
    gc.collect()
    _validate_artifact_tree(
        stage_root,
        expected_source_manifest_sha256=_sha256_file(store.root / "manifest.json"),
        expected_phase7_rows=phase7_row_counts,
        expected_outcome_rows=outcome_row_count,
    )
    stage_seconds["unit_o_write_and_full_verify"] = time.perf_counter() - mark
    artifact_files = tuple(path for path in stage_root.rglob("*") if path.is_file())
    artifact_bytes = sum(path.stat().st_size for path in artifact_files)
    return {
        "private_expansion_rows": private_expansions,
        "live_row_counts": live_row_counts,
        "outcome_row_count": outcome_row_count,
        "artifact_file_count": len(artifact_files),
        "artifact_bytes": artifact_bytes,
        "stage_seconds": stage_seconds,
        **stats,
    }


def run_probe(mode: str, session_count: int) -> dict[str, object]:
    if mode not in {"seasonal", "threshold", "full"}:
        raise ValueError("mode must be seasonal, threshold or full")
    if session_count not in {100, 200, 400}:
        raise ValueError("session_count must be 100, 200 or 400")
    started_wall = time.perf_counter()
    started_cpu = time.process_time()

    if mode == "full":
        with tempfile.TemporaryDirectory(prefix="mnq-atlas-full-memory-") as temporary:
            full = _run_full_shape(Path(temporary), session_count)
        return {
            "mode": mode,
            "sessions": session_count,
            "anchors_per_session": 78,
            "wall_seconds": time.perf_counter() - started_wall,
            "cpu_seconds": time.process_time() - started_cpu,
            "peak_working_set_bytes": _peak_process_memory_bytes(),
            **full,
        }

    sessions, calendar, primary = _full_density_fixture(session_count)
    completed = frozenset(sessions)

    if mode == "seasonal":
        table = build_seasonal_profiles(primary, sessions, completed, calendar)
        rows = table.rows
        live_row_counts = {"seasonal": len(rows)}
    elif mode == "threshold":
        vol_rel = _vol_rel_fixture(primary)
        table = build_thresholds(
            arm_config(ARM_ID), vol_rel, sessions, completed, calendar
        )
        rows = table.rows
        live_row_counts = {"threshold": len(rows)}
    stats = dependency_storage_stats(rows)
    private_expansions = sum(
        "dependency_keys" in getattr(row, "__dict__", {}) for row in rows
    )
    return {
        "mode": mode,
        "sessions": session_count,
        "anchors_per_session": 78,
        "private_expansion_rows": private_expansions,
        "live_row_counts": live_row_counts,
        "wall_seconds": time.perf_counter() - started_wall,
        "cpu_seconds": time.process_time() - started_cpu,
        "peak_working_set_bytes": _peak_process_memory_bytes(),
        **stats,
    }


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: dependency_memory_probe.py MODE N")
    print(
        json.dumps(run_probe(sys.argv[1], int(sys.argv[2])), sort_keys=True),
        flush=True,
    )


if __name__ == "__main__":
    main()
