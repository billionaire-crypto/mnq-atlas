"""External receipt and fail-fast controls for the Phase 8 v2 run."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from mnq_lab import SpineError
from mnq_lab.phase8.runner import MemoryMeasurement
from mnq_lab.production.phase8_v2_run_receipt import (
    MINIMUM_AVAILABLE_MEMORY_BYTES,
    MINIMUM_FREE_DISK_BYTES,
    PRODUCTION_COMMAND,
    PROTECTED_RELATIVE_PATHS,
    RECEIPT_SCHEMA_VERSION,
    _active_phase8_runner_processes,
    _preflight_phase8_run,
    _run_with_receipt,
)


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    protected = repo / "protected.txt"
    protected.write_text("immutable\n", encoding="utf-8")
    (repo / ".gitignore").write_text(
        "output*\ncheckpoint*\nprogress.log\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "audit@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Audit Fixture"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "fixture"], check=True
    )
    return repo, protected


def _paths(repo: Path) -> tuple[Path, Path, Path, Path]:
    output = repo / "output"
    return (
        output,
        repo / "output.staging",
        repo / "output.checkpoint",
        repo / "output.progress.log",
    )


def _passing_preflight() -> dict[str, object]:
    return {
        "certificate_id": "synthetic-v2-certificate",
        "available_memory_bytes": 8 * 1024**3,
        "minimum_available_memory_bytes": MINIMUM_AVAILABLE_MEMORY_BYTES,
        "free_disk_bytes": 8 * 1024**3,
        "minimum_free_disk_bytes": MINIMUM_FREE_DISK_BYTES,
        "conflicting_processes": [],
        "stage1_workers": 2,
        "bootstrap_workers": 3,
        "process_start_method": "spawn",
        "input_manifest_sha256": {"run": "a" * 64, "unit_o": "b" * 64, "phase7": "c" * 64},
    }


def _resource_probes() -> dict[str, object]:
    return {
        "cpu_probe": lambda: {
            "effective_cpu_count": 8, "os_cpu_count": 8,
            "affinity_cpus": tuple(range(8)),
        },
        "physical_memory_sampler": lambda: 16 * 1024**3,
        "aggregate_memory_probe": lambda: MemoryMeasurement(1024, "synthetic", "test"),
        "input_manifest_probe": lambda: {
            "run": "a" * 64, "unit_o": "b" * 64, "phase7": "c" * 64,
        },
    }


def test_posix_process_probe_matches_only_module_launches(monkeypatch):
    process_list = """\
101 python -m mnq_lab.phase8.runner --stage1-workers 1
102 /bin/sh -lc echo mnq_lab.phase8.runner while auditing
103 python mnq_lab.phase8.runner
104 python -m mnq_lab.phase8.runner_extra
105 python -u -m mnq_lab.phase8.runner --resume
106 python -m other.module mnq_lab.phase8.runner
107 python -mmnq_lab.phase8.runner --bootstrap-workers 32
"""
    completed = subprocess.CompletedProcess(
        args=("ps",), returncode=0, stdout=process_list, stderr=""
    )
    monkeypatch.setattr("mnq_lab.production.phase8_v2_run_receipt.os.name", "posix")
    monkeypatch.setattr(
        "mnq_lab.production.phase8_v2_run_receipt.os.getpid", lambda: 999
    )
    monkeypatch.setattr(
        "mnq_lab.production.phase8_v2_run_receipt.subprocess.run",
        lambda *_args, **_kwargs: completed,
    )

    assert _active_phase8_runner_processes() == (
        {
            "pid": 101,
            "command": "python -m mnq_lab.phase8.runner --stage1-workers 1",
        },
        {
            "pid": 105,
            "command": "python -u -m mnq_lab.phase8.runner --resume",
        },
        {
            "pid": 107,
            "command": "python -mmnq_lab.phase8.runner --bootstrap-workers 32",
        },
    )


@pytest.mark.parametrize("malformed", ("108", "not-a-pid command", "0 command"))
def test_posix_process_probe_rejects_malformed_process_metadata(
    malformed, monkeypatch,
):
    completed = subprocess.CompletedProcess(
        args=("ps",), returncode=0, stdout=malformed + "\n", stderr=""
    )
    monkeypatch.setattr("mnq_lab.production.phase8_v2_run_receipt.os.name", "posix")
    monkeypatch.setattr(
        "mnq_lab.production.phase8_v2_run_receipt.subprocess.run",
        lambda *_args, **_kwargs: completed,
    )

    with pytest.raises(SpineError, match="process metadata is malformed"):
        _active_phase8_runner_processes()


def test_success_receipt_records_complete_v2_output_and_unchanged_witness(tmp_path):
    repo, _ = _repo(tmp_path)
    output, staging, checkpoint, progress = _paths(repo)
    script = (
        "from pathlib import Path; import json; "
        f"o=Path({str(output)!r}); o.mkdir(); "
        "(o/'manifest.json').write_text(json.dumps({'complete': True})+'\\n'); "
        f"Path({str(checkpoint)!r}).mkdir(); "
        f"Path({str(progress)!r}).write_text('done\\n')"
    )
    receipt, exit_code = _run_with_receipt(
        tmp_path / "evidence",
        stage1_workers=2,
        bootstrap_workers=3,
        repo_root=repo,
        command=(sys.executable, "-c", script),
        protected_paths=("protected.txt",),
        output_root=output,
        staging_root=staging,
        checkpoint_root=checkpoint,
        progress_log=progress,
        preflight=_passing_preflight,
    )
    assert exit_code == 0
    assert receipt["schema_version"] == RECEIPT_SCHEMA_VERSION
    assert receipt["child_exit_code"] == receipt["wrapper_exit_code"] == 0
    assert receipt["output_complete"] is True
    assert receipt["protected_paths_unchanged"] is True
    assert receipt["phase8_executed"] is True
    assert receipt["outcome_values_inspected"] is False
    assert receipt["output_manifest"]["path"] == "output/manifest.json"
    assert json.loads((tmp_path / "evidence/execution_receipt.json").read_text()) == receipt


def test_failed_child_is_preserved_and_never_retried(tmp_path):
    repo, _ = _repo(tmp_path)
    output, staging, checkpoint, progress = _paths(repo)
    receipt, exit_code = _run_with_receipt(
        tmp_path / "evidence",
        stage1_workers=2,
        bootstrap_workers=3,
        repo_root=repo,
        command=(sys.executable, "-c", "raise SystemExit(7)"),
        protected_paths=("protected.txt",),
        output_root=output,
        staging_root=staging,
        checkpoint_root=checkpoint,
        progress_log=progress,
        preflight=_passing_preflight,
    )
    assert exit_code == 7
    assert receipt["child_exit_code"] == receipt["wrapper_exit_code"] == 7
    assert receipt["output_complete"] is False
    assert (tmp_path / "evidence/child_exit.json").is_file()


def test_preflight_failure_launches_no_child_and_consumes_no_receipt_root(tmp_path):
    repo, _ = _repo(tmp_path)
    output, staging, checkpoint, progress = _paths(repo)
    marker = tmp_path / "child-launched"

    def rejected():
        raise SpineError("named preflight failure")

    with pytest.raises(SpineError, match="named preflight failure"):
        _run_with_receipt(
            tmp_path / "evidence",
            stage1_workers=2,
            bootstrap_workers=3,
            repo_root=repo,
            command=(
                sys.executable, "-c",
                f"from pathlib import Path; Path({str(marker)!r}).touch()",
            ),
            protected_paths=("protected.txt",),
            output_root=output,
            staging_root=staging,
            checkpoint_root=checkpoint,
            progress_log=progress,
            preflight=rejected,
        )
    assert not marker.exists()
    assert not (tmp_path / "evidence").exists()


def test_existing_output_halts_before_certificate_or_resource_checks(tmp_path):
    repo, _ = _repo(tmp_path)
    output, staging, checkpoint, progress = _paths(repo)
    output.mkdir()
    reached = []
    with pytest.raises(SpineError, match="must be absent"):
        _preflight_phase8_run(
            stage1_workers=2,
            bootstrap_workers=3,
            repo_root=repo,
            output_root=output,
            staging_root=staging,
            checkpoint_root=checkpoint,
            progress_log=progress,
            memory_sampler=lambda: reached.append("memory") or 8 * 1024**3,
            disk_sampler=lambda _path: reached.append("disk") or 8 * 1024**3,
            process_probe=lambda: reached.append("process") or (),
            certificate_validator=lambda: reached.append("certificate") or {
                "certificate_id": "synthetic"
            },
        )
    assert reached == []


def test_protected_witness_drift_forces_wrapper_evidence_failure(tmp_path):
    repo, protected = _repo(tmp_path)
    output, staging, checkpoint, progress = _paths(repo)
    script = (
        "from pathlib import Path; "
        f"Path({str(protected)!r}).write_text('changed\\n')"
    )
    receipt, exit_code = _run_with_receipt(
        tmp_path / "evidence",
        stage1_workers=2,
        bootstrap_workers=3,
        repo_root=repo,
        command=(sys.executable, "-c", script),
        protected_paths=("protected.txt",),
        output_root=output,
        staging_root=staging,
        checkpoint_root=checkpoint,
        progress_log=progress,
        preflight=_passing_preflight,
    )
    assert receipt["child_exit_code"] == 0
    assert exit_code == receipt["wrapper_exit_code"] == 86
    assert receipt["protected_paths_unchanged"] is False
    assert receipt["changed_protected_paths"] == ["protected.txt"]


def test_zero_exit_without_complete_output_forces_wrapper_failure(tmp_path):
    repo, _ = _repo(tmp_path)
    output, staging, checkpoint, progress = _paths(repo)
    receipt, exit_code = _run_with_receipt(
        tmp_path / "evidence",
        stage1_workers=2,
        bootstrap_workers=3,
        repo_root=repo,
        command=(sys.executable, "-c", "pass"),
        protected_paths=("protected.txt",),
        output_root=output,
        staging_root=staging,
        checkpoint_root=checkpoint,
        progress_log=progress,
        preflight=_passing_preflight,
    )
    assert receipt["child_exit_code"] == 0
    assert exit_code == receipt["wrapper_exit_code"] == 86
    assert receipt["output_complete"] is False


@pytest.mark.parametrize("resource", ["memory", "disk", "process"])
def test_preflight_rejects_inadequate_resources_before_launch(tmp_path, resource):
    repo, _ = _repo(tmp_path)
    output, staging, checkpoint, progress = _paths(repo)
    memory = lambda: MINIMUM_AVAILABLE_MEMORY_BYTES
    disk = lambda _path: MINIMUM_FREE_DISK_BYTES
    processes = lambda: ()
    if resource == "memory":
        memory = lambda: MINIMUM_AVAILABLE_MEMORY_BYTES - 1
    elif resource == "disk":
        disk = lambda _path: MINIMUM_FREE_DISK_BYTES - 1
    else:
        processes = lambda: ({"pid": 123, "command": "python -m mnq_lab.phase8.runner"},)
    with pytest.raises(SpineError, match={
        "memory": "available memory",
        "disk": "free disk",
        "process": "already running",
    }[resource]):
        _preflight_phase8_run(
            stage1_workers=2,
            bootstrap_workers=3,
            repo_root=repo,
            output_root=output,
            staging_root=staging,
            checkpoint_root=checkpoint,
            progress_log=progress,
            memory_sampler=memory,
            disk_sampler=disk,
            process_probe=processes,
            certificate_validator=lambda: {"certificate_id": "synthetic"},
            **_resource_probes(),
        )


def test_public_wrapper_is_fixed_to_phase8_and_protects_its_v2_input():
    assert PRODUCTION_COMMAND[1:] == ("-m", "mnq_lab.phase8.runner")
    assert (
        "data/exploration/derived/phase7-unit-o-session-aware-v2"
        in PROTECTED_RELATIVE_PATHS
    )
    assert "data/exploration/derived/phase8-session-aware-v2" not in PROTECTED_RELATIVE_PATHS
    assert all("locked_confirmation" not in path for path in PROTECTED_RELATIVE_PATHS)
