"""Phase 10 fast point path remains equivalent to the Phase 8 composition."""

from __future__ import annotations

import numpy as np
import pytest

from mnq_lab.phase10.evaluation import _one_cell
from mnq_lab.phase8.contrasts import (
    CellKey,
    SESSION_PHASES,
    VOLATILITY_STATES,
    prepare_weighted_quantile_ticks,
)
from mnq_lab.phase8.inventory import PRIMARY_ARM_ID, ResultRowSpec
from mnq_lab.phase8.production import (
    ArmFrame,
    ProductionInputs,
    _contrast_partition,
)


def _fixture(weighting="natural_prevalence_contrast", support_case="ok"):
    session_keys = np.arange(60, dtype=np.int32) + 20210101
    cell_phases = np.repeat(np.asarray(SESSION_PHASES), len(VOLATILITY_STATES))
    cell_states = np.tile(np.asarray(VOLATILITY_STATES), len(SESSION_PHASES))
    width = cell_phases.size
    sessions = np.repeat(session_keys, width)
    timestamps = np.arange(sessions.size, dtype=np.int64) * 300_000_000_000
    phases = np.tile(cell_phases, session_keys.size)
    states = np.tile(cell_states, session_keys.size)
    active = np.ones(sessions.size, dtype=np.bool_)
    completed = np.ones(sessions.size, dtype=np.bool_)
    values = (
        np.arange(sessions.size, dtype=np.int64) % 97
    ).astype(np.int32)
    years = np.full(sessions.size, 2021, dtype=np.int64)
    target = CellKey("open", "high")
    target_rows = (phases == target.phase) & (states == target.volatility_state)
    if support_case == "missing":
        active[target_rows] = False
    elif support_case == "thin":
        active[target_rows & (sessions > session_keys[1])] = False
    elif support_case == "incomplete":
        completed[target_rows] = False
    elif support_case != "ok":
        raise AssertionError(f"unknown support case: {support_case}")
    direct = _one_cell(
        values=values,
        prepared_values=prepare_weighted_quantile_ticks(values),
        session_ids=sessions,
        years=years,
        phases=phases,
        states=states,
        active=active,
        completed=completed,
        structural_fit=np.ones(sessions.size, dtype=np.bool_),
        target=target,
        weighting=weighting,
    )
    unit = {
        "estimand": np.full(sessions.size, "fully_labeled_1m_grid"),
        "session_id": sessions,
        "ts_event_ns": timestamps,
        "horizon_minutes": np.full(sessions.size, 30, dtype=np.int16),
        "window_fits_rth": np.ones(sessions.size, dtype=np.bool_),
        "common_support": np.ones(sessions.size, dtype=np.bool_),
        "outcome_valid": completed,
        "downward_excursion_ticks": values,
        "upward_excursion_ticks": values,
    }
    arm = ArmFrame(
        PRIMARY_ARM_ID,
        sessions,
        timestamps,
        phases,
        states,
        active,
        np.full(sessions.size, "regular"),
        np.full(sessions.size, "ok"),
        np.zeros(sessions.size, dtype=np.bool_),
        np.asarray(
            [{name: code for code, name in enumerate(VOLATILITY_STATES)}[value] for value in states],
            dtype=np.int8,
        ),
    )
    inputs = ProductionInputs(
        root=None,
        unit=unit,
        arms={PRIMARY_ARM_ID: arm},
        run_manifest={},
        unit_manifest={},
        phase7_manifest={},
        input_manifest_sha256=(),
    )
    spec = ResultRowSpec(
        PRIMARY_ARM_ID,
        "downward_excursion_ticks",
        "fully_labeled_1m_grid",
        "horizon_specific",
        30,
        "q90",
        "vol_effect_given_phase",
        "prospective_cell",
        weighting,
        target,
        None,
    )
    reference = _contrast_partition(inputs, ((0, spec),), {})
    row = reference.entries[0].row
    return direct, row


def _assert_equivalent(direct, row):
    assert direct[0] == row["contrast_ticks"]
    assert direct[1] == row["contrast_valid"]
    assert direct[2] == row["status"]
    assert direct[3] == row["n_anchors"]
    assert direct[4] == row["n_sessions"]
    assert direct[6] == row["baseline_n_anchors"]
    assert direct[7] == row["baseline_n_sessions"]


@pytest.mark.parametrize(
    "weighting",
    ("equal_phase_contrast", "natural_prevalence_contrast"),
)
def test_phase10_fast_point_path_matches_phase8(weighting):
    direct, row = _fixture(weighting)
    _assert_equivalent(direct, row)


@pytest.mark.parametrize("support_case", ("missing", "thin", "incomplete"))
def test_phase10_non_ok_status_path_matches_phase8(support_case):
    direct, row = _fixture(support_case=support_case)
    assert row["status"] != "ok"
    _assert_equivalent(direct, row)


def test_phase10_evaluation_negative_changed_point_fails_the_same_assertion():
    direct, row = _fixture()
    mutant = dict(row)
    mutant["contrast_ticks"] += 1
    with pytest.raises(AssertionError):
        _assert_equivalent(direct, mutant)
