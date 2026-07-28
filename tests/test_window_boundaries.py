"""`test_window_boundaries` (spec §13 test-18 list) — the clock-window engine.

Pins the §4.2 registered prediction — close-phase eligible anchors per full
session are Δ60→1, Δ30→7, Δ15→10 — by *computing* them from the engine on a full
ordinary session, per §16.7 ("when the spec asserts something checkable, check
it"). It also proves those counts CANNOT discriminate the τ-eligibility ruling
from the rejected label-eligibility reading (they are identical under both), which
is why handoff §6.5 requires the two explicit edge assertions in
`tests/test_time_and_timezone.py`; the grids differ at exactly one gridpoint per
session — τ=08:30 (ruling) versus τ=15:00 (rejected reading) — and that
difference is asserted here.
"""

from __future__ import annotations

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.constants import load_constants
from mnq_lab.core.causality import required_interval_starts
from mnq_lab.spine.timemodel import (
    BAR_MINUTES,
    BAR_NS,
    STATUS_ANCHOR_BAR_MISSING,
    STATUS_OK,
    TimeModel,
)

from tests.conftest import ct_ns, synthetic_session_bars

MINUTE_NS = 60 * 1_000_000_000
ORDINARY = "2021-06-15"


@pytest.fixture(scope="module")
def time_model() -> TimeModel:
    return TimeModel.from_constants(load_constants())


@pytest.fixture(scope="module")
def full_session_grid(time_model):
    session, ts, _, _ = synthetic_session_bars(ORDINARY)
    return time_model.anchor_grid(session, ts)


# --- window construction ------------------------------------------------------------

def test_required_labels_are_the_half_open_grid():
    tau = ct_ns(f"{ORDINARY} 08:35")
    required = required_interval_starts(tau, 15 * MINUTE_NS, BAR_NS)
    assert required.tolist() == [
        ct_ns(f"{ORDINARY} 08:35"),
        ct_ns(f"{ORDINARY} 08:40"),
        ct_ns(f"{ORDINARY} 08:45"),
    ]
    # Δ/5 labels for every declared horizon; the window is [τ, τ+Δ), half-open.
    for horizon in (15, 30, 60):
        grid = required_interval_starts(tau, horizon * MINUTE_NS, BAR_NS)
        assert len(grid) == horizon // BAR_MINUTES
        assert grid[0] == tau
        assert grid[-1] == tau + (horizon - BAR_MINUTES) * MINUTE_NS


def test_negative_malformed_windows_fail_closed():
    tau = ct_ns(f"{ORDINARY} 08:35")
    with pytest.raises(SpineError, match="positive"):
        required_interval_starts(tau, 0, BAR_NS)
    with pytest.raises(SpineError, match="positive"):
        required_interval_starts(tau, -15 * MINUTE_NS, BAR_NS)
    with pytest.raises(SpineError, match="whole number"):
        required_interval_starts(tau, 7 * MINUTE_NS, BAR_NS)
    with pytest.raises(SpineError, match="positive"):
        required_interval_starts(tau, 15 * MINUTE_NS, 0)


def test_negative_undeclared_horizons_are_refused(time_model):
    """45 is not in the YAML's horizons_minutes; the engine must not accept it."""
    with pytest.raises(SpineError, match="declared horizon"):
        time_model.outcome_window_fits_rth(np.asarray([515]), 45)


# --- the registered close-phase counts (spec §4.2), computed not transcribed --------

def test_close_phase_eligible_anchor_counts_are_1_7_10(time_model, full_session_grid):
    close = full_session_grid[full_session_grid["phase"] == "close"]
    assert len(close) == 12  # τ ∈ {14:00, ..., 14:55}
    assert (close["status"] == STATUS_OK).all()

    counts = {}
    for horizon in (60, 30, 15):
        fits = time_model.outcome_window_fits_rth(
            close["tau_ct_minute"].to_numpy(dtype=np.int32), horizon
        )
        counts[horizon] = int(fits.sum())
    assert counts == {60: 1, 30: 7, 15: 10}  # the §4.2 registered prediction


def test_close_phase_counts_reproduce_on_a_real_session(time_model, exploration_5m):
    """The same prediction checked end-to-end on a real full ordinary session."""
    sessions = np.asarray(exploration_5m["session_id"])
    ts = np.asarray(exploration_5m["ts_event_ns"])
    target = 20210615
    mask = sessions == target
    grid = time_model.anchor_grid(sessions[mask], ts[mask])
    assert (grid["status"] == STATUS_OK).all(), "20210615 is not a full session"

    close = grid[grid["phase"] == "close"]
    for horizon, expected in ((60, 1), (30, 7), (15, 10)):
        fits = time_model.outcome_window_fits_rth(
            close["tau_ct_minute"].to_numpy(dtype=np.int32), horizon
        )
        assert int(fits.sum()) == expected


def test_whole_session_eligible_counts(time_model, full_session_grid):
    """78 anchors per full session (Ruling 1); Δ15→76, Δ30→73, Δ60→67 fit RTH."""
    assert len(full_session_grid) == 78
    assert (full_session_grid["status"] == STATUS_OK).all()
    tau = full_session_grid["tau_ct_minute"].to_numpy(dtype=np.int32)
    for horizon, expected in ((15, 76), (30, 73), (60, 67)):
        assert int(time_model.outcome_window_fits_rth(tau, horizon).sum()) == expected


def test_the_registered_counts_cannot_discriminate_the_eligibility_ruling(time_model):
    """Handoff §6.5: under the REJECTED reading (anchor bar's label must lie in
    RTH → τ grid 08:35..15:00) the close-phase counts are IDENTICAL — so a suite
    asserting only 1/7/10 pins nothing about the open edge. This test proves the
    non-discrimination and locates the single gridpoint where the readings differ.
    """
    ruling_grid = np.arange(510, 900, 5)          # τ: 08:30 .. 14:55
    rejected_grid = np.arange(515, 905, 5)        # τ: 08:35 .. 15:00 (label in RTH)

    for grid in (ruling_grid, rejected_grid):
        close = grid[(grid >= 840) & (grid < 900)]  # close phase on τ
        assert [int((close + h <= 900).sum()) for h in (60, 30, 15)] == [1, 7, 10]

    only_ruling = set(ruling_grid) - set(rejected_grid)
    only_rejected = set(rejected_grid) - set(ruling_grid)
    assert only_ruling == {510} and only_rejected == {900}
    # The engine implements the ruling side: 78 gridpoints starting at τ=08:30.
    assert time_model.tau_grid_ct_minutes().tolist() == ruling_grid.tolist()


# --- declared-grid emission (spec §16.4.5) ------------------------------------------

def test_a_missing_anchor_bar_is_a_status_never_a_silent_absence(time_model):
    session, ts, _, _ = synthetic_session_bars(ORDINARY, missing=("08:25", "10:55"))
    grid = time_model.anchor_grid(session, ts)
    assert len(grid) == 78  # nothing dropped

    missing_0830 = grid[grid["tau_ct_minute"] == 510].iloc[0]
    assert missing_0830["status"] == STATUS_ANCHOR_BAR_MISSING
    assert missing_0830["phase"] == "open"  # the gridpoint keeps its phase
    missing_1100 = grid[grid["tau_ct_minute"] == 660].iloc[0]
    assert missing_1100["status"] == STATUS_ANCHOR_BAR_MISSING
    assert (grid["status"] == STATUS_OK).sum() == 76


def test_negative_the_grid_detects_a_wrong_session_count(time_model):
    """Two sessions in, 156 gridpoints out — the grid scales with sessions and a
    dropped session would be visible as a wrong row count."""
    s1, t1, _, _ = synthetic_session_bars("2021-06-15")
    s2, t2, _, _ = synthetic_session_bars("2021-06-16")
    grid = time_model.anchor_grid(
        np.concatenate([s1, s2]), np.concatenate([t1, t2])
    )
    assert len(grid) == 156
    assert set(grid["session_id"].tolist()) == {20210615, 20210616}
