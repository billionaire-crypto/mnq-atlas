"""Synthetic operational witnesses for Phase 8 v2 resumability and bounds."""

from __future__ import annotations

import io
import gc
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from typing import Any

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.phase8 import runner as runner_module
from mnq_lab.phase8.artifacts import CheckpointIdentity, CheckpointStore
from mnq_lab.phase8 import uncertainty as uncertainty_module
from mnq_lab.phase8.runner import (
    AggregateMemoryGate,
    DEFAULT_AGGREGATE_MEMORY_SAMPLE_INTERVAL_SECONDS,
    InventoryChunk,
    MemoryMeasurement,
    RunnerOperatingConfig,
    _linux_process_tree_pss,
    _linux_process_tree_rss,
    execute_checkpointed_chunks,
    probe_effective_cpu_capacity,
    resolve_effective_cpu_capacity,
)
from mnq_lab.production.phase8_v2_run_receipt import (
    MINIMUM_AVAILABLE_MEMORY_BYTES,
    MINIMUM_FREE_DISK_BYTES,
    PRODUCTION_COMMAND,
    _preflight_phase8_run,
    _production_child_command,
    _run_with_receipt,
    main as receipt_main,
)


def _identity(*, stage1_workers: int = 2, bootstrap_workers: int = 3) -> CheckpointIdentity:
    return CheckpointIdentity(
        code_commit="a" * 40,
        input_manifest_sha256=(("run", "b" * 64), ("unit_o", "c" * 64), ("phase7", "d" * 64)),
        stage1_workers=stage1_workers,
        bootstrap_workers=bootstrap_workers,
        process_start_method="spawn",
        bootstrap_contract_sha256="e" * 64,
        phase8_output_version="phase8-session-aware-v2",
        producing_code_sha256=(("mnq_lab/phase8/runner.py", "f" * 64),),
    )


def _linux_probe(*, os_count: int = 384, affinity: int = 192, quota: str = "max 100000", cpuset: str = "0-191"):
    values = {
        "/proc/self/cgroup": "0::/phase8\n",
        "/sys/fs/cgroup/phase8/cpu.max": quota + "\n",
        "/sys/fs/cgroup/phase8/cpuset.cpus.effective": cpuset + "\n",
    }

    def reader(path: Path) -> str:
        try:
            return values[path.as_posix()]
        except KeyError as exc:
            raise OSError(path) from exc

    return probe_effective_cpu_capacity(
        platform_name="Linux", os_cpu_count_fn=lambda: os_count,
        affinity_fn=lambda: range(affinity), reader=reader,
        exists=lambda path: path.as_posix() in values,
    )


def test_cpu_capacity_uses_affinity_when_os_count_is_larger_and_rejects_overrequest():
    observed = _linux_probe()
    assert observed["os_cpu_count"] == 384
    assert observed["affinity_count"] == 192
    assert observed["effective_cpu_count"] == 192
    RunnerOperatingConfig(stage1_workers=191, bootstrap_workers=192, effective_cpu_count=192)
    with pytest.raises(SpineError, match="exceed effective"):
        RunnerOperatingConfig(stage1_workers=193, bootstrap_workers=1, effective_cpu_count=192)


def test_cgroup_quota_smaller_than_affinity_is_the_effective_limit():
    observed = _linux_probe(quota="6400000 100000")
    assert observed["affinity_count"] == 192
    assert observed["cgroup_quota_count"] == 64
    assert observed["effective_cpu_count"] == 64


@pytest.mark.parametrize("bad", (None, 0, True, "192"))
def test_unknown_or_invalid_cpu_and_worker_values_fail_closed(bad):
    with pytest.raises(SpineError):
        resolve_effective_cpu_capacity({"os_cpu_count": bad, "affinity_cpus": (0,)})
    with pytest.raises((SpineError, TypeError)):
        RunnerOperatingConfig(stage1_workers=bad, bootstrap_workers=1, effective_cpu_count=2)


def test_cpu_capacity_probe_unreadable_membership_fails_closed():
    with pytest.raises(SpineError, match="cgroup membership"):
        probe_effective_cpu_capacity(
            platform_name="Linux", os_cpu_count_fn=lambda: 8,
            affinity_fn=lambda: range(8),
            reader=lambda _path: (_ for _ in ()).throw(OSError("denied")),
        )


def test_windows_cpu_capacity_is_affinity_bound_and_fails_when_affinity_is_empty():
    observed = probe_effective_cpu_capacity(
        platform_name="Windows", os_cpu_count_fn=lambda: 64,
        affinity_fn=lambda: range(16),
    )
    assert observed["effective_cpu_count"] == 16
    with pytest.raises(SpineError, match="affinity"):
        probe_effective_cpu_capacity(
            platform_name="Windows", os_cpu_count_fn=lambda: 64,
            affinity_fn=lambda: (),
        )


def test_memory_gate_fails_for_unavailable_metric_breach_and_growth():
    unavailable = AggregateMemoryGate(
        ceiling_bytes=500, launch_minimum_available_bytes=700,
        aggregate_sampler=lambda: (_ for _ in ()).throw(OSError("unreadable")),
        available_sampler=lambda: 700,
    )
    with pytest.raises(SpineError, match="measurement failed"):
        unavailable.sample()
    samples = iter((MemoryMeasurement(100, "pss", "synthetic"), MemoryMeasurement(300, "pss", "synthetic"), MemoryMeasurement(600, "pss", "synthetic")))
    growing = AggregateMemoryGate(
        ceiling_bytes=500, launch_minimum_available_bytes=700,
        aggregate_sampler=lambda: next(samples), available_sampler=lambda: 700,
    )
    assert growing.sample() == 100
    assert growing.sample() == 300
    with pytest.raises(SpineError, match="exceeded ceiling"):
        growing.sample()
    assert growing.peak_bytes == 600
    assert growing.metric == "pss" and growing.source == "synthetic"


def test_default_pss_sampling_interval_avoids_continuous_page_table_walks():
    samples = 0

    def sample():
        nonlocal samples
        samples += 1
        return MemoryMeasurement(100, "pss", "synthetic")

    gate = AggregateMemoryGate(
        ceiling_bytes=500,
        launch_minimum_available_bytes=700,
        aggregate_sampler=sample,
        available_sampler=lambda: 700,
    )
    assert DEFAULT_AGGREGATE_MEMORY_SAMPLE_INTERVAL_SECONDS == 30.0
    assert gate.monitor_interval_seconds == 30.0
    gate.start()
    try:
        time.sleep(0.7)
        assert samples == 1
    finally:
        gate.stop()
    assert gate.monitor_running is False
    # Negative control: the former 0.5-second cadence would have sampled at
    # least twice during the same witness window.


def test_memory_samples_are_serialized_across_threads():
    entered = threading.Event()
    release = threading.Event()
    state_lock = threading.Lock()
    calls = 0
    active = 0
    max_active = 0

    def sample():
        nonlocal calls, active, max_active
        with state_lock:
            calls += 1
            active += 1
            max_active = max(max_active, active)
            position = calls
        if position == 1:
            entered.set()
            assert release.wait(2)
        with state_lock:
            active -= 1
        return 100

    gate = AggregateMemoryGate(
        ceiling_bytes=500, launch_minimum_available_bytes=700,
        aggregate_sampler=sample, available_sampler=lambda: 700,
    )
    first = threading.Thread(target=gate.sample)
    second = threading.Thread(target=gate.sample)
    first.start()
    assert entered.wait(1)
    second.start()
    time.sleep(0.05)
    assert calls == 1
    release.set()
    first.join(1)
    second.join(1)
    assert not first.is_alive() and not second.is_alive()
    assert calls == 2
    assert max_active == 1
    assert gate.peak_bytes == 100


def test_memory_sample_durations_drive_evidence_and_stop_timeout(monkeypatch):
    clock = iter((10.0, 10.25, 20.0, 20.75))
    monkeypatch.setattr(runner_module.time, "monotonic", lambda: next(clock))
    gate = AggregateMemoryGate(
        ceiling_bytes=500, launch_minimum_available_bytes=700,
        aggregate_sampler=lambda: 100, available_sampler=lambda: 700,
        monitor_interval_seconds=7.0, hard_stop_grace_seconds=5.0,
    )

    assert gate.sample() == 100
    assert gate.sample() == 100
    assert gate.sample_count == 2
    assert gate.sample_total_seconds == 1.0
    assert gate.sample_max_seconds == 0.75
    assert gate.sample_mean_seconds == 0.5
    assert gate.stop_join_timeout_seconds == 13.5
    assert gate.sampling_observation() == {
        "aggregate_memory_sample_interval_seconds": 7.0,
        "aggregate_memory_sample_count": 2,
        "aggregate_memory_sample_total_seconds": 1.0,
        "aggregate_memory_sample_mean_seconds": 0.5,
        "aggregate_memory_sample_max_seconds": 0.75,
    }
    # Negative controls: a constant-backed interval would report 30.0, and
    # the abb55fb timeout ignored the observed 0.75-second measurement.
    assert gate.monitor_interval_seconds != 30.0
    assert gate.stop_join_timeout_seconds != 12.0


def test_memory_monitor_rejects_double_start_and_allows_clean_restart():
    gate = AggregateMemoryGate(
        ceiling_bytes=500, launch_minimum_available_bytes=700,
        aggregate_sampler=lambda: 100, available_sampler=lambda: 700,
    )
    gate.start()
    assert gate.monitor_running is True
    with pytest.raises(SpineError, match="already running"):
        gate.start()
    gate.stop()
    assert gate.monitor_running is False
    gate.start()
    assert gate.monitor_running is True
    gate.stop()
    assert gate.monitor_running is False
    assert gate.sample_count == 2


def test_memory_monitor_fails_closed_when_sampler_outlives_measured_timeout():
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def sample():
        nonlocal calls
        calls += 1
        if calls > 1:
            entered.set()
            assert release.wait(5)
        return 100

    gate = AggregateMemoryGate(
        ceiling_bytes=500, launch_minimum_available_bytes=700,
        aggregate_sampler=sample, available_sampler=lambda: 700,
        monitor_interval_seconds=0.01, hard_stop_grace_seconds=0.01,
    )
    gate.start()
    assert entered.wait(1)
    try:
        with pytest.raises(SpineError, match="monitor did not stop"):
            gate.stop()
        assert gate.monitor_running is True
    finally:
        release.set()
    deadline = time.monotonic() + 1.0
    while gate.monitor_running and time.monotonic() < deadline:
        time.sleep(0.01)
    assert gate.monitor_running is False


def test_memory_monitor_interrupts_and_arms_hard_stop_on_breach():
    samples = iter((100, 600, 700, 800))
    interrupted = threading.Event()
    terminated = threading.Event()
    recorded = []
    gate = AggregateMemoryGate(
        ceiling_bytes=500,
        launch_minimum_available_bytes=700,
        aggregate_sampler=lambda: next(samples, 800),
        available_sampler=lambda: 700,
        failure_interrupt=lambda _failure: interrupted.set(),
        failure_terminate=lambda _failure: terminated.set(),
        failure_recorder=lambda current, peak, ceiling: recorded.append(
            (current, peak, ceiling)
        ),
        monitor_interval_seconds=0.01,
        hard_stop_grace_seconds=0.06,
    )

    gate.start()
    assert interrupted.wait(1)
    assert terminated.wait(1)
    assert recorded[0] == (600, 600, 500)
    assert recorded[-1] == (800, 800, 500)
    assert [peak for _current, peak, _ceiling in recorded] == sorted(
        peak for _current, peak, _ceiling in recorded
    )
    with pytest.raises(SpineError, match="exceeded ceiling"):
        gate.stop()


def test_memory_monitor_cancels_hard_stop_after_interrupt_unwinds():
    samples = iter((100, 600))
    interrupted = threading.Event()
    terminated = threading.Event()
    gate = AggregateMemoryGate(
        ceiling_bytes=500,
        launch_minimum_available_bytes=700,
        aggregate_sampler=lambda: next(samples),
        available_sampler=lambda: 700,
        failure_interrupt=lambda _failure: interrupted.set(),
        failure_terminate=lambda _failure: terminated.set(),
        monitor_interval_seconds=0.01,
        hard_stop_grace_seconds=0.2,
    )

    gate.start()
    assert interrupted.wait(1)
    with pytest.raises(SpineError, match="exceeded ceiling"):
        gate.stop()
    time.sleep(0.25)
    assert not terminated.is_set()


def test_memory_monitor_does_not_invent_peak_evidence_for_metric_failure():
    samples = iter((100, SpineError("unreadable")))
    recorded = []
    interrupted = threading.Event()

    def sample():
        value = next(samples, SpineError("unreadable"))
        if isinstance(value, Exception):
            raise value
        return value

    gate = AggregateMemoryGate(
        ceiling_bytes=500,
        launch_minimum_available_bytes=700,
        aggregate_sampler=sample,
        available_sampler=lambda: 700,
        failure_interrupt=lambda _failure: interrupted.set(),
        failure_recorder=lambda current, peak, ceiling: recorded.append(
            (current, peak, ceiling)
        ),
        monitor_interval_seconds=0.01,
        hard_stop_grace_seconds=0.2,
    )
    gate.start()
    assert interrupted.wait(1)
    with pytest.raises(SpineError, match="monitor failed closed"):
        gate.stop()
    assert recorded == []


def test_linux_aggregate_memory_uses_pss_not_reclaimable_cgroup_file_cache(
    tmp_path, monkeypatch,
):
    cgroup = tmp_path / "cgroup"
    cgroup.mkdir()
    (cgroup / "memory.current").write_text(str(7 * 1024**3), encoding="ascii")
    monkeypatch.setattr(runner_module.os, "name", "posix")
    monkeypatch.setattr(runner_module.sys, "platform", "linux")
    monkeypatch.setattr(
        runner_module, "_linux_cgroup_locations", lambda: {"v2": cgroup}
    )
    monkeypatch.setattr(
        runner_module, "_linux_process_tree_pss", lambda _pid: 64 * 1024**2
    )

    measured = runner_module.aggregate_memory_measurement()

    assert measured == MemoryMeasurement(
        64 * 1024**2,
        "process_tree_pss_bytes",
        "/proc/<pid>/smaps_rollup",
    )


def test_linux_aggregate_memory_fails_closed_when_pss_is_unreadable(monkeypatch):
    monkeypatch.setattr(runner_module.os, "name", "posix")
    monkeypatch.setattr(runner_module.sys, "platform", "linux")
    monkeypatch.setattr(
        runner_module,
        "_linux_process_tree_pss",
        lambda _pid: (_ for _ in ()).throw(SpineError("PSS unreadable")),
    )

    with pytest.raises(SpineError, match="PSS unreadable"):
        runner_module.aggregate_memory_measurement()


def _fork_wait(event):
    event.wait(10)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux fork/PSS witness")
def test_fork_shared_pages_are_double_counted_by_rss_but_not_pss():
    shared = bytearray(32 * 1024**2)
    for offset in range(0, len(shared), 4096):
        shared[offset] = 1
    context = multiprocessing.get_context("fork")
    event = context.Event()
    children = [context.Process(target=_fork_wait, args=(event,)) for _ in range(2)]
    for child in children:
        child.start()
    try:
        deadline = time.monotonic() + 5
        while any(not child.is_alive() for child in children) and time.monotonic() < deadline:
            time.sleep(0.01)
        rss = _linux_process_tree_rss(os.getpid())
        pss = _linux_process_tree_pss(os.getpid())
        assert rss > pss + len(shared)
    finally:
        event.set()
        for child in children:
            child.join(10)


def _synthetic_stage1_run(store: CheckpointStore, calls: list[int], *, interrupt: bool = False) -> bytes:
    pieces = []
    for index in range(2):
        name = f"partition-{index:06d}"
        identity = (str(index) * 64)[:64]
        if store.has_stage1_unit(name):
            value = store.read_stage1_unit(
                name, declared_indices=(index,), declared_identity_sha256=identity,
                row_ids=(f"row-{index}",),
            )
        else:
            calls.append(index)
            value = {"row_id": np.asarray([f"row-{index}"]), "value": np.asarray([index], dtype=np.int64)}
            store.write_stage1_unit(
                name, value, declared_indices=(index,),
                declared_identity_sha256=identity, row_ids=(f"row-{index}",),
            )
        pieces.append(value)
        if interrupt and index == 0:
            raise RuntimeError("synthetic host interruption")
    stream = io.BytesIO()
    np.savez(stream, **{
        key: np.concatenate([np.asarray(piece[key]) for piece in pieces])
        for key in ("row_id", "value")
    })
    return stream.getvalue()


def test_stage1_interrupted_resume_is_byte_identical_and_skips_completed_unit(tmp_path):
    clean_calls: list[int] = []
    clean = _synthetic_stage1_run(CheckpointStore(tmp_path / "clean", _identity()), clean_calls)
    resumed_calls: list[int] = []
    resumed_root = tmp_path / "resume"
    with pytest.raises(RuntimeError, match="host interruption"):
        _synthetic_stage1_run(CheckpointStore(resumed_root, _identity()), resumed_calls, interrupt=True)
    resumed = _synthetic_stage1_run(CheckpointStore(resumed_root, _identity()), resumed_calls)
    assert resumed == clean
    assert clean_calls == [0, 1]
    assert resumed_calls == [0, 1], "completed partition 0 was recomputed"
    mutant = bytearray(resumed)
    mutant[-1] ^= 1
    assert bytes(mutant) != clean


def test_stage1_identity_array_manifest_and_staging_mutations_fail_closed(tmp_path):
    root = tmp_path / "checkpoint"
    store = CheckpointStore(root, _identity())
    _synthetic_stage1_run(store, [])
    with pytest.raises(SpineError, match="identity differs"):
        CheckpointStore(root, _identity(stage1_workers=3))
    unit = root / "stage1-partition-000000"
    array = unit / "array-000000.npy"
    payload = bytearray(array.read_bytes()); payload[-1] ^= 1; array.write_bytes(payload)
    with pytest.raises(SpineError, match="array hash differs"):
        store.read_stage1_unit(
            "partition-000000", declared_indices=(0,),
            declared_identity_sha256="0" * 64, row_ids=("row-0",),
        )
    other = tmp_path / "manifest"
    store2 = CheckpointStore(other, _identity())
    _synthetic_stage1_run(store2, [])
    manifest = other / "stage1-partition-000000/manifest.json"
    manifest.write_bytes(manifest.read_bytes() + b" ")
    with pytest.raises(SpineError, match="manifest is not canonical"):
        store2.read_stage1_unit(
            "partition-000000", declared_indices=(0,),
            declared_identity_sha256="0" * 64, row_ids=("row-0",),
        )
    incomplete = tmp_path / "incomplete"
    CheckpointStore(incomplete, _identity())
    (incomplete / ".stage1-partition-000000.staging").mkdir()
    with pytest.raises(SpineError, match="staging evidence"):
        CheckpointStore(incomplete, _identity())
    assert (incomplete / ".stage1-partition-000000.staging").is_dir()


def test_bootstrap_chunk_reuse_mutations_and_unexpected_inventory_fail_closed(tmp_path):
    chunks = (InventoryChunk(0, ("row-0",)), InventoryChunk(1, ("row-1",)))
    calls: list[int] = []

    def compute(chunk):
        calls.append(chunk.index)
        return {"row_id": np.asarray(chunk.row_ids), "value": np.asarray([chunk.index])}

    root = tmp_path / "chunks"
    store = CheckpointStore(root, _identity())
    execute_checkpointed_chunks(chunks, checkpoint=store, compute_chunk=compute)
    execute_checkpointed_chunks(chunks, checkpoint=CheckpointStore(root, _identity()), compute_chunk=compute)
    assert calls == [0, 1]
    array = root / "chunk-000000/00_row_id.npy"
    payload = bytearray(array.read_bytes()); payload[-1] ^= 1; array.write_bytes(payload)
    with pytest.raises(SpineError, match="column hash differs"):
        execute_checkpointed_chunks(chunks, checkpoint=CheckpointStore(root, _identity()), compute_chunk=compute)
    unexpected = tmp_path / "unexpected"
    CheckpointStore(unexpected, _identity())
    (unexpected / "chunk-999999").mkdir()
    with pytest.raises(SpineError, match="unexpected or duplicate"):
        execute_checkpointed_chunks(chunks, checkpoint=CheckpointStore(unexpected, _identity()), compute_chunk=compute)


def test_bootstrap_plans_are_rehashed_and_reused(monkeypatch, tmp_path):
    monkeypatch.setattr(uncertainty_module, "DRAWS_PER_BLOCK_LENGTH", 3)
    groups = np.repeat(np.arange(4, dtype=np.int32), 2)
    bundle = uncertainty_module._prepare_joint_plan_matrices(groups)
    contract = uncertainty_module.bootstrap_contract()
    root = tmp_path / "plans"
    store = CheckpointStore(root, _identity())
    store.write_plan_matrices(bundle)
    reused = CheckpointStore(root, _identity())
    loaded = reused.read_plan_matrices(contract)
    assert reused.reused_plans is True
    assert loaded.group_digest == bundle.group_digest
    del loaded, reused
    gc.collect()
    plan = root / "plans/00_session_multiplicities.npy"
    payload = bytearray(plan.read_bytes()); payload[-1] ^= 1; plan.write_bytes(payload)
    with pytest.raises(SpineError, match="matrix hash differs"):
        CheckpointStore(root, _identity()).read_plan_matrices(contract)


def test_external_mirror_recovers_local_loss_and_mutations_fail_closed(tmp_path):
    local, mirror = tmp_path / "local", tmp_path / "mirror"
    clean = _synthetic_stage1_run(CheckpointStore(local, _identity(), mirror_root=mirror), [])
    shutil.rmtree(local)
    recovered = _synthetic_stage1_run(CheckpointStore(local, _identity(), mirror_root=mirror), [])
    assert recovered == clean
    shutil.rmtree(local)
    array = mirror / "stage1-partition-000000/array-000000.npy"
    payload = bytearray(array.read_bytes()); payload[-1] ^= 1; array.write_bytes(payload)
    recovered_store = CheckpointStore(local, _identity(), mirror_root=mirror)
    with pytest.raises(SpineError, match="array hash differs"):
        _synthetic_stage1_run(recovered_store, [])
    incomplete_local, incomplete_mirror = tmp_path / "local2", tmp_path / "mirror2"
    CheckpointStore(incomplete_local, _identity(), mirror_root=incomplete_mirror)
    (incomplete_mirror / ".plans.staging").mkdir()
    with pytest.raises(SpineError, match="staging evidence"):
        CheckpointStore(incomplete_local, _identity(), mirror_root=incomplete_mirror)
    assert (incomplete_mirror / ".plans.staging").is_dir()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "protected.txt").write_text("immutable\n", encoding="utf-8")
    (repo / ".gitignore").write_text("output*\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "audit@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Audit Fixture"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "fixture"], check=True)
    return repo


def _paths(repo: Path):
    output = repo / "output"
    return output, repo / "output.staging", repo / "output.checkpoint", repo / "output.progress.log"


def _passing_preflight() -> dict[str, Any]:
    return {
        "repo_commit": None,
        "stage1_workers": 2, "bootstrap_workers": 3,
        "process_start_method": "spawn",
        "input_manifest_sha256": {"run": "a" * 64, "unit_o": "b" * 64, "phase7": "c" * 64},
    }


def _failed_receipt(tmp_path: Path, *, success: bool = False):
    repo = _repo(tmp_path)
    output, staging, checkpoint, progress = _paths(repo)
    body = [
        "from pathlib import Path", f"c=Path({str(checkpoint)!r})", "c.mkdir()",
        "(c/'identity.json').write_bytes(b'{}\\n')",
        f"Path({str(progress)!r}).write_text('attempt one\\n')",
    ]
    if success:
        body.extend((f"o=Path({str(output)!r})", "o.mkdir()", "(o/'manifest.json').write_text('{}\\n')"))
    body.append(f"raise SystemExit({0 if success else 7})")
    preflight = _passing_preflight()
    preflight["repo_commit"] = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, check=True, text=True
    ).stdout.strip()
    receipt_root = tmp_path / "prior-receipt"
    receipt, _ = _run_with_receipt(
        receipt_root, stage1_workers=2, bootstrap_workers=3,
        repo_root=repo, command=(sys.executable, "-c", ";".join(body)),
        protected_paths=("protected.txt",), output_root=output,
        staging_root=staging, checkpoint_root=checkpoint, progress_log=progress,
        preflight=lambda: preflight,
    )
    return repo, receipt_root, receipt


def _resume_probes():
    return {
        "memory_sampler": lambda: MINIMUM_AVAILABLE_MEMORY_BYTES,
        "physical_memory_sampler": lambda: 16 * 1024**3,
        "aggregate_memory_probe": lambda: MemoryMeasurement(1024, "synthetic", "test"),
        "cpu_probe": lambda: {"effective_cpu_count": 8, "os_cpu_count": 8, "affinity_cpus": tuple(range(8))},
        "disk_sampler": lambda _path: MINIMUM_FREE_DISK_BYTES,
        "process_probe": lambda: (),
        "certificate_validator": lambda: {"certificate_id": "synthetic"},
        "input_manifest_probe": lambda: {"run": "a" * 64, "unit_o": "b" * 64, "phase7": "c" * 64},
    }


def test_explicit_resume_validates_failed_prior_and_cross_binds_it(tmp_path):
    repo, prior, _receipt = _failed_receipt(tmp_path)
    output, staging, checkpoint, progress = _paths(repo)
    resume_progress = progress.with_name(progress.name + ".resume-test")
    record = _preflight_phase8_run(
        stage1_workers=2, bootstrap_workers=3, resume=True,
        prior_receipt_root=prior, repo_root=repo, output_root=output,
        staging_root=staging, checkpoint_root=checkpoint,
        progress_log=resume_progress, **_resume_probes(),
    )
    assert record["mode"] == "resume"
    assert record["aggregate_memory_sample_interval_seconds"] == 30.0
    assert len(record["prior_attempt"]["prior_receipt_sha256"]) == 64
    assert progress.read_text(encoding="utf-8") == "attempt one\n"
    assert not resume_progress.exists()


@pytest.mark.parametrize("mutation", ("workers", "inputs", "output", "staging", "progress"))
def test_resume_mutations_fail_closed_and_preserve_evidence(tmp_path, mutation):
    repo, prior, _receipt = _failed_receipt(tmp_path)
    output, staging, checkpoint, progress = _paths(repo)
    kwargs = _resume_probes()
    stage1 = 2
    resume_progress = progress.with_name(progress.name + ".resume-test")
    if mutation == "workers":
        stage1 = 1
    elif mutation == "inputs":
        kwargs["input_manifest_probe"] = lambda: {"run": "f" * 64, "unit_o": "b" * 64, "phase7": "c" * 64}
    elif mutation == "output":
        output.mkdir()
    elif mutation == "staging":
        staging.mkdir()
    else:
        resume_progress.write_text("must not overwrite\n", encoding="utf-8")
    with pytest.raises(SpineError):
        _preflight_phase8_run(
            stage1_workers=stage1, bootstrap_workers=3, resume=True,
            prior_receipt_root=prior, repo_root=repo, output_root=output,
            staging_root=staging, checkpoint_root=checkpoint,
            progress_log=resume_progress, **kwargs,
        )
    assert prior.is_dir() and progress.is_file()
    if mutation == "progress":
        assert resume_progress.read_text(encoding="utf-8") == "must not overwrite\n"


def test_resume_rejects_successful_receipt_changed_commit_and_missing_prior(tmp_path):
    success_root = tmp_path / "success"
    success_root.mkdir()
    repo, prior, _ = _failed_receipt(success_root, success=True)
    output, staging, checkpoint, progress = _paths(repo)
    shutil.rmtree(output)
    common = dict(
        stage1_workers=2, bootstrap_workers=3, resume=True,
        repo_root=repo, output_root=output, staging_root=staging,
        checkpoint_root=checkpoint,
        progress_log=progress.with_name(progress.name + ".resume-test"),
        **_resume_probes(),
    )
    with pytest.raises(SpineError, match="successful prior"):
        _preflight_phase8_run(prior_receipt_root=prior, **common)
    failed_root = tmp_path / "changed"
    failed_root.mkdir()
    repo2, prior2, _ = _failed_receipt(failed_root)
    subprocess.run(["git", "-C", str(repo2), "commit", "--allow-empty", "-q", "-m", "changed"], check=True)
    output2, staging2, checkpoint2, progress2 = _paths(repo2)
    with pytest.raises(SpineError, match="run commit differs"):
        _preflight_phase8_run(
            prior_receipt_root=prior2,
            stage1_workers=2, bootstrap_workers=3, resume=True,
            repo_root=repo2, output_root=output2, staging_root=staging2,
            checkpoint_root=checkpoint2,
            progress_log=progress2.with_name(progress2.name + ".resume-test"),
            **_resume_probes(),
        )
    with pytest.raises(SpineError, match="prior receipt"):
        _preflight_phase8_run(prior_receipt_root=None, **common)


def test_external_root_inside_repository_and_existing_new_receipt_fail_closed(tmp_path):
    repo = _repo(tmp_path)
    output, staging, checkpoint, progress = _paths(repo)
    with pytest.raises(SpineError, match="outside the repository"):
        _preflight_phase8_run(
            stage1_workers=2, bootstrap_workers=3,
            external_checkpoint_root=repo / "mirror",
            repo_root=repo, output_root=output, staging_root=staging,
            checkpoint_root=checkpoint, progress_log=progress,
            **_resume_probes(),
        )
    existing = tmp_path / "existing-receipt"
    existing.mkdir()
    with pytest.raises(SpineError):
        _run_with_receipt(
            existing, stage1_workers=2, bootstrap_workers=3,
            repo_root=repo, command=(sys.executable, "-c", "pass"),
            protected_paths=("protected.txt",), output_root=output,
            staging_root=staging, checkpoint_root=checkpoint, progress_log=progress,
            preflight=lambda: _passing_preflight(),
        )


def test_preflight_only_launches_no_child_and_creates_no_requested_paths(tmp_path, monkeypatch, capsys):
    receipt = tmp_path / "unused-receipt"
    output = tmp_path / "unused-output"
    called = []
    monkeypatch.setattr(
        "mnq_lab.production.phase8_v2_run_receipt._preflight_phase8_run",
        lambda **_kwargs: {"mode": "fresh", "phase8_child_launched": False},
    )
    monkeypatch.setattr(
        "mnq_lab.production.phase8_v2_run_receipt.subprocess.Popen",
        lambda *_args, **_kwargs: called.append("Popen"),
    )
    receipt_main([
        "--stage1-workers", "2", "--bootstrap-workers", "3",
        "--receipt-root", str(receipt), "--preflight-only",
    ])
    assert json.loads(capsys.readouterr().out)["phase8_child_launched"] is False
    assert called == []
    assert not receipt.exists() and not output.exists()


def test_wrapper_invokes_popen_exactly_once_and_never_retries(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    output, staging, checkpoint, progress = _paths(repo)
    calls = []

    original_popen = subprocess.Popen

    class FailedChild:
        def __init__(self, *args, **kwargs):
            calls.append((args, kwargs))

        def wait(self):
            return 7

    def selective_popen(*args, **kwargs):
        command = args[0] if args else kwargs.get("args")
        if list(command) == [sys.executable, "-c", "pass"]:
            return FailedChild(*args, **kwargs)
        return original_popen(*args, **kwargs)

    monkeypatch.setattr(
        "mnq_lab.production.phase8_v2_run_receipt.subprocess.Popen", selective_popen
    )
    preflight = _passing_preflight()
    preflight.pop("repo_commit")
    receipt, exit_code = _run_with_receipt(
        tmp_path / "one-attempt-receipt", stage1_workers=2, bootstrap_workers=3,
        repo_root=repo, command=(sys.executable, "-c", "pass"),
        protected_paths=("protected.txt",), output_root=output,
        staging_root=staging, checkpoint_root=checkpoint, progress_log=progress,
        preflight=lambda: preflight,
    )
    assert len(calls) == 1
    assert calls[0][1]["shell"] is False
    assert exit_code == receipt["child_exit_code"] == 7


def test_child_argv_binds_workers_without_shell_interpolation():
    command = _production_child_command(
        PRODUCTION_COMMAND, stage1_workers=17, bootstrap_workers=29,
        process_start_method="fork", resume=True,
        external_checkpoint_root=Path("C:/durable/checkpoint"),
        progress_log=Path("C:/repo/output.progress.log.resume-test"),
    )
    assert command[command.index("--stage1-workers") + 1] == "17"
    assert command[command.index("--bootstrap-workers") + 1] == "29"
    assert command.count("--resume") == 1
