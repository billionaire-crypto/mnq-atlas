"""`test_estimand_definition` (spec §13 test-18 list) — completion accounting (§6).

The two estimands carry exactly the §6 names — `fully_labeled_1m_grid` and
`observed_bar_path`; §14 struck `complete_1m_path`/`observed_trade_path` and this
file asserts the struck names appear nowhere in the package. The window-level
discriminating case mirrors §13 test 5: a 5-min bar built from fewer than five
1-min rows is rejected under `fully_labeled_1m_grid` and retained (visible, with
its reduced coverage counted) under `observed_bar_path`.

Also pins the §10.2 support distinction the schema must keep structural:
`state_anchor` is independent of every outcome window, so prevalence built on it
cannot depend on Δ, while `outcome_eligible_*_h{Δ}` shrinks as Δ grows.
"""

from __future__ import annotations

import numpy as np
import pytest

from mnq_lab.constants import REPO_ROOT, load_constants
from mnq_lab.outcomes.completion import (
    ESTIMAND_FULLY_LABELED,
    ESTIMAND_OBSERVED,
    anchor_outcome_completion,
    completion_by_cell,
    completion_by_year,
)
from mnq_lab.spine.timemodel import TimeModel

from tests.conftest import synthetic_session_bars

ORDINARY = "2021-06-15"


@pytest.fixture(scope="module")
def time_model() -> TimeModel:
    return TimeModel.from_constants(load_constants())


def completion_frame(time_model, **kwargs):
    session, ts, observed, expected = synthetic_session_bars(ORDINARY, **kwargs)
    return anchor_outcome_completion(time_model, session, ts, observed, expected)


def row_at(frame, tau_minute):
    rows = frame[frame["tau_ct_minute"] == tau_minute]
    assert len(rows) == 1
    return rows.iloc[0]


# --- the estimand names are the frozen ones -----------------------------------------

def test_estimand_names_match_the_yaml_and_spec():
    constants = load_constants()
    assert ESTIMAND_FULLY_LABELED == constants.get("estimands", "path")
    assert ESTIMAND_FULLY_LABELED == "fully_labeled_1m_grid"
    assert ESTIMAND_OBSERVED == "observed_bar_path"


def test_struck_estimand_names_appear_nowhere_in_the_package():
    """§14: `complete_1m_path` / `observed_trade_path` must not be reintroduced."""
    offenders = []
    for path in sorted((REPO_ROOT / "mnq_lab").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for struck in ("complete_1m_path", "observed_trade_path"):
            if struck in text:
                offenders.append(f"{path.name}: {struck}")
    assert not offenders, offenders


# --- the §13-test-5 discriminating case, at window level ----------------------------

def test_a_partially_labeled_bar_splits_the_two_estimands(time_model):
    """Window 08:55/09:00/09:05 where the 09:00 bar has 3 of 5 labels: complete
    under `observed_bar_path`, incomplete under `fully_labeled_1m_grid`."""
    frame = completion_frame(time_model, partial={"09:00": 3})
    anchor = row_at(frame, 8 * 60 + 55)  # τ=08:55, Δ15 window covers 09:00

    assert anchor["n_required_h15"] == 3
    assert anchor["n_present_h15"] == 3
    assert anchor["n_fully_labeled_h15"] == 2
    assert anchor[f"complete_{ESTIMAND_OBSERVED}_h15"]
    assert not anchor[f"complete_{ESTIMAND_FULLY_LABELED}_h15"]
    assert anchor[f"outcome_eligible_{ESTIMAND_OBSERVED}_h15"]
    assert not anchor[f"outcome_eligible_{ESTIMAND_FULLY_LABELED}_h15"]


def test_a_bar_expecting_fewer_than_five_labels_is_not_fully_labeled(time_model):
    """Audit finding M-3 (2026-07-28): the `expected == 5` conjunct was untested.

    Every prior fixture set `expected_1m_components = 5`, so the criterion
    `(observed == expected) & (expected == 5)` was indistinguishable from
    `observed == expected` and the mutation dropping the second conjunct survived
    the whole suite. Here the 09:00 bar has `observed == expected == 3`: it is
    internally consistent but does NOT carry a full 1-minute grid, so
    `fully_labeled_1m_grid` must reject it while `observed_bar_path` retains it.
    """
    frame = completion_frame(time_model, expected_components={"09:00": 3})
    anchor = row_at(frame, 8 * 60 + 55)  # Δ15 window covers 08:55/09:00/09:05

    assert anchor["n_present_h15"] == 3
    assert anchor["n_fully_labeled_h15"] == 2  # the 09:00 bar does not count
    assert not anchor[f"complete_{ESTIMAND_FULLY_LABELED}_h15"]
    assert anchor[f"complete_{ESTIMAND_OBSERVED}_h15"]
    assert not anchor[f"outcome_eligible_{ESTIMAND_FULLY_LABELED}_h15"]
    assert anchor[f"outcome_eligible_{ESTIMAND_OBSERVED}_h15"]


def test_a_wholly_missing_bar_fails_both_estimands(time_model):
    """A window crossing an absent 5-min interval is incomplete under BOTH — an
    excursion across it would invent prices (binding D12 user ruling)."""
    frame = completion_frame(time_model, missing=("10:00",))
    anchor = row_at(frame, 9 * 60 + 55)  # τ=09:55, Δ15 window needs 10:00

    assert anchor["n_present_h15"] == 2
    assert not anchor[f"complete_{ESTIMAND_OBSERVED}_h15"]
    assert not anchor[f"complete_{ESTIMAND_FULLY_LABELED}_h15"]
    # An untouched window on the same session is complete under both.
    clean = row_at(frame, 8 * 60 + 35)
    assert clean[f"complete_{ESTIMAND_OBSERVED}_h15"]
    assert clean[f"complete_{ESTIMAND_FULLY_LABELED}_h15"]


def test_the_anchor_bars_own_completeness_is_not_required(time_model):
    """Ruling 1: the worked example lists only outcome-path bars as required. An
    anchor whose own bar has 2 of 5 labels still anchors, and its outcome windows
    are judged on the outcome path alone."""
    frame = completion_frame(time_model, partial={"08:30": 2})
    anchor = row_at(frame, 8 * 60 + 35)  # τ=08:35 observes the 08:30 bar's close
    assert anchor["state_anchor"]
    assert anchor[f"outcome_eligible_{ESTIMAND_FULLY_LABELED}_h15"]
    assert anchor[f"outcome_eligible_{ESTIMAND_OBSERVED}_h15"]
    # But a window that CONTAINS that partial bar notices it: τ=08:30's Δ15
    # window covers 08:30, so the fully-labeled estimand rejects it there.
    upstream = row_at(frame, 8 * 60 + 30)
    assert not upstream[f"complete_{ESTIMAND_FULLY_LABELED}_h15"]
    assert upstream[f"complete_{ESTIMAND_OBSERVED}_h15"]


# --- §10.2: prevalence support vs outcome support -----------------------------------

def test_state_anchors_are_horizon_invariant_and_eligibility_shrinks(time_model):
    frame = completion_frame(time_model)
    n_state = int(frame["state_anchor"].sum())
    assert n_state == 78  # full session: every declared anchor exists

    eligible = {
        h: int(frame[f"outcome_eligible_{ESTIMAND_FULLY_LABELED}_h{h}"].sum())
        for h in (15, 30, 60)
    }
    # τ=14:50/14:55 (and later τ as Δ grows) are outcome-ineligible but remain
    # state anchors: 78 state anchors at every horizon, eligibility 76/73/67.
    assert eligible == {15: 76, 30: 73, 60: 67}
    assert eligible[60] < eligible[30] < eligible[15] < n_state

    late = frame[frame["tau_ct_minute"] >= 14 * 60 + 50]
    assert late["state_anchor"].all()
    for h in (15, 30, 60):
        assert not late[f"outcome_eligible_{ESTIMAND_FULLY_LABELED}_h{h}"].any()


# --- cell summaries: every declared cell, with honest companions --------------------

def test_every_declared_cell_is_emitted_with_status(time_model):
    frame = completion_frame(time_model)
    by_cell = completion_by_cell(frame, time_model)
    assert len(by_cell) == 15  # 5 phases × 3 horizons, unconditionally
    assert by_cell["phase"].tolist() == [
        p for p in time_model.phase_names for _ in time_model.horizons_minutes
    ]
    assert (by_cell["status"] == "ok").all()
    # §16.4.6: n_anchors never without n_sessions and weight_ess beside it.
    for required in ("n_anchors", "n_sessions", "weight_ess"):
        assert required in by_cell.columns
    assert by_cell["weight_ess"].isna().all()  # weighting arrives in Phase 4

    close = by_cell[by_cell["phase"] == "close"].set_index("horizon_minutes")
    assert close.loc[60, "n_anchors"] == 1  # the registered §4.2 prediction again
    assert close.loc[30, "n_anchors"] == 7
    assert close.loc[15, "n_anchors"] == 10


def test_an_empty_cell_gets_a_status_not_an_absence(time_model):
    """A session whose close-phase bars are all absent: the close × Δ cells are
    still emitted, with no structurally eligible anchors and NaN rates."""
    frame = completion_frame(time_model, last_label_exclusive="13:55")
    by_cell = completion_by_cell(frame, time_model)
    close = by_cell[by_cell["phase"] == "close"].set_index("horizon_minutes")
    assert len(close) == 3
    for horizon in (15, 30, 60):
        row = close.loc[horizon]
        # Structural eligibility needs the anchor bar itself; none exist.
        assert row["n_anchors"] == 0
        assert row["status"] == "no_structurally_eligible_anchors"
        assert np.isnan(row[f"completion_rate_{ESTIMAND_FULLY_LABELED}"])


def test_negative_the_summary_reads_the_data_not_its_own_assumptions(time_model):
    """Mutating the completion booleans must move the rates — otherwise the
    summary could not fail and would be worse than no check."""
    frame = completion_frame(time_model)
    intact = completion_by_cell(frame, time_model)
    assert (
        intact[intact["phase"] == "open"].iloc[0][
            f"completion_rate_{ESTIMAND_FULLY_LABELED}"
        ]
        == 1.0
    )
    broken = frame.copy()
    broken[f"complete_{ESTIMAND_FULLY_LABELED}_h15"] = False
    mutated = completion_by_cell(broken, time_model)
    open_h15 = mutated[
        (mutated["phase"] == "open") & (mutated["horizon_minutes"] == 15)
    ].iloc[0]
    assert open_h15[f"completion_rate_{ESTIMAND_FULLY_LABELED}"] == 0.0
    assert open_h15[f"completion_rate_{ESTIMAND_OBSERVED}"] == 1.0


def test_completion_by_year_separates_years(time_model):
    s1, t1, o1, e1 = synthetic_session_bars("2021-06-15", partial={"09:00": 3})
    s2, t2, o2, e2 = synthetic_session_bars("2022-06-15")
    frame = anchor_outcome_completion(
        time_model,
        np.concatenate([s1, s2]),
        np.concatenate([t1, t2]),
        np.concatenate([o1, o2]),
        np.concatenate([e1, e2]),
    )
    by_year = completion_by_year(frame, time_model)
    assert len(by_year) == 6  # 2 years × 3 horizons
    assert by_year["year"].tolist() == [2021, 2021, 2021, 2022, 2022, 2022]

    y2021_h15 = by_year[(by_year["year"] == 2021) & (by_year["horizon_minutes"] == 15)].iloc[0]
    y2022_h15 = by_year[(by_year["year"] == 2022) & (by_year["horizon_minutes"] == 15)].iloc[0]
    assert y2022_h15["n_anchors"] > 0
    # 2021 carries the partial 09:00 bar; three Δ15 windows cross it (τ 08:50,
    # 08:55, 09:00), so exactly 3 of 76 eligible windows fail the labeled grid.
    assert y2021_h15[f"n_complete_{ESTIMAND_FULLY_LABELED}"] == 73
    assert y2021_h15[f"n_complete_{ESTIMAND_OBSERVED}"] == 76
    assert y2022_h15[f"n_complete_{ESTIMAND_FULLY_LABELED}"] == 76


def test_an_absent_intervening_year_is_emitted_as_an_empty_cell(time_model):
    """Audit finding L-1 (2026-07-28): iterating only the years PRESENT dropped
    absent intervening years, so a 2021+2023 corpus silently omitted all three
    2022 cells. The declared year axis is the contiguous span (spec §16.4.5)."""
    s1, t1, o1, e1 = synthetic_session_bars("2021-06-15")
    s2, t2, o2, e2 = synthetic_session_bars("2023-06-15")
    frame = anchor_outcome_completion(
        time_model,
        np.concatenate([s1, s2]),
        np.concatenate([t1, t2]),
        np.concatenate([o1, o2]),
        np.concatenate([e1, e2]),
    )
    by_year = completion_by_year(frame, time_model)
    assert by_year["year"].unique().tolist() == [2021, 2022, 2023]
    assert len(by_year) == 9

    absent = by_year[by_year["year"] == 2022]
    assert len(absent) == 3
    assert (absent["n_anchors"] == 0).all()
    assert (absent["status"] == "no_structurally_eligible_anchors").all()
    assert absent[f"completion_rate_{ESTIMAND_FULLY_LABELED}"].isna().all()


# --- the real exploration store -----------------------------------------------------

@pytest.fixture(scope="module")
def real_completion(time_model, exploration_5m):
    return anchor_outcome_completion(
        time_model,
        np.asarray(exploration_5m["session_id"]),
        np.asarray(exploration_5m["ts_event_ns"]),
        np.asarray(exploration_5m["observed_1m_components"]),
        np.asarray(exploration_5m["expected_1m_components"]),
    )


def test_real_store_emits_the_full_declared_grid(real_completion, exploration_5m):
    n_sessions = len(np.unique(np.asarray(exploration_5m["session_id"])))
    assert n_sessions == 1009
    assert len(real_completion) == n_sessions * 78


def test_real_store_completion_rates_are_coherent(real_completion, time_model):
    by_cell = completion_by_cell(real_completion, time_model)
    assert len(by_cell) == 15
    assert (by_cell["status"] == "ok").all()
    for _, row in by_cell.iterrows():
        rate_fully = row[f"completion_rate_{ESTIMAND_FULLY_LABELED}"]
        rate_observed = row[f"completion_rate_{ESTIMAND_OBSERVED}"]
        assert 0.0 <= rate_fully <= rate_observed <= 1.0
        assert row["n_sessions"] <= row["n_anchors"] or row["n_anchors"] == 0
    # 42 RTH bars carry partial 1-min coverage (measured 2026-07-28), so the two
    # estimands must actually diverge somewhere on the real store.
    assert (
        by_cell[f"n_complete_{ESTIMAND_FULLY_LABELED}"].sum()
        < by_cell[f"n_complete_{ESTIMAND_OBSERVED}"].sum()
    )


# --- the CLI entry point, end to end -------------------------------------------------

def _write_cli_store(root, trade_date, bar_seconds):
    """A real on-disk store (no mocks) shaped the way `completion._run` opens it."""
    from mnq_lab.spine.store import write_store

    session, ts, observed, expected = synthetic_session_bars(trade_date)
    write_store(
        root / "exploration" / "bars_5m",
        {
            "session_id": session,
            "ts_event_ns": ts,
            "observed_1m_components": observed,
            "expected_1m_components": expected,
        },
        metadata={"bar_seconds": bar_seconds},
    )
    return root


def test_the_cli_entry_point_refuses_a_wrong_duration_store(tmp_path):
    """Round-2 audit finding M-1 (2026-07-28): `assert_store_bar_seconds` was
    tested only as a standalone helper, so DELETING ITS CALL from the CLI path
    survived the whole suite — the wiring, not the helper, was the unpinned
    claim. This drives `completion._run` end to end against a real on-disk store
    whose manifest declares 600-second bars, and must fail closed there.
    """
    from mnq_lab import SpineError
    from mnq_lab.outcomes import completion

    bad = _write_cli_store(tmp_path / "bad", ORDINARY, bar_seconds=600)
    with pytest.raises(SpineError, match="bar_seconds=600"):
        completion._run(bad)

    # Positive control through the SAME entry point: a 300-second store passes
    # the guard and produces the full declared cell grid, so the negative case
    # above fails on the guard, not on some unrelated breakage in _run.
    good = _write_cli_store(tmp_path / "good", ORDINARY, bar_seconds=300)
    result = completion._run(good)
    assert result["n_sessions"] == 1
    assert result["n_gridpoints"] == 78
    assert len(result["by_cell"]) == 15


def test_real_store_prevalence_support_is_horizon_invariant(real_completion):
    """§10.2 on real data: state anchors do not depend on any horizon column."""
    n_state = int(real_completion["state_anchor"].sum())
    assert n_state > 0
    for h in (15, 30, 60):
        eligible = int(
            real_completion[f"outcome_eligible_{ESTIMAND_FULLY_LABELED}_h{h}"].sum()
        )
        assert eligible < n_state


# --- Unit O realizes both path estimands without changing their definitions --------

def test_unit_o_partial_components_split_status_but_not_observed_excursion(tmp_path):
    from mnq_lab.outcomes.excursions import (
        ESTIMAND_FULLY_LABELED as O_FULL,
        ESTIMAND_OBSERVED as O_OBSERVED,
        STATUS_INSUFFICIENT_COMPONENTS,
        STATUS_OK as OUTCOME_OK,
        build_outcome_table,
    )
    from tests.conftest import ct_ns
    from tests.unit_o_fixtures import (
        in_memory_store,
        schedule_for_store,
        synthetic_outcome_columns,
    )

    columns = synthetic_outcome_columns(partial={"08:40": 3})
    _store = in_memory_store(tmp_path / "exploration" / "bars_5m", columns)
    table = build_outcome_table(_store, schedule_table=schedule_for_store(_store))
    key = (table.column("tau_ns") == ct_ns(f"{ORDINARY} 08:35")) & (
        table.column("horizon_minutes") == 15
    )
    full = key & (table.column("estimand") == O_FULL)
    observed = key & (table.column("estimand") == O_OBSERVED)
    assert table.column("outcome_status")[full].tolist() == [
        STATUS_INSUFFICIENT_COMPONENTS
    ]
    assert table.column("outcome_status")[observed].tolist() == [OUTCOME_OK]
    assert not table.column("outcome_valid")[full].item()
    assert table.column("outcome_valid")[observed].item()


def test_unit_o_wholly_missing_bar_fails_both_estimands(tmp_path):
    from mnq_lab.outcomes.excursions import (
        STATUS_PATH_TIMESTAMP_MISSING,
        build_outcome_table,
    )
    from tests.conftest import ct_ns
    from tests.unit_o_fixtures import (
        in_memory_store,
        schedule_for_store,
        synthetic_outcome_columns,
    )

    columns = synthetic_outcome_columns(missing=("08:40",))
    _store = in_memory_store(tmp_path / "exploration" / "bars_5m", columns)
    table = build_outcome_table(_store, schedule_table=schedule_for_store(_store))
    rows = (table.column("tau_ns") == ct_ns(f"{ORDINARY} 08:35")) & (
        table.column("horizon_minutes") == 15
    )
    assert table.column("outcome_status")[rows].tolist() == [
        STATUS_PATH_TIMESTAMP_MISSING,
        STATUS_PATH_TIMESTAMP_MISSING,
    ]


def test_unit_o_common_support_is_per_estimand_not_their_intersection(tmp_path):
    from mnq_lab.outcomes.excursions import (
        ESTIMAND_FULLY_LABELED as O_FULL,
        ESTIMAND_OBSERVED as O_OBSERVED,
        STATUS_OK as OUTCOME_OK,
        build_outcome_table,
    )
    from tests.conftest import ct_ns
    from tests.unit_o_fixtures import (
        in_memory_store,
        schedule_for_store,
        synthetic_outcome_columns,
    )

    columns = synthetic_outcome_columns(partial={"09:20": 3})
    _store = in_memory_store(tmp_path / "exploration" / "bars_5m", columns)
    table = build_outcome_table(_store, schedule_table=schedule_for_store(_store))
    key = (table.column("tau_ns") == ct_ns(f"{ORDINARY} 08:35")) & (
        table.column("horizon_minutes") == 15
    )
    full = key & (table.column("estimand") == O_FULL)
    observed = key & (table.column("estimand") == O_OBSERVED)
    assert table.column("outcome_status")[full].item() == OUTCOME_OK
    assert table.column("outcome_status")[observed].item() == OUTCOME_OK
    assert not table.column("common_support")[full].item()
    assert table.column("common_support")[observed].item()


def test_unit_o_anchor_component_count_is_not_an_outcome_requirement(tmp_path):
    from mnq_lab.outcomes.excursions import (
        ESTIMAND_FULLY_LABELED as O_FULL,
        STATUS_OK as OUTCOME_OK,
        build_outcome_table,
    )
    from tests.conftest import ct_ns
    from tests.unit_o_fixtures import (
        in_memory_store,
        schedule_for_store,
        synthetic_outcome_columns,
    )

    columns = synthetic_outcome_columns(partial={"08:30": 2})
    _store = in_memory_store(tmp_path / "exploration" / "bars_5m", columns)
    table = build_outcome_table(_store, schedule_table=schedule_for_store(_store))
    row = (
        (table.column("estimand") == O_FULL)
        & (table.column("tau_ns") == ct_ns(f"{ORDINARY} 08:35"))
        & (table.column("horizon_minutes") == 15)
    )
    assert table.column("outcome_status")[row].item() == OUTCOME_OK
