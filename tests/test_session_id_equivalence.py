"""Session ids computed in the spine must match the DST oracle (spec §13 test 18).

Spec §5: `lora_statistics.cme_session_ids` "is a Python loop with per-row tz conversion.
It survives only as a DST test oracle." This is that use.

Two independent formulations are compared:

  * the spine's rule, ported from `prepare_databento_mnq.py:82` — add 7 hours to the
    *exchange-local* timestamp and take the date part;
  * the oracle's rule — advance the local date by one day when the local hour >= 17.

They are only obviously equivalent away from DST boundaries. `+7h` on a tz-aware
timestamp adds seven *absolute* hours and then re-renders in local time, so a span
crossing a 2:00 AM transition would land an hour off. That is exactly what this file is
for, and the reasoning above is not a substitute for running it.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mnq_lab.spine.calendar import (
    session_ids_to_strings,
    trade_date_ids,
    trade_date_strings,
)

ORIGINAL_ROOT = Path(
    r"C:\Users\kyawz\Documents\Codex\2026-07-27\role-context-you-are-an-elite"
)


@pytest.fixture(scope="module")
def oracle():
    if not (ORIGINAL_ROOT / "lora_statistics.py").is_file():
        pytest.fail(
            f"DST oracle not found at {ORIGINAL_ROOT}. Do not skip: the spine's "
            "session index would then be unverified against any independent rule."
        )
    if str(ORIGINAL_ROOT) not in sys.path:
        sys.path.insert(0, str(ORIGINAL_ROOT))
    return importlib.import_module("lora_statistics")


SPANS = {
    "spring_forward_2021": ("2021-03-11", "2021-03-16"),
    "fall_back_2021": ("2021-11-04", "2021-11-09"),
    "spring_forward_2020": ("2020-03-06", "2020-03-11"),
    "fall_back_2026": ("2026-10-30", "2026-11-04"),
    # US and EU DST diverge for two weeks each spring and one each autumn (spec §13
    # test 1). CT is the only zone that matters here, but the weeks are covered anyway.
    "us_eu_divergence_spring": ("2021-03-14", "2021-03-29"),
    "us_eu_divergence_autumn": ("2021-10-30", "2021-11-08"),
    "ordinary_week": ("2022-06-06", "2022-06-13"),
}


def _grid(start: str, end: str) -> pd.Series:
    return pd.Series(pd.date_range(start, end, freq="1min", tz="UTC", inclusive="left"))


@pytest.mark.parametrize("name", sorted(SPANS))
def test_spine_session_ids_match_the_oracle(oracle, name):
    stamps = _grid(*SPANS[name])
    ns = stamps.to_numpy(dtype="datetime64[ns]").astype(np.int64)

    expected = oracle.cme_session_ids(ns)
    from_strings = trade_date_strings(stamps).to_numpy().astype("U10")
    from_ids = session_ids_to_strings(trade_date_ids(stamps))

    np.testing.assert_array_equal(from_strings, expected)
    np.testing.assert_array_equal(from_ids, expected)


@pytest.mark.parametrize("name", sorted(SPANS))
def test_int_and_string_encodings_agree(name):
    stamps = _grid(*SPANS[name])
    ids = trade_date_ids(stamps)
    assert ids.dtype == np.int32
    np.testing.assert_array_equal(
        session_ids_to_strings(ids), trade_date_strings(stamps).to_numpy().astype("U10")
    )


def test_boundary_is_exactly_1700_ct():
    """16:59 CT belongs to today's trade date, 17:00 CT to tomorrow's — in both zones."""
    for local_day, offset in (("2022-01-11", "CST"), ("2022-06-14", "CDT")):
        before = pd.Series(
            [pd.Timestamp(f"{local_day} 16:59").tz_localize("America/Chicago")]
        ).dt.tz_convert("UTC")
        at = pd.Series(
            [pd.Timestamp(f"{local_day} 17:00").tz_localize("America/Chicago")]
        ).dt.tz_convert("UTC")
        next_day = (pd.Timestamp(local_day) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        assert trade_date_strings(before).iloc[0] == local_day, offset
        assert trade_date_strings(at).iloc[0] == next_day, offset


def test_negative_case_an_offset_error_is_detected(oracle):
    """A 6-hour rule instead of 7 must disagree with the oracle on this grid.

    Without this, "the two agree" could mean the grid contains no timestamp where any
    plausible error is visible.
    """
    stamps = _grid(*SPANS["ordinary_week"])
    ns = stamps.to_numpy(dtype="datetime64[ns]").astype(np.int64)
    expected = oracle.cme_session_ids(ns)

    local = stamps.dt.tz_convert("America/Chicago")
    wrong = (local + pd.Timedelta(hours=6)).dt.strftime("%Y-%m-%d").to_numpy().astype("U10")
    assert not np.array_equal(wrong, expected)


def test_negative_case_dst_spans_are_actually_exercised():
    """Assert the DST fixtures contain a transition, not just ordinary days."""
    for name in ("spring_forward_2021", "fall_back_2021"):
        stamps = _grid(*SPANS[name])
        offsets = stamps.dt.tz_convert("America/Chicago").map(lambda t: t.utcoffset())
        assert offsets.nunique() == 2, (
            f"{name} contains only one UTC offset, so it does not span a DST "
            "transition and the equivalence assertions are untested there"
        )
