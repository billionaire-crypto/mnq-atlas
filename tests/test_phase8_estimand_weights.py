"""Independent weight oracles for Phase 8 preregistration step 2."""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.phase8.contrasts import CellKey
from mnq_lab.phase8.estimands import (
    ESTIMAND_NAMES,
    build_estimand_weights,
)


def _build(
    *,
    estimand_name,
    session_ids,
    quarters,
    phases,
    vol_states,
    target=CellKey("open", "low"),
    contrast_name="absolute_distribution",
    contrast_weighting="not_applicable",
    outcome_eligible=None,
    ordinary_full_length=None,
):
    size = len(session_ids)
    return build_estimand_weights(
        estimand_name=estimand_name,
        session_ids=np.asarray(session_ids, dtype=np.int64),
        calendar_quarters=np.asarray(quarters, dtype="<U8"),
        session_phases=np.asarray(phases, dtype="<U16"),
        volatility_states=np.asarray(vol_states, dtype="<U8"),
        outcome_eligible=(
            np.ones(size, dtype=np.bool_)
            if outcome_eligible is None
            else np.asarray(outcome_eligible, dtype=np.bool_)
        ),
        ordinary_full_length=(
            np.ones(size, dtype=np.bool_)
            if ordinary_full_length is None
            else np.asarray(ordinary_full_length, dtype=np.bool_)
        ),
        target=target,
        contrast_name=contrast_name,
        contrast_weighting=contrast_weighting,
    )


def test_estimand_names_are_literal_and_no_day_type_axis_is_accepted():
    assert ESTIMAND_NAMES == (
        "prospective_cell",
        "common_session_paired",
        "standardized_shared_population",
    )
    parameters = inspect.signature(build_estimand_weights).parameters
    assert "day_type" not in parameters
    assert "liquidity_era" not in parameters


def test_prospective_cell_is_session_equal_not_anchor_equal():
    result = _build(
        estimand_name="prospective_cell",
        session_ids=[1, 1, 1, 2],
        quarters=["2020Q1"] * 4,
        phases=["open"] * 4,
        vol_states=["low"] * 4,
    )
    oracle = np.asarray([1 / 6, 1 / 6, 1 / 6, 1 / 2], dtype=np.float64)
    anchor_equal_mutant = np.full(4, 0.25)

    assert np.array_equal(result.target.weights, oracle)
    assert not np.array_equal(result.target.weights, anchor_equal_mutant)
    assert result.target.n_anchors == 4
    assert result.target.n_sessions == 2
    assert result.target.weight_ess == 3.0


def test_prospective_target_and_baseline_select_sessions_independently():
    result = _build(
        estimand_name="prospective_cell",
        session_ids=[1, 2, 2, 3],
        quarters=["2020Q1"] * 4,
        phases=["open", "open", "morning", "morning"],
        vol_states=["low"] * 4,
        contrast_name="phase_effect_given_vol",
        contrast_weighting="natural_prevalence_contrast",
    )

    assert result.target.session_keys == (1, 2)
    assert result.baseline is not None
    assert result.baseline.session_keys == (2, 3)
    assert result.target.weights[0] > 0.0
    assert result.baseline.weights[3] > 0.0


def test_common_session_paired_removes_each_unilateral_session():
    result = _build(
        estimand_name="common_session_paired",
        session_ids=[1, 2, 2, 3, 3, 3, 4],
        quarters=["2020Q1"] * 7,
        phases=["open", "open", "morning", "open", "open", "morning", "morning"],
        vol_states=["low"] * 7,
        contrast_name="cell_vs_complement",
        contrast_weighting="natural_prevalence_contrast",
    )

    assert result.retained_session_keys == (2, 3)
    assert result.target.session_keys == (2, 3)
    assert result.baseline is not None
    assert result.baseline.session_keys == (2, 3)
    assert result.target.weights[0] == 0.0
    assert result.baseline.weights[6] == 0.0
    assert np.array_equal(
        result.target.weights,
        np.asarray([0.0, 0.5, 0.0, 0.25, 0.25, 0.0, 0.0]),
    )


def test_standardization_keeps_missing_target_quarter_mass_unsupported():
    result = _build(
        estimand_name="standardized_shared_population",
        session_ids=[1, 1, 2, 3, 4],
        quarters=["2020Q1", "2020Q1", "2020Q1", "2020Q2", "2020Q2"],
        phases=["open", "open", "open", "morning", "morning"],
        vol_states=["low"] * 5,
    )
    oracle = np.asarray([0.125, 0.125, 0.25, 0.0, 0.0])

    assert np.array_equal(result.target.weights, oracle)
    assert result.target.quarter_target_masses == (
        ("2020Q1", 0.5),
        ("2020Q2", 0.5),
    )
    assert result.target.unsupported_target_mass == 0.5
    assert np.sum(result.target.weights) == 0.5
    assert result.target.n_anchors == 3
    assert result.target.n_sessions == 2
    assert result.target.weight_ess == 8.0 / 3.0


def test_standardized_population_excludes_a_planted_nonordinary_session():
    result = _build(
        estimand_name="standardized_shared_population",
        session_ids=[1, 2, 3],
        quarters=["2020Q1"] * 3,
        phases=["open"] * 3,
        vol_states=["low"] * 3,
        ordinary_full_length=[True, False, True],
    )

    assert np.array_equal(result.target.weights, np.asarray([0.5, 0.0, 0.5]))
    assert result.target.session_keys == (1, 3)


def test_equal_mass_and_natural_prevalence_use_different_cell_masses():
    session_ids = [
        1, 1, 1, 2,  # morning: four anchors over two sessions
        3, 3,        # midday: two anchors
        4,           # afternoon: one anchor
        5,           # close: one anchor
        6,           # target
    ]
    phases = [
        "morning", "morning", "morning", "morning",
        "midday", "midday", "afternoon", "close", "open",
    ]
    kwargs = dict(
        estimand_name="prospective_cell",
        session_ids=session_ids,
        quarters=["2020Q1"] * len(session_ids),
        phases=phases,
        vol_states=["low"] * len(session_ids),
        contrast_name="phase_effect_given_vol",
    )
    equal = _build(**kwargs, contrast_weighting="equal_phase_contrast")
    natural = _build(**kwargs, contrast_weighting="natural_prevalence_contrast")
    assert equal.baseline is not None and natural.baseline is not None

    equal_masses = {item.cell: item.assigned_mass for item in equal.baseline.cells}
    natural_masses = {item.cell: item.assigned_mass for item in natural.baseline.cells}
    assert equal_masses == {
        CellKey("morning", "low"): 0.25,
        CellKey("midday", "low"): 0.25,
        CellKey("afternoon", "low"): 0.25,
        CellKey("close", "low"): 0.25,
    }
    assert natural_masses == {
        CellKey("morning", "low"): 0.5,
        CellKey("midday", "low"): 0.25,
        CellKey("afternoon", "low"): 0.125,
        CellKey("close", "low"): 0.125,
    }

    # Inside the morning cell, each session gets half its cell's mass;
    # session 1 then divides that half over its three anchors.
    assert np.array_equal(
        natural.baseline.weights[:4],
        np.asarray([1 / 12, 1 / 12, 1 / 12, 0.25]),
    )


def test_every_reported_anchor_count_has_session_count_and_weight_ess():
    result = _build(
        estimand_name="prospective_cell",
        session_ids=[1, 2],
        quarters=["2020Q1", "2020Q1"],
        phases=["open", "morning"],
        vol_states=["low", "low"],
        contrast_name="phase_effect_given_vol",
        contrast_weighting="equal_phase_contrast",
    )
    assert result.target.n_anchors == 1
    assert result.target.n_sessions == 1
    assert result.target.weight_ess == 1.0
    assert result.baseline is not None
    for cell in result.baseline.cells:
        if cell.n_anchors:
            assert cell.n_sessions > 0
            assert cell.weight_ess is not None


def test_undeclared_estimand_is_a_named_fail_closed_input():
    with pytest.raises(SpineError, match="undeclared Phase 8 estimand"):
        _build(
            estimand_name="retrospective_selected_cell",
            session_ids=[1],
            quarters=["2020Q1"],
            phases=["open"],
            vol_states=["low"],
        )


def test_undeclared_comparative_weighting_is_a_named_fail_closed_input():
    with pytest.raises(SpineError, match="declared contrast weighting"):
        _build(
            estimand_name="prospective_cell",
            session_ids=[1, 2],
            quarters=["2020Q1", "2020Q1"],
            phases=["open", "morning"],
            vol_states=["low", "low"],
            contrast_name="phase_effect_given_vol",
            contrast_weighting="outcome_adaptive_weighting",
        )


def test_not_applicable_on_a_comparative_contrast_fails_closed():
    with pytest.raises(SpineError, match="declared contrast weighting"):
        _build(
            estimand_name="prospective_cell",
            session_ids=[1, 2],
            quarters=["2020Q1", "2020Q1"],
            phases=["open", "morning"],
            vol_states=["low", "low"],
            contrast_name="phase_effect_given_vol",
            contrast_weighting="not_applicable",
        )


def test_comparative_weighting_on_absolute_distribution_fails_closed():
    with pytest.raises(SpineError, match="absolute_distribution requires"):
        _build(
            estimand_name="prospective_cell",
            session_ids=[1],
            quarters=["2020Q1"],
            phases=["open"],
            vol_states=["low"],
            contrast_weighting="natural_prevalence_contrast",
        )


def test_mismatched_estimand_vector_lengths_fail_closed():
    with pytest.raises(SpineError, match="equal row length"):
        build_estimand_weights(
            estimand_name="prospective_cell",
            session_ids=np.asarray([1, 2], dtype=np.int64),
            calendar_quarters=np.asarray(["2020Q1"], dtype="<U8"),
            session_phases=np.asarray(["open", "open"], dtype="<U16"),
            volatility_states=np.asarray(["low", "low"], dtype="<U8"),
            outcome_eligible=np.asarray([True, True]),
            ordinary_full_length=np.asarray([True, True]),
            target=CellKey("open", "low"),
            contrast_name="absolute_distribution",
            contrast_weighting="not_applicable",
        )


@pytest.mark.parametrize(
    ("quarters", "ordinary_full_length"),
    [
        pytest.param(
            ["2020Q1", "2020Q2"],
            [True, True],
            id="same-session-two-calendar-quarters",
        ),
        pytest.param(
            ["2020Q1", "2020Q1"],
            [True, False],
            id="same-session-two-ordinary-full-length-values",
        ),
    ],
)
def test_inconsistent_session_metadata_fails_closed(quarters, ordinary_full_length):
    with pytest.raises(SpineError, match="constant within session"):
        _build(
            estimand_name="prospective_cell",
            session_ids=[1, 1],
            quarters=quarters,
            phases=["open", "open"],
            vol_states=["low", "low"],
            ordinary_full_length=ordinary_full_length,
        )
