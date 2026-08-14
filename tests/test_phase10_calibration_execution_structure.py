"""Static wiring witnesses; the evidence runner is never executed here."""

from __future__ import annotations

from dataclasses import fields
import inspect

import pytest

from mnq_lab.phase10.calibration_execution import (
    CalibrationEvidenceRequest,
    execute_calibration_request,
)
from mnq_lab.phase10.calibration_science import (
    compute_calibration_replication,
    compute_unsealed_calibration_replication,
)


def _science_source():
    return inspect.getsource(
        compute_unsealed_calibration_replication
    ) + inspect.getsource(compute_calibration_replication)


def _assert_execution_wiring(science_source, execution_source, request_type):
    assert "build_verified_outer_control" in science_source
    assert "fresh_internal_mappings" in science_source
    assert "seal_scientific_payload" in science_source
    assert "spawn_session_mappings(" not in science_source
    assert "run_after_environment_verification" in execution_source
    assert execution_source.index("run_after_environment_verification") < execution_source.index(
        "compute_calibration_replication"
    )
    assert "assert_complete_replication_inventory" in execution_source
    assert "replication_indices" not in tuple(field.name for field in fields(request_type))


def test_runner_wires_provenance_fresh_resume_environment_schema_and_denominator():
    _assert_execution_wiring(
        _science_source(),
        inspect.getsource(execute_calibration_request) + inspect.getsource(__import__(
            "mnq_lab.phase10.calibration_execution",
            fromlist=["_compute_verified"],
        )._compute_verified),
        CalibrationEvidenceRequest,
    )


@pytest.mark.parametrize(
    "removed",
    (
        "build_verified_outer_control",
        "fresh_internal_mappings",
        "seal_scientific_payload",
        "run_after_environment_verification",
        "assert_complete_replication_inventory",
    ),
)
def test_runner_wiring_omission_mutants_fail_the_same_witness(removed):
    science = _science_source()
    module = __import__("mnq_lab.phase10.calibration_execution", fromlist=["_compute_verified"])
    execution = inspect.getsource(execute_calibration_request) + inspect.getsource(module._compute_verified)
    if removed in science:
        science = science.replace(removed, "removed_witness", 1)
    else:
        execution = execution.replace(removed, "removed_witness", 1)
    with pytest.raises(AssertionError):
        _assert_execution_wiring(science, execution, CalibrationEvidenceRequest)
