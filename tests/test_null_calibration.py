"""Test 9 structure only; this file creates no calibration evidence.

These tests use fixed hand-written summaries and spend no one-shot entropy. A future
randomized-control run, any formal outcome count, and any corpus permutation would
spend one-shot preregistered entropy and must be separately authorized and protected
from ordinary collection. No such runner or generator is present in this file.
"""

from __future__ import annotations

import pytest

from mnq_lab.phase10.calibration import (
    NULL_EVENT_BAND,
    NULL_REPLICATIONS,
    EffectSummary,
    evaluate_calibration_summary,
)


def _effects():
    return (
        EffectSummary("weak", 300, 30, 0.20),
        EffectSummary("medium", 300, 29, 0.19),
        EffectSummary("strong", 300, 100, 0.60),
    )


def _assert_gate(null_events, effects):
    decision = evaluate_calibration_summary(null_events, effects)
    assert decision.accepted, decision.checks


def test_null_calibration_acceptance_plan_uses_preregistered_loose_criteria():
    assert NULL_REPLICATIONS == 300
    assert NULL_EVENT_BAND == (8, 23)
    _assert_gate(19, _effects())


def test_null_calibration_negative_band_failure_hits_the_positive_assertion():
    with pytest.raises(AssertionError):
        _assert_gate(24, _effects())


def test_null_calibration_negative_power_failure_hits_the_positive_assertion():
    flat = (
        EffectSummary("weak", 300, 40, 0.30),
        EffectSummary("medium", 300, 40, 0.30),
        EffectSummary("strong", 300, 40, 0.30),
    )
    with pytest.raises(AssertionError):
        _assert_gate(19, flat)
