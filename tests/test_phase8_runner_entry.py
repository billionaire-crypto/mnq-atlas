"""Entry-point and worker portability witnesses for the Phase 8 runner."""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.phase8 import runner as runner_module
from mnq_lab.phase8.runner import RunnerOperatingConfig, load_ratified_inputs
from mnq_lab.phase8 import uncertainty as uncertainty_module
from mnq_lab.phase8.diagnostics import status_decision
from mnq_lab.phase8.uncertainty import (
    BootstrapIntervalRequest,
    BootstrapQuantileTerm,
    joint_bootstrap_intervals,
)


def _ok():
    return status_decision(
        degenerate_baseline=False,
        insufficient_anchors=False,
        insufficient_completion=False,
        insufficient_overlap=False,
    )


def test_public_entry_accepts_operating_controls_but_no_data_paths():
    parameters = inspect.signature(runner_module.run_phase8).parameters
    assert "workers" in parameters
    assert "aggregate_memory_ceiling_bytes" in parameters
    assert "launch_minimum_available_bytes" in parameters
    assert not ({"path", "root", "corpus", "tree", "input"} & set(parameters))


def test_input_manifest_is_not_opened_until_ratification_passes(monkeypatch):
    events = []

    def rejected(_tree):
        events.append("ratify")
        raise SpineError("named ratification failure")

    monkeypatch.setattr(runner_module, "require_ratified_unit_o", rejected)
    monkeypatch.setattr(
        runner_module,
        "_open_fixed_input_manifests",
        lambda: events.append("open"),
    )
    with pytest.raises(SpineError, match="named ratification failure"):
        load_ratified_inputs()
    assert events == ["ratify"]


def test_worker_count_and_explicit_start_method_reach_process_executor(monkeypatch):
    monkeypatch.setattr(uncertainty_module, "DRAWS_PER_BLOCK_LENGTH", 1)
    monkeypatch.setattr(
        uncertainty_module,
        "percentile_interval",
        lambda replicate_statistics, confidence_level: (
            replicate_statistics[0],
            replicate_statistics[0],
        ),
    )
    groups = np.repeat(np.arange(6, dtype=np.int32), 700)
    values = np.tile(np.arange(700, dtype=np.int32), 6)
    terms = []
    requests = []
    for index in range(2):
        mask = np.zeros(groups.size, dtype=np.bool_)
        mask[index::700] = True
        weights = np.where(mask, 1 / 6, 0.0)
        term = BootstrapQuantileTerm(f"term-{index}", values, mask, weights, "q50")
        terms.append(term)
        requests.append(BootstrapIntervalRequest(f"request-{index}", term.term_id, None, _ok()))

    seen = {}

    class InlineExecutor:
        def __init__(self, *, max_workers, mp_context):
            seen["workers"] = max_workers
            seen["method"] = mp_context.get_start_method()

        def submit(self, function, *args):
            class Result:
                def result(self):
                    return function(*args)
            return Result()

        def shutdown(self, **_kwargs):
            return None

    monkeypatch.setattr(uncertainty_module, "ProcessPoolExecutor", InlineExecutor)
    joint_bootstrap_intervals(
        groups,
        tuple(terms),
        tuple(requests),
        worker_count=2,
        process_start_method="spawn",
    )
    assert seen == {"workers": 2, "method": "spawn"}


def test_invalid_worker_and_start_method_halt_before_bootstrap():
    with pytest.raises(SpineError, match="positive integer"):
        RunnerOperatingConfig(workers=0)
    with pytest.raises(SpineError, match="process start method"):
        RunnerOperatingConfig(process_start_method="platform-default")


def test_checkpoint_chunks_reuse_one_frozen_19996_plan_set(monkeypatch):
    monkeypatch.setattr(uncertainty_module, "DRAWS_PER_BLOCK_LENGTH", 999)
    groups = np.repeat(np.arange(3, dtype=np.int32), 2)
    mask = np.ones(groups.size, dtype=np.bool_)
    weights = np.full(groups.size, 1 / groups.size)
    terms = tuple(
        BootstrapQuantileTerm(
            f"shared-plan-{index}",
            np.arange(groups.size, dtype=np.int32) + index,
            mask,
            weights,
            "q50",
        )
        for index in range(2)
    )
    requests = tuple(
        BootstrapIntervalRequest(f"shared-request-{index}", term.term_id, None, _ok())
        for index, term in enumerate(terms)
    )
    calls = 0
    original = uncertainty_module.stationary_group_resample

    def count_plan(*args):
        nonlocal calls
        calls += 1
        return original(*args)

    monkeypatch.setattr(uncertainty_module, "stationary_group_resample", count_plan)
    plans = uncertainty_module._prepare_joint_plan_matrices(groups, terms)
    first = uncertainty_module._joint_bootstrap_intervals_with_plan_matrices(
        groups, terms[:1], requests[:1], plans
    )
    second = uncertainty_module._joint_bootstrap_intervals_with_plan_matrices(
        groups, terms[1:], requests[1:], plans
    )
    assert calls == 4 * 999
    assert first.requests[0].request_id == "shared-request-0"
    assert second.requests[0].request_id == "shared-request-1"
