"""Immutable Phase 6 conditioner registry mechanics.

This module stores identities and classifications only.  It computes no
conditioner values, reads no data, and creates no market result.  Descriptive
entries are permanently ineligible for confirmation.  Causal admission is
added separately behind the ratified executed-suite boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields
from enum import Enum
import math
from threading import RLock
from types import MappingProxyType
from typing import Any

from mnq_lab import SpineError
from mnq_lab.core.dependency import (
    DependencyCheck,
    DependencyCheckError,
    DependencyCase,
    DependencyFailure,
    DeterministicWitness,
    OutputKind,
    run_dependency_locality,
    run_deterministic_witness,
)

CAUSAL_LABEL = "CAUSAL — EMPIRICAL ADMISSION EVIDENCE, NOT PROOF OF CAUSALITY"
DESCRIPTIVE_LABEL = "NONCAUSAL — NOT ELIGIBLE FOR CONFIRMATION"

__all__ = [
    "CAUSAL_LABEL",
    "DESCRIPTIVE_LABEL",
    "ConditionerClass",
    "ConditionerDescriptor",
    "ConditionerRegistry",
    "NegativeControl",
    "NegativeControlFailure",
    "RegisteredComparison",
    "WitnessCheck",
    "register_causal_conditioner",
    "register_descriptive_conditioner",
]

_DeclarationSnapshot = tuple[tuple[str, Any], ...]


def _snapshot_declaration(value: Any) -> _DeclarationSnapshot:
    """Capture every dataclass field identity before admission code executes."""

    return tuple(
        (field.name, getattr(value, field.name)) for field in fields(value)
    )


def _snapshot_field(snapshot: _DeclarationSnapshot, name: str) -> Any:
    return next(value for field, value in snapshot if field == name)


def _assert_declaration_snapshot(
    value: Any, snapshot: _DeclarationSnapshot, context: str
) -> None:
    for field, expected in snapshot:
        if getattr(value, field) is not expected:
            raise SpineError(
                f"{context} changed snapshotted field {field!r} before execution"
            )


class ConditionerClass(Enum):
    """Permanent registry classifications."""

    CAUSAL = "causal"
    DESCRIPTIVE = "descriptive"


class NegativeControlFailure(Enum):
    """The two required executable failure families for causal admission."""

    LOCALITY_OUTPUT_CHANGE = "locality_output_change"
    WITNESS_CHANGED_OUTPUT = "witness_changed_output"


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
class WitnessCheck:
    """One declared witness paired to its already-declared locality case."""

    case: DependencyCase
    witness: DeterministicWitness

    def __post_init__(self) -> None:
        if type(self.case) is not DependencyCase:
            raise SpineError("witness check case must be a DependencyCase")
        if type(self.witness) is not DeterministicWitness:
            raise SpineError(
                "witness check witness must be a DeterministicWitness"
            )


@dataclass(frozen=True, slots=True)
class NegativeControl:
    """An executable planted failure, never a caller-supplied pass result."""

    name: str
    failure: NegativeControlFailure
    case: DependencyCase
    witness: DeterministicWitness | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise SpineError("negative control name must be a non-empty string")
        if not isinstance(self.failure, NegativeControlFailure):
            raise SpineError(
                "negative control failure must be a NegativeControlFailure"
            )
        if type(self.case) is not DependencyCase:
            raise SpineError("negative control case must be a DependencyCase")
        if self.failure is NegativeControlFailure.LOCALITY_OUTPUT_CHANGE:
            if self.witness is not None:
                raise SpineError(
                    "locality-output negative control must not supply a witness"
                )
        elif type(self.witness) is not DeterministicWitness:
            raise SpineError(
                "witness-output negative control requires a DeterministicWitness"
            )


@dataclass(frozen=True, slots=True)
class RegisteredComparison:
    """Immutable comparison metadata executed for one locality case."""

    case_name: str
    kind: OutputKind
    atol: float
    rtol: float


@dataclass(frozen=True, slots=True, init=False)
class ConditionerDescriptor:
    """Retrieval view immutable through supported Python operations.

    Deliberate same-process bypasses such as ``object.__setattr__`` and
    extracting a mapping proxy's referent are outside the registry threat
    model; Python object encapsulation is not treated as a security boundary.
    """

    identifier: str
    conditioner: Callable[..., Any]
    classification: ConditionerClass
    label: str
    metadata: Mapping[str, ImmutableMetadataValue]
    locality_case_count: int = 0
    witness_count: int = 0
    negative_control_count: int = 0
    comparison_policies: tuple[RegisteredComparison, ...] = ()


def _make_descriptor(
    *,
    identifier: str,
    conditioner: Callable[..., Any],
    classification: ConditionerClass,
    label: str,
    metadata: Mapping[str, ImmutableMetadataValue],
    locality_case_count: int = 0,
    witness_count: int = 0,
    negative_control_count: int = 0,
    comparison_policies: tuple[RegisteredComparison, ...] = (),
) -> ConditionerDescriptor:
    descriptor = object.__new__(ConditionerDescriptor)
    object.__setattr__(descriptor, "identifier", identifier)
    object.__setattr__(descriptor, "conditioner", conditioner)
    object.__setattr__(descriptor, "classification", classification)
    object.__setattr__(descriptor, "label", label)
    object.__setattr__(descriptor, "metadata", metadata)
    object.__setattr__(descriptor, "locality_case_count", locality_case_count)
    object.__setattr__(descriptor, "witness_count", witness_count)
    object.__setattr__(
        descriptor, "negative_control_count", negative_control_count
    )
    object.__setattr__(descriptor, "comparison_policies", comparison_policies)
    return descriptor


class ConditionerRegistry:
    """One insertion-ordered namespace shared by both classifications.

    The supported API and in-suite execution paths are the enforcement
    boundary.  Deliberate access to name-mangled storage is outside the threat
    model because name mangling is not a same-process security boundary.
    """

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

    def __register_descriptive(
        self,
        identifier: Any,
        conditioner: Any,
        metadata: Any,
    ) -> ConditionerDescriptor:
        with self.__lock:
            if self.__admission_in_progress:
                raise SpineError(
                    "registry mutation is forbidden during causal admission"
                )
            exact_identifier = _validate_identifier(identifier)
            exact_conditioner = _validate_conditioner(conditioner)
            frozen_metadata = _freeze_metadata(metadata)
            self.__require_available(exact_identifier, exact_conditioner)
            descriptor = _make_descriptor(
                identifier=exact_identifier,
                conditioner=exact_conditioner,
                classification=ConditionerClass.DESCRIPTIVE,
                label=DESCRIPTIVE_LABEL,
                metadata=frozen_metadata,
            )
            self.__entries[exact_identifier] = descriptor
            self.__callable_identifiers[id(exact_conditioner)] = exact_identifier
            return descriptor

    def __register_causal(
        self,
        identifier: Any,
        conditioner: Any,
        metadata: Any,
        locality_cases: Any,
        witness_checks: Any,
        negative_controls: Any,
    ) -> ConditionerDescriptor:
        with self.__lock:
            if self.__admission_in_progress:
                raise SpineError("nested causal admission is forbidden")
            exact_identifier = _validate_identifier(identifier)
            exact_conditioner = _validate_conditioner(conditioner)
            frozen_metadata = _freeze_metadata(metadata)
            cases, checks, controls = _validate_causal_suite(
                exact_conditioner,
                locality_cases,
                witness_checks,
                negative_controls,
            )
            case_snapshots = tuple(
                _snapshot_declaration(case) for case in cases
            )
            check_snapshots = tuple(
                (
                    _snapshot_declaration(check),
                    _snapshot_declaration(check.case),
                    _snapshot_declaration(check.witness),
                )
                for check in checks
            )
            control_snapshots = tuple(
                (
                    _snapshot_declaration(control),
                    _snapshot_declaration(control.case),
                    None
                    if control.witness is None
                    else _snapshot_declaration(control.witness),
                )
                for control in controls
            )
            comparison_policies = tuple(
                RegisteredComparison(
                    case_name=_snapshot_field(snapshot, "name"),
                    kind=_snapshot_field(snapshot, "comparison").kind,
                    atol=_snapshot_field(snapshot, "comparison").atol,
                    rtol=_snapshot_field(snapshot, "comparison").rtol,
                )
                for snapshot in case_snapshots
            )
            self.__require_available(exact_identifier, exact_conditioner)
            self.__admission_in_progress = True
            try:
                for case, snapshot in zip(cases, case_snapshots, strict=True):
                    if case.invoke is not exact_conditioner:
                        raise SpineError(
                            f"locality case {_snapshot_field(snapshot, 'name')!r} "
                            "no longer invokes "
                            "the exact conditioner callable at execution"
                        )
                    _assert_declaration_snapshot(
                        case,
                        snapshot,
                        f"locality case {_snapshot_field(snapshot, 'name')!r}",
                    )
                    run_dependency_locality(case)
                for check, snapshots in zip(
                    checks, check_snapshots, strict=True
                ):
                    check_snapshot, case_snapshot, witness_snapshot = snapshots
                    _assert_declaration_snapshot(
                        check,
                        check_snapshot,
                        "witness check",
                    )
                    if check.case.invoke is not exact_conditioner:
                        raise SpineError(
                            f"witness {_snapshot_field(witness_snapshot, 'name')!r} "
                            "case no longer "
                            "invokes the exact conditioner callable at execution"
                        )
                    _assert_declaration_snapshot(
                        check.case,
                        case_snapshot,
                        f"witness {_snapshot_field(witness_snapshot, 'name')!r} case",
                    )
                    _assert_declaration_snapshot(
                        check.witness,
                        witness_snapshot,
                        f"witness {_snapshot_field(witness_snapshot, 'name')!r}",
                    )
                    run_deterministic_witness(check.case, check.witness)
                for control, snapshots in zip(
                    controls, control_snapshots, strict=True
                ):
                    control_snapshot, case_snapshot, witness_snapshot = snapshots
                    control_name = _snapshot_field(control_snapshot, "name")
                    _assert_declaration_snapshot(
                        control,
                        control_snapshot,
                        f"negative control {control_name!r}",
                    )
                    expected_invoke = _snapshot_field(case_snapshot, "invoke")
                    if control.case.invoke is not expected_invoke:
                        raise SpineError(
                            f"negative control {control_name!r} case invoke "
                            "identity changed before execution"
                        )
                    _assert_declaration_snapshot(
                        control.case,
                        case_snapshot,
                        f"negative control {control_name!r} case",
                    )
                    if witness_snapshot is not None:
                        _assert_declaration_snapshot(
                            control.witness,
                            witness_snapshot,
                            f"negative control {control_name!r} witness",
                        )
                    _run_negative_control(control)
            finally:
                self.__admission_in_progress = False
            descriptor = _make_descriptor(
                identifier=exact_identifier,
                conditioner=exact_conditioner,
                classification=ConditionerClass.CAUSAL,
                label=CAUSAL_LABEL,
                metadata=frozen_metadata,
                locality_case_count=len(cases),
                witness_count=len(checks),
                negative_control_count=len(controls),
                comparison_policies=comparison_policies,
            )
            self.__entries[exact_identifier] = descriptor
            self.__callable_identifiers[id(exact_conditioner)] = exact_identifier
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


def _require_exact_tuple(
    value: Any, element_type: type[Any], description: str
) -> tuple[Any, ...]:
    if not isinstance(value, tuple) or not value:
        raise SpineError(
            f"{description} must be a non-empty tuple of {element_type.__name__}"
        )
    if any(type(item) is not element_type for item in value):
        raise SpineError(
            f"{description} must be a non-empty tuple of {element_type.__name__}"
        )
    return value


def _validate_causal_suite(
    conditioner: Callable[..., Any],
    locality_cases: Any,
    witness_checks: Any,
    negative_controls: Any,
) -> tuple[
    tuple[DependencyCase, ...],
    tuple[WitnessCheck, ...],
    tuple[NegativeControl, ...],
]:
    cases = _require_exact_tuple(
        locality_cases, DependencyCase, "locality cases"
    )
    checks = _require_exact_tuple(
        witness_checks, WitnessCheck, "witness checks"
    )
    controls = _require_exact_tuple(
        negative_controls, NegativeControl, "negative controls"
    )

    case_names: set[str] = set()
    for case in cases:
        if case.name in case_names:
            raise SpineError(f"duplicate locality case name {case.name!r}")
        case_names.add(case.name)
        if case.invoke is not conditioner:
            raise SpineError(
                f"locality case {case.name!r} does not invoke the exact "
                "conditioner callable being registered"
            )

    declared_case_ids = {id(case) for case in cases}
    witness_names: set[str] = set()
    for check in checks:
        if id(check.case) not in declared_case_ids:
            raise SpineError(
                f"witness {check.witness.name!r} must reference a declared "
                "locality case object"
            )
        if check.witness.name in witness_names:
            raise SpineError(
                f"duplicate deterministic witness name {check.witness.name!r}"
            )
        witness_names.add(check.witness.name)

    control_names: set[str] = set()
    required_failures: set[NegativeControlFailure] = set()
    for control in controls:
        if control.name in control_names:
            raise SpineError(f"duplicate negative control name {control.name!r}")
        control_names.add(control.name)
        required_failures.add(control.failure)
    if required_failures != set(NegativeControlFailure):
        raise SpineError(
            "negative controls must include locality-output and witness-output "
            "failure families"
        )
    return cases, checks, controls


def _run_negative_control(control: NegativeControl) -> None:
    try:
        if control.failure is NegativeControlFailure.LOCALITY_OUTPUT_CHANGE:
            run_dependency_locality(control.case)
        else:
            if control.witness is None:  # defended by NegativeControl validation
                raise SpineError("witness-output negative control lacks witness")
            run_deterministic_witness(control.case, control.witness)
    except DependencyCheckError as exc:
        comparison_failures = {
            DependencyFailure.EXACT_COMPARISON_MISMATCH,
            DependencyFailure.FLOAT_COMPARISON_MISMATCH,
        }
        if control.failure is NegativeControlFailure.LOCALITY_OUTPUT_CHANGE:
            valid_failure = (
                exc.check is DependencyCheck.LOCALITY
                and exc.failure in comparison_failures
            )
        else:
            valid_failure = (
                exc.check is DependencyCheck.WITNESS_CHANGED
                and exc.failure in comparison_failures
            )
        if not valid_failure:
            raise SpineError(
                f"negative control {control.name!r} used the wrong failure mechanism"
            ) from exc
        return
    except SpineError as exc:
        raise SpineError(
            f"negative control {control.name!r} used the wrong failure mechanism"
        ) from exc
    raise SpineError(f"negative control {control.name!r} unexpectedly passed")


def register_causal_conditioner(
    registry: ConditionerRegistry,
    identifier: str,
    conditioner: Callable[..., Any],
    *,
    metadata: Mapping[str, ImmutableMetadataValue],
    locality_cases: tuple[DependencyCase, ...],
    witness_checks: tuple[WitnessCheck, ...],
    negative_controls: tuple[NegativeControl, ...],
) -> ConditionerDescriptor:
    """Execute the complete empirical suite, then atomically admit once.

    Cases, witnesses, and negative controls are executable declarations, never
    cached results or pass certificates.  Successful execution is empirical
    admission evidence against those cases, not proof of causality.
    """

    exact_registry = _require_registry(registry)
    return exact_registry._ConditionerRegistry__register_causal(
        identifier,
        conditioner,
        metadata,
        locality_cases,
        witness_checks,
        negative_controls,
    )


def register_descriptive_conditioner(
    registry: ConditionerRegistry,
    identifier: str,
    conditioner: Callable[..., Any],
    *,
    metadata: Mapping[str, ImmutableMetadataValue],
) -> ConditionerDescriptor:
    """Insert a permanently noncausal descriptor without causal evidence."""

    exact_registry = _require_registry(registry)
    return exact_registry._ConditionerRegistry__register_descriptive(
        identifier, conditioner, metadata
    )
