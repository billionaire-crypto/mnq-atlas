"""Phase 8 Step 7 runner, checkpoint coordinator, and aggregate memory gate.

Launch only as ``python -m mnq_lab.phase8.runner``.  The public entry has no
corpus or path argument: the sole input is the fixed, ratification-guarded Unit
O tree.  Private dependency seams exist only for synthetic tests.
"""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import platform
import sys
import threading
import time
from typing import Any, Callable, Iterable, Mapping

import numpy as np

from mnq_lab import SpineError
from mnq_lab.constants import REPO_ROOT
from mnq_lab.ledger.ratification import require_ratified_unit_o
from mnq_lab.phase8 import progress as _progress
from mnq_lab.phase8.production import _contrast_worker_count as _stage1_worker_count
from mnq_lab.phase8.artifacts import (
    CheckpointIdentity,
    CheckpointStore,
    canonical_json_bytes,
    write_phase8_artifacts,
)

RATIFIED_INPUT_ROOT = (
    REPO_ROOT / "data/exploration/derived/phase7-unit-o-session-aware-v2"
)
PHASE8_OUTPUT_ROOT = REPO_ROOT / "data/exploration/derived/phase8-first-run-v1"
# A real log file beside the output root. The first production attempt wrote
# to a shell redirect that stayed empty for three hours, so progress must land
# in a file this package owns and flushes itself.
PHASE8_PROGRESS_LOG = REPO_ROOT / "data/exploration/derived/phase8-first-run-v1.progress.log"
DEFAULT_AGGREGATE_MEMORY_CEILING_BYTES = int(5.5 * 1024**3)
DEFAULT_LAUNCH_MINIMUM_AVAILABLE_BYTES = 7 * 1024**3

LIMITATIONS = (
    "Gate passage and the audit verdict are attestations, not mechanical proof.",
    "Result visibility rests on a corroborated but externally unanchored timestamp.",
    "Append-only is repository policy rather than code.",
    "The reproduction evidence is empirical byte identity, not structural proof that computation code was unchanged.",
)


def default_process_start_method() -> str:
    return "spawn" if os.name == "nt" else "fork"


@dataclass(frozen=True)
class RunnerOperatingConfig:
    workers: int = max(1, os.cpu_count() or 1)
    aggregate_memory_ceiling_bytes: int = DEFAULT_AGGREGATE_MEMORY_CEILING_BYTES
    launch_minimum_available_bytes: int = DEFAULT_LAUNCH_MINIMUM_AVAILABLE_BYTES
    process_start_method: str = default_process_start_method()

    def __post_init__(self) -> None:
        if isinstance(self.workers, bool) or not isinstance(self.workers, int) or self.workers <= 0:
            raise SpineError("Phase 8 workers must be a positive integer")
        if (
            isinstance(self.aggregate_memory_ceiling_bytes, bool)
            or not isinstance(self.aggregate_memory_ceiling_bytes, int)
            or self.aggregate_memory_ceiling_bytes <= 0
        ):
            raise SpineError("Phase 8 aggregate memory ceiling must be positive")
        if (
            isinstance(self.launch_minimum_available_bytes, bool)
            or not isinstance(self.launch_minimum_available_bytes, int)
            or self.launch_minimum_available_bytes <= 0
        ):
            raise SpineError("Phase 8 launch minimum memory must be positive")
        if self.process_start_method not in {"spawn", "fork"}:
            raise SpineError("Phase 8 process start method must be 'spawn' or 'fork'")
        if self.process_start_method == "fork" and os.name == "nt":
            raise SpineError("Phase 8 process start method 'fork' is unavailable on Windows")


@dataclass(frozen=True)
class RatifiedPhase8Inputs:
    certificate: Mapping[str, Any]
    run_manifest: Mapping[str, Any]
    unit_o_manifest: Mapping[str, Any]
    phase7_manifest: Mapping[str, Any]
    manifest_sha256: tuple[tuple[str, str], ...]


def _canonical_document(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpineError(f"invalid canonical input manifest {path.name}") from exc
    canonical = (json.dumps(document, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("utf-8")
    if payload != canonical:
        raise SpineError(f"input manifest {path.name} is not canonical")
    return document


def _open_fixed_input_manifests() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return (
        _canonical_document(RATIFIED_INPUT_ROOT / "run_manifest.json"),
        _canonical_document(RATIFIED_INPUT_ROOT / "unit_o/manifest.json"),
        _canonical_document(RATIFIED_INPUT_ROOT / "phase7/manifest.json"),
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_ratified_inputs() -> RatifiedPhase8Inputs:
    """Pass the certificate choke point before opening any real input manifest."""
    certificate = require_ratified_unit_o(RATIFIED_INPUT_ROOT)
    run, unit, phase7 = _open_fixed_input_manifests()
    hashes = (
        ("run", _sha256(RATIFIED_INPUT_ROOT / "run_manifest.json")),
        ("unit_o", _sha256(RATIFIED_INPUT_ROOT / "unit_o/manifest.json")),
        ("phase7", _sha256(RATIFIED_INPUT_ROOT / "phase7/manifest.json")),
    )
    return RatifiedPhase8Inputs(certificate, run, unit, phase7, hashes)


def _available_memory_bytes() -> int:
    if os.name == "nt":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise SpineError("Windows available-memory query failed")
        return int(status.ullAvailPhys)
    page_size = os.sysconf("SC_PAGE_SIZE")
    available_pages = os.sysconf("SC_AVPHYS_PAGES")
    return int(page_size * available_pages)


def _linux_process_tree_rss(root_pid: int) -> int:
    proc = Path("/proc")
    parent_by_pid: dict[int, int] = {}
    rss_by_pid: dict[int, int] = {}
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            status = (entry / "status").read_text(encoding="ascii")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        fields = {}
        for line in status.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key] = value.strip()
        try:
            pid = int(entry.name)
            parent_by_pid[pid] = int(fields["PPid"].split()[0])
            rss_by_pid[pid] = int(fields.get("VmRSS", "0 kB").split()[0]) * 1024
        except (KeyError, ValueError):
            continue
    descendants = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, parent in parent_by_pid.items():
            if parent in descendants and pid not in descendants:
                descendants.add(pid)
                changed = True
    return sum(rss_by_pid.get(pid, 0) for pid in descendants)


def _windows_process_tree_rss(root_pid: int) -> int:
    # Toolhelp supplies one coherent parent map; GetProcessMemoryInfo then sums
    # the working set of the parent and every recursively discovered worker.
    import ctypes.wintypes as wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]

    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    invalid_handle = ctypes.c_void_p(-1).value
    if snapshot == invalid_handle:
        raise SpineError("Windows process-tree snapshot failed")
    parents: dict[int, int] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    descendants = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, parent in parents.items():
            if parent in descendants and pid not in descendants:
                descendants.add(pid)
                changed = True
    total = 0
    for pid in descendants:
        handle = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
        if not handle:
            continue
        try:
            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(counters)
            if psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.cb
            ):
                total += int(counters.WorkingSetSize)
        finally:
            kernel32.CloseHandle(handle)
    if total <= 0:
        raise SpineError("Windows aggregate-memory query found no readable process")
    return total


def aggregate_process_tree_rss_bytes() -> int:
    if os.name == "nt":
        return _windows_process_tree_rss(os.getpid())
    if sys.platform.startswith("linux"):
        return _linux_process_tree_rss(os.getpid())
    raise SpineError(f"aggregate memory measurement is unsupported on {platform.system()}")


class AggregateMemoryGate:
    def __init__(
        self,
        *,
        ceiling_bytes: int,
        launch_minimum_available_bytes: int,
        aggregate_sampler: Callable[[], int] = aggregate_process_tree_rss_bytes,
        available_sampler: Callable[[], int] = _available_memory_bytes,
    ) -> None:
        self.ceiling_bytes = int(ceiling_bytes)
        self.launch_minimum_available_bytes = int(launch_minimum_available_bytes)
        self._aggregate_sampler = aggregate_sampler
        self._available_sampler = available_sampler
        self.peak_bytes = 0
        self._breach: int | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def preflight(self) -> int:
        available = int(self._available_sampler())
        if available < self.launch_minimum_available_bytes:
            raise SpineError(
                f"Phase 8 available memory preflight found {available} bytes, below "
                f"the declared minimum {self.launch_minimum_available_bytes}"
            )
        return available

    def sample(self) -> int:
        current = int(self._aggregate_sampler())
        self.peak_bytes = max(self.peak_bytes, current)
        if current > self.ceiling_bytes:
            self._breach = current
            raise SpineError(
                f"aggregate Phase 8 memory {current} exceeded ceiling {self.ceiling_bytes}"
            )
        return current

    def _monitor(self) -> None:
        while not self._stop.wait(0.5):
            try:
                self.sample()
            except SpineError:
                return

    def start(self) -> None:
        self.sample()
        self._stop.clear()
        self._thread = threading.Thread(target=self._monitor, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._breach is not None:
            raise SpineError(
                f"aggregate Phase 8 memory {self._breach} exceeded ceiling {self.ceiling_bytes}"
            )


@dataclass(frozen=True)
class InventoryChunk:
    index: int
    row_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if isinstance(self.index, bool) or not isinstance(self.index, int) or self.index < 0:
            raise SpineError("inventory chunk index must be a nonnegative integer")
        if not isinstance(self.row_ids, tuple) or not self.row_ids:
            raise SpineError("inventory chunk row ids must be a nonempty tuple")
        if len(set(self.row_ids)) != len(self.row_ids):
            raise SpineError("inventory chunk contains a duplicate declared row")


def execute_checkpointed_chunks(
    chunks: Iterable[InventoryChunk],
    *,
    checkpoint: CheckpointStore,
    compute_chunk: Callable[[InventoryChunk], Mapping[str, np.ndarray]],
    memory_gate: AggregateMemoryGate | None = None,
    interrupt_after_chunks: int | None = None,
) -> dict[str, np.ndarray]:
    declared = tuple(chunks)
    if any(not isinstance(chunk, InventoryChunk) for chunk in declared):
        raise SpineError("runner chunks must contain InventoryChunk values")
    if tuple(chunk.index for chunk in declared) != tuple(range(len(declared))):
        raise SpineError("inventory chunks must use contiguous structural indices")
    all_ids = tuple(row_id for chunk in declared for row_id in chunk.row_ids)
    if len(set(all_ids)) != len(all_ids):
        raise SpineError("inventory chunks contain a duplicate declared row")
    if memory_gate is not None:
        memory_gate.preflight()
        memory_gate.start()
    completed_now = 0
    chunk_progress = _progress.get_sink().phase(
        _progress.PHASE_BOOTSTRAP_CHUNKS, len(declared)
    )
    try:
        for chunk_position, chunk in enumerate(declared, start=1):
            if not checkpoint.has_chunk(chunk.index):
                columns = dict(compute_chunk(chunk))
                emitted = tuple(str(value) for value in np.asarray(columns.get("row_id", ())))
                if emitted != chunk.row_ids:
                    raise SpineError("checkpoint chunk differs from its declared row order")
                checkpoint.write_chunk(chunk.index, columns)
                completed_now += 1
                if memory_gate is not None:
                    memory_gate.sample()
            chunk_progress.advance(chunk_position)
            if interrupt_after_chunks is not None and completed_now >= interrupt_after_chunks:
                raise RuntimeError("named interruption")
        pieces = tuple(checkpoint.read_chunk(chunk.index) for chunk in declared)
        names = tuple(pieces[0]) if pieces else ()
        if any(tuple(piece) != names for piece in pieces):
            raise SpineError("checkpoint chunks have inconsistent schemas")
        combined = {
            name: np.concatenate(tuple(piece[name] for piece in pieces))
            for name in names
        }
        if tuple(str(value) for value in combined.get("row_id", ())) != all_ids:
            raise SpineError("completed checkpoint union differs from declared inventory")
        return combined
    finally:
        if memory_gate is not None:
            memory_gate.stop()


def run_phase8(
    *,
    workers: int | None = None,
    aggregate_memory_ceiling_bytes: int = DEFAULT_AGGREGATE_MEMORY_CEILING_BYTES,
    launch_minimum_available_bytes: int = DEFAULT_LAUNCH_MINIMUM_AVAILABLE_BYTES,
    process_start_method: str | None = None,
) -> Mapping[str, Any]:
    """Run and checkpoint the complete Step 7 inventory from the fixed input."""
    if not _progress.is_configured():
        raise SpineError(
            "Phase 8 production progress is not configured; "
            "launch with: python -m mnq_lab.phase8.runner"
        )
    config = RunnerOperatingConfig(
        workers=max(1, os.cpu_count() or 1) if workers is None else workers,
        aggregate_memory_ceiling_bytes=aggregate_memory_ceiling_bytes,
        launch_minimum_available_bytes=launch_minimum_available_bytes,
        process_start_method=process_start_method or default_process_start_method(),
    )
    gate = AggregateMemoryGate(
        ceiling_bytes=config.aggregate_memory_ceiling_bytes,
        launch_minimum_available_bytes=config.launch_minimum_available_bytes,
    )
    gate.preflight()
    guarded = load_ratified_inputs()
    from dataclasses import asdict
    from mnq_lab.phase8.production import (
        build_production_computation,
        interval_table_from_rows,
        open_production_inputs,
        production_provenance,
    )
    from mnq_lab.phase8.uncertainty import (
        BLOCK_LENGTHS,
        BootstrapInteractionRequest,
        _joint_bootstrap_intervals_with_plan_matrices,
        _prepare_joint_plan_matrices,
        bootstrap_contract,
    )
    from mnq_lab.spine.store import environment_fingerprint

    environment = environment_fingerprint(REPO_ROOT)
    if environment.get("dirty") is not False:
        raise SpineError("Phase 8 production requires a clean committed worktree")
    production_inputs = open_production_inputs(
        RATIFIED_INPUT_ROOT,
        run_manifest=guarded.run_manifest,
        unit_manifest=guarded.unit_o_manifest,
        phase7_manifest=guarded.phase7_manifest,
        input_manifest_sha256=guarded.manifest_sha256,
    )
    sink = _progress.get_sink()
    sink.banner(
        contrast_rows=29_430,
        day_type_rows=216,
        interaction_rows=720,
        workers=config.workers,
        stage1_workers=_stage1_worker_count(),
        aggregate_memory_ceiling_bytes=config.aggregate_memory_ceiling_bytes,
        distinct_bootstrap_terms=None,
    )
    gate.start()
    try:
        computation = build_production_computation(production_inputs)
        gate.sample()
    finally:
        gate.stop()
    # Realized distinct term count is not knowable until Stage 1 finishes; the
    # banner printed "pending" and the measured value is emitted here.
    sink.realized_terms(computation.distinct_term_count)

    contract = bootstrap_contract()
    contract_hash = hashlib.sha256(canonical_json_bytes(asdict(contract))).hexdigest()
    checkpoint = CheckpointStore(
        PHASE8_OUTPUT_ROOT.with_name(PHASE8_OUTPUT_ROOT.name + ".checkpoint"),
        CheckpointIdentity(
            code_commit=str(environment["commit"]),
            input_manifest_sha256=guarded.manifest_sha256,
            workers=config.workers,
            process_start_method=config.process_start_method,
            bootstrap_contract_sha256=contract_hash,
        ),
    )
    if checkpoint.has_plan_matrices():
        plan_bundle = checkpoint.read_plan_matrices(contract)
    else:
        plan_progress = sink.phase(
            _progress.PHASE_BOOTSTRAP_PLANS, len(BLOCK_LENGTHS)
        )
        gate.start()
        try:
            plan_bundle = _prepare_joint_plan_matrices(computation.group_ids)
            checkpoint.write_plan_matrices(plan_bundle)
            plan_progress.advance(len(BLOCK_LENGTHS))
            gate.sample()
        finally:
            gate.stop()
    request_tuple = computation.requests
    request_chunk_size = 512
    request_chunks = tuple(
        request_tuple[start : start + request_chunk_size]
        for start in range(0, len(request_tuple), request_chunk_size)
    )
    chunks = tuple(
        InventoryChunk(
            index,
            tuple(
                f"{request.request_id}:{block_length}"
                for request in requests
                for block_length in BLOCK_LENGTHS
            ),
        )
        for index, requests in enumerate(request_chunks)
    )
    def compute_interval_chunk(chunk: InventoryChunk) -> Mapping[str, np.ndarray]:
        selected_requests = request_chunks[chunk.index]
        needed: set[Hashable] = set()
        for request in selected_requests:
            if isinstance(request, BootstrapInteractionRequest):
                needed.update(request.term_ids)
            else:
                needed.add(request.target_term_id)
                if request.baseline_term_id is not None:
                    needed.add(request.baseline_term_id)
        selected_terms = computation.materialize_terms(needed)
        result = _joint_bootstrap_intervals_with_plan_matrices(
            computation.group_ids,
            selected_terms,
            selected_requests,
            plan_bundle,
            worker_count=config.workers,
            process_start_method=config.process_start_method,
        )
        rows: list[dict[str, Any]] = []
        for request_result in result.requests:
            for interval in request_result.intervals:
                rows.append({
                    "row_id": f"{request_result.request_id}:{interval.mean_block_sessions}",
                    "point_row_id": request_result.request_id,
                    "mean_block_sessions": interval.mean_block_sessions,
                    "draws": interval.draws,
                    "confidence_level": interval.confidence_level,
                    "ci_lower_ticks": interval.ci_lower_ticks,
                    "ci_upper_ticks": interval.ci_upper_ticks,
                    "interval_valid": interval.interval_valid,
                    "rng_root_entropy": json.dumps(interval.rng_root_entropy, separators=(",", ":")),
                    "rng_child_spawn_key": json.dumps(interval.rng_child_spawn_key, separators=(",", ":")),
                    "historical_mixture_disclosure": interval.historical_mixture_disclosure,
                    "conditioner_uncertainty_disclosure": interval.conditioner_uncertainty_disclosure,
                    "weight_ess_disclosure": interval.weight_ess_disclosure,
                })
        from mnq_lab.phase8.production import INTERVAL_COLUMNS
        table = interval_table_from_rows(rows)
        return dict(table.columns)

    interval_columns = execute_checkpointed_chunks(
        chunks,
        checkpoint=checkpoint,
        compute_chunk=compute_interval_chunk,
        memory_gate=gate,
    )
    from mnq_lab.phase8.artifacts import Phase8Table
    interval_table = Phase8Table("intervals", tuple(interval_columns.items()))
    tables = (
        computation.contrast_table,
        interval_table,
        computation.day_type_table,
        computation.interaction_table,
    )
    provenance = production_provenance(production_inputs, environment)
    operating = {
        "workers": config.workers,
        "stage1_workers": _stage1_worker_count(),
        "process_start_method": config.process_start_method,
        "aggregate_memory_ceiling_bytes": config.aggregate_memory_ceiling_bytes,
        "launch_minimum_available_bytes": config.launch_minimum_available_bytes,
        "aggregate_peak_memory_bytes": gate.peak_bytes,
        "declared_cell_counts": {
            "contrasts": 29_430, "day_type_descriptives": 216,
            "interactions": 720, "intervals": interval_table.row_count,
        },
        "realized_distinct_bootstrap_terms": computation.distinct_term_count,
    }
    artifact_progress = sink.phase(_progress.PHASE_ARTIFACTS, 1)
    manifest = write_phase8_artifacts(
        PHASE8_OUTPUT_ROOT,
        tables,
        provenance=provenance,
        operating=operating,
        limitations=LIMITATIONS,
    )
    artifact_progress.advance(1)
    return manifest


def main() -> None:
    if not getattr(sys.modules.get("__main__"), "__spec__", None):
        raise SpineError("launch Phase 8 only with: python -m mnq_lab.phase8.runner")
    _progress.configure(log_path=PHASE8_PROGRESS_LOG, stdout=True)
    try:
        run_phase8()
    finally:
        _progress.reset()


if __name__ == "__main__":
    main()


__all__ = [
    "AggregateMemoryGate", "InventoryChunk", "RunnerOperatingConfig",
    "execute_checkpointed_chunks", "load_ratified_inputs", "run_phase8",
]
