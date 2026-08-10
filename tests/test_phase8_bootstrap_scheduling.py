"""Synthetic failure witnesses for Phase 8 bootstrap task scheduling."""

from __future__ import annotations

from concurrent.futures.process import BrokenProcessPool
import pickle

import numpy as np
import pytest

from mnq_lab.phase8 import uncertainty as uncertainty_module
from mnq_lab.phase8.diagnostics import status_decision
from mnq_lab.phase8.uncertainty import (
    BootstrapIntervalRequest,
    BootstrapQuantileTerm,
    joint_bootstrap_intervals_oracle,
)


def _ok():
    return status_decision(
        degenerate_baseline=False,
        insufficient_anchors=False,
        insufficient_completion=False,
        insufficient_overlap=False,
    )


def _unequal_fixture():
    session_count = 8
    rows_per_session = 525
    groups = np.repeat(
        np.arange(session_count, dtype=np.int32), rows_per_session
    )
    terms = []
    requests = []
    for position in range(40):
        per_session = 5 + position
        mask = np.zeros(groups.size, dtype=np.bool_)
        for session_index in range(session_count):
            start = session_index * rows_per_session
            mask[start : start + per_session] = True
        weights = np.zeros(groups.size, dtype=np.float64)
        weights[mask] = 1.0 / int(np.count_nonzero(mask))
        term_id = f"unequal-{position:02d}"
        terms.append(
            BootstrapQuantileTerm(
                term_id,
                np.arange(groups.size, dtype=np.int32) + position * 10_000,
                mask,
                weights,
                "q50",
            )
        )
        requests.append(
            BootstrapIntervalRequest(
                f"request-{position:02d}", term_id, None, _ok()
            )
        )
    return groups, tuple(terms), tuple(requests)


def _evaluation_position(evaluation) -> int:
    return int(str(evaluation.term_ids[0]).rsplit("-", 1)[1])


def _executor_class(partitioning: str):
    class DeferredFuture:
        def __init__(self, executor):
            self.executor = executor
            self.value = None
            self.resolved = False

        def result(self):
            if not self.resolved:
                self.executor.resolve_pending()
            return self.value

    class PartitioningExecutor:
        instances = []

        def __init__(
            self,
            *,
            max_workers,
            mp_context,
            initializer=None,
            initargs=(),
        ):
            self.max_workers = max_workers
            self.start_method = mp_context.get_start_method()
            self.initializer = initializer
            self.initargs = initargs
            self.submissions = []
            initializer(*initargs)
            type(self).instances.append(self)

        def submit(self, function, *args):
            future = DeferredFuture(self)
            self.submissions.append((function, args, future))
            return future

        def _partitions(self, evaluations):
            registered = sorted(evaluations, key=_evaluation_position)
            if partitioning == "one_task":
                return tuple((evaluation,) for evaluation in registered)
            if partitioning == "old_contiguous":
                chunk_size = (
                    len(registered) + self.max_workers - 1
                ) // self.max_workers
                return tuple(
                    tuple(registered[start : start + chunk_size])
                    for start in range(0, len(registered), chunk_size)
                )
            if partitioning == "descending":
                ordered = sorted(
                    evaluations,
                    key=lambda evaluation: (
                        -evaluation.eligible_values.size,
                        _evaluation_position(evaluation),
                    ),
                )
                return tuple((evaluation,) for evaluation in ordered)
            if partitioning == "adversarial":
                interleaved = []
                left = 0
                right = len(registered) - 1
                while left <= right:
                    interleaved.append(registered[left])
                    left += 1
                    if left <= right:
                        interleaved.append(registered[right])
                        right -= 1
                return tuple(
                    tuple(interleaved[start : start + 3])
                    for start in range(0, len(interleaved), 3)
                )
            if partitioning == "drop_one":
                return tuple((evaluation,) for evaluation in registered[:-1])
            raise AssertionError(f"unknown test partitioning: {partitioning}")

        def resolve_pending(self):
            pending = [
                submission
                for submission in self.submissions
                if not submission[2].resolved
            ]
            assert pending
            block_indices = {args[1] for _function, args, _future in pending}
            block_lengths = {args[2] for _function, args, _future in pending}
            assert len(block_indices) == len(block_lengths) == 1
            function = pending[0][0]
            evaluations = [args[0][0] for _function, args, _future in pending]
            block_index = next(iter(block_indices))
            block_length = next(iter(block_lengths))
            outputs = [
                function(partition, block_index, block_length)
                for partition in self._partitions(evaluations)
            ]
            outputs.extend([()] * (len(pending) - len(outputs)))
            assert len(outputs) == len(pending)
            for (_function, _args, future), output in zip(
                pending, outputs, strict=True
            ):
                future.value = output
                future.resolved = True

        def shutdown(self, **_kwargs):
            return None

    return PartitioningExecutor


def _result_bytes(result) -> bytes:
    return pickle.dumps(result, protocol=5)


def _assert_byte_identical(left, right) -> None:
    assert _result_bytes(left) == _result_bytes(right)


def _use_small_fixture_interval(monkeypatch) -> None:
    monkeypatch.setattr(
        uncertainty_module,
        "percentile_interval",
        lambda replicates, _confidence: (
            int(np.min(replicates)),
            int(np.max(replicates)),
        ),
    )


def _run_impl(groups, terms, requests, plan_bundle, monkeypatch, partitioning, workers):
    executor = _executor_class(partitioning)
    monkeypatch.setattr(
        uncertainty_module, "ProcessPoolExecutor", executor
    )
    result = uncertainty_module._joint_bootstrap_intervals_impl(
        groups,
        terms,
        requests,
        worker_count=workers,
        process_start_method="spawn",
        plan_bundle=plan_bundle,
    )
    return result, executor.instances[-1]


def test_partition_invariance_and_mutated_weight_negative(monkeypatch):
    monkeypatch.setattr(uncertainty_module, "DRAWS_PER_BLOCK_LENGTH", 17)
    _use_small_fixture_interval(monkeypatch)
    groups, terms, requests = _unequal_fixture()
    eligible_sizes = tuple(np.count_nonzero(term.eligibility_mask) for term in terms)
    assert len(terms) == 40
    assert min(eligible_sizes) < 64 < max(eligible_sizes)
    plan_bundle = uncertainty_module._prepare_joint_plan_matrices(groups)

    results = []
    for partitioning in (
        "one_task",
        "old_contiguous",
        "descending",
        "adversarial",
    ):
        result, _executor = _run_impl(
            groups, terms, requests, plan_bundle, monkeypatch, partitioning, 7
        )
        results.append(result)
    for result in results[1:]:
        _assert_byte_identical(results[0], result)

    mutated = list(terms)
    original = mutated[20]
    changed_weights = original.weights.copy()
    changed_weights[np.flatnonzero(original.eligibility_mask)[-1]] *= 1_000_000
    mutated[20] = BootstrapQuantileTerm(
        original.term_id,
        original.values,
        original.eligibility_mask,
        changed_weights,
        original.statistic,
    )
    changed, _executor = _run_impl(
        groups,
        tuple(mutated),
        requests,
        plan_bundle,
        monkeypatch,
        "adversarial",
        7,
    )
    with pytest.raises(AssertionError):
        _assert_byte_identical(results[0], changed)


def test_worker_count_invariance_and_dropped_evaluation_negative(monkeypatch):
    monkeypatch.setattr(uncertainty_module, "DRAWS_PER_BLOCK_LENGTH", 17)
    _use_small_fixture_interval(monkeypatch)
    groups, terms, requests = _unequal_fixture()
    plan_bundle = uncertainty_module._prepare_joint_plan_matrices(groups)

    results = []
    for workers in (1, 2, 3, 7):
        result, executor = _run_impl(
            groups, terms, requests, plan_bundle, monkeypatch, "one_task", workers
        )
        assert executor.max_workers == workers
        results.append(result)
    for result in results[1:]:
        _assert_byte_identical(results[0], result)

    with pytest.raises(KeyError, match="unequal-39"):
        _run_impl(
            groups,
            terms,
            requests,
            plan_bundle,
            monkeypatch,
            "drop_one",
            7,
        )


def test_oracle_agreement_and_perturbed_tick_negative(monkeypatch):
    monkeypatch.setattr(uncertainty_module, "DRAWS_PER_BLOCK_LENGTH", 999)
    groups = np.zeros(5, dtype=np.int32)
    values = np.asarray([7, 0, 0, 0, 0], dtype=np.int32)
    mask = np.asarray([True, False, False, False, False])
    weights = np.asarray([1.0, 0.0, 0.0, 0.0, 0.0])
    term = BootstrapQuantileTerm("oracle-term", values, mask, weights, "q75")
    requests = (
        BootstrapIntervalRequest("oracle-request", term.term_id, None, _ok()),
    )

    oracle = joint_bootstrap_intervals_oracle(groups, (term,), requests)
    fixed = uncertainty_module._joint_bootstrap_intervals_impl(
        groups, (term,), requests, worker_count=3
    )
    _assert_byte_identical(oracle, fixed)

    perturbed_values = term.values.copy()
    perturbed_values[0] += np.int32(100)
    perturbed = BootstrapQuantileTerm(
        term.term_id,
        perturbed_values,
        term.eligibility_mask,
        term.weights,
        term.statistic,
    )
    divergent = uncertainty_module._joint_bootstrap_intervals_impl(
        groups, (perturbed,), requests, worker_count=3
    )
    with pytest.raises(AssertionError):
        _assert_byte_identical(oracle, divergent)


def _assert_plan_not_in_task_payload(task_args, plan_matrices) -> None:
    assert not any(
        argument is matrix
        for argument in task_args
        for matrix in plan_matrices
    )


def test_bounded_pool_and_plan_payload_have_old_construction_negatives(monkeypatch):
    monkeypatch.setattr(uncertainty_module, "DRAWS_PER_BLOCK_LENGTH", 17)
    _use_small_fixture_interval(monkeypatch)
    groups, terms, requests = _unequal_fixture()
    plan_bundle = uncertainty_module._prepare_joint_plan_matrices(groups)
    _result, executor = _run_impl(
        groups,
        terms,
        requests,
        plan_bundle,
        monkeypatch,
        "descending",
        32,
    )

    assert executor.max_workers == min(32, len(terms)) == 32
    submissions_by_block = {
        block_index: [
            (function, args)
            for function, args, _future in executor.submissions
            if args[1] == block_index
        ]
        for block_index in range(4)
    }
    assert all(
        len(submissions) == len(terms)
        for submissions in submissions_by_block.values()
    )
    for submissions in submissions_by_block.values():
        for function, args in submissions:
            assert function is uncertainty_module._evaluate_compiled_plan_task
            assert len(args[0]) == 1
            assert isinstance(args[1], int)
            assert isinstance(args[2], int)
            _assert_plan_not_in_task_payload(args, plan_bundle.matrices)

    old_chunk_size = (353 + 32 - 1) // 32
    old_task_count = len(tuple(range(0, 353, old_chunk_size)))
    assert old_chunk_size == 12
    assert old_task_count == 30
    assert old_task_count < min(32, 353)

    pre_fix_args = ((object(),), plan_bundle.matrices[0], 1)
    with pytest.raises(AssertionError):
        _assert_plan_not_in_task_payload(pre_fix_args, plan_bundle.matrices)


def test_worker_initializer_failure_propagates_without_thread_fallback(monkeypatch):
    monkeypatch.setattr(uncertainty_module, "DRAWS_PER_BLOCK_LENGTH", 17)
    groups, terms, requests = _unequal_fixture()
    plan_bundle = uncertainty_module._prepare_joint_plan_matrices(groups)

    class FailedFuture:
        def result(self):
            raise BrokenProcessPool("synthetic initializer failure")

    class FailedInitializerExecutor:
        def __init__(self, **_kwargs):
            return None

        def submit(self, _function, *_args):
            return FailedFuture()

        def shutdown(self, **_kwargs):
            return None

    def forbidden_thread_pool(*_args, **_kwargs):
        raise AssertionError("initializer failure must not fall back to threads")

    monkeypatch.setattr(
        uncertainty_module, "ProcessPoolExecutor", FailedInitializerExecutor
    )
    monkeypatch.setattr(
        uncertainty_module, "ThreadPoolExecutor", forbidden_thread_pool
    )
    with pytest.raises(BrokenProcessPool, match="initializer failure"):
        uncertainty_module._joint_bootstrap_intervals_impl(
            groups,
            terms,
            requests,
            worker_count=7,
            process_start_method="spawn",
            plan_bundle=plan_bundle,
        )
