"""One-minute to five-minute aggregation with component coverage.

Ported from `prepare_databento_mnq.py:379` (`resample_active_chain_to_five_minutes`).
The OHLCV aggregation is unchanged — Gate 2 requires row-for-row identity with output
built by that function — and the coverage columns are added alongside it.

Spec §5: "Component coverage is written during resample (so no 1-min spine is needed at
study time): `expected_1m_components`, `observed_1m_components`,
`component_coverage_rate`, `first_component_time`, `last_component_time`."

Spec §6: "5-min bar existence is not sufficient. A 5-min bar may aggregate fewer than
five 1-min rows, and the missing minutes hide exactly the extremes excursion quantiles
are made of."

`expected_1m_components` is **computed**, not assumed to be 5: for each bar, the five
one-minute labels it spans are tested for CME-session membership and same-trade-date
membership. The session boundaries (16:00 and 17:00 CT) are five-minute aligned, so the
answer should be 5 everywhere — but the build asserts that rather than asserting it in
prose. See `verify_expected_components`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from mnq_lab import SpineError
from mnq_lab.spine.calendar import CME_TIMEZONE, trade_date_strings
from mnq_lab.spine.vendored import cme_session_mask

__all__ = [
    "BAR_SECONDS_1M",
    "BAR_SECONDS_5M",
    "COMPONENTS_PER_5M_BAR",
    "resample_to_five_minutes",
    "compute_rollover",
]

BAR_SECONDS_1M = 60
BAR_SECONDS_5M = 300
COMPONENTS_PER_5M_BAR = BAR_SECONDS_5M // BAR_SECONDS_1M  # 5


@dataclass
class ResampleResult:
    bars: pd.DataFrame
    report: dict[str, Any]


def _expected_components(
    bar_start_utc: pd.DatetimeIndex, bar_trade_date: np.ndarray
) -> np.ndarray:
    """Count one-minute labels a 5-min bar spans that are in-session and same-session.

    A label counts toward `expected` only if it lies inside the CME session mask *and*
    maps to the same CME trade date as the bar. The second condition matters at the
    17:00 CT boundary, where a bar must never draw components from two Globex sessions.
    """
    expected = np.zeros(len(bar_start_utc), dtype=np.int64)
    for offset in range(COMPONENTS_PER_5M_BAR):
        labels = bar_start_utc + pd.Timedelta(minutes=offset)
        local = pd.Series(labels.tz_convert(CME_TIMEZONE))
        in_session = cme_session_mask(local, "open").to_numpy()
        same_session = trade_date_strings(pd.Series(labels)).to_numpy() == bar_trade_date
        expected += (in_session & same_session).astype(np.int64)
    return expected


def resample_to_five_minutes(active_rows: pd.DataFrame) -> ResampleResult:
    """Resample separately by (trade date, contract), then validate.

    `active_rows` must carry tz-aware UTC `timestamp`, `trade_date`, `symbol`, and
    float OHLCV columns. Grouping by (trade_date, symbol) is what guarantees no output
    bar combines contracts or spans the daily maintenance interval.
    """
    required = {"timestamp", "trade_date", "symbol", "open", "high", "low", "close", "volume"}
    missing = required - set(active_rows.columns)
    if missing:
        raise SpineError(f"active rows are missing columns: {sorted(missing)}")

    output_frames: list[pd.DataFrame] = []
    for (trade_date, symbol), group in active_rows.groupby(
        ["trade_date", "symbol"], sort=True, observed=True
    ):
        indexed = group.set_index("timestamp").sort_index()
        indexed = indexed.assign(_component_ts=indexed.index)
        bars = indexed.resample(
            "5min", origin="epoch", label="left", closed="left"
        ).agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            observed_1m_components=("open", "count"),
            first_component_time=("_component_ts", "min"),
            last_component_time=("_component_ts", "max"),
        )
        bars = bars.dropna(subset=["open", "high", "low", "close"])
        if bars.empty:
            continue
        bars["symbol"] = symbol
        bars["trade_date"] = trade_date
        output_frames.append(bars.reset_index())

    if not output_frames:
        raise SpineError("five-minute resampling produced no bars")

    bars = pd.concat(output_frames, ignore_index=True)
    bars = bars.sort_values("timestamp", kind="stable").reset_index(drop=True)

    # --- invariants carried over from prepare_databento_mnq.py:409-431 --------------
    duplicate = bars["timestamp"].duplicated(keep=False)
    if duplicate.any():
        examples = bars.loc[duplicate, ["timestamp", "symbol"]].head(5)
        raise SpineError(
            f"active chain has duplicate 5-minute timestamps: {examples.to_dict('records')}"
        )
    if not bars["timestamp"].is_monotonic_increasing:
        raise SpineError("resampled timestamps are not increasing")
    if (bars["volume"] < 0).any():
        raise SpineError("negative resampled volume")
    invalid_high = (
        (bars["high"] < bars["open"])
        | (bars["high"] < bars["close"])
        | (bars["high"] < bars["low"])
    )
    invalid_low = (
        (bars["low"] > bars["open"])
        | (bars["low"] > bars["close"])
        | (bars["low"] > bars["high"])
    )
    if invalid_high.any() or invalid_low.any():
        raise SpineError("resampled OHLC invariant failure")

    # --- component coverage (spec §5) ----------------------------------------------
    bar_index = pd.DatetimeIndex(bars["timestamp"])
    expected = _expected_components(bar_index, bars["trade_date"].to_numpy())
    observed = bars["observed_1m_components"].to_numpy(dtype=np.int64)

    if (expected <= 0).any():
        offset = int(np.flatnonzero(expected <= 0)[0])
        raise SpineError(
            f"bar at {bars['timestamp'].iloc[offset]} spans zero in-session minute "
            "labels, so its coverage rate is undefined. A bar cannot exist outside the "
            "session it was aggregated from (spec §5)."
        )
    if (observed > expected).any():
        offset = int(np.flatnonzero(observed > expected)[0])
        raise SpineError(
            f"bar at {bars['timestamp'].iloc[offset]} aggregated {observed[offset]} "
            f"one-minute rows but spans only {expected[offset]} in-session labels of "
            "its own trade date. A bar is drawing components from another session "
            "(spec §5); this is a fail-closed condition, not a coverage anomaly."
        )

    bars["expected_1m_components"] = expected.astype(np.int8)
    bars["observed_1m_components"] = observed.astype(np.int8)
    bars["component_coverage_rate"] = observed.astype(np.float64) / expected.astype(
        np.float64
    )

    gaps = bars["timestamp"].diff()
    fully_labeled = int((observed == expected).sum())
    report = {
        "five_minute_rows": int(len(bars)),
        "contract_boundaries": int(bars["symbol"].ne(bars["symbol"].shift()).sum() - 1),
        "non_five_minute_transitions": int(
            (gaps.dropna() != pd.Timedelta(minutes=5)).sum()
        ),
        "utc_start": bars["timestamp"].iloc[0].isoformat(),
        "utc_end": bars["timestamp"].iloc[-1].isoformat(),
        "expected_components_all_five": bool((expected == COMPONENTS_PER_5M_BAR).all()),
        "expected_components_distinct": sorted(
            int(value) for value in np.unique(expected)
        ),
        "fully_labeled_1m_grid_bars": fully_labeled,
        "fully_labeled_1m_grid_rate": fully_labeled / len(bars),
        "symbols": bars["symbol"].value_counts(sort=False).to_dict(),
    }
    return ResampleResult(bars=bars, report=report)


def compute_rollover(symbols: pd.Series | np.ndarray) -> np.ndarray:
    """First bar of the emitted window, or any contract change, is a rollover.

    This flag is **window-relative**: the first row of any emitted range is True because
    no prior contract is visible within that range. The reference CSV was built over
    trade dates 2023-03-30..2026-03-30 and so has True on its first row, even though
    MNQM3 was already active on 2023-03-29. The stores therefore compute `rollover` per
    tier rather than globally — see docs/DISCREPANCIES.md D7.

    `symbol` is the authoritative column; `rollover` is derived and must never be used to
    reconstruct contract identity.
    """
    series = pd.Series(np.asarray(symbols))
    return series.ne(series.shift()).to_numpy(dtype=bool)
