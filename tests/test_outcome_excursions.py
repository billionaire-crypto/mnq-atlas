"""Unit O status, resolver, and int64-safe excursion tests."""

from __future__ import annotations

import numpy as np
import pytest

from mnq_lab import SpineError
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
    STATUS_WINDOW_OUTSIDE_RTH,
    build_outcome_table,
    compute_excursion_ticks,
    resolve_outcome_row,
    validate_outcome_table,
)
from tests.conftest import ct_ns
from tests.unit_o_fixtures import (
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
        STATUS_WINDOW_OUTSIDE_RTH,
        STATUS_PATH_TIMESTAMP_MISSING,
        STATUS_PATH_SESSION_MISMATCH,
        STATUS_PATH_SYMBOL_MISMATCH,
        STATUS_INSUFFICIENT_COMPONENTS,
        STATUS_OK,
    )


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
            STATUS_WINDOW_OUTSIDE_RTH,
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
    table = build_outcome_table(store)
    assert table.row_count == 2 * 78 * 3
    assert table.column("estimand").tolist() == (
        [ESTIMAND_FULLY_LABELED] * (78 * 3)
        + [ESTIMAND_OBSERVED] * (78 * 3)
    )
    assert table.column("horizon_minutes")[:9].tolist() == [15, 30, 60] * 3
    missing_rows = table.column("outcome_status") == STATUS_ANCHOR_BAR_MISSING
    assert int(missing_rows.sum()) == 6  # one anchor x three horizons x two estimands
    validate_outcome_table(table)


def test_duplicate_timestamps_and_impossible_cross_estimand_status_halt(tmp_path):
    columns = synthetic_outcome_columns()
    duplicated = {name: np.insert(value, 1, value[0]) for name, value in columns.items()}
    store = in_memory_store(tmp_path / "exploration" / "bars_5m", duplicated)
    with pytest.raises(SpineError, match="strictly increasing|duplicate"):
        build_outcome_table(store)

    clean = build_outcome_table(
        in_memory_store(tmp_path / "clean" / "exploration" / "bars_5m", columns)
    )
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
    with pytest.raises(SpineError, match="impossible"):
        validate_outcome_table(clean.from_columns(mutated))
