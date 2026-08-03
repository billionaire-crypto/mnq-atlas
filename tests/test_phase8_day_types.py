"""Independent synthetic witnesses for the Phase 8 day-type family."""

from __future__ import annotations

from dataclasses import fields, replace

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.conditioners.calendar import CalendarRow
from mnq_lab.phase8.day_types import (
    DAY_TYPES,
    DayTypeDistribution,
    classify_calendar_day_type,
    declared_day_type_rows,
    evaluate_day_type_distribution,
)


def _calendar_row(
    *,
    trade_date: int = 20200102,
    session_class: str = "regular",
    scheduled_rth_status: str = "full_rth",
    holiday_adjacent: bool = False,
) -> CalendarRow:
    active = session_class != "full_exchange_holiday"
    return CalendarRow(
        trade_date=trade_date,
        market="CME_GLOBEX_EQUITY_INDEX_FUTURES",
        session_class=session_class,
        scheduled_rth_status=scheduled_rth_status,
        scheduled_rth_open_ct="08:30" if active else "",
        scheduled_rth_close_ct="15:00" if active else "",
        raw_exchange_open_ct="17:00" if active else "",
        raw_exchange_close_ct="16:00" if active else "",
        holiday_adjacent=holiday_adjacent,
        source_event_id="synthetic-event",
        source_label="synthetic-label",
        source_as_of="2026-08-01",
        calendar_version="mnq-cme-equity-index-calendar-v1",
        schema_version="cme-equity-index-session-calendar-v1",
    )


def test_day_type_axes_and_inventory_are_literal_and_complete():
    assert DAY_TYPES == ("regular", "holiday_adjacent", "scheduled_early_close")
    rows = declared_day_type_rows()

    # 3 day types x 2 outcomes x 2 path estimands x 2 support kinds x
    # 3 horizons x 3 statistics, primary arm only.
    assert len(rows) == 216
    assert len(set(rows)) == 216
    assert {row.arm_id for row in rows} == {
        "primary_ewma78_permissive_expanding"
    }
    assert {row.day_type for row in rows} == set(DAY_TYPES)
    assert {row.outcome_name for row in rows} == {
        "downward_excursion_ticks",
        "upward_excursion_ticks",
    }
    assert {row.path_estimand for row in rows} == {
        "fully_labeled_1m_grid",
        "observed_bar_path",
    }
    assert {row.support_kind for row in rows} == {
        "horizon_specific",
        "common_support",
    }
    assert {row.horizon_minutes for row in rows} == {15, 30, 60}
    assert {row.statistic for row in rows} == {"q50", "q75", "q90"}


def test_day_type_precedence_uses_calendar_class_before_holiday_adjacency():
    overlap = _calendar_row(
        trade_date=20201127,
        session_class="scheduled_early_close",
        scheduled_rth_status="shortened_rth",
        holiday_adjacent=True,
    )
    adjacent = _calendar_row(trade_date=20201125, holiday_adjacent=True)
    regular = _calendar_row()
    holiday = _calendar_row(
        trade_date=20201225,
        session_class="full_exchange_holiday",
        scheduled_rth_status="full_exchange_holiday",
    )

    assert classify_calendar_day_type(overlap, "ok") == "scheduled_early_close"
    assert classify_calendar_day_type(adjacent, "ok") == "holiday_adjacent"
    assert classify_calendar_day_type(regular, "ok") == "regular"
    assert classify_calendar_day_type(holiday, "not_applicable") is None


@pytest.mark.parametrize("trade_date", (20200228, 20200630))
def test_truncated_regular_sessions_keep_the_frozen_type_and_quality_status(trade_date):
    row = _calendar_row(trade_date=trade_date)
    assert (
        classify_calendar_day_type(row, "unresolved_truncated_session")
        == "regular"
    )
    with pytest.raises(SpineError, match="unresolved_truncated_session"):
        classify_calendar_day_type(row, "ok")


def test_unknown_active_calendar_combination_halts_without_a_default():
    row = _calendar_row(
        session_class="unscheduled_closure",
        scheduled_rth_status="no_scheduled_rth",
    )
    with pytest.raises(SpineError, match="unknown active calendar combination"):
        classify_calendar_day_type(row, "ok")


def _distribution_fixture(*, completed=None, outside_value=777):
    # Session zero has thirty target anchors; sessions 1..29 have one each.
    # Session-equal weighting makes q50=100. Anchor-equal weighting would give 0.
    target_values = [0] * 30 + [100] * 29
    session_ids = np.asarray([0] * 30 + list(range(1, 30)) + list(range(30, 70)))
    values = np.asarray(target_values + [outside_value] * 40, dtype=np.int32)
    day_types = np.asarray(["regular"] * 59 + ["holiday_adjacent"] * 40)
    structural = np.ones(99, dtype=np.bool_)
    complete = structural.copy() if completed is None else np.asarray(completed)
    return evaluate_day_type_distribution(
        values=values,
        session_ids=session_ids,
        calendar_years=np.full(99, 2020, dtype=np.int16),
        structurally_eligible=structural,
        completed=complete,
        day_types=day_types,
        target_day_type="regular",
        horizon_minutes=15,
        statistic="q50",
    )


def test_day_type_level_uses_session_equal_mass_and_reports_all_companions():
    result = _distribution_fixture()

    assert result.status == "ok"
    assert result.status_flags == ()
    assert result.quantile_ticks == 100
    assert result.quantile_valid
    assert result.n_anchors == 59
    assert result.n_sessions == 30
    assert result.weight_ess == pytest.approx(30.998851894374283)
    assert result.completion.target.n_anchors == 59
    assert result.completion.target.n_sessions == 30
    assert result.completion.target.completion_rate == 1.0


def test_day_type_level_is_invariant_to_an_out_of_support_outcome_mutation():
    assert _distribution_fixture(outside_value=-2_000_000_000) == _distribution_fixture(
        outside_value=2_000_000_000
    )


def test_day_type_completion_failure_retains_evidence_but_nulls_the_point():
    complete = np.ones(99, dtype=np.bool_)
    complete[0] = False  # 58/59 is below the frozen h15 completion minimum.
    result = _distribution_fixture(completed=complete)

    assert result.status == "insufficient_completion"
    assert result.status_flags == ("insufficient_completion",)
    assert result.quantile_ticks is None
    assert not result.quantile_valid
    assert result.n_anchors == 58
    assert result.n_sessions == 30
    assert result.weight_ess is not None
    assert result.completion.target.n_anchors == 59
    assert result.completion.target.n_complete == 58


def test_empty_declared_day_type_is_emitted_as_insufficient_anchors():
    result = evaluate_day_type_distribution(
        values=np.asarray([1, 2], dtype=np.int32),
        session_ids=np.asarray([1, 2]),
        calendar_years=np.asarray([2020, 2020]),
        structurally_eligible=np.asarray([True, True]),
        completed=np.asarray([True, True]),
        day_types=np.asarray(["regular", "regular"]),
        target_day_type="scheduled_early_close",
        horizon_minutes=15,
        statistic="q50",
    )

    assert result.status == "insufficient_anchors"
    assert result.status_flags == (
        "insufficient_anchors",
        "insufficient_completion",
    )
    assert result.quantile_ticks is None
    assert not result.quantile_valid
    assert result.n_anchors == 0
    assert result.n_sessions == 0
    assert result.weight_ess is None


def test_day_type_inputs_reject_an_undeclared_label_instead_of_narrowing_support():
    with pytest.raises(SpineError, match="undeclared day_type"):
        evaluate_day_type_distribution(
            values=np.asarray([1], dtype=np.int32),
            session_ids=np.asarray([1]),
            calendar_years=np.asarray([2020]),
            structurally_eligible=np.asarray([True]),
            completed=np.asarray([True]),
            day_types=np.asarray(["observed_short_session"]),
            target_day_type="regular",
            horizon_minutes=15,
            statistic="q50",
        )


def test_day_type_result_schema_has_no_pvalue_or_formal_standardization_field():
    names = {field.name for field in fields(DayTypeDistribution)}
    assert "p_value" not in names
    assert "population_estimand" not in names
    assert "contrast_ticks" not in names

    valid = _distribution_fixture()
    with pytest.raises(SpineError, match="day type result evidence"):
        replace(valid, n_anchors=valid.n_anchors + 1)
