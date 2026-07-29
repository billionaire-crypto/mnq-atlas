"""Validation for the minimal immutable-entry freeze ledger.

An append adds a new canonical JSON file. Existing entry files are never edited;
Git history supplies the durable ordering proof. This is intentionally smaller
than the full governance layer deferred to Phase 11.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from mnq_lab import SpineError
from mnq_lab.constants import Constants, load_constants

LEDGER_DIR = Path(__file__).resolve().parent / "entries"
PHASE3_ENTRY_ID = "phase3-s00-completion-thresholds-v1"
PHASE3_ENTRY_TYPE = "completion_threshold_freeze_authorization"
THRESHOLD_KEYS = (
    "min_completion_h15",
    "min_completion_h30",
    "min_completion_h60",
)

__all__ = [
    "LEDGER_DIR",
    "PHASE3_ENTRY_ID",
    "PHASE3_ENTRY_TYPE",
    "THRESHOLD_KEYS",
    "canonical_entry_bytes",
    "load_ledger_entries",
    "load_phase3_completion_freeze",
    "validate_phase3_freeze_against_constants",
]


def canonical_entry_bytes(entry: dict[str, Any]) -> bytes:
    try:
        encoded = json.dumps(
            entry,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise SpineError(f"ledger entry is not strict JSON: {exc}") from exc
    return (encoded + "\n").encode("utf-8")


def _reject_json_constant(token: str) -> None:
    raise SpineError(f"ledger entry contains non-standard JSON constant {token}")


def _load_entry(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        parsed = json.loads(
            raw.decode("utf-8"), parse_constant=_reject_json_constant
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpineError(f"cannot read ledger entry {path}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SpineError(f"ledger entry {path} must be a JSON object")
    if raw != canonical_entry_bytes(parsed):
        raise SpineError(
            f"ledger entry {path} is not canonical sorted UTF-8 JSON"
        )
    return parsed


def _require(entry: dict[str, Any], key: str, entry_id: str) -> Any:
    if key not in entry:
        raise SpineError(f"ledger entry {entry_id!r} is missing {key!r}")
    return entry[key]


def _validate_entry(entry: dict[str, Any], path: Path) -> None:
    entry_id = _require(entry, "entry_id", path.name)
    if not isinstance(entry_id, str) or not entry_id:
        raise SpineError(f"ledger entry {path} has invalid entry_id {entry_id!r}")
    if _require(entry, "ledger_format", entry_id) != "immutable_entry_file_v1":
        raise SpineError(f"ledger entry {entry_id!r} has unknown ledger_format")

    required = (
        "affected_future_results",
        "artifact",
        "audit",
        "deriving_code_commit",
        "entry_type",
        "keys_previously_absent",
        "no_affected_result_has_run",
        "no_affected_result_has_run_statement",
        "old_yaml_sha256",
        "phase",
        "phase_date",
        "program_id",
        "quantile",
        "source_population",
        "source_store",
        "spec_version",
        "threshold_rule",
        "thresholds",
    )
    for key in required:
        _require(entry, key, entry_id)

    if entry["keys_previously_absent"] != list(THRESHOLD_KEYS):
        raise SpineError(
            f"ledger entry {entry_id!r} does not record the exact absent keys"
        )
    thresholds = entry["thresholds"]
    if not isinstance(thresholds, list) or len(thresholds) != len(THRESHOLD_KEYS):
        raise SpineError(
            f"ledger entry {entry_id!r} must contain exactly three thresholds"
        )
    ledger_keys = []
    for item in thresholds:
        if not isinstance(item, dict) or set(item) != {"key", "value"}:
            raise SpineError(
                f"ledger entry {entry_id!r} has malformed threshold {item!r}"
            )
        ledger_keys.append(item["key"])
        value = item["value"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SpineError(
                f"ledger threshold {item['key']!r} must be numeric"
            )
        if not 0.0 <= float(value) <= 1.0:
            raise SpineError(
                f"ledger threshold {item['key']!r} is outside [0,1]"
            )
    if ledger_keys != list(THRESHOLD_KEYS):
        raise SpineError(
            f"ledger entry {entry_id!r} threshold keys/order differ from "
            f"{THRESHOLD_KEYS}"
        )
    if entry["no_affected_result_has_run"] is not True:
        raise SpineError(
            f"ledger entry {entry_id!r} cannot authorize a retroactive freeze"
        )


def load_ledger_entries(directory: Path = LEDGER_DIR) -> list[dict[str, Any]]:
    if not directory.is_dir():
        raise SpineError(f"freeze ledger directory is absent: {directory}")
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise SpineError(f"freeze ledger contains no entries: {directory}")
    entries = []
    seen_ids: set[str] = set()
    for path in paths:
        entry = _load_entry(path)
        _validate_entry(entry, path)
        entry_id = entry["entry_id"]
        if entry_id in seen_ids:
            raise SpineError(f"duplicate ledger entry_id {entry_id!r}")
        seen_ids.add(entry_id)
        entries.append(entry)
    return entries


def load_phase3_completion_freeze(
    directory: Path = LEDGER_DIR,
) -> dict[str, Any]:
    matches = [
        entry
        for entry in load_ledger_entries(directory)
        if entry["entry_id"] == PHASE3_ENTRY_ID
        and entry["entry_type"] == PHASE3_ENTRY_TYPE
    ]
    if len(matches) != 1:
        raise SpineError(
            f"expected exactly one {PHASE3_ENTRY_ID!r} ledger entry, "
            f"found {len(matches)}"
        )
    return matches[0]


def validate_phase3_freeze_against_constants(
    constants: Constants | None = None,
    directory: Path = LEDGER_DIR,
) -> dict[str, Any]:
    """Require exact agreement between the audited ledger and frozen YAML."""
    frozen = constants if constants is not None else load_constants()
    entry = load_phase3_completion_freeze(directory)

    if frozen.get("program_id") != entry["program_id"]:
        raise SpineError("ledger/YAML program_id mismatch")
    if frozen.get("spec_version") != entry["spec_version"]:
        raise SpineError("ledger/YAML spec_version mismatch")
    if frozen.get("completion", "rule") != entry["threshold_rule"]:
        raise SpineError("ledger/YAML completion rule mismatch")
    if frozen.get("estimands", "path") != entry["source_population"][
        "path_estimand"
    ]:
        raise SpineError("ledger/YAML path estimand mismatch")

    population_pairs = (
        ("rth_only", "rth_only"),
        ("include_holidays_flagged", "include_holidays_and_short_sessions_flagged"),
        ("include_thin_cells", "include_thin_cells"),
    )
    for yaml_key, ledger_key in population_pairs:
        if frozen.get(
            "completion", "source_population", yaml_key
        ) != entry["source_population"][ledger_key]:
            raise SpineError(
                f"ledger/YAML source population mismatch for {yaml_key}"
            )
    if frozen.get("completion", "source_population", "years") != [
        entry["source_population"]["declared_start_inclusive"],
        entry["source_population"]["declared_end_inclusive"],
    ]:
        raise SpineError("ledger/YAML source population date mismatch")
    if frozen.get("horizons_minutes") != entry["source_population"][
        "horizons_minutes"
    ]:
        raise SpineError("ledger/YAML horizon mismatch")
    if list(frozen.get("session_phases")) != entry["source_population"]["phases"]:
        raise SpineError("ledger/YAML phase mismatch")

    completion = frozen.get("completion")
    actual_keys = [
        key
        for key in completion
        if isinstance(key, str) and key.startswith("min_completion_h")
    ]
    ledger_keys = [item["key"] for item in entry["thresholds"]]
    if actual_keys != ledger_keys:
        raise SpineError(
            f"ledger/YAML threshold keys mismatch: {ledger_keys} vs {actual_keys}"
        )
    for item in entry["thresholds"]:
        key = item["key"]
        yaml_value = frozen.get("completion", key)
        if isinstance(yaml_value, bool) or not isinstance(
            yaml_value, (int, float)
        ):
            raise SpineError(f"YAML threshold {key!r} is not numeric")
        if Decimal(str(yaml_value)) != Decimal(str(item["value"])):
            raise SpineError(
                f"ledger/YAML threshold mismatch for {key}: "
                f"{item['value']} vs {yaml_value}"
            )
    return entry
