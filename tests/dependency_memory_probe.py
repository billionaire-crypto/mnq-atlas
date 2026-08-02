"""Fresh-process bounded memory probe for the ratified dependency gate."""

from __future__ import annotations

from dataclasses import replace
from itertools import chain
import json
import sys
import time

from mnq_lab.conditioners.assignments import build_thresholds
from mnq_lab.conditioners.arms import arm_config
from mnq_lab.conditioners.dependencies import dependency_storage_stats
from mnq_lab.conditioners.pipeline import (
    SCALE_SOURCE_ARMS,
    build_conditioner_pipeline,
)
from mnq_lab.conditioners.seasonal import (
    ScaleAnchorTable,
    build_seasonal_profiles,
)
from tests.test_seasonal_dependency_retention import (
    ARM_ID,
    _full_density_fixture,
    _vol_rel_fixture,
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


def run_probe(mode: str, session_count: int) -> dict[str, object]:
    if mode not in {"seasonal", "threshold", "full"}:
        raise ValueError("mode must be seasonal, threshold or full")
    if session_count not in {100, 200, 400}:
        raise ValueError("session_count must be 100, 200 or 400")
    sessions, calendar, primary = _full_density_fixture(session_count)
    completed = frozenset(sessions)
    started_wall = time.perf_counter()
    started_cpu = time.process_time()

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
    else:
        pipeline = build_conditioner_pipeline(
            _full_scale_tables(primary), sessions, completed, calendar
        )
        rows = tuple(
            chain(
                *(table.rows for table in pipeline.seasonal_profiles.values()),
                *(table.rows for table in pipeline.threshold_tables.values()),
            )
        )
        live_row_counts = {
            "seasonal": sum(
                len(table.rows) for table in pipeline.seasonal_profiles.values()
            ),
            "vol_rel": sum(
                len(table.rows) for table in pipeline.vol_rel_tables.values()
            ),
            "threshold": sum(
                len(table.rows) for table in pipeline.threshold_tables.values()
            ),
            "assignment": sum(
                len(table.rows) for table in pipeline.assignment_tables.values()
            ),
        }
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
