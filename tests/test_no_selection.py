"""Accidental-selection friction and the responsibility boundaries (§11, §16.3, §16.4).

Spec §11 is emphatic that these are **friction, not structure**: "A regex banning
`pnl|profit|expectancy|sharpe` stops nothing — write `score`." The value of these checks
is that they catch a slip, not that they prevent a decision. The actual protections are
preregistration, immutable study definitions, complete output, the ledger, access
control, forward vintages, and human discipline.

They are asserted anyway, because a slip is the likely failure and it is cheap to catch.
"""

from __future__ import annotations

import ast

import pytest

from mnq_lab.constants import REPO_ROOT

PACKAGE_ROOT = REPO_ROOT / "mnq_lab"
CORE_ROOT = PACKAGE_ROOT / "core"

# §16.4.4: "No selection verbs anywhere in core/".
SELECTION_VERBS = {"sort_values", "nlargest", "nsmallest", "idxmax", "idxmin",
                   "argmax", "argmin", "rank"}

# §11 forbidden names. Listed knowing full well that `score` defeats the whole list.
FORBIDDEN_NAMES = {"pnl", "profit", "expectancy", "sharpe", "equity_curve", "drawdown"}


def _modules(root):
    return sorted(root.rglob("*.py"))


def _attribute_calls(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            names.append((node.func.attr, node.lineno))
    return names


def test_core_contains_no_selection_verbs():
    offenders = []
    for path in _modules(CORE_ROOT):
        for name, line in _attribute_calls(path):
            if name in SELECTION_VERBS:
                offenders.append(f"{path.relative_to(PACKAGE_ROOT)}:{line} {name}")
    assert not offenders, f"selection verbs in core/: {offenders} (spec §16.4.4)"


def test_core_imports_nothing_market_aware():
    """§16.3: "core/ knows nothing about markets"."""
    forbidden_roots = {"spine", "conditioners", "outcomes", "studies", "report", "nulls"}
    offenders = []
    for path in _modules(CORE_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                module = node.names[0].name
            if not module or not module.startswith("mnq_lab"):
                continue
            parts = module.split(".")
            if len(parts) > 1 and parts[1] in forbidden_roots:
                offenders.append(f"{path.relative_to(PACKAGE_ROOT)} imports {module}")
    assert not offenders, offenders


def test_sorting_outside_core_is_only_ever_chronological():
    """Canonical row order is time. Never a measured value (§11)."""
    tree_sources = {}
    for path in _modules(PACKAGE_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "sort_values"
            ):
                keys = [
                    arg.value
                    for arg in node.args
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                ]
                tree_sources.setdefault(str(path.relative_to(PACKAGE_ROOT)), []).extend(
                    keys
                )
    all_keys = {key for keys in tree_sources.values() for key in keys}
    assert all_keys <= {"timestamp", "ts_event_ns"}, (
        f"sort keys outside the time columns: {sorted(all_keys - {'timestamp', 'ts_event_ns'})}"
    )
    assert all_keys, "no sort_values found at all — this check inspected nothing"


@pytest.mark.parametrize("name", sorted(FORBIDDEN_NAMES))
def test_no_forbidden_identifier_is_defined(name):
    offenders = []
    for path in _modules(PACKAGE_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if name in node.name.lower():
                    offenders.append(f"{path.name}:{node.lineno} {node.name}")
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                if name in node.id.lower():
                    offenders.append(f"{path.name}:{node.lineno} {node.id}")
    assert not offenders, f"forbidden name {name!r}: {offenders}"


def test_negative_case_the_scanners_can_detect_a_violation(tmp_path):
    """Plant each violation and confirm the corresponding scanner sees it."""
    leaky = tmp_path / "leaky.py"
    leaky.write_text(
        "import pandas as pd\n"
        "def rank_cells(frame):\n"
        "    return frame.sort_values('sharpe').nlargest(3, 'pnl')\n",
        encoding="utf-8",
    )
    calls = {name for name, _ in _attribute_calls(leaky)}
    assert calls & SELECTION_VERBS == {"sort_values", "nlargest"}

    tree = ast.parse(leaky.read_text(encoding="utf-8"))
    keys = [
        arg.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "sort_values"
        for arg in node.args
        if isinstance(arg, ast.Constant)
    ]
    assert keys == ["sharpe"] and not set(keys) <= {"timestamp", "ts_event_ns"}


def test_no_currency_or_pnl_column_in_the_real_store(exploration_5m):
    """The store emits ticks and counts. Nothing denominated in money exists."""
    for name in exploration_5m.column_names:
        lowered = name.lower()
        assert not any(bad in lowered for bad in FORBIDDEN_NAMES), name
        assert "usd" not in lowered and "dollar" not in lowered, name
    assert "open_ticks" in exploration_5m.column_names, (
        "prices must be stored as ticks, not currency (spec §4)"
    )
