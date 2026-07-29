"""Build the data spine: 1-minute and 5-minute active-contract stores, both tiers.

Spec §5. Two streaming passes over the source, then a per-year shard pass:

  1. `source.scan_source` validates every row, classifies every symbol, and aggregates
     session volume per outright contract.
  2. `rolls.build_causal_active_contract_map` fixes each session's contract from volumes
     through the *previous* completed session.
  3. `_collect_active_rows_sharded` keeps only the causally selected contract, writing
     one shard per trade-date **year**. Spec §16.2: "The memory constraint is
     `collect_active_rows`' frame concat (1-2 GB peak over 7 years). Fix with per-year
     shards, not clever chunking of the read." A trade date belongs to exactly one year,
     so no (trade_date, symbol) resample group ever spans a shard.
  4. Each shard is resampled to 5 minutes with component coverage.
  5. Rows are split into the exploration and locked-confirmation tiers on CME trade date
     and written to physically separate stores.

This module is one of only three permitted to name the locked store (§16.4.1).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from mnq_lab import SpineError
from mnq_lab.constants import CONSTANTS_PATH, REPO_ROOT, SPEC_PATH, load_spine_constants
from mnq_lab.core.units import from_quanta, to_quanta
from mnq_lab.spine import seal
from mnq_lab.spine.calendar import (
    CME_TIMEZONE,
    session_ids_to_strings,
    trade_date_ids,
    trade_date_strings,
)
from mnq_lab.spine.resample import compute_rollover, resample_to_five_minutes
from mnq_lab.spine.rolls import build_causal_active_contract_map
from mnq_lab.spine.seal import SEAL_BOUNDARY_TRADE_DATE, Corpus, store_path
from mnq_lab.spine.source import read_source_chunks, scan_source
from mnq_lab.spine.store import (
    PIPELINE_VERSION,
    environment_fingerprint,
    write_store,
)
from mnq_lab.spine.symbols import OUTRIGHT_PATTERN
from mnq_lab.spine.vendored import cme_session_mask, sha256_file

__all__ = ["build_spine", "BuildResult"]

_SHARD_COLUMNS = (
    "ts_event_ns",
    "open_ticks",
    "high_ticks",
    "low_ticks",
    "close_ticks",
    "volume",
    "symbol_code",
    "session_id",
)


@dataclass
class BuildResult:
    stores: dict[tuple[str, str], Path]
    manifests: dict[tuple[str, str], dict[str, Any]]
    reports: dict[str, Any]


# --- pass 2: per-year shards -------------------------------------------------------

def _collect_active_rows_sharded(
    source_csv: Path,
    active_map: dict[str, str],
    symbol_codes: dict[str, int],
    shard_dir: Path,
    tick_size: float,
    chunksize: int,
    *,
    verbose: bool = True,
) -> list[Path]:
    """Second streaming pass: keep the causally selected contract, shard by year."""
    shard_dir.mkdir(parents=True, exist_ok=True)
    pending: dict[str, list[dict[str, np.ndarray]]] = {}
    written: dict[str, Path] = {}
    scanned = selected_rows = 0

    def flush(year: str) -> None:
        blocks = pending.pop(year, None)
        if not blocks:
            return
        merged = {
            name: np.concatenate([block[name] for block in blocks])
            for name in _SHARD_COLUMNS
        }
        path = shard_dir / f"shard_{year}.npz"
        if path.exists():
            # Years arrive contiguously in a time-sorted source, so this should never
            # fire. If it does, the source is not sorted and the spine is invalid.
            raise SpineError(
                f"shard {path.name} already exists; trade-date years are not "
                "contiguous, so the source is not time-ordered"
            )
        np.savez(path, **merged)
        written[year] = path

    for chunk_number, chunk in enumerate(read_source_chunks(source_csv, chunksize), 1):
        scanned += len(chunk)
        outright = chunk["symbol"].str.fullmatch(OUTRIGHT_PATTERN, na=False)
        if not outright.any():
            continue
        timestamp = pd.to_datetime(chunk["ts_event"], utc=True, errors="raise")
        selected = chunk.loc[outright]
        selected_timestamp = timestamp.loc[outright]

        local = selected_timestamp.dt.tz_convert(CME_TIMEZONE)
        in_session = cme_session_mask(local, "open")
        selected = selected.loc[in_session]
        selected_timestamp = selected_timestamp.loc[in_session]
        if selected.empty:
            continue

        trade_dates = trade_date_strings(selected_timestamp)
        mapped = trade_dates.map(active_map)
        if mapped.isna().any():
            unknown = sorted(set(trade_dates[mapped.isna()]))[:5]
            raise SpineError(
                f"trade dates {unknown} have no active-contract assignment. Pass 2 sees "
                "a session pass 1 did not, so the two passes disagree; rows would be "
                "dropped silently (spec §16.4.3)."
            )
        keep = selected["symbol"].to_numpy() == mapped.to_numpy()
        if not keep.any():
            continue
        selected = selected.loc[keep]
        selected_timestamp = selected_timestamp.loc[keep]
        trade_dates = trade_dates.loc[keep]
        selected_rows += int(len(selected))

        block = {
            "ts_event_ns": selected_timestamp.to_numpy(dtype="datetime64[ns]").astype(
                np.int64
            ),
            "open_ticks": to_quanta(selected["open"].to_numpy(), tick_size, name="open"),
            "high_ticks": to_quanta(selected["high"].to_numpy(), tick_size, name="high"),
            "low_ticks": to_quanta(selected["low"].to_numpy(), tick_size, name="low"),
            "close_ticks": to_quanta(
                selected["close"].to_numpy(), tick_size, name="close"
            ),
            "volume": selected["volume"].to_numpy(dtype=np.int64),
            "symbol_code": np.array(
                [symbol_codes[str(s)] for s in selected["symbol"]], dtype=np.int16
            ),
            "session_id": trade_date_ids(selected_timestamp),
        }

        years = np.asarray([date[:4] for date in trade_dates], dtype="U4")
        for year in np.unique(years):
            mask = years == year
            pending.setdefault(str(year), []).append(
                {name: values[mask] for name, values in block.items()}
            )
        # Flush every year strictly older than the newest one seen, bounding memory to
        # roughly one year of rows. np.unique returns sorted, so [-1] is the newest;
        # ndarray.max() has no ufunc loop for fixed-width string dtypes.
        newest = str(np.unique(years)[-1])
        for year in sorted(list(pending)):
            if year < newest:
                flush(year)

        if verbose and (chunk_number == 1 or chunk_number % 5 == 0):
            print(
                f"active-chain scan: {scanned:,} rows, {selected_rows:,} selected",
                flush=True,
            )

    for year in sorted(list(pending)):
        flush(year)

    if not written:
        raise SpineError("active-contract selection produced no rows")
    return [written[year] for year in sorted(written)]


# --- shard -> five-minute bars -----------------------------------------------------

def _shard_to_frame(path: Path, symbols: list[str], tick_size: float) -> pd.DataFrame:
    with np.load(path) as payload:
        data = {name: payload[name] for name in _SHARD_COLUMNS}
    table = np.asarray(symbols, dtype=object)
    # Explicit ns: pandas 3.0's `to_datetime(..., utc=True)` yields datetime64[us],
    # and spec §4 requires UTC *nanosecond* storage. Never let the unit be inferred.
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                data["ts_event_ns"].astype("datetime64[ns]"), utc=True
            ),
            "trade_date": session_ids_to_strings(data["session_id"]),
            "symbol": table[data["symbol_code"].astype(np.int64)],
            "open": from_quanta(data["open_ticks"], tick_size),
            "high": from_quanta(data["high_ticks"], tick_size),
            "low": from_quanta(data["low_ticks"], tick_size),
            "close": from_quanta(data["close_ticks"], tick_size),
            "volume": data["volume"],
            "symbol_code": data["symbol_code"],
            "session_id": data["session_id"],
        }
    )


# --- store assembly ----------------------------------------------------------------

def _one_minute_columns(frame: pd.DataFrame, tick_size: float) -> dict[str, np.ndarray]:
    return {
        "ts_event_ns": frame["timestamp"].to_numpy(dtype="datetime64[ns]").astype(np.int64),
        "open_ticks": to_quanta(frame["open"].to_numpy(), tick_size, name="open"),
        "high_ticks": to_quanta(frame["high"].to_numpy(), tick_size, name="high"),
        "low_ticks": to_quanta(frame["low"].to_numpy(), tick_size, name="low"),
        "close_ticks": to_quanta(frame["close"].to_numpy(), tick_size, name="close"),
        "volume": frame["volume"].to_numpy(dtype=np.int64),
        "symbol_code": frame["symbol_code"].to_numpy(dtype=np.int16),
        "session_id": frame["session_id"].to_numpy(dtype=np.int32),
    }


def _five_minute_columns(
    frame: pd.DataFrame, symbol_codes: dict[str, int], tick_size: float
) -> dict[str, np.ndarray]:
    columns = {
        "ts_event_ns": frame["timestamp"].to_numpy(dtype="datetime64[ns]").astype(np.int64),
        "open_ticks": to_quanta(frame["open"].to_numpy(), tick_size, name="open"),
        "high_ticks": to_quanta(frame["high"].to_numpy(), tick_size, name="high"),
        "low_ticks": to_quanta(frame["low"].to_numpy(), tick_size, name="low"),
        "close_ticks": to_quanta(frame["close"].to_numpy(), tick_size, name="close"),
        "volume": frame["volume"].to_numpy(dtype=np.int64),
        "symbol_code": np.array(
            [symbol_codes[str(s)] for s in frame["symbol"]], dtype=np.int16
        ),
        "session_id": frame["session_id"].to_numpy(dtype=np.int32),
        "expected_1m_components": frame["expected_1m_components"].to_numpy(dtype=np.int8),
        "observed_1m_components": frame["observed_1m_components"].to_numpy(dtype=np.int8),
        "component_coverage_rate": frame["component_coverage_rate"].to_numpy(
            dtype=np.float64
        ),
        "first_component_time_ns": frame["first_component_time"]
        .to_numpy(dtype="datetime64[ns]")
        .astype(np.int64),
        "last_component_time_ns": frame["last_component_time"]
        .to_numpy(dtype="datetime64[ns]")
        .astype(np.int64),
        # Window-relative by construction: recomputed per tier (D7).
        "rollover": compute_rollover(frame["symbol"]),
    }
    return columns


def _base_metadata(
    *,
    build_id: str,
    corpus: Corpus,
    frequency: str,
    source_csv: Path,
    source_sha: str,
    scan_report: dict[str, Any],
    classification_manifest: dict[str, Any],
    rolls: list[dict[str, Any]],
    symbols: list[str],
    constants,
    session_ids: np.ndarray,
) -> dict[str, Any]:
    return {
        "build_id": build_id,
        "pipeline_version": PIPELINE_VERSION,
        "spec_version": constants.spec_version,
        "program_id": constants.program_id,
        "corpus": corpus.value,
        "frequency": frequency,
        "bar_seconds": 60 if frequency == "1m" else 300,
        "source": {
            "path": str(source_csv),
            "sha256": source_sha,
            "bytes": source_csv.stat().st_size,
            "rows": scan_report["source_rows"],
            "start_utc": scan_report["source_start_utc"],
            "end_utc": scan_report["source_end_utc"],
        },
        "frozen_files": {
            "REV6_FROZEN_SPEC.md": sha256_file(SPEC_PATH),
            "analysis_constants_v1.yaml": sha256_file(CONSTANTS_PATH),
        },
        "tick_size": constants.tick_size,
        "price_storage": "int32 ticks; value = ticks * tick_size",
        "timezone_rules": {
            "storage_tz": constants.storage_tz,
            "storage_unit": "UTC nanoseconds",
            "session_tz": constants.session_tz,
            "bar_label": constants.bar_label,
            "bar_interval": "[t, t + bar_seconds)",
        },
        "session_rules": {
            "globex_session": "17:00 CT -> 16:00 CT next day",
            "maintenance_break_ct": list(constants.maintenance_break_ct),
            "rth_ct": [constants.rth_start_ct, constants.rth_end_ct],
            "trade_date_rule": "local CT timestamp + 7h, date part",
            "session_id_encoding": "int32 YYYYMMDD of the CME trade date",
            "seal_boundary_trade_date": SEAL_BOUNDARY_TRADE_DATE,
        },
        "trade_date_first": int(session_ids.min()),
        "trade_date_last": int(session_ids.max()),
        "session_count": int(len(np.unique(session_ids))),
        "rolls": rolls,
        "roll_count": len(rolls),
        "roll_policy": {
            "selection": "prior-session volume crossover",
            "direction": "next quarterly contract only; never switch back",
            "effective_time": "next available CME trade date",
            "expiry_guard": True,
            "causality": "session d fixed from volumes through completed session d-1",
        },
        "symbol_classification": classification_manifest,
        "symbols": symbols,
        "source_scan_report": scan_report,
        "environment": environment_fingerprint(REPO_ROOT),
    }


# --- orchestration -----------------------------------------------------------------

def build_spine(
    source_csv: Path | str,
    out_root: Path | str,
    *,
    chunksize: int = 250_000,
    shard_dir: Path | str | None = None,
    keep_shards: bool = False,
    verbose: bool = True,
) -> BuildResult:
    source_csv = Path(source_csv)
    out_root = Path(out_root)
    constants = load_spine_constants()
    tick_size = constants.tick_size

    if verbose:
        print(f"hashing source {source_csv.name} ...", flush=True)
    source_sha = sha256_file(source_csv)

    scan = scan_source(source_csv, chunksize, verbose=verbose)
    roll_map = build_causal_active_contract_map(
        scan.daily_volume, scan.first_year_by_symbol
    )

    symbols = sorted(scan.classification.retained)
    symbol_codes = {symbol: index for index, symbol in enumerate(symbols)}

    # The complete constants file is a build input, not merely its spine subset.
    # Phase 3 later added derived thresholds to that file without falsifying the
    # already-sealed manifests. Reproducing its build_id therefore requires the
    # historical build-time YAML bytes, then restoring the current YAML before
    # validation. Full manifest-byte identity additionally depends on the original
    # dirty environment fingerprint and is not claimed. See
    # docs/SEALED_STORE_REBUILD.md.
    build_id = hashlib.sha256(
        "|".join(
            [
                source_sha,
                PIPELINE_VERSION,
                sha256_file(SPEC_PATH),
                sha256_file(CONSTANTS_PATH),
            ]
        ).encode("utf-8")
    ).hexdigest()[:16]

    shard_root = Path(shard_dir) if shard_dir is not None else out_root / "_shards"
    if shard_root.exists():
        shutil.rmtree(shard_root)

    shard_paths = _collect_active_rows_sharded(
        source_csv,
        roll_map.active,
        symbol_codes,
        shard_root,
        tick_size,
        chunksize,
        verbose=verbose,
    )

    one_minute_frames: list[pd.DataFrame] = []
    five_minute_frames: list[pd.DataFrame] = []
    resample_reports: dict[str, Any] = {}
    for path in shard_paths:
        year = path.stem.split("_")[-1]
        frame = _shard_to_frame(path, symbols, tick_size)
        one_minute_frames.append(frame)
        result = resample_to_five_minutes(frame)
        bars = result.bars
        bars["session_id"] = (
            bars["trade_date"].str.replace("-", "", regex=False).astype(np.int32)
        )
        five_minute_frames.append(bars)
        resample_reports[year] = result.report
        if verbose:
            print(
                f"  {year}: {len(frame):,} 1m rows -> {len(bars):,} 5m bars, "
                f"fully-labelled {result.report['fully_labeled_1m_grid_rate']:.4f}",
                flush=True,
            )

    minute_bars = pd.concat(one_minute_frames, ignore_index=True).sort_values(
        "timestamp", kind="stable"
    ).reset_index(drop=True)
    five_minute_bars = pd.concat(five_minute_frames, ignore_index=True).sort_values(
        "timestamp", kind="stable"
    ).reset_index(drop=True)

    if not keep_shards:
        shutil.rmtree(shard_root, ignore_errors=True)

    boundary = int(SEAL_BOUNDARY_TRADE_DATE.replace("-", ""))
    stores: dict[tuple[str, str], Path] = {}
    manifests: dict[tuple[str, str], dict[str, Any]] = {}

    for corpus in (Corpus.EXPLORATION, Corpus.LOCKED_CONFIRMATION):
        for frequency, frame in (("1m", minute_bars), ("5m", five_minute_bars)):
            session_ids = frame["session_id"].to_numpy(dtype=np.int64)
            mask = (
                session_ids <= boundary
                if corpus is Corpus.EXPLORATION
                else session_ids > boundary
            )
            tier = frame.loc[mask].reset_index(drop=True)
            if tier.empty:
                raise SpineError(
                    f"tier {corpus.value}/{frequency} is empty; the seal boundary "
                    f"{SEAL_BOUNDARY_TRADE_DATE} does not split this source"
                )
            columns = (
                _one_minute_columns(tier, tick_size)
                if frequency == "1m"
                else _five_minute_columns(tier, symbol_codes, tick_size)
            )
            metadata = _base_metadata(
                build_id=build_id,
                corpus=corpus,
                frequency=frequency,
                source_csv=source_csv,
                source_sha=source_sha,
                scan_report=scan.report,
                classification_manifest=scan.classification.to_manifest(),
                rolls=roll_map.rolls,
                symbols=symbols,
                constants=constants,
                session_ids=tier["session_id"].to_numpy(dtype=np.int64),
            )
            if frequency == "5m":
                metadata["resample_reports_by_year"] = resample_reports
            metadata["out_of_session_source_rows"] = scan.out_of_session_rows

            path = store_path(out_root, corpus, frequency)
            manifests[(corpus.value, frequency)] = write_store(
                path, columns, metadata=metadata
            )
            stores[(corpus.value, frequency)] = path
            if verbose:
                print(f"wrote {path}  rows={len(tier):,}", flush=True)

    reports = {
        "build_id": build_id,
        "source_scan": scan.report,
        "roll_count": roll_map.roll_count,
        "resample_by_year": resample_reports,
        "one_minute_rows": int(len(minute_bars)),
        "five_minute_rows": int(len(five_minute_bars)),
        "out_of_session_source_rows": scan.out_of_session_rows,
    }
    return BuildResult(stores=stores, manifests=manifests, reports=reports)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the MNQ data spine (both corpus tiers)."
    )
    parser.add_argument("--source-csv", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "data")
    parser.add_argument("--chunksize", type=int, default=250_000)
    parser.add_argument("--keep-shards", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    result = build_spine(
        args.source_csv,
        args.out,
        chunksize=args.chunksize,
        keep_shards=args.keep_shards,
        verbose=not args.quiet,
    )
    print(json.dumps(result.reports, indent=2, default=str))


if __name__ == "__main__":
    main()
