"""Prose-derived critical values must match `analysis_constants_v1.yaml` (§13 test 13).

    "load `analysis_constants_v1.yaml` and assert prose-derived critical values match:
    path estimand name, formal tests enabled, session phases, roll fixture start time,
    number of null engines, reference levels, completion rule"

The values on the right-hand side of each assertion are transcribed from the frozen spec
prose. If the YAML is edited without a corresponding ledger entry and spec change, these
fail — which is the point (§16.4.2).

Phase 1 does not consume most of these constants. They are asserted now so that drift is
caught at the moment it happens rather than in the phase that finally reads them.
"""

from __future__ import annotations

import hashlib

import pytest

from mnq_lab.constants import CONSTANTS_PATH, SPEC_PATH, load_constants
from mnq_lab.spine.gates import EXPECTED_ROLL_COUNT, ROLL_FIXTURE_PATH
from mnq_lab.spine.seal import SEAL_BOUNDARY_TRADE_DATE

from mnq_lab.conditioners.arms import ARM_CONFIGS
from mnq_lab.conditioners.assignments import (
    CATEGORY_NAMES,
    CATEGORY_ORDER,
    THRESHOLD_WARMUP_SESSIONS,
)
from mnq_lab.conditioners.calendar import (
    CALENDAR_SHA256,
    CALENDAR_VERSION,
    SCHEMA_VERSION as CALENDAR_SCHEMA_VERSION,
)
from mnq_lab.conditioners.scales.ewma import EWMA_WARMUP_RETURNS
from mnq_lab.conditioners.scales.mad import MAD_FACTOR, MAD_WINDOW_RETURNS
from mnq_lab.conditioners.seasonal import (
    RTH_BUCKETS,
    SEASONAL_MIN_BUCKET_OBS,
    SEASONAL_SHRINK_K,
    SEASONAL_WARMUP_SESSIONS,
)
from mnq_lab.conditioners.status import (
    AnchorStatus,
    AssignmentStatus,
    EwmaStatus,
    MadStatus,
    ResetReason,
    ReturnMissingReason,
    ReturnStatus,
    SeasonalStatus,
    ThresholdStatus,
    VolRelStatus,
)

PHASE5_PREREGISTRATION_PATH = (
    SPEC_PATH.parent / "docs" / "PHASE5_PREREGISTRATION.md"
)
PHASE5_PREREGISTRATION_SHA256 = (
    "22b82e3aef8a8dfb1410e3ad4ab5781fcef343371de3f156ec678c19d2a5b87c"
)
PHASE5_PREREGISTRATION_V2_PATH = (
    SPEC_PATH.parent / "docs" / "PHASE5_PREREGISTRATION_V2.md"
)
PHASE5_PREREGISTRATION_V2_SHA256 = (
    "37c94a1e9bae9f406dfac7e374cc9edacb5231ac2710f2baeecf1ce4a5b189ec"
)
PHASE5_PREREGISTRATION_V2_AMENDMENT_1_PATH = (
    SPEC_PATH.parent / "docs" / "PHASE5_PREREGISTRATION_V2_AMENDMENT_1.md"
)
PHASE5_PREREGISTRATION_V2_AMENDMENT_1_SHA256 = (
    "8c2af57b3da0939c5ba057d788500624c2a5dacc4577e4bafb3f6ae2a48df886"
)
PHASE6_PREREGISTRATION_PATH = (
    SPEC_PATH.parent / "docs" / "PHASE6_PREREGISTRATION.md"
)
PHASE6_PREREGISTRATION_SHA256 = (
    "e800e446ecd23fdb416c499603d086c50b1754c99106279284e3277a33b4ccb9"
)
PHASE7_PREREGISTRATION_PATH = SPEC_PATH.parent / "docs" / "PHASE7_PREREGISTRATION.md"
PHASE7_PREREGISTRATION_SHA256 = (
    "eeb97cb7e6ccd17a0ccd676de3cf7424f511fc773bacd62ff9e9f88aa404a930"
)


@pytest.fixture(scope="module")
def constants():
    return load_constants()


def test_both_frozen_files_exist():
    assert SPEC_PATH.is_file(), "REV6_FROZEN_SPEC.md is missing"
    assert CONSTANTS_PATH.is_file(), "analysis_constants_v1.yaml is missing"


def test_phase5_preregistration_bytes_are_pinned():
    assert PHASE5_PREREGISTRATION_PATH.is_file()
    assert (
        hashlib.sha256(PHASE5_PREREGISTRATION_PATH.read_bytes()).hexdigest()
        == PHASE5_PREREGISTRATION_SHA256
    )


def test_phase5_preregistration_v2_bytes_are_pinned():
    assert PHASE5_PREREGISTRATION_V2_PATH.is_file()
    assert (
        hashlib.sha256(PHASE5_PREREGISTRATION_V2_PATH.read_bytes()).hexdigest()
        == PHASE5_PREREGISTRATION_V2_SHA256
    )


def test_phase5_preregistration_v2_amendment_1_bytes_are_pinned():
    assert PHASE5_PREREGISTRATION_V2_AMENDMENT_1_PATH.is_file()
    assert (
        hashlib.sha256(
            PHASE5_PREREGISTRATION_V2_AMENDMENT_1_PATH.read_bytes()
        ).hexdigest()
        == PHASE5_PREREGISTRATION_V2_AMENDMENT_1_SHA256
    )


def test_phase6_preregistration_bytes_are_pinned():
    assert PHASE6_PREREGISTRATION_PATH.is_file()
    assert (
        hashlib.sha256(PHASE6_PREREGISTRATION_PATH.read_bytes()).hexdigest()
        == PHASE6_PREREGISTRATION_SHA256
    )


def test_spec_version_and_program_id(constants):
    assert constants.get("spec_version") == 6
    assert constants.get("program_id") == "mnq-atlas-001"


def test_path_estimand_name(constants):
    """§14 struck `complete_1m_path` / `observed_trade_path`."""
    assert constants.get("estimands", "path") == "fully_labeled_1m_grid"
    text = SPEC_PATH.read_text(encoding="utf-8")
    assert "complete_1m_path" in text and "~~" in text  # only inside the STRUCK table
    assert "observed_bar_path" in text


def test_formal_tests_enabled(constants):
    """§9.1: exactly one formal test in the MVP."""
    assert constants.get("inference", "formal_tests") == ["vol_given_phase"]
    assert constants.get("inference", "descriptive_only") == [
        "phase_given_vol",
        "interaction",
    ]


def test_number_of_null_engines(constants):
    """§14 struck "three residual tests each with its own null"."""
    assert constants.get("inference", "null", "kind") == (
        "whole_session_trajectory_reassignment"
    )
    assert isinstance(constants.get("inference", "null"), dict)
    assert len(constants.get("inference", "formal_tests")) == 1


def test_the_yaml_null_key_still_needs_normalising():
    """D8: `null:` in the frozen YAML resolves to Python `None`, not the string "null".

    The loader restores the written spelling. This asserts the underlying condition is
    still present, so if a future vendor of the frozen file quotes the key, the
    accommodation is revisited deliberately rather than lingering as dead code.
    """
    import yaml

    raw = yaml.safe_load(CONSTANTS_PATH.read_text(encoding="utf-8"))
    assert None in raw["inference"], (
        "the frozen YAML no longer has an unquoted `null:` key — remove the "
        "normalisation in mnq_lab/constants.py and this test"
    )
    assert "null" not in raw["inference"]
    # ...and the loader makes it reachable by the name the file actually shows.
    assert load_constants().get("inference", "null", "kind")


def test_null_strata_and_permutation_rules(constants):
    """§9.2: the retained null's exact mapping constraints."""
    null = constants.get("inference", "null")
    assert null["strata"] == ["calendar_quarter", "liquidity_era"]
    assert null["min_sessions_per_stratum"] == 20
    assert null["without_replacement"] is True
    assert null["disallow_self_assignment"] is True
    assert null["joint_across_outputs"] is True
    assert null["exclude_early_close"] is True
    assert null["exclude_holidays"] is True
    # §14 struck event-day strata — no verified calendar exists locally.
    assert "event_day" not in null["strata"]


def test_session_phases(constants):
    """§4.2, observation-time CT."""
    assert constants.get("session_phases") == {
        "open": ["08:30", "09:00"],
        "morning": ["09:00", "10:30"],
        "midday": ["10:30", "12:30"],
        "afternoon": ["12:30", "14:00"],
        "close": ["14:00", "15:00"],
    }


def test_phases_tile_rth_exactly(constants):
    phases = constants.get("session_phases")
    bounds = sorted(phases.values(), key=lambda pair: pair[0])
    assert bounds[0][0] == constants.get("time", "rth_start_ct") == "08:30"
    assert bounds[-1][1] == constants.get("time", "rth_end_ct") == "15:00"
    for earlier, later in zip(bounds, bounds[1:]):
        assert earlier[1] == later[0], f"gap or overlap between {earlier} and {later}"


def test_time_model(constants):
    """§4."""
    assert constants.get("time", "storage_tz") == "UTC"
    assert constants.get("time", "session_tz") == "America/Chicago"
    assert constants.get("time", "bar_label") == "open"
    assert constants.get("time", "tick_size") == 0.25
    assert constants.get("time", "maintenance_break_ct") == ["16:00", "17:00"]


def test_roll_fixture_start_time():
    """§3 finding C: 28 rolls, 2019-06-18 -> 2026-03-18."""
    import json

    rolls = json.loads(ROLL_FIXTURE_PATH.read_text(encoding="utf-8"))["rolls"]
    assert len(rolls) == EXPECTED_ROLL_COUNT == 28
    assert rolls[0]["effective_trade_date"] == "2019-06-18"
    assert rolls[0]["trigger_trade_date"] == "2019-06-17"
    assert rolls[-1]["effective_trade_date"] == "2026-03-18"
    assert rolls[-1]["trigger_trade_date"] == "2026-03-17"
    assert {roll["reason"] for roll in rolls} == {"prior_session_volume_crossover"}


def test_roll_trigger_is_the_previous_session_not_the_previous_day(
    exploration_5m, locked_5m
):
    """Finding C's "trigger = effective - 1" means one **session**, not one day.

    Read literally it is false: the 2019-09-16 roll triggers on Friday 2019-09-13, three
    calendar days earlier. Sessions are business days. The executable form of the claim
    is that no trade date exists strictly between trigger and effective — which is what
    "the next available CME trade date" in the roll policy actually means.

    See docs/DISCREPANCIES.md D9.
    """
    import json

    import numpy as np

    rolls = json.loads(ROLL_FIXTURE_PATH.read_text(encoding="utf-8"))["rolls"]
    sessions = np.union1d(
        np.unique(np.asarray(exploration_5m["session_id"])),
        np.unique(np.asarray(locked_5m["session_id"])),
    )

    gaps_in_days = set()
    for roll in rolls:
        trigger = int(roll["trigger_trade_date"].replace("-", ""))
        effective = int(roll["effective_trade_date"].replace("-", ""))
        assert effective > trigger

        between = sessions[(sessions > trigger) & (sessions < effective)]
        if trigger < int(sessions.min()):
            continue  # roll predates the built span; nothing to check against
        assert between.size == 0, (
            f"roll {roll['from']}->{roll['to']} effective {effective} skips sessions "
            f"{between.tolist()}; it is not the next available trade date"
        )

        import datetime as dt

        gaps_in_days.add(
            (
                dt.date.fromisoformat(roll["effective_trade_date"])
                - dt.date.fromisoformat(roll["trigger_trade_date"])
            ).days
        )

    assert gaps_in_days - {1}, (
        "every gap is exactly one calendar day, so this test cannot distinguish the "
        "session reading from the literal one and D9 is unproven"
    )


def test_reference_levels(constants):
    """§8 interaction estimand reference cell."""
    assert constants.get("interaction", "reference_phase") == "midday"
    assert constants.get("interaction", "reference_vol") == "mid"
    assert constants.get("interaction", "support") == "four_cell_common_sessions"


def test_completion_rule(constants):
    """§6."""
    assert constants.get("completion", "rule") == (
        "min_completion = max(0.90, floor(s00_p05 * 100) / 100)"
    )
    assert constants.get("completion", "horizon_specific") is True
    assert constants.get("completion", "max_imbalance_absolute") == 0.05
    assert constants.get("completion", "source_population", "rth_only") is True


def test_seal_boundary_is_tied_to_the_completion_population(constants):
    """The tier bound lives in §11 prose; this ties it to a YAML value.

    Changing one without the other now fails, so `SEAL_BOUNDARY_TRADE_DATE` cannot
    drift away from the frozen constants unnoticed.
    """
    years = constants.get("completion", "source_population", "years")
    assert years == ["2019-05-05", "2023-03-29"]
    assert SEAL_BOUNDARY_TRADE_DATE == years[1]


def test_surface_primary(constants):
    """§9.4, chosen from the economic objective before execution."""
    primary = constants.get("surface", "primary")
    assert primary["outcome"] == "downward_excursion"
    assert primary["horizon_minutes"] == 30
    assert primary["statistic"] == "q90"
    assert primary["contrast"] == "vol_effect_given_phase"
    assert primary["estimand"] == "prospective_cell"


def test_surface_region_detection_is_two_sided(constants):
    """§14 struck "region detection via z_c > 1.0 only"; abs(z) is never used."""
    assert constants.get("surface", "use_abs_z") is False
    assert constants.get("surface", "z_threshold_positive") == 1.0
    assert constants.get("surface", "z_threshold_negative") == -1.0
    assert constants.get("surface", "adjacency") == "rook"


def test_permutation_settings(constants):
    """§9.3."""
    assert constants.get("inference", "permutations_final") == 4999
    assert constants.get("inference", "sided") == "one_sided_upper"
    assert constants.get("inference", "rng") == "PCG64"
    assert constants.get("inference", "rng_seed") == 20260728
    assert constants.get("inference", "early_stopping") is False


def test_bootstrap_does_not_truncate_a_session(constants):
    """§7.3: the defect in `lora_statistics.stationary_session_resample`."""
    assert constants.get("bootstrap", "scheme") == "whole_session_stationary"
    assert constants.get("bootstrap", "truncate_partial_session") is False
    assert constants.get("bootstrap", "block_sensitivity") == [1, 5, 10, 20]


def test_reporting_forbids_significance_markers(constants):
    """§11 reporting discipline: no stars, no red/green."""
    assert constants.get("reporting", "significance_markers") is False
    assert constants.get("reporting", "require_n_sessions_beside_n_anchors") is True
    assert constants.get("reporting", "require_weight_ess") is True


def test_forward_budget_cannot_reset(constants):
    """§11: after five tests the counter does not reset."""
    assert constants.get("forward", "alpha_per_vintage") == 0.01
    assert constants.get("forward", "max_confirmatory_tests") == 5
    assert constants.get("forward", "reset_allowed") is False


def test_negative_case_a_drifted_constant_would_be_caught(tmp_path):
    """Prove these assertions are live rather than reading their own inputs."""
    altered = tmp_path / "drift.yaml"
    altered.write_text(
        CONSTANTS_PATH.read_text(encoding="utf-8").replace(
            "path: fully_labeled_1m_grid", "path: observed_bar_path"
        ),
        encoding="utf-8",
    )
    assert load_constants(altered).get("estimands", "path") == "observed_bar_path"
    assert load_constants().get("estimands", "path") == "fully_labeled_1m_grid"


def test_phase7_preregistration_bytes_are_pinned():
    assert PHASE7_PREREGISTRATION_PATH.is_file()
    assert (
        hashlib.sha256(PHASE7_PREREGISTRATION_PATH.read_bytes()).hexdigest()
        == PHASE7_PREREGISTRATION_SHA256
    )


def test_phase7_event_time_and_scale_constants_match_yaml(constants):
    """Frozen test 13: event-time, scale, MAD, and shrinkage constants agree."""
    assert len(RTH_BUCKETS) == 78
    assert RTH_BUCKETS[0] == constants.get("time", "rth_start_ct") == "08:30"
    assert RTH_BUCKETS[-1] == "14:55"
    assert tuple(constants.get("session_phases")) == (
        "open",
        "morning",
        "midday",
        "afternoon",
        "close",
    )
    assert EWMA_WARMUP_RETURNS == constants.get("volatility", "ewma_halflife_bars") == 78
    assert SEASONAL_WARMUP_SESSIONS == constants.get(
        "volatility", "seasonal_warmup_sessions"
    ) == 60
    assert SEASONAL_MIN_BUCKET_OBS == constants.get(
        "volatility", "seasonal_min_bucket_obs"
    ) == 30
    assert SEASONAL_SHRINK_K == constants.get("volatility", "seasonal_shrink_k") == 30
    independent = constants.get("volatility", "independent_estimator")
    assert independent == {
        "kind": "rolling_mad",
        "window_bars": 78,
        "scale_factor": 1.4826,
        "require_contiguous": True,
    }
    assert MAD_WINDOW_RETURNS == independent["window_bars"]
    assert float(MAD_FACTOR) == independent["scale_factor"]
    assert THRESHOLD_WARMUP_SESSIONS == 60


def test_phase7_arm_inventory_matches_frozen_alternatives(constants):
    alternatives = constants.get("alternative_definitions")
    assert alternatives == {
        "tercile_shift_pctpoints": [-5, -2, 2, 5],
        "rolling_window_sessions": [60],
        "ewma_halflife_bars": [39, 156],
    }
    assert tuple(config.order for config in ARM_CONFIGS) == tuple(range(10))
    assert tuple(config.arm_id for config in ARM_CONFIGS) == (
        "primary_ewma78_permissive_expanding",
        "coverage_strict",
        "ewma39",
        "ewma156",
        "mad78",
        "threshold_rolling60",
        "threshold_shift_m05",
        "threshold_shift_m02",
        "threshold_shift_p02",
        "threshold_shift_p05",
    )
    primary = ARM_CONFIGS[0]
    for alternative in ARM_CONFIGS[1:]:
        differences = sum(
            getattr(alternative, field) != getattr(primary, field)
            for field in (
                "scale_kind",
                "coverage",
                "halflife",
                "history_kind",
                "lower_probability",
                "upper_probability",
            )
        )
        if alternative.arm_id.startswith("threshold_shift_"):
            assert differences == 2  # the paired probabilities are one ruled factor
        elif alternative.arm_id == "mad78":
            assert differences == 2  # estimator kind replaces the EWMA halflife field
        else:
            assert differences == 1


def test_phase7_calendar_statuses_and_category_encoding_are_frozen():
    assert CALENDAR_VERSION == "mnq-cme-equity-index-calendar-v1"
    assert CALENDAR_SCHEMA_VERSION == "cme-equity-index-session-calendar-v1"
    assert CALENDAR_SHA256 == "b86e112c16112bf11a6a548ca8b3f21d28a08f90442b4dde84098f9d3f6eb069"
    assert CATEGORY_ORDER == (-1, 0, 1, 2)
    assert CATEGORY_NAMES == {-1: "undefined", 0: "low", 1: "mid", 2: "high"}
    assert tuple(value.value for value in AnchorStatus) == ("ok", "anchor_bar_missing")
    assert tuple(value.value for value in ReturnStatus) == ("ok", "missing_return")
    assert tuple(value.value for value in ReturnMissingReason) == (
        "bar_absent",
        "insufficient_components",
        "spacing_break",
        "symbol_change",
    )
    assert tuple(value.value for value in ResetReason) == (
        "none",
        "roll_reset",
        "gap_reset",
    )
    assert tuple(value.value for value in EwmaStatus) == ("ok", "warmup")
    assert tuple(value.value for value in MadStatus) == ("ok", "warmup", "zero_scale")
    assert tuple(value.value for value in SeasonalStatus) == (
        "ok",
        "warmup",
        "seasonal_fallback_unavailable",
        "calendar_classification_missing",
    )
    assert tuple(value.value for value in VolRelStatus) == (
        "ok",
        "zero_scale",
        "upstream_undefined",
    )
    assert tuple(value.value for value in ThresholdStatus) == (
        "ok",
        "insufficient_threshold_history",
        "degenerate_boundaries",
    )
    assert tuple(value.value for value in AssignmentStatus) == (
        "ok",
        "warmup",
        "upstream_undefined",
    )


def test_phase7_deferred_input_and_phase_boundaries_are_explicit():
    text = PHASE7_PREREGISTRATION_PATH.read_text(encoding="utf-8")
    assert "liquidity_era_status=deferred_missing_versioned_input" in text
    assert "Phase 7 emits no contrast," in text
    assert "prevalence, p-value, null, confirmation, vintage" in text
    assert "Phase 8 owns named outcome contrasts" in text
    assert "Phase 9 owns prevalence" in text
    assert "Phase 10 owns\nnull engines" in text
    assert "Phase 11 owns guards, the\nresult ledger, vintages" in text
    assert "Phase 12 owns S01A rendering" in text
