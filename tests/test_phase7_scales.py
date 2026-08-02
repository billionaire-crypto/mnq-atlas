"""Mathematical witnesses and fail-closed tests for Phase 7 bar scales."""

from __future__ import annotations

import math
from types import MappingProxyType

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.conditioners.scales.ewma import (
    EWMA_HALFLIVES,
    EWMA_WARMUP_RETURNS,
    ewma_alpha,
    ewma_rms,
)
from mnq_lab.conditioners.scales.mad import MAD_FACTOR, rolling_mad
from mnq_lab.conditioners.scales.returns import ReturnSeries
from mnq_lab.conditioners.status import (
    AnchorStatus,
    ConditionerStatuses,
    EwmaStatus,
    MadStatus,
    ResetReason,
    ReturnMissingReason,
    ReturnStatus,
)


def _missing() -> ConditionerStatuses:
    return ConditionerStatuses(
        anchor_status=AnchorStatus.OK,
        return_status=ReturnStatus.MISSING_RETURN,
        return_missing_reason=ReturnMissingReason.SPACING_BREAK,
        reset_reason=ResetReason.GAP_RESET,
        scheduled_break=False,
    )


def _ok() -> ConditionerStatuses:
    return ConditionerStatuses(
        anchor_status=AnchorStatus.OK,
        return_status=ReturnStatus.OK,
        return_missing_reason=None,
        reset_reason=ResetReason.NONE,
        scheduled_break=False,
    )


def _returns_from_values(values: np.ndarray) -> ReturnSeries:
    supplied = np.asarray(values, dtype=np.float64)
    stored = np.concatenate((np.asarray([0.0]), supplied)).astype(np.float64)
    valid = np.concatenate((np.asarray([False]), np.ones(supplied.size, dtype=np.bool_)))
    starts = np.zeros(stored.size, dtype=np.int64)
    return ReturnSeries(
        values=stored,
        valid=valid,
        segment_start=starts,
        statuses=(_missing(),) + (_ok(),) * supplied.size,
        metadata=MappingProxyType({"test_fixture": "contract_values"}),
    )


def test_alpha_is_the_stable_frozen_halflife_conversion():
    for halflife in EWMA_HALFLIVES:
        alpha = ewma_alpha(halflife)
        expected = -np.expm1(np.log(np.float64(0.5)) / np.float64(halflife))
        assert alpha == expected
        assert np.float64(1.0) - alpha == np.float64(0.5) ** (
            np.float64(1.0) / np.float64(halflife)
        )

    for bad in (0, 40, 78.0, True, "78"):
        with pytest.raises(SpineError):
            ewma_alpha(bad)


def test_bias_adjusted_ewma_matches_independent_closed_form_and_kills_seed_mutant():
    raw = np.concatenate((np.asarray([1.0]), np.full(77, 0.1))).astype(np.float64)
    output = ewma_rms(_returns_from_values(raw), 78)
    anchor = 78
    decay = float(np.float64(1.0) - ewma_alpha(78))
    numerator = math.fsum(
        float(raw[index] * raw[index]) * decay ** (77 - index)
        for index in range(78)
    )
    denominator = math.fsum(decay**power for power in range(78))
    expected = math.sqrt(numerator / denominator)
    assert math.isclose(float(output.values[anchor]), expected, rel_tol=2e-15)
    assert output.statuses[anchor] is EwmaStatus.OK

    seeded_variance = 1.0
    alpha = float(ewma_alpha(78))
    for value in raw[1:]:
        seeded_variance = decay * seeded_variance + alpha * float(value * value)
    seeded_mutant = math.sqrt(seeded_variance)
    assert not math.isclose(float(output.values[anchor]), seeded_mutant, rel_tol=1e-3)


def test_all_halflives_use_one_fixed_78_return_warmup():
    returns = _returns_from_values(np.linspace(0.01, 0.78, 78, dtype=np.float64))
    for halflife in EWMA_HALFLIVES:
        output = ewma_rms(returns, halflife)
        assert not bool(np.any(output.valid[:78]))
        assert output.statuses[77] is EwmaStatus.WARMUP
        assert output.valid[78]
        assert output.contiguous_return_count[78] == EWMA_WARMUP_RETURNS
        assert output.metadata["warmup_returns"] == 78

    # The forbidden h-proportional mutation would emit h=39 here.
    assert not ewma_rms(returns, 39).valid[39]


def test_daily_reset_effective_history_matches_the_preregistered_disclosure():
    expected = {
        39: (42.57, 54.68, 56.34, 56.77, 99.2),
        78: (56.52, 91.39, 103.22, 113.03, 91.3),
        156: (66.07, 126.85, 159.09, 225.56, 70.5),
    }
    for halflife, disclosed in expected.items():
        decay = float(np.float64(1.0) - ewma_alpha(halflife))
        den78 = (1.0 - decay**78) / (1.0 - decay)
        den186 = (1.0 - decay**186) / (1.0 - decay)
        den275 = (1.0 - decay**275) / (1.0 - decay)
        steady = 1.0 / (1.0 - decay)
        calculated = (
            round(den78, 2),
            round(den186, 2),
            round(den275, 2),
            round(steady, 2),
            round(100.0 * den275 / steady, 1),
        )
        assert calculated == disclosed

    # A no-reset, steady-state claim is false for the h=156 arm.
    assert expected[156][-1] < 100.0


def test_ewma_zero_is_defined_and_canonical_positive_zero():
    output = ewma_rms(_returns_from_values(np.zeros(78, dtype=np.float64)), 78)
    assert output.valid[-1]
    assert output.values[-1] == 0.0
    assert not np.signbit(output.values[-1])


def test_mad_uses_lower_median_for_center_and_deviations():
    raw = np.arange(78, dtype=np.float64)
    output = rolling_mad(_returns_from_values(raw))
    center = float(np.sort(raw)[38])
    deviations = np.abs(raw - center)
    unscaled = float(np.sort(deviations)[38])
    expected = float(np.float64(MAD_FACTOR * np.float64(unscaled)))
    assert output.valid[-1]
    assert output.values[-1] == expected
    assert output.statuses[-1] is MadStatus.OK

    averaged_center = float(np.median(raw))
    assert averaged_center == 38.5
    assert averaged_center != center


def test_mad_warmup_and_zero_scale_are_distinct_undefined_statuses():
    warmup = rolling_mad(_returns_from_values(np.ones(77, dtype=np.float64)))
    assert warmup.statuses[-1] is MadStatus.WARMUP
    assert not warmup.valid[-1]
    zero = rolling_mad(_returns_from_values(np.ones(78, dtype=np.float64)))
    assert zero.statuses[-1] is MadStatus.ZERO_SCALE
    assert not zero.valid[-1]
    assert zero.values[-1] == 0.0


def test_scale_outputs_are_immutable_and_reject_wrong_input_type():
    returns = _returns_from_values(np.linspace(0.01, 0.78, 78, dtype=np.float64))
    ewma = ewma_rms(returns, 78)
    mad = rolling_mad(returns)
    with pytest.raises(ValueError):
        ewma.values[-1] = 0.0
    with pytest.raises(ValueError):
        mad.valid[-1] = False
    with pytest.raises(SpineError):
        ewma_rms(np.asarray([1.0]), 78)
    with pytest.raises(SpineError):
        rolling_mad(np.asarray([1.0]))
