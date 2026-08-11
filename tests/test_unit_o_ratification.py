"""Focused synthetic negative controls for Unit O ratification."""

from __future__ import annotations

import copy
import hashlib
import inspect
from pathlib import Path
import shutil
import subprocess

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

# path -> entry_id of the ledger entry that documents the withdrawal.
# Empty. Adding a key here is a deliberate, reviewable act.
WITHDRAWN_EVIDENCE: dict[str, str] = {}


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
    # D34: C4 now verifies the producer AT the certificate's run commit, so the
    # synthetic repo must hold the bytes that hash to the pinned constant. Take
    # them from the real repository's history rather than its working tree,
    # which legitimately moves on as the producer evolves.
    producer.write_bytes(_pinned_producer_bytes())


def _pinned_producer_bytes() -> bytes:
    """Producing-code bytes hashing to PRODUCING_CODE_SHA256."""
    relative = "mnq_lab/production/first_exploration_run.py"
    live = (REPO_ROOT / relative).read_bytes()
    if hashlib.sha256(live).hexdigest() == PRODUCING_CODE_SHA256:
        return live
    revisions = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "log", "--format=%H", "--", relative],
        capture_output=True, check=True,
    ).stdout.decode().split()
    for revision in revisions:
        blob = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "cat-file", "blob", f"{revision}:{relative}"],
            capture_output=True, check=False,
        ).stdout
        if hashlib.sha256(blob).hexdigest() == PRODUCING_CODE_SHA256:
            return blob
    raise AssertionError("no revision of the producer matches PRODUCING_CODE_SHA256")


def _commit_synthetic_repo(repo: Path) -> str:
    """Make the fixture a real git repository and return its commit id.

    C4 reads the producer out of git history, so a fabricated 40-hex id would
    only ever prove the check fails closed -- never that it accepts a genuine
    certificate. The fixture therefore commits for real.
    """
    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, check=True
        )

    subprocess.run(["git", "init", "-q", str(repo)], capture_output=True, check=True)
    run("config", "user.email", "synthetic@example.invalid")
    run("config", "user.name", "Synthetic Fixture")
    run("config", "core.autocrlf", "false")
    run("add", "-A")
    run("-c", "commit.gpgsign=false", "commit", "-q", "-m", "synthetic fixture")
    return run("rev-parse", "HEAD").stdout.decode().strip()


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
    environment_overrides: dict[str, object] | None = None,
    scientific_count: int = SCIENTIFIC_COLUMN_COUNT,
    unit_column_count: int = 25,
    unit_schema: str = "unit-o-outcomes-v1",
) -> None:
    environment = _environment(dirty=dirty, commit=commit)
    if environment_overrides:
        environment.update(environment_overrides)
    phase_columns: dict[str, dict[str, object]] = {}
    for index in range(scientific_count - unit_column_count):
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
    for index in range(unit_column_count):
        absolute_index = scientific_count - unit_column_count + index
        name = f"unit_col_{index:03d}"
        filename = f"{index:02d}_{name}.npy"
        path = root / "unit_o" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"scientific-{absolute_index:03d}".encode("ascii"))
        unit_columns[name] = {"file": filename, "sha256": _sha(path)}
    unit_manifest = {
        "artifact_schema_version": unit_schema,
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
    run_commit: str | None = None,
    reproduction_commit: str | None = None,
    reproduction_environment_overrides: dict[str, object] | None = None,
    override_basis: str = "2026-08-02 user ruling and independently audited bounded override",
    certificate_format: str = CERTIFICATE_FORMAT,
    scientific_count: int = SCIENTIFIC_COLUMN_COUNT,
    unit_column_count: int = 25,
    unit_schema: str = "unit-o-outcomes-v1",
) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _copy_protected_repo_bytes(repo)
    # D34: the certificate's run commit must exist, because C4 reads the
    # producer from history at that commit.
    synthetic_commit = _commit_synthetic_repo(repo)
    if run_commit is None:
        run_commit = synthetic_commit
    tree = repo / "artifacts" / tree_name
    replay = repo / "artifacts" / "replay"
    _write_tree(
        tree, source_sha=source_sha, dirty=dirty, commit=run_commit,
        scientific_count=scientific_count, unit_column_count=unit_column_count,
        unit_schema=unit_schema,
    )
    replay_commit = run_commit if reproduction_commit is None else reproduction_commit
    _write_tree(
        replay,
        source_sha=source_sha,
        dirty=dirty,
        commit=replay_commit,
        environment_overrides=reproduction_environment_overrides,
        scientific_count=scientific_count,
        unit_column_count=unit_column_count,
        unit_schema=unit_schema,
    )

    tree_sha = ratification._tree_sha256(tree)
    replay_sha = ratification._tree_sha256(replay)
    columns = ratification._scientific_columns(
        tree, expected_count=scientific_count
    )
    replay_columns = ratification._scientific_columns(
        replay, expected_count=scientific_count
    )
    tree_relative = tree.relative_to(repo).as_posix()
    environment = _environment(dirty=dirty, commit=run_commit)
    reproduction_environment = _environment(
        dirty=dirty, commit=replay_commit
    )
    if reproduction_environment_overrides:
        reproduction_environment.update(reproduction_environment_overrides)

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

    ratification_profile_ref = None
    if certificate_format == ratification.V2_CERTIFICATE_FORMAT:
        profile = {
            "audit_entry": audit_ref,
            "certificate_format": ratification.V2_CERTIFICATE_FORMAT,
            "ledger_format": ratification.RATIFICATION_PROFILE_FORMAT,
            "producing_code": {
                "path": "mnq_lab/production/first_exploration_run.py",
                "sha256": PRODUCING_CODE_SHA256,
            },
            "profile_id": "synthetic-v2-profile",
            "program_id": PROGRAM_ID,
            "recorded_at_utc": "2026-08-03T04:00:00+00:00",
            "run_commit": run_commit,
            "scientific_columns": {
                "count": scientific_count,
                "protocol": SCIENTIFIC_COLUMN_PROTOCOL,
            },
            "scope": "Synthetic v2 ratification-profile coverage.",
            "tree_path": tree_relative,
            "unit": UNIT_NAME,
            "unit_o_artifact_schema_version": unit_schema,
        }
        profile_path = (
            repo
            / "mnq_lab/ledger/ratification_profile_entries/synthetic-v2.json"
        )
        _write_json(profile_path, profile)
        ratification_profile_ref = {
            "path": profile_path.relative_to(repo).as_posix(),
            "sha256": _sha(profile_path),
        }

    certificate = {
        "ledger_format": certificate_format,
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
                "scientific_column_count": scientific_count,
            },
            "tolerances": {},
            "fallback": {"allowed": False, "taken": False},
            "peak_memory_bytes": 1024,
            "all_gates_passed": True,
        },
        "reproduction": {
            "tree_path": replay.relative_to(repo).as_posix(),
            "tree_sha256": replay_sha,
            "environment_fingerprint": reproduction_environment,
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
            "C4": {"attested": True},
            "C5": {"passed": True},
            "C6": {"passed": True},
            "C7": {"attested_closed": True},
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    if ratification_profile_ref is not None:
        certificate["ratification_profile"] = ratification_profile_ref
    certificate_path = repo / "mnq_lab/ledger/ratification_entries/certificate.json"
    _write_json(certificate_path, certificate)
    return repo, tree, certificate_path


def _mutate_certificate(path: Path, mutation) -> None:
    certificate = copy.deepcopy(ratification._load_canonical_json(path, "test certificate"))
    mutation(certificate)
    _write_json(path, certificate)


V2_CERTIFICATE = (
    REPO_ROOT
    / "mnq_lab/ledger/ratification_entries"
    / "2026-08-09-phase7-unit-o-session-aware-v2.json"
)
V2_TREE = REPO_ROOT / "data/exploration/derived/phase7-unit-o-session-aware-v2"
V1_TREE = REPO_ROOT / "data/exploration/derived/phase7-unit-o-first-run-v1"


def test_repository_v2_certificate_passes_every_condition():
    result = evaluate_ratification_certificate(V2_CERTIFICATE, repo_root=REPO_ROOT)
    assert result.passed and result.failures == ()
    document = ratification._load_canonical_json(V2_CERTIFICATE, "v2 certificate")
    assert document["ledger_format"] == ratification.V2_CERTIFICATE_FORMAT
    assert document["run_commit"] == "6f1c506b462b8c4e6df93a4ffcc1be04cbbba76f"
    assert document["tree"]["tree_sha256"] == (
        "dc7b3f607d28d2f2a1ccad1cc04340f48b03623a7448c8516734aa3c95e40a87"
    )
    assert len(document["scientific_columns"]) == 110
    # The reproduction is the preserved f51482a archive: a genuine distinct
    # rerun, not the certified tree pointed back at itself.
    assert document["reproduction"]["tree_path"] != document["tree"]["path"]


def test_each_tree_resolves_to_its_own_certificate_and_v1_is_untouched():
    """Two certificates coexist; neither answers for the other's tree."""
    v2 = require_ratified_unit_o(V2_TREE, repo_root=REPO_ROOT)
    v1 = require_ratified_unit_o(V1_TREE, repo_root=REPO_ROOT)

    assert v2["ledger_format"] == ratification.V2_CERTIFICATE_FORMAT
    assert v1["ledger_format"] == CERTIFICATE_FORMAT
    assert v2["certificate_id"] != v1["certificate_id"]
    # v1 still travels the legacy hard-pinned path and still passes.
    assert evaluate_ratification_certificate(
        REPO_ROOT
        / "mnq_lab/ledger/ratification_entries"
        / "2026-08-03-phase7-unit-o-first-run-v1.json",
        repo_root=REPO_ROOT,
    ).passed


def test_negative_case_a_duplicate_certificate_for_one_tree_fails_closed(tmp_path):
    """Proves the resolver above can fail: two certificates, one tree."""
    directory = tmp_path / "ratification_entries"
    directory.mkdir()
    for name in ("first.json", "second.json"):
        (directory / name).write_bytes(V2_CERTIFICATE.read_bytes())

    with pytest.raises(SpineError, match="exactly one Unit O certificate"):
        require_ratified_unit_o(
            V2_TREE, repo_root=REPO_ROOT, certificate_directory=directory
        )


def test_negative_case_v2_certificate_with_a_tampered_profile_reference(tmp_path):
    """The profile binding is load-bearing, not decorative."""
    document = ratification._load_canonical_json(V2_CERTIFICATE, "v2 certificate")
    document["ratification_profile"]["sha256"] = "0" * 64
    tampered = tmp_path / "tampered.json"
    _write_json(tampered, document)

    with pytest.raises(SpineError, match="profile reference hash differs"):
        evaluate_ratification_certificate(tampered, repo_root=REPO_ROOT)


def test_repository_v2_ratification_profile_pins_distinct_artifact_facts():
    profiles = ratification.load_ratification_profiles()
    profile = next(
        item for item in profiles
        if item["tree_path"]
        == "data/exploration/derived/phase7-unit-o-session-aware-v2"
    )
    assert profile["ledger_format"] == ratification.RATIFICATION_PROFILE_FORMAT
    assert profile["certificate_format"] == ratification.V2_CERTIFICATE_FORMAT
    assert profile["producing_code"]["sha256"] == (
        "4aed08c7d8dfcf342fe18d0a1b07ac65ed09947dc3136a5a489c3e1fae8e7fa9"
    )
    assert profile["producing_code"]["sha256"] != PRODUCING_CODE_SHA256
    assert profile["scientific_columns"] == {
        "count": 110,
        "protocol": SCIENTIFIC_COLUMN_PROTOCOL,
    }
    assert profile["unit_o_artifact_schema_version"] == "unit-o-outcomes-v2"


def test_v2_profile_rejects_legacy_producer_pin():
    profile_path = (
        REPO_ROOT
        / "mnq_lab/ledger/ratification_profile_entries/"
        "2026-08-09-phase7-unit-o-session-aware-v2.json"
    )
    profile = ratification._load_canonical_json(profile_path, "test profile")
    profile["producing_code"]["sha256"] = PRODUCING_CODE_SHA256
    with pytest.raises(SpineError, match="producing code bytes differ"):
        ratification._validate_ratification_profile(profile, repo_root=REPO_ROOT)


def test_v2_profile_rejects_legacy_scientific_column_count():
    profile_path = (
        REPO_ROOT
        / "mnq_lab/ledger/ratification_profile_entries/"
        "2026-08-09-phase7-unit-o-session-aware-v2.json"
    )
    profile = ratification._load_canonical_json(profile_path, "test profile")
    profile["scientific_columns"]["count"] = SCIENTIFIC_COLUMN_COUNT
    with pytest.raises(SpineError, match="scientific column count"):
        ratification._validate_ratification_profile(profile, repo_root=REPO_ROOT)


def test_all_seven_conditions_accept_a_complete_synthetic_certificate(tmp_path):
    repo, tree, certificate = _build_case(tmp_path)
    result = evaluate_ratification_certificate(certificate, repo_root=repo)
    assert result.passed and result.failures == ()
    assert result.mechanically_checked == ("C1", "C2", "C3", "C5", "C6")
    assert result.attested_not_proven == ("C4", "C7")
    assert require_ratified_unit_o(
        tree,
        repo_root=repo,
        certificate_directory=certificate.parent,
    )["certificate_id"] == "synthetic-unit-o-certificate"


def test_all_seven_conditions_accept_a_profiled_v2_certificate(tmp_path):
    repo, tree, certificate = _build_case(
        tmp_path,
        certificate_format=ratification.V2_CERTIFICATE_FORMAT,
        scientific_count=110,
        unit_column_count=26,
        unit_schema="unit-o-outcomes-v2",
    )
    document = ratification._load_canonical_json(certificate, "test certificate")
    assert document["ratification_profile"]["path"].startswith(
        "mnq_lab/ledger/ratification_profile_entries/"
    )
    result = evaluate_ratification_certificate(certificate, repo_root=repo)
    assert result.passed and result.failures == ()
    assert len(document["scientific_columns"]) == 110
    assert require_ratified_unit_o(
        tree,
        repo_root=repo,
        certificate_directory=certificate.parent,
    )["ledger_format"] == ratification.V2_CERTIFICATE_FORMAT


def test_v2_certificate_rejects_profile_with_legacy_count(tmp_path):
    repo, _, certificate = _build_case(
        tmp_path,
        certificate_format=ratification.V2_CERTIFICATE_FORMAT,
        scientific_count=110,
        unit_column_count=26,
        unit_schema="unit-o-outcomes-v2",
    )
    document = ratification._load_canonical_json(certificate, "test certificate")
    profile_path = repo / document["ratification_profile"]["path"]
    profile = ratification._load_canonical_json(profile_path, "test profile")
    profile["scientific_columns"]["count"] = SCIENTIFIC_COLUMN_COUNT
    _write_json(profile_path, profile)
    document["ratification_profile"]["sha256"] = _sha(profile_path)
    _write_json(certificate, document)
    with pytest.raises(SpineError, match="scientific column count"):
        evaluate_ratification_certificate(certificate, repo_root=repo)


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


def test_c5_refuses_self_comparison_disguised_as_a_rerun(tmp_path):
    repo, tree, certificate = _build_case(tmp_path)
    columns = ratification._scientific_columns(tree)
    _mutate_certificate(
        certificate,
        lambda value: value["reproduction"].update(
            {
                "tree_path": tree.relative_to(repo).as_posix(),
                "tree_sha256": ratification._tree_sha256(tree),
                "scientific_columns": columns,
            }
        ),
    )
    assert "C5" in evaluate_ratification_certificate(certificate, repo_root=repo).failures


def test_c4_still_catches_a_tampered_producer_at_the_run_commit(tmp_path):
    """D34 negative control: the check reads history, but it still checks.

    Without this, moving C4 from the working tree to git history could have made
    it vacuous -- passing because it looked somewhere that always agreed. Here
    the producer committed at the run commit is deliberately wrong, and C4 must
    fail. Compare with the untampered fixture, which passes.
    """
    clean_root = tmp_path / "clean"
    clean_root.mkdir(parents=True)
    repo, _, certificate = _build_case(clean_root)
    assert evaluate_ratification_certificate(certificate, repo_root=repo).passed

    tampered_root = tmp_path / "tampered"
    tampered_root.mkdir(parents=True)
    repo, _, certificate = _build_case(tampered_root)
    producer = repo / "mnq_lab/production/first_exploration_run.py"
    producer.write_bytes(producer.read_bytes() + b"\n# silently altered producer\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false",
         "commit", "-q", "-m", "tamper"],
        capture_output=True, check=True,
    )
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, check=True
    ).stdout.decode().strip()
    _mutate_certificate(certificate, lambda value: value.__setitem__("run_commit", head))
    assert "C4" in evaluate_ratification_certificate(certificate, repo_root=repo).failures


def test_c4_fails_closed_when_the_run_commit_is_unreachable(tmp_path):
    repo, _, certificate = _build_case(tmp_path)
    _mutate_certificate(
        certificate, lambda value: value.__setitem__("run_commit", "0" * 40)
    )
    assert "C4" in evaluate_ratification_certificate(certificate, repo_root=repo).failures


def test_c5_accepts_commit_only_fingerprint_variance_with_identical_columns(tmp_path):
    repo, _, certificate = _build_case(
        tmp_path,
        reproduction_commit="b" * 40,
    )
    result = evaluate_ratification_certificate(certificate, repo_root=repo)
    assert result.passed and result.failures == ()


@pytest.mark.parametrize(
    ("field", "different_value"),
    (
        ("python", "different-python"),
        ("numpy", "different-numpy"),
        ("pandas", "different-pandas"),
        ("platform", "different-platform"),
        ("machine", "different-machine"),
        ("branch", "different-branch"),
        ("dirty", True),
        ("vcs", "different-vcs"),
        ("pipeline_version", "different-pipeline"),
    ),
)
def test_c5_refuses_every_noncommit_fingerprint_difference(
    tmp_path, field, different_value
):
    repo, _, certificate = _build_case(
        tmp_path,
        reproduction_commit="b" * 40,
        reproduction_environment_overrides={field: different_value},
    )
    assert "C5" in evaluate_ratification_certificate(
        certificate, repo_root=repo
    ).failures


@pytest.mark.parametrize("mutation", ("missing_key", "additional_key"))
def test_c5_refuses_fingerprint_key_set_mutation(tmp_path, mutation):
    repo, _, certificate = _build_case(
        tmp_path,
        reproduction_commit="b" * 40,
    )
    loaded = ratification._load_canonical_json(certificate, "test certificate")
    reproduction = loaded["reproduction"]["environment_fingerprint"]
    replay_manifest = repo / "artifacts/replay/run_manifest.json"
    replay_unit_manifest = repo / "artifacts/replay/unit_o/manifest.json"
    replay_run = ratification._load_canonical_json(replay_manifest, "replay run")
    replay_unit = ratification._load_canonical_json(
        replay_unit_manifest, "replay unit"
    )
    if mutation == "missing_key":
        for value in (
            reproduction,
            replay_run["environment_fingerprint"],
            replay_unit["environment_fingerprint"],
        ):
            value.pop("machine")
    else:
        for value in (
            reproduction,
            replay_run["environment_fingerprint"],
            replay_unit["environment_fingerprint"],
        ):
            value["extra"] = "undeclared"
    _write_json(replay_unit_manifest, replay_unit)
    replay_run["artifact_manifest_sha256"]["unit_o"] = _sha(
        replay_unit_manifest
    )
    _write_json(replay_manifest, replay_run)
    loaded["reproduction"]["tree_sha256"] = ratification._tree_sha256(
        repo / "artifacts/replay"
    )
    _write_json(certificate, loaded)
    assert "C5" in evaluate_ratification_certificate(
        certificate, repo_root=repo
    ).failures


def test_audit_entry_refuses_casefold_identity_collision():
    entry = {
        "ledger_format": AUDIT_FORMAT,
        "entry_id": "identity-collision",
        "program_id": PROGRAM_ID,
        "unit": UNIT_NAME,
        "audited_commit": RUN_COMMIT,
        "audited_tree": "artifacts/candidate",
        "verdict": "CLOSED",
        "date": "2026-08-03",
        "findings": ["named synthetic finding"],
        "auditor_identity": "Independent Party",
        "producer_identity": " independent party ",
        "evidence_hashes": {"evidence": "a" * 64},
    }
    with pytest.raises(SpineError, match="different parties"):
        ratification._validate_audit_entry(entry)


V2_PRIOR_AUDIT_ENTRY = (
    REPO_ROOT
    / "mnq_lab/ledger/audit_entries"
    / "2026-08-09-phase7-unit-o-session-aware-v2.json"
)
V2_AMENDED_AUDIT_ENTRY = (
    REPO_ROOT
    / "mnq_lab/ledger/audit_entries"
    / "2026-08-10-phase7-unit-o-session-aware-v2-evidence-pin-amendment.json"
)
V2_AUDIT_ENTRY = (
    REPO_ROOT
    / "mnq_lab/ledger/audit_entries"
    / "2026-08-11-phase7-unit-o-session-aware-v2-evidence-pin-restoration.json"
)
V2_PRIOR_RUN_COMMIT_AUDIT_ENTRY = (
    REPO_ROOT
    / "mnq_lab/ledger/audit_entries"
    / "2026-08-09-phase7-unit-o-session-aware-v2-run-commit.json"
)
V2_AMENDED_RUN_COMMIT_AUDIT_ENTRY = (
    REPO_ROOT
    / "mnq_lab/ledger/audit_entries"
    / "2026-08-10-phase7-unit-o-session-aware-v2-run-commit-evidence-pin-amendment.json"
)
V2_RESTORED_RUN_COMMIT_AUDIT_ENTRY = (
    REPO_ROOT
    / "mnq_lab/ledger/audit_entries"
    / "2026-08-11-phase7-unit-o-session-aware-v2-run-commit-evidence-pin-restoration.json"
)
V2_RUN_COMMIT_AUDIT_ENTRY = (
    REPO_ROOT
    / "mnq_lab/ledger/audit_entries"
    / "2026-08-12-phase7-unit-o-session-aware-v2-run-commit-direct-pin-restoration.json"
)


def _v2_entry(entry_id: str) -> dict:
    entries = ratification.load_audit_entries(V2_AUDIT_ENTRY.parent)
    return next(entry for entry in entries if entry["entry_id"] == entry_id)


def _v2_audit_entry() -> dict:
    return _v2_entry(
        "2026-08-11-phase7-unit-o-session-aware-v2-evidence-pin-restoration"
    )


def test_v2_audit_entry_records_the_audited_commit_tree_and_closed_verdict():
    entry = _v2_audit_entry()

    assert entry["verdict"] == "CLOSED"
    assert entry["unit"] == UNIT_NAME
    assert entry["audited_commit"] == "cfe5223a2ae0f2d4a14b940479eb70288cd5c22a"
    assert entry["audited_tree"] == (
        "data/exploration/derived/phase7-unit-o-session-aware-v2"
    )
    # C7 refuses an entry whose auditor and producer are the same party.
    assert (
        entry["auditor_identity"].strip().casefold()
        != entry["producer_identity"].strip().casefold()
    )


def _v2_run_commit_audit_entry() -> dict:
    return _v2_entry(
        "2026-08-12-phase7-unit-o-session-aware-v2-run-commit-direct-pin-restoration"
    )


def test_v2_run_commit_entry_carries_the_scope_c7_actually_compares():
    """C7 matches audited_commit against the certificate run_commit.

    The producing commit is 6f1c506; the closeout commit cfe5223a is a
    different question. Both entries stand -- this one is the C7-usable scope.
    """
    entry = _v2_run_commit_audit_entry()

    assert entry["verdict"] == "CLOSED"
    assert entry["unit"] == UNIT_NAME
    assert entry["audited_commit"] == "6f1c506b462b8c4e6df93a4ffcc1be04cbbba76f"
    assert entry["audited_tree"] == _v2_audit_entry()["audited_tree"]
    assert (
        entry["auditor_identity"].strip().casefold()
        != entry["producer_identity"].strip().casefold()
    )
    # It binds the closeout entry it accompanies, so neither can be read alone.
    prior = (
        "mnq_lab/ledger/audit_entries/"
        "2026-08-11-phase7-unit-o-session-aware-v2-evidence-pin-restoration.json"
    )
    assert entry["evidence_hashes"][prior] == hashlib.sha256(
        (REPO_ROOT / prior).read_bytes()
    ).hexdigest()
    assert _mismatched_evidence(entry) == []


def test_the_two_v2_entries_disagree_only_about_scope():
    """A superseding entry must not quietly change the verdict."""
    closeout, run_commit = _v2_audit_entry(), _v2_run_commit_audit_entry()

    assert closeout["audited_commit"] != run_commit["audited_commit"]
    for field in ("verdict", "unit", "audited_tree", "auditor_identity"):
        assert closeout[field] == run_commit[field]
    for entry in (closeout, run_commit):
        joined = "\n".join(entry["findings"])
        assert ".quarantine-failed-v2-e8542c1" in joined
        assert "prospective only" in joined


def test_v2_audit_entry_records_the_tree_digest_and_quarantine_limitation():
    """The two facts the verdict must not lose: what was audited, and what was not."""
    findings = "\n".join(entry for entry in _v2_audit_entry()["findings"])

    assert (
        "dc7b3f607d28d2f2a1ccad1cc04340f48b03623a7448c8516734aa3c95e40a87"
        in findings
    )
    assert ".quarantine-failed-v2-e8542c1" in findings
    assert "non-retroactive" in findings.casefold()
    assert "prospective only" in findings


def _mismatched_evidence(entry: dict) -> list[str]:
    """Repository-resident evidence whose recorded hash is not the file's hash."""
    bad = []
    for relative, digest in entry["evidence_hashes"].items():
        path = REPO_ROOT / relative
        if not path.is_file():
            continue  # external receipt evidence lives outside the repository
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            bad.append(relative)
    return bad


def _assert_evidence_superset(effective: dict, prior: dict) -> None:
    effective_paths = set(effective["evidence_hashes"])
    documented_withdrawals = {
        path
        for path, entry_id in WITHDRAWN_EVIDENCE.items()
        if entry_id == effective["entry_id"]
    }
    required_paths = set(prior["evidence_hashes"]) - documented_withdrawals
    missing = sorted(required_paths - effective_paths)
    assert effective_paths >= required_paths, (
        "evidence withdrawn without an explicit WITHDRAWN_EVIDENCE record: "
        + ", ".join(missing)
    )


def test_v2_audit_entry_evidence_hashes_match_the_repository_bytes():
    """Every in-repository evidence hash is re-read, not trusted."""
    entry = _v2_audit_entry()
    assert _mismatched_evidence(entry) == []


def test_negative_case_a_tampered_evidence_hash_is_detected():
    """Proves the check above can fail: flip one digit and it must be caught."""
    entry = copy.deepcopy(_v2_audit_entry())
    relative = "docs/DISCREPANCIES.md"
    original = entry["evidence_hashes"][relative]
    entry["evidence_hashes"][relative] = (
        "0" if original[0] != "0" else "1"
    ) + original[1:]

    assert _mismatched_evidence(entry) == [relative]
    # Still schema-valid, so byte-level re-reading -- not schema validation --
    # is what catches this class of defect.
    ratification._validate_audit_entry(entry)


def test_v2_evidence_pin_restorations_bind_the_immutable_prior_entries():
    closeout, run_commit = _v2_audit_entry(), _v2_run_commit_audit_entry()
    amended_closeout = _v2_entry(
        "2026-08-10-phase7-unit-o-session-aware-v2-evidence-pin-amendment"
    )
    amended_run = _v2_entry(
        "2026-08-10-phase7-unit-o-session-aware-v2-run-commit-evidence-pin-amendment"
    )
    restored_run = _v2_entry(
        "2026-08-11-phase7-unit-o-session-aware-v2-run-commit-evidence-pin-restoration"
    )
    prior_closeout = V2_PRIOR_AUDIT_ENTRY.relative_to(REPO_ROOT).as_posix()
    prior_run = V2_PRIOR_RUN_COMMIT_AUDIT_ENTRY.relative_to(REPO_ROOT).as_posix()
    amended_closeout_path = V2_AMENDED_AUDIT_ENTRY.relative_to(REPO_ROOT).as_posix()
    amended_run_path = V2_AMENDED_RUN_COMMIT_AUDIT_ENTRY.relative_to(
        REPO_ROOT
    ).as_posix()
    restored_closeout_path = V2_AUDIT_ENTRY.relative_to(REPO_ROOT).as_posix()

    assert amended_closeout["evidence_hashes"][prior_closeout] == hashlib.sha256(
        V2_PRIOR_AUDIT_ENTRY.read_bytes()
    ).hexdigest()
    assert amended_run["evidence_hashes"][prior_run] == hashlib.sha256(
        V2_PRIOR_RUN_COMMIT_AUDIT_ENTRY.read_bytes()
    ).hexdigest()
    assert amended_run["evidence_hashes"][amended_closeout_path] == hashlib.sha256(
        V2_AMENDED_AUDIT_ENTRY.read_bytes()
    ).hexdigest()
    assert closeout["evidence_hashes"][amended_closeout_path] == hashlib.sha256(
        V2_AMENDED_AUDIT_ENTRY.read_bytes()
    ).hexdigest()
    assert run_commit["evidence_hashes"][amended_run_path] == hashlib.sha256(
        V2_AMENDED_RUN_COMMIT_AUDIT_ENTRY.read_bytes()
    ).hexdigest()
    assert run_commit["evidence_hashes"][restored_closeout_path] == hashlib.sha256(
        V2_AUDIT_ENTRY.read_bytes()
    ).hexdigest()
    assert set(run_commit["evidence_hashes"]) == (
        set(restored_run["evidence_hashes"]) | {prior_closeout}
    )
    for relative, digest in restored_run["evidence_hashes"].items():
        assert run_commit["evidence_hashes"][relative] == digest
    assert run_commit["evidence_hashes"][prior_closeout] == hashlib.sha256(
        V2_PRIOR_AUDIT_ENTRY.read_bytes()
    ).hexdigest()

    # Negative witness: a schema-valid restoration with a corrupted prior-entry
    # pin is detected by repository-byte re-reading.
    altered = copy.deepcopy(closeout)
    original = altered["evidence_hashes"][amended_closeout_path]
    altered["evidence_hashes"][amended_closeout_path] = (
        "0" if original[0] != "0" else "1"
    ) + original[1:]
    assert _mismatched_evidence(altered) == [amended_closeout_path]
    ratification._validate_audit_entry(altered)


def test_v2_restorations_prevent_undocumented_evidence_withdrawal(monkeypatch):
    prior_closeout = _v2_entry(
        "2026-08-09-phase7-unit-o-session-aware-v2-audit"
    )
    prior_run = _v2_entry(
        "2026-08-09-phase7-unit-o-session-aware-v2-run-commit-audit"
    )
    amended_closeout = _v2_entry(
        "2026-08-10-phase7-unit-o-session-aware-v2-evidence-pin-amendment"
    )
    amended_run = _v2_entry(
        "2026-08-10-phase7-unit-o-session-aware-v2-run-commit-evidence-pin-amendment"
    )
    restored_closeout = _v2_audit_entry()
    restored_run = _v2_entry(
        "2026-08-11-phase7-unit-o-session-aware-v2-run-commit-evidence-pin-restoration"
    )
    effective_run = _v2_run_commit_audit_entry()

    # Historical negative controls: this guard catches the undisclosed shrinkage
    # in both 2026-08-10 entries. The run-commit entry also replaced its direct
    # closeout pin with a transitive binding through the closeout amendment.
    with pytest.raises(AssertionError, match="child.stderr.log"):
        _assert_evidence_superset(amended_closeout, prior_closeout)
    with pytest.raises(AssertionError, match="child.stderr.log"):
        _assert_evidence_superset(amended_run, prior_run)

    # Current effective entries may add pins, but may not drop any immediate
    # predecessor pin without an explicit record in WITHDRAWN_EVIDENCE.
    _assert_evidence_superset(restored_closeout, amended_closeout)
    _assert_evidence_superset(restored_run, amended_run)
    _assert_evidence_superset(effective_run, restored_run)
    _assert_evidence_superset(restored_closeout, prior_closeout)
    _assert_evidence_superset(effective_run, prior_run)

    assert len(restored_closeout["evidence_hashes"]) == 18
    assert len(restored_run["evidence_hashes"]) == 20
    assert len(effective_run["evidence_hashes"]) == 21

    # Negative witness: deleting one restored receipt pin remains schema-valid,
    # and only the evidence-set rule identifies and names the withdrawal.
    altered = copy.deepcopy(restored_closeout)
    dropped = (
        "C:/Users/kyawz/mnq_atlas_runs/phase7-unit-o-v2-final-"
        "6f1c506-attempt-2/child.stdout.log"
    )
    del altered["evidence_hashes"][dropped]
    ratification._validate_audit_entry(altered)
    with pytest.raises(AssertionError) as exc_info:
        _assert_evidence_superset(altered, prior_closeout)
    assert dropped in str(exc_info.value)

    # The effective run-commit path is independently guarded against its
    # original evidence set, including all six restored receipt pins.
    altered_run = copy.deepcopy(effective_run)
    del altered_run["evidence_hashes"][dropped]
    ratification._validate_audit_entry(altered_run)
    with pytest.raises(AssertionError) as run_exc_info:
        _assert_evidence_superset(altered_run, prior_run)
    assert dropped in str(run_exc_info.value)
    assert _mismatched_evidence(altered_run) == []

    # Exercise the explicit withdrawal mechanism rather than leaving it inert:
    # the same missing path is allowed only for the entry that documents it.
    assert WITHDRAWN_EVIDENCE == {}
    monkeypatch.setitem(WITHDRAWN_EVIDENCE, dropped, effective_run["entry_id"])
    _assert_evidence_superset(altered_run, prior_run)
    with pytest.raises(AssertionError, match="child.stdout.log"):
        _assert_evidence_superset(altered, prior_closeout)


def test_negative_case_the_v2_entry_must_be_canonical_json(tmp_path):
    directory = tmp_path / "audit_entries"
    directory.mkdir()
    target = directory / V2_AUDIT_ENTRY.name
    target.write_bytes(V2_AUDIT_ENTRY.read_bytes())
    assert ratification.load_audit_entries(directory)

    target.write_bytes(V2_AUDIT_ENTRY.read_bytes().replace(b"\n", b"", 1))
    with pytest.raises(SpineError, match="canonical sorted UTF-8 JSON"):
        ratification.load_audit_entries(directory)


def test_claim_boundary_labels_c4_and_c7_as_attestations():
    assert "C4 is a retrospective attestation" in CLAIM_BOUNDARY
    assert "C2 visibility" in CLAIM_BOUNDARY
    assert "not externally anchored" in CLAIM_BOUNDARY
    assert "C7 is a human attestation" in CLAIM_BOUNDARY
    assert "Append-only is repository policy" in CLAIM_BOUNDARY


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


def test_repository_unit_o_audit_and_certificate_validate_exact_completed_tree():
    audit_path = (
        REPO_ROOT
        / "mnq_lab/ledger/audit_entries/2026-08-02-unit-o-first-run-v1.json"
    )
    certificate_path = (
        REPO_ROOT
        / "mnq_lab/ledger/ratification_entries/"
        "2026-08-03-phase7-unit-o-first-run-v1.json"
    )
    entries = ratification.load_audit_entries(audit_path.parent)
    # Exact list, not a membership check: an unexpected or missing verdict entry
    # must fail here. The v2 entry is appended, never edited into the v1 one.
    assert [entry["entry_id"] for entry in entries] == [
        "2026-08-02-unit-o-first-run-v1-audit",
        "2026-08-09-phase7-unit-o-session-aware-v2-run-commit-audit",
        "2026-08-09-phase7-unit-o-session-aware-v2-audit",
        "2026-08-10-phase7-unit-o-session-aware-v2-evidence-pin-amendment",
        "2026-08-10-phase7-unit-o-session-aware-v2-run-commit-evidence-pin-amendment",
        "2026-08-11-phase7-unit-o-session-aware-v2-evidence-pin-restoration",
        "2026-08-11-phase7-unit-o-session-aware-v2-run-commit-evidence-pin-restoration",
        "2026-08-12-phase7-unit-o-session-aware-v2-run-commit-direct-pin-restoration",
    ]
    result = evaluate_ratification_certificate(
        certificate_path, repo_root=REPO_ROOT
    )
    assert result.passed and result.failures == ()
    tree = (
        REPO_ROOT
        / "data/exploration/derived/phase7-unit-o-first-run-v1"
    )
    certificate = require_ratified_unit_o(tree, repo_root=REPO_ROOT)
    assert certificate["certificate_id"] == (
        "2026-08-03-phase7-unit-o-first-run-v1-ratification"
    )
