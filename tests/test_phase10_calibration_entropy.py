"""Slice 1 witnesses for calibration entropy and unchanged deployment mappings.

All fixtures are synthetic. This file creates no randomized corpus control, p-value,
rejection event, calibration evidence, or acceptance record.
"""

from __future__ import annotations

import hashlib
import inspect
import struct

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.phase10.calibration_entropy import (
    CALIBRATION_ROOT_BYTE_ORDER,
    CALIBRATION_ROOT_ENCODING,
    CALIBRATION_ROOT_ENTROPY,
    CALIBRATION_ROOT_LABEL,
    CALIBRATION_ROOT_SHA256,
    calibration_root_seed_sequence,
)
from mnq_lab.phase10.contract import RNG_ROOT_ENTROPY
from mnq_lab.phase10.mapping import (
    SessionMapping,
    generate_session_mapping,
    spawn_session_mappings,
    spawn_session_mappings_from_seed_sequence,
)


def _fixture() -> tuple[np.ndarray, np.ndarray]:
    sessions = np.arange(40, dtype=np.int32) + 20200101
    strata = np.asarray(("2020Q1",) * 20 + ("2020Q2",) * 20)
    return sessions, strata


def _legacy_deployment_spawn(
    sessions: np.ndarray,
    strata: np.ndarray,
    replications: int,
) -> tuple[SessionMapping, ...]:
    """Executable oracle copied from deployment before Slice 1."""
    children = np.random.SeedSequence(RNG_ROOT_ENTROPY).spawn(replications)
    return tuple(
        generate_session_mapping(
            sessions,
            strata,
            np.random.Generator(np.random.PCG64(child)),
        )
        for child in children
    )


def _mapping_equal(left: SessionMapping, right: SessionMapping) -> bool:
    for name in (
        "recipient_session_ids",
        "donor_session_ids",
        "donor_positions",
        "strata",
        "usable",
    ):
        observed = getattr(left, name)
        expected = getattr(right, name)
        try:
            identical = np.array_equal(observed, expected, equal_nan=True)
        except TypeError:
            identical = np.array_equal(observed, expected)
        if not bool(identical):
            return False
    return True


def _assert_deployment_bit_identity(spawn_function) -> None:
    sessions, strata = _fixture()
    expected = _legacy_deployment_spawn(sessions, strata, replications=199)
    actual = spawn_function(sessions, strata, 199)
    assert len(actual) == len(expected)
    assert all(
        _mapping_equal(observed, legacy)
        for observed, legacy in zip(actual, expected, strict=True)
    )


def _assert_calibration_root_contract(label: str) -> None:
    digest = hashlib.sha256(label.encode("UTF-8")).digest()
    assert CALIBRATION_ROOT_ENCODING == "UTF-8"
    assert CALIBRATION_ROOT_BYTE_ORDER == "big-endian"
    assert digest.hex() == CALIBRATION_ROOT_SHA256
    assert struct.unpack(">8I", digest) == CALIBRATION_ROOT_ENTROPY


def test_calibration_root_entropy_reproduces_exactly():
    _assert_calibration_root_contract(CALIBRATION_ROOT_LABEL)
    root = calibration_root_seed_sequence()
    assert tuple(root.entropy) == CALIBRATION_ROOT_ENTROPY
    assert root.spawn_key == ()
    assert root.n_children_spawned == 0
    assert CALIBRATION_ROOT_ENTROPY != RNG_ROOT_ENTROPY


def test_calibration_root_label_mutant_fails_the_positive_assertion():
    with pytest.raises(AssertionError):
        _assert_calibration_root_contract(CALIBRATION_ROOT_LABEL + " mutated")


def test_deployment_mapping_path_is_bit_identical_to_pre_slice_algorithm():
    assert tuple(inspect.signature(spawn_session_mappings).parameters) == (
        "session_ids",
        "strata",
        "replications",
    )
    _assert_deployment_bit_identity(spawn_session_mappings)


def test_wrong_deployment_root_mutant_fails_the_positive_assertion():
    def wrong_root(sessions, strata, replications):
        return spawn_session_mappings_from_seed_sequence(
            sessions,
            strata,
            replications,
            root_sequence=np.random.SeedSequence(CALIBRATION_ROOT_ENTROPY),
        )

    with pytest.raises(AssertionError):
        _assert_deployment_bit_identity(wrong_root)


def test_explicit_child_path_is_prefix_stable_and_requires_a_fresh_seed_sequence():
    sessions, strata = _fixture()
    first_root = calibration_root_seed_sequence().spawn(1)[0]
    second_root = calibration_root_seed_sequence().spawn(1)[0]
    short = spawn_session_mappings_from_seed_sequence(
        sessions, strata, 2, root_sequence=first_root
    )
    long = spawn_session_mappings_from_seed_sequence(
        sessions, strata, 5, root_sequence=second_root
    )
    assert all(
        _mapping_equal(left, right)
        for left, right in zip(short, long[:2], strict=True)
    )
    with pytest.raises(SpineError, match="fresh and unconsumed"):
        spawn_session_mappings_from_seed_sequence(
            sessions, strata, 1, root_sequence=first_root
        )
    with pytest.raises(SpineError, match="explicit SeedSequence"):
        spawn_session_mappings_from_seed_sequence(
            sessions, strata, 1, root_sequence=CALIBRATION_ROOT_ENTROPY
        )
