"""One-minute component coverage (spec §5, §6; §13 test 5).

    "a 5-min bar from fewer than five 1-min rows is rejected under
    `fully_labeled_1m_grid`, retained-with-flag under `observed_bar_path`"

Spec §14 struck the names `complete_1m_path` / `observed_trade_path`. The current names
are `fully_labeled_1m_grid` and `observed_bar_path`, and they claim only what the data
support: all five labels present proves every expected interval has an OHLCV row, not
that the feed captured every trade.

Spec §16.5 target 3: "verify a 5-min bar built from 3 one-minute rows is actually
rejected" — not that it is flagged, that it is *rejected*.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mnq_lab import SpineError
from mnq_lab.spine.resample import (
    COMPONENTS_PER_5M_BAR,
    resample_to_five_minutes,
)
from tests.conftest import ct

SYMBOL = "MNQM1"
TRADE_DATE = "2021-06-10"


def _rows(minute_offsets_by_bar: dict[str, list[int]]) -> pd.DataFrame:
    """Build 1-min rows; `minute_offsets_by_bar` maps a bar's CT start to its minutes."""
    records = []
    for bar_start, offsets in minute_offsets_by_bar.items():
        base = ct(f"{TRADE_DATE} {bar_start}")
        for offset in offsets:
            stamp = base + pd.Timedelta(minutes=offset)
            records.append(
                {
                    "timestamp": stamp,
                    "trade_date": TRADE_DATE,
                    "symbol": SYMBOL,
                    "open": 12_000.0 + offset,
                    "high": 12_001.0 + offset,
                    "low": 11_999.0 + offset,
                    "close": 12_000.25 + offset,
                    "volume": 10 + offset,
                }
            )
    return pd.DataFrame(records).sort_values("timestamp").reset_index(drop=True)


def _bars(minute_offsets_by_bar):
    return resample_to_five_minutes(_rows(minute_offsets_by_bar)).bars


def test_complete_bar_has_full_coverage():
    bars = _bars({"09:00": [0, 1, 2, 3, 4]})
    assert len(bars) == 1
    row = bars.iloc[0]
    assert row["expected_1m_components"] == COMPONENTS_PER_5M_BAR == 5
    assert row["observed_1m_components"] == 5
    assert row["component_coverage_rate"] == 1.0


def test_bar_from_three_minutes_is_incomplete():
    bars = _bars({"09:00": [0, 2, 4]})
    row = bars.iloc[0]
    assert row["expected_1m_components"] == 5
    assert row["observed_1m_components"] == 3
    assert row["component_coverage_rate"] == pytest.approx(0.6)


def test_incomplete_bar_is_rejected_under_fully_labeled_1m_grid():
    """The estimand that S01A uses as primary must exclude this bar entirely."""
    bars = _bars({"09:00": [0, 2, 4], "09:05": [0, 1, 2, 3, 4]})
    fully_labeled = bars[
        bars["observed_1m_components"] == bars["expected_1m_components"]
    ]
    assert len(bars) == 2
    assert len(fully_labeled) == 1
    assert fully_labeled.iloc[0]["timestamp"] == ct(f"{TRADE_DATE} 09:05")


def test_incomplete_bar_is_retained_with_a_flag_under_observed_bar_path():
    bars = _bars({"09:00": [0, 2, 4], "09:05": [0, 1, 2, 3, 4]})
    assert len(bars) == 2  # observed_bar_path keeps every bar present in the source
    assert bars["component_coverage_rate"].tolist() == [0.6, 1.0]
    assert (bars["component_coverage_rate"] < 1.0).any(), "the flag must be readable"


def test_negative_case_coverage_would_not_distinguish_if_it_were_bar_existence():
    """§6: "5-min bar existence is not sufficient."

    Both bars below exist. Only the coverage column separates them. If this assertion
    ever fails, coverage has collapsed to a constant and the estimand is meaningless.
    """
    bars = _bars({"09:00": [0], "09:05": [0, 1, 2, 3, 4]})
    assert len(bars) == 2
    assert bars["observed_1m_components"].nunique() == 2


def test_a_single_minute_still_produces_a_valid_bar():
    bars = _bars({"09:00": [3]})
    row = bars.iloc[0]
    assert row["observed_1m_components"] == 1
    assert row["component_coverage_rate"] == pytest.approx(0.2)
    # OHLC all come from the one row present.
    assert row["open"] == row["close"] - 0.25 == 12_003.0


def test_first_and_last_component_times_bracket_the_observed_minutes():
    bars = _bars({"09:00": [1, 3]})
    row = bars.iloc[0]
    assert row["first_component_time"] == ct(f"{TRADE_DATE} 09:01")
    assert row["last_component_time"] == ct(f"{TRADE_DATE} 09:03")
    assert row["timestamp"] == ct(f"{TRADE_DATE} 09:00")
    # The bar label is the interval OPEN (finding E), so first_component_time may be
    # strictly after it. A bar-end reading would make this impossible.
    assert row["first_component_time"] >= row["timestamp"]
    assert row["last_component_time"] < row["timestamp"] + pd.Timedelta(minutes=5)


def test_expected_components_is_five_across_the_whole_session():
    """Computed, not assumed. Session bounds are 5-minute aligned, so it should be 5."""
    offsets = {f"{hour:02d}:{minute:02d}": [0, 1, 2, 3, 4]
               for hour in range(8, 16) for minute in (0, 30)}
    bars = _bars(offsets)
    assert (bars["expected_1m_components"] == 5).all()
    assert bars["expected_1m_components"].nunique() == 1


def test_negative_case_a_mislabelled_session_fails_closed():
    """A bar whose label belongs to a different trade date halts the build.

    Coverage is only meaningful if a bar's expected components come from its own
    session. If the label is wrong, `expected` collapses to zero and the rate would be
    undefined — that is a halt, not a coverage anomaly (spec §16.4.3).
    """
    contaminated = _rows({"09:00": [0, 1]}).assign(trade_date="2021-06-11")
    with pytest.raises(SpineError, match="zero in-session minute labels"):
        resample_to_five_minutes(contaminated)


def test_negative_case_duplicate_minute_rows_fail_closed():
    """More observed components than the bar can span means duplicated source rows."""
    frame = _rows({"09:00": [0, 1, 2, 3, 4]})
    duplicated = pd.concat([frame, frame.iloc[[2]]], ignore_index=True).sort_values(
        "timestamp"
    ).reset_index(drop=True)
    with pytest.raises(SpineError, match="another session|aggregated 6"):
        resample_to_five_minutes(duplicated)


def test_negative_case_the_coverage_guards_are_reachable():
    """Both guards above must be distinguishable from the happy path."""
    clean = _rows({"09:00": [0, 1, 2, 3, 4]})
    bars = resample_to_five_minutes(clean).bars
    assert bars.iloc[0]["observed_1m_components"] == 5


def test_real_store_coverage_columns_are_present_and_consistent(exploration_5m):
    expected = np.asarray(exploration_5m["expected_1m_components"])
    observed = np.asarray(exploration_5m["observed_1m_components"])
    rate = np.asarray(exploration_5m["component_coverage_rate"])

    assert (expected == 5).all(), "session bounds should make expected uniformly 5"
    assert (observed >= 1).all(), "a bar cannot exist with zero components"
    assert (observed <= expected).all()
    np.testing.assert_allclose(rate, observed / expected)
    assert (observed < expected).any(), (
        "no incomplete bar anywhere in the exploration tier would mean the coverage "
        "column is inert and §6's selection effect could not be measured"
    )
