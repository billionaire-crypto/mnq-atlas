"""Independent synthetic witnesses for Phase 8 preregistration step 3."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.phase8.contrasts import CellKey
from mnq_lab.phase8.diagnostics import (
    STATUS_PRECEDENCE,
    PositivityStratumInput,
    anchor_support_failure,
    completion_diagnostics,
    positivity_diagnostics,
    resolve_status,
    status_decision,
    validate_result_validity,
)


def _completion_fixture(*, target_complete=99, baseline_complete=99):
    size = 200
    completed = np.zeros(size, dtype=np.bool_)
    completed[:target_complete] = True
    completed[100 : 100 + baseline_complete] = True
    target = np.zeros(size, dtype=np.bool_)
    target[:100] = True
    baseline = ~target
    return completion_diagnostics(
        horizon_minutes=15,
        session_ids=np.arange(size, dtype=np.int64),
        calendar_years=np.full(size, 2020, dtype=np.int64),
        structurally_eligible=np.ones(size, dtype=np.bool_),
        completed=completed,
        target_mask=target,
        target_weights=np.where(target, 0.01, 0.0),
        baseline_mask=baseline,
        baseline_weights=np.where(baseline, 0.01, 0.0),
    )


def test_completion_equality_at_thresholds_passes_inclusively():
    result = _completion_fixture(target_complete=99, baseline_complete=99)

    assert result.threshold == 0.99
    assert result.max_imbalance == 0.05
    assert result.target.completion_rate == 0.99
    assert result.baseline is not None
    assert result.baseline.completion_rate == 0.99
    assert result.completion_imbalance == 0.0
    assert result.breaches == ()
    assert not result.insufficient_completion


def test_completion_records_baseline_and_imbalance_failures_together():
    result = _completion_fixture(target_complete=100, baseline_complete=94)

    assert result.breaches == (
        "baseline_below_completion_minimum",
        "completion_imbalance_above_maximum",
    )
    assert result.insufficient_completion


def test_completion_emits_each_source_year_and_fires_only_total_confinement():
    session_ids = np.arange(100, dtype=np.int64)
    years = np.asarray([2020] * 99 + [2021], dtype=np.int64)
    all_rows = np.ones(100, dtype=np.bool_)
    completed = np.asarray([True] * 99 + [False], dtype=np.bool_)
    result = completion_diagnostics(
        horizon_minutes=15,
        session_ids=session_ids,
        calendar_years=years,
        structurally_eligible=all_rows,
        completed=completed,
        target_mask=all_rows,
        target_weights=np.full(100, 0.01),
    )

    assert tuple(item.year for item in result.target.by_year) == (2020, 2021)
    assert result.target.by_year[1].n_anchors == 1
    assert result.target.by_year[1].n_sessions == 1
    assert result.target.by_year[1].weight_ess == 1.0
    assert result.target.completion_rate == 0.99
    assert result.target.accepted_years == (2020,)
    assert result.target.single_year_concentration
    assert result.breaches == ("target_accepted_support_confined_to_one_year",)


def test_extreme_but_not_total_year_concentration_has_no_invented_cutoff():
    session_ids = np.arange(101, dtype=np.int64)
    years = np.asarray([2020] * 100 + [2021], dtype=np.int64)
    all_rows = np.ones(101, dtype=np.bool_)
    result = completion_diagnostics(
        horizon_minutes=15,
        session_ids=session_ids,
        calendar_years=years,
        structurally_eligible=all_rows,
        completed=all_rows,
        target_mask=all_rows,
        target_weights=np.full(101, 1 / 101),
    )

    assert result.target.accepted_years == (2020, 2021)
    assert not result.target.single_year_concentration
    assert result.breaches == ()


POSITIVITY_TARGET = CellKey("midday", "mid")
POSITIVITY_CONTRAST = "vol_effect_given_phase"
POSITIVITY_BASELINE_CELLS = (
    CellKey("midday", "low"),
    CellKey("midday", "high"),
)


def _supported_stratum(index, *, target_mass=0.5):
    return PositivityStratumInput(
        stratum=POSITIVITY_BASELINE_CELLS[index],
        target_weights=np.asarray([target_mass], dtype=np.float64),
        baseline_session_ids=tuple(range(50)),
    )


def test_positivity_inclusive_maxima_pass_at_exactly_point_zero_two_and_point_zero_five():
    result = positivity_diagnostics(
        strata=(_supported_stratum(0), _supported_stratum(1)),
        target=POSITIVITY_TARGET,
        contrast_name=POSITIVITY_CONTRAST,
        population_estimand="standardized_shared_population",
        quarter_unsupported_target_mass=0.05,
    )

    assert result.strata[0].max_single_anchor_weight_share == 0.02
    assert result.strata[0].weight_cv == 0.0
    assert result.thresholds.min_baseline_anchors_per_stratum == 30
    assert result.thresholds.min_contributing_sessions == 20
    assert result.thresholds.max_single_anchor_weight_share == 0.02
    assert result.thresholds.max_weight_cv == 2.0
    assert result.thresholds.max_unsupported_target_mass == 0.05
    assert result.unsupported_target_mass == 0.0
    assert result.quarter_unsupported_target_mass == 0.05
    assert result.breaches == ()
    assert not result.insufficient_overlap


def test_positivity_inclusive_minima_do_not_breach_at_thirty_anchors_and_twenty_sessions():
    baseline_sessions = tuple(
        session_id for session_id in range(10) for _ in range(2)
    ) + tuple(range(10, 20))
    result = positivity_diagnostics(
        strata=(
            PositivityStratumInput(
                stratum=POSITIVITY_BASELINE_CELLS[0],
                target_weights=np.asarray([1.0]),
                baseline_session_ids=baseline_sessions,
            ),
            _supported_stratum(1, target_mass=0.0),
        ),
        target=POSITIVITY_TARGET,
        contrast_name=POSITIVITY_CONTRAST,
        population_estimand="prospective_cell",
    )

    assert result.strata[0].n_anchors == 30
    assert result.strata[0].n_sessions == 20
    assert "insufficient_baseline_anchors" not in result.breaches
    assert "insufficient_contributing_sessions" not in result.breaches
    assert result.breaches == ("single_anchor_weight_share_above_maximum",)


def test_positivity_weight_cv_equality_at_two_passes_inclusively():
    # 15 one-anchor sessions and 35 twenty-one-anchor sessions produce the
    # exact rational population-CV target of 2 before binary64 evaluation.
    baseline_sessions = tuple(range(15)) + tuple(
        session_id for session_id in range(15, 50) for _ in range(21)
    )
    result = positivity_diagnostics(
        strata=(
            PositivityStratumInput(
                stratum=POSITIVITY_BASELINE_CELLS[0],
                target_weights=np.asarray([1.0]),
                baseline_session_ids=baseline_sessions,
            ),
            _supported_stratum(1, target_mass=0.0),
        ),
        target=POSITIVITY_TARGET,
        contrast_name=POSITIVITY_CONTRAST,
        population_estimand="prospective_cell",
    )

    assert result.strata[0].weight_cv == pytest.approx(2.0)
    assert result.breaches == ()


def test_positivity_unsupported_target_mass_equality_does_not_add_a_boundary_breach():
    result = positivity_diagnostics(
        strata=(
            _supported_stratum(0, target_mass=0.95),
            PositivityStratumInput(
                stratum=POSITIVITY_BASELINE_CELLS[1],
                target_weights=np.asarray([0.05]),
                baseline_session_ids=(),
            ),
        ),
        target=POSITIVITY_TARGET,
        contrast_name=POSITIVITY_CONTRAST,
        population_estimand="prospective_cell",
    )

    assert result.unsupported_target_mass == 0.05
    assert "unsupported_target_mass_above_maximum" not in result.breaches


def test_positivity_uses_session_equal_weights_inside_the_stratum():
    # Session 0 has three anchors; sessions 1..49 have one each. Anchor-equal
    # displayed weights would have CV=0, unlike the literal session-equal oracle.
    result = positivity_diagnostics(
        strata=(
            PositivityStratumInput(
                stratum=POSITIVITY_BASELINE_CELLS[0],
                target_weights=np.asarray([1.0]),
                baseline_session_ids=(0, 0, 0, *range(1, 50)),
            ),
            _supported_stratum(1, target_mass=0.0),
        ),
        target=POSITIVITY_TARGET,
        contrast_name=POSITIVITY_CONTRAST,
        population_estimand="prospective_cell",
    )

    diagnostic = result.strata[0]
    assert diagnostic.n_anchors == 52
    assert diagnostic.n_sessions == 50
    assert diagnostic.weight_ess == pytest.approx(50.675675675675684)
    assert diagnostic.max_single_anchor_weight_share == 0.02
    assert diagnostic.weight_cv == pytest.approx(0.16165807537309515)
    assert result.breaches == ()


def test_positivity_unsupported_mass_uses_target_weight_not_baseline_frequency():
    result = positivity_diagnostics(
        strata=(
            _supported_stratum(0, target_mass=0.8),
            PositivityStratumInput(
                stratum=POSITIVITY_BASELINE_CELLS[1],
                target_weights=np.asarray([0.2]),
                baseline_session_ids=tuple(range(19)),
            ),
        ),
        target=POSITIVITY_TARGET,
        contrast_name=POSITIVITY_CONTRAST,
        population_estimand="prospective_cell",
    )

    assert result.unsupported_target_mass == 0.2
    assert result.breaches == (
        "insufficient_baseline_anchors",
        "insufficient_contributing_sessions",
        "single_anchor_weight_share_above_maximum",
        "unsupported_target_mass_above_maximum",
    )


def test_positivity_empty_support_is_invalid_not_zero_cv():
    result = positivity_diagnostics(
        strata=(
            PositivityStratumInput(
                stratum=POSITIVITY_BASELINE_CELLS[0],
                target_weights=np.asarray([1.0]),
                baseline_session_ids=(),
            ),
            _supported_stratum(1, target_mass=0.0),
        ),
        target=POSITIVITY_TARGET,
        contrast_name=POSITIVITY_CONTRAST,
        population_estimand="prospective_cell",
    )

    diagnostic = result.strata[0]
    assert diagnostic.n_anchors == 0
    assert diagnostic.n_sessions == 0
    assert diagnostic.weight_ess is None
    assert diagnostic.max_single_anchor_weight_share is None
    assert diagnostic.weight_cv is None
    assert "invalid_session_equal_support" in result.breaches


def test_positivity_cv_breach_is_not_repaired_or_clipped():
    result = positivity_diagnostics(
        strata=(
            PositivityStratumInput(
                stratum=POSITIVITY_BASELINE_CELLS[0],
                target_weights=np.asarray([1.0]),
                baseline_session_ids=(0,) * 1000 + tuple(range(1, 50)),
            ),
            _supported_stratum(1, target_mass=0.0),
        ),
        target=POSITIVITY_TARGET,
        contrast_name=POSITIVITY_CONTRAST,
        population_estimand="prospective_cell",
    )

    assert result.strata[0].max_single_anchor_weight_share == 0.02
    assert result.strata[0].weight_cv is not None
    assert result.strata[0].weight_cv > 2.0
    assert result.breaches == ("weight_cv_above_maximum",)


def test_missing_completion_imbalance_constant_has_no_fallback(tmp_path):
    constants = tmp_path / "missing-completion-imbalance.yaml"
    constants.write_text(
        "horizons_minutes: [15, 30, 60]\n"
        "completion:\n"
        "  min_completion_h15: 0.99\n"
        "  min_completion_h30: 0.99\n"
        "  min_completion_h60: 0.98\n",
        encoding="utf-8",
    )
    with pytest.raises(SpineError, match="max_imbalance_absolute.*absent"):
        completion_diagnostics(
            horizon_minutes=15,
            session_ids=np.asarray([1]),
            calendar_years=np.asarray([2020]),
            structurally_eligible=np.asarray([True]),
            completed=np.asarray([True]),
            target_mask=np.asarray([True]),
            target_weights=np.asarray([1.0]),
            constants_path=constants,
        )


def test_missing_positivity_threshold_has_no_fallback(tmp_path):
    constants = tmp_path / "missing-weight-cv.yaml"
    constants.write_text(
        "positivity:\n"
        "  min_baseline_anchors_per_stratum: 30\n"
        "  min_contributing_sessions: 20\n"
        "  max_single_anchor_weight_share: 0.02\n"
        "  max_unsupported_target_mass: 0.05\n",
        encoding="utf-8",
    )
    with pytest.raises(SpineError, match="exactly the keys"):
        positivity_diagnostics(
            strata=(_supported_stratum(0), _supported_stratum(1)),
            target=POSITIVITY_TARGET,
            contrast_name=POSITIVITY_CONTRAST,
            population_estimand="prospective_cell",
            constants_path=constants,
        )


def test_positivity_rejects_a_planted_mismatched_comparison_set():
    with pytest.raises(SpineError, match="declared comparison support"):
        positivity_diagnostics(
            strata=(
                PositivityStratumInput(
                    stratum=CellKey("open", "low"),
                    target_weights=np.asarray([0.5]),
                    baseline_session_ids=tuple(range(50)),
                ),
                PositivityStratumInput(
                    stratum=CellKey("close", "high"),
                    target_weights=np.asarray([0.5]),
                    baseline_session_ids=tuple(range(50)),
                ),
            ),
            target=POSITIVITY_TARGET,
            contrast_name=POSITIVITY_CONTRAST,
            population_estimand="prospective_cell",
        )


def test_anchor_support_threshold_is_inclusive_and_absolute_ignores_baseline():
    assert not anchor_support_failure(
        target_n_anchors=30,
        target_n_sessions=1,
        baseline_n_anchors=None,
        baseline_n_sessions=None,
        has_baseline=False,
    )
    assert anchor_support_failure(
        target_n_anchors=29,
        target_n_sessions=1,
        baseline_n_anchors=None,
        baseline_n_sessions=None,
        has_baseline=False,
    )
    assert anchor_support_failure(
        target_n_anchors=30,
        target_n_sessions=1,
        baseline_n_anchors=29,
        baseline_n_sessions=1,
        has_baseline=True,
    )


def test_status_precedence_keeps_all_simultaneous_failures():
    assert STATUS_PRECEDENCE == (
        "degenerate_baseline",
        "insufficient_anchors",
        "insufficient_completion",
        "insufficient_overlap",
    )
    decision = status_decision(
        degenerate_baseline=True,
        insufficient_anchors=True,
        insufficient_completion=True,
        insufficient_overlap=True,
    )
    assert decision.status == "degenerate_baseline"
    assert decision.status_flags == STATUS_PRECEDENCE


@pytest.mark.parametrize(
    "planted_flags",
    [
        pytest.param(("unknown_failure",), id="unknown-status-flag"),
        pytest.param(
            ("insufficient_overlap", "insufficient_anchors"),
            id="reordered-status-precedence",
        ),
        pytest.param(
            ("insufficient_anchors", "insufficient_anchors"),
            id="duplicate-status-flag",
        ),
    ],
)
def test_status_resolver_rejects_noncanonical_planted_flags(planted_flags):
    with pytest.raises(SpineError, match="status_flags"):
        resolve_status(planted_flags)


def test_non_ok_status_rejects_a_planted_valid_point():
    decision = status_decision(
        degenerate_baseline=False,
        insufficient_anchors=True,
        insufficient_completion=False,
        insufficient_overlap=False,
    )
    with pytest.raises(SpineError, match="non-ok row"):
        validate_result_validity(
            decision,
            point_ticks=7,
            point_valid=True,
            interval_valid=False,
        )

    valid = validate_result_validity(
        decision,
        point_ticks=None,
        point_valid=False,
        interval_valid=False,
    )
    assert not valid.point_valid


def test_tampering_with_a_status_decision_cannot_hide_a_failure():
    decision = status_decision(
        degenerate_baseline=True,
        insufficient_anchors=True,
        insufficient_completion=False,
        insufficient_overlap=False,
    )
    planted = replace(decision, status_flags=("degenerate_baseline",))
    with pytest.raises(SpineError, match="status_flags"):
        validate_result_validity(
            planted,
            point_ticks=None,
            point_valid=False,
            interval_valid=False,
        )
