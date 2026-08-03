"""Permanent, row-keyed support census for Phase 8 bootstrap terms."""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral
from typing import Any, Hashable, Iterable

import numpy as np

from mnq_lab import SpineError

_NON_OK_STATUSES = (
    "degenerate_baseline",
    "insufficient_anchors",
    "insufficient_completion",
    "insufficient_overlap",
    "insufficient_interaction_support",
)
_STATUSES = ("ok", *_NON_OK_STATUSES)


@dataclass(frozen=True)
class BootstrapTermKey:
    """A term label that contains its complete structural result-row identity."""

    family: str
    row_key: tuple[Hashable, ...]
    term_role: str

    def __post_init__(self) -> None:
        if not isinstance(self.family, str) or not self.family:
            raise SpineError("bootstrap term family must be a nonempty string")
        if not isinstance(self.row_key, tuple) or not self.row_key:
            raise SpineError("bootstrap term row_key must be a nonempty tuple")
        if not isinstance(self.term_role, str) or not self.term_role:
            raise SpineError("bootstrap term role must be a nonempty string")
        try:
            hash(self.row_key)
        except TypeError as exc:
            raise SpineError("bootstrap term row_key must be hashable") from exc


@dataclass(frozen=True)
class TermSupportRecord:
    """One support count inseparably bound to the key that produced it."""

    key: BootstrapTermKey
    session_ids: tuple[Hashable, ...]
    n_sessions: int
    status: str
    bootstrap_eligible: bool

    def __post_init__(self) -> None:
        if not isinstance(self.key, BootstrapTermKey):
            raise SpineError("term support record requires a BootstrapTermKey")
        if not isinstance(self.session_ids, tuple):
            raise SpineError("term support session ids must be an immutable tuple")
        computed = len(dict.fromkeys(self.session_ids))
        if (
            isinstance(self.n_sessions, (bool, np.bool_))
            or not isinstance(self.n_sessions, Integral)
            or int(self.n_sessions) != computed
        ):
            raise SpineError(
                "term support count must be computed from its bound session ids"
            )
        if self.status not in _STATUSES:
            raise SpineError(f"undeclared term support status: {self.status!r}")
        if type(self.bootstrap_eligible) is not bool:
            raise SpineError("bootstrap_eligible must be bool")
        if self.bootstrap_eligible != (self.status == "ok"):
            raise SpineError("only an ok term support record may be bootstrap eligible")


def _session_tuple(values: Iterable[Any]) -> tuple[Hashable, ...]:
    try:
        raw_values = tuple(values)
    except TypeError as exc:
        raise SpineError("support session ids must be a finite sequence") from exc
    result: list[Hashable] = []
    for index, raw in enumerate(raw_values):
        value = raw.item() if isinstance(raw, np.generic) else raw
        if value is None or isinstance(value, (bool, np.bool_)):
            raise SpineError(f"invalid support session id at index {index}")
        try:
            hash(value)
        except TypeError as exc:
            raise SpineError(f"unhashable support session id at index {index}") from exc
        result.append(value)
    return tuple(result)


def build_term_support_record(
    *,
    key: BootstrapTermKey,
    session_ids: Iterable[Any],
    status: str,
) -> TermSupportRecord:
    """Construct count and label together; no caller-supplied count is accepted."""
    supplied = _session_tuple(session_ids)
    sessions = tuple(dict.fromkeys(supplied))
    return TermSupportRecord(
        key=key,
        session_ids=sessions,
        n_sessions=len(dict.fromkeys(sessions)),
        status=status,
        bootstrap_eligible=status == "ok",
    )


def interval_eligible_records(
    records: Iterable[TermSupportRecord],
) -> tuple[TermSupportRecord, ...]:
    try:
        values = tuple(records)
    except TypeError as exc:
        raise SpineError("term support census must be a finite sequence") from exc
    if any(not isinstance(record, TermSupportRecord) for record in values):
        raise SpineError("term support census contains an invalid record")
    return tuple(record for record in values if record.bootstrap_eligible)


def thin_support_families(
    records: Iterable[TermSupportRecord], *, threshold: int = 30
) -> tuple[tuple[str, int], ...]:
    values = tuple(records)
    if isinstance(threshold, bool) or not isinstance(threshold, Integral) or threshold <= 0:
        raise SpineError("thin-support threshold must be a positive integer")
    counts: dict[str, int] = {}
    order: list[str] = []
    for record in values:
        if not isinstance(record, TermSupportRecord):
            raise SpineError("term support census contains an invalid record")
        if record.n_sessions < int(threshold):
            if record.key.family not in counts:
                order.append(record.key.family)
                counts[record.key.family] = 0
            counts[record.key.family] += 1
    return tuple((family, counts[family]) for family in order)


__all__ = [
    "BootstrapTermKey",
    "TermSupportRecord",
    "build_term_support_record",
    "interval_eligible_records",
    "thin_support_families",
]
