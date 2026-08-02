"""Structural scope guard for real Phase 7 conditioner modules.

This guard matches operand identifiers, not operand contents. An allowlisted
identifier rebound to a measured series is not detectable by static analysis.
That residual is covered instead by the section 13 canonical-ordering
assertions and the section 14 prefix-invariance tests, which fail if any
artifact row order depends on a measured value.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest


_CONDITIONERS_ROOT = Path(__file__).resolve().parents[1] / "mnq_lab" / "conditioners"
_PHASE6_REGISTRY_FILES = frozenset({
    _CONDITIONERS_ROOT / "registry.py",
    _CONDITIONERS_ROOT / "__init__.py",
})
_FORBIDDEN_IMPORT_ROOTS = frozenset({
    "ledger",
    "nulls",
    "outcomes",
    "report",
    "studies",
})
_FORBIDDEN_SOURCE_PATTERN = re.compile(
    r"(?:locked(?:[_-]confirmation)?|data[\\/]|bars_\d+m)", re.IGNORECASE
)
_UNCONDITIONALLY_FORBIDDEN_CALLS = frozenset({
    "argmax",
    "idxmax",
    "nlargest",
    "rank",
    "sort_values",
})
# Literal and deliberately narrow. Every name denotes an immutable identity
# collection, never a scale, profile, vol_rel, threshold, category, or result.
_IDENTITY_ORDER_OPERANDS = (
    "arm_ids",
    "buckets",
    "completed_sessions",
    "current_sessions",
    "dates",
    "dependency_keys",
    "keys",
    "phase_dependency_keys",
    "phases",
    "primary_keys",
    "session_ids",
    "timestamps",
    "year_phase_groups",
)


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _operand_identifier(node: ast.AST | None) -> str | None:
    """Return the structural collection name used by an ordering expression."""
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in {
            "list",
            "set",
            "tuple",
        } and node.args:
            return _operand_identifier(node.args[0])
        return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _operand_identifier(node.left)
        right = _operand_identifier(node.right)
        return left if left == right else None
    return None


def _phase7_scope_violations_from_source(source: str, filename: str) -> list[str]:
    tree = ast.parse(source, filename=filename)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        else:
            modules = []
        for module in modules:
            parts = module.split(".")
            if (
                len(parts) > 1
                and parts[0] == "mnq_lab"
                and parts[1] in _FORBIDDEN_IMPORT_ROOTS
            ):
                violations.append(f"forbidden import {module}")

        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name in _UNCONDITIONALLY_FORBIDDEN_CALLS:
            violations.append(f"forbidden measured-ordering call {name}")
        elif name == "sorted":
            operand = _operand_identifier(node.args[0] if node.args else None)
            if operand not in _IDENTITY_ORDER_OPERANDS:
                violations.append(
                    f"sorted operand {operand!r} is not an immutable identity"
                )
        elif name == "sort":
            operand = _operand_identifier(
                node.func.value if isinstance(node.func, ast.Attribute) else None
            )
            if operand not in _IDENTITY_ORDER_OPERANDS:
                violations.append(
                    f"sort operand {operand!r} is not an immutable identity"
                )

    if _FORBIDDEN_SOURCE_PATTERN.search(source):
        violations.append("forbidden data-tier or store-path reference")
    return violations


def _phase7_scope_violations(path: Path) -> list[str]:
    return _phase7_scope_violations_from_source(
        path.read_text(encoding="utf-8"), str(path)
    )


def test_phase7_conditioner_modules_obey_market_aware_scope_and_identity_ordering():
    paths = tuple(
        path
        for path in _CONDITIONERS_ROOT.rglob("*.py")
        if path not in _PHASE6_REGISTRY_FILES
    )
    assert paths
    violations = {
        str(path.relative_to(_CONDITIONERS_ROOT)): _phase7_scope_violations(path)
        for path in paths
        if _phase7_scope_violations(path)
    }
    assert not violations


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("result = sorted(scale_values)\n", "not an immutable identity"),
        ("result = vol_rel.sort_values()\n", "forbidden measured-ordering"),
        (
            "def _ordered(measured_series):\n"
            "    return sorted(measured_series)\n"
            "result = _ordered(vol_rel)\n",
            "not an immutable identity",
        ),
    ],
)
def test_phase7_scope_guard_kills_measured_ordering_mutations(source, expected):
    violations = _phase7_scope_violations_from_source(source, "planted_phase7.py")
    assert any(expected in violation for violation in violations)


@pytest.mark.parametrize(
    "source",
    [
        "from mnq_lab.studies import study\n",
        "from mnq_lab.nulls import engine\n",
        "path = 'data/exploration/bars_5m'\n",
    ],
)
def test_phase7_scope_guard_kills_forbidden_layer_and_store_mutations(source):
    assert _phase7_scope_violations_from_source(source, "planted_phase7.py")
