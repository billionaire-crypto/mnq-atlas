"""Independent semantic-mask, dependency-locality, and prefix tests for Unit O."""

from __future__ import annotations

import numpy as np

from mnq_lab.outcomes.excursions import (
    ESTIMAND_FULLY_LABELED,
    ESTIMAND_OBSERVED,
    STATUS_INSUFFICIENT_COMPONENTS,
    STATUS_OK,
    build_outcome_table,
    outcome_dependency_masks,
    resolve_outcome_row,
)
from tests.conftest import ct_ns
from tests.unit_o_fixtures import (
    schedule_for_store,
    combine_columns,
    independent_semantic_masks,
    in_memory_store,
    synthetic_outcome_columns,
)


def _resolve(columns, estimand=ESTIMAND_FULLY_LABELED):
    return resolve_outcome_row(
        columns,
        session_id=20210615,
        tau_ns=ct_ns("2021-06-15 08:35"),
        tau_ct_minute=8 * 60 + 35,
        session_phase="open",
        horizon_minutes=15,
        estimand=estimand,
    )


def test_production_dependency_masks_equal_independent_semantics_exactly():
    columns = synthetic_outcome_columns()
    labels = columns["ts_event_ns"]
    tau_ns = ct_ns("2021-06-15 08:35")
    for estimand in (ESTIMAND_FULLY_LABELED, ESTIMAND_OBSERVED):
        declared = outcome_dependency_masks(labels, tau_ns, 15, estimand)
        expected_bar, expected_component = independent_semantic_masks(
            labels, tau_ns, 15, estimand
        )
        assert expected_bar.any() and expected_component.shape == expected_bar.shape
        assert np.array_equal(declared.bar_rows, expected_bar)
        assert np.array_equal(declared.component_rows, expected_component)


def test_widened_and_narrowed_masks_fail_exact_equality():
    columns = synthetic_outcome_columns()
    labels = columns["ts_event_ns"]
    tau_ns = ct_ns("2021-06-15 08:35")
    declared = outcome_dependency_masks(
        labels, tau_ns, 15, ESTIMAND_FULLY_LABELED
    ).bar_rows
    expected, _ = independent_semantic_masks(
        labels, tau_ns, 15, ESTIMAND_FULLY_LABELED
    )
    witnesses = {
        "one_bar_before_anchor": ct_ns("2021-06-15 08:25"),
        "bar_at_tau_plus_delta": ct_ns("2021-06-15 08:50"),
    }
    for coordinate in witnesses.values():
        widened = declared.copy()
        widened[labels == coordinate] = True
        assert not np.array_equal(widened, expected)
    for coordinate in (
        ct_ns("2021-06-15 08:30"),
        ct_ns("2021-06-15 08:35"),
        ct_ns("2021-06-15 08:40"),
        ct_ns("2021-06-15 08:45"),
    ):
        narrowed = declared.copy()
        narrowed[labels == coordinate] = False
        assert not np.array_equal(narrowed, expected)


def test_out_of_window_price_mutation_is_bit_identical_and_in_window_witness_moves():
    columns = synthetic_outcome_columns(
        price_overrides={
            "08:30": (100, 101, 99, 100),
            "08:35": (100, 103, 98, 100),
            "08:40": (100, 104, 97, 100),
            "08:45": (100, 105, 96, 100),
        }
    )
    baseline = _resolve(columns)
    out_of_window = {name: value.copy() for name, value in columns.items()}
    outside_index = int(
        np.flatnonzero(columns["ts_event_ns"] == ct_ns("2021-06-15 10:00"))[0]
    )
    out_of_window["high_ticks"][outside_index] += np.int32(500)
    assert _resolve(out_of_window) == baseline

    in_window = {name: value.copy() for name, value in columns.items()}
    witness_index = int(
        np.flatnonzero(columns["ts_event_ns"] == ct_ns("2021-06-15 08:40"))[0]
    )
    in_window["high_ticks"][witness_index] += np.int32(500)
    assert _resolve(in_window)["upward_excursion_ticks"] != baseline[
        "upward_excursion_ticks"
    ]


def test_component_fields_are_dependencies_only_for_fully_labeled_estimand():
    columns = synthetic_outcome_columns()
    observed_before = _resolve(columns, ESTIMAND_OBSERVED)
    full_before = _resolve(columns, ESTIMAND_FULLY_LABELED)
    assert observed_before["outcome_status"] == full_before["outcome_status"] == STATUS_OK

    mutated = {name: value.copy() for name, value in columns.items()}
    index = int(
        np.flatnonzero(columns["ts_event_ns"] == ct_ns("2021-06-15 08:40"))[0]
    )
    mutated["observed_1m_components"][index] = 3
    observed_after = _resolve(mutated, ESTIMAND_OBSERVED)
    full_after = _resolve(mutated, ESTIMAND_FULLY_LABELED)
    for name in (
        "outcome_status",
        "outcome_valid",
        "n_present_bars",
        "downward_excursion_ticks",
        "upward_excursion_ticks",
        "signed_downward_extreme_ticks",
        "signed_upward_extreme_ticks",
    ):
        assert observed_after[name] == observed_before[name]
    assert observed_after["n_fully_labeled_bars"] == 2
    assert observed_before["n_fully_labeled_bars"] == 3
    assert full_after["outcome_status"] == STATUS_INSUFFICIENT_COMPONENTS


def _prefix_rows(table, last_session=20210615):
    mask = table.column("session_id") <= last_session
    return {name: values[mask] for name, values in table.columns.items()}


def test_prefix_extension_preserves_every_value_status_support_and_mask(tmp_path):
    first = synthetic_outcome_columns("2021-06-15")
    second = synthetic_outcome_columns("2021-06-16")
    _prefix_store = in_memory_store(tmp_path / "prefix" / "exploration" / "bars_5m", first)
    prefix_table = build_outcome_table(
        _prefix_store, schedule_table=schedule_for_store(_prefix_store)
    )
    extended_columns = combine_columns(first, second)
    _extended_store = in_memory_store(
        tmp_path / "extended" / "exploration" / "bars_5m", extended_columns
    )
    extended_table = build_outcome_table(
        _extended_store, schedule_table=schedule_for_store(_extended_store)
    )
    prefix_rows = _prefix_rows(prefix_table)
    extended_prefix = _prefix_rows(extended_table)
    assert prefix_table.row_count > 0
    assert extended_table.row_count > prefix_table.row_count
    for name in prefix_rows:
        assert np.array_equal(prefix_rows[name], extended_prefix[name]), name

    tau_ns = ct_ns("2021-06-15 08:35")
    short_mask = outcome_dependency_masks(
        first["ts_event_ns"], tau_ns, 60, ESTIMAND_FULLY_LABELED
    )
    long_mask = outcome_dependency_masks(
        extended_columns["ts_event_ns"], tau_ns, 60, ESTIMAND_FULLY_LABELED
    )
    n_prefix = len(first["ts_event_ns"])
    assert np.array_equal(short_mask.bar_rows, long_mask.bar_rows[:n_prefix])
    assert not long_mask.bar_rows[n_prefix:].any()
    assert np.array_equal(
        short_mask.component_rows, long_mask.component_rows[:n_prefix]
    )
    assert not long_mask.component_rows[n_prefix:].any()


def test_backward_carry_mutant_fails_the_same_nonempty_prefix_fixture(tmp_path):
    first = synthetic_outcome_columns("2021-06-15")
    second = synthetic_outcome_columns(
        "2021-06-16", price_overrides={"14:55": (1_000, 20_000, 998, 1_000)}
    )
    prefix_store = in_memory_store(
        tmp_path / "prefix" / "exploration" / "bars_5m", first
    )
    extended_store = in_memory_store(
        tmp_path / "extended" / "exploration" / "bars_5m",
        combine_columns(first, second),
    )

    def backward_carry_mutant(store):
        table = build_outcome_table(store, schedule_table=schedule_for_store(store))
        columns = table.mutable_copy()
        first_valid = int(np.flatnonzero(columns["outcome_valid"])[0])
        columns["upward_excursion_ticks"][first_valid] = np.int32(
            int(np.max(store["high_ticks"].astype(np.int64)))
            - int(columns["anchor_close_ticks"][first_valid])
        )
        return table.from_columns(columns)

    prefix_mutant = _prefix_rows(backward_carry_mutant(prefix_store))
    extended_mutant = _prefix_rows(backward_carry_mutant(extended_store))
    assert prefix_mutant["session_id"].size > 0
    assert not np.array_equal(
        prefix_mutant["upward_excursion_ticks"],
        extended_mutant["upward_excursion_ticks"],
    )
