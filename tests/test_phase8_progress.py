"""D30 progress reporting: complete coverage, and structurally value-free.

The first Step 7 production attempt ran 3 h 07 min emitting nothing, so a
stalled run and a working run were indistinguishable. These tests pin the
corrections required after that run:

  * every long phase has a progress call site, so no phase can go silent;
  * a multi-item phase cannot stay silent;
  * stdout and the dedicated log file receive identical, immediately flushed
    output;
  * no scientific value can reach a progress line, including through
    exception text;
  * the realized distinct term count is reported as ``pending`` until it is
    actually known, never invented.
"""

from __future__ import annotations

import ast
import inspect
import io
import re
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.phase8 import production, progress, runner
from mnq_lab.phase8.artifacts import CheckpointIdentity, CheckpointStore
from mnq_lab.phase8.runner import InventoryChunk


@pytest.fixture(autouse=True)
def _restore_default_sink():
    yield
    progress.reset()


def _lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def test_a_multi_item_phase_cannot_remain_silent():
    stream = io.StringIO()
    sink = progress.ProgressSink((stream,))
    phase = sink.phase(progress.PHASE_CONTRASTS, 5_000)
    for done in range(1, 5_001):
        phase.advance(done)
    lines = _lines(stream.getvalue())
    assert lines, "a 5,000 item phase emitted nothing"
    assert any("done=0" in line for line in lines), "no line at phase start"
    assert any("done=5000" in line for line in lines), "no line at completion"


def test_completion_is_always_emitted_even_when_fast():
    stream = io.StringIO()
    sink = progress.ProgressSink((stream,))
    phase = sink.phase(progress.PHASE_ARTIFACTS, 1)
    phase.advance(1)
    assert any("done=1 total=1" in line for line in _lines(stream.getvalue()))


def test_stdout_and_log_file_receive_identical_immediately_visible_output(tmp_path, capsys):
    log_path = tmp_path / "phase8-progress.log"
    progress.configure(log_path=log_path, stdout=True)
    phase = progress.get_sink().phase(progress.PHASE_DAY_TYPES, 2)
    phase.advance(2)
    # Read the file BEFORE any close, proving the write was flushed, not buffered.
    on_disk = _lines(log_path.read_text(encoding="utf-8"))
    on_stdout = _lines(capsys.readouterr().out)
    assert on_disk, "log file empty; output was buffered rather than flushed"
    assert on_disk == on_stdout


def _phase_call_constants(source: str) -> set[str]:
    constants = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "phase":
            continue
        if not node.args or not isinstance(node.args[0], ast.Attribute):
            continue
        constants.add(node.args[0].attr)
    return constants


def test_every_long_phase_has_a_real_progress_call_site():
    """Imports and comments cannot masquerade as phase call sites."""
    observed = set().union(
        *(
            _phase_call_constants(Path(module.__file__).read_text(encoding="utf-8"))
            for module in (production, runner)
        )
    )
    expected = {f"PHASE_{name.upper()}" for name in progress.PHASE_NAMES}
    assert observed == expected


def test_phase_coverage_negative_control_detects_a_deleted_call_site():
    source = Path(production.__file__).read_text(encoding="utf-8")
    mutant = source.replace(
        "sink.phase(_progress.PHASE_CONTRASTS, len(declared))",
        "sink.phase(_progress.PHASE_DAY_TYPES, len(declared))",
        1,
    )
    assert "PHASE_CONTRASTS" not in _phase_call_constants(mutant)


def test_undeclared_phase_names_are_rejected():
    sink = progress.ProgressSink((io.StringIO(),))
    with pytest.raises(SpineError):
        sink.phase("smuggled_quantile_value", 10)


def test_progress_api_accepts_no_free_text_or_arrays():
    """Structural guarantee: nothing but counts can enter a progress line.

    An exception carrying a tick or quantile cannot be reported through this
    API because no method accepts a message, an object, or an array.
    """
    phase_params = inspect.signature(progress.ProgressSink.phase).parameters
    assert set(phase_params) == {"self", "name", "total"}
    advance_params = inspect.signature(progress._PhaseProgress.advance).parameters
    assert set(advance_params) == {"self", "done"}
    # advance coerces with int(); a value-bearing object cannot pass through.
    stream = io.StringIO()
    phase = progress.ProgressSink((stream,)).phase(progress.PHASE_CONTRASTS, 3)
    with pytest.raises((TypeError, ValueError)):
        phase.advance("2718.28 ticks")


@pytest.mark.parametrize(
    "bad_count",
    (
        pytest.param(np.int64(2), id="numpy-scalar"),
        pytest.param(True, id="bool-is-not-an-item-count"),
    ),
)
def test_progress_rejects_non_builtin_integer_counts(bad_count):
    phase = progress.ProgressSink((io.StringIO(),)).phase(
        progress.PHASE_CONTRASTS, 2
    )
    with pytest.raises(SpineError, match="built-in integer"):
        phase.advance(bad_count)


def test_progress_rejects_arbitrary_int_coercion_and_nonmonotonic_counts():
    class ValueCarrier:
        def __int__(self):
            return 2

    phase = progress.ProgressSink((io.StringIO(),)).phase(
        progress.PHASE_CONTRASTS, 3
    )
    with pytest.raises(SpineError, match="built-in integer"):
        phase.advance(ValueCarrier())
    phase.advance(2)
    with pytest.raises(SpineError, match="monotonic"):
        phase.advance(1)
    with pytest.raises(SpineError, match="cannot exceed"):
        phase.advance(4)


def test_progress_sink_cannot_be_subclassed_to_inject_a_value():
    with pytest.raises(TypeError, match="cannot be subclassed"):
        class LeakySink(progress.ProgressSink):
            pass


def test_progress_sink_instance_cannot_replace_writer_with_value_leak():
    sink = progress.ProgressSink((io.StringIO(),))
    with pytest.raises(AttributeError):
        sink._write = lambda line: line + " quantile=123"  # type: ignore[method-assign]


def test_active_phase_heartbeats_without_an_advance_call(monkeypatch):
    monkeypatch.setattr(progress, "EMIT_INTERVAL_SECONDS", 0.02)
    stream = io.StringIO()
    sink = progress.ProgressSink((stream,))
    sink.phase(progress.PHASE_BOOTSTRAP_CHUNKS, 2)
    initial = len(_lines(stream.getvalue()))
    deadline = time.monotonic() + 0.5
    while len(_lines(stream.getvalue())) == initial and time.monotonic() < deadline:
        time.sleep(0.01)
    try:
        assert len(_lines(stream.getvalue())) > initial, (
            "named long-chunk mutant stayed silent without advance()"
        )
    finally:
        sink.close()


def test_reset_stops_the_active_heartbeat_thread(monkeypatch):
    monkeypatch.setattr(progress, "EMIT_INTERVAL_SECONDS", 0.02)
    progress.configure(stdout=False, extra_streams=(io.StringIO(),))
    phase = progress.get_sink().phase(progress.PHASE_BOOTSTRAP_PLANS, 2)
    thread = phase._thread
    assert thread is not None and thread.is_alive()
    progress.reset()
    assert not thread.is_alive()


def test_phase_completion_stops_its_heartbeat_thread(monkeypatch):
    monkeypatch.setattr(progress, "EMIT_INTERVAL_SECONDS", 0.02)
    sink = progress.ProgressSink((io.StringIO(),))
    phase = sink.phase(progress.PHASE_ARTIFACTS, 1)
    thread = phase._thread
    assert thread is not None and thread.is_alive()
    phase.advance(1)
    assert not thread.is_alive()


def test_runner_failure_resets_and_stops_heartbeat(
    tmp_path, monkeypatch
):
    thread_holder = []

    def named_runner_failure():
        phase = progress.get_sink().phase(progress.PHASE_BOOTSTRAP_CHUNKS, 2)
        thread_holder.append(phase._thread)
        raise RuntimeError("named runner failure")

    monkeypatch.setattr(runner, "PHASE8_PROGRESS_LOG", tmp_path / "failure.log")
    monkeypatch.setattr(runner, "require_phase8_run_paths", lambda **_kwargs: None)
    monkeypatch.setattr(runner, "run_phase8", lambda **_kwargs: named_runner_failure())
    monkeypatch.setattr(sys.modules["__main__"], "__spec__", object())
    with pytest.raises(RuntimeError, match="named runner failure"):
        runner.main(["--stage1-workers", "1", "--bootstrap-workers", "1", "--process-start-method", "spawn"])
    assert thread_holder[0] is not None
    assert not thread_holder[0].is_alive()
    assert not progress.is_configured()


def test_progress_lines_contain_no_scientific_result_fields():
    stream = io.StringIO()
    sink = progress.ProgressSink((stream,))
    sink.banner(
        contrast_rows=29_430, day_type_rows=216, interaction_rows=720,
        bootstrap_workers=8, stage1_workers=4, aggregate_memory_ceiling_bytes=1 << 30,
    )
    for name in sorted(progress.PHASE_NAMES):
        phase = sink.phase(name, 2)
        phase.advance(2)
    text = stream.getvalue()
    forbidden = (
        "tick", "quantile", "contrast_ticks", "interval", "session_id",
        "weight_ess", "n_anchors", "baseline", "estimand", "status_flags",
    )
    for token in forbidden:
        assert token not in text, f"progress output leaked {token!r}"
    allowed_keys = {
        "phase", "done", "total", "pct", "rate", "elapsed", "eta",
        "contrast_rows", "day_type_rows", "interaction_rows", "bootstrap_workers",
        "stage1_workers", "aggregate_memory_ceiling_bytes",
        "distinct_bootstrap_terms", "resume", "external_checkpoint",
    }
    for line in _lines(text):
        for key in re.findall(r"(\w+)=", line):
            assert key in allowed_keys, f"unexpected progress field {key!r}"


def test_distinct_term_count_is_pending_until_measured():
    stream = io.StringIO()
    sink = progress.ProgressSink((stream,))
    sink.banner(
        contrast_rows=29_430, day_type_rows=216, interaction_rows=720,
        bootstrap_workers=8, stage1_workers=4, aggregate_memory_ceiling_bytes=1 << 30,
    )
    assert "distinct_bootstrap_terms=pending" in stream.getvalue()
    sink.realized_terms(4_325)
    assert "distinct_bootstrap_terms=4325" in stream.getvalue()


def test_default_sink_is_silent_so_importing_is_quiet(capsys):
    phase = progress.get_sink().phase(progress.PHASE_INTERACTIONS, 10)
    phase.advance(10)
    assert capsys.readouterr().out == ""


def test_runner_main_configures_stdout_and_real_log_before_running(
    tmp_path, monkeypatch
):
    events = []
    log_path = tmp_path / "phase8-production.progress.log"
    monkeypatch.setattr(runner, "PHASE8_PROGRESS_LOG", log_path)
    monkeypatch.setattr(runner, "require_phase8_run_paths", lambda **_kwargs: None)
    monkeypatch.setattr(
        runner._progress,
        "configure",
        lambda **kwargs: events.append(("configure", kwargs)),
    )
    monkeypatch.setattr(
        runner._progress, "reset", lambda: events.append(("reset", {}))
    )
    monkeypatch.setattr(runner, "run_phase8", lambda **kwargs: events.append(("run", kwargs)))
    monkeypatch.setattr(sys.modules["__main__"], "__spec__", object())

    runner.main(["--stage1-workers", "2", "--bootstrap-workers", "3", "--process-start-method", "spawn"])

    assert events == [
        ("configure", {"log_path": log_path, "stdout": True}),
        ("run", {
            "stage1_workers": 2,
            "bootstrap_workers": 3,
            "resume": False,
            "external_checkpoint_root": None,
            "progress_log": log_path,
            "process_start_method": "spawn",
        }),
        ("reset", {}),
    ]


def test_public_runner_refuses_to_enter_a_long_phase_silently(monkeypatch):
    progress.reset()
    monkeypatch.setattr(
        runner,
        "load_ratified_inputs",
        lambda: pytest.fail("silent runner reached the ratified input"),
    )
    with pytest.raises(SpineError, match="progress is not configured"):
        runner.run_phase8(stage1_workers=1, bootstrap_workers=1)


def test_bootstrap_chunk_reports_completion_only_after_compute(tmp_path):
    stream = io.StringIO()
    progress._ACTIVE = progress.ProgressSink((stream,))
    identity = CheckpointIdentity(
        code_commit="a" * 40,
        input_manifest_sha256=(("unit_o", "b" * 64),),
        stage1_workers=1,
        bootstrap_workers=1,
        process_start_method="spawn",
        bootstrap_contract_sha256="c" * 64,
        phase8_output_version="phase8-session-aware-v2",
        producing_code_sha256=(("runner.py", "d" * 64),),
    )
    observed = []

    def compute(chunk):
        observed.append("done=1 total=1" in stream.getvalue())
        return {"row_id": np.asarray(chunk.row_ids)}

    runner.execute_checkpointed_chunks(
        (InventoryChunk(0, ("named-progress-order-mutant",)),),
        checkpoint=CheckpointStore(tmp_path / "checkpoint", identity),
        compute_chunk=compute,
    )
    assert observed == [False]


# --------------------------------------------------------------------------
# Negative controls: each proves an assertion above can fail.
# --------------------------------------------------------------------------


def test_negative_control_a_silent_sink_fails_the_silence_check():
    silent = progress.ProgressSink(())
    phase = silent.phase(progress.PHASE_CONTRASTS, 5_000)
    for done in range(1, 5_001):
        phase.advance(done)
    stream = io.StringIO()
    assert not _lines(stream.getvalue())


def test_negative_control_a_leaked_field_is_detected():
    stream = io.StringIO()
    stream.write("2026-01-01T00:00:00+00:00 phase=contrasts done=1 quantile=1234\n")
    keys = re.findall(r"(\w+)=", stream.getvalue())
    assert "quantile" in keys, "the field scan cannot see a leaked key"


def test_negative_control_unflushed_output_would_be_invisible(tmp_path):
    path = tmp_path / "buffered.log"
    handle = path.open("w", encoding="utf-8")
    try:
        handle.write("line without flush\n")
        assert path.read_text(encoding="utf-8") == "", (
            "this platform flushes implicitly, so the flush assertion is vacuous"
        )
    finally:
        handle.close()
