"""The vendored helpers must be behaviourally identical to the originals.

Spec §16.2 says to reuse `_sha256_file` and `_cme_session_mask` from `data_pipeline.py`.
They are copied into `mnq_lab/spine/vendored.py` instead, to avoid importing a torch
training stack into the measurement lab (docs/DISCREPANCIES.md D5). That deviation is
only legitimate if the copies are proven equivalent, which is what this file does.

If the originals cannot be imported, this test **fails**. It does not skip: a silently
skipped equivalence proof is exactly the "fluent claim stronger than its mechanism"
failure mode the spec warns about (§16.7).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mnq_lab.spine.vendored import cme_session_mask, sha256_file

ORIGINAL_ROOT = Path(
    r"C:\Users\kyawz\Documents\Codex\2026-07-27\role-context-you-are-an-elite"
)


@pytest.fixture(scope="module")
def original():
    if not (ORIGINAL_ROOT / "data_pipeline.py").is_file():
        pytest.fail(
            f"cannot import the originals from {ORIGINAL_ROOT}. The vendored copies in "
            "mnq_lab/spine/vendored.py are unproven without them (D5). Restore the "
            "path or delete the vendoring — do not skip this test."
        )
    if str(ORIGINAL_ROOT) not in sys.path:
        sys.path.insert(0, str(ORIGINAL_ROOT))
    return importlib.import_module("data_pipeline")


def _minute_grid(start: str, end: str) -> pd.Series:
    """Every minute in [start, end), exchange-local."""
    index = pd.date_range(start, end, freq="1min", tz="UTC", inclusive="left")
    return pd.Series(index.tz_convert("America/Chicago"))


# Both US DST transitions, plus a full ordinary week and a year boundary.
GRIDS = {
    "spring_forward_2021": ("2021-03-12", "2021-03-16"),
    "fall_back_2021": ("2021-11-05", "2021-11-09"),
    "spring_forward_2026": ("2026-03-06", "2026-03-10"),
    "fall_back_2019": ("2019-11-01", "2019-11-05"),
    "ordinary_week": ("2022-06-06", "2022-06-13"),
    "year_boundary": ("2019-12-29", "2020-01-03"),
}


@pytest.mark.parametrize("name", sorted(GRIDS))
@pytest.mark.parametrize("bar_label", ["open", "close"])
def test_session_mask_matches_original(original, name, bar_label):
    start, end = GRIDS[name]
    local = _minute_grid(start, end)
    mine = cme_session_mask(local, bar_label).to_numpy()
    theirs = original._cme_session_mask(local, bar_label).to_numpy()
    assert mine.dtype == theirs.dtype
    np.testing.assert_array_equal(mine, theirs)


def test_negative_case_the_grid_can_detect_a_boundary_change(original):
    """A one-minute shift at the session open must be visible on this grid.

    Without this, "the copies agree" could mean "the grid contains nothing that
    distinguishes them".
    """
    local = _minute_grid(*GRIDS["ordinary_week"])
    correct = cme_session_mask(local, "open").to_numpy()

    def subtly_wrong(local_timestamp: pd.Series) -> np.ndarray:
        weekday = local_timestamp.dt.weekday
        minute_of_day = local_timestamp.dt.hour * 60 + local_timestamp.dt.minute
        # `>` instead of `>=` at 17:00 CT — drops exactly the session-open minute.
        sunday = (weekday == 6) & (minute_of_day > 17 * 60)
        monday_thursday = weekday.between(0, 3) & (
            (minute_of_day < 16 * 60) | (minute_of_day > 17 * 60)
        )
        friday = (weekday == 4) & (minute_of_day < 16 * 60)
        return (sunday | monday_thursday | friday).to_numpy()

    assert not np.array_equal(correct, subtly_wrong(local)), (
        "the test grid cannot distinguish a 17:00 CT boundary error, so the "
        "equivalence assertions above prove nothing"
    )


def test_sha256_matches_original(original, tmp_path):
    payloads = [b"", b"a", b"mnq" * 100_000, bytes(range(256))]
    for index, payload in enumerate(payloads):
        path = tmp_path / f"payload_{index}.bin"
        path.write_bytes(payload)
        assert sha256_file(path) == original._sha256_file(path)


def test_negative_case_sha256_distinguishes_a_one_bit_change(tmp_path):
    first = tmp_path / "a.bin"
    second = tmp_path / "b.bin"
    first.write_bytes(b"\x00" * 4096)
    second.write_bytes(b"\x00" * 4095 + b"\x01")
    assert sha256_file(first) != sha256_file(second)


def test_timezone_constant_matches_original(original):
    from mnq_lab.spine.vendored import CME_TIMEZONE

    assert CME_TIMEZONE == original.CME_TIMEZONE == "America/Chicago"
