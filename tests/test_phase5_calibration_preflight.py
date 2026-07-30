"""Deterministic module-resolution preflight for the Phase 5 calibration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
CALIBRATION_RUNNER_PATH = (
    REPO_ROOT / "tools" / "phase5_coverage_calibration.py"
).resolve()


def test_phase5_calibration_module_resolution_preflight():
    """Locate the module safely and reproduce the superseded launch failure."""
    assert importlib.util.find_spec("mnq_lab") is not None

    # find_spec imports only the parent `tools` namespace package. Because
    # tools/ has no __init__.py, it contains no executable package code and
    # the calibration runner itself is located without being imported.
    runner_module = "tools.phase5_coverage_calibration"
    assert runner_module not in sys.modules
    runner_spec = importlib.util.find_spec(runner_module)
    assert runner_spec is not None
    assert runner_spec.origin is not None
    assert Path(runner_spec.origin).resolve() == CALIBRATION_RUNNER_PATH
    assert runner_module not in sys.modules

    # This negative case is valid only while mnq_lab is not installed into
    # site-packages; it currently resolves only from C:\mnq-atlas\mnq_lab.
    isolated_probe = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            (
                "import importlib.util,sys; "
                "sys.exit(0 if importlib.util.find_spec('mnq_lab') is None else 1)"
            ),
        ],
        cwd=REPO_ROOT / "tools",
        capture_output=True,
        text=True,
        check=False,
    )
    assert isolated_probe.returncode == 0, (
        "mnq_lab unexpectedly resolved under isolated script-path semantics: "
        f"stdout={isolated_probe.stdout!r}, stderr={isolated_probe.stderr!r}"
    )
