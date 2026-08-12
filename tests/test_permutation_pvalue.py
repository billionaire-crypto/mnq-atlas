"""Test 11: exact plus-one p-value and mutation witnesses."""

from __future__ import annotations

import pytest

from mnq_lab.phase10.pvalue import permutation_pvalue


OBSERVED = 3.0
NULL = [1.0, 3.0, 4.0, 2.0]
EXPECTED = 3.0 / 5.0


def _assert_exact(function):
    assert function(OBSERVED, NULL) == EXPECTED


def test_permutation_pvalue_is_exact_plus_one_with_ties():
    _assert_exact(permutation_pvalue)


def test_pvalue_negative_missing_plus_one_fails_the_positive_assertion():
    def mutant(observed, values):
        return sum(value >= observed for value in values) / len(values)

    with pytest.raises(AssertionError):
        _assert_exact(mutant)


def test_pvalue_negative_strict_tie_rule_fails_the_positive_assertion():
    def mutant(observed, values):
        return (1 + sum(value > observed for value in values)) / (len(values) + 1)

    with pytest.raises(AssertionError):
        _assert_exact(mutant)
