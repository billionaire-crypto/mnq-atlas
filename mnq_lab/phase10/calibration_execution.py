"""Authorized 300-index process runner; importing it performs no work."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, fields
import hashlib
import importlib.metadata
import multiprocessing
import os
from pathlib import Path
import platform
import subprocess
from typing import Any, Callable

import numpy as np

from mnq_lab import SpineError
from mnq_lab.phase8.artifacts import canonical_json_bytes
from mnq_lab.phase10.adapter import FormalCorpus
from mnq_lab.phase10.calibration_checkpoint import (
    AttemptRecord,
    CalibrationCheckpointStore,
    ExternalFailureRecord,
    FailureDecision,
    FailureEvidence,
    assert_complete_replication_inventory,
    classify_failure,
    reconcile_duplicate_attempts,
)
from mnq_lab.phase10.calibration_controls import CALIBRATION_REPLICATIONS
from mnq_lab.phase10.calibration_entropy import (
    CALIBRATION_ROOT_LABEL,
    CALIBRATION_ROOT_SHA256,
)
from mnq_lab.phase10.calibration_orchestration import (
    WorkerEnvironmentIdentity,
    run_after_environment_verification,
)
from mnq_lab.phase10.calibration_results import (
    CalibrationReplicationResult,
    validate_scientific_payload,
)
from mnq_lab.phase10.calibration_science import compute_calibration_replication
from mnq_lab.phase10.contract import load_phase10_contract

_REPO_ROOT = Path(__file__).resolve().parents[2]
_THREAD_VARIABLES = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "PYTHONHASHSEED",
)


@dataclass(frozen=True)
class CorpusExecutionIdentity:
    manifest_sha256: str
    column_sha256: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class FailureContext:
    replication_index: int
    attempt_number: int
    attempt_lineage: tuple[str, ...]
    exception_type: str | None
    exception_message: str | None
    recovery: bool


FailureEvidenceResolver = Callable[[FailureContext], ExternalFailureRecord | None]


@dataclass(frozen=True)
class CalibrationEvidenceRequest:
    corpus: FormalCorpus
    corpus_identity: CorpusExecutionIdentity
    expected_environment: WorkerEnvironmentIdentity
    checkpoint_root: Path
    resume: bool
    attempt_label: str
    failure_evidence_resolver: FailureEvidenceResolver

    def __post_init__(self) -> None:
        if not isinstance(self.corpus, FormalCorpus):
            raise SpineError("calibration evidence request requires a FormalCorpus")
        if self.corpus.reconciliation.formal_sessions != 900:
            raise SpineError("calibration evidence request requires exactly 900 sessions")
        if not isinstance(self.corpus_identity, CorpusExecutionIdentity):
            raise SpineError("calibration evidence request lacks corpus hashes")
        if not isinstance(self.expected_environment, WorkerEnvironmentIdentity):
            raise SpineError("calibration evidence request lacks worker environment identity")
        if self.expected_environment.formal_session_count != 900:
            raise SpineError("calibration worker reconciliation differs from 900 sessions")
        if self.corpus_identity.manifest_sha256 != self.expected_environment.corpus_manifest_sha256:
            raise SpineError("calibration request corpus manifest identity differs")
        if self.corpus_identity.column_sha256 != self.expected_environment.corpus_column_sha256:
            raise SpineError("calibration request corpus column identities differ")
        if self.expected_environment.calibration_root_label != CALIBRATION_ROOT_LABEL:
            raise SpineError("calibration worker root label differs")
        if self.expected_environment.calibration_root_digest != CALIBRATION_ROOT_SHA256:
            raise SpineError("calibration worker root digest differs")
        if not isinstance(self.resume, bool):
            raise SpineError("calibration resume state must be boolean")
        if not isinstance(self.attempt_label, str) or not self.attempt_label:
            raise SpineError("calibration attempt label is absent")
        if not callable(self.failure_evidence_resolver):
            raise SpineError("calibration request lacks an external failure-evidence resolver")


@dataclass(frozen=True)
class CalibrationRunCompletion:
    payload_hashes: tuple[tuple[int, str], ...]
    declared_denominator: int


def _git_observation() -> tuple[str, bool]:
    try:
        commit = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=_REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ("git", "status", "--porcelain=v1"),
            cwd=_REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SpineError("worker cannot verify repository commit and dirty state") from exc
    if len(commit) != 40:
        raise SpineError("worker repository commit is not a full SHA-1")
    return commit, bool(status.strip())


def _package_lock_sha256() -> str:
    records = sorted(
        f"{distribution.metadata['Name'].casefold()}=={distribution.version}"
        for distribution in importlib.metadata.distributions()
        if distribution.metadata.get("Name")
    )
    return hashlib.sha256(canonical_json_bytes(records)).hexdigest()


def capture_worker_environment(
    corpus_identity: CorpusExecutionIdentity,
    worker_count: int,
    process_start_method: str,
) -> WorkerEnvironmentIdentity:
    if not isinstance(corpus_identity, CorpusExecutionIdentity):
        raise SpineError("worker environment capture requires corpus identities")
    commit, dirty = _git_observation()
    source_hashes = tuple(
        (
            path.relative_to(_REPO_ROOT).as_posix(),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted((_REPO_ROOT / "mnq_lab" / "phase10").glob("*.py"))
    )
    settings = tuple((name, os.environ.get(name, "<unset>")) for name in _THREAD_VARIABLES)
    return WorkerEnvironmentIdentity(
        repository_commit=commit,
        repository_dirty=dirty,
        python_version=platform.python_version(),
        numpy_version=np.__version__,
        package_lock_sha256=_package_lock_sha256(),
        operating_system=platform.system(),
        architecture=platform.machine(),
        cpu_identity=platform.processor() or platform.machine(),
        phase10_source_sha256=source_hashes,
        constants_sha256=hashlib.sha256(
            (_REPO_ROOT / "analysis_constants_v1.yaml").read_bytes()
        ).hexdigest(),
        corpus_manifest_sha256=corpus_identity.manifest_sha256,
        corpus_column_sha256=corpus_identity.column_sha256,
        formal_session_count=900,
        worker_count=worker_count,
        process_start_method=process_start_method,
        process_thread_settings=settings,
        calibration_root_label=CALIBRATION_ROOT_LABEL,
        calibration_root_digest=CALIBRATION_ROOT_SHA256,
    )


def _compute_verified(
    corpus: FormalCorpus,
    corpus_identity: CorpusExecutionIdentity,
    expected: WorkerEnvironmentIdentity,
    index: int,
    attempt_lineage: tuple[str, ...],
    classified_failures: tuple[str, ...],
    permutation_count: int,
) -> CalibrationReplicationResult:
    for field in fields(FormalCorpus):
        value = getattr(corpus, field.name)
        if isinstance(value, np.ndarray):
            value.setflags(write=False)
    observed = capture_worker_environment(
        corpus_identity,
        expected.worker_count,
        expected.process_start_method,
    )
    return run_after_environment_verification(
        expected,
        observed,
        lambda: compute_calibration_replication(
            corpus,
            index,
            attempt_lineage,
            classified_failures,
            observed,
            permutation_count,
        ),
    )


def _frozen_permutation_count() -> int:
    return load_phase10_contract().permutations_final


def _resolve_failure(
    checkpoint: CalibrationCheckpointStore,
    attempt: AttemptRecord,
    resolver: FailureEvidenceResolver,
    exception: Exception | None,
    *,
    recovery: bool,
) -> FailureDecision:
    context = FailureContext(
        attempt.replication_index,
        attempt.attempt_number,
        attempt.attempt_lineage,
        None if exception is None else type(exception).__name__,
        None if exception is None else str(exception),
        recovery,
    )
    try:
        external = resolver(context)
    except Exception as exc:
        raise SpineError("external failure-evidence resolver failed") from exc
    if external is None:
        external = ExternalFailureRecord(
            "unknown",
            FailureEvidence(None, False, False, False),
        )
    if not isinstance(external, ExternalFailureRecord):
        raise SpineError("external failure-evidence resolver returned an invalid record")
    prior = checkpoint.prior_same_cause_retries(
        attempt.replication_index,
        external.cause,
    )
    decision = classify_failure(external.cause, prior, external.evidence)
    checkpoint.record_failure(attempt, external, decision)
    return decision


def _require_retry_authorization(
    checkpoint: CalibrationCheckpointStore,
    attempt: AttemptRecord,
    resolver: FailureEvidenceResolver,
    exception: Exception | None,
    *,
    recovery: bool,
) -> None:
    persisted = checkpoint.failure_for_attempt(attempt)
    decision = (
        persisted.decision
        if persisted is not None
        else _resolve_failure(
            checkpoint,
            attempt,
            resolver,
            exception,
            recovery=recovery,
        )
    )
    if decision.halt_all_work or not decision.retry_same_replication:
        raise SpineError(
            f"calibration replication {attempt.replication_index} failed structurally"
        ) from exception


def _retry_or_halt(
    checkpoint: CalibrationCheckpointStore,
    attempt: AttemptRecord,
    resolver: FailureEvidenceResolver,
    exception: Exception | None,
    *,
    recovery: bool,
    attempt_label: str,
) -> AttemptRecord:
    _require_retry_authorization(
        checkpoint,
        attempt,
        resolver,
        exception,
        recovery=recovery,
    )
    return checkpoint.start_attempt(attempt.replication_index, attempt_label)


def _accept_worker_result(
    assigned_index: int,
    attempt: AttemptRecord,
    result: CalibrationReplicationResult,
    checkpoint: CalibrationCheckpointStore,
    permutation_count: int,
) -> None:
    if result.scientific_payload.replication_index != assigned_index:
        raise SpineError("worker result differs from its assigned replication index")
    validate_scientific_payload(result.scientific_payload)
    if result.scientific_payload.permutations != permutation_count:
        raise SpineError("worker result permutation count differs from its assignment")
    if result.scientific_payload.attempt_lineage != attempt.attempt_lineage:
        raise SpineError("worker result attempt lineage differs from checkpoint")
    if result.scientific_payload.classified_failures != attempt.classified_failures:
        raise SpineError("worker result failure lineage differs from checkpoint")
    existing = checkpoint.completed_result(assigned_index)
    if existing is not None:
        reconcile_duplicate_attempts((existing, result))
        return
    checkpoint.commit_replication(result)


def _initial_attempts(
    checkpoint: CalibrationCheckpointStore,
    indices: tuple[int, ...],
    resolver: FailureEvidenceResolver,
    attempt_label: str,
) -> tuple[int, ...]:
    if not isinstance(attempt_label, str) or not attempt_label:
        raise SpineError("calibration attempt label is absent")
    recovery = checkpoint.recover()
    completed = {index for index, _ in recovery.completed}
    never_started = set(recovery.never_started)
    attempted = {
        item.attempt.replication_index: item
        for item in recovery.attempted
    }
    result: list[int] = []
    for index in indices:
        if index in completed:
            continue
        if index in never_started:
            result.append(index)
            continue
        if index in attempted:
            item = attempted[index]
            _require_retry_authorization(
                checkpoint,
                item.attempt,
                resolver,
                None,
                recovery=True,
            )
            result.append(index)
            continue
        raise SpineError("checkpoint recovery omitted a declared replication")
    return tuple(result)


def _execute_calibration_indices(
    request: CalibrationEvidenceRequest,
    checkpoint: CalibrationCheckpointStore,
    indices: tuple[int, ...],
    permutation_count: int,
    worker_count: int,
) -> None:
    authorized_indices = _initial_attempts(
        checkpoint,
        indices,
        request.failure_evidence_resolver,
        request.attempt_label,
    )
    if isinstance(worker_count, bool) or not isinstance(worker_count, int) or worker_count <= 0:
        raise SpineError("calibration execution worker count must be positive")
    if worker_count == 1:
        for index in authorized_indices:
            attempt = checkpoint.start_attempt(index, request.attempt_label)
            while True:
                try:
                    result = _compute_verified(
                        request.corpus,
                        request.corpus_identity,
                        request.expected_environment,
                        attempt.replication_index,
                        attempt.attempt_lineage,
                        attempt.classified_failures,
                        permutation_count,
                    )
                except Exception as exc:
                    attempt = _retry_or_halt(
                        checkpoint,
                        attempt,
                        request.failure_evidence_resolver,
                        exc,
                        recovery=False,
                        attempt_label=request.attempt_label,
                    )
                    continue
                _accept_worker_result(
                    attempt.replication_index,
                    attempt,
                    result,
                    checkpoint,
                    permutation_count,
                )
                break
        return

    context = multiprocessing.get_context(
        request.expected_environment.process_start_method
    )
    with ProcessPoolExecutor(
        max_workers=worker_count,
        mp_context=context,
    ) as executor:
        futures = {}
        for index in authorized_indices:
            attempt = checkpoint.start_attempt(index, request.attempt_label)
            futures[
                executor.submit(
                    _compute_verified,
                    request.corpus,
                    request.corpus_identity,
                    request.expected_environment,
                    attempt.replication_index,
                    attempt.attempt_lineage,
                    attempt.classified_failures,
                    permutation_count,
                )
            ] = attempt
        while futures:
            future = next(as_completed(futures))
            attempt = futures.pop(future)
            try:
                result = future.result()
            except Exception as exc:
                retry = _retry_or_halt(
                    checkpoint,
                    attempt,
                    request.failure_evidence_resolver,
                    exc,
                    recovery=False,
                    attempt_label=request.attempt_label,
                )
                futures[
                    executor.submit(
                        _compute_verified,
                        request.corpus,
                        request.corpus_identity,
                        request.expected_environment,
                        retry.replication_index,
                        retry.attempt_lineage,
                        retry.classified_failures,
                        permutation_count,
                    )
                ] = retry
                continue
            _accept_worker_result(
                attempt.replication_index,
                attempt,
                result,
                checkpoint,
                permutation_count,
            )


def execute_calibration_request(
    request: CalibrationEvidenceRequest,
) -> CalibrationRunCompletion:
    if not isinstance(request, CalibrationEvidenceRequest):
        raise SpineError("authorized calibration execution requires a frozen request")
    checkpoint = CalibrationCheckpointStore(
        request.checkpoint_root,
        request.expected_environment,
        resume=request.resume,
    )
    permutation_count = _frozen_permutation_count()
    if permutation_count != load_phase10_contract().permutations_final:
        raise SpineError("authorized evidence path cannot override frozen permutations")
    if request.expected_environment.worker_count <= 0:
        raise SpineError("authorized evidence worker count differs")
    _execute_calibration_indices(
        request,
        checkpoint,
        tuple(range(CALIBRATION_REPLICATIONS)),
        permutation_count,
        request.expected_environment.worker_count,
    )
    final = checkpoint.recover()
    assert_complete_replication_inventory(index for index, _ in final.completed)
    return CalibrationRunCompletion(final.completed, CALIBRATION_REPLICATIONS)
