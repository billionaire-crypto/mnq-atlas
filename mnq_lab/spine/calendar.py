"""CME session calendar: trade dates, session ids, session boundaries.

Spec §4: session calendar is America/Chicago; a Globex session runs 17:00 CT through
16:00 CT the next day; the maintenance break is [16:00, 17:00) CT.

Spec §5: "Session index computed once in the spine. Never call
`lora_statistics.cme_session_ids` at study time — it is a Python loop with per-row tz
conversion. It survives only as a DST test oracle."

The trade-date rule is ported verbatim from `prepare_databento_mnq.py:82`
(`_trade_date_strings`) because Gate 2 requires row-for-row identity with output built by
that function. It adds seven hours to the *exchange-local* timestamp, so 17:00 CT maps to
00:00 the following day in either standard or daylight time.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from mnq_lab import SpineError
from mnq_lab.spine.vendored import CME_TIMEZONE

__all__ = [
    "CME_TIMEZONE",
    "TRADE_DATE_OFFSET_HOURS",
    "trade_date_strings",
    "trade_date_ids",
    "session_ids_to_strings",
    "session_row_groups",
]

# 17:00 CT is the session boundary; +7h maps it to midnight (prepare_databento_mnq.py:84).
TRADE_DATE_OFFSET_HOURS = 7


def _to_local(utc_timestamp: pd.Series) -> pd.Series:
    if utc_timestamp.dt.tz is None:
        raise SpineError(
            "trade-date assignment requires tz-aware UTC timestamps; a naive series "
            "would silently adopt the machine's local zone (spec §4)"
        )
    return utc_timestamp.dt.tz_convert(CME_TIMEZONE)


def trade_date_strings(utc_timestamp: pd.Series) -> pd.Series:
    """CME trade date as 'YYYY-MM-DD'.

    Verbatim port of `prepare_databento_mnq.py:82` `_trade_date_strings`. Gate 2 depends
    on this being the same function, not an equivalent one.
    """
    local = _to_local(utc_timestamp)
    return (local + pd.Timedelta(hours=TRADE_DATE_OFFSET_HOURS)).dt.strftime("%Y-%m-%d")


def trade_date_ids(utc_timestamp: pd.Series) -> np.ndarray:
    """CME trade date as int32 YYYYMMDD, for compact storage in the column store.

    Derived from the same shifted local timestamp as `trade_date_strings`, so the two
    cannot drift. `tests/test_session_id_equivalence.py` asserts they agree with each
    other and with the `lora_statistics.cme_session_ids` DST oracle.
    """
    local = _to_local(utc_timestamp)
    shifted = local + pd.Timedelta(hours=TRADE_DATE_OFFSET_HOURS)
    ids = (
        shifted.dt.year.to_numpy(dtype=np.int64) * 10_000
        + shifted.dt.month.to_numpy(dtype=np.int64) * 100
        + shifted.dt.day.to_numpy(dtype=np.int64)
    )
    return ids.astype(np.int32)


def session_ids_to_strings(session_ids: np.ndarray) -> np.ndarray:
    """Inverse of `trade_date_ids`: int32 YYYYMMDD -> 'YYYY-MM-DD'."""
    ids = np.asarray(session_ids, dtype=np.int64)
    year, remainder = np.divmod(ids, 10_000)
    month, day = np.divmod(remainder, 100)
    return np.char.add(
        np.char.add(
            np.char.add(year.astype("U4"), "-"),
            np.char.zfill(month.astype("U2"), 2),
        ),
        np.char.add("-", np.char.zfill(day.astype("U2"), 2)),
    ).astype("U10")


def session_row_groups(session_ids: np.ndarray) -> list[np.ndarray]:
    """Contiguous row index blocks, one per session.

    Ported from `lora_statistics.py:78` `session_row_groups`, unchanged in behaviour.
    Raises if a session appears in two non-contiguous regions, which would mean the
    spine is not sorted by time.
    """
    ids = np.asarray(session_ids)
    if ids.ndim != 1 or len(ids) == 0:
        raise SpineError("session_ids must be a nonempty vector")
    boundaries = np.flatnonzero(ids[1:] != ids[:-1]) + 1
    groups = np.split(np.arange(len(ids), dtype=np.int64), boundaries)
    if len({str(ids[group[0]]) for group in groups}) != len(groups):
        raise SpineError("a CME session appears in multiple non-contiguous regions")
    return groups
