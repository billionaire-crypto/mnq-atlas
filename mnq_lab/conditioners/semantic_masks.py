"""Independent frozen semantic-mask rules for Phase 7 admission.

This module imports no estimator, pipeline, registry, or declared metadata.
It is the production-side transcription of preregistration section 10.
"""

from __future__ import annotations

import numpy as np

from mnq_lab import SpineError

__all__ = ["ADMISSION_MASK_SIZES", "semantic_mask_for_stage"]


ADMISSION_MASK_SIZES = {
    "scale": 82,
    "seasonal_profile": 8,
    "vol_rel": 8,
    "thresholds": 8,
    "assignment": 8,
}


def semantic_mask_for_stage(stage: str) -> np.ndarray:
    """Construct the exact bar/row mask without consulting a callable."""
    try:
        size = ADMISSION_MASK_SIZES[stage]
    except KeyError as exc:
        raise SpineError(f"unknown Phase 7 semantic-mask stage {stage!r}") from exc
    mask = np.zeros(size, dtype=np.bool_)
    if stage == "scale":
        # Seventy-eight returns consume exactly 79 bars.
        mask[1:80] = True
    elif stage in {"seasonal_profile", "thresholds"}:
        mask[:5] = True
    else:
        # vol_rel and assignment consume five prior profile/threshold rows
        # plus the current scale/vol_rel row at index five.
        mask[:6] = True
    mask.setflags(write=False)
    return mask
