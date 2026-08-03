"""Fail-closed Unit O audit-verdict and ratification-certificate ledger.

The producing run has no import of this module and cannot write either ledger.
Entry files are canonical JSON and append-only by repository policy: corrections
are new files, never edits to an existing entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping

from mnq_lab import SpineError
from mnq_lab.constants import REPO_ROOT
from mnq_lab.production.first_exploration_run import (
    FREE_MEMORY_PREFLIGHT_BYTES,
    GATE_CLASSIFICATION,
    PEAK_MEMORY_CEILING_BYTES,
)


AUDIT_LEDGER_DIR = Path(__file__).resolve().parent / "audit_entries"
COMPLETION_LEDGER_DIR = Path(__file__).resolve().parent / "run_completion_entries"
RATIFICATION_LEDGER_DIR = Path(__file__).resolve().parent / "ratification_entries"

AUDIT_FORMAT = "unit_audit_verdict_v1"
COMPLETION_FORMAT = "run_completion_record_v1"
CERTIFICATE_FORMAT = "unit_o_ratification_certificate_v1"
PROGRAM_ID = "mnq-atlas-001"
UNIT_NAME = "Unit O"
NON_ADMISSIBLE_STAMP = "NON-ADMISSIBLE DIAGNOSTIC ARTIFACTS"
SCIENTIFIC_COLUMN_COUNT = 109
SCIENTIFIC_COLUMN_PROTOCOL = "npy-file-sha256-v1"

CRITERIA_COMMIT = "5996e8f9791bda01d2957b903ae026e75347c36b"
CRITERIA_COMMITTED_AT = "2026-08-02T19:32:39-07:00"
CRITERIA_DOCUMENT_SHA256 = (
    "e97f11f00b3ea898ff121773c5ea3203b825e4774f5df9ba792175bf37a70f97"
)
D22_SHA256 = "cf27329a329df856290a945eec47ad19e52b0298110b1bfe9c1a75581d0386cf"
PRODUCING_CODE_SHA256 = (
    "5c6b3b2d6e5b06533c07489018b7c74932ad32aa823304f535103d6cef31613a"
)

PINNED_INPUTS = {
    "REV6_FROZEN_SPEC.md": (
        "70dae16c8b12fe26d38a7bfdabf0202066fe7149f790d0d2942279d9c3b8ff50"
    ),
    "analysis_constants_v1.yaml": (
        "1c95aa595c30c48b853303291a7dbaabceaf5b7331bca565a30863e8dcf138d4"
    ),
    "docs/OUTCOME_LAYER_PREREGISTRATION.md": (
        "4b5bc97fdfd4b0219c69e6a8adf76f18072091a9389700191d3ddcd10f8207c8"
    ),
    "docs/PHASE8_PREREGISTRATION.md": (
        "d07174ed0acc9e60ab6b255f4b33fc08141969c64e04f66e1e08c0aca98b4680"
    ),
}
SOURCE_STORE_MANIFEST_SHA256 = (
    "1cf6ec5ce7822ce1333984909b52d5c937e4ccc06e280030bcacda22620ffd73"
)
CERTIFICATE_PINNED_INPUTS = {
    "canonical_source_store_manifest": SOURCE_STORE_MANIFEST_SHA256,
    **PINNED_INPUTS,
}

CLAIM_BOUNDARY = (
    "C1-C6 passed mechanical validation. C7 is a recorded human attestation; "
    "code cannot prove that no person inspected outcomes before the criteria "
    "were fixed or that the audit was genuinely blind and independent."
)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class RatificationResult:
    passed: bool
    failures: tuple[str, ...]
    mechanically_checked: tuple[str, ...] = ("C1", "C2", "C3", "C4", "C5", "C6")
    attested_not_proven: tuple[str, ...] = ("C7",)


def canonical_json_bytes(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            indent=2,
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise SpineError(f"ledger record is not strict JSON: {exc}") from exc
    return (encoded + "\n").encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise SpineError(f"cannot hash ratification evidence {path}: {exc}") from exc
    return digest.hexdigest()


def _load_canonical_json(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpineError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SpineError(f"{label} must be a JSON object")
    if raw != canonical_json_bytes(value):
        raise SpineError(f"{label} is not canonical sorted UTF-8 JSON")
    return value


def _reject_constant(token: str) -> None:
    raise SpineError(f"ledger record contains non-standard JSON constant {token}")


def _require_exact_keys(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise SpineError(f"{label} fields differ from the frozen schema")
    return value


def _require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise SpineError(f"{label} is not lowercase SHA-256")
    return value


def _require_commit(value: Any, label: str) -> str:
    if not isinstance(value, str) or COMMIT_RE.fullmatch(value) is None:
        raise SpineError(f"{label} is not a full lowercase commit SHA")
    return value


def _parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise SpineError(f"{label} is not an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SpineError(f"{label} is not an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SpineError(f"{label} must be timezone-aware")
    return parsed


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError as exc:
        raise SpineError(f"cannot inspect ratification path {path}: {exc}") from exc
    return bool(attributes & getattr(os.stat_result, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _resolve_repo_path(repo_root: Path, relative: Any, label: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise SpineError(f"{label} must be a nonempty POSIX repository-relative path")
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise SpineError(f"{label} escapes the repository")
    root = Path(repo_root).resolve(strict=True)
    target = (root / candidate).resolve(strict=True)
    if target != root and root not in target.parents:
        raise SpineError(f"{label} escapes the repository")
    probe = root
    for part in candidate.parts:
        probe = probe / part
        if probe.is_symlink() or _is_reparse_point(probe):
            raise SpineError(f"{label} traverses a symlink or reparse point")
    return target


def _tree_sha256(root: Path) -> str:
    if not root.is_dir():
        raise SpineError(f"certified tree is not a directory: {root}")
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not files:
        raise SpineError("certified tree contains no files")
    for path in files:
        if path.is_symlink() or _is_reparse_point(path):
            raise SpineError("certified tree contains a symlink or reparse point")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        byte_count = path.stat().st_size
        file_sha = _sha256_file(path).encode("ascii")
        digest.update(relative + b"\0" + str(byte_count).encode("ascii"))
        digest.update(b"\0" + file_sha + b"\n")
    return digest.hexdigest()


def _d22_sha256(path: Path) -> str:
    raw = path.read_bytes()
    marker = b"## D22 - Unit O ratification criteria"
    start = raw.find(marker)
    if start < 0:
        raise SpineError("D22 is absent from discrepancies")
    next_entry = raw.find(b"\n---\n\n## D", start + len(marker))
    end = len(raw) if next_entry < 0 else next_entry + 1
    return hashlib.sha256(raw[start:end]).hexdigest()


def _scientific_columns(tree: Path) -> list[dict[str, str]]:
    phase7 = _load_canonical_json(tree / "phase7" / "manifest.json", "Phase 7 manifest")
    unit_o = _load_canonical_json(tree / "unit_o" / "manifest.json", "Unit O manifest")
    result: list[dict[str, str]] = []

    tables = phase7.get("tables")
    if not isinstance(tables, dict) or not tables:
        raise SpineError("Phase 7 manifest has no tables")
    for table_name in sorted(tables):
        table = tables[table_name]
        if not isinstance(table, dict):
            raise SpineError(f"Phase 7 table {table_name!r} is malformed")
        order = table.get("column_order")
        columns = table.get("columns")
        if not isinstance(order, list) or not isinstance(columns, dict) or set(order) != set(columns):
            raise SpineError(f"Phase 7 table {table_name!r} columns are incomplete")
        for column in order:
            record = columns[column]
            if not isinstance(record, dict) or not isinstance(record.get("file"), str):
                raise SpineError(f"Phase 7 column {table_name}.{column} is malformed")
            relative = f"phase7/{record['file']}"
            path = _resolve_repo_path(
                tree / "phase7", record["file"], f"Phase 7 column {column}"
            )
            actual = _sha256_file(path)
            if record.get("sha256") != actual:
                raise SpineError(f"Phase 7 column hash differs for {table_name}.{column}")
            result.append({"relative_path": relative, "column": f"{table_name}.{column}", "sha256": actual})

    order = unit_o.get("column_order")
    columns = unit_o.get("columns")
    if not isinstance(order, list) or not isinstance(columns, dict) or set(order) != set(columns):
        raise SpineError("Unit O manifest columns are incomplete")
    for column in order:
        record = columns[column]
        if not isinstance(record, dict) or not isinstance(record.get("file"), str):
            raise SpineError(f"Unit O column {column!r} is malformed")
        path = _resolve_repo_path(tree / "unit_o", record["file"], f"Unit O column {column}")
        actual = _sha256_file(path)
        if record.get("sha256") != actual:
            raise SpineError(f"Unit O column hash differs for {column}")
        result.append({"relative_path": f"unit_o/{record['file']}", "column": f"unit_o.{column}", "sha256": actual})

    if len(result) != SCIENTIFIC_COLUMN_COUNT:
        raise SpineError(
            f"scientific column count is {len(result)}, expected {SCIENTIFIC_COLUMN_COUNT}"
        )
    identities = [(item["relative_path"], item["column"]) for item in result]
    if len(identities) != len(set(identities)):
        raise SpineError("scientific column identities are duplicated")
    return result


def _validate_audit_entry(entry: Mapping[str, Any]) -> None:
    keys = {
        "ledger_format", "entry_id", "program_id", "unit", "audited_commit",
        "audited_tree", "verdict", "date", "findings", "auditor_identity",
        "producer_identity", "evidence_hashes",
    }
    _require_exact_keys(entry, keys, "audit-verdict entry")
    if entry["ledger_format"] != AUDIT_FORMAT or entry["program_id"] != PROGRAM_ID:
        raise SpineError("audit-verdict ledger format or program differs")
    if not isinstance(entry["entry_id"], str) or not entry["entry_id"]:
        raise SpineError("audit-verdict entry_id is empty")
    if not isinstance(entry["unit"], str) or not entry["unit"]:
        raise SpineError("audit-verdict unit is empty")
    _require_commit(entry["audited_commit"], "audit-verdict audited_commit")
    if not isinstance(entry["audited_tree"], str) or not entry["audited_tree"]:
        raise SpineError("audit-verdict audited_tree is empty")
    if entry["verdict"] not in {"OPEN", "CLOSED", "REJECTED"}:
        raise SpineError("audit-verdict verdict is unknown")
    _parse_timestamp(f"{entry['date']}T00:00:00+00:00", "audit-verdict date")
    if not isinstance(entry["findings"], list) or not entry["findings"] or any(
        not isinstance(item, str) or not item.strip() for item in entry["findings"]
    ):
        raise SpineError("audit-verdict findings must be nonempty strings")
    for identity in ("auditor_identity", "producer_identity"):
        if not isinstance(entry[identity], str) or not entry[identity].strip():
            raise SpineError(f"audit-verdict {identity} is empty")
    evidence = entry["evidence_hashes"]
    if not isinstance(evidence, dict) or not evidence:
        raise SpineError("audit-verdict evidence_hashes are empty")
    for path, digest in evidence.items():
        if not isinstance(path, str) or not path:
            raise SpineError("audit-verdict evidence path is empty")
        _require_sha(digest, f"audit-verdict evidence hash for {path}")


def load_audit_entries(directory: Path = AUDIT_LEDGER_DIR) -> list[dict[str, Any]]:
    paths = sorted(Path(directory).glob("*.json"))
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        entry = _load_canonical_json(path, "audit-verdict entry")
        _validate_audit_entry(entry)
        if entry["entry_id"] in seen:
            raise SpineError(f"duplicate audit-verdict entry_id {entry['entry_id']!r}")
        seen.add(entry["entry_id"])
        entries.append(entry)
    return entries


def _certificate_skeleton(certificate: Mapping[str, Any]) -> None:
    keys = {
        "ledger_format", "certificate_id", "program_id", "unit", "decision_date",
        "tree", "scientific_column_protocol", "scientific_columns", "run_commit",
        "environment_fingerprint", "criteria", "run_completion_record",
        "pinned_inputs", "gate_evidence", "reproduction",
        "non_admissible_override", "audit_entry", "conditions", "claim_boundary",
    }
    _require_exact_keys(certificate, keys, "ratification certificate")
    if certificate["ledger_format"] != CERTIFICATE_FORMAT:
        raise SpineError("ratification certificate format differs")
    if certificate["program_id"] != PROGRAM_ID or certificate["unit"] != UNIT_NAME:
        raise SpineError("ratification certificate program or unit differs")
    if not isinstance(certificate["certificate_id"], str) or not certificate["certificate_id"]:
        raise SpineError("ratification certificate_id is empty")
    if certificate["claim_boundary"] != CLAIM_BOUNDARY:
        raise SpineError("ratification certificate overstates its claim boundary")
    if certificate["scientific_column_protocol"] != SCIENTIFIC_COLUMN_PROTOCOL:
        raise SpineError("scientific-column hashing protocol differs")
    _require_commit(certificate["run_commit"], "certificate run_commit")
    expected_conditions = {
        "C1": {"passed": True}, "C2": {"passed": True},
        "C3": {"passed": True}, "C4": {"passed": True},
        "C5": {"passed": True}, "C6": {"passed": True},
        "C7": {"attested_closed": True},
    }
    if certificate["conditions"] != expected_conditions:
        raise SpineError("certificate does not claim every required condition")


def evaluate_ratification_certificate(
    certificate_path: Path,
    *,
    repo_root: Path = REPO_ROOT,
) -> RatificationResult:
    """Evaluate every condition and return all failing condition codes."""
    certificate = _load_canonical_json(Path(certificate_path), "ratification certificate")
    _certificate_skeleton(certificate)
    repo = Path(repo_root).resolve(strict=True)
    failures: list[str] = []

    tree_record = _require_exact_keys(
        certificate["tree"],
        {"path", "tree_sha256", "unit_o_manifest_sha256", "run_manifest_sha256"},
        "certificate tree",
    )
    tree = _resolve_repo_path(repo, tree_record["path"], "certificate tree path")
    actual_tree_sha = _tree_sha256(tree)
    run_manifest_path = tree / "run_manifest.json"
    unit_manifest_path = tree / "unit_o" / "manifest.json"
    run_manifest = _load_canonical_json(run_manifest_path, "run manifest")
    unit_manifest = _load_canonical_json(unit_manifest_path, "Unit O manifest")
    try:
        actual_columns = _scientific_columns(tree)
    except SpineError:
        actual_columns = None

    try:
        if certificate["pinned_inputs"] != CERTIFICATE_PINNED_INPUTS:
            raise SpineError("certificate pinned inputs differ")
        for relative, expected in PINNED_INPUTS.items():
            if _sha256_file(_resolve_repo_path(repo, relative, f"pinned input {relative}")) != expected:
                raise SpineError(f"pinned input bytes differ for {relative}")
        if run_manifest.get("source_store_manifest_sha256") != SOURCE_STORE_MANIFEST_SHA256:
            raise SpineError("run source-store manifest hash differs")
        if unit_manifest.get("input_store_manifest_sha256") != SOURCE_STORE_MANIFEST_SHA256:
            raise SpineError("Unit O source-store manifest hash differs")
        if unit_manifest.get("frozen_inputs") != PINNED_INPUTS:
            raise SpineError("Unit O frozen input bindings differ")
    except SpineError:
        failures.append("C1")

    try:
        criteria = _require_exact_keys(
            certificate["criteria"],
            {"commit", "committed_at_utc", "document_sha256", "d22_sha256"},
            "certificate criteria",
        )
        if criteria != {
            "commit": CRITERIA_COMMIT,
            "committed_at_utc": CRITERIA_COMMITTED_AT,
            "document_sha256": CRITERIA_DOCUMENT_SHA256,
            "d22_sha256": D22_SHA256,
        }:
            raise SpineError("criteria identity differs")
        if _sha256_file(repo / "docs" / "UNIT_O_RATIFICATION_PREREGISTRATION.md") != CRITERIA_DOCUMENT_SHA256:
            raise SpineError("criteria document bytes differ")
        if _d22_sha256(repo / "docs" / "DISCREPANCIES.md") != D22_SHA256:
            raise SpineError("D22 bytes differ")
        completion_ref = _require_exact_keys(
            certificate["run_completion_record"], {"path", "sha256"},
            "run completion reference",
        )
        completion_path = _resolve_repo_path(repo, completion_ref["path"], "run completion path")
        if _sha256_file(completion_path) != _require_sha(completion_ref["sha256"], "completion hash"):
            raise SpineError("run completion record hash differs")
        completion = _load_canonical_json(completion_path, "run completion record")
        _require_exact_keys(
            completion,
            {"ledger_format", "entry_id", "run_commit", "tree_path", "tree_sha256", "run_manifest_sha256", "visible_at_utc", "recorder_identity"},
            "run completion record",
        )
        if completion["ledger_format"] != COMPLETION_FORMAT:
            raise SpineError("run completion format differs")
        if completion["run_commit"] != certificate["run_commit"]:
            raise SpineError("run completion commit differs")
        if completion["tree_path"] != tree_record["path"] or completion["tree_sha256"] != actual_tree_sha:
            raise SpineError("run completion tree identity differs")
        if completion["run_manifest_sha256"] != _sha256_file(run_manifest_path):
            raise SpineError("run completion manifest identity differs")
        if _parse_timestamp(criteria["committed_at_utc"], "criteria commit time") >= _parse_timestamp(completion["visible_at_utc"], "visibility time"):
            raise SpineError("criteria did not strictly precede result visibility")
    except SpineError:
        failures.append("C2")

    try:
        environment = certificate["environment_fingerprint"]
        if not isinstance(environment, dict) or not environment:
            raise SpineError("environment fingerprint is empty")
        if environment != run_manifest.get("environment_fingerprint"):
            raise SpineError("certificate/run environment fingerprint differs")
        if environment.get("commit") != certificate["run_commit"] or environment.get("dirty") is not False:
            raise SpineError("run did not use one clean committed state")
        if unit_manifest.get("code_commit") != certificate["run_commit"] or unit_manifest.get("dirty_worktree") is not False:
            raise SpineError("Unit O manifest code state differs")
    except SpineError:
        failures.append("C3")

    try:
        gates = _require_exact_keys(
            certificate["gate_evidence"],
            {"producing_code_sha256", "gate_records", "thresholds", "tolerances", "fallback", "peak_memory_bytes", "all_gates_passed"},
            "gate evidence",
        )
        if gates["producing_code_sha256"] != PRODUCING_CODE_SHA256:
            raise SpineError("producing code hash differs")
        if _sha256_file(repo / "mnq_lab" / "production" / "first_exploration_run.py") != PRODUCING_CODE_SHA256:
            raise SpineError("producing code bytes differ")
        expected_gate_records = [dict(record, passed=True) for record in GATE_CLASSIFICATION]
        if gates["gate_records"] != expected_gate_records or gates["all_gates_passed"] is not True:
            raise SpineError("gate pass records are incomplete or changed")
        if gates["thresholds"] != {
            "free_memory_preflight_bytes": FREE_MEMORY_PREFLIGHT_BYTES,
            "peak_memory_ceiling_bytes": PEAK_MEMORY_CEILING_BYTES,
            "scientific_column_count": SCIENTIFIC_COLUMN_COUNT,
        }:
            raise SpineError("gate thresholds were relaxed or changed")
        if gates["tolerances"] != {}:
            raise SpineError("a ratification tolerance was added")
        if gates["fallback"] != {"allowed": False, "taken": False}:
            raise SpineError("a ratification fallback was allowed or taken")
        peak = run_manifest.get("peak_memory_bytes")
        if type(peak) is not int or peak <= 0 or peak > PEAK_MEMORY_CEILING_BYTES or gates["peak_memory_bytes"] != peak:
            raise SpineError("peak-memory gate did not hold")
        if run_manifest.get("gate_classification") != list(GATE_CLASSIFICATION):
            raise SpineError("run gate classification differs")
    except SpineError:
        failures.append("C4")

    try:
        if actual_columns is None:
            raise SpineError("certified scientific column bytes are invalid")
        if certificate["scientific_columns"] != actual_columns:
            raise SpineError("certificate scientific hashes do not match tree bytes")
        reproduction = _require_exact_keys(
            certificate["reproduction"],
            {"tree_path", "tree_sha256", "environment_fingerprint", "scientific_columns"},
            "reproduction evidence",
        )
        comparison = _resolve_repo_path(repo, reproduction["tree_path"], "comparison tree path")
        if reproduction["tree_sha256"] != _tree_sha256(comparison):
            raise SpineError("comparison tree identity differs")
        if reproduction["environment_fingerprint"] != certificate["environment_fingerprint"]:
            raise SpineError("reproduction environment fingerprint differs")
        comparison_columns = _scientific_columns(comparison)
        if reproduction["scientific_columns"] != comparison_columns or comparison_columns != actual_columns:
            raise SpineError("scientific columns are not bit-identical")
    except SpineError:
        failures.append("C5")

    audit: dict[str, Any] | None = None
    audit_path: Path | None = None
    try:
        audit_ref = _require_exact_keys(certificate["audit_entry"], {"path", "sha256"}, "audit reference")
        audit_path = _resolve_repo_path(repo, audit_ref["path"], "audit entry path")
        if _sha256_file(audit_path) != _require_sha(audit_ref["sha256"], "audit entry hash"):
            raise SpineError("audit entry hash differs")
        audit = _load_canonical_json(audit_path, "audit-verdict entry")
        _validate_audit_entry(audit)
        override = _require_exact_keys(
            certificate["non_admissible_override"],
            {"stamp", "scope_tree_sha256", "scope_run_commit", "decision_date", "decider_identity", "basis", "audit_entry"},
            "non-admissible override",
        )
        if run_manifest.get("admissibility") != NON_ADMISSIBLE_STAMP or override["stamp"] != NON_ADMISSIBLE_STAMP:
            raise SpineError("non-admissible stamp differs")
        if override["scope_tree_sha256"] != actual_tree_sha or override["scope_run_commit"] != certificate["run_commit"]:
            raise SpineError("non-admissible override scope differs")
        if not isinstance(override["basis"], str) or not override["basis"].strip():
            raise SpineError("non-admissible override has no recorded basis")
        if not isinstance(override["decider_identity"], str) or not override["decider_identity"].strip():
            raise SpineError("non-admissible override has no decider")
        if override["audit_entry"] != certificate["audit_entry"]:
            raise SpineError("non-admissible override audit reference differs")
    except SpineError:
        failures.append("C6")

    try:
        if audit is None or audit_path is None:
            raise SpineError("C7 has no valid audit entry")
        if audit["verdict"] != "CLOSED" or audit["unit"] != UNIT_NAME:
            raise SpineError("Unit O audit is not CLOSED")
        if audit["audited_commit"] != certificate["run_commit"] or audit["audited_tree"] != tree_record["path"]:
            raise SpineError("audit scope differs from certificate")
        if audit["auditor_identity"].strip().casefold() == audit["producer_identity"].strip().casefold():
            raise SpineError("audit records the producer as auditor")
    except SpineError:
        failures.append("C7")

    if tree_record["tree_sha256"] != actual_tree_sha:
        failures.extend(code for code in ("C2", "C5", "C6") if code not in failures)
    if tree_record["run_manifest_sha256"] != _sha256_file(run_manifest_path):
        failures.extend(code for code in ("C2", "C3", "C4") if code not in failures)
    if tree_record["unit_o_manifest_sha256"] != _sha256_file(unit_manifest_path):
        failures.extend(code for code in ("C1", "C3", "C5") if code not in failures)
    if run_manifest.get("artifact_manifest_sha256", {}).get("unit_o") != _sha256_file(unit_manifest_path):
        failures.extend(code for code in ("C1", "C5") if code not in failures)

    ordered = tuple(code for code in ("C1", "C2", "C3", "C4", "C5", "C6", "C7") if code in failures)
    return RatificationResult(passed=not ordered, failures=ordered)


def require_ratified_unit_o(
    tree_root: Path,
    *,
    repo_root: Path = REPO_ROOT,
    certificate_directory: Path = RATIFICATION_LEDGER_DIR,
) -> dict[str, Any]:
    """Phase 8 guard: require exactly one applicable, fully valid certificate."""
    repo = Path(repo_root).resolve(strict=True)
    tree = Path(tree_root).resolve(strict=True)
    try:
        relative = tree.relative_to(repo).as_posix()
    except ValueError as exc:
        raise SpineError("Phase 8 Unit O input is outside the repository") from exc
    matches: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(Path(certificate_directory).glob("*.json")):
        certificate = _load_canonical_json(path, "ratification certificate")
        _certificate_skeleton(certificate)
        if certificate.get("tree", {}).get("path") == relative:
            matches.append((path, certificate))
    if len(matches) != 1:
        raise SpineError(
            f"Phase 8 requires exactly one Unit O certificate for {relative!r}; found {len(matches)}"
        )
    path, certificate = matches[0]
    result = evaluate_ratification_certificate(path, repo_root=repo)
    if not result.passed:
        raise SpineError(
            "Phase 8 Unit O ratification failed closed: " + ", ".join(result.failures)
        )
    return certificate


__all__ = [
    "AUDIT_LEDGER_DIR",
    "COMPLETION_LEDGER_DIR",
    "RATIFICATION_LEDGER_DIR",
    "RatificationResult",
    "canonical_json_bytes",
    "evaluate_ratification_certificate",
    "load_audit_entries",
    "require_ratified_unit_o",
]
