"""The sole Phase 7 exploration-bar adapter.

The public opener has no corpus, tier, path, or override parameter.  Synthetic
tests call the validator directly with an in-memory ``BarStore``.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

import numpy as np
import pandas as pd

from mnq_lab import SpineError
from mnq_lab.constants import REPO_ROOT
from mnq_lab.spine.calendar import trade_date_ids
from mnq_lab.spine.seal import Corpus, assert_exploration_safe, store_path
from mnq_lab.spine.store import BarStore, PIPELINE_VERSION

__all__ = ["ExplorationBars", "open_exploration_bars", "validate_exploration_store"]

_REQUIRED_DTYPES = MappingProxyType(
    {
        "ts_event_ns": np.dtype("int64"),
        "session_id": np.dtype("int32"),
        "symbol_code": np.dtype("int16"),
        "open_ticks": np.dtype("int32"),
        "high_ticks": np.dtype("int32"),
        "low_ticks": np.dtype("int32"),
        "close_ticks": np.dtype("int32"),
        "volume": np.dtype("int64"),
        "expected_1m_components": np.dtype("int8"),
        "observed_1m_components": np.dtype("int8"),
        "component_coverage_rate": np.dtype("float64"),
        "rollover": np.dtype("bool"),
    }
)


@dataclass(frozen=True)
class ExplorationBars:
    build_id: str
    symbols: tuple[str, ...]
    columns: MappingProxyType

    @property
    def n_rows(self) -> int:
        return int(self.columns["ts_event_ns"].size)

    def column(self, name: str) -> np.ndarray:
        try:
            return self.columns[name]
        except KeyError as exc:
            raise SpineError(f"unknown exploration column {name!r}") from exc


def _readonly(array: np.ndarray) -> np.ndarray:
    result = np.array(array, copy=True)
    result.setflags(write=False)
    return result


def validate_exploration_store(store: BarStore) -> ExplorationBars:
    if not isinstance(store, BarStore):
        raise SpineError("store must be a BarStore")
    manifest = store.manifest
    required_manifest = {
        "corpus": "exploration",
        "frequency": "5m",
        "bar_seconds": 300,
        "program_id": "mnq-atlas-001",
        "pipeline_version": PIPELINE_VERSION,
    }
    for field, expected in required_manifest.items():
        if manifest.get(field) != expected:
            raise SpineError(
                f"exploration manifest {field!r} must be {expected!r}, got {manifest.get(field)!r}"
            )
    build_id = manifest.get("build_id")
    if not isinstance(build_id, str) or not build_id:
        raise SpineError("exploration manifest build_id must be nonempty")
    if manifest.get("row_count", 0) <= 0:
        raise SpineError("exploration store date range is empty")

    missing = set(_REQUIRED_DTYPES) - set(store.column_names)
    if missing:
        raise SpineError(f"exploration store is missing columns {sorted(missing)}")
    columns: dict[str, np.ndarray] = {}
    for name, dtype in _REQUIRED_DTYPES.items():
        array = np.asarray(store[name])
        if array.ndim != 1 or array.size != store.n_rows:
            raise SpineError(f"exploration column {name!r} has invalid shape")
        if array.dtype != dtype:
            raise SpineError(
                f"exploration column {name!r} dtype must be {dtype}, got {array.dtype}"
            )
        columns[name] = array

    timestamps = columns["ts_event_ns"]
    sessions = columns["session_id"]
    if not bool(np.all(timestamps[1:] > timestamps[:-1])):
        raise SpineError("exploration timestamps must be strictly increasing and unique")
    first_session = int(np.min(sessions))
    last_session = int(np.max(sessions))
    if first_session < 20190505 or last_session > 20230329:
        raise SpineError("exploration session range crosses the sealed tier boundary")
    if int(manifest.get("trade_date_first", -1)) != first_session:
        raise SpineError("exploration manifest first trade date differs from rows")
    if int(manifest.get("trade_date_last", -1)) != last_session:
        raise SpineError("exploration manifest last trade date differs from rows")
    derived_sessions = trade_date_ids(
        pd.Series(pd.to_datetime(timestamps, unit="ns", utc=True))
    )
    if not np.array_equal(sessions, derived_sessions):
        raise SpineError("exploration session ownership differs from timestamp trade date")

    symbols = manifest.get("symbols")
    if not isinstance(symbols, list) or not symbols or not all(
        isinstance(symbol, str) and symbol for symbol in symbols
    ):
        raise SpineError("exploration symbols must be nonempty strings")
    codes = columns["symbol_code"]
    if bool(np.any(codes < 0)) or bool(np.any(codes >= len(symbols))):
        raise SpineError("exploration symbol_code is outside the symbol table")

    open_ticks = columns["open_ticks"]
    high_ticks = columns["high_ticks"]
    low_ticks = columns["low_ticks"]
    close_ticks = columns["close_ticks"]
    if not bool(
        np.all(open_ticks > 0)
        and np.all(high_ticks > 0)
        and np.all(low_ticks > 0)
        and np.all(close_ticks > 0)
    ):
        raise SpineError("exploration OHLC ticks must be strictly positive")
    if not bool(
        np.all(high_ticks >= open_ticks)
        and np.all(high_ticks >= close_ticks)
        and np.all(high_ticks >= low_ticks)
        and np.all(low_ticks <= open_ticks)
        and np.all(low_ticks <= close_ticks)
    ):
        raise SpineError("exploration OHLC consistency failed")
    if not bool(np.all(columns["volume"] >= 0)):
        raise SpineError("exploration volume must be nonnegative")

    expected = columns["expected_1m_components"]
    observed = columns["observed_1m_components"]
    coverage = columns["component_coverage_rate"]
    if not bool(np.all(expected == 5)):
        raise SpineError("expected_1m_components must equal five")
    if not bool(np.all((observed >= 0) & (observed <= expected))):
        raise SpineError("observed_1m_components is outside [0, expected]")
    if not bool(np.isfinite(coverage).all()):
        raise SpineError("component_coverage_rate must be finite")
    calculated = observed.astype(np.float64) / expected.astype(np.float64)
    if not np.array_equal(coverage, calculated):
        raise SpineError("component_coverage_rate differs from observed/expected")

    immutable = MappingProxyType(
        {name: _readonly(array) for name, array in columns.items()}
    )
    return ExplorationBars(build_id, tuple(symbols), immutable)


def open_exploration_bars() -> ExplorationBars:
    path = assert_exploration_safe(
        store_path(REPO_ROOT / "data", Corpus.EXPLORATION, "5m")
    )
    store = BarStore.open(path)
    store.verify_hashes()
    return validate_exploration_store(store)
