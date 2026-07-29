"""Machine-verifiable Phase 3 threshold-freeze ledger and YAML agreement."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

from mnq_lab import SpineError
from mnq_lab.constants import (
    CONSTANTS_PATH,
    REPO_ROOT,
    Constants,
    load_completion_thresholds,
    load_constants,
)
from mnq_lab.ledger.freeze import (
    LEDGER_DIR,
    PHASE3_ENTRY_ID,
    THRESHOLD_KEYS,
    canonical_entry_bytes,
    load_ledger_entries,
    load_phase3_completion_freeze,
    validate_phase3_freeze_against_constants,
)

OLD_YAML_SHA256 = (
    "3f5c4bd5258eeb306d76d45aa4ad568a2483f007415e7d11df89ebbc8c4b182a"
)
ARTIFACT_SHA256 = (
    "725df33a00e53c6c356c4348df2a02fe9ed309d9d4e4118216894a70ef8a479d"
)
NEW_YAML_SHA256 = (
    "1c95aa595c30c48b853303291a7dbaabceaf5b7331bca565a30863e8dcf138d4"
)
ENTRY_RELATIVE_PATH = (
    "mnq_lab/ledger/entries/"
    "2026-07-28-phase3-s00-completion-thresholds.json"
)


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_entry(directory, name, entry):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_bytes(canonical_entry_bytes(entry))


def test_phase3_freeze_authorization_is_complete_and_canonical():
    entries = load_ledger_entries()
    assert len(entries) == 1
    entry = load_phase3_completion_freeze()

    assert entry["entry_id"] == PHASE3_ENTRY_ID
    assert entry["program_id"] == "mnq-atlas-001"
    assert entry["spec_version"] == 6
    assert entry["phase"] == 3
    assert entry["phase_date"] == "2026-07-28"
    assert entry["old_yaml_sha256"] == OLD_YAML_SHA256
    assert entry["keys_previously_absent"] == list(THRESHOLD_KEYS)
    assert entry["thresholds"] == [
        {"key": "min_completion_h15", "value": 0.99},
        {"key": "min_completion_h30", "value": 0.99},
        {"key": "min_completion_h60", "value": 0.98},
    ]
    assert entry["threshold_rule"] == (
        "min_completion = max(0.90, floor(s00_p05 * 100) / 100)"
    )
    assert entry["source_population"]["path_estimand"] == (
        "fully_labeled_1m_grid"
    )
    assert entry["source_population"]["tier"] == "exploration"
    assert entry["source_population"]["include_thin_cells"] is True
    assert entry["quantile"] == {
        "all_five_phase_cells_required": True,
        "convention": "discrete_inverse_cdf_equal_phase_weights",
        "phase_weights": "equal",
        "q_denominator": 20,
        "q_numerator": 1,
    }
    assert entry["artifact"]["sha256"] == ARTIFACT_SHA256
    assert entry["source_store"]["build_id"] == "0ad7843647f17258"
    assert entry["source_store"]["manifest_sha256"] == (
        "1cf6ec5ce7822ce1333984909b52d5c937e4ccc06e280030bcacda22620ffd73"
    )
    assert entry["deriving_code_commit"] == (
        "d9f2bc22bf0632531e57be2e5ae9dfb9c1e53124"
    )
    assert entry["audit"]["auditor"] == "Opus 5"
    assert entry["audit"]["verdict"] == "CLOSED"
    assert entry["no_affected_result_has_run"] is True
    assert "S01A" in entry["no_affected_result_has_run_statement"]


def test_ledger_commit_predates_the_yaml_freeze():
    ledger_commits = subprocess.check_output(
        [
            "git",
            "log",
            "--diff-filter=A",
            "--format=%H",
            "--",
            ENTRY_RELATIVE_PATH,
        ],
        cwd=REPO_ROOT,
        text=True,
    ).splitlines()
    assert len(ledger_commits) == 1
    ledger_commit = ledger_commits[0]

    yaml_at_authorization = subprocess.check_output(
        ["git", "show", f"{ledger_commit}:analysis_constants_v1.yaml"],
        cwd=REPO_ROOT,
    )
    assert hashlib.sha256(yaml_at_authorization).hexdigest() == OLD_YAML_SHA256
    for key in THRESHOLD_KEYS:
        assert f"\n  {key}:".encode() not in yaml_at_authorization

    yaml_commits = subprocess.check_output(
        [
            "git",
            "log",
            "-S",
            "min_completion_h15: 0.99",
            "--format=%H",
            "--",
            "analysis_constants_v1.yaml",
        ],
        cwd=REPO_ROOT,
        text=True,
    ).splitlines()
    assert len(yaml_commits) == 1
    yaml_commit = yaml_commits[0]
    assert yaml_commit != ledger_commit
    assert (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", ledger_commit, yaml_commit],
            cwd=REPO_ROOT,
            check=False,
        ).returncode
        == 0
    )


def test_yaml_contains_exactly_the_three_ledgered_values():
    assert _sha256(CONSTANTS_PATH) == NEW_YAML_SHA256
    entry = validate_phase3_freeze_against_constants()
    completion = load_constants().get("completion")
    actual_keys = [
        key for key in completion if key.startswith("min_completion_h")
    ]
    assert actual_keys == list(THRESHOLD_KEYS)
    assert load_completion_thresholds() == {
        int(item["key"].removeprefix("min_completion_h")): item["value"]
        for item in entry["thresholds"]
    }

    yaml_text = CONSTANTS_PATH.read_text(encoding="utf-8")
    yaml_scalars = dict(
        re.findall(
            r"^  (min_completion_h(?:15|30|60)): ([0-9]+\.[0-9]{2})$",
            yaml_text,
            flags=re.MULTILINE,
        )
    )
    ledger_scalars = {
        item["key"]: f"{item['value']:.2f}" for item in entry["thresholds"]
    }
    assert yaml_scalars == ledger_scalars


def test_ledger_artifact_provenance_matches_generated_bytes():
    entry = load_phase3_completion_freeze()
    artifact = REPO_ROOT / entry["artifact"]["path"]
    assert artifact.is_file()
    assert artifact.stat().st_size == entry["artifact"]["bytes"] == 7636
    assert _sha256(artifact) == entry["artifact"]["sha256"]


def test_threshold_loader_refuses_missing_extra_or_invalid_keys(tmp_path):
    frozen_text = CONSTANTS_PATH.read_text(encoding="utf-8")
    mutations = {
        "missing": frozen_text.replace("  min_completion_h30: 0.99\n", ""),
        "extra": frozen_text.replace(
            "  min_completion_h60: 0.98\n",
            "  min_completion_h60: 0.98\n  min_completion_h120: 0.97\n",
        ),
        "precision": frozen_text.replace(
            "  min_completion_h30: 0.99",
            "  min_completion_h30: 0.991",
        ),
        "range": frozen_text.replace(
            "  min_completion_h30: 0.99",
            "  min_completion_h30: 0.89",
        ),
    }
    for name, text in mutations.items():
        path = tmp_path / f"{name}.yaml"
        path.write_text(text, encoding="utf-8")
        with pytest.raises(SpineError):
            load_completion_thresholds(path)


def test_one_ledger_yaml_value_mismatch_fails_closed():
    altered_data = copy.deepcopy(load_constants().as_dict())
    altered_data["completion"]["min_completion_h30"] = 0.98
    altered = Constants(altered_data, Path("<ledger-mismatch-test>"))
    with pytest.raises(SpineError, match="threshold mismatch"):
        validate_phase3_freeze_against_constants(altered)


def test_duplicate_entry_ids_fail_closed(tmp_path):
    entry = load_phase3_completion_freeze()
    _write_entry(tmp_path, "one.json", entry)
    _write_entry(tmp_path, "two.json", entry)
    with pytest.raises(SpineError, match="duplicate ledger entry_id"):
        load_ledger_entries(tmp_path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "missing 'artifact'"),
        ("wrong_keys", "exact absent keys"),
        ("retroactive", "retroactive freeze"),
        ("wrong_threshold_count", "exactly three thresholds"),
    ],
)
def test_malformed_freeze_entries_fail_closed(tmp_path, mutation, message):
    entry = copy.deepcopy(load_phase3_completion_freeze())
    if mutation == "missing":
        del entry["artifact"]
    elif mutation == "wrong_keys":
        entry["keys_previously_absent"] = list(THRESHOLD_KEYS[:-1])
    elif mutation == "retroactive":
        entry["no_affected_result_has_run"] = False
    else:
        entry["thresholds"] = entry["thresholds"][:-1]
    _write_entry(tmp_path, "mutated.json", entry)

    with pytest.raises(SpineError, match=message):
        load_ledger_entries(tmp_path)


def test_noncanonical_entry_bytes_fail_closed(tmp_path):
    entry = load_phase3_completion_freeze()
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "pretty-but-unsorted.json").write_text(
        json.dumps(entry, indent=4) + "\n", encoding="utf-8"
    )
    with pytest.raises(SpineError, match="not canonical"):
        load_ledger_entries(tmp_path)


def test_ledger_directory_contains_only_immutable_json_entries():
    assert sorted(path.suffix for path in LEDGER_DIR.iterdir()) == [".json"]
