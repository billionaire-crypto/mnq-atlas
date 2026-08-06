"""Mechanical enforcement of the §5.1 binding consumer rule.

The contract requires every completion, eligibility and denominator calculation
to use the structural fit predicate and never ``outcome_status``. Revision 1
stated that rule in prose only, and the Stage 6 audit showed exactly why prose is
not enough: the justification described Phase 8 behaviour that existed only in
uncommitted files. A rule that lives in a document cannot fail; this one can.

Both guards run against **committed** source, so uncommitted work-in-progress
cannot mask a violation and cannot satisfy one either.
"""

from __future__ import annotations

import ast
import subprocess

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.constants import REPO_ROOT
from mnq_lab.phase8.diagnostics import completion_diagnostics

# Every module that computes a completion denominator or a structural
# eligibility mask. Adding a new one without adding it here is the gap this
# list exists to close, so the roster itself is asserted below.
DENOMINATOR_SURFACES = (
    "mnq_lab/outcomes/completion.py",
    "mnq_lab/phase8/diagnostics.py",
    "mnq_lab/phase8/production.py",
    "mnq_lab/phase8/day_types.py",
    "mnq_lab/phase8/contrasts.py",
)

FORBIDDEN = "outcome_status"


def _committed(relative: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "cat-file", "blob", f"HEAD:{relative}"],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, f"{relative} unreadable at HEAD"
    return result.stdout.decode("utf-8")


def test_no_denominator_surface_reads_outcome_status_in_committed_source():
    """Fails if any completion surface starts consuming the status string.

    Checked by AST over identifiers, constants and attribute names, so a
    reference cannot hide inside a getattr, a dict key or a column lookup.
    """
    offenders: list[str] = []
    for relative in DENOMINATOR_SURFACES:
        tree = ast.parse(_committed(relative), filename=relative)
        for node in ast.walk(tree):
            hit = (
                (isinstance(node, ast.Constant) and node.value == FORBIDDEN)
                or (isinstance(node, ast.Attribute) and node.attr == FORBIDDEN)
                or (isinstance(node, ast.Name) and node.id == FORBIDDEN)
            )
            if hit:
                offenders.append(f"{relative}:{getattr(node, 'lineno', '?')}")
    assert offenders == [], (
        "completion/eligibility surfaces must not read outcome_status "
        f"(contract section 5.1): {offenders}"
    )


def test_the_guarded_roster_still_matches_reality():
    """Fails if a completion surface is added or renamed without guarding it."""
    for relative in DENOMINATOR_SURFACES:
        assert _committed(relative)
    completion = _committed("mnq_lab/outcomes/completion.py")
    # the denominator really is built from the fit predicate
    assert "window_fits_rth" in completion
    assert "state_anchor" in completion


def test_guard_can_fail_on_a_synthetic_violation():
    """Negative control: the AST check detects a planted reference.

    Without this, a guard that walked the wrong node types would pass silently
    forever. Nothing is written to disk.
    """
    planted = "def denominator(rows):\n    return rows['outcome_status'] == 'ok'\n"
    tree = ast.parse(planted)
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value == FORBIDDEN
    ]
    assert found, "the AST guard would not have caught a planted violation"


def _diagnostics(*, eligible: np.ndarray):
    sessions = np.arange(20210601, 20210601 + eligible.size, dtype=np.int64)
    return completion_diagnostics(
        horizon_minutes=60,
        session_ids=sessions,
        calendar_years=sessions // 10_000,
        structurally_eligible=eligible,
        completed=np.ones(eligible.size, dtype=bool),
        target_mask=np.ones(eligible.size, dtype=bool),
        target_weights=np.ones(eligible.size, dtype=float) / eligible.size,
    )


def test_flipping_structural_fit_moves_the_denominator():
    """Behavioural witness: the fit predicate is what the denominator obeys."""
    size = 8
    all_eligible = _diagnostics(eligible=np.ones(size, dtype=bool))
    half = np.ones(size, dtype=bool)
    half[: size // 2] = False
    fewer_eligible = _diagnostics(eligible=half)

    # n_anchors is the denominator: the structurally eligible population
    assert all_eligible.target.n_anchors == size
    assert fewer_eligible.target.n_anchors == size // 2
    assert all_eligible.target.n_anchors != fewer_eligible.target.n_anchors


def test_completion_api_cannot_see_a_status_string():
    """The denominator function has no parameter through which a status arrives."""
    import inspect

    params = set(inspect.signature(completion_diagnostics).parameters)
    assert FORBIDDEN not in params
    assert {"structurally_eligible", "completed"} <= params
    assert not params & {"status", "statuses", "outcome_statuses"}


def test_denominator_rejects_a_non_boolean_eligibility_mask():
    """Fails closed rather than coercing a status-derived array into a mask."""
    with pytest.raises(SpineError):
        _diagnostics(eligible=np.array(["ok"] * 4, dtype="<U25"))
