"""Exact compact causal-dependency sequences for Phase 7 conditioners."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from functools import lru_cache
from itertools import groupby
import sys
from types import MappingProxyType
from typing import Iterable, Literal, TypeAlias

from mnq_lab import SpineError

DependencyKind: TypeAlias = Literal["seasonal", "threshold"]
SeasonalDependencyKey: TypeAlias = tuple[int, str]
ThresholdDependencyKey: TypeAlias = tuple[int, int]
DependencyKey: TypeAlias = SeasonalDependencyKey | ThresholdDependencyKey

__all__ = [
    "CanonicalDependencyPool",
    "CanonicalDependencySequence",
    "DependencyBlock",
    "DependencyRange",
    "dependency_storage_stats",
    "clear_dependency_expansion_cache",
    "validate_legacy_expansion",
    "validate_dependency_range",
]


@dataclass(frozen=True)
class DependencyBlock:
    """Immutable offsets for one qualifying source-session block."""

    session_id: int
    start: int
    end: int

    def __post_init__(self) -> None:
        if type(self.session_id) is not int:
            raise SpineError("dependency block session_id must be a built-in int")
        if type(self.start) is not int or type(self.end) is not int:
            raise SpineError("dependency block bounds must be built-in integers")
        if not 0 <= self.start < self.end:
            raise SpineError("dependency block must be nonempty with ordered bounds")


class CanonicalDependencySequence:
    """One append-only, then sealed, exact key sequence for an arm and phase."""

    __slots__ = (
        "key_kind",
        "arm_id",
        "session_phase",
        "_keys",
        "_blocks",
        "_block_sessions",
        "_boundary_to_block",
        "_sealed",
        "_canonical",
    )

    def __init__(
        self,
        key_kind: DependencyKind,
        arm_id: str,
        session_phase: str,
        *,
        canonical: bool = True,
    ) -> None:
        if key_kind not in {"seasonal", "threshold"}:
            raise SpineError("dependency sequence kind is outside the closed vocabulary")
        if not isinstance(arm_id, str) or not arm_id:
            raise SpineError("dependency sequence arm_id must be nonempty")
        if not isinstance(session_phase, str) or not session_phase:
            raise SpineError("dependency sequence phase must be nonempty")
        if type(canonical) is not bool:
            raise SpineError("dependency sequence canonical flag must be bool")
        self.key_kind = key_kind
        self.arm_id = arm_id
        self.session_phase = session_phase
        self._keys: list[DependencyKey] | tuple[DependencyKey, ...] = []
        self._blocks: list[DependencyBlock] | tuple[DependencyBlock, ...] = []
        self._block_sessions: tuple[int, ...] = ()
        self._boundary_to_block: MappingProxyType = MappingProxyType({0: 0})
        self._sealed = False
        self._canonical = canonical

    @property
    def canonical(self) -> bool:
        return self._canonical

    @property
    def sealed(self) -> bool:
        return self._sealed

    @property
    def blocks(self) -> tuple[DependencyBlock, ...]:
        if not self._sealed:
            raise SpineError("dependency sequence block metadata requested before sealing")
        return self._blocks

    @property
    def block_sessions(self) -> tuple[int, ...]:
        if not self._sealed:
            raise SpineError("dependency sequence sessions requested before sealing")
        return self._block_sessions

    @property
    def keys(self) -> tuple[DependencyKey, ...]:
        if not self._sealed:
            raise SpineError("dependency sequence keys requested before sealing")
        return self._keys

    def append_block(
        self,
        session_id: int,
        keys: Iterable[DependencyKey],
        *,
        source_phase: str,
        calendar_eligible: bool,
        source_rows_valid: bool,
    ) -> None:
        if self._sealed:
            raise SpineError("cannot append to a sealed dependency sequence")
        if type(session_id) is not int:
            raise SpineError("dependency block session_id must be a built-in int")
        if source_phase != self.session_phase:
            raise SpineError("dependency block source phase differs from sequence phase")
        if calendar_eligible is not True:
            raise SpineError("calendar-ineligible session cannot enter dependency sequence")
        dependency_keys = tuple(keys)
        if not dependency_keys:
            raise SpineError("all-invalid session cannot create a dependency block")
        if source_rows_valid is not True:
            raise SpineError("invalid source rows cannot enter dependency sequence")
        if self._blocks and session_id <= self._blocks[-1].session_id:
            raise SpineError("dependency session blocks must be unique and ascending")
        for key in dependency_keys:
            if not isinstance(key, tuple) or len(key) != 2:
                raise SpineError("dependency key must be a pair")
            if type(key[0]) is not int or key[0] != session_id:
                raise SpineError("dependency key session differs from its block")
            if self.key_kind == "seasonal":
                if not isinstance(key[1], str) or not key[1]:
                    raise SpineError("seasonal dependency key bucket must be nonempty")
            elif type(key[1]) is not int:
                raise SpineError("threshold dependency key tau must be a built-in int")
        if dependency_keys != tuple(sorted(set(dependency_keys))):
            raise SpineError("dependency block keys must be unique and ordered")
        if self._keys and self._keys[-1] >= dependency_keys[0]:
            raise SpineError("dependency append order differs from canonical sorted order")
        start = len(self._keys)
        self._keys.extend(dependency_keys)
        self._blocks.append(DependencyBlock(session_id, start, len(self._keys)))

    def seal(self) -> None:
        if self._sealed:
            raise SpineError("dependency sequence cannot be sealed twice")
        self._keys = tuple(self._keys)
        self._blocks = tuple(self._blocks)
        self._block_sessions = tuple(block.session_id for block in self._blocks)
        boundaries = {0: 0}
        for block_index, block in enumerate(self._blocks, start=1):
            boundaries[block.end] = block_index
        self._boundary_to_block = MappingProxyType(boundaries)
        self._sealed = True

    def __len__(self) -> int:
        if not self._sealed:
            raise SpineError("dependency sequence length requested before sealing")
        return len(self._keys)

    def __getitem__(self, index):
        if not self._sealed:
            raise SpineError("dependency sequence slice requested before sealing")
        return self._keys[index]

    def prefix_block_count(self, current_session: int) -> int:
        if type(current_session) is not int:
            raise SpineError("dependency current session must be a built-in int")
        return bisect_left(self.block_sessions, current_session)

    def boundary_for_block_count(self, block_count: int) -> int:
        if type(block_count) is not int or not 0 <= block_count <= len(self.blocks):
            raise SpineError("dependency block count is outside sequence bounds")
        return 0 if block_count == 0 else self.blocks[block_count - 1].end

    def block_count_between(self, start: int, end: int) -> int:
        try:
            return self._boundary_to_block[end] - self._boundary_to_block[start]
        except KeyError as exc:
            raise SpineError("dependency range bounds must lie on block boundaries") from exc

    @classmethod
    def from_legacy(
        cls,
        key_kind: DependencyKind,
        arm_id: str,
        session_phase: str,
        dependency_keys: tuple[DependencyKey, ...],
    ) -> CanonicalDependencySequence:
        if not isinstance(dependency_keys, tuple):
            raise SpineError("legacy dependency_keys must be a tuple")
        sequence = cls(key_kind, arm_id, session_phase, canonical=False)
        for session_id, grouped in groupby(dependency_keys, key=lambda key: key[0]):
            sequence.append_block(
                session_id,
                tuple(grouped),
                source_phase=session_phase,
                calendar_eligible=True,
                source_rows_valid=True,
            )
        sequence.seal()
        return sequence


@dataclass(frozen=True)
class DependencyRange:
    """Half-open view into one exact canonical dependency sequence."""

    sequence_ref: CanonicalDependencySequence
    start: int
    end: int

    def __post_init__(self) -> None:
        if not isinstance(self.sequence_ref, CanonicalDependencySequence):
            raise SpineError("dependency range requires a canonical sequence")
        if not self.sequence_ref.sealed:
            raise SpineError("dependency range cannot reference an unsealed sequence")
        if type(self.start) is not int or type(self.end) is not int:
            raise SpineError("dependency range bounds must be built-in integers")
        if not 0 <= self.start <= self.end <= len(self.sequence_ref):
            raise SpineError("dependency range must satisfy 0 <= start <= end <= len")
        self.sequence_ref.block_count_between(self.start, self.end)

    @property
    def dependency_keys(self) -> tuple[DependencyKey, ...]:
        return _expand_dependency_range(self)

    @property
    def block_count(self) -> int:
        return self.sequence_ref.block_count_between(self.start, self.end)

    @property
    def block_sessions(self) -> tuple[int, ...]:
        sequence = self.sequence_ref
        first = sequence._boundary_to_block[self.start]
        last = sequence._boundary_to_block[self.end]
        return sequence.block_sessions[first:last]


@lru_cache(maxsize=1)
def _expand_dependency_range(
    dependency_range: DependencyRange,
) -> tuple[DependencyKey, ...]:
    """Retain at most one caller-requested expansion, never one per row."""
    return tuple(
        dependency_range.sequence_ref[
            dependency_range.start : dependency_range.end
        ]
    )


def clear_dependency_expansion_cache() -> None:
    _expand_dependency_range.cache_clear()


class CanonicalDependencyPool:
    """Registered phase sequences for one typed conditioner arm."""

    __slots__ = ("key_kind", "arm_id", "_sequences", "_sealed")

    def __init__(
        self,
        key_kind: DependencyKind,
        arm_id: str,
        phases: tuple[str, ...],
    ) -> None:
        if not phases or len(set(phases)) != len(phases):
            raise SpineError("dependency pool phases must be nonempty and unique")
        self.key_kind = key_kind
        self.arm_id = arm_id
        self._sequences = {
            phase: CanonicalDependencySequence(key_kind, arm_id, phase)
            for phase in phases
        }
        self._sealed = False

    def sequence(self, phase: str) -> CanonicalDependencySequence:
        try:
            return self._sequences[phase]
        except KeyError as exc:
            raise SpineError(f"dependency pool has no registered phase {phase!r}") from exc

    def append_block(
        self,
        phase: str,
        session_id: int,
        keys: Iterable[DependencyKey],
        *,
        source_phase: str,
        calendar_eligible: bool,
        source_rows_valid: bool,
    ) -> None:
        if self._sealed:
            raise SpineError("cannot append through a sealed dependency pool")
        self.sequence(phase).append_block(
            session_id,
            keys,
            source_phase=source_phase,
            calendar_eligible=calendar_eligible,
            source_rows_valid=source_rows_valid,
        )

    def seal(self) -> None:
        if self._sealed:
            raise SpineError("dependency pool cannot be sealed twice")
        for sequence in self._sequences.values():
            sequence.seal()
        self._sequences = MappingProxyType(self._sequences)
        self._sealed = True

    def range_for(
        self,
        phase: str,
        current_session: int,
        history_kind: Literal["expanding", "rolling60", "empty"],
    ) -> DependencyRange:
        if not self._sealed:
            raise SpineError("dependency pool range requested before sealing")
        sequence = self.sequence(phase)
        prefix_count = sequence.prefix_block_count(current_session)
        end = sequence.boundary_for_block_count(prefix_count)
        if history_kind == "expanding":
            start = 0
        elif history_kind == "rolling60":
            start = sequence.boundary_for_block_count(max(0, prefix_count - 60))
        elif history_kind == "empty":
            start = end = 0
        else:
            raise SpineError("dependency history kind is outside the closed vocabulary")
        return DependencyRange(sequence, start, end)


def validate_dependency_range(
    dependency_range: DependencyRange,
    *,
    key_kind: DependencyKind,
    arm_id: str,
    session_phase: str,
    current_session: int,
    qualifying_prior_sessions: int,
    history_kind: Literal["expanding", "rolling60", "empty"],
) -> None:
    sequence = dependency_range.sequence_ref
    if sequence.key_kind != key_kind:
        raise SpineError("dependency range uses the wrong typed pool")
    if sequence.arm_id != arm_id:
        raise SpineError("dependency range arm differs from its row")
    if sequence.session_phase != session_phase:
        raise SpineError("dependency range phase differs from its row")
    if type(current_session) is not int:
        raise SpineError("dependency row session must be a built-in int")
    if type(qualifying_prior_sessions) is not int or qualifying_prior_sessions < 0:
        raise SpineError("dependency qualifying-session count is invalid")
    if any(session >= current_session for session in dependency_range.block_sessions):
        raise SpineError("dependency range includes current or future session")
    if dependency_range.block_count != qualifying_prior_sessions:
        raise SpineError("dependencies and qualifying-session count disagree")

    if not sequence.canonical:
        if history_kind == "rolling60" and dependency_range.block_count > 60:
            raise SpineError("rolling dependency range spans more than sixty blocks")
        if history_kind == "empty" and (dependency_range.start or dependency_range.end):
            raise SpineError("empty dependency range must use zero bounds")
        return

    prefix_count = sequence.prefix_block_count(current_session)
    expected_end = sequence.boundary_for_block_count(prefix_count)
    if history_kind == "expanding":
        if dependency_range.start != 0:
            raise SpineError("expanding dependency range must start at zero")
        expected_start = 0
    elif history_kind == "rolling60":
        expected_start = sequence.boundary_for_block_count(max(0, prefix_count - 60))
        if dependency_range.block_count > 60:
            raise SpineError("rolling dependency range spans more than sixty blocks")
    elif history_kind == "empty":
        expected_start = expected_end = 0
    else:
        raise SpineError("dependency history kind is outside the closed vocabulary")
    if dependency_range.start != expected_start or dependency_range.end != expected_end:
        raise SpineError("dependency range differs from its exact history selection")


def validate_legacy_expansion(
    dependency_range: DependencyRange,
    legacy_dependency_keys: tuple[DependencyKey, ...],
) -> None:
    if not isinstance(legacy_dependency_keys, tuple):
        raise SpineError("legacy dependency oracle must be a tuple")
    if dependency_range.dependency_keys != legacy_dependency_keys:
        raise SpineError("dependency expansion differs from legacy tuple")


def dependency_storage_stats(rows: Iterable[object]) -> dict[str, int]:
    """Count physically retained canonical evidence without expanding row views."""
    sequences: dict[int, CanonicalDependencySequence] = {}
    ranges: dict[int, DependencyRange] = {}
    row_count = 0
    for row in rows:
        row_count += 1
        dependency_range = getattr(row, "_dependency_range", None)
        if not isinstance(dependency_range, DependencyRange):
            raise SpineError("dependency-bearing row lacks compact range storage")
        if "dependency_keys" in getattr(row, "__dict__", {}):
            raise SpineError("row owns a private expanded dependency tuple")
        ranges[id(dependency_range)] = dependency_range
        sequences[id(dependency_range.sequence_ref)] = dependency_range.sequence_ref
    retained_keys = sum(len(sequence) for sequence in sequences.values())
    dependency_bytes = 0
    for sequence in sequences.values():
        dependency_bytes += sys.getsizeof(sequence)
        dependency_bytes += sys.getsizeof(sequence.keys)
        dependency_bytes += sum(sys.getsizeof(key) for key in sequence.keys)
        dependency_bytes += sys.getsizeof(sequence.blocks)
        dependency_bytes += sum(sys.getsizeof(block) for block in sequence.blocks)
        dependency_bytes += sys.getsizeof(sequence.block_sessions)
        dependency_bytes += sys.getsizeof(sequence._boundary_to_block)
    dependency_bytes += sum(sys.getsizeof(value) for value in ranges.values())
    return {
        "row_count": row_count,
        "sequence_count": len(sequences),
        "range_count": len(ranges),
        "retained_keys": retained_keys,
        "dependency_bytes": dependency_bytes,
    }
