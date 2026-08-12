"""Cost-only Phase 10 scaling benchmark with mandatory cleanup."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import tracemalloc
from typing import Any, Iterable

from mnq_lab import SpineError
from mnq_lab.constants import REPO_ROOT
from mnq_lab.phase10.adapter import load_formal_corpus
from mnq_lab.phase10.contract import artifact_metadata
from mnq_lab.phase10.engine import evaluate_null_surfaces

_RSS_STOP_BYTES = 4_000_000_000


class _RssSampler:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self.peak = 0
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        while not self._stop.is_set():
            self.peak = max(self.peak, _current_rss())
            self._stop.wait(0.05)

    def __enter__(self) -> _RssSampler:
        self.peak = _current_rss()
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.peak = max(self.peak, _current_rss())
        self._stop.set()
        self._thread.join(timeout=2.0)


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = (
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    )


def _current_rss() -> int:
    if os.name != "nt":
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(usage * 1024)
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    current_process = ctypes.windll.kernel32.GetCurrentProcess
    current_process.restype = ctypes.c_void_p
    memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
    memory_info.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(_ProcessMemoryCounters),
        ctypes.c_ulong,
    )
    memory_info.restype = ctypes.c_int
    process = current_process()
    success = memory_info(
        process, ctypes.byref(counters), counters.cb
    )
    if not success:
        raise SpineError("Phase 10 benchmark could not read process memory")
    return int(counters.WorkingSetSize)


def _outside_repository(path: Path) -> None:
    resolved = path.resolve()
    repository = REPO_ROOT.resolve()
    if resolved == repository or repository in resolved.parents:
        raise SpineError("Phase 10 benchmark temporary directory is inside the repository")


def _array_bytes(batch: Any) -> int:
    arrays = (
        batch.null_contrasts,
        batch.null_valid,
        batch.null_yearly_contrasts,
        batch.null_yearly_valid,
        batch.null_statistics,
    )
    return sum(int(array.nbytes) for array in arrays)


def run_cost_benchmark(root: Path, replications: tuple[int, ...]) -> None:
    """Print only wiring, scale, time, memory, and cleanup facts."""
    if not replications or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 2
        for value in replications
    ):
        raise SpineError("benchmark replication counts must be built-in integers >= 2")
    temporary = Path(tempfile.mkdtemp(prefix="mnq_phase10_cost_"))
    _outside_repository(temporary)
    deleted = False
    try:
        corpus = load_formal_corpus(root)
        print(
            json.dumps(
                {
                    "kind": "wiring",
                    **artifact_metadata(),
                    "sessions": int(corpus.session_ids.size),
                    "anchors_per_session": int(corpus.observation_grid.size),
                    "rows": int(corpus.state_codes.size),
                    "weighting_planes": 2,
                    "lattice_cells_per_plane": 15,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        for count in replications:
            marker = temporary / f"b{count}.json"
            marker.write_text(
                json.dumps(
                    {
                        "replications": count,
                        "rows": int(corpus.state_codes.size),
                        "effective_null_strata": corpus.metadata[
                            "effective_null_strata"
                        ],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            temporary_bytes = sum(
                int(path.stat().st_size) for path in temporary.iterdir() if path.is_file()
            )
            tracemalloc.start()
            started = time.perf_counter()
            with _RssSampler() as sampler:
                def progress(completed: int) -> None:
                    if sampler.peak >= _RSS_STOP_BYTES:
                        raise SpineError(
                            "Phase 10 cost benchmark reached its 4 GB RSS stop boundary"
                        )
                    if completed % 10 == 0 or completed == count:
                        print(
                            json.dumps(
                                {
                                    "kind": "progress",
                                    "replications": count,
                                    "completed": completed,
                                    "sampled_rss_bytes": sampler.peak,
                                },
                                sort_keys=True,
                            ),
                            flush=True,
                        )

                batch = evaluate_null_surfaces(corpus, count, progress)
            wall = time.perf_counter() - started
            _, traced_peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            print(
                json.dumps(
                    {
                        "kind": "cost",
                        "replications": count,
                        "wall_seconds": wall,
                        "peak_rss_bytes": sampler.peak,
                        "peak_traced_bytes": int(traced_peak),
                        "temporary_output_bytes": temporary_bytes,
                        "result_array_bytes": _array_bytes(batch),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            del batch
    finally:
        shutil.rmtree(temporary, ignore_errors=False)
        deleted = not temporary.exists()
        print(
            json.dumps(
                {
                    "kind": "cleanup",
                    "temporary_directory_deleted": deleted,
                },
                sort_keys=True,
            ),
            flush=True,
        )


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("replications", nargs="+", type=int)
    args = parser.parse_args(argv)
    run_cost_benchmark(args.root, tuple(args.replications))


if __name__ == "__main__":
    main()
