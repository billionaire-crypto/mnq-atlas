"""Windows peak-working-set telemetry and fail-closed preflight tests."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from mnq_lab import SpineError
from mnq_lab.production import first_exploration_run as run_module
from mnq_lab.production.first_exploration_run import _peak_process_memory_bytes
from mnq_lab.production.first_exploration_run import (
    FREE_MEMORY_PREFLIGHT_BYTES,
    PEAK_MEMORY_CEILING_BYTES,
    _enforce_free_memory_preflight,
    _enforce_peak_memory_ceiling,
    _free_physical_memory_bytes,
)


_PLAUSIBLE_PROCESS_FLOOR_BYTES = 4 * 1024 * 1024
_MEMORY_PREREGISTRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "MEMORY_CEILING_V2_PREREGISTRATION.md"
)
_MEMORY_PREREGISTRATION_BYTES = 9_346
_MEMORY_PREREGISTRATION_SHA256 = (
    "76e2bc35e2eef1494ae3328d8099248e2fd1e8936b17ede9d3acc4ada0b2e037"
)


def test_memory_ceiling_v2_preregistration_raw_bytes_are_pinned() -> None:
    payload = _MEMORY_PREREGISTRATION_PATH.read_bytes()

    assert len(payload) == _MEMORY_PREREGISTRATION_BYTES
    assert hashlib.sha256(payload).hexdigest() == _MEMORY_PREREGISTRATION_SHA256
    assert hashlib.sha256(payload[:-1]).hexdigest() != _MEMORY_PREREGISTRATION_SHA256
    mutated = bytearray(payload)
    mutated[100] ^= 1
    assert hashlib.sha256(mutated).hexdigest() != _MEMORY_PREREGISTRATION_SHA256


def test_peak_process_memory_returns_positive_builtin_int() -> None:
    peak = _peak_process_memory_bytes()

    assert type(peak) is int
    assert peak > _PLAUSIBLE_PROCESS_FLOOR_BYTES


def test_free_physical_memory_returns_positive_builtin_int() -> None:
    available = _free_physical_memory_bytes()

    assert type(available) is int
    assert available > _PLAUSIBLE_PROCESS_FLOOR_BYTES


@pytest.mark.skipif(os.name != "nt", reason="WinDLL failure injection is Windows-only")
def test_windows_free_physical_memory_failure_reports_os_error(monkeypatch) -> None:
    import ctypes

    class _FakeFunction:
        def __init__(self) -> None:
            self.argtypes = None
            self.restype = None

        def __call__(self, *args):
            del args
            ctypes.set_last_error(8)
            return 0

    global_memory_status_ex = _FakeFunction()

    class _Kernel32:
        GlobalMemoryStatusEx = global_memory_status_ex

    def _failing_windll(name: str, *, use_last_error: bool):
        assert name == "kernel32"
        assert use_last_error is True
        return _Kernel32()

    monkeypatch.setattr(ctypes, "WinDLL", _failing_windll)

    with pytest.raises(
        SpineError,
        match=r"cannot read free physical memory \(Windows error 8\)",
    ):
        _free_physical_memory_bytes()

    assert global_memory_status_ex.argtypes is not None


@pytest.mark.skipif(os.name != "nt", reason="WinDLL failure injection is Windows-only")
def test_windows_peak_process_memory_failure_reports_os_error(monkeypatch) -> None:
    import ctypes

    class _FakeFunction:
        def __init__(self, result: int, *, error_code: int = 0) -> None:
            self.result = result
            self.error_code = error_code
            self.argtypes = None
            self.restype = None

        def __call__(self, *args):
            del args
            ctypes.set_last_error(self.error_code)
            return self.result

    get_current_process = _FakeFunction(-1)
    get_process_memory_info = _FakeFunction(0, error_code=6)

    class _Kernel32:
        GetCurrentProcess = get_current_process

    class _Psapi:
        GetProcessMemoryInfo = get_process_memory_info

    def _failing_windll(name: str, *, use_last_error: bool):
        assert use_last_error is True
        return _Kernel32() if name == "kernel32" else _Psapi()

    monkeypatch.setattr(ctypes, "WinDLL", _failing_windll)

    with pytest.raises(
        SpineError,
        match=r"cannot read process peak working-set memory \(Windows error 6\)",
    ):
        _peak_process_memory_bytes()

    assert get_current_process.argtypes == []
    assert get_process_memory_info.argtypes is not None


@pytest.mark.skipif(os.name != "nt", reason="64-bit Win32 regression is Windows-only")
def test_untyped_win32_call_fails_while_typed_call_succeeds() -> None:
    import ctypes
    from ctypes import wintypes

    class _Counters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("page_fault_count", wintypes.DWORD),
            ("peak_working_set_size", ctypes.c_size_t),
            ("working_set_size", ctypes.c_size_t),
            ("quota_peak_paged_pool_usage", ctypes.c_size_t),
            ("quota_paged_pool_usage", ctypes.c_size_t),
            ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
            ("quota_non_paged_pool_usage", ctypes.c_size_t),
            ("pagefile_usage", ctypes.c_size_t),
            ("peak_pagefile_usage", ctypes.c_size_t),
        ]

    untyped_counters = _Counters()
    untyped_counters.cb = ctypes.sizeof(untyped_counters)
    untyped_process = ctypes.windll.kernel32.GetCurrentProcess()
    untyped_ok = ctypes.windll.psapi.GetProcessMemoryInfo(
        untyped_process,
        ctypes.byref(untyped_counters),
        untyped_counters.cb,
    )
    untyped_error = ctypes.windll.kernel32.GetLastError()

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    get_current_process = kernel32.GetCurrentProcess
    get_current_process.argtypes = []
    get_current_process.restype = wintypes.HANDLE
    get_process_memory_info = psapi.GetProcessMemoryInfo
    get_process_memory_info.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_Counters),
        wintypes.DWORD,
    ]
    get_process_memory_info.restype = wintypes.BOOL
    typed_counters = _Counters()
    typed_counters.cb = ctypes.sizeof(typed_counters)
    typed_process = get_current_process()
    ctypes.set_last_error(0)
    typed_ok = get_process_memory_info(
        typed_process,
        ctypes.byref(typed_counters),
        typed_counters.cb,
    )

    assert untyped_ok == 0
    assert untyped_error == 6
    assert typed_ok == 1
    assert int(typed_counters.peak_working_set_size) > _PLAUSIBLE_PROCESS_FLOOR_BYTES


@pytest.mark.skipif(os.name == "nt", reason="resource.getrusage is unavailable on Windows")
def test_non_windows_resource_peak_memory_branch_returns_positive_int() -> None:
    peak = _peak_process_memory_bytes()

    assert type(peak) is int
    assert peak > _PLAUSIBLE_PROCESS_FLOOR_BYTES


def test_run_shakedown_preflights_memory_before_opening_store(
    monkeypatch, tmp_path
) -> None:
    final_root = tmp_path / "derived" / "first-run"
    staging_root = tmp_path / "derived" / ".first-run.staging"
    store_opened = False

    def _preflight_failure() -> int:
        raise SpineError("peak-memory preflight failed")

    def _unexpected_store_open(*args, **kwargs):
        nonlocal store_opened
        store_opened = True
        raise AssertionError("store must remain unopened after preflight failure")

    monkeypatch.setattr(run_module, "OUTPUT_ROOT", final_root)
    monkeypatch.setattr(run_module, "STAGING_ROOT", staging_root)
    monkeypatch.setattr(
        run_module,
        "environment_fingerprint",
        lambda root: {"commit": "fixture", "dirty": False},
    )
    monkeypatch.setattr(run_module, "_peak_process_memory_bytes", _preflight_failure)
    monkeypatch.setattr(run_module.BarStore, "open", _unexpected_store_open)

    with pytest.raises(SpineError, match="peak-memory preflight failed"):
        run_module.run_shakedown()

    assert store_opened is False
    assert final_root.exists() is False
    assert staging_root.exists() is False


def test_run_shakedown_rejects_low_free_memory_before_opening_store(
    monkeypatch, tmp_path
) -> None:
    final_root = tmp_path / "derived" / "first-run"
    staging_root = tmp_path / "derived" / ".first-run.staging"
    store_opened = False

    def _unexpected_store_open(*args, **kwargs):
        nonlocal store_opened
        del args, kwargs
        store_opened = True
        raise AssertionError("store must remain unopened after free-memory failure")

    monkeypatch.setattr(run_module, "OUTPUT_ROOT", final_root)
    monkeypatch.setattr(run_module, "STAGING_ROOT", staging_root)
    monkeypatch.setattr(
        run_module,
        "environment_fingerprint",
        lambda root: {"commit": "fixture", "dirty": False},
    )
    monkeypatch.setattr(
        run_module,
        "_peak_process_memory_bytes",
        lambda: PEAK_MEMORY_CEILING_BYTES,
    )
    monkeypatch.setattr(
        run_module,
        "_free_physical_memory_bytes",
        lambda: FREE_MEMORY_PREFLIGHT_BYTES - 1,
    )
    monkeypatch.setattr(run_module.BarStore, "open", _unexpected_store_open)

    with pytest.raises(
        SpineError,
        match=(
            rf"free-physical-memory preflight found "
            rf"{FREE_MEMORY_PREFLIGHT_BYTES - 1} bytes, below the fixed "
            rf"{FREE_MEMORY_PREFLIGHT_BYTES}-byte minimum"
        ),
    ):
        run_module.run_shakedown()

    assert store_opened is False
    assert final_root.exists() is False
    assert staging_root.exists() is False


def test_free_memory_preflight_accepts_boundary_and_rejects_one_byte_below(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        run_module,
        "_free_physical_memory_bytes",
        lambda: FREE_MEMORY_PREFLIGHT_BYTES,
    )
    assert _enforce_free_memory_preflight() == FREE_MEMORY_PREFLIGHT_BYTES

    monkeypatch.setattr(
        run_module,
        "_free_physical_memory_bytes",
        lambda: FREE_MEMORY_PREFLIGHT_BYTES - 1,
    )
    with pytest.raises(
        SpineError,
        match=(
            rf"free-physical-memory preflight found "
            rf"{FREE_MEMORY_PREFLIGHT_BYTES - 1} bytes, below the fixed "
            rf"{FREE_MEMORY_PREFLIGHT_BYTES}-byte minimum"
        ),
    ):
        _enforce_free_memory_preflight()


def test_in_process_memory_ceiling_accepts_boundary_and_rejects_one_byte_over(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        run_module,
        "_peak_process_memory_bytes",
        lambda: PEAK_MEMORY_CEILING_BYTES,
    )
    assert (
        _enforce_peak_memory_ceiling("boundary-control")
        == PEAK_MEMORY_CEILING_BYTES
    )

    monkeypatch.setattr(
        run_module,
        "_peak_process_memory_bytes",
        lambda: PEAK_MEMORY_CEILING_BYTES + 1,
    )
    with pytest.raises(
        SpineError,
        match=(
            rf"peak memory {PEAK_MEMORY_CEILING_BYTES + 1} exceeds the fixed "
            rf"{PEAK_MEMORY_CEILING_BYTES}-byte ceiling after injected-overage"
        ),
    ):
        _enforce_peak_memory_ceiling("injected-overage")
