"""Phase 3 S00 completion atlas and threshold mathematics.

These tests pin the preregistered equal-phase inverse CDF, exact floor, 0.90
lower bound, full declared grid, exploration population, deterministic artifact,
and fail-closed behavior before any YAML threshold is written.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mnq_lab import SpineError
from mnq_lab.constants import CONSTANTS_PATH, REPO_ROOT, Constants, load_constants
from mnq_lab.outcomes import s00
from mnq_lab.outcomes.completion import (
    ESTIMAND_FULLY_LABELED,
    ESTIMAND_OBSERVED,
    anchor_outcome_completion,
)
from mnq_lab.outcomes.s00 import (
    FROZEN_HORIZONS,
    FROZEN_PHASES,
    QUANTILE_CONVENTION,
    build_s00_payload,
    canonical_artifact_bytes,
    derive_threshold_candidates,
    write_s00_artifact,
)
from mnq_lab.spine.timemodel import TimeModel


def _valid_table(
    overrides: dict[tuple[str, int], tuple[int, int]] | None = None,
) -> pd.DataFrame:
    overrides = overrides or {}
    rows = []
    for phase in FROZEN_PHASES:
        for horizon in FROZEN_HORIZONS:
            numerator, denominator = overrides.get(
                (phase, horizon), (999, 1000)
            )
            rows.append(
                {
                    "phase": phase,
                    "horizon_minutes": horizon,
                    "n_anchors": denominator,
                    f"n_complete_{ESTIMAND_FULLY_LABELED}": numerator,
                    f"completion_rate_{ESTIMAND_FULLY_LABELED}": (
                        numerator / denominator
                        if denominator
                        else float("nan")
                    ),
                    f"n_complete_{ESTIMAND_OBSERVED}": denominator,
                    f"completion_rate_{ESTIMAND_OBSERVED}": 1.0,
                    "status": "ok" if denominator else "no_structurally_eligible_anchors",
                }
            )
    return pd.DataFrame.from_records(rows)


def _derive(table: pd.DataFrame) -> list[dict]:
    return derive_threshold_candidates(
        table, FROZEN_PHASES, FROZEN_HORIZONS
    )


def _by_horizon(candidates: list[dict]) -> dict[int, dict]:
    return {row["horizon_minutes"]: row for row in candidates}


# --- ratified threshold mathematics ------------------------------------------------


def test_thresholds_are_horizon_specific_floor_not_round_and_cap_with_max():
    table = _valid_table(
        {
            ("open", 15): (9899, 10000),      # floor -> .98, not rounded .99
            ("morning", 30): (9051, 10000),   # floor -> .90
            ("midday", 60): (8999, 10000),    # raw .89, lower bound -> .90
        }
    )
    result = _by_horizon(_derive(table))

    assert result[15]["s00_p05_numerator"] == 9899
    assert result[15]["s00_p05_denominator"] == 10000
    assert result[15]["raw_threshold"] == 0.98
    assert result[15]["min_completion_candidate"] == 0.98

    assert result[30]["raw_threshold"] == 0.90
    assert result[30]["min_completion_candidate"] == 0.90

    assert result[60]["raw_threshold"] == 0.89
    assert result[60]["min_completion_candidate"] == 0.90


def test_exact_boundary_09000_remains_090():
    table = _valid_table({("close", 60): (9, 10)})
    candidate = _by_horizon(_derive(table))[60]
    assert candidate["raw_threshold"] == 0.90
    assert candidate["min_completion_candidate"] == 0.90


def test_all_five_phases_have_equal_mass_and_a_thin_cell_cannot_be_dropped():
    table = _valid_table({("close", 60): (0, 1)})
    candidate = _by_horizon(_derive(table))[60]
    assert candidate["s00_p05_attaining_phases"] == ["close"]
    assert candidate["s00_p05_numerator"] == 0
    assert candidate["s00_p05_denominator"] == 1
    assert candidate["min_completion_candidate"] == 0.90


def test_ties_at_the_minimum_return_the_same_observed_value():
    table = _valid_table(
        {
            ("open", 15): (49, 50),
            ("midday", 15): (98, 100),
        }
    )
    candidate = _by_horizon(_derive(table))[15]
    assert candidate["s00_p05_numerator"] == 49
    assert candidate["s00_p05_denominator"] == 50
    assert candidate["s00_p05_attaining_phases"] == ["open", "midday"]


def test_default_linear_quantile_cannot_replace_inverse_cdf_unnoticed():
    table = _valid_table(
        {
            ("open", 15): (0, 4),
            ("morning", 15): (1, 4),
            ("midday", 15): (2, 4),
            ("afternoon", 15): (3, 4),
            ("close", 15): (4, 4),
        }
    )
    candidate = _by_horizon(_derive(table))[15]
    rates = table[table["horizon_minutes"] == 15][
        f"completion_rate_{ESTIMAND_FULLY_LABELED}"
    ].to_numpy()

    assert QUANTILE_CONVENTION == "discrete_inverse_cdf_equal_phase_weights"
    assert candidate["s00_p05_decimal"] == 0.0
    assert np.quantile(rates, 0.05, method="linear") == pytest.approx(0.05)
    assert candidate["s00_p05_decimal"] != np.quantile(
        rates, 0.05, method="linear"
    )


def test_derivation_is_input_order_invariant_and_output_remains_canonical():
    table = _valid_table(
        {
            ("open", 15): (991, 1000),
            ("morning", 30): (981, 1000),
            ("midday", 60): (971, 1000),
        }
    )
    expected = _derive(table)
    shuffled = table.sample(frac=1.0, random_state=20260728).reset_index(drop=True)
    actual = _derive(shuffled)

    assert actual == expected
    assert [row["horizon_minutes"] for row in actual] == list(FROZEN_HORIZONS)


# --- fail closed on any population or grid ambiguity -------------------------------


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "extra"])
def test_missing_duplicate_and_extra_cells_fail_closed(mutation):
    table = _valid_table()
    if mutation == "missing":
        table = table.iloc[:-1].copy()
    elif mutation == "duplicate":
        table = pd.concat([table, table.iloc[[0]]], ignore_index=True)
    else:
        extra = table.iloc[[0]].copy()
        extra.loc[:, "phase"] = "overnight"
        table = pd.concat([table, extra], ignore_index=True)

    with pytest.raises(SpineError, match=mutation):
        _derive(table)


def test_empty_or_nan_cell_blocks_the_freeze_and_is_never_skipped():
    table = _valid_table()
    mask = (table["phase"] == "close") & (table["horizon_minutes"] == 60)
    table.loc[mask, "n_anchors"] = 0
    table.loc[mask, f"n_complete_{ESTIMAND_FULLY_LABELED}"] = 0
    table.loc[mask, f"completion_rate_{ESTIMAND_FULLY_LABELED}"] = np.nan
    table.loc[mask, "status"] = "no_structurally_eligible_anchors"

    with pytest.raises(SpineError, match="status"):
        _derive(table)

    table.loc[mask, "status"] = "ok"
    with pytest.raises(SpineError, match="zero structurally eligible"):
        _derive(table)


@pytest.mark.parametrize("bad_rate", [np.nan, np.inf, -np.inf])
def test_non_finite_rate_fails_closed(bad_rate):
    table = _valid_table()
    table.loc[0, f"completion_rate_{ESTIMAND_FULLY_LABELED}"] = bad_rate
    with pytest.raises(SpineError, match="non-finite"):
        _derive(table)


def test_rate_must_agree_with_the_exact_count_fraction():
    table = _valid_table()
    table.loc[0, f"completion_rate_{ESTIMAND_FULLY_LABELED}"] = 0.5
    with pytest.raises(SpineError, match="exact count ratio"):
        _derive(table)


def test_observed_path_rates_cannot_enter_threshold_derivation():
    table = _valid_table()
    with pytest.raises(SpineError, match="wrong estimand"):
        derive_threshold_candidates(
            table,
            FROZEN_PHASES,
            FROZEN_HORIZONS,
            estimand=ESTIMAND_OBSERVED,
        )


def test_axes_must_be_the_exact_yaml_phase_and_horizon_order():
    table = _valid_table()
    with pytest.raises(SpineError, match="exact frozen phase order"):
        derive_threshold_candidates(
            table, tuple(reversed(FROZEN_PHASES)), FROZEN_HORIZONS
        )
    with pytest.raises(SpineError, match="exact frozen horizon order"):
        derive_threshold_candidates(
            table, FROZEN_PHASES, tuple(reversed(FROZEN_HORIZONS))
        )


# --- real-store S00 artifact --------------------------------------------------------


@pytest.fixture(scope="module")
def real_s00_payload():
    return build_s00_payload(REPO_ROOT / "data")


@pytest.fixture(scope="module")
def real_completion(exploration_5m):
    model = TimeModel.from_constants(load_constants())
    return anchor_outcome_completion(
        model,
        np.asarray(exploration_5m["session_id"]),
        np.asarray(exploration_5m["ts_event_ns"]),
        np.asarray(exploration_5m["observed_1m_components"]),
        np.asarray(exploration_5m["expected_1m_components"]),
    )


def test_real_store_population_provenance_and_flags_are_exact(real_s00_payload):
    population = real_s00_payload["source_population"]
    assert population == {
        "declared_start_inclusive": "2019-05-05",
        "declared_end_inclusive": "2023-03-29",
        "actual_first_session": "2019-05-06",
        "actual_last_session": "2023-03-29",
        "n_sessions": 1009,
        "n_gridpoints": 78702,
        "rth_only": True,
        "include_holidays_and_short_sessions_flagged": True,
        "include_thin_cells": True,
        "calendar_early_close_status": "unknown",
    }
    assert real_s00_payload["session_flag_census"] == {
        "n_sessions": 1009,
        "n_observed_short_session": 34,
        "n_observed_rth_ended_early": 34,
        "n_observed_no_rth_bars": 1,
        "n_observed_mid_rth_gap": 4,
        "n_observed_rth_ended_early_and_mid_rth_gap": 0,
        "n_calendar_early_close_unknown": 1009,
    }
    assert real_s00_payload["store_provenance"] == {
        "build_id": "0ad7843647f17258",
        "pipeline_version": "spine-1.0.0",
        "bar_seconds": 300,
        "row_count": 274847,
        "manifest_sha256": (
            "1cf6ec5ce7822ce1333984909b52d5c937e4ccc06e280030bcacda22620ffd73"
        ),
    }


def test_real_store_emits_the_exact_15_cell_threshold_input(real_s00_payload):
    rows = real_s00_payload["rows"]
    assert [(row["phase"], row["horizon_minutes"]) for row in rows] == [
        (phase, horizon)
        for phase in FROZEN_PHASES
        for horizon in FROZEN_HORIZONS
    ]

    # n_gridpoints, n_state, n_anchors, n_sessions, n_complete_fully,
    # n_complete_observed. These are independently replayed from the store.
    expected = {
        ("open", 15): (6054, 6038, 6038, 1008, 6030, 6033),
        ("open", 30): (6054, 6038, 6038, 1008, 6026, 6031),
        ("open", 60): (6054, 6038, 6038, 1008, 6018, 6027),
        ("morning", 15): (18162, 18125, 18125, 1008, 18106, 18119),
        ("morning", 30): (18162, 18125, 18125, 1008, 18095, 18115),
        ("morning", 60): (18162, 18125, 18125, 1008, 18081, 18109),
        ("midday", 15): (24216, 24003, 24003, 1006, 23866, 23904),
        ("midday", 30): (24216, 24003, 24003, 1006, 23763, 23805),
        ("midday", 60): (24216, 24003, 24003, 1006, 23568, 23607),
        ("afternoon", 15): (18162, 17532, 17532, 974, 17523, 17532),
        ("afternoon", 30): (18162, 17532, 17532, 974, 17519, 17532),
        ("afternoon", 60): (18162, 17532, 17532, 974, 17517, 17532),
        ("close", 15): (12108, 11688, 9740, 974, 9740, 9740),
        ("close", 30): (12108, 11688, 6818, 974, 6818, 6818),
        ("close", 60): (12108, 11688, 974, 974, 974, 974),
    }
    for row in rows:
        pair = (row["phase"], row["horizon_minutes"])
        actual = (
            row["n_gridpoints"],
            row["n_state_anchors"],
            row["n_anchors"],
            row["n_sessions"],
            row[f"n_complete_{ESTIMAND_FULLY_LABELED}"],
            row[f"n_complete_{ESTIMAND_OBSERVED}"],
        )
        assert actual == expected[pair]
        assert row["weight_ess"] is None
        assert row["weight_ess_status"] == "not_computed_until_phase_4"
        assert row["status"] == "ok"


def test_real_store_candidates_match_exact_count_inputs(real_s00_payload):
    candidates = _by_horizon(real_s00_payload["candidates"])
    assert candidates[15] == {
        "horizon_minutes": 15,
        "s00_p05_numerator": 23866,
        "s00_p05_denominator": 24003,
        "s00_p05_decimal": 23866 / 24003,
        "s00_p05_attaining_phases": ["midday"],
        "raw_threshold": 0.99,
        "min_completion_candidate": 0.99,
    }
    # Fractions are reduced in candidate metadata; the rows retain original counts.
    assert candidates[30]["s00_p05_numerator"] == 7921
    assert candidates[30]["s00_p05_denominator"] == 8001
    assert candidates[30]["s00_p05_decimal"] == 23763 / 24003
    assert candidates[30]["min_completion_candidate"] == 0.99
    assert candidates[60]["s00_p05_numerator"] == 7856
    assert candidates[60]["s00_p05_denominator"] == 8001
    assert candidates[60]["s00_p05_decimal"] == 23568 / 24003
    assert candidates[60]["min_completion_candidate"] == 0.98


def test_real_store_wholly_missing_bar_cannot_be_complete(real_completion):
    """D12 real-store hardening required by the Phase 3 handoff."""
    for horizon in FROZEN_HORIZONS:
        missing = (
            real_completion[f"n_present_h{horizon}"]
            < real_completion[f"n_required_h{horizon}"]
        )
        assert not real_completion.loc[
            missing, f"complete_{ESTIMAND_FULLY_LABELED}_h{horizon}"
        ].any()
        assert not real_completion.loc[
            missing, f"complete_{ESTIMAND_OBSERVED}_h{horizon}"
        ].any()


def test_artifact_is_strict_deterministic_json(real_s00_payload, tmp_path):
    first = tmp_path / "one" / "s00.json"
    second = tmp_path / "two" / "s00.json"
    first_info = write_s00_artifact(real_s00_payload, first)
    second_info = write_s00_artifact(real_s00_payload, second)

    assert first.read_bytes() == second.read_bytes()
    assert first_info["sha256"] == second_info["sha256"]
    assert first.read_bytes().endswith(b"\n")
    decoded = json.loads(first.read_text(encoding="utf-8"))
    assert len(decoded["rows"]) == 15
    assert all(row["weight_ess"] is None for row in decoded["rows"])
    assert b"NaN" not in first.read_bytes()


def test_canonical_json_refuses_non_finite_values():
    with pytest.raises(SpineError, match="strict canonical JSON"):
        canonical_artifact_bytes({"bad": float("nan")})


def test_s00_is_unchanged_after_its_derived_threshold_keys_exist(real_s00_payload):
    altered_data = copy.deepcopy(load_constants().as_dict())
    altered_data["completion"].update(
        {
            "min_completion_h15": 0.90,
            "min_completion_h30": 0.91,
            "min_completion_h60": 0.92,
        }
    )
    altered = Constants(altered_data, Path("<threshold-invariance-test>"))
    after = build_s00_payload(REPO_ROOT / "data", altered)

    assert after == real_s00_payload
    assert canonical_artifact_bytes(after) == canonical_artifact_bytes(
        real_s00_payload
    )


def test_s00_artifact_does_not_embed_its_derived_threshold_keys(real_s00_payload):
    artifact = canonical_artifact_bytes(real_s00_payload)
    assert b"min_completion_h15" not in artifact
    assert b"min_completion_h30" not in artifact
    assert b"min_completion_h60" not in artifact


def test_cli_writes_the_declared_artifact_without_editing_yaml(tmp_path):
    before = CONSTANTS_PATH.read_bytes()
    output = tmp_path / "s00.json"
    result = s00._run(REPO_ROOT / "data", output)

    assert result["artifact"]["path"] == str(output.resolve())
    assert result["artifact"]["sha256"]
    assert output.read_bytes() == canonical_artifact_bytes(result["payload"])
    assert CONSTANTS_PATH.read_bytes() == before
