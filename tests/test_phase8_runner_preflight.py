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
from mnq_lab.phase8.runner import RunnerOperatingConfig


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
    assert config.stage1_workers == 2
    assert config.bootstrap_workers == 3
    assert config.process_start_method in {"spawn", "fork"}

    with pytest.raises(SpineError, match="positive integer"):
        RunnerOperatingConfig(stage1_workers=0, bootstrap_workers=1, effective_cpu_count=2)
    with pytest.raises(SpineError, match="memory ceiling"):
        RunnerOperatingConfig(
            stage1_workers=1, bootstrap_workers=1, effective_cpu_count=2,
            aggregate_memory_ceiling_bytes=0,
        )
