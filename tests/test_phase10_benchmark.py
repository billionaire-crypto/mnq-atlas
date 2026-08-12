"""Cost benchmark timing and allocation tracing use distinct passes."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from mnq_lab.phase10 import benchmark


class _Sampler:
    def __init__(self):
        self.peak = 123_456

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None


def _batch():
    return SimpleNamespace(
        null_contrasts=np.zeros((2, 1), dtype=np.int64),
        null_valid=np.ones((2, 1), dtype=np.bool_),
        null_yearly_contrasts=np.zeros((2, 1), dtype=np.int64),
        null_yearly_valid=np.ones((2, 1), dtype=np.bool_),
        null_statistics=np.zeros(2, dtype=np.float64),
    )


def _assert_trace_boundaries(trace_states):
    assert trace_states == [False, True]


def test_benchmark_times_untraced_and_measures_allocations_in_second_pass(
    monkeypatch,
):
    trace_states = []

    def evaluate(corpus, count, progress):
        trace_states.append(benchmark.tracemalloc.is_tracing())
        progress(count)
        return _batch()

    monkeypatch.setattr(benchmark, "_RssSampler", _Sampler)
    monkeypatch.setattr(benchmark, "evaluate_null_surfaces", evaluate)

    timed, wall, timed_rss = benchmark._timed_surface_pass(object(), 2)
    traced, allocation_wall, allocation_rss, traced_peak = (
        benchmark._traced_allocation_pass(object(), 2)
    )

    _assert_trace_boundaries(trace_states)
    assert wall >= 0.0
    assert allocation_wall >= 0.0
    assert timed_rss == allocation_rss == 123_456
    assert traced_peak >= 0
    assert benchmark._array_bytes(timed) == benchmark._array_bytes(traced)
    assert not benchmark.tracemalloc.is_tracing()


def test_benchmark_trace_boundary_negative_uses_the_positive_assertion():
    with pytest.raises(AssertionError):
        _assert_trace_boundaries([True, True])
