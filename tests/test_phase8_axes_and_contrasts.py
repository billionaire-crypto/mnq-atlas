"""Independent synthetic witnesses for Phase 8 preregistration steps 1 and 2."""

from __future__ import annotations

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.constants import load_constants
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
from mnq_lab.spine.timemodel import TimeModel


def test_literal_axes_are_exact_and_reject_an_added_tail_statistic():
    assert OUTCOME_NAMES == (
        "downward_excursion_ticks",
        "upward_excursion_ticks",
    )
    assert STATISTICS == (("q50", 0.50), ("q75", 0.75), ("q90", 0.90))
    assert SESSION_PHASES == ("open", "morning", "midday", "afternoon", "close")
    assert VOLATILITY_STATES == ("low", "mid", "high")
    assert CONTRAST_NAMES == (
        "absolute_distribution",
        "phase_effect_given_vol",
        "vol_effect_given_phase",
        "cell_vs_complement",
        "cell_vs_population",
    )

    with pytest.raises(SpineError, match="undeclared Phase 8 statistic"):
        statistic_probability("q95")


def test_phase_axis_is_exactly_the_vocabulary_emitted_by_the_time_model():
    assert SESSION_PHASES == TimeModel.from_constants(load_constants()).phase_names


def test_all_five_support_masks_equal_a_contract_derived_oracle():
    phases = np.asarray(
        ["open", "open", "morning", "close", "midday", "open"], dtype="<U16"
    )
    vol_states = np.asarray(
        ["low", "mid", "low", "high", "mid", "low"], dtype="<U8"
    )
    target = CellKey("open", "low")
    target_oracle = np.asarray([True, False, False, False, False, True])
    baseline_oracles = {
        "absolute_distribution": np.asarray([False, False, False, False, False, False]),
        "phase_effect_given_vol": np.asarray([False, False, True, False, False, False]),
        "vol_effect_given_phase": np.asarray([False, True, False, False, False, False]),
        "cell_vs_complement": np.asarray([False, True, True, True, True, False]),
        "cell_vs_population": np.asarray([True, True, True, True, True, True]),
    }

    for contrast_name, baseline_oracle in baseline_oracles.items():
        actual = support_masks(phases, vol_states, target, contrast_name)
        assert np.array_equal(actual.target, target_oracle)
        assert np.array_equal(actual.baseline, baseline_oracle)

    widened_complement = baseline_oracles["cell_vs_complement"].copy()
    widened_complement[0] = True
    actual_complement = support_masks(
        phases, vol_states, target, "cell_vs_complement"
    )
    assert not np.array_equal(actual_complement.baseline, widened_complement)


def test_named_supports_have_the_exact_declared_cells():
    target = CellKey("open", "low")
    absolute = contrast_support(target, "absolute_distribution")
    phase = contrast_support(target, "phase_effect_given_vol")
    vol = contrast_support(target, "vol_effect_given_phase")
    complement = contrast_support(target, "cell_vs_complement")
    population = contrast_support(target, "cell_vs_population")

    assert absolute.target_cells == (target,)
    assert absolute.baseline_cells == ()
    assert phase.baseline_cells == (
        CellKey("morning", "low"),
        CellKey("midday", "low"),
        CellKey("afternoon", "low"),
        CellKey("close", "low"),
    )
    assert vol.baseline_cells == (CellKey("open", "mid"), CellKey("open", "high"))
    assert len(complement.baseline_cells) == 14
    assert target not in complement.baseline_cells
    assert len(population.baseline_cells) == 15
    assert target in population.baseline_cells


def test_support_masks_reject_a_planted_unknown_volatility_state():
    with pytest.raises(SpineError, match="undeclared volatility state"):
        support_masks(
            np.asarray(["open"]),
            np.asarray(["extreme"]),
            CellKey("open", "low"),
            "absolute_distribution",
        )


def test_inverse_cdf_quantile_uses_the_first_crossing_not_linear_interpolation():
    values = np.asarray([0, 10], dtype=np.int32)
    weights = np.asarray([0.75, 0.25], dtype=np.float64)

    assert weighted_quantile_ticks(values, weights, "q75") == 0
    assert weighted_quantile_ticks(values, weights, "q90") == 10


def test_tick_contrast_widens_before_subtracting_int32_extremes():
    result = tick_contrast(
        np.asarray([np.iinfo(np.int32).max], dtype=np.int32),
        np.asarray([1.0]),
        np.asarray([np.iinfo(np.int32).min], dtype=np.int32),
        np.asarray([1.0]),
        "q50",
    )

    assert result.target_quantile_ticks == 2_147_483_647
    assert result.baseline_quantile_ticks == -2_147_483_648
    assert result.contrast_ticks == 4_294_967_295
    assert result.contrast_ticks != result.target_quantile_ticks / result.baseline_quantile_ticks


def test_tick_quantiles_reject_a_float_input_instead_of_rounding_it():
    with pytest.raises(SpineError, match="signed integer ticks"):
        weighted_quantile_ticks(
            np.asarray([1.0, 2.0], dtype=np.float64),
            np.asarray([0.5, 0.5]),
            "q50",
        )


def test_invalid_numeric_quantile_output_halts_instead_of_rounding(monkeypatch):
    monkeypatch.setattr(
        "mnq_lab.phase8.contrasts.weighted_quantile",
        lambda values, weights, quantile: 1.5,
    )

    with pytest.raises(SpineError, match="non-integral tick quantile"):
        weighted_quantile_ticks(
            np.asarray([1, 2], dtype=np.int32),
            np.asarray([0.5, 0.5]),
            "q50",
        )


def test_degenerate_baseline_depends_only_on_exact_normalized_key_weights():
    target_keys = ("s1:a", "s2:a")
    assert degenerate_baseline(
        target_keys,
        np.asarray([1.0, 1.0]),
        tuple(reversed(target_keys)),
        np.asarray([0.25, 0.25]),
    )

    assert not degenerate_baseline(
        target_keys,
        np.asarray([1.0, 1.0]),
        ("s1:a", "s3:a"),
        np.asarray([1.0, 1.0]),
    )
    assert not degenerate_baseline(
        target_keys,
        np.asarray([1.0, 2.0]),
        target_keys,
        np.asarray([1.0, 1.0]),
    )


def test_identical_support_is_degenerate_even_when_outcomes_would_differ():
    keys = ((1, 100), (2, 200))
    weights = np.asarray([0.4, 0.6])
    first_outcomes = np.asarray([0, 100], dtype=np.int32)
    second_outcomes = np.asarray([999, -4], dtype=np.int32)

    assert not np.array_equal(first_outcomes, second_outcomes)
    assert degenerate_baseline(keys, weights, keys, weights)
