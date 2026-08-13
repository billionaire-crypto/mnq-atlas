"""Separately authorized cost-only benchmark; never invoked by ordinary tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import secrets
import shutil
import sys
import time
import tracemalloc
from typing import Any, Callable

from mnq_lab import SpineError
from mnq_lab.phase8.runner import validate_external_checkpoint_root

CALIBRATION_BENCHMARK_AUTHORIZATION = (
    "MNQ-ATLAS-PHASE10-CALIBRATION-COST-BENCHMARK-REV1"
)


@dataclass(frozen=True)
class CostPassResult:
    rows: int
    worker_utilization: float
    temporary_output_bytes: int

    def __post_init__(self) -> None:
        if isinstance(self.rows, bool) or not isinstance(self.rows, int) or self.rows < 0:
            raise SpineError("benchmark row count is invalid")
        if (
            isinstance(self.worker_utilization, bool)
            or not isinstance(self.worker_utilization, (int, float))
            or not 0.0 <= float(self.worker_utilization) <= 1.0
        ):
            raise SpineError("benchmark worker utilization is invalid")
        if (
            isinstance(self.temporary_output_bytes, bool)
            or not isinstance(self.temporary_output_bytes, int)
            or self.temporary_output_bytes < 0
        ):
            raise SpineError("benchmark temporary-output byte count is invalid")


@dataclass(frozen=True)
class CostBenchmarkResult:
    wall_seconds: float
    cpu_seconds: float
    memory_bytes: int
    rows: int
    worker_utilization: float
    temporary_output_bytes: int


def _validate_benchmark_authorization(authorization: Any) -> None:
    if not isinstance(authorization, str) or not secrets.compare_digest(
        authorization,
        CALIBRATION_BENCHMARK_AUTHORIZATION,
    ):
        raise SpineError("Phase 10 benchmark authorization differs")


def _assert_timing_uninstrumented() -> None:
    if sys.gettrace() is not None:
        raise SpineError("timed benchmark region cannot run with a trace or coverage hook")
    if sys.getprofile() is not None:
        raise SpineError("timed benchmark region cannot run with a profiler hook")
    if tracemalloc.is_tracing():
        raise SpineError("timed benchmark region cannot run with allocation tracing")


def _timed_pass(
    workload: Callable[[Path, int], CostPassResult],
    root: Path,
    worker_count: int,
) -> tuple[float, float, CostPassResult]:
    pass_root = root / f"timed-workers-{worker_count}"
    pass_root.mkdir(parents=True, exist_ok=False)
    try:
        _assert_timing_uninstrumented()
        wall_start = time.perf_counter()
        cpu_start = time.process_time()
        result = workload(pass_root, worker_count)
        cpu_seconds = time.process_time() - cpu_start
        wall_seconds = time.perf_counter() - wall_start
        if not isinstance(result, CostPassResult):
            raise SpineError("benchmark workload returned scientific or undeclared output")
        return wall_seconds, cpu_seconds, result
    finally:
        if pass_root.exists():
            shutil.rmtree(pass_root)


def _memory_pass(
    workload: Callable[[Path, int], CostPassResult],
    root: Path,
    worker_count: int,
) -> tuple[int, CostPassResult]:
    pass_root = root / f"memory-workers-{worker_count}"
    pass_root.mkdir(parents=True, exist_ok=False)
    try:
        if tracemalloc.is_tracing():
            raise SpineError("benchmark memory pass requires a fresh allocation tracer")
        tracemalloc.start()
        try:
            result = workload(pass_root, worker_count)
            _, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        if not isinstance(result, CostPassResult):
            raise SpineError("benchmark workload returned scientific or undeclared output")
        return int(peak_bytes), result
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        if pass_root.exists():
            shutil.rmtree(pass_root)


def run_calibration_cost_benchmark(
    authorization: str,
    *,
    workload: Callable[[Path, int], CostPassResult],
    worker_counts: tuple[int, ...],
    temporary_root: Path,
) -> tuple[CostBenchmarkResult, ...]:
    """Run separate timing and memory passes outside the repository."""
    _validate_benchmark_authorization(authorization)
    root = validate_external_checkpoint_root(Path(temporary_root), resume=False)
    if (
        not isinstance(worker_counts, tuple)
        or not worker_counts
        or len(set(worker_counts)) != len(worker_counts)
        or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in worker_counts)
    ):
        raise SpineError("benchmark worker counts must be unique positive integers")
    root.mkdir(parents=True, exist_ok=False)
    results: list[CostBenchmarkResult] = []
    try:
        for worker_count in worker_counts:
            wall, cpu, timed = _timed_pass(workload, root, worker_count)
            memory, measured = _memory_pass(workload, root, worker_count)
            if timed != measured:
                raise SpineError("timing and memory passes processed different cost inventories")
            results.append(
                CostBenchmarkResult(
                    wall,
                    cpu,
                    memory,
                    timed.rows,
                    timed.worker_utilization,
                    timed.temporary_output_bytes,
                )
            )
        return tuple(results)
    finally:
        if root.exists():
            shutil.rmtree(root)
