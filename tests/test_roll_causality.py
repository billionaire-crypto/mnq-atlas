"""Gate 4: roll causality, tested directly (spec §5.1 gate 4, §13 test 3).

    "Rule: session *d*'s contract is fixed entirely from volumes through completed
    session *d-1*. Prefix invariance is *not sufficient* ... The fixture must diverge
    from 17:00 CT at the start of session *d* (an RTH-open divergence would miss a
    procedure using session *d*'s own overnight volume from 17:00-08:29). Two versions
    identical through the end of session *d-1*, then wholly different volume throughout
    session *d*; assignment must be identical and frozen for the entire Globex session,
    never recalculated at RTH."

Spec §14 struck the earlier fixture that diverged at the RTH open. This one diverges at
17:00 CT.

Three things must hold for this test to mean anything, and all three are asserted:

  1. the assignment for session d is identical across the two versions;
  2. the divergence is *real* — it reaches the map at session d+1. Without this the test
     would pass vacuously on two identical inputs;
  3. a deliberately non-causal selector, given the same fixture, produces *different*
     assignments at session d. This is the negative case: it proves the fixture can
     detect the defect it exists to detect.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd
import pytest

from mnq_lab.spine.build import _collect_active_rows_sharded
from mnq_lab.spine.rolls import build_causal_active_contract_map
from mnq_lab.spine.source import scan_source
from tests.conftest import CT, SourceBuilder, ct, session_grid

NEAR = "MNQM1"  # expires 2021-06-18
FAR = "MNQU1"  # expires 2021-09-17

SESSION_TIMES = ["17:00", "17:05", "23:00", "03:00", "08:30", "12:00", "15:55"]

BEFORE = ["2021-06-08", "2021-06-09"]
SESSION_D = "2021-06-10"
AFTER = "2021-06-11"

# The instant session d begins: 17:00 CT on the preceding calendar day.
SESSION_D_START_UTC = ct("2021-06-09 17:00")


def _build_source(path, *, session_d_flips: bool) -> None:
    """Two versions identical through the end of session d-1.

    When `session_d_flips`, every bar from 17:00 CT at the start of session d carries
    wholly different volume: the far contract dominates instead of the near one.
    """
    builder = SourceBuilder()
    for trade_date in [*BEFORE, SESSION_D, AFTER]:
        flipped = session_d_flips and trade_date == SESSION_D
        near_volume = 2 if flipped else 200
        far_volume = 20_000 if flipped else 2
        stamps = session_grid(trade_date, SESSION_TIMES)
        builder.add_minutes(stamps, NEAR, volume=near_volume, open_=12_000.0)
        builder.add_minutes(stamps, FAR, volume=far_volume, open_=12_100.0)
    builder.write(path)


def _active_map(path) -> dict[str, str]:
    scan = scan_source(path, chunksize=10_000, verbose=False)
    return build_causal_active_contract_map(
        scan.daily_volume, scan.first_year_by_symbol
    ).active


def _non_causal_map(path) -> dict[str, str]:
    """The defect Gate 4 exists to catch: choose session d from session d's own volume.

    This selector is still *prefix invariant* — rebuilding over a longer span never
    changes an earlier assignment, because each session depends only on itself. That is
    precisely why prefix invariance is not sufficient (spec §5.1 gate 4).
    """
    scan = scan_source(path, chunksize=10_000, verbose=False)
    by_day: dict[str, dict[str, int]] = defaultdict(dict)
    for (trade_date, symbol), volume in scan.daily_volume.items():
        by_day[trade_date][symbol] = volume
    return {
        trade_date: max(volumes, key=lambda symbol: volumes[symbol])
        for trade_date, volumes in by_day.items()
    }


@pytest.fixture
def versions(tmp_path):
    baseline = tmp_path / "baseline.csv"
    flipped = tmp_path / "flipped.csv"
    _build_source(baseline, session_d_flips=False)
    _build_source(flipped, session_d_flips=True)
    return baseline, flipped


def test_versions_are_identical_through_end_of_session_d_minus_1(versions):
    """The fixture's own premise. If this fails, nothing below means anything."""
    baseline, flipped = versions
    original = baseline.read_text(encoding="utf-8").splitlines()
    changed = flipped.read_text(encoding="utf-8").splitlines()

    def stamp_of(line: str) -> pd.Timestamp:
        return pd.Timestamp(line.split(",")[0])

    def prefix(lines: list[str]) -> list[str]:
        return [line for line in lines[1:] if stamp_of(line) < SESSION_D_START_UTC]

    assert prefix(original) == prefix(changed)
    assert original != changed, "the two versions must differ somewhere"

    # ...and the very first differing row is at 17:00 CT, not at the RTH open.
    unchanged = set(original[1:])
    first_difference = next(line for line in changed[1:] if line not in unchanged)
    assert stamp_of(first_difference) == SESSION_D_START_UTC, (
        "divergence must begin exactly at 17:00 CT, the start of session d; spec §14 "
        "struck the RTH-open fixture because it misses a selector using session d's "
        "own 17:00-08:29 overnight volume"
    )


def test_session_d_assignment_is_unchanged_by_session_d_volume(versions):
    """Gate 4, the load-bearing assertion."""
    baseline, flipped = versions
    causal_baseline = _active_map(baseline)
    causal_flipped = _active_map(flipped)

    assert causal_baseline[SESSION_D] == causal_flipped[SESSION_D] == NEAR

    for trade_date in BEFORE:
        assert causal_baseline[trade_date] == causal_flipped[trade_date]


def test_the_divergence_actually_reaches_the_map(versions):
    """Guards against a vacuous pass: session d+1 *must* differ."""
    baseline, flipped = versions
    causal_baseline = _active_map(baseline)
    causal_flipped = _active_map(flipped)

    assert causal_baseline[AFTER] == NEAR
    assert causal_flipped[AFTER] == FAR, (
        "session d's volume must change the *next* session's contract; if it changes "
        "nothing, the fixture is inert and the test above proves nothing"
    )


def test_negative_case_non_causal_selector_is_caught(versions):
    """The negative case. A same-day selector must fail the assertion above."""
    baseline, flipped = versions
    leaky_baseline = _non_causal_map(baseline)
    leaky_flipped = _non_causal_map(flipped)

    assert leaky_baseline[SESSION_D] == NEAR
    assert leaky_flipped[SESSION_D] == FAR
    assert leaky_baseline[SESSION_D] != leaky_flipped[SESSION_D], (
        "a non-causal selector must be detected by this fixture, otherwise the fixture "
        "cannot fail and is worse than no test"
    )


def test_negative_case_non_causal_selector_is_still_prefix_invariant(tmp_path):
    """Prefix invariance does not imply causality — the spec's exact point.

    Build through session d, then rebuild through session d+1. The leaky selector's
    earlier assignments are unchanged, so it passes a prefix-invariance check while
    failing the causality check above.
    """
    short = tmp_path / "short.csv"
    long = tmp_path / "long.csv"

    def build(path, trade_dates):
        builder = SourceBuilder()
        for trade_date in trade_dates:
            flipped = trade_date == SESSION_D
            stamps = session_grid(trade_date, SESSION_TIMES)
            builder.add_minutes(
                stamps, NEAR, volume=2 if flipped else 200, open_=12_000.0
            )
            builder.add_minutes(
                stamps, FAR, volume=20_000 if flipped else 2, open_=12_100.0
            )
        builder.write(path)

    build(short, [*BEFORE, SESSION_D])
    build(long, [*BEFORE, SESSION_D, AFTER])

    leaky_short = _non_causal_map(short)
    leaky_long = _non_causal_map(long)
    for trade_date in [*BEFORE, SESSION_D]:
        assert leaky_short[trade_date] == leaky_long[trade_date]


def test_assignment_is_frozen_for_the_whole_globex_session(versions, tmp_path):
    """Never recalculated at RTH: one contract from 17:00 CT through 15:55 CT."""
    _, flipped = versions
    active = _active_map(flipped)
    symbols = sorted({NEAR, FAR})
    codes = {symbol: index for index, symbol in enumerate(symbols)}

    shards = _collect_active_rows_sharded(
        flipped,
        active,
        codes,
        tmp_path / "shards",
        tick_size=0.25,
        chunksize=10_000,
        verbose=False,
    )
    assert shards

    session_ids, symbol_codes, stamps = [], [], []
    for shard in shards:
        with np.load(shard) as payload:
            session_ids.append(payload["session_id"])
            symbol_codes.append(payload["symbol_code"])
            stamps.append(payload["ts_event_ns"])
    session_ids = np.concatenate(session_ids)
    symbol_codes = np.concatenate(symbol_codes)
    stamps = np.concatenate(stamps)

    target = int(SESSION_D.replace("-", ""))
    mask = session_ids == target
    assert mask.any(), "session d produced no bars"
    assert len(np.unique(symbol_codes[mask])) == 1, (
        "the active contract changed inside session d's Globex session"
    )
    assert symbols[int(symbol_codes[mask][0])] == NEAR

    # The session's bars must actually span the 17:00 CT open, the overnight period and
    # the RTH open, otherwise "frozen across the session" is untested where it matters.
    session_ct = (
        pd.DatetimeIndex(np.asarray(stamps[mask], dtype="datetime64[ns]"))
        .tz_localize("UTC")
        .tz_convert(CT)
    )
    ct_hours = set(session_ct.hour)
    assert 17 in ct_hours, "fixture lacks the 17:00 CT session open"
    assert 3 in ct_hours, "fixture lacks overnight bars"
    assert 8 in ct_hours, "fixture lacks bars at the RTH open"
    assert 15 in ct_hours, "fixture lacks bars near the RTH close"
