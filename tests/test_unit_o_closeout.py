"""Raw-byte and commit-scope pins for the Unit O closeout handoff."""

from __future__ import annotations

import hashlib
import subprocess

from mnq_lab.constants import REPO_ROOT

CLOSEOUT = REPO_ROOT / "docs" / "UNIT_O.md"
CLOSEOUT_BYTES = 9_172
CLOSEOUT_SHA256 = "93cc9aeca323d3144c31089350d3fee4b1fb598ab11345337329a7df3c6c634e"

PROTECTED = {
    "REV6_FROZEN_SPEC.md": (48_177, "70dae16c8b12fe26d38a7bfdabf0202066fe7149f790d0d2942279d9c3b8ff50"),
    "analysis_constants_v1.yaml": (3_311, "1c95aa595c30c48b853303291a7dbaabceaf5b7331bca565a30863e8dcf138d4"),
    "docs/OUTCOME_LAYER_PREREGISTRATION.md": (17_614, "4b5bc97fdfd4b0219c69e6a8adf76f18072091a9389700191d3ddcd10f8207c8"),
    "docs/PHASE8_PREREGISTRATION.md": (31_862, "d07174ed0acc9e60ab6b255f4b33fc08141969c64e04f66e1e08c0aca98b4680"),
    "docs/PHASE7.md": (15_856, "d987eddb15fd3f3581c60dbc590704f84d783f8ffe140fcd57259392c0f513a7"),
    "docs/DISCREPANCIES.md": (54_495, "e7d6a2704d7159e5f5f522705f4d989a0120756594c8026c9e559a144042655e"),
    "mnq_lab/outcomes/artifacts.py": (6_242, "7ca7e36a94eb59c38f0e8530ece891dc51c32cf1d736dc3901f468b04eceab76"),
    "mnq_lab/outcomes/excursions.py": (27_972, "c521c17e272a391e39902e4016e913e449f7e567755b18455496cb7f9b7db31e"),
    "tests/test_estimand_definition.py": (19_561, "11d086e6dd1522bb635b52a9e283fc8432b4c07bccca7729454995b8ba8c8b70"),
    "tests/test_outcome_artifacts.py": (7_550, "cd175a9df82d4cd2499a2ffd7b6d7db8105e637b1e68f4232ad0726d1a980930"),
    "tests/test_outcome_excursions.py": (10_965, "f8080b27671012e4b89ece8de87c3921238e751ab23fa3ab12028a3c0e0a2858"),
    "tests/test_outcome_isolation.py": (5_239, "ba38d2bfb978a20357048f58a5ce4f17088b918322ac3c67bf6921d5676e811f"),
    "tests/test_outcome_locality.py": (7_622, "f34cb9170103af5ea58bfd067994763c1a66e6e578c4b2c218c7d73389f081f0"),
    "tests/test_phase7_calendar_input.py": (25_061, "d9b8dee45bf5dd533074623e9f0fae435123b1fe9a03c714d16aab71245d52f5"),
    "tests/test_window_boundaries.py": (9_963, "b37d377674c09fcf5716063cafd9dbb1d64b3da0f5047f50d741a5ccffabf266"),
    "tests/unit_o_fixtures.py": (5_542, "04a6383c9fda1eebcd7811edfde5ed8f3153d0c9f9bb1720e11908a670953bd0"),
}


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def test_unit_o_closeout_raw_bytes_are_pinned():
    payload = CLOSEOUT.read_bytes()
    assert len(payload) == CLOSEOUT_BYTES
    assert _digest(payload) == CLOSEOUT_SHA256


def test_every_unit_o_closeout_protected_hash_matches_raw_bytes():
    for relative, (expected_bytes, expected_hash) in PROTECTED.items():
        payload = (REPO_ROOT / relative).read_bytes()
        assert len(payload) == expected_bytes, relative
        assert _digest(payload) == expected_hash, relative


def test_d21_transition_preserves_the_exact_historical_prefix():
    payload = (REPO_ROOT / "docs" / "DISCREPANCIES.md").read_bytes()
    historical = payload[:51_539]
    assert len(payload) == 54_495
    assert _digest(historical) == (
        "7ec200bb1de83769b8ce07551fec4e0b81f5e90e20a4792c22ae47f285bed615"
    )
    assert _digest(payload) == PROTECTED["docs/DISCREPANCIES.md"][1]


def test_unit_o_commit_chain_is_ordered_and_scope_is_local():
    commits = (
        "e9e8a10b03a3b102cffb9692eef14cfeba563232",
        "fe1476c7955dd64f2b292f60f776b1e03691b22e",
        "67ce72e",
        "212ca4dc231b769fd3eea7130d41d66681798866",
    )
    for older, newer in zip(commits[:-1], commits[1:], strict=True):
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", older, newer],
            cwd=REPO_ROOT,
            check=False,
        )
        assert result.returncode == 0, f"required Unit O commit order failed: {older} -> {newer}"
