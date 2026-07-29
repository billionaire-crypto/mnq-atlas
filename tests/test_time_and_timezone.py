"""Spec §13 test 1 — `test_time_and_timezone`.

    "the §4.1 worked example asserted exactly; a bar-end interpretation must fail;
    RTH asserts 08:30/15:00 CT (finding F); coverage across both US DST
    transitions, early closes, and US/EU DST divergence weeks"

Also pins handoff §6.5 Ruling 1's two discriminating edges — the τ = 08:30 anchor
(from the 08:25-labeled bar) EXISTS in the open phase, and the 14:55-labeled bar
yields NO anchor — because the spec's own close-phase counts (1/7/10) reproduce
identically under either eligibility reading and cannot pin the rule
(`tests/test_window_boundaries.py` proves that non-discrimination explicitly).

And it discharges the Phase 1 re-audit obligation: RTH bounds and phases are
CONSUMED from `analysis_constants_v1.yaml`. The re-audit proved a divergent
`rth_start_ct` built byte-identical Phase 1 data because nothing read it;
`test_negative_a_divergent_yaml_changes_anchor_output` proves that is no longer
true, and `test_negative_an_inconsistent_yaml_refuses_to_construct` proves a YAML
whose phases no longer tile RTH fails closed instead of building anything.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mnq_lab import SpineError
from mnq_lab.constants import CONSTANTS_PATH, load_constants
from mnq_lab.core.causality import required_interval_starts
from mnq_lab.spine.timemodel import (
    BAR_MINUTES,
    BAR_NS,
    STATUS_ANCHOR_BAR_MISSING,
    STATUS_OK,
    TimeModel,
    assert_store_bar_seconds,
)

from tests.conftest import ct_ns, synthetic_session_bars

MINUTE = 60 * 1_000_000_000

# An ordinary full Tuesday, CDT, no roll, mid-2021.
ORDINARY = "2021-06-15"


@pytest.fixture(scope="module")
def time_model() -> TimeModel:
    return TimeModel.from_constants(load_constants())


@pytest.fixture(scope="module")
def ordinary_grid(time_model):
    session, ts, _, _ = synthetic_session_bars(ORDINARY)
    return time_model.anchor_grid(session, ts)


# --- the §4.1 worked example, asserted exactly --------------------------------------

def test_worked_example_exact(time_model):
    """anchor label 08:30 CT -> τ 08:35 CT; bucket keys on 08:35; Δ15 window
    [08:35, 08:50) requires bars 08:35, 08:40, 08:45."""
    label = np.asarray([ct_ns(f"{ORDINARY} 08:30")], dtype=np.int64)
    tau = time_model.observation_times_ns(label)
    assert tau[0] == ct_ns(f"{ORDINARY} 08:35")

    tau_minute = time_model.ct_minute_of_day(tau)
    assert tau_minute[0] == 8 * 60 + 35  # keyed on 08:35, NEVER the 08:30 label
    assert time_model.phase_of(tau_minute)[0] == "open"

    required = required_interval_starts(int(tau[0]), 15 * MINUTE, BAR_NS)
    assert [pd.Timestamp(t, unit="ns", tz="UTC").tz_convert("America/Chicago").strftime("%H:%M")
            for t in required] == ["08:35", "08:40", "08:45"]
    # Half-open [08:35, 08:50): the 08:50 bar is NOT part of the Δ15 window.
    assert ct_ns(f"{ORDINARY} 08:50") not in set(required.tolist())

    # The CT wall clock is 5 hours behind UTC on this (daylight-time) date.
    assert tau[0] == ct_ns(f"{ORDINARY} 08:35")
    assert pd.Timestamp(int(tau[0]), unit="ns", tz="UTC").hour == 13


def test_bar_end_interpretation_fails(time_model, ordinary_grid):
    """Under bar-end semantics (τ = the label itself) every assertion below flips.

    This is the §13-mandated negative: a bar-end implementation cannot pass.
    """
    label_ns = np.asarray([ct_ns(f"{ORDINARY} 08:30")], dtype=np.int64)
    tau_engine = time_model.ct_minute_of_day(time_model.observation_times_ns(label_ns))
    tau_bar_end = time_model.ct_minute_of_day(label_ns)  # the WRONG reading
    assert tau_engine[0] == 515 and tau_bar_end[0] == 510
    assert tau_engine[0] != tau_bar_end[0]

    # 08:25-labeled bar: eligible anchor (τ=08:30) under the engine,
    # ineligible (τ=08:25) under bar-end semantics.
    tau_0825 = time_model.ct_minute_of_day(
        time_model.observation_times_ns(
            np.asarray([ct_ns(f"{ORDINARY} 08:25")], dtype=np.int64)
        )
    )
    assert time_model.anchor_eligible(tau_0825)[0]
    assert not time_model.anchor_eligible(np.asarray([505]))[0]  # bar-end τ=08:25

    # 14:55-labeled bar: NO anchor under the engine (τ=15:00 is in no phase),
    # an eligible close-phase anchor under bar-end semantics (τ=14:55).
    tau_1455 = time_model.ct_minute_of_day(
        time_model.observation_times_ns(
            np.asarray([ct_ns(f"{ORDINARY} 14:55")], dtype=np.int64)
        )
    )
    assert not time_model.anchor_eligible(tau_1455)[0]
    assert time_model.phase_of(tau_1455)[0] == ""
    assert time_model.anchor_eligible(np.asarray([895]))[0]  # bar-end τ=14:55


# --- Ruling 1's two discriminating edges, on the emitted grid -----------------------

def test_tau_0830_anchor_exists_in_the_open_phase(ordinary_grid):
    """The 08:25-labeled bar's τ = 08:30 IS the session's first open-phase anchor."""
    first = ordinary_grid[ordinary_grid["tau_ct_minute"] == 510]
    assert len(first) == 1
    row = first.iloc[0]
    assert row["phase"] == "open"
    assert row["status"] == STATUS_OK  # the 08:25 bar exists in the fixture
    assert row["anchor_label_ns"] == ct_ns(f"{ORDINARY} 08:25")
    assert row["tau_ns"] == ct_ns(f"{ORDINARY} 08:30")


def test_the_1455_labeled_bar_yields_no_anchor(ordinary_grid):
    """τ = 15:00 is outside every phase: no gridpoint has the 14:55 bar as anchor."""
    assert 900 not in set(ordinary_grid["tau_ct_minute"].tolist())
    assert ct_ns(f"{ORDINARY} 14:55") not in set(
        ordinary_grid["anchor_label_ns"].tolist()
    )
    # The grid is exactly τ ∈ {08:30, 08:35, ..., 14:55}: 78 anchors per session.
    assert len(ordinary_grid) == 78
    assert ordinary_grid["tau_ct_minute"].tolist() == list(range(510, 900, 5))


# --- RTH bounds and phases are consumed from the YAML -------------------------------

def test_rth_bounds_come_from_the_yaml(time_model):
    constants = load_constants()
    start = constants.get("time", "rth_start_ct")
    end = constants.get("time", "rth_end_ct")
    assert start == "08:30" and end == "15:00"  # finding F's confirmed boundary
    assert time_model.rth_start_minute == 8 * 60 + 30
    assert time_model.rth_end_minute == 15 * 60
    assert list(time_model.phase_names) == list(constants.get("session_phases"))


def test_negative_a_divergent_yaml_changes_anchor_output(tmp_path):
    """The re-audit's exact scenario: rth_start_ct 09:00 must change behaviour.

    Phase 1 built byte-identical data under this altered YAML because nothing
    consumed the constant. Phase 2 is the consumer: the same alteration must now
    produce a different anchor grid. The phases are moved with the bound so the
    table still tiles RTH and the model constructs — the point is that a VALID
    but different YAML changes output, not that an invalid one is refused (the
    two tests after this one cover refusal).
    """
    altered = tmp_path / "divergent.yaml"
    altered.write_text(
        CONSTANTS_PATH.read_text(encoding="utf-8")
        .replace('rth_start_ct: "08:30"', 'rth_start_ct: "09:00"')
        .replace('open:      ["08:30", "09:00"]', 'open:      ["09:00", "09:30"]')
        .replace('morning:   ["09:00", "10:30"]', 'morning:   ["09:30", "10:30"]'),
        encoding="utf-8",
    )
    divergent = TimeModel.from_constants(load_constants(altered))
    frozen = TimeModel.from_constants(load_constants())

    session, ts, _, _ = synthetic_session_bars(ORDINARY)
    grid_divergent = divergent.anchor_grid(session, ts)
    grid_frozen = frozen.anchor_grid(session, ts)

    assert divergent.rth_start_minute == 540 != frozen.rth_start_minute
    assert len(grid_divergent) == 72 != len(grid_frozen)
    assert grid_divergent["tau_ct_minute"].iloc[0] == 540
    assert not divergent.anchor_eligible(np.asarray([515]))[0]
    assert frozen.anchor_eligible(np.asarray([515]))[0]


def test_negative_an_inconsistent_yaml_refuses_to_construct(tmp_path):
    """rth_start_ct moved WITHOUT moving the phases -> phases no longer tile RTH
    -> fail closed at construction, before any grid can be built."""
    altered = tmp_path / "inconsistent.yaml"
    altered.write_text(
        CONSTANTS_PATH.read_text(encoding="utf-8").replace(
            'rth_start_ct: "08:30"', 'rth_start_ct: "09:00"'
        ),
        encoding="utf-8",
    )
    with pytest.raises(SpineError, match="tile RTH"):
        TimeModel.from_constants(load_constants(altered))


def test_negative_a_divergent_session_tz_fails_closed(tmp_path):
    """Audit-M2 pattern: bucketing under a different zone than the spine built
    with is two data definitions in one atlas."""
    altered = tmp_path / "tz.yaml"
    altered.write_text(
        CONSTANTS_PATH.read_text(encoding="utf-8").replace(
            "session_tz: America/Chicago", "session_tz: America/New_York"
        ),
        encoding="utf-8",
    )
    with pytest.raises(SpineError, match="session_tz"):
        TimeModel.from_constants(load_constants(altered))


# --- DST coverage: both US transitions, and the US/EU divergence weeks --------------

def test_us_spring_forward_shifts_the_utc_anchor_instant(time_model, exploration_5m):
    """08:30 CT is 14:30 UTC in CST and 13:30 UTC in CDT. The 2021 spring
    transition (2021-03-14) sits between the Friday and Monday sessions."""
    sessions = np.asarray(exploration_5m["session_id"])
    ts = np.asarray(exploration_5m["ts_event_ns"])
    friday, monday = 20210312, 20210315
    mask = np.isin(sessions, [friday, monday])
    grid = time_model.anchor_grid(sessions[mask], ts[mask])

    tau_0830 = grid[grid["tau_ct_minute"] == 510].set_index("session_id")["tau_ns"]
    assert pd.Timestamp(int(tau_0830[friday]), unit="ns", tz="UTC").strftime("%H:%M") == "14:30"
    assert pd.Timestamp(int(tau_0830[monday]), unit="ns", tz="UTC").strftime("%H:%M") == "13:30"
    # Same CT wall minute, one hour apart in physical time modulo weekend days.
    assert (int(tau_0830[monday]) - int(tau_0830[friday])) == 3 * 24 * 3600 * 10**9 - 3600 * 10**9

    # The real store's bars land on these instants: presence matching agrees
    # across the transition. If the engine used a fixed UTC offset, the computed
    # 08:25 CT label would miss the stored bar on one side and these would fail.
    assert (grid[grid["tau_ct_minute"] == 510]["status"] == STATUS_OK).all()


def test_us_fall_back_shifts_the_utc_anchor_instant(time_model, exploration_5m):
    """The 2021 fall transition (2021-11-07): Friday CDT -> Monday CST."""
    sessions = np.asarray(exploration_5m["session_id"])
    ts = np.asarray(exploration_5m["ts_event_ns"])
    friday, monday = 20211105, 20211108
    mask = np.isin(sessions, [friday, monday])
    grid = time_model.anchor_grid(sessions[mask], ts[mask])

    tau_0830 = grid[grid["tau_ct_minute"] == 510].set_index("session_id")["tau_ns"]
    assert pd.Timestamp(int(tau_0830[friday]), unit="ns", tz="UTC").strftime("%H:%M") == "13:30"
    assert pd.Timestamp(int(tau_0830[monday]), unit="ns", tz="UTC").strftime("%H:%M") == "14:30"
    assert (grid[grid["tau_ct_minute"] == 510]["status"] == STATUS_OK).all()


def test_us_eu_divergence_week_tracks_chicago_not_a_fixed_offset(time_model, exploration_5m):
    """2021-03-15 .. 2021-03-26: the US is on daylight time, the EU is not.

    An engine keyed to Central Time puts the 08:30 CT anchor at 13:30 UTC
    throughout — the same as after the EU switch (2021-04-07) and one hour
    earlier than before the US switch (2021-03-03). An engine that borrowed a
    European clock, or froze the winter UTC offset, diverges exactly here.
    """
    sessions = np.asarray(exploration_5m["session_id"])
    ts = np.asarray(exploration_5m["ts_event_ns"])
    both_standard, divergence, both_daylight = 20210303, 20210317, 20210407
    mask = np.isin(sessions, [both_standard, divergence, both_daylight])
    grid = time_model.anchor_grid(sessions[mask], ts[mask])

    tau_0830 = grid[grid["tau_ct_minute"] == 510].set_index("session_id")["tau_ns"]
    utc_hhmm = {
        sid: pd.Timestamp(int(value), unit="ns", tz="UTC").strftime("%H:%M")
        for sid, value in tau_0830.items()
    }
    assert utc_hhmm[both_standard] == "14:30"
    assert utc_hhmm[divergence] == "13:30"  # CT already sprang forward; London had not
    assert utc_hhmm[both_daylight] == "13:30"
    # And the CT-wall-clock grid is identical on all three days.
    for sid in (both_standard, divergence, both_daylight):
        day = grid[grid["session_id"] == sid]
        assert day["tau_ct_minute"].tolist() == list(range(510, 900, 5))


# --- early closes: synthetic shape + one real session selected by data --------------

def test_synthetic_early_close_session(time_model):
    """A session whose RTH data ends at 12:00 CT (Ruling 2's synthetic fixture).

    The grid still emits all 78 declared gridpoints; the post-12:00 ones carry
    `anchor_bar_missing` rather than vanishing (spec §16.4.5); the flags read
    ended-early without any calendar claim.
    """
    session, ts, _, _ = synthetic_session_bars(
        ORDINARY, last_label_exclusive="12:00"
    )
    grid = time_model.anchor_grid(session, ts)
    assert len(grid) == 78  # every declared τ, present data or not

    # Last observed bar is 11:55, whose close is τ=12:00: still an anchor.
    assert grid[grid["tau_ct_minute"] == 720]["status"].iloc[0] == STATUS_OK
    late = grid[grid["tau_ct_minute"] > 720]
    assert (late["status"] == STATUS_ANCHOR_BAR_MISSING).all()
    assert len(late) == 35

    flags = time_model.session_flags(session, ts).iloc[0]
    assert flags["observed_rth_ended_early"] and flags["observed_short_session"]
    assert not flags["observed_mid_rth_gap"]
    assert flags["last_rth_bar_end_ct_minute"] == 720
    assert flags["n_rth_bars_missing_trailing"] == 36  # labels 12:00..14:55
    assert flags["n_rth_bars_missing_interior"] == 0
    assert flags["calendar_early_close"] == "unknown"  # unknown, not False


def test_synthetic_mid_session_gap_is_distinguished_from_early_end(time_model):
    """A session missing 10:00–10:25 but trading to 14:55 gaps WITHOUT ending
    early — the two flags are distinct measurements, and a session can be both."""
    gap_labels = ("10:00", "10:05", "10:10", "10:15", "10:20", "10:25")
    session, ts, _, _ = synthetic_session_bars(ORDINARY, missing=gap_labels)
    flags = time_model.session_flags(session, ts).iloc[0]
    assert flags["observed_mid_rth_gap"]
    assert not flags["observed_rth_ended_early"]
    assert flags["n_rth_bars_missing_interior"] == 6
    assert flags["last_rth_bar_end_ct_minute"] == 900

    both_session, both_ts, _, _ = synthetic_session_bars(
        ORDINARY, missing=gap_labels, last_label_exclusive="14:00"
    )
    both = time_model.session_flags(both_session, both_ts).iloc[0]
    assert both["observed_mid_rth_gap"] and both["observed_rth_ended_early"]


def test_a_real_short_session_selected_by_data_not_by_name(time_model, exploration_5m):
    """Ruling 2's real-data complement: the exploration session with the earliest
    observed RTH end, located by measurement. No holiday name, no calendar claim —
    a scheduled close and an outage are indistinguishable here by design."""
    flags = time_model.session_flags(
        np.asarray(exploration_5m["session_id"]),
        np.asarray(exploration_5m["ts_event_ns"]),
    )
    assert (flags["calendar_early_close"] == "unknown").all()

    short = flags[flags["observed_rth_ended_early"]]
    assert len(short) > 0, "no exploration session ends its RTH early — unexpected"
    # The -1 sentinel means "no RTH bars at all", not "ended earliest"; sessions
    # in that state are excluded from this flag entirely (audit adjudication).
    assert not (short["last_rth_bar_end_ct_minute"] == -1).any()
    earliest_end = int(short["last_rth_bar_end_ct_minute"].to_numpy().min())
    assert earliest_end < 900
    example = short[short["last_rth_bar_end_ct_minute"] == earliest_end].iloc[0]
    # The engine behaves on it exactly as on the synthetic fixture: full grid,
    # missing trailing anchors flagged, no silent absence.
    sessions = np.asarray(exploration_5m["session_id"])
    ts = np.asarray(exploration_5m["ts_event_ns"])
    mask = sessions == example["session_id"]
    grid = time_model.anchor_grid(sessions[mask], ts[mask])
    assert len(grid) == 78
    assert (
        grid[grid["tau_ct_minute"] >= earliest_end + BAR_MINUTES]["status"]
        == STATUS_ANCHOR_BAR_MISSING
    ).all()


# --- fail-closed input validation ---------------------------------------------------

def test_negative_non_ns_instants_are_rejected(time_model):
    """pandas 3.0 emits datetime64[us]; anything but int64 ns must refuse."""
    with pytest.raises(SpineError, match="int64"):
        time_model.ct_minute_of_day(np.asarray([1.5e18]))
    with pytest.raises(SpineError, match="int64"):
        time_model.ct_minute_of_day(
            np.asarray(["2021-06-15T08:35"], dtype="datetime64[us]")
        )


def test_negative_off_minute_instants_are_rejected(time_model):
    with pytest.raises(SpineError, match="minute grid"):
        time_model.ct_minute_of_day(
            np.asarray([ct_ns(f"{ORDINARY} 08:35") + 1], dtype=np.int64)
        )


def test_negative_off_grid_bar_labels_are_rejected(time_model):
    session = np.asarray([20210615], dtype=np.int32)
    off_grid = np.asarray([ct_ns(f"{ORDINARY} 08:31")], dtype=np.int64)
    with pytest.raises(SpineError, match="grid"):
        time_model.anchor_grid(session, off_grid)


# --- audit-round fixes: each guard proven able to fire -------------------------------

def test_the_intra_rth_offset_guard_actually_fires():
    """Audit finding M-4 (2026-07-28): the guard was untested — and, as found
    while fixing it, UNREACHABLE, because localizing the τ-grid raised an
    anonymous pandas ValueError before the guard's diagnostic could run.

    Africa/Khartoum really did jump +02:00 → +03:00 at 12:00 local on
    2000-01-15, squarely inside an 08:30–15:00 window: the wall-clock span is 390
    minutes but the physical span is 330. The model is constructed directly
    rather than from the YAML, because `from_constants` (correctly) refuses any
    zone but America/Chicago — the guard, not the loader, is under test here.
    """
    khartoum = TimeModel(
        session_tz="Africa/Khartoum",
        rth_start_minute=8 * 60 + 30,
        rth_end_minute=15 * 60,
        phase_names=("open",),
        phase_starts=(8 * 60 + 30,),
        phase_ends=(15 * 60,),
        horizons_minutes=(15, 30, 60),
    )
    with pytest.raises(SpineError, match="UTC offset changes inside RTH"):
        khartoum._assert_no_offset_change_inside_rth(np.asarray(["2000-01-15"]))

    # Specific, not blanket: the day before and the day after are clean, so the
    # guard is discriminating rather than failing on everything.
    khartoum._assert_no_offset_change_inside_rth(
        np.asarray(["2000-01-14", "2000-01-16"])
    )

    # And it fires through the public entry point, BEFORE the τ-grid is
    # localized — the ordering that makes the diagnostic reachable at all.
    session = np.asarray([20000115], dtype=np.int32)
    label = np.asarray([ct_ns("2000-01-14 08:25")], dtype=np.int64)
    with pytest.raises(SpineError, match="UTC offset changes inside RTH"):
        khartoum.anchor_grid(session, label)


def test_negative_a_backwards_phase_is_refused(tmp_path):
    """Audit finding M-2: `open=[08:30,10:30]`, `morning=[10:30,09:00]`,
    `midday=[09:00,12:30]` chains end-to-start at every step and previously
    constructed, silently emptying `morning` and overlapping `midday`."""
    import copy
    from pathlib import Path

    from mnq_lab.constants import Constants

    data = copy.deepcopy(load_constants().as_dict())
    data["session_phases"] = {
        "open": ["08:30", "10:30"],
        "morning": ["10:30", "09:00"],
        "midday": ["09:00", "12:30"],
        "afternoon": ["12:30", "14:00"],
        "close": ["14:00", "15:00"],
    }
    with pytest.raises(SpineError, match="empty or backwards"):
        TimeModel.from_constants(Constants(data, Path("<memory>")))


def test_negative_a_ten_minute_store_is_refused(time_model):
    """Audit finding M-5: 10-minute labels are divisible by five minutes, so the
    old check accepted them and produced a grid half full of `anchor_bar_missing`."""
    ten_minute = np.asarray(
        [ct_ns(f"{ORDINARY} {m // 60:02d}:{m % 60:02d}") for m in range(505, 900, 10)],
        dtype=np.int64,
    )
    session = np.full(len(ten_minute), 20210615, dtype=np.int32)
    with pytest.raises(SpineError, match="smallest gap"):
        time_model.anchor_grid(session, ten_minute)


def test_negative_a_store_declaring_other_bar_seconds_is_refused(exploration_5m):
    """The manifest's own `bar_seconds` is consumed, not assumed (audit M-5)."""
    assert_store_bar_seconds(exploration_5m.manifest)
    assert exploration_5m.manifest["bar_seconds"] == 300
    with pytest.raises(SpineError, match="bar_seconds=600"):
        assert_store_bar_seconds({**exploration_5m.manifest, "bar_seconds": 600})
    with pytest.raises(SpineError, match="declares no bar_seconds"):
        assert_store_bar_seconds({})


def test_negative_a_bar_labelled_with_the_wrong_session_is_refused(time_model):
    """Audit finding M-6: presence is matched by exact UTC instant across the
    whole input, so a bar carrying another session's id would be counted for
    whichever session claims the instant. The pairing is now enforced."""
    session, ts, _, _ = synthetic_session_bars(ORDINARY)
    corrupted = session.copy()
    corrupted[10] = 20210616  # a real 2021-06-15 bar mislabelled as the next day
    with pytest.raises(SpineError, match="CME trade date"):
        time_model.anchor_grid(corrupted, ts)
    # session_flags does the same exact-instant matching and must be guarded at
    # its own door — the round-1 fix initially covered only anchor_grid.
    with pytest.raises(SpineError, match="CME trade date"):
        time_model.session_flags(corrupted, ts)
    # The uncorrupted input still builds, so the guard is not blanket-failing.
    assert len(time_model.anchor_grid(session, ts)) == 78
    assert len(time_model.session_flags(session, ts)) == 1


def test_a_session_with_no_rth_bars_is_its_own_state(time_model):
    """Audit adjudication: a session that never started did not 'end early'."""
    session, ts, _, _ = synthetic_session_bars(
        ORDINARY, first_label="16:00", last_label_exclusive="16:30"
    )
    flags = time_model.session_flags(session, ts).iloc[0]
    assert flags["observed_no_rth_bars"]
    assert not flags["observed_rth_ended_early"]
    assert not flags["observed_short_session"]
    assert flags["last_rth_bar_end_ct_minute"] == -1
    assert flags["n_rth_bars_observed"] == 0

    # A genuinely truncated session remains ended-early and is NOT no-RTH.
    short_s, short_t, _, _ = synthetic_session_bars(
        ORDINARY, last_label_exclusive="12:00"
    )
    short = time_model.session_flags(short_s, short_t).iloc[0]
    assert short["observed_rth_ended_early"] and not short["observed_no_rth_bars"]


def test_grid_timestamps_are_int64_ns(ordinary_grid):
    assert ordinary_grid["tau_ns"].dtype == np.int64
    assert ordinary_grid["anchor_label_ns"].dtype == np.int64
    assert ordinary_grid["session_id"].dtype == np.int32
    assert ordinary_grid["tau_ct_minute"].dtype == np.int32
