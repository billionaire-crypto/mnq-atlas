"""Immutable Phase 6 conditioner registry mechanics.

This module stores identities and classifications only.  It computes no
conditioner values, reads no data, and creates no market result.  Descriptive
entries are permanently ineligible for confirmation.  Causal admission is
added separately behind the ratified executed-suite boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
import math
from threading import RLock
from types import MappingProxyType
from typing import Any

from mnq_lab import SpineError

DESCRIPTIVE_LABEL = "NONCAUSAL — NOT ELIGIBLE FOR CONFIRMATION"

__all__ = [
    "DESCRIPTIVE_LABEL",
    "ConditionerClass",
    "ConditionerDescriptor",
    "ConditionerRegistry",
    "register_descriptive_conditioner",
]


class ConditionerClass(Enum):
    """Permanent registry classifications."""

    CAUSAL = "causal"
    DESCRIPTIVE = "descriptive"


ImmutableMetadataValue = (
    None | bool | int | float | str | tuple["ImmutableMetadataValue", ...]
    | Mapping[str, "ImmutableMetadataValue"]
)


def _freeze_metadata_value(value: Any, path: str) -> ImmutableMetadataValue:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SpineError(f"{path} must be finite")
        return value
    if isinstance(value, tuple):
        return tuple(
            _freeze_metadata_value(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    if isinstance(value, Mapping):
        return _freeze_metadata(value, path=path)
    raise SpineError(
        f"{path} must contain only immutable metadata values, tuples, or mappings"
    )


def _freeze_metadata(
    metadata: Any, *, path: str = "metadata"
) -> Mapping[str, ImmutableMetadataValue]:
    if not isinstance(metadata, Mapping):
        raise SpineError("metadata must be a mapping")

    frozen: dict[str, ImmutableMetadataValue] = {}
    for key, value in metadata.items():
        if not isinstance(key, str) or not key:
            raise SpineError(f"{path} keys must be non-empty strings")
        frozen[key] = _freeze_metadata_value(value, f"{path}[{key!r}]")
    return MappingProxyType(frozen)


def _validate_identifier(identifier: Any) -> str:
    if (
        not isinstance(identifier, str)
        or not identifier
        or identifier != identifier.strip()
    ):
        raise SpineError(
            "conditioner identifier must be a non-empty unpadded string"
        )
    return identifier


def _validate_conditioner(conditioner: Any) -> Callable[..., Any]:
    if not callable(conditioner):
        raise SpineError("conditioner must be callable")
    return conditioner


@dataclass(frozen=True, slots=True)
class ConditionerDescriptor:
    """Immutable retrieval view of one stored registry entry."""

    identifier: str
    conditioner: Callable[..., Any]
    classification: ConditionerClass
    label: str
    metadata: Mapping[str, ImmutableMetadataValue]


class ConditionerRegistry:
    """One insertion-ordered namespace shared by both classifications."""

    __slots__ = (
        "__entries",
        "__callable_identifiers",
        "__lock",
        "__admission_in_progress",
    )

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("ConditionerRegistry is final and cannot be subclassed")

    def __init__(self) -> None:
        self.__entries: dict[str, ConditionerDescriptor] = {}
        self.__callable_identifiers: dict[int, str] = {}
        self.__lock = RLock()
        self.__admission_in_progress = False

    def get(self, identifier: str) -> ConditionerDescriptor:
        """Retrieve a stored immutable descriptor by exact identifier."""

        with self.__lock:
            try:
                return self.__entries[identifier]
            except (KeyError, TypeError) as exc:
                raise SpineError(
                    f"unknown conditioner identifier {identifier!r}"
                ) from exc

    def entries(self) -> tuple[ConditionerDescriptor, ...]:
        """Return descriptors in insertion order, never measurement order."""

        with self.__lock:
            return tuple(self.__entries.values())

    def is_confirmation_eligible(self, identifier: str) -> bool:
        """The single eligibility query; true only for stored causal entries."""

        return self.get(identifier).classification is ConditionerClass.CAUSAL

    def _register_descriptive(
        self,
        identifier: str,
        conditioner: Callable[..., Any],
        metadata: Mapping[str, ImmutableMetadataValue],
    ) -> ConditionerDescriptor:
        with self.__lock:
            if self.__admission_in_progress:
                raise SpineError(
                    "registry mutation is forbidden during causal admission"
                )
            self.__require_available(identifier, conditioner)
            descriptor = ConditionerDescriptor(
                identifier=identifier,
                conditioner=conditioner,
                classification=ConditionerClass.DESCRIPTIVE,
                label=DESCRIPTIVE_LABEL,
                metadata=metadata,
            )
            self.__entries[identifier] = descriptor
            self.__callable_identifiers[id(conditioner)] = identifier
            return descriptor

    def __require_available(
        self, identifier: str, conditioner: Callable[..., Any]
    ) -> None:
        if identifier in self.__entries:
            raise SpineError(f"duplicate conditioner identifier {identifier!r}")
        existing_identifier = self.__callable_identifiers.get(id(conditioner))
        if existing_identifier is not None:
            existing = self.__entries[existing_identifier]
            if existing.conditioner is conditioner:
                raise SpineError(
                    "conditioner callable object is already registered as "
                    f"{existing_identifier!r}"
                )
            raise SpineError("internal callable identity collision")


def _require_registry(registry: Any) -> ConditionerRegistry:
    if type(registry) is not ConditionerRegistry:
        raise SpineError("registry must be an exact ConditionerRegistry")
    return registry


def register_descriptive_conditioner(
    registry: ConditionerRegistry,
    identifier: str,
    conditioner: Callable[..., Any],
    *,
    metadata: Mapping[str, ImmutableMetadataValue],
) -> ConditionerDescriptor:
    """Insert a permanently noncausal descriptor without causal evidence."""

    exact_registry = _require_registry(registry)
    exact_identifier = _validate_identifier(identifier)
    exact_conditioner = _validate_conditioner(conditioner)
    frozen_metadata = _freeze_metadata(metadata)
    return exact_registry._register_descriptive(
        exact_identifier, exact_conditioner, frozen_metadata
    )
