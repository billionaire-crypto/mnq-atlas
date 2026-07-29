"""Event-time causality windows (spec §4.1) — market-free.

`core/` knows nothing about markets (spec §16.3): no session, contract, RTH, or
phase concept appears in this module. Everything is integer UTC nanoseconds; the
interval length and the horizon arrive as parameters. The spine and outcomes
layers translate market wall-clock rules into these primitives.

The rule this module implements (spec §4.1, verbatim):

    At observation time τ, a conditioner may use every return whose ending
    timestamp ≤ τ and none ending after τ. An outcome may use only the path
    strictly after τ.

Two consequences that are *different rules and must not be conflated* (§4.1):

- an interval ending exactly at τ is **inside** the conditioner window — in market
  terms, the anchor bar's own return enters the state;
- an interval starting at or after τ is the outcome path; the interval ending at τ
  (which *starts* before τ) is **excluded** from it — the anchor bar's own
  high/low never enters its own future excursion. The path of the interval that
  starts exactly at τ lies strictly after τ, so it is included.

`shift()` is one possible implementation of the rule; **it is never the
specification** (§14 struck `shift(1)`-as-spec). These functions implement the
rule directly on interval-end and interval-start timestamps, so they remain
correct on irregular grids, across gaps, and across daylight-saving transitions
(a UTC nanosecond does not observe DST).
"""

from __future__ import annotations

import numpy as np

from mnq_lab import SpineError

__all__ = [
    "interval_end_ns",
    "conditioner_input_mask",
    "outcome_interval_mask",
    "required_interval_starts",
    "interval_presence",
]

_INT64_MIN = np.iinfo(np.int64).min
_INT64_MAX = np.iinfo(np.int64).max


def _as_int64(values: np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(values)
    if array.dtype != np.int64:
        raise SpineError(
            f"{name} must be int64 UTC nanoseconds, got dtype {array.dtype}. "
            "pandas 3.0 silently produces datetime64[us]; convert with "
            '.to_numpy(dtype="datetime64[ns]").view("int64") upstream.'
        )
    return array


def _as_scalar_int64(value: int, name: str) -> np.int64:
    """Validate a SCALAR nanosecond quantity.

    Audit finding M-1 (2026-07-28): array inputs were validated but scalars were
    converted with a bare ``np.int64(...)``, so a ``datetime64[us]`` scalar was
    silently reinterpreted as *nanoseconds* — a value 1000× too small, with no
    error. Unit-bearing types are rejected outright rather than converted,
    because converting one silently is exactly how an off-by-1000 reaches a
    result nothing downstream can detect.
    """
    if isinstance(value, (np.datetime64, np.timedelta64)):
        raise SpineError(
            f"{name} must be a plain integer count of UTC nanoseconds, got "
            f"{type(value).__name__} ({value!r}). A datetime64/timedelta64 scalar "
            "carries its own unit and would be reinterpreted as nanoseconds; "
            'convert explicitly with .astype("datetime64[ns]").view("int64").'
        )
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise SpineError(
            f"{name} must be an integer count of UTC nanoseconds, got "
            f"{type(value).__name__} ({value!r}); floats lose nanosecond precision"
        )
    # Round-2 audit finding M-3 (2026-07-28): np.int64(np.uint64(2**63)) WRAPS to
    # the negative extreme instead of raising, so an unsigned scalar above the
    # signed range produced nonsensical comparisons rather than a SpineError.
    # Convert through Python int (exact for every np.integer) and range-check.
    as_int = int(value)
    if not (_INT64_MIN <= as_int <= _INT64_MAX):
        raise SpineError(
            f"{name} = {as_int} does not fit in int64 nanoseconds; an unsigned or "
            "oversized scalar would silently wrap (round-2 audit M-3)"
        )
    return np.int64(as_int)


def _validate_window(horizon_ns: int, interval_ns: int) -> None:
    horizon_ns = int(_as_scalar_int64(horizon_ns, "horizon_ns"))
    interval_ns = int(_as_scalar_int64(interval_ns, "interval_ns"))
    if interval_ns <= 0:
        raise SpineError(f"interval_ns must be positive, got {interval_ns}")
    if horizon_ns <= 0:
        raise SpineError(f"horizon_ns must be positive, got {horizon_ns}")
    if horizon_ns % interval_ns != 0:
        raise SpineError(
            f"horizon_ns={horizon_ns} is not a whole number of intervals of "
            f"interval_ns={interval_ns}; a partial trailing interval would make "
            "the window boundary ambiguous"
        )


def interval_end_ns(interval_start_ns: np.ndarray, interval_ns: int) -> np.ndarray:
    """End timestamp of each interval: label + length.

    The label is the interval OPEN (spec §4, finding E); the interval is
    ``[t, t + interval_ns)``. The end timestamp is the observation time of
    everything realized inside the interval.
    """
    starts = _as_int64(interval_start_ns, "interval_start_ns")
    length = _as_scalar_int64(interval_ns, "interval_ns")
    if length <= 0:
        raise SpineError(f"interval_ns must be positive, got {interval_ns}")
    return starts + length


def conditioner_input_mask(end_ns: np.ndarray, tau_ns: int) -> np.ndarray:
    """True where a quantity whose realization ends at ``end_ns`` is usable at τ.

    Inclusive at the boundary: an interval ending exactly at τ is realized *by* τ
    and is the freshest information available (spec §4.1). Everything ending
    after τ — even by one nanosecond — is excluded.
    """
    ends = _as_int64(end_ns, "end_ns")
    return ends <= _as_scalar_int64(tau_ns, "tau_ns")


def outcome_interval_mask(
    interval_start_ns: np.ndarray, tau_ns: int, horizon_ns: int, interval_ns: int
) -> np.ndarray:
    """True for intervals belonging to the outcome window ``[τ, τ + horizon)``.

    An interval starting exactly at τ covers path strictly after τ, so it is
    included. The interval *ending* at τ starts before τ and is excluded — its
    extremes are realized history, not outcome (spec §4.1).
    """
    starts = _as_int64(interval_start_ns, "interval_start_ns")
    _validate_window(horizon_ns, interval_ns)
    tau = _as_scalar_int64(tau_ns, "tau_ns")
    return (starts >= tau) & (starts < tau + np.int64(horizon_ns))


def required_interval_starts(tau_ns: int, horizon_ns: int, interval_ns: int) -> np.ndarray:
    """The complete label grid of the outcome window ``[τ, τ + horizon)``.

    For the §4.1 worked example (τ = 08:35 CT, Δ = 15 min, 5-min intervals) this
    is exactly the labels 08:35, 08:40, 08:45 — ``horizon/interval`` labels, the
    last one starting at ``τ + horizon − interval``.
    """
    _validate_window(horizon_ns, interval_ns)
    tau = _as_scalar_int64(tau_ns, "tau_ns")
    return np.arange(tau, tau + np.int64(horizon_ns), np.int64(interval_ns))


def interval_presence(
    present_start_ns: np.ndarray, required_start_ns: np.ndarray
) -> np.ndarray:
    """Boolean mask over ``required_start_ns``: which required labels exist.

    Presence accounting only — no fill, no bridge, no tolerance. A required label
    is either present exactly or absent (spec §7.1: "exact fixed timestamp or
    dropping the anchor"; §14 struck tolerance windows).
    """
    present = _as_int64(present_start_ns, "present_start_ns")
    required = _as_int64(required_start_ns, "required_start_ns")
    return np.isin(required, present)
