"""Pure Slice 3 rejection, localization, aggregation, and result schemas.

No runner, corpus loading, calibration execution, or evidence writing lives here.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from numbers import Integral, Real
from typing import Any

import numpy as np

from mnq_lab import SpineError
from mnq_lab.phase8.contrasts import SESSION_PHASES, VOLATILITY_STATES
from mnq_lab.phase10.calibration import EFFECT_ORDER, NOMINAL_ALPHA, NULL_REPLICATIONS
from mnq_lab.phase10.calibration_controls import (
    CALIBRATION_REPLICATIONS,
    PLANTED_EFFECT_LADDER,
    PLANTED_EFFECT_PHASES,
)
from mnq_lab.phase10.calibration_entropy import (
    CALIBRATION_ROOT_LABEL,
    CALIBRATION_ROOT_SHA256,
)
from mnq_lab.phase10.contract import PERMUTATION_POPULATION, load_phase10_contract
from mnq_lab.phase10.surface import SurfaceRegion, SurfaceStatistic

QUARTET_MEMBERS = ("null", *EFFECT_ORDER)
REJECTION_RULE_IDENTITY = "plus_one_upper_p_value_at_nominal_alpha"
COMPLETION_STATES = ("complete", "failed")


@dataclass(frozen=True)
class LocalizationResult:
    overlap: float
    co_maximal_regions: tuple[SurfaceRegion, ...]


@dataclass(frozen=True)
class QuartetMemberResult:
    member: str
    effect_magnitude_ticks: int
    p_value: float
    rejected: bool
    observed_statistic: float
    retained_regions: tuple[SurfaceRegion, ...]
    co_maximal_regions: tuple[SurfaceRegion, ...]
    localization_overlap: float | None
    structural_statuses: tuple[str, ...]
    classified_failures: tuple[str, ...]


@dataclass(frozen=True)
class ReplicationScientificPayload:
    replication_index: int
    calibration_root_label: str
    calibration_root_digest: str
    control_spawn_key: tuple[int, ...]
    ensemble_spawn_key: tuple[int, ...]
    completion_state: str
    attempt_lineage: tuple[str, ...]
    permutations: int
    rejection_rule_identity: str
    formal_population_identity: str
    weighting_planes: tuple[str, ...]
    quartet_members: tuple[QuartetMemberResult, ...]
    structural_statuses: tuple[str, ...]
    classified_failures: tuple[str, ...]
    code_identity: str
    package_identity: str
    corpus_identity: str
    environment_identity: str
    worker_configuration_identity: str


@dataclass(frozen=True)
class CalibrationReplicationResult:
    scientific_payload: ReplicationScientificPayload
    scientific_payload_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.scientific_payload, ReplicationScientificPayload):
            raise SpineError("calibration result requires a scientific payload")
        expected = scientific_payload_hash(self.scientific_payload)
        if self.scientific_payload_hash != expected:
            raise SpineError("calibration scientific payload hash differs")


@dataclass(frozen=True)
class OperationalTelemetry:
    """Non-scientific runtime data, structurally outside the hashed payload."""

    elapsed_seconds: float
    cpu_seconds: float
    peak_memory_bytes: int
    host_telemetry: tuple[tuple[str, str], ...]


def rejection_event(p_value: Any) -> bool:
    """Apply the imported frozen nominal alpha with an inclusive comparison."""
    if isinstance(p_value, (bool, np.bool_)) or not isinstance(p_value, Real):
        raise SpineError("calibration p-value must be one finite real value")
    numeric = float(p_value)
    if not np.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
        raise SpineError("calibration p-value must be inside [0,1]")
    return numeric <= NOMINAL_ALPHA


def planted_target_cells() -> frozenset[tuple[int, int]]:
    """Derive the preregistered phase/high target from canonical imported axes."""
    high_column = VOLATILITY_STATES.index("high")
    return frozenset(
        (SESSION_PHASES.index(phase), high_column)
        for phase in PLANTED_EFFECT_PHASES
    )


def _validate_region(region: Any, weighting_plane_count: int) -> SurfaceRegion:
    if not isinstance(region, SurfaceRegion):
        raise SpineError("localization regions must be SurfaceRegion values")
    if (
        isinstance(region.plane_index, bool)
        or not isinstance(region.plane_index, int)
        or not 0 <= region.plane_index < weighting_plane_count
    ):
        raise SpineError("localization region plane index differs")
    if region.sign not in ("positive", "negative"):
        raise SpineError("localization region sign differs")
    if not isinstance(region.cells, tuple) or not region.cells:
        raise SpineError("localization region cells must be one nonempty tuple")
    observed_cells: set[tuple[int, int]] = set()
    for cell in region.cells:
        if (
            not isinstance(cell, tuple)
            or len(cell) != 2
            or any(isinstance(value, bool) or not isinstance(value, int) for value in cell)
        ):
            raise SpineError("localization region cell coordinate differs")
        row, column = cell
        if not 0 <= row < len(SESSION_PHASES) or not 0 <= column < len(VOLATILITY_STATES):
            raise SpineError("localization region cell is outside the frozen lattice")
        if cell in observed_cells:
            raise SpineError("localization region contains a duplicate cell")
        observed_cells.add(cell)
    for value, name in (
        (region.mean_z, "mean z"),
        (region.stability, "stability"),
        (region.statistic, "statistic"),
    ):
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
            raise SpineError(f"localization region {name} must be finite")
        if not np.isfinite(float(value)):
            raise SpineError(f"localization region {name} must be finite")
    if not 0.0 <= float(region.stability) <= 1.0:
        raise SpineError("localization region stability must be inside [0,1]")
    if float(region.statistic) < 0.0:
        raise SpineError("localization region statistic must be nonnegative")
    if (region.sign == "positive" and not float(region.mean_z) > 0.0) or (
        region.sign == "negative" and not float(region.mean_z) < 0.0
    ):
        raise SpineError("localization region mean sign differs")
    return region


def _validate_surface(surface: Any) -> tuple[SurfaceStatistic, int]:
    if not isinstance(surface, SurfaceStatistic):
        raise SpineError("localization requires a SurfaceStatistic")
    if isinstance(surface.value, (bool, np.bool_)) or not isinstance(surface.value, Real):
        raise SpineError("surface statistic value must be finite and nonnegative")
    value = float(surface.value)
    if not np.isfinite(value) or value < 0.0:
        raise SpineError("surface statistic value must be finite and nonnegative")
    if not isinstance(surface.regions, tuple):
        raise SpineError("surface retained regions must be one tuple")
    plane_count = len(load_phase10_contract().weighting_planes)
    for region in surface.regions:
        _validate_region(region, plane_count)
    return surface, plane_count


def exact_co_maximal_regions(
    surface: SurfaceStatistic,
) -> tuple[SurfaceRegion, ...]:
    """Retain every region whose own statistic is exactly the joint value."""
    checked, _ = _validate_surface(surface)
    result = tuple(
        region
        for region in checked.regions
        if region.statistic == checked.value
    )
    if checked.value > 0.0 and not result:
        raise SpineError("positive surface statistic has no exact co-maximal region")
    return result


def localization_overlap(
    surface: SurfaceStatistic,
    rejected: bool,
) -> LocalizationResult:
    """Score all exact co-maximal regions against the planted positive target."""
    if not isinstance(rejected, bool):
        raise SpineError("localization rejection event must be boolean")
    checked, _ = _validate_surface(surface)
    if not rejected:
        return LocalizationResult(0.0, ())
    co_maximal = exact_co_maximal_regions(checked)
    if not co_maximal:
        return LocalizationResult(0.0, ())
    target = planted_target_cells()
    contributions: list[float] = []
    for region in co_maximal:
        if region.sign == "negative":
            contributions.append(0.0)
            continue
        cells = frozenset(region.cells)
        intersection_count = len(cells & target)
        union_count = len(cells | target)
        contributions.append(intersection_count / union_count)
    overlap = sum(contributions) / len(contributions)
    return LocalizationResult(float(overlap), co_maximal)


def mean_localization_overlap(values: Any) -> float:
    """Average exactly 300 supplied replication values, including every zero."""
    try:
        supplied = tuple(values)
    except TypeError as exc:
        raise SpineError("localization values must be a finite sequence") from exc
    if len(supplied) != NULL_REPLICATIONS:
        raise SpineError("localization values must match the declared 300 replications")
    converted: list[float] = []
    for value in supplied:
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
            raise SpineError("localization value must be one finite real inside [0,1]")
        numeric = float(value)
        if not np.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
            raise SpineError("localization value must be one finite real inside [0,1]")
        converted.append(numeric)
    return float(sum(converted) / NULL_REPLICATIONS)


def _nonempty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise SpineError(f"{name} must be one nonempty string")
    return value


def _string_tuple(value: Any, name: str, *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(value, tuple) or (not allow_empty and not value):
        raise SpineError(f"{name} must be one fixed tuple of strings")
    if any(not isinstance(item, str) or not item for item in value):
        raise SpineError(f"{name} must be one fixed tuple of strings")
    return value


def _validate_member(
    member: Any,
    expected_name: str,
    expected_magnitude: int,
    plane_count: int,
) -> QuartetMemberResult:
    if not isinstance(member, QuartetMemberResult):
        raise SpineError("quartet result contains an undeclared member type")
    if member.member != expected_name or member.effect_magnitude_ticks != expected_magnitude:
        raise SpineError("quartet member identity or effect magnitude differs")
    if not isinstance(member.rejected, bool):
        raise SpineError("quartet rejection event must be boolean")
    if rejection_event(member.p_value) is not member.rejected:
        raise SpineError("quartet p-value and rejection event disagree")
    if isinstance(member.observed_statistic, (bool, np.bool_)) or not isinstance(
        member.observed_statistic, Real
    ):
        raise SpineError("quartet observed statistic must be finite and nonnegative")
    observed = float(member.observed_statistic)
    if not np.isfinite(observed) or observed < 0.0:
        raise SpineError("quartet observed statistic must be finite and nonnegative")
    if not isinstance(member.retained_regions, tuple) or not isinstance(
        member.co_maximal_regions, tuple
    ):
        raise SpineError("quartet retained and co-maximal regions must be tuples")
    for region in member.retained_regions:
        _validate_region(region, plane_count)
    expected_co_maximal = exact_co_maximal_regions(
        SurfaceStatistic(observed, member.retained_regions)
    )
    if member.co_maximal_regions != expected_co_maximal:
        raise SpineError("quartet exact co-maximal regions differ from retained regions")
    _string_tuple(member.structural_statuses, "member structural statuses", allow_empty=True)
    _string_tuple(member.classified_failures, "member classified failures", allow_empty=True)
    if expected_name == "null":
        if member.localization_overlap is not None:
            raise SpineError("null member must not carry localization overlap")
    else:
        expected_overlap = localization_overlap(
            SurfaceStatistic(observed, member.retained_regions),
            member.rejected,
        ).overlap
        if isinstance(member.localization_overlap, (bool, np.bool_)) or not isinstance(
            member.localization_overlap, Real
        ):
            raise SpineError("effect member localization overlap must be finite")
        overlap = float(member.localization_overlap)
        if not np.isfinite(overlap) or overlap != expected_overlap:
            raise SpineError("effect member localization overlap differs")
    return member


def validate_scientific_payload(
    payload: Any,
) -> ReplicationScientificPayload:
    """Fail closed on every frozen per-replication schema relationship."""
    if not isinstance(payload, ReplicationScientificPayload):
        raise SpineError("canonical serialization requires a scientific payload")
    if (
        isinstance(payload.replication_index, bool)
        or not isinstance(payload.replication_index, int)
        or not 0 <= payload.replication_index < CALIBRATION_REPLICATIONS
    ):
        raise SpineError("scientific payload replication index differs")
    if payload.calibration_root_label != CALIBRATION_ROOT_LABEL:
        raise SpineError("scientific payload calibration root label differs")
    if payload.calibration_root_digest != CALIBRATION_ROOT_SHA256:
        raise SpineError("scientific payload calibration root digest differs")
    if payload.control_spawn_key != (payload.replication_index, 0):
        raise SpineError("scientific payload control spawn key differs")
    if payload.ensemble_spawn_key != (payload.replication_index, 1):
        raise SpineError("scientific payload ensemble spawn key differs")
    if payload.completion_state not in COMPLETION_STATES:
        raise SpineError("scientific payload completion state differs")
    _string_tuple(payload.attempt_lineage, "attempt lineage", allow_empty=False)
    contract = load_phase10_contract()
    if payload.permutations != contract.permutations_final:
        raise SpineError("scientific payload permutation count differs")
    if payload.rejection_rule_identity != REJECTION_RULE_IDENTITY:
        raise SpineError("scientific payload rejection rule identity differs")
    if payload.formal_population_identity != PERMUTATION_POPULATION:
        raise SpineError("scientific payload formal population identity differs")
    if payload.weighting_planes != contract.weighting_planes:
        raise SpineError("scientific payload weighting-plane inventory differs")
    if not isinstance(payload.quartet_members, tuple) or len(payload.quartet_members) != 4:
        raise SpineError("scientific payload must contain one complete quartet")
    expected_magnitudes = (0, *PLANTED_EFFECT_LADDER)
    for member, name, magnitude in zip(
        payload.quartet_members,
        QUARTET_MEMBERS,
        expected_magnitudes,
        strict=True,
    ):
        _validate_member(member, name, magnitude, len(contract.weighting_planes))
    _string_tuple(payload.structural_statuses, "replication structural statuses", allow_empty=True)
    _string_tuple(payload.classified_failures, "replication classified failures", allow_empty=True)
    for field_name in (
        "code_identity",
        "package_identity",
        "corpus_identity",
        "environment_identity",
        "worker_configuration_identity",
    ):
        _nonempty_string(getattr(payload, field_name), field_name)
    return payload


def _float_text(value: float) -> str:
    return float(value).hex()


def _region_mapping(region: SurfaceRegion) -> dict[str, Any]:
    return {
        "cells": [[row, column] for row, column in region.cells],
        "mean_z_hex": _float_text(region.mean_z),
        "plane_index": region.plane_index,
        "sign": region.sign,
        "stability_hex": _float_text(region.stability),
        "statistic_hex": _float_text(region.statistic),
    }


def _member_mapping(member: QuartetMemberResult) -> dict[str, Any]:
    return {
        "classified_failures": list(member.classified_failures),
        "co_maximal_regions": [_region_mapping(region) for region in member.co_maximal_regions],
        "effect_magnitude_ticks": member.effect_magnitude_ticks,
        "localization_overlap_hex": (
            None
            if member.localization_overlap is None
            else _float_text(member.localization_overlap)
        ),
        "member": member.member,
        "observed_statistic_hex": _float_text(member.observed_statistic),
        "p_value_hex": _float_text(member.p_value),
        "rejected": member.rejected,
        "retained_regions": [_region_mapping(region) for region in member.retained_regions],
        "structural_statuses": list(member.structural_statuses),
    }


def _scientific_mapping(payload: ReplicationScientificPayload) -> dict[str, Any]:
    return {
        "attempt_lineage": list(payload.attempt_lineage),
        "calibration_root_digest": payload.calibration_root_digest,
        "calibration_root_label": payload.calibration_root_label,
        "classified_failures": list(payload.classified_failures),
        "code_identity": payload.code_identity,
        "completion_state": payload.completion_state,
        "control_spawn_key": list(payload.control_spawn_key),
        "corpus_identity": payload.corpus_identity,
        "ensemble_spawn_key": list(payload.ensemble_spawn_key),
        "environment_identity": payload.environment_identity,
        "formal_population_identity": payload.formal_population_identity,
        "package_identity": payload.package_identity,
        "permutations": payload.permutations,
        "quartet_members": [_member_mapping(member) for member in payload.quartet_members],
        "rejection_rule_identity": payload.rejection_rule_identity,
        "replication_index": payload.replication_index,
        "structural_statuses": list(payload.structural_statuses),
        "weighting_planes": list(payload.weighting_planes),
        "worker_configuration_identity": payload.worker_configuration_identity,
    }


def canonical_scientific_payload_bytes(
    payload: ReplicationScientificPayload,
) -> bytes:
    """Serialize only validated scientific state with exact float text."""
    checked = validate_scientific_payload(payload)
    return json.dumps(
        _scientific_mapping(checked),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def scientific_payload_hash(payload: ReplicationScientificPayload) -> str:
    """Hash only the scientific payload; telemetry is an unreachable type here."""
    return hashlib.sha256(canonical_scientific_payload_bytes(payload)).hexdigest()


def seal_scientific_payload(
    payload: ReplicationScientificPayload,
) -> CalibrationReplicationResult:
    """Attach the deterministic scientific hash without operational data."""
    return CalibrationReplicationResult(payload, scientific_payload_hash(payload))
