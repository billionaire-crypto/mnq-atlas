"""Synthetic-only deterministic orchestration and provenance witnesses."""

from __future__ import annotations

from dataclasses import fields, replace

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.phase10.adapter import FormalCorpus, FormalJoinReconciliation
from mnq_lab.phase10.calibration_orchestration import (
    WorkerEnvironmentIdentity,
    assert_calibration_control_provenance,
    build_verified_outer_control,
    execute_coordinate_fixture,
    four_way_determinism_witness,
    fresh_internal_mappings,
    run_after_environment_verification,
    synthetic_coordinate_payload,
    verify_worker_environment,
)
from mnq_lab.phase10.mapping import SessionMapping, apply_joint_mapping


def _readonly(values, dtype=None):
    result = np.array(values, dtype=dtype, copy=True)
    result.setflags(write=False)
    return result


def _corpus() -> FormalCorpus:
    sessions = np.arange(40, dtype=np.int32) + 20200101
    quarters = np.asarray(("2020Q1",) * 20 + ("2020Q2",) * 20)
    shape = (40, 5)
    state_codes = np.arange(40, dtype=np.int8)[:, None] % 3
    state_codes = np.repeat(state_codes, 5, axis=1)
    valid = np.ones(shape, dtype=np.bool_)
    reconciliation = FormalJoinReconciliation(200, 200, 0, 0, 40, 40, 0, 0, 40, 200, 5)
    return FormalCorpus(
        _readonly(sessions),
        _readonly(quarters),
        _readonly((2020,) * 40, np.int32),
        _readonly(("08:35", "09:05", "10:35", "12:35", "14:05")),
        _readonly(("open", "morning", "midday", "afternoon", "close")),
        _readonly(np.arange(200, dtype=np.int64).reshape(shape)),
        _readonly(state_codes, np.int8),
        _readonly(valid),
        _readonly(np.arange(200, dtype=np.int32).reshape(shape)),
        _readonly(valid),
        _readonly(valid),
        reconciliation,
        {"synthetic": True},
    )


def _environment() -> WorkerEnvironmentIdentity:
    return WorkerEnvironmentIdentity(
        repository_commit="a" * 40,
        repository_dirty=False,
        python_version="3.13.2",
        numpy_version=np.__version__,
        package_lock_sha256="b" * 64,
        operating_system="synthetic-os",
        architecture="synthetic-arch",
        cpu_identity="synthetic-cpu",
        phase10_source_sha256=(("source.py", "c" * 64),),
        constants_sha256="d" * 64,
        corpus_manifest_sha256="e" * 64,
        corpus_column_sha256=(("column", "f" * 64),),
        formal_session_count=900,
        worker_count=2,
        process_start_method="spawn",
        process_thread_settings=(("OMP_NUM_THREADS", "1"),),
        calibration_root_label="synthetic-label",
        calibration_root_digest="1" * 64,
    )


def _assert_environment_precedes_work(executor, expected, observed):
    trace = []
    mismatch = expected != observed

    def work():
        trace.append("scientific")
        return "done"

    try:
        result = executor(expected, observed, work)
    except SpineError:
        assert trace == []
        assert mismatch
        return
    assert not mismatch
    assert trace == ["scientific"]
    assert result == "done"


def _with_changed_environment_field(environment, field_name):
    changed = object.__new__(WorkerEnvironmentIdentity)
    for field in fields(WorkerEnvironmentIdentity):
        value = getattr(environment, field.name)
        if field.name == field_name:
            if isinstance(value, bool):
                value = not value
            elif isinstance(value, int):
                value += 1
            elif isinstance(value, str):
                value = "fork" if value == "spawn" else f"{value}-different"
            else:
                value = (*value, ("additional", "different"))
        object.__setattr__(changed, field.name, value)
    return changed


def test_environment_identity_is_complete_and_checked_before_work():
    expected = _environment()
    _assert_environment_precedes_work(
        run_after_environment_verification,
        expected,
        expected,
    )
    for field in fields(WorkerEnvironmentIdentity):
        _assert_environment_precedes_work(
            run_after_environment_verification,
            expected,
            _with_changed_environment_field(expected, field.name),
        )


def test_environment_warning_or_late_check_mutants_fail_the_same_witness():
    different = replace(_environment(), cpu_identity="different")

    def warning(expected, observed, work):
        try:
            verify_worker_environment(expected, observed)
        except SpineError:
            pass
        return work()

    def late(expected, observed, work):
        result = work()
        verify_worker_environment(expected, observed)
        return result

    for mutant in (warning, late):
        with pytest.raises((AssertionError, SpineError)):
            _assert_environment_precedes_work(mutant, _environment(), different)


def _assert_control_provenance(builder, checker):
    corpus = _corpus()
    control = builder(corpus, 7)
    checker(corpus, 7, control)
    try:
        checker(corpus, 8, control)
    except SpineError as exc:
        assert "calibration root coordinate" in str(exc)
    else:
        raise AssertionError("wrong-coordinate control was accepted")


def test_outer_control_is_bound_to_its_calibration_coordinate():
    _assert_control_provenance(
        build_verified_outer_control,
        assert_calibration_control_provenance,
    )


def test_unchecked_control_provenance_mutant_fails_the_same_witness():
    def unchecked(_corpus, _index, _control):
        return None

    with pytest.raises(AssertionError):
        _assert_control_provenance(build_verified_outer_control, unchecked)


def _mapping_bytes(mapping: SessionMapping) -> tuple[bytes, ...]:
    return tuple(getattr(mapping, field.name).tobytes() for field in fields(SessionMapping))


def _assert_resume_rederives(producer):
    corpus = _corpus()
    first = producer(corpus, 11, 2)
    other = producer(corpus, 3, 2)
    resumed = producer(corpus, 11, 2)
    assert tuple(map(_mapping_bytes, first)) == tuple(map(_mapping_bytes, resumed))
    assert tuple(map(_mapping_bytes, first)) != tuple(map(_mapping_bytes, other))


def test_resume_rederives_a_fresh_ensemble_root_by_index():
    _assert_resume_rederives(fresh_internal_mappings)


def test_cached_consumed_ensemble_mutant_fails_the_same_resume_witness():
    cache = {}

    def cached(corpus, index, count):
        if index not in cache:
            cache[index] = fresh_internal_mappings(corpus, index, count)
            return cache[index]
        return tuple(reversed(cache[index]))

    with pytest.raises(AssertionError):
        _assert_resume_rederives(cached)


def _assert_indexed_determinism(executor):
    indices = (5, 1, 4, 0, 3, 2)
    serial = executor(indices, 1)
    completion_reversed = executor(indices, 1, completion_order=tuple(reversed(indices)))
    parallel = executor(indices, 2)
    expected = tuple(synthetic_coordinate_payload(index) for index in sorted(indices))
    assert serial == expected
    assert completion_reversed == expected
    assert parallel == expected


def test_work_assignment_and_result_order_are_index_deterministic():
    _assert_indexed_determinism(execute_coordinate_fixture)


def test_completion_order_assignment_mutant_fails_the_same_witness():
    def completion_order(indices, workers, *, completion_order=None):
        order = tuple(indices) if completion_order is None else completion_order
        return tuple(synthetic_coordinate_payload(index) for index in order)

    with pytest.raises(AssertionError):
        _assert_indexed_determinism(completion_order)


def _assert_four_way_bytes(witness):
    variants = witness()
    assert len(variants) == 4
    assert variants[0] == variants[1] == variants[2] == variants[3]
    assert len(variants[0]) == 6


def test_serial_parallel_interrupted_and_resumed_bytes_are_identical():
    _assert_four_way_bytes(four_way_determinism_witness)


def test_different_resumed_bytes_fail_the_same_four_way_witness():
    def different_resumed_bytes():
        variants = list(four_way_determinism_witness())
        resumed = list(variants[-1])
        resumed[0] += b"mutant"
        variants[-1] = tuple(resumed)
        return tuple(variants)

    with pytest.raises(AssertionError):
        _assert_four_way_bytes(different_resumed_bytes)


def test_partial_result_cannot_reduce_the_declared_inventory(monkeypatch):
    import mnq_lab.phase10.calibration_orchestration as module

    def wrong_index(index):
        return replace(synthetic_coordinate_payload(index), replication_index=(index + 1) % 300)

    monkeypatch.setattr(module, "synthetic_coordinate_payload", wrong_index)
    with pytest.raises(SpineError, match="assigned replication index"):
        execute_coordinate_fixture((0, 1), 1)
