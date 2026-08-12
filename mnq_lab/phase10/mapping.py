"""Whole-session trajectory reassignment for the retained formal null."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from mnq_lab import SpineError
from mnq_lab.phase10.contract import RNG_ROOT_ENTROPY, load_phase10_contract


@dataclass(frozen=True)
class SessionMapping:
    recipient_session_ids: np.ndarray
    donor_session_ids: np.ndarray
    donor_positions: np.ndarray
    strata: np.ndarray
    usable: np.ndarray

    def __post_init__(self) -> None:
        arrays = (
            self.recipient_session_ids,
            self.donor_session_ids,
            self.donor_positions,
            self.strata,
            self.usable,
        )
        if any(np.asarray(value).ndim != 1 for value in arrays):
            raise SpineError("session mapping fields must be one-dimensional")
        if len({np.asarray(value).size for value in arrays}) != 1:
            raise SpineError("session mapping fields must have equal length")


@dataclass(frozen=True)
class PermutedTrajectories:
    mapping: SessionMapping
    state_codes: np.ndarray
    state_valid: np.ndarray
    recipient_masks: tuple[np.ndarray, ...]
    output_mapping_positions: tuple[np.ndarray, ...]


def _one_vector(values: Any, name: str) -> np.ndarray:
    array = np.asarray(values)
    if array.ndim != 1 or array.size == 0:
        raise SpineError(f"{name} must be one nonempty vector")
    return array


def _derangement(size: int, rng: np.random.Generator) -> np.ndarray:
    identity = np.arange(size, dtype=np.intp)
    while True:
        proposal = rng.permutation(size)
        if not bool(np.any(proposal == identity)):
            return proposal.astype(np.intp, copy=False)


def generate_session_mapping(
    session_ids: Any,
    strata: Any,
    rng: np.random.Generator,
) -> SessionMapping:
    """Draw one without-replacement, no-self mapping within each stratum."""
    if not isinstance(rng, np.random.Generator) or not isinstance(
        rng.bit_generator, np.random.PCG64
    ):
        raise SpineError("Phase 10 mapping requires an explicit PCG64 Generator")
    sessions = _one_vector(session_ids, "session_ids")
    labels = _one_vector(strata, "strata")
    if sessions.size != labels.size or len(set(sessions.tolist())) != sessions.size:
        raise SpineError("session ids must be unique and aligned with strata")
    contract = load_phase10_contract()
    positions = np.full(sessions.size, -1, dtype=np.intp)
    usable = np.zeros(sessions.size, dtype=np.bool_)
    for label in tuple(dict.fromkeys(labels.tolist())):
        members = np.flatnonzero(labels == label)
        if members.size < contract.min_sessions_per_stratum:
            continue
        local = _derangement(int(members.size), rng)
        positions[members] = members[local]
        usable[members] = True
    donors = np.full(sessions.size, -1, dtype=sessions.dtype)
    donors[usable] = sessions[positions[usable]]
    result = SessionMapping(
        sessions.copy(), donors, positions, labels.copy(), usable
    )
    assert_mapping_contract(result)
    return result


def spawn_session_mappings(
    session_ids: Any,
    strata: Any,
    replications: int,
) -> tuple[SessionMapping, ...]:
    """Spawn prefix-stable PCG64 children from the frozen root entropy."""
    if isinstance(replications, bool) or not isinstance(replications, int) or replications <= 0:
        raise SpineError("replications must be a positive built-in integer")
    root = np.random.SeedSequence(RNG_ROOT_ENTROPY)
    children = root.spawn(replications)
    return tuple(
        generate_session_mapping(
            session_ids,
            strata,
            np.random.Generator(np.random.PCG64(child)),
        )
        for child in children
    )


def assert_mapping_contract(mapping: SessionMapping) -> None:
    """Fail closed on crossing, replacement, self assignment, or silent pooling."""
    sessions = np.asarray(mapping.recipient_session_ids)
    donors = np.asarray(mapping.donor_session_ids)
    positions = np.asarray(mapping.donor_positions)
    strata = np.asarray(mapping.strata)
    usable = np.asarray(mapping.usable)
    if usable.dtype.kind != "b" or positions.dtype.kind not in {"i", "u"}:
        raise SpineError("mapping usability or donor position encoding differs")
    if bool(np.any(positions[~usable] != -1)) or bool(np.any(donors[~usable] != -1)):
        raise SpineError("unusable strata must remain explicitly unmapped")
    for label in tuple(dict.fromkeys(strata.tolist())):
        members = np.flatnonzero(strata == label)
        local_usable = usable[members]
        if bool(np.any(local_usable)) and not bool(np.all(local_usable)):
            raise SpineError("a stratum cannot be partly usable")
        if not bool(np.any(local_usable)):
            continue
        assigned = positions[members]
        if len(set(assigned.tolist())) != members.size:
            raise SpineError("donor trajectories are not assigned without replacement")
        if set(assigned.tolist()) != set(members.tolist()):
            raise SpineError("a donor trajectory crosses its stratum")
        if bool(np.any(assigned == members)):
            raise SpineError("a recipient received its own trajectory")
        if not np.array_equal(donors[members], sessions[assigned]):
            raise SpineError("donor identifiers differ from donor positions")


def apply_joint_mapping(
    state_codes: Any,
    state_valid: Any,
    recipient_masks: Any,
    mapping: SessionMapping,
) -> PermutedTrajectories:
    """Move donor state vectors while retaining every recipient mask unchanged."""
    codes = np.asarray(state_codes)
    valid = np.asarray(state_valid)
    if codes.ndim != 2 or valid.shape != codes.shape or valid.dtype.kind != "b":
        raise SpineError("state trajectories must be aligned session-by-grid matrices")
    if codes.shape[0] != mapping.recipient_session_ids.size:
        raise SpineError("state trajectory count differs from the session mapping")
    if not bool(np.all(mapping.usable)):
        raise SpineError("formal evaluation cannot continue with an unusable stratum")
    try:
        masks = tuple(np.asarray(value) for value in recipient_masks)
    except TypeError as exc:
        raise SpineError("recipient masks must be a finite sequence") from exc
    if not masks or any(mask.shape != codes.shape or mask.dtype.kind != "b" for mask in masks):
        raise SpineError("recipient masks must be aligned boolean matrices")
    reassigned_codes = codes[mapping.donor_positions].copy()
    reassigned_valid = valid[mapping.donor_positions].copy()
    retained_masks = tuple(mask.copy() for mask in masks)
    output_positions = tuple(mapping.donor_positions.copy() for _ in masks)
    result = PermutedTrajectories(
        mapping,
        reassigned_codes,
        reassigned_valid,
        retained_masks,
        output_positions,
    )
    assert_joint_reassignment(codes, valid, masks, result)
    return result


def assert_joint_reassignment(
    original_codes: Any,
    original_valid: Any,
    original_masks: Any,
    result: PermutedTrajectories,
) -> None:
    """Assert the same whole-vector and recipient-mask contract used in tests."""
    assert_mapping_contract(result.mapping)
    codes = np.asarray(original_codes)
    valid = np.asarray(original_valid)
    expected_codes = codes[result.mapping.donor_positions]
    expected_valid = valid[result.mapping.donor_positions]
    if not np.array_equal(result.state_codes, expected_codes):
        raise SpineError("a donor state trajectory was split or altered")
    if not np.array_equal(result.state_valid, expected_valid):
        raise SpineError("donor undefined or warmup entries were not preserved")
    source_masks = tuple(np.asarray(value) for value in original_masks)
    if len(source_masks) != len(result.recipient_masks):
        raise SpineError("joint output inventory differs")
    if len(result.output_mapping_positions) != len(source_masks):
        raise SpineError("joint mapping inventory differs")
    for source, retained, positions in zip(
        source_masks,
        result.recipient_masks,
        result.output_mapping_positions,
        strict=True,
    ):
        if not np.array_equal(source, retained):
            raise SpineError("a donor completeness mask replaced a recipient mask")
        if not np.array_equal(positions, result.mapping.donor_positions):
            raise SpineError("an output used an independent session mapping")
