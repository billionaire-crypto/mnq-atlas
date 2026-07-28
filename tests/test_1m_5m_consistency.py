"""Every 5-minute bar must be the exact aggregation of its 1-minute components.

Spec §13 test 18 (`test_1m_5m_consistency`). This is the check that catches a
five-minute misalignment — the failure spec §16.5 calls the highest-risk item, because
"an off-by-one here shifts every result by five minutes and no statistical test will
catch it."

Comparison is in integer tick space, so it is exact. No tolerance is used or permitted.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

BAR_NS = 300_000_000_000


def _aggregate_from_minutes(store_1m, symbol_codes_of_interest=None):
    """Group 1-minute rows into their containing 5-minute bucket."""
    stamps = np.asarray(store_1m["ts_event_ns"])
    bucket = (stamps // BAR_NS) * BAR_NS
    frame = pd.DataFrame(
        {
            "bucket": bucket,
            "open_ticks": np.asarray(store_1m["open_ticks"]),
            "high_ticks": np.asarray(store_1m["high_ticks"]),
            "low_ticks": np.asarray(store_1m["low_ticks"]),
            "close_ticks": np.asarray(store_1m["close_ticks"]),
            "volume": np.asarray(store_1m["volume"]),
            "symbol_code": np.asarray(store_1m["symbol_code"]),
            "session_id": np.asarray(store_1m["session_id"]),
            "stamp": stamps,
        }
    ).sort_values("stamp", kind="stable")

    grouped = frame.groupby(["session_id", "symbol_code", "bucket"], sort=True).agg(
        open_ticks=("open_ticks", "first"),
        high_ticks=("high_ticks", "max"),
        low_ticks=("low_ticks", "min"),
        close_ticks=("close_ticks", "last"),
        volume=("volume", "sum"),
        observed_1m_components=("stamp", "size"),
        first_component_time_ns=("stamp", "min"),
        last_component_time_ns=("stamp", "max"),
    )
    return grouped.reset_index().sort_values("bucket", kind="stable").reset_index(
        drop=True
    )


@pytest.fixture(scope="module")
def paired(exploration_1m, exploration_5m):
    derived = _aggregate_from_minutes(exploration_1m)
    built = exploration_5m.to_frame().sort_values("ts_event_ns").reset_index(drop=True)
    return derived, built


def test_row_counts_match(paired):
    derived, built = paired
    assert len(derived) == len(built)


def test_bar_labels_match(paired):
    """The 5-min label is the bucket START (finding E: ts_event is the bar open)."""
    derived, built = paired
    np.testing.assert_array_equal(
        derived["bucket"].to_numpy(), built["ts_event_ns"].to_numpy()
    )


@pytest.mark.parametrize(
    "column",
    [
        "open_ticks",
        "high_ticks",
        "low_ticks",
        "close_ticks",
        "volume",
        "symbol_code",
        "session_id",
        "observed_1m_components",
        "first_component_time_ns",
        "last_component_time_ns",
    ],
)
def test_column_is_the_exact_aggregation(paired, column):
    derived, built = paired
    np.testing.assert_array_equal(
        derived[column].to_numpy().astype(np.int64),
        built[column].to_numpy().astype(np.int64),
    )


def test_no_five_minute_bar_spans_two_contracts_or_sessions(exploration_1m):
    stamps = np.asarray(exploration_1m["ts_event_ns"])
    bucket = stamps // BAR_NS
    frame = pd.DataFrame(
        {
            "bucket": bucket,
            "symbol_code": np.asarray(exploration_1m["symbol_code"]),
            "session_id": np.asarray(exploration_1m["session_id"]),
        }
    )
    per_bucket = frame.groupby("bucket").nunique()
    assert (per_bucket["symbol_code"] == 1).all(), "a bucket spans two contracts"
    assert (per_bucket["session_id"] == 1).all(), "a bucket spans two sessions"


def test_negative_case_a_one_bar_shift_is_detected(paired):
    """Shift the derived labels by one bar; the comparison must fail.

    This is what proves the equality assertions above are load-bearing rather than
    comparing something to itself.
    """
    derived, built = paired
    shifted = derived["bucket"].to_numpy() + BAR_NS
    assert not np.array_equal(shifted, built["ts_event_ns"].to_numpy())


def test_negative_case_a_single_altered_tick_is_detected(paired):
    derived, built = paired
    perturbed = derived["high_ticks"].to_numpy().copy()
    perturbed[len(perturbed) // 2] += 1
    assert not np.array_equal(perturbed, built["high_ticks"].to_numpy())


def test_negative_case_bar_end_interpretation_would_fail(paired):
    """Spec §13 test 1: "a bar-end interpretation must fail."

    If `ts_event` denoted the interval close, the 5-min label would be the bucket end.
    Assert that reading disagrees with what was built.
    """
    derived, built = paired
    as_bar_end = derived["bucket"].to_numpy() + BAR_NS
    assert not np.array_equal(as_bar_end, built["ts_event_ns"].to_numpy()), (
        "bar-open and bar-end labelling are indistinguishable here, so this store "
        "cannot confirm finding E"
    )
