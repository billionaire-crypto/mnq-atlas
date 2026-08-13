"""Static and synthetic-only protection checks for the evidence entry point."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from mnq_lab import SpineError
import mnq_lab.phase10.calibration_runner as runner_module


def _supplies_authorization_token(
    source: str,
    entrypoint_name: str,
    token: str,
) -> bool:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = None
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        if name != entrypoint_name:
            continue
        supplied = [*node.args]
        supplied.extend(
            keyword.value
            for keyword in node.keywords
            if keyword.arg == "authorization"
        )
        if any(isinstance(value, ast.Constant) and value.value == token for value in supplied):
            return True
    return False


def _assert_evidence_protection(entrypoint, test_sources, token):
    signature = inspect.signature(entrypoint)
    authorization = signature.parameters["authorization"]
    assert authorization.default is inspect.Parameter.empty
    assert not entrypoint.__name__.startswith("test_")
    assert all(
        not _supplies_authorization_token(source, entrypoint.__name__, token)
        for source in test_sources
    )


def _committed_test_sources() -> tuple[str, ...]:
    root = Path(__file__).resolve().parents[1] / "tests"
    return tuple(
        path.read_text(encoding="utf-8")
        for path in sorted(root.glob("test_*.py"))
    )


def test_evidence_entrypoint_requires_an_unforgeable_call_shape():
    _assert_evidence_protection(
        runner_module.run_calibration_evidence,
        _committed_test_sources(),
        runner_module.CALIBRATION_EXECUTION_AUTHORIZATION,
    )
    with pytest.raises(TypeError):
        runner_module.run_calibration_evidence()
    with pytest.raises(SpineError, match="authorization differs"):
        runner_module.run_calibration_evidence("wrong", request=object())


def test_defaulted_or_token_supplying_mutants_fail_the_same_witness():
    def defaulted(authorization="forbidden-default", *, request=None):
        return authorization, request

    for entrypoint, sources, token in (
        (defaulted, ("pass\n",), runner_module.CALIBRATION_EXECUTION_AUTHORIZATION),
        (
            runner_module.run_calibration_evidence,
            (
                "run_calibration_evidence("
                f"{runner_module.CALIBRATION_EXECUTION_AUTHORIZATION!r}, request=None)\n",
            ),
            runner_module.CALIBRATION_EXECUTION_AUTHORIZATION,
        ),
    ):
        with pytest.raises(AssertionError):
            _assert_evidence_protection(entrypoint, sources, token)
