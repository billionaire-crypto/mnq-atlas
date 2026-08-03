"""Joint whole-session uncertainty for every valid Phase 8 point request."""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral
from pathlib import Path
from typing import Any, Hashable

import numpy as np

from mnq_lab import SpineError
from mnq_lab.constants import load_bootstrap_constants
from mnq_lab.core.bootstrap import (
    apply_group_multiplicities,
    percentile_interval,
    stationary_group_resample,
)
from mnq_lab.phase8.contrasts import (
    prepare_weighted_quantile_ticks,
    statistic_probability,
    weighted_quantile_ticks,
)
from mnq_lab.phase8.diagnostics import StatusDecision, resolve_status

ROOT_ENTROPY = (20260801, 8, 13, 1)
BLOCK_LENGTHS = (1, 5, 10, 20)
DRAWS_PER_BLOCK_LENGTH = 4_999
CONFIDENCE_LEVEL = 0.95
PRIMARY_BLOCK_LENGTH = 5

HISTORICAL_MIXTURE_DISCLOSURE = (
    "This interval measures uncertainty within the historical mixture, not "
    "uncertainty about future regime change."
)
CONDITIONER_UNCERTAINTY_DISCLOSURE = (
    "Conditioner-estimation uncertainty is excluded by construction; alternative "
    "definitions and cell migration make that sensitivity visible instead."
)
WEIGHT_ESS_DISCLOSURE = (
    "weight_ess corrects no serial dependence, overlapping outcome windows or "
    "regime dependence."
)

_INT32_INFO = np.iinfo(np.int32)
_INT64_INFO = np.iinfo(np.int64)

__all__ = [
    "BLOCK_LENGTHS",
    "CONFIDENCE_LEVEL",
    "CONDITIONER_UNCERTAINTY_DISCLOSURE",
    "DRAWS_PER_BLOCK_LENGTH",
    "HISTORICAL_MIXTURE_DISCLOSURE",
    "PRIMARY_BLOCK_LENGTH",
    "ROOT_ENTROPY",
    "WEIGHT_ESS_DISCLOSURE",
    "BootstrapContract",
    "BootstrapInteractionRequest",
    "BootstrapIntervalRequest",
    "BootstrapIntervalRow",
    "BootstrapQuantileTerm",
    "JointBootstrapResult",
    "RequestBootstrapResult",
    "bootstrap_contract",
    "interval_conclusion_reversal",
    "joint_bootstrap_intervals",
]


@dataclass(frozen=True)
class BootstrapContract:
    scheme: str
    root_entropy: tuple[int, int, int, int]
    block_lengths: tuple[int, int, int, int]
    draws_per_block_length: int
    confidence_level: float
    primary_block_length: int
    child_spawn_keys: tuple[tuple[int, ...], ...]
    bit_generator: str
    truncate_partial_session: bool
    early_stopping: bool


@dataclass(frozen=True)
class BootstrapQuantileTerm:
    term_id: Hashable
    values: np.ndarray
    eligibility_mask: np.ndarray
    weights: np.ndarray
    statistic: str

    def __post_init__(self) -> None:
        _validate_identifier(self.term_id, "term_id")
        values = _tick_vector(self.values)
        mask = _bool_vector(self.eligibility_mask, "eligibility_mask")
        weights = _weight_vector(self.weights)
        if values.size != mask.size or values.size != weights.size:
            raise SpineError("bootstrap term vectors must have equal full-frame length")
        if not bool(np.any(mask)):
            raise SpineError("bootstrap term eligibility mask must contain support")
        if bool(np.any(weights[~mask] != 0.0)):
            raise SpineError("bootstrap term weights must be zero outside eligibility")
        if not bool(np.any(weights[mask] > 0.0)):
            raise SpineError("bootstrap term must have positive eligible weight mass")
        statistic_probability(self.statistic)
        values.setflags(write=False)
        mask.setflags(write=False)
        weights.setflags(write=False)
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "eligibility_mask", mask)
        object.__setattr__(self, "weights", weights)


@dataclass(frozen=True)
class BootstrapIntervalRequest:
    request_id: Hashable
    target_term_id: Hashable
    baseline_term_id: Hashable | None
    status: StatusDecision

    def __post_init__(self) -> None:
        _validate_identifier(self.request_id, "request_id")
        _validate_identifier(self.target_term_id, "target_term_id")
        if self.baseline_term_id is not None:
            _validate_identifier(self.baseline_term_id, "baseline_term_id")
            if self.baseline_term_id == self.target_term_id:
                raise SpineError("target and baseline term ids must differ")
        if not isinstance(self.status, StatusDecision):
            raise SpineError("bootstrap request status must be a StatusDecision")


@dataclass(frozen=True)
class BootstrapInteractionRequest:
    request_id: Hashable
    term_ids: tuple[Hashable, Hashable, Hashable, Hashable]
    status: str

    def __post_init__(self) -> None:
        _validate_identifier(self.request_id, "request_id")
        if not isinstance(self.term_ids, tuple) or len(self.term_ids) != 4:
            raise SpineError("interaction request requires exactly four distinct terms")
        for term_id in self.term_ids:
            _validate_identifier(term_id, "interaction term_id")
        if len(set(self.term_ids)) != 4:
            raise SpineError("interaction request requires exactly four distinct terms")
        if not isinstance(self.status, str) or self.status != "ok":
            raise SpineError("bootstrap accepts only ok interaction rows")


@dataclass(frozen=True)
class BootstrapIntervalRow:
    request_id: Hashable
    mean_block_sessions: int
    draws: int
    confidence_level: float
    ci_lower_ticks: int
    ci_upper_ticks: int
    interval_valid: bool
    is_primary: bool
    rng_root_entropy: tuple[int, int, int, int]
    rng_child_spawn_key: tuple[int, ...]
    historical_mixture_disclosure: str
    conditioner_uncertainty_disclosure: str
    weight_ess_disclosure: str


@dataclass(frozen=True)
class RequestBootstrapResult:
    request_id: Hashable
    intervals: tuple[BootstrapIntervalRow, ...]
    block_5_10_reversal: bool


@dataclass(frozen=True)
class JointBootstrapResult:
    contract: BootstrapContract
    requests: tuple[RequestBootstrapResult, ...]


def _validate_identifier(value: Any, name: str) -> Hashable:
    if isinstance(value, (bool, np.bool_)) or value is None:
        raise SpineError(f"{name} must be a non-bool hashable identifier")
    try:
        hash(value)
    except TypeError as exc:
        raise SpineError(f"{name} must be a non-bool hashable identifier") from exc
    return value


def _one_dimensional(values: Any, name: str) -> np.ndarray:
    try:
        array = np.asarray(values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpineError(f"{name} cannot be converted to an array: {exc}") from exc
    if array.ndim != 1:
        raise SpineError(f"{name} must be one-dimensional, got ndim={array.ndim}")
    return array


def _tick_vector(values: Any) -> np.ndarray:
    array = _one_dimensional(values, "values")
    if array.size == 0 or array.dtype.kind != "i":
        raise SpineError("bootstrap values must be nonempty signed integer ticks")
    if bool(np.any(array < _INT32_INFO.min) or np.any(array > _INT32_INFO.max)):
        raise SpineError("bootstrap tick values must remain within int32 storage range")
    return array.copy()


def _bool_vector(values: Any, name: str) -> np.ndarray:
    array = _one_dimensional(values, name)
    if array.dtype.kind != "b":
        raise SpineError(f"{name} must be a one-dimensional bool array")
    return array.astype(np.bool_, copy=True)


def _weight_vector(values: Any) -> np.ndarray:
    array = _one_dimensional(values, "weights")
    object_view = np.asarray(values, dtype=object)
    if any(isinstance(value, (bool, np.bool_)) for value in object_view.flat):
        raise SpineError("bootstrap weights must be finite nonnegative reals")
    if array.dtype.kind not in {"i", "u", "f"}:
        raise SpineError("bootstrap weights must be finite nonnegative reals")
    converted = array.astype(np.float64, copy=True)
    if not bool(np.isfinite(converted).all()) or bool(np.any(converted < 0.0)):
        raise SpineError("bootstrap weights must be finite nonnegative reals")
    return converted


def bootstrap_contract(constants_path: Path | None = None) -> BootstrapContract:
    """Load the frozen core bootstrap mapping and add Phase 8-only constants."""
    loaded = load_bootstrap_constants(constants_path)
    block_lengths = tuple(loaded["block_sensitivity"])
    if block_lengths != BLOCK_LENGTHS:
        raise SpineError(
            f"Phase 8 block lengths must be exactly {BLOCK_LENGTHS}; got {block_lengths}"
        )
    if loaded["mean_block_sessions_primary"] != PRIMARY_BLOCK_LENGTH:
        raise SpineError("Phase 8 primary block length must be exactly 5 sessions")
    if loaded["truncate_partial_session"] is not False:
        raise SpineError("Phase 8 may not truncate a partial session")
    root = np.random.SeedSequence(ROOT_ENTROPY)
    children = root.spawn(len(BLOCK_LENGTHS))
    return BootstrapContract(
        scheme=loaded["scheme"],
        root_entropy=ROOT_ENTROPY,
        block_lengths=BLOCK_LENGTHS,
        draws_per_block_length=DRAWS_PER_BLOCK_LENGTH,
        confidence_level=CONFIDENCE_LEVEL,
        primary_block_length=PRIMARY_BLOCK_LENGTH,
        child_spawn_keys=tuple(tuple(child.spawn_key) for child in children),
        bit_generator="PCG64",
        truncate_partial_session=False,
        early_stopping=False,
    )


def _validated_status(decision: StatusDecision) -> None:
    resolved = resolve_status(decision.status_flags)
    if (
        resolved.status != decision.status
        or resolved.failure_states != decision.failure_states
    ):
        raise SpineError("bootstrap request carries an inconsistent status")
    if decision.status != "ok":
            raise SpineError("Phase 8 intervals accept only ok point rows")


def _exact_interval_tick(value: Any) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.number)):
        raise SpineError("bootstrap produced a non-integral interval endpoint")
    numeric = float(value)
    if not np.isfinite(numeric):
        raise SpineError("bootstrap produced a non-finite interval endpoint")
    if not numeric.is_integer():
        raise SpineError("bootstrap produced a non-integral interval endpoint")
    if numeric < _INT64_INFO.min or numeric > _INT64_INFO.max:
        raise SpineError("bootstrap interval endpoint is outside int64 range")
    return int(numeric)


def _interval_pair(values: Any) -> tuple[int, int]:
    try:
        lower, upper = values
    except (TypeError, ValueError) as exc:
        raise SpineError("interval endpoints must be one lower-upper pair") from exc
    lower_tick = _exact_interval_tick(lower)
    upper_tick = _exact_interval_tick(upper)
    if lower_tick > upper_tick:
        raise SpineError("bootstrap interval lower endpoint exceeds upper endpoint")
    return lower_tick, upper_tick


def interval_conclusion_reversal(
    block_5_interval: tuple[int, int],
    block_10_interval: tuple[int, int],
) -> bool:
    """Report only an opposite-sign closed-interval conclusion."""
    lower_5, upper_5 = _interval_pair(block_5_interval)
    lower_10, upper_10 = _interval_pair(block_10_interval)
    sign_5 = 1 if lower_5 > 0 else -1 if upper_5 < 0 else 0
    sign_10 = 1 if lower_10 > 0 else -1 if upper_10 < 0 else 0
    return sign_5 != 0 and sign_10 != 0 and sign_5 != sign_10


def _validated_inputs(
    group_ids: Any,
    terms: Any,
    requests: Any,
) -> tuple[
    np.ndarray,
    tuple[BootstrapQuantileTerm, ...],
    tuple[BootstrapIntervalRequest | BootstrapInteractionRequest, ...],
]:
    groups = _one_dimensional(group_ids, "group_ids")
    if groups.size == 0:
        raise SpineError("joint bootstrap requires the complete nonempty aligned frame")
    try:
        term_tuple = tuple(terms)
        request_tuple = tuple(requests)
    except TypeError as exc:
        raise SpineError("bootstrap terms and requests must be finite sequences") from exc
    if not term_tuple or any(not isinstance(term, BootstrapQuantileTerm) for term in term_tuple):
        raise SpineError("at least one BootstrapQuantileTerm is required")
    if not request_tuple or any(
        not isinstance(
            request, (BootstrapIntervalRequest, BootstrapInteractionRequest)
        )
        for request in request_tuple
    ):
        raise SpineError("at least one declared bootstrap request is required")
    if any(term.values.size != groups.size for term in term_tuple):
        raise SpineError("every bootstrap term must align to the complete group frame")
    term_ids = tuple(term.term_id for term in term_tuple)
    request_ids = tuple(request.request_id for request in request_tuple)
    if len(set(term_ids)) != len(term_ids):
        raise SpineError("bootstrap term ids must be unique")
    if len(set(request_ids)) != len(request_ids):
        raise SpineError("bootstrap request ids must be unique")
    term_id_set = set(term_ids)
    for request in request_tuple:
        if isinstance(request, BootstrapIntervalRequest):
            _validated_status(request.status)
            if request.target_term_id not in term_id_set:
                raise SpineError("bootstrap request names an undeclared target term")
            if (
                request.baseline_term_id is not None
                and request.baseline_term_id not in term_id_set
            ):
                raise SpineError("bootstrap request names an undeclared baseline term")
        elif any(term_id not in term_id_set for term_id in request.term_ids):
            raise SpineError("bootstrap interaction names an undeclared term")
    return groups.copy(), term_tuple, request_tuple


def joint_bootstrap_intervals(
    group_ids: Any,
    terms: Any,
    requests: Any,
    *,
    constants_path: Path | None = None,
) -> JointBootstrapResult:
    """Apply one global whole-session plan to every aligned term per replicate."""
    contract = bootstrap_contract(constants_path)
    groups, term_tuple, request_tuple = _validated_inputs(
        group_ids, terms, requests
    )
    unit_weights = np.ones(groups.size, dtype=np.float64)
    root = np.random.SeedSequence(contract.root_entropy)
    children = root.spawn(len(contract.block_lengths))
    intervals_by_request: dict[Hashable, list[BootstrapIntervalRow]] = {
        request.request_id: [] for request in request_tuple
    }
    prepared_by_term = {
        term.term_id: prepare_weighted_quantile_ticks(
            term.values[term.eligibility_mask]
        )
        for term in term_tuple
    }

    for block_length, child in zip(contract.block_lengths, children, strict=True):
        rng = np.random.Generator(np.random.PCG64(child))
        replicates = np.empty(
            (len(request_tuple), contract.draws_per_block_length), dtype=np.int64
        )
        for replicate_index in range(contract.draws_per_block_length):
            try:
                plan = stationary_group_resample(groups, block_length, rng)
                row_multiplicities = apply_group_multiplicities(
                    groups, unit_weights, plan
                )
            except SpineError as exc:
                raise SpineError(
                    f"Phase 8 block length {block_length}, replicate "
                    f"{replicate_index} plan failed: {exc}"
                ) from exc

            term_statistics: dict[Hashable, int] = {}
            for term in term_tuple:
                with np.errstate(over="ignore", invalid="ignore"):
                    composed = np.multiply(
                        term.weights, row_multiplicities, dtype=np.float64
                    )
                if not bool(np.isfinite(composed).all()):
                    raise SpineError(
                        f"Phase 8 block length {block_length}, replicate "
                        f"{replicate_index}, term {term.term_id!r} produced "
                        "non-finite composed weights"
                    )
                mask = term.eligibility_mask
                try:
                    term_statistics[term.term_id] = weighted_quantile_ticks(
                        prepared_by_term[term.term_id],
                        composed[mask],
                        term.statistic,
                    )
                except SpineError as exc:
                    raise SpineError(
                        f"Phase 8 block length {block_length}, replicate "
                        f"{replicate_index}, term {term.term_id!r} failed: {exc}"
                    ) from exc

            for request_index, request in enumerate(request_tuple):
                if isinstance(request, BootstrapInteractionRequest):
                    first, second, third, fourth = (
                        np.int64(term_statistics[term_id])
                        for term_id in request.term_ids
                    )
                    statistic = int(first - second - third + fourth)
                else:
                    target_tick = term_statistics[request.target_term_id]
                    if request.baseline_term_id is None:
                        statistic = target_tick
                    else:
                        statistic = int(
                            np.int64(target_tick)
                            - np.int64(term_statistics[request.baseline_term_id])
                        )
                replicates[request_index, replicate_index] = statistic

        for request_index, request in enumerate(request_tuple):
            try:
                raw_interval = percentile_interval(
                    replicates[request_index], contract.confidence_level
                )
            except SpineError as exc:
                raise SpineError(
                    f"Phase 8 block length {block_length}, request "
                    f"{request.request_id!r} interval failed: {exc}"
                ) from exc
            lower, upper = _interval_pair(raw_interval)
            intervals_by_request[request.request_id].append(
                BootstrapIntervalRow(
                    request_id=request.request_id,
                    mean_block_sessions=block_length,
                    draws=contract.draws_per_block_length,
                    confidence_level=contract.confidence_level,
                    ci_lower_ticks=lower,
                    ci_upper_ticks=upper,
                    interval_valid=True,
                    is_primary=block_length == contract.primary_block_length,
                    rng_root_entropy=contract.root_entropy,
                    rng_child_spawn_key=tuple(child.spawn_key),
                    historical_mixture_disclosure=HISTORICAL_MIXTURE_DISCLOSURE,
                    conditioner_uncertainty_disclosure=CONDITIONER_UNCERTAINTY_DISCLOSURE,
                    weight_ess_disclosure=WEIGHT_ESS_DISCLOSURE,
                )
            )

    results: list[RequestBootstrapResult] = []
    for request in request_tuple:
        rows = tuple(intervals_by_request[request.request_id])
        row_by_block = {row.mean_block_sessions: row for row in rows}
        block_5 = row_by_block[5]
        block_10 = row_by_block[10]
        reversal = interval_conclusion_reversal(
            (block_5.ci_lower_ticks, block_5.ci_upper_ticks),
            (block_10.ci_lower_ticks, block_10.ci_upper_ticks),
        )
        results.append(
            RequestBootstrapResult(request.request_id, rows, reversal)
        )
    return JointBootstrapResult(contract, tuple(results))
