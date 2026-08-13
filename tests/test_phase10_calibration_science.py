"""End-to-end synthetic witnesses for the complete calibration quartet."""

from __future__ import annotations

import ast
from dataclasses import replace
import hashlib
import inspect

import pytest

from mnq_lab import SpineError
import mnq_lab.phase10.calibration_results as results_module
import mnq_lab.phase10.calibration_science as science_module
from mnq_lab.phase10.calibration_results import (
    CalibrationReplicationResult,
    canonical_scientific_payload_bytes,
)
from mnq_lab.phase10.contract import load_phase10_contract
from mnq_lab.phase10.evaluation import evaluate_primary_surface as _real_evaluate_primary_surface
from tests.test_phase10_calibration_controls import _fixture
from tests.test_phase10_calibration_orchestration import _environment


def _small_contract(monkeypatch, permutation_count):
    contract = replace(load_phase10_contract(), permutations_final=permutation_count)
    monkeypatch.setattr(results_module, "load_phase10_contract", lambda: contract)
    return contract


def _outcome_digest(corpus):
    return hashlib.sha256(corpus.downward_excursion_ticks.tobytes()).hexdigest()


def _assert_complete_member_specific_science(
    compute,
    evaluate_transform,
    monkeypatch,
    permutation_count,
):
    _small_contract(monkeypatch, permutation_count)
    corpus, _ = _fixture()
    calls = []

    def tracked_evaluate(member_corpus, state_codes, state_valid):
        selected = evaluate_transform(member_corpus, len(calls))
        calls.append(_outcome_digest(selected))
        return _real_evaluate_primary_surface(selected, state_codes, state_valid)

    monkeypatch.setattr(science_module, "evaluate_primary_surface", tracked_evaluate)
    result = compute(
        corpus,
        0,
        ("synthetic-attempt-0",),
        _environment(),
        permutation_count,
    )
    assert isinstance(result, CalibrationReplicationResult)
    assert result.scientific_payload.permutations == permutation_count
    assert len(result.scientific_payload.quartet_members) == 4
    assert len(calls) == 4 * (permutation_count + 1)
    observed_member_outcomes = tuple(calls[:4])
    assert len(set(observed_member_outcomes)) == 4
    for start in range(4, len(calls), 4):
        assert tuple(calls[start : start + 4]) == observed_member_outcomes
    assert canonical_scientific_payload_bytes(result.scientific_payload)
    return result


def test_complete_scientific_quartet_runs_end_to_end_at_small_b(monkeypatch):
    _assert_complete_member_specific_science(
        science_module.compute_calibration_replication,
        lambda corpus, _position: corpus,
        monkeypatch,
        19,
    )


def test_unplanted_null_member_corpora_fail_the_same_end_to_end_witness(monkeypatch):
    observed = []

    def unplanted_after_observed(member_corpus, position):
        if position < 4:
            observed.append(member_corpus)
            return member_corpus
        return observed[0]

    with pytest.raises(AssertionError):
        _assert_complete_member_specific_science(
            science_module.compute_calibration_replication,
            unplanted_after_observed,
            monkeypatch,
            2,
        )


def _assert_required_permutation_coordinate(function):
    parameter = inspect.signature(function).parameters["permutation_count"]
    assert parameter.default is inspect.Parameter.empty
    corpus, _ = _fixture()
    with pytest.raises(TypeError):
        function(corpus, 0, ("attempt",), _environment())


def test_science_permutation_count_is_explicit_with_no_default():
    _assert_required_permutation_coordinate(science_module.compute_calibration_replication)


def test_defaulted_permutation_count_fails_the_same_signature_witness():
    def defaulted(corpus, replication_index, attempt_lineage, environment, permutation_count=19):
        return None

    with pytest.raises(AssertionError):
        _assert_required_permutation_coordinate(defaulted)


def _assert_no_quartet_pvalue_reduction(source):
    tree = ast.parse(source)
    forbidden = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else None
        attribute = node.func.attr if isinstance(node.func, ast.Attribute) else None
        if name == "min" or attribute in {"min", "minimum"}:
            text = ast.unparse(node).casefold()
            if "p_value" in text or "members" in text:
                forbidden.append(text)
    assert forbidden == []


def test_scientific_quartet_contains_no_cross_member_pvalue_reduction():
    _assert_no_quartet_pvalue_reduction(
        inspect.getsource(science_module.compute_calibration_replication)
    )


def test_minimum_quartet_pvalue_mutant_fails_the_same_ast_witness():
    source = inspect.getsource(science_module.compute_calibration_replication)
    source = source.replace(
        "    environment_hash =",
        "    minimum_p_value = min(member.p_value for member in members)\n"
        "    environment_hash =",
        1,
    )
    with pytest.raises(AssertionError):
        _assert_no_quartet_pvalue_reduction(source)


def test_invalid_small_b_coordinates_fail_closed(monkeypatch):
    _small_contract(monkeypatch, 19)
    corpus, _ = _fixture()
    for invalid in (True, 0, -1, 1.0):
        with pytest.raises(SpineError, match="positive built-in integer"):
            science_module.compute_calibration_replication(
                corpus,
                0,
                ("attempt",),
                _environment(),
                invalid,
            )
