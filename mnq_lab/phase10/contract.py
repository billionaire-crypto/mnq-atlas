"""Frozen Phase 10 contract loaded without fallback values."""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral
from pathlib import Path
from typing import Any

from mnq_lab import SpineError
from mnq_lab.constants import load_constants
from mnq_lab.phase8.contrasts import (
    SESSION_PHASES,
    STATISTICS,
    VOLATILITY_STATES,
)
from mnq_lab.phase8.estimands import ESTIMAND_NAMES
from mnq_lab.phase8.inventory import CONTRAST_WEIGHTINGS

FORMAL_TEST = "vol_given_phase"
DEFERRED_TESTS = ("phase_given_vol", "interaction")
PRIMARY_OUTCOME = "downward_excursion_ticks"
PRIMARY_HORIZON_MINUTES = 30
PRIMARY_STATISTIC = "q90"
PRIMARY_CONTRAST = "vol_effect_given_phase"
PRIMARY_ESTIMAND = "prospective_cell"
PRIMARY_PATH_ESTIMAND = "fully_labeled_1m_grid"
PRIMARY_SUPPORT_KIND = "horizon_specific"
PERMUTATION_POPULATION = "ordinary_full_rth_nonadjacent_resolved"
PERMUTATION_SESSIONS = 900
LIQUIDITY_ERA = "undifferentiated_no_versioned_boundaries"
LIQUIDITY_ERA_STATUS = "inactive_missing_versioned_input"
EFFECTIVE_NULL_STRATA = "calendar_quarter_only"
RNG_ROOT_ENTROPY = (20260728,)


@dataclass(frozen=True)
class Phase10Contract:
    """Exact runtime values bound to the frozen YAML and preregistration."""

    permutations_final: int
    permutations_dev_min: int
    min_sessions_per_stratum: int
    rng_seed: int
    positive_threshold: float
    negative_threshold: float
    weighting_planes: tuple[str, ...]


def _built_in_positive_integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value <= 0:
        raise SpineError(f"Phase 10 {name} must be a positive integer")
    return int(value)


def load_phase10_contract(constants_path: Path | None = None) -> Phase10Contract:
    """Load and cross-check every Phase 10 constant used by the engine."""
    constants = load_constants(constants_path)
    inference = constants.get("inference")
    null = constants.get("inference", "null")
    primary = constants.get("surface", "primary")
    if not isinstance(inference, dict) or not isinstance(null, dict):
        raise SpineError("Phase 10 inference mappings are absent")
    if constants.get("inference", "formal_tests") != [FORMAL_TEST]:
        raise SpineError("Phase 10 formal test differs from the frozen singleton")
    if tuple(constants.get("inference", "descriptive_only")) != DEFERRED_TESTS:
        raise SpineError("Phase 10 deferred tests differ from the frozen order")
    if null.get("kind") != "whole_session_trajectory_reassignment":
        raise SpineError("Phase 10 null kind differs")
    if null.get("strata") != ["calendar_quarter", "liquidity_era"]:
        raise SpineError("Phase 10 declared YAML strata differ")
    required_flags = {
        "exclude_early_close": True,
        "exclude_holidays": True,
        "without_replacement": True,
        "disallow_self_assignment": True,
        "joint_across_outputs": True,
    }
    for name, expected in required_flags.items():
        if null.get(name) is not expected:
            raise SpineError(f"Phase 10 inference.null.{name} differs")
    if constants.get("inference", "p_value") != "(1 + #{T_b >= T_obs}) / (B + 1)":
        raise SpineError("Phase 10 p-value expression differs")
    if constants.get("inference", "sided") != "one_sided_upper":
        raise SpineError("Phase 10 sidedness differs")
    if constants.get("inference", "rng") != "PCG64":
        raise SpineError("Phase 10 generator kind differs")
    if constants.get("inference", "early_stopping") is not False:
        raise SpineError("Phase 10 early stopping must remain false")
    expected_primary = {
        "outcome": "downward_excursion",
        "horizon_minutes": PRIMARY_HORIZON_MINUTES,
        "statistic": PRIMARY_STATISTIC,
        "contrast": PRIMARY_CONTRAST,
        "estimand": PRIMARY_ESTIMAND,
    }
    if primary != expected_primary:
        raise SpineError("Phase 10 primary surface differs")
    if PRIMARY_STATISTIC not in {name for name, _ in STATISTICS}:
        raise SpineError("Phase 10 statistic is not imported from Phase 8")
    if PRIMARY_ESTIMAND not in ESTIMAND_NAMES:
        raise SpineError("Phase 10 estimand is not imported from Phase 8")
    if tuple(constants.get("surface", "ordered_families")) != (
        "session_phase", "vol_rel_tercile", "liquidity_era"
    ):
        raise SpineError("Phase 10 ordered topology differs")
    if tuple(constants.get("surface", "unordered_families")) != ("day_type",):
        raise SpineError("Phase 10 unordered topology differs")
    if constants.get("surface", "adjacency") != "rook":
        raise SpineError("Phase 10 adjacency differs")
    if constants.get("surface", "use_abs_z") is not False:
        raise SpineError("Phase 10 signed-region rule differs")
    if len(SESSION_PHASES) != 5 or len(VOLATILITY_STATES) != 3:
        raise SpineError("Phase 10 imported lattice dimensions differ")
    rng_seed = _built_in_positive_integer(
        constants.get("inference", "rng_seed"), "rng_seed"
    )
    if RNG_ROOT_ENTROPY != (rng_seed,):
        raise SpineError("Phase 10 root entropy is not derived from inference.rng_seed")
    return Phase10Contract(
        permutations_final=_built_in_positive_integer(
            constants.get("inference", "permutations_final"),
            "permutations_final",
        ),
        permutations_dev_min=_built_in_positive_integer(
            constants.get("inference", "permutations_dev_min"),
            "permutations_dev_min",
        ),
        min_sessions_per_stratum=_built_in_positive_integer(
            null.get("min_sessions_per_stratum"), "min_sessions_per_stratum"
        ),
        rng_seed=rng_seed,
        positive_threshold=float(constants.get("surface", "z_threshold_positive")),
        negative_threshold=float(constants.get("surface", "z_threshold_negative")),
        weighting_planes=tuple(CONTRAST_WEIGHTINGS),
    )


def artifact_metadata() -> dict[str, Any]:
    """Return mandatory metadata shared by every Phase 10 serialization."""
    contract = load_phase10_contract()
    return {
        "formal_test": FORMAL_TEST,
        "permutation_population": PERMUTATION_POPULATION,
        "permutation_sessions": PERMUTATION_SESSIONS,
        "liquidity_era": LIQUIDITY_ERA,
        "liquidity_era_status": LIQUIDITY_ERA_STATUS,
        "effective_null_strata": EFFECTIVE_NULL_STRATA,
        "rng_seed": contract.rng_seed,
        "rng_root_entropy": list(RNG_ROOT_ENTROPY),
    }
