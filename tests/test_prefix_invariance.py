"""Building through T+k must not change anything the build through T produced.

Spec §13 test 4: "build through T, rebuild through T+k; assert unchanged before T:
contract assignments, roll boundaries, 5-min bars, session IDs, seasonal profiles,
tercile thresholds, conditioner assignments, prevalence results, consumed-vintage
artifacts."

Phase 1 owns the first four. The remainder belong to later phases and are listed in
`test_deferred_prefix_invariance_targets` so they cannot be quietly forgotten.

Prefix invariance is **necessary but not sufficient** for causality — see
`tests/test_roll_causality.py`, which demonstrates a selector that is prefix invariant
and still leaks the future (spec §5.1 gate 4).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mnq_lab.spine.build import _collect_active_rows_sharded, _shard_to_frame
from mnq_lab.spine.calendar import trade_date_ids
from mnq_lab.spine.resample import resample_to_five_minutes
from mnq_lab.spine.rolls import build_causal_active_contract_map
from mnq_lab.spine.source import scan_source
from tests.conftest import SourceBuilder, session_grid

NEAR = "MNQM1"
FAR = "MNQU1"
TIMES = ["17:00", "17:05", "23:00", "03:00", "08:30", "08:35", "12:00", "15:55"]

# Business days spanning a volume crossover, so at least one roll lies inside the prefix.
SESSIONS = [
    "2021-06-07", "2021-06-08", "2021-06-09", "2021-06-10", "2021-06-11",
    "2021-06-14", "2021-06-15", "2021-06-16", "2021-06-17", "2021-06-18",
]
PREFIX_LENGTH = 6
PREFIX = SESSIONS[:PREFIX_LENGTH]
BOUNDARY = PREFIX[-1]


def _write(path, trade_dates):
    """The near contract dominates until 2021-06-10, then the far one takes over."""
    builder = SourceBuilder()
    for trade_date in trade_dates:
        rolled = trade_date >= "2021-06-10"
        stamps = session_grid(trade_date, TIMES)
        builder.add_minutes(
            stamps, NEAR, volume=5 if rolled else 500, open_=12_000.0
        )
        builder.add_minutes(
            stamps, FAR, volume=900 if rolled else 3, open_=12_100.0
        )
    return builder.write(path)


def _pipeline(path, tmp_path, tag):
    scan = scan_source(path, chunksize=10_000, verbose=False)
    roll_map = build_causal_active_contract_map(
        scan.daily_volume, scan.first_year_by_symbol
    )
    symbols = sorted(scan.classification.retained)
    codes = {symbol: index for index, symbol in enumerate(symbols)}
    shards = _collect_active_rows_sharded(
        path, roll_map.active, codes, tmp_path / tag, 0.25, 10_000, verbose=False
    )
    frame = pd.concat(
        [_shard_to_frame(shard, symbols, 0.25) for shard in shards], ignore_index=True
    ).sort_values("timestamp", kind="stable").reset_index(drop=True)
    bars = resample_to_five_minutes(frame).bars
    bars["session_id"] = trade_date_ids(bars["timestamp"])
    return roll_map, bars


@pytest.fixture(scope="module")
def builds(tmp_path_factory):
    root = tmp_path_factory.mktemp("prefix")
    short = _write(root / "short.csv", PREFIX)
    long = _write(root / "long.csv", SESSIONS)
    return _pipeline(short, root, "short"), _pipeline(long, root, "long")


def test_contract_assignments_are_unchanged(builds):
    (short_map, _), (long_map, _) = builds
    for trade_date in PREFIX:
        assert short_map.active[trade_date] == long_map.active[trade_date], trade_date


def test_roll_boundaries_are_unchanged(builds):
    (short_map, _), (long_map, _) = builds
    short_rolls = [r for r in short_map.rolls if r.get("trigger_trade_date") in PREFIX]
    long_rolls = [r for r in long_map.rolls if r.get("trigger_trade_date") in PREFIX]
    assert short_rolls == long_rolls
    assert short_rolls, "the prefix contains no roll, so this assertion is vacuous"


def test_five_minute_bars_are_unchanged(builds):
    (_, short_bars), (_, long_bars) = builds
    cutoff = int(BOUNDARY.replace("-", ""))
    a = short_bars[short_bars["session_id"] <= cutoff].reset_index(drop=True)
    b = long_bars[long_bars["session_id"] <= cutoff].reset_index(drop=True)

    assert len(a) == len(b) > 0
    for column in (
        "timestamp", "open", "high", "low", "close", "volume", "symbol",
        "expected_1m_components", "observed_1m_components", "component_coverage_rate",
        "first_component_time", "last_component_time",
    ):
        np.testing.assert_array_equal(
            a[column].to_numpy(), b[column].to_numpy(), err_msg=column
        )


def test_session_ids_are_unchanged(builds):
    (_, short_bars), (_, long_bars) = builds
    cutoff = int(BOUNDARY.replace("-", ""))
    a = short_bars.loc[short_bars["session_id"] <= cutoff, "session_id"].to_numpy()
    b = long_bars.loc[long_bars["session_id"] <= cutoff, "session_id"].to_numpy()
    np.testing.assert_array_equal(a, b)


def test_negative_case_the_extension_is_not_empty(builds):
    """If the long build added nothing, every assertion above is vacuous."""
    (_, short_bars), (_, long_bars) = builds
    assert len(long_bars) > len(short_bars)
    (short_map, _), (long_map, _) = builds
    assert set(long_map.active) > set(short_map.active)


def test_negative_case_a_lookahead_normaliser_breaks_invariance(builds):
    """Demonstrate that this fixture *can* detect a prefix violation.

    A statistic normalised by the corpus total — a plausible-looking mistake — changes
    retroactively when new sessions arrive. The fixture must catch that.
    """
    (_, short_bars), (_, long_bars) = builds
    cutoff = int(BOUNDARY.replace("-", ""))

    def leaky(bars):
        window = bars[bars["session_id"] <= cutoff]
        return (window["volume"] / bars["volume"].sum()).to_numpy()

    assert not np.array_equal(leaky(short_bars), leaky(long_bars))


DEFERRED_TARGETS = [
    "seasonal_profiles",
    "tercile_thresholds",
    "conditioner_assignments",
    "prevalence_results",
    "consumed_vintage_artifacts",
]


@pytest.mark.parametrize("target", DEFERRED_TARGETS)
def test_deferred_prefix_invariance_targets(target):
    """Registered as unimplemented so §13 test 4 is not silently under-covered.

    These are produced in phases 7, 9 and 11. This is a visible placeholder, not a
    passing check of the property.
    """
    pytest.xfail(f"{target} does not exist until a later phase (spec §15)")
