"""Streaming validation and volume scan over the raw Databento source.

Pass 1 of the two-pass build (spec §5). Ported from `prepare_databento_mnq.py:110`
(`scan_daily_outright_volume`), extended to:

  * classify symbols authoritatively rather than counting a percentage (§5.1 gate 3);
  * retain the actual out-of-session rows rather than only their count, so
    docs/DISCREPANCIES.md D4 can be resolved from evidence.

Memory is bounded by the number of (trade_date, symbol) pairs, not by row count. A full
pass over 3.67M rows takes a few seconds; this is not a scale problem (§16.2).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

import numpy as np
import pandas as pd

from mnq_lab import SpineError
from mnq_lab.spine.calendar import trade_date_strings
from mnq_lab.spine.symbols import (
    OUTRIGHT_PATTERN,
    SymbolClassification,
    classify_symbols,
)
from mnq_lab.spine.vendored import CME_TIMEZONE, cme_session_mask

__all__ = ["SOURCE_COLUMNS", "ScanResult", "read_source_chunks", "scan_source"]

# prepare_databento_mnq.py:33
SOURCE_COLUMNS = ("ts_event", "open", "high", "low", "close", "volume", "symbol")

_DTYPES = {
    "open": "float64",
    "high": "float64",
    "low": "float64",
    "close": "float64",
    "volume": "int64",
    "symbol": "string",
}


def read_source_chunks(
    source_csv: Path, chunksize: int = 250_000
) -> Iterator[pd.DataFrame]:
    """Stream the source with a fixed schema. Ported from prepare_databento_mnq.py:87."""
    if chunksize < 10_000:
        raise SpineError("chunksize must be at least 10,000")
    try:
        yield from pd.read_csv(
            source_csv,
            usecols=list(SOURCE_COLUMNS),
            dtype=_DTYPES,
            chunksize=chunksize,
            low_memory=False,
        )
    except ValueError as exc:
        raise SpineError(
            f"source schema does not contain {list(SOURCE_COLUMNS)}: {exc}"
        ) from exc


def _validate_chunk(chunk: pd.DataFrame, chunk_number: int) -> None:
    """Every validation from prepare_databento_mnq.py:128-173, unchanged."""
    if chunk.isna().any().any():
        counts = chunk.isna().sum()
        raise SpineError(
            f"null source values in chunk {chunk_number}: {counts[counts > 0].to_dict()}"
        )
    for column in ("open", "high", "low", "close"):
        values = chunk[column].to_numpy()
        if not np.isfinite(values).all():
            raise SpineError(f"{column} contains NaN/infinity in chunk {chunk_number}")
    if (chunk["volume"] < 0).any():
        raise SpineError(f"negative volume in chunk {chunk_number}")
    invalid_high = (
        (chunk["high"] < chunk["open"])
        | (chunk["high"] < chunk["close"])
        | (chunk["high"] < chunk["low"])
    )
    invalid_low = (
        (chunk["low"] > chunk["open"])
        | (chunk["low"] > chunk["close"])
        | (chunk["low"] > chunk["high"])
    )
    if invalid_high.any() or invalid_low.any():
        raise SpineError(f"OHLC invariant failure in chunk {chunk_number}")


@dataclass
class ScanResult:
    daily_volume: dict[tuple[str, str], int]
    first_year_by_symbol: dict[str, int]
    classification: SymbolClassification
    out_of_session_rows: list[dict[str, Any]] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)


def scan_source(source_csv: Path, chunksize: int = 250_000, *, verbose: bool = True) -> ScanResult:
    """Validate the full source and aggregate session volume per outright contract."""
    source_csv = Path(source_csv)
    if not source_csv.is_file():
        raise SpineError(f"source CSV not found: {source_csv}")

    daily_volume: defaultdict[tuple[str, str], int] = defaultdict(int)
    first_year_by_symbol: dict[str, int] = {}
    symbol_counts: Counter[str] = Counter()
    out_of_session_rows: list[dict[str, Any]] = []

    rows = 0
    zero_volume_rows = 0
    session_artifacts = 0
    first_timestamp: Optional[pd.Timestamp] = None
    last_timestamp: Optional[pd.Timestamp] = None
    previous_timestamp: Optional[pd.Timestamp] = None

    for chunk_number, chunk in enumerate(read_source_chunks(source_csv, chunksize), 1):
        rows += len(chunk)
        _validate_chunk(chunk, chunk_number)

        timestamp = pd.to_datetime(chunk["ts_event"], utc=True, errors="coerce")
        if timestamp.isna().any():
            bad = np.flatnonzero(timestamp.isna().to_numpy())[:5].tolist()
            raise SpineError(
                f"timestamp parse failures in chunk {chunk_number}, offsets {bad}"
            )
        if previous_timestamp is not None and timestamp.iloc[0] < previous_timestamp:
            raise SpineError("global timestamp order moves backward")
        if (timestamp.diff().dropna() < pd.Timedelta(0)).any():
            raise SpineError(
                f"global timestamp order moves backward in chunk {chunk_number}"
            )
        previous_timestamp = timestamp.iloc[-1]
        if first_timestamp is None:
            first_timestamp = timestamp.iloc[0]
        last_timestamp = timestamp.iloc[-1]

        # Finding B: count explicit zero-volume rows. Observing zero of them does NOT
        # establish the vendor's bar-generation rule (spec §3 finding B).
        zero_volume_rows += int((chunk["volume"] == 0).sum())

        # Distinct-symbol counts over the WHOLE source, before any filtering, so the
        # Gate 3 partition is exhaustive.
        symbol_counts.update(chunk["symbol"].value_counts().to_dict())

        outright = chunk["symbol"].str.fullmatch(OUTRIGHT_PATTERN, na=False)
        selected = chunk.loc[outright].copy()
        selected_timestamp = timestamp.loc[outright]

        local = selected_timestamp.dt.tz_convert(CME_TIMEZONE)
        in_session = cme_session_mask(local, "open")
        excluded = int((~in_session).sum())
        if excluded:
            session_artifacts += excluded
            # D4: retain the evidence, not just the count.
            for offset in np.flatnonzero((~in_session).to_numpy())[:20]:
                row = selected.iloc[int(offset)]
                out_of_session_rows.append(
                    {
                        "ts_event_utc": selected_timestamp.iloc[int(offset)].isoformat(),
                        "ts_event_ct": local.iloc[int(offset)].isoformat(),
                        "weekday_ct": int(local.iloc[int(offset)].weekday()),
                        "symbol": str(row["symbol"]),
                        "volume": int(row["volume"]),
                    }
                )

        selected = selected.loc[in_session].copy()
        selected_timestamp = selected_timestamp.loc[in_session]
        if selected.empty:
            continue
        selected["trade_date"] = trade_date_strings(selected_timestamp).to_numpy()

        years = selected_timestamp.dt.year.to_numpy()
        for symbol, observed_year in zip(selected["symbol"], years):
            first_year_by_symbol.setdefault(str(symbol), int(observed_year))

        aggregate = selected.groupby(
            ["trade_date", "symbol"], sort=False, observed=True
        )["volume"].sum()
        for key, value in aggregate.items():
            daily_volume[(str(key[0]), str(key[1]))] += int(value)

        if verbose and (chunk_number == 1 or chunk_number % 5 == 0):
            print(
                f"volume scan: {rows:,} rows, {len(daily_volume):,} "
                "session-contract totals",
                flush=True,
            )

    if first_timestamp is None:
        raise SpineError("source contained no rows")

    classification = classify_symbols(dict(symbol_counts))

    report = {
        "source_rows": rows,
        "distinct_symbols": classification.retained_symbol_count
        + classification.rejected_symbol_count,
        "outright_rows": classification.retained_rows,
        "calendar_spread_rows_excluded": classification.rejected_rows,
        "out_of_session_outright_rows_excluded": session_artifacts,
        "explicit_zero_volume_rows": zero_volume_rows,
        "source_start_utc": first_timestamp.isoformat(),
        "source_end_utc": last_timestamp.isoformat(),
    }
    return ScanResult(
        daily_volume=dict(daily_volume),
        first_year_by_symbol=first_year_by_symbol,
        classification=classification,
        out_of_session_rows=out_of_session_rows,
        report=report,
    )
