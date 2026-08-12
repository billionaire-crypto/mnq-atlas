"""Phase 10 corpus boundary and deferred-interface witnesses."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.constants import REPO_ROOT
from mnq_lab.phase10.adapter import _reshape_exact_sessions, load_formal_corpus
from mnq_lab.phase10.contract import (
    EFFECTIVE_NULL_STRATA,
    PERMUTATION_SESSIONS,
    RNG_ROOT_ENTROPY,
    artifact_metadata,
    load_phase10_contract,
)
from mnq_lab.phase10.interfaces import DEFERRED_NULLS, DeferredNullError


V2_ROOT = REPO_ROOT / "data/exploration/derived/phase7-unit-o-session-aware-v2"


def test_phase10_adapter_reconciles_the_frozen_formal_population():
    corpus = load_formal_corpus(V2_ROOT)
    assert corpus.session_ids.size == PERMUTATION_SESSIONS == 900
    assert corpus.state_codes.shape == (900, 78)
    assert corpus.outcome_valid.shape == corpus.state_codes.shape
    assert corpus.window_fits_rth.shape == corpus.state_codes.shape
    assert tuple(corpus.observation_grid[[0, -1]]) == ("08:30", "14:55")
    assert tuple(corpus.phase_grid[[0, -1]]) == ("open", "close")
    assert corpus.reconciliation.formal_rows == 70_200
    assert corpus.reconciliation.holiday_adjacent_sessions_removed == 70
    assert corpus.reconciliation.truncated_sessions_removed == 2
    assert corpus.metadata["effective_null_strata"] == EFFECTIVE_NULL_STRATA


def test_phase10_grid_negative_unequal_session_fails_the_same_shape_assertion():
    sessions = np.asarray([1, 1, 2], dtype=np.int32)
    values = np.asarray([10, 11, 20], dtype=np.int32)
    with pytest.raises(SpineError, match="unequal session length"):
        _reshape_exact_sessions(sessions, (values,))


def test_phase10_contract_consumes_only_the_frozen_seed():
    contract = load_phase10_contract()
    assert contract.rng_seed == 20260728
    assert RNG_ROOT_ENTROPY == (contract.rng_seed,)
    assert contract.weighting_planes == (
        "equal_phase_contrast",
        "natural_prevalence_contrast",
    )
    assert artifact_metadata()["rng_root_entropy"] == [20260728]


@pytest.mark.parametrize("interface", DEFERRED_NULLS)
def test_deferred_null_interfaces_cannot_emit_formal_results(interface):
    assert interface.formal is False
    assert interface.p_value_available is False
    with pytest.raises(DeferredNullError, match="descriptive only"):
        interface.execute()
