"""Test 10: whole-session mapping, with same-assertion negative cases."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from mnq_lab import SpineError
from mnq_lab.phase10.mapping import (
    PermutedTrajectories,
    SessionMapping,
    apply_joint_mapping,
    assert_joint_reassignment,
    generate_session_mapping,
)


def _fixture():
    sessions = np.arange(40, dtype=np.int32) + 20200101
    strata = np.asarray(["2020Q1"] * 20 + ["2020Q2"] * 20)
    base = np.asarray([0, 0, 1, 1, 1, 2, 2, -1], dtype=np.int8)
    codes = np.vstack([np.roll(base, index % base.size) for index in range(40)])
    valid = codes >= 0
    completion_30 = np.asarray(
        [[(row + column) % 3 != 0 for column in range(8)] for row in range(40)],
        dtype=np.bool_,
    )
    completion_60 = np.asarray(
        [[(row + column) % 5 != 0 for column in range(8)] for row in range(40)],
        dtype=np.bool_,
    )
    rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence((20260728,))))
    mapping = generate_session_mapping(sessions, strata, rng)
    return sessions, strata, codes, valid, (completion_30, completion_60), mapping


def _assert_gate(codes, valid, masks, result):
    assert_joint_reassignment(codes, valid, masks, result)


def _trajectory_signature(codes, valid):
    transitions = tuple(zip(codes[:-1].tolist(), codes[1:].tolist()))
    run_lengths = []
    start = 0
    for index in range(1, codes.size + 1):
        if index == codes.size or codes[index] != codes[start]:
            run_lengths.append(index - start)
            start = index
    return tuple(run_lengths), transitions, tuple(valid.tolist())


def test_permutation_mapping_reassigns_one_whole_vector_jointly():
    sessions, strata, codes, valid, masks, mapping = _fixture()
    result = apply_joint_mapping(codes, valid, masks, mapping)
    _assert_gate(codes, valid, masks, result)
    assert not bool(np.any(mapping.recipient_session_ids == mapping.donor_session_ids))
    for label in ("2020Q1", "2020Q2"):
        members = np.flatnonzero(strata == label)
        assert set(mapping.donor_positions[members]) == set(members)
    for recipient, donor in enumerate(mapping.donor_positions):
        np.testing.assert_array_equal(result.state_codes[recipient], codes[donor])
        np.testing.assert_array_equal(result.state_valid[recipient], valid[donor])
        assert _trajectory_signature(
            result.state_codes[recipient], result.state_valid[recipient]
        ) == _trajectory_signature(codes[donor], valid[donor])
    for source, retained in zip(masks, result.recipient_masks, strict=True):
        np.testing.assert_array_equal(retained, source)


def test_mapping_negative_with_replacement_fails_the_positive_assertion():
    _, _, codes, valid, masks, mapping = _fixture()
    positions = mapping.donor_positions.copy()
    positions[1] = positions[0]
    mutant_mapping = replace(
        mapping,
        donor_positions=positions,
        donor_session_ids=mapping.recipient_session_ids[positions],
    )
    result = apply_joint_mapping(codes, valid, masks, mapping)
    mutant = replace(result, mapping=mutant_mapping)
    with pytest.raises(SpineError, match="without replacement"):
        _assert_gate(codes, valid, masks, mutant)


def test_mapping_negative_self_assignment_fails_the_positive_assertion():
    _, _, codes, valid, masks, mapping = _fixture()
    positions = mapping.donor_positions.copy()
    previous = int(np.flatnonzero(positions == 0)[0])
    positions[previous] = positions[0]
    positions[0] = 0
    mutant_mapping = replace(
        mapping,
        donor_positions=positions,
        donor_session_ids=mapping.recipient_session_ids[positions],
    )
    result = apply_joint_mapping(codes, valid, masks, mapping)
    mutant = replace(result, mapping=mutant_mapping)
    with pytest.raises(SpineError, match="own trajectory"):
        _assert_gate(codes, valid, masks, mutant)


def test_mapping_negative_pooled_strata_fails_the_positive_assertion():
    _, _, codes, valid, masks, mapping = _fixture()
    positions = mapping.donor_positions.copy()
    positions[0], positions[20] = positions[20], positions[0]
    mutant_mapping = replace(
        mapping,
        donor_positions=positions,
        donor_session_ids=mapping.recipient_session_ids[positions],
    )
    result = apply_joint_mapping(codes, valid, masks, mapping)
    mutant = replace(result, mapping=mutant_mapping)
    with pytest.raises(SpineError, match="crosses its stratum"):
        _assert_gate(codes, valid, masks, mutant)


def test_mapping_negative_donor_mask_fails_the_positive_assertion():
    _, _, codes, valid, masks, mapping = _fixture()
    result = apply_joint_mapping(codes, valid, masks, mapping)
    donor_mask = ~masks[0]
    mutant = replace(result, recipient_masks=(donor_mask, result.recipient_masks[1]))
    with pytest.raises(SpineError, match="recipient mask"):
        _assert_gate(codes, valid, masks, mutant)


def test_mapping_negative_independent_output_mapping_fails_the_positive_assertion():
    _, _, codes, valid, masks, mapping = _fixture()
    result = apply_joint_mapping(codes, valid, masks, mapping)
    independent = np.roll(mapping.donor_positions, 1)
    mutant = replace(
        result,
        output_mapping_positions=(result.output_mapping_positions[0], independent),
    )
    with pytest.raises(SpineError, match="independent session mapping"):
        _assert_gate(codes, valid, masks, mutant)


def test_mapping_marks_a_thin_stratum_unusable_without_pooling():
    sessions = np.arange(23, dtype=np.int32)
    strata = np.asarray(["large"] * 20 + ["thin"] * 3)
    rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence((20260728,))))
    mapping = generate_session_mapping(sessions, strata, rng)
    assert bool(np.all(mapping.usable[:20]))
    assert not bool(np.any(mapping.usable[20:]))
    np.testing.assert_array_equal(mapping.donor_positions[20:], -1)
