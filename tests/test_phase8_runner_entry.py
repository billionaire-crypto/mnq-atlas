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
    assert "stage1_workers" in parameters
    assert "bootstrap_workers" in parameters
    assert "aggregate_memory_ceiling_bytes" in parameters
    assert "launch_minimum_available_bytes" in parameters
    assert "wrapper_launch_capacity_prevalidated" in parameters
    assert not ({"corpus", "tree", "input"} & set(parameters))


@pytest.mark.parametrize(
    ("wrapper_prevalidated", "expected_preflight_calls"),
    ((False, 1), (True, 0)),
)
def test_wrapper_prevalidated_launch_capacity_is_not_rechecked(
    tmp_path, monkeypatch, wrapper_prevalidated, expected_preflight_calls,
):
    events = []

    class StopAfterCapacityCheck(Exception):
        pass

    monkeypatch.setattr(runner_module._progress, "is_configured", lambda: True)
    monkeypatch.setattr(runner_module, "PHASE8_OUTPUT_ROOT", tmp_path / "output")
    monkeypatch.setattr(runner_module, "PHASE8_STAGING_ROOT", tmp_path / "staging")
    monkeypatch.setattr(
        runner_module, "PHASE8_CHECKPOINT_ROOT", tmp_path / "checkpoint"
    )
    monkeypatch.setattr(
        runner_module,
        "probe_effective_cpu_capacity",
        lambda: {"effective_cpu_count": 128},
    )
    monkeypatch.setattr(
        runner_module.AggregateMemoryGate,
        "preflight",
        lambda _self: events.append("capacity"),
    )

    def stop_before_inputs():
        events.append("inputs")
        raise StopAfterCapacityCheck

    monkeypatch.setattr(runner_module, "load_ratified_inputs", stop_before_inputs)
    with pytest.raises(StopAfterCapacityCheck):
        runner_module.run_phase8(
            stage1_workers=6,
            bootstrap_workers=32,
            process_start_method="spawn",
            wrapper_launch_capacity_prevalidated=wrapper_prevalidated,
        )
    assert events.count("capacity") == expected_preflight_calls
    assert events[-1] == "inputs"

    with pytest.raises(SpineError, match="must be a boolean"):
        runner_module.run_phase8(
            stage1_workers=6,
            bootstrap_workers=32,
            process_start_method="spawn",
            wrapper_launch_capacity_prevalidated=1,
        )


def test_ratified_input_root_is_the_session_aware_v2_artifact():
    relative = runner_module.RATIFIED_INPUT_ROOT.relative_to(
        runner_module.REPO_ROOT
    ).as_posix()
    assert relative == "data/exploration/derived/phase7-unit-o-session-aware-v2"
    # Negative control: Phase 8 must not silently consume the pre-D33 v1 tree.
    assert "phase7-unit-o-first-run-v1" not in relative


def test_phase8_v2_output_family_is_new_and_versioned():
    expected = "data/exploration/derived/phase8-session-aware-v2"
    assert runner_module.PHASE8_OUTPUT_ROOT.relative_to(
        runner_module.REPO_ROOT
    ).as_posix() == expected
    assert runner_module.PHASE8_STAGING_ROOT == runner_module.PHASE8_OUTPUT_ROOT.with_name(
        runner_module.PHASE8_OUTPUT_ROOT.name + ".staging"
    )
    assert runner_module.PHASE8_CHECKPOINT_ROOT == runner_module.PHASE8_OUTPUT_ROOT.with_name(
        runner_module.PHASE8_OUTPUT_ROOT.name + ".checkpoint"
    )
    assert runner_module.PHASE8_PROGRESS_LOG == runner_module.PHASE8_OUTPUT_ROOT.with_name(
        runner_module.PHASE8_OUTPUT_ROOT.name + ".progress.log"
    )
    assert "phase8-first-run-v1" not in expected


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
        RunnerOperatingConfig(stage1_workers=0, bootstrap_workers=1, effective_cpu_count=2)
    with pytest.raises(SpineError, match="process start method"):
        RunnerOperatingConfig(
            stage1_workers=1, bootstrap_workers=1, effective_cpu_count=2,
            process_start_method="platform-default",
        )


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
