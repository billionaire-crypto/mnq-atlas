"""Failing witnesses for Phase 8 runner support census and launch gates."""

from __future__ import annotations

from dataclasses import replace

import pytest

from mnq_lab import SpineError
from mnq_lab.phase8.preflight import (
    BootstrapTermKey,
    build_term_support_record,
    interval_eligible_records,
    thin_support_families,
)
from mnq_lab.phase8.runner import (
    AGGREGATE_MEMORY_CEILING_BASIS,
    DEFAULT_AGGREGATE_MEMORY_SAMPLE_INTERVAL_SECONDS,
    RunnerOperatingConfig,
)


def _key(family: str, cell: str) -> BootstrapTermKey:
    return BootstrapTermKey(
        family=family,
        row_key=("primary", "downward_excursion_ticks", cell),
        term_role="target",
    )


def test_thin_support_labels_are_bound_to_the_row_key_at_construction():
    open_low = build_term_support_record(
        key=_key("contrast", "open-low"),
        session_ids=tuple(range(18)),
        status="insufficient_overlap",
    )
    close_high = build_term_support_record(
        key=_key("interaction", "close-high"),
        session_ids=tuple(range(25)),
        status="ok",
    )

    assert open_low.n_sessions == 18
    assert open_low.key.row_key[-1] == "open-low"
    assert close_high.n_sessions == 25
    assert thin_support_families((open_low, close_high)) == (
        ("contrast", 1),
        ("interaction", 1),
    )


def test_eighteen_session_failed_row_is_retained_but_never_bootstrapped():
    failed = build_term_support_record(
        key=_key("contrast", "eighteen-session-mutant"),
        session_ids=tuple(range(18)),
        status="insufficient_overlap",
    )
    adequate = build_term_support_record(
        key=_key("contrast", "adequate-control"),
        session_ids=tuple(range(30)),
        status="ok",
    )

    assert failed.n_sessions == 18
    assert failed.bootstrap_eligible is False
    assert interval_eligible_records((failed, adequate)) == (adequate,)


def test_support_record_rejects_a_stale_caller_supplied_count():
    with pytest.raises(SpineError, match="computed from its bound session ids"):
        replace(
            build_term_support_record(
                key=_key("contrast", "stale-label-mutant"),
                session_ids=(1, 2, 3),
                status="ok",
            ),
            n_sessions=99,
        )


def test_runner_operating_defaults_and_boundaries_are_explicit():
    config = RunnerOperatingConfig(
        stage1_workers=2, bootstrap_workers=3, effective_cpu_count=4
    )
    assert config.aggregate_memory_ceiling_bytes == 192 * 1024**3
    assert config.launch_minimum_available_bytes == 224 * 1024**3
    assert DEFAULT_AGGREGATE_MEMORY_SAMPLE_INTERVAL_SECONDS == 30.0
    assert config.stage1_workers == 2
    assert config.bootstrap_workers == 3
    assert config.process_start_method in {"spawn", "fork"}

    assert AGGREGATE_MEMORY_CEILING_BASIS == {
        "schema_version": "phase8-memory-ceiling-basis-v3",
        "failed_attempt_execution_receipt_sha256": (
            "5216eba31f78c15fc46978dbc15ecef984344c5130e5e52d5b3bbdfd9879d97f"
        ),
        "failed_attempt_run_commit": (
            "c733890c86a49130c0acf06b36200adc394ffbe5"
        ),
        "failed_attempt_stage1_workers": 8,
        "failed_attempt_bootstrap_workers": 64,
        "recorded_stage1_process_tree_pss_at_stop_bytes": 207_103_779_840,
        "recorded_stage1_memory_stop_sample_count": 3,
        "recorded_stage1_memory_stop_was_plateau": False,
        "structural_rows_per_slice": 78_390,
        "prospective_stage1_workers": 6,
        "prospective_bootstrap_workers": 32,
        "synthetic_pss_probe_workers": 6,
        "synthetic_pss_probe_private_bytes": 25_769_803_776,
        "synthetic_pss_probe_measured_bytes": 25_867_137_024,
        "synthetic_pss_probe_max_seconds": 0.015742299146950245,
        "rationale": (
            "attempt 003 proved that the eight-worker pre-fix Stage 1 "
            "exceeded the fixed boundary but did not establish a plateau; "
            "attempt 004 uses the audited invariant-hoisting and "
            "cache-deduplication corrections with six Stage 1 and 32 "
            "bootstrap workers, while the unchanged 192 GiB PSS ceiling, "
            "224 GiB launch minimum, durable stop evidence, and bounded "
            "monitor shutdown remain fail-closed"
        ),
    }

    with pytest.raises(SpineError, match="positive integer"):
        RunnerOperatingConfig(stage1_workers=0, bootstrap_workers=1, effective_cpu_count=2)
    with pytest.raises(SpineError, match="memory ceiling"):
        RunnerOperatingConfig(
            stage1_workers=1, bootstrap_workers=1, effective_cpu_count=2,
            aggregate_memory_ceiling_bytes=0,
        )
