"""Behavioral mutation floor for compact Phase 7 dependency evidence."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from mnq_lab import SpineError
from mnq_lab.conditioners.dependencies import (
    CanonicalDependencyPool,
    CanonicalDependencySequence,
    DependencyRange,
    dependency_storage_stats,
    validate_dependency_range,
    validate_legacy_expansion,
)


def _key(kind: str, session: int, position: int):
    return (
        (session, f"{position:02d}")
        if kind == "seasonal"
        else (session, session * 1_000 + position)
    )


def _pool(
    *,
    kind: str = "seasonal",
    block_count: int = 3,
    keys_per_block: int = 2,
) -> tuple[CanonicalDependencyPool, tuple[int, ...]]:
    sessions = tuple(20200101 + index for index in range(block_count))
    pool = CanonicalDependencyPool(kind, "arm", ("open",))
    for session in sessions:
        pool.append_block(
            "open",
            session,
            tuple(_key(kind, session, position) for position in range(keys_per_block)),
            source_phase="open",
            calendar_eligible=True,
            source_rows_valid=True,
        )
    pool.seal()
    return pool, sessions


def _validate(
    dependency_range: DependencyRange,
    *,
    current_session: int,
    count: int,
    history_kind: str = "expanding",
) -> None:
    validate_dependency_range(
        dependency_range,
        key_kind="seasonal",
        arm_id="arm",
        session_phase="open",
        current_session=current_session,
        qualifying_prior_sessions=count,
        history_kind=history_kind,
    )


@pytest.mark.parametrize("mutation", ("missing", "additional", "changed"))
def test_legacy_identity_rejects_missing_additional_and_changed_dependencies(
    mutation: str,
) -> None:
    expected = ((20200101, "00"), (20200101, "01"))
    if mutation == "missing":
        actual = expected[:-1]
    elif mutation == "additional":
        actual = expected + ((20200101, "02"),)
    else:
        actual = ((20200101, "00"), (20200101, "02"))
    sequence = CanonicalDependencySequence.from_legacy(
        "seasonal", "arm", "open", actual
    )
    dependency_range = DependencyRange(sequence, 0, len(sequence))
    assert expected and actual
    with pytest.raises(SpineError, match="differs from legacy tuple"):
        validate_legacy_expansion(dependency_range, expected)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        ("reordered", "unique and ordered"),
        ("duplicated", "unique and ordered"),
        ("wrong_phase", "source phase"),
        ("calendar_ineligible", "calendar-ineligible"),
        ("all_invalid", "all-invalid"),
    ),
)
def test_block_construction_rejects_each_named_source_mutation(
    mutation: str,
    expected: str,
) -> None:
    sequence = CanonicalDependencySequence("seasonal", "arm", "open")
    keys = ((20200101, "00"), (20200101, "01"))
    kwargs = {
        "source_phase": "open",
        "calendar_eligible": True,
        "source_rows_valid": True,
    }
    if mutation == "reordered":
        keys = tuple(reversed(keys))
    elif mutation == "duplicated":
        keys = (keys[0], keys[0])
    elif mutation == "wrong_phase":
        kwargs["source_phase"] = "midday"
    elif mutation == "calendar_ineligible":
        kwargs["calendar_eligible"] = False
    else:
        keys = ()
        kwargs["source_rows_valid"] = False
    with pytest.raises(SpineError, match=expected):
        sequence.append_block(20200101, keys, **kwargs)


@pytest.mark.parametrize("relation", ("current", "future"))
def test_range_rejects_current_and_future_session_dependencies(relation: str) -> None:
    current = 20200110
    dependency_session = current if relation == "current" else current + 1
    sequence = CanonicalDependencySequence("seasonal", "arm", "open")
    sequence.append_block(
        dependency_session,
        ((dependency_session, "00"),),
        source_phase="open",
        calendar_eligible=True,
        source_rows_valid=True,
    )
    sequence.seal()
    dependency_range = DependencyRange(sequence, 0, len(sequence))
    with pytest.raises(SpineError, match="current or future"):
        _validate(dependency_range, current_session=current, count=1)


def test_range_rejects_end_before_start_and_end_beyond_sequence() -> None:
    pool, _ = _pool(block_count=3, keys_per_block=1)
    sequence = pool.sequence("open")
    with pytest.raises(SpineError, match="0 <= start <= end <= len"):
        DependencyRange(sequence, 2, 1)
    with pytest.raises(SpineError, match="0 <= start <= end <= len"):
        DependencyRange(sequence, 0, len(sequence) + 1)


def test_rolling60_rejects_sixty_one_blocks_and_expanding_rejects_nonzero_start():
    pool, sessions = _pool(block_count=61, keys_per_block=1)
    sequence = pool.sequence("open")
    full = DependencyRange(sequence, 0, len(sequence))
    with pytest.raises(SpineError, match="more than sixty"):
        _validate(
            full,
            current_session=sessions[-1] + 1,
            count=61,
            history_kind="rolling60",
        )

    start = sequence.boundary_for_block_count(1)
    nonzero = DependencyRange(sequence, start, len(sequence))
    with pytest.raises(SpineError, match="must start at zero"):
        _validate(
            nonzero,
            current_session=sessions[-1] + 1,
            count=60,
            history_kind="expanding",
        )


def test_nonmonotone_expanding_prefix_and_noncontiguous_rolling_selection_fail():
    pool, sessions = _pool(block_count=62, keys_per_block=1)
    sequence = pool.sequence("open")
    truncated_end = sequence.boundary_for_block_count(61)
    truncated = DependencyRange(sequence, 0, truncated_end)
    with pytest.raises(SpineError, match="exact history selection"):
        _validate(
            truncated,
            current_session=sessions[-1] + 1,
            count=61,
        )

    expected_latest = tuple(sequence.keys[2:])
    mutant = CanonicalDependencySequence("seasonal", "arm", "open")
    for index, session in enumerate(sessions):
        if index == 30:
            continue
        mutant.append_block(
            session,
            ((session, "00"),),
            source_phase="open",
            calendar_eligible=True,
            source_rows_valid=True,
        )
    mutant.seal()
    mutant_start = mutant.boundary_for_block_count(1)
    mutant_range = DependencyRange(mutant, mutant_start, len(mutant))
    assert mutant_range.block_count == 60
    with pytest.raises(SpineError, match="differs from legacy tuple"):
        validate_legacy_expansion(mutant_range, expected_latest)


@dataclass
class _RangeRow:
    _dependency_range: DependencyRange


class _PrivateExpandedRow:
    def __init__(self, dependency_range: DependencyRange) -> None:
        self._dependency_range = dependency_range
        self.dependency_keys = dependency_range.dependency_keys


def _canonical_rows(size: int) -> tuple[_RangeRow, ...]:
    pool, sessions = _pool(block_count=size, keys_per_block=1)
    sequence = pool.sequence("open")
    return tuple(
        _RangeRow(
            DependencyRange(
                sequence,
                0,
                sequence.boundary_for_block_count(index),
            )
        )
        for index in range(1, len(sessions) + 1)
    )


def _legacy_materialized_rows(size: int) -> tuple[_RangeRow, ...]:
    rows: list[_RangeRow] = []
    for end in range(1, size + 1):
        keys = tuple((20200101 + index, "00") for index in range(end))
        sequence = CanonicalDependencySequence.from_legacy(
            "seasonal", "arm", "open", keys
        )
        rows.append(_RangeRow(DependencyRange(sequence, 0, len(sequence))))
    return tuple(rows)


def _ratios(values: tuple[int, ...]) -> tuple[float, ...]:
    return tuple(
        right / left for left, right in zip(values[:-1], values[1:], strict=True)
    )


def test_no_row_owns_expansion_and_n100_200_400_curve_kills_quadratic_mutant():
    sizes = (100, 200, 400)
    compact = tuple(dependency_storage_stats(_canonical_rows(size)) for size in sizes)
    assert all(result["retained_keys"] == size for result, size in zip(compact, sizes))
    assert all(
        ratio <= 2.4
        for ratio in _ratios(tuple(result["dependency_bytes"] for result in compact))
    )
    assert all(
        ratio <= 2.4
        for ratio in _ratios(tuple(result["retained_keys"] for result in compact))
    )

    legacy = tuple(
        dependency_storage_stats(_legacy_materialized_rows(size)) for size in sizes
    )
    assert all(
        ratio > 2.4
        for ratio in _ratios(tuple(result["retained_keys"] for result in legacy))
    )

    pool, _ = _pool(block_count=2, keys_per_block=1)
    dependency_range = DependencyRange(pool.sequence("open"), 0, 1)
    with pytest.raises(SpineError, match="private expanded"):
        dependency_storage_stats((_PrivateExpandedRow(dependency_range),))
