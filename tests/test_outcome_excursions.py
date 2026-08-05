"""Unit O status, resolver, and int64-safe excursion tests."""

from __future__ import annotations

from copy import deepcopy

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.constants import Constants, load_constants
from mnq_lab.outcomes.excursions import (
    ESTIMAND_FULLY_LABELED,
    ESTIMAND_OBSERVED,
    OUTCOME_STATUSES,
    STATUS_ANCHOR_BAR_MISSING,
    STATUS_INSUFFICIENT_COMPONENTS,
    STATUS_OK,
    STATUS_PATH_SESSION_MISMATCH,
    STATUS_PATH_SYMBOL_MISMATCH,
    STATUS_PATH_TIMESTAMP_MISSING,
    STATUS_STRUCTURALLY_UNAVAILABLE,
    _OutcomeContract,
    build_outcome_table,
    compute_excursion_ticks,
    resolve_outcome_row,
    validate_outcome_table,
)
from tests.conftest import ct_ns
from tests.unit_o_fixtures import (
    schedule_for_store,
    in_memory_store,
    synthetic_outcome_columns,
)


def _row(table, *, estimand, tau="08:35", horizon=15):
    tau_ns = ct_ns(f"2021-06-15 {tau}")
    mask = (
        (table.column("estimand") == estimand)
        & (table.column("tau_ns") == tau_ns)
        & (table.column("horizon_minutes") == horizon)
    )
    indices = np.flatnonzero(mask)
    assert len(indices) == 1
    return {name: values[indices[0]] for name, values in table.columns.items()}


def _resolve(columns, *, tau="08:35", horizon=15, estimand=ESTIMAND_FULLY_LABELED):
    return resolve_outcome_row(
        columns,
        session_id=20210615,
        tau_ns=ct_ns(f"2021-06-15 {tau}"),
        tau_ct_minute=int(tau[:2]) * 60 + int(tau[3:]),
        session_phase="open",
        horizon_minutes=horizon,
        estimand=estimand,
    )


def test_status_vocabulary_and_precedence_are_closed():
    assert OUTCOME_STATUSES == (
        STATUS_ANCHOR_BAR_MISSING,
        STATUS_STRUCTURALLY_UNAVAILABLE,
        STATUS_PATH_TIMESTAMP_MISSING,
        STATUS_PATH_SESSION_MISMATCH,
        STATUS_PATH_SYMBOL_MISMATCH,
        STATUS_INSUFFICIENT_COMPONENTS,
        STATUS_OK,
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.pop("horizons_minutes"),
        lambda data: data.__setitem__("horizons_minutes", [30, 15, 60]),
        lambda data: data.__setitem__("horizons_minutes", [15, 30, 45, 60]),
        lambda data: data.__setitem__("horizons_minutes", [15, 30, 61]),
    ],
)
def test_unit_o_constants_fail_closed_when_horizons_are_missing_extra_or_reordered(
    mutation,
):
    data = deepcopy(load_constants().as_dict())
    mutation(data)
    with pytest.raises(SpineError, match="horizon"):
        _OutcomeContract.from_constants(Constants(data, load_constants().source))


def test_exact_window_uses_anchor_close_and_excludes_anchor_extremes_and_end_bar():
    columns = synthetic_outcome_columns(
        price_overrides={
            "08:30": (90, 200, 10, 100),
            "08:35": (101, 104, 98, 102),
            "08:40": (102, 105, 99, 103),
            "08:45": (101, 103, 97, 102),
            "08:50": (100, 999, 1, 100),
        }
    )
    row = _resolve(columns)
    assert row["outcome_status"] == STATUS_OK
    assert row["anchor_close_ticks"] == 100
    assert row["downward_excursion_ticks"] == 3
    assert row["upward_excursion_ticks"] == 5
    assert row["signed_downward_extreme_ticks"] == 3
    assert row["signed_upward_extreme_ticks"] == 5
    # Every mutant has a nonempty discriminating witness in this one fixture.
    assert 100 - 10 != 3  # including the anchor bar's low
    assert 200 - 100 != 5  # including the anchor bar's high
    assert 90 - 97 != 3  # using anchor open instead of close
    assert 100 - 1 != 3 and 999 - 100 != 5  # including tau + delta


def test_the_bar_labelled_tau_is_included_in_both_off_by_one_directions():
    columns = synthetic_outcome_columns(
        price_overrides={
            "08:30": (100, 101, 99, 100),
            "08:35": (100, 107, 93, 100),
            "08:40": (100, 102, 98, 100),
            "08:45": (100, 103, 97, 100),
        }
    )
    row = _resolve(columns)
    assert row["downward_excursion_ticks"] == 7
    assert row["upward_excursion_ticks"] == 7
    later_only_lows = columns["low_ticks"][
        np.isin(
            columns["ts_event_ns"],
            [ct_ns("2021-06-15 08:40"), ct_ns("2021-06-15 08:45")],
        )
    ]
    assert 100 - int(later_only_lows.min()) == 3  # excluding tau must fail


def test_signed_companions_are_not_floored_but_named_excursions_are():
    above = compute_excursion_ticks(
        np.int32(100),
        np.asarray([101, 104, 102], dtype=np.int32),
        np.asarray([106, 110, 108], dtype=np.int32),
    )
    assert above == (0, 10, -1, 10)
    below = compute_excursion_ticks(
        np.int32(100),
        np.asarray([90, 92, 95], dtype=np.int32),
        np.asarray([99, 96, 98], dtype=np.int32),
    )
    assert below == (10, 0, 10, -1)


def test_int32_prices_widen_before_extrema_and_subtraction():
    safe = compute_excursion_ticks(
        np.int32(np.iinfo(np.int32).max),
        np.asarray([np.iinfo(np.int32).max - 10], dtype=np.int32),
        np.asarray([np.iinfo(np.int32).max], dtype=np.int32),
    )
    assert safe == (10, 0, 10, 0)
    with pytest.raises(SpineError, match="does not fit in int32"):
        compute_excursion_ticks(
            np.int32(np.iinfo(np.int32).max),
            np.asarray([np.iinfo(np.int32).min], dtype=np.int32),
            np.asarray([np.iinfo(np.int32).max], dtype=np.int32),
        )
    with np.errstate(over="ignore"):
        wrapped_mutant = np.int32(np.iinfo(np.int32).max) - np.int32(
            np.iinfo(np.int32).min
        )
    assert int(wrapped_mutant) == -1  # the named mutation is genuinely dangerous


def test_noninteger_empty_and_invalid_ohlc_inputs_halt_as_corruption():
    with pytest.raises(SpineError, match="int32"):
        compute_excursion_ticks(
            100.0,
            np.asarray([99], dtype=np.int32),
            np.asarray([101], dtype=np.int32),
        )
    with pytest.raises(SpineError, match="empty"):
        compute_excursion_ticks(
            np.int32(100), np.asarray([], dtype=np.int32), np.asarray([], dtype=np.int32)
        )
    columns = synthetic_outcome_columns()
    bad = int(np.flatnonzero(columns["ts_event_ns"] == ct_ns("2021-06-15 08:40"))[0])
    columns["low_ticks"][bad] = columns["high_ticks"][bad] + 1
    with pytest.raises(SpineError, match="OHLC"):
        _resolve(columns)


@pytest.mark.parametrize(
    ("columns", "tau", "horizon", "estimand", "expected_status", "flag"),
    [
        (
            synthetic_outcome_columns(missing=("08:30",)),
            "08:35",
            15,
            ESTIMAND_FULLY_LABELED,
            STATUS_ANCHOR_BAR_MISSING,
            None,
        ),
        (
            synthetic_outcome_columns(),
            "14:05",
            60,
            ESTIMAND_FULLY_LABELED,
            STATUS_STRUCTURALLY_UNAVAILABLE,
            None,
        ),
        (
            synthetic_outcome_columns(missing=("08:40",)),
            "08:35",
            15,
            ESTIMAND_OBSERVED,
            STATUS_PATH_TIMESTAMP_MISSING,
            "path_timestamp_missing",
        ),
        (
            synthetic_outcome_columns(session_changes={"08:40": 20210616}),
            "08:35",
            15,
            ESTIMAND_OBSERVED,
            STATUS_PATH_SESSION_MISMATCH,
            "path_session_mismatch",
        ),
        (
            synthetic_outcome_columns(symbol_changes={"08:40": 1}),
            "08:35",
            15,
            ESTIMAND_OBSERVED,
            STATUS_PATH_SYMBOL_MISMATCH,
            "path_symbol_mismatch",
        ),
        (
            synthetic_outcome_columns(partial={"08:40": 3}),
            "08:35",
            15,
            ESTIMAND_FULLY_LABELED,
            STATUS_INSUFFICIENT_COMPONENTS,
            "insufficient_components",
        ),
    ],
)
def test_every_missingness_status_has_a_named_failing_fixture(
    columns, tau, horizon, estimand, expected_status, flag
):
    row = _resolve(columns, tau=tau, horizon=horizon, estimand=estimand)
    assert row["outcome_status"] == expected_status
    assert not row["outcome_valid"]
    if flag is not None:
        assert row[flag]


def test_status_precedence_retains_all_true_diagnostic_flags():
    columns = synthetic_outcome_columns(
        missing=("08:40",),
        symbol_changes={"08:35": 1},
        partial={"08:45": 3},
    )
    row = _resolve(columns)
    assert row["outcome_status"] == STATUS_PATH_TIMESTAMP_MISSING
    assert row["path_timestamp_missing"]
    assert row["path_symbol_mismatch"]
    assert row["insufficient_components"]


def test_public_build_emits_every_anchor_horizon_estimand_row_in_fixed_order(tmp_path):
    columns = synthetic_outcome_columns(missing=("08:25",))
    store = in_memory_store(tmp_path / "exploration" / "bars_5m", columns)
    table = build_outcome_table(store, schedule_table=schedule_for_store(store))
    assert table.row_count == 2 * 78 * 3
    assert table.column("estimand").tolist() == (
        [ESTIMAND_FULLY_LABELED] * (78 * 3)
        + [ESTIMAND_OBSERVED] * (78 * 3)
    )
    assert table.column("horizon_minutes")[:9].tolist() == [15, 30, 60] * 3
    missing_rows = table.column("outcome_status") == STATUS_ANCHOR_BAR_MISSING
    assert int(missing_rows.sum()) == 6  # one anchor x three horizons x two estimands
    validate_outcome_table(table)


def test_public_build_compares_decoded_symbols_not_merely_integer_codes(tmp_path):
    columns = synthetic_outcome_columns(symbol_changes={"08:40": 1})
    store = in_memory_store(
        tmp_path / "exploration" / "bars_5m",
        columns,
        symbols=("MNQM1", "MNQM1"),
    )
    table = build_outcome_table(store, schedule_table=schedule_for_store(store))
    row = _row(table, estimand=ESTIMAND_OBSERVED)
    assert row["outcome_status"] == STATUS_OK
    assert not row["path_symbol_mismatch"]


def test_public_build_flags_a_genuine_decoded_symbol_change(tmp_path):
    columns = synthetic_outcome_columns(symbol_changes={"08:40": 1})
    store = in_memory_store(
        tmp_path / "exploration" / "bars_5m",
        columns,
        symbols=("MNQM1", "MNQU1"),
    )
    table = build_outcome_table(store, schedule_table=schedule_for_store(store))
    row = _row(table, estimand=ESTIMAND_OBSERVED)
    assert row["outcome_status"] == STATUS_PATH_SYMBOL_MISMATCH
    assert row["path_symbol_mismatch"]
    assert not row["outcome_valid"]


def test_duplicate_timestamps_and_impossible_cross_estimand_status_halt(tmp_path):
    columns = synthetic_outcome_columns()
    duplicated = {name: np.insert(value, 1, value[0]) for name, value in columns.items()}
    store = in_memory_store(tmp_path / "exploration" / "bars_5m", duplicated)
    with pytest.raises(SpineError, match="strictly increasing|duplicate"):
        build_outcome_table(store, schedule_table=schedule_for_store(store))

    clean_store = in_memory_store(tmp_path / "clean" / "exploration" / "bars_5m", columns)
    clean = build_outcome_table(clean_store, schedule_table=schedule_for_store(clean_store))
    mutated = clean.mutable_copy()
    full = (
        (mutated["estimand"] == ESTIMAND_FULLY_LABELED)
        & (mutated["tau_ns"] == ct_ns("2021-06-15 08:35"))
        & (mutated["horizon_minutes"] == 15)
    )
    observed = (
        (mutated["estimand"] == ESTIMAND_OBSERVED)
        & (mutated["tau_ns"] == ct_ns("2021-06-15 08:35"))
        & (mutated["horizon_minutes"] == 15)
    )
    mutated["outcome_status"][full] = STATUS_OK
    mutated["outcome_valid"][full] = True
    mutated["outcome_status"][observed] = STATUS_INSUFFICIENT_COMPONENTS
    with pytest.raises(SpineError, match="observed_bar_path"):
        validate_outcome_table(clean.from_columns(mutated))


# ---------------------------------------------------------------------------
# D32 Stage 5 audit finding F-1: nothing proved build_outcome_table actually
# CONSUMES the session schedule. Every fixture used a 15:00 close, so the new
# rule and the old fixed-close rule agreed everywhere and a fixed-15:00 mutant
# survived the whole suite. These tests exercise the disagreement.
# ---------------------------------------------------------------------------


def _rows_at(table, observation_ct, horizon):
    mask = (table.column("observation_time_ct") == observation_ct) & (
        table.column("horizon_minutes") == horizon
    )
    return mask


def test_outcome_layer_honours_a_scheduled_early_close(tmp_path):
    """A window crossing a 12:00 close is structurally unavailable.

    Under the fixed-15:00 rule 11:30 + 60 = 12:30 <= 15:00 would "fit" and the
    row would carry an excursion, inside a session that had already closed.
    """
    store = in_memory_store(
        tmp_path / "exploration" / "bars_5m", synthetic_outcome_columns()
    )
    table = build_outcome_table(
        store,
        schedule_table=schedule_for_store(
            store, close_ct=720, status="shortened_rth"
        ),
    )

    crossing = _rows_at(table, "11:30", 60)
    assert bool(np.any(crossing))
    assert not bool(np.any(table.column("window_fits_rth")[crossing]))
    assert set(table.column("outcome_status")[crossing]) == {
        STATUS_STRUCTURALLY_UNAVAILABLE
    }
    assert set(table.column("structural_unavailability_reason")[crossing]) == {
        "scheduled_close"
    }
    assert not bool(np.any(table.column("outcome_valid")[crossing]))
    for name in (
        "downward_excursion_ticks",
        "upward_excursion_ticks",
        "signed_downward_extreme_ticks",
        "signed_upward_extreme_ticks",
    ):
        assert not bool(np.any(table.column(name)[crossing] != 0))

    # a window comfortably inside the shortened session is untouched
    inside = _rows_at(table, "11:00", 15)
    assert bool(np.any(inside))
    assert bool(np.all(table.column("window_fits_rth")[inside]))
    assert set(table.column("structural_unavailability_reason")[inside]) == {
        "not_applicable"
    }

    # and the boundary is exact: 11:00 + 60 == 12:00 still fits
    boundary = _rows_at(table, "11:00", 60)
    assert bool(np.all(table.column("window_fits_rth")[boundary]))


def test_outcome_layer_emits_no_row_for_an_excluded_session(tmp_path):
    """D33: an excluded session contributes no anchor at all."""
    from tests.unit_o_fixtures import combine_columns

    columns = combine_columns(
        synthetic_outcome_columns("2021-06-15"),
        synthetic_outcome_columns("2021-06-16"),
    )
    store = in_memory_store(tmp_path / "exploration" / "bars_5m", columns)
    excluded_session, kept_session = 20210615, 20210616

    both = build_outcome_table(store, schedule_table=schedule_for_store(store))
    assert bool(np.any(both.column("session_id") == excluded_session))
    assert bool(np.any(both.column("session_id") == kept_session))

    table = build_outcome_table(
        store,
        schedule_table=schedule_for_store(store, excluded=(excluded_session,)),
    )
    assert not bool(np.any(table.column("session_id") == excluded_session))
    assert bool(np.any(table.column("session_id") == kept_session))
    assert table.row_count == both.row_count // 2


def test_each_row_is_judged_against_its_own_session_schedule(tmp_path):
    """Audit F-3: per-session binding, not merely per-table.

    Two sessions, DIFFERENT closes, and the SAME observation time and horizon in
    both. That is what makes this a per-session test: a wrong-session lookup
    still consumes a schedule and still returns a well-formed answer, it just
    returns the wrong one. With a uniform fixture that mistake is invisible.
    """
    from tests.unit_o_fixtures import combine_columns

    early, late = 20210615, 20210616
    store = in_memory_store(
        tmp_path / "exploration" / "bars_5m",
        combine_columns(
            synthetic_outcome_columns("2021-06-15"),
            synthetic_outcome_columns("2021-06-16"),
        ),
    )
    table = build_outcome_table(
        store,
        schedule_table=schedule_for_store(
            store,
            closes={early: 720, late: 900},
            statuses={early: "shortened_rth", late: "full_rth"},
        ),
    )

    def rows(session):
        return (
            (table.column("session_id") == session)
            & (table.column("observation_time_ct") == "11:30")
            & (table.column("horizon_minutes") == 60)
        )

    # 11:30 + 60 = 12:30. Past the early session's 12:00 close ...
    crossing = rows(early)
    assert bool(np.any(crossing))
    assert not bool(np.any(table.column("window_fits_rth")[crossing]))
    assert set(table.column("outcome_status")[crossing]) == {
        "structurally_unavailable"
    }
    assert set(table.column("structural_unavailability_reason")[crossing]) == {
        "scheduled_close"
    }

    # ... and comfortably inside the late session's 15:00 close.
    inside = rows(late)
    assert bool(np.any(inside))
    assert bool(np.all(table.column("window_fits_rth")[inside]))
    assert set(table.column("outcome_status")[inside]) == {"ok"}
    assert set(table.column("structural_unavailability_reason")[inside]) == {
        "not_applicable"
    }


def test_structural_status_string_is_pinned_literally():
    """Audit C-10: the constant's value cannot be renamed silently."""
    assert STATUS_STRUCTURALLY_UNAVAILABLE == "structurally_unavailable"
    assert len(STATUS_STRUCTURALLY_UNAVAILABLE) == 24  # fits the <U25 dtype


def test_heterogeneous_store_judges_full_shortened_and_no_rth_sessions(tmp_path):
    """Audit F-3 follow-up: all three schedule kinds in ONE store.

    Same observation time and horizon in every session, three different
    verdicts. no_scheduled_rth had no build_outcome_table coverage at all,
    because the fixture could not construct such a session.

    The no-RTH session carries a full set of synthetic bars. Its rows are still
    unavailable, which is the point: availability comes from the schedule, never
    from what happens to be observed.
    """
    from tests.unit_o_fixtures import combine_columns

    full, shortened, no_rth = 20210615, 20210616, 20210617
    store = in_memory_store(
        tmp_path / "exploration" / "bars_5m",
        combine_columns(
            synthetic_outcome_columns("2021-06-15"),
            synthetic_outcome_columns("2021-06-16"),
            synthetic_outcome_columns("2021-06-17"),
        ),
    )
    table = build_outcome_table(
        store,
        schedule_table=schedule_for_store(
            store,
            closes={full: 900, shortened: 720},
            statuses={
                full: "full_rth",
                shortened: "shortened_rth",
                no_rth: "no_scheduled_rth",
            },
        ),
    )

    def rows(session):
        mask = (
            (table.column("session_id") == session)
            & (table.column("observation_time_ct") == "11:30")
            & (table.column("horizon_minutes") == 60)
        )
        assert bool(np.any(mask)), session
        return mask

    # full RTH: 11:30 + 60 = 12:30, comfortably inside a 15:00 close
    m = rows(full)
    assert bool(np.all(table.column("window_fits_rth")[m]))
    assert set(table.column("outcome_status")[m]) == {"ok"}
    assert set(table.column("structural_unavailability_reason")[m]) == {
        "not_applicable"
    }
    assert bool(np.all(table.column("outcome_valid")[m]))

    # shortened RTH: the same window runs 30 minutes past a 12:00 close
    m = rows(shortened)
    assert not bool(np.any(table.column("window_fits_rth")[m]))
    assert not bool(np.any(table.column("outcome_valid")[m]))
    assert set(table.column("outcome_status")[m]) == {"structurally_unavailable"}
    assert set(table.column("structural_unavailability_reason")[m]) == {
        "scheduled_close"
    }

    # no scheduled RTH: no window is available at all, bars notwithstanding
    m = rows(no_rth)
    assert not bool(np.any(table.column("window_fits_rth")[m]))
    assert not bool(np.any(table.column("outcome_valid")[m]))
    assert set(table.column("outcome_status")[m]) == {"structurally_unavailable"}
    assert set(table.column("structural_unavailability_reason")[m]) == {
        "no_scheduled_rth"
    }
