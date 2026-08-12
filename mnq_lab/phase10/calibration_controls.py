"""Deterministic calibration controls and synthetic planted-effect data.

This module does not evaluate surfaces, compute p-values, or run calibration.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any

import numpy as np

from mnq_lab import SpineError
from mnq_lab.phase10.adapter import FormalCorpus
from mnq_lab.phase10.calibration_entropy import calibration_root_seed_sequence
from mnq_lab.phase10.mapping import (
    PermutedTrajectories,
    SessionMapping,
    generate_session_mapping,
)
from mnq_lab.phase8.contrasts import SESSION_PHASES, VOLATILITY_STATES

CALIBRATION_REPLICATIONS = 300
PLANTED_EFFECT_LADDER = (10, 30, 60)
PLANTED_EFFECT_PHASES = ("morning", "midday", "afternoon")

_INT32_INFO = np.iinfo(np.int32)


@dataclass(frozen=True)
class CalibrationReplicationStreams:
    """Fresh streams at the frozen ``(replication, role)`` coordinates."""

    replication_index: int
    control_spawn_key: tuple[int, ...]
    ensemble_spawn_key: tuple[int, ...]
    control_rng: np.random.Generator
    ensemble_root: np.random.SeedSequence


@dataclass(frozen=True)
class InterventionSnapshot:
    """Read-only copies frozen before an intervention is applied."""

    session_ids: np.ndarray
    calendar_quarters: np.ndarray
    calendar_years: np.ndarray
    observation_grid: np.ndarray
    phase_grid: np.ndarray
    ts_event_ns: np.ndarray
    corpus_state_codes: np.ndarray
    corpus_state_valid: np.ndarray
    outcomes: np.ndarray
    outcome_valid: np.ndarray
    window_fits_rth: np.ndarray
    control_state_codes: np.ndarray
    control_state_valid: np.ndarray
    modification_mask: np.ndarray


@dataclass(frozen=True)
class PlantedEffect:
    """One independent planted outcome array and its exact modification mask."""

    outcomes: np.ndarray
    modification_mask: np.ndarray
    magnitude_ticks: int


def _built_in_replication_index(value: Any) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value >= CALIBRATION_REPLICATIONS
    ):
        raise SpineError(
            "calibration replication index must be a built-in integer in [0, 300)"
        )
    return value


def calibration_replication_streams(
    replication_index: int,
) -> CalibrationReplicationStreams:
    """Re-derive fresh streams by index from the unreachable calibration root."""
    index = _built_in_replication_index(replication_index)
    calibration_root = calibration_root_seed_sequence()
    replication_roots = calibration_root.spawn(CALIBRATION_REPLICATIONS)
    control_child, ensemble_root = replication_roots[index].spawn(2)
    control_rng = np.random.Generator(np.random.PCG64(control_child))
    if control_child.spawn_key != (index, 0):
        raise SpineError("calibration control child coordinate differs")
    if ensemble_root.spawn_key != (index, 1):
        raise SpineError("calibration ensemble root coordinate differs")
    if ensemble_root.n_children_spawned != 0:
        raise SpineError("calibration ensemble root must be fresh and unconsumed")
    if not isinstance(control_rng.bit_generator, np.random.PCG64):
        raise SpineError("calibration control mapping requires PCG64")
    return CalibrationReplicationStreams(
        replication_index=index,
        control_spawn_key=control_child.spawn_key,
        ensemble_spawn_key=ensemble_root.spawn_key,
        control_rng=control_rng,
        ensemble_root=ensemble_root,
    )


def generate_calibration_outer_control(
    corpus: FormalCorpus,
    replication_index: int,
) -> SessionMapping:
    """Draw one outer mapping using only the corpus's frozen quarter strata."""
    if not isinstance(corpus, FormalCorpus):
        raise SpineError("calibration outer control requires a FormalCorpus")
    streams = calibration_replication_streams(replication_index)
    return generate_session_mapping(
        corpus.session_ids,
        corpus.calendar_quarters,
        streams.control_rng,
    )


def _readonly_copy(values: Any) -> np.ndarray:
    result = np.array(values, copy=True)
    result.setflags(write=False)
    return result


def _validate_intervention_inputs(
    corpus: FormalCorpus,
    control: PermutedTrajectories,
) -> None:
    if not isinstance(corpus, FormalCorpus):
        raise SpineError("planted effect requires a FormalCorpus")
    if not isinstance(control, PermutedTrajectories):
        raise SpineError("planted effect requires control-assigned trajectories")
    shape = corpus.downward_excursion_ticks.shape
    if len(shape) != 2 or shape != corpus.outcome_valid.shape:
        raise SpineError("corpus outcome arrays differ from the session grid")
    if shape != corpus.window_fits_rth.shape:
        raise SpineError("corpus structural-fit mask differs from the session grid")
    if control.state_codes.shape != shape or control.state_valid.shape != shape:
        raise SpineError("control-assigned state arrays differ from the session grid")
    if control.state_valid.dtype.kind != "b":
        raise SpineError("control-assigned state validity must be boolean")
    if corpus.phase_grid.shape != (shape[1],):
        raise SpineError("corpus phase grid must be one column property")
    if corpus.session_ids.shape != (shape[0],):
        raise SpineError("corpus session ids differ from the session grid")
    if corpus.calendar_years.shape != (shape[0],):
        raise SpineError("corpus calendar years differ from the session grid")
    if corpus.calendar_quarters.shape != (shape[0],):
        raise SpineError("corpus calendar quarters differ from the session grid")
    if not np.array_equal(
        control.mapping.recipient_session_ids,
        corpus.session_ids,
    ):
        raise SpineError("control mapping recipients differ from the corpus sessions")
    if corpus.downward_excursion_ticks.dtype != np.dtype(np.int32):
        raise SpineError("anchor outcomes must retain signed int32 tick storage")
    if corpus.outcome_valid.dtype.kind != "b" or corpus.window_fits_rth.dtype.kind != "b":
        raise SpineError("corpus completion and structural-fit masks must be boolean")
    for field in fields(corpus):
        value = getattr(corpus, field.name)
        if isinstance(value, np.ndarray) and value.flags.writeable:
            raise SpineError(f"frozen corpus array became writeable: {field.name}")
    if bool(
        np.any(
            control.state_valid
            & (
                (control.state_codes < 0)
                | (control.state_codes >= len(VOLATILITY_STATES))
            )
        )
    ):
        raise SpineError("valid control-assigned state code is outside the canonical encoding")
    if any(phase not in SESSION_PHASES for phase in PLANTED_EFFECT_PHASES):
        raise SpineError("planted target phase is outside the canonical phase axis")


def freeze_intervention_inputs(
    corpus: FormalCorpus,
    control: PermutedTrajectories,
) -> InterventionSnapshot:
    """Freeze masks, identifiers, axes, states, and null outcomes before planting."""
    _validate_intervention_inputs(corpus, control)
    high_code = VOLATILITY_STATES.index("high")
    target_columns = np.isin(corpus.phase_grid, PLANTED_EFFECT_PHASES)
    modification_mask = (
        (control.state_codes == high_code)
        & target_columns[np.newaxis, :]
        & corpus.outcome_valid
        & control.state_valid
    )
    return InterventionSnapshot(
        session_ids=_readonly_copy(corpus.session_ids),
        calendar_quarters=_readonly_copy(corpus.calendar_quarters),
        calendar_years=_readonly_copy(corpus.calendar_years),
        observation_grid=_readonly_copy(corpus.observation_grid),
        phase_grid=_readonly_copy(corpus.phase_grid),
        ts_event_ns=_readonly_copy(corpus.ts_event_ns),
        corpus_state_codes=_readonly_copy(corpus.state_codes),
        corpus_state_valid=_readonly_copy(corpus.state_valid),
        outcomes=_readonly_copy(corpus.downward_excursion_ticks),
        outcome_valid=_readonly_copy(corpus.outcome_valid),
        window_fits_rth=_readonly_copy(corpus.window_fits_rth),
        control_state_codes=_readonly_copy(control.state_codes),
        control_state_valid=_readonly_copy(control.state_valid),
        modification_mask=_readonly_copy(modification_mask),
    )


def _array_bytes_equal(left: np.ndarray, right: np.ndarray) -> bool:
    return (
        left.dtype == right.dtype
        and left.shape == right.shape
        and left.tobytes(order="C") == right.tobytes(order="C")
    )


def _assert_source_arrays_unchanged(
    corpus: FormalCorpus,
    control: PermutedTrajectories,
    snapshot: InterventionSnapshot,
) -> None:
    current = (
        corpus.session_ids,
        corpus.calendar_quarters,
        corpus.calendar_years,
        corpus.observation_grid,
        corpus.phase_grid,
        corpus.ts_event_ns,
        corpus.state_codes,
        corpus.state_valid,
        corpus.downward_excursion_ticks,
        corpus.outcome_valid,
        corpus.window_fits_rth,
        control.state_codes,
        control.state_valid,
    )
    frozen = tuple(
        getattr(snapshot, field.name)
        for field in fields(snapshot)
        if field.name != "modification_mask"
    )
    labels = (
        "session ids",
        "calendar quarters",
        "calendar years",
        "observation grid",
        "phases",
        "timestamps",
        "corpus state codes",
        "corpus state validity",
        "control outcomes",
        "outcome validity",
        "structural fit",
        "control-assigned state codes",
        "control-assigned state validity",
    )
    for label, observed, expected in zip(labels, current, frozen, strict=True):
        if not _array_bytes_equal(np.asarray(observed), expected):
            raise SpineError(f"planted effect changed frozen {label}")
    for field in fields(corpus):
        value = getattr(corpus, field.name)
        if isinstance(value, np.ndarray) and value.flags.writeable:
            raise SpineError(f"frozen corpus array became writeable: {field.name}")


def _expected_modification_mask(snapshot: InterventionSnapshot) -> np.ndarray:
    high_code = VOLATILITY_STATES.index("high")
    return (
        (snapshot.control_state_codes == high_code)
        & np.isin(snapshot.phase_grid, PLANTED_EFFECT_PHASES)[np.newaxis, :]
        & snapshot.outcome_valid
        & snapshot.control_state_valid
    )


def _validate_magnitude(magnitude_ticks: Any) -> int:
    if (
        isinstance(magnitude_ticks, bool)
        or not isinstance(magnitude_ticks, int)
        or magnitude_ticks <= 0
    ):
        raise SpineError("planted magnitude must be a positive built-in integer tick count")
    return magnitude_ticks


def _shift_in_int64(
    outcomes: np.ndarray,
    modification_mask: np.ndarray,
    magnitude_ticks: int,
) -> np.ndarray:
    widened = outcomes.astype(np.int64, copy=True)
    widened[modification_mask] += magnitude_ticks
    changed = widened[modification_mask]
    if bool(np.any(changed < 0) or np.any(changed > _INT32_INFO.max)):
        raise SpineError("planted outcome is outside signed int32 storage range")
    return widened


def _assert_target_year_support(snapshot: InterventionSnapshot) -> None:
    represented_years = tuple(dict.fromkeys(snapshot.calendar_years.tolist()))
    for phase in PLANTED_EFFECT_PHASES:
        phase_columns = snapshot.phase_grid == phase
        for year in represented_years:
            selected = (
                snapshot.modification_mask
                & phase_columns[np.newaxis, :]
                & (snapshot.calendar_years == year)[:, np.newaxis]
            )
            if not bool(np.any(selected)):
                raise SpineError(
                    "planted target cell lacks eligible support: "
                    f"phase={phase}, volatility_state=high, calendar_year={year}"
                )


def assert_planted_effect_invariants(
    corpus: FormalCorpus,
    control: PermutedTrajectories,
    snapshot: InterventionSnapshot,
    magnitude_ticks: int,
    planted: PlantedEffect | None,
) -> None:
    """Check the same frozen-input, exact-mask, and exact-shift contract in tests."""
    magnitude = _validate_magnitude(magnitude_ticks)
    _validate_intervention_inputs(corpus, control)
    _assert_source_arrays_unchanged(corpus, control, snapshot)
    expected_mask = _expected_modification_mask(snapshot)
    if not _array_bytes_equal(snapshot.modification_mask, expected_mask):
        raise SpineError("planted modification mask differs from the exact conjunction")
    _assert_target_year_support(snapshot)
    expected_widened = _shift_in_int64(
        snapshot.outcomes,
        snapshot.modification_mask,
        magnitude,
    )
    if planted is None:
        return
    if not isinstance(planted, PlantedEffect):
        raise SpineError("planted effect result has an undeclared type")
    if planted.magnitude_ticks != magnitude:
        raise SpineError("planted effect magnitude metadata differs")
    if not _array_bytes_equal(planted.modification_mask, snapshot.modification_mask):
        raise SpineError("planted result mask differs from the frozen modification mask")
    if planted.outcomes.dtype != np.dtype(np.int32):
        raise SpineError("planted outcomes must return to signed int32 storage")
    if planted.outcomes.shape != snapshot.outcomes.shape:
        raise SpineError("planted outcomes differ from the frozen outcome shape")
    if planted.outcomes.flags.writeable or planted.modification_mask.flags.writeable:
        raise SpineError("planted effect arrays must be read-only")
    unchanged = ~snapshot.modification_mask
    if not _array_bytes_equal(
        planted.outcomes[unchanged],
        snapshot.outcomes[unchanged],
    ):
        raise SpineError("an outcome outside the modification mask changed")
    observed_change = (
        planted.outcomes[snapshot.modification_mask].astype(np.int64)
        - snapshot.outcomes[snapshot.modification_mask].astype(np.int64)
    )
    if not bool(np.all(observed_change == magnitude)):
        raise SpineError("a selected outcome did not change by the declared magnitude")
    expected = expected_widened.astype(np.int32)
    if not _array_bytes_equal(planted.outcomes, expected):
        raise SpineError("planted outcomes differ from the independently rebuilt result")


def plant_effect(
    corpus: FormalCorpus,
    control: PermutedTrajectories,
    magnitude_ticks: int,
) -> PlantedEffect:
    """Build one effect independently from the unchanged null-control outcomes."""
    snapshot = freeze_intervention_inputs(corpus, control)
    assert_planted_effect_invariants(
        corpus,
        control,
        snapshot,
        magnitude_ticks,
        None,
    )
    magnitude = _validate_magnitude(magnitude_ticks)
    widened = _shift_in_int64(
        snapshot.outcomes,
        snapshot.modification_mask,
        magnitude,
    )
    outcomes = widened.astype(np.int32)
    outcomes.setflags(write=False)
    modification_mask = _readonly_copy(snapshot.modification_mask)
    result = PlantedEffect(outcomes, modification_mask, magnitude)
    assert_planted_effect_invariants(
        corpus,
        control,
        snapshot,
        magnitude,
        result,
    )
    return result


def plant_frozen_effect_ladder(
    corpus: FormalCorpus,
    control: PermutedTrajectories,
) -> tuple[PlantedEffect, ...]:
    """Build each frozen magnitude independently; the ladder is not overridable."""
    return tuple(
        plant_effect(corpus, control, magnitude)
        for magnitude in PLANTED_EFFECT_LADDER
    )
