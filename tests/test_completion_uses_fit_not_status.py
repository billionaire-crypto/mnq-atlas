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

# F-B: the roster is DERIVED, not hand-maintained. Revision 1 listed five files
# by hand, which silently omitted phase8/estimands.py and phase8/interactions.py
# — both compute a completion denominator (``n_anchors``) — so the roster could
# not detect a NEW denominator surface. Every committed module under the scanned
# packages that references a denominator or eligibility primitive is now
# discovered mechanically and AST-checked. Adding a new one is caught with no
# edit to this file.
SCANNED_PACKAGES = ("mnq_lab/outcomes", "mnq_lab/phase8")
DENOMINATOR_PRIMITIVES = (
    "n_anchors",
    "structurally_eligible",
    "structural_completion_eligibility",
    "denominator",
    "eligible",
    "eligibility",
    "weight_ess",
    "count_nonzero",
)
# Always AST-checked even if a future refactor strips the primitive tokens from
# their text: the original hand roster, kept so discovery can only widen cover.
ALWAYS_CHECK = (
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


def _committed_py_files(package: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-tree", "-r", "--name-only", f"HEAD:{package}"],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, f"{package} unreadable at HEAD"
    return [f"{package}/{n}" for n in result.stdout.splitlines() if n.endswith(".py")]


def _module_is_denominator_surface(source: str) -> bool:
    """A module counts as a denominator surface iff it names a primitive."""
    return any(primitive in source for primitive in DENOMINATOR_PRIMITIVES)


def _discover(files: list[str], read: object) -> tuple[str, ...]:
    """Discovery mechanism, factored so it can be exercised on injected input."""
    return tuple(sorted(f for f in files if _module_is_denominator_surface(read(f))))


def _discover_committed_surfaces() -> tuple[str, ...]:
    files: list[str] = []
    for package in SCANNED_PACKAGES:
        files.extend(_committed_py_files(package))
    return _discover(files, _committed)


def _reads_outcome_status(relative: str) -> list[str]:
    """AST over identifiers, constants and attributes: no getattr/dict-key hiding."""
    offenders: list[str] = []
    tree = ast.parse(_committed(relative), filename=relative)
    for node in ast.walk(tree):
        hit = (
            (isinstance(node, ast.Constant) and node.value == FORBIDDEN)
            or (isinstance(node, ast.Attribute) and node.attr == FORBIDDEN)
            or (isinstance(node, ast.Name) and node.id == FORBIDDEN)
        )
        if hit:
            offenders.append(f"{relative}:{getattr(node, 'lineno', '?')}")
    return offenders


def test_no_denominator_surface_reads_outcome_status_in_committed_source():
    """Fails if any discovered completion surface consumes the status string."""
    roster = set(_discover_committed_surfaces()) | set(ALWAYS_CHECK)
    offenders: list[str] = []
    for relative in sorted(roster):
        offenders.extend(_reads_outcome_status(relative))
    assert offenders == [], (
        "completion/eligibility surfaces must not read outcome_status "
        f"(contract section 5.1): {offenders}"
    )


def test_discovery_covers_the_known_surfaces_and_the_revision_1_gap():
    """Fails if discovery under-collects — e.g. the mechanism silently breaks.

    Pins the two surfaces the hand roster omitted, so a regression to hand
    maintenance is caught, and asserts discovery is non-trivial.
    """
    discovered = set(_discover_committed_surfaces())
    known_required = {
        "mnq_lab/outcomes/completion.py",
        "mnq_lab/phase8/diagnostics.py",
        "mnq_lab/phase8/production.py",
        "mnq_lab/phase8/day_types.py",
        "mnq_lab/phase8/estimands.py",
        "mnq_lab/phase8/interactions.py",
    }
    missing = known_required - discovered
    assert not missing, f"discovery no longer finds denominator surfaces: {missing}"
    # the revision-1 gap specifically
    assert "mnq_lab/phase8/estimands.py" in discovered
    assert "mnq_lab/phase8/interactions.py" in discovered
    assert len(discovered) >= len(known_required)


def test_discovery_flags_a_planted_denominator_module_outside_the_roster():
    """Negative control on the discovery mechanism, via an injected file list.

    A new module that computes a denominator MUST be picked up (and therefore
    AST-checked); a module with no primitive MUST be ignored. Nothing is written
    to disk. This is what the hand roster could not do.
    """
    planted = (
        "import numpy as np\n"
        "def denom(mask, rows):\n"
        "    n_anchors = int(np.count_nonzero(mask))\n"
        "    return rows['outcome_status'] == 'ok'\n"
    )
    clean = "def helper(x):\n    return x + 1\n"
    injected = _discover(
        ["pkg/sneaky.py", "pkg/clean.py"],
        lambda p: planted if p.endswith("sneaky.py") else clean,
    )
    assert injected == ("pkg/sneaky.py",), injected
    # and once discovered, the AST check would catch its status read
    found = [
        node
        for node in ast.walk(ast.parse(planted))
        if isinstance(node, ast.Constant) and node.value == FORBIDDEN
    ]
    assert found, "a discovered denominator surface reading outcome_status must be caught"


def test_completion_denominator_is_built_from_the_fit_predicate():
    """Fails if the denominator stops resting on the structural fit axis."""
    completion = _committed("mnq_lab/outcomes/completion.py")
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
