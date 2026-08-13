"""Evidence-protected entry point for the separately authorized calibration run.

Importing this module performs no corpus loading, computation, or filesystem write.
"""

from __future__ import annotations

import secrets
from typing import Any

from mnq_lab import SpineError

CALIBRATION_EXECUTION_AUTHORIZATION = (
    "MNQ-ATLAS-PHASE10-CALIBRATION-EVIDENCE-EXECUTION-REV1"
)


def _validate_execution_authorization(authorization: Any) -> None:
    if not isinstance(authorization, str) or not secrets.compare_digest(
        authorization,
        CALIBRATION_EXECUTION_AUTHORIZATION,
    ):
        raise SpineError("Phase 10 calibration execution authorization differs")


def _execute_authorized_request(request: Any) -> Any:
    from mnq_lab.phase10.calibration_execution import (
        CalibrationEvidenceRequest,
        execute_calibration_request,
    )

    if not isinstance(request, CalibrationEvidenceRequest):
        raise SpineError("Phase 10 calibration execution request is not configured")
    return execute_calibration_request(request)


def run_calibration_evidence(authorization: str, *, request: Any) -> Any:
    """Run only after an explicit, exact preregistered authorization token."""
    _validate_execution_authorization(authorization)
    return _execute_authorized_request(request)
