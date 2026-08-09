"""External evidence wrapper for fresh, preflight-only, and resumed Phase 8 v2."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

from mnq_lab import SpineError
from mnq_lab.constants import REPO_ROOT
from mnq_lab.ledger.ratification import require_ratified_unit_o
from mnq_lab.phase8.runner import (
    DEFAULT_AGGREGATE_MEMORY_CEILING_BYTES,
    PHASE8_CHECKPOINT_ROOT,
    PHASE8_OUTPUT_ROOT,
    PHASE8_PROGRESS_LOG,
    PHASE8_STAGING_ROOT,
    RATIFIED_INPUT_ROOT,
    AggregateMemoryGate,
    MemoryMeasurement,
    RunnerOperatingConfig,
    _available_memory_bytes,
    aggregate_memory_measurement,
    available_memory_observation,
    default_process_start_method,
    probe_effective_cpu_capacity,
)
from mnq_lab.production.phase7_unit_o_run_receipt import (
    PROTECTED_RELATIVE_PATHS as PHASE7_PROTECTED_RELATIVE_PATHS,
    _canonical_json_bytes,
    _changed_records,
    _git,
    _require_external_absent_root,
    _sha256_file,
    _snapshot,
    _utc_now,
    _write_new,
)


RECEIPT_SCHEMA_VERSION = "phase8-session-aware-v2-external-execution-receipt-v2"
SNAPSHOT_SCHEMA_VERSION = "phase8-v2-protected-pre-post-hashes-v1"
PREFLIGHT_SCHEMA_VERSION = "phase8-session-aware-v2-rented-host-preflight-v2"
CHECKPOINT_SNAPSHOT_SCHEMA_VERSION = "phase8-checkpoint-evidence-snapshot-v1"
MINIMUM_AVAILABLE_MEMORY_BYTES = 8 * 1024**3
MINIMUM_FREE_DISK_BYTES = 4 * 1024**3
V2_INPUT_RELATIVE_PATH = "data/exploration/derived/phase7-unit-o-session-aware-v2"
RATIFICATION_PROFILE_RELATIVE_PATH = "mnq_lab/ledger/ratification_profile_entries"
PRODUCTION_COMMAND = (sys.executable, "-m", "mnq_lab.phase8.runner")
PROTECTED_RELATIVE_PATHS = (
    *PHASE7_PROTECTED_RELATIVE_PATHS,
    V2_INPUT_RELATIVE_PATH,
    RATIFICATION_PROFILE_RELATIVE_PATH,
)


def _free_disk_bytes(path: Path) -> int:
    return int(shutil.disk_usage(path).free)


def _physical_memory_bytes() -> int:
    if os.name == "nt":
        import ctypes

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
            raise SpineError("Windows physical-memory query failed")
        return int(status.ullTotalPhys)
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except (OSError, ValueError) as exc:
        raise SpineError("physical-memory query failed") from exc


def _phase8_snapshot(repo_root: Path, relative_paths: Iterable[str]) -> dict[str, Any]:
    inherited = _snapshot(repo_root, relative_paths)
    payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "repo_commit": inherited["repo_commit"],
        "branch": inherited["branch"],
        "records": inherited["records"],
    }
    return {
        **payload,
        "snapshot_sha256": hashlib.sha256(_canonical_json_bytes(payload)).hexdigest(),
    }


def _active_phase8_runner_processes() -> tuple[dict[str, Any], ...]:
    runner_pattern = re.compile(
        r"(?:^|\s)-m\s*mnq_lab\.phase8\.runner(?:\s|$)", re.IGNORECASE
    )
    if os.name == "nt":
        script = (
            "$selfPid=$PID; Get-CimInstance Win32_Process | "
            "Where-Object { $_.ProcessId -ne $selfPid -and "
            "$_.CommandLine -match '(?i)(?:^|\\s)-m\\s*mnq_lab\\.phase8\\.runner(?:\\s|$)' } | "
            "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
        )
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, check=False, text=True,
        )
        if completed.returncode != 0:
            raise SpineError("cannot inspect existing Phase 8 processes")
        payload = completed.stdout.strip()
        if not payload:
            return ()
        parsed = json.loads(payload)
        records = [parsed] if isinstance(parsed, dict) else parsed
        return tuple({"pid": int(item["ProcessId"]), "command": str(item["CommandLine"])} for item in records)
    completed = subprocess.run(
        ["ps", "-eo", "pid=,args="], capture_output=True, check=False, text=True
    )
    if completed.returncode != 0:
        raise SpineError("cannot inspect existing Phase 8 processes")
    found = []
    for line in completed.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        fields = stripped.split(maxsplit=1)
        if len(fields) != 2:
            raise SpineError("existing Phase 8 process metadata is malformed")
        pid_text, command = fields
        try:
            pid = int(pid_text)
        except ValueError as exc:
            raise SpineError("existing Phase 8 process metadata is malformed") from exc
        if pid <= 0:
            raise SpineError("existing Phase 8 process metadata is malformed")
        if pid != os.getpid() and runner_pattern.search(command):
            found.append({"pid": pid, "command": command})
    return tuple(found)


def _require_bound_paths(
    *, repo_root: Path, output_root: Path, staging_root: Path,
    checkpoint_root: Path, progress_log: Path,
) -> tuple[Path, Path, Path, Path]:
    repository = Path(repo_root).resolve()
    output = Path(output_root).resolve()
    expected = (
        output.with_name(output.name + ".staging"),
        output.with_name(output.name + ".checkpoint"),
    )
    if (Path(staging_root).resolve(), Path(checkpoint_root).resolve()) != expected:
        raise SpineError("Phase 8 staging or checkpoint path is not bound to output")
    progress = Path(progress_log).resolve()
    paths = (output, *expected, progress)
    if len(paths) != len(set(paths)):
        raise SpineError("Phase 8 production paths overlap")
    for path in paths:
        try:
            path.relative_to(repository)
        except ValueError as exc:
            raise SpineError("Phase 8 production path is outside the repository") from exc
    return paths


def _require_absent_paths(
    *, repo_root: Path, output_root: Path, staging_root: Path,
    checkpoint_root: Path, progress_log: Path,
) -> None:
    paths = _require_bound_paths(
        repo_root=repo_root, output_root=output_root, staging_root=staging_root,
        checkpoint_root=checkpoint_root, progress_log=progress_log,
    )
    expected_progress = Path(output_root).resolve().with_name(Path(output_root).name + ".progress.log")
    if paths[-1] != expected_progress:
        raise SpineError("Phase 8 fresh progress path is not the fixed path")
    for path in paths:
        if path.exists():
            raise SpineError(f"Phase 8 fixed production path must be absent: {path}")


def _require_resume_paths(
    *, repo_root: Path, output_root: Path, staging_root: Path,
    checkpoint_root: Path, progress_log: Path,
) -> None:
    output, staging, _checkpoint, progress = _require_bound_paths(
        repo_root=repo_root, output_root=output_root, staging_root=staging_root,
        checkpoint_root=checkpoint_root, progress_log=progress_log,
    )
    base_progress = output.with_name(output.name + ".progress.log")
    if progress == base_progress or not progress.name.startswith(base_progress.name + ".resume-"):
        raise SpineError("resume requires a new bound per-attempt progress log")
    for path in (output, staging, progress):
        if path.exists():
            raise SpineError(f"Phase 8 resume path must be absent: {path}")
    _reject_checkpoint_staging(Path(checkpoint_root))


def _reject_checkpoint_staging(root: Path) -> None:
    candidate = Path(root)
    if not candidate.is_dir():
        return
    for path in candidate.rglob("*"):
        if path.name.startswith(".") and path.name.endswith(".staging"):
            raise SpineError("incomplete checkpoint staging evidence exists")


def _checkpoint_snapshot(root: Path | None) -> dict[str, Any]:
    if root is None:
        payload = {"schema_version": CHECKPOINT_SNAPSHOT_SCHEMA_VERSION, "root": None, "exists": False, "records": []}
    else:
        resolved = Path(root).resolve()
        records = []
        if resolved.exists():
            if not resolved.is_dir():
                raise SpineError("checkpoint evidence root is not a directory")
            for path in sorted((item for item in resolved.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
                records.append({
                    "path": path.relative_to(resolved).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256_file(path),
                })
        payload = {
            "schema_version": CHECKPOINT_SNAPSHOT_SCHEMA_VERSION,
            "root": resolved.as_posix(), "exists": resolved.is_dir(), "records": records,
        }
    return {**payload, "snapshot_sha256": hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()}


def _checkpoint_identity_evidence(
    local_root: Path, external_root: Path | None,
) -> dict[str, Any] | None:
    records = []
    for label, root in (("local", local_root), ("external", external_root)):
        if root is None:
            continue
        path = Path(root) / "identity.json"
        if not path.is_file():
            continue
        document, digest = _load_canonical(path)
        records.append({
            "location": label, "path": path.resolve().as_posix(),
            "bytes": path.stat().st_size, "sha256": digest,
            "identity": document,
        })
    if not records:
        return None
    hashes = {record["sha256"] for record in records}
    if len(hashes) != 1:
        raise SpineError("local and external checkpoint identities differ")
    return {"identity_sha256": records[0]["sha256"], "copies": records}


def _checkpoint_units(snapshot: Mapping[str, Any]) -> list[str]:
    units = set()
    for record in snapshot.get("records", []):
        relative = str(record.get("path", ""))
        parts = relative.split("/")
        if len(parts) == 2 and parts[1] == "manifest.json" and not parts[0].startswith("."):
            units.add(parts[0])
    return sorted(units)


def _checkpoint_activity(
    before_local: Mapping[str, Any], before_external: Mapping[str, Any],
    after_local: Mapping[str, Any], after_external: Mapping[str, Any],
) -> dict[str, Any]:
    before = set(_checkpoint_units(before_local)) | set(_checkpoint_units(before_external))
    after = set(_checkpoint_units(after_local)) | set(_checkpoint_units(after_external))
    return {
        "complete_units_available_before_launch": sorted(before),
        "complete_units_after_child_exit": sorted(after),
        "newly_promoted_complete_units": sorted(after - before),
        "complete_units_missing_after_child_exit": sorted(before - after),
        "classification_note": (
            "availability and promotion are mechanically observed here; exact reuse is "
            "recorded by the child in the final output operating manifest"
        ),
    }


def _filesystem_metadata(path: Path, *, repository: Path) -> dict[str, Any]:
    candidate = Path(path).resolve()
    probe = candidate
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        device = int(probe.stat().st_dev)
        repo_device = int(repository.stat().st_dev)
    except OSError as exc:
        raise SpineError("filesystem identity cannot be inspected") from exc
    mount_point = None
    if sys.platform.startswith("linux"):
        try:
            mounts = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise SpineError("Linux mount identity cannot be inspected") from exc
        candidates = []
        for line in mounts:
            fields = line.split()
            if len(fields) >= 5:
                mount = Path(fields[4])
                try:
                    candidate.relative_to(mount)
                except ValueError:
                    continue
                candidates.append(mount)
        if candidates:
            mount_point = max(candidates, key=lambda item: len(item.parts)).as_posix()
    return {
        "path": candidate.as_posix(), "existing_probe_path": probe.as_posix(),
        "device": device, "repository_device": repo_device,
        "different_device_from_repository": device != repo_device,
        "mount_point": mount_point,
        "free_disk_bytes": _free_disk_bytes(probe),
    }


def _external_checkpoint_metadata(
    path: Path | None, *, repository: Path, resume: bool,
    operator_attested_durable: bool,
) -> dict[str, Any]:
    if path is None:
        if operator_attested_durable:
            raise SpineError("durability cannot be attested without an external checkpoint root")
        return {
            "supplied": False, "outside_repository": None,
            "operator_attested_durable": False,
            "host_loss_durability_mechanically_established": False,
            "durability_status": "not established: no external checkpoint root supplied",
        }
    candidate = Path(path)
    if not candidate.is_absolute():
        raise SpineError("external checkpoint root must be absolute")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(repository)
    except ValueError:
        outside = True
    else:
        raise SpineError("external checkpoint root must be outside the repository")
    identity_staging = resolved.with_name(f".{resolved.name}.identity.staging")
    if identity_staging.exists():
        raise SpineError("incomplete external checkpoint mirror staging evidence exists")
    if resume and not resolved.is_dir():
        raise SpineError("resume external checkpoint root is absent")
    if not resume and resolved.exists():
        raise SpineError("fresh external checkpoint root must be absent")
    if resume:
        _reject_checkpoint_staging(resolved)
    filesystem = _filesystem_metadata(resolved, repository=repository)
    return {
        "supplied": True, "root": resolved.as_posix(), "outside_repository": outside,
        **filesystem,
        "operator_attested_durable": bool(operator_attested_durable),
        "host_loss_durability_mechanically_established": False,
        "durability_status": (
            "operator-attested durable/off-host; physical off-host status is not mechanically proven"
            if operator_attested_durable else
            "outside repository only; host-loss recovery is not established"
        ),
    }


def _fixed_input_manifest_hashes() -> dict[str, str]:
    paths = {
        "run": RATIFIED_INPUT_ROOT / "run_manifest.json",
        "unit_o": RATIFIED_INPUT_ROOT / "unit_o/manifest.json",
        "phase7": RATIFIED_INPUT_ROOT / "phase7/manifest.json",
    }
    result = {}
    for name, path in paths.items():
        if not path.is_file():
            raise SpineError(f"Phase 8 structural input manifest is absent: {name}")
        result[name] = _sha256_file(path)
    return result


def _load_canonical(path: Path) -> tuple[dict[str, Any], str]:
    try:
        payload = path.read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpineError(f"evidence is unreadable: {path.name}") from exc
    if payload != _canonical_json_bytes(value):
        raise SpineError(f"evidence is not canonical: {path.name}")
    return value, hashlib.sha256(payload).hexdigest()


def _validate_file_record(root: Path, record: Mapping[str, Any]) -> None:
    path = root / str(record.get("path", ""))
    if (
        not path.is_file()
        or path.stat().st_size != record.get("bytes")
        or _sha256_file(path) != record.get("sha256")
    ):
        raise SpineError("prior receipt evidence hash differs")


def _validate_prior_receipt(
    prior_root: Path,
    *, repository: Path, commit: str, stage1_workers: int,
    bootstrap_workers: int, input_manifest_sha256: Mapping[str, str],
    checkpoint_root: Path,
    external_checkpoint_root: Path | None,
) -> dict[str, Any]:
    prior = Path(prior_root)
    if not prior.is_absolute() or not prior.is_dir():
        raise SpineError("resume requires an existing absolute prior receipt root")
    receipt, receipt_sha = _load_canonical(prior / "execution_receipt.json")
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise SpineError("prior receipt schema is not resumable")
    if receipt.get("child_exit_code") == 0 or receipt.get("wrapper_exit_code") == 0 or receipt.get("output_complete"):
        raise SpineError("a successful prior execution may not be resumed")
    if receipt.get("output_root_exists") or receipt.get("staging_root_exists"):
        raise SpineError("prior attempt left unexpected output or staging state")
    if not receipt.get("progress_log"):
        raise SpineError("prior attempt progress evidence is absent")
    if receipt.get("run_commit") != commit:
        raise SpineError("prior receipt run commit differs")
    if not receipt.get("protected_paths_unchanged") or not receipt.get("repository_commit_unchanged"):
        raise SpineError("prior receipt did not preserve protected identity")
    prior_preflight = receipt.get("preflight", {})
    stored_preflight, _ = _load_canonical(prior / "preflight.json")
    if stored_preflight != prior_preflight:
        raise SpineError("prior preflight evidence differs from its receipt")
    if (
        prior_preflight.get("stage1_workers") != stage1_workers
        or prior_preflight.get("bootstrap_workers") != bootstrap_workers
    ):
        raise SpineError("prior receipt worker configuration differs")
    if prior_preflight.get("input_manifest_sha256") != dict(input_manifest_sha256):
        raise SpineError("prior receipt input manifests differ")
    for key in ("child_stdout", "child_stderr"):
        _validate_file_record(prior, receipt[key])
    child_exit, _ = _load_canonical(prior / "child_exit.json")
    if (
        child_exit.get("child_exit_code") != receipt.get("child_exit_code")
        or child_exit.get("run_commit") != commit
        or child_exit.get("stage1_workers") != stage1_workers
        or child_exit.get("bootstrap_workers") != bootstrap_workers
    ):
        raise SpineError("prior child-exit evidence differs")
    pre_snapshot, _ = _load_canonical(prior / "pre_run_protected_hashes.json")
    post_snapshot, _ = _load_canonical(prior / "post_run_protected_hashes.json")
    if (
        pre_snapshot.get("snapshot_sha256") != receipt.get("pre_run_snapshot_sha256")
        or post_snapshot.get("snapshot_sha256") != receipt.get("post_run_snapshot_sha256")
    ):
        raise SpineError("prior protected snapshot evidence differs")
    current_external = _checkpoint_snapshot(external_checkpoint_root)
    prior_checkpoint = receipt.get("checkpoint_evidence", {})
    prior_external = prior_checkpoint.get("external")
    if external_checkpoint_root is not None:
        if not isinstance(prior_external, Mapping) or prior_external.get("snapshot_sha256") != current_external["snapshot_sha256"]:
            raise SpineError("external checkpoint mirror differs from prior receipt")
    elif not Path(checkpoint_root).is_dir():
        raise SpineError("resume has neither local nor external checkpoint evidence")
    if Path(checkpoint_root).is_dir():
        current_local = _checkpoint_snapshot(checkpoint_root)
        prior_local = prior_checkpoint.get("local")
        if not isinstance(prior_local, Mapping) or prior_local.get("snapshot_sha256") != current_local["snapshot_sha256"]:
            raise SpineError("local checkpoint evidence differs from prior receipt")
    progress_record = receipt.get("progress_log")
    if isinstance(progress_record, Mapping):
        _validate_file_record(prior, progress_record) if str(progress_record.get("path", "")).startswith(".") else None
        progress_path = Path(str(progress_record.get("absolute_path", "")))
        if not progress_path.is_file() or _sha256_file(progress_path) != progress_record.get("sha256"):
            raise SpineError("prior progress evidence differs")
    return {
        "prior_receipt_root": prior.resolve().as_posix(),
        "prior_receipt_sha256": receipt_sha,
        "prior_checkpoint_evidence_sha256": prior_checkpoint.get("snapshot_sha256"),
        "prior_child_exit_code": receipt["child_exit_code"],
        "prior_wrapper_exit_code": receipt["wrapper_exit_code"],
    }


def _preflight_phase8_run(
    *,
    stage1_workers: int,
    bootstrap_workers: int,
    resume: bool = False,
    prior_receipt_root: Path | None = None,
    external_checkpoint_root: Path | None = None,
    operator_attested_durable: bool = False,
    repo_root: Path = REPO_ROOT,
    output_root: Path = PHASE8_OUTPUT_ROOT,
    staging_root: Path = PHASE8_STAGING_ROOT,
    checkpoint_root: Path = PHASE8_CHECKPOINT_ROOT,
    progress_log: Path = PHASE8_PROGRESS_LOG,
    memory_sampler: Callable[[], int] = _available_memory_bytes,
    physical_memory_sampler: Callable[[], int] = _physical_memory_bytes,
    aggregate_memory_probe: Callable[[], MemoryMeasurement] = aggregate_memory_measurement,
    cpu_probe: Callable[[], Mapping[str, Any]] = probe_effective_cpu_capacity,
    disk_sampler: Callable[[Path], int] = _free_disk_bytes,
    process_probe: Callable[[], Sequence[Mapping[str, Any]]] = _active_phase8_runner_processes,
    certificate_validator: Callable[[], Mapping[str, Any]] | None = None,
    input_manifest_probe: Callable[[], Mapping[str, str]] = _fixed_input_manifest_hashes,
) -> dict[str, Any]:
    """Perform every cheap check without creating any production or evidence path."""
    repository = Path(repo_root).resolve()
    if resume:
        _require_resume_paths(
            repo_root=repository, output_root=output_root, staging_root=staging_root,
            checkpoint_root=checkpoint_root, progress_log=progress_log,
        )
    else:
        _require_absent_paths(
            repo_root=repository, output_root=output_root, staging_root=staging_root,
            checkpoint_root=checkpoint_root, progress_log=progress_log,
        )
    status = _git("status", "--porcelain=v1", "--untracked-files=all", repo_root=repository)
    if status:
        raise SpineError("Phase 8 preflight requires a clean committed worktree")
    conflicts = tuple(dict(item) for item in process_probe())
    if conflicts:
        raise SpineError("another Phase 8 runner process is already running")
    cpu = dict(cpu_probe())
    effective = cpu.get("effective_cpu_count")
    config = RunnerOperatingConfig(
        stage1_workers=stage1_workers, bootstrap_workers=bootstrap_workers,
        effective_cpu_count=effective,
        process_start_method=default_process_start_method(),
    )
    if memory_sampler is _available_memory_bytes:
        memory_capacity = dict(available_memory_observation())
        available_memory = memory_capacity["effective_available_bytes"]
    else:
        available_memory = memory_sampler()
        memory_capacity = {
            "effective_available_bytes": available_memory,
            "source": "injected available-memory sampler",
        }
    physical_memory = physical_memory_sampler()
    if isinstance(available_memory, bool) or not isinstance(available_memory, int) or available_memory < MINIMUM_AVAILABLE_MEMORY_BYTES:
        raise SpineError(
            f"Phase 8 available memory preflight found {available_memory!r}, below "
            f"the wrapper minimum with headroom {MINIMUM_AVAILABLE_MEMORY_BYTES}"
        )
    if isinstance(physical_memory, bool) or not isinstance(physical_memory, int) or physical_memory <= 0:
        raise SpineError("Phase 8 physical memory could not be measured")
    aggregate = aggregate_memory_probe()
    if not isinstance(aggregate, MemoryMeasurement):
        raise SpineError("Phase 8 aggregate memory accounting is unavailable")
    if aggregate.bytes > DEFAULT_AGGREGATE_MEMORY_CEILING_BYTES:
        raise SpineError("aggregate Phase 8 memory already exceeds the fixed ceiling")
    free_disk = disk_sampler(Path(output_root).parent)
    if isinstance(free_disk, bool) or not isinstance(free_disk, int) or free_disk < MINIMUM_FREE_DISK_BYTES:
        raise SpineError(
            f"Phase 8 free disk preflight found {free_disk!r}, below the fixed minimum {MINIMUM_FREE_DISK_BYTES}"
        )
    validator = certificate_validator or (
        lambda: require_ratified_unit_o(RATIFIED_INPUT_ROOT, repo_root=repository)
    )
    certificate = validator()
    certificate_id = certificate.get("certificate_id")
    if not isinstance(certificate_id, str) or not certificate_id:
        raise SpineError("Phase 8 ratification certificate id is absent")
    inputs = dict(input_manifest_probe())
    if set(inputs) != {"run", "unit_o", "phase7"} or any(not isinstance(value, str) or len(value) != 64 for value in inputs.values()):
        raise SpineError("Phase 8 input-manifest hash evidence is invalid")
    external = _external_checkpoint_metadata(
        external_checkpoint_root, repository=repository, resume=resume,
        operator_attested_durable=operator_attested_durable,
    )
    commit = _git("rev-parse", "HEAD", repo_root=repository)
    prior = None
    if resume:
        if prior_receipt_root is None:
            raise SpineError("resume requires an explicit prior receipt reference")
        prior = _validate_prior_receipt(
            prior_receipt_root, repository=repository, commit=commit,
            stage1_workers=stage1_workers, bootstrap_workers=bootstrap_workers,
            input_manifest_sha256=inputs,
            checkpoint_root=checkpoint_root,
            external_checkpoint_root=external_checkpoint_root,
        )
    return {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "mode": "resume" if resume else "fresh",
        "repo_commit": commit,
        "branch": _git("branch", "--show-current", repo_root=repository),
        "clean_worktree": True,
        "certificate_status": "ratified",
        "certificate_id": certificate_id,
        "certificate_ledger_format": certificate.get("ledger_format"),
        "ratified_input_root": Path(RATIFIED_INPUT_ROOT).resolve().as_posix(),
        "input_manifest_sha256": inputs,
        "output_root": Path(output_root).resolve().as_posix(),
        "staging_root": Path(staging_root).resolve().as_posix(),
        "checkpoint_root": Path(checkpoint_root).resolve().as_posix(),
        "progress_log": Path(progress_log).resolve().as_posix(),
        "path_state": {
            "output_exists": Path(output_root).exists(),
            "staging_exists": Path(staging_root).exists(),
            "checkpoint_exists": Path(checkpoint_root).exists(),
            "progress_exists": Path(progress_log).exists(),
        },
        "stage1_workers": config.stage1_workers,
        "bootstrap_workers": config.bootstrap_workers,
        "process_start_method": config.process_start_method,
        "cpu_capacity": cpu,
        "available_memory_bytes": available_memory,
        "available_memory_observations": memory_capacity,
        "physical_memory_bytes": physical_memory,
        "minimum_available_memory_bytes": MINIMUM_AVAILABLE_MEMORY_BYTES,
        "aggregate_memory_metric": aggregate.metric,
        "aggregate_memory_source": aggregate.source,
        "aggregate_memory_observed_bytes": aggregate.bytes,
        "aggregate_memory_ceiling_bytes": DEFAULT_AGGREGATE_MEMORY_CEILING_BYTES,
        "free_disk_bytes": free_disk,
        "minimum_free_disk_bytes": MINIMUM_FREE_DISK_BYTES,
        "conflicting_processes": list(conflicts),
        "external_checkpoint": external,
        "prior_attempt": prior,
        "phase8_child_launched": False,
        "scientific_arrays_opened": False,
    }


def _production_child_command(
    command: Sequence[str], *, stage1_workers: int, bootstrap_workers: int,
    process_start_method: str, resume: bool,
    external_checkpoint_root: Path | None, progress_log: Path,
) -> tuple[str, ...]:
    if not command or any(not isinstance(value, str) or not value for value in command):
        raise SpineError("execution receipt command must be a nonempty string sequence")
    if tuple(command) != PRODUCTION_COMMAND:
        return tuple(command)
    result = [
        *command,
        "--stage1-workers", str(stage1_workers),
        "--bootstrap-workers", str(bootstrap_workers),
        "--process-start-method", process_start_method,
        "--progress-log", str(Path(progress_log).resolve()),
    ]
    if external_checkpoint_root is not None:
        result.extend(("--external-checkpoint-root", str(Path(external_checkpoint_root).resolve())))
    if resume:
        result.append("--resume")
    return tuple(result)


def _run_with_receipt(
    receipt_root: Path,
    *,
    stage1_workers: int,
    bootstrap_workers: int,
    resume: bool = False,
    prior_receipt_root: Path | None = None,
    external_checkpoint_root: Path | None = None,
    operator_attested_durable: bool = False,
    repo_root: Path = REPO_ROOT,
    command: Sequence[str] = PRODUCTION_COMMAND,
    protected_paths: Iterable[str] = PROTECTED_RELATIVE_PATHS,
    output_root: Path = PHASE8_OUTPUT_ROOT,
    staging_root: Path = PHASE8_STAGING_ROOT,
    checkpoint_root: Path = PHASE8_CHECKPOINT_ROOT,
    progress_log: Path = PHASE8_PROGRESS_LOG,
    preflight: Callable[[], Mapping[str, Any]] | None = None,
) -> tuple[dict[str, Any], int]:
    """Launch exactly one Phase 8 child and record its real exit status."""
    for label, value in (("Stage 1", stage1_workers), ("bootstrap", bootstrap_workers)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise SpineError(f"Phase 8 {label} workers must be a positive integer")
    repository = Path(repo_root).resolve()
    evidence_root = _require_external_absent_root(receipt_root, repository)
    preflight_record = dict(
        preflight() if preflight is not None else _preflight_phase8_run(
            stage1_workers=stage1_workers, bootstrap_workers=bootstrap_workers,
            resume=resume, prior_receipt_root=prior_receipt_root,
            external_checkpoint_root=external_checkpoint_root,
            operator_attested_durable=operator_attested_durable,
            repo_root=repository, output_root=output_root, staging_root=staging_root,
            checkpoint_root=checkpoint_root, progress_log=progress_log,
        )
    )
    commit = _git("rev-parse", "HEAD", repo_root=repository)
    branch = _git("branch", "--show-current", repo_root=repository)
    if preflight_record.get("repo_commit", commit) != commit:
        raise SpineError("Phase 8 preflight commit differs before launch")
    for key, expected in (("stage1_workers", stage1_workers), ("bootstrap_workers", bootstrap_workers)):
        if preflight_record.get(key, expected) != expected:
            raise SpineError("Phase 8 preflight worker configuration differs before launch")
    before = _phase8_snapshot(repository, protected_paths)
    checkpoint_before_local = _checkpoint_snapshot(checkpoint_root)
    checkpoint_before_external = _checkpoint_snapshot(external_checkpoint_root)
    if _git("status", "--porcelain=v1", "--untracked-files=all", repo_root=repository):
        raise SpineError("Phase 8 worktree changed between preflight and launch")
    child_command = _production_child_command(
        command, stage1_workers=stage1_workers, bootstrap_workers=bootstrap_workers,
        process_start_method=str(preflight_record.get("process_start_method", default_process_start_method())),
        resume=resume, external_checkpoint_root=external_checkpoint_root,
        progress_log=progress_log,
    )
    evidence_root.mkdir(parents=True, exist_ok=False)
    _write_new(evidence_root / "preflight.json", preflight_record)
    _write_new(evidence_root / "pre_run_protected_hashes.json", before)
    stdout_path = evidence_root / "child.stdout.log"
    stderr_path = evidence_root / "child.stderr.log"
    started_at = _utc_now()
    started = time.perf_counter()
    with stdout_path.open("xb") as stdout_handle, stderr_path.open("xb") as stderr_handle:
        child = subprocess.Popen(
            list(child_command), cwd=repository, stdout=stdout_handle,
            stderr=stderr_handle, shell=False,
        )
        child_exit_code = int(child.wait())
        stdout_handle.flush(); stderr_handle.flush()
        os.fsync(stdout_handle.fileno()); os.fsync(stderr_handle.fileno())
    finished_at = _utc_now()
    elapsed = time.perf_counter() - started
    stdout_record = {"path": stdout_path.name, "bytes": stdout_path.stat().st_size, "sha256": _sha256_file(stdout_path)}
    stderr_record = {"path": stderr_path.name, "bytes": stderr_path.stat().st_size, "sha256": _sha256_file(stderr_path)}
    checkpoint_identity = _checkpoint_identity_evidence(
        Path(checkpoint_root), external_checkpoint_root
    )
    local_checkpoint = _checkpoint_snapshot(checkpoint_root)
    external_checkpoint = _checkpoint_snapshot(external_checkpoint_root)
    checkpoint_activity = _checkpoint_activity(
        checkpoint_before_local, checkpoint_before_external,
        local_checkpoint, external_checkpoint,
    )
    output_operating = None
    early_manifest_path = Path(output_root) / "manifest.json"
    if early_manifest_path.is_file():
        try:
            early_manifest = json.loads(early_manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SpineError("Phase 8 output manifest is unreadable after child exit") from exc
        if isinstance(early_manifest, Mapping) and isinstance(early_manifest.get("operating"), Mapping):
            output_operating = dict(early_manifest["operating"])
    child_exit_record = {
        "command": list(child_command), "run_commit": commit,
        "stage1_workers": stage1_workers, "bootstrap_workers": bootstrap_workers,
        "process_start_method": preflight_record.get("process_start_method"),
        "cpu_capacity": preflight_record.get("cpu_capacity"),
        "aggregate_memory_metric": preflight_record.get("aggregate_memory_metric"),
        "aggregate_memory_source": preflight_record.get("aggregate_memory_source"),
        "checkpoint_root": Path(checkpoint_root).resolve().as_posix(),
        "external_checkpoint_root": None if external_checkpoint_root is None else Path(external_checkpoint_root).resolve().as_posix(),
        "checkpoint_identity": checkpoint_identity,
        "checkpoint_activity": checkpoint_activity,
        "output_operating": output_operating,
        "resume": resume,
        "started_at_utc": started_at, "finished_at_utc": finished_at,
        "elapsed_seconds": elapsed, "child_exit_code": child_exit_code,
        "child_stdout": stdout_record, "child_stderr": stderr_record,
    }
    _write_new(evidence_root / "child_exit.json", child_exit_record)
    after = None
    post_snapshot_error = None
    try:
        after = _phase8_snapshot(repository, protected_paths)
    except Exception as exc:
        post_snapshot_error = f"{type(exc).__name__}: {exc}"
        _write_new(evidence_root / "post_run_protected_hashes.json", {"schema_version": SNAPSHOT_SCHEMA_VERSION, "error": post_snapshot_error})
    else:
        _write_new(evidence_root / "post_run_protected_hashes.json", after)
    changed = _changed_records(before, after) if after is not None else ["<post-run snapshot unavailable>"]
    repository_commit_unchanged = bool(
        after is not None and before["repo_commit"] == after["repo_commit"] == commit
        and before["branch"] == after["branch"] == branch
    )
    post_status = _git("status", "--porcelain=v1", "--untracked-files=all", repo_root=repository)
    manifest_path = Path(output_root) / "manifest.json"
    manifest_record = None
    if manifest_path.is_file():
        manifest_record = {
            "path": manifest_path.resolve().relative_to(repository).as_posix(),
            "bytes": manifest_path.stat().st_size, "sha256": _sha256_file(manifest_path),
        }
    progress_record = None
    if Path(progress_log).is_file():
        progress_record = {
            "absolute_path": Path(progress_log).resolve().as_posix(),
            "bytes": Path(progress_log).stat().st_size,
            "sha256": _sha256_file(Path(progress_log)),
        }
    checkpoint_payload = {"local": local_checkpoint, "external": external_checkpoint}
    checkpoint_evidence = {
        **checkpoint_payload,
        "snapshot_sha256": hashlib.sha256(_canonical_json_bytes(checkpoint_payload)).hexdigest(),
    }
    output_complete = bool(
        child_exit_code == 0 and manifest_record is not None
        and not Path(staging_root).exists() and Path(checkpoint_root).is_dir()
        and progress_record is not None
    )
    evidence_failed = bool(
        changed or not repository_commit_unchanged or post_status
        or (child_exit_code == 0 and not output_complete)
    )
    wrapper_exit_code = child_exit_code if child_exit_code != 0 else 0
    if evidence_failed:
        wrapper_exit_code = 86
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "mode": "resume" if resume else "fresh",
        "command": list(child_command), "repo_root": repository.as_posix(),
        "run_commit": commit, "branch": branch,
        "stage1_workers": stage1_workers, "bootstrap_workers": bootstrap_workers,
        "started_at_utc": started_at, "finished_at_utc": finished_at,
        "elapsed_seconds": elapsed,
        "child_exit_code": child_exit_code, "wrapper_exit_code": wrapper_exit_code,
        "preflight": preflight_record,
        "prior_attempt": preflight_record.get("prior_attempt"),
        "pre_run_snapshot_sha256": before["snapshot_sha256"],
        "post_run_snapshot_sha256": after["snapshot_sha256"] if after else None,
        "post_run_snapshot_error": post_snapshot_error,
        "protected_paths_unchanged": not changed,
        "changed_protected_paths": changed,
        "repository_commit_unchanged": repository_commit_unchanged,
        "post_run_worktree_status": post_status.splitlines(),
        "child_stdout": stdout_record, "child_stderr": stderr_record,
        "output_manifest": manifest_record, "output_complete": output_complete,
        "output_root_exists": Path(output_root).exists(),
        "staging_root_exists": Path(staging_root).exists(),
        "checkpoint_root_exists": Path(checkpoint_root).exists(),
        "progress_log": progress_record,
        "checkpoint_evidence": checkpoint_evidence,
        "checkpoint_identity": checkpoint_identity,
        "checkpoint_activity": checkpoint_activity,
        "output_operating": output_operating,
        "phase8_executed": True, "phase9_executed": False,
        "outcome_values_inspected": False,
    }
    _write_new(evidence_root / "execution_receipt.json", receipt)
    return receipt, wrapper_exit_code


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Audit wrapper for fixed Phase 8 v2")
    parser.add_argument("--stage1-workers", required=True, type=int)
    parser.add_argument("--bootstrap-workers", required=True, type=int)
    parser.add_argument("--receipt-root", type=Path)
    parser.add_argument("--external-checkpoint-root", type=Path)
    parser.add_argument("--external-checkpoint-durable", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--resume-from", type=Path)
    arguments = parser.parse_args(argv)
    resume = arguments.resume_from is not None
    progress_log = PHASE8_PROGRESS_LOG
    if resume:
        prior_path = arguments.resume_from / "execution_receipt.json"
        if not prior_path.is_file():
            raise SpineError("resume prior receipt is absent")
        prior_sha = _sha256_file(prior_path)
        progress_log = PHASE8_PROGRESS_LOG.with_name(
            PHASE8_PROGRESS_LOG.name + f".resume-{prior_sha[:12]}"
        )
    preflight_kwargs = dict(
        stage1_workers=arguments.stage1_workers,
        bootstrap_workers=arguments.bootstrap_workers,
        resume=resume,
        prior_receipt_root=arguments.resume_from,
        external_checkpoint_root=arguments.external_checkpoint_root,
        operator_attested_durable=arguments.external_checkpoint_durable,
        progress_log=progress_log,
    )
    if arguments.preflight_only:
        record = _preflight_phase8_run(**preflight_kwargs)
        print(_canonical_json_bytes(record).decode("utf-8"), end="")
        return
    if arguments.receipt_root is None:
        parser.error("--receipt-root is required unless --preflight-only is used")
    receipt, exit_code = _run_with_receipt(
        arguments.receipt_root, **preflight_kwargs
    )
    print(_canonical_json_bytes(receipt).decode("utf-8"), end="")
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()


__all__ = [
    "MINIMUM_AVAILABLE_MEMORY_BYTES", "MINIMUM_FREE_DISK_BYTES",
    "PRODUCTION_COMMAND", "PROTECTED_RELATIVE_PATHS", "RECEIPT_SCHEMA_VERSION",
    "_preflight_phase8_run", "_production_child_command", "_run_with_receipt",
]
