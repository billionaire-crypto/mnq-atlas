"""Behavioural synthetic tests for execution, recovery, and scientific ordering."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from mnq_lab import SpineError
from mnq_lab.phase10.calibration_checkpoint import (
    AttemptRecord,
    CalibrationCheckpointStore,
    ExternalFailureRecord,
    FailureEvidence,
)
import mnq_lab.phase10.calibration_execution as execution_module
from mnq_lab.phase10.calibration_execution import CorpusExecutionIdentity
from mnq_lab.phase10.calibration_results import (
    canonical_scientific_payload_bytes,
    seal_scientific_payload,
)
import mnq_lab.phase10.calibration_results as results_module
from mnq_lab.phase10.contract import load_phase10_contract
from tests.test_phase10_calibration_checkpoint import _result
from tests.test_phase10_calibration_controls import _fixture
from tests.test_phase10_calibration_orchestration import _environment

_production_compute_verified = execution_module._compute_verified


def _synthetic_compute_verified(
    corpus,
    corpus_identity,
    expected,
    index,
    attempt_lineage,
    classified_failures,
    permutation_count,
):
    contract = replace(load_phase10_contract(), permutations_final=permutation_count)
    original = results_module.load_phase10_contract
    results_module.load_phase10_contract = lambda: contract
    try:
        return _production_compute_verified(
            corpus,
            corpus_identity,
            expected,
            index,
            attempt_lineage,
            classified_failures,
            permutation_count,
        )
    finally:
        results_module.load_phase10_contract = original


def _identity():
    environment = replace(_environment(), worker_count=2)
    corpus_identity = CorpusExecutionIdentity(
        environment.corpus_manifest_sha256,
        environment.corpus_column_sha256,
    )
    return environment, corpus_identity


def _request(corpus, environment, corpus_identity):
    return SimpleNamespace(
        corpus=corpus,
        corpus_identity=corpus_identity,
        expected_environment=environment,
        failure_evidence_resolver=lambda _context: None,
        attempt_label="synthetic-science",
    )


def _bind_small_execution(monkeypatch, permutation_count):
    _, corpus_identity = _identity()
    contract = replace(load_phase10_contract(), permutations_final=permutation_count)
    monkeypatch.setattr(results_module, "load_phase10_contract", lambda: contract)
    monkeypatch.setattr(
        execution_module,
        "_compute_verified",
        _synthetic_compute_verified,
    )
    environment = execution_module.capture_worker_environment(
        corpus_identity,
        2,
        "spawn",
    )
    return environment, corpus_identity


def _execute_variant(
    root: Path,
    corpus,
    environment,
    corpus_identity,
    steps,
    permutation_count,
):
    request = _request(corpus, environment, corpus_identity)
    for position, (indices, worker_count) in enumerate(steps):
        checkpoint = CalibrationCheckpointStore(
            root,
            environment,
            resume=position > 0,
        )
        execution_module._execute_calibration_indices(
            request,
            checkpoint,
            indices,
            permutation_count,
            worker_count,
        )
    checkpoint = CalibrationCheckpointStore(root, environment, resume=True)
    return tuple(
        canonical_scientific_payload_bytes(
            checkpoint.completed_result(index).scientific_payload
        )
        for index in (0, 1)
    )


def _assert_four_way_scientific_bytes(variant_builder, tmp_path):
    variants = variant_builder(tmp_path)
    assert len(variants) == 4
    assert variants[0] == variants[1] == variants[2] == variants[3]
    assert len(variants[0]) == 2
    return variants[0]


def test_serial_parallel_interrupted_and_resumed_scientific_bytes_match(
    monkeypatch,
    tmp_path,
):
    environment, corpus_identity = _bind_small_execution(monkeypatch, 2)
    corpus, _ = _fixture()

    def build(root):
        return (
            _execute_variant(
                root / "serial",
                corpus,
                environment,
                corpus_identity,
                (((0, 1), 1),),
                2,
            ),
            _execute_variant(
                root / "parallel",
                corpus,
                environment,
                corpus_identity,
                (((0, 1), 2),),
                2,
            ),
            _execute_variant(
                root / "interrupted-resumed",
                corpus,
                environment,
                corpus_identity,
                (((0,), 1), ((1,), 2)),
                2,
            ),
            _execute_variant(
                root / "replay",
                corpus,
                environment,
                corpus_identity,
                (((1, 0), 1),),
                2,
            ),
        )

    _assert_four_way_scientific_bytes(build, tmp_path)


def test_changed_resumed_science_fails_the_same_four_way_witness(tmp_path):
    def changed(_root):
        base = ((b"zero", b"one"),) * 4
        return (*base[:3], (b"changed", b"one"))

    with pytest.raises(AssertionError):
        _assert_four_way_scientific_bytes(changed, tmp_path)


def _assert_environment_observation_is_bound(compute_verified, monkeypatch):
    expected, corpus_identity = _identity()
    observed = replace(expected, cpu_identity="different-cpu")
    scientific_calls = []
    monkeypatch.setattr(
        execution_module,
        "capture_worker_environment",
        lambda *_args, **_kwargs: observed,
    )
    monkeypatch.setattr(
        execution_module,
        "compute_calibration_replication",
        lambda *_args, **_kwargs: scientific_calls.append("called"),
    )
    corpus, _ = _fixture()
    try:
        compute_verified(
            corpus,
            corpus_identity,
            expected,
            0,
            ("attempt",),
            (),
            2,
        )
    except SpineError as exc:
        assert "cpu_identity" in str(exc)
    else:
        raise AssertionError("observed worker environment was not verified")
    assert scientific_calls == []


def test_worker_observation_is_verified_before_science(monkeypatch):
    _assert_environment_observation_is_bound(execution_module._compute_verified, monkeypatch)


def test_expected_as_observed_mutant_fails_the_same_environment_witness(monkeypatch):
    def no_op_environment(
        corpus,
        corpus_identity,
        expected,
        index,
        attempt_lineage,
        classified_failures,
        permutation_count,
    ):
        execution_module.capture_worker_environment(corpus_identity, 2, "spawn")
        return execution_module.run_after_environment_verification(
            expected,
            expected,
            lambda: execution_module.compute_calibration_replication(
                corpus,
                index,
                attempt_lineage,
                classified_failures,
                expected,
                permutation_count,
            ),
        )

    with pytest.raises(AssertionError):
        _assert_environment_observation_is_bound(no_op_environment, monkeypatch)


class _AcceptanceCheckpoint:
    def __init__(self, existing=None):
        self.existing = existing
        self.trace = []

    def completed_result(self, _index):
        return self.existing

    def commit_replication(self, _result_value):
        self.trace.append("committed")


def _assert_validation_precedes_commit(acceptor, monkeypatch):
    result = _result()
    attempt = AttemptRecord(
        result.scientific_payload.replication_index,
        0,
        result.scientific_payload.attempt_lineage,
        result.scientific_payload.classified_failures,
    )
    checkpoint = _AcceptanceCheckpoint()
    real_validate = results_module.validate_scientific_payload

    def tracked_validate(payload):
        checkpoint.trace.append("validated")
        return real_validate(payload)

    monkeypatch.setattr(execution_module, "validate_scientific_payload", tracked_validate)
    acceptor(attempt.replication_index, attempt, result, checkpoint, 4999)
    assert checkpoint.trace == ["validated", "committed"]


def test_payload_is_validated_before_execution_commits(monkeypatch):
    _assert_validation_precedes_commit(execution_module._accept_worker_result, monkeypatch)


def test_skipped_payload_validation_fails_the_same_order_witness(monkeypatch):
    def skipped(_assigned, _attempt, result, checkpoint, _permutation_count):
        checkpoint.commit_replication(result)

    with pytest.raises(AssertionError):
        _assert_validation_precedes_commit(skipped, monkeypatch)


def _assert_parallel_index_agreement(acceptor):
    result = _result(7)
    attempt = AttemptRecord(
        7,
        0,
        result.scientific_payload.attempt_lineage,
        result.scientific_payload.classified_failures,
    )
    try:
        acceptor(8, attempt, result, _AcceptanceCheckpoint(), 4999)
    except SpineError as exc:
        assert "assigned replication index" in str(exc)
    else:
        raise AssertionError("wrong-index worker result was accepted")


def test_worker_result_must_match_assigned_parallel_index():
    _assert_parallel_index_agreement(execution_module._accept_worker_result)


def test_missing_parallel_index_check_fails_the_same_witness():
    def unchecked(_assigned, _attempt, result, checkpoint, _permutation_count):
        results_module.validate_scientific_payload(result.scientific_payload)
        checkpoint.commit_replication(result)

    with pytest.raises(AssertionError):
        _assert_parallel_index_agreement(unchecked)


def _assert_duplicate_reconciliation(acceptor, monkeypatch):
    result = _result()
    attempt = AttemptRecord(
        result.scientific_payload.replication_index,
        0,
        result.scientific_payload.attempt_lineage,
        result.scientific_payload.classified_failures,
    )
    calls = []
    monkeypatch.setattr(
        execution_module,
        "reconcile_duplicate_attempts",
        lambda values: calls.append(tuple(values)),
    )
    checkpoint = _AcceptanceCheckpoint(existing=result)
    acceptor(attempt.replication_index, attempt, result, checkpoint, 4999)
    assert calls == [(result, result)]
    assert checkpoint.trace == []


def test_existing_completed_attempt_reaches_duplicate_reconciliation(monkeypatch):
    _assert_duplicate_reconciliation(execution_module._accept_worker_result, monkeypatch)


def test_ignored_duplicate_fails_the_same_reconciliation_witness(monkeypatch):
    def ignored(_assigned, _attempt, _result_value, _checkpoint, _permutation_count):
        return None

    with pytest.raises(AssertionError):
        _assert_duplicate_reconciliation(ignored, monkeypatch)


def _assert_absent_recovery_evidence_halts(initializer, tmp_path):
    environment, _ = _identity()
    checkpoint = CalibrationCheckpointStore(
        tmp_path / "absent-evidence",
        environment,
        resume=False,
    )
    checkpoint.start_attempt(7, "vanished")
    with pytest.raises(SpineError, match="failed structurally"):
        initializer(checkpoint, (7,), lambda _context: None, "vanished")
    state = checkpoint.recover()
    assert state.never_started.count(7) == 0
    assert len(state.attempted) == 1
    assert state.attempted[0].failure is not None
    assert state.attempted[0].failure.decision.classification == "structural"
    assert len(checkpoint.attempt_records(7)) == 1


def test_attempted_recovery_without_external_evidence_halts(tmp_path):
    _assert_absent_recovery_evidence_halts(execution_module._initial_attempts, tmp_path)


def test_auto_retry_attempted_mutant_fails_the_same_recovery_witness(tmp_path):
    def auto_retry(checkpoint, indices, _resolver, label):
        return tuple(checkpoint.start_attempt(index, label) for index in indices)

    with pytest.raises((AssertionError, SpineError)):
        _assert_absent_recovery_evidence_halts(auto_retry, tmp_path)


def test_external_transient_record_retries_same_index_and_populates_lineage(tmp_path):
    environment, _ = _identity()
    checkpoint = CalibrationCheckpointStore(
        tmp_path / "external-transient",
        environment,
        resume=False,
    )
    checkpoint.start_attempt(7, "retry")
    external = ExternalFailureRecord(
        "host_loss",
        FailureEvidence("host_loss", True, True, True),
    )
    attempts = execution_module._initial_attempts(
        checkpoint,
        (7,),
        lambda _context: external,
        "retry",
    )
    assert tuple(item.replication_index for item in attempts) == (7,)
    assert attempts[0].attempt_number == 1
    assert attempts[0].classified_failures == ("attempt-0:host_loss:transient",)


def test_live_transient_failure_is_classified_and_retried_once(monkeypatch, tmp_path):
    environment, corpus_identity = _identity()
    corpus, _ = _fixture()
    checkpoint = CalibrationCheckpointStore(
        tmp_path / "live-retry",
        environment,
        resume=False,
    )
    calls = []

    def fail_then_complete(
        _corpus,
        _identity_value,
        _expected,
        index,
        attempt_lineage,
        classified_failures,
        _permutations,
    ):
        calls.append((index, attempt_lineage, classified_failures))
        if len(calls) == 1:
            raise RuntimeError("externally confirmed host loss")
        base = _result(index).scientific_payload
        return seal_scientific_payload(
            replace(
                base,
                attempt_lineage=attempt_lineage,
                classified_failures=classified_failures,
                quartet_members=tuple(
                    replace(member, classified_failures=classified_failures)
                    for member in base.quartet_members
                ),
            )
        )

    monkeypatch.setattr(execution_module, "_compute_verified", fail_then_complete)
    request = _request(corpus, environment, corpus_identity)
    request.failure_evidence_resolver = lambda _context: ExternalFailureRecord(
        "host_loss",
        FailureEvidence("host_loss", True, True, True),
    )
    execution_module._execute_calibration_indices(request, checkpoint, (7,), 4999, 1)
    assert len(calls) == 2
    assert calls[0][0] == calls[1][0] == 7
    assert calls[1][2] == ("attempt-0:host_loss:transient",)
    assert checkpoint.completed_result(7) is not None
