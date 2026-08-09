"""External execution receipt for the fixed Phase 7 + Unit O v2 producer.

The production process cannot truthfully record its own eventual operating-
system exit code.  This wrapper launches it as a child, records that return
code after the child terminates, and hashes every protected v1 witness before
and after the run.  Receipt files are required to live outside the repository
so creating them cannot dirty the clean production commit.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Iterable, Sequence

from mnq_lab import SpineError
from mnq_lab.constants import REPO_ROOT
from mnq_lab.production.first_exploration_run import OUTPUT_ROOT, STAGING_ROOT
from mnq_lab.spine.seal import LOCKED_STORE_DIRNAME, assert_exploration_safe

RECEIPT_SCHEMA_VERSION = "phase7-unit-o-external-execution-receipt-v1"
SNAPSHOT_SCHEMA_VERSION = "protected-v1-pre-post-hashes-v1"
PRIOR_V2_ARTIFACT_RELATIVE_PATH = (
    "data/exploration/derived/"
    ".archive-phase7-unit-o-session-aware-v2-f51482a"
)
FAILED_V2_ARTIFACT_RELATIVE_PATH = (
    "data/exploration/derived/.quarantine-failed-v2-e8542c1"
)
PRODUCTION_COMMAND = (
    sys.executable,
    "-m",
    "mnq_lab.production.first_exploration_run",
)

# Exact roots only. No command or helper recursively starts at data/. Tracked
# witnesses are protected twice: by these hashes and by the clean-worktree
# checks. Gitignored data witnesses depend on these hashes, so both the
# canonical source store and both preserved v2 witness trees are explicit.
# The live OUTPUT_ROOT cannot be a pre-run witness because the producer
# requires that target to be absent; before authorization, the existing f51482a
# artifact must be moved intact to PRIOR_V2_ARTIFACT_RELATIVE_PATH.
PROTECTED_RELATIVE_PATHS = (
    "data/exploration/bars_5m",
    PRIOR_V2_ARTIFACT_RELATIVE_PATH,
    FAILED_V2_ARTIFACT_RELATIVE_PATH,
    "data/exploration/derived/phase7-unit-o-first-run-v1",
    "data/exploration/derived/phase7-unit-o-first-run-v1.baseline-4f185ea",
    "data/exploration/derived/phase8-first-run-v1",
    "data/exploration/derived/phase8-first-run-v1.checkpoint",
    "data/exploration/derived/phase8-first-run-v1.operational",
    "data/exploration/derived/phase8-first-run-v1.progress.log",
    "data/exploration/s00/s00_threshold_input_v1.json",
    "mnq_lab/ledger/audit_entries",
    "mnq_lab/ledger/calendar_entries",
    "mnq_lab/ledger/entries",
    "mnq_lab/ledger/ratification_entries",
    "mnq_lab/ledger/run_completion_entries",
    "docs/UNIT_O.md",
    "docs/PHASE8.md",
    "analysis_constants_v1.yaml",
)


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        payload = json.dumps(
            value,
            sort_keys=True,
            indent=2,
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise SpineError(f"execution receipt is not strict JSON: {exc}") from exc
    return (payload + "\n").encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(*arguments: str, repo_root: Path = REPO_ROOT) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *arguments],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        raise SpineError(
            f"git {' '.join(arguments)} failed while preparing the execution receipt"
        )
    return result.stdout.strip()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_external_absent_root(receipt_root: Path, repo_root: Path) -> Path:
    root = Path(receipt_root)
    if not root.is_absolute():
        raise SpineError("execution receipt root must be an absolute external path")
    resolved = root.resolve()
    repository = Path(repo_root).resolve()
    try:
        resolved.relative_to(repository)
    except ValueError:
        pass
    else:
        raise SpineError("execution receipt root must be outside the repository")
    if resolved.exists():
        raise SpineError("execution receipt root must be absent")
    if LOCKED_STORE_DIRNAME in resolved.parts:
        raise SpineError("execution receipts may not target the prohibited store")
    return resolved


def _protected_files(
    repo_root: Path,
    relative_paths: Iterable[str],
) -> tuple[Path, ...]:
    repository = Path(repo_root).resolve()
    files: list[Path] = []
    for relative in relative_paths:
        if not isinstance(relative, str) or not relative:
            raise SpineError("protected witness paths must be nonempty strings")
        candidate = repository / relative
        if relative.startswith("data/exploration/"):
            candidate = assert_exploration_safe(candidate)
        resolved = candidate.resolve()
        try:
            resolved.relative_to(repository)
        except ValueError as exc:
            raise SpineError("protected witness escaped the repository") from exc
        if not resolved.exists():
            raise SpineError(f"protected witness is missing: {relative}")
        if resolved.is_symlink():
            raise SpineError(f"protected witness may not be a symlink: {relative}")
        if resolved.is_file():
            files.append(resolved)
            continue
        for path in sorted(resolved.rglob("*")):
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            if path.is_symlink():
                raise SpineError(
                    f"protected witness tree contains a symlink: {path}"
                )
            if path.is_file():
                files.append(path)
    relative_files = [path.relative_to(repository).as_posix() for path in files]
    if len(relative_files) != len(set(relative_files)):
        raise SpineError("protected witness roots overlap")
    return tuple(files)


def _snapshot(
    repo_root: Path,
    relative_paths: Iterable[str] = PROTECTED_RELATIVE_PATHS,
) -> dict[str, Any]:
    repository = Path(repo_root).resolve()
    records = []
    for path in _protected_files(repository, relative_paths):
        records.append(
            {
                "path": path.relative_to(repository).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "repo_commit": _git("rev-parse", "HEAD", repo_root=repository),
        "branch": _git("branch", "--show-current", repo_root=repository),
        "records": records,
    }
    return {
        **payload,
        "snapshot_sha256": hashlib.sha256(_canonical_json_bytes(payload)).hexdigest(),
    }


def _write_new(path: Path, value: Any) -> None:
    if path.exists():
        raise SpineError(f"execution evidence already exists: {path.name}")
    staging = path.with_name(f".{path.name}.staging")
    if staging.exists():
        raise SpineError(f"incomplete execution evidence exists: {staging.name}")
    payload = _canonical_json_bytes(value)
    with staging.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    staging.replace(path)


def _changed_records(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    left = {record["path"]: record for record in before["records"]}
    right = {record["path"]: record for record in after["records"]}
    return sorted(
        path
        for path in set(left) | set(right)
        if left.get(path) != right.get(path)
    )


def _run_with_receipt(
    receipt_root: Path,
    *,
    repo_root: Path = REPO_ROOT,
    command: Sequence[str] = PRODUCTION_COMMAND,
    protected_paths: Iterable[str] = PROTECTED_RELATIVE_PATHS,
    output_root: Path = OUTPUT_ROOT,
    staging_root: Path = STAGING_ROOT,
) -> tuple[dict[str, Any], int]:
    """Launch one child and durably record its actual return code."""
    repository = Path(repo_root).resolve()
    evidence_root = _require_external_absent_root(receipt_root, repository)
    if not command or any(not isinstance(value, str) or not value for value in command):
        raise SpineError("execution receipt command must be a nonempty string sequence")
    evidence_root.mkdir(parents=True, exist_ok=False)
    commit = _git("rev-parse", "HEAD", repo_root=repository)
    branch = _git("branch", "--show-current", repo_root=repository)
    pre_run_worktree_status = _git(
        "status", "--porcelain=v1", "--untracked-files=all", repo_root=repository
    )
    if pre_run_worktree_status:
        raise SpineError("execution wrapper requires a clean committed worktree")
    before = _snapshot(repository, protected_paths)
    _write_new(evidence_root / "pre_run_protected_hashes.json", before)

    stdout_path = evidence_root / "child.stdout.log"
    stderr_path = evidence_root / "child.stderr.log"
    started_at = _utc_now()
    started = time.perf_counter()
    with stdout_path.open("xb") as stdout_handle, stderr_path.open("xb") as stderr_handle:
        child = subprocess.Popen(
            list(command),
            cwd=repository,
            stdout=stdout_handle,
            stderr=stderr_handle,
            shell=False,
        )
        child_exit_code = int(child.wait())
        stdout_handle.flush()
        stderr_handle.flush()
        os.fsync(stdout_handle.fileno())
        os.fsync(stderr_handle.fileno())
    finished_at = _utc_now()
    elapsed = time.perf_counter() - started
    child_stdout_record = {
        "path": stdout_path.name,
        "bytes": stdout_path.stat().st_size,
        "sha256": _sha256_file(stdout_path),
    }
    child_stderr_record = {
        "path": stderr_path.name,
        "bytes": stderr_path.stat().st_size,
        "sha256": _sha256_file(stderr_path),
    }
    # Persist the operating-system result before the potentially slower
    # post-run witness snapshot. This is the durable evidence the child cannot
    # write truthfully about itself.
    _write_new(
        evidence_root / "child_exit.json",
        {
            "command": list(command),
            "run_commit": commit,
            "started_at_utc": started_at,
            "finished_at_utc": finished_at,
            "elapsed_seconds": elapsed,
            "child_exit_code": child_exit_code,
            "child_stdout": child_stdout_record,
            "child_stderr": child_stderr_record,
        },
    )

    after: dict[str, Any] | None = None
    post_snapshot_error = None
    try:
        after = _snapshot(repository, protected_paths)
    except Exception as exc:  # preserve child evidence even if a witness vanished
        post_snapshot_error = f"{type(exc).__name__}: {exc}"
        _write_new(
            evidence_root / "post_run_protected_hashes.json",
            {
                "schema_version": SNAPSHOT_SCHEMA_VERSION,
                "error": post_snapshot_error,
            },
        )
    else:
        _write_new(evidence_root / "post_run_protected_hashes.json", after)
    changed = (
        _changed_records(before, after)
        if after is not None
        else ["<post-run snapshot unavailable>"]
    )
    repository_commit_unchanged = bool(
        after is not None
        and before["repo_commit"] == after["repo_commit"] == commit
        and before["branch"] == after["branch"] == branch
    )
    post_run_worktree_status = _git(
        "status", "--porcelain=v1", "--untracked-files=all", repo_root=repository
    )
    output = Path(output_root)
    manifest_path = output / "run_manifest.json"
    manifest_record = None
    if manifest_path.is_file():
        manifest_record = {
            "path": manifest_path.resolve().relative_to(repository).as_posix(),
            "bytes": manifest_path.stat().st_size,
            "sha256": _sha256_file(manifest_path),
        }
    output_complete = (
        child_exit_code == 0
        and manifest_record is not None
        and not Path(staging_root).exists()
    )
    wrapper_exit_code = child_exit_code if child_exit_code != 0 else 0
    evidence_failed = bool(
        changed
        or not repository_commit_unchanged
        or post_run_worktree_status
        or (child_exit_code == 0 and not output_complete)
    )
    if evidence_failed:
        wrapper_exit_code = 86
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "command": list(command),
        "repo_root": repository.as_posix(),
        "run_commit": commit,
        "branch": branch,
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "elapsed_seconds": elapsed,
        "child_exit_code": child_exit_code,
        "wrapper_exit_code": wrapper_exit_code,
        "pre_run_snapshot_sha256": before["snapshot_sha256"],
        "post_run_snapshot_sha256": (
            after["snapshot_sha256"] if after is not None else None
        ),
        "post_run_snapshot_error": post_snapshot_error,
        "protected_paths_unchanged": not changed,
        "changed_protected_paths": changed,
        "repository_commit_unchanged": repository_commit_unchanged,
        "post_run_worktree_status": post_run_worktree_status.splitlines(),
        "child_stdout": child_stdout_record,
        "child_stderr": child_stderr_record,
        "output_manifest": manifest_record,
        "output_complete": output_complete,
        "staging_root_exists": Path(staging_root).exists(),
        "outcome_values_inspected": False,
        "phase8_executed": False,
    }
    _write_new(evidence_root / "execution_receipt.json", receipt)
    return receipt, wrapper_exit_code


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the fixed Phase 7 + Unit O producer with external evidence"
    )
    parser.add_argument(
        "--receipt-root",
        required=True,
        type=Path,
        help="new absolute directory outside the repository",
    )
    arguments = parser.parse_args()
    if _git("status", "--porcelain=v1", "--untracked-files=all"):
        raise SpineError("execution wrapper requires a clean committed worktree")
    receipt, exit_code = _run_with_receipt(arguments.receipt_root)
    print(_canonical_json_bytes(receipt).decode("utf-8"), end="")
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()


__all__ = [
    "PRIOR_V2_ARTIFACT_RELATIVE_PATH",
    "PROTECTED_RELATIVE_PATHS",
    "PRODUCTION_COMMAND",
    "RECEIPT_SCHEMA_VERSION",
]
