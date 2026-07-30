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
import re

import pytest

from mnq_lab.constants import REPO_ROOT

PACKAGE_ROOT = REPO_ROOT / "mnq_lab"
CORE_ROOT = PACKAGE_ROOT / "core"

# §16.4.4: "No selection verbs anywhere in core/".
SELECTION_VERBS = {"sort_values", "nlargest", "nsmallest", "idxmax", "idxmin",
                   "argmax", "argmin", "rank"}

# §11 forbidden names. Listed knowing full well that `score` defeats the whole list.
FORBIDDEN_NAMES = {"pnl", "profit", "expectancy", "sharpe", "equity_curve", "drawdown"}
FORBIDDEN_CORE_IMPORT_ROOTS = {
    "constants",
    "spine",
    "conditioners",
    "outcomes",
    "studies",
    "report",
    "nulls",
    "ledger",
}
FORBIDDEN_CORE_TOP_LEVEL_IMPORTS = {"lora_statistics", "yaml"}
LOCKED_TIER_PATTERN = re.compile(r"\blocked(?:[_-]confirmation)?\b", re.IGNORECASE)
CORE_STORE_PATH_PATTERN = re.compile(
    r"(?:\bdata[\\/]|bars_\d+m\b)",
    re.IGNORECASE,
)


def _modules(root):
    return sorted(root.rglob("*.py"))


def _attribute_calls(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            names.append((node.func.attr, node.lineno))
    return names


def _forbidden_core_imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] in FORBIDDEN_CORE_TOP_LEVEL_IMPORTS:
                    offenders.append(f"{path.name} imports {alias.name}")
                if (
                    len(parts) > 1
                    and parts[0] == "mnq_lab"
                    and parts[1] in FORBIDDEN_CORE_IMPORT_ROOTS
                ):
                    offenders.append(f"{path.name} imports {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            parts = module.split(".")
            if parts[0] in FORBIDDEN_CORE_TOP_LEVEL_IMPORTS:
                offenders.append(f"{path.name} imports {module}")
            elif (
                len(parts) > 1
                and parts[0] == "mnq_lab"
                and parts[1] in FORBIDDEN_CORE_IMPORT_ROOTS
            ):
                offenders.append(f"{path.name} imports {module}")
            elif module == "mnq_lab":
                for alias in node.names:
                    if alias.name in FORBIDDEN_CORE_IMPORT_ROOTS:
                        offenders.append(
                            f"{path.name} imports mnq_lab.{alias.name}"
                        )
    return offenders


def _locked_tier_references(path):
    return [
        (line_number, line.strip())
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        )
        if LOCKED_TIER_PATTERN.search(line)
    ]


def _core_store_path_references(path):
    return [
        (line_number, line.strip())
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        )
        if CORE_STORE_PATH_PATTERN.search(line)
    ]


def test_core_contains_no_selection_verbs():
    offenders = []
    for path in _modules(CORE_ROOT):
        for name, line in _attribute_calls(path):
            if name in SELECTION_VERBS:
                offenders.append(f"{path.relative_to(PACKAGE_ROOT)}:{line} {name}")
    assert not offenders, f"selection verbs in core/: {offenders} (spec §16.4.4)"


def test_core_imports_nothing_market_aware():
    """§16.3: "core/ knows nothing about markets"."""
    offenders = []
    for path in _modules(CORE_ROOT):
        offenders.extend(_forbidden_core_imports(path))
    assert not offenders, offenders


@pytest.mark.parametrize(
    "source",
    [
        "from mnq_lab.ledger import freeze\n",
        "from mnq_lab import ledger\n",
        "from mnq_lab.constants import load_constants\n",
        "from lora_statistics import stationary_session_resample\n",
        "import yaml\n",
        "from yaml import safe_load\n",
    ],
)
def test_core_import_guard_detects_a_planted_forbidden_import(tmp_path, source):
    leaky = tmp_path / "leaky.py"
    leaky.write_text(source, encoding="utf-8")

    assert _forbidden_core_imports(leaky), (
        "the core import guard did not detect its planted import mutation"
    )


def test_core_does_not_name_the_locked_tier():
    offenders = []
    for path in _modules(CORE_ROOT):
        for line_number, line in _locked_tier_references(path):
            offenders.append(
                f"{path.relative_to(PACKAGE_ROOT)}:{line_number} {line}"
            )
    assert not offenders, offenders


@pytest.mark.parametrize(
    "source",
    [
        "_TIER = 'data/locked_confirmation'\n",
        "import os\nos.path.isdir('locked')\n",
    ],
)
def test_locked_tier_guard_detects_a_planted_reference(tmp_path, source):
    leaky = tmp_path / "leaky.py"
    leaky.write_text(source, encoding="utf-8")

    assert _locked_tier_references(leaky), (
        "the locked-tier guard did not detect its planted source mutation"
    )


def test_core_does_not_name_market_store_paths():
    offenders = []
    for path in _modules(CORE_ROOT):
        for line_number, line in _core_store_path_references(path):
            offenders.append(
                f"{path.relative_to(PACKAGE_ROOT)}:{line_number} {line}"
            )
    assert not offenders, offenders


@pytest.mark.parametrize(
    "source",
    [
        "_STORE = 'data/exploration/session_flags'\n",
        "_STORE = 'data/exploration/bars_5m'\n",
        r"_STORE = 'C:\repo\data\exploration\bars_5m'" "\n",
        "import numpy as np\nnp.load('bars_5m')\n",
    ],
)
def test_core_store_path_guard_detects_a_planted_reference(tmp_path, source):
    leaky = tmp_path / "leaky.py"
    leaky.write_text(source, encoding="utf-8")

    assert _core_store_path_references(leaky), (
        "the core store-path guard did not detect its planted mutation"
    )


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
