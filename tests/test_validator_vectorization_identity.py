"""D30 vectorization of the Phase 8 label validators is byte-identical.

``_session_labels``, ``_quarter_labels`` and ``support_masks`` each validated
every element of a ~157,000-row array in a Python loop, on every one of the
30,366 declared rows, re-checking data that never changed. D30 authorizes
replacing those loops with vectorized equivalents.

The acceptance gate is exact equivalence on BOTH paths:

* accept -- the returned labels or masks must be equal, and
* reject -- the raised ``SpineError`` must carry the identical message,
  including the offending row index. A vectorized check that reports a
  different index than the loop it replaced has changed behaviour even though
  it still fails closed.

Following the pattern D28 established, each pre-change implementation is
retained here verbatim as an independent executable oracle, and each
``test_negative_control_*`` proves the comparison can fail.
"""

from __future__ import annotations

from numbers import Real
from typing import Any, Hashable

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.phase8.contrasts import (
    SESSION_PHASES,
    VOLATILITY_STATES,
    CellKey,
    support_masks,
)
from mnq_lab.phase8.estimands import (
    _one_dimensional,
    _quarter_labels,
    _session_labels,
)


def _reference_session_labels(values: Any) -> tuple[Hashable, ...]:
    """Pre-D30 ``_session_labels``, retained verbatim as an oracle."""
    array = _one_dimensional(values, "session_ids")
    labels: list[Hashable] = []
    for row_index, raw_label in enumerate(np.asarray(array, dtype=object)):
        label = raw_label.item() if isinstance(raw_label, np.generic) else raw_label
        if isinstance(label, (bool, np.bool_)) or label is None:
            raise SpineError(
                f"session_ids contains an invalid label at index {row_index}"
            )
        if isinstance(label, Real):
            try:
                finite = np.isfinite(float(label))
            except (TypeError, ValueError, OverflowError):
                finite = False
            if not finite:
                raise SpineError(
                    f"session_ids contains a non-finite label at index {row_index}"
                )
        elif not isinstance(label, (str, bytes)):
            raise SpineError(
                "session_ids labels must be finite real numbers, strings, or bytes"
            )
        try:
            hash(label)
        except TypeError as exc:
            raise SpineError(
                f"session_ids contains an unhashable label at index {row_index}"
            ) from exc
        labels.append(label)
    return tuple(labels)


def _reference_quarter_labels(values: Any) -> tuple[str, ...]:
    """Pre-D30 ``_quarter_labels``, retained verbatim as an oracle."""
    array = _one_dimensional(values, "calendar_quarters")
    labels: list[str] = []
    for row_index, raw_label in enumerate(np.asarray(array, dtype=object)):
        label = raw_label.item() if isinstance(raw_label, np.generic) else raw_label
        if (
            not isinstance(label, str)
            or len(label) != 6
            or not label[:4].isdigit()
            or label[4] != "Q"
            or label[5] not in "1234"
        ):
            raise SpineError(
                f"calendar_quarters contains an invalid year-quarter at index {row_index}: "
                f"{label!r}"
            )
        labels.append(label)
    return tuple(labels)


def _reference_label_checks(phases: np.ndarray, states: np.ndarray) -> None:
    """Pre-D30 per-element membership loops from ``support_masks``."""
    for row_index, phase in enumerate(phases):
        if not isinstance(phase, (str, np.str_)) or phase not in SESSION_PHASES:
            raise SpineError(
                f"undeclared Phase 8 session phase at index {row_index}: {phase!r}"
            )
    for row_index, state in enumerate(states):
        if not isinstance(state, (str, np.str_)) or state not in VOLATILITY_STATES:
            raise SpineError(
                f"undeclared volatility state at index {row_index}: {state!r}"
            )


def _outcome(callable_, *args):
    """Return ``("ok", value)`` or ``("error", message)``."""
    try:
        return "ok", callable_(*args)
    except SpineError as exc:
        return "error", str(exc)


# --------------------------------------------------------------------------
# _session_labels
# --------------------------------------------------------------------------

SESSION_FIXTURES = [
    pytest.param(np.array([20200101, 20200101, 20200102], dtype=np.int64), id="int64"),
    pytest.param(np.array([5, 6], dtype=np.int32), id="int32"),
    pytest.param(np.array([5, 6], dtype=np.uint8), id="uint8"),
    pytest.param(np.array([-3, -3, 7], dtype=np.int64), id="negative-int64"),
    pytest.param((1, 2, 3), id="python-int-tuple"),
    pytest.param(("a", "b"), id="strings-fall-back"),
    pytest.param((1.5, 2.5), id="floats-fall-back"),
    pytest.param((b"x", b"y"), id="bytes-fall-back"),
    pytest.param(np.array([True, False]), id="bool-array-rejects"),
    pytest.param((None,), id="none-rejects"),
    pytest.param((np.nan,), id="nan-rejects"),
    pytest.param((np.inf,), id="inf-rejects"),
    pytest.param((1 + 0j,), id="complex-rejects"),
    pytest.param(np.array([[1, 2], [3, 4]]), id="two-dimensional-rejects"),
]


@pytest.mark.parametrize("values", SESSION_FIXTURES)
def test_session_labels_match_the_original(values):
    assert _outcome(_session_labels, values) == _outcome(
        _reference_session_labels, values
    )


# --------------------------------------------------------------------------
# _quarter_labels
# --------------------------------------------------------------------------

QUARTER_FIXTURES = [
    pytest.param(np.array(["2020Q1", "2020Q1", "2021Q4"]), id="valid-unicode"),
    pytest.param(("2020Q1", "2020Q3"), id="valid-tuple"),
    pytest.param(np.array(["2020Q1", "2020Q5"]), id="quarter-digit-out-of-range"),
    pytest.param(np.array(["2020Q1", "20X0Q1"]), id="non-digit-year"),
    pytest.param(np.array(["2020Q1", "2020X1"]), id="missing-Q"),
    pytest.param(np.array(["2020Q1", "2020Q"]), id="wrong-length"),
    pytest.param(np.array(["bad", "2020Q1", "worse"]), id="first-offender-index"),
    pytest.param(np.array(["2020Q1", "bad", "2020Q2", "worse"]), id="second-offender"),
    pytest.param((1, 2), id="ints-reject"),
]


@pytest.mark.parametrize("values", QUARTER_FIXTURES)
def test_quarter_labels_match_the_original(values):
    assert _outcome(_quarter_labels, values) == _outcome(
        _reference_quarter_labels, values
    )


def test_quarter_labels_report_the_first_offending_row_not_the_first_bad_value():
    """np.unique sorts, so the first bad VALUE is not the first bad ROW."""
    values = np.array(["2020Q1", "zzz", "2020Q2", "aaa"])
    production = _outcome(_quarter_labels, values)
    oracle = _outcome(_reference_quarter_labels, values)
    assert production == oracle
    assert "index 1" in production[1]


# --------------------------------------------------------------------------
# support_masks membership validation
# --------------------------------------------------------------------------

_TARGET = CellKey(phase="morning", volatility_state="mid")
_N = 600
_PHASES = np.array(["morning", "midday", "close", "open", "afternoon"] * (_N // 5))
_STATES = np.array((["low", "mid", "high"] * (_N // 3 + 1))[:_N])


def _masks_outcome(phases, states):
    return _outcome(support_masks, phases, states, _TARGET, "absolute_distribution")


def _reference_outcome(phases, states):
    def run(*_):
        _reference_label_checks(phases, states)
        return None

    return _outcome(run)


@pytest.mark.parametrize(
    ("phases", "states", "expect_error"),
    [
        pytest.param(_PHASES, _STATES, False, id="all-declared"),
        pytest.param(_PHASES.astype(object), _STATES, False, id="object-dtype"),
    ],
)
def test_support_masks_accepts_declared_labels(phases, states, expect_error):
    kind, _ = _masks_outcome(phases, states)
    assert (kind == "error") is expect_error


@pytest.mark.parametrize("bad_index", [0, 7, _N - 1])
def test_support_masks_phase_rejection_message_matches(bad_index):
    phases = _PHASES.copy()
    phases[bad_index] = "nonsense"
    production = _masks_outcome(phases, _STATES)
    oracle = _reference_outcome(phases, _STATES)
    assert production[0] == "error"
    assert production[1] == oracle[1]


@pytest.mark.parametrize("bad_index", [0, 11, _N - 1])
def test_support_masks_state_rejection_message_matches(bad_index):
    states = _STATES.copy()
    states[bad_index] = "zz"
    production = _masks_outcome(_PHASES, states)
    oracle = _reference_outcome(_PHASES, states)
    assert production[0] == "error"
    assert production[1] == oracle[1]


def test_support_masks_object_dtype_with_non_string_still_rejects():
    phases = _PHASES.astype(object)
    phases[3] = 42
    assert _masks_outcome(phases, _STATES)[0] == "error"


# --------------------------------------------------------------------------
# Negative controls. Each proves the comparisons above can fail.
# --------------------------------------------------------------------------


def test_negative_control_session_labels_detects_a_dropped_element():
    def mutant(values):
        return _reference_session_labels(values)[:-1]

    values = np.array([1, 2, 3], dtype=np.int64)
    assert _outcome(mutant, values) != _outcome(_reference_session_labels, values)


def test_negative_control_session_labels_detects_a_changed_value():
    def mutant(values):
        labels = list(_reference_session_labels(values))
        labels[0] = labels[0] + 1
        return tuple(labels)

    values = np.array([1, 2, 3], dtype=np.int64)
    assert _outcome(mutant, values) != _outcome(_reference_session_labels, values)


def test_negative_control_quarter_labels_detects_a_wrong_reported_index():
    """A vectorized check that reports the wrong row must be caught."""

    def mutant(values):
        raise SpineError(
            "calendar_quarters contains an invalid year-quarter at index 99: 'zzz'"
        )

    values = np.array(["2020Q1", "zzz"])
    assert _outcome(mutant, values) != _outcome(_reference_quarter_labels, values)


def test_negative_control_quarter_labels_detects_silent_acceptance():
    def mutant(values):
        return tuple(np.asarray(values).tolist())

    values = np.array(["2020Q1", "zzz"])
    assert _outcome(mutant, values) != _outcome(_reference_quarter_labels, values)


def test_negative_control_support_masks_detects_a_wrong_reported_index():
    phases = _PHASES.copy()
    phases[7] = "nonsense"

    def mutant(*_):
        raise SpineError(
            "undeclared Phase 8 session phase at index 0: np.str_('nonsense')"
        )

    assert _outcome(mutant) != _reference_outcome(phases, _STATES)
