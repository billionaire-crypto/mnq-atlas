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
from mnq_lab.phase8.diagnostics import (
    STATUS_PRECEDENCE,
    anchor_support_failure,
    completion_diagnostics,
    positivity_diagnostics,
    status_decision,
)
from mnq_lab.phase8.inventory import declared_result_rows
from mnq_lab.phase8.uncertainty import (
    BootstrapIntervalRequest,
    BootstrapQuantileTerm,
    bootstrap_contract,
    joint_bootstrap_intervals,
)

__all__ = [
    "CONTRAST_NAMES",
    "ESTIMAND_NAMES",
    "OUTCOME_NAMES",
    "SESSION_PHASES",
    "STATISTICS",
    "STATUS_PRECEDENCE",
    "VOLATILITY_STATES",
    "CellKey",
    "BootstrapIntervalRequest",
    "BootstrapQuantileTerm",
    "build_estimand_weights",
    "bootstrap_contract",
    "anchor_support_failure",
    "completion_diagnostics",
    "contrast_support",
    "degenerate_baseline",
    "declared_result_rows",
    "positivity_diagnostics",
    "joint_bootstrap_intervals",
    "statistic_probability",
    "support_masks",
    "status_decision",
    "tick_contrast",
    "weighted_quantile_ticks",
]
