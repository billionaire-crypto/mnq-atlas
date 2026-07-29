"""Spec §13 test 2 — `test_event_time_conditioner`.

    "hand-built timestamps proving exactly which returns enter the state at τ;
    the anchor bar's own return IS included, its path IS not"

The rule under test (§4.1, verbatim): at observation time τ, a conditioner may use
every return whose ending timestamp ≤ τ and none ending after τ; an outcome may
use only the path strictly after τ. `shift()` is one possible implementation and
never the specification (§14) — so the masks are proven on *gapped, irregular*
timestamps where any positional implementation diverges from the event-time rule.

Every hand-built expectation below is written out bar by bar rather than computed,
so the test cannot inherit a bug from the code under test.
"""

from __future__ import annotations

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.core.causality import (
    conditioner_input_mask,
    interval_end_ns,
    outcome_interval_mask,
    required_interval_starts,
)

from tests.conftest import ct_ns

DAY = "2021-06-15"
BAR_NS = 5 * 60 * 1_000_000_000
MINUTE_NS = 60 * 1_000_000_000


def labels(*times: str) -> np.ndarray:
    return np.asarray([ct_ns(f"{DAY} {t}") for t in times], dtype=np.int64)


# τ = 10:00 CT: the close of the bar labeled 09:55 is observed at 10:00.
TAU = ct_ns(f"{DAY} 10:00")


def test_exactly_which_returns_enter_the_state_at_tau():
    """Bar by bar: returns ending 09:45..10:00 are in; 10:05 onward are out."""
    bar_labels = labels("09:40", "09:45", "09:50", "09:55", "10:00", "10:05")
    return_ends = interval_end_ns(bar_labels, BAR_NS)  # each return ends label+5m

    mask = conditioner_input_mask(return_ends, TAU)
    #                 label:  09:40  09:45  09:50  09:55  10:00  10:05
    #                  ends:  09:45  09:50  09:55  10:00  10:05  10:10
    assert mask.tolist() == [True,  True,  True,  True,  False, False]

    # The anchor bar's own return — ending exactly at τ — IS included (§4.1:
    # "it ends exactly at τ and is the freshest information available").
    anchor_position = 3  # the 09:55-labeled bar
    assert return_ends[anchor_position] == TAU
    assert mask[anchor_position]

    # Nothing ending after τ enters, even by one nanosecond.
    assert not conditioner_input_mask(np.asarray([TAU + 1], dtype=np.int64), TAU)[0]
    assert conditioner_input_mask(np.asarray([TAU - 1], dtype=np.int64), TAU)[0]


def test_the_anchor_bars_path_is_not_in_the_outcome():
    """The outcome window [τ, τ+15m) contains the 10:00, 10:05, 10:10 bars and
    NOT the anchor bar — its high/low is realized by τ (§4.1's second rule)."""
    bar_labels = labels("09:55", "10:00", "10:05", "10:10", "10:15")
    mask = outcome_interval_mask(bar_labels, TAU, 15 * MINUTE_NS, BAR_NS)
    #                 label:  09:55  10:00  10:05  10:10  10:15
    assert mask.tolist() == [False, True,  True,  True,  False]

    anchor_label = ct_ns(f"{DAY} 09:55")
    assert not mask[0] and bar_labels[0] == anchor_label

    # The two §4.1 consequences are DIFFERENT rules on the SAME bar: the anchor's
    # return is conditioner input, its interval is not outcome path.
    anchor_return_end = interval_end_ns(np.asarray([anchor_label], dtype=np.int64), BAR_NS)
    assert conditioner_input_mask(anchor_return_end, TAU)[0]


def test_event_time_not_position_on_a_gapped_series():
    """Drop the 09:50 bar. A positional (shift-style) implementation slides a
    different bar into the window; the event-time rule keeps every remaining
    bar's classification identical."""
    full = labels("09:40", "09:45", "09:50", "09:55", "10:00", "10:05")
    gapped = labels("09:40", "09:45", "09:55", "10:00", "10:05")

    full_in = set(full[conditioner_input_mask(interval_end_ns(full, BAR_NS), TAU)].tolist())
    gapped_in = set(
        gapped[conditioner_input_mask(interval_end_ns(gapped, BAR_NS), TAU)].tolist()
    )
    assert gapped_in == full_in - {ct_ns(f"{DAY} 09:50")}

    full_out = set(full[outcome_interval_mask(full, TAU, 15 * MINUTE_NS, BAR_NS)].tolist())
    gapped_out = set(
        gapped[outcome_interval_mask(gapped, TAU, 15 * MINUTE_NS, BAR_NS)].tolist()
    )
    assert gapped_out == full_out  # the gap precedes τ; the outcome window is untouched


def test_negative_a_strict_inequality_conditioner_is_detectably_wrong():
    """The single strongest wrong implementation: `end < τ` instead of `end ≤ τ`.

    It differs from the correct mask in exactly one place — the anchor bar's own
    return — which is precisely the §4.1 consequence this suite must pin. If the
    two masks ever agree, this test has lost its discriminating power and fails.
    """
    bar_labels = labels("09:40", "09:45", "09:50", "09:55", "10:00")
    ends = interval_end_ns(bar_labels, BAR_NS)
    correct = conditioner_input_mask(ends, TAU)
    strict = ends < TAU  # the wrong reading
    differs = correct != strict
    assert differs.sum() == 1
    assert bar_labels[differs][0] == ct_ns(f"{DAY} 09:55")  # the anchor bar


def test_negative_a_label_keyed_conditioner_is_detectably_wrong():
    """Keying on the bar LABEL (≤ τ) instead of the return's END admits the bar
    labeled 10:00, whose return ends 10:05 — information from after τ."""
    bar_labels = labels("09:55", "10:00")
    ends = interval_end_ns(bar_labels, BAR_NS)
    correct = conditioner_input_mask(ends, TAU)
    label_keyed = bar_labels <= TAU  # the wrong reading
    assert correct.tolist() == [True, False]
    assert label_keyed.tolist() == [True, True]
    leaked = bar_labels[label_keyed & ~correct]
    assert leaked.tolist() == [ct_ns(f"{DAY} 10:00")]


def test_negative_an_outcome_window_including_the_anchor_is_detectably_wrong():
    """An outcome mask keyed `start ≥ τ − 5m` (off by one bar) admits the anchor
    bar's own high/low — measuring known movement as if it were future."""
    bar_labels = labels("09:55", "10:00", "10:05", "10:10")
    correct = outcome_interval_mask(bar_labels, TAU, 15 * MINUTE_NS, BAR_NS)
    off_by_one = (bar_labels >= TAU - BAR_NS) & (bar_labels < TAU + 15 * MINUTE_NS)
    assert (correct != off_by_one).sum() == 1
    assert bar_labels[correct != off_by_one][0] == ct_ns(f"{DAY} 09:55")


def test_negative_malformed_inputs_fail_closed():
    good = labels("09:55")
    with pytest.raises(SpineError, match="int64"):
        conditioner_input_mask(good.astype("datetime64[ns]"), TAU)
    with pytest.raises(SpineError, match="int64"):
        outcome_interval_mask(good.astype(np.float64), TAU, 15 * MINUTE_NS, BAR_NS)
    with pytest.raises(SpineError, match="positive"):
        outcome_interval_mask(good, TAU, -15 * MINUTE_NS, BAR_NS)


def test_negative_scalar_unit_bearing_inputs_fail_closed():
    """Audit finding M-1 (2026-07-28): arrays were validated but SCALARS were
    converted with a bare `np.int64(...)`, so a `datetime64[us]` τ silently became
    its microsecond count — a value 1000× too small, with no error anywhere.

    The concrete leak, before the fix:
        required_interval_starts(np.datetime64('2021-06-15T15:00','us'), ...)
        -> 1623769200000000   (want 1623769200000000000)
    """
    good = labels("09:55")
    micro_tau = np.datetime64("2021-06-15T15:00", "us")

    with pytest.raises(SpineError, match="datetime64"):
        required_interval_starts(micro_tau, 15 * MINUTE_NS, BAR_NS)
    with pytest.raises(SpineError, match="datetime64"):
        conditioner_input_mask(good, micro_tau)
    with pytest.raises(SpineError, match="datetime64"):
        outcome_interval_mask(good, micro_tau, 15 * MINUTE_NS, BAR_NS)
    with pytest.raises(SpineError, match="datetime64|timedelta64"):
        outcome_interval_mask(good, TAU, np.timedelta64(15, "m"), BAR_NS)
    # Floats lose nanosecond precision and are refused rather than truncated.
    with pytest.raises(SpineError, match="integer"):
        conditioner_input_mask(good, float(TAU))
    with pytest.raises(SpineError, match="integer"):
        interval_end_ns(good, 300.0)

    # The correct scalar forms still work, so the guard is not blanket-failing.
    assert conditioner_input_mask(good, TAU)[0]
    assert int(required_interval_starts(TAU, 15 * MINUTE_NS, BAR_NS)[0]) == TAU


def test_negative_unsigned_overflow_scalars_fail_closed():
    """Round-2 audit finding M-3 (2026-07-28): `np.int64(np.uint64(2**63))` WRAPS
    to the negative extreme instead of raising, so an oversized unsigned scalar
    sailed through the round-1 guard and produced nonsensical comparisons.

    The concrete leak, before the fix:
        required_interval_starts(np.uint64(2**63), 5, 1)
        -> array([-9223372036854775808, ...])
    """
    good = labels("09:55")
    overflow = np.uint64(2**63)

    with pytest.raises(SpineError, match="does not fit in int64"):
        required_interval_starts(overflow, 15 * MINUTE_NS, BAR_NS)
    with pytest.raises(SpineError, match="does not fit in int64"):
        conditioner_input_mask(good, overflow)
    with pytest.raises(SpineError, match="does not fit in int64"):
        outcome_interval_mask(good, overflow, 15 * MINUTE_NS, BAR_NS)
    with pytest.raises(SpineError, match="does not fit in int64"):
        outcome_interval_mask(good, TAU, np.uint64(2**63), BAR_NS)
    with pytest.raises(SpineError, match="does not fit in int64"):
        interval_end_ns(good, 2**64)  # oversized Python int, same wrap risk

    # Representable unsigned and numpy scalars still work: the guard rejects the
    # unrepresentable range, not the unsigned type.
    assert conditioner_input_mask(good, np.uint64(TAU))[0]
    assert conditioner_input_mask(good, np.int64(TAU))[0]
