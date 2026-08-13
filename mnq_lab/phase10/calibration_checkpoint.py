"""Atomic Phase 10 replication persistence and fail-closed failure accounting."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Callable

import numpy as np

from mnq_lab import SpineError
from mnq_lab.phase8.artifacts import CheckpointIdentity, CheckpointStore, canonical_json_bytes
from mnq_lab.phase8.runner import validate_external_checkpoint_root
from mnq_lab.phase10.calibration_controls import CALIBRATION_REPLICATIONS
from mnq_lab.phase10.calibration_results import (
    CalibrationReplicationResult,
    canonical_scientific_payload_bytes,
    scientific_payload_hash,
    validate_scientific_payload,
)
from mnq_lab.phase10.calibration_orchestration import WorkerEnvironmentIdentity

CALIBRATION_CHECKPOINT_VERSION = "phase10-calibration-checkpoint-v1"
_TRANSIENT_EXTERNAL_EVENTS = (
    "host_loss",
    "spot_reclaim",
    "infrastructure_termination",
)
_STRUCTURAL_CAUSES = (
    "engine_exception",
    "invalid_value",
    "failed_invariant",
    "structural_status",
    "corpus_hash_mismatch",
    "code_hash_mismatch",
    "payload_hash_mismatch",
    "checkpoint_inconsistency",
)


@dataclass(frozen=True)
class FailureEvidence:
    external_event: str | None
    externally_confirmed: bool
    healthy_host: bool
    environment_compatible: bool


@dataclass(frozen=True)
class FailureDecision:
    classification: str
    retry_same_replication: bool
    halt_all_work: bool
    declared_denominator: int


@dataclass(frozen=True)
class ExternalFailureRecord:
    cause: str
    evidence: FailureEvidence


@dataclass(frozen=True)
class AttemptRecord:
    replication_index: int
    attempt_number: int
    attempt_lineage: tuple[str, ...]
    classified_failures: tuple[str, ...]


@dataclass(frozen=True)
class PersistedFailure:
    replication_index: int
    attempt_number: int
    cause: str
    prior_same_cause_retries: int
    evidence: FailureEvidence
    decision: FailureDecision


@dataclass(frozen=True)
class AttemptedReplication:
    attempt: AttemptRecord
    failure: PersistedFailure | None


@dataclass(frozen=True)
class RecoveryState:
    completed: tuple[tuple[int, str], ...]
    never_started: tuple[int, ...]
    attempted: tuple[AttemptedReplication, ...]


@dataclass(frozen=True)
class DuplicateAttemptState:
    replication_index: int
    scientific_payload_hash: str
    attempt_count: int


def checkpoint_identity_from_environment(
    environment: WorkerEnvironmentIdentity,
) -> CheckpointIdentity:
    if not isinstance(environment, WorkerEnvironmentIdentity):
        raise SpineError("calibration checkpoint requires a complete worker identity")
    input_hashes = (
        ("analysis_constants_v1.yaml", environment.constants_sha256),
        ("corpus_manifest", environment.corpus_manifest_sha256),
        *environment.corpus_column_sha256,
    )
    contract_hash = hashlib.sha256(
        canonical_json_bytes(
            {
                "calibration_root_digest": environment.calibration_root_digest,
                "calibration_root_label": environment.calibration_root_label,
                "formal_session_count": environment.formal_session_count,
            }
        )
    ).hexdigest()
    return CheckpointIdentity(
        code_commit=environment.repository_commit,
        input_manifest_sha256=tuple(input_hashes),
        stage1_workers=environment.worker_count,
        bootstrap_workers=environment.worker_count,
        process_start_method=environment.process_start_method,
        bootstrap_contract_sha256=contract_hash,
        phase8_output_version=CALIBRATION_CHECKPOINT_VERSION,
        producing_code_sha256=environment.phase10_source_sha256,
    )


def classify_failure(
    cause: str,
    prior_same_cause_retries: int,
    evidence: FailureEvidence,
) -> FailureDecision:
    if not isinstance(cause, str) or not cause:
        raise SpineError("failure cause must be one nonempty classification")
    if (
        isinstance(prior_same_cause_retries, bool)
        or not isinstance(prior_same_cause_retries, int)
        or prior_same_cause_retries < 0
    ):
        raise SpineError("failure retry count is invalid")
    if not isinstance(evidence, FailureEvidence):
        raise SpineError("failure classification requires external evidence")
    externally_transient = (
        evidence.externally_confirmed
        and evidence.external_event in _TRANSIENT_EXTERNAL_EVENTS
    )
    if cause in {"oom", "timeout"}:
        retry = (
            prior_same_cause_retries == 0
            and evidence.healthy_host
            and evidence.environment_compatible
        )
        return FailureDecision(
            "transient" if retry else "structural",
            retry,
            not retry,
            CALIBRATION_REPLICATIONS,
        )
    if cause == "vanished_process":
        return FailureDecision("structural", False, True, CALIBRATION_REPLICATIONS)
    if externally_transient and cause not in _STRUCTURAL_CAUSES:
        return FailureDecision("transient", True, False, CALIBRATION_REPLICATIONS)
    return FailureDecision("structural", False, True, CALIBRATION_REPLICATIONS)


def assert_complete_replication_inventory(indices: Any) -> None:
    try:
        supplied = tuple(indices)
    except TypeError as exc:
        raise SpineError("replication inventory must be one finite sequence") from exc
    expected = tuple(range(CALIBRATION_REPLICATIONS))
    if len(supplied) != CALIBRATION_REPLICATIONS or set(supplied) != set(expected):
        raise SpineError("partial results cannot reduce the declared denominator of 300")


def reconcile_duplicate_attempts(
    attempts: Any,
) -> DuplicateAttemptState:
    try:
        supplied = tuple(attempts)
    except TypeError as exc:
        raise SpineError("duplicate attempts must be one finite sequence") from exc
    if len(supplied) < 2 or any(
        not isinstance(item, CalibrationReplicationResult) for item in supplied
    ):
        raise SpineError("duplicate reconciliation requires at least two completed attempts")
    indices = {item.scientific_payload.replication_index for item in supplied}
    if len(indices) != 1:
        raise SpineError("duplicate attempts refer to different stream coordinates")
    hashes = {item.scientific_payload_hash for item in supplied}
    canonical = {canonical_scientific_payload_bytes(item.scientific_payload) for item in supplied}
    if len(hashes) != 1 or len(canonical) != 1:
        raise SpineError(
            "duplicate scientific payloads differ; nondeterminism halts without selection"
        )
    return DuplicateAttemptState(indices.pop(), hashes.pop(), len(supplied))


class CalibrationCheckpointStore:
    """Two durable public stores: committed payloads, then completion transitions."""

    def __init__(
        self,
        root: Path,
        environment: WorkerEnvironmentIdentity,
        *,
        resume: bool,
        phase_observer: Callable[[str, int], None] | None = None,
    ) -> None:
        self.root = validate_external_checkpoint_root(Path(root), resume=resume)
        self.environment = environment
        self.identity = checkpoint_identity_from_environment(environment)
        self._phase_observer = phase_observer
        if resume:
            self._assert_no_validation_residue()
        self.payloads = CheckpointStore(self.root / "payloads", self.identity)
        self.transitions = CheckpointStore(self.root / "transitions", self.identity)

    @staticmethod
    def _validated_index(index: Any) -> int:
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or not 0 <= index < CALIBRATION_REPLICATIONS
        ):
            raise SpineError("checkpoint replication index must be in [0,300)")
        return index

    def _numbered_store(
        self,
        prefix: str,
        number: int,
        *,
        create: bool,
    ) -> CheckpointStore | None:
        path = self.root / f"{prefix}-{number:06d}"
        if not path.exists() and not create:
            return None
        return CheckpointStore(path, self.identity)

    def _numbered_store_indices(self, prefix: str) -> tuple[int, ...]:
        result: list[int] = []
        for path in self.root.glob(f"{prefix}-*"):
            suffix = path.name[len(prefix) + 1 :]
            if not path.is_dir() or not suffix.isdigit():
                raise SpineError(f"unexpected {prefix} checkpoint entry")
            result.append(int(suffix))
        return tuple(sorted(result))

    @staticmethod
    def _decode_string_tuple(value: Any, name: str) -> tuple[str, ...]:
        try:
            decoded = json.loads(str(value))
        except (TypeError, ValueError) as exc:
            raise SpineError(f"checkpoint {name} is not canonical JSON") from exc
        if (
            not isinstance(decoded, list)
            or any(not isinstance(item, str) or not item for item in decoded)
        ):
            raise SpineError(f"checkpoint {name} is invalid")
        return tuple(decoded)

    def attempt_records(self, index: int) -> tuple[AttemptRecord, ...]:
        checked = self._validated_index(index)
        records: list[AttemptRecord] = []
        for number in self._numbered_store_indices("attempts"):
            store = self._numbered_store("attempts", number, create=False)
            assert store is not None
            if not store.has_chunk(checked):
                continue
            chunk = store.read_chunk(checked)
            observed_number = int(chunk["attempt_number"][0])
            if observed_number != number or number != len(records):
                raise SpineError("checkpoint attempt lineage is non-contiguous")
            records.append(
                AttemptRecord(
                    checked,
                    number,
                    self._decode_string_tuple(
                        chunk["attempt_lineage_json"][0],
                        "attempt lineage",
                    ),
                    self._decode_string_tuple(
                        chunk["classified_failures_json"][0],
                        "classified failures",
                    ),
                )
            )
        return tuple(records)

    def _read_failure(self, index: int, attempt_number: int) -> PersistedFailure | None:
        store = self._numbered_store("failures", attempt_number, create=False)
        if store is None or not store.has_chunk(index):
            return None
        chunk = store.read_chunk(index)
        evidence = FailureEvidence(
            str(chunk["external_event"][0]) or None,
            bool(chunk["externally_confirmed"][0]),
            bool(chunk["healthy_host"][0]),
            bool(chunk["environment_compatible"][0]),
        )
        cause = str(chunk["cause"][0])
        prior = int(chunk["prior_same_cause_retries"][0])
        decision = classify_failure(cause, prior, evidence)
        recorded = FailureDecision(
            str(chunk["classification"][0]),
            bool(chunk["retry_same_replication"][0]),
            bool(chunk["halt_all_work"][0]),
            int(chunk["declared_denominator"][0]),
        )
        if decision != recorded:
            raise SpineError("persisted failure decision differs from frozen classification")
        return PersistedFailure(index, attempt_number, cause, prior, evidence, decision)

    def failure_for_attempt(self, attempt: AttemptRecord) -> PersistedFailure | None:
        if not isinstance(attempt, AttemptRecord):
            raise SpineError("failure lookup requires one persisted attempt")
        return self._read_failure(attempt.replication_index, attempt.attempt_number)

    def prior_same_cause_retries(self, index: int, cause: str) -> int:
        checked = self._validated_index(index)
        if not isinstance(cause, str) or not cause:
            raise SpineError("failure cause must be one nonempty classification")
        count = 0
        for attempt in self.attempt_records(checked):
            failure = self._read_failure(checked, attempt.attempt_number)
            if (
                failure is not None
                and failure.cause == cause
                and failure.decision.retry_same_replication
            ):
                count += 1
        return count

    @staticmethod
    def _failure_label(failure: PersistedFailure) -> str:
        return (
            f"attempt-{failure.attempt_number}:{failure.cause}:"
            f"{failure.decision.classification}"
        )

    def start_attempt(self, index: int, attempt_label: str) -> AttemptRecord:
        checked = self._validated_index(index)
        if not isinstance(attempt_label, str) or not attempt_label:
            raise SpineError("checkpoint attempt label is absent")
        if self.payloads.has_stage1_unit(self._unit_name(checked)):
            raise SpineError("completed replication cannot start another attempt")
        previous = self.attempt_records(checked)
        classified: tuple[str, ...] = ()
        lineage: tuple[str, ...] = ()
        if previous:
            prior_attempt = previous[-1]
            prior_failure = self._read_failure(checked, prior_attempt.attempt_number)
            if prior_failure is None:
                raise SpineError("attempted replication lacks a classified failure")
            if not prior_failure.decision.retry_same_replication:
                raise SpineError("structural failure cannot start another attempt")
            lineage = prior_attempt.attempt_lineage
            classified = (
                *prior_attempt.classified_failures,
                self._failure_label(prior_failure),
            )
        number = len(previous)
        lineage = (*lineage, f"{attempt_label}:attempt-{number}")
        store = self._numbered_store("attempts", number, create=True)
        assert store is not None
        store.write_chunk(
            checked,
            {
                "replication_index": np.asarray([checked], dtype=np.int32),
                "attempt_number": np.asarray([number], dtype=np.int32),
                "attempt_lineage_json": np.asarray(
                    [canonical_json_bytes(list(lineage)).decode("utf-8")],
                    dtype="U4096",
                ),
                "classified_failures_json": np.asarray(
                    [canonical_json_bytes(list(classified)).decode("utf-8")],
                    dtype="U4096",
                ),
            },
        )
        self._observe("attempt_started", checked)
        return AttemptRecord(checked, number, lineage, classified)

    def record_failure(
        self,
        attempt: AttemptRecord,
        record: ExternalFailureRecord,
        decision: FailureDecision,
    ) -> PersistedFailure:
        if not isinstance(attempt, AttemptRecord) or not isinstance(
            record, ExternalFailureRecord
        ):
            raise SpineError("failure persistence requires one attempt and external record")
        observed_attempts = self.attempt_records(attempt.replication_index)
        if not observed_attempts or observed_attempts[-1] != attempt:
            raise SpineError("failure record does not match the latest attempt")
        if self._read_failure(attempt.replication_index, attempt.attempt_number) is not None:
            raise SpineError("attempt failure is already classified")
        prior = sum(
            self._read_failure(attempt.replication_index, item.attempt_number).cause
            == record.cause
            for item in observed_attempts[:-1]
            if self._read_failure(attempt.replication_index, item.attempt_number) is not None
        )
        expected = classify_failure(record.cause, prior, record.evidence)
        if decision != expected:
            raise SpineError("failure decision differs from frozen classification")
        store = self._numbered_store("failures", attempt.attempt_number, create=True)
        assert store is not None
        store.write_chunk(
            attempt.replication_index,
            {
                "cause": np.asarray([record.cause], dtype="U64"),
                "prior_same_cause_retries": np.asarray([prior], dtype=np.int32),
                "external_event": np.asarray(
                    [record.evidence.external_event or ""], dtype="U64"
                ),
                "externally_confirmed": np.asarray(
                    [record.evidence.externally_confirmed], dtype=np.bool_
                ),
                "healthy_host": np.asarray([record.evidence.healthy_host], dtype=np.bool_),
                "environment_compatible": np.asarray(
                    [record.evidence.environment_compatible], dtype=np.bool_
                ),
                "classification": np.asarray([decision.classification], dtype="U16"),
                "retry_same_replication": np.asarray(
                    [decision.retry_same_replication], dtype=np.bool_
                ),
                "halt_all_work": np.asarray([decision.halt_all_work], dtype=np.bool_),
                "declared_denominator": np.asarray(
                    [decision.declared_denominator], dtype=np.int32
                ),
            },
        )
        return PersistedFailure(
            attempt.replication_index,
            attempt.attempt_number,
            record.cause,
            prior,
            record.evidence,
            decision,
        )

    def _observe(self, phase: str, index: int) -> None:
        if self._phase_observer is not None:
            self._phase_observer(phase, index)

    def _assert_no_validation_residue(self) -> None:
        residue = (
            *self.root.glob(".replication-*.validation"),
            *self.root.glob(".replication-*.validation.identity.staging"),
        )
        if residue:
            raise SpineError("incomplete temporary payload validation evidence exists")

    @staticmethod
    def _unit_name(index: int) -> str:
        return f"partition-{index:06d}"

    def _write_validated_temporary(
        self,
        result: CalibrationReplicationResult,
    ) -> Path:
        index = result.scientific_payload.replication_index
        temporary = self.root / f".replication-{index:06d}.validation"
        if temporary.exists():
            raise SpineError("temporary payload validation location already exists")
        store = CheckpointStore(temporary, self.identity)
        name = self._unit_name(index)
        store.write_stage1_unit(
            name,
            result,
            declared_indices=(index,),
            declared_identity_sha256=result.scientific_payload_hash,
            row_ids=(f"replication-{index:06d}",),
        )
        self._observe("temporary_written", index)
        restored = store.read_stage1_unit(
            name,
            declared_indices=(index,),
            declared_identity_sha256=result.scientific_payload_hash,
            row_ids=(f"replication-{index:06d}",),
        )
        if not isinstance(restored, CalibrationReplicationResult):
            raise SpineError("temporary payload restored with the wrong type")
        validate_scientific_payload(restored.scientific_payload)
        if restored.scientific_payload_hash != scientific_payload_hash(restored.scientific_payload):
            raise SpineError("temporary payload scientific hash differs")
        if canonical_scientific_payload_bytes(restored.scientific_payload) != canonical_scientific_payload_bytes(
            result.scientific_payload
        ):
            raise SpineError("temporary payload canonical bytes differ")
        self._observe("temporary_validated", index)
        return temporary

    def _write_transition(self, result: CalibrationReplicationResult) -> None:
        index = result.scientific_payload.replication_index
        self.transitions.write_chunk(
            index,
            {
                "replication_index": np.asarray([index], dtype=np.int32),
                "payload_hash": np.asarray([result.scientific_payload_hash], dtype="U64"),
                "completion_state": np.asarray(["complete"], dtype="U8"),
            },
        )
        self._observe("checkpoint_transition", index)

    def commit_replication(self, result: CalibrationReplicationResult) -> None:
        if not isinstance(result, CalibrationReplicationResult):
            raise SpineError("checkpoint commit requires a sealed replication result")
        payload = validate_scientific_payload(result.scientific_payload)
        if result.scientific_payload_hash != scientific_payload_hash(payload):
            raise SpineError("checkpoint payload hash differs before temporary write")
        index = payload.replication_index
        temporary: Path | None = None
        try:
            temporary = self._write_validated_temporary(result)
            name = self._unit_name(index)
            self.payloads.write_stage1_unit(
                name,
                result,
                declared_indices=(index,),
                declared_identity_sha256=result.scientific_payload_hash,
                row_ids=(f"replication-{index:06d}",),
            )
            self._observe("payload_atomically_committed", index)
            self._write_transition(result)
        finally:
            if temporary is not None and temporary.exists():
                shutil.rmtree(temporary)

    def _read_payload(self, index: int) -> CalibrationReplicationResult:
        name = self._unit_name(index)
        transition = self.transitions.read_chunk(index) if self.transitions.has_chunk(index) else None
        expected_hash = None if transition is None else str(transition["payload_hash"][0])
        if expected_hash is None:
            raise SpineError("payload read requires a recorded completion hash")
        restored = self.payloads.read_stage1_unit(
            name,
            declared_indices=(index,),
            declared_identity_sha256=expected_hash,
            row_ids=(f"replication-{index:06d}",),
        )
        if not isinstance(restored, CalibrationReplicationResult):
            raise SpineError("committed payload restored with the wrong type")
        if restored.scientific_payload_hash != expected_hash:
            raise SpineError("checkpoint transition payload hash differs")
        validate_scientific_payload(restored.scientific_payload)
        return restored

    def completed_result(self, index: int) -> CalibrationReplicationResult | None:
        checked = self._validated_index(index)
        payload_exists = self.payloads.has_stage1_unit(self._unit_name(checked))
        transition_exists = self.transitions.has_chunk(checked)
        if transition_exists and not payload_exists:
            raise SpineError("checkpoint marks a replication complete without its payload")
        if not payload_exists:
            return None
        if not transition_exists:
            result = self._read_payload_without_transition(checked)
            self._write_transition(result)
        return self._read_payload(checked)

    def _read_payload_without_transition(self, index: int) -> CalibrationReplicationResult:
        name = self._unit_name(index)
        manifest_path = self.root / "payloads" / f"stage1-{name}" / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected_hash = str(manifest["declared_identity_sha256"])
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise SpineError("committed payload manifest is unreadable during recovery") from exc
        if manifest_path.read_bytes() != canonical_json_bytes(manifest):
            raise SpineError("committed payload manifest is not canonical during recovery")
        restored = self.payloads.read_stage1_unit(
            name,
            declared_indices=(index,),
            declared_identity_sha256=expected_hash,
            row_ids=(f"replication-{index:06d}",),
        )
        if not isinstance(restored, CalibrationReplicationResult):
            raise SpineError("committed payload restored with the wrong type")
        validate_scientific_payload(restored.scientific_payload)
        if restored.scientific_payload_hash != scientific_payload_hash(restored.scientific_payload):
            raise SpineError("committed payload hash differs during recovery")
        return restored

    def recover(self) -> RecoveryState:
        self._assert_no_validation_residue()
        completed: list[tuple[int, str]] = []
        never_started: list[int] = []
        attempted: list[AttemptedReplication] = []
        for index in range(CALIBRATION_REPLICATIONS):
            result = self.completed_result(index)
            attempts = self.attempt_records(index)
            if result is not None:
                completed.append((index, result.scientific_payload_hash))
            elif not attempts:
                never_started.append(index)
            else:
                latest = attempts[-1]
                attempted.append(
                    AttemptedReplication(
                        latest,
                        self._read_failure(index, latest.attempt_number),
                    )
                )
        return RecoveryState(
            tuple(completed),
            tuple(never_started),
            tuple(attempted),
        )
