"""Market-free dependency declarations and adversarial locality checks.

Phase 6 supplies empirical admission infrastructure, not proof of causality.
Membership is declared by immutable event-time coordinates plus an immutable
boolean mask.  The locality runner mutates values only, exercises every
forbidden region with the ordinary test generator ``Generator(PCG64(0))``, and
fails closed if the declared output changes under the registered comparison
policy.

This module knows nothing about markets, stores, studies, confirmation, or
conditioner semantics.  Whether a future real callable declared the correct
minimally sufficient window remains a Phase 7 obligation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from numbers import Real
from types import MappingProxyType
from typing import Any

import numpy as np

from mnq_lab import SpineError

__all__ = [
    "DependencyCase",
    "DependencyInputs",
    "LocalityReport",
    "OutputComparison",
    "OutputKind",
    "run_dependency_locality",
]

_TEST_SEED = 0
_VALUE_DTYPE_KINDS = frozenset("biuf")


class OutputKind(Enum):
    """The ratified comparison families for a declared output."""

    TICKS = "ticks"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    FLOAT = "float"


def _finite_nonnegative_tolerance(value: Any, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise SpineError(f"{name} must be a finite non-bool nonnegative real")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpineError(
            f"{name} must be a finite non-bool nonnegative real"
        ) from exc
    if not np.isfinite(result):
        raise SpineError(f"{name} must be finite")
    if result < 0.0:
        raise SpineError(f"{name} must be nonnegative")
    return result


@dataclass(frozen=True)
class OutputComparison:
    """Immutable exact or floating output-comparison policy."""

    kind: OutputKind
    atol: float = 0.0
    rtol: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.kind, OutputKind):
            raise SpineError("comparison kind must be an OutputKind")
        atol = _finite_nonnegative_tolerance(self.atol, "atol")
        rtol = _finite_nonnegative_tolerance(self.rtol, "rtol")
        if self.kind is not OutputKind.FLOAT and (atol != 0.0 or rtol != 0.0):
            raise SpineError(
                "exact tick, integer, and boolean comparison forbids tolerance"
            )
        object.__setattr__(self, "atol", atol)
        object.__setattr__(self, "rtol", rtol)


def _immutable_copy(array: np.ndarray) -> np.ndarray:
    """Return an owned-by-immutable-bytes C-order copy."""

    contiguous = np.ascontiguousarray(array)
    frozen = np.frombuffer(contiguous.tobytes(order="C"), dtype=contiguous.dtype)
    return frozen.reshape(contiguous.shape)


def _require_readonly_array(value: Any, name: str) -> np.ndarray:
    if not isinstance(value, np.ndarray):
        raise SpineError(f"{name} must be an immutable numpy array")
    if value.flags.writeable:
        raise SpineError(f"{name} must be immutable (writeable=False)")
    return value


def _validate_coordinates(value: Any) -> np.ndarray:
    array = _require_readonly_array(value, "coordinates_ns")
    if array.dtype != np.int64:
        raise SpineError("coordinates_ns must have dtype int64")
    if array.ndim != 1:
        raise SpineError("coordinates_ns must be one-dimensional")
    if array.size == 0:
        raise SpineError("coordinates_ns must be non-empty")
    if np.any(array[1:] <= array[:-1]):
        raise SpineError("coordinates_ns must be strictly increasing")
    return _immutable_copy(array)


def _validate_allowed_mask(value: Any, size: int) -> np.ndarray:
    array = _require_readonly_array(value, "allowed_dependency_mask")
    if array.dtype != np.bool_:
        raise SpineError("allowed_dependency_mask must have boolean dtype")
    if array.ndim != 1:
        raise SpineError("allowed_dependency_mask must be one-dimensional")
    if array.size != size:
        raise SpineError(
            "allowed_dependency_mask length must equal coordinates_ns length"
        )
    if not np.any(array):
        raise SpineError(
            "allowed_dependency_mask must contain at least one in-window value"
        )
    if np.all(array):
        raise SpineError(
            "allowed_dependency_mask must contain at least one out-of-window value"
        )
    return _immutable_copy(array)


def _validate_inputs(value: Any, size: int) -> Mapping[str, np.ndarray]:
    if not isinstance(value, Mapping) or not value:
        raise SpineError("inputs must be a non-empty mapping")

    validated: dict[str, np.ndarray] = {}
    for name, raw in value.items():
        if not isinstance(name, str) or not name:
            raise SpineError("input names must be non-empty strings")
        array = _require_readonly_array(raw, f"input {name!r}")
        if array.ndim != 1:
            raise SpineError(f"input {name!r} must be one-dimensional")
        if array.size != size:
            raise SpineError(
                f"input {name!r} length must equal coordinates_ns length"
            )
        if array.dtype.kind not in _VALUE_DTYPE_KINDS:
            raise SpineError(
                f"input {name!r} dtype {array.dtype} is not bool, integer, "
                "unsigned integer, or floating"
            )
        if array.dtype.kind == "f" and not np.isfinite(array).all():
            raise SpineError(f"input {name!r} contains non-finite values")
        validated[name] = _immutable_copy(array)
    return MappingProxyType(validated)


@dataclass(frozen=True)
class DependencyInputs:
    """Fresh immutable invocation inputs supplied to the callable."""

    coordinates_ns: np.ndarray
    values: Mapping[str, np.ndarray]


@dataclass(frozen=True)
class DependencyCase:
    """One declared dependency window for one explicitly invoked output."""

    name: str
    coordinates_ns: np.ndarray
    allowed_dependency_mask: np.ndarray
    inputs: Mapping[str, np.ndarray]
    invoke: Callable[[DependencyInputs], Any]
    comparison: OutputComparison

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise SpineError("dependency case name must be a non-empty string")
        coordinates = _validate_coordinates(self.coordinates_ns)
        allowed = _validate_allowed_mask(
            self.allowed_dependency_mask, coordinates.size
        )
        inputs = _validate_inputs(self.inputs, coordinates.size)
        if not callable(self.invoke):
            raise SpineError("dependency case invoke must be callable")
        if not isinstance(self.comparison, OutputComparison):
            raise SpineError(
                "dependency case comparison must be an OutputComparison"
            )
        object.__setattr__(self, "coordinates_ns", coordinates)
        object.__setattr__(self, "allowed_dependency_mask", allowed)
        object.__setattr__(self, "inputs", inputs)


@dataclass(frozen=True)
class LocalityReport:
    """Diagnostic facts from one executed locality run; never admission proof."""

    case_name: str
    forbidden_region_count: int
    forbidden_region_sizes: tuple[int, ...]
    changed_value_counts: tuple[int, ...]
    test_seed: int = _TEST_SEED


def _validate_output(raw: Any, policy: OutputComparison, context: str) -> np.ndarray:
    array = np.asarray(raw)
    if array.size == 0:
        raise SpineError(f"{context} output must be non-empty")
    if policy.kind is OutputKind.BOOLEAN:
        valid_dtype = array.dtype == np.bool_
    elif policy.kind in (OutputKind.INTEGER, OutputKind.TICKS):
        valid_dtype = array.dtype.kind in "iu" and array.dtype != np.bool_
    else:
        valid_dtype = array.dtype.kind == "f"
    if not valid_dtype:
        raise SpineError(
            f"{context} output dtype {array.dtype} is invalid for "
            f"{policy.kind.value} comparison"
        )
    if array.dtype.kind == "f" and not np.isfinite(array).all():
        raise SpineError(f"{context} output contains non-finite values")
    return _immutable_copy(array)


def _bit_identical(left: np.ndarray, right: np.ndarray) -> bool:
    return (
        left.shape == right.shape
        and left.dtype == right.dtype
        and left.tobytes(order="C") == right.tobytes(order="C")
    )


def _compare_outputs(
    actual: np.ndarray,
    expected: np.ndarray,
    policy: OutputComparison,
    context: str,
) -> None:
    if actual.shape != expected.shape:
        raise SpineError(
            f"{context} output shape {actual.shape} does not match "
            f"expected shape {expected.shape}"
        )
    if actual.dtype != expected.dtype:
        raise SpineError(
            f"{context} output dtype {actual.dtype} does not match "
            f"expected dtype {expected.dtype}"
        )
    if policy.kind is not OutputKind.FLOAT:
        if not _bit_identical(actual, expected):
            raise SpineError(f"{context} exact comparison failed")
        return

    actual_wide = actual.astype(np.longdouble)
    expected_wide = expected.astype(np.longdouble)
    difference = np.abs(actual_wide - expected_wide)
    allowed = np.longdouble(policy.atol) + np.longdouble(policy.rtol) * np.abs(
        expected_wide
    )
    mismatch = difference > allowed
    if np.any(mismatch):
        flat_index = int(np.flatnonzero(mismatch)[0])
        raise SpineError(
            f"{context} floating comparison failed at flat index {flat_index}: "
            f"difference {difference.flat[flat_index]!r} exceeds "
            f"atol + rtol * abs(expected) = {allowed.flat[flat_index]!r}"
        )


def _fresh_invocation(
    case: DependencyCase, values: Mapping[str, np.ndarray]
) -> DependencyInputs:
    coordinates = _immutable_copy(case.coordinates_ns)
    fresh_values = {
        name: _immutable_copy(np.asarray(values[name])) for name in case.inputs
    }
    return DependencyInputs(coordinates, MappingProxyType(fresh_values))


def _invoke_once(
    case: DependencyCase, values: Mapping[str, np.ndarray], context: str
) -> np.ndarray:
    call = _fresh_invocation(case, values)
    coordinate_snapshot = call.coordinates_ns.tobytes(order="C")
    value_snapshots = {
        name: array.tobytes(order="C") for name, array in call.values.items()
    }
    try:
        raw_output = case.invoke(call)
    except Exception as exc:
        raise SpineError(f"case {case.name!r} callable raised: {exc}") from exc
    if call.coordinates_ns.tobytes(order="C") != coordinate_snapshot:
        raise SpineError(f"case {case.name!r} callable mutated coordinates_ns")
    for name, array in call.values.items():
        if array.tobytes(order="C") != value_snapshots[name]:
            raise SpineError(f"case {case.name!r} callable mutated input {name!r}")
    return _validate_output(raw_output, case.comparison, context)


def _invoke_stably(
    case: DependencyCase, values: Mapping[str, np.ndarray], context: str
) -> np.ndarray:
    first = _invoke_once(case, values, context)
    second = _invoke_once(case, values, context)
    if not _bit_identical(first, second):
        raise SpineError(
            f"case {case.name!r} produced nondeterministic output on "
            "identical fresh inputs"
        )
    return first


def _forbidden_regions(mask: np.ndarray) -> tuple[np.ndarray, ...]:
    forbidden = np.flatnonzero(~mask)
    split_points = np.flatnonzero(np.diff(forbidden) > 1) + 1
    return tuple(np.asarray(region, dtype=np.intp) for region in np.split(forbidden, split_points))


def _mutate_scalar(value: np.generic, dtype: np.dtype, rng: np.random.Generator):
    if dtype.kind == "b":
        rng.integers(0, 2, dtype=np.int8)
        return np.bool_(not bool(value))

    direction = 1 if int(rng.integers(0, 2, dtype=np.int8)) else -1
    if dtype.kind in "iu":
        info = np.iinfo(dtype)
        magnitude = int(rng.integers(1, 1025))
        candidate = int(value) + direction * magnitude
        if candidate < int(info.min) or candidate > int(info.max):
            candidate = int(value) - direction * magnitude
        if candidate < int(info.min) or candidate > int(info.max):
            candidate = int(info.min) if int(value) != int(info.min) else int(info.max)
        return np.asarray(candidate, dtype=dtype)[()]

    factor = np.longdouble(rng.uniform(0.5, 1.5))
    value_wide = np.longdouble(value)
    magnitude = (np.abs(value_wide) + np.longdouble(1.0)) * factor
    candidate_wide = value_wide + np.longdouble(direction) * magnitude
    candidate = np.asarray(candidate_wide, dtype=dtype)[()]
    if not np.isfinite(candidate) or candidate == value:
        candidate = np.asarray(-value_wide, dtype=dtype)[()]
    if not np.isfinite(candidate) or candidate == value:
        target = np.inf if direction > 0 else -np.inf
        candidate = np.nextafter(value, target, dtype=dtype)
    if not np.isfinite(candidate) or candidate == value:
        opposite = -np.inf if direction > 0 else np.inf
        candidate = np.nextafter(value, opposite, dtype=dtype)
    if not np.isfinite(candidate) or candidate == value:
        raise SpineError("deterministic out-of-window mutation was a no-op")
    return candidate


def _element_changed(left: np.generic, right: np.generic) -> bool:
    return left.tobytes() != right.tobytes()


def _mutated_region_inputs(
    case: DependencyCase,
    region: np.ndarray,
    rng: np.random.Generator,
) -> tuple[dict[str, np.ndarray], int]:
    mutated = {name: np.array(array, copy=True) for name, array in case.inputs.items()}
    changed = 0
    for array in mutated.values():
        baseline = np.array(array, copy=True)
        for index in region:
            array[index] = _mutate_scalar(array[index], array.dtype, rng)
            changed += int(_element_changed(baseline[index], array[index]))
        outside = np.ones(array.size, dtype=np.bool_)
        outside[region] = False
        if not np.array_equal(array[outside], baseline[outside]):
            raise SpineError("out-of-window mutation changed values outside its region")
    if changed == 0:
        raise SpineError("deterministic out-of-window mutation was a no-op")
    return mutated, changed


def run_dependency_locality(case: DependencyCase) -> LocalityReport:
    """Execute every declared forbidden-region locality comparison.

    The returned report is diagnostic only.  The future causal registry is
    required to execute this function inside registration and must never accept
    a caller-created report as admission evidence.
    """

    if not isinstance(case, DependencyCase):
        raise SpineError("case must be a DependencyCase")
    baseline = _invoke_stably(case, case.inputs, "baseline")
    regions = _forbidden_regions(case.allowed_dependency_mask)
    if not regions:
        raise SpineError("dependency case has no out-of-window region")

    rng = np.random.Generator(np.random.PCG64(_TEST_SEED))
    region_sizes: list[int] = []
    changed_counts: list[int] = []
    for region_index, region in enumerate(regions):
        mutated, changed = _mutated_region_inputs(case, region, rng)
        output = _invoke_stably(
            case, mutated, f"out-of-window region {region_index}"
        )
        try:
            _compare_outputs(
                output,
                baseline,
                case.comparison,
                f"out-of-window region {region_index}",
            )
        except SpineError as exc:
            raise SpineError(
                f"case {case.name!r}: out-of-window region {region_index} "
                f"changed output: {exc}"
            ) from exc
        region_sizes.append(int(region.size))
        changed_counts.append(changed)

    return LocalityReport(
        case_name=case.name,
        forbidden_region_count=len(regions),
        forbidden_region_sizes=tuple(region_sizes),
        changed_value_counts=tuple(changed_counts),
    )
