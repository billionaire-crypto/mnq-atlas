"""External execution receipt for the fixed Phase 8 session-aware v2 run.

The wrapper performs cheap fail-fast checks before it creates the external
receipt directory or launches the expensive child. The child is invoked once,
and its output, checkpoint and logs are preserved on every exit path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

from mnq_lab import SpineError
from mnq_lab.constants import REPO_ROOT
from mnq_lab.ledger.ratification import require_ratified_unit_o
from mnq_lab.phase8.runner import (
    PHASE8_CHECKPOINT_ROOT,
    PHASE8_OUTPUT_ROOT,
    PHASE8_PROGRESS_LOG,
    PHASE8_STAGING_ROOT,
    RATIFIED_INPUT_ROOT,
    _available_memory_bytes,
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


RECEIPT_SCHEMA_VERSION = "phase8-session-aware-v2-external-execution-receipt-v1"
SNAPSHOT_SCHEMA_VERSION = "phase8-v2-protected-pre-post-hashes-v1"
MINIMUM_AVAILABLE_MEMORY_BYTES = 8 * 1024**3
MINIMUM_FREE_DISK_BYTES = 4 * 1024**3
V2_INPUT_RELATIVE_PATH = (
    "data/exploration/derived/phase7-unit-o-session-aware-v2"
)
RATIFICATION_PROFILE_RELATIVE_PATH = "mnq_lab/ledger/ratification_profile_entries"
PRODUCTION_COMMAND = (sys.executable, "-m", "mnq_lab.phase8.runner")
PROTECTED_RELATIVE_PATHS = (
    *PHASE7_PROTECTED_RELATIVE_PATHS,
    V2_INPUT_RELATIVE_PATH,
    RATIFICATION_PROFILE_RELATIVE_PATH,
)


def _free_disk_bytes(path: Path) -> int:
    return int(shutil.disk_usage(path).free)


def _phase8_snapshot(
    repo_root: Path, relative_paths: Iterable[str]
) -> dict[str, Any]:
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
    """Return process metadata only for already-running Phase 8 children."""
    marker = "mnq_lab.phase8.runner"
    if os.name == "nt":
        script = (
            "$selfPid=$PID; "
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.ProcessId -ne $selfPid -and "
            "$_.CommandLine -match '(?i)(?:^|\\s)-m\\s+mnq_lab\\.phase8\\.runner(?:\\s|$)' } | "
            "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
        )
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            check=False,
            text=True,
        )
        if completed.returncode != 0:
            raise SpineError("cannot inspect existing Phase 8 processes")
        payload = completed.stdout.strip()
        if not payload:
            return ()
        parsed = json.loads(payload)
        records = [parsed] if isinstance(parsed, dict) else parsed
        return tuple(
            {
                "pid": int(record["ProcessId"]),
                "command": str(record["CommandLine"]),
            }
            for record in records
        )
    completed = subprocess.run(
        ["ps", "-eo", "pid=,args="], capture_output=True, check=False, text=True
    )
    if completed.returncode != 0:
        raise SpineError("cannot inspect existing Phase 8 processes")
    found = []
    for line in completed.stdout.splitlines():
        stripped = line.strip()
        if not stripped or marker not in stripped:
            continue
        pid_text, command = stripped.split(maxsplit=1)
        pid = int(pid_text)
        if pid != os.getpid():
            found.append({"pid": pid, "command": command})
    return tuple(found)


def _require_absent_paths(
    *,
    repo_root: Path,
    output_root: Path,
    staging_root: Path,
    checkpoint_root: Path,
    progress_log: Path,
) -> None:
    repository = Path(repo_root).resolve()
    output = Path(output_root).resolve()
    expected = (
        output.with_name(output.name + ".staging"),
        output.with_name(output.name + ".checkpoint"),
        output.with_name(output.name + ".progress.log"),
    )
    supplied = tuple(
        Path(path).resolve()
        for path in (staging_root, checkpoint_root, progress_log)
    )
    if supplied != expected:
        raise SpineError("Phase 8 staging, checkpoint or progress path is not bound to output")
    paths = (output, *supplied)
    if len(paths) != len(set(paths)):
        raise SpineError("Phase 8 fixed production paths overlap")
    for path in paths:
        try:
            path.relative_to(repository)
        except ValueError as exc:
            raise SpineError("Phase 8 production path is outside the repository") from exc
        if path.exists():
            raise SpineError(f"Phase 8 fixed production path must be absent: {path}")


def _preflight_phase8_run(
    *,
    repo_root: Path = REPO_ROOT,
    output_root: Path = PHASE8_OUTPUT_ROOT,
    staging_root: Path = PHASE8_STAGING_ROOT,
    checkpoint_root: Path = PHASE8_CHECKPOINT_ROOT,
    progress_log: Path = PHASE8_PROGRESS_LOG,
    memory_sampler: Callable[[], int] = _available_memory_bytes,
    disk_sampler: Callable[[Path], int] = _free_disk_bytes,
    process_probe: Callable[[], Sequence[Mapping[str, Any]]] = _active_phase8_runner_processes,
    certificate_validator: Callable[[], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate every cheap prerequisite without creating output or evidence."""
    repository = Path(repo_root).resolve()
    _require_absent_paths(
        repo_root=repository,
        output_root=output_root,
        staging_root=staging_root,
        checkpoint_root=checkpoint_root,
        progress_log=progress_log,
    )
    status = _git(
        "status", "--porcelain=v1", "--untracked-files=all", repo_root=repository
    )
    if status:
        raise SpineError("Phase 8 preflight requires a clean committed worktree")
    conflicts = tuple(dict(item) for item in process_probe())
    if conflicts:
        raise SpineError("another Phase 8 runner process is already running")
    available_memory = int(memory_sampler())
    if available_memory < MINIMUM_AVAILABLE_MEMORY_BYTES:
        raise SpineError(
            f"Phase 8 available memory preflight found {available_memory} bytes, below "
            f"the wrapper minimum with headroom {MINIMUM_AVAILABLE_MEMORY_BYTES}"
        )
    free_disk = int(disk_sampler(Path(output_root).parent))
    if free_disk < MINIMUM_FREE_DISK_BYTES:
        raise SpineError(
            f"Phase 8 free disk preflight found {free_disk} bytes, below "
            f"the fixed minimum {MINIMUM_FREE_DISK_BYTES}"
        )
    validator = certificate_validator or (
        lambda: require_ratified_unit_o(RATIFIED_INPUT_ROOT, repo_root=repository)
    )
    certificate = validator()
    certificate_id = certificate.get("certificate_id")
    if not isinstance(certificate_id, str) or not certificate_id:
        raise SpineError("Phase 8 ratification certificate id is absent")
    return {
        "repo_commit": _git("rev-parse", "HEAD", repo_root=repository),
        "branch": _git("branch", "--show-current", repo_root=repository),
        "certificate_id": certificate_id,
        "certificate_ledger_format": certificate.get("ledger_format"),
        "ratified_input_root": Path(RATIFIED_INPUT_ROOT).resolve().as_posix(),
        "output_root": Path(output_root).resolve().as_posix(),
        "staging_root": Path(staging_root).resolve().as_posix(),
        "checkpoint_root": Path(checkpoint_root).resolve().as_posix(),
        "progress_log": Path(progress_log).resolve().as_posix(),
        "available_memory_bytes": available_memory,
        "minimum_available_memory_bytes": MINIMUM_AVAILABLE_MEMORY_BYTES,
        "free_disk_bytes": free_disk,
        "minimum_free_disk_bytes": MINIMUM_FREE_DISK_BYTES,
        "conflicting_processes": list(conflicts),
    }


def _run_with_receipt(
    receipt_root: Path,
    *,
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
    repository = Path(repo_root).resolve()
    evidence_root = _require_external_absent_root(receipt_root, repository)
    if not command or any(not isinstance(value, str) or not value for value in command):
        raise SpineError("execution receipt command must be a nonempty string sequence")
    preflight_record = dict(
        preflight()
        if preflight is not None
        else _preflight_phase8_run(
            repo_root=repository,
            output_root=output_root,
            staging_root=staging_root,
            checkpoint_root=checkpoint_root,
            progress_log=progress_log,
        )
    )
    commit = _git("rev-parse", "HEAD", repo_root=repository)
    branch = _git("branch", "--show-current", repo_root=repository)
    if preflight_record.get("repo_commit", commit) != commit:
        raise SpineError("Phase 8 preflight commit differs before launch")
    before = _phase8_snapshot(repository, protected_paths)
    launch_status = _git(
        "status", "--porcelain=v1", "--untracked-files=all", repo_root=repository
    )
    if launch_status:
        raise SpineError("Phase 8 worktree changed between preflight and launch")
    # Any failed prerequisite above leaves the requested receipt root reusable:
    # no production child was launched and no evidence directory was consumed.
    evidence_root.mkdir(parents=True, exist_ok=False)
    _write_new(evidence_root / "preflight.json", preflight_record)
    _write_new(evidence_root / "pre_run_protected_hashes.json", before)

    stdout_path = evidence_root / "child.stdout.log"
    stderr_path = evidence_root / "child.stderr.log"
    started_at = _utc_now()
    started = time.perf_counter()
    with stdout_path.open("xb") as stdout_handle, stderr_path.open("xb") as stderr_handle:
        child = subprocess.Popen(
            list(command), cwd=repository, stdout=stdout_handle,
            stderr=stderr_handle, shell=False,
        )
        child_exit_code = int(child.wait())
        stdout_handle.flush()
        stderr_handle.flush()
        os.fsync(stdout_handle.fileno())
        os.fsync(stderr_handle.fileno())
    finished_at = _utc_now()
    elapsed = time.perf_counter() - started
    stdout_record = {
        "path": stdout_path.name,
        "bytes": stdout_path.stat().st_size,
        "sha256": _sha256_file(stdout_path),
    }
    stderr_record = {
        "path": stderr_path.name,
        "bytes": stderr_path.stat().st_size,
        "sha256": _sha256_file(stderr_path),
    }
    _write_new(
        evidence_root / "child_exit.json",
        {
            "command": list(command), "run_commit": commit,
            "started_at_utc": started_at, "finished_at_utc": finished_at,
            "elapsed_seconds": elapsed, "child_exit_code": child_exit_code,
            "child_stdout": stdout_record, "child_stderr": stderr_record,
        },
    )

    after: dict[str, Any] | None = None
    post_snapshot_error = None
    try:
        after = _phase8_snapshot(repository, protected_paths)
    except Exception as exc:
        post_snapshot_error = f"{type(exc).__name__}: {exc}"
        _write_new(
            evidence_root / "post_run_protected_hashes.json",
            {"schema_version": SNAPSHOT_SCHEMA_VERSION, "error": post_snapshot_error},
        )
    else:
        _write_new(evidence_root / "post_run_protected_hashes.json", after)
    changed = (
        _changed_records(before, after)
        if after is not None else ["<post-run snapshot unavailable>"]
    )
    repository_commit_unchanged = bool(
        after is not None
        and before["repo_commit"] == after["repo_commit"] == commit
        and before["branch"] == after["branch"] == branch
    )
    post_status = _git(
        "status", "--porcelain=v1", "--untracked-files=all", repo_root=repository
    )
    manifest_path = Path(output_root) / "manifest.json"
    manifest_record = None
    if manifest_path.is_file():
        manifest_record = {
            "path": manifest_path.resolve().relative_to(repository).as_posix(),
            "bytes": manifest_path.stat().st_size,
            "sha256": _sha256_file(manifest_path),
        }
    output_complete = bool(
        child_exit_code == 0
        and manifest_record is not None
        and not Path(staging_root).exists()
        and Path(checkpoint_root).is_dir()
        and Path(progress_log).is_file()
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
        "command": list(command), "repo_root": repository.as_posix(),
        "run_commit": commit, "branch": branch,
        "started_at_utc": started_at, "finished_at_utc": finished_at,
        "elapsed_seconds": elapsed,
        "child_exit_code": child_exit_code, "wrapper_exit_code": wrapper_exit_code,
        "preflight": preflight_record,
        "pre_run_snapshot_sha256": before["snapshot_sha256"],
        "post_run_snapshot_sha256": after["snapshot_sha256"] if after else None,
        "post_run_snapshot_error": post_snapshot_error,
        "protected_paths_unchanged": not changed,
        "changed_protected_paths": changed,
        "repository_commit_unchanged": repository_commit_unchanged,
        "post_run_worktree_status": post_status.splitlines(),
        "child_stdout": stdout_record, "child_stderr": stderr_record,
        "output_manifest": manifest_record, "output_complete": output_complete,
        "staging_root_exists": Path(staging_root).exists(),
        "checkpoint_root_exists": Path(checkpoint_root).exists(),
        "progress_log_exists": Path(progress_log).exists(),
        "phase8_executed": True,
        "phase9_executed": False,
        "outcome_values_inspected": False,
    }
    _write_new(evidence_root / "execution_receipt.json", receipt)
    return receipt, wrapper_exit_code


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the fixed Phase 8 v2 producer with external evidence"
    )
    parser.add_argument(
        "--receipt-root", required=True, type=Path,
        help="new absolute directory outside the repository",
    )
    arguments = parser.parse_args()
    receipt, exit_code = _run_with_receipt(arguments.receipt_root)
    print(_canonical_json_bytes(receipt).decode("utf-8"), end="")
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()


__all__ = [
    "MINIMUM_AVAILABLE_MEMORY_BYTES", "MINIMUM_FREE_DISK_BYTES", "PRODUCTION_COMMAND",
    "PROTECTED_RELATIVE_PATHS", "RECEIPT_SCHEMA_VERSION",
]
