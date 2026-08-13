"""End-to-end synthetic witnesses for the complete calibration quartet."""

from __future__ import annotations

import ast
from dataclasses import replace
import hashlib
import inspect

import numpy as np
import pytest

from mnq_lab import SpineError
import mnq_lab.phase10.calibration_results as results_module
import mnq_lab.phase10.calibration_science as science_module
from mnq_lab.phase10.adapter import FormalCorpus, FormalJoinReconciliation
from mnq_lab.phase10.calibration_results import (
    CalibrationReplicationResult,
    canonical_scientific_payload_bytes,
)
from mnq_lab.phase10.evaluation import evaluate_primary_surface as _real_evaluate_primary_surface
from mnq_lab.phase10.contract import load_phase10_contract
from mnq_lab.phase8.contrasts import SESSION_PHASES, VOLATILITY_STATES
from tests.test_phase10_calibration_controls import _fixture
from tests.test_phase10_calibration_orchestration import _environment


def _small_contract(monkeypatch, permutation_count):
    contract = replace(load_phase10_contract(), permutations_final=permutation_count)
    monkeypatch.setattr(results_module, "load_phase10_contract", lambda: contract)
    return contract


def _outcome_digest(corpus):
    return hashlib.sha256(corpus.downward_excursion_ticks.tobytes()).hexdigest()


def _assert_exact_member_p_values(values):
    assert tuple(values) == (0.70, 0.05, 0.05, 0.05)


def _assert_every_lattice_cell_is_ok(evaluations):
    statuses = tuple(
        tuple(np.asarray(evaluation.statuses).reshape(-1))
        for evaluation in evaluations
    )
    assert len(statuses) == 4
    assert all(len(member_statuses) == 30 for member_statuses in statuses)
    assert all(
        status == "ok"
        for member_statuses in statuses
        for status in member_statuses
    )


def _assert_payload_statuses_are_ok(members):
    assert tuple(member.structural_statuses for member in members) == (("ok",),) * 4


def _readonly(values, dtype=None):
    result = np.array(values, dtype=dtype, copy=True)
    result.setflags(write=False)
    return result


def _nondegenerate_fixture():
    session_count = 120
    width = 25
    shape = (session_count, width)
    generator = np.random.Generator(np.random.PCG64(7))
    sessions = np.arange(session_count, dtype=np.int32) + 20200101
    quarters = np.repeat(
        np.asarray(("2020Q1", "2020Q2", "2020Q3", "2020Q4")),
        30,
    )
    phases = np.asarray(tuple(SESSION_PHASES[index % 5] for index in range(width)))
    state_codes = generator.integers(
        0,
        len(VOLATILITY_STATES),
        size=shape,
        dtype=np.int8,
    )
    outcomes = generator.integers(0, 401, size=shape, dtype=np.int32)
    reconciliation = FormalJoinReconciliation(
        verified_anchor_rows=session_count * width,
        verified_arm_rows=session_count * width,
        schedule_excluded_sessions=0,
        schedule_excluded_rows=0,
        active_sessions=session_count,
        regular_full_rth_sessions=session_count,
        holiday_adjacent_sessions_removed=0,
        truncated_sessions_removed=0,
        formal_sessions=session_count,
        formal_rows=session_count * width,
        anchors_per_session=width,
    )
    return FormalCorpus(
        session_ids=_readonly(sessions, np.int32),
        calendar_quarters=_readonly(quarters),
        calendar_years=_readonly(np.full(session_count, 2020), np.int32),
        observation_grid=_readonly(tuple(f"anchor-{index:02d}" for index in range(width))),
        phase_grid=_readonly(phases),
        ts_event_ns=_readonly(np.arange(session_count * width).reshape(shape), np.int64),
        state_codes=_readonly(state_codes, np.int8),
        state_valid=_readonly(np.ones(shape), np.bool_),
        downward_excursion_ticks=_readonly(outcomes, np.int32),
        outcome_valid=_readonly(np.ones(shape), np.bool_),
        window_fits_rth=_readonly(np.ones(shape), np.bool_),
        reconciliation=reconciliation,
        metadata={"effective_null_strata": "calendar_quarter_only"},
    )


def _assert_complete_member_specific_science(
    compute,
    evaluate_transform,
    monkeypatch,
    permutation_count,
):
    _small_contract(monkeypatch, permutation_count)
    corpus = _nondegenerate_fixture()
    calls = []
    evaluations = []

    def tracked_evaluate(member_corpus, state_codes, state_valid):
        selected = evaluate_transform(member_corpus, len(calls))
        calls.append(_outcome_digest(selected))
        evaluated = _real_evaluate_primary_surface(selected, state_codes, state_valid)
        evaluations.append(evaluated)
        return evaluated

    monkeypatch.setattr(science_module, "evaluate_primary_surface", tracked_evaluate)
    result = compute(
        corpus,
        0,
        ("synthetic-attempt-0",),
        (),
        _environment(),
        permutation_count,
    )
    assert isinstance(result, CalibrationReplicationResult)
    assert result.scientific_payload.permutations == permutation_count
    assert len(result.scientific_payload.quartet_members) == 4
    _assert_every_lattice_cell_is_ok(evaluations[:4])
    _assert_payload_statuses_are_ok(result.scientific_payload.quartet_members)
    assert len(calls) == 4 * (permutation_count + 1)
    observed_member_outcomes = tuple(calls[:4])
    assert len(set(observed_member_outcomes)) == 4
    for start in range(4, len(calls), 4):
        assert tuple(calls[start : start + 4]) == observed_member_outcomes
    _assert_exact_member_p_values(
        member.p_value for member in result.scientific_payload.quartet_members
    )
    assert canonical_scientific_payload_bytes(result.scientific_payload)
    return result


def test_complete_scientific_quartet_runs_end_to_end_at_small_b(monkeypatch):
    _assert_complete_member_specific_science(
        science_module.compute_calibration_replication,
        lambda corpus, _position: corpus,
        monkeypatch,
        19,
    )


def test_aliased_null_storage_fails_the_same_exact_pvalue_witness():
    with pytest.raises(AssertionError):
        _assert_exact_member_p_values((0.75, 0.05, 0.05, 0.05))


@pytest.mark.parametrize(
    "statuses",
    (("ok",) * 29, ("ok",) * 29 + ("insufficient_anchors",)),
)
def test_invalid_lattice_statuses_fail_the_same_all_ok_witness(statuses):
    incomplete = type("Incomplete", (), {"statuses": np.asarray(statuses)})()
    with pytest.raises(AssertionError):
        _assert_every_lattice_cell_is_ok((incomplete,) * 4)


def test_invalid_payload_status_fails_the_same_payload_status_witness():
    invalid = type("Invalid", (), {"structural_statuses": ("insufficient_anchors",)})()
    with pytest.raises(AssertionError):
        _assert_payload_statuses_are_ok((invalid,) * 4)


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
        function(corpus, 0, ("attempt",), (), _environment())


def test_science_permutation_count_is_explicit_with_no_default():
    _assert_required_permutation_coordinate(science_module.compute_calibration_replication)


def test_defaulted_permutation_count_fails_the_same_signature_witness():
    def defaulted(
        corpus,
        replication_index,
        attempt_lineage,
        classified_failures,
        environment,
        permutation_count=19,
    ):
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
                (),
                _environment(),
                invalid,
            )
