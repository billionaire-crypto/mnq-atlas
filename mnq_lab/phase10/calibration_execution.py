"""Authorized 300-index process runner; importing it performs no work."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import importlib.metadata
import multiprocessing
import os
from pathlib import Path
import platform
import subprocess
from typing import Any

import numpy as np

from mnq_lab import SpineError
from mnq_lab.phase8.artifacts import canonical_json_bytes
from mnq_lab.phase10.adapter import FormalCorpus
from mnq_lab.phase10.calibration_checkpoint import (
    CalibrationCheckpointStore,
    assert_complete_replication_inventory,
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
class CalibrationEvidenceRequest:
    corpus: FormalCorpus
    corpus_identity: CorpusExecutionIdentity
    expected_environment: WorkerEnvironmentIdentity
    checkpoint_root: Path
    resume: bool
    attempt_label: str

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
    attempt_label: str,
) -> CalibrationReplicationResult:
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
            (attempt_label,),
            observed,
        ),
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
    recovery = checkpoint.recover()
    pending = recovery.unfinished
    if request.expected_environment.worker_count == 1:
        for index in pending:
            result = _compute_verified(
                request.corpus,
                request.corpus_identity,
                request.expected_environment,
                index,
                request.attempt_label,
            )
            validate_scientific_payload(result.scientific_payload)
            checkpoint.commit_replication(result)
    else:
        context = multiprocessing.get_context(
            request.expected_environment.process_start_method
        )
        with ProcessPoolExecutor(
            max_workers=request.expected_environment.worker_count,
            mp_context=context,
        ) as executor:
            futures = {
                executor.submit(
                    _compute_verified,
                    request.corpus,
                    request.corpus_identity,
                    request.expected_environment,
                    index,
                    request.attempt_label,
                ): index
                for index in pending
            }
            for future in as_completed(futures):
                index = futures[future]
                result = future.result()
                if result.scientific_payload.replication_index != index:
                    raise SpineError("worker result differs from its assigned replication index")
                validate_scientific_payload(result.scientific_payload)
                checkpoint.commit_replication(result)
    final = checkpoint.recover()
    assert_complete_replication_inventory(index for index, _ in final.completed)
    return CalibrationRunCompletion(final.completed, CALIBRATION_REPLICATIONS)
