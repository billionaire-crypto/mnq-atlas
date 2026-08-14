"""Structural tests only; the Slice 4 cost benchmark is never executed here."""

from __future__ import annotations

import inspect
from dataclasses import fields
from pathlib import Path
import sys
import tracemalloc

import pytest

from mnq_lab.phase10.calibration_benchmark import (
    CostPassResult,
    CostBenchmarkResult,
    _memory_pass,
    _timed_pass,
    run_calibration_cost_benchmark,
)
from tests.test_phase10_calibration_results import _payload


ALLOWED_RESULT_FIELDS = (
    "wall_seconds",
    "cpu_seconds",
    "memory_bytes",
    "rows",
    "worker_utilization",
    "temporary_output_bytes",
)


def _assert_benchmark_structure(timed_source, memory_source, result_type, entrypoint):
    lowered_timed = timed_source.casefold()
    lowered_memory = memory_source.casefold()
    for forbidden in (
        "tracemalloc.start",
        "settrace",
        "setprofile",
        "coverage.start",
        "debugger",
    ):
        assert forbidden not in lowered_timed
    assert "perf_counter" not in lowered_memory
    assert "process_time" not in lowered_memory
    assert "finally:" in timed_source and "shutil.rmtree" in timed_source
    assert "finally:" in memory_source and "shutil.rmtree" in memory_source
    assert tuple(field.name for field in fields(result_type)) == ALLOWED_RESULT_FIELDS
    signature = inspect.signature(entrypoint)
    assert signature.parameters["authorization"].default is inspect.Parameter.empty
    assert "validate_external_checkpoint_root" in inspect.getsource(entrypoint)


def test_timing_memory_cleanup_and_result_inventory_are_structurally_separate():
    _assert_benchmark_structure(
        inspect.getsource(_timed_pass),
        inspect.getsource(_memory_pass),
        CostBenchmarkResult,
        run_calibration_cost_benchmark,
    )


@pytest.mark.parametrize(
    "timed_mutation,memory_mutation",
    (
        ("    tracemalloc.start()\n", ""),
        ("", "    time.perf_counter()\n"),
        ("", ""),
    ),
)
def test_instrumented_timing_memory_timing_and_cleanup_mutants_fail_same_witness(
    timed_mutation,
    memory_mutation,
):
    timed_source = inspect.getsource(_timed_pass)
    memory_source = inspect.getsource(_memory_pass)
    result_type = CostBenchmarkResult
    if timed_mutation:
        timed_source = timed_source.replace(
            "    pass_root =",
            f"{timed_mutation}    pass_root =",
            1,
        )
    elif memory_mutation:
        memory_source = memory_source.replace(
            "    pass_root =",
            f"{memory_mutation}    pass_root =",
            1,
        )
    else:
        timed_source = timed_source.replace("finally:", "if True:", 1)
    with pytest.raises(AssertionError):
        _assert_benchmark_structure(
            timed_source,
            memory_source,
            result_type,
            run_calibration_cost_benchmark,
        )


def test_scientific_result_field_mutants_fail_the_same_inventory_witness():
    class MutantResult:
        pass

    MutantResult.__dataclass_fields__ = {
        **CostBenchmarkResult.__dataclass_fields__,
        "p_value": CostBenchmarkResult.__dataclass_fields__["wall_seconds"],
    }
    with pytest.raises(AssertionError):
        _assert_benchmark_structure(
            inspect.getsource(_timed_pass),
            inspect.getsource(_memory_pass),
            MutantResult,
            run_calibration_cost_benchmark,
        )


def _assert_timed_region_rejects_instrumentation(timed_pass, root: Path, hook):
    workload_calls = []

    def workload(_path, _workers):
        workload_calls.append("called")
        return CostPassResult(1, 1.0, 0)

    prior_trace = sys.gettrace()
    prior_profile = sys.getprofile()
    was_tracing = tracemalloc.is_tracing()
    try:
        if hook == "trace":
            sys.settrace(lambda *_args: None)
        elif hook == "profile":
            sys.setprofile(lambda *_args: None)
        elif hook == "allocation":
            if not was_tracing:
                tracemalloc.start()
        else:
            raise AssertionError("undeclared instrumentation hook")
        try:
            timed_pass(workload, root, 1)
        except Exception as exc:
            assert "timed benchmark region cannot run" in str(exc)
        else:
            raise AssertionError("instrumented timed region was executed")
        assert workload_calls == []
    finally:
        sys.settrace(prior_trace)
        sys.setprofile(prior_profile)
        if not was_tracing and tracemalloc.is_tracing():
            tracemalloc.stop()


@pytest.mark.parametrize("hook", ("trace", "profile", "allocation"))
def test_timed_region_refuses_live_instrumentation(tmp_path, hook):
    _assert_timed_region_rejects_instrumentation(
        _timed_pass,
        tmp_path / hook,
        hook,
    )


def test_unguarded_timed_region_fails_the_same_live_hook_witness(tmp_path):
    def unguarded(workload, root, workers):
        root.mkdir(parents=True, exist_ok=True)
        return 0.0, 0.0, workload(root, workers)

    with pytest.raises(AssertionError):
        _assert_timed_region_rejects_instrumentation(
            unguarded,
            tmp_path / "unguarded",
            "allocation",
        )


def _assert_timed_result_type_guard(timed_pass, root: Path, returned=object()):
    try:
        timed_pass(lambda _path, _workers: returned, root, 1)
    except Exception as exc:
        assert "scientific or undeclared output" in str(exc)
    else:
        raise AssertionError("timed pass accepted an undeclared result type")


def test_timed_pass_rejects_undeclared_scientific_results(tmp_path):
    _assert_timed_result_type_guard(_timed_pass, tmp_path / "result-guard")


def test_timed_pass_rejects_an_unsealed_scientific_payload(tmp_path):
    _assert_timed_result_type_guard(
        _timed_pass,
        tmp_path / "unsealed-scientific-result",
        _payload(),
    )


def test_missing_timed_result_guard_fails_the_same_witness(tmp_path):
    def unguarded(workload, root, workers):
        root.mkdir(parents=True, exist_ok=True)
        return 0.0, 0.0, workload(root, workers)

    with pytest.raises(AssertionError):
        _assert_timed_result_type_guard(
            unguarded,
            tmp_path / "missing-result-guard",
        )
