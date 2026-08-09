"""Phase 8 Step 7 runner, checkpoint coordinator, and aggregate memory gate.

Launch only as ``python -m mnq_lab.phase8.runner``.  The public entry has no
corpus or path argument: the sole input is the fixed, ratification-guarded Unit
O tree.  Private dependency seams exist only for synthetic tests.
"""

from __future__ import annotations

import argparse
import _thread
from dataclasses import dataclass
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import sys
import threading
import time
from typing import Any, Callable, Iterable, Mapping

import numpy as np

from mnq_lab import SpineError
from mnq_lab.constants import REPO_ROOT
from mnq_lab.ledger.ratification import require_ratified_unit_o
from mnq_lab.phase8 import progress as _progress
from mnq_lab.phase8.artifacts import (
    CheckpointIdentity,
    CheckpointStore,
    canonical_json_bytes,
    write_phase8_artifacts,
)

RATIFIED_INPUT_ROOT = (
    REPO_ROOT / "data/exploration/derived/phase7-unit-o-session-aware-v2"
)
PHASE8_OUTPUT_ROOT = REPO_ROOT / "data/exploration/derived/phase8-session-aware-v2"
PHASE8_STAGING_ROOT = PHASE8_OUTPUT_ROOT.with_name(PHASE8_OUTPUT_ROOT.name + ".staging")
PHASE8_CHECKPOINT_ROOT = PHASE8_OUTPUT_ROOT.with_name(
    PHASE8_OUTPUT_ROOT.name + ".checkpoint"
)
# A real log file beside the output root. The first production attempt wrote
# to a shell redirect that stayed empty for three hours, so progress must land
# in a file this package owns and flushes itself.
PHASE8_PROGRESS_LOG = PHASE8_OUTPUT_ROOT.with_name(
    PHASE8_OUTPUT_ROOT.name + ".progress.log"
)
# Attempt 002 durably recorded a 17.36 GB Stage 1 PSS peak before the fixed
# 16 GiB stop. The pod preflight recorded 251.40 GB effectively available.
# Keep a substantial fixed boundary below that measured capacity: 192 GiB for
# the Phase 8 process tree, with launch requiring 224 GiB effectively free.
# This preserves more than 40 GB of observed host headroom instead of setting
# the gate equal to the cgroup/physical maximum.
DEFAULT_AGGREGATE_MEMORY_CEILING_BYTES = 192 * 1024**3
DEFAULT_LAUNCH_MINIMUM_AVAILABLE_BYTES = 224 * 1024**3
# Linux PSS requires a page-table walk through every Phase 8 process.  At the
# observed Stage 1 footprint, sampling it every 0.5 seconds became effectively
# continuous and competed with the workers.  Thirty seconds bounds the delay
# to the emergency stop while preserving at least 32 GiB between the fixed
# process-tree ceiling and the fixed launch-capacity requirement.
DEFAULT_AGGREGATE_MEMORY_SAMPLE_INTERVAL_SECONDS = 30.0
AGGREGATE_MEMORY_CEILING_BASIS = {
    "schema_version": "phase8-memory-ceiling-basis-v2",
    "failed_attempt_execution_receipt_sha256": (
        "8c89ad96b9f238016571686bae5a66706d2ee6be8bc1cbe2b127d3d4ec8bfc8b"
    ),
    "recorded_stage1_process_tree_pss_peak_bytes": 17_357_831_168,
    "recorded_effective_available_bytes": 251_401_981_952,
    "rationale": (
        "fixed 192 GiB process-tree PSS ceiling remains more than 40 GB below "
        "the pod capacity recorded by attempt 002, while a separate 224 GiB "
        "launch minimum preserves pre-launch headroom and the fail-closed "
        "emergency stop"
    ),
}
PHASE8_OUTPUT_VERSION = "phase8-session-aware-v2"

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
    stage1_workers: int
    bootstrap_workers: int
    effective_cpu_count: int
    aggregate_memory_ceiling_bytes: int = DEFAULT_AGGREGATE_MEMORY_CEILING_BYTES
    launch_minimum_available_bytes: int = DEFAULT_LAUNCH_MINIMUM_AVAILABLE_BYTES
    process_start_method: str = default_process_start_method()

    def __post_init__(self) -> None:
        for label, value in (
            ("Stage 1 workers", self.stage1_workers),
            ("bootstrap workers", self.bootstrap_workers),
            ("effective CPU count", self.effective_cpu_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise SpineError(f"Phase 8 {label} must be a positive integer")
        if self.stage1_workers > self.effective_cpu_count:
            raise SpineError("Phase 8 Stage 1 workers exceed effective available CPUs")
        if self.bootstrap_workers > self.effective_cpu_count:
            raise SpineError("Phase 8 bootstrap workers exceed effective available CPUs")
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


def _parse_cpuset(raw: str) -> tuple[int, ...]:
    cpus: set[int] = set()
    if not isinstance(raw, str) or not raw.strip():
        raise SpineError("cgroup cpuset observation is empty")
    try:
        for component in raw.strip().split(","):
            bounds = component.split("-", 1)
            start = int(bounds[0])
            stop = int(bounds[-1])
            if start < 0 or stop < start:
                raise ValueError
            cpus.update(range(start, stop + 1))
    except ValueError as exc:
        raise SpineError("cgroup cpuset observation is invalid") from exc
    if not cpus:
        raise SpineError("cgroup cpuset observation contains no CPU")
    return tuple(sorted(cpus))


def _linux_cgroup_locations(
    *,
    reader: Callable[[Path], str] = lambda path: path.read_text(encoding="ascii"),
) -> dict[str, Path]:
    try:
        lines = reader(Path("/proc/self/cgroup")).splitlines()
    except OSError as exc:
        raise SpineError("cannot inspect Linux process cgroup membership") from exc
    result: dict[str, Path] = {}
    for line in lines:
        parts = line.split(":", 2)
        if len(parts) != 3:
            raise SpineError("Linux process cgroup membership is malformed")
        hierarchy, controllers, relative = parts
        relative_path = relative.lstrip("/")
        if hierarchy == "0" and controllers == "":
            result["v2"] = Path("/sys/fs/cgroup") / relative_path
        else:
            for controller in controllers.split(","):
                if controller:
                    result[controller] = Path("/sys/fs/cgroup") / controller / relative_path
    if not result:
        raise SpineError("Linux process cgroup membership is empty")
    return result


def _windows_affinity_cpus() -> tuple[int, ...]:
    process = ctypes.windll.kernel32.GetCurrentProcess()
    process_mask = ctypes.c_size_t()
    system_mask = ctypes.c_size_t()
    if not ctypes.windll.kernel32.GetProcessAffinityMask(
        process, ctypes.byref(process_mask), ctypes.byref(system_mask)
    ):
        raise SpineError("cannot inspect Windows process affinity")
    mask = int(process_mask.value)
    cpus = tuple(index for index in range(ctypes.sizeof(ctypes.c_size_t) * 8) if mask & (1 << index))
    if not cpus:
        raise SpineError("Windows process affinity contains no CPU")
    return cpus


def resolve_effective_cpu_capacity(observations: Mapping[str, Any]) -> dict[str, Any]:
    raw_os_count = observations.get("os_cpu_count")
    affinity = observations.get("affinity_cpus")
    if isinstance(raw_os_count, bool) or not isinstance(raw_os_count, int) or raw_os_count <= 0:
        raise SpineError("os.cpu_count() did not provide a coherent CPU capacity")
    if not isinstance(affinity, tuple) or not affinity or any(
        isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in affinity
    ):
        raise SpineError("process affinity could not be determined coherently")
    counts = {"os_cpu_count": raw_os_count, "affinity_count": len(set(affinity))}
    quota_count = observations.get("cgroup_quota_count")
    if quota_count is not None:
        if isinstance(quota_count, bool) or not isinstance(quota_count, int) or quota_count <= 0:
            raise SpineError("cgroup CPU quota is incoherent")
        counts["cgroup_quota_count"] = quota_count
    cpuset = observations.get("cgroup_cpuset_cpus")
    if cpuset is not None:
        if not isinstance(cpuset, tuple) or not cpuset:
            raise SpineError("cgroup cpuset is incoherent")
        counts["cgroup_cpuset_count"] = len(set(cpuset))
    effective = min(counts.values())
    if effective <= 0:
        raise SpineError("effective CPU capacity is zero")
    return {**dict(observations), **counts, "effective_cpu_count": effective}


def probe_effective_cpu_capacity(
    *,
    platform_name: str | None = None,
    os_cpu_count_fn: Callable[[], int | None] = os.cpu_count,
    affinity_fn: Callable[[], Iterable[int]] | None = None,
    reader: Callable[[Path], str] = lambda path: path.read_text(encoding="ascii"),
    exists: Callable[[Path], bool] = lambda path: path.is_file(),
) -> dict[str, Any]:
    """Resolve every enforceable CPU bound without changing host settings."""
    system = platform_name or platform.system()
    raw_os_count = os_cpu_count_fn()
    if affinity_fn is not None:
        try:
            affinity = tuple(sorted(set(int(cpu) for cpu in affinity_fn())))
        except Exception as exc:
            raise SpineError("cannot inspect process CPU affinity") from exc
    elif system == "Linux" and hasattr(os, "sched_getaffinity"):
        try:
            affinity = tuple(sorted(os.sched_getaffinity(0)))
        except OSError as exc:
            raise SpineError("cannot inspect Linux process CPU affinity") from exc
    elif system == "Windows":
        affinity = _windows_affinity_cpus()
    else:
        raise SpineError(f"CPU capacity inspection is unsupported on {system}")
    observation: dict[str, Any] = {
        "platform": system,
        "os_cpu_count": raw_os_count,
        "affinity_cpus": affinity,
        "cgroup_version": None,
        "cgroup_cpu_quota_raw": None,
        "cgroup_quota_count": None,
        "cgroup_cpuset_raw": None,
        "cgroup_cpuset_cpus": None,
    }
    if system == "Linux":
        locations = _linux_cgroup_locations(reader=reader)
        if "v2" in locations:
            root = locations["v2"]
            quota_path = root / "cpu.max"
            cpuset_paths = (root / "cpuset.cpus.effective", root / "cpuset.cpus")
            if not exists(quota_path):
                raise SpineError("Linux cgroup v2 CPU quota is unreadable")
            try:
                quota_raw = reader(quota_path).strip()
            except OSError as exc:
                raise SpineError("Linux cgroup v2 CPU quota is unreadable") from exc
            parts = quota_raw.split()
            if len(parts) != 2:
                raise SpineError("Linux cgroup v2 CPU quota is malformed")
            quota_count = None
            if parts[0] != "max":
                try:
                    quota, period = int(parts[0]), int(parts[1])
                except ValueError as exc:
                    raise SpineError("Linux cgroup v2 CPU quota is malformed") from exc
                if quota <= 0 or period <= 0:
                    raise SpineError("Linux cgroup v2 CPU quota is incoherent")
                quota_count = max(1, quota // period)
            cpuset_path = next((path for path in cpuset_paths if exists(path)), None)
            if cpuset_path is None:
                raise SpineError("Linux cgroup v2 cpuset is unreadable")
            try:
                cpuset_raw = reader(cpuset_path).strip()
            except OSError as exc:
                raise SpineError("Linux cgroup v2 cpuset is unreadable") from exc
            observation.update({
                "cgroup_version": 2,
                "cgroup_cpu_quota_path": quota_path.as_posix(),
                "cgroup_cpu_quota_raw": quota_raw,
                "cgroup_quota_count": quota_count,
                "cgroup_cpuset_path": cpuset_path.as_posix(),
                "cgroup_cpuset_raw": cpuset_raw,
                "cgroup_cpuset_cpus": _parse_cpuset(cpuset_raw),
            })
        else:
            cpu_root = locations.get("cpu") or locations.get("cpuacct")
            cpuset_root = locations.get("cpuset")
            if cpu_root is None or cpuset_root is None:
                raise SpineError("Linux cgroup v1 CPU controllers are unavailable")
            quota_path = cpu_root / "cpu.cfs_quota_us"
            period_path = cpu_root / "cpu.cfs_period_us"
            cpuset_path = cpuset_root / "cpuset.cpus"
            if not all(exists(path) for path in (quota_path, period_path, cpuset_path)):
                raise SpineError("Linux cgroup v1 CPU limits are unreadable")
            try:
                quota_raw, period_raw, cpuset_raw = (
                    reader(quota_path).strip(), reader(period_path).strip(),
                    reader(cpuset_path).strip(),
                )
                quota, period = int(quota_raw), int(period_raw)
            except (OSError, ValueError) as exc:
                raise SpineError("Linux cgroup v1 CPU limits are malformed") from exc
            quota_count = None if quota < 0 else max(1, quota // period)
            if quota == 0 or period <= 0:
                raise SpineError("Linux cgroup v1 CPU quota is incoherent")
            observation.update({
                "cgroup_version": 1,
                "cgroup_cpu_quota_path": quota_path.as_posix(),
                "cgroup_cpu_period_path": period_path.as_posix(),
                "cgroup_cpu_quota_raw": {"quota": quota_raw, "period": period_raw},
                "cgroup_quota_count": quota_count,
                "cgroup_cpuset_path": cpuset_path.as_posix(),
                "cgroup_cpuset_raw": cpuset_raw,
                "cgroup_cpuset_cpus": _parse_cpuset(cpuset_raw),
            })
    return resolve_effective_cpu_capacity(observation)


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


def require_phase8_run_paths(
    *,
    progress_log: Path,
    resume: bool,
) -> None:
    """Enforce fresh/resume path state without deleting or repairing evidence."""
    expected = {
        "staging": PHASE8_OUTPUT_ROOT.with_name(PHASE8_OUTPUT_ROOT.name + ".staging"),
        "checkpoint": PHASE8_OUTPUT_ROOT.with_name(PHASE8_OUTPUT_ROOT.name + ".checkpoint"),
        "progress": PHASE8_OUTPUT_ROOT.with_name(PHASE8_OUTPUT_ROOT.name + ".progress.log"),
    }
    if PHASE8_STAGING_ROOT != expected["staging"]:
        raise SpineError("Phase 8 staging root is not bound to the fixed v2 output root")
    if PHASE8_CHECKPOINT_ROOT != expected["checkpoint"]:
        raise SpineError("Phase 8 checkpoint root is not bound to the fixed v2 output root")
    if PHASE8_PROGRESS_LOG != expected["progress"]:
        raise SpineError("Phase 8 progress log is not bound to the fixed v2 output root")
    if resume:
        if progress_log == PHASE8_PROGRESS_LOG or progress_log.parent != PHASE8_PROGRESS_LOG.parent:
            raise SpineError("Phase 8 resume requires a new bound per-attempt progress log")
        if not progress_log.name.startswith(PHASE8_PROGRESS_LOG.name + ".resume-"):
            raise SpineError("Phase 8 resume progress log name is not bound to the logical run")
        candidates = [PHASE8_OUTPUT_ROOT, PHASE8_STAGING_ROOT, progress_log]
    else:
        if progress_log != PHASE8_PROGRESS_LOG:
            raise SpineError("Phase 8 fresh progress log differs from the fixed path")
        candidates = [
            PHASE8_OUTPUT_ROOT, PHASE8_STAGING_ROOT, PHASE8_CHECKPOINT_ROOT,
            PHASE8_PROGRESS_LOG,
        ]
    resolved = [Path(path).resolve() for path in candidates]
    if len(resolved) != len(set(resolved)):
        raise SpineError("Phase 8 fixed v2 run paths overlap")
    if RATIFIED_INPUT_ROOT.resolve() in resolved:
        raise SpineError("Phase 8 output paths alias the ratified Unit O input")
    for path in candidates:
        if Path(path).exists():
            raise SpineError(f"Phase 8 fixed production path must be absent: {path}")


def require_absent_phase8_run_paths(*, include_progress_log: bool) -> None:
    """Backward-compatible fresh-mode absence check used by focused tests."""
    if not include_progress_log:
        candidates = (PHASE8_OUTPUT_ROOT, PHASE8_STAGING_ROOT, PHASE8_CHECKPOINT_ROOT)
        for path in candidates:
            if Path(path).exists():
                raise SpineError(f"Phase 8 fixed production path must be absent: {path}")
        return
    require_phase8_run_paths(progress_log=PHASE8_PROGRESS_LOG, resume=False)


def validate_external_checkpoint_root(path: Path, *, resume: bool) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise SpineError("external checkpoint root must be absolute")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve())
    except ValueError:
        pass
    else:
        raise SpineError("external checkpoint root must be outside the repository")
    identity_staging = resolved.with_name(f".{resolved.name}.identity.staging")
    if identity_staging.exists():
        raise SpineError("incomplete external checkpoint identity staging evidence exists")
    if resume:
        if not resolved.is_dir():
            raise SpineError("resume external checkpoint root must exist")
    elif resolved.exists():
        raise SpineError("fresh external checkpoint root must be absent")
    return resolved


def _physical_available_memory_bytes() -> int:
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


def available_memory_observation() -> dict[str, Any]:
    """Return physical availability bounded by an enforceable cgroup limit."""
    physical_available = _physical_available_memory_bytes()
    observation: dict[str, Any] = {
        "physical_available_bytes": physical_available,
        "cgroup_version": None,
        "cgroup_memory_current_bytes": None,
        "cgroup_memory_limit_bytes": None,
        "effective_available_bytes": physical_available,
        "source": "physical_available_memory",
    }
    if not sys.platform.startswith("linux"):
        return observation
    locations = _linux_cgroup_locations()
    if "v2" in locations:
        root = locations["v2"]
        current_path, limit_path = root / "memory.current", root / "memory.max"
        try:
            current_raw = current_path.read_text(encoding="ascii").strip()
            limit_raw = limit_path.read_text(encoding="ascii").strip()
            current = int(current_raw)
            limit = None if limit_raw == "max" else int(limit_raw)
        except (OSError, ValueError) as exc:
            raise SpineError("Linux cgroup v2 memory capacity is unreadable") from exc
        if current < 0 or (limit is not None and (limit <= 0 or current > limit)):
            raise SpineError("Linux cgroup v2 memory capacity is incoherent")
        effective = physical_available if limit is None else min(physical_available, limit - current)
        observation.update({
            "cgroup_version": 2,
            "cgroup_memory_current_bytes": current,
            "cgroup_memory_limit_bytes": limit,
            "cgroup_memory_current_path": current_path.as_posix(),
            "cgroup_memory_limit_path": limit_path.as_posix(),
            "effective_available_bytes": effective,
            "source": "minimum of physical available and cgroup v2 headroom",
        })
    else:
        root = locations.get("memory")
        if root is None:
            raise SpineError("Linux cgroup memory controller is unavailable")
        current_path, limit_path = root / "memory.usage_in_bytes", root / "memory.limit_in_bytes"
        try:
            current = int(current_path.read_text(encoding="ascii").strip())
            limit = int(limit_path.read_text(encoding="ascii").strip())
        except (OSError, ValueError) as exc:
            raise SpineError("Linux cgroup v1 memory capacity is unreadable") from exc
        if current < 0 or limit <= 0 or current > limit:
            raise SpineError("Linux cgroup v1 memory capacity is incoherent")
        effective = min(physical_available, limit - current)
        observation.update({
            "cgroup_version": 1,
            "cgroup_memory_current_bytes": current,
            "cgroup_memory_limit_bytes": limit,
            "cgroup_memory_current_path": current_path.as_posix(),
            "cgroup_memory_limit_path": limit_path.as_posix(),
            "effective_available_bytes": effective,
            "source": "minimum of physical available and cgroup v1 headroom",
        })
    if observation["effective_available_bytes"] <= 0:
        raise SpineError("effective available memory is zero")
    return observation


def _available_memory_bytes() -> int:
    return int(available_memory_observation()["effective_available_bytes"])


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


def _linux_process_tree_pids(root_pid: int) -> tuple[int, ...]:
    parent_by_pid: dict[int, int] = {}
    try:
        entries = tuple(Path("/proc").iterdir())
    except OSError as exc:
        raise SpineError("Linux process inventory is unreadable") from exc
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            status = (entry / "status").read_text(encoding="ascii")
            parent_line = next(line for line in status.splitlines() if line.startswith("PPid:"))
            parent_by_pid[int(entry.name)] = int(parent_line.split()[1])
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        except (StopIteration, ValueError) as exc:
            raise SpineError("Linux process parent metadata is malformed") from exc
    if root_pid not in parent_by_pid and root_pid != os.getpid():
        raise SpineError("Linux memory root process is absent")
    descendants = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, parent in parent_by_pid.items():
            if parent in descendants and pid not in descendants:
                descendants.add(pid)
                changed = True
    return tuple(sorted(descendants))


def _linux_process_tree_pss(root_pid: int) -> int:
    """Sum PSS, which proportionally allocates rather than duplicates shared pages."""
    total_kib = 0
    read_count = 0
    for pid in _linux_process_tree_pids(root_pid):
        try:
            rollup = (Path("/proc") / str(pid) / "smaps_rollup").read_text(encoding="ascii")
        except (FileNotFoundError, ProcessLookupError):
            # A child that exited after the coherent parent snapshot contributes
            # no continuing memory and is safe to omit.
            continue
        except (OSError, PermissionError) as exc:
            raise SpineError("Linux process-tree PSS is unreadable") from exc
        values = [line for line in rollup.splitlines() if line.startswith("Pss:")]
        if len(values) != 1:
            raise SpineError("Linux process-tree PSS is malformed")
        try:
            total_kib += int(values[0].split()[1])
        except (IndexError, ValueError) as exc:
            raise SpineError("Linux process-tree PSS is malformed") from exc
        read_count += 1
    if read_count == 0 or total_kib <= 0:
        raise SpineError("Linux process-tree PSS found no readable process")
    return total_kib * 1024


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


@dataclass(frozen=True)
class MemoryMeasurement:
    bytes: int
    metric: str
    source: str

    def __post_init__(self) -> None:
        if isinstance(self.bytes, bool) or not isinstance(self.bytes, int) or self.bytes <= 0:
            raise SpineError("aggregate memory measurement must be a positive integer")
        if not self.metric or not self.source:
            raise SpineError("aggregate memory measurement metadata is absent")


def aggregate_memory_measurement() -> MemoryMeasurement:
    if os.name == "nt":
        return MemoryMeasurement(
            _windows_process_tree_rss(os.getpid()),
            "process_tree_working_set_bytes", "Windows Toolhelp/GetProcessMemoryInfo",
        )
    if sys.platform.startswith("linux"):
        # cgroup memory.current includes reclaimable file cache charged while
        # hashing the governed input and witness trees.  That cache can exceed
        # the fixed process-memory ceiling even when the complete process tree
        # is nearly idle.  Enforce the fixed aggregate ceiling against PSS,
        # which accounts shared pages proportionally and excludes closed-file
        # cache.  Cgroup current/limit remain fail-closed launch-capacity inputs
        # in available_memory_observation().
        return MemoryMeasurement(
            _linux_process_tree_pss(os.getpid()),
            "process_tree_pss_bytes", "/proc/<pid>/smaps_rollup",
        )
    raise SpineError(f"aggregate memory measurement is unsupported on {platform.system()}")


def aggregate_process_tree_rss_bytes() -> int:
    """Compatibility shim returning the safer aggregate-accounted measurement."""
    return aggregate_memory_measurement().bytes


class AggregateMemoryGate:
    def __init__(
        self,
        *,
        ceiling_bytes: int,
        launch_minimum_available_bytes: int,
        aggregate_sampler: Callable[[], int | MemoryMeasurement] = aggregate_memory_measurement,
        available_sampler: Callable[[], int] = _available_memory_bytes,
        failure_interrupt: Callable[[SpineError], None] | None = None,
        failure_terminate: Callable[[SpineError], None] | None = None,
        failure_recorder: Callable[[int, int, int], None] | None = None,
        monitor_interval_seconds: float = (
            DEFAULT_AGGREGATE_MEMORY_SAMPLE_INTERVAL_SECONDS
        ),
        hard_stop_grace_seconds: float = 5.0,
    ) -> None:
        self.ceiling_bytes = int(ceiling_bytes)
        self.launch_minimum_available_bytes = int(launch_minimum_available_bytes)
        self._aggregate_sampler = aggregate_sampler
        self._available_sampler = available_sampler
        self._failure_interrupt = failure_interrupt
        self._failure_terminate = failure_terminate
        self._failure_recorder = failure_recorder
        self._monitor_interval_seconds = float(monitor_interval_seconds)
        self._hard_stop_grace_seconds = float(hard_stop_grace_seconds)
        if self._monitor_interval_seconds <= 0 or self._hard_stop_grace_seconds <= 0:
            raise SpineError("Phase 8 memory-monitor timings must be positive")
        self.peak_bytes = 0
        self.current_bytes = 0
        self.metric: str | None = None
        self.source: str | None = None
        self._breach: int | None = None
        self._failure: SpineError | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sample_lock = threading.Lock()
        self._sample_count = 0
        self._sample_total_seconds = 0.0
        self._sample_max_seconds = 0.0

    @property
    def monitor_interval_seconds(self) -> float:
        return self._monitor_interval_seconds

    @property
    def monitor_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def sample_count(self) -> int:
        return self._sample_count

    @property
    def sample_total_seconds(self) -> float:
        return self._sample_total_seconds

    @property
    def sample_max_seconds(self) -> float:
        return self._sample_max_seconds

    @property
    def sample_mean_seconds(self) -> float:
        if self._sample_count == 0:
            return 0.0
        return self._sample_total_seconds / self._sample_count

    @property
    def stop_join_timeout_seconds(self) -> float:
        observed = self._sample_max_seconds if self._sample_count else 2.0
        return max(
            2.0,
            self._monitor_interval_seconds
            + self._hard_stop_grace_seconds
            + (2.0 * observed),
        )

    def sampling_observation(self) -> dict[str, int | float]:
        with self._sample_lock:
            count = self._sample_count
            total = self._sample_total_seconds
            maximum = self._sample_max_seconds
            return {
                "aggregate_memory_sample_interval_seconds": (
                    self._monitor_interval_seconds
                ),
                # This is an attempt count: failed measurements are timed too.
                "aggregate_memory_sample_count": count,
                "aggregate_memory_sample_total_seconds": total,
                "aggregate_memory_sample_mean_seconds": (
                    total / count if count else 0.0
                ),
                "aggregate_memory_sample_max_seconds": maximum,
            }

    def preflight(self) -> int:
        available = int(self._available_sampler())
        if available < self.launch_minimum_available_bytes:
            raise SpineError(
                f"Phase 8 available memory preflight found {available} bytes, below "
                f"the declared minimum {self.launch_minimum_available_bytes}"
            )
        return available

    def sample(self) -> int:
        with self._sample_lock:
            started = time.monotonic()
            try:
                try:
                    sampled = self._aggregate_sampler()
                except SpineError:
                    raise
                except Exception as exc:
                    raise SpineError(
                        "aggregate Phase 8 memory measurement failed"
                    ) from exc
            finally:
                elapsed = max(0.0, time.monotonic() - started)
                self._sample_count += 1
                self._sample_total_seconds += elapsed
                self._sample_max_seconds = max(
                    self._sample_max_seconds, elapsed
                )
            if isinstance(sampled, MemoryMeasurement):
                current = sampled.bytes
                if self.metric is None:
                    self.metric, self.source = sampled.metric, sampled.source
                elif (self.metric, self.source) != (sampled.metric, sampled.source):
                    raise SpineError(
                        "aggregate Phase 8 memory source changed during execution"
                    )
            elif (
                isinstance(sampled, bool)
                or not isinstance(sampled, int)
                or sampled <= 0
            ):
                raise SpineError("aggregate Phase 8 memory measurement is invalid")
            else:
                current = sampled
                if self.metric is None:
                    self.metric = "injected_aggregate_bytes"
                    self.source = "injected sampler"
            self.current_bytes = current
            self.peak_bytes = max(self.peak_bytes, current)
            if current > self.ceiling_bytes:
                self._breach = max(self._breach or 0, current)
                raise SpineError(
                    f"aggregate Phase 8 memory {current} exceeded ceiling "
                    f"{self.ceiling_bytes}"
                )
            return current

    def _monitor(self) -> None:
        while not self._stop.wait(self._monitor_interval_seconds):
            try:
                self.sample()
            except SpineError as exc:
                self._failure = exc
                if self._failure_recorder is not None and self._breach is not None:
                    try:
                        self._failure_recorder(
                            self.current_bytes,
                            self.peak_bytes,
                            self.ceiling_bytes,
                        )
                    except Exception as record_exc:
                        self._failure = SpineError(
                            "aggregate Phase 8 memory failure record could not be written"
                        )
                        self._failure.__cause__ = record_exc
                if self._failure_interrupt is not None:
                    try:
                        self._failure_interrupt(exc)
                    except Exception as action_exc:
                        self._failure = SpineError(
                            "aggregate Phase 8 memory emergency interrupt failed"
                        )
                        self._failure.__cause__ = action_exc
                deadline = time.monotonic() + self._hard_stop_grace_seconds
                while not self._stop.is_set():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    if self._stop.wait(min(self._monitor_interval_seconds, remaining)):
                        break
                    try:
                        current = self.sample()
                    except SpineError as followup:
                        self._failure = followup
                        current = self.current_bytes
                    if self._failure_recorder is not None and self._breach is not None:
                        try:
                            self._failure_recorder(
                                current, self.peak_bytes, self.ceiling_bytes
                            )
                        except Exception as record_exc:
                            self._failure = SpineError(
                                "aggregate Phase 8 memory failure record could not be written"
                            )
                            self._failure.__cause__ = record_exc
                if self._failure_terminate is not None and not self._stop.is_set():
                    self._failure_terminate(exc)
                return

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            raise SpineError("aggregate Phase 8 memory monitor is already running")
        self.sample()
        self._stop.clear()
        self._thread = threading.Thread(target=self._monitor, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        monitor_did_not_stop = False
        if self._thread is not None:
            join_timeout = self.stop_join_timeout_seconds
            self._thread.join(timeout=join_timeout)
            if self._thread.is_alive():
                # The final PSS walk can be slower than every earlier sample
                # because Stage 1 is at peak footprint.  Permit one complete,
                # equally bounded measurement window before failing closed.
                self._thread.join(timeout=join_timeout)
            if self._thread.is_alive():
                monitor_did_not_stop = True
            else:
                self._thread = None
        if self._breach is not None:
            raise SpineError(
                f"aggregate Phase 8 memory {self._breach} exceeded ceiling {self.ceiling_bytes}"
            )
        if monitor_did_not_stop:
            timeout_failure = SpineError(
                "aggregate Phase 8 memory monitor did not stop"
            )
            if self._failure is not None:
                raise timeout_failure from self._failure
            raise timeout_failure
        if self._failure is not None:
            raise SpineError("aggregate Phase 8 memory monitor failed closed") from self._failure


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
    checkpoint.validate_chunk_inventory(chunk.index for chunk in declared)
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
    stage1_workers: int,
    bootstrap_workers: int,
    resume: bool = False,
    external_checkpoint_root: Path | None = None,
    progress_log: Path = PHASE8_PROGRESS_LOG,
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
    for path in (PHASE8_OUTPUT_ROOT, PHASE8_STAGING_ROOT):
        if path.exists():
            raise SpineError(f"Phase 8 fixed production path must be absent: {path}")
    if not resume and PHASE8_CHECKPOINT_ROOT.exists():
        raise SpineError(
            f"Phase 8 fixed production path must be absent: {PHASE8_CHECKPOINT_ROOT}"
        )
    cpu_capacity = probe_effective_cpu_capacity()
    config = RunnerOperatingConfig(
        stage1_workers=stage1_workers,
        bootstrap_workers=bootstrap_workers,
        effective_cpu_count=int(cpu_capacity["effective_cpu_count"]),
        aggregate_memory_ceiling_bytes=aggregate_memory_ceiling_bytes,
        launch_minimum_available_bytes=launch_minimum_available_bytes,
        process_start_method=process_start_method or default_process_start_method(),
    )
    def interrupt_for_memory_failure(_failure: SpineError) -> None:
        _thread.interrupt_main()

    def terminate_for_memory_failure(_failure: SpineError) -> None:
        os.kill(os.getpid(), signal.SIGTERM)

    def record_memory_failure(
        current_bytes: int, peak_bytes: int, ceiling_bytes: int
    ) -> None:
        _progress.get_sink().memory_stop(
            current_bytes=current_bytes,
            peak_bytes=peak_bytes,
            ceiling_bytes=ceiling_bytes,
        )

    gate = AggregateMemoryGate(
        ceiling_bytes=config.aggregate_memory_ceiling_bytes,
        launch_minimum_available_bytes=config.launch_minimum_available_bytes,
        failure_interrupt=interrupt_for_memory_failure,
        failure_terminate=terminate_for_memory_failure,
        failure_recorder=record_memory_failure,
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
        bootstrap_workers=config.bootstrap_workers,
        stage1_workers=config.stage1_workers,
        aggregate_memory_ceiling_bytes=config.aggregate_memory_ceiling_bytes,
        distinct_bootstrap_terms=None,
        resume=resume,
        external_checkpoint=external_checkpoint_root is not None,
    )
    contract = bootstrap_contract()
    contract_hash = hashlib.sha256(canonical_json_bytes(asdict(contract))).hexdigest()
    producing_paths = (
        REPO_ROOT / "mnq_lab/phase8/runner.py",
        REPO_ROOT / "mnq_lab/phase8/production.py",
        REPO_ROOT / "mnq_lab/phase8/artifacts.py",
        REPO_ROOT / "mnq_lab/phase8/uncertainty.py",
    )
    producing_hashes = tuple(
        (path.relative_to(REPO_ROOT).as_posix(), _sha256(path))
        for path in producing_paths
    )
    mirror = None
    if external_checkpoint_root is not None:
        mirror = validate_external_checkpoint_root(
            external_checkpoint_root, resume=resume
        )
    checkpoint = CheckpointStore(
        PHASE8_CHECKPOINT_ROOT,
        CheckpointIdentity(
            code_commit=str(environment["commit"]),
            input_manifest_sha256=guarded.manifest_sha256,
            stage1_workers=config.stage1_workers,
            bootstrap_workers=config.bootstrap_workers,
            process_start_method=config.process_start_method,
            bootstrap_contract_sha256=contract_hash,
            phase8_output_version=PHASE8_OUTPUT_VERSION,
            producing_code_sha256=producing_hashes,
        ),
        mirror_root=mirror,
    )
    gate.start()
    try:
        computation = build_production_computation(
            production_inputs,
            stage1_workers=config.stage1_workers,
            process_start_method=config.process_start_method,
            checkpoint=checkpoint,
        )
        gate.sample()
    finally:
        gate.stop()
    # Realized distinct term count is not knowable until Stage 1 finishes; the
    # banner printed "pending" and the measured value is emitted here.
    sink.realized_terms(computation.distinct_term_count)
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
            worker_count=config.bootstrap_workers,
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
        "stage1_workers": config.stage1_workers,
        "bootstrap_workers": config.bootstrap_workers,
        "effective_cpu_count": config.effective_cpu_count,
        "cpu_capacity_observations": cpu_capacity,
        "process_start_method": config.process_start_method,
        "aggregate_memory_ceiling_bytes": config.aggregate_memory_ceiling_bytes,
        "aggregate_memory_ceiling_basis": dict(AGGREGATE_MEMORY_CEILING_BASIS),
        **gate.sampling_observation(),
        "launch_minimum_available_bytes": config.launch_minimum_available_bytes,
        "aggregate_peak_memory_bytes": gate.peak_bytes,
        "aggregate_memory_metric": gate.metric,
        "aggregate_memory_source": gate.source,
        "checkpoint_identity": asdict(checkpoint.identity),
        "checkpoint_root": PHASE8_CHECKPOINT_ROOT.resolve().as_posix(),
        "external_checkpoint_root": None if mirror is None else mirror.as_posix(),
        "resume": resume,
        "checkpoint_reuse": {
            "stage1_units_reused": list(checkpoint.reused_stage1_units),
            "stage1_units_new": list(checkpoint.new_stage1_units),
            "plans_reused": checkpoint.reused_plans,
            "plans_new": checkpoint.new_plans,
            "bootstrap_chunks_reused": list(checkpoint.reused_chunks),
            "bootstrap_chunks_new": list(checkpoint.new_chunks),
        },
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


def main(argv: Iterable[str] | None = None) -> None:
    if not getattr(sys.modules.get("__main__"), "__spec__", None):
        raise SpineError("launch Phase 8 only with: python -m mnq_lab.phase8.runner")
    parser = argparse.ArgumentParser(description="Fixed Phase 8 v2 child runner")
    parser.add_argument("--stage1-workers", required=True, type=int)
    parser.add_argument("--bootstrap-workers", required=True, type=int)
    parser.add_argument("--process-start-method", choices=("spawn", "fork"), required=True)
    parser.add_argument("--external-checkpoint-root", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--progress-log", type=Path, default=PHASE8_PROGRESS_LOG)
    arguments = parser.parse_args(None if argv is None else list(argv))
    require_phase8_run_paths(progress_log=arguments.progress_log, resume=arguments.resume)
    _progress.configure(log_path=arguments.progress_log, stdout=True)
    try:
        run_phase8(
            stage1_workers=arguments.stage1_workers,
            bootstrap_workers=arguments.bootstrap_workers,
            resume=arguments.resume,
            external_checkpoint_root=arguments.external_checkpoint_root,
            progress_log=arguments.progress_log,
            process_start_method=arguments.process_start_method,
        )
    finally:
        _progress.reset()


if __name__ == "__main__":
    main()


__all__ = [
    "AggregateMemoryGate", "InventoryChunk", "MemoryMeasurement", "RunnerOperatingConfig",
    "DEFAULT_AGGREGATE_MEMORY_SAMPLE_INTERVAL_SECONDS",
    "probe_effective_cpu_capacity", "resolve_effective_cpu_capacity",
    "execute_checkpointed_chunks", "load_ratified_inputs",
    "require_absent_phase8_run_paths", "require_phase8_run_paths", "run_phase8",
]
