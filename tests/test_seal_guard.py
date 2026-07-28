"""The exploration runtime must not reach the locked confirmation store.

Spec §16.4.1: "Never touch `data/locked_confirmation/`. The exploration runtime must not
import or mmap it."

Spec §11 is explicit that this is **friction, not structure**: "a reader who believes the
code prevents selection will select more freely." The AST scan below stops an accidental
import; it stops nothing deliberate. The real protections are preregistration, immutable
study definitions, the ledger, access control, forward vintages, and human discipline.

Only `spine/build.py`, `spine/gates.py` and `spine/seal.py` may name the locked store,
and only to write and validate it — the Gate 2 oracle *is* the locked tier
(docs/DISCREPANCIES.md D6).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from mnq_lab import SpineError
from mnq_lab.constants import REPO_ROOT
from mnq_lab.spine.seal import (
    LOCKED_STORE_DIRNAME,
    SEAL_BOUNDARY_TRADE_DATE,
    Corpus,
    assert_exploration_safe,
    store_path,
)

PACKAGE_ROOT = REPO_ROOT / "mnq_lab"

PERMITTED = {
    Path("spine/build.py"),
    Path("spine/gates.py"),
    Path("spine/seal.py"),
}


def _string_literals(path: Path) -> list[str]:
    """Non-docstring string constants in a module.

    Docstrings are excluded: prose cannot open a file, and the responsibility rules are
    documented in module docstrings throughout the package. Excluding them keeps the
    scan pointed at things that could actually reach the store.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def _modules():
    return sorted(PACKAGE_ROOT.rglob("*.py"))


def test_only_permitted_modules_name_the_locked_store():
    offenders = []
    for path in _modules():
        relative = path.relative_to(PACKAGE_ROOT)
        if relative in PERMITTED:
            continue
        if any(LOCKED_STORE_DIRNAME in text for text in _string_literals(path)):
            offenders.append(str(relative))
    assert not offenders, (
        f"modules naming {LOCKED_STORE_DIRNAME!r} outside the permitted set: "
        f"{offenders}. Spec §16.4.1."
    )


def test_the_scan_covers_a_meaningful_number_of_modules():
    """Guards against a scan that passes because it inspected nothing."""
    assert len(_modules()) >= 10


def test_negative_case_the_scan_detects_an_offending_module(tmp_path):
    """Plant a violation and confirm the scanner finds it."""
    offender = tmp_path / "leaky.py"
    offender.write_text(
        'STORE = "data/locked_confirmation/bars_5m"\n', encoding="utf-8"
    )
    assert any(LOCKED_STORE_DIRNAME in text for text in _string_literals(offender))


def test_negative_case_the_scan_ignores_an_innocent_module(tmp_path):
    innocent = tmp_path / "clean.py"
    innocent.write_text('STORE = "data/exploration/bars_5m"\n', encoding="utf-8")
    assert not any(LOCKED_STORE_DIRNAME in text for text in _string_literals(innocent))


def test_guard_refuses_a_locked_path(tmp_path):
    locked = tmp_path / "data" / LOCKED_STORE_DIRNAME / "bars_5m"
    locked.mkdir(parents=True)
    with pytest.raises(SpineError, match="locked confirmation store"):
        assert_exploration_safe(locked)


def test_guard_allows_an_exploration_path(tmp_path):
    exploration = tmp_path / "data" / "exploration" / "bars_5m"
    exploration.mkdir(parents=True)
    assert assert_exploration_safe(exploration) == exploration.resolve()


def test_guard_catches_traversal_through_a_relative_path(tmp_path):
    locked = tmp_path / "data" / LOCKED_STORE_DIRNAME / "bars_5m"
    locked.mkdir(parents=True)
    sneaky = tmp_path / "data" / "exploration" / ".." / LOCKED_STORE_DIRNAME / "bars_5m"
    with pytest.raises(SpineError, match="locked confirmation store"):
        assert_exploration_safe(sneaky)


def test_tiers_are_physically_separate_directories():
    exploration = store_path("data", Corpus.EXPLORATION, "5m")
    locked = store_path("data", Corpus.LOCKED_CONFIRMATION, "5m")
    assert exploration.parent != locked.parent
    assert LOCKED_STORE_DIRNAME not in exploration.parts


def test_seal_boundary_splits_the_real_stores(exploration_5m, locked_5m):
    """No session may appear in both tiers, and the split must be at the boundary."""
    boundary = int(SEAL_BOUNDARY_TRADE_DATE.replace("-", ""))
    assert exploration_5m.manifest["trade_date_last"] == boundary
    assert locked_5m.manifest["trade_date_first"] > boundary

    import numpy as np

    overlap = np.intersect1d(
        np.asarray(exploration_5m["session_id"]), np.asarray(locked_5m["session_id"])
    )
    assert overlap.size == 0, f"{overlap.size} sessions appear in both tiers"


def test_exploration_tier_matches_the_spec_span(exploration_5m):
    """Spec §11: exploration is 2019-05-05 -> 2023-03-29."""
    assert exploration_5m.manifest["trade_date_last"] == 20230329
    assert exploration_5m.manifest["trade_date_first"] >= 20190505


def test_locked_tier_matches_the_spec_span(locked_5m):
    """Spec §11: locked confirmation begins 2023-03-30."""
    assert locked_5m.manifest["trade_date_first"] == 20230330
