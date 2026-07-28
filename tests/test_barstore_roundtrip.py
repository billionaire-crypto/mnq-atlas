"""BarStore: memory-mapped `.npy` column store round-trip (spec §5).

    "One `.npy` per column plus `manifest.json` with per-file sha256 ... Loads via
    `mmap_mode="r"`."

Prices must round-trip as **exact** ticks. A float round-trip that is merely close would
mean every measured excursion carries an unbounded rounding error.
"""

from __future__ import annotations

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.core.units import from_quanta, to_quanta
from mnq_lab.spine.store import BarStore, write_store

TICK = 0.25


def _columns(n=64):
    rng = np.random.default_rng(20260728)
    prices = 12_000.0 + rng.integers(-4000, 4000, size=n) * TICK
    return {
        "ts_event_ns": (np.arange(n, dtype=np.int64) * 300_000_000_000),
        "open_ticks": to_quanta(prices, TICK),
        "high_ticks": to_quanta(prices + TICK, TICK),
        "low_ticks": to_quanta(prices - TICK, TICK),
        "close_ticks": to_quanta(prices, TICK),
        "volume": rng.integers(0, 10_000, size=n).astype(np.int64),
        "symbol_code": np.zeros(n, dtype=np.int16),
        "session_id": np.full(n, 20210610, dtype=np.int32),
        "rollover": np.zeros(n, dtype=bool),
    }, prices


def _metadata():
    return {"build_id": "test", "symbols": ["MNQM1"], "tick_size": TICK}


def test_round_trip_preserves_every_column(tmp_path):
    columns, _ = _columns()
    write_store(tmp_path / "bars", columns, metadata=_metadata())
    store = BarStore.open(tmp_path / "bars")

    assert store.n_rows == len(columns["ts_event_ns"])
    assert set(store.column_names) == set(columns)
    for name, expected in columns.items():
        np.testing.assert_array_equal(np.asarray(store[name]), expected)
        assert np.asarray(store[name]).dtype == expected.dtype


def test_prices_round_trip_as_exact_ticks(tmp_path):
    columns, prices = _columns()
    write_store(tmp_path / "bars", columns, metadata=_metadata())
    store = BarStore.open(tmp_path / "bars")

    recovered = from_quanta(store["open_ticks"], TICK)
    # Exact equality, not approx: 0.25 is dyadic, so there is no excuse for drift.
    np.testing.assert_array_equal(recovered, prices)
    assert np.asarray(store["open_ticks"]).dtype == np.int32


def test_store_is_memory_mapped(tmp_path):
    columns, _ = _columns()
    write_store(tmp_path / "bars", columns, metadata=_metadata())
    store = BarStore.open(tmp_path / "bars")
    assert isinstance(store["open_ticks"], np.memmap), (
        "columns must load via mmap_mode='r' (spec §5), not be read into memory"
    )


def test_mapped_columns_are_read_only(tmp_path):
    columns, _ = _columns()
    write_store(tmp_path / "bars", columns, metadata=_metadata())
    store = BarStore.open(tmp_path / "bars")
    with pytest.raises(ValueError):
        store["open_ticks"][0] = 1


def test_symbol_decoding(tmp_path):
    columns, _ = _columns()
    columns["symbol_code"] = np.array([0, 1] * 32, dtype=np.int16)
    metadata = {**_metadata(), "symbols": ["MNQM1", "MNQU1"]}
    write_store(tmp_path / "bars", columns, metadata=metadata)
    store = BarStore.open(tmp_path / "bars")
    decoded = store.symbol_series()
    assert decoded[0] == "MNQM1"
    assert decoded[1] == "MNQU1"


def test_hash_verification_passes_on_an_untouched_store(tmp_path):
    columns, _ = _columns()
    write_store(tmp_path / "bars", columns, metadata=_metadata())
    BarStore.open(tmp_path / "bars").verify_hashes()


def test_negative_case_a_modified_column_is_detected(tmp_path):
    """Tamper with one byte; verification must fail."""
    columns, _ = _columns()
    write_store(tmp_path / "bars", columns, metadata=_metadata())
    target = tmp_path / "bars" / "volume.npy"
    payload = bytearray(target.read_bytes())
    payload[-1] ^= 0xFF
    target.write_bytes(bytes(payload))

    with pytest.raises(SpineError, match="sha256 mismatch"):
        BarStore.open(tmp_path / "bars").verify_hashes()


def test_negative_case_a_missing_column_file_is_detected(tmp_path):
    columns, _ = _columns()
    write_store(tmp_path / "bars", columns, metadata=_metadata())
    (tmp_path / "bars" / "volume.npy").unlink()
    with pytest.raises(SpineError, match="column file missing"):
        BarStore.open(tmp_path / "bars")


def test_negative_case_ragged_columns_are_refused(tmp_path):
    columns, _ = _columns()
    columns["volume"] = columns["volume"][:-1]
    with pytest.raises(SpineError, match="differing lengths"):
        write_store(tmp_path / "bars", columns, metadata=_metadata())


def test_negative_case_empty_store_is_refused(tmp_path):
    with pytest.raises(SpineError, match="no columns"):
        write_store(tmp_path / "bars", {}, metadata=_metadata())
    with pytest.raises(SpineError, match="empty store"):
        write_store(
            tmp_path / "bars2",
            {"ts_event_ns": np.array([], dtype=np.int64)},
            metadata=_metadata(),
        )


def test_negative_case_unknown_column_raises(tmp_path):
    columns, _ = _columns()
    write_store(tmp_path / "bars", columns, metadata=_metadata())
    store = BarStore.open(tmp_path / "bars")
    with pytest.raises(SpineError, match="not in this store"):
        store["pnl"]


def test_real_store_round_trip(exploration_5m):
    exploration_5m.verify_hashes()
    assert exploration_5m.n_rows > 0
    assert isinstance(exploration_5m["open_ticks"], np.memmap)
    assert np.asarray(exploration_5m["open_ticks"]).dtype == np.int32
    assert np.asarray(exploration_5m["ts_event_ns"]).dtype == np.int64

    tick = exploration_5m.manifest["tick_size"]
    prices = from_quanta(exploration_5m["open_ticks"], tick)
    # Round-tripping back through the quantiser must be a fixed point.
    np.testing.assert_array_equal(
        to_quanta(prices, tick), np.asarray(exploration_5m["open_ticks"])
    )


def test_real_store_timestamps_are_utc_nanoseconds(exploration_5m):
    """Spec §4: "Storage timestamps UTC nanoseconds."

    pandas 3.0's `to_datetime(..., utc=True)` yields microsecond resolution, so a build
    that let the unit be inferred would store values 1000x too small. Minute-aligned
    nanosecond timestamps are divisible by 60e9; microsecond ones would not be.
    """
    stamps = np.asarray(exploration_5m["ts_event_ns"])
    assert (stamps % 300_000_000_000 == 0).all(), (
        "5-minute bar timestamps are not aligned to 300e9 ns — the storage unit is "
        "probably microseconds, not nanoseconds"
    )
    assert stamps.min() > 1_500_000_000_000_000_000  # after 2017 in ns
