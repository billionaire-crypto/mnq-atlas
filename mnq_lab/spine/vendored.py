"""Verbatim copies of validated helpers from the prior pipeline.

Spec §16.2 directs reuse of `_sha256_file` and `_cme_session_mask` from
`data_pipeline.py`. That module defines `torch.nn.Module` subclasses at module scope, so
importing it pulls a training stack into the measurement lab and inflates the environment
fingerprint. The two helpers are therefore copied here **byte-for-byte in behaviour**,
with provenance recorded below.

    source: C:\\Users\\kyawz\\Documents\\Codex\\2026-07-27\\
            role-context-you-are-an-elite\\data_pipeline.py
    CME_TIMEZONE       :42
    _sha256_file       :113
    _cme_session_mask  :255

`tests/test_vendored_equivalence.py` imports the originals and asserts identical output
across an exhaustive minute grid spanning both US DST transitions. Vendoring without that
proof would be an unjustified reimplementation (spec §16.2) — if the test cannot import
the originals it fails, it does not skip. See docs/DISCREPANCIES.md D5.

Do not "improve" anything in this file. Divergence from the original is the one defect it
exists to make impossible.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

import pandas as pd

__all__ = ["CME_TIMEZONE", "sha256_file", "cme_session_mask"]

# data_pipeline.py:42
CME_TIMEZONE = "America/Chicago"


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """data_pipeline.py:113 `_sha256_file`, unchanged."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def cme_session_mask(
    local_timestamp: pd.Series, bar_label: Literal["open", "close"]
) -> pd.Series:
    """data_pipeline.py:255 `_cme_session_mask`, unchanged.

    Return bars entirely inside the standard CME equity-index session.

    CME session: Sunday 17:00 CT through Friday 16:00 CT, with the daily
    maintenance interval 16:00-17:00 CT.
    """

    weekday = local_timestamp.dt.weekday
    minute_of_day = local_timestamp.dt.hour * 60 + local_timestamp.dt.minute
    session_open = 17 * 60
    session_close = 16 * 60

    if bar_label == "open":
        sunday = (weekday == 6) & (minute_of_day >= session_open)
        monday_thursday = weekday.between(0, 3) & (
            (minute_of_day < session_close) | (minute_of_day >= session_open)
        )
        friday = (weekday == 4) & (minute_of_day < session_close)
    else:
        # A close-labelled 17:00 bar spans the maintenance interval; the first
        # valid evening close is 17:05. The 16:00 close remains valid.
        sunday = (weekday == 6) & (minute_of_day > session_open)
        monday_thursday = weekday.between(0, 3) & (
            (minute_of_day <= session_close) | (minute_of_day > session_open)
        )
        friday = (weekday == 4) & (minute_of_day <= session_close)
    return sunday | monday_thursday | friday
