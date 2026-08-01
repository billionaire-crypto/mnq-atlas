"""Fail-closed validation for the separate Phase 7 calendar-input ledger."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from mnq_lab import SpineError


REPO_ROOT = Path(__file__).resolve().parents[3]
CALENDAR_LEDGER_DIR = Path(__file__).resolve().parent
CALENDAR_ENTRY_ID = "phase7-cme-equity-index-calendar-v1"
CALENDAR_ENTRY_PATH = (
    CALENDAR_LEDGER_DIR
    / "2026-08-01-phase7-cme-equity-index-calendar-v1.json"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def canonical_entry_bytes(entry: dict[str, Any]) -> bytes:
    return (
        json.dumps(entry, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    ).encode("utf-8")


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise SpineError(f"calendar ledger field {field!r} is not lowercase SHA-256")
    return value


def _require_artifact(record: Any, field: str) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise SpineError(f"calendar ledger field {field!r} must be an object")
    if set(record) != {"bytes", "path", "sha256"}:
        raise SpineError(f"calendar ledger field {field!r} has unexpected keys")
    if not isinstance(record["bytes"], int) or record["bytes"] <= 0:
        raise SpineError(f"calendar ledger field {field!r} has invalid byte count")
    if not isinstance(record["path"], str) or not record["path"]:
        raise SpineError(f"calendar ledger field {field!r} has invalid path")
    _require_sha256(record["sha256"], f"{field}.sha256")
    return record


def load_calendar_entry(path: Path = CALENDAR_ENTRY_PATH) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        entry = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpineError(f"cannot read strict calendar ledger entry {path}: {exc}") from exc
    if not isinstance(entry, dict):
        raise SpineError("calendar ledger entry must be an object")
    if raw != canonical_entry_bytes(entry):
        raise SpineError("calendar ledger entry is not canonical sorted UTF-8 JSON")
    if entry.get("entry_id") != CALENDAR_ENTRY_ID:
        raise SpineError("calendar ledger entry_id differs")
    if entry.get("ledger_format") != "immutable_calendar_entry_v1":
        raise SpineError("calendar ledger format differs")
    if entry.get("program_id") != "mnq-atlas-001" or entry.get("phase") != 7:
        raise SpineError("calendar ledger program or phase differs")
    if entry.get("scope") != "calendar_reference_input_only":
        raise SpineError("calendar ledger scope differs")
    if entry.get("base_commit") != "4100abadad1d8212b8c98ad7382e1019a1afbe96":
        raise SpineError("calendar ledger base commit differs")
    if entry.get("branch") != "phase-7-calendar-input":
        raise SpineError("calendar ledger branch differs")
    if entry.get("no_affected_result_has_run") is not True:
        raise SpineError("calendar ledger cannot authorize retroactively")
    if entry.get("phase7_production_authorized") is not False:
        raise SpineError("calendar ledger must not authorize Phase 7 production")
    if entry.get("local_only_no_push") is not True:
        raise SpineError("calendar ledger must remain local-only")
    if entry.get("phase3_ledger_unchanged") is not True:
        raise SpineError("calendar ledger must preserve the Phase 3 ledger")
    for field in (
        "acceptance_record",
        "canonical_table",
        "extractor",
        "manifest",
    ):
        _require_artifact(entry.get(field), field)
    discrepancies = entry.get("discrepancies")
    _require_artifact(discrepancies, "discrepancies")
    if discrepancies["path"] != "docs/DISCREPANCIES.md":
        raise SpineError("calendar ledger D19 path differs")
    source = entry.get("source")
    if not isinstance(source, dict):
        raise SpineError("calendar ledger source must be an object")
    if source.get("release") != "5.4.0":
        raise SpineError("calendar ledger source release differs")
    if source.get("commit") != "275890784073a3a3a347e4f05f4dc986456e6a75":
        raise SpineError("calendar ledger source commit differs")
    _require_sha256(
        entry.get("source_provenance", {}).get("tree_sha256"),
        "source_provenance.tree_sha256",
    )
    return entry


def validate_calendar_entry_artifacts(
    entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active = load_calendar_entry() if entry is None else entry
    for field in (
        "acceptance_record",
        "canonical_table",
        "discrepancies",
        "extractor",
        "manifest",
    ):
        record = _require_artifact(active[field], field)
        path = REPO_ROOT / record["path"]
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise SpineError(f"calendar ledger artifact {field!r} is absent: {exc}") from exc
        if len(payload) != record["bytes"]:
            raise SpineError(f"calendar ledger artifact {field!r} byte count differs")
        if hashlib.sha256(payload).hexdigest() != record["sha256"]:
            raise SpineError(f"calendar ledger artifact {field!r} SHA-256 differs")
    return active


__all__ = [
    "CALENDAR_ENTRY_ID",
    "CALENDAR_ENTRY_PATH",
    "CALENDAR_LEDGER_DIR",
    "canonical_entry_bytes",
    "load_calendar_entry",
    "validate_calendar_entry_artifacts",
]
