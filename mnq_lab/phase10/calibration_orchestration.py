"""Index-addressed Slice 4 orchestration with no evidence execution at import."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, fields
import multiprocessing
from typing import Any, Callable

import numpy as np

from mnq_lab import SpineError
from mnq_lab.phase8.artifacts import canonical_json_bytes
from mnq_lab.phase8.runner import default_process_start_method
from mnq_lab.phase10.adapter import FormalCorpus
from mnq_lab.phase10.calibration_controls import (
    CALIBRATION_REPLICATIONS,
    calibration_replication_streams,
    generate_calibration_outer_control,
)
from mnq_lab.phase10.mapping import (
    PermutedTrajectories,
    SessionMapping,
    apply_joint_mapping,
    spawn_session_mappings_from_seed_sequence,
)


@dataclass(frozen=True)
class WorkerEnvironmentIdentity:
    repository_commit: str
    repository_dirty: bool
    python_version: str
    numpy_version: str
    package_lock_sha256: str
    operating_system: str
    architecture: str
    cpu_identity: str
    phase10_source_sha256: tuple[tuple[str, str], ...]
    constants_sha256: str
    corpus_manifest_sha256: str
    corpus_column_sha256: tuple[tuple[str, str], ...]
    formal_session_count: int
    worker_count: int
    process_start_method: str
    process_thread_settings: tuple[tuple[str, str], ...]
    calibration_root_label: str
    calibration_root_digest: str

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name == "repository_dirty":
                if not isinstance(value, bool):
                    raise SpineError("worker dirty-state identity must be boolean")
                continue
            if field.name in {"formal_session_count", "worker_count"}:
                if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                    raise SpineError(f"worker {field.name} must be positive")
                continue
            if isinstance(value, str):
                if not value:
                    raise SpineError(f"worker {field.name} identity is absent")
                continue
            if not isinstance(value, tuple) or not value:
                raise SpineError(f"worker {field.name} identity inventory is absent")
            for name, item in value:
                if not isinstance(name, str) or not name or not isinstance(item, str) or not item:
                    raise SpineError(f"worker {field.name} identity record is invalid")
        if self.formal_session_count != 900:
            raise SpineError("worker formal-session reconciliation differs from 900")
        if self.process_start_method not in {"spawn", "fork"}:
            raise SpineError("worker process start method is invalid")


@dataclass(frozen=True)
class IndexedPayload:
    replication_index: int
    canonical_bytes: bytes


def verify_worker_environment(
    expected: WorkerEnvironmentIdentity,
    observed: WorkerEnvironmentIdentity,
) -> None:
    if not isinstance(expected, WorkerEnvironmentIdentity) or not isinstance(
        observed, WorkerEnvironmentIdentity
    ):
        raise SpineError("worker environment verification requires complete identities")
    for field in fields(WorkerEnvironmentIdentity):
        if getattr(observed, field.name) != getattr(expected, field.name):
            raise SpineError(f"worker environment differs before scientific work: {field.name}")


def run_after_environment_verification(
    expected: WorkerEnvironmentIdentity,
    observed: WorkerEnvironmentIdentity,
    scientific_work: Callable[[], Any],
) -> Any:
    verify_worker_environment(expected, observed)
    return scientific_work()


def _built_in_index(value: Any) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value < CALIBRATION_REPLICATIONS
    ):
        raise SpineError("calibration work index must be a built-in integer in [0,300)")
    return value


def _mapping_equal(left: SessionMapping, right: SessionMapping) -> bool:
    return all(
        np.array_equal(getattr(left, field.name), getattr(right, field.name))
        for field in fields(SessionMapping)
    )


def assert_calibration_control_provenance(
    corpus: FormalCorpus,
    replication_index: int,
    control: PermutedTrajectories,
) -> None:
    if not isinstance(corpus, FormalCorpus) or not isinstance(control, PermutedTrajectories):
        raise SpineError("calibration control provenance requires frozen corpus trajectories")
    index = _built_in_index(replication_index)
    expected_mapping = generate_calibration_outer_control(corpus, index)
    expected = apply_joint_mapping(
        corpus.state_codes,
        corpus.state_valid,
        (corpus.outcome_valid, corpus.window_fits_rth),
        expected_mapping,
    )
    if not _mapping_equal(control.mapping, expected.mapping):
        raise SpineError("control does not descend from the calibration root coordinate")
    if not np.array_equal(control.state_codes, expected.state_codes) or not np.array_equal(
        control.state_valid,
        expected.state_valid,
    ):
        raise SpineError("control trajectories differ from the calibration root coordinate")


def build_verified_outer_control(
    corpus: FormalCorpus,
    replication_index: int,
) -> PermutedTrajectories:
    index = _built_in_index(replication_index)
    mapping = generate_calibration_outer_control(corpus, index)
    control = apply_joint_mapping(
        corpus.state_codes,
        corpus.state_valid,
        (corpus.outcome_valid, corpus.window_fits_rth),
        mapping,
    )
    assert_calibration_control_provenance(corpus, index, control)
    return control


def fresh_internal_mappings(
    corpus: FormalCorpus,
    replication_index: int,
    mapping_count: int,
) -> tuple[SessionMapping, ...]:
    if not isinstance(corpus, FormalCorpus):
        raise SpineError("internal calibration mappings require a FormalCorpus")
    index = _built_in_index(replication_index)
    streams = calibration_replication_streams(index)
    return spawn_session_mappings_from_seed_sequence(
        corpus.session_ids,
        corpus.calendar_quarters,
        mapping_count,
        root_sequence=streams.ensemble_root,
    )


def synthetic_coordinate_payload(replication_index: int) -> IndexedPayload:
    """Small deterministic coordinate witness; it does not load or evaluate a corpus."""
    index = _built_in_index(replication_index)
    streams = calibration_replication_streams(index)
    control_words = streams.control_rng.integers(0, 2**32, size=4, dtype=np.uint32)
    internal_child = streams.ensemble_root.spawn(1)[0]
    internal_rng = np.random.Generator(np.random.PCG64(internal_child))
    internal_words = internal_rng.integers(0, 2**32, size=4, dtype=np.uint32)
    payload = canonical_json_bytes(
        {
            "control_spawn_key": list(streams.control_spawn_key),
            "control_words": [int(value) for value in control_words],
            "ensemble_spawn_key": list(streams.ensemble_spawn_key),
            "internal_spawn_key": list(internal_child.spawn_key),
            "internal_words": [int(value) for value in internal_words],
            "replication_index": index,
        }
    )
    return IndexedPayload(index, payload)


def _validated_indices(indices: Any) -> tuple[int, ...]:
    try:
        result = tuple(indices)
    except TypeError as exc:
        raise SpineError("calibration work indices must be one finite sequence") from exc
    if not result or len(set(result)) != len(result):
        raise SpineError("calibration work indices must be unique and nonempty")
    for index in result:
        _built_in_index(index)
    return result


def execute_coordinate_fixture(
    indices: Any,
    worker_count: int,
    *,
    completion_order: tuple[int, ...] | None = None,
) -> tuple[IndexedPayload, ...]:
    """Execute explicitly indexed synthetic work and return canonical index order."""
    declared = _validated_indices(indices)
    if isinstance(worker_count, bool) or not isinstance(worker_count, int) or worker_count <= 0:
        raise SpineError("calibration fixture worker count must be positive")
    if completion_order is not None and set(completion_order) != set(declared):
        raise SpineError("synthetic completion order differs from declared indices")
    observed: dict[int, IndexedPayload] = {}
    if worker_count == 1:
        order = declared if completion_order is None else completion_order
        for index in order:
            result = synthetic_coordinate_payload(index)
            if result.replication_index != index:
                raise SpineError("serial result differs from its assigned replication index")
            observed[index] = result
    else:
        context = multiprocessing.get_context(default_process_start_method())
        with ProcessPoolExecutor(max_workers=worker_count, mp_context=context) as executor:
            futures = {
                executor.submit(synthetic_coordinate_payload, index): index
                for index in declared
            }
            for future in as_completed(futures):
                index = futures[future]
                result = future.result()
                if result.replication_index != index:
                    raise SpineError("parallel result differs from its assigned replication index")
                observed[index] = result
    if set(observed) != set(declared):
        raise SpineError("partial execution cannot reduce the declared denominator")
    return tuple(observed[index] for index in sorted(declared))


def four_way_determinism_witness() -> tuple[tuple[bytes, ...], ...]:
    """Compare serial, process-parallel, interrupted, and freshly resumed coordinates."""
    indices = (0, 1, 2, 3, 4, 5)
    serial = execute_coordinate_fixture(indices, 1)
    parallel = execute_coordinate_fixture(indices, 2)
    interrupted = execute_coordinate_fixture(indices[:3], 1, completion_order=(2, 0, 1))
    resumed = execute_coordinate_fixture(indices[3:], 2)
    combined = tuple(sorted((*interrupted, *resumed), key=lambda item: item.replication_index))
    variants = (serial, parallel, combined, execute_coordinate_fixture(indices, 1))
    encoded = tuple(tuple(item.canonical_bytes for item in variant) for variant in variants)
    if not all(value == encoded[0] for value in encoded[1:]):
        raise SpineError("serial, parallel, interrupted, and resumed canonical bytes differ")
    return encoded
