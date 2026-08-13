"""Synthetic checkpoint, recovery, duplicate, and failure-accounting witnesses."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from mnq_lab import SpineError
from mnq_lab.phase10.calibration_checkpoint import (
    CalibrationCheckpointStore,
    FailureEvidence,
    assert_complete_replication_inventory,
    classify_failure,
    reconcile_duplicate_attempts,
)
from mnq_lab.phase10.calibration_results import seal_scientific_payload
from tests.test_phase10_calibration_orchestration import _environment
from tests.test_phase10_calibration_results import _payload


def _result(index=7):
    payload = _payload()
    payload = replace(
        payload,
        replication_index=index,
        control_spawn_key=(index, 0),
        ensemble_spawn_key=(index, 1),
    )
    return seal_scientific_payload(payload)


def _assert_commit_order(committer, root: Path):
    phases = []
    store = CalibrationCheckpointStore(
        root,
        _environment(),
        resume=False,
        phase_observer=lambda phase, index: phases.append((phase, index)),
    )
    committer(store, _result())
    assert phases == [
        ("temporary_written", 7),
        ("temporary_validated", 7),
        ("payload_atomically_committed", 7),
        ("checkpoint_transition", 7),
    ]
    recovered = store.recover()
    assert recovered.completed == ((7, _result().scientific_payload_hash),)
    assert len(recovered.unfinished) == 299


def test_payload_is_validated_and_atomically_committed_before_transition(tmp_path):
    _assert_commit_order(
        lambda store, result: store.commit_replication(result),
        tmp_path / "checkpoint",
    )


def test_transition_first_mutant_fails_the_same_order_witness(tmp_path):
    def transition_first(store, result):
        store._write_transition(result)
        store.commit_replication(result)

    with pytest.raises((AssertionError, SpineError)):
        _assert_commit_order(transition_first, tmp_path / "checkpoint-mutant")


def _assert_recovery_reconciles_one_sided_state(mutator, root, should_recover):
    store = CalibrationCheckpointStore(root, _environment(), resume=False)
    mutator(store, _result())
    if should_recover:
        recovered = store.recover()
        assert recovered.completed == ((7, _result().scientific_payload_hash),)
        assert store.transitions.has_chunk(7)
    else:
        with pytest.raises(SpineError):
            store.recover()


def test_recovery_halts_when_transition_or_payload_is_missing(tmp_path):
    def transition_only(store, result):
        store._write_transition(result)

    def payload_only(store, result):
        index = result.scientific_payload.replication_index
        store.payloads.write_stage1_unit(
            store._unit_name(index),
            result,
            declared_indices=(index,),
            declared_identity_sha256=result.scientific_payload_hash,
            row_ids=(f"replication-{index:06d}",),
        )

    _assert_recovery_reconciles_one_sided_state(
        transition_only,
        tmp_path / "transition-only",
        False,
    )
    _assert_recovery_reconciles_one_sided_state(
        payload_only,
        tmp_path / "payload-only",
        True,
    )


def _assert_duplicate_contract(reconciler):
    result = _result()
    state = reconciler((result, result))
    assert state.replication_index == 7
    assert state.attempt_count == 2
    different = seal_scientific_payload(
        replace(result.scientific_payload, attempt_lineage=("attempt-2",))
    )
    try:
        reconciler((result, different))
    except SpineError as exc:
        assert "nondeterminism halts without selection" in str(exc)
    else:
        raise AssertionError("conflicting duplicate attempts were selected")


def test_duplicate_attempts_compare_scientific_hashes_and_halt_on_conflict():
    _assert_duplicate_contract(reconcile_duplicate_attempts)


def test_conflict_selection_mutant_fails_the_same_duplicate_witness():
    def selects_first(attempts):
        first = tuple(attempts)[0]
        return type("State", (), {
            "replication_index": first.scientific_payload.replication_index,
            "attempt_count": len(tuple(attempts)),
        })()

    with pytest.raises(AssertionError):
        _assert_duplicate_contract(selects_first)


def _evidence(event=None, confirmed=False, healthy=True, compatible=True):
    return FailureEvidence(event, confirmed, healthy, compatible)


def _assert_failure_contract(classifier):
    transient = classifier("host_loss", 0, _evidence("host_loss", True))
    assert transient.classification == "transient"
    assert transient.retry_same_replication and not transient.halt_all_work
    assert transient.declared_denominator == 300
    unknown = classifier("unknown", 0, _evidence())
    assert unknown.classification == "structural" and unknown.halt_all_work
    vanished = classifier("vanished_process", 0, _evidence())
    assert vanished.classification == "structural" and vanished.halt_all_work
    first_oom = classifier("oom", 0, _evidence(healthy=True, compatible=True))
    assert first_oom.retry_same_replication and not first_oom.halt_all_work
    repeated_oom = classifier("oom", 1, _evidence(healthy=True, compatible=True))
    assert repeated_oom.classification == "structural" and repeated_oom.halt_all_work


def test_failure_accounting_uses_external_evidence_and_one_retry():
    _assert_failure_contract(classify_failure)


@pytest.mark.parametrize("mutant_kind", ("unknown_transient", "vanished_transient", "two_oom_retries"))
def test_failure_classification_mutants_fail_the_same_witness(mutant_kind):
    def mutant(cause, retries, evidence):
        decision = classify_failure(cause, retries, evidence)
        if mutant_kind == "unknown_transient" and cause == "unknown":
            return replace(decision, classification="transient", retry_same_replication=True, halt_all_work=False)
        if mutant_kind == "vanished_transient" and cause == "vanished_process":
            return replace(decision, classification="transient", retry_same_replication=True, halt_all_work=False)
        if mutant_kind == "two_oom_retries" and cause == "oom" and retries == 1:
            return replace(decision, classification="transient", retry_same_replication=True, halt_all_work=False)
        return decision

    with pytest.raises(AssertionError):
        _assert_failure_contract(mutant)


def _assert_denominator_guard(guard):
    guard(range(300))
    try:
        guard(range(299))
    except SpineError as exc:
        assert "denominator of 300" in str(exc)
    else:
        raise AssertionError("a dropped replication reduced the denominator")


def test_declared_denominator_cannot_shrink():
    _assert_denominator_guard(assert_complete_replication_inventory)


def test_shortened_denominator_mutant_fails_the_same_witness():
    def accepts_short(_indices):
        return None

    with pytest.raises(AssertionError):
        _assert_denominator_guard(accepts_short)
