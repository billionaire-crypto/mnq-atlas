"""Exact quantized-value conversion.

Spec §4: "Tick size 0.25 index points (prices stored int32 ticks)."

This module is market-free (§16.3): it converts between a real-valued quantity and an
integer count of a quantum supplied by the caller. It knows nothing about prices,
contracts, or exchanges.

Exactness is the point. A price that is not an exact multiple of the quantum is a
fail-closed condition, not something to round (§16.4.3).
"""

from __future__ import annotations

import numpy as np

from mnq_lab import SpineError

__all__ = ["to_quanta", "from_quanta", "INT32_MIN", "INT32_MAX"]

INT32_MIN = np.iinfo(np.int32).min
INT32_MAX = np.iinfo(np.int32).max


def to_quanta(
    values: np.ndarray, quantum: float, *, name: str = "value"
) -> np.ndarray:
    """Convert real values to an exact int32 count of `quantum`.

    Raises SpineError if any value is not an exact multiple of `quantum`, is
    non-finite, or falls outside int32. No rounding, no tolerance.

    For quantum = 0.25 the scaling is exact in binary floating point: 0.25 is a dyadic
    rational, so `value / 0.25` is exact for every representable price in range, and
    the integrality check below is a true test rather than a near-check.
    """
    if not np.isfinite(quantum) or quantum <= 0:
        raise SpineError(f"quantum must be finite and positive, got {quantum!r}")

    array = np.asarray(values, dtype=np.float64)
    if array.size and not np.isfinite(array).all():
        bad = int(np.flatnonzero(~np.isfinite(array))[0])
        raise SpineError(f"{name} contains non-finite value at index {bad}")

    scaled = array / quantum
    rounded = np.rint(scaled)
    inexact = scaled != rounded
    if inexact.any():
        index = int(np.flatnonzero(inexact)[0])
        raise SpineError(
            f"{name} at index {index} is {array[index]!r}, which is not an exact "
            f"multiple of {quantum} ({scaled[index]!r} quanta). Prices must round-trip "
            "exactly; rounding here would silently alter measured data (spec §4)."
        )

    if rounded.size:
        low, high = float(rounded.min()), float(rounded.max())
        if low < INT32_MIN or high > INT32_MAX:
            raise SpineError(
                f"{name} spans [{low}, {high}] quanta, outside int32 (spec §4 "
                "requires int32 tick storage)"
            )
    return rounded.astype(np.int32)


def from_quanta(quanta: np.ndarray, quantum: float) -> np.ndarray:
    """Convert an integer count of `quantum` back to real values."""
    if not np.isfinite(quantum) or quantum <= 0:
        raise SpineError(f"quantum must be finite and positive, got {quantum!r}")
    return np.asarray(quanta, dtype=np.int64).astype(np.float64) * quantum
