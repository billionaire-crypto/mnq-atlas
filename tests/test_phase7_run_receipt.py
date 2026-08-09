"""Durable external evidence for the Phase 7 + Unit O production process."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from mnq_lab import SpineError
from mnq_lab.production.phase7_unit_o_run_receipt import (
    FAILED_V2_ARTIFACT_RELATIVE_PATH,
    PRIOR_V2_ARTIFACT_RELATIVE_PATH,
    PRODUCTION_COMMAND,
    PROTECTED_RELATIVE_PATHS,
    RECEIPT_SCHEMA_VERSION,
    _run_with_receipt,
)


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    protected = repo / "protected.txt"
    protected.write_text("immutable\n", encoding="utf-8")
    (repo / ".gitignore").write_text("output\n.output.staging\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "audit@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Audit Fixture"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "add", "protected.txt", ".gitignore"], check=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "fixture"], check=True
    )
    return repo, protected


def _success_command(output: Path) -> tuple[str, ...]:
    script = (
        "from pathlib import Path; "
        f"p=Path({str(output)!r}); p.mkdir(); "
        "(p/'run_manifest.json').write_text('{}\\n', encoding='utf-8')"
    )
    return sys.executable, "-c", script


def test_success_receipt_records_the_real_child_exit_and_unchanged_witnesses(
    tmp_path,
):
    repo, _ = _repo(tmp_path)
    output = repo / "output"
    receipt, exit_code = _run_with_receipt(
        tmp_path / "evidence",
        repo_root=repo,
        command=_success_command(output),
        protected_paths=("protected.txt",),
        output_root=output,
        staging_root=repo / ".output.staging",
    )

    assert exit_code == 0
    assert receipt["schema_version"] == RECEIPT_SCHEMA_VERSION
    assert receipt["child_exit_code"] == 0
    assert receipt["wrapper_exit_code"] == 0
    assert receipt["protected_paths_unchanged"] is True
    assert receipt["repository_commit_unchanged"] is True
    assert receipt["post_run_worktree_status"] == []
    assert receipt["changed_protected_paths"] == []
    assert receipt["output_complete"] is True
    stored = json.loads((tmp_path / "evidence/execution_receipt.json").read_text())
    assert stored == receipt
    durable_exit = json.loads((tmp_path / "evidence/child_exit.json").read_text())
    assert durable_exit["child_exit_code"] == 0
    assert durable_exit["run_commit"] == receipt["run_commit"]


def test_failed_child_exit_is_recorded_and_propagated(tmp_path):
    repo, _ = _repo(tmp_path)
    receipt, exit_code = _run_with_receipt(
        tmp_path / "evidence",
        repo_root=repo,
        command=(sys.executable, "-c", "raise SystemExit(7)"),
        protected_paths=("protected.txt",),
        output_root=repo / "output",
        staging_root=repo / ".output.staging",
    )

    assert exit_code == 7
    assert receipt["child_exit_code"] == 7
    assert receipt["wrapper_exit_code"] == 7
    assert receipt["output_complete"] is False
    assert json.loads((tmp_path / "evidence/child_exit.json").read_text())[
        "child_exit_code"
    ] == 7
    assert (tmp_path / "evidence/execution_receipt.json").is_file()


def test_changed_historical_witness_fails_even_when_child_exits_zero(tmp_path):
    repo, protected = _repo(tmp_path)
    output = repo / "output"
    script = (
        "from pathlib import Path; "
        f"Path({str(protected)!r}).write_text('changed\\n', encoding='utf-8'); "
        f"p=Path({str(output)!r}); p.mkdir(); "
        "(p/'run_manifest.json').write_text('{}\\n', encoding='utf-8')"
    )
    receipt, exit_code = _run_with_receipt(
        tmp_path / "evidence",
        repo_root=repo,
        command=(sys.executable, "-c", script),
        protected_paths=("protected.txt",),
        output_root=output,
        staging_root=repo / ".output.staging",
    )

    assert receipt["child_exit_code"] == 0
    assert exit_code == 86
    assert receipt["protected_paths_unchanged"] is False
    assert receipt["changed_protected_paths"] == ["protected.txt"]


def test_missing_post_run_witness_still_records_the_real_child_exit(tmp_path):
    repo, protected = _repo(tmp_path)
    output = repo / "output"
    script = (
        "from pathlib import Path; "
        f"Path({str(protected)!r}).unlink(); "
        f"p=Path({str(output)!r}); p.mkdir(); "
        "(p/'run_manifest.json').write_text('{}\\n', encoding='utf-8')"
    )
    receipt, exit_code = _run_with_receipt(
        tmp_path / "evidence",
        repo_root=repo,
        command=(sys.executable, "-c", script),
        protected_paths=("protected.txt",),
        output_root=output,
        staging_root=repo / ".output.staging",
    )

    assert receipt["child_exit_code"] == 0
    assert exit_code == 86
    assert receipt["post_run_snapshot_sha256"] is None
    assert "protected witness is missing" in receipt["post_run_snapshot_error"]
    assert json.loads((tmp_path / "evidence/child_exit.json").read_text())[
        "child_exit_code"
    ] == 0
    assert (tmp_path / "evidence/execution_receipt.json").is_file()


def test_repository_commit_must_not_change_during_the_child_run(tmp_path):
    repo, _ = _repo(tmp_path)
    output = repo / "output"
    script = (
        "import subprocess; from pathlib import Path; "
        "subprocess.run(['git','commit','--allow-empty','-q','-m','mutant'],check=True); "
        f"p=Path({str(output)!r}); p.mkdir(); "
        "(p/'run_manifest.json').write_text('{}\\n', encoding='utf-8')"
    )
    receipt, exit_code = _run_with_receipt(
        tmp_path / "evidence",
        repo_root=repo,
        command=(sys.executable, "-c", script),
        protected_paths=("protected.txt",),
        output_root=output,
        staging_root=repo / ".output.staging",
    )

    assert receipt["child_exit_code"] == 0
    assert exit_code == 86
    assert receipt["repository_commit_unchanged"] is False


def test_receipt_root_must_be_new_absolute_and_outside_the_repository(tmp_path):
    repo, _ = _repo(tmp_path)
    common = {
        "repo_root": repo,
        "command": (sys.executable, "-c", "raise SystemExit(0)"),
        "protected_paths": ("protected.txt",),
        "output_root": repo / "output",
        "staging_root": repo / ".output.staging",
    }
    with pytest.raises(SpineError, match="absolute external"):
        _run_with_receipt(Path("relative-receipt"), **common)
    with pytest.raises(SpineError, match="outside the repository"):
        _run_with_receipt(repo / "receipt", **common)
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(SpineError, match="must be absent"):
        _run_with_receipt(existing, **common)


def test_public_wrapper_is_fixed_to_the_governed_producer_and_safe_roots():
    assert PRODUCTION_COMMAND[1:] == (
        "-m",
        "mnq_lab.production.first_exploration_run",
    )
    assert all("locked_confirmation" not in path for path in PROTECTED_RELATIVE_PATHS)
    assert "data" not in PROTECTED_RELATIVE_PATHS
    assert "data/exploration/bars_5m" in PROTECTED_RELATIVE_PATHS
    assert PRIOR_V2_ARTIFACT_RELATIVE_PATH in PROTECTED_RELATIVE_PATHS
    assert FAILED_V2_ARTIFACT_RELATIVE_PATH in PROTECTED_RELATIVE_PATHS
    assert (
        "data/exploration/derived/phase7-unit-o-session-aware-v2"
        not in PROTECTED_RELATIVE_PATHS
    )


def test_prior_v2_witness_is_a_fixed_archive_not_the_live_output_target():
    assert PRIOR_V2_ARTIFACT_RELATIVE_PATH == (
        "data/exploration/derived/"
        ".archive-phase7-unit-o-session-aware-v2-f51482a"
    )


def test_failed_v2_witness_is_a_fixed_quarantine_root():
    assert FAILED_V2_ARTIFACT_RELATIVE_PATH == (
        "data/exploration/derived/.quarantine-failed-v2-e8542c1"
    )
    assert FAILED_V2_ARTIFACT_RELATIVE_PATH != PRIOR_V2_ARTIFACT_RELATIVE_PATH
