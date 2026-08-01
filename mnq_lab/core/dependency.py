"""Market-free dependency declarations and adversarial locality checks.

Phase 6 supplies empirical admission infrastructure, not proof of causality.
Membership is declared by immutable event-time coordinates plus an immutable
boolean mask.  The locality runner mutates values only, exercises every
forbidden region with the ordinary test generator ``Generator(PCG64(0))`` plus
deterministic zero and dtype-extreme landmarks, and fails closed if the declared
output changes under the registered comparison policy.

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
    "DependencyCheck",
    "DependencyCheckError",
    "DependencyCase",
    "DependencyFailure",
    "DependencyInputs",
    "DeterministicWitness",
    "LocalityReport",
    "OutputComparison",
    "OutputKind",
    "WitnessReport",
    "run_dependency_locality",
    "run_deterministic_witness",
]

_TEST_SEED = 0
_VALUE_DTYPE_KINDS = frozenset("biuf")


class OutputKind(Enum):
    """The ratified comparison families for a declared output."""

    TICKS = "ticks"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    FLOAT = "float"


class DependencyCheck(Enum):
    """The executed check whose output comparison failed."""

    LOCALITY = "locality"
    WITNESS_BASELINE = "witness_baseline"
    WITNESS_CHANGED = "witness_changed"


class DependencyFailure(Enum):
    """Machine-readable output failure families; never inferred from prose."""

    SHAPE_MISMATCH = "shape_mismatch"
    DTYPE_MISMATCH = "dtype_mismatch"
    EXACT_COMPARISON_MISMATCH = "exact_comparison_mismatch"
    FLOAT_COMPARISON_MISMATCH = "float_comparison_mismatch"


class DependencyCheckError(SpineError):
    """A structured harness failure safe for negative-control dispatch."""

    def __init__(
        self,
        check: DependencyCheck,
        failure: DependencyFailure,
        message: str,
    ) -> None:
        if not isinstance(check, DependencyCheck):
            raise TypeError("check must be a DependencyCheck")
        if not isinstance(failure, DependencyFailure):
            raise TypeError("failure must be a DependencyFailure")
        if not isinstance(message, str) or not message:
            raise TypeError("message must be a non-empty string")
        self.check = check
        self.failure = failure
        super().__init__(message)


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

    original_shape = array.shape
    contiguous = np.ascontiguousarray(array)
    frozen = np.frombuffer(contiguous.tobytes(order="C"), dtype=contiguous.dtype)
    return frozen.reshape(original_shape)


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
    mutation_trial_count: int
    test_seed: int = _TEST_SEED


@dataclass(frozen=True)
class DeterministicWitness:
    """Hand-built in-window change with independently written expectations."""

    name: str
    changed_inputs: Mapping[str, np.ndarray]
    expected_baseline: np.ndarray
    expected_changed: np.ndarray
    affected_output_index: tuple[int, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise SpineError("witness name must be a non-empty string")
        if not isinstance(self.changed_inputs, Mapping):
            raise SpineError("witness changed_inputs must be a mapping")
        frozen_inputs: dict[str, np.ndarray] = {}
        for name, raw in self.changed_inputs.items():
            if not isinstance(name, str) or not name:
                raise SpineError("witness input names must be non-empty strings")
            array = _require_readonly_array(raw, f"witness input {name!r}")
            frozen_inputs[name] = _immutable_copy(array)
        expected_baseline = _require_readonly_array(
            self.expected_baseline, "witness expected_baseline"
        )
        expected_changed = _require_readonly_array(
            self.expected_changed, "witness expected_changed"
        )
        if not isinstance(self.affected_output_index, tuple):
            raise SpineError(
                "witness affected_output_index must be an immutable tuple"
            )
        object.__setattr__(
            self, "changed_inputs", MappingProxyType(frozen_inputs)
        )
        object.__setattr__(
            self, "expected_baseline", _immutable_copy(expected_baseline)
        )
        object.__setattr__(
            self, "expected_changed", _immutable_copy(expected_changed)
        )


@dataclass(frozen=True)
class WitnessReport:
    """Diagnostic facts from one executed witness; never admission proof."""

    case_name: str
    witness_name: str
    changed_input_count: int
    affected_output_index: tuple[int, ...]


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
    check: DependencyCheck,
) -> None:
    if actual.shape != expected.shape:
        raise DependencyCheckError(
            check,
            DependencyFailure.SHAPE_MISMATCH,
            f"{context} output shape {actual.shape} does not match "
            f"expected shape {expected.shape}",
        )
    if actual.dtype != expected.dtype:
        raise DependencyCheckError(
            check,
            DependencyFailure.DTYPE_MISMATCH,
            f"{context} output dtype {actual.dtype} does not match "
            f"expected dtype {expected.dtype}",
        )
    if policy.kind is not OutputKind.FLOAT:
        if not _bit_identical(actual, expected):
            raise DependencyCheckError(
                check,
                DependencyFailure.EXACT_COMPARISON_MISMATCH,
                f"{context} exact comparison failed",
            )
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
        raise DependencyCheckError(
            check,
            DependencyFailure.FLOAT_COMPARISON_MISMATCH,
            f"{context} floating comparison failed at flat index {flat_index}: "
            f"difference {difference.flat[flat_index]!r} exceeds "
            f"atol + rtol * abs(expected) = {allowed.flat[flat_index]!r}",
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
    float_limit = np.longdouble(np.finfo(dtype).max)
    if -float_limit <= candidate_wide <= float_limit:
        candidate = np.asarray(candidate_wide, dtype=dtype)[()]
    else:
        candidate = np.asarray(np.nan, dtype=dtype)[()]
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


def _mutated_region_input(
    case: DependencyCase,
    region: np.ndarray,
    input_name: str,
    rng: np.random.Generator,
) -> tuple[dict[str, np.ndarray], int]:
    mutated = {name: np.array(array, copy=True) for name, array in case.inputs.items()}
    array = mutated[input_name]
    baseline = np.array(array, copy=True)
    changed = 0
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


def _landmark_targets(dtype: np.dtype) -> tuple[tuple[str, np.generic], ...]:
    if dtype.kind == "b":
        return (
            ("false", np.asarray(False, dtype=dtype)[()]),
            ("true", np.asarray(True, dtype=dtype)[()]),
        )
    if dtype.kind in "iu":
        info = np.iinfo(dtype)
        candidates = (
            ("zero", 0),
            ("minimum", int(info.min)),
            ("maximum", int(info.max)),
        )
    else:
        limit = np.finfo(dtype).max
        candidates = (
            ("zero", 0.0),
            ("minimum", -limit),
            ("maximum", limit),
        )

    targets: list[tuple[str, np.generic]] = []
    seen: set[bytes] = set()
    for name, value in candidates:
        target = np.asarray(value, dtype=dtype)[()]
        signature = target.tobytes()
        if signature not in seen:
            targets.append((name, target))
            seen.add(signature)
    return tuple(targets)


def _landmark_region_input(
    case: DependencyCase,
    region: np.ndarray,
    input_name: str,
    target: np.generic,
) -> tuple[dict[str, np.ndarray], int] | None:
    mutated = {
        name: np.array(array, copy=True) for name, array in case.inputs.items()
    }
    array = mutated[input_name]
    baseline = np.array(array, copy=True)
    array[region] = target
    changed = sum(
        int(_element_changed(baseline[index], array[index])) for index in region
    )
    if changed == 0:
        return None
    outside = np.ones(array.size, dtype=np.bool_)
    outside[region] = False
    if not np.array_equal(array[outside], baseline[outside]):
        raise SpineError("landmark mutation changed values outside its region")
    return mutated, changed


def _region_mutation_trials(
    case: DependencyCase,
    region: np.ndarray,
    input_name: str,
    rng: np.random.Generator,
) -> tuple[tuple[str, dict[str, np.ndarray], int], ...]:
    random_mutated, random_changed = _mutated_region_input(
        case, region, input_name, rng
    )
    trials = [("pcg64", random_mutated, random_changed)]
    seen = {random_mutated[input_name].tobytes(order="C")}
    dtype = case.inputs[input_name].dtype
    for name, target in _landmark_targets(dtype):
        result = _landmark_region_input(case, region, input_name, target)
        if result is None:
            continue
        mutated, changed = result
        signature = mutated[input_name].tobytes(order="C")
        if signature in seen:
            continue
        trials.append((name, mutated, changed))
        seen.add(signature)
    return tuple(trials)


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
    trial_count = 0
    for region_index, region in enumerate(regions):
        region_changed = 0
        for input_name in case.inputs:
            trials = _region_mutation_trials(case, region, input_name, rng)
            for probe_name, mutated, changed in trials:
                context = (
                    f"out-of-window region {region_index} input {input_name!r} "
                    f"probe {probe_name!r}"
                )
                output = _invoke_stably(case, mutated, context)
                try:
                    _compare_outputs(
                        output,
                        baseline,
                        case.comparison,
                        context,
                        DependencyCheck.LOCALITY,
                    )
                except DependencyCheckError as exc:
                    raise DependencyCheckError(
                        exc.check,
                        exc.failure,
                        f"case {case.name!r}: {context} changed output: {exc}",
                    ) from exc
                region_changed += changed
                trial_count += 1
        region_sizes.append(int(region.size))
        changed_counts.append(region_changed)

    return LocalityReport(
        case_name=case.name,
        forbidden_region_count=len(regions),
        forbidden_region_sizes=tuple(region_sizes),
        changed_value_counts=tuple(changed_counts),
        mutation_trial_count=trial_count,
    )


def _validated_witness_inputs(
    case: DependencyCase, witness: DeterministicWitness
) -> tuple[Mapping[str, np.ndarray], int]:
    if not isinstance(witness.changed_inputs, Mapping) or set(
        witness.changed_inputs
    ) != set(case.inputs):
        raise SpineError(
            "witness changed_inputs must have exactly the same names as "
            "the dependency case inputs"
        )

    validated: dict[str, np.ndarray] = {}
    changed_count = 0
    for name, baseline in case.inputs.items():
        raw = _require_readonly_array(
            witness.changed_inputs[name], f"witness input {name!r}"
        )
        if raw.shape != baseline.shape:
            raise SpineError(
                f"witness input {name!r} shape {raw.shape} does not match "
                f"baseline shape {baseline.shape}"
            )
        if raw.dtype != baseline.dtype:
            raise SpineError(
                f"witness input {name!r} dtype {raw.dtype} does not match "
                f"baseline dtype {baseline.dtype}"
            )
        if raw.dtype.kind == "f" and not np.isfinite(raw).all():
            raise SpineError(f"witness input {name!r} contains non-finite values")
        changed = np.asarray(
            [
                _element_changed(baseline[index], raw[index])
                for index in range(baseline.size)
            ],
            dtype=np.bool_,
        )
        forbidden_change = changed & ~case.allowed_dependency_mask
        if np.any(forbidden_change):
            index = int(np.flatnonzero(forbidden_change)[0])
            raise SpineError(
                f"witness changed out-of-window input {name!r} at index {index}"
            )
        changed_count += int(np.count_nonzero(changed))
        validated[name] = _immutable_copy(raw)

    if changed_count == 0:
        raise SpineError("witness must change at least one in-window input value")
    return MappingProxyType(validated), changed_count


def _validated_affected_index(
    raw_index: Any, output_shape: tuple[int, ...]
) -> tuple[int, ...]:
    if not isinstance(raw_index, tuple):
        raise SpineError("witness affected_output_index must be an immutable tuple")
    if len(raw_index) != len(output_shape):
        raise SpineError(
            "witness affected output index rank must match expected output rank"
        )
    index: list[int] = []
    for axis, value in enumerate(raw_index):
        if isinstance(value, (bool, np.bool_)) or not isinstance(
            value, (int, np.integer)
        ):
            raise SpineError(
                "witness affected output index components must be integers"
            )
        position = int(value)
        if position < 0 or position >= output_shape[axis]:
            raise SpineError("witness affected output index is out of bounds")
        index.append(position)
    return tuple(index)


def _validated_witness_expectations(
    case: DependencyCase, witness: DeterministicWitness
) -> tuple[np.ndarray, np.ndarray, tuple[int, ...]]:
    raw_baseline = _require_readonly_array(
        witness.expected_baseline, "witness expected_baseline"
    )
    raw_changed = _require_readonly_array(
        witness.expected_changed, "witness expected_changed"
    )
    expected_baseline = _validate_output(
        raw_baseline, case.comparison, "witness expected_baseline"
    )
    expected_changed = _validate_output(
        raw_changed, case.comparison, "witness expected_changed"
    )
    if expected_baseline.shape != expected_changed.shape:
        raise SpineError("witness expected outputs must have the same shape")
    if expected_baseline.dtype != expected_changed.dtype:
        raise SpineError("witness expected outputs must have the same dtype")
    index = _validated_affected_index(
        witness.affected_output_index, expected_baseline.shape
    )

    baseline_value = expected_baseline[index]
    changed_value = expected_changed[index]
    if case.comparison.kind is not OutputKind.FLOAT:
        if not _element_changed(baseline_value, changed_value):
            raise SpineError(
                "witness is vacuous at the required affected output element"
            )
        return expected_baseline, expected_changed, index

    baseline_wide = np.longdouble(baseline_value)
    changed_wide = np.longdouble(changed_value)
    baseline_band = np.longdouble(case.comparison.atol) + np.longdouble(
        case.comparison.rtol
    ) * np.abs(baseline_wide)
    changed_band = np.longdouble(case.comparison.atol) + np.longdouble(
        case.comparison.rtol
    ) * np.abs(changed_wide)
    separation = np.abs(changed_wide - baseline_wide)
    if not separation > baseline_band + changed_band:
        raise SpineError(
            "floating witness must have disjoint baseline and changed "
            "comparison bands at the required affected output element"
        )
    return expected_baseline, expected_changed, index


def run_deterministic_witness(
    case: DependencyCase, witness: DeterministicWitness
) -> WitnessReport:
    """Execute one independently specified, non-vacuous in-window witness."""

    if not isinstance(case, DependencyCase):
        raise SpineError("case must be a DependencyCase")
    if not isinstance(witness, DeterministicWitness):
        raise SpineError("witness must be a DeterministicWitness")
    if not isinstance(witness.name, str) or not witness.name:
        raise SpineError("witness name must be a non-empty string")

    changed_inputs, changed_count = _validated_witness_inputs(case, witness)
    expected_baseline, expected_changed, index = _validated_witness_expectations(
        case, witness
    )
    baseline_output = _invoke_stably(case, case.inputs, "witness baseline")
    changed_output = _invoke_stably(case, changed_inputs, "witness changed")
    _compare_outputs(
        baseline_output,
        expected_baseline,
        case.comparison,
        "witness baseline",
        DependencyCheck.WITNESS_BASELINE,
    )
    _compare_outputs(
        changed_output,
        expected_changed,
        case.comparison,
        "witness changed",
        DependencyCheck.WITNESS_CHANGED,
    )
    return WitnessReport(
        case_name=case.name,
        witness_name=witness.name,
        changed_input_count=changed_count,
        affected_output_index=index,
    )
