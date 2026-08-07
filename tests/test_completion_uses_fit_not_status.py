"""Mechanical enforcement of the §5.1 binding consumer rule.

The contract requires every completion, eligibility and denominator calculation
to use the structural fit predicate and never ``outcome_status``. Revision 1
stated that rule in prose only, and the Stage 6 audit showed exactly why prose is
not enough: the justification described Phase 8 behaviour that existed only in
uncommitted files. A rule that lives in a document cannot fail; this one can.

Every revision so far was refuted by the next audit, so the history is kept:

* Revision 2 chose which modules to scan using eight denominator substrings.
  Re-audit 1: denominator logic named ``sum``, ``len``, ``size`` or ``total``
  would never be scanned. Substring discovery no longer decides anything.
* Revision 3 scanned two packages and pinned references by file, enclosing scope
  name and count. Re-audit 2: a same-scope, same-count rewrite of a producer
  turned its references into denominator logic and passed.
* Revision 4 pinned the enclosing STATEMENT of each reference. Re-audit 3 broke
  it twice. First, a producer reads the column into a local (``statuses =
  table.column("outcome_status")``); a new statement using that local computes a
  denominator without touching any pinned statement and without adding any
  literal. Second, a name assembled from constants (``"outcome_" + "status"``)
  read the forbidden field while matching none of the AST shapes scanned.

So, now:

1. **Every committed Python file under mnq_lab and tools is scanned.** Not a
   roster, not a package subset. ``tests`` is deliberately excluded: it plants
   forbidden references on purpose, and including it would make this guard
   self-defeating.
2. **Whole functions are pinned, not statements.** Any function containing an
   approved reference is fingerprinted in full, so a downstream use of a local
   alias changes the fingerprint even though the approved read is untouched.
   Module-level references are still pinned per statement, since a module has no
   enclosing function to fingerprint.
3. **Statically determinable names are resolved** before matching. Re-audit 4
   found the first version of this too narrow, so the resolved forms are now:
   string concatenation; f-strings including the ``!s``, ``!r`` and ``!a``
   conversions; ``str.join`` over an inline tuple/list OR a name bound to a
   constant sequence; ``str.format`` with positional AND keyword arguments,
   including constant tuples consumed by indexed fields such as ``{0[0]}`` and
   ``{p[1]}``; and names bound to any of those.
4. **Every name carries the SET of values it could statically hold**, unioned
   over the whole file and iterated to genuine convergence. Re-audit 5 showed
   why: resolving a name to a single value made the result order-dependent, so
   reassigning a name to something safe AFTER a forbidden read erased the
   evidence and under-detected. Union cannot be masked by a later assignment.
5. Substring discovery survives only as supplementary reporting.

**Stated limitations, deliberately not overclaimed.**

* Detection is STATIC. A name that can only be known at runtime — from
  configuration, an environment variable, a function return, ``**kwargs``, or a
  runtime format spec — is NOT detected, and refusing to guess is intentional.
* Resolution is file-wide, scope-INSENSITIVE and flow-INSENSITIVE. Because every
  binding is unioned rather than overwritten, shadowing and reassignment now
  over-approximate. This is NOT scope-aware analysis and is not claimed to be.
  The earlier claim that insensitivity "only over-detects" was FALSE while
  resolution was single-valued, and is recorded here as a corrected error.
* Two conditions fail CLOSED rather than passing quietly: a value set that grows
  past the enumeration cap collapses to an ABSORBING overflow sentinel and is
  treated as a hit, and a binding analysis that does not converge raises instead
  of returning a partial answer. Re-audit 6 found both claimed here but neither
  reachable-and-tested — the sentinel was not absorbing, and mutating either
  branch to fail open left the whole suite green. Both now carry controls.

The guarantee is therefore narrow and exact: a reference written as a literal,
or as a name derivable from literals by the forms in (3), cannot hide in a key,
attribute, lookup or alias, and cannot be hidden by later reassignment. It is
not a guarantee against runtime construction.

All guards run against **committed** source, so uncommitted work-in-progress
cannot mask a violation and cannot satisfy one either.
"""

from __future__ import annotations

import ast
import hashlib
import subprocess
from collections import Counter

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.constants import REPO_ROOT
from mnq_lab.phase8.diagnostics import completion_diagnostics

# tests/ is excluded on purpose: it contains planted references as controls.
SCAN_ROOTS = ("mnq_lab", "tools")

FORBIDDEN = "outcome_status"

# The ONLY permitted references, pinned by MEANING with full sha256 fingerprints
# of the normalised AST (``ast.dump`` without attributes, so line numbers,
# whitespace and comments do not matter but structure does).
#
# Functions that contain an approved read are pinned WHOLE. That is what closes
# the alias hole: excursions.validate_outcome_table and
# artifacts.write_outcome_artifact both bind the column to a local, and any later
# use of that local changes the function fingerprint.
PRODUCER_ALLOWANCE = {
    "mnq_lab/outcomes/artifacts.py": (
        (
            "write_outcome_artifact:function",
            "c74dc429d77d5dd3da270322a880c390063d9c57dae83ca77946710df3db01b5",
        ),
    ),
    "mnq_lab/outcomes/excursions.py": (
        (
            "<module>:statement",
            "263289011255a581e84df33e7adb6112d2eac85c8077b5c8431c42d01ca305d7",
        ),
        (
            "<module>:statement",
            "50587692788767edf5bd1b02f7ebc66b5fc293410d9809b2c0caa5f2dcc9cc1c",
        ),
        (
            "_ExactResolver.resolve:function",
            "f68aa0eb3f14b23d20d2d449a9cedf55e7e08fc5b38ba197c1bbb69bef9c8a61",
        ),
        (
            "validate_outcome_table:function",
            "79e0d0b5267f636e8811ea6a17a3726d0b6cdad12025effbdf3090e91a1b9c72",
        ),
    ),
}
# Direct references remain the independently auditable count; the pins above
# collapse the two inside validate_outcome_table into one function entry.
DIRECT_REFERENCE_TOTAL = 6

# Supplementary only. Reported, never used to decide what gets scanned.
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


def _committed(relative: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "cat-file", "blob", f"HEAD:{relative}"],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, f"{relative} unreadable at HEAD"
    return result.stdout.decode("utf-8")


def _all_scanned_files() -> list[str]:
    """Every committed .py under the scan roots, from git, with no filtering."""
    files: list[str] = []
    for root in SCAN_ROOTS:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-tree", "-r", "--name-only", f"HEAD:{root}"],
            capture_output=True,
            check=False,
            text=True,
        )
        assert result.returncode == 0, f"{root} unreadable at HEAD"
        files.extend(
            f"{root}/{name}"
            for name in result.stdout.splitlines()
            if name.endswith(".py")
        )
    return files


# f-string conversion codes: none, !s, !r, !a
_NO_CONVERSION = -1
_CONVERSIONS = {_NO_CONVERSION: str, 115: str, 114: repr, 97: ascii}

# Re-audit 5 forced a redesign. Resolving each name to ONE value made the
# analysis order-dependent, so a later reassignment erased an earlier forbidden
# binding and the read before it went undetected — an under-detection, not the
# conservative over-detection previously claimed. Every name therefore now
# carries the SET of every value it could statically hold anywhere in the file,
# and a read is forbidden if ANY member is the forbidden name. Union is monotone,
# so the analysis genuinely converges instead of stopping after a fixed count.
_MAX_POSSIBILITIES = 512
_MAX_ROUNDS = 100
# Emitted when a set would exceed the cap. Treated as a HIT, so an inability to
# enumerate fails closed rather than passing silently.
_OVERFLOW = object()


def _overflowed(*value_sets) -> bool:
    return any(_OVERFLOW in values for values in value_sets)


def _bounded(values) -> frozenset:
    """Collapse past the cap to the overflow sentinel, and keep it ABSORBING.

    Re-audit 6: without the ``_OVERFLOW in values`` test, a set that had already
    collapsed could be re-expanded by a later union, so the analysis oscillated
    and reached the round cap instead of settling on the sentinel. The claimed
    fail-closed hit was therefore unreachable in practice. Once overflow is
    reached it must stay reached.
    """
    values = frozenset(values)
    if _OVERFLOW in values or len(values) > _MAX_POSSIBILITIES:
        return frozenset({_OVERFLOW})
    return values


def _combinations(option_sets):
    """Cartesian product of option sets, or _OVERFLOW, or None if any is empty."""
    combinations = [()]
    for options in option_sets:
        usable = [value for value in options if value is not _OVERFLOW]
        if not usable:
            return None
        combinations = [
            combination + (value,) for combination in combinations for value in usable
        ]
        if len(combinations) > _MAX_POSSIBILITIES:
            return _OVERFLOW
    return combinations


def _static_values(node: ast.AST, bindings: dict) -> frozenset:
    """Every value this node could statically take.

    Members are ``str`` or ``tuple[str, ...]`` (so a constant sequence can flow
    into ``join`` or an indexed ``format`` field). An EMPTY set means the value
    is not statically determinable — an honest unknown, never a guess.
    """
    if isinstance(node, ast.Constant):
        return frozenset({node.value}) if isinstance(node.value, str) else frozenset()
    if isinstance(node, ast.Name):
        return bindings.get(node.id, frozenset())
    if isinstance(node, (ast.Tuple, ast.List)):
        element_sets = [_static_values(element, bindings) for element in node.elts]
        if _overflowed(*element_sets):
            return frozenset({_OVERFLOW})
        combinations = _combinations(
            [{v for v in options if isinstance(v, str)} for options in element_sets]
        )
        if combinations is None:
            return frozenset()
        if combinations is _OVERFLOW:
            return frozenset({_OVERFLOW})
        return _bounded(combinations)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_values(node.left, bindings)
        right = _static_values(node.right, bindings)
        if _overflowed(left, right):
            return frozenset({_OVERFLOW})
        return _bounded(
            first + second
            for first in left
            if isinstance(first, str)
            for second in right
            if isinstance(second, str)
        )
    if isinstance(node, ast.JoinedStr):
        part_sets = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                part_sets.append(frozenset({value.value}))
            elif isinstance(value, ast.FormattedValue):
                # a format spec can depend on runtime state; refuse it
                if value.format_spec is not None:
                    return frozenset()
                convert = _CONVERSIONS.get(value.conversion)
                if convert is None:
                    return frozenset()
                resolved = _static_values(value.value, bindings)
                if _overflowed(resolved):
                    return frozenset({_OVERFLOW})
                part_sets.append(
                    frozenset(
                        convert(item) for item in resolved if isinstance(item, str)
                    )
                )
            else:
                return frozenset()
        combinations = _combinations(part_sets)
        if combinations is None:
            return frozenset()
        if combinations is _OVERFLOW:
            return frozenset({_OVERFLOW})
        return _bounded("".join(parts) for parts in combinations)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        bases = _static_values(node.func.value, bindings)
        if _overflowed(bases):
            return frozenset({_OVERFLOW})
        base_strings = {value for value in bases if isinstance(value, str)}
        if not base_strings:
            return frozenset()
        if node.func.attr == "join":
            if node.keywords or len(node.args) != 1:
                return frozenset()
            sequences = _static_values(node.args[0], bindings)
            if _overflowed(sequences):
                return frozenset({_OVERFLOW})
            return _bounded(
                base.join(sequence)
                for base in base_strings
                for sequence in sequences
                if isinstance(sequence, tuple)
            )
        if node.func.attr == "format":
            option_sets = [frozenset(base_strings)]
            for argument in node.args:
                option_sets.append(_static_values(argument, bindings))
            names: list[str] = []
            for keyword in node.keywords:
                if keyword.arg is None:  # **kwargs: not statically known
                    return frozenset()
                names.append(keyword.arg)
                option_sets.append(_static_values(keyword.value, bindings))
            if _overflowed(*option_sets):
                return frozenset({_OVERFLOW})
            combinations = _combinations(option_sets)
            if combinations is None:
                return frozenset()
            if combinations is _OVERFLOW:
                return frozenset({_OVERFLOW})
            results = set()
            positional = len(node.args)
            for combination in combinations:
                base = combination[0]
                arguments = combination[1 : 1 + positional]
                keywords = dict(zip(names, combination[1 + positional :]))
                try:
                    results.add(base.format(*arguments, **keywords))
                except (IndexError, KeyError, ValueError, TypeError, AttributeError):
                    continue
            return _bounded(results)
    return frozenset()


def _constant_bindings(tree: ast.AST) -> dict:
    """Every static value each name could hold, unioned to genuine convergence.

    File-wide, scope-INSENSITIVE and flow-INSENSITIVE, but now by UNION rather
    than by overwrite: a name keeps every static value assigned to it anywhere,
    so a later reassignment can never mask an earlier forbidden one. Shadowing
    across scopes still over-approximates, which is the safe direction.

    The loop runs until nothing changes. Union over a bounded lattice is
    monotone, so this terminates; the round cap exists only as a backstop and
    raises rather than returning a half-computed answer.
    """
    bindings: dict = {}
    for _ in range(_MAX_ROUNDS):
        changed = False
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.value is not None
            ):
                targets = [node.target.id]
            if not targets:
                continue
            values = _static_values(node.value, bindings)
            if not values:
                continue
            for target in targets:
                merged = _bounded(bindings.get(target, frozenset()) | values)
                if merged != bindings.get(target):
                    bindings[target] = merged
                    changed = True
        if not changed:
            return bindings
    raise AssertionError(  # fail closed: never return a half-converged analysis
        "constant-binding analysis did not converge; the guard cannot vouch for "
        "this file and must not report it as clean"
    )


def _is_forbidden_reference(node: ast.AST, bindings: dict) -> bool:
    if isinstance(node, ast.Attribute) and node.attr == FORBIDDEN:
        return True
    if isinstance(node, ast.Name) and node.id == FORBIDDEN:
        return True
    if isinstance(
        node, (ast.Constant, ast.BinOp, ast.JoinedStr, ast.Call, ast.Name)
    ):
        values = _static_values(node, bindings)
        if _OVERFLOW in values:
            return True  # cannot enumerate: fail closed
        return FORBIDDEN in values
    return False


def _protection_signature(relative: str, source: str) -> tuple[tuple[str, str], ...]:
    """Sorted (label, full sha256) covering every forbidden reference.

    A reference inside a function contributes ONE entry fingerprinting that whole
    function, so downstream use of a local alias is covered. A module-level
    reference contributes its enclosing statement.
    """
    tree = ast.parse(source, filename=relative)
    consts = _constant_bindings(tree)
    parent_of: dict = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent_of[child] = node

    module_entries: list[tuple[str, str]] = []
    function_entries: dict[str, str] = {}
    for node in ast.walk(tree):
        if not _is_forbidden_reference(node, consts):
            continue
        chain: list[str] = []
        statement = None
        function = None
        current = node
        while current in parent_of:
            current = parent_of[current]
            if statement is None and isinstance(current, ast.stmt):
                statement = current
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if function is None:
                    function = current
                chain.append(current.name)
            elif isinstance(current, ast.ClassDef):
                chain.append(current.name)
        if function is None:
            dumped = ast.dump(statement, include_attributes=False)
            module_entries.append(
                ("<module>:statement", hashlib.sha256(dumped.encode("utf-8")).hexdigest())
            )
        else:
            qualname = ".".join(reversed(chain))
            dumped = ast.dump(function, include_attributes=False)
            function_entries[f"{qualname}:function"] = hashlib.sha256(
                dumped.encode("utf-8")
            ).hexdigest()
    return tuple(sorted(module_entries + list(function_entries.items())))


def _direct_reference_count(relative: str, source: str) -> int:
    """How many forbidden references exist, independent of how they are pinned."""
    tree = ast.parse(source, filename=relative)
    consts = _constant_bindings(tree)
    return sum(1 for node in ast.walk(tree) if _is_forbidden_reference(node, consts))


def _offenders(files, read, allowance: dict) -> list[str]:
    """Every forbidden reference not covered by an exact pinned allowance."""
    offenders: list[str] = []
    for relative in sorted(files):
        signature = _protection_signature(relative, read(relative))
        if not signature:
            continue
        permitted = allowance.get(relative)
        if permitted is None:
            offenders.append(
                f"{relative}: {len(signature)} protected region(s) referencing "
                f"{FORBIDDEN}; file is not a pinned producer"
            )
        elif signature != tuple(permitted):
            offenders.append(
                f"{relative}: protection signature changed; pinned {tuple(permitted)} "
                f"got {signature}"
            )
    return offenders


def test_the_scan_covers_every_committed_module_under_the_scan_roots():
    """The boundary is whole trees, not a subset, and includes operational tools."""
    files = _all_scanned_files()
    assert len(files) >= 70, len(files)
    for package in (
        "mnq_lab/spine",
        "mnq_lab/phase8",
        "mnq_lab/conditioners",
        "mnq_lab/core",
        "mnq_lab/outcomes",
        "mnq_lab/production",
        "mnq_lab/ledger",
        "tools",
    ):
        assert any(f.startswith(package + "/") for f in files), package
    # tests/ is excluded on purpose; it plants references as controls
    assert not any(f.startswith("tests/") for f in files)
    for relative in files:
        assert isinstance(_protection_signature(relative, _committed(relative)), tuple)


def test_no_module_reads_outcome_status_outside_the_pinned_producers():
    """The gate. Fails on any unpinned, rewritten or newly-aliased reference."""
    offenders = _offenders(_all_scanned_files(), _committed, PRODUCER_ALLOWANCE)
    assert offenders == [], (
        "outcome_status may only be read in pinned producer contexts "
        f"(contract section 5.1): {offenders}"
    )


def test_the_pinned_producer_allowance_is_exactly_the_committed_reality():
    """Fails if a producer reference is added, removed, moved or rewritten."""
    for relative, permitted in PRODUCER_ALLOWANCE.items():
        assert _protection_signature(relative, _committed(relative)) == tuple(permitted), (
            relative
        )
    direct = sum(
        _direct_reference_count(relative, _committed(relative))
        for relative in PRODUCER_ALLOWANCE
    )
    assert direct == DIRECT_REFERENCE_TOTAL
    others = [
        relative
        for relative in _all_scanned_files()
        if relative not in PRODUCER_ALLOWANCE
        and _protection_signature(relative, _committed(relative))
    ]
    assert others == [], others


def test_a_downstream_alias_of_an_approved_read_is_rejected():
    """Re-audit 3 blocker 1: the alias hole.

    A producer binds the status column to a local. A new statement using that
    local computes a denominator while adding no literal and leaving the approved
    read untouched. Statement-level pins missed this entirely; the whole-function
    pin must catch it. Nothing is written to disk.
    """
    relative = "mnq_lab/outcomes/excursions.py"
    source = _committed(relative)
    lines = source.split("\n")
    anchors = [
        index
        for index, line in enumerate(lines)
        if 'statuses = table.column("outcome_status")' in line
    ]
    assert len(anchors) == 1, anchors
    lines.insert(
        anchors[0] + 1,
        "    denominator_from_status = int(np.count_nonzero(statuses == STATUS_OK))",
    )
    mutated = "\n".join(lines)

    # the mutant adds NO new forbidden reference: that is what made it invisible
    assert _direct_reference_count(relative, mutated) == _direct_reference_count(
        relative, source
    )
    # ...and it is rejected anyway, because the enclosing function changed
    offenders = _offenders([relative], {relative: mutated}.__getitem__, PRODUCER_ALLOWANCE)
    assert len(offenders) == 1 and "signature changed" in offenders[0], offenders


def test_statically_constructed_field_names_are_detected():
    """Re-audit 3 blocker 2: names assembled from constants.

    Each module reads exactly the forbidden field without ever writing it as a
    single literal. All must be detected and rejected.
    """
    sources = {
        "mnq_lab/phase8/by_concat.py": (
            'KEY = "outcome_" + "status"\n'
            "def denominator(rows):\n"
            "    return rows[KEY]\n"
        ),
        "mnq_lab/phase8/by_join.py": (
            'KEY = "".join(("outcome", "_status"))\n'
            "def denominator(rows):\n"
            "    return rows[KEY]\n"
        ),
        "mnq_lab/phase8/by_fstring.py": (
            'PREFIX = "outcome"\n'
            'KEY = f"{PREFIX}_status"\n'
            "def denominator(rows):\n"
            "    return rows[KEY]\n"
        ),
        "mnq_lab/phase8/by_format.py": (
            'KEY = "{}_{}".format("outcome", "status")\n'
            "def denominator(rows):\n"
            "    return rows[KEY]\n"
        ),
        # --- re-audit 4 escapes ---
        "mnq_lab/phase8/by_format_kwargs.py": (
            'KEY = "{left}_{right}".format(\n'
            '    left="outcome",\n'
            '    right="status",\n'
            ")\n"
            "def denominator(rows):\n"
            "    return rows[KEY]\n"
        ),
        "mnq_lab/phase8/by_fstring_conversion.py": (
            'PREFIX = "outcome"\n'
            'KEY = f"{PREFIX!s}_status"\n'
            "def denominator(rows):\n"
            "    return rows[KEY]\n"
        ),
        "mnq_lab/phase8/by_named_sequence_join.py": (
            'PARTS = ("outcome", "_status")\n'
            'KEY = "".join(PARTS)\n'
            "def denominator(rows):\n"
            "    return rows[KEY]\n"
        ),
        # --- re-audit 5 escapes: constant tuple consumed by an indexed field ---
        "mnq_lab/phase8/by_positional_tuple_format.py": (
            'KEY = "{0[0]}_{0[1]}".format(("outcome", "status"))\n'
            "def denominator(rows):\n"
            "    return rows[KEY]\n"
        ),
        "mnq_lab/phase8/by_keyword_tuple_format.py": (
            'KEY = "{p[0]}_{p[1]}".format(\n'
            '    p=("outcome", "status")\n'
            ")\n"
            "def denominator(rows):\n"
            "    return rows[KEY]\n"
        ),
    }
    for relative, source in sources.items():
        assert FORBIDDEN not in source, f"the control must not use a literal: {relative}"
        assert _protection_signature(relative, source), f"undetected: {relative}"
    offenders = _offenders(list(sources), sources.__getitem__, PRODUCER_ALLOWANCE)
    assert len(offenders) == len(sources), offenders
    for offender in offenders:
        assert "not a pinned producer" in offender, offender


def test_a_later_reassignment_cannot_mask_an_earlier_forbidden_read():
    """Re-audit 5 blocker: resolving each name to ONE value under-detected.

    The forbidden field is read BEFORE the names are reassigned to safe values.
    Single-value resolution kept only the later bindings and missed the read
    entirely — an under-detection, which is why the previous "only over-detects"
    claim was wrong. Union over every static binding must catch it.
    """
    source = (
        "def denominator(rows):\n"
        '    PREFIX = "outcome"\n'
        '    KEY = f"{PREFIX}_status"\n'
        "    value = rows[KEY]\n"
        '    PREFIX = "safe"\n'
        '    KEY = "safe"\n'
        "    return value\n"
    )
    relative = "mnq_lab/phase8/by_reassignment.py"
    assert FORBIDDEN not in source
    assert _protection_signature(relative, source), "reassignment escape survived"
    offenders = _offenders([relative], {relative: source}.__getitem__, PRODUCER_ALLOWANCE)
    assert len(offenders) == 1 and "not a pinned producer" in offenders[0], offenders


def test_binding_analysis_converges_rather_than_stopping_after_a_fixed_count():
    """The loop must reach a fixpoint, not run a fixed number of passes.

    A reverse-ordered alias chain needs one round per link when the file is
    walked top-down. Eight links previously exceeded the six-pass loop; genuine
    convergence resolves the whole chain.
    """
    links = "\n".join(f"A{index} = A{index + 1}" for index in range(8))
    source = (
        f"{links}\n"
        'A8 = "outcome_" + "status"\n'
        "def denominator(rows):\n"
        "    return rows[A0]\n"
    )
    assert FORBIDDEN not in source
    tree = ast.parse(source)
    bindings = _constant_bindings(tree)
    assert bindings["A0"] == frozenset({FORBIDDEN}), bindings.get("A0")


def test_nonconstant_format_arguments_are_refused_not_guessed():
    """Resolution must stop at the first genuinely unknown value.

    A ``**kwargs`` expansion, a runtime keyword value and a runtime format spec
    are all undecidable statically. Refusing them is what keeps the resolver
    honest rather than speculative.
    """
    undecidable = (
        'def denominator(rows, mapping):\n'
        '    return rows["{left}_{right}".format(**mapping)]\n',
        "def denominator(rows, part):\n"
        '    return rows["{left}_status".format(left=part)]\n',
        "def denominator(rows, spec):\n"
        '    return rows[f"outcome_{spec:>{spec}}"]\n',
    )
    for index, source in enumerate(undecidable):
        assert _protection_signature(f"mnq_lab/phase8/undecidable_{index}.py", source) == ()


def test_a_runtime_constructed_name_is_documented_as_undetected():
    """Pins the STATED limitation so the guarantee is never quietly widened.

    A name that only exists at runtime is not detected. Recorded as a live
    witness rather than a caveat in prose, so any future claim of complete
    detection has to confront a failing test.
    """
    source = (
        "import os\n"
        "def denominator(rows):\n"
        '    return rows[os.environ["FIELD"]]\n'
    )
    assert _protection_signature("mnq_lab/phase8/by_runtime.py", source) == ()


def test_overflow_is_absorbing_and_fails_closed(monkeypatch):
    """Re-audit 6 blocker: the overflow path was claimed but never exercised.

    Two defects at once. The sentinel was not absorbing, so a collapsed set could
    be re-expanded by a later union and the analysis oscillated to the round cap
    instead of settling — meaning the fail-closed hit never actually arrived. And
    no test drove the path at all, so mutating it to fail OPEN left the suite
    green. Lowering the cap makes the path deterministic and cheap.

    The source contains no forbidden literal: detection comes purely from the
    guard refusing to vouch for what it cannot enumerate.
    """
    monkeypatch.setitem(globals(), "_MAX_POSSIBILITIES", 3)
    source = (
        'KEY = "alpha"\n'
        'KEY = "bravo"\n'
        'KEY = "charlie"\n'
        'KEY = "delta"\n'
        'KEY = "echo"\n'
        "def denominator(rows):\n"
        "    return rows[KEY]\n"
    )
    relative = "mnq_lab/phase8/by_overflow.py"
    assert FORBIDDEN not in source

    # it must CONVERGE on the sentinel, not raise, and not oscillate
    bindings = _constant_bindings(ast.parse(source))
    assert bindings["KEY"] == frozenset({_OVERFLOW}), bindings["KEY"]
    # absorbing: unioning more values in cannot re-expand it
    assert _bounded(bindings["KEY"] | {"anything"}) == frozenset({_OVERFLOW})
    # and an unenumerable name is treated as a hit
    assert _is_forbidden_reference(ast.parse("KEY").body[0].value, bindings)

    assert _protection_signature(relative, source), "overflow must fail closed"
    offenders = _offenders([relative], {relative: source}.__getitem__, PRODUCER_ALLOWANCE)
    assert len(offenders) == 1 and "not a pinned producer" in offenders[0], offenders


def test_non_convergence_raises_rather_than_returning_partial_bindings(monkeypatch):
    """Re-audit 6 blocker: the round-cap backstop was never exercised either.

    A reverse-ordered alias chain propagates one link per round, so a chain
    longer than the cap cannot settle. The guard must refuse to answer rather
    than hand back a half-computed analysis, which would read as clean. Mutating
    the raise into ``return bindings`` previously left the whole suite green.
    """
    monkeypatch.setitem(globals(), "_MAX_ROUNDS", 3)
    links = "\n".join(f"A{index} = A{index + 1}" for index in range(10))
    source = f'{links}\nA10 = "outcome_" + "status"\n'
    with pytest.raises(AssertionError, match="did not converge"):
        _constant_bindings(ast.parse(source))


def test_a_same_scope_same_count_denominator_rewrite_is_rejected():
    """Re-audit 2 blocker: counts and scope names are not meaning."""
    relative = "mnq_lab/outcomes/excursions.py"
    rewritten = (
        'OUTCOME_SCHEMA = ("outcome_status",)\n'
        '_DTYPES = {"outcome_status": "str"}\n'
        "\n"
        "class _ExactResolver:\n"
        "    def resolve(self, rows):\n"
        '        return sum(rows["outcome_status"] == "ok")\n'
        "\n"
        "def validate_outcome_table(rows):\n"
        "    return (\n"
        '        sum(rows["outcome_status"] == "ok"),\n'
        '        len(rows["outcome_status"]),\n'
        "    )\n"
    )
    signature = _protection_signature(relative, rewritten)
    pinned = PRODUCER_ALLOWANCE[relative]

    # the control only means something if it reproduces the pinned region labels
    assert Counter(label for label, _ in signature) == Counter(
        label for label, _ in pinned
    ), signature

    offenders = _offenders([relative], {relative: rewritten}.__getitem__, PRODUCER_ALLOWANCE)
    assert len(offenders) == 1 and "signature changed" in offenders[0], offenders


def test_a_new_consumer_outside_outcomes_and_phase8_is_rejected():
    """A consumer in any other package, or in tools, fails automatically."""
    sources = {
        "mnq_lab/conditioners/new_consumer.py": (
            "def keep(rows):\n    return rows['outcome_status'] == 'ok'\n"
        ),
        "mnq_lab/spine/new_consumer.py": (
            "def usable(rows):\n    return [r for r in rows if r['outcome_status']]\n"
        ),
        "mnq_lab/core/new_consumer.py": (
            "def tally(rows):\n    return sum(1 for r in rows if r['outcome_status'])\n"
        ),
        "tools/new_consumer.py": (
            "def eligible(rows):\n    return len(rows[rows['outcome_status'] == 'ok'])\n"
        ),
    }
    offenders = _offenders(list(sources), sources.__getitem__, PRODUCER_ALLOWANCE)
    assert len(offenders) == 4, offenders
    for relative in sources:
        assert any(o.startswith(f"{relative}:") for o in offenders), relative


def test_injected_denominators_without_any_primitive_are_still_caught():
    """Re-audit 1 requirement: naming is irrelevant, everything is scanned."""
    sources = {
        "mnq_lab/phase8/by_sum.py": (
            "def total(fit, rows):\n"
            "    return int(fit.sum()), rows['outcome_status']\n"
        ),
        "mnq_lab/phase8/by_len.py": (
            "def sample_size(rows, fit):\n"
            "    return len(rows[fit]) if rows['outcome_status'] else 0\n"
        ),
        "mnq_lab/outcomes/by_other_name.py": (
            "def population(rows):\n"
            "    n_units = rows['outcome_status'].shape[0]\n"
            "    return n_units\n"
        ),
    }
    for relative, source in sources.items():
        assert not any(p in source for p in DENOMINATOR_PRIMITIVES), relative
    offenders = _offenders(list(sources), sources.__getitem__, PRODUCER_ALLOWANCE)
    assert len(offenders) == 3, offenders


def test_a_new_reference_inside_a_pinned_producer_fails():
    """An allowance is a pin, not a blanket exemption for the file."""
    relative = "mnq_lab/outcomes/artifacts.py"
    source = _committed(relative) + (
        "\n\ndef sneaked(rows):\n    return rows['outcome_status']\n"
    )
    offenders = _offenders([relative], {relative: source}.__getitem__, PRODUCER_ALLOWANCE)
    assert len(offenders) == 1 and "signature changed" in offenders[0], offenders


def test_a_clean_new_module_does_not_trip_the_guard():
    """Fails if the guard degenerates into flagging every new file."""
    sources = {"mnq_lab/phase8/clean.py": "def helper(x):\n    return x + 1\n"}
    assert _offenders(list(sources), sources.__getitem__, PRODUCER_ALLOWANCE) == []


def test_primitive_discovery_is_supplementary_reporting_only():
    """Discovery still names known denominator surfaces, but gates nothing."""
    scanned = set(_all_scanned_files())
    discovered = {
        relative
        for relative in scanned
        if any(p in _committed(relative) for p in DENOMINATOR_PRIMITIVES)
    }
    assert {
        "mnq_lab/outcomes/completion.py",
        "mnq_lab/phase8/diagnostics.py",
        "mnq_lab/phase8/production.py",
        "mnq_lab/phase8/day_types.py",
        "mnq_lab/phase8/estimands.py",
        "mnq_lab/phase8/interactions.py",
    } <= discovered
    # strictly fewer than the scanned set, which is exactly why it cannot gate
    assert discovered < scanned


def test_completion_denominator_is_built_from_the_fit_predicate():
    """Fails if the denominator stops resting on the structural fit axis."""
    completion = _committed("mnq_lab/outcomes/completion.py")
    assert "window_fits_rth" in completion
    assert "state_anchor" in completion


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
