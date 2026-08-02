"""Independent semantic-mask fixtures frozen before Phase 7 estimators."""

from __future__ import annotations

import numpy as np
import pytest

from tests.phase7_contract_oracles import (
    composite_row_mask,
    ewma_semantic_mask,
    mad_semantic_mask,
)


def test_ewma_mask_is_the_whole_segment_and_halflife_independent():
    expected = ewma_semantic_mask(size=130, segment_start=10, anchor=120)
    declarations = {halflife: expected.copy() for halflife in (39, 78, 156)}
    assert expected.sum() == 111
    assert expected[10] and expected[120]
    assert not expected[9] and not expected[121]
    assert np.array_equal(declarations[39], declarations[78])
    assert np.array_equal(declarations[78], declarations[156])

    widened_leading = expected.copy()
    widened_leading[9] = True
    widened_trailing = expected.copy()
    widened_trailing[121] = True
    narrowed = expected.copy()
    narrowed[10] = False
    assert not np.array_equal(widened_leading, expected)
    assert not np.array_equal(widened_trailing, expected)
    assert not np.array_equal(narrowed, expected)


def test_mad_mask_is_exactly_79_bars_not_the_whole_long_segment():
    ewma = ewma_semantic_mask(size=130, segment_start=10, anchor=120)
    mad = mad_semantic_mask(size=130, segment_start=10, anchor=120)
    assert mad.sum() == 79
    assert mad[42] and mad[120]
    assert not mad[41]
    assert ewma[41]

    narrowed_to_78 = mad.copy()
    narrowed_to_78[42] = False
    widened_to_segment = ewma.copy()
    assert not np.array_equal(narrowed_to_78, mad)
    assert not np.array_equal(widened_to_segment, mad)


def test_anchor_minus_79_cross_check_discriminates_ewma_from_mad():
    anchor = 120
    probe = anchor - 79
    ewma = ewma_semantic_mask(size=130, segment_start=10, anchor=anchor)
    mad = mad_semantic_mask(size=130, segment_start=10, anchor=anchor)
    assert ewma[probe]
    assert not mad[probe]

    baseline = np.arange(130, dtype=np.int64)
    changed = baseline.copy()
    changed[probe] = -999
    assert not np.array_equal(baseline[ewma], changed[ewma])
    assert np.array_equal(baseline[mad], changed[mad])


def test_composite_masks_use_exact_independently_named_rows():
    expected = composite_row_mask(20, (1, 5, 9, 13))
    assert np.flatnonzero(expected).tolist() == [1, 5, 9, 13]

    current_session_mutant = expected.copy()
    current_session_mutant[17] = True
    different_bucket_mutant = expected.copy()
    different_bucket_mutant[6] = True
    narrowed = expected.copy()
    narrowed[5] = False
    assert not np.array_equal(current_session_mutant, expected)
    assert not np.array_equal(different_bucket_mutant, expected)
    assert not np.array_equal(narrowed, expected)


@pytest.mark.parametrize(
    ("constructor", "args"),
    [
        (ewma_semantic_mask, (10, 5, 4)),
        (ewma_semantic_mask, (10, 0, 10)),
        (mad_semantic_mask, (100, 30, 90)),
        (composite_row_mask, (10, ())),
        (composite_row_mask, (10, (1, 1))),
        (composite_row_mask, (10, (1, 10))),
    ],
)
def test_semantic_mask_oracles_fail_closed_on_vacuous_support(constructor, args):
    with pytest.raises(ValueError):
        constructor(*args)
