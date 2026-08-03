"""Synthetic-only Phase 8 contrast and estimand primitives."""

from mnq_lab.phase8.contrasts import (
    CONTRAST_NAMES,
    OUTCOME_NAMES,
    SESSION_PHASES,
    STATISTICS,
    VOLATILITY_STATES,
    CellKey,
    contrast_support,
    degenerate_baseline,
    statistic_probability,
    support_masks,
    tick_contrast,
    weighted_quantile_ticks,
)
from mnq_lab.phase8.estimands import ESTIMAND_NAMES, build_estimand_weights

__all__ = [
    "CONTRAST_NAMES",
    "ESTIMAND_NAMES",
    "OUTCOME_NAMES",
    "SESSION_PHASES",
    "STATISTICS",
    "VOLATILITY_STATES",
    "CellKey",
    "build_estimand_weights",
    "contrast_support",
    "degenerate_baseline",
    "statistic_probability",
    "support_masks",
    "tick_contrast",
    "weighted_quantile_ticks",
]
