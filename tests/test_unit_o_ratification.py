"""Focused synthetic negative controls for Unit O ratification."""

from __future__ import annotations

import copy
import hashlib
import inspect
from pathlib import Path
import shutil

import pytest

from mnq_lab import SpineError
from mnq_lab.constants import REPO_ROOT
from mnq_lab.ledger import ratification
from mnq_lab.ledger.ratification import (
    AUDIT_FORMAT,
    CERTIFICATE_FORMAT,
    CLAIM_BOUNDARY,
    COMPLETION_FORMAT,
    CRITERIA_COMMIT,
    CRITERIA_COMMITTED_AT,
    CRITERIA_DOCUMENT_SHA256,
    D22_SHA256,
    NON_ADMISSIBLE_STAMP,
    PINNED_INPUTS,
    PRODUCING_CODE_SHA256,
    PROGRAM_ID,
    SCIENTIFIC_COLUMN_COUNT,
    SCIENTIFIC_COLUMN_PROTOCOL,
    SOURCE_STORE_MANIFEST_SHA256,
    UNIT_NAME,
    canonical_json_bytes,
    evaluate_ratification_certificate,
    require_ratified_unit_o,
)
from mnq_lab.production.first_exploration_run import (
    FREE_MEMORY_PREFLIGHT_BYTES,
    GATE_CLASSIFICATION,
    PEAK_MEMORY_CEILING_BYTES,
)


RUN_COMMIT = "a" * 40
AUDITOR = "Independent Auditor"
PRODUCER = "Corpus Producer"
VISIBLE_AFTER = "2026-08-03T03:00:00+00:00"
VISIBLE_BEFORE = "2026-08-02T18:00:00-07:00"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _copy_protected_repo_bytes(repo: Path) -> None:
    for relative in PINNED_INPUTS:
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, target)
    criteria = repo / "docs/UNIT_O_RATIFICATION_PREREGISTRATION.md"
    criteria.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "docs/UNIT_O_RATIFICATION_PREREGISTRATION.md", criteria)
    shutil.copy2(REPO_ROOT / "docs/DISCREPANCIES.md", repo / "docs/DISCREPANCIES.md")
    producer = repo / "mnq_lab/production/first_exploration_run.py"
    producer.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "mnq_lab/production/first_exploration_run.py", producer)


def _environment(*, dirty: bool = False, commit: str = RUN_COMMIT) -> dict[str, object]:
    return {
        "vcs": "git",
        "commit": commit,
        "branch": "synthetic",
        "dirty": dirty,
        "python": "3.synthetic",
        "numpy": "synthetic",
        "pandas": "synthetic",
        "platform": "synthetic",
        "machine": "synthetic",
        "pipeline_version": "spine-1.0.0",
    }


def _write_tree(
    root: Path,
    *,
    source_sha: str = SOURCE_STORE_MANIFEST_SHA256,
    dirty: bool = False,
    commit: str = RUN_COMMIT,
) -> None:
    environment = _environment(dirty=dirty, commit=commit)
    phase_columns: dict[str, dict[str, object]] = {}
    for index in range(SCIENTIFIC_COLUMN_COUNT - 25):
        name = f"phase_col_{index:03d}"
        relative = f"table/{index:03d}_{name}.npy"
        path = root / "phase7" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"scientific-{index:03d}".encode("ascii"))
        phase_columns[name] = {"file": relative, "sha256": _sha(path)}
    phase_manifest = {
        "artifact_schema_version": "phase7-conditioners-v1",
        "tables": {
            "table": {
                "column_order": list(phase_columns),
                "columns": phase_columns,
                "row_count": 1,
            }
        },
    }
    _write_json(root / "phase7/manifest.json", phase_manifest)

    unit_columns: dict[str, dict[str, object]] = {}
    for index in range(25):
        absolute_index = SCIENTIFIC_COLUMN_COUNT - 25 + index
        name = f"unit_col_{index:03d}"
        filename = f"{index:02d}_{name}.npy"
        path = root / "unit_o" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"scientific-{absolute_index:03d}".encode("ascii"))
        unit_columns[name] = {"file": filename, "sha256": _sha(path)}
    unit_manifest = {
        "artifact_schema_version": "unit-o-outcomes-v1",
        "code_commit": commit,
        "dirty_worktree": dirty,
        "environment_fingerprint": environment,
        "frozen_inputs": dict(PINNED_INPUTS),
        "input_store_manifest_sha256": source_sha,
        "column_order": list(unit_columns),
        "columns": unit_columns,
    }
    _write_json(root / "unit_o/manifest.json", unit_manifest)
    unit_sha = _sha(root / "unit_o/manifest.json")
    run_manifest = {
        "admissibility": NON_ADMISSIBLE_STAMP,
        "source_store_manifest_sha256": source_sha,
        "artifact_manifest_sha256": {"phase7": _sha(root / "phase7/manifest.json"), "unit_o": unit_sha},
        "environment_fingerprint": environment,
        "gate_classification": list(GATE_CLASSIFICATION),
        "peak_memory_bytes": 1024,
    }
    _write_json(root / "run_manifest.json", run_manifest)


def _build_case(
    tmp_path: Path,
    *,
    tree_name: str = "candidate",
    source_sha: str = SOURCE_STORE_MANIFEST_SHA256,
    visible_at: str = VISIBLE_AFTER,
    dirty: bool = False,
    run_commit: str = RUN_COMMIT,
    override_basis: str = "2026-08-02 user ruling and independently audited bounded override",
) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _copy_protected_repo_bytes(repo)
    tree = repo / "artifacts" / tree_name
    replay = repo / "artifacts" / "replay"
    _write_tree(tree, source_sha=source_sha, dirty=dirty, commit=run_commit)
    _write_tree(replay, source_sha=source_sha, dirty=dirty, commit=run_commit)

    tree_sha = ratification._tree_sha256(tree)
    replay_sha = ratification._tree_sha256(replay)
    columns = ratification._scientific_columns(tree)
    replay_columns = ratification._scientific_columns(replay)
    tree_relative = tree.relative_to(repo).as_posix()
    environment = _environment(dirty=dirty, commit=run_commit)

    completion = {
        "ledger_format": COMPLETION_FORMAT,
        "entry_id": "synthetic-completion",
        "run_commit": run_commit,
        "tree_path": tree_relative,
        "tree_sha256": tree_sha,
        "run_manifest_sha256": _sha(tree / "run_manifest.json"),
        "visible_at_utc": visible_at,
        "recorder_identity": "Synthetic Completion Recorder",
    }
    completion_path = repo / "mnq_lab/ledger/run_completion_entries/completion.json"
    _write_json(completion_path, completion)

    audit = {
        "ledger_format": AUDIT_FORMAT,
        "entry_id": "synthetic-unit-o-audit",
        "program_id": PROGRAM_ID,
        "unit": UNIT_NAME,
        "audited_commit": run_commit,
        "audited_tree": tree_relative,
        "verdict": "CLOSED",
        "date": "2026-08-03",
        "findings": ["C1-C6 verified against synthetic raw bytes"],
        "auditor_identity": AUDITOR,
        "producer_identity": PRODUCER,
        "evidence_hashes": {"run_manifest.json": _sha(tree / "run_manifest.json")},
    }
    audit_path = repo / "mnq_lab/ledger/audit_entries/audit.json"
    _write_json(audit_path, audit)
    audit_ref = {"path": audit_path.relative_to(repo).as_posix(), "sha256": _sha(audit_path)}

    certificate = {
        "ledger_format": CERTIFICATE_FORMAT,
        "certificate_id": "synthetic-unit-o-certificate",
        "program_id": PROGRAM_ID,
        "unit": UNIT_NAME,
        "decision_date": "2026-08-03",
        "tree": {
            "path": tree_relative,
            "tree_sha256": tree_sha,
            "unit_o_manifest_sha256": _sha(tree / "unit_o/manifest.json"),
            "run_manifest_sha256": _sha(tree / "run_manifest.json"),
        },
        "scientific_column_protocol": SCIENTIFIC_COLUMN_PROTOCOL,
        "scientific_columns": columns,
        "run_commit": run_commit,
        "environment_fingerprint": environment,
        "criteria": {
            "commit": CRITERIA_COMMIT,
            "committed_at_utc": CRITERIA_COMMITTED_AT,
            "document_sha256": CRITERIA_DOCUMENT_SHA256,
            "d22_sha256": D22_SHA256,
        },
        "run_completion_record": {
            "path": completion_path.relative_to(repo).as_posix(),
            "sha256": _sha(completion_path),
        },
        "pinned_inputs": {
            "canonical_source_store_manifest": SOURCE_STORE_MANIFEST_SHA256,
            **PINNED_INPUTS,
        },
        "gate_evidence": {
            "producing_code_sha256": PRODUCING_CODE_SHA256,
            "gate_records": [dict(record, passed=True) for record in GATE_CLASSIFICATION],
            "thresholds": {
                "free_memory_preflight_bytes": FREE_MEMORY_PREFLIGHT_BYTES,
                "peak_memory_ceiling_bytes": PEAK_MEMORY_CEILING_BYTES,
                "scientific_column_count": SCIENTIFIC_COLUMN_COUNT,
            },
            "tolerances": {},
            "fallback": {"allowed": False, "taken": False},
            "peak_memory_bytes": 1024,
            "all_gates_passed": True,
        },
        "reproduction": {
            "tree_path": replay.relative_to(repo).as_posix(),
            "tree_sha256": replay_sha,
            "environment_fingerprint": environment,
            "scientific_columns": replay_columns,
        },
        "non_admissible_override": {
            "stamp": NON_ADMISSIBLE_STAMP,
            "scope_tree_sha256": tree_sha,
            "scope_run_commit": run_commit,
            "decision_date": "2026-08-03",
            "decider_identity": "User ruling 2026-08-02",
            "basis": override_basis,
            "audit_entry": audit_ref,
        },
        "audit_entry": audit_ref,
        "conditions": {
            "C1": {"passed": True},
            "C2": {"passed": True},
            "C3": {"passed": True},
            "C4": {"passed": True},
            "C5": {"passed": True},
            "C6": {"passed": True},
            "C7": {"attested_closed": True},
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    certificate_path = repo / "mnq_lab/ledger/ratification_entries/certificate.json"
    _write_json(certificate_path, certificate)
    return repo, tree, certificate_path


def _mutate_certificate(path: Path, mutation) -> None:
    certificate = copy.deepcopy(ratification._load_canonical_json(path, "test certificate"))
    mutation(certificate)
    _write_json(path, certificate)


def test_all_seven_conditions_accept_a_complete_synthetic_certificate(tmp_path):
    repo, tree, certificate = _build_case(tmp_path)
    result = evaluate_ratification_certificate(certificate, repo_root=repo)
    assert result.passed and result.failures == ()
    assert result.mechanically_checked == ("C1", "C2", "C3", "C4", "C5", "C6")
    assert result.attested_not_proven == ("C7",)
    assert require_ratified_unit_o(
        tree,
        repo_root=repo,
        certificate_directory=certificate.parent,
    )["certificate_id"] == "synthetic-unit-o-certificate"


def test_c1_refuses_a_different_source_store_manifest_hash(tmp_path):
    repo, _, certificate = _build_case(tmp_path, source_sha="f" * 64)
    assert "C1" in evaluate_ratification_certificate(certificate, repo_root=repo).failures


def test_c2_refuses_criteria_committed_after_visibility(tmp_path):
    repo, _, certificate = _build_case(tmp_path, visible_at=VISIBLE_BEFORE)
    assert "C2" in evaluate_ratification_certificate(certificate, repo_root=repo).failures


def test_c3_refuses_a_dirty_worktree_at_run_time(tmp_path):
    repo, _, certificate = _build_case(tmp_path, dirty=True)
    assert "C3" in evaluate_ratification_certificate(certificate, repo_root=repo).failures


@pytest.mark.parametrize("mutation", ["lowered_threshold", "added_tolerance"])
def test_c4_refuses_relaxed_thresholds_or_added_tolerance(tmp_path, mutation):
    repo, _, certificate = _build_case(tmp_path)
    if mutation == "lowered_threshold":
        _mutate_certificate(
            certificate,
            lambda value: value["gate_evidence"]["thresholds"].__setitem__(
                "free_memory_preflight_bytes", FREE_MEMORY_PREFLIGHT_BYTES - 1
            ),
        )
    else:
        _mutate_certificate(
            certificate,
            lambda value: value["gate_evidence"]["tolerances"].__setitem__(
                "column_hash", "one-bit"
            ),
        )
    assert "C4" in evaluate_ratification_certificate(certificate, repo_root=repo).failures


def test_c6_refuses_non_admissible_override_without_recorded_basis(tmp_path):
    repo, _, certificate = _build_case(tmp_path, override_basis="")
    assert "C6" in evaluate_ratification_certificate(certificate, repo_root=repo).failures


def test_c5_refuses_certificate_hashes_that_do_not_match_tree_bytes(tmp_path):
    repo, tree, certificate = _build_case(tmp_path)
    column = next((tree / "unit_o").glob("*.npy"))
    column.write_bytes(column.read_bytes() + b"mutation")
    assert "C5" in evaluate_ratification_certificate(certificate, repo_root=repo).failures


def test_certificate_for_a_different_tree_or_commit_is_refused(tmp_path):
    repo, tree, certificate = _build_case(tmp_path)
    other = repo / "artifacts/other"
    _write_tree(other)
    with pytest.raises(SpineError, match="found 0"):
        require_ratified_unit_o(
            other,
            repo_root=repo,
            certificate_directory=certificate.parent,
        )

    _mutate_certificate(
        certificate,
        lambda value: value.__setitem__("run_commit", "b" * 40),
    )
    result = evaluate_ratification_certificate(certificate, repo_root=repo)
    assert "C2" in result.failures or "C3" in result.failures


def test_preserved_baseline_is_refused_by_c2_and_c6_without_a_name_blacklist(tmp_path):
    repo, _, certificate = _build_case(
        tmp_path,
        tree_name="phase7-unit-o-first-run-v1.baseline-4f185ea",
        visible_at=VISIBLE_BEFORE,
        override_basis="",
    )
    result = evaluate_ratification_certificate(certificate, repo_root=repo)
    assert {"C2", "C6"}.issubset(result.failures)
    assert "baseline-4f185ea" not in inspect.getsource(ratification)


def test_phase8_halts_when_no_certificate_exists(tmp_path):
    repo, tree, certificate = _build_case(tmp_path)
    certificate.unlink()
    with pytest.raises(SpineError, match="found 0"):
        require_ratified_unit_o(
            tree,
            repo_root=repo,
            certificate_directory=certificate.parent,
        )
