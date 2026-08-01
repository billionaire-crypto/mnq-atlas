"""Exact-rational guards for the preregistered Phase 5 v2 coverage gate."""

from __future__ import annotations

import ast
import copy
from fractions import Fraction
from math import comb
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE_FIXTURE_PATH = REPO_ROOT / "tests" / "test_bootstrap_acceptance.py"
ACCEPTANCE_RECORD_PATH = REPO_ROOT / "docs" / "PHASE5_ACCEPTANCE_RECORD.md"

CALIBRATION_COVERED = 2771
CALIBRATION_REPLICATIONS = 3000
V2_OUTER_REPLICATIONS = 300
V2_COVERAGE_ROOT_ENTROPY = 329373099305365003560734362733578893222
EXPECTED_LOWER_BOUND = 268
EXPECTED_UPPER_BOUND = 286
LOWER_QUANTILE = Fraction(1, 40)
UPPER_QUANTILE = Fraction(39, 40)
DERIVATION_RECORD_HEADING = (
    "## V2 exact gate derivation and static fixture — `NOT EXECUTED`"
)


def _direct_binomial_cdfs(
    trials: int,
    success_probability: Fraction,
) -> tuple[Fraction, ...]:
    failure_probability = 1 - success_probability
    cumulative = Fraction(0, 1)
    cdfs = []
    for count in range(trials + 1):
        cumulative += (
            comb(trials, count)
            * success_probability**count
            * failure_probability ** (trials - count)
        )
        cdfs.append(cumulative)
    return tuple(cdfs)


def _recurrence_binomial_cdfs(
    trials: int,
    success_probability: Fraction,
) -> tuple[Fraction, ...]:
    failure_probability = 1 - success_probability
    probability = failure_probability**trials
    cumulative = probability
    cdfs = [cumulative]
    for count in range(trials):
        probability *= Fraction(trials - count, count + 1)
        probability *= success_probability / failure_probability
        cumulative += probability
        cdfs.append(cumulative)
    return tuple(cdfs)


def _derive_bounds(cdfs: tuple[Fraction, ...]) -> tuple[int, int]:
    lower = next(
        count for count, cumulative in enumerate(cdfs)
        if cumulative >= LOWER_QUANTILE
    )
    upper = next(
        count for count, cumulative in enumerate(cdfs)
        if cumulative >= UPPER_QUANTILE
    )
    return lower, upper


def _satisfies_smallest_quantile_definition(
    cdfs: tuple[Fraction, ...],
    bound: int,
    quantile: Fraction,
) -> bool:
    previous = cdfs[bound - 1] if bound > 0 else Fraction(0, 1)
    return previous < quantile <= cdfs[bound]


def _literal_integer_assignments(path: Path) -> dict[str, int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assignments = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, int)
        ):
            assignments[node.targets[0].id] = node.value.value
    return assignments


def _function_node(path: Path, function_name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    matches = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    ]
    assert len(matches) == 1
    return matches[0]


class _CoverageFixtureNormalizer(ast.NodeTransformer):
    def visit_Assign(self, node: ast.Assign) -> ast.Assign:
        node = self.generic_visit(node)
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
            if target == "lower_coverage_count":
                node.value = ast.Name(id="REGISTERED_LOWER_BOUND", ctx=ast.Load())
            elif target == "upper_coverage_count":
                node.value = ast.Name(id="REGISTERED_UPPER_BOUND", ctx=ast.Load())
        return node

    def visit_Name(self, node: ast.Name) -> ast.Name:
        if node.id in {"COVERAGE_ROOT_ENTROPY", "V2_COVERAGE_ROOT_ENTROPY"}:
            return ast.copy_location(
                ast.Name(id="REGISTERED_ROOT_ENTROPY", ctx=ast.Load()),
                node,
            )
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.Constant:
        if node.value in {
            "PHASE5_COVERAGE_RESULT=",
            "PHASE5_COVERAGE_V2_RESULT=",
        }:
            return ast.copy_location(
                ast.Constant(value="REGISTERED_EVIDENCE_LABEL="),
                node,
            )
        return node


def _normalized_coverage_body(function: ast.FunctionDef) -> str:
    body = copy.deepcopy(function.body)
    normalized = _CoverageFixtureNormalizer().visit(ast.Module(body=body))
    ast.fix_missing_locations(normalized)
    return ast.dump(normalized, include_attributes=False)


def _fixture_constants_match(assignments: dict[str, int]) -> bool:
    expected = {
        "V2_COVERAGE_ROOT_ENTROPY": V2_COVERAGE_ROOT_ENTROPY,
        "V2_CALIBRATION_COVERED": CALIBRATION_COVERED,
        "V2_CALIBRATION_REPLICATIONS": CALIBRATION_REPLICATIONS,
        "V2_LOWER_COVERAGE_COUNT": EXPECTED_LOWER_BOUND,
        "V2_UPPER_COVERAGE_COUNT": EXPECTED_UPPER_BOUND,
    }
    return all(assignments.get(name) == value for name, value in expected.items())


def _record_contains_contract(record: str) -> bool:
    required = (
        "K = 2771",
        "K/3000 = 2771/3000",
        "[268, 286]",
        "P[C < 268]",
        "P[C > 286]",
        "sum(c=0..267)",
        "sum(c=287..300)",
    )
    return all(token in record for token in required)


def test_v2_exact_binomial_bounds_are_mechanically_derived():
    probability = Fraction(CALIBRATION_COVERED, CALIBRATION_REPLICATIONS)
    direct_cdfs = _direct_binomial_cdfs(V2_OUTER_REPLICATIONS, probability)
    recurrence_cdfs = _recurrence_binomial_cdfs(
        V2_OUTER_REPLICATIONS,
        probability,
    )

    assert direct_cdfs == recurrence_cdfs
    assert direct_cdfs[-1] == 1
    assert _derive_bounds(direct_cdfs) == (
        EXPECTED_LOWER_BOUND,
        EXPECTED_UPPER_BOUND,
    )
    assert _satisfies_smallest_quantile_definition(
        direct_cdfs,
        EXPECTED_LOWER_BOUND,
        LOWER_QUANTILE,
    )
    assert _satisfies_smallest_quantile_definition(
        direct_cdfs,
        EXPECTED_UPPER_BOUND,
        UPPER_QUANTILE,
    )

    lower_tail = direct_cdfs[EXPECTED_LOWER_BOUND - 1]
    upper_tail = 1 - direct_cdfs[EXPECTED_UPPER_BOUND]
    central_probability = (
        direct_cdfs[EXPECTED_UPPER_BOUND] - lower_tail
    )
    assert lower_tail + central_probability + upper_tail == 1

    # Required negative cases: all adjacent bound mutations violate the
    # frozen smallest-quantile definition at at least one boundary.
    assert not _satisfies_smallest_quantile_definition(
        direct_cdfs,
        EXPECTED_LOWER_BOUND - 1,
        LOWER_QUANTILE,
    )
    assert not _satisfies_smallest_quantile_definition(
        direct_cdfs,
        EXPECTED_LOWER_BOUND + 1,
        LOWER_QUANTILE,
    )
    assert not _satisfies_smallest_quantile_definition(
        direct_cdfs,
        EXPECTED_UPPER_BOUND - 1,
        UPPER_QUANTILE,
    )
    assert not _satisfies_smallest_quantile_definition(
        direct_cdfs,
        EXPECTED_UPPER_BOUND + 1,
        UPPER_QUANTILE,
    )


def test_v2_fixture_literals_match_the_exact_derivation_without_importing_it():
    assignments = _literal_integer_assignments(ACCEPTANCE_FIXTURE_PATH)
    assert _fixture_constants_match(assignments)

    expected_names = (
        "V2_COVERAGE_ROOT_ENTROPY",
        "V2_CALIBRATION_COVERED",
        "V2_CALIBRATION_REPLICATIONS",
        "V2_LOWER_COVERAGE_COUNT",
        "V2_UPPER_COVERAGE_COUNT",
    )
    for name in expected_names:
        mutated = assignments.copy()
        mutated[name] += 1
        assert not _fixture_constants_match(mutated)

    source = ACCEPTANCE_FIXTURE_PATH.read_text(encoding="utf-8")
    assert "def test_preregistered_synthetic_median_coverage_v2_once():" in source
    assert "PHASE5_COVERAGE_V2_RESULT=" in source


def test_v2_fixture_matches_v1_except_registered_seed_bounds_and_label():
    v1_function = _function_node(
        ACCEPTANCE_FIXTURE_PATH,
        "test_preregistered_synthetic_median_coverage_once",
    )
    v2_function = _function_node(
        ACCEPTANCE_FIXTURE_PATH,
        "test_preregistered_synthetic_median_coverage_v2_once",
    )
    v1_normalized = _normalized_coverage_body(v1_function)
    v2_normalized = _normalized_coverage_body(v2_function)
    assert v2_normalized == v1_normalized

    # Required negative case: a one-replication mutation remains visible after
    # permitted seed/bound/label differences are normalized.
    mutated_v2 = copy.deepcopy(v2_function)
    outer_assignment = next(
        node for node in mutated_v2.body
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "outer_count"
        )
    )
    outer_assignment.value = ast.Constant(value=301)
    assert _normalized_coverage_body(mutated_v2) != v1_normalized


def test_v2_derivation_record_contains_the_exact_contract():
    record = ACCEPTANCE_RECORD_PATH.read_text(encoding="utf-8")
    assert record.count(DERIVATION_RECORD_HEADING) == 1
    derivation_record = record.split(DERIVATION_RECORD_HEADING, 1)[1]
    assert _record_contains_contract(derivation_record)

    for old, new in (
        ("K = 2771", "K = 2770"),
        ("K/3000 = 2771/3000", "K/3000 = 2770/3000"),
        ("[268, 286]", "[267, 286]"),
        ("sum(c=0..267)", "sum(c=0..266)"),
        ("sum(c=287..300)", "sum(c=288..300)"),
    ):
        mutated = derivation_record.replace(old, new)
        assert mutated != derivation_record
        assert not _record_contains_contract(mutated)
